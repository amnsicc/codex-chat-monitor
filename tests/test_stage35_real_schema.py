"""Finite real-schema adaptation boundaries. Synthetic variants never edit real input."""
import copy,hashlib,json,tempfile,unittest
from pathlib import Path
from chat_monitor.extract import extract
from tests.fixtures import meta,user,assistant,completed,write

def harness(kind='environments.environment_context'):
    row=user('host','HOST_NOT_CHAT')
    md=row['payload']['internal_chat_message_metadata_passthrough']
    md['content_item_kinds']=[kind]
    md['content_item_metadata']=[{'provenance':{'type':'harness','hook':False}}]
    return row

def desktop(mid='a',text='VISIBLE',turn='t1',**fields):
    row=completed(mid,text,turn=turn,phase='final_answer',**fields)
    row['payload']['item']['content'][0]['type']='Text'
    return row

def config():
    return {'type':'response_item','payload':{'type':'configuration_update','reasoning':{'effort':'xhigh'}},
            'metadata':{'client_authored':False,'harness_authored_configuration':True}}

def usage():
    counters={'input_tokens':10,'cached_input_tokens':0,'cache_write_input_tokens':0,
        'output_tokens':3,'reasoning_output_tokens':1,'total_tokens':13}
    return {'type':'token_usage_record','payload':{'thread_id':'c1','session_id':'c1','turn_id':'t1',
        'root_turn_id':'t1','response_id':'resp_test','usage':counters,
        'turn_token_usage':dict(counters),'thread_token_usage':dict(counters)}}

class RealSchemaTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
    def page(self,name,rows):
        path=self.root/name;write(path,[meta('c1',self.root),*rows]);return path
    def one(self,rows):return extract([self.page('one.jsonl',rows)],'c1')
    def bad(self,row,reason=None):
        result=self.one([row]);self.assertFalse(result.complete,result.issues)
        if reason:self.assertTrue(any(i['reason']==reason for i in result.issues),result.issues)
        return result

    def test_known_harness_pairs_excluded_with_explicit_audit(self):
        for kind in ('environments.environment_context','additional_content.codex_apps_open_page'):
            with self.subTest(kind=kind):
                row=harness(kind);p=row['payload']['content'][0]
                p['provenance']={'type':'harness','hook':False}
                result=self.one([row,user('u','HUMAN')]);self.assertTrue(result.complete,result.issues)
                self.assertEqual(result.text,'## user\n\nHUMAN\n')
                audit=result.audit['sources'][0]['parts_excluded']
                self.assertEqual(audit[0],{'line':2,'position':0,'reason':'verified_harness_context','kind':kind})

    def test_harness_requires_exact_kind_origin_hook_and_part_shape(self):
        variants=[]
        for kind in ('user.text','host.context','future.harness',None,{},[]):
            row=harness();row['payload']['internal_chat_message_metadata_passthrough']['content_item_kinds']=[kind];variants.append(row)
        for source in ({'type':'harness'},{'type':'harness','hook':True},{'type':'harness','hook':0},
                {'type':'harness','hook':False,'future':True}):
            row=harness();row['payload']['internal_chat_message_metadata_passthrough']['content_item_metadata']=[{'provenance':source}];variants.append(row)
        row=harness();row['payload']['content'][0]['type']='Text';variants.append(row)
        row=harness();row['payload']['content'][0]['text']={'text':'maybe'};variants.append(row)
        row=harness();row['payload']['internal_chat_message_metadata_passthrough'].pop('content_item_kinds');variants.append(row)
        row=harness();row['payload']['content'][0]['provenance']={'type':'harness','hook':0};variants.append(row)
        for row in variants:
            with self.subTest(row=row):self.bad(row)

    def test_harness_source_conflicts_both_directions_precede_exclusion(self):
        for reverse in (False,True):
            row=harness()
            if reverse:
                row=user('u','CONFLICT')
                row['payload']['content'][0]['provenance']={'type':'harness','hook':False}
            else:row['payload']['content'][0]['provenance']={'type':'user'}
            result=self.bad(row,'conflicting_part_provenance')
            self.assertEqual(result.audit['sources'][0]['parts_excluded'],[])

    def test_harness_missing_provenance_and_completed_forgery_unverified(self):
        row=harness();row['payload']['internal_chat_message_metadata_passthrough']['content_item_metadata']=[{}]
        self.bad(row)
        row=completed('u','HOST_NOT_CHAT',kind='UserMessage',client_id='client')
        row['payload']['item']['internal_chat_message_metadata_passthrough']=harness()['payload']['internal_chat_message_metadata_passthrough']
        self.bad(row)

    def test_user_literals_named_like_host_metadata_and_Text_remain_literal(self):
        literal='<environment_context>harness configuration_update token_usage_record Text</environment_context>'
        result=self.one([user('u',literal)])
        self.assertTrue(result.complete,result.issues);self.assertEqual(result.text,'## user\n\n'+literal+'\n')

    def test_mixed_harness_and_repeated_user_blocks_keep_original_positions_and_projection(self):
        row=harness();item=row['payload'];md=item['internal_chat_message_metadata_passthrough']
        item['content'] += [{'type':'input_text','text':'SAME'},{'type':'input_text','text':'SAME'}]
        md['content_item_kinds'] += ['user.text','user.text']
        md['content_item_metadata'] += [{'provenance':{'type':'user'}},{'provenance':{'type':'user'}}]
        mirror=completed('desk','SAME\n\nSAME',kind='UserMessage',client_id='client')
        result=self.one([row,mirror]);self.assertTrue(result.complete,result.issues)
        self.assertEqual(result.text,'## user\n\nSAME\n\nSAME\n')
        self.assertEqual(len(result.audit['messages']),1)
        ref=result.audit['messages'][0]['refs'][0]
        self.assertEqual(ref['content_positions'],['payload.content[1]','payload.content[2]'])
        self.assertEqual(result.audit['merges'][0]['kept_refs'][0]['text_fields'],['payload.content[1].text','payload.content[2].text'])

    def test_completed_Text_only_is_counted_and_located_without_native(self):
        text='  原话\r\n\r\n重复\r重复\n🙂e\u0301  '
        result=self.one([desktop(text=text)])
        self.assertTrue(result.complete,result.issues);self.assertEqual(result.text,'## assistant\n\n'+text+'\n')
        ref=result.audit['messages'][0]['refs'][0]
        self.assertEqual(ref['line'],2);self.assertEqual(ref['text_fields'],['payload.item.content[0].text'])

    def test_native_only_and_complete_mirror_use_one_message(self):
        a=assistant('a','VISIBLE');a['payload']['channel']=None;a['payload']['phase']='final_answer'
        for rows,refs in [([a],1),([desktop(),a],2),([a,desktop()],2)]:
            with self.subTest(rows=rows):
                result=self.one(rows);self.assertTrue(result.complete,result.issues)
                self.assertEqual(result.text,'## assistant\n\nVISIBLE\n')
                self.assertEqual(len(result.audit['messages'][0]['refs']),refs)

    def test_completed_Text_cross_source_mirror_and_identity_conflict(self):
        a=assistant('a','VISIBLE');a['payload']['phase']='final_answer';a['payload']['channel']=None
        p1=self.page('a.jsonl',[desktop()]);p2=self.page('b.jsonl',[a])
        result=extract([p2,p1],'c1');self.assertTrue(result.complete,result.issues)
        self.assertEqual(result.text,'## assistant\n\nVISIBLE\n')
        self.assertEqual({r['source'] for r in result.audit['messages'][0]['refs']},{str(p1),str(p2)})
        a['payload']['content'][0]['text']='CONFLICT';write(p2,[meta('c1',self.root),a])
        result=extract([p1,p2],'c1');self.assertFalse(result.complete)
        self.assertTrue(any(i['reason']=='identity_content_conflict' for i in result.issues))
        self.assertIn('VISIBLE',result.text);self.assertIn('CONFLICT',result.text)

    def test_completed_Text_same_content_distinct_ids_and_turns_preserved(self):
        result=self.one([desktop('a','REPEAT'),desktop('b','REPEAT'),desktop('a','REPEAT',turn='t2')])
        self.assertTrue(result.complete,result.issues);self.assertEqual(len(result.audit['messages']),3)
        self.assertEqual(result.text.count('REPEAT'),3)

    def test_completed_Text_repeated_blocks_preserve_positions_and_extra_field_audit(self):
        row=desktop(text='SAME');part=row['payload']['item']['content'][0]
        part.update(summary='DO_NOT_INCLUDE',content=[{'type':'text','text':'NESTED'}])
        row['payload']['item']['content'].append({'type':'Text','text':'SAME'})
        result=self.one([row]);self.assertTrue(result.complete,result.issues)
        self.assertEqual(result.text,'## assistant\n\nSAME\n\nSAME\n')
        ref=result.audit['messages'][0]['refs'][0]
        self.assertEqual(ref['text_fields'],['payload.item.content[0].text','payload.item.content[1].text'])
        self.assertEqual(result.audit['sources'][0]['fields_excluded'][0]['fields'],['content','summary'])

    def test_Text_is_not_global_case_folding_or_user_or_unknown_schema(self):
        rows=[]
        row=user('u','SPOOF');row['payload']['content'][0]['type']='Text';rows.append(row)
        row=assistant('a','SPOOF');row['payload']['content'][0]['type']='Text';rows.append(row)
        row=completed('u','SPOOF',kind='UserMessage',client_id='client');row['payload']['item']['content'][0]['type']='Text';rows.append(row)
        row=desktop();row['payload']['item']['type']='agentmessage';rows.append(row)
        row=desktop();row['payload']['item']['type']='FutureAgentMessage';rows.append(row)
        row=desktop();row['payload']['item']['content'][0]['type']='TEXT';rows.append(row)
        for row in rows:
            with self.subTest(row=row):
                result=self.bad(row);self.assertEqual(result.text,'')

    def test_completed_Text_visibility_internal_unknown_and_recipient(self):
        for fields,complete in [({'phase':'analysis'},True),({'phase':'future'},False),
                ({'phase':'analysis','channel':'final'},False),({'recipient':'tool'},True)]:
            row=desktop();row['payload']['item'].update(fields)
            result=self.one([row]);self.assertEqual(result.complete,complete,result.issues)
            self.assertEqual(result.text,'')

    def test_completed_Text_truncation_flags_remain_unverified(self):
        for where,field in [('item','truncated'),('item','incomplete'),('part','truncated'),('part','is_truncated')]:
            row=desktop();target=row['payload']['item']
            if where=='part':target=target['content'][0]
            target[field]=True
            with self.subTest(where=where,field=field):self.bad(row)

    def test_completed_Text_truncation_words_are_literal_as_required_by_contract(self):
        text='BEFORE …123 tokens truncated… AFTER'
        result=self.one([desktop(text=text)])
        self.assertTrue(result.complete,result.issues)
        self.assertEqual(result.text,'## assistant\n\n'+text+'\n')

    def test_completed_Text_missing_identity_or_turn_not_silently_adopted(self):
        for where,key in [('item','id'),('payload','turn_id')]:
            row=desktop();target=row['payload']['item'] if where=='item' else row['payload'];target.pop(key)
            self.bad(row,'unverified_completed_text_identity')
        for target,key,value in [('item','role','user'),('item','turn_id','other'),
                ('payload','thread_id','foreign'),('payload','thread_id',None)]:
            row=desktop();where=row['payload']['item'] if target=='item' else row['payload']
            where[key]=value;self.bad(row,'unverified_completed_text_identity')
        row=desktop();row['payload']['item']['internal_chat_message_metadata_passthrough']={'turn_id':'other'}
        self.bad(row,'unverified_completed_text_identity')

    def test_known_configuration_exact_shape_excluded(self):
        result=self.one([config(),user('u','NORMAL')]);self.assertTrue(result.complete,result.issues)
        self.assertEqual(result.text,'## user\n\nNORMAL\n')
        self.assertEqual(result.audit['sources'][0]['excluded'][1]['reason'],'verified_configuration_metadata')

    def test_configuration_unknown_fields_provenance_and_wrong_types_unverified(self):
        rows=[]
        for target,key,value in [('payload','text','MAYBE_CHAT'),('payload','reasoning','xhigh'),
                ('root','content','MAYBE_CHAT'),('metadata','client_authored',True),
                ('metadata','harness_authored_configuration',1)]:
            row=config();(row if target=='root' else row[target])[key]=value;rows.append(row)
        row=config();row['payload']['reasoning']['future']='unknown';rows.append(row)
        row=config();row['payload']['reasoning']['effort']={'text':'MAYBE_CHAT'};rows.append(row)
        row=config();row.pop('metadata');rows.append(row)
        row=config();row['payload']['reasoning']['effort']='future';rows.append(row)
        row=config();row['payload']['type']='configuration_update_v2';rows.append(row)
        for row in rows:
            with self.subTest(row=row):self.bad(row)

    def test_known_usage_exact_shape_excluded_with_source_identity(self):
        result=self.one([usage(),user('u','NORMAL')]);self.assertTrue(result.complete,result.issues)
        self.assertEqual(result.text,'## user\n\nNORMAL\n')
        self.assertEqual(result.audit['sources'][0]['excluded'][1]['reason'],'verified_usage_metadata')

    def test_usage_unknown_fields_types_counter_values_and_identity_unverified(self):
        rows=[]
        for target,key,value in [('payload','text','MAYBE_CHAT'),('root','content','MAYBE_CHAT'),
                ('payload','thread_id','foreign'),('payload','session_id','foreign'),
                ('payload','response_id',None),('payload','turn_token_usage',[])]:
            row=usage();(row if target=='root' else row[target])[key]=value;rows.append(row)
        row=usage();row['payload']['thread_id']=row['payload']['session_id']='foreign';rows.append(row)
        for value in (True,-1,1.5,'10',{'text':'MAYBE_CHAT'}):
            row=usage();row['payload']['usage']['input_tokens']=value;rows.append(row)
        row=usage();row['payload']['usage']['future_tokens']=1;rows.append(row)
        row=usage();row['payload']['usage'].pop('total_tokens');rows.append(row)
        row=usage();row['type']='token_usage_record_v2';rows.append(row)
        row=usage();row['type']='event_msg';row['payload']['type']='token_usage_record';rows.append(row)
        for row in rows:
            with self.subTest(row=row):self.bad(row)

    def test_a35_user_projection_audit_uses_physical_sources_and_named_record_seq(self):
        prefix=[{'type':'event_msg','payload':{'type':'task_started'}} for _ in range(20)]
        path=self.page('located.jsonl',[*prefix,user('native','BODY'),completed('desk','BODY',kind='UserMessage',client_id='c')])
        result=extract([path],'c1');self.assertTrue(result.complete,result.issues)
        merge=result.audit['merges'][0]
        self.assertNotIn('kept_line',merge);self.assertNotIn('merged_line',merge)
        self.assertEqual((merge['kept_record_seq'],merge['merged_record_seq']),(1,2))
        for key,line in [('kept_refs',22),('merged_refs',23)]:
            refs=merge[key];self.assertEqual(len(refs),1)
            ref=refs[0];self.assertEqual((ref['source'],ref['line']),(str(path),line))
            self.assertEqual(ref['line_text_sha256'],hashlib.sha256(path.read_bytes().splitlines(keepends=True)[line-1]).hexdigest())
            self.assertEqual(len(ref['text_fields']),1)

    def test_a35_cross_file_same_physical_line_has_both_file_identities(self):
        p1=self.page('a.jsonl',[desktop()]);p2=self.page('b.jsonl',[assistant('a','VISIBLE')])
        result=extract([p1,p2],'c1');self.assertTrue(result.complete,result.issues)
        merge=result.audit['merges'][0]
        self.assertEqual((merge['kept_refs'][0]['line'],merge['merged_refs'][0]['line']),(2,2))
        self.assertEqual(merge['kept_refs'][0]['source'],str(p1));self.assertEqual(merge['merged_refs'][0]['source'],str(p2))
        self.assertEqual(len(result.audit['messages'][0]['refs']),2)
        self.assertEqual(len(merge['kept_refs']),1,'Audit snapshot mutated after extending refs')

    @unittest.skip("Local-only authorized real snapshots are excluded from public export")
    def test_real_snapshot_complete_identical_to_both_preserved_expected_files(self):
        pass

if __name__=='__main__':unittest.main()
