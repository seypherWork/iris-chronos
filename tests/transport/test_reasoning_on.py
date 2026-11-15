"""Synthetic pilot checks only: no model, Docker, credentials or native IRIS.

HTTP tests contact a local guard with a mocked upstream. They establish wire,
capability and allowance behavior, not reasoning quality or SDK compatibility.
"""
from contextlib import redirect_stdout
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import http.client
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
from threading import Thread
import time
import unittest
from unittest.mock import patch
import uuid

ROOT=Path(os.environ.get('CHRONOS_REASONING_SOURCE_ROOT',Path(__file__).resolve().parents[2]))
sys.path.insert(0,str(ROOT/'src'))
from chronos_transport import guard as g
from chronos_transport.deployment import Profile,Allowance,DeploymentError


def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec)
    sys.modules[name]=module
    spec.loader.exec_module(module)
    return module


provider=load('_reasoning_on_provider',ROOT/'deployment/local_provider.py')
with patch.dict(sys.modules,{'local_provider':provider}):
    readiness=load('_reasoning_on_readiness',ROOT/'deployment/model_readiness.py')
E1=json.loads((ROOT/'src/chronos_transport/extraction-schema.json').read_bytes())
C1=json.loads((ROOT/'src/chronos_transport/conversation-schema.json').read_bytes())
A1=json.loads((ROOT/'src/chronos_transport/proposal-schema-v2.json').read_bytes())
IDENT='a'*32
MODEL='synthetic-thinking-pilot'


def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True)


def public(effort='on'):
    return dict(version=3,deployment_id=IDENT,provider='ollama',model=MODEL,
        schema_sha256=sha256(canonical(E1).encode()).hexdigest(),request_limit=2,
        local_port=11434,reasoning_effort=effort,response_contract=g.EXTRACTION_CONTRACT)


def body(settings,schema=None):
    schema=settings.schema if schema is None else schema
    contract=g.response_contract(schema)
    return dict(model=settings.model,messages=[dict(role='system',content='Synthetic contract test'),
        dict(role='user',content='{"synthetic_test":true}')],temperature=0,max_tokens=2048,
        response_format=dict(type='json_schema',json_schema=dict(
            name='chronos_e1' if contract==g.EXTRACTION_CONTRACT else 'chronos_c1' if contract==g.CONVERSATION_CONTRACT else 'chronos_a1',
            strict=True,schema=schema)),reasoning_effort=settings.reasoning_effort,user=str(uuid.uuid4()),
        chronos_deadline_us=time.time_ns()//1000+28000000,chronos_profile_sha256=settings.profile_sha256)


class ReasoningOnTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='chronos-thinking-pilot-tests-')
        self.root=Path(self.temp.name).resolve();self.addCleanup(self.temp.cleanup)

    def settings(self,effort='on'):
        p=Profile.parse(canonical(public(effort)))
        allowance=Allowance.create(self.root/(uuid.uuid4().hex+'.sqlite'),p)
        return g.configured_settings(E1,allowance),allowance

    def serve(self,settings):
        server=g.make_server(settings,0)
        thread=Thread(target=server.serve_forever,kwargs={'poll_interval':.01},daemon=True)
        thread.start()
        def close():
            server.shutdown();server.server_close();thread.join(2)
        self.addCleanup(close)
        return server

    def call(self,server,request):
        conn=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=3)
        try:
            conn.request('POST','/v1/chat/completions',canonical(request),{'Content-Type':'application/json'})
            response=conn.getresponse()
            return response.status,json.loads(response.read())
        finally:conn.close()

    def test_profile_on_is_explicit_and_legacy_none_bytes_are_unchanged(self):
        p=Profile.parse(canonical(public()))
        self.assertEqual(p.reasoning_effort,'on')
        self.assertEqual(p.public(),public())
        old=public('none')
        self.assertEqual(canonical(Profile.parse(canonical(old)).public()),canonical(old))
        self.assertEqual(Profile.parse(canonical(old)).digest,sha256(canonical(old).encode()).hexdigest())
        self.assertNotEqual(p.digest,Profile.parse(canonical(old)).digest)

    def test_on_rejects_cloud_recorded_a1_and_every_conversation_version(self):
        invalid=[public()|dict(provider='openai-chat-json',local_port=None),
            public()|dict(provider='recorded-fixture',model=g.RECORDED_MODEL,local_port=None,
                          replay_corpus_sha256='b'*64,replay_fixture_sha256='c'*64),
            public()|dict(version=2,response_contract='chronos.agent-proposal.v2')]
        for version,contract in ((4,g.CONVERSATION_CONTRACT),(5,g.PLAN_CONTRACT),(6,g.PLAN_V2_CONTRACT)):
            invalid.append(public()|dict(version=version,response_contract=contract))
        invalid[2].pop('response_contract')
        for value in invalid:
            with self.subTest(value=value),self.assertRaises(DeploymentError):
                Profile.parse(canonical(value))

    def test_local_cli_accepts_on_without_preparing_state(self):
        stdout=io.StringIO()
        with redirect_stdout(stdout):
            code=provider.main(['plan','--deployment-id',IDENT,'--model',MODEL,
                '--request-limit','2','--reasoning-effort','on'])
        self.assertEqual(code,0)
        self.assertEqual(json.loads(stdout.getvalue())['reasoning_effort'],'on')
        self.assertEqual(list(self.root.iterdir()),[])

    def test_legacy_native_payload_bytes_remain_identical(self):
        for schema in (E1,C1):
            for effort in ('none','low','medium'):
                settings,_=self.settings(effort)
                request=body(replace(settings,schema=schema),schema)
                expected={'model':request['model'],'messages':request['messages'],
                    'format':schema,'stream':False,'truncate':False,'shift':False,
                    'think':False if effort=='none' else effort,
                    'options':{'temperature':0,'num_predict':2048}}
                with self.subTest(contract=g.response_contract(schema),effort=effort):
                    self.assertEqual(json.dumps(g.native_conversation_request(request)),json.dumps(expected))

    def test_on_maps_to_real_boolean_without_changing_generation_limits(self):
        settings,_=self.settings();request=body(settings)
        checked,_=g.request_body(canonical(request).encode(),E1,MODEL,settings.profile_sha256,'on')
        native=g.native_conversation_request(checked)
        self.assertIs(native['think'],True)
        self.assertEqual(native['options'],{'temperature':0,'num_predict':2048})
        self.assertEqual(settings.budget_seconds,28)
        self.assertFalse(native['truncate']);self.assertFalse(native['shift'])

    def test_request_and_settings_decline_on_outside_e1_bound_ollama(self):
        settings,_=self.settings()
        for schema in (C1,A1):
            with self.subTest(schema=g.response_contract(schema)):
                with self.assertRaises(g.Rejected):
                    g.request_body(canonical(body(replace(settings,schema=schema))).encode(),schema,
                        MODEL,settings.profile_sha256,'on')
                with self.assertRaises(g.Rejected):
                    g.native_conversation_request(body(replace(settings,schema=schema)))
                with self.assertRaises(ValueError):g.make_server(replace(settings,schema=schema),0)
        with self.assertRaises(ValueError):g.make_server(replace(settings,transport_kind='openai-chat-json'),0)
        with self.assertRaises(ValueError):g.make_server(replace(settings,transport_kind=g.RECORDED_PROVIDER),0)
        with self.assertRaises(ValueError):g.make_server(replace(settings,claims=object()),0)
        with self.assertRaises(ValueError):g.make_server(replace(settings,profile_sha256='f'*64),0)

    def test_capability_checks_share_the_exact_deadline_and_discard_show_metadata(self):
        settings,_=self.settings();deadline=time.monotonic()+1;disconnected=lambda:False
        replies=[json.dumps({'version':g.NATIVE_CONTEXT_VERSION}).encode(),
            json.dumps({'thinking':{'values':[False,True],'default':True},
                'template':'PRIVATE_TEMPLATE_SENTINEL','system':'PRIVATE_SYSTEM_SENTINEL'}).encode()]
        with patch.object(g,'upstream_exchange',side_effect=replies) as upstream:
            self.assertIsNone(g.verify_context_policy(settings,disconnected,deadline))
        self.assertEqual(upstream.call_count,2)
        self.assertEqual(upstream.call_args_list[0].kwargs,{'method':'GET','path':'/api/version'})
        self.assertEqual(upstream.call_args_list[1].kwargs,{'method':'POST','path':'/api/show'})
        self.assertEqual(upstream.call_args_list[1].args,(settings,{'model':MODEL},disconnected,deadline))

    def test_legacy_context_policy_does_not_add_a_show_probe(self):
        for effort in ('none','low','medium'):
            settings,_=self.settings(effort)
            with patch.object(g,'upstream_exchange',return_value=canonical({'version':g.NATIVE_CONTEXT_VERSION}).encode()) as upstream:
                g.verify_context_policy(settings)
            self.assertEqual(upstream.call_count,1)

    def test_unsupported_or_numeric_thinking_controls_are_rejected(self):
        settings,_=self.settings()
        for values in (None,[],[False],[1],['true'],['on'],True,{'true':True}):
            show={} if values is None else {'thinking':{'values':values,'default':True}}
            with self.subTest(values=values),patch.object(g,'upstream_exchange',side_effect=[
                canonical({'version':g.NATIVE_CONTEXT_VERSION}).encode(),canonical(show).encode()]):
                with self.assertRaises(g.Rejected) as exc:g.verify_context_policy(settings)
                self.assertEqual(exc.exception.code,'THINKING_POLICY_UNSUPPORTED')

    def test_capability_failure_cannot_claim_or_dispatch(self):
        settings,allowance=self.settings();server=self.serve(settings);calls=[]
        def upstream(settings,request,*args,**kwargs):
            calls.append(kwargs['path'])
            if kwargs['path']=='/api/version':return canonical({'version':g.NATIVE_CONTEXT_VERSION}).encode()
            if kwargs['path']=='/api/show':return canonical({'thinking':{'values':[False]},'template':'PRIVATE_TEMPLATE_SENTINEL'}).encode()
            raise AssertionError('No model request is permitted')
        with patch.object(g,'upstream_exchange',upstream):status,result=self.call(server,body(settings))
        self.assertEqual(status,422)
        self.assertEqual(result,{'error':{'code':'THINKING_POLICY_UNSUPPORTED'}})
        self.assertEqual(calls,['/api/version','/api/show'])
        self.assertEqual(allowance.snapshot()['used'],0)
        self.assertNotIn('PRIVATE_TEMPLATE_SENTINEL',canonical(result))

    def test_success_dispatches_boolean_true_once_and_strips_thinking(self):
        settings,allowance=self.settings();server=self.serve(settings);calls=[]
        content=canonical(dict(schema_version=g.EXTRACTION_CONTRACT,interpreted_preference='CHEAPEST_ON_TIME',
            reason_code='PREFERENCE_MATCH',source_ids=['synthetic-message'],rationale='Synthetic test interpretation.',clarification=None))
        def upstream(settings,request,*args,**kwargs):
            calls.append((kwargs['path'],request))
            if kwargs['path']=='/api/version':return canonical({'version':g.NATIVE_CONTEXT_VERSION}).encode()
            if kwargs['path']=='/api/show':return canonical({'thinking':{'values':[False,True]},'system':'PRIVATE_SYSTEM_SENTINEL'}).encode()
            self.assertEqual(kwargs['path'],'/api/chat');self.assertIs(request['think'],True)
            return canonical(dict(model=MODEL,done=True,done_reason='stop',
                message=dict(role='assistant',content=content,thinking='PRIVATE_THINKING_SENTINEL'),
                prompt_eval_count=32,eval_count=28)).encode()
        request=body(settings)
        with patch.object(g,'upstream_exchange',upstream):
            status,result=self.call(server,request)
            repeated_status,_=self.call(server,request)
        self.assertEqual(status,200);self.assertEqual(repeated_status,422)
        self.assertEqual(sum(path=='/api/chat' for path,_ in calls),1)
        self.assertEqual(allowance.snapshot()['used'],1)
        self.assertEqual(json.loads(result['choices'][0]['message']['content'])['source_ids'],['synthetic-message'])
        self.assertNotIn('PRIVATE_',canonical(result))

    def test_warmup_on_is_deliberately_nonreasoning_and_legacy_payload_unchanged(self):
        for effort in ('none','low','medium','on'):
            p=Profile.parse(canonical(public(effort)))
            request=readiness.neutral_request(p)
            self.assertEqual(request['think'],False if effort in ('none','on') else effort)
            self.assertEqual(request['options'],{'num_predict':128,'temperature':0})
        legacy={'status':'NOT_FOUND','performed_request':False}
        for effort in ('none','low','medium'):
            self.assertIs(readiness.reasoning_scope(legacy,Profile.parse(canonical(public(effort)))),legacy)
        result=readiness.reasoning_scope(legacy,Profile.parse(canonical(public())))
        self.assertFalse(result['warmup_thinking']);self.assertFalse(result['reasoning_enabled_verified'])
        self.assertEqual(result['reasoning_validation'],'NOT_TESTED_BY_NEUTRAL_WARMUP')

    def test_on_warmup_report_stays_unverified_after_historical_read(self):
        runtime=self.root/'guard';runtime.mkdir();data=self.root/'data';(data/IDENT).mkdir(parents=True)
        profile=provider.prepare(IDENT,MODEL,2,'on',authorize_id=IDENT,runtime=runtime)
        args=(IDENT,profile['profile_sha256'],'c'*32,'b'*64,8192)
        calls=[]
        def fake(path,request,deadline):
            calls.append(path)
            if path=='/api/chat':
                self.assertIs(request['think'],False)
                return dict(model=MODEL,done=True,done_reason='stop',message=dict(role='assistant',content='{"ready":true}',thinking='PRIVATE_THINKING_SENTINEL'),eval_count=19,prompt_eval_count=1698)
            return {'models':[dict(name=MODEL,model=MODEL,digest='b'*64,size=1000,details={'format':'gguf'},context_length=8192,size_vram=900,expires_at=(datetime.now(timezone.utc)+timedelta(minutes=10)).isoformat())]}
        with patch.object(readiness,'exchange',fake):
            result=readiness.run(*args,authorize_id=IDENT,runtime=runtime,data_root=data)
        self.assertEqual(result['status'],'NEUTRAL_INFERENCE_OBSERVED')
        self.assertFalse(result['reasoning_enabled_verified']);self.assertFalse(result['warmup_thinking'])
        with patch.object(readiness,'exchange',side_effect=AssertionError('No retry')):
            old=readiness.inspect(*args,runtime=runtime,data_root=data)
        self.assertTrue(old['historical']);self.assertFalse(old['reasoning_enabled_verified'])
        self.assertEqual(calls,['/api/tags','/api/chat','/api/ps'])
        stored=b''.join(p.read_bytes() for p in (data/IDENT/'model-readiness').rglob('*.json'))
        self.assertNotIn(b'PRIVATE_',stored)
        self.assertEqual(provider.status(IDENT,runtime=runtime)['allowance']['used'],0)


if __name__=='__main__':unittest.main()
