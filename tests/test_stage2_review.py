"""Regression cases for the three independent stage-2 findings."""
import json
from pathlib import Path
import unittest

from chat_monitor.engine import Engine
from tests import test_engine
from tests.fixtures import meta, user, write


class Stage2ReviewTests(unittest.TestCase):
    setUp = test_engine.EngineTests.setUp

    def tick(self, engine):
        engine.scan()
        engine.process_pending()

    def adopted(self):
        engine = Engine(self.config)
        write(self.path, [meta('one', self.project), user('u', 'ORIGINAL'+' x'*150)])
        self.tick(engine)
        self.assertEqual(engine.chats['one']['status'], 'ready')
        for event in engine.outbox(): engine.ack(event['id'], {'test': 'setup'})
        return engine

    def unverified_page(self, engine):
        page = self.logs/'late.jsonl'
        row = user('late', 'IMPORTANT_LATE', turn='late')
        row['timestamp'] = '2026-11-09T04:00:00Z'
        write(page, [meta('one', self.project), row])
        good = page.read_bytes()
        page.write_bytes(good+b'BROKEN\n')
        self.tick(engine)
        self.assertEqual(engine.chats['one']['status'], 'unverified')
        return page, good

    def test_missing_unverified_page_survives_retry_and_restart(self):
        engine = self.adopted()
        page, good = self.unverified_page(engine)
        self.assertIn(str(page), engine.db['observed_sources']['one'])
        self.assertNotIn(str(page), engine.db['history']['one'])
        page.unlink()
        self.tick(engine)
        for _ in range(2):
            engine.pending.add('one'); engine.process_pending()
            self.assertEqual(engine.chats['one']['status'], 'unverified')
            self.assertIn('source_missing', str(engine.chats['one']['issues']))
        engine = Engine(self.config)
        self.tick(engine)
        self.assertEqual(engine.chats['one']['status'], 'unverified')
        page.write_bytes(good)
        self.tick(engine)
        self.assertEqual(engine.chats['one']['status'], 'ready')
        self.assertIn('IMPORTANT_LATE', Path(engine.chats['one']['material_path']).read_bytes().decode())

    def test_historical_page_found_during_adoption_retains_gap(self):
        # A pre-existing page is read only after this chat becomes active.
        write(self.path, [meta('one', self.project), user('u', 'ORIGINAL')])
        late = self.logs/'late.jsonl'
        row = user('late', 'IMPORTANT_LATE', turn='late')
        row['timestamp'] = '2026-11-09T04:00:00Z'
        write(late, [meta('one', self.project), row])
        with late.open('ab') as stream: stream.write(b'BROKEN\n')
        engine = Engine(self.config)
        write(self.path, [user('activity', 'ACTIVITY')], append=True)
        self.tick(engine)
        self.assertEqual(engine.chats['one']['status'], 'unverified')
        late.unlink(); self.tick(engine)
        engine.pending.add('one'); engine.process_pending()
        self.assertEqual(engine.chats['one']['status'], 'unverified')

    def test_uncertain_project_header_stays_associated_after_disappearance(self):
        engine = self.adopted()
        page = self.logs/'uncertain.jsonl'
        header = meta('one', self.project)
        header['payload']['cwd'] = 'relative-project'
        write(page, [header, user('uncertain', 'IMPORTANT')])
        self.tick(engine)
        self.assertEqual(engine.chats['one']['status'], 'unverified')
        self.assertIn(str(page), engine.db['observed_sources']['one'])
        page.unlink(); self.tick(engine)
        engine = Engine(self.config); self.tick(engine)
        self.assertEqual(engine.chats['one']['status'], 'unverified')

    def test_changed_identity_of_unverified_page_preserves_original_gap(self):
        engine = self.adopted()
        page, _ = self.unverified_page(engine)
        write(page, [meta('foreign', self.project), user('f', 'FOREIGN')])
        self.tick(engine)
        self.assertEqual(engine.chats['one']['status'], 'unverified')
        self.assertIn('source_missing', str(engine.chats['one']['issues']))

    def test_legacy_history_migrates_to_observed_sources(self):
        engine = self.adopted()
        engine.db.pop('observed_sources')
        engine.save()
        self.path.unlink()
        restarted = Engine(self.config)
        self.tick(restarted)
        self.assertEqual(restarted.chats['one']['status'], 'unverified')

    def test_exclusion_cancels_pending_and_preserves_other_chat(self):
        engine = Engine(self.config)
        for cid in ('one', 'two'):
            write(self.logs/(cid+'.jsonl'), [meta(cid, self.project), user('u', ' x'*150)])
        self.tick(engine)
        old = next(e for e in engine.outbox() if e['chat_id']=='one')
        levels = engine.db['notifications']['one']['levels'].copy()
        engine.exclude('one', True)
        self.assertEqual({e['chat_id'] for e in engine.outbox()}, {'two'})
        engine = Engine(self.config)
        self.assertEqual({e['chat_id'] for e in engine.outbox()}, {'two'})
        for event in engine.outbox(): engine.ack(event['id'], {'test': 'delivered'})
        engine.exclude('one', False); engine.process_pending()
        self.assertEqual(engine.chats['one']['status'], 'ready')
        self.assertEqual(engine.db['notifications']['one']['levels'], levels)
        self.assertFalse(engine.outbox())
        entries = [json.loads(line) for line in (engine.runtime/'alerts.jsonl').read_text().splitlines()]
        self.assertTrue(any(e['event']=='cancelled' and e['id']==old['id'] for e in entries))

    def test_legacy_excluded_outbox_is_cancelled_on_restart(self):
        engine = Engine(self.config)
        write(self.path, [meta('one', self.project), user('u', ' x'*150)])
        self.tick(engine)
        engine.db['excluded'] = ['one']
        engine.chats['one']['status'] = 'excluded'
        engine.save()
        restarted = Engine(self.config)
        self.assertFalse(restarted.outbox())
        self.assertEqual(restarted.chats['one']['status'], 'excluded')

    def test_sender_filters_excluded_pending_event(self):
        engine = Engine(self.config)
        write(self.path, [meta('one', self.project), user('u', ' x'*150)])
        self.tick(engine)
        engine.db['excluded'] = ['one']
        self.assertFalse(engine.outbox())

    def test_one_recovery_rearms_faults_and_keeps_budget_history_across_restart(self):
        engine = self.adopted()
        levels = engine.db['notifications']['one']['levels'].copy()
        good = self.path.read_bytes()
        self.path.write_bytes(good+b'BROKEN\n')
        self.tick(engine)
        for _ in range(2):
            engine.pending.add('one'); engine.process_pending()
        errors = [e for e in engine.outbox() if e['level']=='error']
        self.assertEqual(len(errors), 1)
        engine.ack(errors[0]['id'], {'test': 'first fault'})
        self.path.write_bytes(good); self.tick(engine)
        self.assertEqual(engine.chats['one']['status'], 'ready')
        self.assertEqual(engine.db['notifications']['one']['faults'], [])
        engine = Engine(self.config); self.tick(engine)
        self.path.write_bytes(good+b'BROKEN\n'); self.tick(engine)
        self.assertEqual(len([e for e in engine.outbox() if e['level']=='error']), 1)
        self.assertEqual(engine.db['notifications']['one']['levels'], levels)
        self.assertFalse([e for e in engine.outbox() if e['level']!='error'])
        entries = [json.loads(line) for line in (engine.runtime/'alerts.jsonl').read_text().splitlines()]
        self.assertTrue(any(e['event']=='recovered' and e['sha256'] for e in entries))
