"""Read-only, typed explanation supplements from host-owned records.

These functions do not authenticate inputs. The native caller must own the
reads and preserve actor/case/runtime bindings. They never query a provider,
create a preview, claim inference, dispatch or change authority.
"""
from copy import deepcopy
from . import renderer_v1 as v1
if '_chronos_supplement_dependencies' in globals():
    agent,Destinations,Change = _chronos_supplement_dependencies
else:
    from chronos_agent import contract as agent
    from chronos_simulation.store import Destinations
    from chronos_simulation.workflow import Change

c=v1.c

def historical_change(current_json,previous_json,scope,*,projector,receipt_validator):
    current=c.parse(current_json);previous=c.parse(previous_json)
    # Both records must pass the same historical projector and receipt check.
    catalogs=[]
    for d,raw in ((previous,previous_json),(current,current_json)):
        v1.need(d['orderId']==scope['case_id'] and d['shipmentVersion']==scope['shipment_version'],'HISTORY_CASE_MISMATCH')
        catalogs.append(v1.build(raw,d['requestId'],scope,projector=projector,receipt_validator=receipt_validator,
            generation=d['generation'],revision=1,conversation_revision=1).checked())
    v1.need(previous['requestId']!=current['requestId'] and previous['completedUS']<=current['createdUS'],'HISTORY_ORDER_INVALID')
    p,curr=(x['prepared']['record']['wire'] for x in (previous,current))
    v1.need(p['utc_origin_us']==curr['utc_origin_us'] and p['observed_at']<=curr['observed_at'],'HISTORY_CLOCK_MISMATCH')
    old=previous['result']['proposal'];new=current['result']['proposal']
    def label(proposal):return 'HOLD' if proposal['action']=='HOLD' else 'option '+proposal['action'][-1]
    text='The earlier recorded proposal was '+label(old)+'; the later recorded proposal was '+label(new)+'. '
    text+='The recorded priority '+('stayed '+str(new['interpreted_preference']) if old['interpreted_preference']==new['interpreted_preference'] else 'also changed')+'.'
    changes=[]
    before={x['event_id']:x for x in p['facts']['known_changes']}
    for change in curr['facts']['known_changes']:
        if change['event_id'] not in before:
            changes.append(deepcopy(change))
        elif change!=before[change['event_id']]:
            raise c.Invalid('HISTORY_EVENT_REWRITTEN')
    # Bound output, preserving a visible count instead of claiming full listing.
    if len(changes)>8:raise c.Invalid('HISTORY_CHANGE_LIMIT')
    for change in changes:
        v1.need(change['kind']=='DELAY_QUEUE' and change['target'] in {'A','B','*'},'UNSUPPORTED_HISTORY_CHANGE')
        text+=' The later snapshot additionally recorded '+v1.minute(change['value'])+' of queue delay for '+('both options' if change['target']=='*' else 'option '+change['target'])+'.'
    available=[]
    for d in (previous,current):
        receipt=d['result'].get('explanation');available.append(None if receipt is None else receipt['selection_available'])
    for i,rows in enumerate(available):
        if rows is not None:
            text+=' '+('Earlier' if i==0 else 'Later')+' eligible predictions: '+('; '.join(r['action'][-1]+' at '+v1.minute(r['arrival'])+' / '+str(r['cost'])+' synthetic units' for r in rows) or 'none')+'.'
    text+=' These are archived observations and predictions. They do not prove a dispatch, and a recorded change alone is not proof that no other factor affected the decision.'
    source=dict(id='decision-change',kind='VALIDATED_HISTORICAL_COMPARISON',decision_id=current['requestId'],
        previous_decision_id=previous['requestId'],previous_digest=catalogs[0]['decision_digest'],
        decision_digest=catalogs[1]['decision_digest'],previous_preference=old['interpreted_preference'],
        current_preference=new['interpreted_preference'],newly_observed_changes=changes,
        previous_available=available[0],current_available=available[1])
    return text,source

REVIEW_REASONS={
    'ABLATION_NOT_ACTIONABLE':'the comparison-only mode uses analytical estimates without executable trial validation',
    'STALE_CONTEXT':'the case facts or review binding changed',
    'REVIEW_EXPIRED':'the original human-review window has expired',
    'RANKING_MISMATCH':'the recorded option no longer ranks first under the recorded priority',
    'OPTION_NOT_FEASIBLE':'the recorded option no longer meets the current checked constraints',
    'RUNTIME_GENERATION_CHANGED':'the runtime generation changed',
    'AUTHORITY_REFRESH_REQUIRED':'the authoritative snapshot needs a separate refresh',
    'EXISTING_ACCEPTANCE':'an existing acceptance blocks another submission',
    'ACCEPTANCE_RECONCILIATION_REQUIRED':'acceptance evidence must first be reconciled',
    'ACCEPTANCE_UNRESOLVED':'acceptance remains unresolved',
    'CONFLICTING_EVIDENCE':'the current evidence conflicts',
    'NO_FEASIBLE_OPTION':'no eligible option remains',
    'DECISION_NOT_ACTIONABLE':'the recorded decision is not executable',
    'RECOVERY_IN_PROGRESS':'a recovery is already in progress',
}

def current_review(decision,observation,authority,*,now_us,gate_state,generation):
    # STALE_CONTEXT alone is not proof that a read belongs to this case.
    # Bind both stores before deriving any explanatory source, even on expiry.
    observed=agent.observation_copy(observation,now_us)
    expected=(decision['orderId'],decision['shipmentVersion'])
    v1.need((observed['definition']['order_id'],observed['definition']['shipment_version'])==expected,'REVIEW_CASE_MISMATCH')
    v1.need(type(authority) is dict and type(authority.get('effect')) is dict and type(authority.get('operation')) is dict,'INVALID_REVIEW_AUTHORITY')
    snapshot=authority['effect'].get('snapshot');v1.need(type(snapshot) is dict,'INVALID_REVIEW_AUTHORITY')
    for source in (snapshot,authority['operation']):
        v1.need((source.get('orderId'),source.get('shipmentVersion'))==expected,'REVIEW_CASE_MISMATCH')
    agent.authority_check(observed,authority)
    result=agent.review(decision,observation,authority,now_us=now_us,gate_state=gate_state,generation=generation)
    code=result['code'];status=result['status']
    v1.need(result.get('dispatch_authorized') is False,'REVIEW_CANNOT_AUTHORIZE')
    if status=='REVIEWABLE' and code=='HUMAN_PREVIEW_REQUIRED':
        text='At this read, the recorded proposal remains eligible for a separate human review. This does not create, renew or confirm a preview, and does not establish that an earlier preview is still valid.'
    elif code in REVIEW_REASONS and status in {'REJECTED','RECHECK_REQUIRED','ERROR'}:
        text='The recorded proposal cannot currently proceed to confirmation because '+REVIEW_REASONS[code]+'. An earlier preview must not be reused to bypass this check. Resolve the stated condition and obtain a fresh evaluation and preview as required.'
    else:raise c.Invalid('CURRENT_REVIEW_UNAVAILABLE')
    text+=' This check does not select a new best option or change the historical decision.'
    source=dict(id='current-review',kind='CURRENT_READ_ONLY_REVALIDATION',decision_id=decision['requestId'],
        observed_us=now_us,status=status,code=code,input_digest=c.digest(dict(decision=decision,observation=observation,authority=authority,
        now_us=now_us,gate_state=gate_state,generation=generation)),dispatch_authorized=False)
    return text,source

def simulator_result(decision,observation,current_operation,*,now_us):
    """Verify actual simulator operation result, never branch trial output."""
    o=agent.observation_copy(observation,now_us);world=o['definition']
    v1.need((world['order_id'],world['shipment_version'])==(decision['orderId'],decision['shipmentVersion']),'SIMULATOR_CASE_MISMATCH')
    v1.need(type(current_operation) is dict and current_operation.get('code')=='DECISION_OPERATION_RECORDED','CURRENT_OPERATION_REQUIRED')
    op=current_operation['operation']
    rows=[x for x in o['operations'] if x['binding']['operation_id']==op['operationId'] and x['binding']['attempt_id']==op['attemptId']]
    v1.need(len(rows)==1,'SIMULATOR_OPERATION_MISMATCH');row=rows[0];binding=row['binding']
    Destinations._binding(binding)
    v1.need((binding['order_id'],binding['shipment_version'],binding['payload'])==(decision['orderId'],decision['shipmentVersion'],agent.canonical(world['payload'])),'SIMULATOR_BINDING_MISMATCH')
    rebuilt=Destinations._rebuild(world,[Change(**x) for x in o['calendar']],binding,row['start'],row['closed_at'],o['clock']).result()
    v1.need(c.canonical(rebuilt)==c.canonical(row['result']),'SIMULATOR_RESULT_CHANGED')
    receipt=Destinations._receipt(binding,rebuilt)
    v1.need(receipt==row['receipt'],'SIMULATOR_RECEIPT_CHANGED')
    v1.need(receipt['status']==op['state'] and receipt['reference']==op['reference'],'SIMULATOR_AUTHORITY_DISAGREES')
    state=rebuilt['state']
    if state=='DELIVERED_SIMULATED':
        text='The owned simulator records DELIVERED_SIMULATED for this exact operation. Its simulated arrival was '+v1.minute(rebuilt['arrival'])+' on the case timeline. This is a laboratory result, not a physical delivery confirmation; do not tell a real customer that a parcel arrived on this basis.'
    elif state=='ACCEPTED':text='The owned simulator records acceptance for this exact operation, but not yet a simulated delivery.'
    elif state=='NOT_ACCEPTED_FINAL':text='The owned simulator records final non-acceptance for this exact operation. This does not authorize another attempt.'
    else:text='The owned simulator does not record a settled acceptance or delivery for this operation at this read.'
    if op['quarantined']:text+=' The authority read is quarantined; this simulator observation cannot settle that conflict or authorize an action.'
    source=dict(id='simulator-result',kind='OWNED_SIMULATOR_OPERATION_RESULT',decision_id=decision['requestId'],
        operation_id=op['operationId'],attempt_id=op['attemptId'],state=state,
        arrival=rebuilt['arrival'],observed_at=o['clock'],observation_digest=o['observation_id'],
        result_digest=c.digest(rebuilt),time_unit='relative_microseconds',physical_delivery=False)
    return text,source


def stable_sources(catalog,*,review_inputs,simulator_inputs):
    """Project already revalidated inputs, retaining material facts, not read ticks.

    A host must rebuild the catalog from fresh reads first. This is no cache and
    may never be used to reuse a stale read. Timed legacy source shapes remain
    accepted for replay. Scope/namespace/operation/claim binding stays separate.
    """
    record=catalog.checked();sources=record['source_records']
    if 'current-review' in sources:
        v1.need(review_inputs is not None,'REVIEW_INPUTS_REQUIRED')
        i=review_inputs;o=agent.observation_copy(i['observation'],i['now_us'])
        s=sources['current-review']
        semantic=dict(decision_digest=record['decision_digest'],case_id=record['scope']['case_id'],
            shipment_version=record['scope']['shipment_version'],generation=i['generation'],gate_state=i['gate_state'],
            authority=i['authority'],facts_id=o['facts_id'],facts_revision=o['facts_revision'],
            public_facts=agent.public_facts(o),status=s['status'],code=s['code'])
        sources['current-review']={k:v for k,v in s.items() if k not in {'observed_us','input_digest'}}|dict(
            kind='CURRENT_REVALIDATION_RESULT',semantic_digest=c.digest(semantic))
    if 'simulator-result' in sources:
        v1.need(simulator_inputs is not None,'SIMULATOR_INPUTS_REQUIRED')
        i=simulator_inputs;o=agent.observation_copy(i['observation'],i['now_us']);s=sources['simulator-result']
        if s['state']=='DELIVERED_SIMULATED':
            v1.need(type(s['arrival']) is int and s['arrival']<=o['clock'],'SIMULATOR_FUTURE_DELIVERY')
        material=dict(case_id=record['scope']['case_id'],shipment_version=record['scope']['shipment_version'],
            facts_id=o['facts_id'],facts_revision=o['facts_revision'],public_facts=agent.public_facts(o),
            operation_id=s['operation_id'],attempt_id=s['attempt_id'],state=s['state'],arrival=s['arrival'],result_digest=s['result_digest'])
        sources['simulator-result']={k:v for k,v in s.items() if k not in {'observed_at','observation_digest'}}|dict(
            kind='OWNED_SIMULATOR_RESULT',semantic_digest=c.digest(material))
    return record
