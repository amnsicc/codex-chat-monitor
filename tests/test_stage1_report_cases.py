"""Direct, reproducible acceptance failures against the unchanged delivery copy."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parent

from chat_monitor.extract import extract

def load(name, reverse=False):
    paths = sorted((ROOT/'stage1_cases'/name).glob('page-*.jsonl'))
    if reverse: paths.reverse()
    return extract(paths, 'acceptance-thread')

class AcceptanceRegressions(unittest.TestCase):
    def test_internal_or_unknown_assistant_visibility_is_not_verified_chat(self):
        for case in ['04-assistant-analysis-phase','05-assistant-summary-channel','06-assistant-unknown-phase']:
            with self.subTest(case=case):
                value=load(case)
                self.assertTrue(not value.complete or 'INTERNAL_OR_UNVERIFIED' not in value.text,
                    f'{case}: body included with complete={value.complete}; issues={value.issues}')

    def test_multiblock_user_projection_is_not_two_verified_messages(self):
        value=load('03-multiblock-user-projection')
        self.assertTrue(not value.complete or len(value.audit['messages'])==1,
            f"complete={value.complete}; ids={[m['id'] for m in value.audit['messages']]}")

    def test_source_ref_uses_original_position_after_filtering(self):
        value=load('08-filtered-original-content-position')
        actual=value.audit['messages'][0]['refs'][0]['content_positions']
        self.assertTrue(not value.complete or actual==['payload.content[1]'],
            f'actual={actual}; original content[0] is HOST_ONLY; human text is at content[1]')

    def test_overlapping_pages_do_not_silently_violate_source_order(self):
        value=load('10-overlap-equal-timestamps-reversed',reverse=True)
        ids=[m['id'] for m in value.audit['messages']]
        self.assertTrue(not value.complete or ids==['a','b','c','d'],f'complete={value.complete}; ids={ids}')

    def test_invalid_utf8_cannot_be_complete_original_text(self):
        value=load('12-invalid-utf8-in-chat')
        self.assertFalse(value.complete,f'issues={value.issues}; text={value.text!r}')

    def test_unselected_extra_field_is_not_promoted_to_body(self):
        value=load('13-unselected-extra-text-field')
        self.assertTrue(not value.complete or 'UNVERIFIED_EXTRA_FIELD' not in value.text,
            f'complete={value.complete}; text={value.text!r}')

    def test_desktop_client_id_does_not_override_explicit_host_provenance(self):
        value=load('14-desktop-mixed-explicit-provenance')
        self.assertTrue(not value.complete or 'HOST_DESKTOP' not in value.text,
            f'complete={value.complete}; text={value.text!r}')

if __name__=='__main__': unittest.main(verbosity=2)
