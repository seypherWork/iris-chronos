"""C2 adapter for the shared conversation ledger, not an authority boundary.

Only the authenticated host may construct contexts. The public context contains
checked explanations and sources, never the private scope or the raw ledger.
The model selects a plan; the pinned renderer supplies all factual reply text.
"""
from copy import deepcopy
import re
from . import contract as c
if '_chronos_grounded_dependencies' in globals():
    g, = _chronos_grounded_dependencies
else:
    from chronos_grounding import plan as g

SCHEMA = g.PLAN_SCHEMA
CONTEXT_EXTRA = {'response_contract','renderer_version','grounding'}
CATALOG_FIELDS = {'decision_digest','sections','sources','source_records',
                  'operation_missing','quarantined','blocking_notice'}


def base_context(context):
    return {key:deepcopy(context[key]) for key in c.CONTEXT}


def with_conversation_revision(context, revision):
    """Rebind revision-dependent absence evidence symmetrically with RECORD."""
    c.positive(revision)
    revised=deepcopy(context)
    revised['conversation_revision']=revision
    if revised['grounding']['operation_missing']:
        revised['grounding']['source_records']['current-read-missing']['context_digest']=c.digest(base_context(revised))
    return revised


def renderer(context):
    return g.renderer(context['renderer_version'])


def validate_context(scope, context):
    c.exact(context,c.CONTEXT|CONTEXT_EXTRA,'INVALID_GROUNDED_CONTEXT')
    c.validate_context(scope,base_context(context))
    if context['response_contract']!=SCHEMA:raise c.Invalid('INVALID_CONVERSATION_CONTRACT')
    render=renderer(context)
    payload=context['grounding']
    c.exact(payload,CATALOG_FIELDS,'INVALID_GROUNDED_CATALOG')
    if type(payload['decision_digest']) is not str or not re.fullmatch('[0-9a-f]{64}',payload['decision_digest']):
        raise c.Invalid('INVALID_DECISION_DIGEST')
    topics=render.TOPICS-{'PREFERENCE_CHANGE'}
    c.exact(payload['sections'],topics,'INVALID_GROUNDED_SECTIONS')
    c.exact(payload['sources'],topics,'INVALID_GROUNDED_SOURCES')
    records=payload['source_records']
    if type(records) is not dict or not {'decision'}<=set(records)<={'decision','finish','current-operation','current-read-missing'}:
        raise c.Invalid('INVALID_GROUNDED_SOURCES')
    for flag in ('operation_missing','quarantined'):
        if type(payload[flag]) is not bool:raise c.Invalid('INVALID_GROUNDED_STATE')
    expected_current='current-read-missing' if payload['operation_missing'] else 'current-operation'
    if expected_current not in records or ({'current-read-missing','current-operation'}-{expected_current})&set(records):
        raise c.Invalid('INVALID_GROUNDED_SOURCES')
    for key,source in records.items():
        expected={
            'decision':{'id','kind','decision_id','decision_digest','context_digest','action','option_id','interpreted_preference','reason_code','attribution'},
            'finish':{'id','kind','decision_id','decision_digest','receipt','receipt_digest','policy','trial_mode','time_unit','cost_unit'},
            'current-operation':{'id','kind','decision_id','operation_id','attempt_id','state','quarantined','read_digest'},
            'current-read-missing':{'id','kind','decision_id','context_digest'}}[key]
        c.exact(source,expected,'INVALID_GROUNDED_SOURCE')
        if source['id']!=key or source['decision_id']!=context['decision_id']:raise c.Invalid('SOURCE_BINDING_CHANGED')
        if key in {'decision','finish'} and source['decision_digest']!=payload['decision_digest']:raise c.Invalid('SOURCE_BINDING_CHANGED')
        if key=='finish' and c.digest(source['receipt'])!=source['receipt_digest']:raise c.Invalid('SOURCE_BINDING_CHANGED')
    for topic in topics:
        c.answer_text(payload['sections'][topic])
        refs=payload['sources'][topic]
        if type(refs) is not list or any(type(ref) is not str or ref not in records for ref in refs) or len(set(refs))!=len(refs):
            raise c.Invalid('INVALID_GROUNDED_REFERENCES')
    notice=payload['blocking_notice']
    if notice is not None:
        c.answer_text(notice)
        if notice!=payload['sections']['OPERATION_STATUS']:raise c.Invalid('INVALID_BLOCKING_NOTICE')
    if payload['sources']['OPERATION_STATUS']!=[expected_current]:raise c.Invalid('INVALID_STATUS_SOURCES')
    if expected_current=='current-operation':
        operation=records[expected_current]
        if operation['operation_id']!=context['operation_id'] or operation['quarantined'] is not payload['quarantined']:
            raise c.Invalid('OPERATION_BINDING_CHANGED')
        blocked=payload['quarantined'] or operation['state'] in {'UNKNOWN','IN_FLIGHT'}
    else:
        if payload['quarantined']:raise c.Invalid('INVALID_GROUNDED_STATE')
        if records[expected_current]['context_digest']!=c.digest(base_context(context)):raise c.Invalid('SOURCE_BINDING_CHANGED')
        blocked=False
    if (notice is not None)!=blocked:raise c.Invalid('INVALID_BLOCKING_NOTICE')
    if c.sensitive(context):raise c.Invalid('SENSITIVE_CONTEXT')
    if len(c.canonical(context).encode('utf-8'))>65536:raise c.Invalid('CONTEXT_TOO_LARGE')


def from_catalog(catalog, *, renderer_version=g.RENDERER_VERSION):
    """Only use a catalog built from authenticated records, never request JSON."""
    render=g.renderer(renderer_version)
    if type(catalog) is not render.Catalog:raise c.Invalid('CATALOG_REQUIRED')
    facts=catalog.checked()
    c.exact(facts,CATALOG_FIELDS|{'context','scope'},'INVALID_CATALOG')
    context={**deepcopy(facts['context']), 'response_contract':SCHEMA,
             'renderer_version':renderer_version,
             'grounding':{key:deepcopy(facts[key]) for key in CATALOG_FIELDS}}
    validate_context(facts['scope'],context)
    return context


def catalog(scope,context):
    validate_context(scope,context)
    record={**deepcopy(context['grounding']),'scope':deepcopy(scope),'context':base_context(context)}
    render=renderer(context)
    return render.Catalog(c.canonical(record),c.digest(record))


def prepare(scope,context,*,conversation_id,turn_id,user_text,history=()):
    cat=catalog(scope,context);render=renderer(context)
    base,_=c.prepare(scope,base_context(context),conversation_id=conversation_id,turn_id=turn_id,user_text=user_text,history=history)
    wire=base.checked()['wire']
    wire.update(schema=SCHEMA,context=deepcopy(context),context_digest=c.digest({'scope':scope,'context':context}),
                catalog_digest=cat.sha256,renderer_version=context['renderer_version'])
    record={'scope':deepcopy(scope),'wire':wire}
    frozen=c.Prepared(c.canonical(record),c.digest(record))
    binding={key:wire[key] for key in ('schema','conversation_id','turn_id','context_digest','catalog_digest')}
    provider={**binding,'message':user_text,'history':wire['history'],
              'available_topics':sorted(render.TOPICS),'case_explanations':cat.checked()['sections']}
    raw=c.canonical(provider)
    if len(raw.encode('utf-8'))>32768:raise c.Invalid('TURN_TOO_LARGE')
    if len(frozen.record_json.encode('utf-8'))>98304:raise c.Invalid('TURN_TOO_LARGE')
    return frozen,{'system':render.PROMPT,'input_json':raw}


def finish(prepared,raw,*,current_scope,current_context):
    if type(prepared) is not c.Prepared:raise c.Invalid('PREPARED_REQUIRED')
    record=prepared.checked();wire=record['wire']
    validate_context(current_scope,current_context)
    if record['scope']!=current_scope:raise c.Invalid('CONVERSATION_SCOPE_CHANGED')
    if wire['schema']!=SCHEMA or wire['context_digest']!=c.digest({'scope':current_scope,'context':current_context}):
        raise c.Invalid('CONTEXT_CHANGED')
    render=renderer(wire['context']);cat=catalog(current_scope,current_context)
    if wire['catalog_digest']!=cat.sha256 or wire['renderer_version']!=current_context['renderer_version']:
        raise c.Invalid('CONTEXT_CHANGED')
    binding={key:wire[key] for key in ('schema','conversation_id','turn_id','context_digest','catalog_digest')}
    inner={'binding':binding,'catalog_sha256':cat.sha256}
    plan=render.Prepared(c.canonical(inner),c.digest(inner))
    return render.finish(plan,raw,current_catalog=cat)


def response_raw(response):
    """Restore the bounded plan, not free prose, for deterministic replay."""
    plan={key:response[key] for key in ('conversation_id','turn_id','context_digest','catalog_digest','topic','detail','preference')}
    plan['schema']=SCHEMA
    return c.canonical(plan)
