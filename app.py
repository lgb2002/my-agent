# -*- coding: utf-8 -*-
"""디지털 자산 거래 AI 에이전트 | Chat-first Streamlit app (one process, Python 3.12)."""
import json
import hashlib
import uuid
import re
from html import escape
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env", override=False)
# Bridge Streamlit Cloud top-level TOML Secrets before core.config is imported.
# Never render, log or expose secret values.
from core.runtime_secrets import configure_from_secrets, ai_activation_reason
try:
    configure_from_secrets(st.secrets)
except Exception:
    # Local installation without .streamlit/secrets.toml.
    pass

from agent.chat import ChatAgent  # noqa: E402
from agent.core import AgentError, AgentRuntime  # noqa: E402
from agent.tools import TOOL_LABELS, perform_confirmed_action  # noqa: E402
from core.config import AGENT_MODE, ENABLE_OPENAI_CHAT, OPENAI_API_KEY, OPENAI_MODEL, SHOW_DEVELOPER_TOOLS, marketplace_config_error  # noqa: E402
from core.request_context import set_request_context  # noqa: E402
from core.llm_service import contains_obvious_secret  # noqa: E402
from core.config import MARKETPLACE_BASE_URL  # noqa: E402
from core.live_diagnostics import run_diagnostics  # noqa: E402
from core.chat_sessions import conversation_scope, get_or_migrate_session, append_turn  # noqa: E402

st.set_page_config(page_title="ProjectAgain · 프로젝트 에이전트", page_icon="🧭", layout="wide", initial_sidebar_state="expanded")
st.markdown("<style>" + (ROOT / "assets" / "style.css").read_text(encoding="utf-8") + "</style>", unsafe_allow_html=True)


def get_session(scope, legacy_scopes=()):
    all_sessions = st.session_state.setdefault("chat_sessions_v06", {})
    return get_or_migrate_session(all_sessions, scope, legacy_scopes)


def add_turn(session, role, content, **kwargs):
    append_turn(session, role, content, **kwargs)


def show_event(event, idx, turn_id):
    label = str(event.get("label") or event.get("name") or "도구")
    status = "완료" if event.get("success") else "확인 필요"
    with st.expander("{}  ·  {}  ·  결과 상세".format(label, status), expanded=False):
        st.caption(str(event.get("summary") or ""))
        data = event.get("data") or {}
        if data:
            st.json(data, expanded=False)


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
      <div class="approval-kicker">사용자 확인 필요 · DEMO</div>
      <div class="approval-title">거래 요청을 확인해 주세요</div>
      <p class="approval-desc">대화만으로 거래가 진행되지 않습니다. 아래 내용을 직접 확인한 뒤 진행해 주세요.</p>
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
        add_turn(session, "assistant", "**요청 처리 완료** · " + message)
        st.rerun()
    except (AgentError, ValueError, KeyError) as exc:
        st.error("확인 단계 처리 실패: " + str(exc)[:350])
    except Exception:
        st.error("확인 단계 처리 중 오류가 발생했어요. 상태를 다시 조회해줘.")


# ── Sidebar: a short path to listings and optional account connection. ──
visitor = st.session_state.setdefault("visitor_uuid_v06", uuid.uuid4().hex)
with st.sidebar:
    st.markdown('<div class="brand"><span class="brand-symbol">◈</span><span>ProjectAgain</span></div>',
                unsafe_allow_html=True)

    if AGENT_MODE == "mock":
        actor = st.selectbox("체험할 역할", ["구매자 B", "판매자 A"])
        token = ""
        show_demo = True
        st.caption("샌드박스 환경")
    else:
        actor = "ProjectAgain 사용자"
        st.markdown('<div class="sidebar-heading">매물 보기</div>', unsafe_allow_html=True)
        # First visit defaults to including demo listings, but each visitor
        # can turn the filter off. New widget key avoids sticky old defaults.
        show_demo = st.checkbox("시연 매물 포함", value=True, key="include_demo_v10")
        with st.expander("내 계정 연결", expanded=False):
            token = st.text_input(
                "위임 토큰", type="password", key="user_grant_v06",
                placeholder="12시간 위임 토큰",
                help="개인 구매 조건이나 제안 내역 조회 시에만 필요합니다. 공개 매물은 토큰 없이 조회할 수 있어요.",
            )
            if token and st.button("연결 해제", key="disconnect_grant_v10", width="stretch"):
                st.session_state["user_grant_v06"] = ""
                st.rerun()
        st.caption("계정 연결됨" if token else "공개 매물 조회 가능")

    # Shared Cloud Secrets grant must never be attached to public visitors.
    set_request_context(token=token, visitor_id=visitor, include_demo=show_demo)
    owner_scope = hashlib.sha256(token.encode("utf-8")).hexdigest()[:12] if token else visitor
    scope = conversation_scope(AGENT_MODE, actor, owner_scope if AGENT_MODE == 'live' else 'demo')
    # Before v0.10, demo-filter switches created separate chat scopes.
    old_scopes = [scope + '::' + str(show_demo), scope + '::' + str(not show_demo)]
    current = get_session(scope, old_scopes)
    # A search filter change must not erase the chat, but old search ordinals
    # must not accidentally point to a listing excluded by the new filter.
    previous_filter = current.get("_include_demo_filter")
    if previous_filter is not None and previous_filter != show_demo:
        for context_key in ("recent_listings", "listing_next_cursor", "last_search_query"):
            current["context"].pop(context_key, None)
    current["_include_demo_filter"] = show_demo
    if st.button("＋ 새 대화", type="primary", width="stretch"):
        st.session_state["chat_sessions_v06"][scope] = {"turns": [], "context": {"recent_listings": []}, "pending": None}
        st.rerun()

    if AGENT_MODE == "mock" and actor == "판매자 A":
        with st.expander("ZIP 검사 파일", expanded=False):
            uploaded = st.file_uploader("검사할 ZIP", type=["zip"], help="4MB 이하 · 압축 파일을 실행하지 않고 검사합니다.")
    else:
        uploaded = None

    # Debug tools remain available for maintainers, but ordinary visitors
    # don't need server diagnostics, raw model metadata or admin panels.
    if SHOW_DEVELOPER_TOOLS:
        st.markdown('<div class="side-divider"></div><div class="sidebar-heading">운영 진단</div>', unsafe_allow_html=True)
        with st.expander("사용 가능한 도구", expanded=False):
            for tool, label in TOOL_LABELS.items():
                if AGENT_MODE == "live" and (tool.startswith("prepare_") or tool == "inspect_attached_zip"):
                    continue
                st.caption("· " + label)
        with st.expander("최근 작업", expanded=False):
            try:
                jobs = AgentRuntime(actor).request("GET", "/api/agent/v1/jobs").get("items", [])[:5]
                if not jobs:
                    st.caption("아직 작업 기록이 없습니다.")
                for job in jobs:
                    st.caption("{} · {}".format(job.get("task_type", "작업"), job.get("status", "미확인")))
            except Exception:
                st.caption("작업 기록 연결 대기 중")
        if current["turns"]:
            st.download_button("대화 기록 저장", json.dumps(current["turns"], ensure_ascii=False, indent=2),
                               file_name="projectagain_conversation.json", mime="application/json", width="stretch")
        if AGENT_MODE == "live":
            with st.expander("API 연결 진단", expanded=False):
                if st.button("연결 상태 검사", key="diagnose_marketplace_v08", width="stretch"):
                    config_error = marketplace_config_error()
                    if config_error:
                        st.session_state["live_diagnostics_v08"] = {"configuration_error": config_error}
                    else:
                        with st.spinner("연결 상태 확인 중..."):
                            st.session_state["live_diagnostics_v08"] = run_diagnostics(
                                MARKETPLACE_BASE_URL, token=token, include_demo=show_demo)
                report = st.session_state.get("live_diagnostics_v08")
                if report:
                    if "configuration_error" in report:
                        st.error(report["configuration_error"])
                    else:
                        for title, key in (("공개 매물", "public"), ("시연 포함", "with_demo"),
                                           ("사용자 인증", "delegation")):
                            entry = report[key]
                            status = entry.get("http_status")
                            count = " · {}건".format(entry["count"]) if entry.get("count") is not None else ""
                            st.caption("{} · HTTP {}{} · {}".format(title, status if status is not None else "미확인", count, entry["detail"]))
                        st.info(report["interpretation"])
        with st.expander("OpenAI 상태", expanded=False):
            st.caption(ai_activation_reason(bool(OPENAI_API_KEY), ENABLE_OPENAI_CHAT))
            st.caption("모델: " + (OPENAI_MODEL if ENABLE_OPENAI_CHAT and OPENAI_API_KEY else "비활성"))

# ── Main: minimal conversation-first interface. ────────────────────
online = ENABLE_OPENAI_CHAT and bool(OPENAI_API_KEY)
connection_error = marketplace_config_error()
mode_title = "샌드박스" if AGENT_MODE == "mock" else ("플랫폼 설정 필요" if connection_error else "플랫폼 조회 · 읽기 전용")
st.markdown('''<div class="workspace-bar"><div class="workspace-name">프로젝트 에이전트</div>
<div class="workspace-meta"><span class="status-dot"></span>{}</div></div>'''.format(escape(mode_title)), unsafe_allow_html=True)

session = current
pending_prompt = None
if not session["turns"]:
    # The empty chat state is the product's primary entry point: one clear question,
    # followed by four real tool-entry actions. Keep business logic below unchanged.
    st.markdown('''<section class="welcome" aria-labelledby="welcome-title">
        <div class="welcome-eyebrow"><span class="welcome-rule" aria-hidden="true"></span>PROJECTAGAIN / AI DESK</div>
        <h1 class="welcome-title" id="welcome-title">어떤 프로젝트를<br>찾고 계신가요?</h1>
        <p class="welcome-description">예산이나 개발 기술, 원하는 운영 방식을 알려주세요. <br class="desktop-break">
        매물을 찾고 검토할 내용을 대화 안에서 정리해 드립니다.</p>
        </section>''', unsafe_allow_html=True)
    examples = [
        ("01", "매물 둘러보기", "등록된 프로젝트부터 살펴보기", "현재 등록된 매물 목록 보여줘"),
        ("02", "맞춤 추천 받기", "필요한 조건을 물어보고 적합한 후보 선별", "나에게 맞는 프로젝트 추천해줘"),
        ("03", "실사 준비하기", "검토할 매물을 먼저 선택하기", "현재 등록된 매물 목록 보여줘"),
        ("04", "작업 내역 확인", "이전에 진행한 작업 다시 보기", "최근 작업 기록 보여줘"),
    ]
    with st.container(key="welcome_actions"):
        st.markdown('''<div class="welcome-actions-heading">
           <span class="welcome-actions-title">이런 요청부터 시작해 보세요</span>
           <span class="welcome-actions-count">QUICK START / 04</span>
           </div>''', unsafe_allow_html=True)
        # Use one pair of columns per row. Mobile stacking keeps the reading
        # and keyboard order 01 -> 02 -> 03 -> 04, including screen readers.
        for start in (0, 2):
            columns = st.columns(2, gap="large")
            for offset, column in enumerate(columns):
                index = start + offset
                number, title, hint, prompt = examples[index]
                with column:
                    st.markdown('<div class="suggestion-index">{}</div>'.format(number), unsafe_allow_html=True)
                    if st.button(title, width="stretch", key="welcome_" + str(index)):
                        pending_prompt = prompt
                    st.markdown('<p class="suggestion-hint">{}</p>'.format(escape(hint)), unsafe_allow_html=True)

if AGENT_MODE == 'live':
    if connection_error:
        st.warning(connection_error)
# Diagnostics stay off the primary conversational surface.
# Keep a dedicated scroll area so the first message is reachable on long chats.
if session["turns"]:
    with st.container(height=540, border=False, key="chat_history_v10"):
        st.markdown('<div id="chat-history-start" class="history-start-label">대화 기록</div>', unsafe_allow_html=True)
        for i, turn in enumerate(session["turns"]):
            show_turn(turn, i)
        if session.get("pending"):
            pending_ui(session, actor)
elif session.get("pending"):
    pending_ui(session, actor)

submitted_text = st.chat_input("예: 50만원 이하 Python 프로젝트 추천해줘", max_chars=2000)
submitted = submitted_text or pending_prompt
if submitted:
    if len(submitted) > 2000:
        st.error("메시지는 2000자 이내로 입력해 주세요.")
    elif contains_obvious_secret(submitted):
        add_turn(session, "assistant", "비밀정보로 보이는 입력은 처리하지 않았습니다. 민감한 정보를 제외하고 다시 요청해 주세요.")
        st.rerun()
    else:
        history = list(session["turns"])
        add_turn(session, "user", submitted)
        context = session["context"]
        try:
            if uploaded is not None:
                if uploaded.size > 4 * 1024 * 1024:
                    st.error("ZIP 파일은 4MB 이하여야 해요.")
                else:
                    context["attachment_bytes"] = uploaded.getvalue()
            with st.spinner("도구를 실행하고 결과를 정리하는 중..."):
                result = ChatAgent(actor).reply(submitted, history, context)
        except Exception:
            result = {"content": "요청을 처리하는 동안 오류가 발생했습니다. 연결 상태를 확인한 뒤 다시 시도해 주세요.",
                      "events": [], "pending": None, "mode": "runtime_error"}
        finally:
            context.pop("attachment_bytes", None)
        if result.get("pending") and session.get("pending"):
            add_turn(session, "assistant", result["content"] + "\n\n이전 승인 요청이 남아 있어 새로운 승인 건은 보류했습니다.",
                     events=result.get("events", []), mode=result.get("mode"))
        else:
            add_turn(session, "assistant", result["content"], events=result.get("events", []), mode=result.get("mode"))
            if result.get("pending"):
                session["pending"] = result["pending"]
        st.rerun()

st.markdown('<p class="footer-note">추천과 분석은 참고 자료이며 실제 거래와 자산 이전을 실행하지 않습니다.</p>', unsafe_allow_html=True)
