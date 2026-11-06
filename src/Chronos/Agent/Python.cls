Include %occStatus

/// Trusted composition only; no endpoints, arbitrary modules or caller URLs.
Class Chronos.Agent.Python Extends %RegisteredObject
{
ClassMethod Run(root As %String, dataRoot As %String, command As %String, args As %DynamicObject, Output result As %DynamicObject) As %Status
{
    If $TLevel Return $$$ERROR($$$GeneralError,"AGENT_REQUIRES_NO_TRANSACTION")
    Try {
        Set simulation=##class(Chronos.Runtime.Python).Module(root,$Namespace)
        Set module=..Load(root,$Namespace,simulation)
        Set result=##class(%DynamicObject).%FromJSON(..Evaluate(dataRoot,simulation,module,command,args.%ToJSON()))
    } Catch ex {
        Set result={"status":"ERROR","code":"AGENT_CONTRACT_UNAVAILABLE","dispatch_authorized":false}
        Return $$$ERROR($$$GeneralError,"AGENT_CONTRACT_UNAVAILABLE")
    }
    Return $$$OK
}

/// Trusted caller has already loaded the immutable ledger record and checked
/// READ. No I/O to model/destinations or fresh inference; only projection helpers.
ClassMethod Detail(root As %String, decisionJSON As %String, expectedId As %String, Output result As %DynamicObject) As %Status
{
    Set result={"code":"DECISION_DETAIL_UNAVAILABLE","dispatchGranted":false,"canConfirm":false,"currentAuthorityVerified":false}
    If $TLevel Return $$$ERROR($$$GeneralError,"REVIEW_REQUIRES_NO_TRANSACTION")
    Try {
        Set simulation=##class(Chronos.Runtime.Python).Module(root,$Namespace)
        Set module=..Load(root,$Namespace,simulation)
        Return ##class(Chronos.Review.Python).Project(root,$Namespace,module,simulation,decisionJSON,expectedId,.result)
    } Catch ex {
        Return $$$ERROR($$$GeneralError,"REVIEW_PROJECTION_UNAVAILABLE")
    }
}

/// Trusted conversation adapter composition. No model calls or credentials.
ClassMethod ConversationModule(root As %String, Output module As %String) As %Status
{
    Set module=""
    If $TLevel Return $$$ERROR($$$GeneralError,"CONVERSATION_LOAD_REQUIRES_NO_TRANSACTION")
    Try {
        Set simulation=##class(Chronos.Runtime.Python).Module(root,$Namespace)
        Set agent=..Load(root,$Namespace,simulation)
        Set module=##class(Chronos.Conversation.Python).Module(root,$Namespace,agent)
    } Catch ex {
        Return $$$ERROR($$$GeneralError,"CONVERSATION_MODULE_UNAVAILABLE")
    }
    Return $$$OK
}

/// Internal composition over the same freshly authenticated immutable decision.
/// The raw record and private scope never leave this bridge for model/browser I/O.
ClassMethod GroundedContext(root As %String, decisionJSON As %String, expectedDetailJSON As %String, scopeJSON As %String, currentJSON As %String, generation As %String, revision As %Integer, conversationRevision As %Integer, Output result As %DynamicObject) As %Status
{
    Set result={"code":"CONVERSATION_CONTEXT_UNAVAILABLE","dispatch_authorized":false}
    If $TLevel Return $$$ERROR($$$GeneralError,"CONVERSATION_REQUIRES_NO_TRANSACTION")
    Try {
        Set expected=##class(%DynamicObject).%FromJSON(expectedDetailJSON)
        Set simulation=##class(Chronos.Runtime.Python).Module(root,$Namespace)
        Set agent=..Load(root,$Namespace,simulation)
        Set sc=##class(Chronos.Review.Python).Project(root,$Namespace,agent,simulation,decisionJSON,expected.decisionId,.detail) $$$ThrowOnError(sc)
        If (detail.%Get("code")'="DECISION_DETAIL_RECORDED")||(detail.%ToJSON()'=expectedDetailJSON) Throw ##class(%Exception.General).%New("DECISION_CHANGED_DURING_READ")
        Set module=##class(Chronos.Conversation.Python).Module(root,$Namespace,agent)
        Set result=##class(%DynamicObject).%FromJSON(##class(Chronos.Conversation.Python).GroundedContext(module,$Namespace,agent,decisionJSON,detail.%ToJSON(),scopeJSON,currentJSON,generation,revision,conversationRevision))
    } Catch ex {
        Set result={"code":"CONVERSATION_CONTEXT_UNAVAILABLE","dispatch_authorized":false}
        Return $$$ERROR($$$GeneralError,"CONVERSATION_CONTEXT_UNAVAILABLE")
    }
    Return $$$OK
}

ClassMethod Load(root As %String, namespace As %String, simulation As %String) As %String [ Language = python, Private ]
{
    import hashlib,importlib.util,sys,threading,types
    from pathlib import Path
    root=Path(root);package=root/'chronos_agent'
    if not root.is_absolute() or root.resolve()!=root or package.resolve()!=package:raise ValueError('FIXED_AGENT_ROOT_REQUIRED')
    simroot=simulation.rsplit('.',1)[0];simmodule=sys.modules.get(simroot)
    identity=getattr(simmodule,'_chronos_identity',None)
    if not identity or identity[:2]!=(namespace,str(root)):raise ValueError('SIMULATION_BINDING_MISMATCH')
    expected={'__init__.py','engine.py','proposal.py','contract.py','timeview.py','extraction.py','AGENT_INSTRUCTIONS.txt','EXTRACTION_INSTRUCTIONS.txt'}
    if {p.name for p in package.iterdir() if p.name!='__pycache__'}!=expected:raise ValueError('UNEXPECTED_AGENT_CONTENTS')
    sources={};digest=hashlib.sha256()
    for name in sorted(expected):
        path=package/name
        if not path.is_file() or path.resolve()!=path:raise ValueError('LINKED_AGENT_SOURCE')
        sources[name]=path.read_bytes();digest.update(name.encode()+b'\0'+sources[name]+b'\0')
    manifest=digest.hexdigest();binding=(namespace,str(root),simulation,manifest)
    alias='_chronos_agent_'+hashlib.sha256(repr(binding).encode()).hexdigest()
    key='_chronos_agent_loader_v1';candidate=types.ModuleType(key);candidate.version=1;candidate.lock=threading.RLock()
    control=sys.modules.setdefault(key,candidate)
    if getattr(control,'version',None)!=1 or not hasattr(control,'lock'):raise ValueError('AGENT_LOADER_CONFLICT')
    with control.lock:
        cached=sys.modules.get(alias)
        if cached is not None:
            required={alias}|{alias+'.'+x for x in ('engine','proposal','timeview','extraction','contract')}
            if getattr(cached,'_chronos_binding',None)!=binding or {x for x in sys.modules if x==alias or x.startswith(alias+'.')}!=required:raise ValueError('PARTIAL_AGENT_PACKAGE')
            for name in required:
                file='__init__.py' if name==alias else name[len(alias)+1:]+'.py'
                if getattr(sys.modules[name],'__file__',None)!=str(package/file):raise ValueError('AGENT_ORIGIN_CHANGED')
            if sys.modules[alias+'.engine']._package!=simroot:raise ValueError('AGENT_ENGINE_CHANGED')
            return alias+'.contract'
        if any(x.startswith(alias+'.') for x in sys.modules):raise ValueError('ORPHAN_AGENT_MODULES')
        sys.dont_write_bytecode=True
        try:
            spec=importlib.util.spec_from_file_location(alias,package/'__init__.py',submodule_search_locations=[str(package)])
            module=importlib.util.module_from_spec(spec);sys.modules[alias]=module
            exec(compile(sources['__init__.py'],str(package/'__init__.py'),'exec'),module.__dict__)
            for child in ('engine','proposal','timeview','extraction','contract'):
                path=package/(child+'.py');spec=importlib.util.spec_from_file_location(alias+'.'+child,path)
                imported=importlib.util.module_from_spec(spec);sys.modules[alias+'.'+child]=imported
                if child=='engine':imported._simulation_package=simroot
                exec(compile(sources[child+'.py'],str(path),'exec'),imported.__dict__)
                setattr(module,child,imported)
            module._chronos_binding=binding
            module._chronos_prompt=sources['AGENT_INSTRUCTIONS.txt'].decode('utf-8')
            module._chronos_extraction_prompt=sources['EXTRACTION_INSTRUCTIONS.txt'].decode('utf-8')
        except BaseException:
            for name in tuple(sys.modules):
                if name==alias or name.startswith(alias+'.'):del sys.modules[name]
            raise
        return alias+'.contract'
}

ClassMethod Evaluate(dataRoot As %String, simulation As %String, module As %String, command As %String, arguments As %String) As %String [ Language = python, Private ]
{
    import importlib,json
    contract=importlib.import_module(module);sim=importlib.import_module(simulation)
    args=contract.parse(arguments)
    # Defense in depth for trusted callers bypassing Context.Review. A terminal
    # nonproposal cannot be human consent and need not touch the destination.
    if command=='REVIEW':
        decision=args.get('decision')
        if type(decision) is dict and decision.get('state')=='COMPLETED':
            outcome=decision.get('result')
            if type(outcome) is not dict or outcome.get('status')!='VALIDATED_PROPOSAL':
                return json.dumps({'status':'REJECTED','code':'DECISION_NOT_ACTIONABLE','dispatch_authorized':False})
    runtime=sim.Runtime(dataRoot)
    package=importlib.import_module(module.rsplit('.',1)[0])
    record=args['decision']['prepared']['record'] if command=='REVIEW' else args.get('record')
    selected=args.get('responseContract',contract.PROPOSAL_CONTRACT)
    if selected not in contract.RESPONSE_CONTRACTS:raise ValueError('UNSUPPORTED_RESPONSE_CONTRACT')
    if command in {'FINISH','REVIEW'} and contract.response_contract_of(record)!=selected:
        return json.dumps({'status':'REJECTED','code':'RESPONSE_CONTRACT_CHANGED','dispatch_authorized':False})
    prompt=package._chronos_extraction_prompt if selected==contract.EXTRACTION_CONTRACT else package._chronos_prompt
    binding={'agent_manifest':package._chronos_binding[3],'simulation_module':simulation,
             'installation_binding':contract.fingerprint(package._chronos_binding),
             'prompt_sha256':contract.fingerprint(prompt)}
    if command in {'FINISH','REVIEW'} and record.get('runtime_binding')!=binding:
        return json.dumps({'status':'REJECTED','code':'CONTRACT_VERSION_CHANGED','dispatch_authorized':False})
    observation=runtime.observe(args['orderId']);now=sim.clock.now_us()
    if command=='PREPARE':
        result=contract.prepare(observation,args['authority'],args['contextId'],now_us=now,
                                gate_state='OPEN',mode=args['mode'],response_contract=selected)
        if result['status']=='READY':
            result['record']['runtime_binding']=binding
            result['instructions']=prompt
            result['prompt_sha256']=contract.fingerprint(prompt)
    elif command=='FINISH':
        result=contract.finish(args['record'],args['responseText'],observation,args['authority'],
                               now_us=now,gate_state='OPEN',provider_status=args['providerStatus'])
    elif command=='REVIEW':
        result=contract.review(args['decision'],observation,args['authority'],
                               now_us=now,gate_state='OPEN',generation=args['generation'])
    else:raise ValueError('UNKNOWN_AGENT_COMMAND')
    return json.dumps(result,ensure_ascii=False,separators=(',',':'),allow_nan=False)
}
/// Host-only v2 composition. No model call, grant or browser-provided source.
ClassMethod GroundedV2Context(root As %String, dataRoot As %String, decisionJSON As %String, expectedDetailJSON As %String, scopeJSON As %String, currentJSON As %String, authorityJSON As %String, conversationJSON As %String, previousJSON As %String, historyStatus As %String, generation As %String, revision As %Integer, conversationRevision As %Integer, Output result As %DynamicObject) As %Status
{
    Set result={"code":"CONVERSATION_CONTEXT_UNAVAILABLE","dispatch_authorized":false}
    If $TLevel Return $$$ERROR($$$GeneralError,"CONVERSATION_REQUIRES_NO_TRANSACTION")
    Try {
        Set expected=##class(%DynamicObject).%FromJSON(expectedDetailJSON),previousDetailJSON=""
        Set simulation=##class(Chronos.Runtime.Python).Module(root,$Namespace)
        Set agent=..Load(root,$Namespace,simulation)
        Set sc=##class(Chronos.Review.Python).Project(root,$Namespace,agent,simulation,decisionJSON,expected.decisionId,.detail) $$$ThrowOnError(sc)
        If (detail.%Get("code")'="DECISION_DETAIL_RECORDED")||(detail.%ToJSON()'=expectedDetailJSON) Throw ##class(%Exception.General).%New("DECISION_CHANGED_DURING_READ")
        If previousJSON'="" {
            Set prior=##class(%DynamicObject).%FromJSON(previousJSON)
            Set sc=##class(Chronos.Review.Python).Project(root,$Namespace,agent,simulation,previousJSON,prior.requestId,.previousDetail) $$$ThrowOnError(sc)
            If previousDetail.%Get("code")'="DECISION_DETAIL_RECORDED" Throw ##class(%Exception.General).%New("HISTORY_UNAVAILABLE")
            Set previousDetailJSON=previousDetail.%ToJSON()
        }
        Set module=##class(Chronos.Conversation.Python).Module(root,$Namespace,agent)
        Set result=##class(%DynamicObject).%FromJSON(##class(Chronos.Conversation.Python).GroundedV2Context(module,$Namespace,agent,dataRoot,decisionJSON,detail.%ToJSON(),scopeJSON,currentJSON,authorityJSON,conversationJSON,previousJSON,previousDetailJSON,historyStatus,generation,revision,conversationRevision))
    } Catch ex { Return $$$ERROR($$$GeneralError,"CONVERSATION_CONTEXT_UNAVAILABLE") }
    Return $$$OK
}

}
