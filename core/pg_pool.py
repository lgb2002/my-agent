"""Bounded, process-local PostgreSQL connection reuse.

Never expose URLs or SQL errors to the browser. Every checkout uses its own
transaction; session/auth credentials never become pooled application state.
"""
import hashlib
import os
import threading
from contextlib import contextmanager

_LOCK = threading.RLock()
_POOLS = {}


def _pool_size():
    try:
        return max(1, min(6, int(os.environ.get('AGENT_PG_POOL_MAX', '3'))))
    except (TypeError, ValueError):
        return 3


@contextmanager
def connection(url):
    """Checkout a DB transaction from the bounded connection pool.

    Pool construction can be deferred until the first actual DB request. A
    dedicated pool is used for each connection string; user-scoped SQL must
    still filter on owner_key, and this API does not cache authorization.
    """
    import psycopg_pool
    ident = hashlib.sha256(url.encode('utf-8')).hexdigest()
    with _LOCK:
        pool = _POOLS.get(ident)
        if pool is None:
            pool = psycopg_pool.ConnectionPool(
                conninfo=url, min_size=0, max_size=_pool_size(),
                timeout=7, max_idle=90, max_lifetime=900,
                kwargs={'connect_timeout': 5, 'sslmode': 'require'},
                open=True,
            )
            _POOLS[ident] = pool
    with pool.connection() as conn:
        yield conn
