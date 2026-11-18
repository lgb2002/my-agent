"""User-facing factual task progress. Never infer a completed API action."""

TOOL_ACTIVITIES = {
    'search_listings': '등록된 프로젝트를 검색하고 있어요',
    'recommend_listings': '구매 조건에 맞는 후보를 비교하고 있어요',
    'inspect_listing': '매물의 공개 자료와 위험 항목을 확인하고 있어요',
    'inspect_attached_zip': '첨부된 ZIP 파일을 정적으로 검사하고 있어요',
    'get_buyer_preferences': '저장된 구매 조건을 조회하고 있어요',
    'list_offers': '구매 제안 내역을 확인하고 있어요',
    'get_handover': '인수인계 현황을 확인하고 있어요',
    'get_recent_jobs': '이전 작업 기록을 조회하고 있어요',
    'prepare_offer': '구매 제안 초안을 준비하고 있어요',
}


def describe_tool(name):
    """Safe Korean message, never echo attacker-controlled tool arguments."""
    return TOOL_ACTIVITIES.get(str(name), '요청한 도구 작업을 처리하고 있어요')


class ProgressMetrics:
    """Non-sensitive wall-clock stage durations; no prompts, tokens or URLs."""
    def __init__(self, clock=None):
        import time
        self.clock = clock or time.perf_counter
        self.started = self.clock()
        self._current = {}
        self.times = {}
        self.tool_results = []

    def event(self, stage, name=None, success=None):
        if stage.endswith('_start'):
            self._current[(stage[:-6], name)] = self.clock()
        elif stage.endswith('_done'):
            key = (stage[:-5], name)
            begun = self._current.pop(key, None)
            if begun is not None:
                duration = max(0, self.clock() - begun)
                self.times[stage[:-5]] = round(self.times.get(stage[:-5], 0) + duration, 3)
            if stage == 'tool_done':
                self.tool_results.append({'tool': describe_tool(name), 'success': bool(success)})

    def report(self):
        return {'total_s': round(max(0, self.clock() - self.started), 3),
                'model_s': self.times.get('model', 0),
                'tool_s': self.times.get('tool', 0),
                'tool_calls': len(self.tool_results)}
