# -*- coding: utf-8 -*-
"""디지털 자산 거래 AI 에이전트 | Chat-first Streamlit app (one process, Python 3.12)."""
import json
import os
import time
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
from core.config import ENABLE_OPENAI_CHAT, OPENAI_API_KEY, OPENAI_MODEL, SHOW_DEVELOPER_TOOLS, ENABLE_LIVE_DRAFTS, marketplace_config_error  # noqa: E402
from core.request_context import (set_request_context, set_broker_refresh_handler,
    set_broker_access_handler, set_current_access_token)  # noqa: E402
from core.oidc_session import resolve_login, revoke_access, _fetch_identity  # noqa: E402
from core.oauth_broker import (BrokerStore,BrokerClient,BrokerError,BrokerReauth,
    _browser_identity,new_intent,resolve_broker,BROKER_SCOPE)  # noqa: E402
from core.marketplace_client import origin_only  # noqa: E402
from core.ai_usage import set_ai_identity, usage_snapshot, storage_kind as ai_usage_storage_kind  # noqa: E402
from core.llm_service import contains_obvious_secret  # noqa: E402
from core.config import MARKETPLACE_BASE_URL  # noqa: E402
from core.live_diagnostics import run_diagnostics  # noqa: E402
from core.chat_sessions import (conversation_scope, get_or_migrate_session, append_turn,
    init_archive, start_conversation, open_conversation, remove_conversation, conversation_list, conversation_title)  # noqa: E402
from core.chat_archive_store import (save_conversation, list_conversations, load_conversation,
    delete_conversation)  # noqa: E402
from core.ux_actions import suggested_actions, friendly_state, tool_result_label, request_requires_account  # noqa: E402
from core.workflow_store import (verified_owner, save_preferences, load_preferences,
    delete_preferences, list_workflows, load_workflow, delete_workflow, storage_kind, storage_health)  # noqa: E402
from agent.workflow import workflow_outline, verify_plan, _checkpoint  # noqa: E402
from core.ui_presentation import workflow_view, recommendation_view  # noqa: E402
from core.ui_design import layout_mode, evidence_rows, activity_tone  # noqa: E402
from core.workspace_state import workspace_view, focused_actions, profile_summary  # noqa: E402

st.set_page_config(page_title="ProjectAgain · 프로젝트 에이전트", page_icon="🧭", layout="wide", initial_sidebar_state="expanded")
st.markdown("<style>" + (ROOT / "assets" / "style.css").read_text(encoding="utf-8") + "</style>", unsafe_allow_html=True)


def get_session(scope, legacy_scopes=()):
    all_sessions = st.session_state.setdefault("chat_sessions_v06", {})
    return get_or_migrate_session(all_sessions, scope, legacy_scopes)


def add_turn(session, role, content, **kwargs):
    append_turn(session, role, content, **kwargs)


def show_recommendation_snapshot(data, idx, turn_id):
    """Comparison first, evidence on demand; never invent a listing or safety claim."""
    view = recommendation_view(data)
    cards = view['cards']
    if not cards:
        reasons = data.get('excluded_reasons') or []
        st.info('현재 조건으로 추천할 수 있는 매물이 없어요. 위험 기준이나 예산을 임의로 바꾸지 않았어요.')
        if reasons:
            st.caption('주요 제외 이유 · ' + ' / '.join(str(x)[:70] for x in reasons[:2]))
        return
    st.markdown('<div class="result-section-heading"><span>추천 후보 비교</span>'
                '<span class="result-section-count">{}개 표시 / 조건 부합 {}개</span></div>'.format(
                len(cards), escape(str(view['eligible']))), unsafe_allow_html=True)
    st.caption('플랫폼 공개 매물 기준 · 추천 순위는 개인 조건에 따른 상대적 적합성이에요.')
    if len(cards) > 1:
        # Table is a single glanceable comparison instead of repeated vertical
        # cards that force the user to memorize previous candidates.
        st.table(view['comparison'])
        st.markdown('<p class="mobile-table-cue" role="note">표를 좌우로 밀어 나머지 비교 항목을 볼 수 있어요.</p>',
                    unsafe_allow_html=True)
    for card in cards:
        header = '{}순위 · {} · {}'.format(card['number'], card['title'][:58], card['price'])
        with st.expander(header, expanded=card['number'] == 1):
            st.markdown('**맞는 이유** · ' + card['reason'])
            st.markdown('**먼저 확인할 점** · ' + card['risk'])
            st.caption('위험 검토 · ' + card['risk_label'])
            if card['unverified'] is not None and card['unverified'] > 0:
                st.caption('미확인 위험 항목 · {}개 (안전하다는 뜻이 아니에요)'.format(card['unverified']))
            if card['assessments']:
                st.markdown('**추가 선호와의 비교**')
                for item in card['assessments']:
                    verdict = '일치' if item.get('verdict') == 'MATCH' else '불일치'
                    st.caption('{} · {}'.format(verdict, str(item.get('preference') or '')[:90]))
                    if item.get('evidence_quote'):
                        st.caption('판매자 공개 자료 인용 · ' + str(item['evidence_quote'])[:140])
            elif view['qualitative']:
                st.caption('추가 선호에 대한 공개 근거가 부족해 점수에 반영하지 않았어요.')
            # Relative scoring is an implementation detail, not an objective
            # safety or investment-worthiness certification.
            if card['score'] is not None:
                st.caption('상대적 적합도 · {} (기본 {} / AI 보정 {:+d}) · 안전·수익 보증 아님'.format(
                    card['score'], card['base_score'], int(card['adjustment'] or 0)))
            if card['dimensions']:
                st.markdown('**위험 항목별 공개 근거**')
                st.markdown(evidence_rows(card['dimensions']), unsafe_allow_html=True)
            listing_id = card['listing_id']
            try:
                uuid.UUID(listing_id)
                safe_listing = True
            except (ValueError, AttributeError):
                safe_listing = False
            if safe_listing and st.button('이 후보 공개 정보 검토', key='rec_review_{}_{}_{}'.format(turn_id,idx,card['number'])):
                st.session_state['queued_tool_prompt_v015'] = '{} 매물의 공개 정보를 검토해줘'.format(listing_id)
                st.rerun()
    st.caption('추천은 매물 등록 정보를 바탕으로 한 판단 보조예요. 수익·권리·실제 실행 여부는 추가 검증이 필요해요.')


def show_event(event, idx, turn_id, *, render_detail=True):
    """Keep tool activity visible without displaying raw payloads by default."""
    label = str(event.get("label") or event.get("name") or "도구")
    success = bool(event.get("success"))
    # A successful tool response does not certify the listing, the risk, or a trade.
    status = tool_result_label(event.get('name'), success)
    tone = activity_tone(success)
    st.markdown(
        '<div class="tool-activity tool-activity-{}" role="status">'
        '<span class="tool-activity-indicator" aria-hidden="true"></span>'
        '<span class="tool-activity-name">{}</span>'
        '<span class="tool-activity-state">{}</span></div>'.format(
            tone, escape(label), escape(status)), unsafe_allow_html=True)
    if success and event.get('name') in ('recommend_listings', 'compare'):
        if 'data' in event and render_detail:
            show_recommendation_snapshot(event.get('data') or {}, idx, turn_id)
        elif 'data' not in event:
            st.caption('도구 요약만 보관되어 있어요. 추천 상세는 최신 매물 조회로 다시 확인해 주세요.')
        else:
            st.caption('추천 결과는 위 작업 공간에서 확인할 수 있어요.')
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
            show_event(event, no, idx, render_detail=False)


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
        st.markdown('**플랫폼 구매 제안 초안**')
        st.caption('대상 매물 · ' + str(pending.get('listing_title') or '매물 제목 확인 필요'))
        st.metric('제안 금액', '{:,}원'.format(int(pending.get('price_krw') or 0)))
        st.caption('현재 단계 · ' + {'live_offer_draft':'초안 제출 전 · 사용자 확인 필요',
                   'live_action_created':'플랫폼에 초안 등록됨 · 승인 대기',
                   'live_submission_unknown':'제출 여부 미확인 · 재제출 금지'}.get(kind, '확인 필요'))
        with st.expander('매물 식별정보', expanded=False):
            st.code(str(pending.get('listing_id') or '미확인')[:36], language=None)
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
            st.info('플랫폼에 구매 제안 초안만 등록됐어요. 승인·실행·거래 완료와는 다른 단계예요.')
            if pending.get('remote_status'):
                st.caption('마지막 확인 상태 · '+friendly_state(pending['remote_status']))
            if st.button('플랫폼 승인 상태 확인', key='live_status_'+pending['token']):
                try:
                    from core.live_actions import check_action_status
                    data = check_action_status(pending['action_id'])
                    pending['remote_status'] = str(data.get('status') or '미확인')[:60]
                    st.info('플랫폼 상태 · ' + friendly_state(pending['remote_status']))
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





def display_profile(profile, *, title='현재 확인된 추천 조건'):
    chips = profile_summary(profile)
    if not chips:
        return
    st.markdown('**' + title + '**')
    # Model-generated preference text is always escaped for the HTML surface.
    spans = ''.join('<span class="criteria-pill">{}</span>'.format(escape(x)) for x in chips)
    st.markdown('<div class="criteria-strip">{}</div>'.format(spans), unsafe_allow_html=True)


def inline_profile_edit(session, prefix='workbench'):
    context = session.get('context') or {}
    profile = (context.get('recommendation_intake') or {}).get('profile') or context.get('last_recommendation_profile') or {}
    if not profile:
        st.caption('아직 확인된 구매 조건이 없어요. 대화로 조건을 알려주세요.')
        return
    with st.popover('조건 수정'):
        with st.form('wb_profile_edit_' + prefix):
            goal = st.text_input('구매 목적', value=str(profile.get('objective') or '')[:120], max_chars=120)
            budget = st.number_input('예산 상한 (원)', min_value=0, max_value=1_000_000_000,
                step=10_000, value=int(profile.get('max_budget_krw') or 0))
            skill_opts = ['', 'NONE', 'BASIC', 'INTERMEDIATE', 'ADVANCED']
            risk_opts = ['', 'LOW', 'MEDIUM', 'HIGH']
            skill_names = {'':'미정', 'NONE':'처음','BASIC':'초급','INTERMEDIATE':'중급','ADVANCED':'고급'}
            risk_names = {'':'미정','LOW':'낮음','MEDIUM':'보통','HIGH':'높음'}
            old_skill = profile.get('skill_level') or ''
            old_risk = profile.get('risk_tolerance') or ''
            skill = st.selectbox('개발 경험', skill_opts, index=skill_opts.index(old_skill) if old_skill in skill_opts else 0,
                format_func=lambda x:skill_names[x])
            risk = st.selectbox('위험 허용도', risk_opts, index=risk_opts.index(old_risk) if old_risk in risk_opts else 0,
                format_func=lambda x:risk_names[x])
            technologies = st.text_input('선호 기술 (쉼표 구분)',
                value=', '.join(profile.get('preferred_tech_stack') or [])[:160], max_chars=160)
            if st.form_submit_button('이 조건 적용', width='stretch'):
                updated = dict(profile)
                for key, value in (('objective',goal.strip()),('max_budget_krw',int(budget) if budget else None),
                                   ('skill_level',skill),('risk_tolerance',risk)):
                    if value:
                        updated[key] = value
                    else:
                        updated.pop(key,None)
                updated['preferred_tech_stack'] = [item.strip()[:30] for item in technologies.split(',') if item.strip()][:10]
                context['last_recommendation_profile'] = updated
                if isinstance(context.get('recommendation_intake'),dict):
                    context['recommendation_intake']['profile'] = dict(updated)
                    context['recommendation_intake']['waiting'] = ''
                st.session_state['workspace_profile_notice_v0173'] = True
                st.rerun()


def is_listing_uuid(value):
    try:
        return isinstance(value, str) and str(uuid.UUID(value)) == value.lower()
    except (ValueError, AttributeError, TypeError):
        return False


def show_search_workspace(data):
    listings = data.get('listings') or []
    if not isinstance(listings, list):
        listings = []
    st.markdown('<div class="result-section-heading">현재 조회한 매물 '
                '<span class="result-section-count">{}건</span></div>'.format(len(listings)), unsafe_allow_html=True)
    st.caption('ProjectAgain 플랫폼 응답을 기반으로 한 조회 당시 목록이에요. 가격·등록 정보는 변경될 수 있어요.')
    if not listings:
        st.info('이 조회 조건에 표시할 매물이 없어요. 시연 매물 포함 여부나 검색 조건을 변경해 보세요.')
        return
    rows = []
    for idx, item in enumerate(listings[:15], 1):
        if not isinstance(item, dict):
            continue
        price = item.get('price_krw')
        stack = item.get('tech_stack') or []
        rows.append({'순서':idx, '프로젝트':str(item.get('title') or '제목 미확인')[:56],
                     '가격':f'{price:,}원' if type(price) is int and price >= 0 else '미확인',
                     '기술':', '.join(str(x)[:24] for x in stack[:3]) if isinstance(stack,list) else '미확인'})
    st.table(rows[:8])
    if len(rows) > 8:
        with st.expander('나머지 매물 · {}건 더 보기'.format(len(rows) - 8), expanded=False):
            st.table(rows[8:])
    selectable = [(str(item.get('id')), '{}. {}'.format(i, str(item.get('title') or '제목 미확인')[:65]))
                  for i, item in enumerate(listings[:15], 1) if isinstance(item,dict)
                  and isinstance(item.get('id'),str) and is_listing_uuid(item['id'])]
    if selectable:
        chosen = st.selectbox('검토할 프로젝트', selectable, format_func=lambda item:item[1],
                              key='search_selection_v0173')
        if st.button('선택한 매물 공개 정보 검토', key='search_inspect_v0173'):
            st.session_state['queued_tool_prompt_v015'] = '{} 매물의 공개 정보를 검토해줘'.format(chosen[0])
            st.rerun()
    if data.get('next_cursor') is not None:
        st.caption('다음 페이지가 있어요. 아래 ‘다음 매물 보기’로 계속 조회할 수 있어요.')


def show_inspection_workspace(data):
    st.markdown('**' + escape(str(data.get('listing_title') or '매물')[:90]) + '**')
    report = data.get('report') or {}
    if not isinstance(report, dict):
        report = {}
    findings = report.get('findings') or []
    if not isinstance(findings, list):
        findings = []
    st.caption('플랫폼 공개 자료 기반 정적 점검 · 실제 실행, 매출 증빙, 소스 및 권리 이전 검증과 구분해 주세요.')
    st.markdown('<div class="result-section-heading">확인할 사항 '
                '<span class="result-section-count">{}건</span></div>'.format(len(findings)), unsafe_allow_html=True)
    if not findings:
        st.info('상세 검토 근거가 반환되지 않았어요. 정보가 없다는 이유만으로 안전하다고 판단하지 않아요.')
    else:
        for index, finding in enumerate(findings[:4], 1):
            if not isinstance(finding, dict):
                continue
            title = str(finding.get('title') or '추가 확인 필요')[:180]
            st.markdown('{}. {}'.format(index, title))
            rec = str(finding.get('recommendation') or '')[:200]
            if rec:
                st.caption('다음 확인 · ' + rec)
        if len(findings) > 4:
            with st.expander('나머지 검토 항목 {}건'.format(len(findings)-4), expanded=False):
                for finding in findings[4:]:
                    if isinstance(finding, dict):
                        st.markdown('· ' + str(finding.get('title') or '항목')[:180])
    with st.expander('검토 범위와 상태', expanded=False):
        from core.ux_actions import friendly_state
        st.caption('검토 상태 · ' + friendly_state(report.get('verdict')))
        st.caption('동적 실행 여부 · ' + ('실행하지 않음' if report.get('dynamic_execution') == 'NOT_TESTED' else '플랫폼 기록 별도 확인 필요'))
        st.caption('검사 데이터는 사용자가 요청한 당시의 결과이며, 실제 구동·법적 권리를 보증하지 않아요.')


def render_primary_workspace(view, session, actor):
    """Only one focus surface is primary. Transcript and tool trace are secondary."""
    focus = view['focus']
    if focus == 'welcome':
        return
    st.markdown('<div class="workbench-eyebrow">{}</div>'.format(escape(view['eyebrow'])), unsafe_allow_html=True)
    st.markdown('<h1 class="workbench-title">{}</h1>'.format(escape(view['title'])), unsafe_allow_html=True)
    if focus in ('recommend','intake'):
        # An old recommendation must keep its original filtering criteria even
        # after the user edits their current profile for the next run.
        snapshot = view['data'].get('criteria') or {}
        profile = snapshot if focus == 'recommend' and snapshot else view['profile']
        if profile:
            display_profile(profile, title='이 결과에 적용된 조건' if focus == 'recommend' else '현재 확인된 추천 조건')
            inline_profile_edit(session, prefix='top')
            if focus == 'recommend':
                st.caption('조건을 수정했다면 새 추천을 실행해 주세요. 위 결과는 조회 당시 조건으로 계산됐어요.')
            if st.session_state.pop('workspace_profile_notice_v0173', False):
                st.success('변경한 조건은 다음 추천 요청부터 적용해요. 이전 결과는 변경되지 않아요.')
        else:
            st.caption('구매 목적과 예산, 개발 경험, 위험 허용도를 알려주면 후보를 추릴 수 있어요.')
    if focus == 'offer':
        pending_ui(session, actor)
        plan = view.get('plan') or {}
        if plan.get('ranked'):
            with st.expander('제안 전에 비교했던 후보 다시 보기 · 조회 당시 자료', expanded=False):
                show_recommendation_snapshot({'ranked':plan['ranked'], 'eligible_count':len(plan['ranked'])}, 0, 0)
    elif focus == 'search':
        show_search_workspace(view['data'])
    elif focus == 'recommend':
        show_recommendation_snapshot(view['data'], view['event_index'] or 0, view['turn_index'] or 0)
    elif focus == 'intake':
        st.markdown('**다음에 필요한 정보**')
        st.markdown(view['last_assistant'] or '추천 조건을 이어서 알려주세요.')
    elif focus == 'inspection':
        show_inspection_workspace(view['data'])
    elif focus == 'workflow':
        st.caption('진행 상태를 확인하고 남은 정보를 대화로 입력하거나, 아래 작업 단계에서 이어서 실행할 수 있어요.')
        plan = view.get('plan') or {}
        if plan.get('ranked'):
            with st.expander('지금까지 확보한 추천 후보 · 조회 당시 자료', expanded=False):
                show_recommendation_snapshot({'ranked':plan['ranked'], 'eligible_count':len(plan['ranked'])}, 0, 0)
    elif focus == 'error':
        st.warning('마지막 도구 요청이 성공하지 않았어요. 거래 관련 작업은 자동으로 재시도하지 않아요.')
        if view['event']:
            st.caption(str(view['event'].get('summary') or '결과 확인 필요')[:240])
    elif focus == 'restored':
        st.info('저장된 대화의 도구 요약만 있어요. 당시 매물 가격·검토 상세·거래 상태는 새로 조회해야 해요.')
    elif focus == 'stale':
        st.warning('시연 매물 포함 설정이 변경되었어요. 이전에 조회한 매물 목록·추천 결과를 새 조건의 결과로 취급하지 않아요.')
    elif focus == 'offer_summary':
        st.caption('초안 준비와 플랫폼 등록은 별도 단계이며, 실제 거래 승인·실행은 플랫폼에서 확인해야 해요.')
        st.markdown(str(view['event'].get('summary') or '제안 준비 상태 확인 필요')[:250])
    elif focus == 'account_result':
        st.caption('계정별 조회 결과 · 현재 조회에서 반환된 정보 기준')
        st.markdown(str(view['event'].get('summary') or '조회 결과 확인')[:250])
    elif focus == 'conversation':
        if view['last_assistant']:
            st.markdown(view['last_assistant'])
        else:
            st.caption('아래 입력창에서 이어서 질문해 주세요.')
        earlier = view.get('previous_result')
        if earlier and view['data']:
            title = {'recommend':'앞서 추천한 후보 다시 보기', 'search':'앞서 조회한 매물 다시 보기',
                     'inspection':'앞서 점검한 결과 다시 보기'}.get(earlier, '앞서 조회한 결과 보기')
            with st.expander(title + ' · 조회 당시 기록', expanded=False):
                if earlier == 'recommend':
                    show_recommendation_snapshot(view['data'], view['event_index'] or 0, view['turn_index'] or 0)
                elif earlier == 'search':
                    show_search_workspace(view['data'])
                elif earlier == 'inspection':
                    show_inspection_workspace(view['data'])
                else:
                    st.caption(str(view['event'].get('summary') or '')[:240])


def show_contextual_actions(view, session, authenticated, uploaded):
    actions = focused_actions(view, session['context'], authenticated, offer_enabled=bool(ENABLE_LIVE_DRAFTS))
    # Fallback contextual suggestions, without duplicating identical commands.
    if not actions and view['focus'] not in ('welcome','offer'):
        actions = suggested_actions(session['context'], authenticated=authenticated,
                                     has_upload=bool(uploaded),limit=3)
    if not actions or view['focus'] == 'offer':
        return None
    st.markdown('<div class="next-actions-heading">이어 할 수 있는 일</div>',unsafe_allow_html=True)
    submitted = None
    with st.container(key='workspace_action_row_v0173'):
        cols = st.columns(len(actions), gap='small')
        for idx, (label,command) in enumerate(actions):
            with cols[idx]:
                if st.button(label, key='workspace_action_v0173_' + str(idx), width='stretch'):
                    submitted = command
    return submitted


# -- ProjectAgain Broker login: native OIDC cookie is a secure browser-session anchor --
def broker_connect_ui(platform_origin, native_configured):
    """Returns (verified login, forced 401 handler). Fail closed on broker errors.

    Native st.login is used to authenticate the BROWSER, not to maintain access
    tokens. Broker linkage is a separate explicit consent, then the broker
    renews access automatically before each authorized server-side operation.
    """
    # Clear transient callback values immediately, including unauthenticated
    # visits. A callback URL is never a login credential by itself.
    ticket=st.query_params.get('pa_broker_ticket')
    state=st.query_params.get('pa_broker_state')
    auth_error=st.query_params.get('pa_broker_error')
    for param in ('pa_broker_ticket','pa_broker_state','pa_broker_error'):
        if param in st.query_params:
            del st.query_params[param]
    if ticket or state or auth_error:
        st.session_state.pop('broker_authorization_url',None)
        st.session_state.pop('broker_authorization_created',None)
    if not native_configured:
        st.warning('통합 로그인 설정이 필요해요. 공개 매물은 로그인 없이 볼 수 있어요.')
        return None, None
    if not bool(getattr(st.user,'is_logged_in',False)):
        st.caption('ProjectAgain 로그인 후 필요한 권한을 안전하게 연결할 수 있어요.')
        if st.button('ProjectAgain 계정으로 로그인',key='broker_native_login',type='primary',width='stretch'):
            st.login()
        return None,None
    try:
        db_url=os.environ.get('AGENT_STATE_DATABASE_URL','')
        secret=os.environ.get('AGENT_BROKER_STORE_KEY','')
        origin=os.environ.get('PROJECTAGAIN_API_ORIGIN','')
        client_id=os.environ.get('PROJECTAGAIN_BROKER_CLIENT_ID','')
        client_secret=os.environ.get('PROJECTAGAIN_BROKER_CLIENT_SECRET','')
        expected_redirect=os.environ.get('PROJECTAGAIN_BROKER_REDIRECT_URL','')
        # The broker is registered for exactly this application's homepage.
        if origin_only(origin)!=origin_only(platform_origin) or expected_redirect!='https://projectagain.streamlit.app/':
            raise BrokerError('configuration_mismatch','플랫폼 주소와 등록된 복귀 주소가 일치하지 않아요.')
        store=BrokerStore(db_url,secret)
        client=BrokerClient(origin,client_id,client_secret)
        binding,uid=_browser_identity(st.user,platform_origin,secret)
    except (BrokerError,BrokerReauth,ValueError,TypeError) as exc:
        st.warning(str(exc) if isinstance(exc,BrokerError) else '로그인 연결 설정을 확인해 주세요.')
        if st.button('ProjectAgain 로그인 다시 시작',key='broker_reset_native'):
            st.logout()
        return None,None

    if ticket or state or auth_error:
        if auth_error:
            st.warning('계정 권한 연결이 취소됐어요.')
        elif isinstance(ticket,str) and isinstance(state,str):
            try:
                store.finish(state,binding,uid,ticket,client.exchange)
                st.rerun()
            except (BrokerError,ValueError):
                st.warning('인증 연결을 완료하지 못했어요. 다시 연결해 주세요.')
        else:
            st.warning('인증 복귀 정보가 올바르지 않아요. 다시 연결해 주세요.')

    try:
        login,record=resolve_broker(store,client,binding,uid,platform_origin)
    except BrokerReauth:
        store.clear(binding)
        login,record=None,None
        st.warning('권한 연결이 만료됐어요. 다시 연결해 주세요.')
    except BrokerError as exc:
        # On 503 keep encrypted persisted credentials; do NOT rotate again
        # from the Streamlit side or silently fall back to a legacy token.
        login,record=None,None
        st.warning(str(exc))
    if login and login.connected:
        st.caption('계정 연결됨 · 인증 정보 자동 갱신')
        def ensure_fresh():
            fresh, scopes = client.access(record)
            if 'openid' not in scopes:
                raise BrokerError('invalid_scope','계정 권한을 확인할 수 없어요.')
            set_current_access_token(fresh)
            return fresh
        set_broker_access_handler(ensure_fresh)
        if ENABLE_LIVE_DRAFTS and not login.has_scope('offer:draft'):
            st.caption('구매 제안 초안은 별도 권한이 필요해요.')
            if st.button('제안 초안 권한 추가',key='broker_add_draft',width='stretch'):
                try:
                    st.session_state['broker_draft_url']=new_intent(store,client,binding,uid,BROKER_SCOPE+' offer:draft')
                    st.session_state['broker_draft_created']=time.time()
                except BrokerError:
                    st.warning('권한 요청을 준비하지 못했어요.')
            draft_url=st.session_state.get('broker_draft_url')
            if draft_url and time.time()-float(st.session_state.get('broker_draft_created',0))<240:
                st.link_button('추가 권한 동의 화면 열기',draft_url,width='stretch')
        if st.button('로그아웃',key='broker_logout',width='stretch'):
            try:
                client.logout(record)
            except BrokerError:
                # Never imply server-side revocation succeeded on network error.
                pass
            try:
                store.clear(binding)
            finally:
                set_request_context(token='',visitor_id='',include_demo=False)
                set_ai_identity(None)
                st.logout()
        def refresh_one_get(observed_token):
            try:
                refreshed, _=client.access(record,force=True,observed_token=observed_token)
                status,profile=_fetch_identity(origin_only(origin)+'/api/v1/oauth/userinfo',refreshed)
                status2,me=_fetch_identity(origin_only(origin)+'/api/v1/auth/me',refreshed)
                if status!='ok' or status2!='ok' or profile.get('sub')!=uid or me.get('id')!=uid:
                    return None
                set_current_access_token(refreshed)
                return refreshed
            except (BrokerError,AttributeError):
                return None
        return login,refresh_one_get

    st.caption('ProjectAgain 계정 확인됨 · API 이용 권한을 연결해 주세요.')
    try:
        auth_url=st.session_state.get('broker_authorization_url')
        if (not auth_url or st.session_state.get('broker_authorization_binding')!=binding
                or time.time()-float(st.session_state.get('broker_authorization_created',0))>240):
            auth_url=new_intent(store,client,binding,uid)
            st.session_state['broker_authorization_url']=auth_url
            st.session_state['broker_authorization_binding']=binding
            st.session_state['broker_authorization_created']=time.time()
        st.link_button('ProjectAgain 작업 권한 연결',auth_url,type='primary',width='stretch')
        st.caption('첫 연결 시 플랫폼에서 권한 동의가 필요해요.')
    except BrokerError:
        st.warning('권한 연결을 준비하지 못했어요. 연결 설정과 플랫폼 상태를 확인해 주세요.')
    if st.button('다른 계정으로 로그인',key='broker_switch_account',width='stretch'):
        st.logout()
    return None,None


# ── Sidebar: a short path to listings and optional account connection. ──
visitor = st.session_state.setdefault("visitor_uuid_v06", uuid.uuid4().hex)
with st.sidebar:
    st.markdown('<div class="brand"><span class="brand-symbol">◈</span><span>ProjectAgain</span></div>',
                unsafe_allow_html=True)

    actor = "ProjectAgain 사용자"
    st.markdown('<div class="sidebar-heading">매물 보기</div>', unsafe_allow_html=True)
    # Platform-registered demo listings are a normal API filter, NOT a local sandbox.
    show_demo = st.checkbox("시연 매물 포함", value=True, key="include_demo_v10")
    # Native OIDC handles redirect/state/nonce/PKCE. Only a platform-validated
    # API access token may enable personalized features or paid model calls.
    # Never use a manually pasted grant, a shared secret, or unverified OIDC sub.
    st.session_state.pop('user_grant_v06', None)  # legacy manual-token control
    try:
        auth_settings = st.secrets.get('auth', {})
    except Exception:
        auth_settings = {}
    configured = bool(auth_settings) and bool(auth_settings.get('server_metadata_url'))
    platform_issuer = str(auth_settings.get('server_metadata_url') or '').removesuffix('/.well-known/openid-configuration')
    set_broker_refresh_handler(None)
    set_broker_access_handler(None)
    broker_requested = any(os.environ.get(k,'').strip() for k in (
        'PROJECTAGAIN_BROKER_CLIENT_ID','PROJECTAGAIN_BROKER_CLIENT_SECRET',
        'PROJECTAGAIN_API_ORIGIN','AGENT_BROKER_STORE_KEY',
        'PROJECTAGAIN_BROKER_REDIRECT_URL'))
    st.markdown('<div class="sidebar-heading">ProjectAgain 계정</div>', unsafe_allow_html=True)
    if broker_requested:
        login,refresh_handler=broker_connect_ui(MARKETPLACE_BASE_URL,configured)
        token=login.access_token if login and login.connected else ''
        connected=bool(token)
        set_request_context(token=token,visitor_id=visitor,include_demo=show_demo)
        set_broker_refresh_handler(refresh_handler)
        ai_identity=login.ai_identity if connected else None
        set_ai_identity(ai_identity)
    else:
        login = resolve_login(st.user, MARKETPLACE_BASE_URL, expected_issuer=platform_issuer) if configured else None
        token = login.access_token if login and login.connected else ''
        connected = bool(token)
        set_request_context(token=token, visitor_id=visitor, include_demo=show_demo)
        ai_identity = login.ai_identity if connected else None
        set_ai_identity(ai_identity)
        if connected:
            st.caption('계정 연결됨 · 개인화 기능 이용 가능')
            if 'offer:draft' not in login.scopes and ENABLE_LIVE_DRAFTS:
                st.caption('구매 제안 초안 등록은 추가 권한 동의가 필요해요.')
                if auth_settings.get('drafts') and st.button('제안 초안 권한 추가', key='oidc_draft_scope_v018', width='stretch'):
                    st.login('drafts')
            if st.button('로그아웃', key='oidc_logout_v018', width='stretch'):
                # Platform revocation is best-effort. Streamlit logout always clears
                # its own identity cookie; no private data is shown after logout.
                revoke_access(token, platform_issuer, str(auth_settings.get('client_id') or ''),
                              str(auth_settings.get('client_secret') or ''))
                set_request_context(token='', visitor_id=visitor, include_demo=show_demo)
                set_ai_identity(None)
                st.logout()
        elif not configured:
            st.info('통합 로그인 설정을 준비 중이에요. 공개 매물은 로그인 없이 볼 수 있어요.')
        else:
            if login and login.status == 'expired':
                st.warning(login.message)
                if st.button('다시 로그인', key='oidc_reauth_v018', width='stretch'):
                    # Native Streamlit does not expose refresh tokens. Explicitly
                    # restart login rather than reusing expired API credentials.
                    st.logout()
            elif login and login.status in ('invalid', 'unavailable'):
                st.warning(login.message or '로그인 연결 상태를 확인하지 못했어요.')
                if st.button('로그인 다시 시작', key='oidc_invalid_v018', width='stretch'):
                    st.logout()
            else:
                st.caption('공개 매물 조회는 로그인 없이 사용할 수 있어요.')
                if st.button('ProjectAgain 계정으로 로그인', key='oidc_login_v018',
                             type='primary', width='stretch'):
                    st.login()
    if ENABLE_OPENAI_CHAT and OPENAI_API_KEY:
        if ai_identity:
            usage = usage_snapshot(ai_identity)
            if usage:
                st.caption('AI 오늘 사용 · {} / {}회'.format(usage['calls'], usage['max_calls']))
            else:
                st.caption('AI 사용량 저장소 연결 확인 필요 · 오류 시 AI 호출 차단')
        else:
            st.caption('AI 대화는 로그인과 사용량 저장소 연결 후 이용할 수 있어요.')
    owner_scope = login.owner_key[:12] if connected else visitor
    scope = conversation_scope('live', actor, owner_scope)
    # Before v0.10, demo-filter switches created separate chat scopes.
    old_scopes = [scope + '::' + str(show_demo), scope + '::' + str(not show_demo)]
    current = get_session(scope, old_scopes)
    # A search filter change must not erase the chat, but old search ordinals
    # must not accidentally point to a listing excluded by the new filter.
    previous_filter = current.get("_include_demo_filter")
    if previous_filter is not None and previous_filter != show_demo:
        current['context']['_listing_snapshot_stale'] = True
        for context_key in ("recent_listings", "listing_next_cursor", "last_search_query"):
            current["context"].pop(context_key, None)
    current["_include_demo_filter"] = show_demo
    # v0.17.1 migration: preserve the old live session as the first archived chat.
    archive = st.session_state.setdefault('conversation_archive_v0172', {})
    # Always initialize through the archive helper: do not insert a None
    # placeholder with setdefault(), which crashes on a visitor's first load.
    # The helper also recovers a None placeholder left by earlier app versions.
    current = init_archive(archive, scope, current)
    active_archive = archive[scope]
    st.session_state['chat_sessions_v06'][scope] = current
    # Filters affect only the currently opened conversation, never archive identity.
    earlier_filter = current.get('_include_demo_filter')
    if earlier_filter is not None and earlier_filter != show_demo:
        current['context']['_listing_snapshot_stale'] = True
        for context_key in ('recent_listings','listing_next_cursor','last_search_query'):
            current['context'].pop(context_key, None)
    current['_include_demo_filter'] = show_demo
    # Opt-in persistence is allowed only after validating the visitor's OWN
    # ProjectAgain delegation token against /auth/me. No shared Cloud Secrets.
    current['context'].pop('_persist_owner', None)
    with st.expander('내 작업 · 기억', expanded=False):
        consent_key = 'remember_workflow_v014_' + scope[-12:]
        consent = st.checkbox('확인한 조건과 작업 계획 저장', value=False,
                              disabled=not token, key=consent_key)
        account_owner = verified_owner(actor) if consent else None
        if consent and not account_owner:
            st.warning('ProjectAgain 계정 확인에 실패해 저장하지 않았어요.')
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
    # Existing chats remain reachable; only the active ID changes.
    if st.button("＋ 새 대화", type="primary", width="stretch"):
        if current.get('pending'):
            current['pending'] = None  # pending nonces are never transferred
            plan_for_switch = current['context'].get('workflow')
            if isinstance(plan_for_switch, dict):
                for step in plan_for_switch.get('steps', []):
                    if step.get('status') == 'WAITING_APPROVAL':
                        step['status'] = 'BLOCKED'
                        step['note'] = '대화 전환으로 승인 카드 종료 · 플랫폼 상태를 다시 확인하세요'
                plan_for_switch['status'] = 'PARTIAL'
        start_conversation(active_archive)
        st.rerun()
    with st.expander('대화 보관함 · {}개'.format(len(active_archive['items'])), expanded=False):
        st.caption('이 브라우저 세션에서 나눈 대화예요. 저장 동의 없이는 재접속 후 유지되지 않을 수 있어요.')
        for cid, title, _ in conversation_list(active_archive)[:30]:
            is_active = cid == active_archive['active']
            c1, c2 = st.columns([4,1], gap='small')
            with c1:
                if st.button(('● ' if is_active else '') + title[:32], key='open_chat_'+cid,
                             disabled=is_active, width='stretch'):
                    if current.get('pending'):
                        current['pending'] = None
                    open_conversation(active_archive, cid)
                    st.rerun()
            with c2:
                if st.button('삭제', key='remove_chat_'+cid, width='stretch'):
                    remove_conversation(active_archive, cid)
                    st.rerun()
        st.caption('대화를 삭제하면 이 브라우저 보관함에서 지워져요. 계정에 별도로 저장한 대화는 따로 삭제해야 해요.')
    with st.expander('대화 장기 보관', expanded=False):
        archive_consent_key = 'conversation_consent_v0172_' + scope[-12:]
        archive_consent = st.checkbox('필요한 대화를 직접 계정 저장소에 보관하는 데 동의',
                                     value=False, disabled=not token, key=archive_consent_key)
        archive_owner = verified_owner(actor) if archive_consent else None
        if archive_consent and not archive_owner:
            st.warning('ProjectAgain 계정이 확인되지 않아 저장할 수 없어요.')
        if archive_owner:
            st.caption('저장 버튼을 누를 때만 외부 저장소에 대화 문장과 도구 요약을 보관해요. 승인 카드·원본 API 응답은 제외하며, 민감한 내용은 저장하지 않는 것이 좋아요.')
            if storage_kind() == 'sqlite':
                st.warning('현재 로컬 저장소는 Cloud 재배포 후 사라질 수 있어요. PostgreSQL 연결을 추천해요.')
            if st.button('현재 대화 계정에 저장', key='save_chat_v0172', width='stretch'):
                try:
                    save_conversation(archive_owner, active_archive['active'], current)
                    st.success('현재 대화를 계정별 보관함에 저장했어요.')
                except Exception:
                    st.error('대화 보관에 실패했어요. 저장소 상태 또는 대화 속 비밀정보를 확인해 주세요.')
            try:
                remote_chats = list_conversations(archive_owner, limit=20)
            except Exception:
                remote_chats = []
                st.error('계정 대화 보관함을 읽지 못했어요.')
            for remote_chat in remote_chats:
                rid = remote_chat['id']
                st.caption(remote_chat['title'])
                load_col, del_col = st.columns(2)
                with load_col:
                    if st.button('불러오기', key='load_chat_v0172_'+rid, width='stretch'):
                        try:
                            loaded = load_conversation(archive_owner, rid)
                            if loaded:
                                active_archive['items'][rid] = loaded
                                active_archive['created'][rid] = remote_chat['updated_at']
                                open_conversation(active_archive, rid)
                                st.session_state['archive_restore_notice_v0172'] = True
                                st.rerun()
                        except Exception:
                            st.error('대화를 불러오지 못했어요.')
                with del_col:
                    if st.button('영구 삭제', key='del_chat_v0172_'+rid, width='stretch'):
                        try:
                            delete_conversation(archive_owner, rid)
                            st.rerun()
                        except Exception:
                            st.error('대화를 삭제하지 못했어요.')
        else:
            st.caption('브라우저를 떠나도 대화를 보관하려면 본인 계정 연결과 저장 동의가 필요해요.')

    current_profile = (current['context'].get('recommendation_intake') or {}).get('profile') or current['context'].get('last_recommendation_profile') or {}
    with st.expander('추천 조건 확인·수정' + (' · 설정됨' if current_profile else ''), expanded=False):
        if not current_profile:
            st.caption('맞춤 추천에서 구매 조건을 알려주면 여기에 표시돼요. 조건은 대화로도 수정할 수 있어요.')
        else:
            labels = {'NONE':'입문','BASIC':'초급','INTERMEDIATE':'중급','ADVANCED':'고급',
                      'LOW':'낮음','MEDIUM':'보통','HIGH':'높음'}
            st.caption('현재 대화에 적용할 조건 · ' + str(current_profile.get('objective') or '목적 미확인')[:65])
            with st.form('edit_recommendation_v0172_'+active_archive['active']):
                objective_text = st.text_input('구매 목적', value=str(current_profile.get('objective') or '')[:120], max_chars=120)
                budget_amount = st.number_input('구매 예산 상한 (원)', min_value=0, max_value=1_000_000_000,
                    step=10_000, value=int(current_profile.get('max_budget_krw') or 0))
                skills = ['', 'NONE','BASIC','INTERMEDIATE','ADVANCED']
                risks = ['', 'LOW','MEDIUM','HIGH']
                existing_skill = str(current_profile.get('skill_level') or '')
                existing_risk = str(current_profile.get('risk_tolerance') or '')
                skill_pick = st.selectbox('개발 수준', options=skills,
                    format_func=lambda x: labels.get(x,'선택하지 않음'),
                    index=skills.index(existing_skill) if existing_skill in skills else 0)
                risk_pick = st.selectbox('위험 허용도', options=risks,
                    format_func=lambda x: labels.get(x,'선택하지 않음'),
                    index=risks.index(existing_risk) if existing_risk in risks else 0)
                tech_text = st.text_input('선호 기술 (쉼표로 구분)',
                    value=', '.join(current_profile.get('preferred_tech_stack') or [])[:160], max_chars=160)
                monthly_amount = st.number_input('월 운영비 상한 (원, 0이면 미설정)', min_value=0, max_value=1_000_000_000,
                    step=5_000, value=int(current_profile.get('max_monthly_cost_krw') or 0))
                if st.form_submit_button('이 대화의 조건 수정', width='stretch'):
                    amended = dict(current_profile)
                    for field, value in [('objective', objective_text.strip()), ('max_budget_krw',budget_amount),
                                         ('skill_level',skill_pick),('risk_tolerance',risk_pick)]:
                        if value:
                            amended[field] = value
                        else:
                            amended.pop(field, None)
                    amended['preferred_tech_stack'] = [x.strip()[:30] for x in tech_text.split(',') if x.strip()][:10]
                    if monthly_amount:
                        amended['max_monthly_cost_krw'] = int(monthly_amount)
                    else:
                        amended.pop('max_monthly_cost_krw',None)
                    current['context']['last_recommendation_profile'] = amended
                    if isinstance(current['context'].get('recommendation_intake'),dict):
                        current['context']['recommendation_intake']['profile'] = dict(amended)
                        current['context']['recommendation_intake']['waiting'] = ''
                    st.success('구매 조건을 수정했어요. 다음 추천 요청부터 적용해요. 기존 추천 결과는 소급 변경되지 않아요.')
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
                st.caption("· " + TOOL_LABELS[key] +
                           (' · 계정 연결 필요' if not token and key in (
                            'get_buyer_preferences','list_offers','get_handover','get_recent_jobs','prepare_offer') else ''))
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

# ── Main: state-aware project workbench (results first; transcript on demand). ──
online = ENABLE_OPENAI_CHAT and bool(OPENAI_API_KEY) and bool(ai_identity)
connection_error = marketplace_config_error()
mode_title = "플랫폼 설정 필요" if connection_error else "ProjectAgain API 연결"
st.markdown('''<div class="workspace-bar"><div class="workspace-name">프로젝트 작업 공간</div>
<div class="workspace-meta"><span class="status-dot"></span>{}</div></div>'''.format(escape(mode_title)), unsafe_allow_html=True)

session = current
if st.session_state.pop('archive_restore_notice_v0172', False):
    st.info('대화 문장만 불러왔어요. 원본 매물 데이터와 거래 상태는 플랫폼에서 다시 조회해 주세요.')
pending_prompt = None
workbench = workspace_view(session)
# The exact current task determines reading or comparison width. No JavaScript
# mutations or artificial scrolling; the native Streamlit document still scrolls.
mode = layout_mode(workbench['focus'])
st.markdown('<div class="pa-layout-mode pa-layout-mode--{}" aria-hidden="true"></div>'.format(mode),
            unsafe_allow_html=True)

# First entry retains the restrained welcome. After first request the current
# task result becomes the primary workspace, not a nested chat bubble.
if workbench['focus'] != 'welcome':
    with st.container(key='primary_workbench_v0173'):
        render_primary_workspace(workbench, session, actor)

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
        ("03", "실사 준비하기", "인수 전 검토 항목과 필요한 자료 먼저 확인", "프로젝트를 인수하기 전 실사에서 어떤 위험과 자료를 확인해야 하는지 알려줘. 매물을 고른 뒤 검토할게"),
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

# A pending task is secondary to the result, unless it requests immediate
# input/approval. Keep the precise progression and existing safe controls.
plan = session['context'].get('workflow')
if isinstance(plan, dict) and plan.get('status') not in ('CANCELLED',):
    view = workflow_view(plan)
    with st.container(key='workflow_summary_v0171'):
        st.markdown('**현재 작업** · ' + view['label'])
        st.caption('{} / {}단계 완료 · 미완료 {}단계'.format(view['completed'], view['total'], view['outstanding']))
        if view['total']:
            st.progress(view['fraction'])
        st.caption('다음 행동 · ' + view['next_action'])
        # Detailed steps are useful, but no longer pre-empt the conversation
        # with an always-expanded administrative panel.
        with st.expander('작업 단계 및 상세 확인', expanded=False):
            st.caption(str(plan.get('goal') or '')[:230])
            for step in view['steps']:
                st.caption('{} {} · {}{}'.format(step['icon'], step['label'], step['state'],
                    ' · ' + step['note'] if step['note'] else ''))
            if plan.get('storage_warning'):
                st.warning(plan['storage_warning'])
            remote_id = plan.get('remote_action_id')
            if remote_id and token:
                st.caption('플랫폼 초안 식별번호 · ' + str(remote_id)[:36])
                if st.button('플랫폼 초안 상태 다시 확인', key='workflow_remote_check_v015'):
                    try:
                        from core.live_actions import check_action_status
                        action = check_action_status(remote_id)
                        remote_status = str(action.get('status') or 'UNKNOWN')[:40]
                        st.info('플랫폼에서 확인된 상태 · '+friendly_state(remote_status))
                        # Approval is NOT proof of executed trade or rights transfer.
                        if remote_status in ('REJECTED','EXPIRED','CANCELLED'):
                            for step in plan.get('steps',[]):
                                if step.get('key')=='prepare_offer':
                                    step['status']='BLOCKED'
                                    step['note']='플랫폼 초안 '+friendly_state(remote_status)+' · 재확인 필요'
                            plan['status']='PARTIAL'
                        elif remote_status == 'EXECUTED':
                            for step in plan.get('steps',[]):
                                if step.get('key')=='prepare_offer':
                                    step['status']='COMPLETED'
                                    step['note']='플랫폼에서 실행 상태 확인 · 결제/권리 이전 검증과 별개'
                            plan['verified']=verify_plan(plan)
                            plan['status']='COMPLETED' if plan['verified']['fulfilled'] else 'PARTIAL'
                        _checkpoint(plan, session['context'])
                        st.rerun()
                    except Exception:
                        st.error('원격 상태 조회에 실패했어. 플랫폼에서 초안과 권한을 확인해 줘.')
            if plan.get('status') in ('PARTIAL','FAILED','INTERRUPTED') and any(
                    step.get('status') in ('PENDING','FAILED','INTERRUPTED') for step in plan.get('steps', [])):
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


if connection_error:
    st.warning(connection_error)
# The next action is tied to the currently visible result, not a permanent row
# of generic tool buttons above the conversation.
if session['turns']:
    next_prompt = show_contextual_actions(workbench, session, bool(token), uploaded)
    if next_prompt:
        pending_prompt = next_prompt
    if session['context'].get('recommendation_intake'):
        st.caption('부족한 조건은 아래 대화 입력창에 한 번에 작성해도 돼요. 취소하려면 ‘취소’라고 말해 주세요.')

# A full, accessible transcript stays in the current conversation, without a
# fixed-height nested scrollbar or a second copy of the recommendation cards.
if session['turns']:
    st.markdown('<div class="conversation-history-separator"></div>',unsafe_allow_html=True)
    with st.container(key='conversation_history_v0174'):
        with st.expander('이전 대화 및 도구 실행 기록 · {}개 메시지'.format(len(session['turns'])), expanded=False):
            st.caption('과거 답변은 당시 조회 내용을 바탕으로 해요. 실제 매물 정보와 거래 상태는 새로 확인해 주세요.')
            for i, turn in enumerate(session['turns']):
                show_turn(turn, i)

# Follow-up actions submit through exactly the same validation/tool path as typed text.
queued_followup = st.session_state.pop('queued_tool_prompt_v015', None)
if queued_followup:
    pending_prompt = queued_followup
input_hint = {
    'welcome':'예: 50만원 이하 Python 프로젝트를 찾아줘',
    'intake':'원하는 조건을 한 번에 알려주세요',
    'search':'이 중에서 어떤 프로젝트를 검토할까요?',
    'recommend':'추천 후보에 대해 더 질문하거나 조건을 바꿔 보세요',
    'inspection':'미확인 항목이나 다른 후보에 대해 질문해 보세요',
    'offer':'제안 내용과 확인이 필요한 조건을 질문할 수 있어요',
    'workflow':'부족한 정보를 알려주거나 작업을 이어가세요',
}.get(workbench['focus'], '프로젝트에 관해 질문해 주세요')
submitted_text = st.chat_input(input_hint, max_chars=2000)
submitted = submitted_text or pending_prompt
if submitted:
    if len(submitted) > 2000:
        st.error("메시지는 2000자 이내로 입력해 주세요.")
    elif contains_obvious_secret(submitted):
        add_turn(session, "assistant", "비밀정보로 보이는 입력은 처리하지 않았습니다. 민감한 정보를 제외하고 다시 요청해 주세요.")
        st.rerun()
    elif not token and request_requires_account(submitted):
        add_turn(session, 'user', submitted)
        add_turn(session, 'assistant', '이 요청은 개인 계정의 정보나 거래 권한이 필요해요. '
                 '왼쪽 **ProjectAgain 계정**에서 로그인한 후 다시 요청해 주세요. '
                 '공개 매물 검색은 연결 없이도 이용할 수 있어요.')
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
            with st.status('요청 분석 및 도구 실행 중', expanded=False, state='running') as activity:
                result = ChatAgent(actor, allow_model=bool(ai_identity)).reply(submitted, history, context)
                tool_events = [e for e in result.get('events', []) if isinstance(e, dict)]
                if tool_events and any(not e.get('success') for e in tool_events):
                    activity.update(label='일부 도구 응답을 확인할 수 없어요 · 상세 내용 확인 필요', state='error')
                elif tool_events:
                    activity.update(label='도구 응답 수신 · 검증 상태는 결과에서 확인', state='complete')
                else:
                    activity.update(label='답변 생성 단계 종료 · 도구 실행은 없음', state='complete')
        except Exception:
            result = {"content": "요청을 처리하는 동안 오류가 발생했습니다. 연결 상태를 확인한 뒤 다시 시도해 주세요.",
                      "events": [], "pending": None, "mode": "runtime_error"}
        finally:
            context.pop("attachment_bytes", None)
        # A fresh successful platform lookup makes the last search filter
        # snapshot usable again. Previous responses remain in chat history.
        if any(isinstance(e, dict) and e.get('success') and
               e.get('name') in ('search_listings','recommend_listings','inspect_listing')
               for e in result.get('events', [])):
            context.pop('_listing_snapshot_stale', None)
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
