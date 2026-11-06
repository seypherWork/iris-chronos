/// Namespace/source-isolated Embedded Python package loader for trusted installs.
Class Chronos.Runtime.Python Extends %RegisteredObject
{
ClassMethod Module(root As %String, namespace As %String) As %String [ Language = python ]
{
    import hashlib,importlib,importlib.util,sys,threading,types
    from pathlib import Path
    root=Path(root)
    if not root.is_absolute() or root.resolve()!=root:raise ValueError('FIXED_SOURCE_ROOT_REQUIRED')
    package=root/'chronos_simulation'
    if package.resolve()!=package:raise ValueError('LINKED_PACKAGE_REJECTED')
    expected={'__init__.py','clock.py','model.py','realtime.py','registry.py','store.py','workflow.py'}
    entries=list(package.iterdir())
    if {p.name for p in entries if p.name!='__pycache__'}!=expected:raise ValueError('UNEXPECTED_PACKAGE_CONTENTS')
    digest=hashlib.sha256()
    sources={}
    for name in sorted(expected):
        source=package/name
        if not source.is_file() or source.resolve()!=source:raise ValueError('LINKED_OR_MISSING_SOURCE')
        sources[name]=source.read_bytes()
        digest.update(name.encode()+b'\0'+sources[name]+b'\0')
    manifest=digest.hexdigest()
    alias='_chronos_'+hashlib.sha256((namespace+'\0'+str(root)+'\0'+manifest).encode()).hexdigest()
    # IRIS reuses interpreter processes across namespaces. Do not replace or
    # import the globally named chronos_simulation package in those processes.
    key='_chronos_runtime_loader_v1'
    candidate=types.ModuleType(key)
    candidate.version=1
    candidate.lock=threading.RLock()
    control=sys.modules.setdefault(key,candidate)
    if getattr(control,'version',None)!=1 or not hasattr(control,'lock'):raise ValueError('LOADER_STATE_CONFLICT')
    with control.lock:
        cached=sys.modules.get(alias)
        if cached is not None:
            if getattr(cached,'_chronos_identity',None)!=(namespace,str(root),manifest):raise ValueError('PARTIAL_OR_FOREIGN_PACKAGE')
            required={alias}|{alias+'.'+name[:-3] for name in expected if name!='__init__.py'}
            present={name for name in sys.modules if name==alias or name.startswith(alias+'.')}
            if present!=required:raise ValueError('PARTIAL_OR_FOREIGN_PACKAGE')
            for name,module in tuple(sys.modules.items()):
                if name==alias or name.startswith(alias+'.'):
                    relative='__init__.py' if name==alias else name[len(alias)+1:].replace('.','/')+'.py'
                    file=getattr(module,'__file__',None)
                    if relative not in expected or not file or Path(file)!=package/relative:raise ValueError('MODULE_ORIGIN_CHANGED')
            return alias+'.realtime'
        if any(name.startswith(alias+'.') for name in sys.modules):raise ValueError('ORPHAN_PACKAGE_MODULES')
        sys.dont_write_bytecode=True
        spec=importlib.util.spec_from_file_location(alias,package/'__init__.py',submodule_search_locations=[str(package)])
        if spec is None or spec.loader is None:raise ValueError('PACKAGE_SPEC_UNAVAILABLE')
        module=importlib.util.module_from_spec(spec)
        sys.modules[alias]=module
        try:
            # Execute exactly the bytes included in the manifest. Preload the
            # closed dependency graph, avoiding timestamp-based .pyc caches.
            exec(compile(sources['__init__.py'],str(package/'__init__.py'),'exec'),module.__dict__)
            for child in ('model','clock','workflow','store','registry','realtime'):
                filename=package/(child+'.py')
                childspec=importlib.util.spec_from_file_location(alias+'.'+child,filename)
                imported=importlib.util.module_from_spec(childspec)
                sys.modules[alias+'.'+child]=imported
                exec(compile(sources[child+'.py'],str(filename),'exec'),imported.__dict__)
                setattr(module,child,imported)
            if Path(imported.__file__)!=package/'realtime.py':raise ValueError('MODULE_ORIGIN_CHANGED')
            module._chronos_identity=(namespace,str(root),manifest)
        except BaseException:
            # Remove only this failed, newly-owned alias. Never unload others.
            for name in tuple(sys.modules):
                if name==alias or name.startswith(alias+'.'):del sys.modules[name]
            raise
        return alias+'.realtime'
}
}
