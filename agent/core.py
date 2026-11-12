"""Streamlit의 동일 프로세스에서 실행되는 거래 지원 에이전트 업무 엔진.

작업/판정/승인을 로컬 SQLite 및 정책 함수에 분리합니다. FastAPI 불필요.
DEMO 상태 변경은 반드시 명시적 승인 + 원본 payload 해시 검증을 거치고,
LIVE 모드에서는 Replit 플랫폼에 GET 요청만 전송합니다.
"""
import hashlib
import re
import uuid
from urllib.parse import parse_qs, unquote, urlsplit

from core import db
from core.config import (
    AGENT_MODE, MARKETPLACE_BASE_URL, MARKETPLACE_AUTH_SCHEME, MARKETPLACE_API_KEY,
    OPENAI_MODEL, RULE_VERSION, MAX_MODEL_CALLS_PER_JOB, MAX_COST_KRW_PER_JOB,
    openai_chat_status, marketplace_config_error, writes_enabled,
)
from core.inspector import inspect_zip, UnsafeArchive, MAX_ARCHIVE_BYTES
from core.marketplace_client import MarketplaceError
from core.policy import (
    expiration_iso, metadata_findings, offer_payload, payload_sha, recommendation, verify_amount,
)
from services.marketplace import client_for_actor
from services.demo_marketplace import DemoMarketplaceError


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
        elif AGENT_MODE == 'mock':
            status = '로컬 DEMO (서버 불필요)'
        else:
            try:
                client_for_actor(self.actor_name).me()
                status = 'Replit 연결됨 (읽기 전용)'
            except (MarketplaceError, DemoMarketplaceError):
                status = '인증 또는 연결 확인 필요'
        return {'status': 'ok', 'api_version': '0.3.0', 'marketplace': status,
                'agent_mode': AGENT_MODE, 'rule_version': RULE_VERSION,
                'max_model_calls_per_job': MAX_MODEL_CALLS_PER_JOB,
                'max_cost_krw_per_job': MAX_COST_KRW_PER_JOB,
                'platform_auth_scheme': MARKETPLACE_AUTH_SCHEME,
                'platform_configured': AGENT_MODE == 'live' and err is None,
                'writes_enabled': writes_enabled(), 'openai_chat': openai_chat_status(),
                'openai_model': OPENAI_MODEL}

    def authenticated(self):
        config_error = marketplace_config_error()
        if config_error:
            error(503, 'MARKETPLACE_CONFIG', config_error)
        client = client_for_actor(self.actor_name)
        actor = client.me()
        return client, actor

    def process_job(self, job_id, client, task, listing_id, request):
        # Synchronous: Streamlit only invokes once when a real form is submitted.
        try:
            db.set_status(job_id, 'RUNNING')
            db.add_step(job_id, 'AUTH', 'PASS', '플랫폼 사용자 조회 및 권한 확인')
            if task == 'RECOMMEND':
                items = []
                cursor = None
                for _ in range(10):
                    params = {'limit': 100}
                    if cursor:
                        params['cursor'] = cursor
                    part = client.listings(**params)
                    items.extend(part['items'])
                    cursor = part.get('next_cursor')
                    if not cursor:
                        break
                if cursor:
                    raise ValueError('매물 API 조회 페이지 제한에 도달했습니다.')
                db.add_step(job_id, 'LISTINGS', 'PASS', '매물 {}개 조회'.format(len(items)))
                result = recommendation(items, request['preferences'], demo_only=(AGENT_MODE == 'mock'))
                result['is_demo'] = AGENT_MODE == 'mock'
                db.add_step(job_id, 'RANK', 'PASS', '하드 필터/정적 규칙 기반 정렬')
                db.set_status(job_id, 'SUCCEEDED', result)
            else:
                listing = client.listing(listing_id)
                result = metadata_findings(listing)
                result['listing_id'] = listing_id
                result['is_demo'] = AGENT_MODE == 'mock'
                db.add_step(job_id, 'INSPECT', 'NOT_TESTED', '소스 실행·법률 확인은 별도 절차 필요')
                db.set_status(job_id, 'PARTIAL', result)
        except (MarketplaceError, DemoMarketplaceError, ValueError, KeyError, TypeError) as exc:
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
                'is_demo': AGENT_MODE == 'mock'}

    def inspect_upload(self, client, actor, lid, raw, key):
        require_write()
        demand_key(key)
        if not isinstance(raw, bytes) or len(raw) > MAX_ARCHIVE_BYTES:
            error(413, 'ARCHIVE_TOO_LARGE', '4MB 이하 ZIP만 업로드할 수 있습니다.')
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

    def publish_inspection(self, client, actor, jid, key):
        require_write()
        demand_key(key)
        job = db.get_job(jid, actor['id'])
        if not job or job['task_type'] != 'INSPECT_ZIP' or job['status'] != 'PARTIAL':
            error(422, 'INSPECTION_NOT_READY', '정적 ZIP 검사 결과가 없습니다.')
        listing = client.listing(job['listing_id'])
        if listing['seller_id'] != actor['id']:
            error(403, 'FORBIDDEN', '판매자만 결과를 제출할 수 있습니다.')
        result = job['result']
        payload = {'report_type': 'STATIC', 'verdict': result['verdict'],
                   'findings': result['findings'], 'evidence_refs': result['evidence_refs'],
                   'source_version_sha256': result['source_version_sha256'], 'agent_job_id': jid}
        return client.publish_report(job['listing_id'], payload, key)

    def draft_offer(self, client, actor, payload, key):
        require_write()
        demand_key(key)
        listing = client.listing(payload.get('listing_id', ''))
        if listing['seller_id'] == actor['id']:
            error(403, 'FORBIDDEN', '본인 매물에 제안할 수 없습니다.')
        try:
            content = offer_payload(listing, payload.get('offered_price_krw'),
                                    payload.get('message',''), payload.get('repair_requests', []))
        except (ValueError, TypeError) as exc:
            error(422, 'INVALID_OFFER', str(exc))
        return client.create_action({'action_type': 'SUBMIT_OFFER', 'resource_id': listing['id'],
                                    'proposed_payload': content, 'payload_sha256': payload_sha(content),
                                    'expires_at': expiration_iso()}, key)

    def counter_offer(self, client, actor, payload, key):
        require_write()
        demand_key(key)
        offer_id = payload.get('offer_id','')
        offer = client.offer(offer_id)
        if actor['id'] != offer['seller_id'] or offer['status'] != 'PENDING':
            error(403, 'FORBIDDEN', '유효한 제안에 대해 판매자만 역제안 가능')
        try:
            verify_amount(payload.get('offered_price_krw'))
        except ValueError as exc:
            error(422, 'INVALID_PRICE', str(exc))
        terms = {'handover_deadline_days': 7, 'seller_support_days': 1,
                 'repair_requests': [], 'acceptance_criteria': ['구매자 별도 검수'],
                 'message': str(payload.get('message','DEMO 역제안'))[:4000]}
        content = {'offered_price_krw': payload['offered_price_krw'],
                   'terms': terms, 'expires_at': expiration_iso(), 'expected_version': offer['version']}
        return client.create_action({'action_type': 'COUNTER_OFFER', 'resource_id': offer_id,
                                    'proposed_payload': content, 'payload_sha256': payload_sha(content),
                                    'expires_at': expiration_iso()}, key)

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
                'is_demo': AGENT_MODE == 'mock'}

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
                return client.listings(q=query.get('q',[''])[0], limit=100)
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
                if len(tail) == 3 and tail[2] == 'publish' and method == 'POST':
                    return self.publish_inspection(client, actor, jid, key)
            if tail == ['inspections','zip'] and method == 'POST':
                lid = query.get('listing_id',[''])[0]
                return self.inspect_upload(client, actor, lid, body, key)
            if tail == ['negotiations','draft'] and method == 'POST':
                return self.draft_offer(client, actor, payload or {}, key)
            if tail == ['negotiations','counter-draft'] and method == 'POST':
                return self.counter_offer(client, actor, payload or {}, key)
            if len(tail) == 3 and tail[:2] == ['negotiations','actions'] and method == 'GET':
                return client.action(tail[2])
            if len(tail) == 4 and tail[:2] == ['negotiations','actions'] and method == 'POST':
                require_write()
                demand_key(key)
                action_id, operation = tail[2], tail[3]
                if operation == 'approve':
                    return client.action_approve(action_id, key)
                if operation == 'reject':
                    return client.action_reject(action_id, key)
                if operation == 'execute':
                    return client.action_execute(action_id, key)
                error(404, 'INVALID_OPERATION', '초안 동작 불가')
            if tail == ['offers'] and method == 'GET':
                return client.offers(query.get('listing_id',[''])[0])
            if len(tail) == 3 and tail[0] == 'offers' and tail[2] == 'accept' and method == 'POST':
                require_write()
                demand_key(key)
                if not isinstance(payload, dict) or not isinstance(payload.get('expected_version'), int):
                    error(422, 'VERSION_REQUIRED', 'expected_version 필수')
                return client.accept_offer(tail[1], payload['expected_version'], key)
            if len(tail) == 3 and tail[0] == 'transactions' and tail[2] == 'handover-checks':
                if method == 'GET':
                    return client.handover_checks(tail[1])
                if method == 'POST':
                    require_write()
                    demand_key(key)
                    if not isinstance(payload, dict) or payload.get('result') not in ('NOT_TESTED','NEEDS_FIX','SELLER_SUBMITTED'):
                        error(422, 'INVALID_CHECK', '확인되지 않은 인수 완료 상태는 기록할 수 없습니다.')
                    return client.create_handover_check(tail[1], payload, key)
            error(404, 'NOT_FOUND', '지원하지 않는 내부 작업')
        except DemoMarketplaceError as exc:
            raise AgentError(exc.status, exc.code, str(exc)) from None
        except MarketplaceError as exc:
            raise AgentError(exc.status, exc.code, str(exc)) from None
