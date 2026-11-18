"""Ephemeral, per-conversation ZIP handoff for settings-dialog upload.

The user must explicitly choose Scan; simply closing the dialog never attaches a
ZIP to the next unrelated chat prompt. This module is pure and testable.
"""
MAX_ZIP_BYTES = 4 * 1024 * 1024


def stored_zip_bytes(record, scope, conversation_id, *, require_armed=True):
    if not isinstance(record, dict):
        return None
    if record.get('scope') != scope or record.get('conversation_id') != conversation_id:
        return None
    data = record.get('data')
    if not isinstance(data, bytes) or not 0 < len(data) <= MAX_ZIP_BYTES:
        return None
    if require_armed and record.get('armed') is not True:
        return None
    return data


def zip_record(scope, conversation_id, data, *, armed=False):
    if not isinstance(scope, str) or not scope or not isinstance(conversation_id, str) or not conversation_id:
        raise ValueError('현재 대화가 확인되지 않았어요.')
    if not isinstance(data, bytes) or not 0 < len(data) <= MAX_ZIP_BYTES:
        raise ValueError('ZIP 파일은 4MB 이하여야 해요.')
    return {'scope':scope, 'conversation_id':conversation_id, 'data':data, 'armed':bool(armed)}
