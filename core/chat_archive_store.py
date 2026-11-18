"""Account-scoped cloud conversation history for authenticated users.

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
from core.chat_history_snapshot import capture_event, historic_listing_references

_CREATE = '''CREATE TABLE IF NOT EXISTS agent_saved_conversations (
 owner_key TEXT NOT NULL, conversation_id TEXT NOT NULL, title TEXT NOT NULL,
 transcript_json TEXT NOT NULL, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 PRIMARY KEY(owner_key, conversation_id))'''
_SETTINGS = '''CREATE TABLE IF NOT EXISTS agent_chat_settings (
 owner_key TEXT PRIMARY KEY, auto_save INTEGER NOT NULL DEFAULT 0,
 updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)'''
_ID = re.compile(r'^[a-f0-9]{32}$')


def _conversation_id(ident):
    if not isinstance(ident, str) or not _ID.fullmatch(ident):
        raise ValueError('대화 ID가 올바르지 않습니다.')
    return ident


def _sanitize(session):
    """Versioned, owner-scoped transcript and safe historic evidence.

    v1 transcripts remain readable without migration. A snapshot is NOT
    execution context: it cannot restore pending approval, tool authorization,
    private API payloads, ZIP files or live transaction state.
    """
    turns = session.get('turns', [])
    if not isinstance(turns, list):
        raise ValueError('대화 형식이 올바르지 않습니다.')
    saved = []
    for entry in turns:
        if not isinstance(entry, dict) or entry.get('role') not in ('user','assistant'):
            continue
        content = str(entry.get('content') or '')[:6000]
        if contains_obvious_secret(content):
            raise ValueError('비밀정보로 보이는 문장이 있어 대화를 보관하지 않았습니다.')
        stamp = entry.get('created_at')
        events = []
        for ev in (entry.get('events') or [])[:8]:
            safe_event = capture_event(ev, captured_at=stamp)
            if safe_event:
                events.append(safe_event)
        turn = {'role':entry['role'],'content':content,'events':events}
        if isinstance(stamp,str) and len(stamp)<60:
            turn['created_at']=stamp
        saved.append(turn)
    raw = json.dumps({'version':2,'turns':saved}, ensure_ascii=False, separators=(',',':'))
    if len(raw.encode('utf-8')) > 8_000_000:
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


def list_conversations(owner, limit=60):
    _guard_owner(owner)
    with _LOCK, _db_connection() as con:
        con.execute(_CREATE)
        rows = con.execute(_sql('''SELECT conversation_id,title,updated_at
            FROM agent_saved_conversations WHERE owner_key=? ORDER BY updated_at DESC LIMIT ?'''),
            (owner, min(100,max(1,int(limit))))).fetchall()
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
    session['context']['recent_listings'] = historic_listing_references(session['turns'])
    session['context']['_listing_snapshot_stale'] = bool(session['context']['recent_listings'])
    session['_historical_restore'] = True
    # Deliberately never restore authorization, tool argument caches, approval
    # cards or stale execution state from an exported transcript.
    return session


def delete_conversation(owner, ident):
    _guard_owner(owner)
    _conversation_id(ident)
    with _LOCK, _db_connection() as con:
        con.execute(_CREATE)
        con.execute(_sql('DELETE FROM agent_saved_conversations WHERE owner_key=? AND conversation_id=?'), (owner,ident))


def chat_auto_save_enabled(owner):
    """Return saved, account-specific consent. No row means disabled."""
    _guard_owner(owner)
    with _LOCK, _db_connection() as con:
        con.execute(_SETTINGS)
        row = con.execute(_sql('SELECT auto_save FROM agent_chat_settings WHERE owner_key=?'),
                          (owner,)).fetchone()
    return bool(row and row[0])


def set_chat_auto_save(owner, enabled):
    """Persist opt-in; disabling does not delete earlier saved conversations."""
    _guard_owner(owner)
    if not isinstance(enabled, bool):
        raise TypeError('대화 저장 동의 상태가 올바르지 않습니다.')
    with _LOCK, _db_connection() as con:
        con.execute(_SETTINGS)
        con.execute(_sql('''INSERT INTO agent_chat_settings(owner_key,auto_save,updated_at)
            VALUES(?,?,CURRENT_TIMESTAMP) ON CONFLICT(owner_key)
            DO UPDATE SET auto_save=excluded.auto_save,updated_at=CURRENT_TIMESTAMP'''),
            (owner, int(enabled)))


def delete_all_conversations(owner):
    """Erase only the verified owner's saved chat transcripts (not preferences/jobs)."""
    _guard_owner(owner)
    with _LOCK, _db_connection() as con:
        con.execute(_CREATE)
        con.execute(_sql('DELETE FROM agent_saved_conversations WHERE owner_key=?'), (owner,))
