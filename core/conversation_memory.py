"""Small, source-attributed, session-scoped context snapshot for the LLM.

Do not treat old free-text summaries as verified facts or persist raw chat.
The confirmed preference and workflow stores are authoritative. This module
never calls the model, saves credentials or runs a background worker.
"""
import json

from core.llm_service import contains_obvious_secret


def build_context_digest(context, transcript, max_chars=1800):
    """Deterministic, bounded digest in addition to the last chat turns."""
    blocks = []
    profile = (context.get('recommendation_intake') or {}).get('profile') or context.get('last_recommendation_profile')
    if isinstance(profile,dict):
        keys = ('objective','max_budget_krw','max_monthly_cost_krw','skill_level',
                'risk_tolerance','preferred_tech_stack','preferred_categories',
                'qualitative_preferences','require_preferred_stack')
        clean = {k: profile[k] for k in keys if k in profile and profile[k] is not None}
        if clean:
            blocks.append('사용자가 확인한/수집 중인 구매 조건 (미확정 여부 확인 필요): '+
                          json.dumps(clean,ensure_ascii=False,default=str)[:850])
    plan = context.get('workflow')
    if isinstance(plan,dict):
        steps = [{ 'step':s.get('key'), 'state':s.get('status')} for s in plan.get('steps',[])[:5]]
        blocks.append('현재 작업 단계 (이 기록은 실행 결과의 요약이지 거래 승인 아님): '+
                      json.dumps({'goal':str(plan.get('goal') or '')[:100],
                                  'status':plan.get('status'), 'steps':steps},ensure_ascii=False)[:520])
    last = context.get('recent_listings') or []
    if isinstance(last,list) and last:
        # Server verified IDs are the source of truth for references like '첫 번째'.
        blocks.append('현재 대화에서 고정된 매물 순서: '+json.dumps([
            {'id':str(x.get('id') or '')[:36], 'title':str(x.get('title') or '')[:60]}
            for x in last[:3] if isinstance(x,dict)],ensure_ascii=False)[:450])
    # Briefly preserve old user intent as unverified utterances, not as profile facts.
    older = [x for x in transcript[:-10] if x.get('role') == 'user']
    quotes=[]
    for item in older[-3:]:
        value = str(item.get('content') or '').replace('\n',' ')[:105]
        if value and not contains_obvious_secret(value):
            quotes.append(value)
    if quotes:
        blocks.append('이전 요청 참고(조건으로 확정하지 말 것): '+ ' / '.join(quotes))
    digest = '\n'.join(blocks)[:max_chars]
    return digest if not contains_obvious_secret(digest) else ''
