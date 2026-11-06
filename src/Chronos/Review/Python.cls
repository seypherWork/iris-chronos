Include %occStatus

/// Trusted internal projection bridge. Caller supplies installation-owned roots
/// and aliases from the existing native loaders, never browser-controlled names.
/// This class does not load ledger records, authenticate or authorize effects.
Class Chronos.Review.Python Extends %RegisteredObject
{
ClassMethod Project(root As %String, namespace As %String, agent As %String, simulation As %String, decisionJSON As %String, expectedId As %String, Output result As %DynamicObject) As %Status
{
    Set result={"code":"DECISION_DETAIL_UNAVAILABLE","dispatchGranted":false,"canConfirm":false,"currentAuthorityVerified":false}
    If $TLevel Return $$$ERROR($$$GeneralError,"REVIEW_REQUIRES_NO_TRANSACTION")
    If namespace'=$Namespace Return $$$ERROR($$$GeneralError,"REVIEW_NAMESPACE_MISMATCH")
    Try {
        Set module=..Module(root,namespace,agent,simulation)
        Set result=##class(%DynamicObject).%FromJSON(..Evaluate(module,decisionJSON,expectedId))
    } Catch ex {
        Return $$$ERROR($$$GeneralError,"REVIEW_PROJECTION_UNAVAILABLE")
    }
    Return $$$OK
}

ClassMethod Module(root As %String, namespace As %String, agent As %String, simulation As %String) As %String [ Language = python, Private ]
{
    import hashlib,importlib.util,re,sys,threading,types
    from pathlib import Path
    root=Path(root);package=root/'chronos_review'
    if not root.is_absolute() or root.resolve()!=root or package.resolve()!=package:raise ValueError('FIXED_REVIEW_ROOT_REQUIRED')
    if not isinstance(namespace,str) or not namespace:raise ValueError('REVIEW_NAMESPACE_REQUIRED')
    if not isinstance(agent,str) or not re.fullmatch(r'_chronos_agent_[0-9a-f]{64}\.contract',agent):raise ValueError('REVIEW_AGENT_ALIAS_REQUIRED')
    if not isinstance(simulation,str) or not re.fullmatch(r'_chronos_[0-9a-f]{64}\.realtime',simulation):raise ValueError('REVIEW_SIMULATION_ALIAS_REQUIRED')
    agentroot=agent.rsplit('.',1)[0];simroot=simulation.rsplit('.',1)[0]
    agentpackage=sys.modules.get(agentroot);simpackage=sys.modules.get(simroot)
    agentbinding=getattr(agentpackage,'_chronos_binding',None)
    simbinding=getattr(simpackage,'_chronos_identity',None)
    if not isinstance(agentbinding,tuple) or len(agentbinding)!=4 or agentbinding[:3]!=(namespace,str(root),simulation):raise ValueError('REVIEW_AGENT_BINDING_MISMATCH')
    if not isinstance(simbinding,tuple) or len(simbinding)!=3 or simbinding[:2]!=(namespace,str(root)):raise ValueError('REVIEW_SIMULATION_BINDING_MISMATCH')
    for binding in (agentbinding,simbinding):
        if not isinstance(binding[-1],str) or not re.fullmatch(r'[0-9a-f]{64}',binding[-1]):raise ValueError('REVIEW_MANIFEST_REQUIRED')
    for prefix,children,directory in (
        (agentroot,('__init__','engine','proposal','timeview','extraction','contract'),'chronos_agent'),
        (simroot,('__init__','model','clock','workflow','store','registry','realtime'),'chronos_simulation')):
        required={prefix if child=='__init__' else prefix+'.'+child for child in children}
        if {name for name in sys.modules if name==prefix or name.startswith(prefix+'.')}!=required:raise ValueError('REVIEW_DEPENDENCY_GRAPH_CHANGED')
        for child in children:
            name=prefix if child=='__init__' else prefix+'.'+child
            if getattr(sys.modules[name],'__file__',None)!=str(root/directory/(child+'.py')):raise ValueError('REVIEW_DEPENDENCY_ORIGIN_CHANGED')
    if sys.modules[agentroot+'.engine']._package!=simroot:raise ValueError('REVIEW_ENGINE_BINDING_MISMATCH')
    proposal=sys.modules[agentroot+'.proposal'];model=sys.modules[simroot+'.model']
    dependencies=(proposal.parse,proposal.sensitive,proposal.OPTIONS,proposal.HOLD_REASONS,model.canonical,model.fingerprint,sys.modules[agent].response_contract_of,sys.modules[agent].validate_explanation)
    expected={'__init__.py','projection.py','README.md'}
    if {p.name for p in package.iterdir() if p.name!='__pycache__'}!=expected:raise ValueError('UNEXPECTED_REVIEW_CONTENTS')
    sources={};digest=hashlib.sha256()
    for name in sorted(expected):
        path=package/name
        if not path.is_file() or path.resolve()!=path:raise ValueError('LINKED_REVIEW_SOURCE')
        sources[name]=path.read_bytes()
        if len(sources[name])>1048576:raise ValueError('REVIEW_SOURCE_TOO_LARGE')
        digest.update(name.encode()+b'\0'+sources[name]+b'\0')
    binding=(namespace,str(root),agentbinding,simbinding,digest.hexdigest())
    alias='_chronos_review_'+hashlib.sha256(repr(binding).encode()).hexdigest()
    key='_chronos_review_loader_v1';candidate=types.ModuleType(key);candidate.version=1;candidate.lock=threading.RLock()
    control=sys.modules.setdefault(key,candidate)
    if getattr(control,'version',None)!=1 or not hasattr(control,'lock'):raise ValueError('REVIEW_LOADER_CONFLICT')
    with control.lock:
        cached=sys.modules.get(alias)
        if cached is not None:
            required={alias,alias+'.projection'}
            if getattr(cached,'_chronos_review_binding',None)!=binding or {name for name in sys.modules if name==alias or name.startswith(alias+'.')}!=required:raise ValueError('PARTIAL_REVIEW_PACKAGE')
            child=sys.modules[alias+'.projection']
            if getattr(cached,'projection',None) is not child:raise ValueError('REVIEW_CHILD_CHANGED')
            for name,filename in ((alias,'__init__.py'),(alias+'.projection','projection.py')):
                if getattr(sys.modules[name],'__file__',None)!=str(package/filename):raise ValueError('REVIEW_ORIGIN_CHANGED')
            prior=getattr(child,'_chronos_review_dependencies',())
            if len(prior)!=len(dependencies) or not all(a is b for a,b in zip(prior,dependencies)):raise ValueError('REVIEW_DEPENDENCIES_CHANGED')
            for name,value in zip(('parse','sensitive','OPTIONS','HOLD_REASONS','canonical','fingerprint','response_contract_of','validate_explanation'),dependencies):
                if getattr(child,name,None) is not value:raise ValueError('REVIEW_HELPER_CHANGED')
            return alias+'.projection'
        if any(name.startswith(alias+'.') for name in sys.modules):raise ValueError('ORPHAN_REVIEW_MODULES')
        sys.dont_write_bytecode=True
        try:
            spec=importlib.util.spec_from_file_location(alias,package/'__init__.py',submodule_search_locations=[str(package)])
            module=importlib.util.module_from_spec(spec);sys.modules[alias]=module
            exec(compile(sources['__init__.py'],str(package/'__init__.py'),'exec'),module.__dict__)
            filename=package/'projection.py'
            spec=importlib.util.spec_from_file_location(alias+'.projection',filename)
            child=importlib.util.module_from_spec(spec)
            child._chronos_review_dependencies=dependencies
            sys.modules[alias+'.projection']=child
            exec(compile(sources['projection.py'],str(filename),'exec'),child.__dict__)
            module.projection=child;module._chronos_review_binding=binding
        except BaseException:
            for name in tuple(sys.modules):
                if name==alias or name.startswith(alias+'.'):del sys.modules[name]
            raise
        return alias+'.projection'
}

ClassMethod Evaluate(module As %String, decisionJSON As %String, expectedId As %String) As %String [ Language = python, Private ]
{
    import sys
    projection=sys.modules[module]
    package=sys.modules[module.rsplit('.',1)[0]]
    namespace=package._chronos_review_binding[0]
    return projection.canonical(projection.project(decisionJSON,expectedId,namespace=namespace))
}
}
