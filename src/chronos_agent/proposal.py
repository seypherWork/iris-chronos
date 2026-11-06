"""Strict inert proposal validation, promoted from A1 without its offline engine.

Checking a cited source or a ranking does not validate a natural-language
interpretation. Even VALIDATED_PROPOSAL requires authenticated human review.
"""
import json
import re

FIELDS=set('schema_version context_id context_digest order_id shipment_version '
           'state_revision action option_id interpreted_preference source_ids '
           'reason_code rationale clarification'.split())
OPTIONS={'RETRY_A':'opt-a','FAILOVER_B':'opt-b'}
HOLD_REASONS={'CONTEXT_AMBIGUOUS':{'UNRESOLVED'},
              'CONFLICTING_EVIDENCE':{'UNRESOLVED','NOT_USED'},
              'CONTEXT_INCOMPLETE':{'NOT_USED'},
              'NO_FEASIBLE_OPTION':{'NOT_USED'},
              'ACCEPTANCE_UNRESOLVED':{'NOT_USED'}}
SENSITIVE_KEY=re.compile(r'(?:password|passwd|api[_ -]?key|client[_ -]?secret|'
                         r'access[_ -]?token|authorization|private[_ -]?key)',re.I)
SENSITIVE=re.compile(r"(?:password|passwd|api[_ -]?key|client[_ -]?secret|access[_ -]?token)\s*['\"]?\s*[:=]\s*\S+|"
                     r"authorization\s*['\"]?\s*:\s*['\"]?\s*(?:bearer|basic)\s+\S+|-----BEGIN [^-]*PRIVATE KEY-----",re.I)
# Inspect JSON spelling as data only; never change the business payload.
SENSITIVE_JSON_KEY=re.compile(r"['\"]\s*(?:password|passwd|api[_ -]?key|client[_ -]?secret|access[_ -]?token|authorization|private[_ -]?key)\s*['\"]\s*:",re.I)
JSON_ESCAPE=re.compile(r'\\(?:u[0-9a-fA-F]{4}|["\\/bfnrt])')



class Invalid(ValueError):pass


def parse(text):
    def pairs(items):
        result={}
        for key,value in items:
            if key in result:raise Invalid('DUPLICATE_JSON_KEY')
            result[key]=value
        return result
    def constant(_):raise Invalid('NONFINITE_JSON')
    return json.loads(text,object_pairs_hook=pairs,parse_constant=constant)


def sensitive(value, _depth=0):
    # Known credential markers only, not a general secret-discovery guarantee.
    # Reject rather than silently redact fields from an exact business effect.
    if _depth>32:return True
    if type(value) is str:
        if SENSITIVE.search(value) or SENSITIVE_JSON_KEY.search(value):return True
        # Decode only recognized JSON escapes for detection, also in prose and
        # partial/duplicate JSON. Prefixes/suffixes cannot hide a detected key.
        decoded=JSON_ESCAPE.sub(lambda m: json.loads('"'+m.group(0)+'"'),value)
        return decoded!=value and sensitive(decoded,_depth+1)
    if type(value) is dict:
        return any((type(k) is str and SENSITIVE_KEY.fullmatch(k.strip()) is not None) or
                   (type(k) is str and '\\' in k and sensitive(json.dumps(k)+':',_depth+1)) or
                   sensitive(k,_depth+1) or sensitive(v,_depth+1) for k,v in value.items())
    if type(value) is list:return any(sensitive(v,_depth+1) for v in value)
    return False


def check(raw,wire,available):
    """Raise a bounded code; never fix JSON or execute response contents."""
    if type(raw) is not str or len(raw.encode('utf-8'))>4096:raise Invalid('INVALID_PROPOSAL')
    response=parse(raw)
    if sensitive(response):raise Invalid('SENSITIVE_OUTPUT')
    if type(response) is not dict or set(response)!=FIELDS:raise Invalid('INVALID_PROPOSAL')
    for field in ('schema_version','context_id','context_digest','order_id'):
        expected='chronos.agent-proposal.v2' if field=='schema_version' else wire[field]
        if type(response[field]) is not str or response[field]!=expected:raise Invalid('PROPOSAL_IDENTITY_MISMATCH')
    for field in ('shipment_version','state_revision'):
        if type(response[field]) is not int or response[field]!=wire[field]:raise Invalid('PROPOSAL_IDENTITY_MISMATCH')
    action,pref,reason=(response[k] for k in ('action','interpreted_preference','reason_code'))
    if type(action) is not str or action not in {*OPTIONS,'HOLD'}:raise Invalid('INVALID_PROPOSAL')
    if type(pref) is not str or pref not in {'CHEAPEST_ON_TIME','EARLIEST_ALLOWED','UNRESOLVED','NOT_USED'}:raise Invalid('INVALID_PROPOSAL')
    if type(reason) is not str:raise Invalid('INVALID_PROPOSAL')
    sources=response['source_ids'];catalog={item['id'] for item in wire['source_catalog']}
    if (type(sources) is not list or not 1<=len(sources)<=16 or
        any(type(s) is not str or s not in catalog for s in sources) or len(set(sources))!=len(sources)):
        raise Invalid('INVALID_SOURCES')
    rationale=response['rationale'];question=response['clarification']
    if type(rationale) is not str or not rationale.strip() or len(rationale)>600:raise Invalid('INVALID_PROPOSAL')
    if question is not None and (type(question) is not str or not question.strip() or len(question)>240 or
                               action!='HOLD' or reason not in {'CONTEXT_AMBIGUOUS','CONTEXT_INCOMPLETE'}):
        raise Invalid('INVALID_PROPOSAL')
    if action=='HOLD':
        if response['option_id'] is not None or reason not in HOLD_REASONS or pref not in HOLD_REASONS[reason]:raise Invalid('INVALID_PROPOSAL')
        if reason=='ACCEPTANCE_UNRESOLVED' or (reason=='NO_FEASIBLE_OPTION' and available):raise Invalid('UNSUPPORTED_HOLD_REASON')
    else:
        if pref not in {'CHEAPEST_ON_TIME','EARLIEST_ALLOWED'} or reason!='PREFERENCE_MATCH' or response['option_id']!=OPTIONS[action]:raise Invalid('INVALID_PROPOSAL')
        facts=wire['facts']
        if facts['preference_mode']=='STRUCTURED' and pref!=facts['structured_preference']:raise Invalid('POLICY_MISMATCH')
        if facts['preference_mode']=='CONTEXT_REQUIRED':
            relevant={m['message_id'] for m in facts['messages'] if m['order_link']=='VERIFIED_CURRENT'}
            if not relevant.intersection(sources):raise Invalid('MISSING_CONTEXT_SOURCE')
        if action not in {item['action'] for item in available}:raise Invalid('OPTION_NOT_FEASIBLE')
        first,second=('cost','arrival') if pref=='CHEAPEST_ON_TIME' else ('arrival','cost')
        best=min(available,key=lambda item:(item[first],item[second],OPTIONS[item['action']]))['action']
        if action!=best:raise Invalid('RANKING_MISMATCH')
    return response
