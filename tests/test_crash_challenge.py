"""Synthetic, offline tests: these fixtures are not evidence of an IRIS run."""
from __future__ import annotations
from contextlib import redirect_stdout
from copy import deepcopy
from datetime import datetime,timezone
from hashlib import sha256
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import sqlite3
import stat
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location('chronos_crash_challenge',ROOT/'tools/crash_challenge.py')
c=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(c)


class Clock(datetime):
    @classmethod
    def now(cls,tz=None):return cls(2026,11,13,0,1,30,tzinfo=timezone.utc)


class Lab:
    """Create only disposable files; no application, Docker or model runs."""
    def __init__(self,base,*,short=False):
        self.base=Path(base);self.workspace=self.base/('w' if short else 'jury-workspace')
        self.stage=self.workspace/('s' if short else 'stage');self.app=self.stage/'app'
        self.data=self.stage/'data';self.guard=self.stage/'guard'
        for p in (self.app,self.data,self.guard,self.app/'tools'):p.mkdir(parents=True,exist_ok=True)
        content={
            'src/Chronos/Destination/Simulator.cls':b'// SYNTHETIC TEST ONLY: no runnable engine\n',
            'src/Chronos/Recovery/Coordinator.cls':b'// SYNTHETIC TEST ONLY: no recovery\n',
            'deployment/native_resume.py':b'# SYNTHETIC TEST ONLY\n',
            'src/chronos_web/index.html':b'<!-- SYNTHETIC TEST ONLY -->\n',
        }
        for name,value in content.items():
            file=self.app/name;file.parent.mkdir(parents=True,exist_ok=True);file.write_bytes(value)
        hashes={name:sha256(value).hexdigest() for name,value in content.items()}
        self.manifest=dict(schema_version='chronos.application-bundle.v1',status='STAGED_LOCAL_NOT_INSTALLED',
            api_base='/csp/chronos',required_iris_build='2026.3.0AI.154.0',source_sha256=hashes.copy(),
            output_sha256=hashes.copy(),transformed_files=['src/chronos_web/index.html'],contains_image=False,
            contains_accounts=False,contains_runtime_data=False,installed=False,native_compilation_verified=False)
        raw=self.put(self.app/'bundle-manifest.json',self.manifest);self.manifest_sha=sha256(raw).hexdigest()
        self.ident='a'*32;self.cid='b'*64;self.image='sha256:'+'c'*64
        self.profile=dict(version=3,deployment_id=self.ident,provider='ollama',model='synthetic-local-test',
            schema_sha256='d'*64,request_limit=12,local_port=11434,reasoning_effort='none',
            response_contract='chronos.preference-extraction.v1')
        profile_raw=self.put(self.stage/'profile.json',self.profile)
        self.config=dict(version=3,deployment_id=self.ident,host_bundle=str(self.app),host_data_root=str(self.data),
            host_guard_state=str(self.guard),web_origin='http://127.0.0.1:53135',
            native_guard_base_url='http://127.0.0.1:11512/v1/')
        config_raw=self.put(self.stage/'config.json',self.config)
        self.receipt=dict(schema_version='chronos.install-stage.v3',status='STAGED_FILES_ONLY_NOT_INSTALLED',
            root=str(self.stage),staging_id='e'*32,created_at='2026-11-13T00:00:00Z',
            bundle_manifest_sha256=self.manifest_sha,profile_sha256=c.profile_binding(profile_raw)[1],
            profile_file_sha256=sha256(profile_raw).hexdigest(),config_file_sha256=sha256(config_raw).hexdigest(),
            data_identity=[self.data.stat().st_dev,self.data.stat().st_ino],
            guard_identity=[self.guard.stat().st_dev,self.guard.stat().st_ino],
            allowance_initialized=False,account_changes=0,native_calls=0,model_calls=0)
        self.put(self.stage/'stage-receipt.json',self.receipt)
        self.project='chronos-jury-'+self.ident[:12]
        mounts=[dict(type='bind',source=str(source),destination=dest,read_write=rw) for source,dest,rw in (
            (self.data,'/durable',True),(self.app,'/opt/chronos/bundle',False),
            (self.app/'src','/opt/chronos/src',False),(self.app/'deployment','/opt/chronos/deployment',False),
            (self.app/'tools','/opt/chronos/tools',False),(self.guard,'/opt/chronos/runtime',True))]
        self.snapshot=dict(schema=c.SNAPSHOT_SCHEMA,captured_at='2026-11-13T00:01:00Z',container=dict(
            id=self.cid,image=self.image,project=self.project,service='iris',mounts=mounts,
            state=dict(running=True,oom_killed=False,started_at='2026-11-13T00:00:00Z'),host=dict(
                privileged=False,memory_bytes=4*2**30,network_mode=self.project+'_default',
                port_bindings={'52773/tcp':[dict(HostIp='127.0.0.1',HostPort='53135')]})))
        self.snapshot_file=self.base/'owner-snapshot.json';self.put(self.snapshot_file,self.snapshot)
        self.output=self.base/'new-plan'

    @staticmethod
    def put(path,obj):
        raw=c.canonical(obj);Path(path).write_bytes(raw);return raw

    def refresh_receipt(self):
        self.receipt['config_file_sha256']=sha256((self.stage/'config.json').read_bytes()).hexdigest()
        raw=(self.stage/'profile.json').read_bytes()
        self.receipt['profile_file_sha256']=sha256(raw).hexdigest()
        self.receipt['profile_sha256']=c.profile_binding(raw)[1]
        self.put(self.stage/'stage-receipt.json',self.receipt)

    def plan(self,**overrides):
        self.put(self.snapshot_file,self.snapshot)
        values=dict(stage=self.stage,snapshot_path=self.snapshot_file,expected_manifest=self.manifest_sha,
            container_id=self.cid,image=self.image,output=self.output)
        values.update(overrides)
        with patch.object(c,'datetime',Clock):return c.plan(**values)

    def jury_layout(self,*,replay=False):
        """Mirror the real setup receipt/mount layout using synthetic bytes."""
        if replay:
            corpus=c.canonical({'synthetic_test_only':True,'not_native_capture_evidence':True})
            allowed=c.canonical({'synthetic_test_only':True})
            self.profile.update(provider='recorded-fixture',model='chronos-recorded-fixture-v1',local_port=None,
                replay_corpus_sha256=sha256(corpus).hexdigest(),replay_fixture_sha256='2'*64)
            self.put(self.stage/'profile.json',self.profile);self.refresh_receipt()
        c2=self.profile|dict(version=6,response_contract='chronos.case-explanation-plan.v2',request_limit=24,schema_sha256='9'*64)
        profiles=self.workspace/'profiles';profiles.mkdir()
        self.put(profiles/'e1.json',self.profile);c2raw=self.put(profiles/'c2.json',c2)
        chat=self.workspace/'chat-state';chat.mkdir()
        env=dict(CHRONOS_PROJECT=self.project,CHRONOS_IMAGE=self.image,CHRONOS_APP=str(self.app),
            CHRONOS_DATA=str(self.data),CHRONOS_GUARD_STATE=str(self.guard),CHRONOS_WEB_PORT='53135',
            CHRONOS_CONVERSATION_STATE=str(chat),CHRONOS_CONVERSATION_CONTRACT='c2-v2')
        receipt=dict(schema='chronos.jury-workspace.v1',status='FILES_PREPARED_NOT_INSTALLED',
            mode='RECORDED_FIXTURE_SETUP_ONLY' if replay else 'LIVE_LOCAL_SETUP_ONLY',root=str(self.workspace),
            deployment_id=self.ident,origin=self.config['web_origin'],bundle_manifest_sha256=self.manifest_sha,
            e1_profile_sha256=self.receipt['profile_sha256'],c2_profile_sha256=c.profile_binding(c2raw,conversation=True)[1],
            environment=env,installed=False,accounts_created=0,services_started=0,model_calls=0,allowances_initialized=False)
        self.snapshot['container']['mounts'].append(dict(type='bind',source=str(chat),
            destination='/opt/chronos/conversation-runtime',read_write=True))
        if replay:
            fixtures=self.workspace/'fixtures';fixtures.mkdir()
            (fixtures/'corpus.json').write_bytes(corpus);(fixtures/'evidence-allowlist.json').write_bytes(allowed)
            env.update(CHRONOS_DEPLOYMENT_ID=self.ident,CHRONOS_REPLAY_FIXTURES=str(fixtures))
            receipt.update(replay_corpus_sha256=self.profile['replay_corpus_sha256'],
                replay_fixture_sha256=self.profile['replay_fixture_sha256'],capture_allowlist_sha256=sha256(allowed).hexdigest(),
                compose_files=['compose.yaml','compose.web-local.yaml','compose.replay.yaml'],profiles=['recorded-fixture'])
            self.snapshot['container']['mounts'].append(dict(type='bind',source=str(fixtures),
                destination='/opt/chronos/fixtures',read_write=False))
        else:
            (self.workspace/'model-home').mkdir()
            env.update(CHRONOS_OLLAMA_IMAGE='ollama/ollama@sha256:93c1376d651a9f1579ee40cc5763852f08b204466371e4bb64bca2a1d8d08e2d',
                CHRONOS_MODELS=str(self.base/'unused-model-cache'),CHRONOS_MODEL_HOME=str(self.workspace/'model-home'),
                CHRONOS_MODEL_CPUS='4',CHRONOS_MODEL_MEMORY='4g',CHRONOS_GPU_DEVICE_ID='0')
            receipt.update(compose_files=['compose.yaml','compose.web-local.yaml','compose.local-model.yaml',
                'compose.conversation.yaml','compose.local-gpu.yaml'],profiles=['local-model','conversation'])
        self.put(self.workspace/'jury-workspace.json',receipt)
        return receipt


def observations(plan):
    """Every observation below is invented test data, explicitly labelled."""
    ids=dict(operationId='synthetic-operation-1',attemptId='synthetic-attempt-1',admissionId='synthetic-admission-1')
    effect=plan['expected_effect'];order=effect['order_id'];target=effect['target']
    pending=ids|dict(orderId=order,shipmentVersion=1,target=target,state='IN_FLIGHT',reference='')
    accepted={k:v for k,v in pending.items() if k not in ('admissionId','reference')}
    accepted.update(state='ACCEPTED',submits=1,attempts=1)
    receipt={k:v for k,v in pending.items() if k not in ('admissionId','state','reference')}
    receipt.update(status='ACCEPTED',reference='synthetic-reference-1',receiptId='synthetic-receipt-1',closedForever=False)
    owner=plan['owner']
    return dict(schema=c.OBSERVATION_SCHEMA,evidence_kind='SYNTHETIC_TEST_ONLY',captured_at='2026-11-13T00:03:00Z',plan_sha256=plan['plan_sha256'],
        instrumentation=dict(base_manifest_sha256=plan['bindings']['manifest_sha256'],
            instrumented_manifest_sha256='f'*64,hook_sha256='0'*64,boundary=c.BOUNDARY,test_only=True),
        before_cut=dict(iris=deepcopy(pending),destination=deepcopy(accepted),barrier=ids|dict(
            armed_at='2026-11-13T00:01:59Z',started_at='2026-11-13T00:02:00Z',wait_seconds=45,receipt=receipt)),
        cut=dict(container_id=owner['container_id'],image=owner['image'],started_at=owner['started_at'],
            finished_at='2026-11-13T00:02:03Z',running=False,exit_code=137,oom_killed=False),
        after_restart=dict(container_id=owner['container_id'],started_at='2026-11-13T00:02:04Z',
            operation=deepcopy(pending),inspection=dict(status='CRASH_RECOVERY_AVAILABLE',
                current_generation='synthetic-generation-before',production_state=4)),
        resume=dict(status='RESUME_VERIFIED',request_id='synthetic-resume-1',
            previous_generation='synthetic-generation-before',current_generation='synthetic-generation-after',
            runtime_ready=True,recovery_phase='VERIFIED',model_tested=False),
        recovered_operation=pending|dict(state='ACCEPTED',reference=receipt['reference'],lastReceiptId=receipt['receiptId']),
        operator_readback=dict(operationId=ids['operationId'],attemptId=ids['attemptId'],state='ACCEPTED',
            reference=receipt['reference'],quarantined=False,dispatchGranted=False),
        destination_final=dict(accepted=deepcopy(accepted),raw_submit_calls=[ids],accepted_recovery_effects=1,
            scope='ALL_RECOVERIES_FOR_OWNED_ORDER_EXCLUDING_ORIGINAL'))


class PlannerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='chronos-offline-planner-test-')
        self.addCleanup(self.temp.cleanup);self.lab=Lab(self.temp.name)

    def test_plan_is_pinned_and_explicitly_offline(self):
        before={str(p):p.read_bytes() for p in self.lab.stage.rglob('*') if p.is_file()}
        with patch('subprocess.run',side_effect=AssertionError('No process may run')):
            result=self.lab.plan()
        self.assertFalse(result['ready']);self.assertFalse(result['execution_supported'])
        self.assertEqual(result['services_started'],0);self.assertEqual(result['accounts_changed'],0)
        self.assertEqual(result['bindings']['web_port'],53135)
        self.assertEqual(result['owner']['container_id'],self.lab.cid)
        self.assertEqual(c.verify_plan(result,result['plan_sha256']),result)
        self.assertEqual(c.parse((self.lab.output/c.PLAN_NAME).read_bytes()),result)
        self.assertEqual(list(self.lab.output.iterdir()),[self.lab.output/c.PLAN_NAME])
        self.assertEqual(before,{str(p):p.read_bytes() for p in self.lab.stage.rglob('*') if p.is_file()})

    def test_existing_output_is_preserved_and_repeated_plan_rejected(self):
        first=self.lab.plan();raw=(self.lab.output/c.PLAN_NAME).read_bytes()
        with self.assertRaisesRegex(c.ChallengeError,'OUTPUT_ALREADY_EXISTS'):self.lab.plan()
        self.assertEqual((self.lab.output/c.PLAN_NAME).read_bytes(),raw)
        self.assertEqual(c.parse(raw)['plan_sha256'],first['plan_sha256'])

    def test_even_an_empty_existing_directory_is_not_adopted(self):
        self.lab.output.mkdir()
        with self.assertRaisesRegex(c.ChallengeError,'OUTPUT_ALREADY_EXISTS'):self.lab.plan()
        self.assertEqual(list(self.lab.output.iterdir()),[])

    def test_output_must_be_new_and_outside_jury_workspace(self):
        for path in (self.lab.stage/'plan',self.lab.workspace/'plan',self.lab.workspace):
            with self.subTest(path=path),self.assertRaises(c.ChallengeError):self.lab.plan(output=path)
            self.assertFalse((path/c.PLAN_NAME).exists())

    def test_foreign_container_and_image_arguments_rejected_before_write(self):
        for override in ({'container_id':'c'*64},{'image':'sha256:'+'d'*64},{'container_id':'short'}):
            with self.subTest(override=override),self.assertRaises(c.ChallengeError):self.lab.plan(**override)
            self.assertFalse(self.lab.output.exists())

    def test_foreign_or_unsafe_snapshot_rejected_before_write(self):
        baseline=deepcopy(self.lab.snapshot)
        changes=[('id','c'*64),('image','sha256:'+'d'*64),('project','other-project'),('service','worker'),
                 ('state.running',False),('state.oom_killed',True),('state.started_at','2026-11-13T00:03:00Z'),
                 ('host.privileged',True),('host.memory_bytes',0),('host.memory_bytes',True),
                 ('host.network_mode','host'),('host.port_bindings',{'52773/tcp':[{'HostIp':'0.0.0.0','HostPort':'53135'}]}),
                 ('host.port_bindings',{'52773/tcp':[{'HostIp':'127.0.0.1','HostPort':'52773'}]})]
        for dotted,value in changes:
            self.lab.snapshot=deepcopy(baseline);node=self.lab.snapshot['container'];parts=dotted.split('.')
            for part in parts[:-1]:node=node[part]
            node[parts[-1]]=value
            with self.subTest(field=dotted),self.assertRaises(c.ChallengeError):self.lab.plan()
            self.assertFalse(self.lab.output.exists())

    def test_unknown_fields_including_environment_are_not_copied(self):
        self.lab.snapshot['container']['Env']=['SYNTHETIC_PLACEHOLDER=not-a-secret']
        with self.assertRaisesRegex(c.ChallengeError,'INVALID_OWNER_SNAPSHOT'):self.lab.plan()
        self.assertFalse(self.lab.output.exists())

    def test_foreign_mutated_or_extra_mount_is_refused(self):
        baseline=deepcopy(self.lab.snapshot)
        changes=[lambda m:m[0].update(source=str(self.lab.base/'foreign-data')),
                 lambda m:m[0].update(read_write=False),lambda m:m[1].update(read_write=True),
                 lambda m:m[0].update(type='volume'),lambda m:m.append(deepcopy(m[0])),
                 lambda m:m[0].update(destination='/other'),lambda m:m[1].update(destination='/durable')]
        for index,mutate in enumerate(changes):
            self.lab.snapshot=deepcopy(baseline);mutate(self.lab.snapshot['container']['mounts'])
            with self.subTest(index=index),self.assertRaises(c.ChallengeError):self.lab.plan()
            self.assertFalse(self.lab.output.exists())

    def test_modified_profile_and_config_bytes_rejected(self):
        for name in ('profile.json','config.json'):
            p=self.lab.stage/name;original=p.read_bytes();p.write_bytes(original+b'\n')
            with self.subTest(name=name),self.assertRaisesRegex(c.ChallengeError,'STAGE_INPUT_BYTES_CHANGED'):self.lab.plan()
            p.write_bytes(original)
        self.assertFalse(self.lab.output.exists())

    def test_resealed_config_cannot_claim_foreign_data(self):
        self.lab.config['host_data_root']=str(self.lab.base/'foreign-data')
        self.lab.put(self.lab.stage/'config.json',self.lab.config);self.lab.refresh_receipt()
        with self.assertRaisesRegex(c.ChallengeError,'STAGE_PATH_BINDING_CHANGED'):self.lab.plan()

    def test_resealed_profile_cannot_claim_other_deployment(self):
        self.lab.profile['deployment_id']='f'*32
        self.lab.put(self.lab.stage/'profile.json',self.lab.profile);self.lab.refresh_receipt()
        with self.assertRaisesRegex(c.ChallengeError,'STAGE_PROFILE_CHANGED'):self.lab.plan()

    def test_data_directory_identity_is_bound(self):
        old=self.lab.stage/'preserved-test-data';self.lab.data.rename(old);self.lab.data.mkdir()
        with self.assertRaisesRegex(c.ChallengeError,'STAGE_DIRECTORY_REPLACED'):self.lab.plan()
        self.assertTrue(old.is_dir())

    def test_bundle_bytes_inventory_and_manifest_are_pinned(self):
        file=self.lab.app/'deployment/native_resume.py';original=file.read_bytes();file.write_bytes(b'mutated synthetic test')
        with self.assertRaisesRegex(c.ChallengeError,'BUNDLE_SOURCE_CHANGED'):self.lab.plan()
        file.write_bytes(original)
        extra=self.lab.app/'untrusted.txt';extra.write_text('synthetic extra',encoding='utf-8')
        with self.assertRaisesRegex(c.ChallengeError,'BUNDLE_INVENTORY_CHANGED'):self.lab.plan()

    def test_modified_manifest_cannot_be_self_authorized(self):
        self.lab.manifest['required_iris_build']='2027.1.0AI.109.0'
        self.lab.put(self.lab.app/'bundle-manifest.json',self.lab.manifest)
        with self.assertRaisesRegex(c.ChallengeError,'MANIFEST_DIGEST_MISMATCH'):self.lab.plan()

    def test_recorded_fixture_profile_supported_without_model_execution(self):
        self.lab.jury_layout(replay=True)
        result=self.lab.plan();self.assertFalse(result['execution_supported'])
        self.assertEqual(len(result['owner']['mounts']),8)
        self.assertEqual(result['bindings']['runtime']['mode'],'RECORDED_FIXTURE')
        self.assertEqual(c.verify_plan(result,result['plan_sha256']),result)

    def test_real_live_jury_layout_accepts_exact_seven_mounts(self):
        self.lab.jury_layout()
        result=self.lab.plan();self.assertEqual(len(result['owner']['mounts']),7)
        self.assertEqual(result['bindings']['runtime']['mode'],'LIVE')
        self.assertEqual(c.verify_plan(result,result['plan_sha256']),result)

    def test_extra_jury_mounts_require_their_sealed_receipt(self):
        self.lab.jury_layout()
        receipt=self.lab.workspace/'jury-workspace.json';receipt.rename(self.lab.workspace/'preserved-receipt.json')
        with self.assertRaisesRegex(c.ChallengeError,'FOREIGN_MOUNT_SCOPE'):self.lab.plan()

    def test_chat_mount_must_be_owned_rw_and_c2_profile_bound(self):
        self.lab.jury_layout();baseline=deepcopy(self.lab.snapshot)
        self.lab.snapshot['container']['mounts'][-1]['read_write']=False
        with self.assertRaisesRegex(c.ChallengeError,'FOREIGN_MOUNT_SCOPE'):self.lab.plan()
        self.lab.snapshot=baseline
        c2=self.lab.workspace/'profiles/c2.json';raw=c2.read_bytes();c2.write_bytes(raw+b'\n')
        changed=c.parse(raw);changed['model']='foreign-model';self.lab.put(c2,changed)
        with self.assertRaisesRegex(c.ChallengeError,'JURY_PROFILE_BINDING_CHANGED'):self.lab.plan()
        c2.write_bytes(raw+b'\n')
        # A semantic profile digest alone does not conceal changed bytes: the
        # new plan still records the changed file digest for later rechecks.
        result=self.lab.plan();self.assertEqual(result['bindings']['runtime']['c2_profile_file_sha256'],sha256(raw+b'\n').hexdigest())

    def test_replay_fixture_mount_cannot_be_writable_or_foreign(self):
        self.lab.jury_layout(replay=True);baseline=deepcopy(self.lab.snapshot)
        self.lab.snapshot['container']['mounts'][-1]['read_write']=True
        with self.assertRaisesRegex(c.ChallengeError,'FOREIGN_MOUNT_SCOPE'):self.lab.plan()
        self.lab.snapshot=baseline
        self.lab.snapshot['container']['mounts'][-1]['source']=str(self.lab.data)
        with self.assertRaisesRegex(c.ChallengeError,'FOREIGN_MOUNT_SCOPE'):self.lab.plan()

    def test_replay_corpus_tamper_or_wrong_workspace_manifest_is_rejected(self):
        receipt=self.lab.jury_layout(replay=True)
        corpus=self.lab.workspace/'fixtures/corpus.json';old=corpus.read_bytes();corpus.write_bytes(old+b'\n')
        with self.assertRaisesRegex(c.ChallengeError,'RECORDED_FIXTURE_BYTES_CHANGED'):self.lab.plan()
        corpus.write_bytes(old);receipt['bundle_manifest_sha256']='0'*64
        self.lab.put(self.lab.workspace/'jury-workspace.json',receipt)
        with self.assertRaisesRegex(c.ChallengeError,'JURY_WORKSPACE_BINDING_CHANGED'):self.lab.plan()

    def test_windows_unicode_casefold_collision_is_not_directory_identity(self):
        first=Path(self.temp.name)/'stra\u00dfe';other=Path(self.temp.name)/'strasse'
        first.mkdir();other.mkdir()
        self.assertEqual(str(first).casefold(),str(other).casefold())
        self.assertNotEqual((first.stat().st_dev,first.stat().st_ino),(other.stat().st_dev,other.stat().st_ino))
        self.assertFalse(c.same_directory(str(first),other))
        expected=Lab(first);foreign=Lab(other)
        expected.snapshot['container']['mounts'][0]['source']=str(foreign.data)
        with self.assertRaisesRegex(c.ChallengeError,'FOREIGN_MOUNT_SCOPE'):expected.plan()

    @unittest.skipUnless(os.name=='nt','A real Windows case alias is needed')
    def test_existing_windows_case_alias_and_desktop_prefix_use_identity(self):
        alias=str(self.lab.data).swapcase()
        self.assertTrue(c.same_directory(alias,self.lab.data))
        absolute=str(self.lab.data).replace('\\','/')
        desktop='/run/desktop/mnt/host/'+absolute[0].lower()+absolute[2:]
        self.assertTrue(c.same_directory(desktop,self.lab.data))
        self.lab.snapshot['container']['mounts'][0]['source']=desktop
        result=self.lab.plan();self.assertEqual(result['owner']['mounts'][0]['source'],str(self.lab.data))
        self.assertEqual(c.verify_plan(result,result['plan_sha256']),result)

    def test_nonloopback_web_origin_rejected(self):
        for origin in ('http://0.0.0.0:53135','http://127.0.0.1:53135/path','http://name:53135','http://127.0.0.1',
                       'http://user:pass@127.0.0.1:53135','http://127.0.0.1:53135?x=1'):
            with self.subTest(origin=origin),self.assertRaises(c.ChallengeError):c.origin_port(origin)

    def test_known_windows_mount_aliases_only(self):
        for path in ('D:\\Proyectos\\Chronos\\stage','D:/Proyectos/Chronos/stage',
                     '/run/desktop/mnt/host/d/Proyectos/Chronos/stage','/host_mnt/d/Proyectos/Chronos/stage'):
            self.assertEqual(c.mount_source(path),'d:/Proyectos/Chronos/stage')
        self.assertNotEqual(c.mount_source('/srv/Chronos'),c.mount_source('/srv/chronos'))
        self.assertNotEqual(c.mount_source('/mnt/d/Proyectos/Chronos/stage'),'d:/proyectos/chronos/stage')
        for path in ('/srv/../foreign','D:/a//b','/run/desktop/mnt/host/d/a/../b','/srv/./stage'):
            with self.subTest(path=path),self.assertRaises(c.ChallengeError):c.mount_source(path)

    def test_snapshot_replaced_during_planning_does_not_create_output(self):
        original=c.stage_binding;calls=0
        def mutate(*args):
            nonlocal calls
            result=original(*args);calls+=1
            if calls==2:self.lab.snapshot_file.write_bytes(b'{}')
            return result
        with patch.object(c,'stage_binding',side_effect=mutate),self.assertRaisesRegex(c.ChallengeError,'PLAN_INPUT_CHANGED'):
            self.lab.plan()
        self.assertFalse(self.lab.output.exists())

    def test_execution_commands_cannot_run_without_exact_inputs(self):
        for action in c.EXECUTION_COMMANDS:
            with redirect_stdout(io.StringIO()),patch('sys.stderr',io.StringIO()),self.assertRaises(SystemExit) as result:
                c.main([action])
            self.assertEqual(result.exception.code,2)
        self.assertFalse(self.lab.output.exists())


class ObservationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='chronos-offline-record-test-')
        self.addCleanup(self.temp.cleanup);self.lab=Lab(self.temp.name);self.plan=self.lab.plan()
        self.records=observations(self.plan)

    def verify(self,records=None,**kw):
        return c.verify_records(self.records if records is None else records,self.plan,
            expected_plan_sha256=self.plan['plan_sha256'],allow_synthetic=True,**kw)

    def test_terminal_simulated_delivery_keeps_same_accepted_effect(self):
        advanced=deepcopy(self.records)
        advanced['destination_final']['accepted']['state']='DELIVERED_SIMULATED'
        self.assertEqual(self.verify(advanced)['status'],'PASS')
        for field,value in (('operationId','other'),('attemptId','other'),('submits',2),('attempts',2),('shipmentVersion',True)):
            with self.subTest(field=field):
                changed=deepcopy(advanced);changed['destination_final']['accepted'][field]=value
                with self.assertRaises(c.ChallengeError):self.verify(changed)
        advanced['destination_final']['accepted']['state']='UNKNOWN'
        with self.assertRaises(c.ChallengeError):self.verify(advanced)

    def test_consistency_pass_never_claims_native_execution(self):
        result=self.verify()
        self.assertEqual(result['status'],'PASS');self.assertEqual(result['cut_seconds_after_barrier'],3)
        self.assertEqual(result['recorded_submit_calls'],1);self.assertEqual(result['accepted_recovery_effects'],1)
        self.assertFalse(result['ready']);self.assertFalse(result['native_run_reproduced'])
        self.assertEqual(result['scope'],'OFFLINE_RETAINED_RECORD_CONSISTENCY_ONLY')

    def test_synthetic_observations_require_explicit_unit_test_opt_in(self):
        with self.assertRaisesRegex(c.ChallengeError,'SYNTHETIC_OR_UNKNOWN_OBSERVATIONS'):
            c.verify_records(self.records,self.plan,expected_plan_sha256=self.plan['plan_sha256'])

    def test_valid_window_is_computed_instead_of_fixed_to_archived_timing(self):
        for finish,delay in (('2026-11-13T00:02:00.100Z',.1),('2026-11-13T00:02:44Z',44)):
            row=deepcopy(self.records);row['cut']['finished_at']=finish
            row['after_restart']['started_at']='2026-11-13T00:02:46Z'
            self.assertEqual(self.verify(row)['cut_seconds_after_barrier'],delay)
        for finish in ('2026-11-13T00:01:59Z','2026-11-13T00:02:45Z','2026-11-13T00:02:46Z'):
            row=deepcopy(self.records);row['cut']['finished_at']=finish
            with self.subTest(finish=finish),self.assertRaisesRegex(c.ChallengeError,'CUT_OUTSIDE_BARRIER'):self.verify(row)

    def test_foreign_container_or_generation_cannot_be_recovered(self):
        changes=[('cut.container_id','c'*64),('cut.image','sha256:'+'d'*64),
            ('cut.started_at','2026-11-12T00:00:00Z'),('cut.oom_killed',True),('cut.exit_code',143),
            ('after_restart.container_id','c'*64),('after_restart.started_at','2026-11-13T00:02:02Z'),
            ('after_restart.inspection.current_generation','foreign-generation'),
            ('resume.current_generation','synthetic-generation-before'),('resume.model_tested',True)]
        for dotted,value in changes:
            row=deepcopy(self.records);node=row;parts=dotted.split('.')
            for part in parts[:-1]:node=node[part]
            node[parts[-1]]=value
            with self.subTest(field=dotted),self.assertRaises(c.ChallengeError):self.verify(row)

    def test_resealed_plan_cannot_be_created_after_arm_or_cut(self):
        original=self.plan
        for created in ('2026-11-13T00:02:02Z','2026-11-13T00:02:03.500Z','2026-11-13T00:02:05Z'):
            self.plan=deepcopy(original);self.plan['created_at']=created
            self.plan['plan_sha256']=c.digest({k:v for k,v in self.plan.items() if k!='plan_sha256'})
            row=deepcopy(self.records);row['plan_sha256']=self.plan['plan_sha256']
            with self.subTest(created=created),self.assertRaisesRegex(c.ChallengeError,'INVALID_CUT_CHRONOLOGY'):self.verify(row)
        self.plan=original

    def test_snapshot_plan_arm_cut_restart_observation_order_is_enforced(self):
        self.plan['created_at']='2026-11-13T00:00:30Z'
        self.plan['plan_sha256']=c.digest({k:v for k,v in self.plan.items() if k!='plan_sha256'})
        row=deepcopy(self.records);row['plan_sha256']=self.plan['plan_sha256']
        with self.assertRaisesRegex(c.ChallengeError,'PLAN_PRECEDES_OWNER_SNAPSHOT'):self.verify(row)
        self.plan=self.lab.plan(output=self.lab.base/'second-distinct-plan')
        baseline=observations(self.plan)
        for dotted,value,code in (
                ('before_cut.barrier.armed_at','2026-11-13T00:01:29Z','INVALID_CUT_CHRONOLOGY'),
                ('before_cut.barrier.armed_at','2026-11-13T00:02:01Z','INVALID_CUT_CHRONOLOGY'),
                ('captured_at','2026-11-13T00:02:03Z','OBSERVATIONS_PRECEDE_ENGINE_RESTART')):
            row=deepcopy(baseline);node=row;parts=dotted.split('.')
            for part in parts[:-1]:node=node[part]
            node[parts[-1]]=value
            with self.subTest(field=dotted),self.assertRaisesRegex(c.ChallengeError,code):self.verify(row)

    def test_attempt_receipt_or_order_identity_change_fails(self):
        changes=[('before_cut.iris.attemptId','foreign-attempt'),('before_cut.iris.reference','already-recorded'),
            ('after_restart.operation.admissionId','foreign-admission'),('before_cut.barrier.receipt.orderId','foreign-order'),
            ('before_cut.destination.target','A'),('recovered_operation.operationId','foreign-operation'),
            ('recovered_operation.lastReceiptId','foreign-receipt'),('recovered_operation.reference','foreign-reference'),
            ('operator_readback.dispatchGranted',True),('operator_readback.quarantined',True),
            ('operator_readback.reference','foreign-reference')]
        for dotted,value in changes:
            row=deepcopy(self.records);node=row;parts=dotted.split('.')
            for part in parts[:-1]:node=node[part]
            node[parts[-1]]=value
            with self.subTest(field=dotted),self.assertRaises(c.ChallengeError):self.verify(row)

    def test_duplicate_effect_even_with_deduplicated_destination_fails(self):
        row=deepcopy(self.records);row['destination_final']['raw_submit_calls']*=2
        with self.assertRaisesRegex(c.ChallengeError,'DUPLICATE_SUBMIT_CALL'):self.verify(row)
        row=deepcopy(self.records);row['destination_final']['accepted_recovery_effects']=2
        with self.assertRaisesRegex(c.ChallengeError,'DUPLICATE_RECOVERY_EFFECT'):self.verify(row)
        row=deepcopy(self.records);row['destination_final']['accepted']['attempts']=2
        with self.assertRaisesRegex(c.ChallengeError,'DESTINATION_EFFECT_MISMATCH'):self.verify(row)
        row=deepcopy(self.records);row['destination_final']['raw_submit_calls'][0]['attemptId']='foreign-attempt'
        with self.assertRaisesRegex(c.ChallengeError,'SUBMIT_CALL_IDENTITY_CHANGED'):self.verify(row)

    def test_hook_and_base_manifest_must_match_the_plan(self):
        row=deepcopy(self.records);row['instrumentation']['base_manifest_sha256']='1'*64
        with self.assertRaisesRegex(c.ChallengeError,'INSTRUMENTED_PLAN_REQUIRED'):self.verify(row)
        row=deepcopy(self.records);row['instrumentation']['instrumented_manifest_sha256']=self.plan['bindings']['manifest_sha256']
        with self.assertRaisesRegex(c.ChallengeError,'INSTRUMENTATION_BINDING_MISMATCH'):self.verify(row)

    def test_forged_plan_digest_or_fields_fail(self):
        original=self.plan;self.plan=deepcopy(original);self.plan['ready']=True
        with self.assertRaisesRegex(c.ChallengeError,'PLAN_DIGEST_MISMATCH'):self.verify()
        # Even a caller who repins altered bytes cannot expand the fixed effect scope.
        self.plan=deepcopy(original);self.plan['expected_effect']['target']='A'
        self.plan['plan_sha256']=c.digest({k:v for k,v in self.plan.items() if k!='plan_sha256'})
        row=deepcopy(self.records);row['plan_sha256']=self.plan['plan_sha256']
        with self.assertRaisesRegex(c.ChallengeError,'INVALID_PLAN_EFFECT_SCOPE'):self.verify(row)

    def test_unknown_fields_and_bad_json_are_rejected(self):
        row=deepcopy(self.records);row['authorization']='SYNTHETIC_PLACEHOLDER'
        with self.assertRaisesRegex(c.ChallengeError,'INVALID_OBSERVATION_PACKET'):self.verify(row)
        for raw in (b'{"a":1,"a":2}',b'{"a":NaN}',b'{"a":"\\ud800"}'):
            with self.subTest(raw=raw),self.assertRaises(c.ChallengeError):c.parse(raw)

    def test_cli_refuses_unpinned_observation_bytes(self):
        packet=Path(self.temp.name)/'synthetic-observations.json';self.lab.put(packet,self.records)
        stdout=io.StringIO()
        with redirect_stdout(stdout):
            code=c.main(['verify','--plan',str(self.lab.output/c.PLAN_NAME),'--plan-sha256',self.plan['plan_sha256'],
                '--observations',str(packet),'--observations-sha256','1'*64])
        result=json.loads(stdout.getvalue());self.assertEqual(code,1);self.assertFalse(result['execution_attempted'])
        self.assertFalse(result['ready'])


def instrument_fixture(lab):
    """A synthetic bundle + simulated ordinary builder; never native evidence."""
    baseline=lab.base/'original-bundle';shutil.copytree(lab.app,baseline)
    simulator=(ROOT/c.SIMULATOR).read_bytes()
    (baseline/c.SIMULATOR).write_bytes(simulator)
    index='src/chronos_web/index.html'
    empty=b'<meta name="chronos-api-base" content="">\n'
    (baseline/index).write_bytes(empty.replace(b'content=""',b'content="/csp/chronos/"'))
    helper='tools/application_bundle.py';(baseline/helper).write_bytes(b'# SYNTHETIC BUILD FIXTURE: NEVER EXECUTED\n')
    old=c.parse((baseline/'bundle-manifest.json').read_bytes())
    old['api_base']='/csp/chronos/'
    old['output_sha256']={p.relative_to(baseline).as_posix():sha256(p.read_bytes()).hexdigest()
        for p in baseline.rglob('*') if p.is_file() and p.name!='bundle-manifest.json'}
    old['source_sha256']=dict(old['output_sha256']);old['source_sha256'][index]=sha256(empty).hexdigest()
    raw=lab.put(baseline/'bundle-manifest.json',old);old_sha=sha256(raw).hexdigest()

    def fake_builder(args,**kwargs):
        # Emulate only the builder's source/output contract. The real ordinary
        # builder and IRIS compilation require separate runtime validation.
        assert args[0]==os.sys.executable and args[1]=='-B' and args[3]=='build'
        source=Path(args[5]);output=Path(args[7]);api=args[9];output.mkdir()
        sources={p.relative_to(source).as_posix():p.read_bytes() for p in source.rglob('*') if p.is_file()}
        outputs=dict(sources);outputs[index]=sources[index].replace(b'content=""',('content="'+api+'"').encode())
        for name,content in outputs.items():
            p=output/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(content)
        manifest=deepcopy(old);manifest['source_sha256']={k:sha256(v).hexdigest() for k,v in sources.items()}
        manifest['output_sha256']={k:sha256(v).hexdigest() for k,v in outputs.items()}
        lab.put(output/'bundle-manifest.json',manifest)
        return subprocess.CompletedProcess(args,0,'{}','')
    with patch.object(c,'datetime',Clock):proof=c.instrument(baseline,old_sha,lab.base/'instrumented',run=fake_builder)
    # A newly staged copy is used; preserve both original app trees.
    lab.app.rename(lab.stage/'preserved-original-app')
    shutil.copytree(lab.base/'instrumented/bundle',lab.app)
    lab.manifest=c.parse((lab.app/'bundle-manifest.json').read_bytes())
    lab.manifest_sha=proof['derived_manifest_sha256'];lab.receipt['bundle_manifest_sha256']=lab.manifest_sha
    lab.refresh_receipt()
    return proof,lab.base/'instrumented/instrumentation.json'


class ExecutionClock(datetime):
    current=datetime(2026,11,13,0,2,0,tzinfo=timezone.utc)
    @classmethod
    def now(cls,tz=None):return cls.current
    @classmethod
    def advance(cls):cls.current+=c.timedelta(seconds=1)


class FakeDocker:
    """A fake process boundary. All files and decisions are synthetic."""
    evidence_kind='SYNTHETIC_TEST_ONLY'
    def __init__(self,lab,record):
        self.lab=lab;self.record=record;self.snapshot=deepcopy(lab.snapshot);self.commands=[]
        self.exit=dict(finished_at='0001-01-01T00:00:00Z',exit_code=0)
        self.restarted=False;self.recovered=False;self.rows=observations(record)
    def inspect(self,cid):
        assert cid==self.record['owner']['container_id']
        snap=deepcopy(self.snapshot);snap['captured_at']=ExecutionClock.now().isoformat()
        return snap,dict(self.exit)
    def call(self,args,**kwargs):
        self.commands.append(list(args));cid=self.record['owner']['container_id']
        if args[0]=='exec':
            assert args[4]==cid and args[-1]==c.ARM_PROGRAM
            arm=json.loads(kwargs['input']);control=c.challenge_paths(self.record);control.mkdir()
            self.lab.put(control/'arm.json',arm)
            return json.dumps(dict(status='ARMED_ONCE',run_id=self.record['run_id']))
        if args[0]=='kill':
            assert args==['kill','--signal','KILL',cid]
            ExecutionClock.advance();self.snapshot['container']['state']['running']=False
            self.exit=dict(finished_at=ExecutionClock.now().isoformat(),exit_code=137)
            return cid
        if args[0]=='start':
            assert args==['start',cid]
            ExecutionClock.advance();self.snapshot['container']['state'].update(running=True,started_at=ExecutionClock.now().isoformat())
            self.restarted=True;return cid
        raise AssertionError('No other process command is allowed in the test')
    def script(self,cid,name,args=(),**kwargs):
        assert cid==self.record['owner']['container_id']
        self.commands.append(['script',cid,name,*args])
        if name=='native_health':return dict(ready=True,code='ENGINE_READY')
        if args[0]=='inspect':
            return dict(status='CRASH_RECOVERY_AVAILABLE' if self.restarted else 'CURRENTLY_RUNNING',
                runtime_ready=not self.restarted,profile_sha256=self.record['bindings']['profile_sha256'],
                current_generation='synthetic-generation-before',production_state=4 if self.restarted else 1)
        assert name=='native_resume' and args[0]=='recover'
        request_id=args[args.index('--request-id')+1];self.recovered=True
        return dict(self.rows['resume'],request_id=request_id)
    def engine_health(self,cid,*,timeout=15):
        return self.script(cid,'native_health',['engine'],timeout=timeout)
    def console_ready(self,cid,**kwargs):
        assert cid==self.lab.cid and kwargs=={'timeout':30}
        self.commands.append(['readonly-console-ready',cid])
    def operation(self,record,operation_id,*,pending):
        assert operation_id==self.rows['before_cut']['barrier']['operationId']
        return deepcopy(self.rows['before_cut']['iris'] if pending else self.rows['recovered_operation'])
    def human_confirmation_marker(self):
        # Simulate an independently supplied native marker. This is not a login
        # or approval and must never be published as an observed native run.
        control=c.challenge_paths(self.record);arm=c.parse((control/'arm.json').read_bytes())
        ids={k:self.rows['before_cut']['barrier'][k] for k in ('operationId','attemptId','admissionId')}
        ExecutionClock.advance()
        marker=dict(ids,armed_at=arm['armed_at'],started_at=ExecutionClock.now().isoformat(),wait_seconds=45,
            receipt=self.rows['before_cut']['barrier']['receipt'],run_id=self.record['run_id'],plan_sha256=self.record['plan_sha256'])
        self.lab.put(control/'claim.json',ids|dict(run_id=self.record['run_id'],plan_sha256=self.record['plan_sha256']))
        self.lab.put(control/'submit-call.json',ids);self.lab.put(control/'committed-before-return.json',marker)


class ExecutorTests(unittest.TestCase):
    def setUp(self):
        # The Windows app's redirected temp root is unusually long. Keep owned
        # test names short without changing any OS setting or writing to D.
        self.temp=tempfile.TemporaryDirectory(prefix='cc-');self.addCleanup(self.temp.cleanup)
        self.lab=Lab(self.temp.name,short=True);self.proof,self.proof_file=instrument_fixture(self.lab)
        self.record=self.lab.plan(instrumentation_path=self.proof_file,instrumentation_sha256=self.proof['instrumentation_sha256'])
        (self.lab.data/'chronos'/self.lab.ident).mkdir(parents=True)
        self.fake=FakeDocker(self.lab,self.record);ExecutionClock.current=datetime(2026,11,13,0,2,0,tzinfo=timezone.utc)
        self.clock=patch.object(c,'datetime',ExecutionClock);self.clock.start();self.addCleanup(self.clock.stop)
        self.destination=patch.object(c,'destination',return_value=(self.fake.rows['before_cut']['destination'],1))
        self.destination.start();self.addCleanup(self.destination.stop)

    def inputs(self):return (self.lab.output/c.PLAN_NAME,self.record['plan_sha256'],self.proof_file,self.proof['instrumentation_sha256'],self.fake)
    def arm(self):return c.arm(*self.inputs(),authorize_id=self.lab.ident)
    def cut(self):return c.watch_and_cut(*self.inputs(),authorize_cut=self.record['run_id']+':'+self.lab.cid)
    def recover(self):return c.recover(*self.inputs(),authorize_recover=self.record['run_id']+':'+self.lab.cid)

    def test_derived_source_is_explicit_and_original_preserved(self):
        self.assertEqual(self.proof['changed_files'],[c.SIMULATOR]);self.assertFalse(self.proof['native_tested'])
        self.assertFalse(self.proof['ready']);self.assertNotEqual(self.proof['base_manifest_sha256'],self.proof['derived_manifest_sha256'])
        self.assertEqual(c.check_instrumentation(self.proof_file,self.proof['instrumentation_sha256'],self.record['bindings']),self.proof)
        original=Path(self.proof['original_bundle'])/c.SIMULATOR
        self.assertIn(c.ORIGINAL_SUBMIT,original.read_text(encoding='utf-8'))
        self.assertEqual((Path(self.proof['derived_bundle'])/c.SIMULATOR).read_bytes(),c.instrumented_simulator(original.read_bytes()))

    def test_recover_accepts_only_terminal_destination_advance(self):
        self.arm();self.fake.human_confirmation_marker();self.cut()
        advanced=deepcopy(self.fake.rows['before_cut']['destination']);advanced['state']='DELIVERED_SIMULATED'
        with patch.object(c,'destination',return_value=(advanced,1)):
            result=self.recover()
        evidence=result['native_observations'];evidence['operator_readback']=self.fake.rows['operator_readback']
        self.assertEqual(evidence['destination_final']['accepted']['state'],'DELIVERED_SIMULATED')
        self.assertEqual(c.verify_records(evidence,self.record,expected_plan_sha256=self.record['plan_sha256'],allow_synthetic=True)['status'],'PASS')
        self.assertEqual(len([row for row in self.fake.commands if row[0]=='kill']),1)
        self.assertEqual(len([row for row in self.fake.commands if row[:3]==['script',self.lab.cid,'native_resume'] and row[3]=='recover']),1)

    def test_synthetic_full_sequence_cuts_once_and_restarts_same_container(self):
        armed=self.arm();self.assertFalse(armed['approval_sent']);self.assertEqual(armed['status'],'ARMED_ONCE_WAITING_FOR_HUMAN_UI_CONFIRMATION')
        self.fake.human_confirmation_marker();cut=self.cut();self.assertEqual(cut['status'],'ENGINE_CUT_OBSERVED')
        result=self.recover();self.assertEqual(result['status'],'NATIVE_RECOVERY_VERIFIED_OPERATOR_READBACK_PENDING')
        evidence=result['native_observations'];self.assertEqual(evidence['evidence_kind'],'SYNTHETIC_TEST_ONLY')
        evidence['operator_readback']=self.fake.rows['operator_readback']
        self.assertEqual(c.verify_records(evidence,self.record,expected_plan_sha256=self.record['plan_sha256'],allow_synthetic=True)['status'],'PASS')
        kills=[row for row in self.fake.commands if row[0]=='kill'];starts=[row for row in self.fake.commands if row[0]=='start']
        self.assertEqual(kills,[['kill','--signal','KILL',self.lab.cid]]);self.assertEqual(starts,[['start',self.lab.cid]])
        self.assertFalse(result['ready']);self.assertFalse(result['approval_sent'])
        with self.assertRaisesRegex(c.ChallengeError,'CUT_ALREADY_RESERVED_OR_COMPLETED'):self.cut()
        with self.assertRaisesRegex(c.ChallengeError,'RECOVERY_ALREADY_RESERVED_USE_NATIVE_STATUS'):self.recover()
        self.assertEqual(len([row for row in self.fake.commands if row[0]=='kill']),1)

    def test_exact_current_authorization_is_required_before_any_mutation(self):
        with self.assertRaisesRegex(c.ChallengeError,'EXPLICIT_ARM_AUTHORIZATION_REQUIRED'):
            c.arm(*self.inputs(),authorize_id='f'*32)
        self.assertEqual(self.fake.commands,[])
        with self.assertRaisesRegex(c.ChallengeError,'EXPLICIT_EXACT_CUT_AUTHORIZATION_REQUIRED'):
            c.watch_and_cut(*self.inputs(),authorize_cut=self.record['run_id']+':'+'c'*64)
        self.assertEqual(self.fake.commands,[])

    def test_arm_is_exclusive_even_when_container_result_is_uncertain(self):
        original=self.fake.call
        def uncertain(args,**kwargs):
            result=original(args,**kwargs)
            if args[0]=='exec':raise c.ChallengeError('SIMULATED_PROCESS_REPLY_LOST')
            return result
        self.fake.call=uncertain
        with self.assertRaisesRegex(c.ChallengeError,'SIMULATED_PROCESS_REPLY_LOST'):self.arm()
        with self.assertRaisesRegex(c.ChallengeError,'CHALLENGE_ALREADY_ARMED_OR_CONSUMED'):self.arm()
        self.assertEqual(len([row for row in self.fake.commands if row[0]=='exec']),1)

    def test_foreign_owner_and_changed_bundle_never_trigger_cut(self):
        self.arm();self.fake.human_confirmation_marker()
        self.fake.snapshot['container']['id']='c'*64
        with self.assertRaisesRegex(c.ChallengeError,'FOREIGN_CONTAINER_ID'):self.cut()
        self.assertFalse(any(row[0]=='kill' for row in self.fake.commands))
        self.fake.snapshot['container']['id']=self.lab.cid
        (self.lab.app/'deployment/native_resume.py').write_bytes(b'# SYNTHETIC TAMPER')
        with self.assertRaisesRegex(c.ChallengeError,'BUNDLE_SOURCE_CHANGED'):self.cut()
        self.assertFalse(any(row[0]=='kill' for row in self.fake.commands))

    def test_generation_change_during_last_read_never_cuts(self):
        self.arm();self.fake.human_confirmation_marker()
        original=self.fake.operation
        reads=0
        def restart_during_read(*args,**kwargs):
            nonlocal reads
            answer=original(*args,**kwargs);reads+=1
            if reads==2:
                self.fake.snapshot['container']['state']['started_at']=ExecutionClock.now().isoformat()
            return answer
        self.fake.operation=restart_during_read
        with self.assertRaisesRegex(c.ChallengeError,'ENGINE_GENERATION_CHANGED'):
            self.cut()
        self.assertEqual(reads,2)
        self.assertEqual([x for x in self.fake.commands if x[0]=='kill'],[])
        self.assertTrue(self.fake.snapshot['container']['state']['running'])
        self.assertTrue((self.lab.output/'cut-request.json').exists())
        with self.assertRaisesRegex(c.ChallengeError,'CUT_ALREADY_RESERVED_OR_COMPLETED'):
            self.cut()
        self.assertFalse(any(x[0]=='kill' for x in self.fake.commands))

    def test_uncertain_cut_is_not_issued_again(self):
        self.arm();self.fake.human_confirmation_marker();original=self.fake.call
        def uncertain(args,**kwargs):
            result=original(args,**kwargs)
            if args[0]=='kill':raise c.ChallengeError('SIMULATED_KILL_REPLY_LOST')
            return result
        self.fake.call=uncertain
        with self.assertRaisesRegex(c.ChallengeError,'SIMULATED_KILL_REPLY_LOST'):self.cut()
        with self.assertRaisesRegex(c.ChallengeError,'CUT_ALREADY_RESERVED_OR_COMPLETED'):self.cut()
        self.assertEqual(len([row for row in self.fake.commands if row[0]=='kill']),1)

    def test_missing_marker_does_not_cut_or_initiate_approval(self):
        self.arm();ticks=iter((0,2))
        with self.assertRaisesRegex(c.ChallengeError,'BARRIER_NOT_OBSERVED_NO_CUT'):
            c.watch_and_cut(*self.inputs(),authorize_cut=self.record['run_id']+':'+self.lab.cid,
                timeout=1,monotonic=lambda:next(ticks),sleep=lambda _:None)
        self.assertFalse(any(row[0] in ('kill','start') for row in self.fake.commands))

    def test_readonly_hook_tamper_is_detected_before_process_calls(self):
        hook=self.proof_file.parent/'hook.py';os.chmod(hook,stat.S_IRUSR|stat.S_IWUSR)
        hook.write_bytes(b'# SYNTHETIC TAMPER')
        with self.assertRaisesRegex(c.ChallengeError,'READONLY_HOOK_CHANGED'):self.arm()
        self.assertEqual(self.fake.commands,[])

    def test_changed_cut_record_is_rejected_before_restart(self):
        self.arm();self.fake.human_confirmation_marker();self.cut()
        path=self.lab.output/'cut-result.json';changed=c.parse(path.read_bytes());changed['cut']['exit_code']=0
        self.lab.put(path,changed)
        with self.assertRaisesRegex(c.ChallengeError,'STOPPED_ENGINE_DIFFERS_FROM_CUT'):self.recover()
        self.assertFalse(any(row[0]=='start' for row in self.fake.commands))

    def test_offline_finalizer_will_not_promote_simulation_to_native_proof(self):
        self.arm();self.fake.human_confirmation_marker();self.cut();self.recover()
        native=self.lab.output/'recover-result.json';ui=self.lab.base/'ui.json';self.lab.put(ui,self.fake.rows['operator_readback'])
        output=self.lab.base/'not-a-native-proof.json';commands=deepcopy(self.fake.commands)
        with self.assertRaisesRegex(c.ChallengeError,'SYNTHETIC_OR_UNKNOWN_OBSERVATIONS'):
            c.finalize(self.lab.output/c.PLAN_NAME,self.record['plan_sha256'],native,sha256(native.read_bytes()).hexdigest(),
                ui,sha256(ui.read_bytes()).hexdigest(),output)
        self.assertFalse(output.exists());self.assertEqual(self.fake.commands,commands)


class DockerBoundaryTests(unittest.TestCase):
    def test_only_local_endpoint_and_exact_sanitized_inspection_fields(self):
        with tempfile.TemporaryDirectory(prefix='chronos-fake-docker-test-') as root:
            lab=Lab(root);exe=Path(root)/'docker.exe';exe.write_bytes(b'SYNTHETIC FILE; NEVER EXECUTED')
            row=lab.snapshot['container'];state=row['state'];host=row['host']
            values=[row['id'],row['image'],row['project'],row['service'],state['running'],state['oom_killed'],state['started_at'],
                '0001-01-01T00:00:00Z',0,host['privileged'],host['memory_bytes'],host['network_mode'],host['port_bindings']]
            text='\n'.join(json.dumps(v) for v in values)+'\n'
            for mount in row['mounts']:text+='\t'.join(json.dumps(mount[k]) for k in ('type','source','destination','read_write'))+'\n'
            calls=[]
            def run(args,**kwargs):calls.append((args,kwargs));return subprocess.CompletedProcess(args,0,text,'')
            docker=c.Docker(exe,run=run);snapshot,_=docker.inspect(lab.cid)
            self.assertEqual(snapshot['container'],row)
            self.assertIn('--host',calls[0][0]);self.assertNotIn('.Config.Env',c.INSPECT_TEMPLATE)
            self.assertEqual(calls[0][0][-1],lab.cid)
            with self.assertRaisesRegex(c.ChallengeError,'LOCAL_DOCKER_ENDPOINT_REQUIRED'):
                c.Docker(exe,run=run,host='tcp://remote.example:2375')


class HookTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='h-');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.ident='a'*32
        self.control=self.root/'chronos'/self.ident/c.CONTROL;self.control.mkdir(parents=True)
        self.scope={};exec(compile(c.HOOK_CODE,'synthetic-exact-hook-test','exec'),self.scope)
        self.scope['Path']=lambda value:self.root/str(value).removeprefix('/durable/')
        self.operation=dict(operationId='test-operation',attemptId='test-attempt',admissionId='test-admission',
            orderId='jury-'+self.ident+'-queue_inventory',shipmentVersion=1,target='B')
        now=datetime.now(timezone.utc)
        self.arm=dict(schema='chronos.crash-arm.v1',deployment_id=self.ident,order_id=self.operation['orderId'],
            shipment_version=1,target='B',run_id='b'*32,plan_sha256='c'*64,instrumentation_sha256='d'*64,
            armed_at=(now-c.timedelta(seconds=1)).isoformat(),expires_at=(now+c.timedelta(seconds=180)).isoformat(),wait_seconds=45)
        Lab.put(self.control/'arm.json',self.arm)
        self.calls=[]
        outer=self
        class Runtime:
            def submit(self,operation,ticket):
                outer.calls.append(deepcopy(operation))
                return {k:operation[k] for k in ('operationId','attemptId','orderId','shipmentVersion','target')}|dict(
                    status='ACCEPTED',closedForever=False,reference='B-test-operation',receiptId='r-'+'1'*64)
        self.runtime=Runtime()

    def test_exact_hook_claims_once_before_submit_and_retains_committed_receipt(self):
        with patch.object(self.scope['time'],'sleep',side_effect=TimeoutError('SYNTHETIC_SLEEP_NOT_EXECUTED')):
            with self.assertRaisesRegex(TimeoutError,'SYNTHETIC_SLEEP_NOT_EXECUTED'):
                self.scope['submit'](self.runtime,'/durable/chronos/'+self.ident+'/owned-destinations',
                    dict(operation=self.operation,ticket={'synthetic_test_only':True}))
        marker=c.parse((self.control/'committed-before-return.json').read_bytes())
        self.assertEqual(marker['receipt']['reference'],'B-test-operation');self.assertFalse(marker['receipt']['closedForever'])
        self.assertEqual(len(self.calls),1)
        with self.assertRaises(FileExistsError):
            self.scope['submit'](self.runtime,'/durable/chronos/'+self.ident+'/owned-destinations',dict(operation=self.operation,ticket={}))
        self.assertEqual(len(self.calls),1)

    def test_expired_arm_and_foreign_target_never_enter_submit(self):
        self.arm['expires_at']=(datetime.now(timezone.utc)-c.timedelta(seconds=1)).isoformat()
        Lab.put(self.control/'arm.json',self.arm)
        with self.assertRaisesRegex(ValueError,'CRASH_LAB_ARM_EXPIRED'):
            self.scope['submit'](self.runtime,'/durable/chronos/'+self.ident+'/owned-destinations',dict(operation=self.operation,ticket={}))
        with self.assertRaisesRegex(ValueError,'CRASH_LAB_ONLY_EXACT_B'):
            self.scope['submit'](self.runtime,'/durable/chronos/'+self.ident+'/owned-destinations',
                dict(operation=self.operation|{'target':'A'},ticket={}))
        self.assertEqual(self.calls,[])

    def test_other_owned_case_keeps_original_submit_behavior(self):
        other=self.operation|dict(orderId='jury-'+self.ident+'-economy',target='A')
        result=self.scope['submit'](self.runtime,'/durable/chronos/'+self.ident+'/owned-destinations',dict(operation=other,ticket={}))
        self.assertEqual(result['status'],'ACCEPTED');self.assertEqual(len(self.calls),1)
        self.assertFalse((self.control/'claim.json').exists())


class SQLiteReadbackTests(unittest.TestCase):
    """All databases and exec boundaries here are synthetic local fixtures."""
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='sql-',dir=os.environ.get('CHRONOS_TEST_TMPDIR'))
        self.addCleanup(self.temp.cleanup)
        self.lab=Lab(self.temp.name,short=True);self.record=self.lab.plan();rows=observations(self.record)
        self.ids={k:rows['before_cut']['barrier'][k] for k in ('operationId','attemptId','admissionId')}
        self.order=self.record['expected_effect']['order_id']
        definition={'world':{'order_id':self.order},'calendar':[],'start':0}
        self.dest=self.lab.data/'chronos'/self.lab.ident/'owned-destinations';self.dest.mkdir(parents=True)
        registry=sqlite3.connect(self.dest/'registry.sqlite')
        registry.execute('CREATE TABLE registrations(order_id TEXT,definition TEXT)')
        registry.execute('INSERT INTO registrations VALUES (?,?)',(self.order,c.canonical(definition).decode()))
        registry.commit();registry.close()
        provider=self.dest/'orders'/c.digest(definition)/'provider.sqlite';provider.parent.mkdir(parents=True)
        self.db=sqlite3.connect(provider);self.addCleanup(self.db.close)
        self.db.executescript('CREATE TABLE operations(target TEXT,operation_id TEXT,binding TEXT,result TEXT);'
            'CREATE TABLE attempts(target TEXT,operation_id TEXT);CREATE TABLE observations(kind TEXT,target TEXT,operation_id TEXT);')
        binding=dict(operation_id=self.ids['operationId'],attempt_id=self.ids['attemptId'],order_id=self.order,shipment_version=1,target='B')
        self.db.execute('INSERT INTO operations VALUES (?,?,?,?)',('B',self.ids['operationId'],json.dumps(binding),'{"state":"ACCEPTED"}'))
        self.db.execute('INSERT INTO attempts VALUES (?,?)',('B',self.ids['operationId']))
        self.db.execute('INSERT INTO observations VALUES (?,?,?)',('SUBMIT','B',self.ids['operationId']));self.db.commit()
        self.commands=[];self.connections=[];outer=self
        real_connect=sqlite3.connect
        class Connection:
            def __init__(self,db):self.db=db;self.closed=False
            def execute(self,*args,**kwargs):return self.db.execute(*args,**kwargs)
            def close(self):self.closed=True;self.db.close()
        def fake_connect(*args,**kwargs):
            obj=Connection(real_connect(*args,**kwargs));outer.connections.append(obj);return obj
        class FakeSQLite:
            Error=sqlite3.Error
            connect=staticmethod(fake_connect)
        class FakeSys:
            stdin=None
            @staticmethod
            def exit(code):raise SystemExit(code)
        def fake_call(args,**kwargs):
            outer.commands.append((args,kwargs))
            assert args==['exec','-i','--user','irisowner',outer.lab.cid,'/usr/bin/python3','-B','-c',c.DESTINATION_READ_PROGRAM]
            assert kwargs['timeout']==15
            body=__import__('ast').parse(c.DESTINATION_READ_PROGRAM)
            # Replace only imports for an isolated interpreter/FS boundary simulation.
            body.body=[node for node in body.body if not isinstance(node,(__import__('ast').Import,__import__('ast').ImportFrom))]
            def path(value):
                if str(value)=='/durable/chronos':return outer.lab.data/'chronos'
                return Path(value)
            FakeSys.stdin=io.StringIO(kwargs['input'])
            scope=dict(json=json,os=os,re=__import__('re'),sqlite3=FakeSQLite,stat=stat,sys=FakeSys,sha256=sha256,Path=path)
            output=io.StringIO()
            try:
                with redirect_stdout(output):exec(compile(body,'synthetic-container-exec','exec'),scope)
            except SystemExit as exc:
                raise c.ChallengeError('DOCKER_COMMAND_FAILED_STATE_PRESERVED') from None
            return output.getvalue()
        self.docker=type('SyntheticDocker',(),{'call':staticmethod(fake_call)})()
        self.owner=patch.object(c,'current_owner',return_value=(deepcopy(self.lab.snapshot),{}))
        self.owner_mock=self.owner.start();self.addCleanup(self.owner.stop)

    def test_real_sqlite_acceptance_count_survives_simulator_clock_advance(self):
        # Real owned SQLite and the actual temporal engine; no Docker/IRIS/model.
        import ast,sys
        saved_path=list(sys.path)
        try:
            sys.path.insert(0,str(ROOT/'src'))
            from chronos_simulation.registry import Registry
            from chronos_simulation.model import canonical as simulator_json
        finally:sys.path[:]=saved_path
        lab=Lab(Path(self.temp.name)/'actual-clock',short=True);record=lab.plan()
        root=lab.data/'chronos'/lab.ident/'owned-destinations';registry=Registry(root.resolve(),create=True)
        order=record['expected_effect']['order_id'];op='clock-op';attempt_id='clock-attempt'
        world=dict(order_id=order,shipment_version=1,revision=1,budget=8,deadline=20,inventory_expires=6,
            original_status='NOT_ACCEPTED_FINAL',preference='fastest',payload={'sku':'SYNTHETIC','quantity':1},messages=[],
            options={'A':dict(cost=3,available_at=0,queue_minutes=7,travel_minutes=8),
                     'B':dict(cost=6,available_at=0,queue_minutes=0,travel_minutes=9)})
        registry.register(world)
        attempt=dict(operation_id=op,attempt_id=attempt_id,order_id=order,shipment_version=1,target='B',
            payload=simulator_json(world['payload']),reserved_at=0,valid_until=60)
        store=registry._destination(order);receipt=store.submit(attempt)
        self.assertEqual(receipt['status'],'ACCEPTED')
        def read_actual_program():
            body=ast.parse(c.DESTINATION_READ_PROGRAM)
            body.body=[node for node in body.body if not isinstance(node,(ast.Import,ast.ImportFrom))]
            class ProgramSys:
                stdin=io.StringIO(json.dumps(dict(deployment_id=lab.ident,order_id=order,operation_id=op)))
                @staticmethod
                def exit(code):raise AssertionError('READ_PROGRAM_REJECTED:'+str(code))
            def local_path(value):return lab.data/'chronos' if str(value)=='/durable/chronos' else Path(value)
            namespace=dict(json=json,os=os,re=__import__('re'),sqlite3=sqlite3,stat=stat,sys=ProgramSys,sha256=sha256,Path=local_path)
            output=io.StringIO()
            with redirect_stdout(output):exec(compile(body,'actual-destination-read-program','exec'),namespace)
            return json.loads(output.getvalue())
        before=read_actual_program();self.assertEqual((before['accepted']['state'],before['accepted_effects']),('ACCEPTED',1))
        registry.advance(order,10)
        after=read_actual_program()
        self.assertEqual((after['accepted']['state'],after['accepted_effects']),('DELIVERED_SIMULATED',1))
        self.assertEqual((after['accepted']['submits'],after['accepted']['attempts']),(1,1))
        self.assertEqual(store.query(attempt),receipt)
        self.assertTrue(c.same_destination_after_acceptance(before['accepted'],after['accepted']))
        self.assertFalse(c.same_destination_after_acceptance(after['accepted'],before['accepted']))
        for field,value in (('operationId','other'),('attemptId','other'),('submits',2),('attempts',2),('submits',True)):
            with self.subTest(field=field):
                self.assertFalse(c.same_destination_after_acceptance(before['accepted'],dict(after['accepted'],**{field:value})))

    def test_read_only_provider_counts_detect_duplicate_recovery_effect(self):
        accepted,effects=c.destination(self.record,self.ids,self.docker)
        self.assertEqual((accepted['submits'],accepted['attempts'],effects),(1,1,1))
        self.db.execute('INSERT INTO observations VALUES (?,?,?)',('SUBMIT','B',self.ids['operationId']));self.db.commit()
        accepted,effects=c.destination(self.record,self.ids,self.docker)
        self.assertEqual(accepted['submits'],2)
        self.assertTrue(all(row.closed for row in self.connections))

    def test_host_never_imports_or_opens_sqlite_and_only_fixed_selects_are_used(self):
        import ast
        tree=ast.parse(Path(c.__file__).read_text(encoding='utf-8'))
        self.assertFalse(any(isinstance(node,ast.Import) and any(alias.name=='sqlite3' for alias in node.names)
                             for node in tree.body))
        wrapper=next(node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name=='destination')
        self.assertNotIn('connect',ast.unparse(wrapper))
        selects=[node.value for node in ast.walk(ast.parse(c.DESTINATION_READ_PROGRAM))
                 if isinstance(node,ast.Constant) and isinstance(node.value,str) and node.value.startswith('SELECT ')]
        self.assertCountEqual(selects,[
            'SELECT definition FROM registrations WHERE order_id=?',
            'SELECT target,operation_id,binding,result FROM operations ORDER BY operation_id',
            'SELECT COUNT(*) FROM attempts WHERE target=? AND operation_id=?',
            "SELECT COUNT(*) FROM observations WHERE kind='SUBMIT' AND target=? AND operation_id=?"])
        c.destination(self.record,self.ids,self.docker)
        self.assertEqual(len(self.commands),1)

    def test_exact_full_container_and_mount_ownership_checked_before_and_after(self):
        c.destination(self.record,self.ids,self.docker)
        self.assertEqual(self.owner_mock.call_count,2)
        for call in self.owner_mock.call_args_list:
            self.assertEqual(call.args,(self.docker,self.record))
            self.assertEqual(call.kwargs,dict(running=True,original_start=False))
        self.assertEqual(self.commands[0][0][4],self.lab.cid)

    def test_foreign_cid_or_mount_rejected_before_exec(self):
        for code in ('FOREIGN_CONTAINER_ID','FOREIGN_MOUNT_SCOPE'):
            with self.subTest(code=code):
                self.owner_mock.side_effect=c.ChallengeError(code)
                with self.assertRaisesRegex(c.ChallengeError,code):c.destination(self.record,self.ids,self.docker)
                self.assertEqual(self.commands,[])
        self.owner_mock.side_effect=None

    def test_generation_change_during_exec_rejected(self):
        before=deepcopy(self.lab.snapshot);after=deepcopy(before)
        after['container']['state']['started_at']='2026-11-13T00:01:50Z'
        self.owner_mock.side_effect=[(before,{}),(after,{})]
        with self.assertRaisesRegex(c.ChallengeError,'ENGINE_GENERATION_CHANGED_DURING_DESTINATION_READ'):
            c.destination(self.record,self.ids,self.docker)

    def test_foreign_deployment_order_or_operation_rejected_before_exec(self):
        for key in ('deployment','order','operation'):
            with self.subTest(key=key):
                record=deepcopy(self.record);ids=deepcopy(self.ids)
                if key=='deployment':record['bindings']['deployment_id']='../outside'
                elif key=='order':record['expected_effect']['order_id']='foreign'
                else:ids['operationId']='../outside'
                with self.assertRaises(c.ChallengeError):c.destination(record,ids,self.docker)
                self.assertEqual(self.commands,[])

    def test_wrong_operation_and_provider_errors_close_connections_without_raw_output(self):
        self.db.execute('UPDATE operations SET operation_id=?',('foreign-operation',));self.db.commit()
        with self.assertRaisesRegex(c.ChallengeError,'DOCKER_COMMAND_FAILED_STATE_PRESERVED'):
            c.destination(self.record,self.ids,self.docker)
        self.assertTrue(all(row.closed for row in self.connections))

    def test_malformed_or_oversharing_exec_output_rejected(self):
        for value in ('not-json',json.dumps(dict(status='DESTINATION_READ_VERIFIED',accepted={},accepted_effects=1,secret='NEVER_RETURN'))):
            with self.subTest(value=value):
                docker=type('BadOutput',(),{'call':staticmethod(lambda *a,**k:value)})()
                with self.assertRaises(c.ChallengeError):c.destination(self.record,self.ids,docker)

    def test_error_output_is_sanitized(self):
        self.db.execute('DROP TABLE operations');self.db.commit()
        with self.assertRaisesRegex(c.ChallengeError,'DOCKER_COMMAND_FAILED_STATE_PRESERVED') as found:
            c.destination(self.record,self.ids,self.docker)
        self.assertNotIn(str(self.dest),str(found.exception))
        self.assertNotIn('operations',str(found.exception))
        self.assertTrue(all(row.closed for row in self.connections))


if __name__=='__main__':unittest.main()
