Include %occStatus

/// Internal, manifest-bound bridge. No credentials, model I/O or HTTP entry.
Class Chronos.Conversation.Python Extends %RegisteredObject
{
ClassMethod Module(root As %String, namespace As %String, agent As %String) As %String [ Language = python ]
{
    import hashlib,importlib.util,re,sys,threading,types
    from pathlib import Path
    root=Path(root);package=root/'chronos_conversation';grounding=root/'chronos_grounding'
    if not root.is_absolute() or root.resolve()!=root or package.resolve()!=package or grounding.resolve()!=grounding:raise ValueError('FIXED_CONVERSATION_ROOT_REQUIRED')
    if not isinstance(namespace,str) or not namespace:raise ValueError('NAMESPACE_REQUIRED')
    if not isinstance(agent,str) or not re.fullmatch(r'_chronos_agent_[0-9a-f]{64}\.contract',agent):raise ValueError('BOUND_AGENT_REQUIRED')
    agentroot=agent.rsplit('.',1)[0];agentpackage=sys.modules.get(agentroot)
    binding=getattr(agentpackage,'_chronos_binding',None)
    if not isinstance(binding,tuple) or len(binding)!=4 or binding[:2]!=(namespace,str(root)):raise ValueError('AGENT_BINDING_CHANGED')
    proposal=sys.modules.get(agentroot+'.proposal')
    if proposal is None or getattr(agentpackage,'proposal',None) is not proposal or getattr(proposal,'__file__',None)!=str(root/'chronos_agent/proposal.py'):raise ValueError('AGENT_ORIGIN_CHANGED')
    dependencies=(proposal.parse,proposal.sensitive)
    agentcontract=sys.modules.get(agent);simroot=binding[2].rsplit('.',1)[0];simpackage=sys.modules.get(simroot)
    if agentcontract is None or getattr(agentpackage,'contract',None) is not agentcontract or getattr(agentcontract,'__file__',None)!=str(root/'chronos_agent/contract.py'):raise ValueError('AGENT_ORIGIN_CHANGED')
    if not re.fullmatch(r'_chronos_[0-9a-f]{64}\.realtime',binding[2]) or getattr(simpackage,'_chronos_identity',())[:2]!=(namespace,str(root)):raise ValueError('SIMULATION_BINDING_CHANGED')
    store=sys.modules.get(simroot+'.store');workflow=sys.modules.get(simroot+'.workflow')
    for name,loaded in (('store',store),('workflow',workflow)):
        if loaded is None or getattr(simpackage,name,None) is not loaded or getattr(loaded,'__file__',None)!=str(root/('chronos_simulation/'+name+'.py')):raise ValueError('SIMULATION_ORIGIN_CHANGED')
    supplements=(agentcontract,store.Destinations,workflow.Change)
    expected={'chronos_conversation':{'__init__.py','contract.py','ledger.py','evidence.py','grounded.py','grounded_v2.py'},
              'chronos_grounding':{'__init__.py','plan.py','renderer_v1.py','renderer_v2.py','evidence_v2.py','README.md'}}
    sources={};digest=hashlib.sha256()
    for directory,names in sorted(expected.items()):
        parent=root/directory
        if {p.name for p in parent.iterdir() if p.name!='__pycache__'}!=names:raise ValueError('UNEXPECTED_CONVERSATION_CONTENTS')
        for name in sorted(names):
            path=parent/name;rel=directory+'/'+name
            if not path.is_file() or path.resolve()!=path:raise ValueError('LINKED_SOURCE')
            sources[rel]=path.read_bytes()
            if len(sources[rel])>131072:raise ValueError('SOURCE_TOO_LARGE')
            digest.update(rel.encode()+b'\0'+sources[rel]+b'\0')
    identity=(namespace,str(root),binding,digest.hexdigest())
    alias='_chronos_conversation_'+hashlib.sha256(repr(identity).encode()).hexdigest()
    origins={'':'chronos_conversation/__init__.py','contract':'chronos_conversation/contract.py',
        'evidence':'chronos_conversation/evidence.py','grounding':'chronos_grounding/__init__.py',
        'grounding.renderer_v1':'chronos_grounding/renderer_v1.py',
        'grounding.evidence_v2':'chronos_grounding/evidence_v2.py','grounding.renderer_v2':'chronos_grounding/renderer_v2.py',
        'grounding.plan':'chronos_grounding/plan.py',
        'grounded':'chronos_conversation/grounded.py','grounded_v2':'chronos_conversation/grounded_v2.py','ledger':'chronos_conversation/ledger.py'}
    def graph():
        required={alias+('.'+name if name else '') for name in origins}
        if {n for n in sys.modules if n==alias or n.startswith(alias+'.')}!=required:raise ValueError('PARTIAL_CONVERSATION_PACKAGE')
        for child,rel in origins.items():
            name=alias+('.'+child if child else '');loaded=sys.modules[name]
            if getattr(loaded,'__file__',None)!=str(root/rel):raise ValueError('CONVERSATION_ORIGIN_CHANGED')
            if child:
                parent,attr=name.rsplit('.',1)
                if getattr(sys.modules[parent],attr,None) is not loaded:raise ValueError('CONVERSATION_CHILD_CHANGED')
        module=sys.modules[alias];contract=module.contract;evidence=module.evidence
        renderer=module.grounding.renderer_v1;plan=module.grounding.plan;grounded=module.grounded;ledger=module.ledger
        prior=getattr(contract,'_chronos_conversation_dependencies',())
        if len(prior)!=2 or any(a is not b for a,b in zip(prior,dependencies)) or contract.parse is not dependencies[0] or contract.sensitive is not dependencies[1]:raise ValueError('CONVERSATION_DEPENDENCIES_CHANGED')
        if evidence.c is not contract or ledger.c is not contract or grounded.c is not contract or ledger.grounded is not grounded:raise ValueError('CONVERSATION_CHILD_CHANGED')
        if renderer.c is not contract or renderer.evidence is not evidence or plan.renderer_v1 is not renderer or grounded.g is not plan:raise ValueError('CONVERSATION_GROUNDING_CHANGED')
        if getattr(renderer,'_chronos_renderer_dependencies',None)!=(contract,evidence) or getattr(grounded,'_chronos_grounded_dependencies',None)!=(plan,):raise ValueError('CONVERSATION_GROUNDING_CHANGED')
        v2=module.grounding.renderer_v2;extra=module.grounding.evidence_v2;adapter=module.grounded_v2
        if v2.v1 is not renderer or v2.c is not contract or v2.extra is not extra or extra.v1 is not renderer or extra.c is not contract:raise ValueError('CONVERSATION_V2_GRAPH_CHANGED')
        if getattr(extra,'_chronos_supplement_dependencies',None)!=supplements or (extra.agent,extra.Destinations,extra.Change)!=supplements:raise ValueError('CONVERSATION_V2_DEPENDENCIES_CHANGED')
        if adapter.c is not contract or adapter.legacy is not grounded or adapter.g is not v2 or ledger.grounded_v2 is not adapter:raise ValueError('CONVERSATION_V2_GRAPH_CHANGED')
        if getattr(adapter,'_chronos_grounded_v2_dependencies',None)!=(v2,):raise ValueError('CONVERSATION_V2_GRAPH_CHANGED')
    candidate=types.ModuleType('_chronos_conversation_loader_v2');candidate.version=2;candidate.lock=threading.RLock()
    control=sys.modules.setdefault(candidate.__name__,candidate)
    if getattr(control,'version',None)!=2 or not hasattr(control,'lock'):raise ValueError('LOADER_CONFLICT')
    with control.lock:
        cached=sys.modules.get(alias)
        if cached is not None:
            if getattr(cached,'_chronos_conversation_binding',None)!=identity:raise ValueError('PARTIAL_CONVERSATION_PACKAGE')
            graph();return alias+'.ledger'
        if any(n.startswith(alias+'.') for n in sys.modules):raise ValueError('ORPHAN_CONVERSATION_MODULES')
        sys.dont_write_bytecode=True
        try:
            for child,rel in origins.items():
                name=alias+('.'+child if child else '');path=root/rel
                options={'submodule_search_locations':[str(path.parent)]} if path.name=='__init__.py' else {}
                spec=importlib.util.spec_from_file_location(name,path,**options)
                loaded=importlib.util.module_from_spec(spec);sys.modules[name]=loaded
                if child=='contract':loaded._chronos_conversation_dependencies=dependencies
                if child=='grounding.renderer_v1':loaded._chronos_renderer_dependencies=(sys.modules[alias+'.contract'],sys.modules[alias+'.evidence'])
                if child=='grounding.evidence_v2':loaded._chronos_supplement_dependencies=supplements
                if child=='grounded_v2':loaded._chronos_grounded_v2_dependencies=(sys.modules[alias+'.grounding.renderer_v2'],)
                if child=='grounded':loaded._chronos_grounded_dependencies=(sys.modules[alias+'.grounding.plan'],)
                exec(compile(sources[rel],str(path),'exec'),loaded.__dict__)
                if child:
                    parent,attr=name.rsplit('.',1);setattr(sys.modules[parent],attr,loaded)
            sys.modules[alias]._chronos_conversation_binding=identity
            graph()
        except BaseException:
            for name in tuple(sys.modules):
                if name==alias or name.startswith(alias+'.'):del sys.modules[name]
            raise
        return alias+'.ledger' 
}

/// Caller owns lock/transaction and supplies only the module returned above.
ClassMethod Evaluate(module As %String, namespace As %String, previousJSON As %String, command As %String, scopeJSON As %String, argsJSON As %String) As %String [ Language = python ]
{
    import re,sys
    if not re.fullmatch(r'_chronos_conversation_[0-9a-f]{64}\.ledger',module):raise ValueError('BOUND_MODULE_REQUIRED')
    package=sys.modules[module.rsplit('.',1)[0]]
    if package._chronos_conversation_binding[0]!=namespace:raise ValueError('NAMESPACE_CHANGED')
    ledger=sys.modules[module];contract=package.contract
    if package.ledger is not ledger or ledger.c is not contract:raise ValueError('BOUND_MODULE_CHANGED')
    for value,limit in ((previousJSON,524288),(scopeJSON,4096),(argsJSON,131072)):
        if type(value) is not str or len(value.encode('utf-8'))>limit:raise ValueError('INPUT_TOO_LARGE')
    previous=None if previousJSON=='' else contract.parse(previousJSON)
    state,result=ledger.transition(previous,command,contract.parse(scopeJSON),contract.parse(argsJSON))
    newJSON=contract.canonical(state)
    changed=previous is None or newJSON!=contract.canonical(previous)
    if result['inference_granted'] and (not changed or command!='CLAIM'):raise ValueError('INVALID_GRANT')
    return contract.canonical({'stateJSON':newJSON,'changed':changed,'result':result})
}

/// Trusted projection from authenticated Context.Snapshot, never request JSON.
ClassMethod Context(module As %String, namespace As %String, detailJSON As %String, scopeJSON As %String, currentJSON As %String, generation As %String, revision As %Integer, conversationRevision As %Integer) As %String [ Language = python ]
{
    import re,sys
    if not re.fullmatch(r'_chronos_conversation_[0-9a-f]{64}\.ledger',module):raise ValueError('BOUND_MODULE_REQUIRED')
    package=sys.modules[module.rsplit('.',1)[0]]
    if package._chronos_conversation_binding[0]!=namespace:raise ValueError('NAMESPACE_CHANGED')
    ledger=sys.modules[module];contract=package.contract;evidence=package.evidence
    if package.ledger is not ledger or ledger.c is not contract or evidence.c is not contract or sys.modules.get(package.__name__+'.evidence') is not evidence:raise ValueError('BOUND_MODULE_CHANGED')
    for value,limit in ((detailJSON,262144),(scopeJSON,4096),(currentJSON,16384)):
        if type(value) is not str or len(value.encode('utf-8'))>limit:raise ValueError('INPUT_TOO_LARGE')
    detail=contract.parse(detailJSON);scope=contract.parse(scopeJSON)
    current=None if currentJSON=='' else contract.parse(currentJSON)
    # This wrapper receives the output of the authenticated historical projector;
    # it must never be used to turn an untrusted detail object into a trusted one.
    context=evidence.build('',detail['decisionId'],scope,projector=lambda raw,ident:detail,
        generation=generation,revision=revision,conversation_revision=conversationRevision,
        current_operation=current)
    return contract.canonical({'code':'CONVERSATION_CONTEXT_READY','scope':scope,
        'context':context,'context_digest':contract.digest({'scope':scope,'context':context}),
        'dispatch_authorized':False})
}

/// Only Agent.Python.GroundedContext calls this after bound review projection.
ClassMethod GroundedContext(module As %String, namespace As %String, agent As %String, decisionJSON As %String, detailJSON As %String, scopeJSON As %String, currentJSON As %String, generation As %String, revision As %Integer, conversationRevision As %Integer) As %String [ Language = python ]
{
    import re,sys
    if type(module) is not str or not re.fullmatch(r'_chronos_conversation_[0-9a-f]{64}\.ledger',module):raise ValueError('BOUND_MODULE_REQUIRED')
    if type(agent) is not str or not re.fullmatch(r'_chronos_agent_[0-9a-f]{64}\.contract',agent):raise ValueError('BOUND_AGENT_REQUIRED')
    package=sys.modules[module.rsplit('.',1)[0]];agentpackage=sys.modules[agent.rsplit('.',1)[0]]
    binding=package._chronos_conversation_binding
    if binding[0]!=namespace:raise ValueError('NAMESPACE_CHANGED')
    if getattr(agentpackage,'_chronos_binding',None)!=binding[2]:raise ValueError('AGENT_BINDING_CHANGED')
    ledger=sys.modules[module];contract=package.contract;grounded=package.grounded;agentcontract=sys.modules[agent]
    if package.ledger is not ledger or ledger.c is not contract or ledger.grounded is not grounded or grounded.g is not package.grounding.plan:raise ValueError('BOUND_MODULE_CHANGED')
    if getattr(agentpackage,'contract',None) is not agentcontract:raise ValueError('BOUND_AGENT_CHANGED')
    for value,limit in ((decisionJSON,524288),(detailJSON,262144),(scopeJSON,4096),(currentJSON,16384)):
        if type(value) is not str or len(value.encode('utf-8'))>limit:raise ValueError('INPUT_TOO_LARGE')
    detail=contract.parse(detailJSON);scope=contract.parse(scopeJSON)
    current=None if currentJSON=='' else contract.parse(currentJSON)
    render=package.grounding.plan.renderer(package.grounding.plan.RENDERER_VERSION)
    catalog=render.build(decisionJSON,detail['decisionId'],scope,projector=lambda raw,ident:detail,
        receipt_validator=agentcontract.validate_explanation,generation=generation,revision=revision,
        conversation_revision=conversationRevision,current_operation=current)
    context=grounded.from_catalog(catalog)
    return contract.canonical({'code':'CONVERSATION_CONTEXT_READY','scope':scope,'context':context,
        'context_digest':contract.digest({'scope':scope,'context':context}),'dispatch_authorized':False})
}


/// Parse after fixed-origin, CSRF and native capability checks. No model call.
ClassMethod Request(module As %String, namespace As %String, bodyHex As %String) As %String [ Language = python ]
{
    import re,sys
    if not re.fullmatch(r'_chronos_conversation_[0-9a-f]{64}\.ledger',module):raise ValueError('BOUND_MODULE_REQUIRED')
    package=sys.modules[module.rsplit('.',1)[0]]
    if package._chronos_conversation_binding[0]!=namespace:raise ValueError('NAMESPACE_CHANGED')
    ledger=sys.modules[module];contract=package.contract
    if package.ledger is not ledger or ledger.c is not contract:raise ValueError('BOUND_MODULE_CHANGED')
    if type(bodyHex) is not str or len(bodyHex)>32768:
        return contract.canonical({'allowed':False,'code':'REQUEST_TOO_LARGE'})
    if len(bodyHex)%2 or not re.fullmatch('[0-9a-fA-F]*',bodyHex):
        return contract.canonical({'allowed':False,'code':'INVALID_CONVERSATION_REQUEST'})
    try:
        body=bytes.fromhex(bodyHex).decode('utf-8',errors='strict')
    except UnicodeError:
        return contract.canonical({'allowed':False,'code':'INVALID_UTF8'})
    try:
        result=contract.validate_http_body(body)
    except contract.Invalid as ex:
        result={'allowed':False,'code':str(ex)}
    return contract.canonical(result)
}

/// Fixed English prompt from the same manifest/namespace-bound conversation module.
ClassMethod Prompt(module As %String, namespace As %String, responseContract As %String = "chronos.case-conversation.v1") As %String [ Language = python ]
{
    import re,sys
    if type(module) is not str or not re.fullmatch(r'_chronos_conversation_[0-9a-f]{64}\.ledger',module):raise ValueError('BOUND_MODULE_REQUIRED')
    package=sys.modules[module.rsplit('.',1)[0]]
    if package._chronos_conversation_binding[0]!=namespace:raise ValueError('NAMESPACE_CHANGED')
    ledger=sys.modules[module];contract=package.contract
    if package.ledger is not ledger or ledger.c is not contract or sys.modules.get(package.__name__+'.contract') is not contract:raise ValueError('BOUND_MODULE_CHANGED')
    if responseContract==contract.SCHEMA:prompt=contract.PROMPT
    elif responseContract==package.grounded.SCHEMA:prompt=package.grounding.plan.PROMPT
    elif responseContract==package.grounded_v2.SCHEMA:prompt=package.grounding.renderer_v2.PROMPT
    else:raise ValueError('INVALID_CONVERSATION_CONTRACT')
    if type(prompt) is not str or not 1<=len(prompt.encode('utf-8'))<=16384:raise ValueError('INVALID_PROMPT')
    return prompt
}
/// Native authenticated caller only. Reads the owned simulator twice; no dispatch.
ClassMethod GroundedV2Context(module As %String, namespace As %String, agent As %String, dataRoot As %String, decisionJSON As %String, detailJSON As %String, scopeJSON As %String, currentJSON As %String, authorityJSON As %String, conversationJSON As %String, previousJSON As %String, previousDetailJSON As %String, historyStatus As %String, generation As %String, revision As %Integer, conversationRevision As %Integer) As %String [ Language = python ]
{
    import re,sys
    from copy import deepcopy
    if type(module) is not str or not re.fullmatch(r'_chronos_conversation_[0-9a-f]{64}\.ledger',module):raise ValueError('BOUND_MODULE_REQUIRED')
    package=sys.modules[module.rsplit('.',1)[0]];binding=package._chronos_conversation_binding
    if binding[0]!=namespace:raise ValueError('NAMESPACE_CHANGED')
    if type(agent) is not str or not re.fullmatch(r'_chronos_agent_[0-9a-f]{64}\.contract',agent):raise ValueError('BOUND_AGENT_REQUIRED')
    agentpackage=sys.modules[agent.rsplit('.',1)[0]]
    if agentpackage._chronos_binding!=binding[2]:raise ValueError('AGENT_BINDING_CHANGED')
    ledger=sys.modules[module];c=package.contract;adapter=package.grounded_v2;render=package.grounding.renderer_v2
    if ledger is not package.ledger or ledger.c is not c or ledger.grounded_v2 is not adapter or adapter.g is not render:raise ValueError('BOUND_MODULE_CHANGED')
    sim=sys.modules[binding[2][2]];contract=sys.modules[agent]
    if render.extra.agent is not contract or sim.Runtime.__module__!=binding[2][2]:raise ValueError('BOUND_RUNTIME_CHANGED')
    for value,limit in ((decisionJSON,524288),(detailJSON,262144),(scopeJSON,4096),(currentJSON,16384),(authorityJSON,262144),(conversationJSON,524288),(previousJSON,524288),(previousDetailJSON,262144)):
        if type(value) is not str or len(value.encode('utf-8'))>limit:raise ValueError('INPUT_TOO_LARGE')
    decision=c.parse(decisionJSON);detail=c.parse(detailJSON);scope=c.parse(scopeJSON);authority=c.parse(authorityJSON)
    state=c.parse(conversationJSON);ledger.check(state,scope)
    if state['revision']!=conversationRevision:raise ValueError('CONVERSATION_REVISION_CHANGED')
    prefix=deepcopy(state)
    if prefix['turns'] and prefix['turns'][-1]['status'] in ledger.PENDING:
        prefix['turns'].pop();prefix['revision']-=1
    ledger.check(prefix,scope)
    current=None if currentJSON=='' else c.parse(currentJSON)
    previous=None if previousJSON=='' else c.parse(previousJSON)
    previous_detail=None if previousDetailJSON=='' else c.parse(previousDetailJSON)
    if (previous is None)!=(previous_detail is None):raise ValueError('HISTORY_BINDING_CHANGED')
    if type(historyStatus) is not str or historyStatus not in {'PREVIOUS_DECISION_RECORDED','HISTORY_NOT_FOUND','HISTORY_SCAN_LIMIT'}:raise ValueError('INVALID_HISTORY_READ')
    if (historyStatus=='PREVIOUS_DECISION_RECORDED')!=(previous is not None):raise ValueError('HISTORY_BINDING_CHANGED')
    def project(raw,ident):
        if raw==decisionJSON and ident==decision['requestId']:return detail
        if raw==previousJSON and previous is not None and ident==previous['requestId']:return previous_detail
        raise ValueError('HISTORY_BINDING_CHANGED')
    selected=contract.response_contract_of(decision['prepared']['record'])
    prompt=agentpackage._chronos_extraction_prompt if selected==contract.EXTRACTION_CONTRACT else agentpackage._chronos_prompt
    installed=dict(agent_manifest=agentpackage._chronos_binding[3],simulation_module=binding[2][2],installation_binding=contract.fingerprint(agentpackage._chronos_binding),prompt_sha256=contract.fingerprint(prompt))
    if decision['prepared']['record'].get('runtime_binding')!=installed:raise ValueError('CONTRACT_VERSION_CHANGED')
    runtime=sim.Runtime(dataRoot)
    def build():
        observation=runtime.observe(scope['case_id']);now=sim.clock.now_us()
        review=dict(observation=observation,authority=authority,now_us=now,gate_state='OPEN',generation=generation)
        simulator=None
        if current is not None:
            op=current['operation']
            if any(x['binding']['operation_id']==op['operationId'] and x['binding']['attempt_id']==op['attemptId'] for x in observation['operations']):
                simulator=dict(observation=observation,now_us=now)
        cat=render.build(decisionJSON,decision['requestId'],scope,projector=project,receipt_validator=contract.validate_explanation,
            generation=generation,revision=revision,conversation_revision=prefix['revision'],current_operation=current,
            conversation_state=prefix,conversation_validator=ledger.check,previous_decision_json=previousJSON or None,
            review_inputs=review,simulator_inputs=simulator)
        facts=render.extra.stable_sources(cat,review_inputs=review,simulator_inputs=simulator)
        if historyStatus=='HISTORY_SCAN_LIMIT':
            text='The bounded historical lookup reached its limit. I cannot identify the earlier decision from this read; this does not establish that no earlier decision exists. The current decision and other checked sources remain available.'
            facts['sections']['DECISION_CHANGE']={'concise':text,'detailed':text}
        checked=render.Catalog(c.canonical(facts),c.digest(facts))
        context=adapter.with_conversation_revision(adapter.from_catalog(checked),conversationRevision)
        return context
    context=build();again=build()
    if c.canonical(context)!=c.canonical(again):raise ValueError('SIMULATOR_CHANGED_DURING_READ')
    return c.canonical({'code':'CONVERSATION_CONTEXT_READY','scope':scope,'context':context,
        'context_digest':c.digest({'scope':scope,'context':context}),'dispatch_authorized':False})
}

}
