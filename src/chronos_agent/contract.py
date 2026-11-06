"""Native-time proposal contract, with no I/O and no mutation authority.

The trusted orchestrator supplies an atomic destination observation, a stable
IRIS authority read and recovery gate. They are separate stores, not one atomic
transaction. This module never authenticates their origin. Its serializable
record must be retained and consumed once by the native decision ledger.
"""
from copy import deepcopy
import re

from .engine import S, M, authority_snapshot, require_native, canonical, fingerprint, integer, validate, Change, preview
from .proposal import Invalid, OPTIONS, check, parse, sensitive
from .timeview import model_input
from .extraction import BoundContext, assemble, Invalid as ExtractionInvalid, SCHEMA_VERSION as EXTRACTION_CONTRACT

MODES={'WITH_TRIALS','WITHOUT_TRIALS_ABLATION'}
PROPOSAL_CONTRACT='chronos.agent-proposal.v2'
RESPONSE_CONTRACTS={PROPOSAL_CONTRACT,EXTRACTION_CONTRACT}
FAILURES=(ValueError,TypeError,KeyError,UnicodeError,RecursionError,OverflowError)
EXTRACTION_DIAGNOSTIC_CODES=frozenset({
    'CONTEXT_DIGEST_MISMATCH','INVALID_AVAILABLE','DUPLICATE_AVAILABLE',
    'CALL_CONTEXT_MISMATCH','BOUND_CONTEXT_CHANGED','INVALID_EXTRACTION',
    'INVALID_EXTRACTION_JSON','SENSITIVE_OUTPUT','EXTRACTION_CONTRACT_MISMATCH',
    'INCONSISTENT_EXTRACTION','INVALID_SOURCES','INVALID_RATIONALE',
    'INVALID_SOURCES_LIST','INVALID_SOURCES_COUNT','INVALID_SOURCES_TYPE',
    'INVALID_SOURCES_UNKNOWN','INVALID_SOURCES_DUPLICATE',
    'INVALID_CLARIFICATION','STRUCTURED_POLICY_MISMATCH','CURRENT_SOURCE_REQUIRED',
    'CONFLICT_SOURCES_REQUIRED','UNKNOWN_PREFERENCE_MODE',
})


def result(status,code,**extra):
    return {'status':status,'code':code,'dispatch_authorized':False,**extra}


def identifier(value):
    if type(value) is not str or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}',value):raise Invalid('INVALID_IDENTITY')


def exact(value,keys):
    if type(value) is not dict or set(value)!=set(keys.split()):raise Invalid('INVALID_INPUT')


def observation_copy(observation,now_us):
    integer(now_us,'utc_now')
    text=canonical(observation)
    if len(text.encode('utf-8'))>1_048_576:raise Invalid('OBSERVATION_TOO_LARGE')
    o=parse(text)
    exact(o,'definition calendar clock clock_domain sequence operations facts_id facts_revision observation_id')
    if o['observation_id']!=fingerprint({k:v for k,v in o.items() if k!='observation_id'}):raise Invalid('OBSERVATION_CHANGED')
    material={k:v for k,v in o.items() if k not in {'clock','clock_domain','sequence','facts_id','facts_revision','observation_id'}}
    if o['facts_id']!=fingerprint(material):raise Invalid('FACTS_CHANGED')
    world=o['definition'];validate(world);require_native(world)
    integer(o['clock'],'clock');integer(o['facts_revision'],'revision',1)
    if o['clock_domain']!='LOGICAL_MICROSECONDS':raise Invalid('CLOCK_DOMAIN_MISMATCH')
    observed=world['utc_origin_us']+o['clock']
    if not observed<=now_us or now_us-observed>60*S:raise Invalid('STALE_OR_FUTURE_OBSERVATION')
    if type(o['operations']) is not list or not o['operations']:raise Invalid('MISSING_OPERATION_EVIDENCE')
    if type(o['calendar']) is not list or len(o['calendar'])>64:raise Invalid('INVALID_CALENDAR')
    return o


def authority_check(o,a):
    """Return deterministic disposition or None; never infer closure from time."""
    if type(a) is not dict or a.get('dispatchGranted') is not False:raise Invalid('INVALID_AUTHORITY_READ')
    e,op=a['effect'],a['operation'];world=o['definition']
    if type(e['quarantined']) is not bool:raise Invalid('INVALID_AUTHORITY_READ')
    if e['quarantined']:return result('DETERMINISTIC','CONFLICTING_EVIDENCE')
    expected=(world['order_id'],world['shipment_version'])
    if (op['orderId'],op['shipmentVersion'])!=expected or e['currentOperationId']!=op['operationId']:raise Invalid('AUTHORITY_IDENTITY_MISMATCH')
    integer(e['snapshotId'],'snapshot_id',1)
    snapshot=authority_snapshot(o)
    # observedAt naturally advances on a fresh read. Constraints, revisions and
    # identity may not differ; Refresh is a separate trusted native operation.
    if {k:v for k,v in e['snapshot'].items() if k!='observedAt'}!={k:v for k,v in snapshot.items() if k!='observedAt'}:
        return result('RECHECK_REQUIRED','AUTHORITY_REFRESH_REQUIRED')
    found=[];accepted=False;uncertain=False;seen=set()
    for operation in o['operations']:
        b,r=operation['binding'],operation['receipt']
        fields={'operationId':'operation_id','attemptId':'attempt_id','orderId':'order_id',
                'shipmentVersion':'shipment_version','target':'target'}
        if any(r[k]!=b[v] for k,v in fields.items()):raise Invalid('PROVIDER_IDENTITY_MISMATCH')
        if (r['orderId'],r['shipmentVersion'])!=expected or b['payload']!=canonical(world['payload']):raise Invalid('PROVIDER_IDENTITY_MISMATCH')
        if r['operationId'] in seen:raise Invalid('DUPLICATE_OPERATION')
        seen.add(r['operationId'])
        if r['operationId']==op['operationId']:found.append(r)
        state=r['status']
        if state=='ACCEPTED':accepted=True
        elif state!='NOT_ACCEPTED_FINAL' or r['closedForever'] is not True:uncertain=True
    if len(found)!=1:raise Invalid('CURRENT_OPERATION_MISSING')
    current=found[0]
    if any(current[k]!=op[k] for k in ('operationId','attemptId','orderId','shipmentVersion','target')) or op['payload']!=canonical(world['payload']):raise Invalid('AUTHORITY_IDENTITY_MISMATCH')
    if accepted:
        if e['state']=='ACCEPTED' and op['state']=='ACCEPTED' and current['status']=='ACCEPTED' and op['reference']==current['reference']:
            return result('DETERMINISTIC','EXISTING_ACCEPTANCE')
        return result('RECHECK_REQUIRED','ACCEPTANCE_RECONCILIATION_REQUIRED')
    if uncertain or e['state']!='OPEN' or op['state']!='NOT_ACCEPTED_FINAL':return result('DETERMINISTIC','ACCEPTANCE_UNRESOLVED')
    return None


def public_facts(o):
    """Only explicitly observed provenance; never infer it from message text.

    agent_provenance is immutable installer metadata stored with the scenario.
    Message and calendar observation times are scenario minutes, converted here
    exactly once. Undeclared calendar entries are withheld from both branches.
    """
    w=o['definition'];at=o['clock']
    provenance=w.get('agent_provenance',{'messages':{},'changes':{}})
    exact(provenance,'messages changes')
    if type(provenance['messages']) is not dict or type(provenance['changes']) is not dict:raise Invalid('INVALID_PROVENANCE')
    if len(w['messages'])>8:raise Invalid('TOO_MANY_MESSAGES')
    if set(provenance['messages'])- {m['id'] for m in w['messages']}:raise Invalid('UNKNOWN_MESSAGE_PROVENANCE')
    messages=[]
    for m in w['messages']:
        identifier(m['id'])
        if type(m['text']) is not str or not 0<len(m['text'])<=2000:raise Invalid('INVALID_MESSAGE')
        p=provenance['messages'].get(m['id'])
        if p is None:raise Invalid('MESSAGE_PROVENANCE_REQUIRED')
        exact(p,'source_id at_minutes order_link order_id shipment_version')
        identifier(p['source_id']);identifier(p['order_id']);integer(p['shipment_version'],'message_version',1)
        integer(p['at_minutes'],'message_time')
        if p['order_link'] not in {'VERIFIED_CURRENT','VERIFIED_OTHER','UNRESOLVED'}:raise Invalid('INVALID_ORDER_LINK')
        same=(p['order_id'],p['shipment_version'])==(w['order_id'],w['shipment_version'])
        if (p['order_link']=='VERIFIED_CURRENT' and not same) or (p['order_link']=='VERIFIED_OTHER' and same):raise Invalid('MESSAGE_IDENTITY_MISMATCH')
        if p['at_minutes']*M<=at:
            messages.append({'message_id':m['id'],'source_id':p['source_id'],'at':p['at_minutes']*M,
                             'order_link':p['order_link'],'text':m['text']})
    changes=[];ids=set()
    for c in o['calendar']:
        exact(c,'event_id at kind target value');change=Change(**c);change.validate();identifier(c['event_id'])
        if c['event_id'] in ids:raise Invalid('DUPLICATE_CALENDAR_EVENT')
        ids.add(c['event_id'])
        p=provenance['changes'].get(c['event_id'])
        if p is None:continue
        exact(p,'observed_at_minutes');integer(p['observed_at_minutes'],'change_observation')
        observed=p['observed_at_minutes']*M
        if observed<=at<=c['at']:changes.append(c|{'observed_at':observed})
    if set(provenance['changes'])-ids:raise Invalid('UNKNOWN_CHANGE_PROVENANCE')
    mode='CONTEXT_REQUIRED' if w['preference']=='context' else 'STRUCTURED'
    preference={'cheapest':'CHEAPEST_ON_TIME','fastest':'EARLIEST_ALLOWED','context':None}[w['preference']]
    return {'payload':deepcopy(w['payload']),'budget':w['budget'],'deadline':w['deadline']*M,
            'inventory_expires':w['inventory_expires']*M,'offer_until':w['offer_until_us']-w['utc_origin_us'],
            'preference_mode':mode,'structured_preference':preference,'messages':messages,
            'known_changes':changes,'options':{t:{'cost':x['cost'],'available_at':x['available_at']*M,
                'queue_duration':x['queue_minutes']*M,'travel_duration':x['travel_minutes']*M} for t,x in w['options'].items()}}


def outcomes(o,facts,mode):
    at=o['clock'];results=[]
    known=[Change(**{k:v for k,v in c.items() if k!='observed_at'}) for c in facts['known_changes']]
    if mode=='WITH_TRIALS':
        world=deepcopy(o['definition'])
        # Authority and every observed operation have already proven closure.
        # Do not carry the scenario's original_status label over live evidence.
        world['original_status']='NOT_ACCEPTED_FINAL'
        results=[preview(world,a,at,known) for a in OPTIONS]
    else:
        for a,target in (('RETRY_A','A'),('FAILOVER_B','B')):
            offer=facts['options'][target];ready=max(at,offer['available_at'])+offer['queue_duration']
            for c in sorted(known,key=lambda c:(c.at,c.event_id)):
                if c.at<=ready and c.target in {target,'*'}:ready+=c.value
            results.append({'action':a,'cost':offer['cost'],'accepted_at':ready,'arrival':ready+offer['travel_duration']})
    allowed=[r for r in results if (mode!='WITH_TRIALS' or r['state']=='DELIVERED_SIMULATED')
             and r['accepted_at'] is not None and r['arrival'] is not None
             and at<=r['accepted_at']<min(facts['inventory_expires'],facts['offer_until'])
             and r['accepted_at']<=r['arrival']<=min(facts['deadline'],at+30*M) and r['cost']<=facts['budget']]
    return results,allowed


def authority_stamp(a):
    return fingerprint({'effect':a['effect'],'operation':a['operation']})


def review_authority_stamp(a):
    """Ignore only observation renewal; retain every operational/material field.

    A human preview is subsequently bound to the CURRENT full snapshot ID.
    Inference validation continues using authority_stamp without exclusions.
    """
    effect=deepcopy(a['effect'])
    del effect['snapshotId'];del effect['snapshot']['observedAt']
    return fingerprint({'effect':effect,'operation':a['operation']})


def prepare(observation,authority,context_id,*,now_us,gate_state,mode='WITH_TRIALS',response_contract=PROPOSAL_CONTRACT):
    try:
        identifier(context_id)
        if type(response_contract) is not str or response_contract not in RESPONSE_CONTRACTS:raise Invalid('INVALID_RESPONSE_CONTRACT')
        if type(mode) is not str or mode not in MODES:raise Invalid('INVALID_MODE')
        o=observation_copy(observation,now_us);a=parse(canonical(authority))
        if gate_state!='OPEN':return result('RECHECK_REQUIRED','RECOVERY_IN_PROGRESS')
        disposition=authority_check(o,a)
        if disposition:return disposition
        facts=public_facts(o)
        if sensitive(facts):return result('ERROR','SENSITIVE_INPUT')
        trials,allowed=outcomes(o,facts,mode)
        if not allowed:return result('DETERMINISTIC','NO_FEASIBLE_OPTION')
        catalog=[{'id':k,'kind':'fact'} for k in ('fact:order','fact:policy','option:A','option:B')]
        catalog += [{'id':m['message_id'],'kind':'message'} for m in facts['messages']]
        catalog += [{'id':c['event_id'],'kind':'known_change'} for c in facts['known_changes']]
        evidence=[]
        for operation in o['operations']:
            r=operation['receipt'];source='evidence:'+r['receiptId'];identifier(source)
            evidence.append({'source_id':source,**{k:r[k] for k in ('operationId','attemptId','target','status','closedForever')}})
            catalog.append({'id':source,'kind':'evidence'})
        exposed=[]
        if mode=='WITH_TRIALS':
            for t in trials:
                if len(t['trace'])>30:raise Invalid('TOO_MANY_TRIAL_EVENTS')
                source='trial:'+OPTIONS[t['action']];catalog.append({'id':source,'kind':'trial'})
                exposed.append({'trial_id':source,'option_id':OPTIONS[t['action']],'observations':t})
        if len({s['id'] for s in catalog})!=len(catalog):raise Invalid('SOURCE_ID_COLLISION')
        valid=min(o['clock']+30*S,facts['offer_until'],facts['inventory_expires'])
        wire={'schema_version':'chronos.agent-input.v2','context_id':context_id,'order_id':o['definition']['order_id'],
              'shipment_version':o['definition']['shipment_version'],'state_revision':o['facts_revision'],
              'policy_revision':a['effect']['snapshot']['policyRevision'],'observation_id':o['observation_id'],
              'facts_id':o['facts_id'],'clock_kind':'relative_microseconds','ticks_per_minute':M,
              'utc_origin_us':o['definition']['utc_origin_us'],'observed_at':o['clock'],'valid_until':valid,
              'trial_horizon':30*M,'facts':facts,'evidence':evidence,'source_catalog':catalog,
              'trial_mode':mode,'trial_status':'COMPLETE' if mode=='WITH_TRIALS' else 'NOT_REQUESTED','trials':exposed}
        wire['context_digest']=fingerprint(wire)
        # Identities and receipt references are added after the facts projection.
        if sensitive(wire):return result('ERROR','SENSITIVE_INPUT')
        text=model_input(wire)
        if len(text.encode('utf-8'))>65536:raise Invalid('CONTEXT_TOO_LARGE')
        record={'wire':wire,'authority_stamp':authority_stamp(a),'started_us':now_us,
                'deadline_us':min(now_us+30*S,o['definition']['utc_origin_us']+valid),
                'review_deadline_us':min(now_us+300*S,o['definition']['utc_origin_us']+min(facts['offer_until'],facts['inventory_expires'])),
                'review_authority_stamp':review_authority_stamp(a),'authority_snapshot_id':a['effect']['snapshotId'],
                'facts_digest':fingerprint(facts),
                'available':[{k:r[k] for k in ('action','cost','accepted_at','arrival')} for r in allowed]}
        if response_contract==EXTRACTION_CONTRACT:
            record['response_contract']=response_contract
            record['extraction_binding']=BoundContext.create(wire,record['available']).binding_sha256
        if now_us>=record['deadline_us']:return result('RECHECK_REQUIRED','CONTEXT_EXPIRED')
        return result('READY','READY_FOR_INFERENCE',input_json=text,record=record)
    except FAILURES as exc:
        return result('ERROR',str(exc) if type(exc) is Invalid else 'INVALID_INPUT')


def response_contract_of(record):
    value=record.get('response_contract',PROPOSAL_CONTRACT)
    if type(value) is not str or value not in RESPONSE_CONTRACTS:raise Invalid('INVALID_RESPONSE_CONTRACT')
    if value==EXTRACTION_CONTRACT:
        bound=BoundContext.create(record['wire'],record['available'])
        bound.checked(record.get('extraction_binding'))
    elif 'extraction_binding' in record:raise Invalid('RESPONSE_CONTRACT_MISMATCH')
    return value


def validate_explanation(receipt, record, proposal):
    """Check an archived FINISH receipt, not current feasibility or authority.

    Only the trusted native ledger supplies these arguments. A digest is binding,
    not authentication. No simulation, model call, retry or reranking of live data.
    Older decisions have no receipt; callers must preserve that absence explicitly.
    """
    keys={'schema','context_digest','proposal_digest','source_contract','selection_basis',
          'selection_available','validation_observed_at','validation_available',
          'validation_trials','finished_at_us'}
    if type(receipt) is not dict or set(receipt)!=keys:raise Invalid('INVALID_EXPLANATION')
    if receipt['schema']!='chronos.decision-explanation.v1':raise Invalid('INVALID_EXPLANATION')
    wire=record['wire'];facts=wire['facts'];selected=response_contract_of(record)
    if (receipt['context_digest']!=wire['context_digest'] or
        receipt['proposal_digest']!=fingerprint(proposal) or
        receipt['source_contract']!=selected):raise Invalid('EXPLANATION_BINDING_MISMATCH')
    expected_basis='BOUND_PREPARE' if selected==EXTRACTION_CONTRACT else 'FRESH_FINISH'
    if receipt['selection_basis']!=expected_basis:raise Invalid('EXPLANATION_BASIS_MISMATCH')
    at,finished=receipt['validation_observed_at'],receipt['finished_at_us']
    for n in (at,finished):
        if type(n) is not int or not 0<=n<=2**53-1:raise Invalid('INVALID_EXPLANATION_TIME')
    if not (wire['observed_at']<=at<wire['valid_until'] and
            record['started_us']<=wire['utc_origin_us']+at<=finished<record['deadline_us']):
        raise Invalid('INVALID_EXPLANATION_TIME')

    def available(rows, observed):
        if type(rows) is not list or len(rows)>2:raise Invalid('INVALID_EXPLANATION_OPTIONS')
        actions=set()
        for row in rows:
            if type(row) is not dict or set(row)!={'action','cost','accepted_at','arrival'}:
                raise Invalid('INVALID_EXPLANATION_OPTIONS')
            action=row['action']
            if type(action) is not str or action not in OPTIONS or action in actions:
                raise Invalid('INVALID_EXPLANATION_OPTIONS')
            actions.add(action)
            for key in ('cost','accepted_at','arrival'):
                if type(row[key]) is not int or not 0<=row[key]<=2**53-1:
                    raise Invalid('INVALID_EXPLANATION_OPTIONS')
            if row['cost']!=facts['options'][action[-1]]['cost']:
                raise Invalid('EXPLANATION_COST_MISMATCH')
            if row['arrival']!=row['accepted_at']+facts['options'][action[-1]]['travel_duration']:
                raise Invalid('EXPLANATION_TIME_MISMATCH')
            if not (observed<=row['accepted_at']<min(facts['inventory_expires'],facts['offer_until'])
                    and row['accepted_at']<=row['arrival']<=min(facts['deadline'],observed+30*M)
                    and row['cost']<=facts['budget']):raise Invalid('INVALID_EXPLANATION_OPTIONS')
        return rows

    fresh=available(receipt['validation_available'],at)
    selection=available(receipt['selection_available'],wire['observed_at'] if expected_basis=='BOUND_PREPARE' else at)
    if selection!=(record['available'] if expected_basis=='BOUND_PREPARE' else fresh):
        raise Invalid('EXPLANATION_SELECTION_MISMATCH')
    # Recheck the already recorded comparison against its archived inputs only.
    # This never selects another action or renews the original decision.
    check(canonical(proposal),wire,selection)
    check(canonical(proposal),wire,fresh)
    trials=receipt['validation_trials']
    if type(trials) is not list:raise Invalid('INVALID_EXPLANATION_TRIALS')
    if wire['trial_mode']=='WITHOUT_TRIALS_ABLATION':
        if trials:raise Invalid('INVALID_EXPLANATION_TRIALS')
    else:
        if len(trials)!=2:raise Invalid('INVALID_EXPLANATION_TRIALS')
        seen=set();derived=[]
        for row in trials:
            if type(row) is not dict or set(row)!={'action','state','reason','cost','accepted_at','arrival','rejected_at'}:
                raise Invalid('INVALID_EXPLANATION_TRIALS')
            action=row['action'];state=row['state'];reason=row['reason']
            if type(action) is not str or action not in OPTIONS or action in seen:
                raise Invalid('INVALID_EXPLANATION_TRIALS')
            seen.add(action)
            if (type(state) is not str or state not in {'QUEUED','BLOCKED','NOT_ACCEPTED_FINAL','ACCEPTED','DELIVERED_SIMULATED'}
                or type(reason) is not str or re.fullmatch(r'[A-Z0-9_]{0,128}',reason) is None):
                raise Invalid('INVALID_EXPLANATION_TRIALS')
            for key in ('cost','accepted_at','arrival','rejected_at'):
                value=row[key]
                if value is None and key!='cost':continue
                if type(value) is not int or not 0<=value<=2**53-1:raise Invalid('INVALID_EXPLANATION_TRIALS')
            offer=facts['options'][action[-1]]
            if row['cost']!=offer['cost']:raise Invalid('EXPLANATION_COST_MISMATCH')
            accepted,arrival,rejected=row['accepted_at'],row['arrival'],row['rejected_at']
            if state in {'ACCEPTED','DELIVERED_SIMULATED'}:
                if (reason or rejected is not None or accepted is None or arrival is None or
                    not at<=accepted<min(facts['offer_until'],facts['inventory_expires']) or
                    arrival!=accepted+offer['travel_duration'] or arrival>facts['deadline'] or row['cost']>facts['budget']):
                    raise Invalid('EXPLANATION_STATE_MISMATCH')
                if (state=='DELIVERED_SIMULATED')!=(arrival<=at+30*M):
                    raise Invalid('EXPLANATION_STATE_MISMATCH')
            elif state=='NOT_ACCEPTED_FINAL':
                if accepted is not None or arrival is not None or rejected is None or not at<=rejected<=at+30*M:
                    raise Invalid('EXPLANATION_STATE_MISMATCH')
                # Same rejection precedence as the simulator, using its recorded
                # admission instant. No queue replay or invented rejection time.
                expected=('OFFER_EXPIRED' if rejected>=facts['offer_until'] else
                          'INVENTORY_EXPIRED' if rejected>=facts['inventory_expires'] else
                          'OVER_BUDGET' if row['cost']>facts['budget'] else
                          'DEADLINE_EXCEEDED' if rejected+offer['travel_duration']>facts['deadline'] else None)
                if reason!=expected or expected is None:raise Invalid('EXPLANATION_STATE_MISMATCH')
            elif state=='QUEUED':
                if reason or accepted is not None or arrival is not None or rejected is not None:
                    raise Invalid('EXPLANATION_STATE_MISMATCH')
            else:
                # FINISH's independently closed original attempt cannot produce
                # a PREVIOUS_ATTEMPT_UNRESOLVED trial in the current rule version.
                raise Invalid('EXPLANATION_STATE_MISMATCH')
            if row['state']=='DELIVERED_SIMULATED' and row['accepted_at'] is not None and row['arrival'] is not None:
                if (at<=row['accepted_at']<min(facts['inventory_expires'],facts['offer_until'])
                    and row['accepted_at']<=row['arrival']<=min(facts['deadline'],at+30*M)
                    and row['cost']<=facts['budget']):
                    derived.append({k:row[k] for k in ('action','cost','accepted_at','arrival')})
        if sorted(derived,key=lambda x:x['action'])!=sorted(fresh,key=lambda x:x['action']):
            raise Invalid('EXPLANATION_TRIALS_MISMATCH')
    if sensitive(receipt) or len(canonical(receipt).encode('utf-8'))>4096:raise Invalid('INVALID_EXPLANATION')
    return deepcopy(receipt)


def explanation_receipt(record, fresh, proposal, now_us):
    """Capture the actual successful validation snapshots before they are lost."""
    selected=response_contract_of(record)
    rows=[]
    for trial in fresh['wire']['trials']:
        observed=trial['observations']
        row={k:observed[k] for k in ('action','state','reason','cost','accepted_at','arrival')}
        row['rejected_at']=None
        if row['state']=='NOT_ACCEPTED_FINAL':
            events=[event[0] for event in observed['trace'] if event[1]=='rejected:'+row['reason']]
            if len(events)!=1:raise Invalid('EXPLANATION_REJECTION_TIME_MISSING')
            row['rejected_at']=events[0]
        rows.append(row)
    receipt=dict(schema='chronos.decision-explanation.v1',context_digest=record['wire']['context_digest'],
        proposal_digest=fingerprint(proposal),source_contract=selected,
        selection_basis='BOUND_PREPARE' if selected==EXTRACTION_CONTRACT else 'FRESH_FINISH',
        selection_available=deepcopy(record['available'] if selected==EXTRACTION_CONTRACT else fresh['available']),
        validation_observed_at=fresh['wire']['observed_at'],validation_available=deepcopy(fresh['available']),
        validation_trials=rows,finished_at_us=now_us)
    return validate_explanation(receipt,record,proposal)


def finish(record,response_text,observation,authority,*,now_us,gate_state,provider_status='ok'):
    """Pure validator only; caller MUST atomically consume its native record once."""
    try:
        record=parse(canonical(record));wire=record['wire'];integer(now_us,'utc_now');response_contract=response_contract_of(record)
        if now_us<record['started_us']:return result('ERROR','INVALID_CLOCK')
        if now_us>=record['deadline_us'] or provider_status=='timeout':return result('ERROR','MODEL_TIMEOUT')
        if provider_status!='ok':return result('ERROR','MODEL_REFUSAL' if provider_status=='refusal' else 'MODEL_ERROR')
        fresh=prepare(observation,authority,wire['context_id'],now_us=now_us,gate_state=gate_state,mode=wire['trial_mode'],response_contract=response_contract)
        if fresh['status']!='READY':return result('RECHECK_REQUIRED',fresh['code'])
        f=fresh['record'];current=f['wire']
        if current['utc_origin_us']+current['observed_at']<record['started_us']:return result('RECHECK_REQUIRED','FRESH_READ_REQUIRED')
        if current['observed_at']<wire['observed_at']:return result('ERROR','INVALID_CLOCK')
        if now_us>=wire['utc_origin_us']+wire['valid_until']:return result('ERROR','CONTEXT_EXPIRED')
        if (current['facts_id']!=wire['facts_id'] or f['facts_digest']!=record['facts_digest'] or
            f['authority_stamp']!=record['authority_stamp']):return result('REJECTED','STALE_CONTEXT')
        # Use outcomes from the validated, frozen fresh observation. Never
        # revisit a mutable caller-owned observation after checking its digest.
        if response_contract==EXTRACTION_CONTRACT:
            # Assemble from the original bound outcomes, never silently rerank
            # against later observations. The existing fresh validator may reject.
            bound=BoundContext.create(wire,record['available'])
            assembled=assemble(response_text,bound,record['extraction_binding'])
            response_text=canonical(assembled['proposal'])
        response=check(response_text,wire,f['available'])
        return result('VALIDATED_HOLD' if response['action']=='HOLD' else 'VALIDATED_PROPOSAL',
                      'SEMANTICS_AND_HUMAN_REVIEW_REQUIRED',proposal=response,
                      explanation=explanation_receipt(record,f,response,now_us))
    except FAILURES as exc:
        # E1 has its own exception class. Keep only bounded diagnostic codes;
        # never expose arbitrary provider text, exception arguments or subclasses.
        code='INVALID_PROPOSAL'
        if type(exc) is Invalid:
            code=str(exc)
        elif type(exc) is ExtractionInvalid and str(exc) in EXTRACTION_DIAGNOSTIC_CODES:
            code=str(exc)
        return result('ERROR',code)


def review(decision,observation,authority,*,now_us,gate_state,generation):
    """Recheck a trusted, immutable COMPLETED ledger entry for human preview.

    This does not finish inference, renew its deadline, authenticate a person or
    reserve an effect. The caller must load the entry from the native ledger,
    bind the installed runtime, and atomically bind the returned snapshot ID to
    a new short-lived preview. Never accept this entry from a browser or model.
    """
    try:
        d=parse(canonical(decision));integer(now_us,'utc_now');identifier(generation)
        if d['state']!='COMPLETED':return result('RECHECK_REQUIRED','DECISION_NOT_COMPLETED')
        if d['generation']!=generation:return result('RECHECK_REQUIRED','RUNTIME_GENERATION_CHANGED')
        if d['mode']!='WITH_TRIALS':return result('REJECTED','ABLATION_NOT_ACTIONABLE')
        r=d['result']
        # Historical precontrols have no model context and can never be consent.
        if r['status']!='VALIDATED_PROPOSAL':return result('REJECTED','DECISION_NOT_ACTIONABLE')
        p=d['prepared'];record=p['record'];wire=record['wire'];response_contract=response_contract_of(record)
        if r.get('dispatch_authorized') is not False:raise Invalid('RESULT_CANNOT_AUTHORIZE')
        if (r.get('code')!='SEMANTICS_AND_HUMAN_REVIEW_REQUIRED' or
            set(r)-{'status','code','dispatch_authorized','proposal','runtime_generation','explanation'}):
            raise Invalid('INVALID_VALIDATED_RESULT')
        if r.get('runtime_generation',generation)!=generation:raise Invalid('DECISION_BINDING_MISMATCH')
        if (p['status']!='READY' or p['runtime_generation']!=generation or
            (d['requestId'],d['orderId'],d['shipmentVersion'],d['mode'])!=
            (wire['context_id'],wire['order_id'],wire['shipment_version'],wire['trial_mode'])):
            raise Invalid('DECISION_BINDING_MISMATCH')
        for k in ('createdUS','deadlineUS','completedUS'):integer(d[k],k)
        for k in ('started_us','deadline_us','review_deadline_us'):integer(record[k],k)
        # Completion must have been committed within its original inference
        # window. A new observation can never rehabilitate a timed-out result.
        if not (record['started_us']<=d['createdUS']<=d['completedUS']<d['deadlineUS']==record['deadline_us']
                <=record['started_us']+30*S):raise Invalid('INVALID_COMPLETION_WINDOW')
        if now_us<d['completedUS']:raise Invalid('INVALID_CLOCK')
        if not record['deadline_us']<=record['review_deadline_us']<=min(record['started_us']+300*S,
                wire['utc_origin_us']+min(wire['facts']['inventory_expires'],wire['facts']['offer_until'])):
            raise Invalid('INVALID_REVIEW_WINDOW')
        if now_us>=record['review_deadline_us']:return result('RECHECK_REQUIRED','REVIEW_EXPIRED')
        if wire['context_digest']!=fingerprint({k:v for k,v in wire.items() if k!='context_digest'}):
            raise Invalid('CONTEXT_CHANGED')
        fresh=prepare(observation,authority,wire['context_id'],now_us=now_us,gate_state=gate_state,mode=d['mode'],response_contract=response_contract)
        if fresh['status']!='READY':return result('RECHECK_REQUIRED',fresh['code'])
        f=fresh['record'];current=f['wire']
        if current['utc_origin_us']+current['observed_at']<d['completedUS']:
            return result('RECHECK_REQUIRED','FRESH_READ_REQUIRED')
        if (current['facts_id']!=wire['facts_id'] or f['facts_digest']!=record['facts_digest'] or
            f['review_authority_stamp']!=record['review_authority_stamp'] or
            f['authority_snapshot_id']<record['authority_snapshot_id']):return result('REJECTED','STALE_CONTEXT')
        # A still-valid offer is insufficient if its queue can only accept after
        # the original human window. Do not silently choose a different option.
        available=[item for item in f['available'] if current['utc_origin_us']+item['accepted_at']<record['review_deadline_us']]
        proposal=check(canonical(r['proposal']),wire,available)
        if proposal['action']=='HOLD':return result('REJECTED','DECISION_NOT_ACTIONABLE')
        if 'explanation' in r:
            receipt=validate_explanation(r['explanation'],record,r['proposal'])
            if not d['createdUS']<=receipt['finished_at_us']<=d['completedUS']:
                raise Invalid('INVALID_EXPLANATION_TIME')
        # Hash public, immutable semantics, not claims, credentials or the
        # moving observation clock. Re-reading cannot silently change consent.
        digest=fingerprint({'requestId':d['requestId'],'generation':generation,'completedUS':d['completedUS'],
                            'context_digest':wire['context_digest'],'result':r,'reviewDeadlineUS':record['review_deadline_us']})
        return result('REVIEWABLE','HUMAN_PREVIEW_REQUIRED',proposal=proposal,
                      binding={'decisionId':d['requestId'],'decisionDigest':digest,'orderId':d['orderId'],
                               'shipmentVersion':d['shipmentVersion'],'expectedSnapshotId':f['authority_snapshot_id'],
                               'option':proposal['action'],'generation':generation,'reviewDeadlineUS':record['review_deadline_us']})
    except FAILURES as exc:
        return result('ERROR',str(exc) if type(exc) is Invalid else 'INVALID_REVIEW_INPUT')
