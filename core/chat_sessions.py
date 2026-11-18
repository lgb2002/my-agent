"""In-browser multi-conversation archive, scoped to the authenticated visitor.

Unlike a conversation reset, starting a new conversation never overwrites the
previous transcript. Persistence beyond a browser session is separately opt-in.
"""
from datetime import datetime, timezone
from uuid import uuid4


def conversation_scope(mode, actor, credential_scope):
    return '{}::{}::{}'.format(mode, actor, credential_scope)


def new_session():
    return {'turns': [], 'context': {'recent_listings': []}, 'pending': None}


def get_or_migrate_session(store, scope, legacy_scopes=()):
    if scope not in store:
        source = next((key for key in legacy_scopes if key in store), None)
        store[scope] = store.pop(source) if source else new_session()
    return store[scope]


def append_turn(session, role, content, **kwargs):
    if role == 'user':
        session.pop('_historical_restore', None)
    session['turns'].append({'role': role, 'content': content, 'created_at': _now(), **kwargs})
    session['updated_at'] = datetime.now(timezone.utc).isoformat()
    session['_chat_revision'] = int(session.get('_chat_revision', 0)) + 1


def conversation_title(session):
    """Choose earliest meaningful user request; don't title work just '안녕'."""
    messages=[]
    for turn in session.get('turns', []):
        if isinstance(turn,dict) and turn.get('role') == 'user':
            value=' '.join(str(turn.get('content') or '').split())
            if value:
                messages.append(value)
    greetings={'안녕','안녕하세요','하이','hi','hello','ㅎㅇ','고마워','감사합니다'}
    chosen = next((v for v in messages if v.casefold() not in greetings and len(v)>5),
                  messages[0] if messages else '새 대화')
    return chosen[:36] + ('…' if len(chosen)>36 else '')


def _now():
    return datetime.now(timezone.utc).isoformat()


def init_archive(archive_store, scope, legacy_session):
    """Migrate the existing v0.17.1 live conversation on first use."""
    # A previous app version used setdefault(scope, None) before calling us.
    # Treat only that placeholder as uninitialized, preserving real archives.
    if archive_store.get(scope) is None:
        conversation_id = uuid4().hex
        archive_store[scope] = {
            'active': conversation_id,
            'items': {conversation_id: legacy_session},
            'created': {conversation_id: _now()},
        }
    archive = archive_store[scope]
    active = archive.get('active')
    if active not in archive.get('items', {}):
        archive['active'] = next(iter(archive['items']), None)
    if not archive['active']:
        return start_conversation(archive)
    return archive['items'][archive['active']]


def start_conversation(archive):
    ident = uuid4().hex
    session = new_session()
    archive['items'][ident] = session
    archive.setdefault('created', {})[ident] = _now()
    archive['active'] = ident
    return session


def open_conversation(archive, ident):
    if ident not in archive['items']:
        raise ValueError('대화를 찾을 수 없습니다.')
    archive['active'] = ident
    # An approval nonce cannot survive leaving and reopening the conversation.
    archive['items'][ident]['pending'] = None
    return archive['items'][ident]


def remove_conversation(archive, ident):
    if ident not in archive['items']:
        raise ValueError('대화를 찾을 수 없습니다.')
    del archive['items'][ident]
    archive.get('created', {}).pop(ident, None)
    if archive.get('active') == ident:
        archive['active'] = None
        return start_conversation(archive)
    return archive['items'][archive['active']]


def conversation_list(archive):
    items = [(ident, conversation_title(session), session.get('updated_at') or
              archive.get('created', {}).get(ident) or '') for ident, session in archive['items'].items()]
    return sorted(items, key=lambda row: row[2], reverse=True)
