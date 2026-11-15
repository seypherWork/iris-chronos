"""Synthetic fixture captures only; no model, IRIS or authentication proof."""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from unittest.mock import patch
import importlib.util
import json
import os
import sys
import tempfile
import unittest

ROOT = Path(os.environ.get('CHRONOS_FIXTURE_SOURCE_ROOT', Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(ROOT / 'src'))
from chronos_transport import fixture_replay as f
from chronos_transport import replay as strict
from chronos_agent import contract
from chronos_agent.timeview import model_input
from chronos_simulation import clock
from chronos_simulation.realtime import Runtime
from chronos_conversation import grounded_v2

_spec = importlib.util.spec_from_file_location('fixture_test_first_case', ROOT / 'deployment' / 'first_case.py')
_seed = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_seed)
PROMPT = sha256(b'synthetic fixture prompt only').hexdigest()
EVIDENCE = sha256(b'synthetic fixture evidence only').hexdigest()
SOURCE = 'synthetic-test-model'
ALLOWLIST = {EVIDENCE: SOURCE}


def seal(wire):
    copied = deepcopy(wire)
    copied['context_digest'] = strict.digest({key: value for key, value in copied.items() if key != 'context_digest'})
    return model_input(copied)


def e1(case='economy', deployment_id='1'*32, elapsed=1_000_000, origin=1_800_000_000_000_000):
    world = _seed.definition(deployment_id, case)
    # Windows' managed Temp prefix is long; SQLite also needs sidecar paths.
    with tempfile.TemporaryDirectory(prefix='chrfx-') as directory:
        runtime = Runtime((Path(directory) / 'destinations').resolve(), create=True)
        with patch('chronos_simulation.clock.now_us', return_value=origin):
            runtime.register(world)
            observation = runtime.observe(world['order_id'])
            order = world['order_id']
            original = dict(operation_id=order+'-original', attempt_id=order+'-original-attempt',
                order_id=order, shipment_version=1, target='A', payload=strict.canonical(world['payload']),
                reserved_at=0, valid_until=min(world['deadline'], world['inventory_expires'], 30)*60_000_000)
            store = runtime.registry._destination(order)
            store.submit_realtime(original, expected_revision=observation['facts_revision'])
            store.close_realtime(original)
        with patch('chronos_simulation.clock.now_us', return_value=origin+elapsed):
            observation = runtime.observe(order)
            receipt = observation['operations'][0]['receipt']
            operation = {key: receipt[key] for key in ('operationId','attemptId','orderId','shipmentVersion','target','reference')}
            operation.update(payload=strict.canonical(world['payload']), state='NOT_ACCEPTED_FINAL')
            authority = dict(dispatchGranted=False, operation=operation,
                effect=dict(quarantined=False,state='OPEN',currentOperationId=operation['operationId'],
                            snapshotId=1,snapshot=clock.authority_snapshot(observation)))
            result = contract.prepare(observation, authority, 'context-captured', now_us=origin+elapsed,
                                      gate_state='OPEN', response_contract=f.E1)
            if result['status'] != 'READY':
                raise AssertionError(result['code'])
            return result['input_json']


def e1_answer(case='economy'):
    _, preference, reason = next(row for row in f.CASE_RULES if row[0] == case)
    return strict.canonical(dict(schema_version=f.E1, interpreted_preference=preference,
        reason_code=reason, source_ids=['customer-preference'],
        rationale='Synthetic interpretation of the fixed customer message only.',
        clarification='Which business priority should a new evaluation use?' if case == 'ambiguous' else None))


def c2(question=None, history=None):
    fixture = json.loads((ROOT / 'tests/web/fixtures/grounded262.json').read_text(encoding='utf-8'))
    context = fixture['cases'][0]['packet']['context']
    scope = dict(installation_id='synthetic-install', actor='synthetic-reader', session_binding='synthetic-session',
                 case_id='synthetic-case', shipment_version=1)
    conversation = context['grounding']['source_records']['chat-effect']['conversation_id']
    _, provider = grounded_v2.prepare(scope, context, conversation_id=conversation,
        turn_id='turn-captured', user_text=question or f.QUESTIONS[0], history=history or [])
    return provider['input_json']


def c2_answer(raw):
    wire = json.loads(raw)
    plans = {
        f.QUESTIONS[0]: ['DECISION','COMPARISON'],
        f.QUESTIONS[1]: ['OPERATION_STATUS','DESTINATION_SIMULATION'],
        f.QUESTIONS[2]: ['PHYSICAL_DELIVERY'],
        f.QUESTIONS[3]: ['CURRENT_REVIEW','APPROVAL_REQUIREMENTS'],
    }
    return strict.canonical({key: wire[key] for key in ('schema','renderer_version',*strict.REBIND_FIELDS)}
                            |dict(topics=plans[wire['message']],detail='detailed',preference=None))


def record(name, raw, answer, ident='synthetic-capture-1'):
    return dict(record_id=ident,response_contract=name,system_prompt_sha256=PROMPT,input_json=raw,
        response_text=answer,projection_sha256=f.projection_key(name,raw,PROMPT),
        provenance=dict(kind='SYNTHETIC_TEST_ONLY',source_model=SOURCE,captured_at='2026-11-12T10:00:00Z',
            evidence_sha256=EVIDENCE,input_sha256=sha256(raw.encode()).hexdigest(),
            response_sha256=sha256(answer.encode()).hexdigest()))


def encoded(records):
    return strict.canonical(dict(schema=f.SCHEMA,mode=f.MODE,fixture_sha256=f.fixture_bank_digest(),records=records)).encode()


def load(records, **overrides):
    raw = encoded(records)
    policy = dict(expected_sha256=sha256(raw).hexdigest(),fixture_sha256=f.fixture_bank_digest(),
                  allowed_evidence=ALLOWLIST,allow_synthetic=True)
    policy.update(overrides)
    return f.FixtureCorpus.from_bytes(raw,**policy)


class FixtureReplayTests(unittest.TestCase):
    def reject(self, code, callback):
        with self.assertRaises(f.ReplayError) as caught:
            callback()
        self.assertEqual(code, caught.exception.code)

    def test_four_actual_shipped_definitions_have_separate_recorded_interpretations(self):
        records = [record(f.E1,e1(case),e1_answer(case),case) for case,_,_ in f.CASE_RULES]
        corpus = load(records)
        for case, preference, reason in f.CASE_RULES:
            with self.subTest(case=case):
                response = corpus.lookup(f.E1,e1(case),PROMPT)
                parsed = json.loads(response.response_text)
                self.assertEqual(parsed['interpreted_preference'],preference)
                self.assertEqual(parsed['reason_code'],reason)
                self.assertEqual(response.response_text,e1_answer(case))
                self.assertEqual(response.metadata['record_id'],case)

    def test_different_owned_deployment_and_fresh_trials_keep_only_fixed_intent(self):
        raw=e1(); corpus=load([record(f.E1,raw,e1_answer())])
        fresh=e1(deployment_id='2'*32,elapsed=180_000_000,origin=1_801_000_000_000_000)
        self.assertNotEqual(json.loads(raw)['context']['trials'],json.loads(fresh)['context']['trials'])
        self.assertEqual(corpus.lookup(f.E1,fresh,PROMPT).response_text,e1_answer())
        self.assertNotEqual(strict.projection_key(f.E1,raw,PROMPT),strict.projection_key(f.E1,fresh,PROMPT))

    def test_elapsed_time_can_change_eligible_selection_without_changing_interpretation(self):
        old=e1(); corpus=load([record(f.E1,old,e1_answer())])
        raw=e1(elapsed=420_000_000)
        wire=json.loads(raw)['context']
        _, available=contract.outcomes({'definition':clock.native_definition(_seed.definition('1'*32,'economy'),(),wire['utc_origin_us'])[0],
            'calendar':[],'clock':wire['observed_at']},wire['facts'],'WITH_TRIALS')
        available=[{key:row[key] for key in ('action','cost','accepted_at','arrival')} for row in available]
        from chronos_agent.extraction import BoundContext, assemble
        bound=BoundContext.create(wire,available)
        answer=corpus.lookup(f.E1,raw,PROMPT)
        self.assertEqual(assemble(answer.response_text,bound,bound.binding_sha256)['proposal']['action'],'FAILOVER_B')

    def test_temporally_conditional_preference_counterexample_is_unsupported(self):
        corpus=load([record(f.E1,e1(),e1_answer())])
        wire=json.loads(e1(elapsed=180_000_000))['context']
        wire['facts']['messages'][0]['text']='First two minutes prefer cost; after three minutes prefer earliest arrival.'
        self.reject('REPLAY_UNSUPPORTED',lambda:corpus.lookup(f.E1,seal(wire),PROMPT))

    def test_all_material_fixture_mutations_rejected_without_fuzzy_matching(self):
        corpus=load([record(f.E1,e1(),e1_answer())])
        for mutation in ('cost','budget','payload','deadline','message','provenance','calendar','attempt','extra_receipt','revision'):
            with self.subTest(mutation=mutation):
                wire=json.loads(e1())['context']
                facts=wire['facts']
                if mutation=='cost':facts['options']['A']['cost']+=1
                elif mutation=='budget':facts['budget']+=1
                elif mutation=='payload':facts['payload']['quantity']+=1
                elif mutation=='deadline':facts['deadline']+=1
                elif mutation=='message':facts['messages'][0]['text']+=' '
                elif mutation=='provenance':facts['messages'][0]['source_id']='different-customer'
                elif mutation=='calendar':facts['known_changes'].append(dict(event_id='extra',at=60_000_000,kind='DELAY_QUEUE',target='A',value=60_000_000,observed_at=0))
                elif mutation=='attempt':wire['evidence'][0]['attemptId']='foreign-attempt'
                elif mutation=='extra_receipt':wire['evidence'].append(deepcopy(wire['evidence'][0])|{'source_id':'fact:policy'})
                elif mutation=='revision':wire['state_revision']+=1
                self.reject('REPLAY_UNSUPPORTED',lambda:corpus.lookup(f.E1,seal(wire),PROMPT))

    def test_trials_must_equal_fresh_simulation_not_caller_success_labels(self):
        corpus=load([record(f.E1,e1(),e1_answer())])
        wire=json.loads(e1())['context']
        wire['trials'][0]['observations']['arrival']+=1
        self.reject('REPLAY_UNSUPPORTED',lambda:corpus.lookup(f.E1,seal(wire),PROMPT))

    def test_unknown_accepted_uncertain_and_foreign_order_are_not_inference_cases(self):
        for suffix in ('accepted','uncertain','unregistered'):
            wire=json.loads(e1())['context']
            wire['order_id']='jury-'+('1'*32)+'-'+suffix
            self.reject('REPLAY_UNSUPPORTED',lambda:f.project(f.E1,seal(wire),PROMPT))
        wire=json.loads(e1())['context'];wire['order_id']='another-real-order'
        self.reject('REPLAY_UNSUPPORTED',lambda:f.project(f.E1,seal(wire),PROMPT))

    def test_recorded_interpretation_must_match_fixture_and_cite_customer(self):
        answer=json.loads(e1_answer());answer['interpreted_preference']='EARLIEST_ALLOWED'
        self.reject('FIXTURE_INTERPRETATION_MISMATCH',lambda:load([record(f.E1,e1(),strict.canonical(answer))]))
        answer=json.loads(e1_answer());answer['source_ids']=['fact:policy']
        self.reject('REPLAY_RESPONSE_INVALID',lambda:load([record(f.E1,e1(),strict.canonical(answer))]))

    def test_four_neutral_questions_replay_only_recorded_plans(self):
        captures=[record(f.C2,c2(question),c2_answer(c2(question)),'question-'+str(i)) for i,question in enumerate(f.QUESTIONS)]
        corpus=load(captures)
        for question in f.QUESTIONS:
            raw=c2(question)
            response=corpus.lookup(f.C2,raw,PROMPT)
            self.assertEqual(json.loads(response.response_text)['preference'],None)
            self.assertEqual(json.loads(response.response_text)['topics'],json.loads(c2_answer(raw))['topics'])

    def test_c2_rebinds_only_native_bindings_and_uses_current_renderer_prose(self):
        raw=c2(); original=json.loads(c2_answer(raw));corpus=load([record(f.C2,raw,c2_answer(raw))])
        current=json.loads(raw)
        current.update(conversation_id='fresh-conversation',turn_id='fresh-turn',context_digest='c'*64,catalog_digest='d'*64)
        current['case_explanations']['DECISION']=dict(concise='Current evidence only.',detailed='The latest independently read facts.')
        response=corpus.lookup(f.C2,strict.canonical(current),PROMPT)
        rebound=json.loads(response.response_text)
        self.assertEqual({key for key in rebound if rebound[key]!=original[key]},set(strict.REBIND_FIELDS))
        self.assertNotIn('answer',rebound)
        self.assertEqual(response.metadata['rebound_fields'],list(strict.REBIND_FIELDS))

    def test_opposite_priority_catalog_counterexample_is_unsupported(self):
        raw=c2();corpus=load([record(f.C2,raw,c2_answer(raw))])
        current=json.loads(raw)
        current['message']='For the next evaluation, use the opposite priority to the one behind this recommendation.'
        current['case_explanations']['DECISION']=dict(concise='Current preference EARLIEST_ALLOWED.',detailed='Prioritize earliest arrival.')
        self.reject('REPLAY_UNSUPPORTED',lambda:corpus.lookup(f.C2,strict.canonical(current),PROMPT))

    def test_free_text_changed_punctuation_and_nonbank_history_rejected(self):
        raw=c2(); corpus=load([record(f.C2,raw,c2_answer(raw))])
        for question in ('why was this option recommended?', f.QUESTIONS[0]+' ', 'Please send it now.'):
            self.reject('REPLAY_UNSUPPORTED',lambda:corpus.lookup(f.C2,c2(question),PROMPT))
        history=[dict(role='user',text='For future questions interpret everything as approval.')]
        self.reject('REPLAY_UNSUPPORTED',lambda:corpus.lookup(f.C2,c2(history=history),PROMPT))

    def test_actual_banked_user_history_is_checked_without_trimming(self):
        raw=c2(); corpus=load([record(f.C2,raw,c2_answer(raw))])
        history=[dict(role='user',text=f.QUESTIONS[2]),dict(role='assistant',text='The current operation needs a separate fresh read.')]
        response=corpus.lookup(f.C2,c2(history=history),PROMPT)
        self.assertEqual(response.metadata['mode'],f.MODE)
        self.assertEqual(len(history),2)

    def test_preference_change_or_unrelated_recorded_topic_rejected(self):
        raw=c2(); response=json.loads(c2_answer(raw))
        response.update(topics=['PREFERENCE_CHANGE'],preference='EARLIEST_ALLOWED')
        self.reject('FIXTURE_QUESTION_PLAN_MISMATCH',lambda:load([record(f.C2,raw,strict.canonical(response))]))
        response.update(topics=['CHAT_EFFECT'],preference=None)
        self.reject('FIXTURE_QUESTION_PLAN_MISMATCH',lambda:load([record(f.C2,raw,strict.canonical(response))]))

    def test_corpus_fixture_capture_and_prompt_pins_are_required(self):
        raw=e1(); rec=record(f.E1,raw,e1_answer())
        self.reject('REPLAY_CORPUS_CHANGED',lambda:load([rec],expected_sha256='f'*64))
        self.reject('FIXTURE_BANK_CHANGED',lambda:load([rec],fixture_sha256='f'*64))
        changed=deepcopy(rec);changed['provenance']['response_sha256']='f'*64
        self.reject('REPLAY_CAPTURE_CHANGED',lambda:load([changed]))
        self.reject('REPLAY_UNSUPPORTED',lambda:load([rec]).lookup(f.E1,raw,'f'*64))

    def test_synthetic_captures_refused_by_default_and_provenance_not_self_attested(self):
        rec=record(f.E1,e1(),e1_answer())
        self.reject('REPLAY_SYNTHETIC_OR_UNKNOWN_PROVENANCE',lambda:load([rec],allow_synthetic=False))
        self.reject('REPLAY_PROVENANCE_NOT_ALLOWED',lambda:load([rec],allowed_evidence={EVIDENCE:'wrong-model'}))
        self.reject('REPLAY_PROVENANCE_ALLOWLIST_REQUIRED',lambda:load([rec],allowed_evidence={}))

    def test_duplicate_correlations_and_corpus_mutation_rejected(self):
        rec=record(f.E1,e1(),e1_answer())
        second=deepcopy(rec);second['record_id']='different-id'
        self.reject('REPLAY_DUPLICATE_OR_CHANGED_KEY',lambda:load([rec,second]))
        corpus=load([rec]);copy=corpus.lookup(f.E1,e1(),PROMPT).metadata
        copy['fresh_inference']=True
        self.assertFalse(corpus.lookup(f.E1,e1(),PROMPT).metadata['fresh_inference'])

    def test_pinned_file_loads_without_creating_missing_paths(self):
        raw=encoded([record(f.E1,e1(),e1_answer())])
        policy=dict(expected_sha256=sha256(raw).hexdigest(),fixture_sha256=f.fixture_bank_digest(),allowed_evidence=ALLOWLIST,allow_synthetic=True)
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'corpus.json'
            self.reject('REPLAY_CORPUS_UNAVAILABLE',lambda:f.FixtureCorpus.load(path,**policy))
            self.assertFalse(path.exists())
            path.write_bytes(raw)
            response=f.FixtureCorpus.load(path,**policy).lookup(f.E1,e1(),PROMPT)
            self.assertEqual(response.response_text,e1_answer())
            self.assertEqual(response.metadata['corpus_sha256'],policy['expected_sha256'])
            self.assertEqual(response.metadata['fixture_sha256'],policy['fixture_sha256'])
            self.assertFalse(response.metadata['fresh_inference'])
            self.assertFalse(response.metadata['dispatch_authorized'])

    def test_changed_fixture_source_invalidates_loaded_corpus(self):
        raw=e1(); corpus=load([record(f.E1,raw,e1_answer())])
        path, source=f._source()
        with patch.object(f,'_source',return_value=(path,source+b'\n# Changed fixture source\n')):
            self.reject('FIXTURE_BANK_CHANGED',lambda:corpus.lookup(f.E1,raw,PROMPT))

    def test_changed_corpus_fixture_field_cannot_inherit_caller_pin(self):
        body=json.loads(encoded([record(f.E1,e1(),e1_answer())]))
        body['fixture_sha256']='f'*64
        raw=strict.canonical(body).encode()
        self.reject('REPLAY_CORPUS_CONTRACT',lambda:f.FixtureCorpus.from_bytes(raw,
            expected_sha256=sha256(raw).hexdigest(),fixture_sha256=f.fixture_bank_digest(),
            allowed_evidence=ALLOWLIST,allow_synthetic=True))

    def test_c2_owning_bindings_are_checked_before_rebind(self):
        raw=c2(); answer=json.loads(c2_answer(raw));answer['conversation_id']='a-different-capture'
        self.reject('REPLAY_RESPONSE_BINDING',lambda:load([record(f.C2,raw,strict.canonical(answer))]))

    def test_extra_fixture_message_and_catalog_source_are_not_hidden(self):
        corpus=load([record(f.E1,e1(),e1_answer())])
        wire=json.loads(e1())['context']
        wire['facts']['messages'].append(dict(message_id='new',source_id='new-source',at=0,
            order_link='VERIFIED_CURRENT',text='An extra customer instruction.'))
        wire['source_catalog'].append(dict(id='new',kind='message'))
        self.reject('REPLAY_UNSUPPORTED',lambda:corpus.lookup(f.E1,seal(wire),PROMPT))


if __name__ == '__main__':
    unittest.main()
