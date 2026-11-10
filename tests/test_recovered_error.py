import unittest
from tests import test_stage2_review as review
from tests.fixtures import meta,user,write
from chat_monitor.engine import Engine

class RecoveredErrorTests(unittest.TestCase):
    setUp=review.Stage2ReviewTests.setUp
    tick=review.Stage2ReviewTests.tick
    adopted=review.Stage2ReviewTests.adopted
    def fault(self,e):
        good=self.path.read_bytes();self.path.write_bytes(good+b'BROKEN\n');self.tick(e)
        self.assertEqual(e.chats['one']['status'],'unverified')
        return good,next(x for x in e.outbox() if x['chat_id']=='one' and x['level']=='error')
    def test_recovery_retires_queued_error_and_keeps_history(self):
        e=self.adopted();good,old=self.fault(e)
        self.path.write_bytes(good);self.tick(e)
        self.assertEqual(e.chats['one']['status'],'ready');self.assertNotIn(old['id'],{x['id'] for x in e.outbox()})
        self.assertFalse(e.ack(old['id'],{'interaction':'automation'}))
        self.assertIn('error_resolved',(e.runtime/'alerts.jsonl').read_text())
    def test_continuous_fault_dedup_then_new_fault_and_late_ack(self):
        e=self.adopted();good,old=self.fault(e)
        for _ in range(3):e.pending.add('one');e.process_pending()
        self.assertEqual([x['id'] for x in e.outbox()],[old['id']])
        self.path.write_bytes(good);self.tick(e);self.path.write_bytes(good+b'BROKEN\n');self.tick(e)
        new=e.outbox()[0];self.assertNotEqual(new['id'],old['id'])
        self.assertFalse(e.ack(old['id'],{'interaction':'human'}));self.assertEqual(e.outbox()[0]['id'],new['id'])
    def test_other_chat_and_budget_not_cleared(self):
        e=self.adopted();good,old=self.fault(e)
        write(self.logs/'two.jsonl',[meta('two',self.project),user('u','OTHER')]);self.tick(e)
        e.invalidate('two','unverified',[{'reason':'other'}]);e.notify('two',None,'other')
        e.notify('one',100000);protected={x['id'] for x in e.outbox() if x['id']!=old['id']}
        levels=e.db['notifications']['one']['levels'].copy()
        self.path.write_bytes(good);self.tick(e)
        self.assertEqual({x['id'] for x in e.outbox()},protected)
        self.assertEqual(e.db['notifications']['one']['levels'],levels)
        self.assertFalse(e.ack(old['id'],{}));self.assertEqual({x['id'] for x in e.outbox()},protected)
    def test_restart_then_recovery_and_legacy_ready_outbox(self):
        e=self.adopted();good,old=self.fault(e);e=Engine(self.config)
        self.assertIn(old['id'],{x['id'] for x in e.outbox()})
        self.path.write_bytes(good);self.tick(e);self.assertFalse(e.outbox())
        # Simulate old persisted ready state with an unresolved historic error ID.
        e.db['outbox'].append(old);e.save();e=Engine(self.config)
        self.tick(e);self.assertFalse(e.outbox())
    def test_new_budget_crossing_after_fault_keeps_prior_levels(self):
        self.config['budget']=1000;e=self.adopted()
        for tokens,level in [(500,'50'),(750,'75'),(900,'90'),(1001,'over')]:
            e.notify('one',tokens);event=e.outbox()[0];self.assertEqual(event['level'],level)
            e.ack(event['id'],{'interaction':'automation','confirmed_by_user':False})
            levels=e.db['notifications']['one']['levels'].copy()
            good,old=self.fault(e);self.path.write_bytes(good);self.tick(e)
            self.assertEqual(e.db['notifications']['one']['levels'],levels)
            e=Engine(self.config);self.tick(e)
            self.assertEqual(e.db['notifications']['one']['levels'],levels)
            e.notify('one',tokens);self.assertFalse(e.outbox())

    def test_actual_counting_race_is_unverified_then_resolved_on_verified_retry(self):
        from unittest.mock import patch
        from chat_monitor import engine as module
        e=self.adopted();original=module.count_file
        def race(*args,**kwargs):
            result=original(*args,**kwargs)
            write(self.path,[user('late','LATE',turn='t2')],append=True)
            return result
        e.pending.add('one')
        with patch('chat_monitor.engine.count_file',side_effect=race):e.process_pending()
        self.assertEqual(e.chats['one']['status'],'unverified')
        old=next(x for x in e.outbox() if x['level']=='error')
        self.assertEqual(old['reason'],'source_changed_while_counting')
        e.process_pending();self.assertEqual(e.chats['one']['status'],'ready')
        self.assertIn('LATE',__import__('pathlib').Path(e.chats['one']['material_path']).read_text())
        self.assertNotIn(old['id'],{x['id'] for x in e.outbox()})

if __name__=='__main__':unittest.main()
