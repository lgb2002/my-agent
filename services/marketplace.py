"""ProjectAgain HTTPS adapter; user-scoped reads and explicit drafts only.

There is no internal catalogue or marketplace emulator.
"""
from core.config import ENABLE_LIVE_DRAFTS
from core.request_context import delegated_token
from core.marketplace_client import MarketplaceClient, MarketplaceError


class LiveReadOnlyClient(MarketplaceClient):
    """Read-only API; an independently confirmed draft is the sole POST exception."""
    def __init__(self):
        super().__init__(delegated_token())

    def request(self, method, path, payload=None, params=None, key=None):
        if method.upper() != 'GET':
            raise MarketplaceError(403, '실제 플랫폼 변경은 여기서 실행할 수 없습니다.', 'WRITE_DISABLED')
        return super().request('GET', path, payload=None, params=params, key=None)

    def draft_action(self, action, key):
        """Called only after a human confirms. Never approves or executes."""
        if not ENABLE_LIVE_DRAFTS:
            raise MarketplaceError(403, '플랫폼 초안 제출이 비활성화돼 있습니다.', 'WRITE_DISABLED')
        if action.get('action_type') != 'SUBMIT_OFFER':
            raise MarketplaceError(422, '구매 제안 초안만 제출할 수 있습니다.', 'INVALID_ACTION')
        return super().request('POST', '/api/v1/agent-actions', payload=action, key=key)


def client_for_actor(_actor_name):
    """All actor identities come from a visitor's verified platform token."""
    return LiveReadOnlyClient()
