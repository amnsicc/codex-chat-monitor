"""Finite medium configuration support; retained xhigh and unknown boundaries."""
from pathlib import Path
import copy,json,hashlib
from tests import test_stage35_real_schema as real_cases
from tests.fixtures import user,assistant,meta,write
from chat_monitor.extract import extract
from chat_monitor.material import count_file
import unittest

class MediumConfigurationTests(unittest.TestCase):
    setUp=real_cases.RealSchemaTests.setUp
    page=real_cases.RealSchemaTests.page
    one=real_cases.RealSchemaTests.one
    bad=real_cases.RealSchemaTests.bad

    def medium(self):
        row=real_cases.config();row['payload']['reasoning']['effort']='medium';return row

    def test_medium_and_xhigh_both_preserve_neighbor_text(self):
        for row in [self.medium(),real_cases.config()]:
            with self.subTest(effort=row['payload']['reasoning']['effort']):
                value=self.one([user('u','BEFORE'),row,assistant('a','AFTER')])
                self.assertTrue(value.complete,value.issues)
                self.assertEqual(value.text,'## user\n\nBEFORE\n\n## assistant\n\nAFTER\n')
                self.assertEqual(value.audit['sources'][0]['excluded'][1]['reason'],'verified_configuration_metadata')

    def test_mixed_medium_then_xhigh_does_not_require_discarding_history(self):
        value=self.one([self.medium(),user('u','EARLY'),real_cases.config(),assistant('a','LATE')])
        self.assertTrue(value.complete,value.issues)
        self.assertEqual(value.text,'## user\n\nEARLY\n\n## assistant\n\nLATE\n')

    def test_unknown_efforts_wrong_types_and_case_remain_unverified(self):
        for effort in ['low','high','future','MEDIUM','Medium','',None,False,0,[],{},['medium']]:
            row=self.medium();row['payload']['reasoning']['effort']=effort
            with self.subTest(effort=effort):self.bad(row,'unverified_metadata_structure')

    def test_medium_extra_fields_or_wrong_authorship_not_excluded_as_complete(self):
        variants=[]
        for section,key,value in [('payload','text','CANDIDATE_CHAT'),('root','content','CANDIDATE_CHAT'),
                ('metadata','client_authored',True),('metadata','client_authored',0),
                ('metadata','harness_authored_configuration',False),('metadata','harness_authored_configuration',1)]:
            row=self.medium();(row if section=='root' else row[section])[key]=value;variants.append(row)
        row=self.medium();row['payload']['reasoning']['text']='CANDIDATE_CHAT';variants.append(row)
        row=self.medium();row.pop('metadata');variants.append(row)
        row=self.medium();row['type']='event_msg';variants.append(row)
        for row in variants:
            with self.subTest(row=row):self.bad(row)

    def test_medium_words_in_user_text_are_literal(self):
        text='configuration_update reasoning effort medium xhigh {"reasoning":{"effort":"medium"}}'
        value=self.one([user('u',text)])
        self.assertTrue(value.complete,value.issues);self.assertEqual(value.text,'## user\n\n'+text+'\n')

    @unittest.skip("Local-only authorized real snapshots are excluded from public export")
    def test_current_two_real_sources_complete_and_same_preserved_expected_bytes(self):
        pass

if __name__=='__main__':unittest.main()
