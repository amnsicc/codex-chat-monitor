"""F3-1 event-scoped cancellation and independent shutdown regressions."""
import queue
import tempfile
import threading
import tkinter as tk
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from chat_monitor.gui import Window
from chat_monitor.storage import dump,load


class Completed:
    returncode=0
    def poll(self):return self.returncode


class CancelFailureTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)
        self.service=SimpleNamespace(runtime=self.path,config={'encoding':'cl100k_base'},
            commands=queue.Queue(),replies=queue.Queue(),stop=threading.Event())
        self.window=Window(self.service)
        dump(self.path/'state.json',{'chats':{},'outbox':[]})

    def tearDown(self):
        if not self.window.closing:
            self.window.shutdown()

    def test_cancel_failure_merges_and_keeps_refresh_scheduled(self):
        w=self.window;w.toast_jobs['event-id']=Completed()
        with patch('chat_monitor.notifications.cancel_toast',side_effect=OSError('launcher denied')) as launch:
            for _ in range(3):w.update_view()
            self.assertEqual(launch.call_count,1)
        self.assertEqual(w.cancel_failures,{'event-id':'launcher denied'})
        self.assertNotIn('event-id',w.cancel_jobs)
        self.assertIn('取消失败 1',w.status.cget('text'))
        rows=(self.path/'ui-events.jsonl').read_text(encoding='utf-8')
        self.assertEqual(rows.count('toast_cancel_failed'),1)
        self.assertIn('"removal_submitted": false',rows)
        self.assertTrue(w.root.tk.call('after','info'))

    def test_normal_cancel_receipt_stays_successful(self):
        w=self.window;w.toast_jobs['event-id']=Completed()
        dump(self.path/'delivery/event-id.cancel.json',{'removal_submitted':True})
        with patch('chat_monitor.notifications.cancel_toast',return_value=Completed()) as launch:
            w.update_view();w.update_view()
        self.assertEqual(launch.call_count,1)
        self.assertFalse(w.cancel_failures)

    def test_failed_cancel_receipt_is_reported_once(self):
        w=self.window;w.toast_jobs['event-id']=Completed()
        dump(self.path/'delivery/event-id.cancel.json',{'removal_submitted':False,'error':'rejected'})
        with patch('chat_monitor.notifications.cancel_toast',return_value=Completed()):
            w.update_view();w.update_view()
        self.assertEqual(w.cancel_failures,{'event-id':'rejected'})

    def test_unexpected_refresh_error_still_schedules_and_quit_closes(self):
        w=self.window
        with patch.object(w,'update_view',side_effect=OSError('transient state read')):
            with self.assertRaisesRegex(OSError,'transient'):w.refresh()
        self.assertTrue(w.root.tk.call('after','info'))
        w.quit()
        self.assertTrue(self.service.stop.is_set())
        with self.assertRaises(tk.TclError):w.root.winfo_exists()
