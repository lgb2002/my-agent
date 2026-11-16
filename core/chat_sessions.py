"""Session-bound chat transcripts; listing filters are not conversation identities.

Streamlit session_state provides per-browser-session isolation, but is not
permanent storage. Never put credentials in chat history or persistent logs.
"""


def conversation_scope(mode, actor, credential_scope):
    """Changing a listing filter must not start a new conversation."""
    return '{}::{}::{}'.format(mode, actor, credential_scope)


def get_or_migrate_session(store, scope, legacy_scopes=()):
    """Preserve v0.9 sessions whose old keys included the demo filter."""
    if scope not in store:
        source = next((key for key in legacy_scopes if key in store), None)
        store[scope] = store.pop(source) if source else {
            'turns': [], 'context': {'recent_listings': []}, 'pending': None
        }
    return store[scope]


def append_turn(session, role, content, **kwargs):
    """Retain the whole visible conversation until the user resets it.

    The model is independently restricted to recent turns in agent.chat;
    limiting model context must never silently delete the displayed history.
    """
    session['turns'].append({'role': role, 'content': content, **kwargs})
