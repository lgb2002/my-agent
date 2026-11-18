"""Account-scoped conversation navigation helpers; no Streamlit or network dependency.

The browser's active conversation is authoritative while it is in memory.
Cloud records are metadata only until explicitly selected by the owner.
"""
from datetime import datetime, timezone
import hashlib
import json

from core.chat_sessions import conversation_list


def visible_conversations(archive, cloud_rows=(), limit=40):
    """Merge local and owner-verified saved items by id; do not clone sessions."""
    by_id = {}
    for ident, title, updated in conversation_list(archive):
        session = archive['items'][ident]
        # Keep the current empty draft reachable, but omit old empty drafts.
        if not session.get('turns') and ident != archive.get('active'):
            continue
        by_id[ident] = {'id': ident, 'title': title, 'updated_at': updated,
                        'remote': False, 'local': True}
    for item in cloud_rows:
        ident = item.get('id')
        if not isinstance(ident, str) or not ident:
            continue
        if ident in by_id:
            by_id[ident]['remote'] = True
            # Preserve live local title and dirty content without overwriting.
        else:
            by_id[ident] = {'id': ident, 'title': str(item.get('title') or '저장된 대화')[:50],
                            'updated_at': str(item.get('updated_at') or ''),
                            'remote': True, 'local': False}
    def _sort_time(row):
        try:
            stamp = datetime.fromisoformat(row['updated_at'].replace('Z', '+00:00'))
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=timezone.utc)
            return stamp.timestamp()
        except (ValueError, TypeError, OverflowError):
            return 0.0
    return sorted(by_id.values(), key=_sort_time, reverse=True)[:limit]


def transcript_fingerprint(session):
    """Detect changes without serializing private tool payloads or approval cards."""
    parts = []
    for entry in session.get('turns') or []:
        if entry.get('role') not in ('user', 'assistant'):
            continue
        ev = []
        for e in (entry.get('events') or [])[:8]:
            if isinstance(e, dict):
                ev.append((str(e.get('name') or ''), str(e.get('label') or ''),
                           str(e.get('summary') or ''), e.get('success') is True))
        parts.append((entry.get('role'), str(entry.get('content') or ''), ev))
    data = json.dumps(parts, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    return hashlib.sha256(data).hexdigest()
