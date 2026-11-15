"""Synthetic clarified-case chat composition, without model/native authority."""
from copy import deepcopy
from pathlib import Path
import sys,unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'src'))
sys.path.insert(0,str(Path(__file__).resolve().parent))
import test_clarification_contract as f
import test_clarification_projection as sample
from chronos_agent import contract
from chronos_review.projection import project
from chronos_grounding import evidence_v2 as evidence,renderer_v2 as renderer
from chronos_conversation import ledger,grounded_v2
from chronos_simulation.model import canonical

class ClarifiedChatTests(unittest.TestCase):
    def inputs(self):
        decision,_=sample.ClarificationProjectionTests().decision()
        observation=f.observation();observation['clock']+=2*f.S;observation=f.reseal(observation)
        return decision,dict(observation=observation,authority=f.authority(observation),
            now_us=f.ORIGIN+62*f.S,gate_state='OPEN',generation=f.GENERATION)

    def test_missing_fresh_clarification_is_explained_without_approval(self):
        d,inputs=self.inputs();original=deepcopy((d,inputs))
        text,source=evidence.current_review(d,**inputs)
        self.assertEqual(source['code'],'CLARIFICATION_SOURCE_REQUIRED')
        self.assertEqual(source['status'],'ERROR')
        self.assertIs(source['dispatch_authorized'],False)
        self.assertIn('does not include a fresh native clarification check',text)
        self.assertIn('cannot establish current eligibility',text)
        self.assertNotIn('remains eligible',text)
        self.assertEqual((d,inputs),original)
        self.assertEqual(contract.review(d,**inputs)['code'],'CLARIFICATION_SOURCE_REQUIRED')

    def test_complete_open_catalog_and_c2_context_accept_the_limited_read(self):
        d,inputs=self.inputs()
        scope=dict(installation_id='installation-1',actor='principal-test',session_binding='session-test',
            case_id=d['orderId'],shipment_version=1)
        state,opened=ledger.transition(None,'OPEN',scope,dict(conversation_id='clarified-chat'))
        self.assertEqual(opened['code'],'CONVERSATION_OPENED')
        cat=renderer.build(canonical(d),d['requestId'],scope,projector=project,
            receipt_validator=contract.validate_explanation,generation=f.GENERATION,revision=1,
            conversation_revision=1,conversation_state=state,conversation_validator=ledger.check,
            review_inputs=inputs)
        stable=evidence.stable_sources(cat,review_inputs=inputs,simulator_inputs=None)
        context=grounded_v2.from_catalog(renderer.Catalog(canonical(stable),renderer.c.digest(stable)))
        grounded_v2.validate_context(scope,context)
        self.assertEqual(context['grounding']['source_records']['current-review']['code'],'CLARIFICATION_SOURCE_REQUIRED')
        self.assertIn('earlier arrival',stable['sections']['DECISION']['concise'])
        self.assertIs(context['grounding']['source_records']['current-review']['dispatch_authorized'],False)

    def test_unknown_review_errors_are_still_rejected(self):
        d,inputs=self.inputs()
        with patch.object(evidence.agent,'review',return_value=dict(status='ERROR',code='UNKNOWN_FAILURE',dispatch_authorized=False)):
            with self.assertRaisesRegex(ValueError,'CURRENT_REVIEW_UNAVAILABLE'):
                evidence.current_review(d,**inputs)

if __name__=='__main__':unittest.main()
