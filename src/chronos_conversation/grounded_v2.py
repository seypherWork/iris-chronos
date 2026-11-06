"""Explicit C2 v2 adapter. Host-owned reads only, never browser/model authority.

Versioned alongside the frozen v1 adapter, sharing the transactional ledger.
New sources have closed shapes. Digests bind content, not authentication.
"""
from copy import deepcopy
import re
from . import contract as c, grounded as legacy
if '_chronos_grounded_v2_dependencies' in globals():
    g, = _chronos_grounded_v2_dependencies
else:
    from chronos_grounding import renderer_v2 as g

SCHEMA=g.PLAN_SCHEMA
CATALOG_FIELDS=legacy.CATALOG_FIELDS
CONTEXT_EXTRA=legacy.CONTEXT_EXTRA
base_context=legacy.base_context
with_conversation_revision=legacy.with_conversation_revision
BASE_SOURCES={'decision','finish','current-operation','current-read-missing'}
EXTRA_SOURCES={'chat-policy','chat-effect','decision-change','current-review','simulator-result','timing','case-progress'}

def need(value,code='INVALID_GROUNDED_SOURCE'):
    if not value:raise c.Invalid(code)

def sha(value):need(type(value) is str and re.fullmatch('[0-9a-f]{64}',value) is not None)
def ticks(value):need(type(value) is int and 0<=value<=2**53-1)
def preference(value):need(type(value) is str and value in (set(g.PREFERENCES)|{'UNRESOLVED'}))

def option_rows(rows):
    if rows is None:return
    need(type(rows) is list and len(rows)<=2)
    seen=set()
    for row in rows:
        c.exact(row,{'action','cost','accepted_at','arrival'},'INVALID_GROUNDED_SOURCE')
        need(type(row['action']) is str and row['action'] in {'RETRY_A','FAILOVER_B'} and row['action'] not in seen)
        seen.add(row['action'])
        for key in ('cost','accepted_at','arrival'):ticks(row[key])
        need(row['accepted_at']<=row['arrival'])

def validate_sources(context):
    p=context['grounding'];records=p['source_records']
    for key in EXTRA_SOURCES & records.keys():
        s=records[key]
        need(type(s) is dict and s.get('id')==key and s.get('decision_id')==context['decision_id'],'SOURCE_BINDING_CHANGED')
        if key=='timing':
            c.exact(s,{'id','kind','decision_id','decision_digest','context_digest','observed_at','time_unit','options','policy'},'INVALID_GROUNDED_SOURCE')
            need(s['kind']=='ARCHIVED_TIMING_SNAPSHOT' and s['time_unit']=='relative_microseconds')
            sha(s['decision_digest']);sha(s['context_digest']);ticks(s['observed_at'])
            need(s['decision_digest']==p['decision_digest']==records['decision']['decision_digest'],'TIMING_DECISION_MISMATCH')
            need(s['context_digest']==records['decision']['context_digest'],'TIMING_CONTEXT_MISMATCH')
            c.exact(s['policy'],{'inventory_expires','deadline','offer_until'},'INVALID_GROUNDED_SOURCE')
            for value in s['policy'].values():ticks(value)
            c.exact(s['options'],{'A','B'},'INVALID_GROUNDED_SOURCE')
            for row in s['options'].values():
                c.exact(row,{'cost','available_at','queue_duration','travel_duration'},'INVALID_GROUNDED_SOURCE')
                for value in row.values():ticks(value)
            need('finish' in records,'TIMING_FINISH_REQUIRED')
            need(all(s['policy'][field]==records['finish']['policy'][field] for field in s['policy']),'TIMING_POLICY_MISMATCH')
        elif key=='case-progress':
            c.exact(s,{'id','kind','decision_id','decision_digest','operation_id','attempt_id','read_digest'},'INVALID_GROUNDED_SOURCE')
            need(s['kind']=='ONE_DECISION_WITH_OPERATION_READ' and 'decision-change' not in records,'PROGRESS_SOURCE_CONFLICT')
            sha(s['decision_digest']);sha(s['read_digest'])
            c.identifier(s['operation_id']);c.identifier(s['attempt_id'])
            op=records.get('current-operation');need(op is not None,'PROGRESS_OPERATION_REQUIRED')
            need(s['decision_digest']==p['decision_digest']==records['decision']['decision_digest'],'PROGRESS_DECISION_MISMATCH')
            need(all(s[field]==op[field] for field in ('operation_id','attempt_id','read_digest')),'PROGRESS_READ_MISMATCH')
        elif key=='chat-policy':
            c.exact(s,{'id','kind','renderer_version','decision_id','dispatch_authorized','confirmation_granted'},'INVALID_GROUNDED_SOURCE')
            need(s['kind']=='CODE_POLICY' and s['renderer_version']==g.RENDERER_VERSION)
            need(s['dispatch_authorized'] is False and s['confirmation_granted'] is False)
        elif key=='chat-effect':
            common={'id','kind','decision_id','conversation_id','revision'}
            if s.get('kind')=='CHECKED_CHAT_HISTORY':
                c.exact(s,common|{'ledger_digest','preference_proposals'},'INVALID_GROUNDED_SOURCE')
                sha(s['ledger_digest']);need(type(s['preference_proposals']) is int and s['preference_proposals']==0)
            elif s.get('kind')=='RECORDED_CHAT_PREFERENCES':
                c.exact(s,common|{'proposals'},'INVALID_GROUNDED_SOURCE')
                need(type(s['proposals']) is list and 1<=len(s['proposals'])<=6)
                seen=set()
                for event in s['proposals']:
                    c.exact(event,{'decision_id','turn_id','preference','adopted','event_digest'},'INVALID_GROUNDED_SOURCE')
                    c.identifier(event['decision_id']);c.identifier(event['turn_id']);sha(event['event_digest'])
                    need(type(event['preference']) is str and event['preference'] in g.PREFERENCES and event['adopted'] is False)
                    need(event['turn_id'] not in seen);seen.add(event['turn_id'])
            else:raise c.Invalid('INVALID_GROUNDED_SOURCE')
            c.identifier(s['conversation_id']);c.positive(s['revision'])
            # The read revision is not rewritten when RECORD reserves the turn.
            need(s['revision'] in (context['conversation_revision'],context['conversation_revision']-1),'CHAT_REVISION_MISMATCH')
        elif key=='decision-change':
            c.exact(s,{'id','kind','decision_id','previous_decision_id','previous_digest','decision_digest','previous_preference','current_preference','newly_observed_changes','previous_available','current_available'},'INVALID_GROUNDED_SOURCE')
            need(s['kind']=='VALIDATED_HISTORICAL_COMPARISON' and s['decision_digest']==p['decision_digest'])
            c.identifier(s['previous_decision_id']);need(s['previous_decision_id']!=context['decision_id'])
            sha(s['previous_digest']);preference(s['previous_preference']);preference(s['current_preference'])
            need(s['current_preference']==records['decision']['interpreted_preference'])
            changes=s['newly_observed_changes'];need(type(changes) is list and len(changes)<=8);ids=set()
            for row in changes:
                c.exact(row,{'event_id','at','kind','target','value','observed_at'},'INVALID_GROUNDED_SOURCE')
                c.identifier(row['event_id']);need(row['event_id'] not in ids);ids.add(row['event_id'])
                need(row['kind']=='DELAY_QUEUE' and type(row['target']) is str and row['target'] in {'A','B','*'})
                for field in ('at','value','observed_at'):ticks(row[field])
            option_rows(s['previous_available']);option_rows(s['current_available'])
            if 'finish' in records:need(s['current_available']==records['finish']['receipt']['selection_available'])
        elif key=='current-review':
            fields={'id','kind','decision_id','status','code','dispatch_authorized'}
            if s.get('kind')=='CURRENT_REVALIDATION_RESULT':
                c.exact(s,fields|{'semantic_digest'},'INVALID_GROUNDED_SOURCE');sha(s['semantic_digest'])
            else:
                c.exact(s,fields|{'observed_us','input_digest'},'INVALID_GROUNDED_SOURCE')
                need(s['kind']=='CURRENT_READ_ONLY_REVALIDATION');c.positive(s['observed_us']);sha(s['input_digest'])
            need(s['dispatch_authorized'] is False)
            need(type(s['status']) is str and type(s['code']) is str)
            need((s['status']=='REVIEWABLE' and s['code']=='HUMAN_PREVIEW_REQUIRED') or
                 (s['status'] in {'REJECTED','RECHECK_REQUIRED','ERROR'} and s['code'] in g.extra.REVIEW_REASONS))
        elif key=='simulator-result':
            fields={'id','kind','decision_id','operation_id','attempt_id','state','arrival','result_digest','time_unit','physical_delivery'}
            if s.get('kind')=='OWNED_SIMULATOR_RESULT':
                c.exact(s,fields|{'semantic_digest'},'INVALID_GROUNDED_SOURCE');sha(s['semantic_digest'])
            else:
                c.exact(s,fields|{'observed_at','observation_digest'},'INVALID_GROUNDED_SOURCE')
                need(s['kind']=='OWNED_SIMULATOR_OPERATION_RESULT');sha(s['observation_digest']);ticks(s['observed_at'])
            need(s['physical_delivery'] is False and s['time_unit']=='relative_microseconds')
            c.identifier(s['operation_id']);c.identifier(s['attempt_id']);sha(s['result_digest'])
            need(type(s['state']) is str and s['state'] in {'QUEUED','BLOCKED','NOT_ACCEPTED_FINAL','ACCEPTED','DELIVERED_SIMULATED'})
            if s['arrival'] is not None:ticks(s['arrival'])
            need(s['state']!='DELIVERED_SIMULATED' or (s['arrival'] is not None and ('observed_at' not in s or s['arrival']<=s['observed_at'])))
            op=records.get('current-operation');need(op is not None)
            need((s['operation_id'],s['attempt_id'])==(op['operation_id'],op['attempt_id']),'SIMULATOR_BINDING_MISMATCH')
            status={'DELIVERED_SIMULATED':'ACCEPTED','ACCEPTED':'ACCEPTED','NOT_ACCEPTED_FINAL':'NOT_ACCEPTED_FINAL'}.get(s['state'],'UNKNOWN')
            need(op['state']==status,'SIMULATOR_AUTHORITY_DISAGREES')

def validate_context(scope,context):
    c.exact(context,c.CONTEXT|CONTEXT_EXTRA,'INVALID_GROUNDED_CONTEXT')
    c.validate_context(scope,base_context(context))
    need(context['response_contract']==SCHEMA,'INVALID_CONVERSATION_CONTRACT')
    need(context['renderer_version']==g.RENDERER_VERSION,'UNSUPPORTED_RENDERER_VERSION')
    p=context['grounding'];c.exact(p,CATALOG_FIELDS,'INVALID_GROUNDED_CATALOG');sha(p['decision_digest'])
    topics=g.TOPICS-{'PREFERENCE_CHANGE'}
    c.exact(p['sections'],topics,'INVALID_GROUNDED_SECTIONS');c.exact(p['sources'],topics,'INVALID_GROUNDED_SOURCES')
    records=p['source_records']
    need(type(records) is dict and {'decision','chat-policy'}<=records.keys()<=BASE_SOURCES|EXTRA_SOURCES,'INVALID_GROUNDED_SOURCES')
    for topic in topics:
        c.exact(p['sections'][topic],{'concise','detailed'},'INVALID_GROUNDED_SECTIONS')
        for value in p['sections'][topic].values():c.answer_text(value)
        refs=p['sources'][topic]
        need(type(refs) is list and all(type(ref) is str and ref in records for ref in refs) and len(set(refs))==len(refs),'INVALID_GROUNDED_REFERENCES')
    # Reuse frozen common checks without changing the historical v1 contract.
    old=deepcopy(context);old.update(response_contract=legacy.SCHEMA,renderer_version=legacy.g.RENDERER_VERSION)
    old['grounding']['source_records']={k:deepcopy(v) for k,v in records.items() if k in BASE_SOURCES}
    oldtopics=legacy.g.TOPICS-{'PREFERENCE_CHANGE'}
    old['grounding']['sections']={t:p['sections'][t]['concise'] for t in oldtopics}
    old['grounding']['sources']={t:[s for s in p['sources'][t] if s in BASE_SOURCES] for t in oldtopics}
    legacy.validate_context(scope,old)
    validate_sources(context)
    expected={'COMPARISON':['decision']+(['finish'] if 'finish' in records else [])+(['timing'] if 'timing' in records else []),
              'CHAT_EFFECT':['chat-policy']+(['chat-effect'] if 'chat-effect' in records else []),
              'CURRENT_REVIEW':['current-review'] if 'current-review' in records else [],
              'DECISION_CHANGE':(['decision-change'] if 'decision-change' in records else ['decision','current-operation','case-progress'] if 'case-progress' in records else []),
              'DESTINATION_SIMULATION':['simulator-result'] if 'simulator-result' in records else []}
    for topic,refs in expected.items():need(p['sources'][topic]==refs,'INVALID_GROUNDED_REFERENCES')
    need(not c.sensitive(context),'SENSITIVE_CONTEXT')
    need(len(c.canonical(context).encode('utf-8'))<=98304,'CONTEXT_TOO_LARGE')

def validate_history_binding(context,prefix):
    """Ledger invokes this on its already checked prefix, before appending a turn.

    Replays compare the archived observed prefix, never the incremented revision
    or today's conversation. It neither validates nor authenticates the prefix.
    """
    source=context['grounding']['source_records'].get('chat-effect')
    if source is None:return
    # Derive exactly the same projection without recursively revalidating history.
    _,expected=g._chat_effect(prefix['scope'],prefix,lambda state,scope:None)
    expected['decision_id']=context['decision_id']
    need(source==expected,'CHAT_HISTORY_BINDING_CHANGED')

def from_catalog(value):
    need(type(value) is g.Catalog,'CATALOG_REQUIRED');facts=value.checked()
    c.exact(facts,CATALOG_FIELDS|{'context','scope','renderer_version'},'INVALID_CATALOG')
    context={**deepcopy(facts['context']),'response_contract':SCHEMA,'renderer_version':facts['renderer_version'],
             'grounding':{key:deepcopy(facts[key]) for key in CATALOG_FIELDS}}
    validate_context(facts['scope'],context);return context

def catalog(scope,context):
    validate_context(scope,context)
    record={**deepcopy(context['grounding']),'scope':deepcopy(scope),'context':base_context(context),'renderer_version':g.RENDERER_VERSION}
    return g.Catalog(c.canonical(record),c.digest(record))

def prepare(scope,context,*,conversation_id,turn_id,user_text,history=()):
    cat=catalog(scope,context)
    base,_=c.prepare(scope,base_context(context),conversation_id=conversation_id,turn_id=turn_id,user_text=user_text,history=())
    wire=base.checked()['wire']
    wire.update(schema=SCHEMA,context=deepcopy(context),context_digest=c.digest({'scope':scope,'context':context}),
                catalog_digest=cat.sha256,renderer_version=g.RENDERER_VERSION,history=g.checked_history(history))
    source=context['grounding']['source_records'].get('chat-effect')
    if source is not None:need(source['conversation_id']==conversation_id,'CHAT_CONVERSATION_MISMATCH')
    record={'scope':deepcopy(scope),'wire':wire}
    frozen=c.Prepared(c.canonical(record),c.digest(record))
    binding={key:wire[key] for key in ('schema','renderer_version','conversation_id','turn_id','context_digest','catalog_digest')}
    provider={**binding,'message':user_text,'history':wire['history'],'available_topics':sorted(g.TOPICS),'case_explanations':cat.checked()['sections']}
    raw=c.canonical(provider);c.text(raw,g.WIRE_BYTE_LIMIT,'TURN_TOO_LARGE')
    need(len(frozen.record_json.encode('utf-8'))<=98304,'TURN_TOO_LARGE')
    return frozen,{'system':g.PROMPT,'input_json':raw}

def finish(prepared,raw,*,current_scope,current_context):
    need(type(prepared) is c.Prepared,'PREPARED_REQUIRED')
    record=prepared.checked();wire=record['wire'];cat=catalog(current_scope,current_context)
    need(record['scope']==current_scope,'CONVERSATION_SCOPE_CHANGED')
    need(wire['schema']==SCHEMA and wire['context_digest']==c.digest({'scope':current_scope,'context':current_context}),'CONTEXT_CHANGED')
    need(wire['catalog_digest']==cat.sha256 and wire['renderer_version']==g.RENDERER_VERSION,'CONTEXT_CHANGED')
    binding={key:wire[key] for key in ('schema','renderer_version','conversation_id','turn_id','context_digest','catalog_digest')}
    inner={'binding':binding,'catalog_sha256':cat.sha256}
    return g.finish(g.Prepared(c.canonical(inner),c.digest(inner)),raw,current_catalog=cat)

def response_raw(response):
    plan={key:response[key] for key in ('renderer_version','conversation_id','turn_id','context_digest','catalog_digest','topics','detail','preference')}
    return c.canonical(plan|{'schema':SCHEMA})
