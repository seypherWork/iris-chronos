"""Explicit E1 extraction -> A1 assembly. No I/O or runtime authority.

This is a new contract, never repair/fallback for a rejected A1 response.
Only the model's explicit interpretation/citations are accepted. The server-side
candidate supplies identity and ranks trusted feasible outcomes deterministically.
"""
from dataclasses import dataclass
from hashlib import sha256
import json, math
from . import proposal
from .proposal import parse
from .engine import canonical, fingerprint
SCHEMA_VERSION='chronos.preference-extraction.v1'
FIELDS={'schema_version','interpreted_preference','reason_code','source_ids','rationale','clarification'}
MATCH={'CHEAPEST_ON_TIME','EARLIEST_ALLOWED'}
REASONS={'PREFERENCE_MATCH','CONTEXT_AMBIGUOUS','CONFLICTING_EVIDENCE','CONTEXT_INCOMPLETE'}

class Invalid(ValueError):pass

@dataclass(frozen=True)
class BoundContext:
    wire_json: str
    available_json: str
    binding_sha256: str

    @classmethod
    def create(cls,wire,available):
        w,a=canonical(wire),canonical(available)
        wire,available=parse(w),parse(a)
        if wire.get('context_digest')!=fingerprint({k:v for k,v in wire.items() if k!='context_digest'}):
            raise Invalid('CONTEXT_DIGEST_MISMATCH')
        if type(available) is not list:raise Invalid('INVALID_AVAILABLE')
        actions=[]
        for row in available:
            if type(row) is not dict or set(row)!={'action','cost','accepted_at','arrival'}:raise Invalid('INVALID_AVAILABLE')
            if row['action'] not in proposal.OPTIONS:raise Invalid('INVALID_AVAILABLE')
            for k in ('cost','accepted_at','arrival'):
                # canonical/parse uses Decimal for non-integer numeric values.
                from decimal import Decimal
                v=row[k]
                if type(v) not in (int,Decimal) or v<0 or not math.isfinite(v):raise Invalid('INVALID_AVAILABLE')
            if row['accepted_at']>row['arrival']:raise Invalid('INVALID_AVAILABLE')
            actions.append(row['action'])
        if len(set(actions))!=len(actions):raise Invalid('DUPLICATE_AVAILABLE')
        digest=sha256((w+'\n'+a).encode()).hexdigest()
        return cls(w,a,digest)

    def checked(self,expected_binding):
        if type(expected_binding) is not str or expected_binding!=self.binding_sha256:raise Invalid('CALL_CONTEXT_MISMATCH')
        if sha256((self.wire_json+'\n'+self.available_json).encode()).hexdigest()!=expected_binding:raise Invalid('BOUND_CONTEXT_CHANGED')
        return parse(self.wire_json),parse(self.available_json)


def extraction(raw,wire):
    if type(raw) is not str or not 0<len(raw.encode('utf-8'))<=2048:raise Invalid('INVALID_EXTRACTION')
    try:x=proposal.parse(raw)
    except (ValueError,TypeError,RecursionError):raise Invalid('INVALID_EXTRACTION_JSON') from None
    if proposal.sensitive(x):raise Invalid('SENSITIVE_OUTPUT')
    if type(x) is not dict or set(x)!=FIELDS or x['schema_version']!=SCHEMA_VERSION:raise Invalid('EXTRACTION_CONTRACT_MISMATCH')
    pref,reason=x['interpreted_preference'],x['reason_code']
    if type(pref) is not str or type(reason) is not str or reason not in REASONS:raise Invalid('INVALID_EXTRACTION')
    if (reason=='PREFERENCE_MATCH' and pref not in MATCH) or (reason!='PREFERENCE_MATCH' and pref!='UNRESOLVED'):raise Invalid('INCONSISTENT_EXTRACTION')
    sources=x['source_ids'];catalog={s['id'] for s in wire['source_catalog']}
    # Fixed codes only: never echo model strings, repair references or weaken
    # the original rejection. Validate types before hashing arbitrary values.
    if type(sources) is not list:raise Invalid('INVALID_SOURCES_LIST')
    if not 1<=len(sources)<=16:raise Invalid('INVALID_SOURCES_COUNT')
    if any(type(s) is not str for s in sources):raise Invalid('INVALID_SOURCES_TYPE')
    if any(s not in catalog for s in sources):raise Invalid('INVALID_SOURCES_UNKNOWN')
    if len(set(sources))!=len(sources):raise Invalid('INVALID_SOURCES_DUPLICATE')
    rationale,question=x['rationale'],x['clarification']
    if type(rationale) is not str or not rationale.strip() or len(rationale)>240:raise Invalid('INVALID_RATIONALE')
    if question is not None and (type(question) is not str or not question.strip() or len(question)>160 or reason not in {'CONTEXT_AMBIGUOUS','CONTEXT_INCOMPLETE'}):raise Invalid('INVALID_CLARIFICATION')
    if reason=='PREFERENCE_MATCH' and question is not None:raise Invalid('INVALID_CLARIFICATION')
    facts=wire['facts'];mode=facts['preference_mode']
    current={m['message_id'] for m in facts['messages'] if m['order_link']=='VERIFIED_CURRENT'}
    if mode=='STRUCTURED':
        if reason=='PREFERENCE_MATCH' and pref!=facts['structured_preference']:raise Invalid('STRUCTURED_POLICY_MISMATCH')
    elif mode=='CONTEXT_REQUIRED':
        if reason=='PREFERENCE_MATCH' and not current.intersection(sources):raise Invalid('CURRENT_SOURCE_REQUIRED')
        if reason=='CONFLICTING_EVIDENCE' and not current.intersection(sources):raise Invalid('CONFLICT_SOURCES_REQUIRED')
    else:raise Invalid('UNKNOWN_PREFERENCE_MODE')
    return x


def assemble(raw,bound,expected_binding):
    """Fresh callers must bind the received response to their original request.

    Offline helper does not authenticate that caller or check a live provider.
    Native integration must obtain BoundContext from the trusted consumed ledger,
    never the browser/model, and perform existing finish/review/readback afterward.
    """
    wire,available=bound.checked(expected_binding)
    x=extraction(raw,wire)
    p={k:wire[k] for k in ('context_id','context_digest','order_id','shipment_version','state_revision')}
    p.update(schema_version='chronos.agent-proposal.v2',action='HOLD',option_id=None,
             interpreted_preference=x['interpreted_preference'],reason_code=x['reason_code'],
             source_ids=x['source_ids'][:],rationale=x['rationale'],clarification=x['clarification'])
    if x['reason_code']=='PREFERENCE_MATCH':
        if not available:
            p.update(interpreted_preference='NOT_USED',reason_code='NO_FEASIBLE_OPTION',clarification=None,
                     rationale='No option satisfies the independently checked operational constraints.')
        else:
            first,second=('cost','arrival') if x['interpreted_preference']=='CHEAPEST_ON_TIME' else ('arrival','cost')
            best=min(available,key=lambda a:(a[first],a[second],proposal.OPTIONS[a['action']]))
            p.update(action=best['action'],option_id=proposal.OPTIONS[best['action']])
    elif x['reason_code']=='CONTEXT_INCOMPLETE':
        p['interpreted_preference']='NOT_USED'
    checked=proposal.check(canonical(p),wire,available)
    return {'extraction':x,'proposal':checked,'binding_sha256':expected_binding,
            'decision_origin':{'interpretation':'MODEL','identity':'BOUND_CONTEXT','ranking':'DETERMINISTIC'},
            'dispatch_authorized':False}
