import hashlib
from pathlib import Path
import unittest
from unittest.mock import patch

from chat_monitor import discovery
from chat_monitor.engine import Engine
from chat_monitor.material import count_file
from chat_monitor.storage import load
from tests import test_engine
from tests.fixtures import meta, user, write


class Stage2Tests(unittest.TestCase):
    setUp = test_engine.EngineTests.setUp

    def test_transient_read_permission_error_retries(self):
        with patch.object(Path, 'read_text', side_effect=[PermissionError(13, 'busy'), '{"ok":true}']):
            with patch('chat_monitor.storage.time.sleep'):
                self.assertTrue(load(self.root/'state.json')['ok'])

    def test_atomic_publish_keeps_temporary_basename_short(self):
        from chat_monitor.storage import atomic_bytes
        directory = self.root / ('d' * 110)
        name_length = 245 - len(str(directory)) - 1
        path = directory / ('m' * name_length)
        atomic_bytes(path, b'raw\r\nbytes')
        self.assertEqual(path.read_bytes(), b'raw\r\nbytes')

    def test_equal_time_disconnected_pages_remain_ambiguous(self):
        engine = Engine(self.config)
        for name in ('a', 'b'):
            write(self.logs / (name+'.jsonl'), [meta('one', self.project), user(name, name)])
        engine.scan(); engine.process_pending()
        self.assertEqual(engine.chats['one']['status'], 'unverified')
        self.assertIn('ambiguous_cross_source_order', str(engine.chats['one']['issues']))

    def test_baseline_and_recovery_read_only_adopted_bodies(self):
        for name in ('active', 'idle'):
            write(self.logs / (name+'.jsonl'), [meta(name, self.project), user(name, name)])
        with patch('chat_monitor.discovery.header', side_effect=AssertionError('body baseline')):
            engine = Engine(self.config)
        write(self.logs/'active.jsonl', [user('new', 'NEW', turn='t2')], append=True)
        from chat_monitor.engine import extract
        seen = []
        def capture(paths, cid):
            seen.extend(paths)
            return extract(paths, cid)
        with patch('chat_monitor.engine.extract', side_effect=capture):
            engine.scan(); engine.process_pending()
        self.assertEqual(set(seen), {self.logs/'active.jsonl'})
        self.assertNotIn('idle', engine.chats)

    def test_file_created_between_baseline_and_first_scan_is_found(self):
        engine = Engine(self.config)
        write(self.path, [meta('one', self.project), user('u', 'NEW')])
        engine.scan(); engine.process_pending()
        self.assertEqual(engine.chats['one']['status'], 'ready')

    def test_immutable_material_and_old_cutoff_on_failure(self):
        engine = Engine(self.config)
        write(self.path, [meta('one', self.project), user('u', 'a\r\nb\rc\n🙂')])
        engine.scan(); engine.process_pending()
        first = dict(engine.chats['one'])
        raw = Path(first['material_path']).read_bytes()
        self.assertEqual(first['sha256'], hashlib.sha256(raw).hexdigest())
        self.assertEqual(first['tokens'], count_file(first['material_path'], 'cl100k_base')['tokens'])
        for i in range(3):
            write(self.path, [user('next'+str(i), 'next', turn='next'+str(i))], append=True)
            engine.scan(); engine.process_pending()
        self.assertEqual(Path(first['material_path']).read_bytes(), raw)
        latest = dict(engine.chats['one'])
        with self.path.open('ab') as stream: stream.write(b'BROKEN\n')
        engine.scan(); engine.process_pending()
        invalid = engine.chats['one']
        self.assertNotIn('tokens', invalid)
        self.assertEqual(invalid['budget_label'], '无法判断')
        self.assertEqual(invalid['previous_reference']['cutoff'], latest['cutoff'])
        self.assertEqual(load(engine.runtime/'state.json')['chats']['one'], invalid)

    def test_count_error_recovers_without_resetting_alerts(self):
        engine = Engine(self.config)
        write(self.path, [meta('one', self.project), user('u', 'hello '*200)])
        engine.scan(); engine.process_pending()
        for event in engine.outbox(): engine.ack(event['id'], {'test': True})
        levels = dict(engine.db['notifications']['one']['levels'])
        engine.pending.add('one')
        with patch('chat_monitor.engine.count_file', side_effect=ValueError('count failed')):
            engine.process_pending()
        self.assertEqual(engine.chats['one']['status'], 'unverified')
        engine.pending.add('one'); engine.process_pending()
        self.assertEqual(engine.chats['one']['status'], 'ready')
        self.assertEqual(engine.db['notifications']['one']['levels'], levels)
        self.assertFalse([e for e in engine.outbox() if e['level'] != 'error'])

    def test_missing_file_recovery_and_changed_budget(self):
        engine = Engine(self.config)
        write(self.path, [meta('one', self.project), user('u', 'hello '*200)])
        engine.scan(); engine.process_pending()
        original = self.path.read_bytes()
        self.path.unlink(); engine.scan(); engine.process_pending()
        self.assertEqual(engine.chats['one']['status'], 'unverified')
        self.path.write_bytes(original); engine.scan(); engine.process_pending()
        self.assertEqual(engine.chats['one']['status'], 'ready')
        restarted = Engine({**self.config, 'budget': 200})
        self.assertEqual(restarted.chats['one']['status'], 'processing')
        self.assertNotIn('tokens', restarted.chats['one'])
        self.assertIn('cutoff', restarted.chats['one']['previous_reference'])
        restarted.process_pending()
        self.assertNotEqual(restarted.policy, engine.policy)
        self.assertEqual(set(restarted.db['notifications']['one']['levels']), {engine.policy, restarted.policy})
