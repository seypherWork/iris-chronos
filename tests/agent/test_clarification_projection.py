"""Cross-boundary regression: historical detail must identify the reviewed decision.

Pure synthetic fixtures; no native identity, model or dispatch is exercised.
"""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'src'))
sys.path.insert(0,str(Path(__file__).resolve().parent))
import test_clarification_contract as fixture
from chronos_agent import contract
from chronos_review.projection import project
from chronos_simulation.model import canonical, fingerprint


class ClarificationProjectionTests(unittest.TestCase):
    def decision(self, clarified=True):
        o=fixture.observation(None if clarified else fixture.world(resolved=True))
        authority=fixture.authority(o)
        source=fixture.source_for(o) if clarified else None
        now=fixture.ORIGIN+60*fixture.S
        p=contract.prepare(o,authority,'new-decision',now_us=now,gate_state='OPEN',
            response_contract=contract.EXTRACTION_CONTRACT,clarification_source=source)
        self.assertEqual(p['status'],'READY')
        fresh=deepcopy(o);fresh['clock']+=fixture.S;fresh=fixture.reseal(fresh)
        answer=fixture.e1('clarification:clarify-1' if clarified else 'customer-0')
        result=contract.finish(p['record'],answer,fresh,authority,now_us=now+fixture.S,
            gate_state='OPEN',clarification_source=source)
        self.assertEqual(result['status'],'VALIDATED_PROPOSAL')
        d=fixture.completed(p,result)
        d['call']=dict(responseContract=contract.EXTRACTION_CONTRACT,
            interpretationOrigin='MODEL',selectionOrigin='DETERMINISTIC_CODE',
            profileSha256='b'*64,model='synthetic-model')
        fresh['clock']+=fixture.S;fresh=fixture.reseal(fresh)
        reviewed=contract.review(d,fresh,authority,now_us=now+2*fixture.S,
            gate_state='OPEN',generation=fixture.GENERATION,clarification_source=source)
        self.assertEqual(reviewed['status'],'REVIEWABLE')
        return d,reviewed

    def test_clarified_detail_matches_the_actual_review_binding(self):
        d,reviewed=self.decision()
        detail=project(canonical(d),d['requestId'])
        self.assertEqual(detail['code'],'DECISION_DETAIL_RECORDED')
        self.assertEqual(detail['decisionDigest'],reviewed['binding']['decisionDigest'])
        self.assertIs(detail['dispatchGranted'],False)
        self.assertIs(detail['canConfirm'],False)
        self.assertNotIn('clarification_binding',canonical(detail))

    def test_changed_private_clarification_is_not_the_same_decision(self):
        d,_=self.decision()
        before=project(canonical(d),d['requestId'])
        changed=deepcopy(d)
        changed['prepared']['record']['clarification_binding']['expires_us']-=1
        after=project(canonical(changed),changed['requestId'])
        self.assertEqual(after['code'],'DECISION_DETAIL_RECORDED')
        self.assertEqual(before['context'],after['context'])
        self.assertNotEqual(before['decisionDigest'],after['decisionDigest'])

    def test_unclarified_historical_digest_remains_byte_compatible(self):
        d,reviewed=self.decision(False)
        record=d['prepared']['record']
        legacy=fingerprint(dict(requestId=d['requestId'],generation=d['generation'],
            completedUS=d['completedUS'],context_digest=record['wire']['context_digest'],
            result=d['result'],reviewDeadlineUS=record['review_deadline_us']))
        detail=project(canonical(d),d['requestId'])
        self.assertEqual(detail['code'],'DECISION_DETAIL_RECORDED')
        self.assertEqual(detail['decisionDigest'],legacy)
        self.assertEqual(detail['decisionDigest'],reviewed['binding']['decisionDigest'])

    def test_malformed_present_binding_is_not_a_legacy_decision(self):
        d,_=self.decision()
        original=deepcopy(d)
        for value in (None,[],False,'invalid'):
            changed=deepcopy(d)
            changed['prepared']['record']['clarification_binding']=value
            with self.subTest(value=value):
                result=project(canonical(changed),changed['requestId'])
                self.assertEqual(result['code'],'DECISION_DETAIL_UNAVAILABLE')
                self.assertIs(result['dispatchGranted'],False)
                self.assertIs(result['canConfirm'],False)
        self.assertEqual(d,original)

if __name__=='__main__':unittest.main()
