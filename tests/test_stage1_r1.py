"""Stage-1 regression for conflicting explicit sources on user text parts."""
from pathlib import Path
import tempfile
import unittest

from chat_monitor.extract import extract
from tests.fixtures import completed, meta, user, write


class Stage1ProvenanceTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / 'source.jsonl'

    def extract_parts(self, representation, metadata_type, part_type):
        if representation == 'native':
            row = user('u', 'CHECK_SOURCE')
            item = row['payload']
        else:
            row = completed('u', 'CHECK_SOURCE', kind='UserMessage', client_id='client')
            item = row['payload']['item']
        first = item['content'][0]
        if part_type is not None:
            first['provenance'] = {'type': part_type}
        item['content'].append({'type': first['type'], 'text': 'VERIFIED_NEIGHBOR'})
        metadata = item.setdefault('internal_chat_message_metadata_passthrough', {})
        metadata['content_item_kinds'] = [
            'user.text' if metadata_type == 'user' else 'host.context', 'user.text',
        ]
        metadata['content_item_metadata'] = [
            {'provenance': {'type': metadata_type}}, {'provenance': {'type': 'user'}},
        ]
        write(self.path, [meta('r1', self.path.parent), row])
        return extract([self.path], 'r1')

    def test_host_metadata_conflicts_with_user_part(self):
        self.assert_source_conflict('context', 'user')

    def test_user_metadata_conflicts_with_host_part(self):
        self.assert_source_conflict('user', 'context')

    def assert_source_conflict(self, metadata_type, part_type):
        for representation in ('native', 'completed'):
            with self.subTest(representation=representation):
                result = self.extract_parts(representation, metadata_type, part_type)
                self.assertFalse(result.complete)
                self.assertEqual(result.text, '## user\n\nVERIFIED_NEIGHBOR\n')
                self.assertEqual(result.issues, [{
                    'source': str(self.path),
                    'line': 2,
                    'position': 0,
                    'reason': 'conflicting_part_provenance',
                    'metadata_provenance_type': metadata_type,
                    'part_provenance_type': part_type,
                }])
                source_audit = result.audit['sources'][0]
                self.assertEqual(source_audit['parts_excluded'], [])
                self.assertEqual(source_audit['included'][0]['positions'], [1])

    def test_matching_user_source_preserves_text(self):
        self.assert_resolved_source('user', 'user')

    def test_matching_host_source_excludes_text(self):
        self.assert_resolved_source('context', 'context')

    def test_absent_part_source_uses_supported_metadata(self):
        for metadata_type in ('user', 'context'):
            self.assert_resolved_source(metadata_type, None)

    def assert_resolved_source(self, metadata_type, part_type):
        for representation in ('native', 'completed'):
            with self.subTest(representation=representation, metadata_type=metadata_type,
                              part_type=part_type):
                result = self.extract_parts(representation, metadata_type, part_type)
                self.assertTrue(result.complete, result.issues)
                self.assertEqual(result.issues, [])
                source_audit = result.audit['sources'][0]
                if metadata_type == 'user':
                    self.assertEqual(result.text, '## user\n\nCHECK_SOURCE\n\nVERIFIED_NEIGHBOR\n')
                    self.assertEqual(source_audit['parts_excluded'], [])
                    self.assertEqual(source_audit['included'][0]['positions'], [0, 1])
                else:
                    self.assertEqual(result.text, '## user\n\nVERIFIED_NEIGHBOR\n')
                    self.assertEqual(source_audit['parts_excluded'], [
                        {'line': 2, 'position': 0, 'reason': 'host_provenance'},
                    ])
                    self.assertEqual(source_audit['included'][0]['positions'], [1])
