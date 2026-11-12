"""Direct in-process DEMO adapter + Replit HTTPS read-only API adapter.

Both expose the same subset of the marketplace OpenAPI methods. The DEMO
adapter does not require any HTTP server; the remote adapter never writes.
"""
from core.config import AGENT_MODE, DEMO_BUYER_TOKEN, DEMO_SELLER_TOKEN, MARKETPLACE_API_KEY
from core.marketplace_client import MarketplaceClient, MarketplaceError
from services import demo_marketplace as demo


class DemoClient:
    def __init__(self, actor_name):
        tokens = {'구매자 B': DEMO_BUYER_TOKEN, '판매자 A': DEMO_SELLER_TOKEN}
        if actor_name not in tokens:
            raise MarketplaceError(403, '허용되지 않은 샌드박스 사용자입니다.', 'FORBIDDEN')
        self.authorization = 'Bearer ' + tokens[actor_name]

    def me(self):
        return demo.auth_me(authorization=self.authorization)

    def listings(self, **params):
        return demo.listings(authorization=self.authorization, **params)

    def listing(self, listing_id):
        return demo.listing_detail(listing_id, authorization=self.authorization)

    def reports(self, listing_id):
        return demo.inspection_reports(listing_id, authorization=self.authorization)

    def publish_report(self, listing_id, report, key):
        return demo.post_inspection_report(listing_id, report, authorization=self.authorization, idempotency_key=key)

    def create_action(self, action, key):
        return demo.agent_action_create(action, authorization=self.authorization, idempotency_key=key)

    def action(self, action_id):
        return demo.agent_action_get(action_id, authorization=self.authorization)

    def action_approve(self, action_id, key):
        return demo.approve_action(action_id, authorization=self.authorization, idempotency_key=key)

    def action_reject(self, action_id, key):
        return demo.reject_action(action_id, authorization=self.authorization, idempotency_key=key)

    def action_execute(self, action_id, key):
        return demo.execute_action(action_id, authorization=self.authorization, idempotency_key=key)

    def offers(self, listing_id):
        return demo.offer_list(listing_id, authorization=self.authorization)

    def offer(self, offer_id):
        return demo.offer_detail(offer_id, authorization=self.authorization)

    def accept_offer(self, offer_id, version, key):
        return demo.offer_accept(offer_id, {'expected_version': version}, authorization=self.authorization, idempotency_key=key)

    def handover_checks(self, tx_id):
        return demo.list_handover(tx_id, authorization=self.authorization)

    def create_handover_check(self, tx_id, payload, key):
        return demo.create_handover(tx_id, payload, authorization=self.authorization, idempotency_key=key)


class LiveReadOnlyClient(MarketplaceClient):
    """Only the allowed GET routes. Future writes require new security design."""
    def __init__(self):
        super().__init__(MARKETPLACE_API_KEY)

    def request(self, method, path, payload=None, params=None, key=None):
        if method.upper() != 'GET':
            raise MarketplaceError(403, 'Replit 실플랫폼 쓰기는 아직 차단되어 있습니다.', 'WRITE_DISABLED')
        return super().request('GET', path, payload=None, params=params, key=None)


def client_for_actor(actor_name):
    return DemoClient(actor_name) if AGENT_MODE == 'mock' else LiveReadOnlyClient()
