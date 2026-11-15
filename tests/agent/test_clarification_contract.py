"""Pure composition fixtures only; no IRIS user, task, authentication or model.

The trusted-native source below is synthetic test data. Passing these tests
does not establish that the native CSP/Workflow adoption path is implemented.
"""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import json
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
from chronos_agent import contract, clarification
from chronos_simulation import clock
from chronos_simulation.model import canonical, fingerprint

ORIGIN = 1_800_000_000_000_000
S = 1_000_000
GENERATION = 'generation-1'


def world(*, messages=1, preference='context', resolved=False):
    text = ('For this order, prioritize earlier arrival within the authorized budget.' if resolved
            else 'The customer has not decided whether lower cost or earlier arrival matters more.')
    msgs = [{'id': 'customer-' + str(i), 'text': text} for i in range(messages)]
    return dict(order_id='clarification-order', shipment_version=1, revision=1, budget=8,
        deadline=25, inventory_expires=30, original_status='NOT_ACCEPTED_FINAL',
        preference=preference, payload=dict(sku='SYNTHETIC', quantity=1), messages=msgs,
        agent_provenance=dict(messages={m['id']: dict(source_id='synthetic-customer',
            at_minutes=0, order_link='VERIFIED_CURRENT', order_id='clarification-order',
            shipment_version=1) for m in msgs}, changes={}),
        options=dict(A=dict(cost=3, available_at=0, queue_minutes=1, travel_minutes=18),
                     B=dict(cost=6, available_at=0, queue_minutes=0, travel_minutes=10)))


def observation(w=None, elapsed=60*S):
    native, _ = clock.native_definition(w or world(), (), ORIGIN)
    binding=dict(operation_id='original-op', attempt_id='original-attempt',
        order_id=native['order_id'], shipment_version=1, target='A',
        payload=canonical(native['payload']), reserved_at=0, valid_until=30*60*S)
    receipt=dict(operationId='original-op', attemptId='original-attempt',
        orderId=native['order_id'], shipmentVersion=1, target='A',
        payload=binding['payload'], status='NOT_ACCEPTED_FINAL', closedForever=True,
        reference='', receiptId='receipt-original')
    o=dict(definition=native, calendar=[], clock=elapsed, clock_domain='LOGICAL_MICROSECONDS',
        sequence=1, operations=[dict(binding=binding, receipt=receipt)], facts_revision=1)
    return reseal(o)


def reseal(o):
    o=deepcopy(o)
    o['facts_id']=fingerprint({k:v for k,v in o.items() if k not in
        {'clock','clock_domain','sequence','facts_id','facts_revision','observation_id'}})
    o['observation_id']=fingerprint({k:v for k,v in o.items() if k!='observation_id'})
    return o


def authority(o):
    r=o['operations'][0]['receipt']
    op={k:r[k] for k in ('operationId','attemptId','orderId','shipmentVersion','target','reference')}
    op.update(payload=canonical(o['definition']['payload']),state='NOT_ACCEPTED_FINAL')
    return dict(dispatchGranted=False,operation=op,effect=dict(quarantined=False,state='OPEN',
        currentOperationId=op['operationId'],snapshotId=1,snapshot=clock.authority_snapshot(o)))


def source_for(o):
    facts=contract.public_facts(o)
    bound=dict(clarification_id='clarify-1',task_id='143',source_decision_id='original-hold',
        order_id=o['definition']['order_id'],shipment_version=1,generation=GENERATION,
        decision_digest='a'*64,facts_id=o['facts_id'],facts_digest=fingerprint(facts),
        authority_digest=contract._clarification_authority_stamp(authority(o)),
        source_outcome='VALIDATED_HOLD',reason_code='CONTEXT_AMBIGUOUS',
        preference_mode='CONTEXT_REQUIRED',utc_origin_us=ORIGIN,
        valid_until_us=ORIGIN+min(facts['deadline'],facts['inventory_expires'],facts['offer_until']))
    record=dict(schema_version=clarification.SCHEMA,state='RESOLVED',binding=deepcopy(bound),
        binding_sha256=clarification.binding_digest(bound),created_us=ORIGIN+10*S,
        resolved_us=ORIGIN+20*S,expires_us=ORIGIN+610*S,actor='principal-'+'e'*64,
        preference='EARLIEST_ALLOWED',note='The customer confirmed earlier arrival within the existing budget.')
    completion=dict(clarification_id='clarify-1',task_id='143',role=clarification.ROLE,
        completed=True,action='Clarified',actor=record['actor'],completed_us=record['resolved_us'],
        preference=record['preference'],note=record['note'])
    return dict(record=record,expected_binding=bound,native_completion=completion)


def rebind(source, **changes):
    source=deepcopy(source)
    source['expected_binding'].update(changes)
    source['record']['binding']=deepcopy(source['expected_binding'])
    source['record']['binding_sha256']=clarification.binding_digest(source['expected_binding'])
    return source


def e1(source='clarification:clarify-1'):
    return canonical(dict(schema_version='chronos.preference-extraction.v1',
        interpreted_preference='EARLIEST_ALLOWED',reason_code='PREFERENCE_MATCH',source_ids=[source],
        rationale='The current cited communication prioritizes earlier arrival within the existing budget.',
        clarification=None))


def a1(prepared, source='customer-0'):
    wire=prepared['record']['wire']
    return canonical(dict(schema_version='chronos.agent-proposal.v2',
        **{k:wire[k] for k in ('context_id','context_digest','order_id','shipment_version','state_revision')},
        action='FAILOVER_B',option_id='opt-b',interpreted_preference='EARLIEST_ALLOWED',
        reason_code='PREFERENCE_MATCH',source_ids=[source],rationale='Current evidence prioritizes earlier arrival.',
        clarification=None))


def completed(prepared, result):
    p=deepcopy(prepared);p['runtime_generation']=GENERATION;w=p['record']['wire']
    return dict(requestId=w['context_id'],orderId=w['order_id'],shipmentVersion=1,
        generation=GENERATION,mode='WITH_TRIALS',state='COMPLETED',prepared=p,
        createdUS=p['record']['started_us'],deadlineUS=p['record']['deadline_us'],
        completedUS=p['record']['started_us']+S,result=deepcopy(result))


class ClarificationContractTests(unittest.TestCase):
    def setUp(self):
        self.o=observation();self.a=authority(self.o);self.source=source_for(self.o)
        self.now=ORIGIN+60*S

    def prepare(self, source=None, o=None, a=None, now=None, **kw):
        return contract.prepare(o or self.o,a or self.a,'new-decision',
            now_us=self.now if now is None else now,gate_state='OPEN',
            response_contract=contract.EXTRACTION_CONTRACT,
            clarification_source=self.source if source is None else source,**kw)

    def finish(self, p, source=None, now=None, **kw):
        now=self.now+S if now is None else now
        fresh=deepcopy(self.o);fresh['clock']=now-ORIGIN;fresh=reseal(fresh)
        return contract.finish(p['record'],e1(),fresh,self.a,now_us=now,gate_state='OPEN',
            clarification_source=self.source if source is None else source,**kw)

    def review(self, p, result, source=None, now=None, **kw):
        now=self.now+2*S if now is None else now
        fresh=deepcopy(self.o);fresh['clock']=now-ORIGIN;fresh=reseal(fresh)
        return contract.review(completed(p,result),fresh,self.a,now_us=now,gate_state='OPEN',
            generation=GENERATION,clarification_source=self.source if source is None else source,**kw)

    def assert_rejected(self, result, code=None):
        self.assertNotIn(result['status'],{'READY','VALIDATED_PROPOSAL','REVIEWABLE'})
        self.assertIs(result['dispatch_authorized'],False)
        if code is not None:self.assertEqual(result['code'],code)

    def test_provider_ids_and_original_observation_are_untouched(self):
        before=deepcopy((self.o,self.a,self.source))
        bare=contract.prepare(self.o,self.a,'bare',now_us=self.now,gate_state='OPEN',response_contract=contract.EXTRACTION_CONTRACT)
        p=self.prepare();self.assertEqual(p['status'],'READY')
        self.assertEqual((self.o,self.a,self.source),before)
        w=p['record']['wire'];b=bare['record']['wire']
        self.assertEqual((w['facts_id'],w['observation_id']),(b['facts_id'],b['observation_id']))
        self.assertNotEqual(p['record']['facts_digest'],bare['record']['facts_digest'])
        self.assertNotEqual(w['context_digest'],b['context_digest'])
        self.assertEqual(w['facts']['messages'][-1]['source_id'],'clarification:clarify-1')
        self.assertIn({'id':'clarification:clarify-1','kind':'message'},w['source_catalog'])
        self.assertNotIn('clarification_binding',json.loads(p['input_json'])['context'])
        self.assertNotIn(self.source['record']['actor'],p['input_json'])

    def test_human_wait_does_not_reuse_the_old_thirty_second_window(self):
        p=self.prepare();self.assertEqual(p['status'],'READY')
        self.assertGreater(self.now-self.source['record']['created_us'],30*S)
        self.assertEqual(p['record']['started_us'],self.now)
        self.assertLessEqual(p['record']['deadline_us'],self.now+30*S)
        self.assertIs(p['dispatch_authorized'],False)

    def test_human_absolute_expiry_bounds_inference_and_review(self):
        source=deepcopy(self.source);source['record']['expires_us']=self.now+5*S
        p=self.prepare(source);self.assertEqual(p['status'],'READY')
        self.assertEqual(p['record']['deadline_us'],self.now+5*S)
        self.assertEqual(p['record']['review_deadline_us'],self.now+5*S)
        self.assertEqual(self.prepare(source,now=self.now+5*S)['code'],'CLARIFICATION_EXPIRED')
        self.assert_rejected(self.finish(p,source,now=self.now+5*S),'MODEL_TIMEOUT')

    def test_human_window_cannot_exceed_ten_minutes(self):
        s=deepcopy(self.source);s['record']['expires_us']=s['record']['created_us']+601*S
        self.assert_rejected(self.prepare(s),'CLARIFICATION_HUMAN_WINDOW_EXCEEDED')

    def test_provider_identity_facts_and_business_expiry_are_checked(self):
        variants=[(dict(order_id='other-order'),'CLARIFICATION_PROVIDER_IDENTITY_MISMATCH'),
                  (dict(facts_id='f'*64),'CLARIFICATION_PROVIDER_FACTS_CHANGED'),
                  (dict(facts_digest='f'*64),'CLARIFICATION_PROVIDER_FACTS_CHANGED'),
                  (dict(valid_until_us=self.source['expected_binding']['valid_until_us']+1),'CLARIFICATION_BUSINESS_EXPIRY_CHANGED')]
        for changes,code in variants:
            with self.subTest(changes=changes):self.assert_rejected(self.prepare(rebind(self.source,**changes)),code)

    def test_structured_policy_cannot_be_replaced_by_a_clarification(self):
        o=observation(world(preference='fastest'));s=source_for(o)
        self.assert_rejected(self.prepare(s,o=o,a=authority(o)),'CLARIFICATION_POLICY_NOT_ELIGIBLE')

    def test_prepare_binds_source_to_actual_authority_not_only_its_internal_hash(self):
        # Update the source's own binding hash too: rejection must come from
        # correlation with actual authority, not the projector's generic hash.
        s=rebind(self.source,authority_digest='f'*64)
        self.assert_rejected(self.prepare(s),'CLARIFICATION_AUTHORITY_CHANGED')
        for name,mutate in (
            ('additional_effect_material',lambda a:a['effect'].__setitem__('policy_marker',2)),
            ('operation_reference',lambda a:a['operation'].__setitem__('reference','changed-reference')),
            ('additional_operation_material',lambda a:a['operation'].__setitem__('revision',2)),
            ('operation_snapshot_id_is_still_material',lambda a:a['operation'].__setitem__('snapshotId',2)),
        ):
            a=deepcopy(self.a);mutate(a)
            with self.subTest(change=name):
                self.assert_rejected(self.prepare(a=a),'CLARIFICATION_AUTHORITY_CHANGED')

    def test_observation_only_renewal_preserves_actual_authority_correlation(self):
        a=deepcopy(self.a);a['effect']['snapshot']['observedAt']+=1
        # The freshly rederived expected binding is identical. The material
        # projection excludes observation time and the effect's snapshot nonce;
        # every other effect/operation field remains bound.
        s=rebind(self.source,authority_digest=contract._clarification_authority_stamp(a))
        self.assertEqual(self.prepare(s,a=a)['status'],'READY')
        self.assertEqual(s['expected_binding']['authority_digest'],self.source['expected_binding']['authority_digest'])

    def test_effect_snapshot_nonce_renewal_is_not_a_new_human_window(self):
        a=deepcopy(self.a);a['effect']['snapshotId']+=1
        a['effect']['snapshot']['observedAt']+=1
        p=self.prepare(a=a)
        self.assertEqual(p['status'],'READY')
        self.assertEqual(p['record']['clarification_binding']['binding']['authority_digest'],
            self.source['expected_binding']['authority_digest'])
        self.assertEqual(p['record']['clarification_binding']['expires_us'],self.source['record']['expires_us'])

    def test_current_effect_or_operation_state_never_becomes_ready(self):
        for effect_state,operation_state in (('UNKNOWN','NOT_ACCEPTED_FINAL'),
                                             ('OPEN','IN_FLIGHT'),('ACCEPTED','ACCEPTED')):
            a=deepcopy(self.a);a['effect']['state']=effect_state;a['operation']['state']=operation_state
            with self.subTest(effect=effect_state,operation=operation_state):
                self.assert_rejected(self.prepare(a=a))

    def test_changed_cost_quarantine_or_policy_never_becomes_ready(self):
        for name,mutate in (
            ('cost',lambda a:a['effect']['snapshot']['offers']['A'].__setitem__('cost',4)),
            ('quarantine',lambda a:a['effect'].__setitem__('quarantined',True)),
            ('policy',lambda a:a['effect']['snapshot'].__setitem__('policyRevision',2)),
        ):
            a=deepcopy(self.a);mutate(a)
            with self.subTest(change=name):self.assert_rejected(self.prepare(a=a))

    def test_existing_projector_rejects_nonresolved_or_wrong_native_completion(self):
        variants=[]
        for value in ('PENDING','UNCERTAIN','CANCELLED'):
            s=deepcopy(self.source);s['record']['state']=value;variants.append(s)
        for field,value in (('role','UnknownRole'),('completed',1),('action','Approve'),('task_id','144'),('actor','principal-'+'f'*64)):
            s=deepcopy(self.source);s['native_completion'][field]=value;variants.append(s)
        for s in variants:
            with self.subTest(source=s):self.assert_rejected(self.prepare(s))

    def test_ambiguous_and_incomplete_sources_only_not_conflict(self):
        s=rebind(self.source,reason_code='CONTEXT_INCOMPLETE')
        self.assertEqual(self.prepare(s)['status'],'READY')
        s=deepcopy(self.source)
        s['record']['binding']['reason_code']='CONFLICTING_EVIDENCE'
        s['expected_binding']['reason_code']='CONFLICTING_EVIDENCE'
        self.assert_rejected(self.prepare(s))

    def test_eighth_message_allowed_ninth_rejected(self):
        for n,allowed in ((7,True),(8,False)):
            o=observation(world(messages=n));s=source_for(o)
            p=self.prepare(s,o=o,a=authority(o))
            with self.subTest(raw_messages=n):
                if allowed:self.assertEqual(len(p['record']['wire']['facts']['messages']),8)
                else:self.assert_rejected(p,'TOO_MANY_CLARIFICATION_MESSAGES')

    def test_source_types_extra_fields_sensitive_note_and_future_resolution_fail_closed(self):
        variants=[None,[],{},dict(self.source,actorVerified=True)]
        for value in variants:
            # Explicit None is the legacy route, not a way to create a source.
            if value is None:continue
            with self.subTest(value=value):self.assert_rejected(self.prepare(value))
        for field,value in (('note','password=synthetic-only'),('resolved_us',self.now+1)):
            s=deepcopy(self.source);s['record'][field]=value
            self.assert_rejected(self.prepare(s))

    def test_prepare_reference_is_detached_from_mutable_caller_data(self):
        p=self.prepare();before=canonical(p)
        self.source['expected_binding']['generation']='changed'
        self.source['record']['note']='Changed after preparation.'
        self.assertEqual(canonical(p),before)

    def test_finish_requires_explicit_fresh_source_and_never_falls_back(self):
        p=self.prepare();fresh=reseal(dict(self.o,clock=self.o['clock']+S))
        r=contract.finish(p['record'],e1(),fresh,self.a,now_us=self.now+S,gate_state='OPEN')
        self.assert_rejected(r,'CLARIFICATION_SOURCE_REQUIRED')
        good=self.finish(p);self.assertEqual(good['status'],'VALIDATED_PROPOSAL')
        self.assertEqual(good['proposal']['action'],'FAILOVER_B')
        self.assertIs(good['dispatch_authorized'],False)

    def test_fresh_source_cannot_silently_change_note_preference_or_task(self):
        p=self.prepare()
        for field,value in (('note','Changed instruction.'),('preference','CHEAPEST_ON_TIME')):
            s=deepcopy(self.source);s['record'][field]=value;s['native_completion'][field]=value
            with self.subTest(field=field):self.assert_rejected(self.finish(p,s),'CLARIFICATION_SOURCE_CHANGED')
        s=rebind(self.source,task_id='144');s['native_completion']['task_id']='144'
        self.assert_rejected(self.finish(p,s),'CLARIFICATION_SOURCE_CHANGED')

    def test_provider_changes_are_not_hidden_by_the_human_overlay(self):
        p=self.prepare();fresh=deepcopy(self.o);fresh['definition']['budget']=9
        fresh['clock']+=S;fresh=reseal(fresh)
        r=contract.finish(p['record'],e1(),fresh,authority(fresh),now_us=self.now+S,
            gate_state='OPEN',clarification_source=self.source)
        self.assert_rejected(r,'CLARIFICATION_PROVIDER_FACTS_CHANGED')

    def test_provider_observation_must_not_precede_the_human_completion(self):
        s=deepcopy(self.source)
        s['record']['resolved_us']=ORIGIN+55*S
        s['native_completion']['completed_us']=ORIGIN+55*S
        stale=reseal(dict(self.o,clock=50*S))
        # This is recent enough for the legacy 60-second observation rule, but
        # must not combine post-observation human data with an older provider.
        self.assert_rejected(self.prepare(s,o=stale,a=authority(stale)),
            'CLARIFICATION_FRESH_PROVIDER_READ_REQUIRED')

    def test_legacy_inference_cannot_inject_a_human_source_only_at_finish(self):
        p=contract.prepare(self.o,self.a,'bare',now_us=self.now,gate_state='OPEN',response_contract=contract.EXTRACTION_CONTRACT)
        fresh=reseal(dict(self.o,clock=self.o['clock']+S))
        self.assert_rejected(contract.finish(p['record'],e1(),fresh,self.a,
            now_us=self.now+S,gate_state='OPEN',clarification_source=self.source),'UNEXPECTED_CLARIFICATION_SOURCE')

    def test_review_revalidates_source_and_retains_separate_human_approval(self):
        p=self.prepare();done=self.finish(p);r=self.review(p,done)
        self.assertEqual(r['status'],'REVIEWABLE');self.assertEqual(r['code'],'HUMAN_PREVIEW_REQUIRED')
        self.assertIs(r['dispatch_authorized'],False)
        self.assertEqual(r['binding']['option'],'FAILOVER_B')
        fresh=reseal(dict(self.o,clock=self.o['clock']+2*S))
        missing=contract.review(completed(p,done),fresh,self.a,now_us=self.now+2*S,
            gate_state='OPEN',generation=GENERATION)
        self.assert_rejected(missing,'CLARIFICATION_SOURCE_REQUIRED')

    def test_review_rejects_changed_native_completion_or_context_generation(self):
        p=self.prepare();done=self.finish(p)
        s=deepcopy(self.source);s['native_completion']['completed_us']+=1
        self.assert_rejected(self.review(p,done,s))
        d=completed(p,done);d['generation']='generation-2';d['prepared']['runtime_generation']='generation-2'
        fresh=reseal(dict(self.o,clock=self.o['clock']+2*S))
        self.assert_rejected(contract.review(d,fresh,self.a,now_us=self.now+2*S,
            gate_state='OPEN',generation='generation-2',clarification_source=self.source),'CLARIFICATION_GENERATION_CHANGED')

    def test_review_accepts_only_observation_nonce_renewal_and_binds_actual_preview_snapshot(self):
        p=self.prepare();done=self.finish(p);fresh=reseal(dict(self.o,clock=self.o['clock']+2*S))
        a=deepcopy(self.a);a['effect']['snapshot']['observedAt']+=2
        a['effect']['snapshotId']+=1
        ok=contract.review(completed(p,done),fresh,a,now_us=self.now+2*S,gate_state='OPEN',
            generation=GENERATION,clarification_source=self.source)
        self.assertEqual(ok['status'],'REVIEWABLE')
        self.assertEqual(ok['binding']['expectedSnapshotId'],a['effect']['snapshotId'])
        self.assertEqual(ok['binding']['reviewDeadlineUS'],p['record']['review_deadline_us'])

    def test_review_expiry_is_absolute_and_cannot_be_renewed_by_source_read(self):
        s=deepcopy(self.source);s['record']['expires_us']=self.now+5*S
        p=self.prepare(s);done=self.finish(p,s)
        self.assert_rejected(self.review(p,done,s,now=self.now+5*S),'REVIEW_EXPIRED')

    def test_inputs_remain_unchanged_after_prepare_finish_and_review(self):
        before=deepcopy((self.o,self.a,self.source));p=self.prepare();saved=deepcopy(p)
        done=self.finish(p);self.review(p,done)
        self.assertEqual((self.o,self.a,self.source),before);self.assertEqual(p,saved)

    def test_legacy_no_source_matches_preserved_prechange_canonical_bytes(self):
        # Hashes are captured from the pre-change pure contract backup, not from
        # model calls or current implementation output. They cover both A1/E1.
        expected={
            'chronos.agent-proposal.v2': [
                'db7f3df429b4b50a051fdfb0074be7698982ef79d30365ad471488146639dc31',
                'decd209161f006915fd93849a0e0badfe8cfafcf077445cb154ec1e19e3933cf',
                '9090ed159f4acebb20fc25f5bdaa19227a7670e92819652ca16374777ac208ad'],
            'chronos.preference-extraction.v1': [
                '070f9cbcb3f279352e3c1c5328609f55df4e20822e0b5cdaa8607bd64c2abfb7',
                '287d9d80ffac9f9f00b5ba7e87f2207c2ebc126ab0b8d8c147b8f2d7c5c31d01',
                'bd337e3d1bcbd96da845faef057fe3ec6dd45c318f8b954f9bb33c7d15effbe4'],
        }
        for selected,gold in expected.items():
            with self.subTest(contract=selected):
                o=observation(world(resolved=True));a=authority(o)
                p=contract.prepare(o,a,'legacy-decision',now_us=self.now,gate_state='OPEN',response_contract=selected)
                future=reseal(dict(o,clock=o['clock']+S))
                text=e1('customer-0') if selected==contract.EXTRACTION_CONTRACT else a1(p)
                done=contract.finish(p['record'],text,future,a,now_us=self.now+S,gate_state='OPEN')
                review_o=reseal(dict(o,clock=o['clock']+2*S))
                reviewed=contract.review(completed(p,done),review_o,a,now_us=self.now+2*S,gate_state='OPEN',generation=GENERATION)
                self.assertEqual(done['status'],'VALIDATED_PROPOSAL');self.assertEqual(reviewed['status'],'REVIEWABLE')
                self.assertIsNotNone(gold,'prechange hashes must be frozen before claiming regression success')
                self.assertEqual([sha256(canonical(x).encode()).hexdigest() for x in (p,done,reviewed)],gold)


if __name__=='__main__':unittest.main()
