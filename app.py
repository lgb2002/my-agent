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
from agent.tools import TOOL_LABELS  # noqa: E402
from core.config import ENABLE_OPENAI_CHAT, OPENAI_API_KEY, OPENAI_MODEL, SHOW_DEVELOPER_TOOLS, marketplace_config_error  # noqa: E402
from core.request_context import set_request_context  # noqa: E402
from core.ai_usage import set_ai_identity, usage_snapshot, storage_kind as ai_usage_storage_kind  # noqa: E402
from core.llm_service import contains_obvious_secret  # noqa: E402
from core.config import MARKETPLACE_BASE_URL  # noqa: E402
from core.live_diagnostics import run_diagnostics  # noqa: E402
from core.chat_sessions import conversation_scope, get_or_migrate_session, append_turn  # noqa: E402
from core.workflow_store import (verified_owner, save_preferences, load_preferences,
    delete_preferences, list_workflows, load_workflow, delete_workflow, storage_kind, storage_health)  # noqa: E402
from agent.workflow import workflow_outline, verify_plan, _checkpoint  # noqa: E402

st.set_page_config(page_title="ProjectAgain · 프로젝트 에이전트", page_icon="🧭", layout="wide", initial_sidebar_state="expanded")
st.markdown("<style>" + (ROOT / "assets" / "style.css").read_text(encoding="utf-8") + "</style>", unsafe_allow_html=True)


def get_session(scope, legacy_scopes=()):
    all_sessions = st.session_state.setdefault("chat_sessions_v06", {})
    return get_or_migrate_session(all_sessions, scope, legacy_scopes)


def add_turn(session, role, content, **kwargs):
    append_turn(session, role, content, **kwargs)


def show_recommendation_snapshot(data, idx, turn_id):
    rows = data.get('ranked') or []
    if not isinstance(rows,list):
        return
    if not rows:
        reasons = data.get('excluded_reasons') or []
        st.info('확인 가능한 적합 매물이 없어. 조건을 자동으로 완화하지 않았어.')
        if reasons:
            st.caption('주요 이유 · ' + ' / '.join(str(x)[:65] for x in reasons[:2]))
        return
    st.caption('추천 후보 · {}건 / 적격 {}건 · 공개 매물 자료 기반'.format(
        len(rows), data.get('eligible_count',len(rows))))
    for n, entry in enumerate(rows[:3],1):
        price = entry.get('price_krw')
        text_price = '{:,}원'.format(price) if type(price) is int else '가격 미확인'
        with st.container(border=True):
            st.markdown('**{}. {}** · {}'.format(n, escape(str(entry.get('title') or '제목 미확인')[:95]), text_price))
            cols = st.columns([1,1])
            with cols[0]:
                base = entry.get('base_score', entry.get('score'))
                adjustment = entry.get('qualitative_adjustment', 0)
                if adjustment:
                    st.caption('적합도 점수 · {} (조건 {} / AI 선호 {:+d})'.format(
                        entry.get('score','미확인'), base, adjustment))
                else:
                    st.caption('조건 적합도 · '+str(base if base is not None else '미확인'))
            with cols[1]:
                st.caption('위험 검토 · '+str(entry.get('risk_label') or '미확인'))
            matches = [a for a in (entry.get('qualitative_assessments') or [])
                       if a.get('verdict') in ('MATCH','MISMATCH')]
            if matches:
                first = matches[0]
                st.caption('AI 선호 비교 · {} · {}'.format(
                    '일치' if first['verdict']=='MATCH' else '불일치',
                    str(first.get('preference',''))[:60]))
                if first.get('evidence_quote'):
                    st.caption('판매자 등록 근거 · '+str(first['evidence_quote'])[:130])
            elif data.get('qualitative_preferences'):
                st.caption('추가 선호는 공개 근거 부족으로 적합도에 반영하지 않았어.')
            if entry.get('reasons'):
                st.write('추천 근거 · '+ str(entry['reasons'][0])[:150])
            if entry.get('risks'):
                st.caption('확인 필요 · '+str(entry['risks'][0])[:150])
            listing_id = str(entry.get('listing_id') or '')
            try:
                uuid.UUID(listing_id)
                safe_listing = True
            except ValueError:
                safe_listing = False
            if safe_listing and st.button('이 매물 공개 정보 검토', key='rec_review_{}_{}_{}'.format(turn_id,idx,n)):
                # Same ordinary chat pipeline as keyboard submission; NEVER auto-write.
                st.session_state['queued_tool_prompt_v015'] = '{} 매물의 공개 정보를 검토해줘'.format(listing_id)
                st.rerun()
            dims = entry.get('risk_dimensions') or []
            if dims:
                with st.expander('위험 항목별 근거',expanded=False):
                    for dim in dims[:7]:
                        st.caption('{} · {} · {}'.format(
                            dim.get('label','항목'),dim.get('status','UNKNOWN'),dim.get('explanation','')))


def show_event(event, idx, turn_id):
    """Keep tool activity visible without displaying raw payloads by default."""
    label = str(event.get("label") or event.get("name") or "도구")
    success = bool(event.get("success"))
    status = "실행 완료" if success else "확인 필요"
    tone = "ok" if success else "problem"
    st.markdown(
        '<div class="tool-activity tool-activity-{}" role="status">'
        '<span class="tool-activity-indicator" aria-hidden="true"></span>'
        '<span class="tool-activity-name">{}</span>'
        '<span class="tool-activity-state">{}</span></div>'.format(
            tone, escape(label), escape(status)), unsafe_allow_html=True)
    if success and event.get('name') in ('recommend_listings', 'compare'):
        show_recommendation_snapshot(event.get('data') or {}, idx, turn_id)
    with st.expander("실행 결과와 근거 보기", expanded=False):
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
      <div class="approval-kicker">사용자 확인 필요 · 플랫폼 거래는 별도 승인</div>
      <div class="approval-title">거래 요청을 확인해 주세요</div>
      <p class="approval-desc">대화만으로 거래가 진행되지 않습니다. 아래 내용을 직접 확인한 뒤 진행해 주세요.</p>
      </div>''', unsafe_allow_html=True)
    kind = pending["kind"]
    if kind in ('live_offer_draft', 'live_action_created', 'live_submission_unknown'):
        st.markdown('**플랫폼 구매 제안 초안** · {} · {:,}원'.format(
            escape(str(pending.get('listing_title') or '매물')), pending.get('price_krw') or 0))
        if kind == 'live_offer_draft':
            st.write(str(pending.get('message') or ''))
            st.caption('여기서는 승인·전송하지 않습니다. 초안 생성 후 ProjectAgain 웹에서 직접 승인하세요.')
            a, b = st.columns(2)
            if a.button('플랫폼에 초안 제출', type='primary', key='live_draft_create_'+pending['token']):
                if pending.get('attempted'):
                    st.error('이미 제출을 시도했어요. 중복 제출을 방지하려면 플랫폼에서 먼저 확인해 주세요.')
                else:
                    pending['attempted'] = True
                    from core.live_actions import submit_confirmed_draft
                    try:
                        action_id = submit_confirmed_draft(pending)
                        pending.update(kind='live_action_created', action_id=action_id)
                        plan = session.get('context',{}).get('workflow')
                        if isinstance(plan, dict) and pending.get('workflow_id') == plan.get('id'):
                            plan['remote_action_id'] = action_id
                            for step in plan.get('steps',[]):
                                if step.get('key') == 'prepare_offer':
                                    step['status'] = 'WAITING_APPROVAL'
                                    step['note'] = 'ProjectAgain 플랫폼에 초안 등록 · 웹 승인/실행 대기'
                            _checkpoint(plan, session['context'])
                        add_turn(session, 'assistant', '플랫폼에 초안을 등록했어. 아직 승인 또는 실행되지 않았어. ProjectAgain 거래 업무실에서 내용을 확인하고 승인해 줘.')
                        st.rerun()
                    except Exception:
                        pending['kind'] = 'live_submission_unknown'
                        st.error('제출 결과를 확정할 수 없어요. 중복 전송하지 말고 플랫폼의 승인 요청에서 먼저 확인해 줘.')
            if b.button('취소', key='live_draft_cancel_'+pending['token']):
                session['pending'] = None
                st.rerun()
        elif kind == 'live_action_created':
            st.success('초안이 생성되었어. 플랫폼 웹에서 승인과 실행을 처리해 줘.')
            if pending.get('remote_status'):
                st.caption('마지막 확인 상태 · '+str(pending['remote_status'])[:35])
            if st.button('플랫폼 승인 상태 확인', key='live_status_'+pending['token']):
                try:
                    from core.live_actions import check_action_status
                    data = check_action_status(pending['action_id'])
                    pending['remote_status'] = str(data.get('status') or '미확인')[:60]
                    st.info('플랫폼 상태: ' + escape(pending['remote_status']))
                except Exception:
                    st.error('상태 조회 실패. 다시 연결하거나 플랫폼에서 확인해 줘.')
            if st.button('이 카드 닫기', key='live_close_'+pending['token']):
                session['pending'] = None
                st.rerun()
        else:
            st.warning('제출 성공 여부가 불확실해. 플랫폼 웹의 승인 요청을 확인하고 이 카드를 닫아 줘.')
            if st.button('확인 후 카드 닫기',key='live_unknown_close_'+pending['token']):
                session['pending'] = None
                st.rerun()
        return



# ── Sidebar: a short path to listings and optional account connection. ──
visitor = st.session_state.setdefault("visitor_uuid_v06", uuid.uuid4().hex)
with st.sidebar:
    st.markdown('<div class="brand"><span class="brand-symbol">◈</span><span>ProjectAgain</span></div>',
                unsafe_allow_html=True)

    actor = "ProjectAgain 사용자"
    st.markdown('<div class="sidebar-heading">매물 보기</div>', unsafe_allow_html=True)
    # Platform-registered demo listings are a normal API filter, NOT a local sandbox.
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
    # AI is metered only for identities verified independently of Streamlit session IDs.
    # A shared deployment secret is never an end-user identity.
    ai_identity = None
    if ENABLE_OPENAI_CHAT and OPENAI_API_KEY:
        if token:
            owner_id = verified_owner(actor)  # ProjectAgain /auth/me check
            if owner_id:
                ai_identity = 'platform:' + owner_id
        if not ai_identity:
            try:
                signed_in = bool(st.user.is_logged_in)
                claims = st.user.to_dict() if signed_in else {}
                subject = str(claims.get('sub') or '')
                issuer = str(claims.get('iss') or 'default')
                if signed_in and subject:
                    ai_identity = 'oidc:' + hashlib.sha256((issuer+'::'+subject).encode('utf-8')).hexdigest()
            except (AttributeError, KeyError, TypeError):
                pass
    set_ai_identity(ai_identity)
    if ENABLE_OPENAI_CHAT and OPENAI_API_KEY:
        if ai_identity:
            usage = usage_snapshot(ai_identity)
            if usage:
                st.caption('AI 오늘 사용 · {} / {}회'.format(usage['calls'], usage['max_calls']))
            else:
                st.caption('AI 사용량 저장소 연결 확인 필요 · 오류 시 AI 호출 차단')
        else:
            st.caption('AI 이용은 계정 인증 후 가능해요. 공개 매물 조회는 계속 사용할 수 있어요.')
            # Optional OIDC; only enabled if [auth] Secrets exists.
            try:
                configured = bool(st.secrets.get('auth'))
            except Exception:
                configured = False
            if configured and st.button('AI 이용 계정 로그인', key='ai_oidc_login'):
                st.login()
        try:
            if st.user.is_logged_in and st.button('서비스 로그아웃', key='ai_oidc_logout'):
                # Disconnect the platform grant too, to avoid a seemingly logged-out
                # browser session retaining a separate ProjectAgain delegation.
                st.session_state['user_grant_v06'] = ''
                set_ai_identity(None)
                st.logout()
        except (AttributeError, KeyError, TypeError):
            pass
    owner_scope = hashlib.sha256(token.encode("utf-8")).hexdigest()[:12] if token else visitor
    scope = conversation_scope('live', actor, owner_scope)
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
    # Opt-in persistence is allowed only after validating the visitor's OWN
    # ProjectAgain delegation token against /auth/me. No shared Cloud Secrets.
    current['context'].pop('_persist_owner', None)
    with st.expander('내 작업 · 기억', expanded=False):
        consent_key = 'remember_workflow_v014_' + scope[-12:]
        consent = st.checkbox('확인한 조건과 작업 계획 저장', value=False,
                              disabled=not token, key=consent_key)
        account_owner = verified_owner(actor) if consent else None
        if consent and not account_owner:
            st.warning('사용자 위임 토큰을 확인하지 못해 저장하지 않았어.')
        if account_owner:
            health = storage_health()
            if not health['ready']:
                st.error('기억 저장소 연결 실패 · 대화 내 작업은 계속할 수 있지만 영구 저장은 이용할 수 없어.')
                account_owner = None
        if account_owner:
            current['context']['_persist_owner'] = account_owner
            st.caption('저장소: ' + ('외부 PostgreSQL' if storage_kind() == 'postgres' else '앱 로컬 SQLite'))
            if storage_kind() == 'sqlite':
                st.warning('이 저장은 일시적이야. Streamlit Cloud 재배포 후 작업을 복원하려면 외부 PostgreSQL을 연결해 줘.')
            profile = current['context'].get('last_recommendation_profile')
            if profile and st.button('현재 확인된 구매 조건 저장', key='save_profile_v014'):
                try:
                    save_preferences(account_owner, profile)
                    st.success('확인된 구매 조건만 저장했어.')
                except Exception:
                    st.error('조건을 저장하지 못했어. 저장소 상태를 확인해 줘.')
            cols = st.columns(2)
            with cols[0]:
                if st.button('조건 불러오기', key='load_profile_v014'):
                    try:
                        saved = load_preferences(account_owner)
                        if saved:
                            current['context']['last_recommendation_profile'] = saved
                            st.success('구매 조건을 불러왔어. 새 추천에서 재사용을 요청할 수 있어.')
                        else:
                            st.info('저장된 조건이 없어.')
                    except Exception:
                        st.error('구매 조건을 불러오지 못했어.')
            with cols[1]:
                if st.button('조건 삭제', key='delete_profile_v014'):
                    try:
                        delete_preferences(account_owner)
                        st.success('저장된 조건을 삭제했어.')
                    except Exception:
                        st.error('저장된 조건 삭제에 실패했어.')
            try:
                saved_plans = list_workflows(account_owner, limit=5)
            except Exception:
                saved_plans = []
                st.error('저장소 연결을 확인할 수 없어.')
            if saved_plans:
                st.caption('저장된 작업 계획')
            for saved in saved_plans:
                with st.container():
                    st.caption(saved['goal'][:55] + ' · ' + str(saved['status']))
                    restore_col, delete_col = st.columns(2)
                    with restore_col:
                        if st.button('복원', key='restore_plan_'+saved['id']):
                            try:
                                restored = load_workflow(account_owner, saved['id'])
                                if restored:
                                    current['context']['workflow'] = restored
                                    current['context']['recent_listings'] = [
                                        {'id': r['listing_id'], 'title': r['title']}
                                        for r in restored.get('ranked') or []]
                                    if restored.get('recommendation_criteria'):
                                        if restored.get('status') == 'WAITING_INPUT':
                                            current['context']['recommendation_intake'] = {
                                                'profile': dict(restored['recommendation_criteria']), 'waiting': ''}
                                        else:
                                            current['context']['last_recommendation_profile'] = restored['recommendation_criteria']
                                    elif restored.get('status') == 'WAITING_INPUT':
                                        current['context']['recommendation_intake'] = {'profile': {}, 'waiting': ''}
                                    st.rerun()
                            except Exception:
                                st.error('작업 계획을 복원하지 못했어.')
                    with delete_col:
                        if st.button('삭제', key='delete_plan_'+saved['id']):
                            try:
                                delete_workflow(account_owner, saved['id'])
                                st.rerun()
                            except Exception:
                                st.error('저장된 작업 계획을 삭제하지 못했어.')
        elif not consent:
            st.caption('계정 연결 후 저장에 동의하면 확인된 조건과 작업 계획을 불러올 수 있어요. 기본값은 저장 안 함.')
    if st.button("＋ 새 대화", type="primary", width="stretch"):
        st.session_state["chat_sessions_v06"][scope] = {"turns": [], "context": {"recent_listings": []}, "pending": None}
        st.rerun()

    uploaded = None
    if token:
        with st.expander("ZIP 정적 검사", expanded=False):
            uploaded = st.file_uploader("본인 매물의 ZIP 파일", type=["zip"], help="4MB 이하 · 서버에서 실행하지 않고 정적 검사합니다. 플랫폼에 업로드하지 않습니다.")

    # Tool discovery is part of the product, not a developer-only diagnostic.
    # Keep the index accessible after the first message without overwhelming
    # the primary chat. Tools with missing parameters are invoked via chat.
    with st.expander("사용 가능한 도구 · {}개".format(len(TOOL_LABELS)), expanded=False):
        for key in ("search_listings", "recommend_listings", "inspect_listing", "get_buyer_preferences",
                    "list_offers", "get_handover", "get_recent_jobs", "inspect_attached_zip",
                    "prepare_offer"):
            if key in TOOL_LABELS:
                st.caption("· " + TOOL_LABELS[key])
        st.caption("실거래 승인·실행은 ProjectAgain 플랫폼에서만 할 수 있어요.")

    # Technical diagnostics remain optional; the basic tool index does not.
    if SHOW_DEVELOPER_TOOLS:
        st.markdown('<div class="side-divider"></div><div class="sidebar-heading">운영 진단</div>', unsafe_allow_html=True)
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
online = ENABLE_OPENAI_CHAT and bool(OPENAI_API_KEY) and bool(ai_identity)
connection_error = marketplace_config_error()
mode_title = "플랫폼 설정 필요" if connection_error else "플랫폼 조회 · 읽기 전용"
st.markdown('''<div class="workspace-bar"><div class="workspace-name">프로젝트 에이전트</div>
<div class="workspace-meta"><span class="status-dot"></span>{}</div></div>'''.format(escape(mode_title)), unsafe_allow_html=True)

session = current
pending_prompt = None
plan = session['context'].get('workflow')
if isinstance(plan, dict) and plan.get('status') not in ('CANCELLED',):
    with st.expander('진행 중인 작업 계획 · ' + str(plan.get('status') or '확인 필요'), expanded=True):
        st.caption(str(plan.get('goal') or '')[:230])
        steps = plan.get('steps', [])
        finished = sum(x.get('status') in ('COMPLETED','PARTIAL','SKIPPED','BLOCKED','WAITING_APPROVAL') for x in steps)
        if steps:
            st.progress(min(1.0, finished/len(steps)))
        for step in steps:
            icons = {'COMPLETED':'✓','PARTIAL':'△','WAITING_INPUT':'?','WAITING_APPROVAL':'◇',
                     'FAILED':'×','INTERRUPTED':'↻','BLOCKED':'×','SKIPPED':'–'}
            st.caption('{} {} · {}'.format(icons.get(step.get('status'),'○'),
                                         step.get('label', '단계'), step.get('note') or step.get('status')))
        if plan.get('storage_warning'):
            st.warning(plan['storage_warning'])
        remote_id = plan.get('remote_action_id')
        if remote_id and token:
            st.caption('플랫폼 초안 ID · ' + str(remote_id)[:36])
            if st.button('플랫폼 초안 상태 다시 확인', key='workflow_remote_check_v015'):
                try:
                    from core.live_actions import check_action_status
                    action = check_action_status(remote_id)
                    remote_status = str(action.get('status') or 'UNKNOWN')[:40]
                    st.info('ProjectAgain 원격 상태 · '+remote_status)
                    # Never claim a trade as complete merely because the platform says APPROVED.
                    if remote_status in ('REJECTED','EXPIRED','CANCELLED'):
                        for step in plan.get('steps',[]):
                            if step.get('key')=='prepare_offer':
                                step['status']='BLOCKED'
                                step['note']='플랫폼 초안 '+remote_status+' · 재확인 필요'
                        plan['status']='PARTIAL'
                    elif remote_status == 'EXECUTED':
                        for step in plan.get('steps',[]):
                            if step.get('key')=='prepare_offer':
                                step['status']='COMPLETED'
                                step['note']='플랫폼에서 실행 상태 확인 · 결제/권리 이전 검증과 별개'
                        plan['verified']=verify_plan(plan)
                        plan['status']='COMPLETED' if plan['verified']['fulfilled'] else 'PARTIAL'
                    _checkpoint(plan, session['context'])
                except Exception:
                    st.error('원격 상태 조회에 실패했어. 플랫폼에서 초안과 권한을 확인해 줘.')
        if plan.get('status') in ('PARTIAL','FAILED','INTERRUPTED') and any(
                step.get('status') in ('PENDING','FAILED','INTERRUPTED') for step in steps):
            if st.button('계획 이어서 실행', key='resume_workflow_v014', width='stretch'):
                with st.spinner('완료된 단계를 제외하고 작업 재개 중...'):
                    out = ChatAgent(actor, allow_model=bool(ai_identity)).resume_workflow(session['context'], retry=True)
                add_turn(session,'assistant',out['content'],events=out.get('events',[]),mode=out['mode'])
                if out.get('pending'):
                    session['pending'] = out['pending']
                st.rerun()
        if plan.get('status') not in ('COMPLETED','CANCELLED'):
            if st.button('현재 계획 중단',key='cancel_workflow_v014'):
                from agent.workflow import cancel_plan
                cancel_plan(plan, session['context'])
                add_turn(session,'assistant','진행 중이던 작업 계획을 중단했어. 이미 완료된 조회 기록은 대화에 남아 있어.')
                st.rerun()
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

if connection_error:
    st.warning(connection_error)
# Keep useful tool entry points available after conversation starts.
# Buttons submit an ordinary user request through the exact same chat pipeline.
if session["turns"]:
    st.markdown('<div class="conversation-actions-label">대화 중에도 바로 요청할 수 있어요</div>', unsafe_allow_html=True)
    shortcuts = [
        ("매물 검색", "현재 등록된 매물 목록 보여줘"),
        ("맞춤 추천", "나에게 맞는 프로젝트 추천해줘"),
        ("최근 작업", "최근 작업 기록 보여줘"),
    ]
    with st.container(key="conversation_shortcuts_v11"):
        cols = st.columns(3, gap="small")
        for n, (label, command) in enumerate(shortcuts):
            with cols[n]:
                intake_open = bool(session["context"].get("recommendation_intake"))
                if st.button(label, key="continue_tool_v11_" + str(n), width="stretch",
                             disabled=bool(n == 1 and intake_open)):
                    pending_prompt = command
    if session["context"].get("recommendation_intake"):
        st.caption("맞춤 추천 조건을 확인하는 중이에요. 답변을 입력하거나 '취소'라고 말할 수 있어요.")
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

# Follow-up actions submit through exactly the same validation/tool path as typed text.
queued_followup = st.session_state.pop('queued_tool_prompt_v015', None)
if queued_followup:
    pending_prompt = queued_followup
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
                result = ChatAgent(actor, allow_model=bool(ai_identity)).reply(submitted, history, context)
        except Exception:
            result = {"content": "요청을 처리하는 동안 오류가 발생했습니다. 연결 상태를 확인한 뒤 다시 시도해 주세요.",
                      "events": [], "pending": None, "mode": "runtime_error"}
        finally:
            context.pop("attachment_bytes", None)
        # Save only the user's confirmed, scoped preferences when consented.
        owner = context.get('_persist_owner')
        if owner and context.get('last_recommendation_profile'):
            try:
                save_preferences(owner, context['last_recommendation_profile'])
            except Exception:
                st.warning('계정별 선호 저장에 실패했어. 이번 대화에서의 추천은 유지돼.')
        if result.get("pending") and session.get("pending"):
            # Preserve only the earlier approval card. Do not record the new
            # workflow as approved/waiting on a card that is not on screen.
            plan = context.get('workflow')
            if plan and result['pending'].get('workflow_id') == plan.get('id'):
                for step in plan.get('steps', []):
                    if step['key'] == 'prepare_offer' and step['status'] == 'WAITING_APPROVAL':
                        step.update(status='BLOCKED', note='다른 승인 요청을 먼저 처리해야 함')
                plan['status'] = 'PARTIAL'
                plan.setdefault('issues', []).append('이전 승인 카드가 남아 새 승인 카드를 표시하지 못함')
                _checkpoint(plan, context)
            add_turn(session, "assistant", result["content"] + "\n\n이전 승인 요청이 남아 있어 새로운 승인 건은 보류했습니다.",
                     events=result.get("events", []), mode=result.get("mode"))
        else:
            add_turn(session, "assistant", result["content"], events=result.get("events", []), mode=result.get("mode"))
            if result.get("pending"):
                session["pending"] = result["pending"]
        st.rerun()

st.markdown('<p class="footer-note">추천과 분석은 참고 자료입니다. 실거래 승인·실행과 자산 이전은 ProjectAgain 플랫폼에서만 처리합니다.</p>', unsafe_allow_html=True)
