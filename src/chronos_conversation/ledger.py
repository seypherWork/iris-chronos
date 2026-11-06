"""Pure transitions for a native transactional conversation ledger.

Not persistent or authenticated on its own. The IRIS adapter must hold the
conversation lock, commit+journal-sync before exposing inference_granted, enforce
provider quota and authenticate every scope. No time-based retries or dispatch.
"""
from copy import deepcopy
import re
from . import contract as c, grounded, grounded_v2


def protocol(context):
    if type(context) is dict and "response_contract" in context:
        for adapter in (grounded,grounded_v2):
            if context["response_contract"]==adapter.SCHEMA:return adapter
        raise c.Invalid("INVALID_CONVERSATION_CONTRACT")
    return c


def context_revision(context,revision):
    adapter=protocol(context)
    if adapter is not c:return adapter.with_conversation_revision(context,revision)
    result=deepcopy(context);result['conversation_revision']=revision;return result

SCHEMA = 'chronos.conversation-ledger.v2'
LIMIT = 6
PENDING = {'RECORDED','PROCESSING','UNCERTAIN'}
TERMINAL = {'COMPLETED','REJECTED'}


CALL_FIELDS={'transport_id','model','profile_sha256','schema_sha256','reasoning_effort',
             'ai_hub_session_id','deadline_us','response_contract'}

def clock(value):
    if type(value) is not int or not 0<value<2**53:raise c.Invalid('INVALID_CALL_CLOCK')

def call_check(call,expected_contract=None):
    c.exact(call,CALL_FIELDS|{'claimed_at_us'},'INVALID_CALL_BINDING')
    for key in ('profile_sha256','schema_sha256'):
        if type(call[key]) is not str or not re.fullmatch(r'[a-f0-9]{64}',call[key]):raise c.Invalid('INVALID_CALL_BINDING')
    if type(call['transport_id']) is not str or not re.fullmatch(r'[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}',call['transport_id']):raise c.Invalid('INVALID_CALL_BINDING')
    if type(call['model']) is not str or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}',call['model']):raise c.Invalid('INVALID_CALL_BINDING')
    if type(call['ai_hub_session_id']) is not str or not re.fullmatch(r'[1-9][0-9]{0,17}',call['ai_hub_session_id']):raise c.Invalid('INVALID_CALL_BINDING')
    if type(call['reasoning_effort']) is not str or call['reasoning_effort'] not in {'none','low','medium'}:raise c.Invalid('INVALID_CALL_BINDING')
    if call['response_contract'] not in (c.SCHEMA,grounded.SCHEMA,grounded_v2.SCHEMA):raise c.Invalid('INVALID_CALL_BINDING')
    if expected_contract is not None and call['response_contract']!=expected_contract:raise c.Invalid('CALL_CONTRACT_MISMATCH')
    clock(call['claimed_at_us']);clock(call['deadline_us'])
    if not call['claimed_at_us']<call['deadline_us']<=call['claimed_at_us']+30_000_000:raise c.Invalid('INVALID_CALL_DEADLINE')

def call_digest(t):return c.digest({'prepared_binding':t['binding_sha256'],'claim_id':t['claim_id'],'call':t['call']})

def receipt_check(receipt,call):
    c.exact(receipt,{'version','request_id','finish_reason','model','profile_sha256','response_contract'},'INVALID_TRANSPORT_RECEIPT')
    if type(receipt['version']) is not int or receipt['version']!=1 or receipt['finish_reason']!='stop':raise c.Invalid('INVALID_TRANSPORT_RECEIPT')
    for key,source in (('request_id','transport_id'),('model','model'),('profile_sha256','profile_sha256'),('response_contract','response_contract')):
        if type(receipt[key]) is not str or receipt[key]!=call[source]:raise c.Invalid('CALL_RECEIPT_MISMATCH')

def scope_check(scope):
    c.exact(scope,c.SCOPE,'INVALID_SCOPE')
    for key in c.SCOPE-{'shipment_version'}:c.identifier(scope[key])
    c.positive(scope['shipment_version'])
    if c.sensitive(scope):raise c.Invalid('SENSITIVE_SCOPE')

def check(state,scope):
    c.exact(state,{'schema','conversation_id','scope','revision','turns','preference_events'},'INVALID_LEDGER')
    if state['schema']!=SCHEMA or state['scope']!=scope:raise c.Invalid('CONVERSATION_SCOPE_CHANGED')
    c.identifier(state['conversation_id']);c.positive(state['revision'])
    turns=state['turns']
    if type(turns) is not list or len(turns)>LIMIT or state['revision']!=len(turns)+1:raise c.Invalid('INVALID_LEDGER')
    if len(c.canonical(state).encode('utf-8'))>524288:raise c.Invalid('LEDGER_TOO_LARGE')
    ids=set();history=[];events=[];transports=set();sessions=set()
    for i,t in enumerate(turns):
        c.exact(t,{'id','request_digest','user_text','status','prepared_json','binding_sha256',
                   'claim_id','call','call_digest','observed_us','response','error','recorded_us','record_observed_us'},'INVALID_LEDGER_TURN')
        c.identifier(t['id']);clock(t['recorded_us']);clock(t['record_observed_us']);clock(t['recorded_us']+30_000_000)
        if t['record_observed_us']<t['recorded_us']:raise c.Invalid('RECORD_CLOCK_REVERSED')
        if t['id'] in ids or type(t['status']) is not str or t['status'] not in PENDING|TERMINAL:
            raise c.Invalid('INVALID_LEDGER_TURN')
        ids.add(t['id'])
        if t['status'] in PENDING and i!=len(turns)-1:raise c.Invalid('INVALID_PENDING_ORDER')
        c.text(t['user_text'],2048,'INVALID_LEDGER_TURN')
        try:
            p=c.Prepared(t['prepared_json'],t['binding_sha256']);record=p.checked();w=record['wire']
            check_history(w['context'],state,i,events)
            rebuilt,_=protocol(w['context']).prepare(scope,w['context'],conversation_id=state['conversation_id'],turn_id=t['id'],user_text=t['user_text'],history=history)
            if rebuilt!=p or w['context']['conversation_revision']!=i+2:raise c.Invalid('PREPARED_CHANGED')
            original_context=context_revision(w['context'],i+1)
            request={'turn_id':t['id'],'expected_revision':i+1,'user_text':t['user_text'],
                     'expected_context_digest':c.digest({'scope':scope,'context':original_context})}
            if t['request_digest']!=c.digest(request):raise c.Invalid('REQUEST_BINDING_CHANGED')
        except (ValueError,TypeError,KeyError,AttributeError,UnicodeError,RecursionError):
            raise c.Invalid('INVALID_LEDGER_BINDING') from None
        if t['status']=='RECORDED':
            if any(t[k] is not None for k in ('claim_id','call','call_digest','observed_us','response','error')):raise c.Invalid('INVALID_TURN_STATE')
        elif t['status']=='REJECTED' and t['error'] in {'CONTEXT_CHANGED','MODEL_NOT_STARTED'}:
            if any(t[k] is not None for k in ('claim_id','call','call_digest','observed_us','response')):raise c.Invalid('INVALID_TURN_STATE')
        else:
            c.identifier(t['claim_id']);call_check(t['call'],w['schema']);clock(t['observed_us'])
            if t['call']['claimed_at_us']!=t['record_observed_us'] or t['call']['claimed_at_us']>=t['recorded_us']+30_000_000:raise c.Invalid('INVALID_RESERVATION_WINDOW')
            if t['observed_us']<t['call']['claimed_at_us']:raise c.Invalid('CALL_CLOCK_REVERSED')
            if t['status']=='COMPLETED' and t['observed_us']>=t['call']['deadline_us']:raise c.Invalid('COMPLETED_AFTER_DEADLINE')
            if t['call_digest']!=call_digest(t):raise c.Invalid('CALL_BINDING_CHANGED')
            if t['call']['transport_id'] in transports or t['call']['ai_hub_session_id'] in sessions:raise c.Invalid('CALL_ID_REUSED')
            transports.add(t['call']['transport_id']);sessions.add(t['call']['ai_hub_session_id'])
            if t['status']=='PROCESSING' and (t['response'] is not None or t['error'] is not None):raise c.Invalid('INVALID_TURN_STATE')
            if t['status']=='UNCERTAIN' and (t['response'] is not None or t['error']!='PROVIDER_OUTCOME_UNCERTAIN'):raise c.Invalid('INVALID_TURN_STATE')
            if t['status']=='REJECTED' and (t['response'] is not None or t['error'] not in ('PROVIDER_REFUSED','COMPLETION_REJECTED')):raise c.Invalid('INVALID_TURN_STATE')
            if t['status']=='COMPLETED':
                if t['error'] is not None or type(t['response']) is not dict:raise c.Invalid('INVALID_TURN_STATE')
                try:
                    adapter=protocol(w['context'])
                    raw=(adapter.response_raw(t['response']) if adapter is not c else c.canonical({k:t['response'][k] for k in ('schema','conversation_id','turn_id','context_digest','intent','answer','source_ids','preference')}))
                    validated=adapter.finish(p,raw,current_scope=scope,current_context=w['context'])
                    if c.canonical(validated)!=c.canonical(t['response']):raise c.Invalid('INVALID_STORED_RESPONSE')
                except (ValueError,TypeError,KeyError,UnicodeError,RecursionError):raise c.Invalid('INVALID_STORED_RESPONSE') from None
                history.extend([{'role':'user','text':t['user_text']},{'role':'assistant','text':validated['answer']}])
                if validated['intent']=='PREFERENCE_PROPOSAL':events.append(preference_event(state,t,w['context']))
    if type(state['preference_events']) is not list or c.canonical(state['preference_events'])!=c.canonical(events):
        raise c.Invalid('INVALID_PREFERENCE_EVENTS')

def check_history(context,state,count,events):
    if protocol(context) is grounded_v2:
        prefix={**state,'revision':count+1,'turns':state['turns'][:count],'preference_events':events}
        grounded_v2.validate_history_binding(context,prefix)

def preference_event(state,t,context):
    response=t['response']
    event={'kind':'OPERATOR_PREFERENCE_PROPOSAL','turn_id':t['id'],
        'decision_id':context['decision_id'],'context_digest':response['context_digest'],
        'preference':response['preference'],'adopted':False}
    event['event_id']=c.digest({'conversation_id':state['conversation_id'],'event':event})
    return event

def public(state):
    check(state,state['scope'])
    return {'conversation_id':state['conversation_id'],'case_id':state['scope']['case_id'],
            'shipment_version':state['scope']['shipment_version'],'revision':state['revision'],
            'turn_limit':LIMIT,'turns':[{'turn_id':t['id'],'user_text':t['user_text'],'state':t['status'],
                'response':deepcopy(t['response']),'error':t['error']} for t in state['turns']],
            'preference_events':deepcopy(state['preference_events']),
            'dispatch_authorized':False,'confirmation_granted':False}

def output(state,code,**extra):
    return {'code':code,'public':public(state),'inference_granted':False,'dispatch_authorized':False,**extra}

def turn(state,ident):
    c.identifier(ident)
    found=next((t for t in state['turns'] if t['id']==ident),None)
    if found is None:raise c.Invalid('TURN_NOT_FOUND')
    return found

def bound_context(state,t,context):
    protocol(context).validate_context(state['scope'],context)
    prepared=c.Prepared(t['prepared_json'],t['binding_sha256'])
    record=prepared.checked()
    if record['scope']!=state['scope']:raise c.Invalid('PREPARED_SCOPE_CHANGED')
    if context['conversation_revision']!=state['revision']:raise c.Invalid('CONVERSATION_REVISION_CHANGED')
    if record['wire']['context_digest']!=c.digest({'scope':state['scope'],'context':context}):raise c.Invalid('CONTEXT_CHANGED')
    history=[]
    for prior in state['turns']:
        if prior['id']==t['id']:break
        if prior['status']=='COMPLETED':history.extend([{'role':'user','text':prior['user_text']},{'role':'assistant','text':prior['response']['answer']}])
    rebuilt,request=protocol(context).prepare(state['scope'],context,conversation_id=state['conversation_id'],turn_id=t['id'],user_text=t['user_text'],history=history)
    if rebuilt!=prepared:raise c.Invalid('PREPARED_CHANGED')
    return prepared,request

def transition(previous,command,scope,args):
    """Return a new value plus a result; never mutate caller-owned input.

    Args and scope are trusted-controller inputs, not raw HTTP bodies. A caller
    must not release a private CLAIM response before the returned state is durable.
    """
    scope_check(scope)
    if command=='OPEN':
        c.exact(args,{'conversation_id'},'INVALID_OPEN');c.identifier(args['conversation_id'])
        if previous is not None:
            check(previous,scope)
            if previous['conversation_id']!=args['conversation_id']:raise c.Invalid('CONVERSATION_CONFLICT')
            state=deepcopy(previous);return state,output(state,'CONVERSATION_EXISTS')
        state={'schema':SCHEMA,'conversation_id':args['conversation_id'],'scope':deepcopy(scope),
               'revision':1,'turns':[],'preference_events':[]}
        return state,output(state,'CONVERSATION_OPENED')
    check(previous,scope);state=deepcopy(previous)
    if command=='READ':
        c.exact(args,set(),'INVALID_READ');return state,output(state,'CONVERSATION_READ')
    if command=='RECORD':
        c.exact(args,{'turn_id','expected_revision','expected_context_digest','user_text','context','now_us'},'INVALID_RECORD');clock(args['now_us']);clock(args['now_us']+30_000_000)
        c.identifier(args['turn_id']);c.text(args['user_text'],2048,'INVALID_USER_TEXT');c.positive(args['expected_revision'])
        if type(args['expected_context_digest']) is not str or not re.fullmatch('[0-9a-f]{64}',args['expected_context_digest']):
            raise c.Invalid('INVALID_CONTEXT_DIGEST')
        request_digest=c.digest({k:args[k] for k in ('turn_id','expected_revision','expected_context_digest','user_text')})
        existing=next((t for t in state['turns'] if t['id']==args['turn_id']),None)
        if existing:
            if existing['request_digest']!=request_digest:raise c.Invalid('MESSAGE_ID_CONFLICT')
            return state,output(state,'TURN_REPLAY')
        if state['turns'] and state['turns'][-1]['status'] in PENDING:raise c.Invalid('CONVERSATION_BUSY')
        if len(state['turns'])>=LIMIT:raise c.Invalid('TURN_LIMIT_REACHED')
        if args['expected_revision']!=state['revision']:raise c.Invalid('CONVERSATION_REVISION_CHANGED')
        context=deepcopy(args['context']);protocol(context).validate_context(scope,context)
        if context['conversation_revision']!=state['revision']:raise c.Invalid('CONVERSATION_REVISION_CHANGED')
        if args['expected_context_digest']!=c.digest({'scope':scope,'context':context}):raise c.Invalid('CONTEXT_CHANGED')
        check_history(context,state,len(state['turns']),state['preference_events'])
        context=context_revision(context,context['conversation_revision']+1)
        history=[]
        for old in state['turns']:
            if old['status']=='COMPLETED':history.extend([{'role':'user','text':old['user_text']},{'role':'assistant','text':old['response']['answer']}])
        prepared,_=protocol(context).prepare(scope,context,conversation_id=state['conversation_id'],turn_id=args['turn_id'],user_text=args['user_text'],history=history)
        state['turns'].append({'id':args['turn_id'],'request_digest':request_digest,'user_text':args['user_text'],
            'status':'RECORDED','prepared_json':prepared.record_json,'binding_sha256':prepared.binding_sha256,
            'recorded_us':args['now_us'],'record_observed_us':args['now_us'],
            'claim_id':None,'call':None,'call_digest':None,'observed_us':None,'response':None,'error':None})
        state['revision']+=1;check(state,scope)
        return state,output(state,'TURN_RECORDED')
    if command=='DECLINE':
        # Trusted host failed before reserving inference. Never unlock a spent call.
        c.exact(args,{'turn_id'},'INVALID_DECLINE');t=turn(state,args['turn_id'])
        if t['status']=='RECORDED':
            t.update(status='REJECTED',error='MODEL_NOT_STARTED')
            return state,output(state,'TURN_REJECTED')
        return state,output(state,'NO_NEW_INFERENCE')
    if command=='CLAIM':
        c.exact(args,{'turn_id','claim_id','context','call','now_us'},'INVALID_CLAIM');c.identifier(args['claim_id']);clock(args['now_us'])
        t=turn(state,args['turn_id'])
        if t['status']!='RECORDED':return state,output(state,'NO_NEW_INFERENCE')
        if args['now_us']<t['record_observed_us']:raise c.Invalid('RECORD_CLOCK_REVERSED')
        t['record_observed_us']=args['now_us']
        if args['now_us']>=t['recorded_us']+30_000_000:
            t.update(status='REJECTED',error='MODEL_NOT_STARTED')
            return state,output(state,'TURN_REJECTED')
        c.exact(args['call'],CALL_FIELDS,'INVALID_CALL_BINDING')
        call=deepcopy(args['call']);call['claimed_at_us']=args['now_us'];call_check(call)
        for prior in state['turns']:
            if prior['call'] is not None and (prior['call']['transport_id']==call['transport_id'] or prior['call']['ai_hub_session_id']==call['ai_hub_session_id']):raise c.Invalid('CALL_ID_REUSED')
        try:prepared,request=bound_context(state,t,args['context'])
        except c.Invalid:
            t.update(status='REJECTED',error='CONTEXT_CHANGED')
            return state,output(state,'TURN_REJECTED')
        call_check(call,prepared.checked()['wire']['schema'])
        t.update(status='PROCESSING',claim_id=args['claim_id'],call=call,observed_us=args['now_us'])
        t['call_digest']=call_digest(t);check(state,scope)
        return state,output(state,'INFERENCE_RESERVED',inference_granted=True,
                            private_provider_request=request,private_call=deepcopy(call))
    if command=='RECOVER':
        c.exact(args,{'turn_id','now_us'},'INVALID_RECOVERY');clock(args['now_us']);t=turn(state,args['turn_id'])
        if t['status']=='RECORDED':
            if args['now_us']<t['record_observed_us']:raise c.Invalid('RECORD_CLOCK_REVERSED')
            t['record_observed_us']=args['now_us']
            if args['now_us']>=t['recorded_us']+30_000_000:
                t.update(status='REJECTED',error='MODEL_NOT_STARTED')
                return state,output(state,'TURN_REJECTED')
            return state,output(state,'CALL_STILL_PENDING')
        if t['status'] in {'PROCESSING','UNCERTAIN'}:
            if args['now_us']<t['observed_us']:raise c.Invalid('CALL_CLOCK_REVERSED')
            t['observed_us']=args['now_us']
            if args['now_us']>=t['call']['deadline_us']:
                t.update(status='UNCERTAIN',error='PROVIDER_OUTCOME_UNCERTAIN')
            elif t['status']=='PROCESSING':return state,output(state,'CALL_STILL_PENDING')
        return state,output(state,'NO_AUTOMATIC_RETRY')
    if command=='COMPLETE':
        c.exact(args,{'turn_id','claim_id','context','raw','provider_status','receipt','now_us'},'INVALID_COMPLETION')
        c.identifier(args['claim_id']);clock(args['now_us']);t=turn(state,args['turn_id'])
        if t['claim_id'] is None or t['claim_id']!=args['claim_id']:raise c.Invalid('CLAIM_MISMATCH')
        if t['status'] in TERMINAL:return state,output(state,'COMPLETION_REPLAY')
        if t['status'] not in {'PROCESSING','UNCERTAIN'}:raise c.Invalid('NOT_PROCESSING')
        provider_status=args['provider_status']
        if type(provider_status) is not str or provider_status not in {'ok','timeout','refusal','error'}:raise c.Invalid('INVALID_PROVIDER_STATUS')
        if args['now_us']<t['observed_us']:raise c.Invalid('CALL_CLOCK_REVERSED')
        t['observed_us']=args['now_us']
        if provider_status in {'timeout','error'} or args['now_us']>=t['call']['deadline_us']:
            t.update(status='UNCERTAIN',error='PROVIDER_OUTCOME_UNCERTAIN')
            return state,output(state,'NO_AUTOMATIC_RETRY')
        if provider_status=='refusal':
            t.update(status='REJECTED',error='PROVIDER_REFUSED')
            return state,output(state,'TURN_REJECTED')
        try:
            receipt_check(args['receipt'],t['call'])
            prepared,_=bound_context(state,t,args['context'])
            response=protocol(args['context']).finish(prepared,args['raw'],current_scope=scope,current_context=args['context'])
        except (ValueError,TypeError,KeyError,UnicodeError,RecursionError):
            t.update(status='REJECTED',error='COMPLETION_REJECTED')
            return state,output(state,'TURN_REJECTED')
        t.update(status='COMPLETED',response=response,error=None)
        if response['intent']=='PREFERENCE_PROPOSAL':
            state['preference_events'].append(preference_event(state,t,args['context']))
        check(state,scope);return state,output(state,'TURN_COMPLETED')
    raise c.Invalid('INVALID_LEDGER_COMMAND')
