"""Cheap conversation dirty tracking, bounded owner-scoped metadata caching.

Cached values are navigation metadata, not authorization, tokens, API results
or trade status. Callers must verify the account on every run and always pass
the matching owner to database queries.
"""
import time

CHAT_LIST_TTL = 18.0
DEFAULT_VISIBLE_TURNS = 24
MORE_VISIBLE_TURNS = 24


def conversation_revision(session):
    """O(1) dirty tracking; incremented whenever a chat turn is appended."""
    return int(session.get('_chat_revision', 0))


def cloud_list(cache, owner, fetch, *, now=None, ttl=CHAT_LIST_TTL):
    """At most one remote list read per owner per TTL interval."""
    now = time.monotonic() if now is None else now
    item = cache.get(owner)
    if isinstance(item, dict) and item.get('expires', -1) > now:
        return list(item.get('rows', ()))
    rows = fetch(owner)
    cache[owner] = {'rows': list(rows), 'expires': now + max(0, ttl)}
    return list(rows)


def invalidate_cloud_list(cache, owner):
    cache.pop(owner, None)


def visible_tail(turns, count=DEFAULT_VISIBLE_TURNS):
    """Render a bounded tail without dropping any persisted history."""
    limit = max(1, int(count))
    return max(0, len(turns) - limit), turns[-limit:]
