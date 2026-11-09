import queue
import tempfile
import threading
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from tests import test_engine
from tests.fixtures import meta,user,write
from chat_monitor.engine import Engine
from chat_monitor.gui import Window

class DesktopEventTests(unittest.TestCase):
    setUp=test_engine.EngineTests.setUp

    def test_stale_receipt_after_replacement_and_exclusion_is_ignored(self):
        engine=Engine(self.config)
        write(self.path,[meta('one',self.project),user('u','hello')])
        engine.scan();engine.process_pending()
        engine.notify('one',50)
        old=engine.outbox()[0]['id']
        engine.notify('one',90)
        current=engine.outbox()[0]['id']
        self.assertFalse(engine.ack(old,{'interaction':'automation'}))
        self.assertEqual(engine.outbox()[0]['id'],current)
        engine.exclude('one',True)
        self.assertFalse(engine.ack(current,{'interaction':'automation'}))
        self.assertFalse(engine.outbox())

    def test_submission_launch_failure_is_retained_without_retry_storm(self):
        service=SimpleNamespace(runtime=self.root,config={'encoding':'cl100k_base'},commands=queue.Queue(),
                                replies=queue.Queue(),stop=threading.Event())
        window=Window(service)
        event={'id':'e','chat_id':'one','title':'same','level':'50','tokens':50,'budget':100}
        try:
            with patch('chat_monitor.notifications.toast',side_effect=OSError('launch failed')) as launch:
                window.deliver([event]);window.deliver([event])
            self.assertEqual(launch.call_count,1)
            self.assertIn('e',window.failed)
            self.assertTrue(service.commands.empty())
        finally:window.root.destroy()
