"""Regression contracts for stage-1 F1--F7; synthetic files only."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from tests.fixtures import meta,user,assistant,completed,write
from chat_monitor.extract import extract
from chat_monitor.material import count_text

class Stage1RevisionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
    def page(self,name,records):
        path=self.root/name
        write(path,[meta('c1',self.root),*records]);return path
    def one(self,records):return extract([self.page('one.jsonl',records)],'c1')

    def test_f4_invalid_utf8_is_a_located_failure_without_replacement_body(self):
        path=self.page('bad.jsonl',[user('u','BEFORE_BAD_AFTER')])
        path.write_bytes(path.read_bytes().replace(b'BAD',b'\xff'))
        result=extract([path],'c1')
        self.assertFalse(result.complete)
        self.assertEqual(result.text,'')
        self.assertNotIn('\ufffd',result.text)
        problem=next(x for x in result.issues if x['reason']=='invalid_utf8')
        self.assertEqual(problem['source'],str(path))
        self.assertEqual(problem['line'],2)
        self.assertEqual(path.read_bytes()[problem['byte_offset']],255)
        self.assertEqual(result.sources[0]['sha256'],hashlib.sha256(path.read_bytes()).hexdigest())

    def test_f4_literal_replacement_character_and_embedded_newlines_are_not_damage(self):
        text='  🙂 e\u0301\t\r\n正文\r末尾\n\ufffd  '
        path=self.page('valid.jsonl',[user('u',text)])
        # Physical JSONL CRLF and embedded escaped CR/LF have different roles.
        path.write_bytes(path.read_bytes().replace(b'\n',b'\r\n'))
        result=extract([path],'c1')
        self.assertTrue(result.complete,result.issues)
        self.assertEqual(result.text,'## user\n\n'+text+'\n')
        ref=result.audit['messages'][0]['refs'][0]
        self.assertEqual(ref['line_text_sha256'],hashlib.sha256(path.read_bytes().splitlines(keepends=True)[1]).hexdigest())

    def test_f1_internal_phase_is_excluded_and_unknown_visibility_is_unverified(self):
        for fields,reason in [({'phase':'analysis','channel':None},None),
                ({'channel':'summary'},'unsupported_assistant_channel'),
                ({'phase':'future_private_phase','channel':None},'unsupported_assistant_phase'),
                ({'phase':{'unexpected':'object'}},'unsupported_assistant_phase')]:
            with self.subTest(fields=fields):
                row=assistant('a','INTERNAL_OR_UNVERIFIED');row['payload'].update(fields)
                result=self.one([row])
                self.assertNotIn('INTERNAL_OR_UNVERIFIED',result.text)
                if reason:
                    self.assertFalse(result.complete)
                    self.assertTrue(any(i['reason']==reason for i in result.issues))
                else:self.assertTrue(result.complete,result.issues)
        row=completed('a','DESKTOP_INTERNAL',phase='analysis')
        self.assertNotIn('DESKTOP_INTERNAL',self.one([row]).text)

    def test_f1_visible_progress_final_and_explicit_phase_only_are_preserved(self):
        for row in [assistant('a','KEEP',channel='commentary'),assistant('a','KEEP'),
                completed('a','KEEP',phase='final_answer'),completed('a','KEEP')]:
            with self.subTest(row=row):
                result=self.one([row]);self.assertTrue(result.complete,result.issues)
                self.assertEqual(result.text,'## assistant\n\nKEEP\n')
        row=assistant('a','PHASE_ONLY',channel=None);row['payload']['phase']='final_answer'
        result=self.one([row]);self.assertTrue(result.complete,result.issues)
        self.assertIn('PHASE_ONLY',result.text)

    def test_f6_only_checked_text_fields_are_rendered(self):
        for row,item in [(user('u','VISIBLE_TEXT'),None),(completed('u','VISIBLE_TEXT',kind='UserMessage',client_id='c'),True)]:
            target=row['payload']['item'] if item else row['payload']
            target['content'][0].update(summary='UNVERIFIED_EXTRA_FIELD',output='UNVERIFIED_OUTPUT',
                content=[{'type':'text','text':'NESTED_EXTRA'}])
            result=self.one([row])
            self.assertTrue(result.complete,result.issues)
            self.assertEqual(result.text,'## user\n\nVISIBLE_TEXT\n')
            self.assertTrue(result.audit['sources'][0]['fields_excluded'])

    def test_f6_text_looking_like_json_and_repeated_parts_remains_literal(self):
        row=user('u','{"summary":"this is user literal"}')
        result=self.one([row])
        self.assertTrue(result.complete,result.issues)
        self.assertEqual(result.text,'## user\n\n{"summary":"this is user literal"}\n')

    def test_f5_original_positions_and_text_fields_survive_filtering(self):
        row=user('u','HOST')
        row['payload']['content'].append({'type':'input_text','text':'HUMAN'})
        md=row['payload']['internal_chat_message_metadata_passthrough']
        md['content_item_metadata']=[{'provenance':{'type':'context'}},{'provenance':{'type':'user'}}]
        md['content_item_kinds']=['host.context','user.text']
        result=self.one([row]);self.assertTrue(result.complete,result.issues)
        ref=result.audit['messages'][0]['refs'][0]
        self.assertEqual(ref['content_positions'],['payload.content[1]'])
        self.assertEqual(ref['text_fields'],['payload.content[1].text'])
        included=result.audit['sources'][0]['included'][0]
        self.assertEqual(included['positions'],[1])
        self.assertEqual(result.text,'## user\n\nHUMAN\n')

    def test_f5_completed_inline_text_ref_does_not_invent_content_array(self):
        row=completed('a','text')
        row['payload']['item'].pop('content');row['payload']['item']['text']='INLINE'
        result=self.one([row]);self.assertTrue(result.complete,result.issues)
        ref=result.audit['messages'][0]['refs'][0]
        self.assertEqual(ref['content_positions'],[])
        self.assertEqual(ref['text_fields'],['payload.item.text'])

    def multiblock(self,mid,parts,turn='t1'):
        row=user(mid,parts[0],turn=turn)
        row['payload']['content']=[{'type':'input_text','text':p} for p in parts]
        md=row['payload']['internal_chat_message_metadata_passthrough']
        md['content_item_kinds']=['user.text']*len(parts)
        md['content_item_metadata']=[{'provenance':{'type':'user'}} for _ in parts]
        return row

    def test_f2_multiple_user_parts_and_completed_projection_merge_without_losing_parts(self):
        for parts in [['alpha','beta'],['same','same']]:
            row=self.multiblock('native',parts)
            desktop=completed('desktop','\n\n'.join(parts),kind='UserMessage',client_id='client')
            result=self.one([row,desktop]);self.assertTrue(result.complete,result.issues)
            self.assertEqual(result.text,'## user\n\n'+'\n\n'.join(parts)+'\n')
            self.assertEqual(len(result.audit['messages']),1)
            self.assertEqual(len(result.audit['messages'][0]['refs']),2)
            self.assertEqual(result.audit['merges'][0]['reason'],'desktop_unique_user_turn_projection')

    def test_f2_ambiguous_projection_is_retained_and_not_verified(self):
        a=self.multiblock('native-a',['a','b']);b=self.multiblock('native-b',['a','b'])
        desktop=completed('desktop','a\n\nb',kind='UserMessage',client_id='client')
        result=self.one([a,b,desktop])
        self.assertFalse(result.complete)
        self.assertEqual(len(result.audit['messages']),3)
        self.assertTrue(any(i['reason']=='ambiguous_desktop_user_turn_projection' for i in result.issues))

    def test_f2_identical_blocks_in_separate_turns_are_two_real_messages(self):
        result=self.one([self.multiblock('a',['same','same'],'t1'),
            completed('da','same\n\nsame',turn='t1',kind='UserMessage',client_id='c1'),
            self.multiblock('b',['same','same'],'t2'),
            completed('db','same\n\nsame',turn='t2',kind='UserMessage',client_id='c2')])
        self.assertTrue(result.complete,result.issues)
        self.assertEqual(len(result.audit['messages']),2)
        self.assertEqual(result.text.count('same'),4)

    def test_f7_completed_user_respects_explicit_mixed_provenance(self):
        row=completed('desktop','HUMAN',kind='UserMessage',client_id='c')
        item=row['payload']['item']
        item['content'].append({'type':'text','text':'HOST_DESKTOP'})
        item['internal_chat_message_metadata_passthrough']={'content_item_kinds':['user.text','host.context'],
            'content_item_metadata':[{'provenance':{'type':'user'}},{'provenance':{'type':'context'}}]}
        result=self.one([row]);self.assertTrue(result.complete,result.issues)
        self.assertEqual(result.text,'## user\n\nHUMAN\n')
        self.assertEqual(result.audit['messages'][0]['refs'][0]['content_positions'],['payload.item.content[0]'])

    def test_f7_incomplete_or_conflicting_metadata_is_not_overridden_by_client_id(self):
        metadata_cases=[{'content_item_metadata':[]},
            {'content_item_kinds':['host.context'],'content_item_metadata':[{'provenance':{'type':'user'}}]},
            {'content_item_metadata':[{'provenance':{'type':'future'}}]},
            {'content_item_metadata':['not an object']}]
        for md in metadata_cases:
            with self.subTest(metadata=md):
                row=completed('desktop','UNVERIFIED',kind='UserMessage',client_id='c',
                    internal_chat_message_metadata_passthrough=md)
                result=self.one([row]);self.assertFalse(result.complete)
                self.assertNotIn('UNVERIFIED',result.text)

    def test_f7_absent_desktop_metadata_retains_supported_client_projection(self):
        result=self.one([completed('d','NORMAL',kind='UserMessage',client_id='c')])
        self.assertTrue(result.complete,result.issues)
        self.assertEqual(result.text,'## user\n\nNORMAL\n')

    def test_f3_overlap_order_is_independent_of_page_argument_order(self):
        rows={mid:assistant(mid,mid.upper()) for mid in 'abcd'}
        for row in rows.values():row['timestamp']='2026-11-03T00:00:00Z'
        a=self.page('p1.jsonl',[rows[mid] for mid in 'abc'])
        b=self.page('p2.jsonl',[rows[mid] for mid in 'bcd'])
        forward=extract([a,b],'c1');reverse=extract([b,a],'c1')
        for result in [forward,reverse]:
            self.assertTrue(result.complete,result.issues)
            self.assertEqual([m['id'] for m in result.audit['messages']],list('abcd'))
        self.assertEqual(forward.text,reverse.text)

    def test_f3_timezone_offsets_are_compared_as_instants_between_pages(self):
        older=assistant('a','OLDER');older['timestamp']='2026-11-03T08:00:00+08:00'
        newer=assistant('b','NEWER');newer['timestamp']='2026-11-03T00:01:00Z'
        a=self.page('z-older.jsonl',[older]);b=self.page('a-newer.jsonl',[newer])
        for paths in [[a,b],[b,a]]:
            result=extract(paths,'c1');self.assertTrue(result.complete,result.issues)
            self.assertEqual([m['id'] for m in result.audit['messages']],['a','b'])
            self.assertEqual(result.activity,'2026-11-03T00:01:00Z')
        same=self.one([older,newer]);self.assertTrue(same.complete,same.issues)
        self.assertEqual([m['id'] for m in same.audit['messages']],['a','b'])

    def test_f3_equal_unrelated_pages_report_ambiguity_instead_of_silent_tie_break(self):
        a=assistant('a','A');b=assistant('b','B')
        a['timestamp']=b['timestamp']='2026-11-03T00:00:00Z'
        pa=self.page('a.jsonl',[a]);pb=self.page('b.jsonl',[b])
        for paths in [[pa,pb],[pb,pa]]:
            result=extract(paths,'c1');self.assertFalse(result.complete)
            self.assertTrue(any(i['reason']=='ambiguous_cross_source_order' for i in result.issues))
            self.assertEqual(len(result.audit['messages']),2)

    def test_f3_conflicting_page_order_is_an_explicit_cycle(self):
        a=assistant('a','A');b=assistant('b','B')
        a['timestamp']=b['timestamp']='2026-11-03T00:00:00Z'
        pa=self.page('a.jsonl',[a,b]);pb=self.page('b.jsonl',[b,a])
        result=extract([pb,pa],'c1')
        self.assertFalse(result.complete)
        self.assertTrue(any(i['reason']=='conflicting_source_message_order' for i in result.issues))
        self.assertEqual(len(result.audit['messages']),2)

    def test_f3_invalid_timestamp_is_reported_without_reordering_single_source(self):
        a=assistant('a','A');a['timestamp']='not-an-instant'
        result=self.one([a,assistant('b','B')])
        self.assertFalse(result.complete)
        self.assertTrue(any(i['reason']=='unsupported_message_timestamp' for i in result.issues))
        self.assertEqual([m['id'] for m in result.audit['messages']],['a','b'])

    def test_f3_activity_compares_fractional_instants_not_normalized_strings(self):
        a=assistant('a','A');a['timestamp']='2026-11-03T00:00:00Z'
        b=assistant('b','B');b['timestamp']='2026-11-03T00:00:00.123456Z'
        result=self.one([a,b]);self.assertTrue(result.complete,result.issues)
        self.assertEqual(result.activity,'2026-11-03T00:00:00.123456Z')

    def test_f7_non_scalar_provenance_is_located_unverified_input(self):
        row=completed('d','DO_NOT_PROMOTE',kind='UserMessage',client_id='c',
            internal_chat_message_metadata_passthrough={'content_item_metadata':[{'provenance':{'type':['user']}}]})
        result=self.one([row]);self.assertFalse(result.complete)
        self.assertNotIn('DO_NOT_PROMOTE',result.text)

    def test_f6_empty_and_whitespace_parts_keep_their_original_positions_in_text(self):
        row=self.multiblock('u',['FIRST','','  ','LAST'])
        result=self.one([row]);self.assertTrue(result.complete,result.issues)
        self.assertEqual(result.text,'## user\n\nFIRST\n\n\n\n  \n\nLAST\n')
        spaces=self.one([user('s',' \t  ')])
        self.assertTrue(spaces.complete,spaces.issues)
        self.assertEqual(spaces.text,'## user\n\n \t  \n')
        empty=self.one([user('e','')])
        self.assertTrue(empty.complete,empty.issues)
        self.assertEqual(empty.text,'## user\n\n\n')
        self.assertEqual(len(empty.audit['messages']),1)

    def test_newline_material_file_counter_uses_raw_bytes_and_strict_utf8(self):
        import chat_monitor.material as material
        self.assertTrue(callable(getattr(material,'count_file',None)))
        text='## user\n\n🙂 e\u0301\t\r\n原话\r结尾\n'
        path=self.root/'material.md';path.write_bytes(text.encode('utf-8'))
        result=material.count_file(path,'cl100k_base')
        self.assertEqual(result['sha256'],hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertEqual(result['newline_policy'],'preserve_embedded_crlf_cr_lf')
        self.assertNotEqual(result['sha256'],hashlib.sha256(path.read_text(encoding='utf-8').encode('utf-8')).hexdigest())
        import tiktoken
        self.assertEqual(result['tokens'],len(tiktoken.get_encoding('cl100k_base').encode(text,disallowed_special=())))
        path.write_bytes(b'BAD\xff')
        with self.assertRaises(UnicodeDecodeError):material.count_file(path,'cl100k_base')

if __name__=='__main__':unittest.main()
