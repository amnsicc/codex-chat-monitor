import hashlib
import tempfile
import unittest
from pathlib import Path
from tests.fixtures import meta, user, assistant, completed, write
from chat_monitor.extract import extract
from chat_monitor.material import count_text

class ExtractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root/'one.jsonl'

    def run_records(self, records, tail=b''):
        write(self.path, [meta('c1', self.root), *records])
        if tail:
            with self.path.open('ab') as stream: stream.write(tail)
        return extract([self.path], 'c1')

    def test_sources_repeats_and_exact_text(self):
        literal = '  系统指令与工具调用是用户引用\n```py\nprint(1)\n```\n' + '长'*25000 + '\nEND  '
        u = user('u1', literal)
        # Host text shares the user role, but has separate structural provenance.
        host = user('host', 'HOST_SECRET', provenance='context')
        a = assistant('a1', 'same\nblock', channel='commentary')
        a['payload']['content'].append({'type':'output_text','text':'same\nblock'})
        result = self.run_records([host, u, a, completed('a1', 'same\nblock\n\nsame\nblock'),
            assistant('a2','same\nblock'), assistant('a3','HIDDEN',channel='analysis'),
            {'type':'response_item','payload':{'type':'function_call_output','call_id':'tool',
                'output':'TOOL …100 tokens truncated…'}},
            {'type':'response_item','payload':{'type':'reasoning','summary':[{'text':'THOUGHT'}]}}])
        self.assertTrue(result.complete, result.issues)
        self.assertEqual(result.text, '## user\n\n'+literal+'\n\n## assistant\n\nsame\nblock\n\nsame\nblock\n\n## assistant\n\nsame\nblock\n')
        self.assertEqual(len(result.audit['merges']), 1)

    def test_unknown_user_role_does_not_imply_user_authorship(self):
        record = user('u1','KEEP_BUT_UNVERIFIED')
        record['payload'].pop('internal_chat_message_metadata_passthrough')
        result = self.run_records([record])
        self.assertFalse(result.complete)
        self.assertTrue(any('provenance' in str(x) for x in result.issues))

    def test_user_projection_uses_turn_not_shared_id_namespace(self):
        result = self.run_records([user('retained','repeat'),
            completed('desktop','repeat',kind='UserMessage',client_id='client'),
            user('other','repeat',turn='t2')])
        self.assertTrue(result.complete, result.issues)
        self.assertEqual(result.text.count('repeat'), 2)

    def test_mixed_content_provenance_and_attachment(self):
        item = user('u1','USER')
        item['payload']['content'] += [{'type':'input_text','text':'HOST'}, {'type':'input_image','image_url':'fake'}]
        md = item['payload']['internal_chat_message_metadata_passthrough']
        md['content_item_kinds'] = ['user.text','host.context','user.image']
        md['content_item_metadata'] += [{'provenance':{'type':'context'}},{'provenance':{'type':'user'}}]
        result = self.run_records([item])
        self.assertTrue(result.complete, result.issues)
        self.assertIn('USER',result.text)
        self.assertNotIn('HOST',result.text)
        self.assertNotIn('image',result.text)

    def test_chat_truncation_and_half_line_are_not_safe(self):
        record = assistant('a','partial')
        record['payload']['truncated'] = True
        self.assertFalse(self.run_records([record]).complete)
        self.assertFalse(self.run_records([user('u','valid')], b'{"type":').complete)
        self.assertFalse(self.run_records([user('u','valid')], b'{BAD}\n').complete)
        self.assertFalse(self.run_records([{'type':'new_chat_shape','payload':{'text':'maybe chat'}}]).complete)

    def test_multiple_logs_and_identity_conflict(self):
        write(self.path,[meta('c1',self.root),user('u1','early'),assistant('a1','same')])
        second = self.root/'two.jsonl'
        write(second,[meta('c1',self.root),assistant('a1','same'),user('u2','late',turn='t2')])
        result = extract([self.path,second],'c1')
        self.assertTrue(result.complete,result.issues)
        self.assertEqual(result.text.count('early'),1)
        self.assertEqual(result.text.count('same'),1)
        self.assertEqual(result.text.count('late'),1)
        write(second,[meta('c1',self.root),assistant('a1','CHANGED')])
        self.assertFalse(extract([self.path,second],'c1').complete)
        write(second,[meta('other',self.root),user('u','foreign')])
        self.assertFalse(extract([self.path,second],'c1').complete)

    def test_full_text_count_hash_and_uncalibrated_target(self):
        result = self.run_records([user('u1','hello 世界\nhello 世界')])
        value = count_text(result.text,'cl100k_base')
        import tiktoken
        self.assertEqual(value['tokens'],len(tiktoken.get_encoding('cl100k_base').encode(result.text,disallowed_special=())))
        self.assertEqual(value['sha256'],hashlib.sha256(result.text.encode('utf-8')).hexdigest())
        self.assertFalse(value['calibrated'])
        self.assertEqual(value['target'],'gpt-6.1-sol/xhigh')
        with self.assertRaises(ValueError): count_text(result.text,'unknown_encoding')

if __name__ == '__main__': unittest.main()
