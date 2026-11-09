from pathlib import Path
import unittest
from tests import test_engine
from tests.fixtures import meta,user,write
from chat_monitor.engine import Engine

class PublicationScopeTests(unittest.TestCase):
    setUp=test_engine.EngineTests.setUp
    def test_isolated_output_preserves_real_project_and_full_material(self):
        config={**self.config,'publication_root':str(self.root/'published')}
        engine=Engine(config)
        write(self.path,[meta('one',self.project),user('u','WHOLE_BODY')])
        engine.scan();engine.process_pending()
        chat=engine.chats['one'];self.assertEqual(chat['status'],'ready',chat.get('issues'))
        self.assertTrue(Path(chat['material_path']).is_relative_to(self.root/'published'))
        self.assertEqual(chat['project'],str(self.project).lower())
        self.assertEqual(Path(chat['material_path']).read_bytes(),b'## user\n\nWHOLE_BODY\n')
        self.assertFalse((self.project/'.codex-chat-monitor').exists())
    def test_publication_inside_watched_input_rejected(self):
        with self.assertRaisesRegex(ValueError,'publication_root_must_be_outside_input'):
            Engine({**self.config,'publication_root':str(self.logs/'output')})
    def test_restart_cannot_switch_publication_scope(self):
        Engine({**self.config,'publication_root':str(self.root/'first')})
        with self.assertRaisesRegex(ValueError,'runtime_input_scope_changed'):
            Engine({**self.config,'publication_root':str(self.root/'second')})
