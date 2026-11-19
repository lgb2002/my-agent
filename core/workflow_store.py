"""Opt-in, account-scoped workflow checkpoints and confirmed preferences.

Only a verified ProjectAgain principal may read/write. Never persist bearer
credentials, messages, raw private tool outputs, or secrets. SQLite is local
and NOT durable over Streamlit Community Cloud redeploys. Optional PostgreSQL
uses AGENT_STATE_DATABASE_URL with psycopg (when configured).
"""
import hashlib
import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

from core.config import DATA_DIR, MARKETPLACE_BASE_URL
from core.llm_service import contains_obvious_secret

_LOCK = threading.RLock()
LOCAL_DB = str(Path(DATA_DIR) / 'workflow_memory.sqlite3')
_SCHEMA = '''
CREATE TABLE IF NOT EXISTS agent_saved_workflows (
    owner_key TEXT NOT NULL, workflow_id TEXT NOT NULL, state_json TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (owner_key, workflow_id)
);
CREATE TABLE IF NOT EXISTS agent_saved_preferences (
    owner_key TEXT PRIMARY KEY, preferences_json TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
'''


def storage_kind():
    return 'postgres' if os.environ.get('AGENT_STATE_DATABASE_URL', '').strip() else 'sqlite'


def storage_health():
    """Database connectivity test, no secret URL or exception in results."""
    try:
        with _db_connection() as con:
            _initialize(con)
            con.execute('SELECT 1').fetchone()
        return {'ready':True,'kind':storage_kind(),
                'durable_across_cloud_redeploy':storage_kind() == 'postgres'}
    except Exception:
        return {'ready':False,'kind':storage_kind(),
                'durable_across_cloud_redeploy':False}



def verified_owner(actor):
    """Never use a visitor UUID, shared principal, or caller supplied ID."""
    from agent.core import AgentRuntime
    from core.request_context import delegated_token
    if not delegated_token():
        return None
    try:
        _client, me = AgentRuntime(actor).authenticated()
    except Exception:
        return None
    uid = me.get('id') if isinstance(me, dict) else None
    if not isinstance(uid, str) or not uid or uid.startswith('visitor:'):
        return None
    # Hash domain + verified user ID, never the bearer token.
    return hashlib.sha256((MARKETPLACE_BASE_URL + '::' + uid).encode('utf-8')).hexdigest()


def _connect():
    url = os.environ.get('AGENT_STATE_DATABASE_URL', '').strip()
    if url:
        if not url.startswith(('postgresql://', 'postgres://')):
            raise ValueError('AGENT_STATE_DATABASE_URL must be a PostgreSQL URL')
        try:
            import psycopg
        except ImportError as exc:
            raise RuntimeError('PostgreSQL 저장에는 psycopg[binary] 설치가 필요합니다.') from exc
        # Caller supplies SSL options in secret URL. Never log URL or exceptions.
        return psycopg.connect(url, connect_timeout=5, sslmode='require')
    con = sqlite3.connect(LOCAL_DB, timeout=10)
    con.execute('PRAGMA busy_timeout=10000')
    return con


@contextmanager
def _db_connection():
    # Use a bounded pool for PostgreSQL. SQLite tests retain their per-call DB
    # path so patching LOCAL_DB in isolated test runs remains effective.
    url = os.environ.get('AGENT_STATE_DATABASE_URL', '').strip()
    if url:
        if not url.startswith(('postgresql://', 'postgres://')):
            raise ValueError('AGENT_STATE_DATABASE_URL must be a PostgreSQL URL')
        from core.pg_pool import connection
        with connection(url) as con:
            yield con
        return
    con = _connect()
    try:
        with con:
            yield con
    finally:
        con.close()


def _sql(statement):
    return statement.replace('?', '%s') if storage_kind() == 'postgres' else statement


def _initialize(con):
    if storage_kind() == 'postgres':
        for sql in _SCHEMA.split(';'):
            if sql.strip():
                con.execute(sql)
    else:
        con.executescript(_SCHEMA)


def _guard_owner(owner):
    if not isinstance(owner, str) or len(owner) != 64 or not all(c in '0123456789abcdef' for c in owner):
        raise ValueError('검증된 사용자 계정 연결이 필요합니다.')


def _payload(data, max_bytes=12000):
    raw = json.dumps(data, ensure_ascii=False, separators=(',', ':'))
    if len(raw.encode('utf-8')) > max_bytes or contains_obvious_secret(raw):
        raise ValueError('저장 크기 또는 비밀정보 제한을 초과했어요.')
    return raw


def save_workflow(owner, plan):
    _guard_owner(owner)
    if not isinstance(plan, dict) or not plan.get('id'):
        raise ValueError('저장할 작업 계획이 없습니다.')
    # Store allowlisted plan data, not runtime context, approval payload or logs.
    safe = {k: plan.get(k) for k in (
        'id', 'goal', 'requested_count', 'steps', 'status', 'offer_price_krw',
        'ranked', 'recommendation_criteria', 'inspection', 'offer_listing_id',
        'issues', 'verified', 'remote_action_id', 'version')}
    raw = _payload(safe, 26000)
    with _LOCK:
        with _db_connection() as con:
            _initialize(con)
            con.execute(_sql('''INSERT INTO agent_saved_workflows(owner_key,workflow_id,state_json,updated_at)
                VALUES(?,?,?,CURRENT_TIMESTAMP)
                ON CONFLICT(owner_key,workflow_id) DO UPDATE SET
                  state_json=excluded.state_json,updated_at=CURRENT_TIMESTAMP'''),
                (owner, str(plan['id']), raw))


def _safe_load(plan):
    # A lost process between step start and completion is not a success.
    if not isinstance(plan, dict) or not isinstance(plan.get('steps'), list):
        return None
    for step in plan['steps']:
        if step.get('key') not in ('recommend','compare','inspect','prepare_offer','verify'):
            return None
        if step.get('status') == 'RUNNING':
            step['status'] = 'INTERRUPTED'
            step['note'] = '실행 중 연결이 끊겨 결과 확인 필요'
        elif step.get('status') == 'WAITING_APPROVAL':
            # Deliberately never save approval payloads or secret UI nonces.
            # A restored plan may not claim it has a live approval card.
            step['status'] = 'BLOCKED'
            step['note'] = '승인 카드는 복원되지 않음 · 플랫폼/대화 상태 재확인 필요'
            plan.setdefault('issues', []).append('승인 카드 복원 불가; 거래 상태 별도 확인 필요')
    if plan.get('status') in ('RUNNING', 'ACTIVE'):
        plan['status'] = 'INTERRUPTED'
    if any(step.get('key') == 'prepare_offer' and step.get('status') == 'BLOCKED'
           for step in plan['steps']):
        plan['status'] = 'PARTIAL'
    return plan


def load_workflow(owner, workflow_id):
    _guard_owner(owner)
    with _LOCK:
        with _db_connection() as con:
            _initialize(con)
            row = con.execute(_sql('SELECT state_json FROM agent_saved_workflows WHERE owner_key=? AND workflow_id=?'),
                              (owner, workflow_id)).fetchone()
    return _safe_load(json.loads(row[0])) if row else None


def list_workflows(owner, limit=12):
    _guard_owner(owner)
    with _LOCK:
        with _db_connection() as con:
            _initialize(con)
            rows = con.execute(_sql('''SELECT workflow_id,state_json,updated_at FROM agent_saved_workflows
                WHERE owner_key=? ORDER BY updated_at DESC LIMIT ?'''), (owner, min(30, max(1, limit)))).fetchall()
    out = []
    for wid, raw, updated in rows:
        try:
            plan = json.loads(raw)
            out.append({'id': wid, 'goal': str(plan.get('goal') or '')[:120],
                        'status': plan.get('status'), 'updated_at': str(updated)})
        except (ValueError, TypeError):
            continue
    return out


def delete_workflow(owner, workflow_id):
    _guard_owner(owner)
    with _LOCK:
        with _db_connection() as con:
            _initialize(con)
            con.execute(_sql('DELETE FROM agent_saved_workflows WHERE owner_key=? AND workflow_id=?'),
                        (owner, workflow_id))

PREFERENCE_KEYS = ('objective','max_budget_krw','max_monthly_cost_krw','skill_level',
                   'risk_tolerance','preferred_tech_stack','require_preferred_stack',
                   'preferred_categories','qualitative_preferences','assumptions')


def save_preferences(owner, profile):
    _guard_owner(owner)
    if not isinstance(profile, dict) or any(not profile.get(k) for k in
                                           ('objective','max_budget_krw','skill_level','risk_tolerance')):
        raise ValueError('사용자가 확인한 필수 구매 조건만 저장할 수 있어요.')
    safe = {k: profile[k] for k in PREFERENCE_KEYS if k in profile}
    raw = _payload(safe, 6000)
    with _LOCK:
        with _db_connection() as con:
            _initialize(con)
            con.execute(_sql('''INSERT INTO agent_saved_preferences(owner_key,preferences_json,updated_at)
                VALUES(?,?,CURRENT_TIMESTAMP)
                ON CONFLICT(owner_key) DO UPDATE SET preferences_json=excluded.preferences_json,
                updated_at=CURRENT_TIMESTAMP'''), (owner, raw))


def load_preferences(owner):
    _guard_owner(owner)
    with _LOCK:
        with _db_connection() as con:
            _initialize(con)
            row = con.execute(_sql('SELECT preferences_json FROM agent_saved_preferences WHERE owner_key=?'), (owner,)).fetchone()
    return json.loads(row[0]) if row else None


def delete_preferences(owner):
    _guard_owner(owner)
    with _LOCK:
        with _db_connection() as con:
            _initialize(con)
            con.execute(_sql('DELETE FROM agent_saved_preferences WHERE owner_key=?'), (owner,))
