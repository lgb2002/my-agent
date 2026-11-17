"""Streamlit의 동일 프로세스에서 실행되는 거래 지원 에이전트 업무 엔진.

작업/판정/승인을 로컬 SQLite 및 정책 함수에 분리합니다. FastAPI 불필요.
매물은 ProjectAgain HTTPS API에서만 조회합니다. 모든 거래 승인·실행은 플랫폼에서 처리합니다.
"""
import hashlib
import re
import uuid
from urllib.parse import parse_qs, unquote, urlsplit

from core import db
from core.config import (
    MARKETPLACE_BASE_URL, MARKETPLACE_AUTH_SCHEME,
    OPENAI_MODEL, RULE_VERSION, MAX_MODEL_CALLS_PER_JOB, MAX_COST_KRW_PER_JOB,
    openai_chat_status, marketplace_config_error, writes_enabled,
)
from core.inspector import inspect_zip, UnsafeArchive, MAX_ARCHIVE_BYTES
from core.marketplace_client import MarketplaceError
from core.request_context import delegated_token, visitor_id
from core.policy import (
    metadata_findings, recommendation,
)
from services.marketplace import client_for_actor


class AgentError(Exception):
    def __init__(self, status, code, message):
        self.status = status
        self.code = code
        super().__init__(message)


def error(status, code, message):
    raise AgentError(status, code, message)


def require_write():
    if not writes_enabled():
        error(403, 'WRITE_DISABLED', '실제 플랫폼 수정·제안 전송은 인증·권한 계약 검증 전까지 차단합니다.')


def demand_key(key):
    if not isinstance(key, str) or not key or len(key) > 128:
        error(422, 'IDEMPOTENCY_REQUIRED', '변경 요청에는 중복 방지 키가 필요합니다.')


def validate_preferences(prefs):
    if not isinstance(prefs, dict) or any(x not in prefs for x in ('max_budget_krw', 'skill_level', 'risk_tolerance', 'objectives')):
        error(422, 'PREFERENCES_REQUIRED', '예산·기술 수준·위험 허용·목적을 모두 입력해 주세요.')
    if prefs['skill_level'] not in ('NONE','BASIC','INTERMEDIATE','ADVANCED') or prefs['risk_tolerance'] not in ('LOW','MEDIUM','HIGH'):
        error(422, 'INVALID_PREFERENCES', '기술 수준 또는 위험 허용도가 올바르지 않습니다.')
    try:
        if int(prefs['max_budget_krw']) < 0 or int(prefs.get('min_budget_krw', 0)) < 0:
            raise ValueError()
        monthly = prefs.get('max_monthly_cost_krw')
        if monthly is not None and int(monthly) < 0:
            raise ValueError()
    except (ValueError, TypeError):
        error(422, 'INVALID_BUDGET', '예산·운영비는 0 이상의 정수여야 합니다.')
    if not isinstance(prefs['objectives'], list) or not isinstance(prefs.get('preferred_tech_stack', []), list):
        error(422, 'INVALID_PREFERENCES', '목적과 기술은 배열이어야 합니다.')


class AgentRuntime:
    """A stateless facade; safe to reconstruct on every Streamlit rerun."""
    def __init__(self, actor_name='구매자 B'):
        db.init_db()
        self.actor_name = actor_name

    def health(self):
        err = marketplace_config_error()
        if err:
            status = '설정 필요'
        else:
            status = '사용자별 조회 전용' if delegated_token() else '공개 매물 조회 전용'
        return {'status': 'ok', 'api_version': '0.3.0', 'marketplace': status,
                'agent_mode': 'live', 'rule_version': RULE_VERSION,
                'max_model_calls_per_job': MAX_MODEL_CALLS_PER_JOB,
                'max_cost_krw_per_job': MAX_COST_KRW_PER_JOB,
                'platform_auth_scheme': MARKETPLACE_AUTH_SCHEME,
                'platform_configured': err is None,
                'writes_enabled': writes_enabled(), 'openai_chat': openai_chat_status(),
                'openai_model': OPENAI_MODEL}

    def authenticated(self):
        config_error = marketplace_config_error()
        if config_error:
            error(503, 'MARKETPLACE_CONFIG', config_error)
        client = client_for_actor(self.actor_name)
        if not delegated_token():
            # Anonymous access is limited to public listings; isolate local job history
            # using a random visitor identifier kept only in Streamlit session state.
            return client, {'id': 'visitor:' + (visitor_id() or str(uuid.uuid4())),
                            'role': 'PUBLIC', 'scopes': []}
        actor = client.me()
        if not isinstance(actor, dict) or not actor.get('id'):
            error(502, 'INVALID_PRINCIPAL', '플랫폼 사용자 응답을 확인할 수 없습니다.')
        return client, actor

    def process_job(self, job_id, client, task, listing_id, request):
        # Synchronous: Streamlit only invokes once when a real form is submitted.
        try:
            db.set_status(job_id, 'RUNNING')
            db.add_step(job_id, 'AUTH', 'PASS', '플랫폼 사용자 조회 및 권한 확인')
            if task == 'RECOMMEND':
                items = []
                cursor = 0
                seen_cursors = set()
                for _ in range(10):
                    if cursor in seen_cursors:
                        raise ValueError('플랫폼 페이지 커서가 반복되었습니다.')
                    seen_cursors.add(cursor)
                    part = client.listings(limit=100, cursor=cursor)
                    if not isinstance(part, dict) or not isinstance(part.get('items'), list):
                        raise ValueError('플랫폼 매물 목록 응답 형식 불일치')
                    items.extend(part['items'])
                    nxt = part.get('next_cursor')
                    if nxt is None or nxt == '':
                        break
                    if not str(nxt).isdigit():
                        raise ValueError('플랫폼 커서가 정수 오프셋이 아닙니다.')
                    cursor = int(nxt)
                else:
                    raise ValueError('추천 조회가 10페이지 제한에 도달했습니다. 검색 조건을 좁혀 주세요.')
                db.add_step(job_id, 'LISTINGS', 'PASS', '매물 {}개 조회'.format(len(items)))
                result = recommendation(items, request['preferences'])
                result['is_demo'] = False
                db.add_step(job_id, 'RANK', 'PASS', '하드 필터/정적 규칙 기반 정렬')
                db.set_status(job_id, 'SUCCEEDED', result)
            else:
                listing = client.listing(listing_id)
                result = metadata_findings(listing)
                result['listing_id'] = listing_id
                result['is_demo'] = bool(listing.get('is_demo', False))
                db.add_step(job_id, 'INSPECT', 'NOT_TESTED', '소스 실행·법률 확인은 별도 절차 필요')
                db.set_status(job_id, 'PARTIAL', result)
        except (MarketplaceError, ValueError, KeyError, TypeError) as exc:
            db.add_step(job_id, 'ERROR', 'FAIL', type(exc).__name__ + ': 처리 실패')
            db.set_status(job_id, 'FAILED', error='업무 처리 실패: ' + type(exc).__name__)

    def create_job(self, client, actor, payload, key):
        demand_key(key)
        if not isinstance(payload, dict):
            error(422, 'INVALID_REQUEST', '작업 요청 형식 오류')
        task = payload.get('task_type')
        if task not in ('RECOMMEND','INSPECT_METADATA'):
            error(422, 'INVALID_TASK', '미지원 작업')
        lid = payload.get('listing_id')
        if task == 'RECOMMEND':
            validate_preferences(payload.get('preferences'))
        if task == 'INSPECT_METADATA' and not lid:
            error(422, 'LISTING_REQUIRED', 'listing_id 누락')
        try:
            jid, created = db.new_job(str(uuid.uuid4()), actor['id'], key, task, lid, payload)
        except ValueError as exc:
            error(409, 'IDEMPOTENCY_CONFLICT', str(exc))
        if created:
            db.add_step(jid, 'QUEUE', 'QUEUED', 'Streamlit 동기 실행 · LLM 호출 0회')
            self.process_job(jid, client, task, lid, payload)
        job = db.get_job(jid, actor['id'])
        return {'job_id': jid, 'status': job['status'], 'created': created,
                'is_demo': False}

    def inspect_upload(self, client, actor, lid, raw, key):
        # Local static scan: no remote upload, no marketplace mutation.
        demand_key(key)
        if not isinstance(raw, bytes) or len(raw) > MAX_ARCHIVE_BYTES:
            error(413, 'ARCHIVE_TOO_LARGE', '4MB 이하 ZIP만 업로드할 수 있습니다.')
        if not delegated_token() or actor.get('role') == 'PUBLIC':
            error(401, 'AUTH_REQUIRED', '판매자 본인 인증 후 ZIP을 검사할 수 있습니다.')
        listing = client.listing(lid)
        if listing['seller_id'] != actor['id']:
            error(403, 'FORBIDDEN', '판매자 본인 매물만 검사할 수 있습니다.')
        request = {'task_type': 'INSPECT_ZIP', 'listing_id': lid,
                   'sha256': hashlib.sha256(raw).hexdigest()}
        try:
            jid, created = db.new_job(str(uuid.uuid4()), actor['id'], key, 'INSPECT_ZIP', lid, request)
        except ValueError as exc:
            error(409, 'IDEMPOTENCY_CONFLICT', str(exc))
        if not created:
            return {'job_id': jid, 'created': False}
        db.set_status(jid, 'RUNNING')
        db.add_step(jid, 'ZIP', 'RUNNING', '아카이브 내용 정적 검사 · 실행 및 압축해제 없음')
        try:
            report = inspect_zip(raw)
            report['listing_id'], report['agent_job_id'] = lid, jid
            db.add_step(jid, 'ZIP', 'PASS', '정적 스캔 {}개 파일'.format(report['files_scanned']))
            db.set_status(jid, 'PARTIAL', report)
        except UnsafeArchive as exc:
            db.add_step(jid, 'ZIP', 'FAIL', '위험한 ZIP 정책상 거부')
            db.set_status(jid, 'FAILED', error='위험한 ZIP이므로 차단: ' + str(exc))
        return {'job_id': jid, 'created': True}

    def assistant_chat(self, payload):
        if openai_chat_status() != 'ready':
            error(409, 'OPENAI_DISABLED', 'OpenAI가 비활성화되어 있거나 API 키가 없습니다.')
        message = payload.get('message', '')
        history = payload.get('history', [])
        if not isinstance(message, str) or not message.strip() or len(message) > 2000:
            error(422, 'INVALID_MESSAGE', '메시지는 1~2000자여야 합니다.')
        if not isinstance(history, list) or len(history) > 6:
            error(422, 'INVALID_HISTORY', '최대 6개 메시지만 이력으로 보낼 수 있습니다.')
        from core.llm_service import contains_obvious_secret, answer_user
        checked = []
        if contains_obvious_secret(message):
            error(422, 'SECRET_INPUT', 'API 키로 추정되는 내용은 외부 모델로 전송하지 않습니다.')
        for item in history:
            if not isinstance(item, dict) or item.get('role') not in ('user','assistant') or not isinstance(item.get('content'), str) or len(item['content']) > 2000 or contains_obvious_secret(item['content']):
                error(422, 'INVALID_HISTORY', '대화 기록에 불가능한 항목이 있습니다.')
            checked.append(item)
        try:
            result = answer_user(message.strip(), checked)
        except Exception:
            error(502, 'OPENAI_FAILED', 'OpenAI 호출 실패. 키·모델·연결 또는 사용량을 확인하세요.')
        return {'answer': result, 'model': OPENAI_MODEL, 'read_only': True,
                'is_demo': False}

    def request(self, method, path, payload=None, body=None, write=False, key=None):
        """Dispatcher retains v0.2 UI route names, without any HTTP or server."""
        try:
            if path == '/health' and method == 'GET':
                return self.health()
            client, actor = self.authenticated()
            parsed = urlsplit(path)
            p = unquote(parsed.path)
            query = parse_qs(parsed.query)
            part = p.strip('/').split('/')
            if part[:3] != ['api','agent','v1']:
                error(404, 'NOT_FOUND', '지원하지 않는 내부 작업')
            tail = part[3:]
            if tail == ['me'] and method == 'GET':
                return actor
            if tail == ['listings'] and method == 'GET':
                requested_limit = query.get('limit', ['100'])[0]
                requested_cursor = query.get('cursor', ['0'])[0]
                try:
                    limit = int(requested_limit)
                    cursor = int(requested_cursor)
                except (TypeError, ValueError):
                    error(422, 'INVALID_PAGINATION', 'limit/cursor는 정수여야 합니다.')
                if limit < 1 or limit > 100 or cursor < 0:
                    error(422, 'INVALID_PAGINATION', 'limit 1~100, cursor 0 이상만 지원합니다.')
                return client.listings(q=query.get('q', [''])[0], limit=limit, cursor=cursor)
            if len(tail) == 2 and tail[0] == 'listings' and method == 'GET':
                return client.listing(tail[1])
            if len(tail) == 3 and tail[0] == 'listings' and tail[2] == 'reports' and method == 'GET':
                return client.reports(tail[1])
            if tail == ['assistant','chat'] and method == 'POST':
                return self.assistant_chat(payload or {})
            if tail == ['jobs'] and method == 'GET':
                return {'items': db.list_jobs(actor['id'])}
            if tail == ['jobs'] and method == 'POST':
                return self.create_job(client, actor, payload, key)
            if len(tail) >= 2 and tail[0] == 'jobs':
                jid = tail[1]
                if len(tail) == 2 and method == 'GET':
                    job = db.get_job(jid, actor['id'])
                    if not job:
                        error(404, 'NOT_FOUND', '본인 작업만 조회 가능')
                    return job
                if len(tail) == 3 and tail[2] == 'cancel' and method == 'POST':
                    demand_key(key)
                    job = db.get_job(jid, actor['id'])
                    if not job:
                        error(404, 'NOT_FOUND', '존재하지 않는 작업')
                    if job['status'] != 'QUEUED':
                        error(409, 'ALREADY_STARTED', '동기 작업은 대기 상태에서만 취소 가능')
                    db.set_status(jid, 'CANCELLED')
                    db.add_step(jid, 'CANCEL', 'CANCELLED', '사용자 취소')
                    return {'job_id': jid, 'status': 'CANCELLED'}
            if tail == ['inspections','zip'] and method == 'POST':
                lid = query.get('listing_id',[''])[0]
                return self.inspect_upload(client, actor, lid, body, key)
            if tail == ['offers'] and method == 'GET':
                return client.offers(query.get('listing_id',[''])[0])
            if len(tail) == 3 and tail[0] == 'transactions' and tail[2] == 'handover-checks':
                if method == 'GET':
                    return client.handover_checks(tail[1])
            error(404, 'NOT_FOUND', '지원하지 않는 내부 작업')
        except MarketplaceError as exc:
            raise AgentError(exc.status, exc.code, str(exc)) from None
