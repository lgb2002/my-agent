"""Per-Streamlit-session remote authorization, never a process-wide API credential.

Streamlit runs visitors in independent script contexts within one Python process.
ContextVar keeps their delegated bearer tokens out of global state and off disk.
"""
from contextvars import ContextVar

_token = ContextVar('projectagain_delegation', default='')
_visitor = ContextVar('projectagain_visitor', default='')
_include_demo = ContextVar('projectagain_show_demo', default=False)
_refresh = ContextVar('projectagain_broker_refresh', default=None)
_access = ContextVar('projectagain_broker_access', default=None)


def set_request_context(*, token='', visitor_id='', include_demo=False):
    _token.set(str(token or '').strip())
    _visitor.set(str(visitor_id or '').strip())
    _include_demo.set(bool(include_demo))


def delegated_token():
    return _token.get()


def visitor_id():
    return _visitor.get()


def include_demo():
    return _include_demo.get()


def set_broker_refresh_handler(callback=None):
    """A current verified broker session may retry only a safe GET on 401."""
    _refresh.set(callback)

def force_refresh_for_get(observed_access_token):
    callback = _refresh.get()
    return callback(observed_access_token) if callback else None

def set_current_access_token(token):
    _token.set(str(token or '').strip())


def set_broker_access_handler(callback=None):
    _access.set(callback)

def ensure_broker_access():
    callback = _access.get()
    return callback() if callback else None
