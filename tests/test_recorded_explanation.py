"""Rendering attribution only; mocked evidence here is not authenticated state."""
import json,sys
from pathlib import Path
from unittest.mock import patch
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from chronos_grounding import renderer_v1 as renderer

def rendered(origin,action='HOLD'):
    proposal=dict(action=action,option_id=None if action=='HOLD' else 'B',
                  interpreted_preference='UNRESOLVED' if action=='HOLD' else 'EARLIEST_ALLOWED',
                  reason_code='CONTEXT_AMBIGUOUS' if action=='HOLD' else 'PREFERENCE_MATCH')
    detail=dict(code='DECISION_DETAIL_RECORDED',decisionDigest='a'*64,proposal=proposal,
                attribution=dict(interpretationOrigin=origin,selectionOrigin='DETERMINISTIC_CODE'))
    raw=json.dumps(dict(prepared=dict(record=dict(wire=dict(context_digest='b'*64))),result={}))
    with patch.object(renderer.evidence,'build',return_value={'mocked':'render-only'}):
        catalog=renderer.build(raw,'synthetic-decision',{},projector=lambda *_:detail,
            receipt_validator=lambda *_:None,generation='synthetic-generation',revision=1,conversation_revision=1)
    return catalog.checked()['sections']['DECISION']

class RecordedExplanationTests(unittest.TestCase):
    def test_recorded_hold_does_not_claim_missing_or_fresh_attribution(self):
        text=rendered('RECORDED_MODEL')
        self.assertIn('recorded model response; no fresh inference is performed',text)
        self.assertIn('No option was selected.',text)
        self.assertNotIn('older record does not establish',text)

    def test_recorded_choice_separates_interpretation_from_current_ranking(self):
        text=rendered('RECORDED_MODEL','FAILOVER_B')
        self.assertIn('Deterministic code ranked the options eligible in the recorded selection snapshot.',text)
        self.assertIn('not evidence of dispatch or current preview validity',text)

    def test_existing_live_and_legacy_attribution_wording_retained(self):
        self.assertIn('The interpretation came from the model; no option was selected.',rendered('MODEL'))
        self.assertIn('The model interpreted the preference; deterministic code ranked the eligible options.',rendered('MODEL','FAILOVER_B'))
        self.assertIn('This older record does not establish',rendered('NOT_RECORDED'))

if __name__=='__main__':unittest.main()
