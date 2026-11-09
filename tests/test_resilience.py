import hashlib
import json
import subprocess
import os
import unittest
from pathlib import Path
from unittest.mock import patch
from tests import test_engine
from tests.fixtures import meta,user,write
from chat_monitor.engine import Engine
from chat_monitor.material import count_text, count_file
from chat_monitor.storage import load
from chat_monitor.storage import atomic_bytes

class ResilienceTests(unittest.TestCase):
    setUp = test_engine.EngineTests.setUp
    # These test observable failures at OS/file/worker boundaries, not private fields.
    def test_powershell_utf8_receipt_is_readable(self):
        receipt=self.root/'receipt.json'
        result=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',
            "@{submitted=$true} | ConvertTo-Json | Set-Content -LiteralPath $env:CHAT_MONITOR_TEST_RECEIPT -Encoding UTF8"],
            capture_output=True,env={**os.environ,'CHAT_MONITOR_TEST_RECEIPT':str(receipt)})
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertTrue(load(receipt)['submitted'])

    def test_change_while_tokenizing_is_not_published_as_current(self):
        engine=Engine(self.config)
        write(self.path,[meta('one',self.project),user('u1','early')])
        engine.scan()
        def count_and_append(path,encoding):
            measured=count_file(path,encoding)
            write(self.path,[user('u2','arrived while counting',turn='t2')],append=True)
            return measured
        with patch('chat_monitor.engine.count_file',side_effect=count_and_append):engine.process_pending()
        self.assertNotEqual(engine.chats['one']['status'],'ready')
        self.assertNotIn('tokens',engine.chats['one'])
        engine.scan();engine.process_pending()
        self.assertEqual(engine.chats['one']['status'],'ready')
        self.assertIn('arrived while counting',Path(engine.chats['one']['material_path']).read_text(encoding='utf-8'))

    def test_missing_previously_adopted_page_after_restart_is_not_complete(self):
        engine=Engine(self.config)
        write(self.path,[meta('one',self.project),user('u1','early')])
        second=self.logs/'second.jsonl'
        write(second,[meta('one',self.project),dict(user('u2','late',turn='t2'), timestamp='2026-11-03T02:00:00Z')])
        engine.scan();engine.process_pending()
        self.assertEqual(engine.chats['one']['status'],'ready')
        self.assertIn(str(self.path),engine.db['history']['one'])
        self.path.unlink()
        restarted=Engine(self.config);restarted.scan();restarted.process_pending()
        self.assertEqual(restarted.chats['one']['status'],'unverified')
        self.assertIn('source_missing',str(restarted.chats['one']['issues']))

    def test_header_identity_change_invalidates_original_chat(self):
        engine=Engine(self.config)
        write(self.path,[meta('one',self.project),user('u1','original')])
        engine.scan();engine.process_pending()
        write(self.path,[meta('two',self.project),user('u2','foreign')])
        engine.scan();engine.process_pending()
        self.assertEqual(engine.chats['one']['status'],'unverified')
        self.assertNotIn('tokens',engine.chats['one'])

    def test_new_policy_does_not_deliver_obsolete_pending_levels(self):
        engine=Engine(self.config)
        write(self.path,[meta('one',self.project),user('u','hello')])
        engine.scan();engine.process_pending()
        engine.notify('one',50);engine.notify('one',75);engine.notify('one',101)
        self.assertEqual([e['level'] for e in engine.outbox() if e['chat_id']=='one'],['over'])

    def test_changed_runtime_input_does_not_reuse_foreign_state(self):
        engine=Engine(self.config)
        write(self.path,[meta('one',self.project),user('u1','private scope')])
        engine.scan();engine.process_pending()
        other=self.root/'otherlogs';other.mkdir()
        with self.assertRaisesRegex(ValueError,'runtime_input_scope_changed'):
            Engine({**self.config,'sessions_root':str(other)})

    def test_atomic_publish_waits_for_short_windows_reader_lock(self):
        import ctypes
        import threading
        import time
        target=self.root/'state.json';target.write_bytes(b'old')
        dll=ctypes.WinDLL('kernel32',use_last_error=True)
        dll.CreateFileW.restype=ctypes.c_void_p
        dll.CreateFileW.argtypes=[ctypes.c_wchar_p,ctypes.c_ulong,ctypes.c_ulong,ctypes.c_void_p,ctypes.c_ulong,ctypes.c_ulong,ctypes.c_void_p]
        dll.CloseHandle.argtypes=[ctypes.c_void_p]
        handle=dll.CreateFileW(str(target),0x80000000,1,None,3,0,None)
        self.assertNotEqual(handle,ctypes.c_void_p(-1).value)
        def close_later():time.sleep(.08);dll.CloseHandle(handle)
        thread=threading.Thread(target=close_later);thread.start()
        try:atomic_bytes(target,b'new')
        finally:thread.join()
        self.assertEqual(target.read_bytes(),b'new')
