"""Confirmed Streamlit-button initiated live draft submission only.

No LLM route can call this module. Platform browser handles approval/rejection,
execution is not offered from this app. External API schema is version-dependent:
remote 422/409 is reported, never silently retried as a new draft.
"""
import uuid

from core.config import ENABLE_LIVE_DRAFTS
from core.request_context import delegated_token
from core.policy import payload_sha, expiration_iso, verify_amount
from services.marketplace import LiveReadOnlyClient
from core.marketplace_client import MarketplaceError


def submit_confirmed_draft(pending):
    """Invoke only on a human click; call exactly once per pending confirmation."""
    if not ENABLE_LIVE_DRAFTS:
        raise ValueError('실플랫폼 초안 제출은 현재 비활성화되어 있습니다.')
    if pending.get('kind') != 'live_offer_draft' or not delegated_token():
        raise ValueError('사용자별 위임 토큰과 확인된 초안이 필요합니다.')
    verify_amount(pending.get('price_krw'))
    try:
        lid = str(uuid.UUID(str(pending['listing_id'])))
    except (KeyError, ValueError, TypeError):
        raise ValueError('매물 ID가 유효하지 않습니다.') from None
    msg = str(pending.get('message') or '')
    if not 1 <= len(msg) <= 1000:
        raise ValueError('제안 메시지 길이가 올바르지 않습니다.')
    client = LiveReadOnlyClient()
    principal = client.me()
    if not principal.get('id') or 'offer:draft' not in (principal.get('scopes') or []):
        raise ValueError('본인 인증 및 offer:draft 권한이 필요합니다.')
    if pending.get('principal_id') != principal['id']:
        raise ValueError('초안 준비 시 연결한 계정과 현재 계정이 다릅니다.')
    listing = client.listing(lid)
    if listing.get('seller_id') == principal['id']:
        raise ValueError('자신의 매물에는 구매 제안을 할 수 없습니다.')
    if listing.get('status') != 'ACTIVE':
        raise ValueError('활성 매물에 대해서만 초안 제출이 가능합니다.')
    content = {'listing_id': lid, 'offered_price_krw': pending['price_krw'],
               'message': msg, 'repair_requests': []}
    proposal = {'action_type': 'SUBMIT_OFFER', 'resource_id': lid,
                'proposed_payload': content, 'payload_sha256': payload_sha(content),
                'expires_at': expiration_iso()}
    nonce = pending.get('token')
    if not isinstance(nonce,str) or len(nonce) < 16:
        raise ValueError('초안 확인 상태가 유효하지 않습니다.')
    # Stable for THIS button confirmation only. Never retry automatically;
    # server-side Idempotency-Key handling remains a platform prerequisite.
    from agent.tools import write_key
    key = write_key(principal['id'], 'SUBMIT_OFFER', proposal, nonce)
    response = client.draft_action(proposal, key)
    action_id = response.get('id') or response.get('action_id')
    if not action_id:
        raise MarketplaceError(502, '플랫폼 초안 ID를 확인할 수 없습니다.', 'CONTRACT_MISMATCH')
    return str(uuid.UUID(str(action_id)))


def check_action_status(action_id):
    return LiveReadOnlyClient().action(str(uuid.UUID(str(action_id))))
