"""Safe, display-only historic tool snapshots (v0.19.0).

Snapshots are historical evidence; NEVER feed them into a write/replay context,
restore a pending approval, or consider them current prices or ownership.
Allowlist every nested field; no arbitrary API responses, auth, identity, files,
or tool arguments may be persisted.
"""
from datetime import datetime, timezone
from core.llm_service import contains_obvious_secret

# Each field must be intentionally declared. Non-displayed API internals vanish.
LISTING = {'id':None,'title':None,'price_krw':None,'category':None,
           'tech_stack':[None,10],'verification_status':None,'description':None}
RECOMMEND_ENTRY = {'listing_id':None,'title':None,'price_krw':None,'score':None,
                   'base_score':None,'qualitative_adjustment':None,'risk_label':None,
                   'uncertainty_count':None,'reasons':[None,8],'risks':[None,8],
                   'risk_dimensions':[{'label':None,'status':None,'explanation':None},10],
                   'qualitative_assessments':[{'verdict':None,'preference':None,'evidence_quote':None},8]}
CRITERIA = {'max_budget_krw':None,'min_budget_krw':None,'max_monthly_cost_krw':None,
            'skill_level':None,'risk_tolerance':None,'objectives':[None,3],
            'preferred_tech_stack':[None,10], 'require_preferred_stack':None,
            'preferred_categories':[None,10], 'max_results':None}
FINDING = {'finding_id':None,'title':None,'recommendation':None,'severity':None,
           'status':None,'description':None,'evidence':None}
REPORT = {'verdict':None,'dynamic_execution':None,'status':None,
          'summary':None,'findings':[FINDING,40]}
ALLOWED = {
 'search_listings': {'query':None,'listings':[LISTING,15],'next_cursor':None,'total_estimate':None},
 'recommend_listings': {'ranked':[RECOMMEND_ENTRY,5],'eligible_count':None,
     'criteria':CRITERIA,'status':None,'excluded_count':None,
     'excluded_reasons':[None,8], 'qualitative_review_status':None,
     'qualitative_preferences':[None,10]},
 'compare': {'ranked':[RECOMMEND_ENTRY,5],'eligible_count':None,'criteria':CRITERIA},
 'inspect_listing': {'listing_id':None,'listing_title':None,'status':None,'report':REPORT},
 'inspect_attached_zip': {'listing_title':None,'status':None,'report':REPORT},
 'list_offers': {'listing_title':None, 'offers': [
     {'id':None,'price_krw':None,'status':None,'version':None,'proposed_by':None},20]},
 'get_handover': {'checks': [
     {'id':None,'status':None,'title':None,'label':None,'verified':None,'completed':None},30]},
 'get_buyer_preferences': {'buyer_preferences':CRITERIA},
 'get_recent_jobs': {'jobs':[
     {'id':None,'job_id':None,'task_type':None,'status':None,'created_at':None,'updated_at':None},12]},
 # Proposed purchase terms may be shown in message text, but no reusable
 # signed draft, approval token or request object is snapshotted.
}


def _scalar(value):
    if isinstance(value, str):
        text = value[:500]
        return '[민감정보 제외]' if contains_obvious_secret(text) else text
    if value is None or type(value) in (bool, int, float):
        return value
    return None


def _pick(value, schema, depth=0):
    if depth > 5:
        return None
    if schema is None:
        return _scalar(value)
    if isinstance(schema, dict):
        if not isinstance(value, dict):
            return {}
        return {key:_pick(value[key], rule, depth+1)
                for key,rule in schema.items() if key in value}
    if isinstance(schema, list):
        if not isinstance(value, list):
            return []
        rule, limit = schema
        return [_pick(item, rule, depth+1) for item in value[:limit]]
    return None


def capture_event(event, *, captured_at=None):
    """Return presentation-only fields. Invalid/unsafe tools have no data."""
    if not isinstance(event, dict):
        return None
    name = str(event.get('name') or '')[:48]
    if not name:
        return None
    safe = {}
    for key,size in [('name',48),('label',70),('summary',350)]:
        text = str(event.get(key) or '')[:size]
        safe[key] = '[민감정보 제외]' if contains_obvious_secret(text) else text
    safe['success'] = event.get('success') is True
    timestamp = captured_at or event.get('captured_at')
    if isinstance(timestamp, str):
        try:
            date = datetime.fromisoformat(timestamp.replace('Z','+00:00'))
            if date.tzinfo:
                safe['captured_at'] = date.isoformat()
        except (ValueError, OverflowError):
            pass
    if safe['success'] and name in ALLOWED and isinstance(event.get('data'), dict):
        safe['data'] = _pick(event['data'], ALLOWED[name])
        safe['historical'] = True
    return safe


def refresh_prompt(event):
    """Read-only new request, not a replay of cached tool invocation."""
    if not isinstance(event, dict) or not event.get('success'):
        return None
    name = event.get('name')
    data = event.get('data') or {}
    if name == 'search_listings':
        query = data.get('query') if isinstance(data,dict) else ''
        if isinstance(query,str) and query and len(query) <= 100:
            return '현재 플랫폼에서 ' + query + ' 매물을 새로 검색해줘'
        return '현재 등록된 매물 목록 보여줘'
    if name in ('recommend_listings','compare'):
        return '현재 플랫폼 매물을 기준으로 맞춤 추천을 다시 진행해줘. 필요한 조건을 다시 확인해줘'
    if name == 'inspect_listing':
        listing_id = data.get('listing_id') if isinstance(data,dict) else None
        from uuid import UUID
        if isinstance(listing_id,str):
            try:
                if str(UUID(listing_id)) == listing_id.lower():
                    return listing_id + ' 매물의 최신 공개 정보를 검토해줘'
            except (ValueError,AttributeError):
                pass
        return '현재 등록된 매물 목록 보여줘'
    return None


def historic_listing_references(turns):
    """Pinned UUIDs for explicit fresh lookups; NEVER restore result or cursor.

    This is a navigation aid, not a saved transaction/execution context.
    A subsequent tool invocation resolves UUIDs against the live platform.
    """
    from uuid import UUID
    for turn in reversed(turns):
        if not isinstance(turn,dict):
            continue
        for event in reversed(turn.get('events') or []):
            if not isinstance(event,dict) or not event.get('success'):
                continue
            data = event.get('data') or {}
            if not isinstance(data,dict):
                continue
            if event.get('name') == 'search_listings':
                entries = data.get('listings') or []
                key = 'id'
            elif event.get('name') in ('recommend_listings','compare'):
                entries = data.get('ranked') or []
                key = 'listing_id'
            else:
                continue
            pinned=[]
            for entry in entries[:15]:
                if not isinstance(entry,dict):
                    continue
                ident = entry.get(key)
                try:
                    if not isinstance(ident,str) or str(UUID(ident)) != ident.lower():
                        continue
                except (ValueError,TypeError,AttributeError):
                    continue
                pinned.append({'id':ident,'title':str(entry.get('title') or '')[:95]})
            if pinned:
                return pinned
    return []
