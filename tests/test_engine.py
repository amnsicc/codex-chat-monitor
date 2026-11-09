import json
import tempfile
import unittest
from pathlib import Path
from tests.fixtures import meta, user, assistant, write
from chat_monitor.engine import Engine
from chat_monitor.policy import transition

class EngineTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name); self.logs=self.root/'logs'; self.logs.mkdir()
        self.project=self.root/'project'; self.project.mkdir()
        self.config={'sessions_root':str(self.logs),'runtime':str(self.root/'runtime'),
            'allowed_projects':[str(self.project)],'budget':100,'encoding':'cl100k_base',
            'reserves':{'host':100,'prompt':100,'metadata':100,'output':100,'reasoning':100,'safety':100}}
        self.path=self.logs/'old.jsonl'

    def test_baseline_activity_multiple_logs_and_exclusion(self):
        write(self.path,[meta('old',self.project),user('u','historical')])
        engine=Engine(self.config)
        engine.scan(); engine.process_pending()
        self.assertFalse(engine.chats)
        write(self.path,[assistant('a','new')],append=True)
        engine.scan(); engine.process_pending()
        first=engine.chats['old']
        self.assertEqual(first['status'],'ready')
        self.assertIn('historical',Path(first['material_path']).read_text(encoding='utf-8'))
        old_activity=first['activity']
        write(self.path,[{'type':'response_item','timestamp':'2026-11-03T01:00:00Z',
            'payload':{'type':'function_call_output','output':'TOOL'}}],append=True)
        engine.scan(); engine.process_pending()
        self.assertEqual(engine.chats['old']['activity'],old_activity)
        page=self.logs/'continuation.jsonl'
        write(page,[meta('old',self.project),dict(user('u2','continued',turn='t2'), timestamp='2026-11-03T02:00:00Z')])
        engine.scan(); engine.process_pending()
        self.assertEqual(engine.chats['old']['status'],'ready')
        text=Path(engine.chats['old']['material_path']).read_text(encoding='utf-8')
        self.assertIn('historical',text); self.assertIn('continued',text)
        engine.exclude('old',True)
        write(page,[user('u3','excluded_add',turn='t3')],append=True)
        engine.scan(); engine.process_pending()
        self.assertEqual(engine.chats['old']['status'],'excluded')
        restarted=Engine(self.config)
        self.assertEqual(restarted.chats['old']['status'],'excluded')
        restarted.exclude('old',False); restarted.process_pending()
        self.assertIn('excluded_add',Path(restarted.chats['old']['material_path']).read_text(encoding='utf-8'))

    def test_half_line_recovery_identity_and_source_loss(self):
        engine=Engine(self.config)
        write(self.path,[meta('one',self.project),user('u1','good')])
        with self.path.open('ab') as f: f.write(b'{"type":')
        engine.scan(); engine.process_pending()
        self.assertEqual(engine.chats['one']['status'],'unverified')
        self.assertNotIn('tokens',engine.chats['one'])
        with self.path.open('ab') as f: f.write(b'"event_msg","payload":{"type":"task_complete"}}\n')
        engine.scan(); engine.process_pending()
        self.assertEqual(engine.chats['one']['status'],'ready')
        write(self.path,[meta('one',self.project),user('u2','short')])
        engine.scan(); engine.process_pending()
        self.assertEqual(engine.chats['one']['status'],'unverified')
        self.assertIn('source_rewritten',str(engine.chats['one']['issues']))

    def test_subagents_and_unauthorized_projects_never_write(self):
        engine=Engine(self.config)
        write(self.logs/'sub.jsonl',[meta('sub',self.project,{'subagent':{'parent_thread_id':'p'}}),user('u','internal')])
        write(self.logs/'outside.jsonl',[meta('outside',self.root/'outside'),user('u','no write')])
        engine.scan(); engine.process_pending()
        self.assertNotIn('sub',engine.chats)
        self.assertEqual(engine.chats['outside']['status'],'unverified')
        self.assertFalse((self.root/'outside').exists())

    def test_restart_alert_history_and_same_title_distinct_ids(self):
        engine=Engine(self.config)
        for cid in ['a','b']:
            header=meta(cid,self.project); header['payload']['title']='same title'
            write(self.logs/(cid+'.jsonl'),[header,user('u','hello '*400)])
        engine.scan(); engine.process_pending()
        self.assertEqual(set(engine.chats),{'a','b'})
        events=engine.outbox()
        self.assertEqual(len(events),2)
        for event in events: engine.ack(event['id'],{'delivery':'test-only'})
        restarted=Engine(self.config); restarted.scan(); restarted.process_pending()
        self.assertFalse(restarted.outbox())

class PolicyTests(unittest.TestCase):
    def test_four_boundaries_crossing_and_recovery(self):
        state={}
        for value,want in [(49,None),(50,'50'),(74,None),(75,'75'),(90,'90'),(100,None),(101,'over')]:
            state,event=transition(state,value,'policy-1',100)
            self.assertEqual(event['level'] if event else None,want)
        state,event=transition(state,None,'policy-1',100,'read_error')
        self.assertEqual(event['level'],'error')
        state,event=transition(state,None,'policy-1',100,'read_error'); self.assertIsNone(event)
        state,event=transition(state,101,'policy-1',100); self.assertIsNone(event)
        state,event=transition(json.loads(json.dumps(state)),101,'policy-1',100); self.assertIsNone(event)
        state,event=transition(state,101,'new-policy',100); self.assertEqual(event['level'],'over')
        state,event=transition({},101,'p',100)
        self.assertEqual(event['level'],'over'); self.assertEqual(event['crossed'],['50','75','90','over'])

if __name__=='__main__':unittest.main()
