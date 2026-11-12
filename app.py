# -*- coding: utf-8 -*-
"""국비 AI 에이전트 | Chat-first Streamlit app (one process, Python 3.12)."""
import json
import re
from html import escape
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env", override=False)

from agent.chat import ChatAgent  # noqa: E402
from agent.core import AgentError, AgentRuntime  # noqa: E402
from agent.tools import TOOL_LABELS, perform_confirmed_action  # noqa: E402
from core.config import AGENT_MODE, ENABLE_OPENAI_CHAT, OPENAI_API_KEY, OPENAI_MODEL  # noqa: E402
from core.llm_service import contains_obvious_secret  # noqa: E402

st.set_page_config(page_title="Asset Agent | 대화형 거래 에이전트", page_icon="🧭", layout="centered", initial_sidebar_state="expanded")
st.markdown("<style>" + (ROOT / "assets" / "style.css").read_text(encoding="utf-8") + "</style>", unsafe_allow_html=True)


def get_session(scope):
    all_sessions = st.session_state.setdefault("chat_sessions_v4", {})
    if scope not in all_sessions:
        all_sessions[scope] = {"turns": [], "context": {"recent_listings": []}, "pending": None}
    return all_sessions[scope]


def add_turn(session, role, content, **kwargs):
    session["turns"].append({"role": role, "content": content, **kwargs})
    # Keep the UI responsive, and avoid oversized LLM-context history.
    session["turns"] = session["turns"][-80:]


def show_event(event, idx, turn_id):
    prefix = "✓" if event.get("success") else "!"
    label = escape(event.get("label", event.get("name", "툴")))
    st.markdown('<span class="workflow-tag{}">{} · {}</span>'.format(
        "" if event.get("success") else " danger", prefix, label), unsafe_allow_html=True)
    with st.expander("{} · 실행 결과 확인".format(label), expanded=False):
        st.caption(event.get("summary", ""))
        data = event.get("data") or {}
        if data:
            st.json(data, expanded=False)
        jid = data.get("job_id")
        if jid:
            st.caption("작업 ID: " + jid)


def show_turn(turn, idx):
    is_user = turn["role"] == "user"
    with st.chat_message("user" if is_user else "assistant", avatar="👤" if is_user else "🧭"):
        st.markdown(turn["content"])
        for no, event in enumerate(turn.get("events") or []):
            show_event(event, no, idx)


def pending_ui(session, actor_name):
    pending = session.get("pending")
    if not pending:
        return
    if pending.get("actor") != actor_name:
        session["pending"] = None
        return
    st.markdown('''<div class="approval-panel">
      <div class="approval-kicker">Human in control / 승인 대기</div>
      <div class="approval-title">실행 전에 내용을 확인해 주세요</div>
      <p class="approval-desc">AI는 아래 단계를 자동으로 승인하거나 전송하지 못합니다. DEMO 환경에서만 사용 가능해요.</p>
      </div>''', unsafe_allow_html=True)
    kind = pending["kind"]
    if kind in ("offer_draft", "counter_draft"):
        st.markdown("**{} · {:,}원**".format(
            escape(pending.get("listing_title", "기존 제안 " + pending.get("offer_id", "")[:8])), pending["price_krw"]))
        st.write(pending.get("message", ""))
        st.caption("1단계: DEMO 초안 생성 · 아직 제안 전송 아님")
        col_a, col_b = st.columns([1, 1])
        create = col_a.button("초안 생성", type="primary", width="stretch", key="approve_create_" + pending["token"])
        cancel = col_b.button("취소", width="stretch", key="approve_cancel_" + pending["token"])
        if create:
            confirmed(session, actor_name, "create")
        if cancel:
            session["pending"] = None
            add_turn(session, "assistant", "요청을 취소했어요. 플랫폼에 전송된 내용은 없어요.")
            st.rerun()
    elif kind == "review_action":
        try:
            action = AgentRuntime(actor_name).request("GET", "/api/agent/v1/negotiations/actions/" + pending["action_id"])
            st.markdown("**초안 종류:** {}   ·   **상태:** {}".format(action["action_type"], action["status"]))
            with st.expander("승인할 정확한 내용과 SHA-256 보기", expanded=True):
                st.json(action["proposed_payload"])
                st.caption("SHA-256 · " + action["payload_sha256"])
            if action["status"] == "PENDING_APPROVAL":
                a, b = st.columns(2)
                if a.button("내용 승인", type="primary", width="stretch", key="review_yes_" + pending["token"]):
                    confirmed(session, actor_name, "approve")
                if b.button("초안 거절", width="stretch", key="review_no_" + pending["token"]):
                    confirmed(session, actor_name, "reject")
            elif action["status"] == "APPROVED":
                checked = st.checkbox("DEMO 플랫폼에 해당 초안이 전송되는 것에 동의해요.", key="execute_check_" + pending["token"])
                if st.button("승인된 DEMO 제안 전송", type="primary", disabled=not checked,
                             width="stretch", key="execute_" + pending["token"]):
                    confirmed(session, actor_name, "execute")
            else:
                st.info("현재 상태: {}. 더 이상 실행할 단계가 없어요.".format(action["status"]))
                if st.button("승인 카드 닫기", key="close_review_" + pending["token"]):
                    session["pending"] = None
                    st.rerun()
        except AgentError:
            st.error("이 초안을 조회할 수 없어요. 본인 계정과 상태를 확인해줘.")
    elif kind == "publish_report":
        st.markdown("**ZIP 정적 검사 보고서 제출** · 작업 ID `{}`".format(pending["job_id"]))
        st.caption("DEMO 플랫폼의 검토 대기 상태로 등록됩니다. 검증 통과를 의미하지 않아요.")
        a, b = st.columns(2)
        if a.button("DEMO 보고서 제출", type="primary", width="stretch", key="publish_" + pending["token"]):
            confirmed(session, actor_name, "publish")
        if b.button("취소", width="stretch", key="publish_cancel_" + pending["token"]):
            session["pending"] = None
            st.rerun()
    elif kind == "handover_check":
        st.markdown("**인수인계 기록** · {} / {}".format(pending["check_key"], pending["result"]))
        st.write(pending.get("remarks") or "비고 없음")
        st.caption("기록은 판매자 제출 상태일 뿐, 구매자 인수 확인은 아닙니다.")
        a, b = st.columns(2)
        if a.button("DEMO 항목 기록", type="primary", width="stretch", key="handover_" + pending["token"]):
            confirmed(session, actor_name, "record")
        if b.button("취소", width="stretch", key="handover_cancel_" + pending["token"]):
            session["pending"] = None
            st.rerun()
    elif kind == "accept_offer":
        st.markdown("**판매자 역제안 수락 · {:,}원**".format(pending["price_krw"]))
        st.caption("수락하면 가상 거래 상태가 만들어지며, 실제 결제나 계약은 진행하지 않아요.")
        checked = st.checkbox("수락 금액과 DEMO 거래 생성에 동의해요.", key="accept_check_" + pending["token"])
        a, b = st.columns(2)
        if a.button("DEMO 역제안 수락", type="primary", disabled=not checked, width="stretch",
                    key="accept_" + pending["token"]):
            confirmed(session, actor_name, "accept")
        if b.button("취소", width="stretch", key="accept_cancel_" + pending["token"]):
            session["pending"] = None
            st.rerun()


def confirmed(session, actor, operation):
    # This is ONLY wired to physical Streamlit buttons, never to ChatAgent.
    try:
        message, next_pending = perform_confirmed_action(actor, session["pending"], operation)
        session["pending"] = next_pending
        if operation == "accept":
            found = re.search(r"[0-9a-fA-F-]{36}", message)
            if found:
                session["context"]["last_transaction_id"] = found.group(0)
        add_turn(session, "assistant", "**사용자 확인 완료** · " + message)
        st.rerun()
    except (AgentError, ValueError, KeyError) as exc:
        st.error("확인 단계 처리 실패: " + str(exc)[:350])
    except Exception:
        st.error("확인 단계 처리 중 오류가 발생했어요. 상태를 다시 조회해줘.")


# ── Sidebar: utility controls, not the main navigation. ──────────────
with st.sidebar:
    st.markdown('<div class="side-brand"><span class="mark">◈</span> asset agent</div>'
                '<div class="side-caption">DIGITAL PROJECT DESK</div>', unsafe_allow_html=True)
    st.markdown('<div class="side-section">WORKSPACE</div>', unsafe_allow_html=True)
    if AGENT_MODE == "mock":
        actor = st.selectbox("시연 역할", ["구매자 B", "판매자 A"], label_visibility="collapsed")
    else:
        actor = "Replit 연결 계정"
        st.caption("Replit 실플랫폼 · 조회 전용")
    scope = AGENT_MODE + "::" + actor
    current = get_session(scope)
    if st.button("＋ 새 대화", width="stretch"):
        st.session_state["chat_sessions_v4"][scope] = {"turns": [], "context": {"recent_listings": []}, "pending": None}
        st.rerun()
    st.markdown('<div class="side-section">CONNECTION</div>', unsafe_allow_html=True)
    if ENABLE_OPENAI_CHAT and OPENAI_API_KEY:
        st.markdown('<div class="side-small">● OpenAI Tool Calling 활성 · 모델: {}</div>'.format(escape(OPENAI_MODEL)), unsafe_allow_html=True)
    else:
        st.markdown('<div class="side-small">● 로컬 도구 체험 · OpenAI 비활성</div>', unsafe_allow_html=True)
    st.markdown('<div class="side-small">● {} · {} 모드</div>'.format(
        "내장 DEMO" if AGENT_MODE == "mock" else "Replit HTTPS", escape(AGENT_MODE)), unsafe_allow_html=True)
    st.markdown('<div class="side-section">AVAILABLE TOOLS</div>', unsafe_allow_html=True)
    with st.expander("연결된 {}개 도구".format(len(TOOL_LABELS))):
        for label in TOOL_LABELS.values():
            st.caption("· " + label)
        st.caption("협상 변경은 채팅 이후 별도 사용자 승인이 필요합니다.")
    if AGENT_MODE == "mock" and actor == "판매자 A":
        st.markdown('<div class="side-section">SOURCE ARCHIVE</div>', unsafe_allow_html=True)
        uploaded = st.file_uploader("정적 검사할 ZIP 첨부", type=["zip"], help="최대 4MB · 압축해제/실행하지 않음")
        if uploaded:
            st.caption("선택됨: " + uploaded.name[:70])
    else:
        uploaded = None
    st.markdown('<div class="side-section">RECENT WORK</div>', unsafe_allow_html=True)
    try:
        jobs = AgentRuntime(actor).request("GET", "/api/agent/v1/jobs").get("items", [])[:4]
        for job in jobs:
            st.caption("{} · {} · {}".format(job["task_type"], job["status"], job["id"][:8]))
        if not jobs:
            st.caption("아직 저장된 작업이 없습니다.")
    except Exception:
        st.caption("작업 기록 연결 대기 중")
    st.markdown("---")
    if current["turns"]:
        st.download_button("대화 기록 JSON", json.dumps(current["turns"], ensure_ascii=False, indent=2),
                           file_name="asset_agent_conversation.json", mime="application/json", width="stretch")
    st.markdown('<div class="side-small">이 프로젝트는 실제 결제·계약·자산 이전을 수행하지 않습니다.</div>', unsafe_allow_html=True)

# ── Main: conversation is the product. ──────────────────────────────
online = ENABLE_OPENAI_CHAT and bool(OPENAI_API_KEY)
status = "AI 자동 도구 선택" if online else "로컬 시연 도구"
mode_title = "DEMO 데이터" if AGENT_MODE == "mock" else "플랫폼 조회 전용"
st.markdown('''<div class="main-head">
  <div class="main-kicker">WORKSPACE / CONVERSATION 01</div>
  <div class="main-title">대화로 프로젝트를<br>탐색하고, 검증하고, 협상하세요.</div>
  <p class="main-desc">원하는 조건을 말하면 에이전트가 연결된 도구를 사용해 결과를 가져옵니다.
    거래에 영향을 주는 행동은 반드시 직접 확인한 후 진행합니다.</p>
  <div class="main-meta"><span class="main-chip"><span class="dot"></span>{}</span>
  <span class="main-chip"><span class="dot"></span>{}</span>
  <span class="main-chip warn"><span class="dot"></span>실거래 차단</span></div>
 </div>'''.format(escape(status), escape(mode_title)), unsafe_allow_html=True)

if AGENT_MODE != "mock":
    st.info("Replit 실플랫폼 연결은 조회만 지원해요. 인증 키 방식과 권한이 확정되기 전에는 거래 변경이 차단돼요.")
if not online:
    st.caption("현재는 API 비용 없는 규칙형 체험 모드예요. OpenAI를 활성화하면 대화 맥락에 맞춰 도구를 자동 선택합니다.")

session = current
pending_prompt = None
if not session["turns"]:
    st.markdown('''<div class="empty-wrap"><div class="empty-kicker">START A TASK</div>
      <div class="empty-title">무엇부터 진행할까요?</div>
      <p class="empty-desc">직접 도구를 찾을 필요 없어요. 아래 예시를 선택하거나 자유롭게 요청해 보세요.</p></div>''', unsafe_allow_html=True)
    examples = [
        ("매물 둘러보기", "현재 등록된 매물 목록 보여줘"),
        ("예산 맞춤 추천", "100만원 이하 Python 프로젝트 추천해줘"),
        ("실사 결과 확인", "매물 목록 보여줘"),
        ("현재 작업 기록", "최근 작업 기록 보여줘"),
    ]
    cols = st.columns(2, gap="small")
    for i, (label, prompt) in enumerate(examples):
        with cols[i % 2]:
            if st.button("↗  " + label, width="stretch", key="start_" + str(i)):
                pending_prompt = prompt

for i, turn in enumerate(session["turns"]):
    show_turn(turn, i)

if session.get("pending"):
    pending_ui(session, actor)

text = st.chat_input("예: 100만원 이하 프로젝트 추천해줘", max_chars=2000)
submitted = text or pending_prompt
if submitted:
    if len(submitted) > 2000:
        st.error("메시지는 최대 2000자까지 입력할 수 있어요.")
    else:
        if contains_obvious_secret(submitted):
            add_turn(session, "user", "[비밀정보로 판단된 입력을 차단했어요]")
            add_turn(session, "assistant", "API 키나 토큰으로 보이는 내용은 대화 기록과 OpenAI에 저장·전송하지 않도록 차단했어요. 비밀정보를 삭제하고 다시 입력해줘.")
            st.rerun()
        history = list(session["turns"])
        add_turn(session, "user", submitted)
        context = session["context"]
        if uploaded is not None:
            # Only the local static inspector sees bytes; never include attachment bytes in LLM context.
            if uploaded.size > 4 * 1024 * 1024:
                st.error("첨부 ZIP은 4MB 이하여야 해요. 더 작은 파일을 첨부해줘.")
            else:
                context["attachment_bytes"] = uploaded.getvalue()
        with st.spinner("연결된 도구를 확인하고 있어요..."):
            result = ChatAgent(actor).reply(submitted, history, context)
        context.pop("attachment_bytes", None)
        if result.get("pending") and session.get("pending"):
            add_turn(session, "assistant", result["content"] + "\n\n⚠️ 이전 승인 대기 건이 있어 새로운 승인 요청은 보류했어요. 먼저 처리하거나 취소해줘.",
                     events=result.get("events", []), mode=result.get("mode"))
        else:
            add_turn(session, "assistant", result["content"], events=result.get("events", []), mode=result.get("mode"))
            if result.get("pending"):
                session["pending"] = result["pending"]
        st.rerun()

st.markdown('<div class="tiny-footer">Digital Asset Agent · 근거가 없는 내용은 검증되지 않은 것으로 표시합니다.<br>'
            'DEMO 거래만 지원 · 개인정보 및 API 키는 채팅에 입력하지 마세요.</div>', unsafe_allow_html=True)
