"""Opt-in, account-scoped cloud conversation history.

Only text and safe tool *summaries* are stored; no bearer tokens, arbitrary
API payloads, pending approval cards, private tool results, or workflow auth.
Never accept an unverified visitor ID as owner.
"""
import json
import re
import uuid

from core.llm_service import contains_obvious_secret
from core.workflow_store import _db_connection, _sql, _guard_owner, _LOCK
from core.chat_sessions import new_session, conversation_title

_CREATE = '''CREATE TABLE IF NOT EXISTS agent_saved_conversations (
 owner_key TEXT NOT NULL, conversation_id TEXT NOT NULL, title TEXT NOT NULL,
 transcript_json TEXT NOT NULL, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 PRIMARY KEY(owner_key, conversation_id))'''
_ID = re.compile(r'^[a-f0-9]{32}$')


def _conversation_id(ident):
    if not isinstance(ident, str) or not _ID.fullmatch(ident):
        raise ValueError('대화 ID가 올바르지 않습니다.')
    return ident


def _sanitize(session):
    turns = session.get('turns', [])
    if not isinstance(turns, list):
        raise ValueError('대화 형식이 올바르지 않습니다.')
    saved = []
    for entry in turns:
        role = entry.get('role')
        if role not in ('user', 'assistant'):
            continue
        content = str(entry.get('content') or '')[:6000]
        if contains_obvious_secret(content):
            raise ValueError('비밀정보로 보이는 문장이 있어 대화를 보관하지 않았습니다.')
        # Preserve tool labels/status, not raw response data or listing details.
        events = []
        for ev in (entry.get('events') or [])[:8]:
            if not isinstance(ev, dict):
                continue
            name = str(ev.get('name') or '')[:45]
            label = str(ev.get('label') or '')[:65]
            summary = str(ev.get('summary') or '')[:200]
            if any(contains_obvious_secret(x) for x in (name, label, summary)):
                raise ValueError('도구 응답에 비밀정보가 있어 대화를 보관하지 않았습니다.')
            events.append({'name': name, 'label':label, 'summary':summary,
                           'success':ev.get('success') is True})
        saved.append({'role': role, 'content': content, 'events': events})
    raw = json.dumps({'version':1, 'turns': saved}, ensure_ascii=False)
    if len(raw.encode('utf-8')) > 750_000:
        raise ValueError('대화 보관 용량을 초과했습니다. 현재 대화를 내려받아 보관해 주세요.')
    return raw


def save_conversation(owner, ident, session):
    _guard_owner(owner)
    _conversation_id(ident)
    raw = _sanitize(session)
    title = conversation_title(session)[:80]
    with _LOCK, _db_connection() as con:
        con.execute(_CREATE)
        con.execute(_sql('''INSERT INTO agent_saved_conversations(owner_key,conversation_id,title,transcript_json,updated_at)
             VALUES(?,?,?,?,CURRENT_TIMESTAMP) ON CONFLICT(owner_key,conversation_id)
             DO UPDATE SET title=excluded.title,transcript_json=excluded.transcript_json,updated_at=CURRENT_TIMESTAMP'''),
             (owner,ident,title,raw))


def list_conversations(owner, limit=30):
    _guard_owner(owner)
    with _LOCK, _db_connection() as con:
        con.execute(_CREATE)
        rows = con.execute(_sql('''SELECT conversation_id,title,updated_at
            FROM agent_saved_conversations WHERE owner_key=? ORDER BY updated_at DESC LIMIT ?'''),
            (owner, min(60,max(1,int(limit))))).fetchall()
    return [{'id':ident,'title':str(title)[:45], 'updated_at':str(updated)}
            for ident,title,updated in rows]


def load_conversation(owner, ident):
    _guard_owner(owner)
    _conversation_id(ident)
    with _LOCK, _db_connection() as con:
        con.execute(_CREATE)
        row = con.execute(_sql('SELECT transcript_json FROM agent_saved_conversations WHERE owner_key=? AND conversation_id=?'),
                          (owner,ident)).fetchone()
    if not row:
        return None
    safe = json.loads(row[0])
    session = new_session()
    session['turns'] = safe.get('turns') or []
    # Deliberately never restore authorization, tool argument caches, approval
    # cards or stale execution state from an exported transcript.
    return session


def delete_conversation(owner, ident):
    _guard_owner(owner)
    _conversation_id(ident)
    with _LOCK, _db_connection() as con:
        con.execute(_CREATE)
        con.execute(_sql('DELETE FROM agent_saved_conversations WHERE owner_key=? AND conversation_id=?'), (owner,ident))
