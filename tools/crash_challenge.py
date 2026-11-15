"""Offline ownership planner and retained-record verifier for a synthetic crash lab.

Plan/verify/instrument are offline. The explicit arm/watch-and-cut/recover
commands are limited to a separately installed, instrumented disposable lab.
They never create accounts, log in, read credentials or confirm an approval.
The operator must approve the synthetic recovery through the ordinary UI.
A passing offline verifier establishes consistency, not a new IRIS execution.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timedelta, timezone
import difflib
from hashlib import sha256
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import time
from urllib.parse import urlsplit
from uuid import uuid4

PLAN_SCHEMA='chronos.crash-plan.v1'
SNAPSHOT_SCHEMA='chronos.crash-owner-snapshot.v1'
OBSERVATION_SCHEMA='chronos.crash-observations.v1'
EXECUTION_COMMANDS=frozenset({'arm','watch-and-cut','recover'})
PLAN_NAME='crash-plan.json'
BOUNDARY='DESTINATION_COMMIT_BEFORE_ADAPTER_RETURN'
HEX=re.compile(r'[a-f0-9]{64}\Z')
IDENTIFIER=re.compile(r'[A-Za-z0-9_.:-]{1,128}\Z')
MAX_JSON=1024*1024
MAX_FILE=8*1024*1024
MAX_BUNDLE=64*1024*1024
INSTRUMENT_SCHEMA='chronos.crash-instrumentation.v1'
SIMULATOR='src/Chronos/Destination/Simulator.cls'
CONTROL='crash'
ORIGINAL_SUBMIT='    elif command=="SUBMIT":result=runtime.submit(args["operation"],args["ticket"])'

# This exact source is embedded in only the derived lab's synthetic adapter.
# It is never executed by plan, instrument or the offline unit-test verifier.
HOOK_CODE='''import json,os,re,time
from pathlib import Path
from datetime import datetime,timezone

def submit(runtime,root,args):
    match=re.fullmatch(r'/durable/chronos/([a-f0-9]{32})/owned-destinations',root)
    if not match:raise ValueError('CRASH_LAB_DESTINATION_SCOPE')
    ident=match[1];operation=args['operation'];order='jury-'+ident+'-queue_inventory'
    if operation.get('orderId')!=order:return runtime.submit(operation,args['ticket'])
    if operation.get('target')!='B' or type(operation.get('shipmentVersion')) is not int or operation['shipmentVersion']!=1:
        raise ValueError('CRASH_LAB_ONLY_EXACT_B')
    control=Path('/durable/chronos')/ident/'crash'
    for path in (*reversed(control.parents),control):
        info=path.lstat()
        if path.is_symlink() or getattr(info,'st_file_attributes',0)&0x400 or not path.is_dir():
            raise ValueError('CRASH_LAB_CONTROL_LINK')
    def pairs(items):
        out={}
        for key,value in items:
            if key in out:raise ValueError('CRASH_LAB_DUPLICATE_FIELD')
            out[key]=value
        return out
    raw=(control/'arm.json').read_bytes()
    if len(raw)>32768:raise ValueError('CRASH_LAB_CONTROL_LIMIT')
    arm=json.loads(raw,object_pairs_hook=pairs)
    fields={'schema','deployment_id','order_id','shipment_version','target','run_id','plan_sha256','instrumentation_sha256','armed_at','expires_at','wait_seconds'}
    if type(arm) is not dict or set(arm)!=fields or arm['schema']!='chronos.crash-arm.v1':
        raise ValueError('CRASH_LAB_ARM_SHAPE')
    if arm['deployment_id']!=ident or arm['order_id']!=order or arm['shipment_version']!=1 or arm['target']!='B':
        raise ValueError('CRASH_LAB_ARM_SCOPE')
    for key in ('plan_sha256','instrumentation_sha256'):
        if type(arm[key]) is not str or not re.fullmatch('[a-f0-9]{64}',arm[key]):raise ValueError('CRASH_LAB_ARM_BINDING')
    if type(arm['run_id']) is not str or not re.fullmatch('[a-f0-9]{32}',arm['run_id']):raise ValueError('CRASH_LAB_RUN_ID')
    now=datetime.now(timezone.utc)
    start=datetime.fromisoformat(arm['armed_at']);expiry=datetime.fromisoformat(arm['expires_at'])
    if start.tzinfo is None or expiry.tzinfo is None or start.utcoffset().total_seconds()!=0 or expiry.utcoffset().total_seconds()!=0:
        raise ValueError('CRASH_LAB_UTC_REQUIRED')
    if not start<=now<expiry or not 1<=(expiry-start).total_seconds()<=300 or arm['wait_seconds']!=45:
        raise ValueError('CRASH_LAB_ARM_EXPIRED')
    entered={key:operation.get(key) for key in ('operationId','attemptId','admissionId')}
    if any(type(value) is not str or not re.fullmatch('[A-Za-z0-9_.:-]{1,128}',value) for value in entered.values()):
        raise ValueError('CRASH_LAB_OPERATION_ID')
    def write(name,value):
        with (control/name).open('x',encoding='utf-8') as stream:
            json.dump(value,stream,sort_keys=True,allow_nan=False);stream.flush();os.fsync(stream.fileno())
    # The exclusive claim is durable BEFORE entering runtime.submit. An
    # uncertain/failed attempt cannot be retried by deleting an in-memory flag.
    write('claim.json',dict(entered,run_id=arm['run_id'],plan_sha256=arm['plan_sha256']))
    write('submit-call.json',entered)
    result=runtime.submit(operation,args['ticket'])
    if result.get('status')!='ACCEPTED':return result
    if any(result.get(key)!=entered[key] for key in ('operationId','attemptId')):
        raise ValueError('CRASH_LAB_RECEIPT_BINDING')
    marker=dict(entered,armed_at=arm['armed_at'],started_at=datetime.now(timezone.utc).isoformat(),
        wait_seconds=45,receipt=result,run_id=arm['run_id'],plan_sha256=arm['plan_sha256'])
    write('committed-before-return.json',marker)
    time.sleep(45)
    raise TimeoutError('CRASH_LAB_CUT_NOT_OBSERVED')
'''


class ChallengeError(ValueError):pass


def need(condition,code):
    if not condition:raise ChallengeError(code)


def shape(value,fields,code='INVALID_RECORD_SHAPE'):
    need(type(value) is dict and set(value)==set(fields),code)


def canonical(value):
    try:
        text=json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)
        return text.encode('utf-8')
    except (ValueError,TypeError,UnicodeError,RecursionError):raise ChallengeError('INVALID_JSON') from None


def digest(value):return sha256(canonical(value)).hexdigest()


def hex64(value):return type(value) is str and HEX.fullmatch(value) is not None


def integer(value,minimum=0,maximum=2**64-1):return type(value) is int and minimum<=value<=maximum


def parse(raw):
    need(type(raw) is bytes and 0<len(raw)<=MAX_JSON,'JSON_SIZE_LIMIT')
    def pairs(items):
        out={}
        for key,value in items:
            need(key not in out,'DUPLICATE_JSON_FIELD');out[key]=value
        return out
    def constant(_):raise ChallengeError('INVALID_JSON')
    try:
        result=json.loads(raw,object_pairs_hook=pairs,parse_constant=constant)
        canonical(result)
        return result
    except ChallengeError:raise
    except (ValueError,UnicodeError,RecursionError,OverflowError):raise ChallengeError('INVALID_JSON') from None


def local_path(value):
    need(isinstance(value,(str,os.PathLike)),'ABSOLUTE_PATH_REQUIRED')
    text=os.fspath(value)
    need(type(text) is str and not any(ord(c)<32 for c in text),'INVALID_LOCAL_PATH')
    path=Path(text)
    need(path.is_absolute() and '..' not in path.parts and '.' not in path.parts,'ABSOLUTE_PATH_REQUIRED')
    return path


def plain(path,*,directory=False):
    info=path.lstat()
    need(not stat.S_ISLNK(info.st_mode) and not getattr(info,'st_file_attributes',0)&0x400,'LINK_OR_REPARSE_POINT')
    need(stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode),'WRONG_PATH_KIND')
    return info


def directories(path):
    for part in (*reversed(path.parents),path):plain(part,directory=True)


def read(path,limit=MAX_JSON):
    path=local_path(path);directories(path.parent);before=plain(path)
    need(before.st_size<=limit,'FILE_SIZE_LIMIT')
    with path.open('rb') as stream:
        opened=os.fstat(stream.fileno())
        need((opened.st_dev,opened.st_ino)==(before.st_dev,before.st_ino),'FILE_CHANGED')
        raw=stream.read(limit+1);after=os.fstat(stream.fileno())
    current=plain(path)
    def identity(s):return s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns
    need(len(raw)<=limit and identity(before)==identity(after)==identity(current),'FILE_CHANGED')
    return raw


def timestamp(value):
    need(type(value) is str and 1<=len(value)<=48,'INVALID_UTC_TIME')
    try:
        stamp=datetime.fromisoformat(value.replace('Z','+00:00'))
        need(stamp.tzinfo is not None and stamp.utcoffset().total_seconds()==0,'UTC_REQUIRED')
        return stamp
    except (ValueError,OverflowError):raise ChallengeError('INVALID_UTC_TIME') from None


def relative_file(value):
    need(type(value) is str and 0<len(value)<240 and '\\' not in value and ':' not in value,'INVALID_MANIFEST_PATH')
    path=PurePosixPath(value)
    need(not path.is_absolute() and path.as_posix()==value and all(p not in ('.','..','') for p in path.parts),'INVALID_MANIFEST_PATH')
    return path


def verify_bundle(app,expected):
    need(hex64(expected),'EXPECTED_MANIFEST_DIGEST_REQUIRED')
    raw=read(app/'bundle-manifest.json');need(sha256(raw).hexdigest()==expected,'MANIFEST_DIGEST_MISMATCH')
    manifest=parse(raw)
    fields='schema_version status api_base required_iris_build source_sha256 output_sha256 transformed_files contains_image contains_accounts contains_runtime_data installed native_compilation_verified'.split()
    shape(manifest,fields,'INVALID_BUNDLE_MANIFEST')
    need(manifest['schema_version']=='chronos.application-bundle.v1'
         and manifest['status']=='STAGED_LOCAL_NOT_INSTALLED'
         and manifest['required_iris_build']=='2026.3.0AI.154.0','UNSUPPORTED_ENGINE_BUNDLE')
    need(all(manifest[k] is False for k in ('contains_image','contains_accounts','contains_runtime_data','installed','native_compilation_verified')),'INVALID_BUNDLE_CLAIM')
    need(manifest['transformed_files']==['src/chronos_web/index.html'],'UNRECOGNIZED_TRANSFORMATION')
    for field in ('source_sha256','output_sha256'):
        need(type(manifest[field]) is dict and 1<=len(manifest[field])<=1024,'INVALID_MANIFEST_HASHES')
        for name,value in manifest[field].items():relative_file(name);need(hex64(value),'INVALID_MANIFEST_HASHES')
    need(set(manifest['source_sha256'])==set(manifest['output_sha256']),'MANIFEST_INVENTORY_CHANGED')
    required={'src/Chronos/Destination/Simulator.cls','src/Chronos/Recovery/Coordinator.cls','deployment/native_resume.py','src/chronos_web/index.html'}
    need(required<=set(manifest['output_sha256']),'REQUIRED_CRASH_COMPONENT_MISSING')
    found=set();total=0
    for parent,dirs,files in os.walk(app,followlinks=False):
        parent=Path(parent);directories(parent)
        for name in dirs:plain(parent/name,directory=True)
        for name in files:
            path=parent/name;plain(path);found.add(path.relative_to(app).as_posix())
    need(found==set(manifest['output_sha256'])|{'bundle-manifest.json'},'BUNDLE_INVENTORY_CHANGED')
    for name,expected_hash in manifest['output_sha256'].items():
        raw=read(app/name,MAX_FILE);total+=len(raw)
        need(total<=MAX_BUNDLE,'BUNDLE_SIZE_LIMIT')
        need(sha256(raw).hexdigest()==expected_hash,'BUNDLE_SOURCE_CHANGED')
        if name!='src/chronos_web/index.html':
            need(expected_hash==manifest['source_sha256'][name],'UNRECOGNIZED_TRANSFORMATION')
    return manifest


def profile_binding(raw,*,conversation=False):
    value=parse(raw)
    fields=set('version deployment_id provider model schema_sha256 request_limit local_port reasoning_effort response_contract'.split())
    if type(value) is dict and value.get('provider')=='recorded-fixture':fields|={'replay_corpus_sha256','replay_fixture_sha256'}
    shape(value,fields,'INVALID_STAGE_PROFILE')
    version,contract=(6,'chronos.case-explanation-plan.v2') if conversation else (3,'chronos.preference-extraction.v1')
    need(value['version']==version and type(value['version']) is int and value['response_contract']==contract,'EXPECTED_PROFILE_REQUIRED')
    ident=value['deployment_id'];need(type(ident) is str and re.fullmatch(r'[a-f0-9]{32}',ident),'INVALID_DEPLOYMENT_ID')
    need(hex64(value['schema_sha256']) and integer(value['request_limit'],1,1000),'INVALID_STAGE_PROFILE')
    need(type(value['model']) is str and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}',value['model']),'INVALID_STAGE_PROFILE')
    if value['provider']=='ollama':
        need(value['local_port']==11434 and type(value['local_port']) is int and value['reasoning_effort'] in ('none','low','medium'),'INVALID_STAGE_PROFILE')
    else:
        need(value['provider']=='recorded-fixture' and value['model']=='chronos-recorded-fixture-v1'
             and value['local_port'] is None and value['reasoning_effort']=='none'
             and all(hex64(value[k]) for k in ('replay_corpus_sha256','replay_fixture_sha256')),'INVALID_STAGE_PROFILE')
    # Profile digest uses the existing public Profile's ASCII canonical format.
    fingerprint=sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True).encode()).hexdigest()
    return value,fingerprint


def origin_port(value):
    need(type(value) is str,'INVALID_WEB_ORIGIN')
    try:p=urlsplit(value);port=p.port
    except ValueError:raise ChallengeError('INVALID_WEB_ORIGIN') from None
    need(p.scheme in ('http','https') and p.hostname in ('127.0.0.1','localhost','::1') and p.username is None
         and p.password is None and not p.path and not p.query and not p.fragment and integer(port,1024,65535),'LOOPBACK_ORIGIN_REQUIRED')
    return port


def mount_source(value):
    """Strict Docker Desktop drive mapping; Linux paths keep case and spelling."""
    need(type(value) is str and 1<len(value)<512 and not any(ord(c)<32 for c in value),'INVALID_MOUNT_SOURCE')
    text=value.replace('\\','/')
    drive=re.fullmatch(r'([A-Za-z]):/(.+)',text)
    if drive:
        need(all(p not in ('','..','.') for p in drive[2].split('/')),'INVALID_MOUNT_SOURCE')
        return drive[1].lower()+':/'+drive[2]
    desktop=re.fullmatch(r'/(?:run/desktop/mnt/host|host_mnt)/([a-zA-Z])/(.+)',text)
    if desktop:
        need(all(p not in ('','..','.') for p in desktop[2].split('/')),'INVALID_MOUNT_SOURCE')
        return desktop[1].lower()+':/'+desktop[2]
    need(text.startswith('/') and not text.startswith('//') and '\\' not in value
         and all(p not in ('','..','.') for p in text[1:].split('/')),'INVALID_MOUNT_SOURCE')
    return text


def same_directory(observed,expected):
    """Compare real directory identities, never Unicode casefold or suffixes.

    Docker Desktop's two known drive prefixes are translated to their host
    paths. Both complete ancestor chains must be ordinary directories. This
    resolves Windows case aliases using the filesystem's own identity rules.
    """
    source=local_path(mount_source(observed));expected=local_path(expected)
    try:
        directories(source);directories(expected)
        return os.path.samefile(source,expected)
    except OSError:return False


def runtime_binding(stage,bindings,profile):
    """Bind the optional real jury layout without inspecting runtime secrets.

    The original workspace receipt remains a historical files-only statement;
    populated guard/chat directories are allowed, but their identities and the
    immutable profile/corpus bytes are sealed into this new plan.
    """
    root=stage.parent;file=root/'jury-workspace.json'
    if not os.path.lexists(file):
        need(profile['provider']=='ollama','RECORDED_WORKSPACE_RECEIPT_REQUIRED')
        return None
    raw=read(file);receipt=parse(raw)
    fields=set('schema status mode root deployment_id origin bundle_manifest_sha256 e1_profile_sha256 c2_profile_sha256 environment compose_files profiles installed accounts_created services_started model_calls allowances_initialized'.split())
    replay=profile['provider']=='recorded-fixture'
    if replay:fields|={'replay_corpus_sha256','replay_fixture_sha256','capture_allowlist_sha256'}
    shape(receipt,fields,'INVALID_JURY_WORKSPACE_RECEIPT')
    need(receipt['schema']=='chronos.jury-workspace.v1' and receipt['status']=='FILES_PREPARED_NOT_INSTALLED'
         and receipt['mode']==('RECORDED_FIXTURE_SETUP_ONLY' if replay else 'LIVE_LOCAL_SETUP_ONLY')
         and receipt['root']==str(root) and receipt['deployment_id']==bindings['deployment_id']
         and receipt['origin']==bindings['origin'] and receipt['bundle_manifest_sha256']==bindings['manifest_sha256']
         and receipt['e1_profile_sha256']==bindings['profile_sha256'],'JURY_WORKSPACE_BINDING_CHANGED')
    need(receipt['installed'] is False and receipt['allowances_initialized'] is False
         and all(type(receipt[k]) is int and receipt[k]==0 for k in ('accounts_created','services_started','model_calls')),
         'INVALID_JURY_WORKSPACE_CLAIM')
    env=receipt['environment']
    expected=dict(CHRONOS_PROJECT='chronos-jury-'+bindings['deployment_id'][:12],CHRONOS_IMAGE=None,
        CHRONOS_DEPLOYMENT_ID=bindings['deployment_id'],CHRONOS_APP=str(stage/'app'),
        CHRONOS_DATA=str(stage/'data'),CHRONOS_GUARD_STATE=str(stage/'guard'),
        CHRONOS_WEB_PORT=str(bindings['web_port']),CHRONOS_CONVERSATION_STATE=str(root/'chat-state'),
        CHRONOS_CONVERSATION_CONTRACT='c2-v2')
    if replay:
        expected['CHRONOS_REPLAY_FIXTURES']=str(root/'fixtures')
        compose=['compose.yaml','compose.web-local.yaml','compose.replay.yaml'];profiles=['recorded-fixture']
    else:
        del expected['CHRONOS_DEPLOYMENT_ID']
        expected.update(CHRONOS_OLLAMA_IMAGE='ollama/ollama@sha256:93c1376d651a9f1579ee40cc5763852f08b204466371e4bb64bca2a1d8d08e2d',
            CHRONOS_MODELS=None,CHRONOS_MODEL_HOME=str(root/'model-home'),CHRONOS_MODEL_CPUS='4',
            CHRONOS_MODEL_MEMORY='4g',CHRONOS_GPU_DEVICE_ID='0')
        compose=['compose.yaml','compose.web-local.yaml','compose.local-model.yaml','compose.conversation.yaml','compose.local-gpu.yaml']
        profiles=['local-model','conversation']
    shape(env,expected,'INVALID_JURY_ENVIRONMENT')
    expected['CHRONOS_IMAGE']=env['CHRONOS_IMAGE']
    need(type(env['CHRONOS_IMAGE']) is str and re.fullmatch(r'sha256:[a-f0-9]{64}',env['CHRONOS_IMAGE']),'INVALID_JURY_IMAGE')
    if not replay:
        # The model cache is not mounted in IRIS. Bind the declared path without
        # opening its model files or starting a model service.
        expected['CHRONOS_MODELS']=str(local_path(env['CHRONOS_MODELS']))
    need(env==expected and receipt['compose_files']==compose and receipt['profiles']==profiles,'JURY_COMPOSE_BINDING_CHANGED')
    raw_e1=read(root/'profiles/e1.json');raw_c2=read(root/'profiles/c2.json')
    c2,c2_sha=profile_binding(raw_c2,conversation=True)
    need(raw_e1==read(stage/'profile.json') and c2_sha==receipt['c2_profile_sha256']
         and c2['deployment_id']==profile['deployment_id'] and c2['provider']==profile['provider']
         and c2['model']==profile['model'],'JURY_PROFILE_BINDING_CHANGED')
    chat=root/'chat-state';directories(chat);chat_info=plain(chat,directory=True)
    result=dict(mode='RECORDED_FIXTURE' if replay else 'LIVE',workspace_sha256=sha256(raw).hexdigest(),
        c2_profile_sha256=c2_sha,c2_profile_file_sha256=sha256(raw_c2).hexdigest(),
        chat_state=str(chat),chat_identity=[chat_info.st_dev,chat_info.st_ino],image=env['CHRONOS_IMAGE'],
        fixtures=None)
    if replay:
        fixtures=root/'fixtures';directories(fixtures)
        need({p.name for p in fixtures.iterdir()}=={'corpus.json','evidence-allowlist.json'},'RECORDED_FIXTURE_INVENTORY_CHANGED')
        corpus=read(fixtures/'corpus.json',2*1024*1024);allowlist=read(fixtures/'evidence-allowlist.json',65536)
        need(sha256(corpus).hexdigest()==receipt['replay_corpus_sha256']==profile['replay_corpus_sha256']==c2['replay_corpus_sha256']
             and receipt['replay_fixture_sha256']==profile['replay_fixture_sha256']==c2['replay_fixture_sha256']
             and hex64(receipt['replay_fixture_sha256']) and sha256(allowlist).hexdigest()==receipt['capture_allowlist_sha256'],
             'RECORDED_FIXTURE_BYTES_CHANGED')
        info=plain(fixtures,directory=True)
        result['fixtures']=dict(path=str(fixtures),identity=[info.st_dev,info.st_ino],
            corpus_sha256=receipt['replay_corpus_sha256'],bank_sha256=receipt['replay_fixture_sha256'],
            allowlist_sha256=receipt['capture_allowlist_sha256'])
    return result


def write_new(path,value):
    raw=canonical(value) if type(value) is not bytes else value
    with path.open('xb') as stream:
        stream.write(raw);stream.flush();os.fsync(stream.fileno())
    need(read(path,max(MAX_JSON,len(raw)))==raw,'EXCLUSIVE_WRITE_MISMATCH')
    return sha256(raw).hexdigest()


def instrumented_simulator(raw):
    try:text=raw.decode('utf-8')
    except UnicodeError:raise ChallengeError('SIMULATOR_SOURCE_ENCODING') from None
    need(text.count(ORIGINAL_SUBMIT)==1 and 'CRASH_LAB_CUT_NOT_OBSERVED' not in text,'UNRECOGNIZED_SIMULATOR_SOURCE')
    compile(HOOK_CODE,'chronos-exact-crash-hook','exec',dont_inherit=True)
    replacement=('    elif command=="SUBMIT":\n'
        '        _crash_scope={}\n'
        '        exec('+repr(HOOK_CODE)+',_crash_scope)\n'
        '        result=_crash_scope["submit"](runtime,root,args)')
    return text.replace(ORIGINAL_SUBMIT,replacement,1).encode('utf-8')


def instrument(bundle,expected_manifest,output,*,run=subprocess.run):
    """Create an explicit derived source and use its ordinary bundle builder.

    This is files-only. The original bundle is never modified. The derived
    installation must be created separately; this does not replace any running
    container mount or compile a class into an existing namespace.
    """
    bundle=local_path(bundle);output=local_path(output);directories(output.parent)
    need(not os.path.lexists(output),'OUTPUT_ALREADY_EXISTS')
    need(not output.is_relative_to(bundle) and not bundle.is_relative_to(output),'OUTPUT_OVERLAPS_SOURCE')
    original=verify_bundle(bundle,expected_manifest)
    source_bytes={name:read(bundle/name,MAX_FILE) for name in original['output_sha256']}
    index='src/chronos_web/index.html';api=original['api_base']
    need(type(api) is str and re.fullmatch(r'/csp/chronos(?:-[a-z0-9-]+)?/',api),'INVALID_API_BASE')
    marker=('<meta name="chronos-api-base" content="'+api+'">').encode('ascii')
    need(source_bytes[index].count(marker)==1,'INDEX_SOURCE_BINDING_MISMATCH')
    source_bytes[index]=source_bytes[index].replace(marker,b'<meta name="chronos-api-base" content="">',1)
    need(all(sha256(raw).hexdigest()==original['source_sha256'][name] for name,raw in source_bytes.items()),'BASE_SOURCE_BINDING_MISMATCH')
    before=source_bytes[SIMULATOR];after=instrumented_simulator(before)
    difference=''.join(difflib.unified_diff(before.decode().splitlines(True),after.decode().splitlines(True),
        fromfile='original/'+SIMULATOR,tofile='derived/'+SIMULATOR)).encode('utf-8')
    need(verify_bundle(bundle,expected_manifest)==original,'INSTRUMENT_INPUT_CHANGED')
    output.mkdir(exist_ok=False);source=output/'source';source.mkdir()
    try:
        for name,raw in source_bytes.items():
            path=source/name;path.parent.mkdir(parents=True,exist_ok=True)
            write_new(path,after if name==SIMULATOR else raw)
        write_new(output/'hook.py',HOOK_CODE.encode());os.chmod(output/'hook.py',stat.S_IRUSR|stat.S_IRGRP|stat.S_IROTH)
        write_new(output/'simulator.patch',difference)
        # Invoke only the ordinary builder from the pinned derived source.
        process=run([sys.executable,'-B',str(source/'tools/application_bundle.py'),'build','--source-root',str(source),
            '--output',str(output/'bundle'),'--api-base',api],capture_output=True,text=True,encoding='utf-8',timeout=60,check=False)
        need(process.returncode==0,'DERIVED_BUNDLE_BUILD_FAILED')
        raw_manifest=read(output/'bundle/bundle-manifest.json');derived_sha=sha256(raw_manifest).hexdigest()
        derived=verify_bundle(output/'bundle',derived_sha)
        expected_source=dict(original['source_sha256']);expected_source[SIMULATOR]=sha256(after).hexdigest()
        need(derived['source_sha256']==expected_source and derived['api_base']==api,'DERIVED_SOURCE_SCOPE_CHANGED')
        need(verify_bundle(bundle,expected_manifest)==original,'ORIGINAL_BUNDLE_CHANGED')
        body=dict(schema=INSTRUMENT_SCHEMA,created_at=datetime.now(timezone.utc).isoformat(),
            original_bundle=str(bundle),derived_source=str(source),derived_bundle=str(output/'bundle'),
            base_manifest_sha256=expected_manifest,derived_manifest_sha256=derived_sha,
            base_source_sha256=original['source_sha256'],derived_source_sha256=derived['source_sha256'],
            changed_files=[SIMULATOR],hook_sha256=sha256(HOOK_CODE.encode()).hexdigest(),diff_sha256=sha256(difference).hexdigest(),
            boundary=BOUNDARY,required_iris_build='2026.3.0AI.154.0',test_only=True,
            native_tested=False,accounts_changed=0,services_started=0,ready=False)
        result=body|{'instrumentation_sha256':digest(body)}
        write_new(output/'instrumentation.json',result)
        return result
    except (OSError,ValueError,subprocess.SubprocessError):raise ChallengeError('INSTRUMENT_PARTIAL_PRESERVED') from None


def check_instrumentation(path,expected_sha256,bindings):
    path=local_path(path);record=parse(read(path))
    fields='schema created_at original_bundle derived_source derived_bundle base_manifest_sha256 derived_manifest_sha256 base_source_sha256 derived_source_sha256 changed_files hook_sha256 diff_sha256 boundary required_iris_build test_only native_tested accounts_changed services_started ready instrumentation_sha256'.split()
    shape(record,fields,'INVALID_INSTRUMENTATION_RECEIPT')
    need(hex64(expected_sha256) and record['instrumentation_sha256']==expected_sha256
         and digest({k:v for k,v in record.items() if k!='instrumentation_sha256'})==expected_sha256,'INSTRUMENTATION_DIGEST_MISMATCH')
    need(record['schema']==INSTRUMENT_SCHEMA and record['boundary']==BOUNDARY
         and record['required_iris_build']=='2026.3.0AI.154.0' and record['changed_files']==[SIMULATOR]
         and record['test_only'] is True and record['native_tested'] is False and record['ready'] is False
         and type(record['accounts_changed']) is int and record['accounts_changed']==0
         and type(record['services_started']) is int and record['services_started']==0,'INVALID_INSTRUMENTATION_CLAIM')
    timestamp(record['created_at'])
    original=verify_bundle(local_path(record['original_bundle']),record['base_manifest_sha256'])
    derived=verify_bundle(local_path(record['derived_bundle']),record['derived_manifest_sha256'])
    need(bindings['manifest_sha256']==record['derived_manifest_sha256']
         and original['source_sha256']==record['base_source_sha256'] and derived['source_sha256']==record['derived_source_sha256']
         and set(original['source_sha256'])==set(derived['source_sha256']),'INSTRUMENTED_STAGE_REQUIRED')
    changed={k for k in original['source_sha256'] if original['source_sha256'][k]!=derived['source_sha256'][k]}
    need(changed=={SIMULATOR},'INSTRUMENTATION_SOURCE_SCOPE_CHANGED')
    before=read(Path(record['original_bundle'])/SIMULATOR,MAX_FILE)
    need(read(Path(record['derived_bundle'])/SIMULATOR,MAX_FILE)==instrumented_simulator(before),'INSTRUMENTATION_SOURCE_SCOPE_CHANGED')
    hook=path.parent/'hook.py';info=plain(hook)
    need(not info.st_mode&stat.S_IWUSR and read(hook)==HOOK_CODE.encode()
         and record['hook_sha256']==sha256(HOOK_CODE.encode()).hexdigest(),'READONLY_HOOK_CHANGED')
    need(sha256(read(path.parent/'simulator.patch',MAX_FILE)).hexdigest()==record['diff_sha256'],'INSTRUMENTATION_DIFF_CHANGED')
    return record


def stage_binding(stage,expected_manifest):
    directories(stage)
    receipt_raw=read(stage/'stage-receipt.json');receipt=parse(receipt_raw)
    fields='schema_version status root staging_id created_at bundle_manifest_sha256 profile_sha256 profile_file_sha256 config_file_sha256 data_identity guard_identity allowance_initialized account_changes native_calls model_calls'.split()
    shape(receipt,fields,'INVALID_STAGE_RECEIPT')
    need(receipt['schema_version']=='chronos.install-stage.v3' and receipt['status']=='STAGED_FILES_ONLY_NOT_INSTALLED'
         and Path(receipt['root'])==stage and receipt['bundle_manifest_sha256']==expected_manifest,'STAGE_BINDING_CHANGED')
    need(type(receipt['staging_id']) is str and re.fullmatch(r'[a-f0-9]{32}',receipt['staging_id']),'INVALID_STAGE_RECEIPT')
    timestamp(receipt['created_at'])
    need(receipt['allowance_initialized'] is False and all(type(receipt[k]) is int and receipt[k]==0
         for k in ('account_changes','native_calls','model_calls')),'UNSUPPORTED_STAGE_CLAIM')
    for name,field in (('data','data_identity'),('guard','guard_identity')):
        path=stage/name;directories(path);info=plain(path,directory=True)
        need(receipt[field]==[info.st_dev,info.st_ino],'STAGE_DIRECTORY_REPLACED')
    config_raw=read(stage/'config.json');profile_raw=read(stage/'profile.json')
    need(sha256(config_raw).hexdigest()==receipt['config_file_sha256']
         and sha256(profile_raw).hexdigest()==receipt['profile_file_sha256'],'STAGE_INPUT_BYTES_CHANGED')
    config=parse(config_raw)
    shape(config,'version deployment_id host_bundle host_data_root host_guard_state web_origin native_guard_base_url'.split(),'INVALID_STAGE_CONFIG')
    need(type(config['version']) is int and config['version']==3 and Path(config['host_bundle'])==stage/'app'
         and Path(config['host_data_root'])==stage/'data' and Path(config['host_guard_state'])==stage/'guard'
         and config['native_guard_base_url']=='http://127.0.0.1:11512/v1/','STAGE_PATH_BINDING_CHANGED')
    profile,profile_sha=profile_binding(profile_raw)
    need(config['deployment_id']==profile['deployment_id'] and profile_sha==receipt['profile_sha256'],'STAGE_PROFILE_CHANGED')
    manifest=verify_bundle(stage/'app',expected_manifest)
    port=origin_port(config['web_origin'])
    bindings=dict(stage=str(stage),deployment_id=profile['deployment_id'],profile_sha256=profile_sha,
        manifest_sha256=expected_manifest,stage_receipt_sha256=sha256(receipt_raw).hexdigest(),
        config_sha256=sha256(config_raw).hexdigest(),profile_file_sha256=sha256(profile_raw).hexdigest(),
        origin=config['web_origin'],web_port=port,engine_build=manifest['required_iris_build'])
    bindings['runtime']=runtime_binding(stage,bindings,profile)
    return bindings


def owner_snapshot(snapshot,stage,bindings,container_id,image,*,live_paths=True):
    shape(snapshot,{'schema','captured_at','container'},'INVALID_OWNER_SNAPSHOT')
    need(snapshot['schema']==SNAPSHOT_SCHEMA,'INVALID_OWNER_SNAPSHOT');timestamp(snapshot['captured_at'])
    row=snapshot['container']
    shape(row,{'id','image','project','service','state','host','mounts'},'INVALID_OWNER_SNAPSHOT')
    need(type(container_id) is str and HEX.fullmatch(container_id) and row['id']==container_id,'FOREIGN_CONTAINER_ID')
    need(type(image) is str and re.fullmatch(r'sha256:[a-f0-9]{64}',image) and row['image']==image,'FOREIGN_IMAGE')
    project='chronos-jury-'+bindings['deployment_id'][:12]
    need(row['project']==project and row['service']=='iris','FOREIGN_PROJECT_OR_SERVICE')
    state=row['state'];shape(state,{'running','oom_killed','started_at'},'INVALID_OWNER_SNAPSHOT')
    need(state['running'] is True and state['oom_killed'] is False,'OWNER_NOT_RUNNING_CLEANLY')
    need(timestamp(state['started_at'])<=timestamp(snapshot['captured_at']),'INVALID_OWNER_TIME')
    host=row['host'];shape(host,{'privileged','memory_bytes','network_mode','port_bindings'},'INVALID_OWNER_SNAPSHOT')
    need(host['privileged'] is False and type(host['memory_bytes']) is int and host['memory_bytes']==4*2**30,'UNSAFE_CONTAINER_LIMITS')
    need(host['network_mode']==project+'_default','FOREIGN_NETWORK_SCOPE')
    ports=host['port_bindings'];shape(ports,{'52773/tcp'},'FOREIGN_PORT_SCOPE')
    need(type(ports['52773/tcp']) is list and len(ports['52773/tcp'])==1,'FOREIGN_PORT_SCOPE')
    binding=ports['52773/tcp'][0];shape(binding,{'HostIp','HostPort'},'FOREIGN_PORT_SCOPE')
    need(binding['HostIp']=='127.0.0.1' and binding['HostPort']==str(bindings['web_port']),'FOREIGN_PORT_SCOPE')
    expected={'/durable':(stage/'data',True),'/opt/chronos/bundle':(stage/'app',False),
        '/opt/chronos/src':(stage/'app/src',False),'/opt/chronos/deployment':(stage/'app/deployment',False),
        '/opt/chronos/tools':(stage/'app/tools',False),'/opt/chronos/runtime':(stage/'guard',True)}
    runtime=bindings['runtime']
    if runtime is not None:
        need(image==runtime['image'],'FOREIGN_IMAGE')
        expected['/opt/chronos/conversation-runtime']=(Path(runtime['chat_state']),True)
        if runtime['fixtures'] is not None:expected['/opt/chronos/fixtures']=(Path(runtime['fixtures']['path']),False)
    mounts=row['mounts'];need(type(mounts) is list and len(mounts)==len(expected),'FOREIGN_MOUNT_SCOPE')
    seen=set();normalized=[]
    for item in mounts:
        shape(item,{'type','source','destination','read_write'},'INVALID_OWNER_SNAPSHOT')
        destination=item['destination']
        need(type(destination) is str and destination in expected and destination not in seen,'FOREIGN_MOUNT_SCOPE')
        seen.add(destination);path,rw=expected[destination]
        need(item['type']=='bind' and item['read_write'] is rw,'FOREIGN_MOUNT_SCOPE')
        need(same_directory(item['source'],path) if live_paths else item['source']==str(path),'FOREIGN_MOUNT_SCOPE')
        normalized.append(dict(type='bind',source=str(path),destination=destination,read_write=rw))
    # Retain the caller's raw snapshot separately in source_snapshot_sha256.
    # The ownership projection normalizes only a path proved to identify the
    # exact expected directory; it does not equate names with casefold.
    projected={**snapshot,'container':{**row,'mounts':normalized}}
    return dict(container_id=container_id,image=image,project=project,service='iris',started_at=state['started_at'],
                snapshot_sha256=digest(projected),snapshot_captured_at=snapshot['captured_at'],mounts=normalized,
                network_mode=host['network_mode'],port_bindings=ports,memory_bytes=host['memory_bytes'])


def plan(stage,snapshot_path,expected_manifest,container_id,image,output,*,instrumentation_path=None,instrumentation_sha256=None):
    stage=local_path(stage);snapshot_path=local_path(snapshot_path);output=local_path(output)
    directories(output.parent)
    need(not os.path.lexists(output),'OUTPUT_ALREADY_EXISTS')
    need(output!=stage.parent and not output.is_relative_to(stage.parent) and not stage.parent.is_relative_to(output),'OUTPUT_OVERLAPS_WORKSPACE')
    bindings=stage_binding(stage,expected_manifest)
    raw=read(snapshot_path);snapshot=parse(raw)
    owner=owner_snapshot(snapshot,stage,bindings,container_id,image)
    instrumentation=None
    if instrumentation_path is not None:
        instrument_path=local_path(instrumentation_path)
        proof=check_instrumentation(instrument_path,instrumentation_sha256,bindings)
        instrumentation=dict(receipt_path=str(instrument_path),sha256=instrumentation_sha256,
            base_manifest_sha256=proof['base_manifest_sha256'],derived_manifest_sha256=proof['derived_manifest_sha256'],hook_sha256=proof['hook_sha256'])
    else:need(instrumentation_sha256 is None,'INSTRUMENTATION_PATH_REQUIRED')
    body=dict(schema=PLAN_SCHEMA,status='OFFLINE_PLAN_ONLY_NATIVE_EXECUTION_UNVALIDATED',run_id=uuid4().hex,
        created_at=datetime.now(timezone.utc).isoformat(),bindings=bindings,owner=owner,instrumentation=instrumentation,
        expected_effect=dict(order_id='jury-'+bindings['deployment_id']+'-queue_inventory',shipment_version=1,target='B',max_submit_calls=1,max_accepted_effects=1),
        boundary=BOUNDARY,execution_supported=False,ready=False,accounts_changed=0,services_started=0,
        source_snapshot_sha256=sha256(raw).hexdigest(),unimplemented_actions=[])
    record=body|{'plan_sha256':digest(body)}
    need(timestamp(owner['snapshot_captured_at'])<=timestamp(body['created_at']),'PLAN_PRECEDES_OWNER_SNAPSHOT')
    # Recheck immutable input observations before reserving the output directory.
    need(stage_binding(stage,expected_manifest)==bindings and read(snapshot_path)==raw,'PLAN_INPUT_CHANGED')
    output.mkdir(exist_ok=False)
    try:
        with (output/PLAN_NAME).open('xb') as stream:
            stream.write(canonical(record));stream.flush();os.fsync(stream.fileno())
        need(parse(read(output/PLAN_NAME))==record,'PLAN_WRITE_MISMATCH')
    except (OSError,ValueError):raise ChallengeError('PLAN_PARTIAL_PRESERVED') from None
    return record


def verify_plan(record,expected_sha256):
    fields='schema status run_id created_at bindings owner instrumentation expected_effect boundary execution_supported ready accounts_changed services_started source_snapshot_sha256 unimplemented_actions plan_sha256'.split()
    shape(record,fields,'INVALID_PLAN')
    need(hex64(expected_sha256) and record['plan_sha256']==expected_sha256
         and digest({k:v for k,v in record.items() if k!='plan_sha256'})==expected_sha256,'PLAN_DIGEST_MISMATCH')
    need(record['schema']==PLAN_SCHEMA and record['status']=='OFFLINE_PLAN_ONLY_NATIVE_EXECUTION_UNVALIDATED'
         and record['boundary']==BOUNDARY and record['execution_supported'] is False and record['ready'] is False
         and record['accounts_changed']==0 and type(record['accounts_changed']) is int
         and record['services_started']==0 and type(record['services_started']) is int
         and record['unimplemented_actions']==[],'INVALID_PLAN_CLAIM')
    need(type(record['run_id']) is str and re.fullmatch(r'[a-f0-9]{32}',record['run_id']),'INVALID_PLAN')
    timestamp(record['created_at'])
    bindings=record['bindings']
    shape(bindings,'stage deployment_id profile_sha256 manifest_sha256 stage_receipt_sha256 config_sha256 profile_file_sha256 origin web_port engine_build runtime'.split(),'INVALID_PLAN_BINDINGS')
    ident=bindings['deployment_id']
    need(type(ident) is str and re.fullmatch(r'[a-f0-9]{32}',ident)
         and type(bindings['stage']) is str and bool(bindings['stage'])
         and all(hex64(bindings[k]) for k in ('profile_sha256','manifest_sha256','stage_receipt_sha256','config_sha256','profile_file_sha256'))
         and bindings['engine_build']=='2026.3.0AI.154.0'
         and type(bindings['web_port']) is int and bindings['web_port']==origin_port(bindings['origin']),'INVALID_PLAN_BINDINGS')
    runtime=bindings['runtime']
    if runtime is not None:
        shape(runtime,'mode workspace_sha256 c2_profile_sha256 c2_profile_file_sha256 chat_state chat_identity image fixtures'.split(),'INVALID_RUNTIME_BINDING')
        need(runtime['mode'] in ('LIVE','RECORDED_FIXTURE')
             and all(hex64(runtime[k]) for k in ('workspace_sha256','c2_profile_sha256','c2_profile_file_sha256'))
             and runtime['chat_state']==str(Path(bindings['stage']).parent/'chat-state')
             and type(runtime['image']) is str and re.fullmatch(r'sha256:[a-f0-9]{64}',runtime['image'])
             and type(runtime['chat_identity']) is list and len(runtime['chat_identity'])==2
             and all(integer(v) for v in runtime['chat_identity']),'INVALID_RUNTIME_BINDING')
        fixtures=runtime['fixtures']
        if runtime['mode']=='LIVE':need(fixtures is None,'INVALID_RUNTIME_BINDING')
        else:
            shape(fixtures,{'path','identity','corpus_sha256','bank_sha256','allowlist_sha256'},'INVALID_FIXTURE_BINDING')
            need(fixtures['path']==str(Path(bindings['stage']).parent/'fixtures')
                 and type(fixtures['identity']) is list and len(fixtures['identity'])==2 and all(integer(v) for v in fixtures['identity'])
                 and all(hex64(fixtures[k]) for k in ('corpus_sha256','bank_sha256','allowlist_sha256')),'INVALID_FIXTURE_BINDING')
    owner=record['owner']
    shape(owner,'container_id image project service started_at snapshot_sha256 snapshot_captured_at mounts network_mode port_bindings memory_bytes'.split(),'INVALID_PLAN_OWNER')
    snapshot={'schema':SNAPSHOT_SCHEMA,'captured_at':owner['snapshot_captured_at'],'container':{
        'id':owner['container_id'],'image':owner['image'],'project':owner['project'],'service':owner['service'],
        'state':{'running':True,'oom_killed':False,'started_at':owner['started_at']},
        'host':{'privileged':False,'memory_bytes':owner['memory_bytes'],'network_mode':owner['network_mode'],'port_bindings':owner['port_bindings']},
        'mounts':owner['mounts']}}
    need(owner_snapshot(snapshot,Path(bindings['stage']),bindings,owner['container_id'],owner['image'],live_paths=False)==owner,'INVALID_PLAN_OWNER')
    need(timestamp(owner['snapshot_captured_at'])<=timestamp(record['created_at']),'PLAN_PRECEDES_OWNER_SNAPSHOT')
    instrument=record['instrumentation']
    if instrument is not None:
        shape(instrument,{'receipt_path','sha256','base_manifest_sha256','derived_manifest_sha256','hook_sha256'},'INVALID_PLAN_INSTRUMENTATION')
        need(type(instrument['receipt_path']) is str and bool(instrument['receipt_path'])
             and all(hex64(instrument[k]) for k in ('sha256','base_manifest_sha256','derived_manifest_sha256','hook_sha256'))
             and instrument['derived_manifest_sha256']==bindings['manifest_sha256']
             and instrument['base_manifest_sha256']!=instrument['derived_manifest_sha256'],'INVALID_PLAN_INSTRUMENTATION')
    expected=dict(order_id='jury-'+ident+'-queue_inventory',shipment_version=1,target='B',max_submit_calls=1,max_accepted_effects=1)
    need(canonical(record['expected_effect'])==canonical(expected) and hex64(record['source_snapshot_sha256']),'INVALID_PLAN_EFFECT_SCOPE')
    return record


def same_destination_after_acceptance(before,current):
    """Only terminal simulated delivery may advance; retain raw observations."""
    if type(before) is not dict or type(current) is not dict or set(before)!=set(current):return False
    if type(before.get('state')) is not str or type(current.get('state')) is not str:return False
    if before.get('state') not in {'ACCEPTED','DELIVERED_SIMULATED'}:return False
    permitted={before['state']}|({'DELIVERED_SIMULATED'} if before['state']=='ACCEPTED' else set())
    return current.get('state') in permitted and all(type(current[key]) is type(before[key])
        and current[key]==before[key] for key in before if key!='state')


def verify_records(records,plan_record,*,expected_plan_sha256,allow_synthetic=False):
    plan_record=verify_plan(plan_record,expected_plan_sha256)
    fields='schema evidence_kind captured_at plan_sha256 instrumentation before_cut cut after_restart resume recovered_operation operator_readback destination_final'.split()
    shape(records,fields,'INVALID_OBSERVATION_PACKET')
    need(records['schema']==OBSERVATION_SCHEMA and records['plan_sha256']==expected_plan_sha256,'OBSERVATION_PLAN_MISMATCH')
    need(type(allow_synthetic) is bool and (records['evidence_kind']=='OBSERVED_NATIVE_RUN'
         or allow_synthetic and records['evidence_kind']=='SYNTHETIC_TEST_ONLY'),'SYNTHETIC_OR_UNKNOWN_OBSERVATIONS')
    tool=records['instrumentation'];shape(tool,{'base_manifest_sha256','instrumented_manifest_sha256','hook_sha256','boundary','test_only'},'INVALID_INSTRUMENTATION')
    bound=plan_record['instrumentation']
    if bound is not None:
        need(tool['base_manifest_sha256']==bound['base_manifest_sha256']
             and tool['instrumented_manifest_sha256']==bound['derived_manifest_sha256'] and tool['hook_sha256']==bound['hook_sha256'],'INSTRUMENTATION_BINDING_MISMATCH')
    else:
        need(records['evidence_kind']=='SYNTHETIC_TEST_ONLY' and allow_synthetic is True
             and tool['base_manifest_sha256']==plan_record['bindings']['manifest_sha256'],'INSTRUMENTED_PLAN_REQUIRED')
    need(hex64(tool['base_manifest_sha256'])
         and hex64(tool['instrumented_manifest_sha256']) and tool['instrumented_manifest_sha256']!=tool['base_manifest_sha256']
         and hex64(tool['hook_sha256']) and tool['boundary']==BOUNDARY and tool['test_only'] is True,'INSTRUMENTATION_BINDING_MISMATCH')
    before=records['before_cut'];shape(before,{'iris','destination','barrier'},'INVALID_BEFORE_CUT')
    barrier=before['barrier'];shape(barrier,{'operationId','attemptId','admissionId','armed_at','started_at','wait_seconds','receipt'},'INVALID_BARRIER')
    ids={k:barrier[k] for k in ('operationId','attemptId','admissionId')}
    need(all(type(v) is str and IDENTIFIER.fullmatch(v) for v in ids.values()),'INVALID_OPERATION_IDENTIFIERS')
    need(integer(barrier['wait_seconds'],1,120),'INVALID_BARRIER_WINDOW')
    cut=records['cut'];shape(cut,{'container_id','image','started_at','finished_at','running','exit_code','oom_killed'},'INVALID_CUT_RECORD')
    owner=plan_record['owner']
    need(cut['container_id']==owner['container_id'] and cut['image']==owner['image'] and cut['started_at']==owner['started_at'],'FOREIGN_CUT_CONTAINER')
    need(cut['running'] is False and type(cut['exit_code']) is int and cut['exit_code']==137 and cut['oom_killed'] is False,'NOT_AN_INTENTIONAL_ENGINE_CUT')
    delay=(timestamp(cut['finished_at'])-timestamp(barrier['started_at'])).total_seconds()
    need(timestamp(owner['started_at'])<=timestamp(owner['snapshot_captured_at'])<=timestamp(plan_record['created_at'])
         <=timestamp(barrier['armed_at'])<=timestamp(barrier['started_at']),'INVALID_CUT_CHRONOLOGY')
    need(0<=delay<barrier['wait_seconds'],'CUT_OUTSIDE_BARRIER')
    restart=records['after_restart'];shape(restart,{'container_id','started_at','operation','inspection'},'INVALID_RESTART_RECORD')
    need(restart['container_id']==owner['container_id'] and timestamp(restart['started_at'])>timestamp(cut['finished_at']),'ENGINE_RESTART_NOT_ESTABLISHED')
    need(timestamp(restart['started_at'])<=timestamp(records['captured_at']),'OBSERVATIONS_PRECEDE_ENGINE_RESTART')
    expected=plan_record['expected_effect'];target=expected['target']
    for row in (before['iris'],restart['operation']):
        shape(row,{'operationId','attemptId','admissionId','orderId','shipmentVersion','target','state','reference'},'INVALID_PENDING_OPERATION')
        need(all(row[k]==v for k,v in ids.items()) and row['orderId']==expected['order_id']
             and type(row['shipmentVersion']) is int and row['shipmentVersion']==expected['shipment_version']
             and row['target']==target and row['state']=='IN_FLIGHT' and row['reference']=='','RECEIPT_ALREADY_RECORDED_OR_IDENTITY_CHANGED')
    receipt=barrier['receipt'];shape(receipt,{'operationId','attemptId','orderId','shipmentVersion','target','status','reference','receiptId','closedForever'},'INVALID_BARRIER_RECEIPT')
    need(receipt['operationId']==ids['operationId'] and receipt['attemptId']==ids['attemptId']
         and receipt['orderId']==expected['order_id'] and type(receipt['shipmentVersion']) is int
         and receipt['shipmentVersion']==expected['shipment_version'] and receipt['target']==target and receipt['status']=='ACCEPTED' and receipt['closedForever'] is False
         and type(receipt['reference']) is str and IDENTIFIER.fullmatch(receipt['reference'])
         and type(receipt['receiptId']) is str and IDENTIFIER.fullmatch(receipt['receiptId']),'INVALID_ACCEPTED_RECEIPT')
    def accepted(row,*,allow_terminal_delivery=False):
        shape(row,{'operationId','attemptId','orderId','shipmentVersion','target','state','submits','attempts'},'INVALID_DESTINATION_RECORD')
        need(row['operationId']==ids['operationId'] and row['attemptId']==ids['attemptId']
             and row['orderId']==expected['order_id'] and type(row['shipmentVersion']) is int
             and row['shipmentVersion']==expected['shipment_version'] and row['target']==target and row['state'] in ({'ACCEPTED','DELIVERED_SIMULATED'} if allow_terminal_delivery else {'ACCEPTED'})
             and type(row['submits']) is int and row['submits']==1 and type(row['attempts']) is int and row['attempts']==1,'DESTINATION_EFFECT_MISMATCH')
    accepted(before['destination'])
    final=records['destination_final'];shape(final,{'accepted','raw_submit_calls','accepted_recovery_effects','scope'},'INVALID_FINAL_DESTINATION')
    accepted(final['accepted'],allow_terminal_delivery=True)
    need(same_destination_after_acceptance(before['destination'],final['accepted']),'DESTINATION_IDENTITY_OR_SUBMISSION_CHANGED')
    need(final['scope']=='ALL_RECOVERIES_FOR_OWNED_ORDER_EXCLUDING_ORIGINAL'
         and type(final['accepted_recovery_effects']) is int and final['accepted_recovery_effects']==1,'DUPLICATE_RECOVERY_EFFECT')
    need(type(final['raw_submit_calls']) is list and len(final['raw_submit_calls'])==1,'DUPLICATE_SUBMIT_CALL')
    shape(final['raw_submit_calls'][0],ids,'INVALID_SUBMIT_CALL')
    need(final['raw_submit_calls'][0]==ids,'SUBMIT_CALL_IDENTITY_CHANGED')
    recovered=records['recovered_operation'];shape(recovered,{'operationId','attemptId','admissionId','orderId','shipmentVersion','target','state','reference','lastReceiptId'},'INVALID_RECOVERED_OPERATION')
    need(all(recovered[k]==v for k,v in ids.items()) and recovered['orderId']==expected['order_id']
         and type(recovered['shipmentVersion']) is int and recovered['shipmentVersion']==expected['shipment_version']
         and recovered['target']==target and recovered['state']=='ACCEPTED'
         and recovered['reference']==receipt['reference'] and recovered['lastReceiptId']==receipt['receiptId'],'RECOVERED_RECEIPT_CHANGED')
    resume=records['resume'];shape(resume,{'status','request_id','previous_generation','current_generation','runtime_ready','recovery_phase','model_tested'},'INVALID_RESUME_RECORD')
    need(resume['status']=='RESUME_VERIFIED' and resume['recovery_phase']=='VERIFIED' and resume['runtime_ready'] is True
         and resume['model_tested'] is False and all(type(resume[k]) is str and IDENTIFIER.fullmatch(resume[k])
         for k in ('request_id','previous_generation','current_generation'))
         and resume['previous_generation']!=resume['current_generation'],'PRODUCTION_RECOVERY_NOT_ESTABLISHED')
    inspection=restart['inspection'];shape(inspection,{'status','current_generation','production_state'},'INVALID_RESTART_INSPECTION')
    need(inspection['status']=='CRASH_RECOVERY_AVAILABLE' and inspection['current_generation']==resume['previous_generation']
         and type(inspection['production_state']) is int and inspection['production_state']==4,'RECOVERY_GENERATION_BINDING_CHANGED')
    user=records['operator_readback'];shape(user,{'operationId','attemptId','state','reference','quarantined','dispatchGranted'},'INVALID_OPERATOR_READBACK')
    need(user['operationId']==ids['operationId'] and user['attemptId']==ids['attemptId'] and user['state']=='ACCEPTED'
         and user['reference']==receipt['reference'] and user['quarantined'] is False and user['dispatchGranted'] is False,'OPERATOR_READBACK_MISMATCH')
    return dict(status='PASS',scope='OFFLINE_RETAINED_RECORD_CONSISTENCY_ONLY',ready=False,native_run_reproduced=False,
        plan_sha256=expected_plan_sha256,evidence_kind=records['evidence_kind'],cut_seconds_after_barrier=delay,
        recorded_submit_calls=1,accepted_recovery_effects=1,operation_id=ids['operationId'],receipt_id=receipt['receiptId'])


INSPECT_TEMPLATE=('{{json .Id}}\n{{json .Image}}\n{{json (index .Config.Labels "com.docker.compose.project")}}\n'
    '{{json (index .Config.Labels "com.docker.compose.service")}}\n'
    '{{json .State.Running}}\n{{json .State.OOMKilled}}\n{{json .State.StartedAt}}\n'
    '{{json .State.FinishedAt}}\n{{json .State.ExitCode}}\n'
    '{{json .HostConfig.Privileged}}\n{{json .HostConfig.Memory}}\n{{json .HostConfig.NetworkMode}}\n'
    '{{json .HostConfig.PortBindings}}\n'
    '{{range .Mounts}}{{json .Type}}\t{{json .Source}}\t{{json .Destination}}\t{{json .RW}}\n{{end}}')


class Docker:
    """A local-only CLI adapter. Raw output/errors are never printed or saved."""
    evidence_kind='OBSERVED_NATIVE_RUN'
    def __init__(self,executable,*,run=subprocess.run,host=None):
        self.executable=local_path(executable);plain(self.executable)
        need(self.executable.name.lower() in ('docker','docker.exe'),'DOCKER_EXECUTABLE_REQUIRED')
        self.host=host or ('npipe:////./pipe/dockerDesktopLinuxEngine' if os.name=='nt' else 'unix:///var/run/docker.sock')
        need(self.host in ('npipe:////./pipe/dockerDesktopLinuxEngine','npipe:////./pipe/docker_engine','unix:///var/run/docker.sock'),'LOCAL_DOCKER_ENDPOINT_REQUIRED')
        self.run=run

    def call(self,args,*,input=None,timeout=30):
        env=dict(os.environ)
        for key in ('DOCKER_HOST','DOCKER_CONTEXT','DOCKER_TLS_VERIFY','DOCKER_CERT_PATH'):env.pop(key,None)
        try:process=self.run([str(self.executable),'--host',self.host,*args],input=input,
            capture_output=True,text=True,encoding='utf-8',timeout=timeout,env=env,check=False)
        except (OSError,subprocess.SubprocessError,UnicodeError):raise ChallengeError('DOCKER_CALL_OUTCOME_UNCERTAIN') from None
        need(process.returncode==0 and len(process.stdout.encode('utf-8'))<=MAX_JSON,'DOCKER_COMMAND_FAILED_STATE_PRESERVED')
        return process.stdout

    def inspect(self,cid):
        need(hex64(cid),'FULL_CONTAINER_ID_REQUIRED')
        raw=self.call(['inspect','--type','container','--format',INSPECT_TEMPLATE,cid])
        lines=raw.strip().splitlines();need(14<=len(lines)<=32,'DOCKER_INSPECTION_SHAPE')
        values=[parse(row.encode()) for row in lines[:13]];mounts=[]
        for line in lines[13:]:
            parts=line.split('\t');need(len(parts)==4,'DOCKER_INSPECTION_SHAPE')
            kind,source,destination,rw=[parse(v.encode()) for v in parts]
            mounts.append(dict(type=kind,source=source,destination=destination,read_write=rw))
        return dict(schema=SNAPSHOT_SCHEMA,captured_at=datetime.now(timezone.utc).isoformat(),container=dict(
            id=values[0],image=values[1],project=values[2],service=values[3],
            state=dict(running=values[4],oom_killed=values[5],started_at=values[6]),
            host=dict(privileged=values[9],memory_bytes=values[10],network_mode=values[11],port_bindings=values[12]),mounts=mounts)),dict(
                finished_at=values[7],exit_code=values[8])

    def script(self,cid,name,args=(),*,timeout=100):
        need(name in ('native_resume','native_health'),'UNRECOGNIZED_NATIVE_HELPER')
        text=self.call(['exec','--user','irisowner',cid,'/usr/bin/python3','-B',
            '/opt/chronos/deployment/'+name+'.py',*args],timeout=timeout)
        rows=[parse(line.encode()) for line in text.splitlines() if line.strip()]
        need(len(rows)==1 and type(rows[0]) is dict,'NATIVE_RESULT_SHAPE')
        return rows[0]

    def engine_health(self,cid,*,timeout=15):
        """Read a starting engine without treating its exact rc1 as mutation failure."""
        need(hex64(cid),'FULL_CONTAINER_ID_REQUIRED')
        need(type(timeout) is int and 1<=timeout<=15,'BOUNDED_ENGINE_HEALTH_READ_REQUIRED')
        env=dict(os.environ)
        for key in ('DOCKER_HOST','DOCKER_CONTEXT','DOCKER_TLS_VERIFY','DOCKER_CERT_PATH'):env.pop(key,None)
        try:
            p=self.run([str(self.executable),'--host',self.host,'exec','--user','irisowner',cid,
                '/usr/bin/python3','-B','/opt/chronos/deployment/native_health.py','engine'],
                capture_output=True,text=True,encoding='utf-8',env=env,timeout=timeout,check=False)
        except (OSError,subprocess.SubprocessError,UnicodeError):
            raise ChallengeError('ENGINE_HEALTH_READ_UNCERTAIN')from None
        need(p.returncode in (0,1)and not p.stderr.strip()and len(p.stdout.encode('utf-8'))<=16384,'ENGINE_HEALTH_TRANSPORT_REJECTED')
        value=parse(p.stdout.encode('utf-8'))
        shape(value,{'schema_version','scope','code','ready','provider_checked','model_calls'},'ENGINE_HEALTH_SHAPE_REJECTED')
        need(value['schema_version']=='chronos.health.v1'and value['scope']=='IRIS_ENGINE_ONLY'
             and value['provider_checked'] is False and type(value['model_calls']) is int and value['model_calls']==0,'ENGINE_HEALTH_BINDING_REJECTED')
        need((p.returncode==0 and value['ready'] is True and value['code']=='ENGINE_READY')
             or (p.returncode==1 and value['ready'] is False and value['code']=='ENGINE_NOT_RUNNING'),'ENGINE_HEALTH_STATE_REJECTED')
        return value

    def console_ready(self,cid,*,timeout=30,monotonic=time.monotonic,sleep=time.sleep):
        """Read-only startup barrier; only the exact startup refusal is retried."""
        need(hex64(cid),'FULL_CONTAINER_ID_REQUIRED')
        need(type(timeout) is int and 1<=timeout<=30,'BOUNDED_CONSOLE_STARTUP_WAIT_REQUIRED')
        marker='CHRONOS_CRASH_CONSOLE_READY:';refused='Sign-on inhibited: Startup or Installation in progress'
        until=monotonic()+timeout;env=dict(os.environ)
        for key in ('DOCKER_HOST','DOCKER_CONTEXT','DOCKER_TLS_VERIFY','DOCKER_CERT_PATH'):env.pop(key,None)
        while monotonic()<until:
            try:
                p=self.run([str(self.executable),'--host',self.host,'exec','-i','--user','irisowner',cid,
                    'iris','session','IRIS','-U','%SYS'],input='Write !,"'+marker+'",$ZVersion,! Halt\n',
                    capture_output=True,text=True,encoding='utf-8',env=env,timeout=min(4,max(.1,until-monotonic())),check=False)
            except (OSError,subprocess.SubprocessError,UnicodeError):
                raise ChallengeError('READONLY_CONSOLE_STARTUP_UNCERTAIN_NO_RETRY')from None
            need(len(p.stdout.encode('utf-8'))<=16384 and len(p.stderr.encode('utf-8'))<=16384,'CONSOLE_STARTUP_RESPONSE_LIMIT')
            rows=[line[len(marker):]for line in p.stdout.splitlines()if line.startswith(marker)]
            if p.returncode==0 and not p.stderr.strip()and len(rows)==1 and '2026.3.0AI (Build 154U)'in rows[0]and not re.search(r'<[^<>\r\n]{1,160}>|\bERROR\b|Sign-on inhibited',p.stdout):return
            need(p.returncode==239 and p.stdout.strip()==refused and not p.stderr.strip(),'READONLY_CONSOLE_STARTUP_OTHER_FAILURE_NO_RETRY')
            sleep(min(1,max(0,until-monotonic())))
        raise ChallengeError('READONLY_CONSOLE_STARTUP_NOT_READY_WITHIN_BOUND')

    def operation(self,plan_record,operation_id,*,pending):
        need(type(operation_id) is str and IDENTIFIER.fullmatch(operation_id),'INVALID_OPERATION_IDENTIFIERS')
        namespace='CHRONOS_'+plan_record['bindings']['deployment_id'][:12].upper();nonce=uuid4().hex
        source=('set sc=##class(Chronos.Authority.Store).Apply("READ_OPERATION",{"operationId":"'+operation_id+'"},.r)\n'
            'if $System.Status.IsOK(sc) write !,"CHRONOS_CRASH_'+nonce+':",r.operation.%ToJSON(),!\nhalt\n')
        text=self.call(['exec','-i','--user','irisowner',plan_record['owner']['container_id'],
            'iris','session','IRIS','-U',namespace],input=source,timeout=15)
        lines=[line[len('CHRONOS_CRASH_'+nonce+':'):] for line in text.splitlines() if line.startswith('CHRONOS_CRASH_'+nonce+':')]
        need(len(lines)==1,'NATIVE_OPERATION_READBACK_FAILED')
        row=parse(lines[0].encode());need(type(row) is dict,'NATIVE_OPERATION_READBACK_FAILED')
        fields='operationId attemptId admissionId orderId shipmentVersion target state reference'.split()
        if not pending:fields.append('lastReceiptId')
        need(set(fields)<=set(row),'NATIVE_OPERATION_READBACK_FAILED')
        return {key:row[key] for key in fields}


def native_args(plan_record):
    b=plan_record['bindings']
    return ['--deployment-id',b['deployment_id'],'--origin',b['origin'],'--application','/csp/chronos/',
        '--manifest-sha256',b['manifest_sha256'],'--profile-sha256',b['profile_sha256']]


def current_owner(docker,record,*,running,original_start=True):
    need(stage_binding(Path(record['bindings']['stage']),record['bindings']['manifest_sha256'])==record['bindings'],'LIVE_STAGE_BINDING_CHANGED')
    snapshot,exit_record=docker.inspect(record['owner']['container_id']);state=snapshot['container']['state']
    need(state['running'] is running and state['oom_killed'] is False,'ENGINE_STATE_CHANGED')
    if original_start:need(state['started_at']==record['owner']['started_at'],'ENGINE_GENERATION_CHANGED')
    checked={**snapshot,'container':{**snapshot['container'],'state':{**state,'running':True}}}
    owner_snapshot(checked,Path(record['bindings']['stage']),record['bindings'],record['owner']['container_id'],record['owner']['image'])
    return snapshot,exit_record


def challenge_paths(record):
    base=Path(record['bindings']['stage'])/'data'/'chronos'/record['bindings']['deployment_id']
    directories(base)
    return base/CONTROL


def phase_write(folder,name,value):
    folder=local_path(folder);directories(folder)
    need(name in ('arm-request.json','arm-result.json','cut-request.json','cut-result.json','recover-request.json',
         'recover-result.json','observations.json'),'UNRECOGNIZED_PHASE_FILE')
    write_new(folder/name,value)


def load_context(plan_path,expected_plan_sha256,instrumentation_path,expected_instrumentation_sha256):
    plan_path=local_path(plan_path);record=verify_plan(parse(read(plan_path)),expected_plan_sha256)
    bound=record['instrumentation']
    need(bound is not None and bound['receipt_path']==str(local_path(instrumentation_path))
         and bound['sha256']==expected_instrumentation_sha256,'INSTRUMENTED_PLAN_REQUIRED')
    tool=check_instrumentation(instrumentation_path,expected_instrumentation_sha256,record['bindings'])
    need(timestamp(tool['created_at'])<=timestamp(record['created_at']),'PLAN_PRECEDES_INSTRUMENTATION')
    need(parse(read(plan_path.parent/PLAN_NAME))==record,'PLAN_PATH_BINDING_CHANGED')
    return record,tool,plan_path.parent


ARM_PROGRAM='''import json,os,re,sys
from pathlib import Path
value=json.load(sys.stdin)
ident=value['deployment_id']
if not re.fullmatch('[a-f0-9]{32}',ident):raise ValueError('ID')
base=Path('/durable/chronos')/ident
for path in (*reversed(base.parents),base):
    if path.is_symlink() or not path.is_dir():raise ValueError('PATH')
control=base/'crash'
control.mkdir(mode=0o700,exist_ok=False)
with (control/'arm.json').open('x',encoding='utf-8') as stream:
    json.dump(value,stream,sort_keys=True,allow_nan=False);stream.flush();os.fsync(stream.fileno())
print(json.dumps({'status':'ARMED_ONCE','run_id':value['run_id']}))
'''


def arm(plan_path,plan_sha256,instrumentation_path,instrumentation_sha256,docker,*,authorize_id,seconds=180):
    record,tool,folder=load_context(plan_path,plan_sha256,instrumentation_path,instrumentation_sha256)
    ident=record['bindings']['deployment_id']
    need(authorize_id==ident and integer(seconds,30,300),'EXPLICIT_ARM_AUTHORIZATION_REQUIRED')
    current_owner(docker,record,running=True)
    native=docker.script(record['owner']['container_id'],'native_resume',['inspect',*native_args(record)])
    need(native.get('status')=='CURRENTLY_RUNNING' and native.get('runtime_ready') is True
         and native.get('profile_sha256')==record['bindings']['profile_sha256'],'NATIVE_RUNTIME_NOT_READY')
    control=challenge_paths(record);need(not os.path.lexists(control),'CHALLENGE_ALREADY_ARMED_OR_CONSUMED')
    now=datetime.now(timezone.utc)
    need(timestamp(record['created_at'])<=now,'PLAN_IS_FROM_FUTURE')
    value=dict(schema='chronos.crash-arm.v1',deployment_id=ident,order_id=record['expected_effect']['order_id'],
        shipment_version=1,target='B',run_id=record['run_id'],plan_sha256=plan_sha256,
        instrumentation_sha256=instrumentation_sha256,armed_at=now.isoformat(),expires_at=(now+timedelta(seconds=seconds)).isoformat(),wait_seconds=45)
    # Reserve first. If an invocation becomes uncertain, it is not repeated.
    phase_write(folder,'arm-request.json',value)
    current_owner(docker,record,running=True)
    raw=docker.call(['exec','-i','--user','irisowner',record['owner']['container_id'],
        '/usr/bin/python3','-B','-c',ARM_PROGRAM],input=canonical(value).decode(),timeout=15)
    observed=parse(raw.encode());need(observed=={'status':'ARMED_ONCE','run_id':record['run_id']},'ARM_RESULT_UNCERTAIN')
    need(parse(read(control/'arm.json'))==value,'ARM_READBACK_MISMATCH')
    result=dict(status='ARMED_ONCE_WAITING_FOR_HUMAN_UI_CONFIRMATION',run_id=record['run_id'],
        plan_sha256=plan_sha256,armed_at=value['armed_at'],expires_at=value['expires_at'],ready=False,approval_sent=False)
    phase_write(folder,'arm-result.json',result)
    return result


DESTINATION_READ_PROGRAM='''import json,os,re,sqlite3,stat,sys
from hashlib import sha256
from pathlib import Path

LIMIT=1024*1024
def need(ok):
    if not ok:raise ValueError("DESTINATION_READ_REJECTED")
def pairs(items):
    result={}
    for key,value in items:
        need(key not in result);result[key]=value
    return result
def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False).encode("utf-8")
def parse(value):
    need(type(value) is str and 0<len(value.encode("utf-8"))<=LIMIT)
    def constant(_):raise ValueError("DESTINATION_READ_REJECTED")
    result=json.loads(value,object_pairs_hook=pairs,parse_constant=constant)
    canonical(result)
    return result
def plain(path,directory=False):
    info=path.lstat()
    need(not stat.S_ISLNK(info.st_mode) and not getattr(info,"st_file_attributes",0)&0x400)
    need(stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode))
    return info
def directories(path):
    for part in (*reversed(path.parents),path):plain(part,directory=True)
def database(path):
    directories(path.parent);before=plain(path)
    db=sqlite3.connect(path.as_uri()+"?mode=ro",uri=True,timeout=2)
    try:
        db.execute("PRAGMA query_only=ON");now=plain(path)
        need((before.st_dev,before.st_ino)==(now.st_dev,now.st_ino))
        return db
    except Exception:
        db.close();raise
def main():
    raw=sys.stdin.read(LIMIT+1);args=parse(raw)
    need(type(args) is dict and set(args)=={"deployment_id","order_id","operation_id"})
    ident=args["deployment_id"];order=args["order_id"];operation_id=args["operation_id"]
    need(type(ident) is str and re.fullmatch("[a-f0-9]{32}",ident))
    need(order=="jury-"+ident+"-queue_inventory")
    need(type(operation_id) is str and re.fullmatch("[A-Za-z0-9_.:-]{1,128}",operation_id))
    root=Path("/durable/chronos")/ident/"owned-destinations"
    db=database(root/"registry.sqlite")
    try:rows=db.execute("SELECT definition FROM registrations WHERE order_id=?",(order,)).fetchmany(2)
    finally:db.close()
    need(len(rows)==1);definition=parse(rows[0][0])
    need(type(definition) is dict and type(definition.get("world")) is dict and definition["world"].get("order_id")==order)
    db=database(root/"orders"/sha256(canonical(definition)).hexdigest()/"provider.sqlite")
    try:
        result=[];accepted_effects=0
        for target,operation,binding,flow in db.execute("SELECT target,operation_id,binding,result FROM operations ORDER BY operation_id").fetchmany(17):
            b=parse(binding);f=parse(flow)
            need(type(b) is dict and type(f) is dict and b.get("order_id")==order and b.get("operation_id")==operation and b.get("target")==target)
            if operation==order+"-original":continue
            if f.get("state") in {"ACCEPTED","DELIVERED_SIMULATED"}:accepted_effects+=1
            attempts=db.execute("SELECT COUNT(*) FROM attempts WHERE target=? AND operation_id=?",(target,operation)).fetchone()[0]
            submits=db.execute("SELECT COUNT(*) FROM observations WHERE kind='SUBMIT' AND target=? AND operation_id=?",(target,operation)).fetchone()[0]
            result.append(dict(operationId=operation,attemptId=b.get("attempt_id"),orderId=order,shipmentVersion=b.get("shipment_version"),target=target,state=f.get("state"),submits=submits,attempts=attempts))
        need(len(result)==1 and result[0]["operationId"]==operation_id)
    finally:db.close()
    return dict(status="DESTINATION_READ_VERIFIED",accepted=result[0],accepted_effects=accepted_effects)
try:
    result=main()
except Exception:
    print('{"status":"DESTINATION_READ_REJECTED"}')
    sys.exit(1)
print(json.dumps(result,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False))
'''


def destination(record,ids,docker):
    # SQLite belongs to Linux: never open a live WAL database from the host.
    ident=record['bindings']['deployment_id'];order=record['expected_effect']['order_id']
    need(type(ident) is str and re.fullmatch(r'[a-f0-9]{32}',ident),'INVALID_DESTINATION_SCOPE')
    need(order=='jury-'+ident+'-queue_inventory','INVALID_DESTINATION_SCOPE')
    operation_id=ids.get('operationId')
    need(type(operation_id) is str and IDENTIFIER.fullmatch(operation_id),'INVALID_OPERATION_IDENTIFIERS')
    before,_=current_owner(docker,record,running=True,original_start=False)
    raw=docker.call(['exec','-i','--user','irisowner',record['owner']['container_id'],
        '/usr/bin/python3','-B','-c',DESTINATION_READ_PROGRAM],
        input=canonical(dict(deployment_id=ident,order_id=order,operation_id=operation_id)).decode(),timeout=15)
    after,_=current_owner(docker,record,running=True,original_start=False)
    need(before['container']['state']['started_at']==after['container']['state']['started_at'],
         'ENGINE_GENERATION_CHANGED_DURING_DESTINATION_READ')
    value=parse(raw.encode())
    shape(value,{'status','accepted','accepted_effects'},'DESTINATION_READBACK_SHAPE')
    need(value['status']=='DESTINATION_READ_VERIFIED','DESTINATION_READBACK_REJECTED')
    accepted=value['accepted']
    shape(accepted,'operationId attemptId orderId shipmentVersion target state submits attempts'.split(),'DESTINATION_READBACK_SHAPE')
    need(accepted['operationId']==operation_id and accepted['orderId']==order,'DESTINATION_OPERATION_SCOPE_CHANGED')
    need(integer(value['accepted_effects']) and integer(accepted['submits']) and integer(accepted['attempts']),
         'DESTINATION_READBACK_SHAPE')
    return accepted,value['accepted_effects']



def entered_barrier(control,record,arm_value):
    marker=parse(read(control/'committed-before-return.json'))
    shape(marker,{'operationId','attemptId','admissionId','armed_at','started_at','wait_seconds','receipt','run_id','plan_sha256'},'INVALID_BARRIER_MARKER')
    need(marker['run_id']==record['run_id'] and marker['plan_sha256']==record['plan_sha256']
         and marker['armed_at']==arm_value['armed_at'] and marker['wait_seconds']==45
         and timestamp(arm_value['armed_at'])<=timestamp(marker['started_at'])<timestamp(arm_value['expires_at']),'BARRIER_ARM_BINDING_CHANGED')
    ids={k:marker[k] for k in ('operationId','attemptId','admissionId')}
    need(all(type(v) is str and IDENTIFIER.fullmatch(v) for v in ids.values()),'INVALID_OPERATION_IDENTIFIERS')
    need(parse(read(control/'claim.json'))==ids|{'run_id':record['run_id'],'plan_sha256':record['plan_sha256']}
         and parse(read(control/'submit-call.json'))==ids,'EXCLUSIVE_SUBMIT_CLAIM_CHANGED')
    receipt=marker['receipt']
    shape(receipt,{'operationId','attemptId','orderId','shipmentVersion','target','status','reference','receiptId','closedForever'},'INVALID_BARRIER_RECEIPT')
    need(receipt['operationId']==ids['operationId'] and receipt['attemptId']==ids['attemptId']
         and receipt['orderId']==record['expected_effect']['order_id'] and type(receipt['shipmentVersion']) is int
         and receipt['shipmentVersion']==1 and receipt['target']=='B' and receipt['status']=='ACCEPTED'
         and receipt['closedForever'] is False
         and all(type(receipt[k]) is str and IDENTIFIER.fullmatch(receipt[k]) for k in ('reference','receiptId')),'INVALID_ACCEPTED_RECEIPT')
    return marker,ids


def watch_and_cut(plan_path,plan_sha256,instrumentation_path,instrumentation_sha256,docker,*,authorize_cut,
                  timeout=90,monotonic=time.monotonic,sleep=time.sleep):
    record,tool,folder=load_context(plan_path,plan_sha256,instrumentation_path,instrumentation_sha256)
    need(authorize_cut==record['run_id']+':'+record['owner']['container_id'],'EXPLICIT_EXACT_CUT_AUTHORIZATION_REQUIRED')
    need(integer(timeout,1,180),'INVALID_WATCH_TIMEOUT')
    need(not os.path.lexists(folder/'cut-request.json') and not os.path.lexists(folder/'cut-result.json'),'CUT_ALREADY_RESERVED_OR_COMPLETED')
    control=challenge_paths(record);arm_value=parse(read(folder/'arm-request.json'))
    need(parse(read(control/'arm.json'))==arm_value and arm_value['plan_sha256']==plan_sha256
         and arm_value['instrumentation_sha256']==instrumentation_sha256,'ARM_BINDING_CHANGED')
    deadline=monotonic()+timeout;marker_path=control/'committed-before-return.json'
    while not os.path.lexists(marker_path):
        need(monotonic()<deadline and datetime.now(timezone.utc)<timestamp(arm_value['expires_at']),'BARRIER_NOT_OBSERVED_NO_CUT')
        current_owner(docker,record,running=True);sleep(.1)
    marker,ids=entered_barrier(control,record,arm_value)
    before=docker.operation(record,ids['operationId'],pending=True)
    expected=record['expected_effect']
    need(before==ids|dict(orderId=expected['order_id'],shipmentVersion=1,target='B',state='IN_FLIGHT',reference=''),
         'RECEIPT_ALREADY_RECORDED_OR_IDENTITY_CHANGED')
    accepted,effects=destination(record,ids,docker)
    need(accepted==dict(operationId=ids['operationId'],attemptId=ids['attemptId'],orderId=expected['order_id'],
        shipmentVersion=1,target='B',state='ACCEPTED',submits=1,attempts=1) and effects==1,'DESTINATION_EFFECT_MISMATCH')
    # Re-observe ownership immediately before reserving the one cut. Nothing
    # starts a confirmation request: the ordinary browser approval did that.
    snapshot,_=current_owner(docker,record,running=True)
    elapsed=(datetime.now(timezone.utc)-timestamp(marker['started_at'])).total_seconds()
    need(0<=elapsed<marker['wait_seconds']-5,'CUT_WINDOW_EXPIRED_NO_CUT')
    barrier={k:marker[k] for k in ('operationId','attemptId','admissionId','armed_at','started_at','wait_seconds','receipt')}
    request=dict(schema='chronos.crash-cut.v1',plan_sha256=plan_sha256,run_id=record['run_id'],
        requested_at=datetime.now(timezone.utc).isoformat(),before_cut=dict(iris=before,destination=accepted,barrier=barrier),
        instrumentation=dict(base_manifest_sha256=tool['base_manifest_sha256'],
            instrumented_manifest_sha256=tool['derived_manifest_sha256'],hook_sha256=tool['hook_sha256'],boundary=BOUNDARY,test_only=True))
    phase_write(folder,'cut-request.json',request)
    need(docker.operation(record,ids['operationId'],pending=True)==before,'RECEIPT_CHANGED_BEFORE_CUT')
    # The native read above can block while an operator restarts this same CID.
    # Recheck its generation AFTER that read, immediately before the cut window
    # check and kill. The exclusive request remains spent if either check fails.
    current_owner(docker,record,running=True)
    elapsed=(datetime.now(timezone.utc)-timestamp(marker['started_at'])).total_seconds()
    need(0<=elapsed<marker['wait_seconds']-5,'CUT_WINDOW_EXPIRED_NO_CUT')
    # A failed or interrupted CLI result is uncertain; the reservation is kept
    # and this runner will never issue a second kill for the same plan.
    docker.call(['kill','--signal','KILL',record['owner']['container_id']],timeout=15)
    stopped,exit_info=current_owner(docker,record,running=False)
    state=stopped['container']['state']
    cut=dict(container_id=record['owner']['container_id'],image=record['owner']['image'],started_at=state['started_at'],
        finished_at=exit_info['finished_at'],running=False,exit_code=exit_info['exit_code'],oom_killed=state['oom_killed'])
    delay=(timestamp(cut['finished_at'])-timestamp(marker['started_at'])).total_seconds()
    need(cut['exit_code']==137 and type(cut['exit_code']) is int and 0<=delay<marker['wait_seconds'],'ENGINE_CUT_NOT_VERIFIED')
    result=dict(status='ENGINE_CUT_OBSERVED',plan_sha256=plan_sha256,run_id=record['run_id'],cut=cut,
        cut_seconds_after_barrier=delay,ready=False,approval_sent=False)
    phase_write(folder,'cut-result.json',result)
    return result


def recover(plan_path,plan_sha256,instrumentation_path,instrumentation_sha256,docker,*,authorize_recover,
            timeout=150,monotonic=time.monotonic,sleep=time.sleep,operator_readback=None):
    record,tool,folder=load_context(plan_path,plan_sha256,instrumentation_path,instrumentation_sha256)
    need(authorize_recover==record['run_id']+':'+record['owner']['container_id'],'EXPLICIT_EXACT_RECOVERY_AUTHORIZATION_REQUIRED')
    need(integer(timeout,30,180),'INVALID_RECOVERY_TIMEOUT')
    cut_request=parse(read(folder/'cut-request.json'));cut_result=parse(read(folder/'cut-result.json'))
    shape(cut_request,{'schema','plan_sha256','run_id','requested_at','before_cut','instrumentation'},'INVALID_CUT_REQUEST')
    shape(cut_result,{'status','plan_sha256','run_id','cut','cut_seconds_after_barrier','ready','approval_sent'},'INVALID_CUT_RESULT')
    need(cut_request.get('plan_sha256')==plan_sha256 and cut_result.get('plan_sha256')==plan_sha256
         and cut_request['run_id']==record['run_id'] and cut_request['schema']=='chronos.crash-cut.v1'
         and cut_result.get('status')=='ENGINE_CUT_OBSERVED' and cut_result.get('run_id')==record['run_id']
         and cut_result['ready'] is False and cut_result['approval_sent'] is False,'UNBOUND_CUT_RESULT')
    need(not os.path.lexists(folder/'recover-request.json'),'RECOVERY_ALREADY_RESERVED_USE_NATIVE_STATUS')
    stopped,exit_info=current_owner(docker,record,running=False)
    control=challenge_paths(record);arm_value=parse(read(folder/'arm-request.json'))
    need(parse(read(control/'arm.json'))==arm_value and arm_value['instrumentation_sha256']==instrumentation_sha256,'ARM_BINDING_CHANGED')
    marker,ids=entered_barrier(control,record,arm_value)
    expected_before=dict(iris=ids|dict(orderId=record['expected_effect']['order_id'],shipmentVersion=1,target='B',state='IN_FLIGHT',reference=''),
        destination=dict(operationId=ids['operationId'],attemptId=ids['attemptId'],orderId=record['expected_effect']['order_id'],
            shipmentVersion=1,target='B',state='ACCEPTED',submits=1,attempts=1),
        barrier={k:marker[k] for k in ('operationId','attemptId','admissionId','armed_at','started_at','wait_seconds','receipt')})
    need(cut_request['before_cut']==expected_before and cut_request['instrumentation']==dict(
        base_manifest_sha256=tool['base_manifest_sha256'],instrumented_manifest_sha256=tool['derived_manifest_sha256'],
        hook_sha256=tool['hook_sha256'],boundary=BOUNDARY,test_only=True),'CUT_REQUEST_OBSERVATIONS_CHANGED')
    expected_cut=dict(container_id=record['owner']['container_id'],image=record['owner']['image'],
        started_at=stopped['container']['state']['started_at'],finished_at=exit_info['finished_at'],
        running=False,exit_code=exit_info['exit_code'],oom_killed=False)
    need(cut_result['cut']==expected_cut and type(exit_info['exit_code']) is int and exit_info['exit_code']==137,'STOPPED_ENGINE_DIFFERS_FROM_CUT')
    delay=(timestamp(exit_info['finished_at'])-timestamp(marker['started_at'])).total_seconds()
    need(0<=delay<marker['wait_seconds'] and cut_result['cut_seconds_after_barrier']==delay
         and timestamp(record['created_at'])<=timestamp(marker['armed_at'])<=timestamp(marker['started_at'])
         <=timestamp(cut_request['requested_at'])<=timestamp(exit_info['finished_at']),'INVALID_CUT_CHRONOLOGY')
    request_id=uuid4().hex
    phase_write(folder,'recover-request.json',dict(plan_sha256=plan_sha256,run_id=record['run_id'],request_id=request_id,
        requested_at=datetime.now(timezone.utc).isoformat()))
    docker.call(['start',record['owner']['container_id']],timeout=60)
    until=monotonic()+timeout
    while True:
        snapshot,_=current_owner(docker,record,running=True,original_start=False)
        need(timestamp(snapshot['container']['state']['started_at'])>timestamp(cut_result['cut']['finished_at']),'ENGINE_RESTART_NOT_ESTABLISHED')
        health=docker.engine_health(record['owner']['container_id'],timeout=15)
        if health.get('ready') is True and health.get('code')=='ENGINE_READY':break
        need(monotonic()<until,'ENGINE_RESTART_HEALTH_UNVERIFIED');sleep(1)
    docker.console_ready(record['owner']['container_id'],timeout=30)
    pending=docker.operation(record,ids['operationId'],pending=True)
    need(pending==cut_request['before_cut']['iris'],'ADMISSION_CHANGED_ACROSS_ENGINE_RESTART')
    inspection=docker.script(record['owner']['container_id'],'native_resume',['inspect',*native_args(record)])
    need(inspection.get('status')=='CRASH_RECOVERY_AVAILABLE' and inspection.get('production_state')==4
         and inspection.get('profile_sha256')==record['bindings']['profile_sha256'],'NATIVE_CRASH_RECOVERY_NOT_AVAILABLE')
    generation=inspection.get('current_generation')
    need(type(generation) is str and IDENTIFIER.fullmatch(generation),'INVALID_RECOVERY_GENERATION')
    resumed=docker.script(record['owner']['container_id'],'native_resume',['recover',*native_args(record),
        '--request-id',request_id,'--expected-generation',generation,'--authorize-id',record['bindings']['deployment_id']],timeout=130)
    need(resumed.get('status')=='RESUME_VERIFIED' and resumed.get('request_id')==request_id
         and resumed.get('previous_generation')==generation and resumed.get('current_generation')!=generation
         and resumed.get('runtime_ready') is True and resumed.get('recovery_phase')=='VERIFIED'
         and resumed.get('model_tested') is False,'NATIVE_RECOVERY_OUTCOME_UNCERTAIN_USE_STATUS')
    final=docker.operation(record,ids['operationId'],pending=False)
    accepted,effects=destination(record,ids,docker)
    control=challenge_paths(record);marker,observed_ids=entered_barrier(control,record,parse(read(folder/'arm-request.json')))
    need(observed_ids==ids,'OPERATION_IDENTITY_CHANGED_AFTER_RESTART')
    receipt=marker['receipt'];expected=dict(cut_request['before_cut']['iris'],state='ACCEPTED',reference=receipt['reference'],lastReceiptId=receipt['receiptId'])
    need(final==expected and effects==1 and same_destination_after_acceptance(cut_request['before_cut']['destination'],accepted),'RECOVERY_RESULT_CHANGED')
    evidence=dict(schema=OBSERVATION_SCHEMA,evidence_kind=docker.evidence_kind,captured_at=datetime.now(timezone.utc).isoformat(),
        plan_sha256=plan_sha256,instrumentation=cut_request['instrumentation'],before_cut=cut_request['before_cut'],
        cut=cut_result['cut'],after_restart=dict(container_id=record['owner']['container_id'],
            started_at=snapshot['container']['state']['started_at'],operation=pending,
            inspection={k:inspection[k] for k in ('status','current_generation','production_state')}),
        resume={k:resumed[k] for k in ('status','request_id','previous_generation','current_generation','runtime_ready','recovery_phase','model_tested')},
        recovered_operation=final,destination_final=dict(accepted=accepted,raw_submit_calls=[parse(read(control/'submit-call.json'))],
            accepted_recovery_effects=effects,scope='ALL_RECOVERIES_FOR_OWNED_ORDER_EXCLUDING_ORIGINAL'))
    # Native authority readback does not impersonate the logged-in Operator.
    # A separate browser observation is required for the complete jury packet.
    result=dict(status='NATIVE_RECOVERY_VERIFIED_OPERATOR_READBACK_PENDING',plan_sha256=plan_sha256,
        run_id=record['run_id'],request_id=request_id,operation_id=ids['operationId'],ready=False,
        services_stopped=False,accounts_changed=0,approval_sent=False,native_recovery_observed=True)
    if operator_readback is not None:
        evidence['operator_readback']=parse(read(local_path(operator_readback)))
        verify_records(evidence,record,expected_plan_sha256=plan_sha256,allow_synthetic=docker.evidence_kind=='SYNTHETIC_TEST_ONLY')
        phase_write(folder,'observations.json',evidence)
        result['status']='ENGINE_RESTART_RECOVERY_AND_RETAINED_OPERATOR_READBACK_VERIFIED'
    else:
        # Preserve partial proof rather than fabricate the missing UI readback.
        result['native_observations']=evidence
    phase_write(folder,'recover-result.json',result)
    return result


def finalize(plan_path,plan_sha256,native_result,native_result_sha256,operator_readback,operator_readback_sha256,output):
    """Combine retained native proof and a later browser observation, offline.

    This never restarts or recovers again. Caller-supplied hashes pin both input
    artifacts; consistency verification does not authenticate a supplied UI file.
    """
    record=verify_plan(parse(read(local_path(plan_path))),plan_sha256)
    raw=read(local_path(native_result));ui=read(local_path(operator_readback))
    need(hex64(native_result_sha256) and sha256(raw).hexdigest()==native_result_sha256
         and hex64(operator_readback_sha256) and sha256(ui).hexdigest()==operator_readback_sha256,'FINALIZE_INPUT_DIGEST_MISMATCH')
    result=parse(raw)
    need(type(result) is dict and result.get('status')=='NATIVE_RECOVERY_VERIFIED_OPERATOR_READBACK_PENDING'
         and result.get('plan_sha256')==plan_sha256 and result.get('run_id')==record['run_id']
         and result.get('ready') is False and result.get('approval_sent') is False,'INVALID_RETAINED_RECOVERY_RESULT')
    evidence=result.get('native_observations');need(type(evidence) is dict,'RETAINED_NATIVE_PROOF_MISSING')
    need('operator_readback' not in evidence,'OPERATOR_READBACK_ALREADY_PRESENT')
    evidence={**evidence,'operator_readback':parse(ui),'captured_at':datetime.now(timezone.utc).isoformat()}
    checked=verify_records(evidence,record,expected_plan_sha256=plan_sha256)
    output=local_path(output);directories(output.parent)
    need(not os.path.lexists(output),'OUTPUT_ALREADY_EXISTS')
    need(output not in (local_path(plan_path),local_path(native_result),local_path(operator_readback)),'OUTPUT_OVERLAPS_INPUT')
    write_new(output,evidence)
    return dict(status='RETAINED_NATIVE_AND_OPERATOR_RECORDS_CONSISTENT',observations_sha256=sha256(read(output)).hexdigest(),
        plan_sha256=plan_sha256,ready=False,native_run_reproduced=False,scope=checked['scope'])


def main(argv=None):
    args_list=list(sys.argv[1:] if argv is None else argv)
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='action',required=True)
    create=sub.add_parser('plan')
    for field in ('stage','snapshot','manifest-sha256','container-id','image','output'):create.add_argument('--'+field,required=True)
    create.add_argument('--instrumentation');create.add_argument('--instrumentation-sha256')
    derive=sub.add_parser('instrument',help='Create new derived source and bundle only; no installation')
    for field in ('bundle','manifest-sha256','output'):derive.add_argument('--'+field,required=True)
    snapshot=sub.add_parser('snapshot',help='Inspect one owned lab; never starts or changes a container')
    for field in ('stage','manifest-sha256','container-id','image','output'):snapshot.add_argument('--'+field,required=True)
    snapshot.add_argument('--docker',required=True);snapshot.add_argument('--docker-host')
    for action in sorted(EXECUTION_COMMANDS):
        command=sub.add_parser(action)
        for field in ('plan','plan-sha256','instrumentation','instrumentation-sha256','docker'):command.add_argument('--'+field,required=True)
        command.add_argument('--docker-host')
        if action=='arm':command.add_argument('--authorize-id',required=True);command.add_argument('--seconds',type=int,default=180)
        elif action=='watch-and-cut':command.add_argument('--authorize-cut',required=True);command.add_argument('--timeout',type=int,default=90)
        else:
            command.add_argument('--authorize-recover',required=True);command.add_argument('--timeout',type=int,default=150)
            command.add_argument('--operator-readback')
    check=sub.add_parser('verify')
    for field in ('plan','plan-sha256','observations','observations-sha256'):check.add_argument('--'+field,required=True)
    finish=sub.add_parser('finalize',help='Combine later browser readback without repeating a recovery')
    for field in ('plan','plan-sha256','native-result','native-result-sha256','operator-readback','operator-readback-sha256','output'):
        finish.add_argument('--'+field,required=True)
    args=parser.parse_args(args_list)
    try:
        if args.action=='plan':result=plan(args.stage,args.snapshot,args.manifest_sha256,args.container_id,args.image,args.output,
            instrumentation_path=args.instrumentation,instrumentation_sha256=args.instrumentation_sha256)
        elif args.action=='instrument':result=instrument(args.bundle,args.manifest_sha256,args.output)
        elif args.action=='snapshot':
            stage=local_path(args.stage);bindings=stage_binding(stage,args.manifest_sha256)
            observed,_=Docker(args.docker,host=args.docker_host).inspect(args.container_id)
            owner_snapshot(observed,stage,bindings,args.container_id,args.image)
            output=local_path(args.output);directories(output.parent)
            need(not output.is_relative_to(stage.parent) and not stage.parent.is_relative_to(output),'OUTPUT_OVERLAPS_WORKSPACE')
            need(not os.path.lexists(output),'OUTPUT_ALREADY_EXISTS');write_new(output,observed)
            result=dict(status='OWNED_ENGINE_SNAPSHOT_RECORDED',snapshot_sha256=sha256(read(output)).hexdigest(),ready=False,executed=False)
        elif args.action in EXECUTION_COMMANDS:
            client=Docker(args.docker,host=args.docker_host)
            inputs=(args.plan,args.plan_sha256,args.instrumentation,args.instrumentation_sha256,client)
            if args.action=='arm':result=arm(*inputs,authorize_id=args.authorize_id,seconds=args.seconds)
            elif args.action=='watch-and-cut':result=watch_and_cut(*inputs,authorize_cut=args.authorize_cut,timeout=args.timeout)
            else:result=recover(*inputs,authorize_recover=args.authorize_recover,timeout=args.timeout,operator_readback=args.operator_readback)
        elif args.action=='finalize':result=finalize(args.plan,args.plan_sha256,args.native_result,args.native_result_sha256,
            args.operator_readback,args.operator_readback_sha256,args.output)
        else:
            raw=read(local_path(args.observations))
            need(hex64(args.observations_sha256) and sha256(raw).hexdigest()==args.observations_sha256,'OBSERVATION_DIGEST_MISMATCH')
            result=verify_records(parse(raw),parse(read(local_path(args.plan))),expected_plan_sha256=args.plan_sha256)
    except (OSError,ValueError,TypeError,KeyError,subprocess.SubprocessError) as exc:
        code=str(exc) if isinstance(exc,ChallengeError) else 'INPUT_OR_OWNERSHIP_REJECTED'
        # A rejection after reserving a mutation may still have an uncertain
        # outcome. Never label that path "executed:false" or automatically retry.
        print(json.dumps(dict(status='REJECTED_STATE_PRESERVED',code=code,ready=False,
            execution_attempted=args.action in EXECUTION_COMMANDS)))
        return 1
    print(json.dumps(result,sort_keys=True));return 0


if __name__=='__main__':raise SystemExit(main())
