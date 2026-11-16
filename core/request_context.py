"""Per-Streamlit-session remote authorization, never a process-wide API credential.

Streamlit runs visitors in independent script contexts within one Python process.
ContextVar keeps their delegated bearer tokens out of global state and off disk.
"""
from contextvars import ContextVar

_token = ContextVar('projectagain_delegation', default='')
_visitor = ContextVar('projectagain_visitor', default='')
_include_demo = ContextVar('projectagain_show_demo', default=False)


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
