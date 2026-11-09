import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from tests.fixtures import meta,user,write
from chat_monitor.engine import Engine
from chat_monitor.prepare import prepare,verify_package,read_chunk

class PrepareTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.logs=self.root/'input';self.logs.mkdir()
        self.project=self.root/'project';self.project.mkdir()
        self.config={'sessions_root':str(self.logs),'runtime':str(self.root/'runtime'),
            'allowed_projects':[str(self.project)],'budget':10000,'encoding':'cl100k_base'}
        self.engine=Engine(self.config);self.path=self.logs/'s.jsonl'
        write(self.path,[meta('source-id',self.project),user('u1','  长行'+('界'*8000)+'\nREPEAT\nREPEAT  ')])
        self.engine.scan();self.engine.process_pending();self.value=self.engine.chats['source-id']

    def test_frozen_material_matches_count_and_survives_growth(self):
        package=prepare(self.value)
        before=(package/'material.md').read_bytes()
        manifest=verify_package(package)
        self.assertEqual(manifest['sha256'],self.value['sha256'])
        self.assertEqual(manifest['source_id'],'source-id')
        self.assertEqual(manifest['tokens'],self.value['tokens'])
        write(self.path,[user('u2','NEW GROWTH',turn='t2')],append=True)
        self.engine.scan();self.engine.process_pending()
        self.assertEqual((package/'material.md').read_bytes(),before)
        self.assertTrue(verify_package(package))
        launch=(package/'launch.txt').read_text(encoding='utf-8')
        self.assertIn('$conversation-context-migrator',launch)
        self.assertIn(str(package/'manifest.json'),launch)

    def test_stale_unverified_or_tampered_material_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'not_ready'):prepare({**self.value,'status':'processing'})
        original=Path(self.value['material_path']).read_bytes()
        Path(self.value['material_path']).write_bytes(original+b'TAMPER')
        with self.assertRaisesRegex(ValueError,'hash'):prepare(self.value)
        Path(self.value['material_path']).write_bytes(original)
        write(self.path,[user('u2','grew',turn='t2')],append=True)
        with self.assertRaisesRegex(ValueError,'source_changed'):prepare(self.value)

    def test_bounded_lossless_chunks_and_tamper_detection(self):
        package=prepare(self.value)
        manifest=verify_package(package)
        pieces=[];offset=0
        while offset<manifest['characters']:
            part=read_chunk(package,offset,max_characters=997)
            self.assertEqual(part['start'],offset)
            self.assertLessEqual(len(part['text']),997)
            pieces.append(part['text']);offset=part['end']
            self.assertIn(part['chunk_sha256'],part['end_marker'])
        self.assertEqual(''.join(pieces),(package/'material.md').read_text(encoding='utf-8'))
        (package/'material.md').write_bytes(b'corrupt')
        with self.assertRaisesRegex(ValueError,'hash'):verify_package(package)

    def test_project_and_input_paths_cannot_be_redirected(self):
        with self.assertRaisesRegex(ValueError,'material_path'):
            prepare({**self.value,'project':str(self.root/'foreign')})
        with self.assertRaises(ValueError):read_chunk(prepare(self.value),-1)

if __name__=='__main__':unittest.main()
