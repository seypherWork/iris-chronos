"""Synthetic HTTP/profile tests only; no model or native IRIS proof."""
from dataclasses import replace
from hashlib import sha256
import http.client
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
from threading import Thread
from types import SimpleNamespace
import time
import unittest
from unittest.mock import patch
import uuid

ROOT=Path(os.environ.get('CHRONOS_REPLAY_SOURCE_ROOT',Path(__file__).resolve().parents[2]))
sys.path.insert(0,str(ROOT/'src'))
from chronos_transport import guard
from chronos_transport.deployment import Profile,Allowance,DeploymentError
spec=importlib.util.spec_from_file_location('replay_provider_under_test',ROOT/'deployment/replay_provider.py')
provider=importlib.util.module_from_spec(spec);spec.loader.exec_module(provider)

IDENT='a'*32;CORPUS='b'*64;FIXTURE='c'*64


def profile(contract='e1',limit=5):
    return Profile.parse(provider.canonical(provider.plan(IDENT,limit,CORPUS,FIXTURE,contract=contract)))


def request(settings,contract='e1',request_id=None):
    if contract=='e1':
        content='{"synthetic_fixture_test":true}'
    else:
        content=json.dumps(dict(schema=guard.PLAN_V2_CONTRACT,renderer_version=guard.PLAN_V2_RENDERER,
            conversation_id='synthetic-chat',turn_id='synthetic-turn',context_digest='d'*64,catalog_digest='e'*64,
            message='Why was this option recommended?',history=[],available_topics=sorted(guard.PLAN_V2_TOPICS),case_explanations={}))
    return dict(model=guard.RECORDED_MODEL,messages=[dict(role='system',content='Synthetic test prompt'),dict(role='user',content=content)],
        temperature=0,max_tokens=2048,response_format=dict(type='json_schema',json_schema=dict(name='chronos_e1' if contract=='e1' else 'chronos_c2_v2',strict=True,schema=settings.schema)),
        reasoning_effort='none',user=request_id or str(uuid.uuid4()),chronos_deadline_us=time.time_ns()//1000+28000000,
        chronos_profile_sha256=settings.profile_sha256)


def response_text(contract,raw):
    if contract==guard.EXTRACTION_CONTRACT:
        return json.dumps(dict(schema_version=contract,interpreted_preference='CHEAPEST_ON_TIME',reason_code='PREFERENCE_MATCH',
            source_ids=['synthetic-message'],rationale='Synthetic recorded test interpretation.',clarification=None))
    wire=json.loads(raw)
    return json.dumps({k:wire[k] for k in ('schema','renderer_version','conversation_id','turn_id','context_digest','catalog_digest')}
        |dict(topics=['DECISION'],detail='concise',preference=None))


class ProviderTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name).resolve();self.servers=[]
        self.calls=[]

    def tearDown(self):
        for server,thread in self.servers:
            server.shutdown();server.server_close();thread.join(timeout=2)
        self.temp.cleanup()

    def settings(self,contract='e1',limit=5,handler=None):
        p=profile(contract,limit)
        allowance=Allowance.create(self.root/(uuid.uuid4().hex+'.sqlite'),p)
        def recorded(kind,raw,prompt):
            self.calls.append((kind,raw,prompt))
            return SimpleNamespace(response_text=response_text(kind,raw),metadata=dict(mode='RECORDED_FIXTURE',fresh_inference=False,corpus_sha256=CORPUS,fixture_sha256=FIXTURE))
        return guard.configured_settings(provider.schema(contract),allowance,recorded_handler=handler or recorded),allowance

    def server(self,settings):
        server=guard.make_server(settings,port=0)
        thread=Thread(target=server.serve_forever,kwargs={'poll_interval':0.01},daemon=True);thread.start()
        self.servers.append((server,thread));return server

    def http(self,server,body=None,method='POST'):
        conn=http.client.HTTPConnection('127.0.0.1',server.server_address[1],timeout=3)
        try:
            conn.request(method,'/v1/chat/completions',body=None if body is None else json.dumps(body),headers={'Content-Type':'application/json'})
            answer=conn.getresponse();return answer.status,json.loads(answer.read())
        finally:conn.close()

    def test_live_public_profile_bytes_and_digest_unchanged(self):
        old=dict(version=3,deployment_id=IDENT,provider='ollama',model='local-test-model',schema_sha256='d'*64,request_limit=5,
                 local_port=11434,reasoning_effort='none',response_contract=guard.EXTRACTION_CONTRACT)
        p=Profile.parse(provider.canonical(old))
        self.assertEqual(old,p.public())
        self.assertEqual(sha256(provider.canonical(old)).hexdigest(),p.digest)
        self.assertEqual('http://127.0.0.1:11434/v1/chat/completions',p.endpoint)
        self.assertNotIn('replay_corpus_sha256',p.public())
        cloud=old|dict(provider='openai-chat-json',local_port=None)
        self.assertEqual('https://api.openai.com/v1/chat/completions',Profile.parse(provider.canonical(cloud)).endpoint)

    def test_recorded_profile_rejects_upstream_alias_effort_versions_or_missing_hashes(self):
        valid=profile().public()
        for key,value in (('model','qwen-actual'),('reasoning_effort','low'),('local_port',11434),('version',4),('replay_fixture_sha256','bad')):
            with self.subTest(field=key),self.assertRaises(DeploymentError):Profile.parse(provider.canonical(valid|{key:value}))
        missing=dict(valid);missing.pop('replay_corpus_sha256')
        with self.assertRaises(DeploymentError):Profile.parse(provider.canonical(missing))
        with self.assertRaises(DeploymentError):Profile.parse(provider.canonical(valid|dict(provider='ollama',local_port=11434)))

    def test_recorded_endpoint_can_never_fall_through_to_cloud(self):
        with self.assertRaisesRegex(DeploymentError,'RECORDED_FIXTURE_HAS_NO_UPSTREAM'):_=profile().endpoint
        self.assertEqual(6,profile('c2-v2').version)
        self.assertEqual(guard.PLAN_V2_CONTRACT,profile('c2-v2').response_contract)

    def test_profile_digest_pins_both_corpus_and_fixture(self):
        p=profile()
        self.assertNotEqual(p.digest,Profile.parse(provider.canonical(p.public()|dict(replay_corpus_sha256='d'*64))).digest)
        self.assertNotEqual(p.digest,Profile.parse(provider.canonical(p.public()|dict(replay_fixture_sha256='d'*64))).digest)
        allowance=Allowance.create(self.root/'owned.sqlite',p)
        with self.assertRaisesRegex(DeploymentError,'PROFILE_MISMATCH'):
            Allowance(allowance.path,Profile.parse(provider.canonical(p.public()|dict(replay_fixture_sha256='d'*64))))

    def test_plan_is_read_only_and_uses_distinct_contract_profiles(self):
        before=list(self.root.iterdir())
        e1=provider.plan(IDENT,4,CORPUS,FIXTURE)
        c2=provider.plan(IDENT,4,CORPUS,FIXTURE,contract='c2-v2')
        self.assertEqual(before,list(self.root.iterdir()))
        self.assertEqual(e1['replay_corpus_sha256'],c2['replay_corpus_sha256'])
        self.assertNotEqual(Profile.parse(provider.canonical(e1)).digest,Profile.parse(provider.canonical(c2)).digest)
        self.assertIsNone(e1['local_port'])

    def test_recorded_http_has_zero_egress_exact_receipt_and_zero_new_tokens(self):
        settings,allowance=self.settings();server=self.server(settings);body=request(settings)
        with (patch.object(guard,'verify_context_policy',side_effect=AssertionError('Unexpected capability GET')) as capability,
              patch.object(guard,'upstream_exchange',side_effect=AssertionError('Unexpected egress')) as upstream):
            status,answer=self.http(server,body)
            self.assertEqual(200,status);capability.assert_not_called();upstream.assert_not_called()
        self.assertEqual(1,len(self.calls));self.assertEqual(1,allowance.snapshot()['used'])
        self.assertEqual(sha256(b'Synthetic test prompt').hexdigest(),self.calls[0][2])
        self.assertEqual(dict(prompt_tokens=0,completion_tokens=0,total_tokens=0),answer['usage'])
        self.assertEqual({'version','request_id','finish_reason','model','profile_sha256','response_contract'},set(answer['chronos_transport']))
        self.assertEqual(guard.RECORDED_MODEL,answer['model'])

    def test_c2_http_preserves_bound_plan_receipt_contract(self):
        settings,allowance=self.settings('c2-v2');server=self.server(settings)
        status,answer=self.http(server,request(settings,'c2-v2'))
        self.assertEqual(200,status)
        self.assertEqual(guard.PLAN_V2_CONTRACT,answer['chronos_transport']['response_contract'])
        self.assertEqual('synthetic-chat',json.loads(answer['choices'][0]['message']['content'])['conversation_id'])
        self.assertEqual(1,allowance.snapshot()['used'])

    def test_duplicate_request_is_rejected_without_second_handler_call(self):
        settings,allowance=self.settings();server=self.server(settings);body=request(settings)
        self.assertEqual(200,self.http(server,body)[0])
        status,answer=self.http(server,body)
        self.assertEqual((422,'REQUEST_ALREADY_USED'),(status,answer['error']['code']))
        self.assertEqual(1,len(self.calls));self.assertEqual(1,allowance.snapshot()['used'])

    def test_failed_replay_keeps_claim_and_never_calls_model(self):
        def unsupported(*_):raise ValueError('Private case text must never be returned')
        settings,allowance=self.settings(handler=unsupported);server=self.server(settings);body=request(settings)
        status,answer=self.http(server,body)
        self.assertEqual((422,'RECORDED_INPUT_UNSUPPORTED'),(status,answer['error']['code']))
        self.assertNotIn('Private',json.dumps(answer));self.assertEqual(1,allowance.snapshot()['used'])
        self.assertEqual('REQUEST_ALREADY_USED',self.http(server,body)[1]['error']['code'])

    def test_invalid_profile_deadline_and_get_do_not_spend_quota(self):
        settings,allowance=self.settings();server=self.server(settings)
        body=request(settings);body['chronos_profile_sha256']='f'*64
        self.assertEqual('PROFILE_MISMATCH',self.http(server,body)[1]['error']['code'])
        body=request(settings);body['chronos_deadline_us']=time.time_ns()//1000-1
        self.assertEqual('REQUEST_DEADLINE',self.http(server,body)[1]['error']['code'])
        self.assertEqual(404,self.http(server,method='GET')[0])
        self.assertEqual(0,allowance.snapshot()['used']);self.assertFalse(self.calls)

    def test_recorded_settings_refuse_any_upstream_or_unpinned_handler(self):
        settings,_=self.settings()
        for changed in (dict(upstream_port=11434),dict(recorded_handler=None),dict(model='qwen-actual'),dict(transport_kind='unknown'),dict(claims=None)):
            with self.subTest(changed=changed),self.assertRaises(ValueError):guard.make_server(replace(settings,**changed),port=0)

    def test_corpus_validation_occurs_before_initialization(self):
        runtime=self.root/'runtime';runtime.mkdir();corpus=self.root/'source.json';corpus.write_bytes(b'not a verified corpus')
        with patch.object(provider,'_corpus',side_effect=ValueError('REPLAY_CORPUS_CHANGED')):
            with self.assertRaises(ValueError):provider.prepare(IDENT,4,CORPUS,FIXTURE,corpus_path=corpus,allowed_evidence={'d'*64:'synthetic-model'},
                authorize_id=IDENT,runtime=runtime)
        self.assertEqual([],list(runtime.iterdir()))

    def fixture_capture(self):
        # Reuse the protocol-generating synthetic fixture builder, not a fake
        # production corpus or a declaration that an actual model executed.
        fixture_spec=importlib.util.spec_from_file_location('provider_fixture_capture_tests',ROOT/'tests/transport/test_fixture_replay.py')
        fixture=importlib.util.module_from_spec(fixture_spec);fixture_spec.loader.exec_module(fixture)
        records=[fixture.record(fixture.f.E1,fixture.e1(),fixture.e1_answer(),'e1-economy'),
                 fixture.record(fixture.f.C2,fixture.c2(),fixture.c2_answer(fixture.c2()),'c2-why')]
        raw=fixture.encoded(records);path=self.root/'synthetic-corpus.json';path.write_bytes(raw)
        return fixture,path,sha256(raw).hexdigest(),fixture.f.fixture_bank_digest()

    def test_complete_python_prepare_status_and_http_with_sealed_synthetic_fixture_corpus(self):
        fixture,path,corpus_sha,bank_sha=self.fixture_capture()
        runtime=self.root/'runtime';runtime.mkdir()
        observed=provider.prepare(IDENT,4,corpus_sha,bank_sha,corpus_path=path,allowed_evidence=fixture.ALLOWLIST,
                                 authorize_id=IDENT,runtime=runtime,allow_synthetic=True)
        self.assertEqual('RECORDED_FIXTURE',observed['mode'])
        self.assertFalse(observed['model_tested']);self.assertEqual(0,observed['allowance']['used'])
        settings=provider.configured(IDENT,runtime=runtime,allow_synthetic=True)
        server=self.server(settings);body=request(settings)
        body['messages'][0]['content']='synthetic fixture prompt only'
        body['messages'][1]['content']=fixture.e1(deployment_id='2'*32)
        with patch.object(guard,'upstream_exchange',side_effect=AssertionError('No egress')):
            status,answer=self.http(server,body)
        self.assertEqual(200,status)
        self.assertEqual(fixture.e1_answer(),answer['choices'][0]['message']['content'])
        final=provider.status(IDENT,runtime=runtime,allow_synthetic=True)
        self.assertEqual(1,final['allowance']['used'])
        self.assertEqual(corpus_sha,final['profile']['replay_corpus_sha256'])
        self.assertEqual(final['profile_sha256'],final['binding_sha256'])
        with self.assertRaisesRegex(ValueError,'PROVIDER_STATE_EXISTS_NO_RESET'):
            provider.prepare(IDENT,4,corpus_sha,bank_sha,corpus_path=path,allowed_evidence=fixture.ALLOWLIST,
                             authorize_id=IDENT,runtime=runtime,allow_synthetic=True)
        self.assertEqual(1,provider.status(IDENT,runtime=runtime,allow_synthetic=True)['allowance']['used'])

    def test_default_prepare_refuses_synthetic_capture_without_creating_quota(self):
        fixture,path,corpus_sha,bank_sha=self.fixture_capture()
        runtime=self.root/'runtime';runtime.mkdir()
        with self.assertRaisesRegex(ValueError,'REPLAY_SYNTHETIC_OR_UNKNOWN_PROVENANCE'):
            provider.prepare(IDENT,4,corpus_sha,bank_sha,corpus_path=path,allowed_evidence=fixture.ALLOWLIST,
                             authorize_id=IDENT,runtime=runtime)
        self.assertEqual([],list(runtime.iterdir()))

    def test_status_rejects_tampered_corpus_or_evidence_allowlist(self):
        fixture,path,corpus_sha,bank_sha=self.fixture_capture()
        for field in ('corpus','allowlist'):
            runtime=self.root/field;runtime.mkdir()
            provider.prepare(IDENT,4,corpus_sha,bank_sha,corpus_path=path,allowed_evidence=fixture.ALLOWLIST,
                             authorize_id=IDENT,runtime=runtime,allow_synthetic=True)
            area=runtime/'fixture-provider'
            if field=='corpus':(area/'corpus.json').write_bytes(b'{}')
            else:(area/'evidence-allowlist.json').write_text(json.dumps({fixture.EVIDENCE:'wrong-model'}),encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'REPLAY_CORPUS_CHANGED' if field=='corpus' else 'REPLAY_PROVENANCE_NOT_ALLOWED'):
                provider.status(IDENT,runtime=runtime,allow_synthetic=True)

    def test_e1_and_c2_use_separate_runtime_and_durable_quotas(self):
        fixture,path,corpus_sha,bank_sha=self.fixture_capture()
        roots={}
        for kind in ('e1','c2-v2'):
            runtime=self.root/kind;runtime.mkdir();roots[kind]=runtime
            observed=provider.prepare(IDENT,4,corpus_sha,bank_sha,corpus_path=path,allowed_evidence=fixture.ALLOWLIST,
                authorize_id=IDENT,runtime=runtime,contract=kind,allow_synthetic=True)
            self.assertEqual(0,observed['allowance']['used'])
        self.assertTrue((roots['e1']/'fixture-provider').is_dir())
        self.assertTrue((roots['c2-v2']/'fixture-conversation-provider').is_dir())
        settings=provider.configured(IDENT,runtime=roots['c2-v2'],contract='c2-v2',allow_synthetic=True)
        body=request(settings,'c2-v2');body['messages'][0]['content']='synthetic fixture prompt only';body['messages'][1]['content']=fixture.c2()
        self.assertEqual(200,self.http(self.server(settings),body)[0])
        self.assertEqual(0,provider.status(IDENT,runtime=roots['e1'],allow_synthetic=True)['allowance']['used'])
        self.assertEqual(1,provider.status(IDENT,runtime=roots['c2-v2'],contract='c2-v2',allow_synthetic=True)['allowance']['used'])


if __name__=='__main__':unittest.main()
