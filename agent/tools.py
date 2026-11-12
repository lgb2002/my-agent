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
from core.config import AGENT_MODE
from core.inspector import MAX_ARCHIVE_BYTES


TOOL_DEFINITIONS = [
    {
        "type": "function", "function": {
            "name": "search_listings", "description": "거래 플랫폼의 공개 매물을 검색하거나 매물 목록을 가져옵니다. 조회 전용.",
            "parameters": {"type": "object", "properties": {
                "query": {"type": "string", "description": "프로젝트 이름이나 검색 키워드, 없으면 빈 문자열"}}, "required": []},
        },
    },
    {
        "type": "function", "function": {
            "name": "recommend_listings", "description": "구매 예산, 기술 수준 및 위험 허용도에 따라 매물을 규칙 기반으로 평가하고 추천 작업을 저장합니다.",
            "parameters": {"type": "object", "properties": {
                "max_budget_krw": {"type": "integer", "description": "원화 예산 상한, 모르면 1000000"},
                "max_monthly_cost_krw": {"type": "integer", "description": "월 운영비 상한, 모르면 30000"},
                "skill_level": {"type": "string", "enum": ["NONE", "BASIC", "INTERMEDIATE", "ADVANCED"]},
                "risk_tolerance": {"type": "string", "enum": ["LOW", "MEDIUM", "HIGH"]},
                "preferred_tech_stack": {"type": "array", "items": {"type": "string"}},
                "objective": {"type": "string", "description": "사용자의 구매 목적"}},
                "required": ["max_budget_krw"]},
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
            "name": "inspect_attached_zip", "description": "사용자가 직접 첨부한 ZIP을 정적 검사합니다. DEMO 판매자 본인 매물만 검사 가능합니다. 압축 해제/실행하지 않습니다.",
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
            "name": "prepare_offer", "description": "구매자가 DEMO 매물에 제안하려는 가격/메시지를 미리 작성합니다. 절대로 제안을 생성·전송하지 않고 화면에 확인 요청을 띄웁니다.",
            "parameters": {"type": "object", "properties": {
                "listing": {"type": "string", "description": "매물 ID/제목/순번"},
                "price_krw": {"type": "integer", "description": "제안 가격, 원 단위"},
                "message": {"type": "string", "description": "거래 상대에게 전달될 협상 메시지"}},
                "required": ["listing", "price_krw", "message"]},
        },
    },
    {
        "type": "function", "function": {
            "name": "prepare_counter_offer", "description": "판매자가 기존 구매자 제안에 역제안을 준비합니다. 전송하지 않고 사용자 확인을 요청합니다.",
            "parameters": {"type": "object", "properties": {
                "offer_id": {"type": "string", "description": "기존 제안 UUID"},
                "price_krw": {"type": "integer", "description": "역제안 금액"},
                "message": {"type": "string"}},
                "required": ["offer_id", "price_krw", "message"]},
        },
    },
    {
        "type": "function", "function": {
            "name": "prepare_accept_offer", "description": "판매자의 역제안 수락을 위한 확인 요청을 준비합니다. 사용자의 확인 버튼 전에는 아무것도 실행하지 않습니다.",
            "parameters": {"type": "object", "properties": {
                "offer_id": {"type": "string", "description": "수락하려는 역제안의 UUID"}},
                "required": ["offer_id"]},
        },
    },
    {
        "type": "function", "function": {
            "name": "prepare_publish_report", "description": "판매자가 자신의 ZIP 정적 검사 보고서를 플랫폼 검토 대기로 제출하기 위한 확인 요청을 준비합니다. AI는 제출하지 않습니다.",
            "parameters": {"type": "object", "properties": {
                "job_id": {"type": "string", "description": "완료된 ZIP 정적 검사 작업 UUID"}},
                "required": ["job_id"]},
        },
    },
    {
        "type": "function", "function": {
            "name": "prepare_handover_check", "description": "판매자가 DEMO 인수인계 체크 항목을 기록할 수 있도록 내용 검토 요청을 준비합니다. 구매자 최종 확인을 주장하지 않습니다.",
            "parameters": {"type": "object", "properties": {
                "transaction_id": {"type": "string", "description": "DEMO 거래 UUID"},
                "check_key": {"type": "string", "enum": ["source_manifest", "run_in_new_environment", "external_accounts", "ip_rights_review"]},
                "result": {"type": "string", "enum": ["NOT_TESTED", "NEEDS_FIX", "SELLER_SUBMITTED"]},
                "remarks": {"type": "string", "description": "검사 결과 또는 미확인 사항"}},
                "required": ["transaction_id", "check_key", "result", "remarks"]},
        },
    },
    {
        "type": "function", "function": {
            "name": "get_handover", "description": "DEMO 거래의 인수인계 점검 항목을 조회합니다.",
            "parameters": {"type": "object", "properties": {
                "transaction_id": {"type": "string", "description": "거래 UUID"}},
                "required": ["transaction_id"]},
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
    "prepare_counter_offer": "역제안 준비", "prepare_accept_offer": "수락 검토",
    "get_handover": "인수인계 조회", "get_recent_jobs": "작업 기록 조회",
    "prepare_publish_report": "검사 보고서 제출 준비", "prepare_handover_check": "인계 기록 준비",
}
READ_TOOLS = {"search_listings", "list_offers", "get_handover", "get_recent_jobs"}
STAGED_TOOLS = {"prepare_offer", "prepare_counter_offer", "prepare_accept_offer"}


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
        items = self.request("GET", "/api/agent/v1/listings")["items"]
        text = str(value or "").strip()
        lowered = text.casefold()
        if not items:
            raise ValueError("조회할 수 있는 매물이 없습니다.")
        recent = self.context.get("recent_listings") or []
        if lowered in ("1", "first") or re.search(r"(?:첫\s*번째|1\s*번|1위)", lowered):
            match = recent[0] if recent else items[0]
            return next(x for x in items if x["id"] == match["id"])
        if lowered in ("2", "second") or re.search(r"(?:두\s*번째|2\s*번|2위)", lowered):
            source = recent or items
            if len(source) > 1:
                return next(x for x in items if x["id"] == source[1]["id"])
        if lowered in ("3", "third") or re.search(r"(?:세\s*번째|3\s*번|3위)", lowered):
            source = recent or items
            if len(source) > 2:
                return next(x for x in items if x["id"] == source[2]["id"])
        if not text:
            raise ValueError("어떤 매물인지 알려줘. 예: '첫 번째 매물 실사해줘'.")
        exact = [x for x in items if lowered in (x["id"].casefold(), x["title"].casefold())]
        if len(exact) == 1:
            return exact[0]
        matches = [x for x in items if lowered in x["title"].casefold() or x["id"].casefold().startswith(lowered)]
        if len(matches) == 1:
            return matches[0]
        raise ValueError("매물을 하나로 지정할 수 없어요. 매물 제목이나 순번(1번, 2번)을 알려줘.")

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
                items = self.request("GET", "/api/agent/v1/listings?q=" + quote(q, safe=""))["items"][:15]
                self.context["recent_listings"] = [{"id": a["id"], "title": a["title"]} for a in items]
                data = {"listings": [{"id": x["id"], "title": x["title"], "price_krw": x["price_krw"],
                         "category": x.get("category", ""), "tech_stack": x.get("tech_stack", []),
                         "verification_status": x.get("verification_status", "UNKNOWN"),
                         "description": str(x.get("description", ""))[:240]} for x in items]}
                summary = "검색 결과 {}건을 찾았어요.".format(len(items))
            elif name == "recommend_listings":
                budget = int(args.get("max_budget_krw", 1000000))
                if not 0 < budget <= 1000000000:
                    raise ValueError("구매 예산은 1원~10억원 사이로 지정해줘.")
                max_cost = int(args.get("max_monthly_cost_krw", 30000))
                if not 0 <= max_cost <= 100000000:
                    raise ValueError("월 운영비 상한을 확인해줘.")
                skill = args.get("skill_level", "BASIC")
                risk = args.get("risk_tolerance", "MEDIUM")
                if skill not in ("NONE", "BASIC", "INTERMEDIATE", "ADVANCED") or risk not in ("LOW", "MEDIUM", "HIGH"):
                    raise ValueError("기술 수준 또는 위험 허용도가 올바르지 않아요.")
                tech = args.get("preferred_tech_stack", [])
                if not isinstance(tech, list) or len(tech) > 10 or any(not isinstance(t, str) or len(t) > 40 for t in tech):
                    raise ValueError("선호 기술은 최대 10개의 이름으로 입력해줘.")
                objective = str(args.get("objective") or "학습 및 프로젝트 인수")[:80]
                prefs = {"max_budget_krw": budget, "min_budget_krw": 0,
                         "max_monthly_cost_krw": max_cost, "skill_level": skill,
                         "risk_tolerance": risk, "objectives": [objective], "preferred_tech_stack": tech}
                job = self.request("POST", "/api/agent/v1/jobs", {"task_type": "RECOMMEND", "preferences": prefs}, write=True)
                full = self.request("GET", "/api/agent/v1/jobs/" + job["job_id"])
                self.context["last_job_id"] = job["job_id"]
                ranked = (full.get("result") or {}).get("ranked", [])
                self.context["recent_listings"] = [{"id": x["listing_id"], "title": x["title"]} for x in ranked]
                data = {"job_id": job["job_id"], "ranked": ranked, "excluded": (full.get("result") or {}).get("excluded", []),
                        "criteria": prefs, "status": full["status"]}
                summary = "조건을 적용해 {}개 후보를 추렸어요. 점수는 규칙 기반 추정이며 수익성 보증은 아니에요.".format(len(ranked))
            elif name == "inspect_listing":
                listing = self._listing(args.get("listing"))
                job = self.request("POST", "/api/agent/v1/jobs", {"task_type": "INSPECT_METADATA", "listing_id": listing["id"]}, write=True)
                full = self.request("GET", "/api/agent/v1/jobs/" + job["job_id"])
                self.context["last_job_id"] = job["job_id"]
                data = {"listing_title": listing["title"], "job_id": job["job_id"], "report": full.get("result"), "status": full["status"]}
                summary = "{}의 공개 자료를 점검했어요. 실행 검증·권리 검증은 미완료예요.".format(listing["title"])
            elif name == "inspect_attached_zip":
                if AGENT_MODE != "mock" or self.actor_name != "판매자 A":
                    raise ValueError("DEMO 판매자 본인만 ZIP 정적 검사를 실행할 수 있어요.")
                raw = self.context.get("attachment_bytes")
                if not isinstance(raw, bytes) or not raw:
                    raise ValueError("먼저 사이드바에서 검사할 ZIP 파일을 첨부해줘.")
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
                data = {"listing_title": listing["title"], "offers": [{"id": o["id"], "price_krw": o["offered_price_krw"],
                        "status": o["status"], "version": o["version"], "proposed_by": o["proposed_by"],
                        "buyer_id": o["buyer_id"], "seller_id": o["seller_id"]} for o in offers]}
                summary = "{}의 협상 제안 {}건을 조회했어요.".format(listing["title"], len(offers))
            elif name == "prepare_offer":
                if AGENT_MODE != "mock" or self.actor_name != "구매자 B":
                    raise ValueError("구매자 DEMO에서만 제안 초안을 만들 수 있어요. 실플랫폼 변경은 차단돼요.")
                listing = self._listing(args.get("listing"))
                price = int(args.get("price_krw"))
                if not 0 < price <= 1000000000:
                    raise ValueError("제안 금액을 확인해줘.")
                message = str(args.get("message") or "")[:1000].strip()
                if not message:
                    raise ValueError("제안 메시지를 입력해줘.")
                pending = {"kind": "offer_draft", "listing_id": listing["id"], "listing_title": listing["title"],
                           "price_krw": price, "message": message, "actor": self.actor_name, "token": uuid.uuid4().hex}
                data = {"listing_title": listing["title"], "price_krw": price, "message": message}
                summary = "{}에 {:,}원 제안 내용을 준비했어요. 아래 확인 버튼을 누르기 전에는 초안을 생성하지 않아요.".format(listing["title"], price)
            elif name == "prepare_counter_offer":
                if AGENT_MODE != "mock" or self.actor_name != "판매자 A":
                    raise ValueError("판매자 DEMO에서만 역제안을 준비할 수 있어요.")
                offer, actor = self._offer(args.get("offer_id"))
                if offer["seller_id"] != actor["id"] or offer["status"] != "PENDING":
                    raise ValueError("본인이 받은 유효한 구매자 제안만 역제안할 수 있어요.")
                price = int(args.get("price_krw"))
                if not 0 < price <= 1000000000:
                    raise ValueError("역제안 금액을 확인해줘.")
                message = str(args.get("message") or "역제안을 제시합니다.")[:1000]
                pending = {"kind": "counter_draft", "offer_id": offer["id"], "price_krw": price, "message": message,
                           "actor": self.actor_name, "token": uuid.uuid4().hex}
                data = {"offer_id": offer["id"], "price_krw": price, "message": message}
                summary = "역제안 {:,}원을 준비했어요. 아래에서 확인할 수 있어요.".format(price)
            elif name == "prepare_accept_offer":
                if AGENT_MODE != "mock" or self.actor_name != "구매자 B":
                    raise ValueError("구매자 DEMO에서만 역제안을 수락할 수 있어요.")
                offer, actor = self._offer(args.get("offer_id"))
                if offer["buyer_id"] != actor["id"] or offer["proposed_by"] != offer["seller_id"] or offer["status"] != "PENDING":
                    raise ValueError("수락 가능한 판매자 역제안이 아니에요.")
                pending = {"kind": "accept_offer", "offer_id": offer["id"], "version": offer["version"],
                           "price_krw": offer["offered_price_krw"], "actor": self.actor_name, "token": uuid.uuid4().hex}
                data = {"offer_id": offer["id"], "price_krw": offer["offered_price_krw"]}
                summary = "{:,.0f}원 역제안 수락을 준비했어요. 사용자 확인 전에는 거래 상태를 변경하지 않아요.".format(offer["offered_price_krw"])
            elif name == "prepare_publish_report":
                if AGENT_MODE != "mock" or self.actor_name != "판매자 A":
                    raise ValueError("DEMO 판매자만 검사 보고서 제출을 준비할 수 있어요.")
                jid = str(args.get("job_id", "")).strip()
                if jid in ("최근", "latest", "마지막"):
                    jid = str(self.context.get("last_job_id") or "")
                if not re.fullmatch(r"[0-9a-fA-F-]{36}", jid):
                    raise ValueError("정적 ZIP 검사 작업 UUID를 알려줘.")
                job = self.request("GET", "/api/agent/v1/jobs/" + quote(jid))
                if job["task_type"] != "INSPECT_ZIP" or job["status"] != "PARTIAL":
                    raise ValueError("제출할 수 있는 ZIP 정적 검사 결과가 아니에요.")
                pending = {"kind": "publish_report", "job_id": jid, "listing_id": job["listing_id"],
                           "actor": self.actor_name, "token": uuid.uuid4().hex}
                data = {"job_id": jid, "verdict": (job.get("result") or {}).get("verdict", "UNVERIFIED")}
                summary = "ZIP 정적 검사 보고서를 플랫폼 검토 대기로 제출할 준비가 됐어요. 직접 제출을 확인해줘."
            elif name == "prepare_handover_check":
                if AGENT_MODE != "mock" or self.actor_name != "판매자 A":
                    raise ValueError("DEMO 판매자만 인수인계 제출 항목을 등록할 수 있어요.")
                txid = str(args.get("transaction_id", "")).strip()
                if txid in ("최근", "latest", "마지막"):
                    txid = str(self.context.get("last_transaction_id") or "")
                key_name = str(args.get("check_key", ""))
                result_name = str(args.get("result", ""))
                if not re.fullmatch(r"[0-9a-fA-F-]{36}", txid):
                    raise ValueError("거래 UUID를 입력해줘.")
                if key_name not in ("source_manifest", "run_in_new_environment", "external_accounts", "ip_rights_review"):
                    raise ValueError("지원하지 않는 인수인계 점검 항목입니다.")
                if result_name not in ("NOT_TESTED", "NEEDS_FIX", "SELLER_SUBMITTED"):
                    raise ValueError("판매자가 구매자 확인 완료/검증 통과를 임의로 기록할 수는 없어요.")
                remarks = str(args.get("remarks", ""))[:700]
                # Access check: the seller must be a party to this transaction.
                self.request("GET", "/api/agent/v1/transactions/" + quote(txid) + "/handover-checks")
                pending = {"kind": "handover_check", "transaction_id": txid, "check_key": key_name,
                           "result": result_name, "remarks": remarks, "actor": self.actor_name, "token": uuid.uuid4().hex}
                data = {"transaction_id": txid, "check_key": key_name, "result": result_name, "remarks": remarks}
                summary = "인수인계 항목을 준비했어요. 실제 등록 전 내용을 확인해줘."
            elif name == "get_handover":
                txid = str(args.get("transaction_id", "")).strip()
                if txid in ("최근", "latest", "마지막"):
                    txid = str(self.context.get("last_transaction_id") or "")
                if not re.fullmatch(r"[0-9a-fA-F-]{36}", txid):
                    raise ValueError("거래 ID(UUID)를 알려줘.")
                checks = self.request("GET", "/api/agent/v1/transactions/" + quote(txid) + "/handover-checks")
                data = {"transaction_id": txid, "checks": checks["items"][:30]}
                summary = "인수인계 확인 항목 {}건을 가져왔어요.".format(len(data["checks"]))
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


def perform_confirmed_action(actor: str, pending: dict, button: str) -> tuple[str, dict | None]:
    """Only invoked by Streamlit button clicks, never called from model tool dispatch.

    Each state transition re-checks actor and marketplace policy inside runtime.
    """
    if AGENT_MODE != "mock" or pending.get("actor") != actor:
        raise ValueError("이 계정에서 실행할 수 없는 요청입니다.")
    runtime = AgentRuntime(actor)
    nonce = pending.get("token")
    if not nonce or not isinstance(nonce, str):
        raise ValueError("승인 세션이 유효하지 않습니다.")
    kind = pending.get("kind")
    if kind == "offer_draft" and button == "create":
        path = "/api/agent/v1/negotiations/draft"
        payload = {"listing_id": pending["listing_id"], "offered_price_krw": int(pending["price_krw"]),
                   "message": pending["message"], "repair_requests": []}
        result = runtime.request("POST", path, payload, None, True, write_key(actor, path, payload, nonce))
        return "DEMO 제안 초안이 생성됐어요. 이제 원문을 검토하고 승인해야 해요.", {
            "kind": "review_action", "action_id": result["id"], "actor": actor, "token": uuid.uuid4().hex}
    if kind == "counter_draft" and button == "create":
        path = "/api/agent/v1/negotiations/counter-draft"
        payload = {"offer_id": pending["offer_id"], "offered_price_krw": int(pending["price_krw"]),
                   "message": pending["message"]}
        result = runtime.request("POST", path, payload, None, True, write_key(actor, path, payload, nonce))
        return "DEMO 역제안 초안이 생성됐어요. 내용을 승인한 뒤 전송할 수 있어요.", {
            "kind": "review_action", "action_id": result["id"], "actor": actor, "token": uuid.uuid4().hex}
    if kind == "review_action" and button in {"approve", "reject", "execute"}:
        action_id = pending["action_id"]
        action = runtime.request("GET", "/api/agent/v1/negotiations/actions/" + action_id)
        allowed = {"approve": "PENDING_APPROVAL", "reject": "PENDING_APPROVAL", "execute": "APPROVED"}
        if action["status"] != allowed[button]:
            raise ValueError("초안 상태가 변경됐어요. 현재 상태를 다시 확인해줘.")
        path = "/api/agent/v1/negotiations/actions/" + action_id + "/" + button
        result = runtime.request("POST", path, None, None, True, write_key(actor, path, {}, nonce))
        if button == "approve":
            return "초안을 승인했어요. 아직 제안이 전송되지는 않았어요.", pending
        if button == "reject":
            return "초안을 거절했어요. 상대방에게 전송되지 않았어요.", None
        return "DEMO 플랫폼에 제안을 전송했어요. 제안 ID: " + str(result.get("created_offer_id", "미확인")), None
    if kind == "publish_report" and button == "publish":
        jid = pending["job_id"]
        path = "/api/agent/v1/jobs/" + jid + "/publish"
        result = runtime.request("POST", path, None, None, True, write_key(actor, path, {}, nonce))
        return "DEMO 검토 대기로 보고서를 제출했어요. 상태: " + result["review_status"], None
    if kind == "handover_check" and button == "record":
        txid = pending["transaction_id"]
        path = "/api/agent/v1/transactions/" + txid + "/handover-checks"
        payload = {"check_key": pending["check_key"], "description": pending["check_key"],
                   "result": pending["result"], "remarks": pending["remarks"], "evidence_refs": []}
        result = runtime.request("POST", path, payload, None, True, write_key(actor, path, payload, nonce))
        return "DEMO 인수인계 항목이 기록됐어요. 구매자 최종 확인과는 별개예요.", None
    if kind == "accept_offer" and button == "accept":
        oid = pending["offer_id"]
        path = "/api/agent/v1/offers/" + oid + "/accept"
        payload = {"expected_version": pending["version"]}
        result = runtime.request("POST", path, payload, None, True, write_key(actor, path, payload, nonce))
        return "DEMO 거래가 생성됐어요. 인수인계 ID: " + result["id"], None
    raise ValueError("지원하지 않는 승인 요청입니다.")
