"""Allowlisted marketplace tools for the Streamlit conversation engine.

The model may propose these tools, but business rules, authorizations and
human confirmation are enforced here and by AgentRuntime. No model-controlled
HTTP URLs, shell commands, code execution or arbitrary Python functions.
"""
import hashlib
import json
import re
import uuid
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote

from agent.core import AgentError, AgentRuntime
from core.inspector import MAX_ARCHIVE_BYTES


TOOL_DEFINITIONS = [
    {
        "type": "function", "function": {
            "name": "search_listings", "description": "거래 플랫폼의 공개 매물을 검색하거나 매물 목록을 가져옵니다. 조회 전용.",
            "parameters": {"type": "object", "properties": {
                "query": {"type": "string", "description": "프로젝트 이름이나 검색 키워드, 없으면 빈 문자열"},
                "cursor": {"type": "integer", "description": "다음 페이지를 조회할 때 플랫폼이 반환한 정수 오프셋"}}, "required": []},
        },
    },
    {
        "type": "function", "function": {
            "name": "recommend_listings", "description": "예산·기술·위험 조건으로 안전한 후보를 1차 선별합니다. 정성 선호가 있으면 별도 AI 평가로 순위를 보완합니다.",
            "parameters": {"type": "object", "properties": {
                "max_budget_krw": {"type": "integer", "description": "사용자가 실제로 제시한 원화 예산 상한"},
                "max_monthly_cost_krw": {"type": "integer", "description": "사용자가 제시한 월 운영비 상한. 없으면 생략"},
                "skill_level": {"type": "string", "enum": ["NONE", "BASIC", "INTERMEDIATE", "ADVANCED"]},
                "risk_tolerance": {"type": "string", "enum": ["LOW", "MEDIUM", "HIGH"]},
                "preferred_tech_stack": {"type": "array", "items": {"type": "string"}},
                "objective": {"type": "string", "description": "사용자에게 확인한 구매 목적"},
                "require_preferred_stack": {"type": "boolean", "description": "선호 기술을 필수로 요구하는지"},
                "preferred_categories": {"type": "array", "items": {"type": "string"}, "description": "요구한 프로젝트 유형"},
                "max_results": {"type": "integer", "description": "최대 표시 후보 1~5, 기본 3"}},
                "required": ["max_budget_krw", "objective", "skill_level", "risk_tolerance"]},
        },
    },
    {
        "type": "function", "function": {
            "name": "inspect_listing", "description": "한 매물의 공개 메타데이터를 정적으로 점검합니다. 코드를 실행하거나 법적 권리를 보증하지 않습니다.",
            "parameters": {"type": "object", "properties": {
                "listing": {"type": "string", "description": "정확한 매물 UUID, 제목, 또는 사용자가 말한 1번/첫 번째 같은 순번"}},
                "required": ["listing"]},
        },
    },
    {
        "type": "function", "function": {
            "name": "inspect_attached_zip", "description": "판매자가 자신의 매물에 첨부할 ZIP을 로컬에서 정적 검사합니다. 플랫폼에 파일이나 보고서를 전송하지 않습니다.",
            "parameters": {"type": "object", "properties": {
                "listing": {"type": "string", "description": "판매자 본인 매물 UUID/제목/순번"}},
                "required": ["listing"]},
        },
    },
    {
        "type": "function", "function": {
            "name": "list_offers", "description": "특정 매물의 제안/협상 현황을 조회합니다. 조회 전용.",
            "parameters": {"type": "object", "properties": {
                "listing": {"type": "string", "description": "매물 UUID, 제목 또는 순번"}},
                "required": ["listing"]},
        },
    },
    {
        "type": "function", "function": {
            "name": "prepare_offer", "description": "사용자가 구매 제안 초안을 준비합니다. 실제 플랫폼에 제출하려면 별도 버튼 확인과 offer:draft 권한이 필요합니다.",
            "parameters": {"type": "object", "properties": {
                "listing": {"type": "string", "description": "매물 ID/제목/순번"},
                "price_krw": {"type": "integer", "description": "제안 가격, 원 단위"},
                "message": {"type": "string", "description": "거래 상대에게 전달될 협상 메시지"}},
                "required": ["listing", "price_krw", "message"]},
        },
    },
    {
        "type": "function", "function": {
            "name": "get_handover", "description": "플랫폼 거래의 인수인계 점검 항목을 조회합니다. 사용자 인증 필요.",
            "parameters": {"type": "object", "properties": {
                "transaction_id": {"type": "string", "description": "거래 UUID"}},
                "required": ["transaction_id"]},
        },
    },
    {
        "type": "function", "function": {
            "name": "get_buyer_preferences", "description": "연결된 사용자 계정의 구매 조건을 조회합니다. 사용자별 위임 토큰과 buyer_profile:read 권한이 필요합니다.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function", "function": {
            "name": "get_recent_jobs", "description": "현재 계정의 최근 에이전트 작업과 상태를 조회합니다.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
]

TOOL_LABELS = {
    "search_listings": "매물 검색", "recommend_listings": "맞춤 추천", "inspect_listing": "매물 실사",
    "inspect_attached_zip": "ZIP 정적 검사", "list_offers": "협상 현황 조회", "prepare_offer": "구매 제안 준비",
    "get_handover": "인수인계 조회", "get_recent_jobs": "작업 기록 조회",
    "get_buyer_preferences": "내 구매 조건",
}
READ_TOOLS = {"search_listings", "list_offers", "get_handover", "get_recent_jobs"}
STAGED_TOOLS = {"prepare_offer"}


@dataclass
class ToolEvent:
    name: str
    label: str
    success: bool
    summary: str
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self):
        return {"name": self.name, "label": self.label, "success": self.success,
                "summary": self.summary, "data": self.data}


def write_key(actor, operation, payload, nonce):
    """Unique per explicit click, stable only for a single operation retry."""
    raw = json.dumps([actor, operation, payload, nonce], sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class ToolDispatcher:
    def __init__(self, actor_name: str, context: dict):
        self.actor_name = actor_name
        self.context = context
        self.runtime = AgentRuntime(actor_name)

    def request(self, method, path, payload=None, body=None, *, write=False, nonce=None):
        key = write_key(self.actor_name, path, payload, nonce or uuid.uuid4().hex) if write else None
        return self.runtime.request(method, path, payload, body, write, key)

    def _listing(self, value):
        """Resolve user-visible ordinals through the stored *UUID*, never a moving page.

        A numerical choice is invalid if a previous search/recommendation has not
        explicitly pinned that position in the current conversation session.
        """
        text = str(value or "").strip()
        lowered = text.casefold()
        if not text:
            raise ValueError("어떤 매물인지 알려줘. 예: '매물 검색 후 1번 실사해줘'.")
        recent = self.context.get("recent_listings") or []
        index = None
        for idx, variants in enumerate((("1", "first", "첫 번째", "첫번째", "1번", "1위"),
                                       ("2", "second", "두 번째", "두번째", "2번", "2위"),
                                       ("3", "third", "세 번째", "세번째", "3번", "3위"))):
            if lowered in variants or (idx < 3 and re.fullmatch(r"{}\s*번(?:\s*매물)?".format(idx + 1), lowered)):
                index = idx
                break
        if index is not None:
            if index >= len(recent):
                raise ValueError("선택할 목록이 없어요. 먼저 매물을 검색하거나 추천받아 줘.")
            return self.request("GET", "/api/agent/v1/listings/" + quote(recent[index]["id"], safe=""))
        if re.fullmatch(r"[0-9a-fA-F-]{36}", text):
            return self.request("GET", "/api/agent/v1/listings/" + quote(text, safe=""))
        exact = [x for x in recent if str(x.get("title") or "").casefold() == lowered]
        matches = exact or [x for x in recent if lowered in str(x.get("title") or "").casefold()]
        if len(matches) == 1:
            return self.request("GET", "/api/agent/v1/listings/" + quote(matches[0]["id"], safe=""))
        if len(matches) > 1:
            raise ValueError("비슷한 매물이 여러 개야. 매물 순번 또는 UUID로 지정해줘.")
        # Only search public listings if the current conversation has no match.
        response = self.request("GET", "/api/agent/v1/listings?q=" + quote(text, safe=""))
        candidates = [x for x in response.get("items", []) if isinstance(x, dict) and x.get("id")]
        matches = [x for x in candidates if lowered == str(x.get("title") or "").casefold()]
        if len(matches) == 1:
            return self.request("GET", "/api/agent/v1/listings/" + quote(matches[0]["id"], safe=""))
        raise ValueError("매물을 하나로 선택할 수 없어요. 먼저 검색 후 순번이나 정확한 UUID를 사용해줘.")

    def _offer(self, offer_id):
        offer_id = str(offer_id or "").strip()
        recent = self.context.get("last_offers") or []
        if offer_id in ("최근", "마지막", "latest") and recent:
            offer_id = recent[-1]
        elif offer_id in ("1번", "첫 번째", "1") and recent:
            offer_id = recent[0]
        elif offer_id in ("2번", "두 번째", "2") and len(recent) > 1:
            offer_id = recent[1]
        # The lower-level marketplace implementation owns actor-scoped permissions.
        client, actor = self.runtime.authenticated()
        offer = client.offer(offer_id)
        if actor["id"] not in (offer["buyer_id"], offer["seller_id"]):
            raise ValueError("내 계정과 관련된 제안이 아닙니다.")
        return offer, actor

    def invoke(self, name: str, args: dict) -> tuple[ToolEvent, dict | None]:
        label = TOOL_LABELS.get(name, name)
        pending = None
        if name not in TOOL_LABELS:
            return ToolEvent(name, label, False, "등록되지 않은 도구는 실행하지 않아요."), None
        if not isinstance(args, dict):
            return ToolEvent(name, label, False, "도구 입력 형식이 올바르지 않아요."), None
        try:
            if name == "search_listings":
                q = str(args.get("query", ""))[:100].strip()
                offset = int(args.get("cursor") or 0)
                if offset < 0 or offset > 1000000:
                    raise ValueError("조회 페이지 번호가 올바르지 않아요.")
                page = self.request("GET", "/api/agent/v1/listings?q=" + quote(q, safe="") + "&limit=15&cursor=" + str(offset))
                items = page.get("items", [])[:15]
                self.context["recent_listings"] = [{"id": a["id"], "title": a.get("title") or "제목 미확인"} for a in items]
                self.context["listing_next_cursor"] = page.get("next_cursor")
                self.context["last_search_query"] = q
                data = {"listings": [{"id": x["id"], "title": x.get("title") or "제목 미확인", "price_krw": x.get("price_krw"),
                         "category": x.get("category") or "", "tech_stack": x.get("tech_stack") or [],
                         "verification_status": x.get("verification_status", "UNKNOWN"),
                         "description": str(x.get("description") or "")[:240]} for x in items]}
                data["query"] = q
                data["next_cursor"] = page.get("next_cursor")
                data["total_estimate"] = page.get("total_estimate")
                summary = "매물 {}건을 표시했어요.{}".format(len(items), " 다음 페이지가 있어요." if page.get("next_cursor") else "")
                if not items:
                    from core.request_context import include_demo
                    if not include_demo():
                        summary = "조회 성공 · 현재 조건에 0건입니다. 시연 매물이 제외되었을 수 있어요. 사이드바의 '시연 매물 포함'을 켠 뒤 다시 조회해 주세요."
                    else:
                        summary = "조회 성공 · 시연 매물 포함 조건에서도 0건입니다. ACTIVE 상태, 다른 필터 또는 플랫폼 연결 주소를 확인해 주세요."
            elif name == "recommend_listings":
                # Always check that the user supplied or accepted these fields.
                # Model-generated parameters alone must not bypass chat intake.
                # One recommendation run per explicit user-completed intake.
                # Never reuse this authorization for unsolicited model tool calls.
                confirmed = self.context.pop('confirmed_recommendation', None)
                if not isinstance(confirmed, dict) or any(not confirmed.get(field) for field in
                        ('objective', 'max_budget_krw', 'skill_level', 'risk_tolerance')):
                    raise ValueError('맞춤 추천 전에 구매 목적, 예산, 개발 수준, 위험 허용도를 확인해야 해요.')
                budget = int(confirmed['max_budget_krw'])
                if not 0 < budget <= 1000000000:
                    raise ValueError('구매 예산은 1원~10억원 사이로 지정해줘.')
                max_cost = confirmed.get('max_monthly_cost_krw')
                if max_cost is not None:
                    max_cost = int(max_cost)
                    if not 0 <= max_cost <= 100000000:
                        raise ValueError('월 운영비 상한을 확인해줘.')
                skill = confirmed['skill_level']
                risk = confirmed['risk_tolerance']
                if skill not in ('NONE', 'BASIC', 'INTERMEDIATE', 'ADVANCED') or risk not in ('LOW', 'MEDIUM', 'HIGH'):
                    raise ValueError('기술 수준 또는 위험 허용도가 올바르지 않아요.')
                tech = confirmed.get('preferred_tech_stack') or []
                if not isinstance(tech, list) or len(tech) > 10 or any(not isinstance(t, str) or len(t) > 40 for t in tech):
                    raise ValueError('선호 기술은 최대 10개의 이름으로 입력해줘.')
                objective = str(confirmed['objective'])[:90]
                prefs = {'max_budget_krw': budget, 'min_budget_krw': 0,
                         'max_monthly_cost_krw': max_cost, 'skill_level': skill,
                         'risk_tolerance': risk, 'objectives': [objective],
                         'preferred_tech_stack': tech,
                         'require_preferred_stack': bool(confirmed.get('require_preferred_stack')),
                         'preferred_categories': confirmed.get('preferred_categories', []),
                         'max_results': 3,
                         'qualitative_preferences': confirmed.get('qualitative_preferences') or []}
                job = self.request('POST', '/api/agent/v1/jobs', {'task_type': 'RECOMMEND', 'preferences': prefs}, write=True)
                full = self.request('GET', '/api/agent/v1/jobs/' + job['job_id'])
                self.context['last_job_id'] = job['job_id']
                result = full.get('result') or {}
                ranked = result.get('ranked', [])
                self.context['recent_listings'] = [{'id': x['listing_id'], 'title': x['title']} for x in ranked]
                self.context['listing_next_cursor'] = None
                self.context['last_search_query'] = ''
                data = {'job_id': job['job_id'], 'ranked': ranked,
                        'excluded': result.get('excluded', []),
                        'eligible_count': result.get('eligible_count', len(ranked)),
                        'criteria': prefs, 'status': full['status'],
                        'candidate_pool': result.get('candidate_pool', []),
                        'qualitative_preferences': result.get('qualitative_preferences', []),
                        'qualitative_review_status': result.get('qualitative_review_status', 'NOT_RUN'),
                        'excluded_count': len(result.get('excluded', [])),
                        'excluded_reasons': list(dict.fromkeys(
                            reason for item in result.get('excluded', [])
                            for reason in item.get('reasons', [])))[:5],
                        'risk_exclusions': [x for x in result.get('excluded', [])
                                            if any('저위험' in reason or '검증' in reason
                                                   for reason in x.get('reasons', []))][:3]}
                summary = ('맞춤 조건에 맞는 후보가 없습니다. 필요한 조건만 완화해 다시 추천받을 수 있어요.'
                           if not ranked else '조건에 맞는 후보 {}건 중 상위 {}건을 보여드려요.'.format(
                               data['eligible_count'], len(ranked)))
            elif name == "inspect_listing":
                listing = self._listing(args.get("listing"))
                job = self.request("POST", "/api/agent/v1/jobs", {"task_type": "INSPECT_METADATA", "listing_id": listing["id"]}, write=True)
                full = self.request("GET", "/api/agent/v1/jobs/" + job["job_id"])
                self.context["last_job_id"] = job["job_id"]
                data = {"listing_id": listing["id"], "listing_title": listing["title"], "job_id": job["job_id"], "report": full.get("result"), "status": full["status"]}
                summary = "{}의 공개 자료를 점검했어요. 실행 검증·권리 검증은 미완료예요.".format(listing["title"])
            elif name == "inspect_attached_zip":
                raw = self.context.get("attachment_bytes")
                if not isinstance(raw, bytes) or not raw:
                    raise ValueError("먼저 사이드바에서 검사할 ZIP 파일을 첨부해줘. 판매자 본인 매물만 검사할 수 있어.")
                if len(raw) > MAX_ARCHIVE_BYTES:
                    raise ValueError("첨부 ZIP은 최대 4MB예요.")
                listing = self._listing(args.get("listing"))
                job = self.request("POST", "/api/agent/v1/inspections/zip?listing_id=" + quote(listing["id"]), body=raw, write=True)
                full = self.request("GET", "/api/agent/v1/jobs/" + job["job_id"])
                self.context["last_job_id"] = job["job_id"]
                data = {"listing_title": listing["title"], "job_id": job["job_id"], "status": full["status"], "report": full.get("result")}
                summary = "첨부 ZIP을 실행하지 않고 검사했어요. 결과: {}.".format(full["status"])
            elif name == "list_offers":
                listing = self._listing(args.get("listing"))
                offers = self.request("GET", "/api/agent/v1/offers?listing_id=" + quote(listing["id"]))["items"][:20]
                self.context["last_offers"] = [x["id"] for x in offers]
                data = {"listing_title": listing["title"], "offers": [{"id": o["id"], "price_krw": o.get("offered_price_krw"),
                        "status": o.get("status", "UNKNOWN"), "version": o.get("version"), "proposed_by": o.get("proposed_by"),
                        "buyer_id": o.get("buyer_id"), "seller_id": o.get("seller_id")} for o in offers]}
                summary = "{}의 협상 제안 {}건을 조회했어요.".format(listing["title"], len(offers))
            elif name == "prepare_offer":
                from core.config import ENABLE_LIVE_DRAFTS
                if not ENABLE_LIVE_DRAFTS:
                    raise ValueError('플랫폼 초안 제출이 현재 비활성화되어 있습니다.')
                _client, live_principal = self.runtime.authenticated()
                if not str(live_principal.get('id') or '') or 'offer:draft' not in (live_principal.get('scopes') or []):
                    raise ValueError('위임 토큰에 offer:draft 권한이 필요합니다.')
                listing = self._listing(args.get("listing"))
                price = int(args.get("price_krw"))
                if not 0 < price <= 1000000000:
                    raise ValueError("제안 금액을 확인해줘.")
                message = str(args.get("message") or "")[:1000].strip()
                if not message:
                    raise ValueError("제안 메시지를 입력해줘.")
                pending = {"kind": "live_offer_draft", "listing_id": listing["id"], "listing_title": listing["title"],
                           "price_krw": price, "message": message, "actor": self.actor_name, "token": uuid.uuid4().hex}
                if live_principal:
                    if listing.get('seller_id') == live_principal['id']:
                        raise ValueError('본인 매물에는 제안할 수 없습니다.')
                    pending['principal_id'] = live_principal['id']
                data = {"listing_title": listing["title"], "listing_id": listing["id"], "price_krw": price, "message": message}
                summary = "{}에 {:,}원 제안 내용을 준비했어요. 플랫폼 승인 전에는 제안이 전송되지 않아요.".format(listing["title"], price)
            elif name == "get_handover":
                txid = str(args.get("transaction_id", "")).strip()
                if txid in ("최근", "latest", "마지막"):
                    txid = str(self.context.get("last_transaction_id") or "")
                if not re.fullmatch(r"[0-9a-fA-F-]{36}", txid):
                    raise ValueError("거래 ID(UUID)를 알려줘.")
                checks = self.request("GET", "/api/agent/v1/transactions/" + quote(txid) + "/handover-checks")
                data = {"transaction_id": txid, "checks": checks["items"][:30]}
                summary = "인수인계 확인 항목 {}건을 가져왔어요.".format(len(data["checks"]))
            elif name == "get_buyer_preferences":
                client, actor = self.runtime.authenticated()
                if not callable(getattr(client, "buyer_preferences", None)):
                    raise ValueError("구매 조건 조회는 실제 플랫폼 사용자 연결 후 사용할 수 있어요.")
                data = {"buyer_preferences": client.buyer_preferences()}
                summary = "연결된 계정의 구매 조건을 확인했어요."
            elif name == "get_recent_jobs":
                jobs = self.request("GET", "/api/agent/v1/jobs")["items"][:12]
                data = {"jobs": jobs}
                summary = "최근 작업 {}건을 조회했어요.".format(len(jobs))
            else:
                raise ValueError("허용되지 않은 도구입니다.")
            return ToolEvent(name, label, True, summary, data), pending
        except (AgentError, ValueError, KeyError, TypeError, StopIteration) as exc:
            return ToolEvent(name, label, False, str(exc)[:250]), None
        except Exception as exc:
            # An uncaught network/DB error must not leak secrets or internal paths to the user/LLM.
            return ToolEvent(name, label, False, "도구 실행에 실패했어요. 연결 상태와 데이터베이스를 확인해줘."), None
