"""Explicit local neutral inference check; never a business request or readiness lease.

Run inside the installed IRIS container. No service start, downloads, credentials,
quota changes, retries or remote destinations. Results are historical evidence.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import argparse
import http.client
import json
import os
import re
import socket
import stat
import threading
import time
import local_provider as provider

MAX_BYTES = 65536
DEADLINE_SECONDS = 240
DATA_ROOT = Path('/durable/chronos')
CODES = frozenset({'DEADLINE_EXCEEDED','HTTP_REJECTED','BODY_TOO_LARGE','INVALID_JSON',
    'INVALID_HTTP_BODY','MODEL_IDENTITY_MISMATCH','INVALID_NEUTRAL_RESULT',
    'INVALID_TOKEN_COUNTS','INVALID_MODEL_RESIDENCY','TRANSPORT_UNCERTAIN',
    'INVALID_BINDING','BUSY','EXISTING_ATTEMPT_UNVERIFIED','STATE_WRITE_UNCERTAIN'})
class ReadinessError(ValueError):
    pass

def require(value, code):
    if not value: raise ReadinessError(code)

def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode()

def strict_json(raw):
    def pairs(rows):
        result={}
        for key,value in rows:
            require(key not in result,'INVALID_JSON');result[key]=value
        return result
    def constant(_): raise ReadinessError('INVALID_JSON')
    try:return json.loads(raw,object_pairs_hook=pairs,parse_constant=constant)
    except (ValueError,TypeError,UnicodeError):raise ReadinessError('INVALID_JSON') from None

def exchange(path, body, deadline):
    require(path in {'/api/chat','/api/tags','/api/ps'},'INVALID_BINDING')
    remaining=deadline-time.monotonic();require(remaining>0,'DEADLINE_EXCEEDED')
    conn=http.client.HTTPConnection('127.0.0.1',11434,timeout=remaining)
    state={'response':None};expired=threading.Event()
    def cancel():
        expired.set();response=state['response'];raw=getattr(getattr(response,'fp',None),'raw',None)
        for sock in (conn.sock,getattr(raw,'_sock',None)):
            if sock is not None:
                try:sock.shutdown(socket.SHUT_RDWR)
                except OSError:pass
                try:sock.close()
                except OSError:pass
    def check_time():
        left=deadline-time.monotonic();require(left>0 and not expired.is_set(),'DEADLINE_EXCEEDED')
        conn.timeout=left
        if conn.sock is not None:conn.sock.settimeout(left)
    timer=threading.Timer(remaining,cancel);timer.daemon=True;timer.start()
    try:
        conn.connect();check_time()
        conn.request('GET' if body is None else 'POST',path,None if body is None else canonical(body),
                     {'Content-Type':'application/json','Connection':'close'})
        check_time();response=conn.getresponse();state['response']=response;check_time()
        require(response.status==200,'HTTP_REJECTED')
        require((response.getheader('Content-Type') or '').lower().split(';')[0].strip()=='application/json','INVALID_HTTP_BODY')
        length=response.getheader('Content-Length')
        if length is not None:
            require(length.isascii() and length.isdigit() and len(length)<=8 and int(length)<=MAX_BYTES,'BODY_TOO_LARGE')
        parts=[];size=0
        while True:
            check_time();part=response.read1(min(4096,MAX_BYTES+1-size));check_time()
            if not part:break
            size+=len(part);require(size<=MAX_BYTES,'BODY_TOO_LARGE');parts.append(part)
        require(length is None or size==int(length),'INVALID_HTTP_BODY')
        value=strict_json(b''.join(parts));check_time();return value
    except ReadinessError:raise
    except (OSError,http.client.HTTPException,ValueError):
        raise ReadinessError('DEADLINE_EXCEEDED' if expired.is_set() or time.monotonic()>=deadline else 'TRANSPORT_UNCERTAIN') from None
    finally:timer.cancel();conn.close()

def neutral_request(profile):
    return {'model':profile.model,'messages':[{'role':'user','content':
        'This is a neutral readiness check. Ignore the numeric padding below. '
        'Return only the JSON object {"ready":true}.\n<neutral-padding>\n'+
        '0 1 2 3 4 5 6 7 8 9 '*80+'\n</neutral-padding>'}],
        'format':{'type':'object','properties':{'ready':{'type':'boolean','const':True}},
                  'required':['ready'],'additionalProperties':False},
        'think':False if profile.reasoning_effort=='none' else profile.reasoning_effort,
        'options':{'num_predict':128,'temperature':0},'stream':False,'keep_alive':'10m',
        'truncate':False,'shift':False}

def validate_neutral(value, model):
    require(type(value)is dict and value.get('model')==model and value.get('done')is True
            and value.get('done_reason')=='stop','INVALID_NEUTRAL_RESULT')
    msg=value.get('message')
    require(type(msg)is dict and msg.get('role')=='assistant' and type(msg.get('content'))is str
            and len(msg['content'].encode())<=2048 and msg.get('tool_calls',[])==[]
            and value.get('tool_calls',[])==[],'INVALID_NEUTRAL_RESULT')
    content=strict_json(msg['content'])
    require(type(content)is dict and set(content)=={'ready'} and content['ready']is True,'INVALID_NEUTRAL_RESULT')
    require(type(value.get('eval_count'))is int and 1<=value['eval_count']<=128
            and type(value.get('prompt_eval_count'))is int and 512<=value['prompt_eval_count']<=4096,'INVALID_TOKEN_COUNTS')
    return {'eval_count':value['eval_count'],'prompt_eval_count':value['prompt_eval_count'],
            'content_sha256':sha256(msg['content'].encode()).hexdigest()}

def model_record(value, model, digest, *, resident=False, context_length=None):
    require(type(value)is dict and type(value.get('models'))is list,'MODEL_IDENTITY_MISMATCH')
    matches=[v for v in value['models'] if type(v)is dict and v.get('name')==model and v.get('model')==model]
    require(len(matches)==1,'MODEL_IDENTITY_MISMATCH');m=matches[0]
    require(m.get('digest')==digest and type(m.get('size'))is int and m['size']>0
            and not m.get('remote_host') and not m.get('remote_model')
            and type(m.get('details'))is dict and m['details'].get('format')=='gguf','MODEL_IDENTITY_MISMATCH')
    if resident:
        require(len(value['models'])==1 and type(m.get('context_length'))is int
                and m['context_length']==context_length and type(m.get('size_vram'))is int
                and 0<=m['size_vram']<=m['size'],'INVALID_MODEL_RESIDENCY')
        try:expires=datetime.fromisoformat(m['expires_at'].replace('Z','+00:00'))
        except (ValueError,KeyError,TypeError,AttributeError):raise ReadinessError('INVALID_MODEL_RESIDENCY') from None
        require(expires.tzinfo is not None and expires>datetime.now(timezone.utc),'INVALID_MODEL_RESIDENCY')
    return {'digest':digest,'context_length':m.get('context_length') if resident else None,
            'size':m['size'],'size_vram':m.get('size_vram') if resident else None}

def sync_dir(path):
    if os.name=='posix':
        fd=os.open(path,os.O_RDONLY|os.O_DIRECTORY)
        try:os.fsync(fd)
        finally:os.close(fd)

def write_new(path, value):
    provider.plain(path.parent,directory=True)
    with path.open('xb') as f:f.write(canonical(value));f.flush();os.fsync(f.fileno())
    sync_dir(path.parent)

def checked_parent(path):
    for p in reversed((path,*path.parents)):provider.plain(p,directory=True)

@contextmanager
def exclusive(area):
    lock=area/'execution.lock'
    if os.path.lexists(lock):provider.plain(lock)
    fd=os.open(lock,os.O_RDWR|os.O_CREAT|getattr(os,'O_NOFOLLOW',0),0o600);locked=False
    try:
        require(stat.S_ISREG(os.fstat(fd).st_mode),'INVALID_BINDING')
        provider.plain(lock)
        try:
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(fd,msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            locked=True
        except OSError:raise ReadinessError('BUSY') from None
        yield
    finally:
        if locked:
            if os.name=='nt':
                import msvcrt
                os.lseek(fd,0,0);msvcrt.locking(fd,msvcrt.LK_UNLCK,1)
            else:
                import fcntl
                fcntl.flock(fd,fcntl.LOCK_UN)
        os.close(fd)

def binding(ident, profile_sha, attempt, model_digest, context_length, runtime, data_root):
    provider.identity(ident)
    require(all(type(x)is str and re.fullmatch('[a-f0-9]{64}',x) for x in [profile_sha,model_digest])
            and type(attempt)is str and re.fullmatch('[a-f0-9]{32}',attempt)
            and type(context_length)is int and 512<=context_length<=131072,'INVALID_BINDING')
    profile=provider.read_profile(provider.location(runtime),ident)
    require(profile.digest==profile_sha,'INVALID_BINDING')
    parent=Path(data_root)/ident;checked_parent(parent)
    return profile,parent/'model-readiness',{'version':1,'deployment_id':ident,'attempt_id':attempt,
        'profile_sha256':profile_sha,'model_sha256':sha256(profile.model.encode()).hexdigest(),
        'expected_model_digest':model_digest,'expected_context_length':context_length}

def read_record(path):
    provider.plain(path)
    with path.open('rb') as stream:raw=stream.read(8193)
    require(len(raw)<=8192,'EXISTING_ATTEMPT_UNVERIFIED')
    return strict_json(raw)

def historical(area, identity):
    attempt=area/identity['attempt_id']
    if not os.path.lexists(attempt):return dict(identity,status='NOT_FOUND',performed_request=False)
    provider.plain(attempt,directory=True)
    try:
        intent=read_record(attempt/'intent.json');require(intent==identity,'EXISTING_ATTEMPT_UNVERIFIED')
        if not os.path.lexists(attempt/'result.json'):return dict(identity,status='RESERVED_OUTCOME_UNCERTAIN',performed_request=False,historical=True,prior_request_outcome_unknown=True)
        v=read_record(attempt/'result.json')
        require(type(v)is dict and set(v)=={'binding','status','code','observed_at','metrics'} and v['binding']==identity
                and v['status'] in {'NEUTRAL_INFERENCE_OBSERVED','READINESS_UNVERIFIED'} and v['code'] in CODES|{'OK'},'EXISTING_ATTEMPT_UNVERIFIED')
        stamp=v['observed_at']
        require(type(stamp)is str and len(stamp)<=40,'EXISTING_ATTEMPT_UNVERIFIED')
        observed=datetime.fromisoformat(stamp)
        require(observed.tzinfo is not None and observed.utcoffset().total_seconds()==0
                and observed.isoformat()==stamp,'EXISTING_ATTEMPT_UNVERIFIED')
        metrics=v['metrics']
        require(type(metrics)is dict,'EXISTING_ATTEMPT_UNVERIFIED')
        if v['status']=='NEUTRAL_INFERENCE_OBSERVED':
            require(v['code']=='OK' and set(metrics)=={'eval_count','prompt_eval_count',
                'content_sha256','residency_sha256','elapsed_ms'},'EXISTING_ATTEMPT_UNVERIFIED')
            require(type(metrics['eval_count'])is int and 1<=metrics['eval_count']<=128
                and type(metrics['prompt_eval_count'])is int and 512<=metrics['prompt_eval_count']<=4096
                and type(metrics['elapsed_ms'])is int and 0<=metrics['elapsed_ms']<=DEADLINE_SECONDS*1000
                and all(type(metrics[k])is str and re.fullmatch('[a-f0-9]{64}',metrics[k])
                    for k in ('content_sha256','residency_sha256')),'EXISTING_ATTEMPT_UNVERIFIED')
        else:
            require(v['code'] in CODES and metrics=={},'EXISTING_ATTEMPT_UNVERIFIED')
        # Observation time is historical, never a current readiness lease.
        return dict(identity,status=v['status'],code=v['code'],observed_at=stamp,metrics=metrics,
                    performed_request=False,historical=True,availability_guaranteed=False)
    except (OSError,ValueError,KeyError,TypeError):
        return dict(identity,status='EXISTING_ATTEMPT_UNVERIFIED',performed_request=False)

def inspect(ident, profile_sha, attempt, model_digest, context_length, *, runtime=provider.RUNTIME,data_root=DATA_ROOT):
    _,area,identity=binding(ident,profile_sha,attempt,model_digest,context_length,runtime,data_root)
    if not os.path.lexists(area):return dict(identity,status='NOT_FOUND',performed_request=False)
    checked_parent(area);return historical(area,identity)

def run(ident, profile_sha, attempt, model_digest, context_length, *, authorize_id,
        runtime=provider.RUNTIME,data_root=DATA_ROOT):
    require(authorize_id==ident,'INVALID_BINDING')
    profile,area,identity=binding(ident,profile_sha,attempt,model_digest,context_length,runtime,data_root)
    if not os.path.lexists(area):
        try:area.mkdir(mode=0o700);sync_dir(area.parent)
        except FileExistsError:pass
    checked_parent(area)
    with exclusive(area):
        existing=historical(area,identity)
        if existing['status']!='NOT_FOUND':return existing
        target=area/attempt
        target.mkdir(mode=0o700);sync_dir(area)
        write_new(target/'intent.json',identity)  # Persist before any HTTP request.
        begun=time.monotonic();deadline=begun+DEADLINE_SECONDS;sent=False;metrics={}
        status='READINESS_UNVERIFIED';code='TRANSPORT_UNCERTAIN'
        try:
            model_record(exchange('/api/tags',None,deadline),profile.model,model_digest)
            sent=True
            value=exchange('/api/chat',neutral_request(profile),deadline)
            metrics=validate_neutral(value,profile.model);value=None
            residency=model_record(exchange('/api/ps',None,deadline),profile.model,model_digest,
                                   resident=True,context_length=context_length)
            require(time.monotonic()<deadline,'DEADLINE_EXCEEDED')
            metrics.update(residency_sha256=sha256(canonical(residency)).hexdigest(),elapsed_ms=round((time.monotonic()-begun)*1000))
            status='NEUTRAL_INFERENCE_OBSERVED';code='OK'
        except Exception as e:
            code=str(e) if type(e)is ReadinessError and str(e) in CODES else 'TRANSPORT_UNCERTAIN'
            metrics={}
        result={'binding':identity,'status':status,'code':code,'observed_at':datetime.now(timezone.utc).isoformat(),'metrics':metrics}
        write_new(target/'result.json',result)
        return dict(identity,status=status,code=code,observed_at=result['observed_at'],metrics=metrics,
                    performed_request=sent,historical=False,business_requests=0,availability_guaranteed=False)

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='command',required=True)
    for name in ['run','status']:
        p=sub.add_parser(name)
        for arg in ['deployment-id','profile-sha256','attempt-id','model-digest']:p.add_argument('--'+arg,required=True)
        p.add_argument('--context-length',type=int,required=True)
        if name=='run':p.add_argument('--authorize-id',required=True)
    args=parser.parse_args(argv)
    try:
        values=(args.deployment_id,args.profile_sha256,args.attempt_id,args.model_digest,args.context_length)
        value=run(*values,authorize_id=args.authorize_id) if args.command=='run' else inspect(*values)
    except Exception as e:
        code=str(e) if type(e)is ReadinessError and str(e) in CODES else 'STATE_WRITE_UNCERTAIN'
        value={'status':'READINESS_UNVERIFIED','code':code,'retry_performed':False}
    print(json.dumps(value,sort_keys=True,allow_nan=False))
    return 0 if value['status']=='NEUTRAL_INFERENCE_OBSERVED' else 2

if __name__=='__main__':raise SystemExit(main())
