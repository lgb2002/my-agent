"""v0.19.1 safety and latency regression tests; no network or credentials."""
import ast
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from core.chat_performance import (cloud_list, invalidate_cloud_list, conversation_revision,
    visible_tail, DEFAULT_VISIBLE_TURNS)
from core.activity_progress import (describe_tool, ProgressMetrics, TOOL_ACTIVITIES)
from core.chat_sessions import new_session, append_turn

ROOT = Path(__file__).resolve().parents[1]


class NavigationPerfTest(unittest.TestCase):
    def test_list_cache_owner_isolation(self):
        cache = {}; reads=[]
        def fetch(owner):
            reads.append(owner)
            return [{'id': owner, 'title': 'owner-specific'}]
        for _ in range(3):
            self.assertEqual(cloud_list(cache,'alice',fetch,now=100), [{'id':'alice','title':'owner-specific'}])
        self.assertEqual(reads,['alice'])
        self.assertEqual(cloud_list(cache,'bob',fetch,now=101)[0]['id'],'bob')
        self.assertEqual(reads,['alice','bob'])

    def test_ttl_and_invalidation(self):
        cache={}; n=[]
        def fetch(owner):
            n.append(len(n))
            return list(n)
        self.assertEqual(cloud_list(cache,'user',fetch,now=0,ttl=10),[0])
        self.assertEqual(cloud_list(cache,'user',fetch,now=9,ttl=10),[0])
        self.assertEqual(cloud_list(cache,'user',fetch,now=11,ttl=10),[0,1])
        invalidate_cloud_list(cache,'user')
        self.assertEqual(cloud_list(cache,'user',fetch,now=12,ttl=10),[0,1,2])

    def test_revision_avoids_full_json_serialization(self):
        session=new_session()
        self.assertEqual(conversation_revision(session),0)
        append_turn(session,'user','예산 40만원')
        self.assertEqual(conversation_revision(session),1)
        append_turn(session,'assistant','현재 매물을 확인했어요',events=[{'name':'search_listings'}])
        self.assertEqual(conversation_revision(session),2)

    def test_long_history_is_not_discarded(self):
        turns=[{'role':'user','content':str(i)} for i in range(100)]
        offset,shown=visible_tail(turns,DEFAULT_VISIBLE_TURNS)
        self.assertEqual(offset,100-DEFAULT_VISIBLE_TURNS)
        self.assertEqual(shown[-1]['content'],'99')
        self.assertEqual(len(turns),100)
        self.assertEqual(visible_tail(turns,120)[0],0)


class ActivityTest(unittest.TestCase):
    def test_only_allowlisted_korean_statuses(self):
        self.assertIn('검색', describe_tool('search_listings'))
        self.assertIn('검사', describe_tool('inspect_attached_zip'))
        self.assertIn('도구', describe_tool('attacker_SECRET_HERE'))
        self.assertNotIn('SECRET', describe_tool('attacker_SECRET_HERE'))
        self.assertEqual(len(TOOL_ACTIVITIES),9)

    def test_metrics_have_no_prompt_or_token_data(self):
        times=iter([0, 1, 2.5, 3, 4.5, 5.0])
        metrics=ProgressMetrics(clock=lambda:next(times))
        metrics.event('model_start')
        metrics.event('model_done')
        metrics.event('tool_start','search_listings')
        metrics.event('tool_done','search_listings',True)
        report=metrics.report()
        self.assertEqual(report['model_s'],1.5)
        self.assertEqual(report['tool_s'],1.5)
        self.assertEqual(report['tool_calls'],1)
        self.assertNotIn('password',str(report))

    def test_agent_progress_is_real_invoke_boundary(self):
        from agent.chat import ChatAgent
        class Event:
            success=True
            def to_dict(self):return {'success':True}
        events=[]
        with patch('agent.chat.ToolDispatcher') as dispatcher:
            dispatcher.return_value.invoke.return_value=(Event(),None)
            agent=ChatAgent('viewer',progress=lambda *args:events.append(args))
            result=agent._invoke({},'search_listings',{'query':''})
        self.assertEqual(result[0].success, True)
        self.assertEqual([x[0] for x in events],['tool_start','tool_done'])
        self.assertTrue(events[-1][2])

    def test_agent_never_interrupts_tool_if_ui_fails(self):
        from agent.chat import ChatAgent
        class Event: success=True
        with patch('agent.chat.ToolDispatcher') as dispatcher:
            dispatcher.return_value.invoke.return_value=(Event(),None)
            agent=ChatAgent('viewer',progress=lambda *_: (_ for _ in ()).throw(ValueError('UI crash')))
            self.assertTrue(agent._invoke({},'search_listings',{})[0].success)

    def test_workflow_callbacks_only_on_actual_invocation(self):
        src=(ROOT/'agent/workflow.py').read_text('utf8')
        self.assertIn("progress('tool_start', name, None)",src)
        self.assertIn("progress('tool_done', name, bool(event.success))",src)
        self.assertIn('if kind == \'prepare_offer\' and not ENABLE_LIVE_DRAFTS:',src)


class PoolAndUiTest(unittest.TestCase):
    def test_pool_bounded_and_reused_by_connection_string(self):
        from core import pg_pool
        pools=[]
        class FakePool:
            def __init__(self,**kw):
                pools.append(kw)
                self.con=object()
            def connection(self):
                class Context:
                    def __enter__(inner):return self.con
                    def __exit__(inner,*args):pass
                return Context()
        with patch.dict(sys.modules,{'psycopg_pool':types.SimpleNamespace(ConnectionPool=FakePool)}):
            with pg_pool.connection('postgresql://test:user@mock:5432/postgres') as c1: pass
            with pg_pool.connection('postgresql://test:user@mock:5432/postgres') as c2: pass
        self.assertIs(c1,c2)
        self.assertEqual(len(pools),1)
        self.assertLessEqual(pools[0]['max_size'],6)
        self.assertEqual(pools[0]['min_size'],0)
        self.assertTrue(pools[0]['kwargs']['sslmode']=='require')

    def test_app_keeps_verified_identity_and_avoids_duplicate_reruns(self):
        src=(ROOT/'app.py').read_text('utf8')
        ast.parse(src)
        self.assertIn('cloud_list(cloud_list_cache, cloud_owner',src)
        self.assertIn('login.owner_key if connected and login',src)
        self.assertIn('on_click=_request_conversation_selection',src)
        self.assertIn('on_click=_request_new_conversation',src)
        self.assertIn('for i, turn in enumerate(visible_turns, start=offset):',src)
        self.assertIn("if session.get('pending'):",src)
        self.assertIn('st.chat_message(\'assistant\'',src)
        self.assertIn('save_conversation(cloud_owner, active_archive',src)

    def test_sidebar_controls_compact_not_trade_controls(self):
        css=(ROOT/'assets/style.css').read_text('utf8')
        self.assertIn('.st-key-compact_account_popover_v0191',css)
        self.assertIn('height:35px !important;max-height:35px',css)
        self.assertIn('height:34px !important;max-height:34px',css)
        self.assertIn('@media (max-width:760px)',css)
        self.assertIn('with st.container(key=\'compact_account_popover_v0191\')',
                      (ROOT/'app.py').read_text('utf8'))

    def test_temporary_metrics_do_not_replace_auth_or_quotas(self):
        source=(ROOT/'app.py').read_text('utf8')
        self.assertIn('set_broker_access_handler(ensure_fresh)',source)
        self.assertIn('set_ai_identity(ai_identity)',source)
        self.assertIn('submit_confirmed_draft(pending)',source)
        self.assertIn('ENABLE_LIVE_DRAFTS',source)
        self.assertIn('st.session_state[\'last_performance_v0191\']',source)

if __name__ == '__main__':
    unittest.main()
