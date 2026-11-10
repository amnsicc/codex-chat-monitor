import copy
import os
import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from chat_monitor.conservative import build
from chat_monitor.extract import extract
from chat_monitor.material import count_file
from tests.fixtures import meta, user, assistant, completed, write
from tests.test_stage35_real_schema import config, harness


class ConservativeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.n=0
    def page(self,name,rows,cid='c1',project=None):
        path=self.root/name;write(path,[meta(cid,project or self.root),*rows]);return path
    def spec(self,paths):
        return {'source_id':'c1','project':str(self.root),'sources':[{'path':str(p),'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in paths]}
    def run_build(self,paths=None,spec=None,helper=None):
        self.n+=1;out=self.root/f'out{self.n}'
        result=build(spec or self.spec(paths),out,helper)
        return result,(out/'material.md').read_bytes().decode('utf-8'),out
    def test_strict_unchanged_and_candidate_retained(self):
        row=user('u','UNVERIFIED 原话');row['payload'].pop('internal_chat_message_metadata_passthrough')
        p=self.page('p.jsonl',[row]);old=extract([p],'c1')
        r,text,_=self.run_build([p]);self.assertFalse(old.complete);self.assertFalse(r['complete'])
        self.assertEqual(extract([p],'c1'),old);self.assertIn('UNVERIFIED 原话',text);self.assertTrue(r['count_valid']);self.assertFalse(r['hard_issues'])
    def test_keywords_and_true_repeats_preserved(self):
        literal='skills high max tool <environment_context> 🙂 e\u0301\r\n\r正文\n'
        p=self.page('p.jsonl',[user('u',literal),user('u2',literal)])
        _,text,_=self.run_build([p]);self.assertEqual(text.count(literal),2)
    def test_verified_config_and_spoof(self):
        rows=[]
        for effort in ('high','max'):
            row=config();row['payload']['reasoning']['effort']=effort;rows.append(row)
        p=self.page('good.jsonl',rows);_,text,_=self.run_build([p]);self.assertNotIn('"effort"',text)
        rows[0]['payload']['extra']='POTENTIAL';p=self.page('bad.jsonl',[rows[0]])
        _,text,_=self.run_build([p]);self.assertIn('POTENTIAL',text)
    def test_skill_pair_excluded_missing_or_conflict_kept(self):
        row=user('u','SKILL_BODY');md=row['payload']['internal_chat_message_metadata_passthrough']
        md['content_item_kinds']=['skills.selected_skill_instructions'];md['content_item_metadata']=[{'provenance':{'type':'skills'}}]
        p=self.page('a.jsonl',[row]);_,text,_=self.run_build([p]);self.assertNotIn('SKILL_BODY',text)
        row['payload']['content'][0]['provenance']={'type':'user'}
        p=self.page('b.jsonl',[row]);_,text,_=self.run_build([p]);self.assertIn('SKILL_BODY',text);self.assertIn('explicit_provenance_conflict',text)
        del row['payload']['content'][0]['provenance'];md['content_item_metadata']=[]
        p=self.page('c.jsonl',[row]);_,text,_=self.run_build([p]);self.assertIn('SKILL_BODY',text);self.assertIn('source_or_visibility_unverified',text)
    def test_known_harness_excluded_but_user_quote_kept(self):
        p=self.page('p.jsonl',[harness(),user('u','HOST_NOT_CHAT')]);_,text,_=self.run_build([p]);self.assertEqual(text.count('HOST_NOT_CHAT'),1)
    def test_versions_not_longest_and_no_global_dedup(self):
        p=self.page('p.jsonl',[assistant('a','SHORT'),assistant('a','SHORT LONG'),assistant('b','SHORT')])
        r,text,_=self.run_build([p]);self.assertEqual(text.count('SHORT'),3);self.assertTrue(r['soft_issues'])
    def test_multi_turn_projection_kept(self):
        p=self.page('p.jsonl',[user('u','REPEAT'),user('v','REPEAT'),completed('d','REPEAT',kind='UserMessage',client_id='x')])
        _,text,_=self.run_build([p]);self.assertEqual(text.count('REPEAT'),3)
    def test_verified_mirror_merges_cross_page(self):
        a=assistant('a','ONE');a['timestamp']='2026-11-03T00:00:01Z'
        p=self.page('p.jsonl',[a]);q=self.page('q.jsonl',[a]);_,text,_=self.run_build([p,q]);self.assertEqual(text.count('ONE'),1)
    def test_unknown_json_not_flattened_and_attachment_redacted(self):
        row={'type':'future','payload':{'nested':{'future_text':'POTENTIAL'},'attachment':{'type':'local_image','path':'SECRET_BODY'},'base64':'BINARY'}}
        p=self.page('p.jsonl',[row]);r,text,out=self.run_build([p]);self.assertIn('POTENTIAL',text);self.assertNotIn('SECRET_BODY',text);self.assertNotIn('BINARY',text)
        self.assertIn(b'SECRET_BODY',(out/'snapshots/001.jsonl').read_bytes());self.assertTrue(r['count_valid'])
    def test_unknown_part_fields_retained(self):
        row=assistant('a','BODY');row['payload']['content'][0]['future']='EXTRA'
        p=self.page('p.jsonl',[row]);_,text,_=self.run_build([p]);self.assertIn('BODY',text);self.assertIn('EXTRA',text)
    def test_bad_utf8_no_replacement_and_partial_line(self):
        p=self.page('p.jsonl',[user('u','GOOD')]);p.write_bytes(p.read_bytes()+b'\xff\n')
        r,text,_=self.run_build([p]);self.assertTrue(r['hard_issues']);self.assertNotIn('\ufffd',text);self.assertFalse(r['complete'])
        p=self.page('q.jsonl',[user('u','GOOD')]);p.write_bytes(p.read_bytes().rstrip(b'\n'))
        r,text,_=self.run_build([p]);self.assertIn('GOOD',text);self.assertTrue(any(i['reason']=='partial_final_line' for i in r['hard_issues']))
    def test_bad_json_keeps_other_lines_diagnostic(self):
        p=self.page('p.jsonl',[user('u','GOOD')]);p.write_bytes(p.read_bytes()+b'{BROKEN}\n')
        r,text,_=self.run_build([p]);self.assertIn('GOOD',text);self.assertTrue(any(i['reason']=='invalid_json_record' for i in r['hard_issues']));self.assertEqual(r['quality'],'partial_diagnostic')
    def test_identity_project_conflicts_never_mixed(self):
        for cid,project in [('other',self.root),('c1',self.root/'other')]:
            p=self.page('p.jsonl',[user('u','FOREIGN')],cid,project)
            r,text,_=self.run_build([p]);self.assertTrue(r['hard_issues']);self.assertNotIn('FOREIGN',text)
    def test_record_identity_conflict(self):
        row=completed('a','FOREIGN');row['payload']['thread_id']='other'
        p=self.page('p.jsonl',[row]);r,text,_=self.run_build([p]);self.assertTrue(r['hard_issues']);self.assertNotIn('FOREIGN',text)
    def test_missing_page_and_rewrite(self):
        p=self.page('p.jsonl',[user('u','GOOD')]);spec=self.spec([p]);p.unlink()
        r,_,_=self.run_build(spec=spec);self.assertTrue(r['hard_issues'])
        p=self.page('p.jsonl',[user('u','GOOD')]);spec=self.spec([p]);p.write_bytes(p.read_bytes()+b'\n')
        r,text,_=self.run_build(spec=spec);self.assertTrue(r['hard_issues']);self.assertNotIn('GOOD',text)
    def test_actual_truncation_hard(self):
        row=user('u','PART');row['payload']['content'][0]['truncated']=True
        p=self.page('p.jsonl',[row]);r,text,_=self.run_build([p]);self.assertIn('PART',text);self.assertTrue(r['hard_issues'])
    def test_source_changes_during_count_invalidates(self):
        p=self.page('p.jsonl',[user('u','GOOD')]);spec=self.spec([p])
        def count(path,encoding):
            result=count_file(path,encoding);p.write_bytes(p.read_bytes()+b'\n');return result
        with patch('chat_monitor.conservative.count_file',side_effect=count):r,_,_=self.run_build(spec=spec)
        self.assertFalse(r['count_valid']);self.assertTrue(r['hard_issues'])
    def test_full_bytes_labels_json_and_unicode_counted(self):
        p=self.page('p.jsonl',[user('u','\r\n🙂e\u0301\r'),{'type':'future','text':'JSON'}])
        r,text,out=self.run_build([p]);raw=(out/'material.md').read_bytes()
        self.assertEqual(r['counts'],count_file(out/'material.md','cl100k_base'));self.assertEqual(r['counts']['sha256'],hashlib.sha256(raw).hexdigest());self.assertEqual(len(text),r['counts']['characters'])
    def test_output_cannot_overwrite(self):
        p=self.page('p.jsonl',[]);r,_,out=self.run_build([p])
        with self.assertRaises(FileExistsError):build(self.spec([p]),out)
    def test_zstd_overlap_and_bad_compression(self):
        helper_name=os.environ.get('C1_ZSTD_PYTHON')
        if not helper_name:self.skipTest('set C1_ZSTD_PYTHON to an existing Python 3.14 executable')
        helper=Path(helper_name);self.assertTrue(helper.is_file())
        p=self.page('p.jsonl',[assistant('a','ONE')]);q=self.root/'q.jsonl.zst'
        q.write_bytes(subprocess.check_output([str(helper),'-I','-B','-c','from compression import zstd; import sys; sys.stdout.buffer.write(zstd.compress(sys.stdin.buffer.read()))'],input=p.read_bytes()))
        r,text,_=self.run_build([p,q],helper=helper);self.assertEqual(text.count('ONE'),1);self.assertFalse(r['hard_issues'])
        q.write_bytes(b'BAD');r,_,_=self.run_build([q],helper=helper);self.assertTrue(r['hard_issues'])
    def test_internal_tool_and_attachment_not_in_material(self):
        tool={'type':'response_item','payload':{'type':'function_call_output','output':'TOOL_SECRET'}}
        row=user('u','CAPTION');row['payload']['content'].append({'type':'local_image','path':'ATTACHMENT_SECRET'})
        p=self.page('p.jsonl',[tool,assistant('a','INTERNAL_SECRET',channel='analysis'),row])
        _,text,_=self.run_build([p]);self.assertNotIn('TOOL_SECRET',text);self.assertNotIn('INTERNAL_SECRET',text);self.assertNotIn('ATTACHMENT_SECRET',text);self.assertIn('CAPTION',text)
    def test_collaboration_requires_origin_not_name_only(self):
        row={'type':'response_item','payload':{'type':'agent_message','content':'POTENTIAL'}}
        p=self.page('p.jsonl',[row]);_,text,_=self.run_build([p]);self.assertIn('POTENTIAL',text)
        row['payload'].update(author='/root/sub',recipient='/root');row['metadata']={'client_authored':False}
        p=self.page('q.jsonl',[row]);_,text,_=self.run_build([p]);self.assertNotIn('POTENTIAL',text)
    def test_unverified_truncated_candidate_is_hard(self):
        row=user('u','PARTIAL');row['payload'].pop('internal_chat_message_metadata_passthrough')
        row['payload']['content'][0]['truncated']=True
        p=self.page('p.jsonl',[row]);r,text,_=self.run_build([p]);self.assertIn('PARTIAL',text);self.assertTrue(r['hard_issues'])
    def test_malformed_schema_yields_diagnostic_not_crash(self):
        row=user('u','POTENTIAL');row['payload']['role']=['future']
        p=self.page('p.jsonl',[row]);r,text,_=self.run_build([p]);self.assertIn('POTENTIAL',text);self.assertTrue(r['hard_issues'])
    def test_subagent_source_never_mixed(self):
        p=self.root/'sub.jsonl';write(p,[meta('c1',self.root,{'subagent':'agent'}),user('u','SUB_PRIVATE')])
        r,text,_=self.run_build([p]);self.assertTrue(r['hard_issues']);self.assertNotIn('SUB_PRIVATE',text)
    def test_unknown_origin_is_soft_not_fake_hard(self):
        row=user('u','POTENTIAL');row['payload']['internal_chat_message_metadata_passthrough']['content_item_metadata']=[{'provenance':{'type':['future']}}]
        p=self.page('p.jsonl',[row]);r,text,_=self.run_build([p]);self.assertIn('POTENTIAL',text);self.assertFalse(r['hard_issues']);self.assertTrue(r['soft_issues'])


if __name__=='__main__':unittest.main()
