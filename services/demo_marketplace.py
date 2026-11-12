"""순수 Python DEMO 플랫폼: FastAPI/HTTP 서버 없이 로컬 SQLite에서 실행.

샌드박스 계정·매물은 전부 허구이며 공개 서비스로 배포하면 안 됩니다.
원본 v0.2 Mock의 유효성 검사·권한 확인·상태 변경 규칙을 유지합니다.
"""
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from core.config import MOCK_DB, FIXTURE_PATH, DEMO_BUYER_TOKEN, DEMO_SELLER_TOKEN
from core.policy import canonical_json, payload_sha, verify_amount

class DemoMarketplaceError(Exception):
    def __init__(self, status, code, message):
        self.status, self.code = status, code
        super().__init__(message)

def db():
    conn = sqlite3.connect(MOCK_DB, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA busy_timeout=15000')
    return conn

def iso_now():
    return datetime.now(timezone.utc).isoformat()

def bad(status, code, message):
    raise DemoMarketplaceError(status, code, message)

def require_actor(authorization):
    token = ((authorization or '')[7:] if (authorization or '').startswith('Bearer ') else '').strip()
    fixture = json.loads(Path(FIXTURE_PATH).read_text(encoding='utf-8'))
    if token == DEMO_BUYER_TOKEN:
        return fixture['buyer']
    if token == DEMO_SELLER_TOKEN:
        return fixture['seller']
    bad(401, 'UNAUTHORIZED', 'DEMO 인증 토큰이 유효하지 않습니다.')


def init_db():
    with db() as con:
        con.execute('CREATE TABLE IF NOT EXISTS listings (id TEXT PRIMARY KEY,seller_id TEXT NOT NULL, payload TEXT NOT NULL)')
        con.execute('CREATE TABLE IF NOT EXISTS reports (id TEXT PRIMARY KEY,listing_id TEXT, payload TEXT NOT NULL)')
        con.execute('''CREATE TABLE IF NOT EXISTS actions (id TEXT PRIMARY KEY, user_id TEXT,
            action_type TEXT, resource_id TEXT, proposed_payload TEXT, payload_sha256 TEXT,
            status TEXT, expires_at TEXT, created_at TEXT)''')
        con.execute('''CREATE TABLE IF NOT EXISTS offers (id TEXT PRIMARY KEY, listing_id TEXT,
            buyer_id TEXT,seller_id TEXT, proposed_by TEXT, parent_offer_id TEXT,
            offered_price_krw INTEGER, terms TEXT, status TEXT, version INTEGER,
            is_demo INTEGER, created_at TEXT, expires_at TEXT)''')
        con.execute('''CREATE TABLE IF NOT EXISTS transactions (id TEXT PRIMARY KEY,
            listing_id TEXT, accepted_offer_id TEXT, buyer_id TEXT, seller_id TEXT,
            status TEXT, version INTEGER, created_at TEXT)''')
        con.execute('''CREATE TABLE IF NOT EXISTS handover_checks (id TEXT PRIMARY KEY,
            transaction_id TEXT,check_key TEXT, description TEXT, seller_submitted INTEGER,
            agent_checked INTEGER, buyer_confirmed INTEGER,result TEXT,evidence_refs TEXT,remarks TEXT,updated_at TEXT)''')
        con.execute('''CREATE TABLE IF NOT EXISTS idempotencies (actor TEXT,key TEXT,digest TEXT,
            response_json TEXT,status_code INTEGER,PRIMARY KEY(actor,key))''')
        seeded = con.execute('SELECT COUNT(*) FROM listings').fetchone()[0]
        if seeded == 0:
            fixture = json.loads(Path(FIXTURE_PATH).read_text(encoding='utf-8'))
            for item in fixture['listings']:
                con.execute('INSERT INTO listings(id,seller_id,payload) VALUES(?,?,?)',
                            (item['id'], item['seller_id'], json.dumps(item, ensure_ascii=False)))


init_db()


def validated_write(actor, idempotency_key, signature, operation):
    if not idempotency_key or len(idempotency_key) > 128:
        bad(422, 'IDEMPOTENCY_REQUIRED', 'Idempotency-Key를 입력하세요.')
    with db() as con:
        con.execute('BEGIN IMMEDIATE')
        row = con.execute('SELECT digest,response_json,status_code FROM idempotencies WHERE actor=? AND key=?',
                          (actor['id'], idempotency_key)).fetchone()
        if row:
            if row['digest'] != signature:
                bad(409, 'IDEMPOTENCY_CONFLICT', '동일한 키로 다른 요청을 보낼 수 없습니다.')
            return json.loads(row['response_json'])
        result, status = operation(con)
        con.execute('INSERT INTO idempotencies(actor,key,digest,response_json,status_code) VALUES(?,?,?,?,?)',
                    (actor['id'], idempotency_key, signature, json.dumps(result, ensure_ascii=False), status))
        return result


def get_listing(con, listing_id):
    row = con.execute('SELECT payload FROM listings WHERE id=?', (listing_id,)).fetchone()
    if not row:
        bad(404, 'NOT_FOUND', '매물이 없거나 접근할 수 없습니다.')
    item = json.loads(row['payload'])
    if not item.get('is_demo'):
        bad(404, 'NOT_FOUND', '비데모 매물은 이 서버에서 이용할 수 없습니다.')
    return item


def require_listing_owner(con, actor, listing_id):
    item = get_listing(con, listing_id)
    if item['seller_id'] != actor['id']:
        bad(403, 'FORBIDDEN', '이 매물 자료의 소유자가 아닙니다.')
    return item


def offer_dict(row):
    out = dict(row)
    out['terms'] = json.loads(out['terms'])
    out['is_demo'] = bool(out['is_demo'])
    return out


def action_dict(row):
    out = dict(row)
    out['proposed_payload'] = json.loads(out['proposed_payload'])
    return out


def get_offer(con, offer_id):
    row = con.execute('SELECT * FROM offers WHERE id=?', (offer_id,)).fetchone()
    if not row:
        bad(404, 'NOT_FOUND', '제안이 존재하지 않습니다.')
    return offer_dict(row)


def require_offer_party(offer, actor):
    if actor['id'] not in (offer['buyer_id'], offer['seller_id']):
        bad(403, 'FORBIDDEN', '제안 당사자만 볼 수 있습니다.')


def get_transaction(con, tx_id, actor):
    row = con.execute('SELECT * FROM transactions WHERE id=?', (tx_id,)).fetchone()
    if not row:
        bad(404, 'NOT_FOUND', '거래를 찾을 수 없습니다.')
    tx = dict(row)
    if actor['id'] not in (tx['buyer_id'], tx['seller_id']):
        bad(403, 'FORBIDDEN', '거래 당사자에게만 허용됩니다.')
    tx['is_demo'] = True
    return tx


def health():
    return {'status': 'ok', 'api_version': '1.0.0', 'is_demo': True}


def auth_me(authorization: str = ''):
    return require_actor(authorization)


def listings(q: str = '', category: str = '', lifecycle_status: str = '',
             min_price_krw: int = 0, max_price_krw: int = 0, limit: int = 20,
             cursor: str = '', authorization: str = ''):
    require_actor(authorization)
    if not 1 <= limit <= 100:
        bad(422, 'VALIDATION_ERROR', 'limit는 1~100입니다.')
    with db() as con:
        records = [json.loads(row['payload']) for row in con.execute('SELECT payload FROM listings ORDER BY id')]
    records = [v for v in records if v['status'] == 'ACTIVE' and v['is_demo'] and
               (not q or q.lower() in (v['title'] + ' ' + v.get('description', '')).lower()) and
               (not category or v['category'] == category) and
               (not lifecycle_status or v['lifecycle_status'] == lifecycle_status) and
               v['price_krw'] >= min_price_krw and (not max_price_krw or v['price_krw'] <= max_price_krw)]
    try:
        start = int(cursor or '0')
    except ValueError:
        bad(422, 'INVALID_CURSOR', 'cursor가 잘못되었습니다.')
    if start < 0:
        bad(422, 'INVALID_CURSOR', 'cursor가 잘못되었습니다.')
    subset = records[start:start + limit]
    return {'items': subset, 'next_cursor': str(start + limit) if start + limit < len(records) else None,
            'total_estimate': len(records)}


def listing_detail(listing_id: str, authorization: str = ''):
    require_actor(authorization)
    with db() as con:
        listing = get_listing(con, listing_id)
    if listing['status'] not in ('ACTIVE', 'RESERVED'):
        bad(404, 'NOT_FOUND', '공개되지 않은 매물입니다.')
    return listing


def inspection_reports(listing_id: str, authorization: str = ''):
    require_actor(authorization)
    with db() as con:
        get_listing(con, listing_id)
        rows = con.execute('SELECT payload FROM reports WHERE listing_id=?', (listing_id,)).fetchall()
        return {'items': [json.loads(r['payload']) for r in rows], 'next_cursor': None}


def post_inspection_report(listing_id: str, payload: dict, authorization: str = '',
                           idempotency_key: str = ''):
    actor = require_actor(authorization)
    if payload.get('report_type') not in ('STATIC', 'EXECUTION', 'HANDOVER', 'LEGAL_CHECKLIST') or payload.get('verdict') not in ('NOT_TESTED','UNVERIFIED','PASS','PARTIAL','FAIL') or not isinstance(payload.get('findings'), list) or not payload.get('agent_job_id'):
        bad(422, 'INVALID_REPORT', '실사 보고서 필수 필드가 없습니다.')

    def operation(con):
        require_listing_owner(con, actor, listing_id)
        rid = str(uuid.uuid4())
        result = dict(payload)
        result.update({'id': rid, 'listing_id': listing_id, 'reviewer_kind': 'AI_AGENT', 'created_at': iso_now(), 'review_status': 'PENDING_REVIEW', 'is_demo': True})
        con.execute('INSERT INTO reports(id,listing_id,payload) VALUES(?,?,?)',
                    (rid, listing_id, json.dumps(result, ensure_ascii=False)))
        return result, 201

    return validated_write(actor, idempotency_key, payload_sha({'listing_id': listing_id, 'payload': payload}), operation)


def agent_action_create(payload: dict, authorization: str = '',
                        idempotency_key: str = ''):
    actor = require_actor(authorization)
    kind = payload.get('action_type')
    if kind not in ('SUBMIT_OFFER', 'COUNTER_OFFER', 'RECORD_HANDOVER_CHECK', 'REQUEST_SELLER_FIX'):
        bad(422, 'INVALID_ACTION', '지원하지 않는 action_type입니다.')
    content = payload.get('proposed_payload')
    if not isinstance(content, dict) or payload.get('payload_sha256') != payload_sha(content):
        bad(422, 'HASH_MISMATCH', '초안 해시와 내용이 다릅니다.')
    try:
        expiry = datetime.fromisoformat(payload['expires_at'].replace('Z', '+00:00'))
    except (ValueError, KeyError):
        bad(422, 'INVALID_EXPIRY', '만료일 형식이 잘못되었습니다.')
    if expiry <= datetime.now(timezone.utc):
        bad(422, 'EXPIRED', '이미 만료된 초안입니다.')

    def operation(con):
        if kind == 'SUBMIT_OFFER':
            listing = get_listing(con, payload['resource_id'])
            if actor['id'] == listing['seller_id'] or listing['status'] != 'ACTIVE':
                bad(403, 'FORBIDDEN', '활성 매물의 구매자만 제안할 수 있습니다.')
            if content.get('listing_id') != listing['id'] or content.get('is_demo') is not True:
                bad(422, 'INVALID_PAYLOAD', '초안의 매물 또는 DEMO 표시가 불일치합니다.')
            try:
                verify_amount(content.get('offered_price_krw'))
            except ValueError as exc:
                bad(422, 'INVALID_PRICE', str(exc))
        elif kind == 'COUNTER_OFFER':
            offer = get_offer(con, payload['resource_id'])
            if actor['id'] != offer['seller_id'] or offer['status'] != 'PENDING':
                bad(403, 'FORBIDDEN', '매도자만 유효한 제안에 역제안할 수 있습니다.')
            if content.get('expected_version') != offer['version']:
                bad(409, 'VERSION_CONFLICT', '제안 버전이 변경되었습니다.')
            try:
                verify_amount(content.get('offered_price_krw'))
            except ValueError as exc:
                bad(422, 'INVALID_PRICE', str(exc))
        else:
            bad(422, 'NOT_IMPLEMENTED', '이 action_type은 다음 개발 단계에서 구현됩니다.')
        aid = str(uuid.uuid4())
        con.execute('''INSERT INTO actions(id,user_id,action_type,resource_id,proposed_payload,payload_sha256,status,expires_at,created_at)
            VALUES(?,?,?,?,?,?,?,?,?)''', (aid, actor['id'], kind, payload['resource_id'],
                canonical_json(content), payload['payload_sha256'], 'PENDING_APPROVAL', payload['expires_at'], iso_now()))
        return action_dict(con.execute('SELECT * FROM actions WHERE id=?', (aid,)).fetchone()), 201

    return validated_write(actor, idempotency_key, payload_sha(payload), operation)


def agent_action_get(action_id: str, authorization: str = ''):
    actor = require_actor(authorization)
    with db() as con:
        row = con.execute('SELECT * FROM actions WHERE id=? AND user_id=?', (action_id, actor['id'])).fetchone()
        if row is None:
            bad(404, 'NOT_FOUND', '초안을 찾을 수 없습니다.')
        return action_dict(row)


def change_action_status(action_id, authorization, key, target):
    actor = require_actor(authorization)

    def operation(con):
        row = con.execute('SELECT * FROM actions WHERE id=? AND user_id=?', (action_id, actor['id'])).fetchone()
        if row is None:
            bad(404, 'NOT_FOUND', '초안을 찾을 수 없습니다.')
        action = action_dict(row)
        if action['status'] != 'PENDING_APPROVAL':
            bad(409, 'ACTION_STATE', '승인 대기 상태가 아닙니다.')
        if datetime.fromisoformat(action['expires_at'].replace('Z', '+00:00')) <= datetime.now(timezone.utc):
            bad(409, 'EXPIRED', '초안이 만료되었습니다.')
        con.execute('UPDATE actions SET status=? WHERE id=?', (target, action_id))
        return action_dict(con.execute('SELECT * FROM actions WHERE id=?', (action_id,)).fetchone()), 200

    return validated_write(actor, key, payload_sha({'id': action_id, 'target': target}), operation)


def approve_action(action_id: str, authorization: str = '',
                   idempotency_key: str = ''):
    return change_action_status(action_id, authorization, idempotency_key, 'APPROVED')


def reject_action(action_id: str, authorization: str = '',
                  idempotency_key: str = ''):
    return change_action_status(action_id, authorization, idempotency_key, 'REJECTED')


def execute_action(action_id: str, authorization: str = '',
                   idempotency_key: str = ''):
    actor = require_actor(authorization)

    def operation(con):
        row = con.execute('SELECT * FROM actions WHERE id=? AND user_id=?', (action_id, actor['id'])).fetchone()
        if row is None:
            bad(404, 'NOT_FOUND', '초안을 찾을 수 없습니다.')
        action = action_dict(row)
        if action['status'] != 'APPROVED' or payload_sha(action['proposed_payload']) != action['payload_sha256']:
            bad(409, 'APPROVAL_OR_HASH_MISMATCH', '승인이 없거나 승인된 초안 내용이 변경되었습니다.')
        if datetime.fromisoformat(action['expires_at'].replace('Z', '+00:00')) <= datetime.now(timezone.utc):
            bad(409, 'EXPIRED', '초안이 만료되었습니다.')
        content = action['proposed_payload']
        if action['action_type'] == 'SUBMIT_OFFER':
            listing = get_listing(con, action['resource_id'])
            if listing['status'] != 'ACTIVE' or actor['id'] == listing['seller_id']:
                bad(409, 'LISTING_STATE', '매물 거래 가능 상태가 아닙니다.')
            oid = str(uuid.uuid4())
            con.execute('''INSERT INTO offers(id,listing_id,buyer_id,seller_id,proposed_by,parent_offer_id,
                offered_price_krw,terms,status,version,is_demo,created_at,expires_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)''', (oid, listing['id'], actor['id'], listing['seller_id'],
                actor['id'], None, content['offered_price_krw'], canonical_json(content['terms']),
                'PENDING', 1, 1, iso_now(), content['expires_at']))
        elif action['action_type'] == 'COUNTER_OFFER':
            original = get_offer(con, action['resource_id'])
            if original['seller_id'] != actor['id'] or original['status'] != 'PENDING' or original['version'] != content['expected_version']:
                bad(409, 'VERSION_CONFLICT', '원 제안이 변경되어 역제안 불가합니다.')
            oid = str(uuid.uuid4())
            con.execute("UPDATE offers SET status='COUNTERED',version=version+1 WHERE id=?", (original['id'],))
            con.execute('''INSERT INTO offers(id,listing_id,buyer_id,seller_id,proposed_by,parent_offer_id,
                offered_price_krw,terms,status,version,is_demo,created_at,expires_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)''', (oid, original['listing_id'], original['buyer_id'], original['seller_id'],
                actor['id'], original['id'], content['offered_price_krw'], canonical_json(content['terms']),
                'PENDING', 1, 1, iso_now(), content['expires_at']))
        else:
            bad(422, 'NOT_IMPLEMENTED', '지원하지 않는 실행 작업입니다.')
        con.execute("UPDATE actions SET status='EXECUTED' WHERE id=?", (action_id,))
        result = action_dict(con.execute('SELECT * FROM actions WHERE id=?', (action_id,)).fetchone())
        result['created_offer_id'] = oid  # additive non-contract field, for DEMO screen navigation
        return result, 200

    return validated_write(actor, idempotency_key, payload_sha({'id': action_id, 'target': 'EXECUTE'}), operation)


def offer_list(listing_id: str = '', authorization: str = ''):
    actor = require_actor(authorization)
    with db() as con:
        rows = con.execute('SELECT * FROM offers WHERE buyer_id=? OR seller_id=? ORDER BY created_at',
                           (actor['id'], actor['id'])).fetchall()
    offers = [offer_dict(row) for row in rows if not listing_id or row['listing_id'] == listing_id]
    return {'items': offers, 'next_cursor': None}


def offer_detail(offer_id: str, authorization: str = ''):
    actor = require_actor(authorization)
    with db() as con:
        offer = get_offer(con, offer_id)
    require_offer_party(offer, actor)
    return offer


def offer_accept(offer_id: str, payload: dict, authorization: str = '',
                 idempotency_key: str = ''):
    actor = require_actor(authorization)

    def operation(con):
        offer = get_offer(con, offer_id)
        require_offer_party(offer, actor)
        # Counterparty's explicit human approval required.
        if offer['proposed_by'] == actor['id']:
            bad(403, 'SELF_ACCEPT', '자신이 보낸 제안을 직접 수락할 수 없습니다.')
        if offer['status'] != 'PENDING' or payload.get('expected_version') != offer['version']:
            bad(409, 'VERSION_CONFLICT', '제안 상태 또는 버전이 변경되었습니다.')
        listing = get_listing(con, offer['listing_id'])
        if listing['status'] != 'ACTIVE':
            bad(409, 'LISTING_STATE', '거래 가능한 매물이 아닙니다.')
        tx_id = str(uuid.uuid4())
        con.execute("UPDATE offers SET status='ACCEPTED',version=version+1 WHERE id=?", (offer_id,))
        con.execute('''INSERT INTO transactions(id,listing_id,accepted_offer_id,buyer_id,seller_id,status,version,created_at)
            VALUES(?,?,?,?,?,?,?,?)''', (tx_id, offer['listing_id'], offer_id, offer['buyer_id'], offer['seller_id'],
            'AWAITING_HANDOVER', 1, iso_now()))
        listing['status'] = 'RESERVED'
        listing['version'] = int(listing['version']) + 1
        con.execute('UPDATE listings SET payload=? WHERE id=?', (json.dumps(listing, ensure_ascii=False), listing['id']))
        return {'id': tx_id, 'listing_id': offer['listing_id'], 'accepted_offer_id': offer_id,
                'buyer_id': offer['buyer_id'], 'seller_id': offer['seller_id'],
                'is_demo': True, 'status': 'AWAITING_HANDOVER', 'version': 1, 'created_at': iso_now()}, 200

    return validated_write(actor, idempotency_key, payload_sha({'id': offer_id, 'payload': payload}), operation)


def transaction_detail(transaction_id: str, authorization: str = ''):
    actor = require_actor(authorization)
    with db() as con:
        return get_transaction(con, transaction_id, actor)


def list_handover(transaction_id: str, authorization: str = ''):
    actor = require_actor(authorization)
    with db() as con:
        get_transaction(con, transaction_id, actor)
        rows = con.execute('SELECT * FROM handover_checks WHERE transaction_id=? ORDER BY updated_at', (transaction_id,)).fetchall()
        return {'items': [handover_dict(r) for r in rows], 'next_cursor': None}


def handover_dict(row):
    out = dict(row)
    out['seller_submitted'] = bool(out['seller_submitted'])
    out['agent_checked'] = bool(out['agent_checked'])
    out['buyer_confirmed'] = bool(out['buyer_confirmed'])
    out['evidence_refs'] = json.loads(out['evidence_refs'])
    return out


def create_handover(transaction_id: str, payload: dict, authorization: str = '',
                    idempotency_key: str = ''):
    actor = require_actor(authorization)
    if payload.get('result') not in ('SELLER_SUBMITTED', 'NOT_TESTED', 'NEEDS_FIX') or not payload.get('check_key'):
        bad(422, 'INVALID_CHECK', '결과 상태 또는 check_key가 잘못되었습니다.')

    def operation(con):
        tx = get_transaction(con, transaction_id, actor)
        if payload['result'] == 'SELLER_SUBMITTED' and actor['id'] != tx['seller_id']:
            bad(403, 'FORBIDDEN', '판매자 제출은 판매자만 수행할 수 있습니다.')
        cid = str(uuid.uuid4())
        con.execute('''INSERT INTO handover_checks(id,transaction_id,check_key,description,seller_submitted,
            agent_checked,buyer_confirmed,result,evidence_refs,remarks,updated_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?)''', (cid, transaction_id, payload['check_key'], payload.get('description', ''),
                int(payload['result'] == 'SELLER_SUBMITTED'), 0, 0,
                payload['result'], json.dumps(payload.get('evidence_refs') or []), payload.get('remarks', ''), iso_now()))
        result = handover_dict(con.execute('SELECT * FROM handover_checks WHERE id=?', (cid,)).fetchone())
        return result, 201

    return validated_write(actor, idempotency_key, payload_sha({'tx': transaction_id, 'payload': payload}), operation)
