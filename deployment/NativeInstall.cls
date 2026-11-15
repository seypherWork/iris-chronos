Include %occStatus

/// Trusted console installer, compiled into %SYS only. No HTTP route.
/// Create fresh owned objects only. Accounts/apps stay disabled; no inference.
/// Use native_install.py to verify the complete source bundle BEFORE this class.
Class Chronos.Deployment.NativeInstall Extends %RegisteredObject
{
ClassMethod Match(pattern As %String, value As %String) As %Boolean [ Private ]
{
    Set m=##class(%Regex.Matcher).%New(pattern),m.Text=value,m.OperationLimit=10000
    Return m.Locate()
}

ClassMethod Spec(id As %String, origin As %String, application As %String) As %DynamicObject
{
    If '..Match("\A[a-f0-9]{32}\z",id) Throw ##class(%Exception.General).%New("INVALID_DEPLOYMENT_ID")
    If ($Length(application)>100)||'..Match("\A/csp/chronos(?:-[a-z0-9-]+)?/\z",application) Throw ##class(%Exception.General).%New("INVALID_APPLICATION")
    If ($Length(origin)>256)||'..Match("\Ahttps?://(?:[a-z0-9.-]+|\[::1\])(?::[1-9][0-9]{0,4})?\z",origin) Throw ##class(%Exception.General).%New("INVALID_ORIGIN")
    Set scheme=$Piece(origin,"://",1),authority=$Piece(origin,"://",2)
    Set host=authority,port=""
    If $Extract(host,1)="[" { Set host=$Piece(authority,"]",1)_"]",port=$Piece(authority,"]:",2) }
    ElseIf authority[":" { Set host=$Piece(authority,":",1),port=$Piece(authority,":",2) }
    If (port'="")&&((port>65535)||(port=$Select(scheme="https":443,1:80))) Throw ##class(%Exception.General).%New("INVALID_PORT")
    If scheme="http",'$ListFind($ListBuild("127.0.0.1","localhost","[::1]"),host) Throw ##class(%Exception.General).%New("TLS_REQUIRED")
    Set short=$Extract(id,1,12),ns="CHRONOS_"_$ZConvert(short,"U"),prefix="Chronos_"_short
    Set root="/durable/chronos/"_id,main=root_"/db/",temp=root_"/temp/"
    Set resource="%DB_"_prefix,secondary="%DB_"_ns_"SECONDARY",access=prefix_"_Access"
    Set temporary=resource_"_TEMP"
    Set s={"layoutVersion":4,"id":(id),"namespace":(ns),"prefix":(prefix),"root":(root),"origin":(origin),"application":(application),"access":(access),"resource":(resource),"tempResource":(temporary),"secondaryResource":(secondary)}
    Set s.databases=[{"name":(ns),"directory":(main),"resource":(resource),"journal":3},{"name":(ns_"_TEMP"),"directory":(temp),"resource":(temporary),"journal":2},{"name":(ns_"SECONDARY"),"directory":(main_$ZConvert(ns,"L")_"secondary/"),"resource":(secondary),"journal":3}]
    Set s.roles=[{"name":(prefix_"_Base"),"resources":(resource_":RW,"_temporary_":RW,%DB_IRISSYS:R,"_access_":U")},{"name":(prefix_"_Read"),"resources":"Chronos_Read:U"},{"name":(prefix_"_Approve"),"resources":"Chronos_Approve:U"},{"name":(prefix_"_Python"),"resources":"%Service_EmbeddedPython:U"}]
    Set base=prefix_"_Base,"_prefix_"_Read"
    Set s.users=[{"name":(prefix_"_Reader"),"roles":(base)},{"name":(prefix_"_Operator"),"roles":(base_","_prefix_"_Approve")}]
    Set s.defaultApplication="/csp/"_$ZConvert(ns,"L"),s.webPath=$Extract(application,1,*-1),s.destinations=root_"/owned-destinations"
    Return s
}

ClassMethod Context() As %Boolean [ Private ]
{
    If ($Namespace'="%SYS")||$TLevel||$Data(%request)||$Data(%session) Return 0
    If $Username'="irisowner" Return 0
    Return $ZVersion["2026.3.0AI (Build 154U)"
}

ClassMethod Lookup(class As %String, name As %String, absentCode As %String) As %String [ Private ]
{
    Set sc=0,found=0
    Try { Set found=$ClassMethod(class,"Exists",name,,.sc) }
    Catch ex { Return "LOOKUP_ERROR" }
    If found,$System.Status.IsOK(sc),$System.Status.GetErrorCodes(sc)="" Return "PRESENT"
    If 'found,$System.Status.IsError(sc),$System.Status.GetErrorCodes(sc)=absentCode Return "ABSENT"
    Return "LOOKUP_ERROR"
}

ClassMethod Add(rows As %DynamicArray, kind As %String, name As %String, class As %String, code As %String) [ Private ]
{
    Set status=..Lookup(class,name,code)
    If status="PRESENT" Set status="CONFLICT"
    Do rows.%Push({"kind":(kind),"name":(name),"status":(status)})
}

/// Hash exact UTF8 file bytes, not a native character-string conversion. The
/// fixed path is already covered by native_install.py's verified RO bundle.
ClassMethod WorkflowQuerySourceSHA256() As %String [ Language = python, Private ]
{
    from pathlib import Path
    from hashlib import sha256
    import stat
    try:
        path=Path('/opt/chronos/deployment/WorkflowAccountQuery.cls')
        if any(p.is_symlink() for p in (path,*path.parents)):return ''
        before=path.stat()
        if not stat.S_ISREG(before.st_mode) or not 0<before.st_size<=1048576:return ''
        raw=path.read_bytes();raw.decode('utf-8','strict')
        after=path.stat()
        def identity(info):return info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns
        if identity(before)!=identity(after) or len(raw)!=before.st_size:return ''
        return sha256(raw).hexdigest()
    except Exception:return ''
}

/// Pure classification only. A source digest or marker is not authorization.
/// Partial, unknown and unowned states never permit a compile or blind retry.
ClassMethod WorkflowQueryPolicy(sourceSHA As %String, present As %Boolean, markerData As %Integer, markerJSON As %String, metadataReady As %Boolean) As %String [ Language = python, Private ]
{
    import json,re
    out=dict(status='QUERY_STATE_UNAVAILABLE',sourceSha256='',classPresent=bool(present),markerPresent=bool(markerData),metadataVerified=bool(metadataReady),reuse=False)
    def emit(code):out['status']=code;return json.dumps(out,sort_keys=True,separators=(',',':'))
    if type(sourceSHA)is not str or re.fullmatch(r'[a-f0-9]{64}',sourceSHA)is None:return emit('QUERY_SOURCE_UNAVAILABLE')
    out['sourceSha256']=sourceSHA
    if markerData==0:return emit('QUERY_CLASS_UNOWNED' if present else 'ABSENT_AND_SOURCE_VERIFIED')
    if markerData!=1:return emit('QUERY_MARKER_INVALID')
    try:
        def pairs(items):
            d={}
            for k,v in items:
                if k in d:raise ValueError('DUPLICATE_MARKER_FIELD')
                d[k]=v
            return d
        marker=json.loads(markerJSON,object_pairs_hook=pairs)
        fields={'schema','state','sourceSha256','deploymentId','manifestSha256'}
        if type(marker)is not dict or set(marker)!=fields or any(type(v)is not str for v in marker.values()):return emit('QUERY_MARKER_INVALID')
        if marker['schema']!='chronos.workflow-system-query.v1' or marker['state'] not in ('LOADING','READY','PARTIAL_PRESERVED_NO_RETRY'):return emit('QUERY_MARKER_INVALID')
        if re.fullmatch(r'[a-f0-9]{32}',marker['deploymentId'])is None or any(re.fullmatch(r'[a-f0-9]{64}',marker[k])is None for k in ('sourceSha256','manifestSha256')):return emit('QUERY_MARKER_INVALID')
        if marker['state']!='READY':return emit('QUERY_PARTIAL_NO_RETRY')
        if marker['sourceSha256']!=sourceSHA:return emit('QUERY_SOURCE_CHANGED')
        if not present or not metadataReady:return emit('QUERY_METADATA_UNAVAILABLE')
        out['reuse']=True
        return emit('OWNED_READY_SOURCE_MATCHED')
    except (ValueError,TypeError,UnicodeError,OverflowError,RecursionError):return emit('QUERY_MARKER_INVALID')
}

/// Read only fixed dictionary metadata. This is not attestation against manual
/// alteration of compiled method bodies after installation.
ClassMethod WorkflowQueryMetadata() As %Boolean [ Private ]
{
    Try {
        Set name="%ZChronos.Workflow.AccountQuery"
        If '##class(%Dictionary.CompiledClass).%ExistsId(name) Return 0
        If '##class(%Dictionary.CompiledMethod).%ExistsId(name_"||ReadFlags") Return 0
        If '##class(%Dictionary.CompiledQuery).%ExistsId(name_"||ReadOne") Return 0
        Set parameter=##class(%Dictionary.CompiledParameter).%OpenId(name_"||RESOURCEREQUIRED",0,.sc)
        If $$$ISERR(sc)||'$IsObject(parameter) Return 0
        Return parameter.Default="%Admin_Secure"
    } Catch ex { Return 0 }
}

/// Used by Inspect too: no OBJ.Load, class save, marker write or account read.
ClassMethod WorkflowQueryStatus() As %DynamicObject [ Private ]
{
    Set sourceSHA=..WorkflowQuerySourceSHA256()
    Set present=##class(%Dictionary.CompiledClass).%ExistsId("%ZChronos.Workflow.AccountQuery")
    Set data=$Data(^ChronosInstall("workflowSystemQuery")),raw=$Get(^ChronosInstall("workflowSystemQuery"))
    Set metadata=..WorkflowQueryMetadata()
    Return ##class(%DynamicObject).%FromJSON(..WorkflowQueryPolicy(sourceSHA,present,data,raw,metadata))
}

/// Called only under Install's existing mutex, approval and console checks.
/// One shared compile; a failed attempt remains fenced even before accounts or
/// databases are created. Reuse checks the RO source hash and narrow metadata.
ClassMethod InstallWorkflowQuery(id As %String, digest As %String, Output view As %DynamicObject) As %Status [ Private ]
{
    Set view=..WorkflowQueryStatus(),begun=0
    If '..Context() Return $$$ERROR($$$GeneralError,"WORKFLOW_QUERY_CONSOLE_REQUIRED")
    If view.status="OWNED_READY_SOURCE_MATCHED" Return $$$OK
    If view.status'="ABSENT_AND_SOURCE_VERIFIED" Return $$$ERROR($$$GeneralError,"WORKFLOW_QUERY_PREFLIGHT_REJECTED")
    Set sc=$$$OK
    Try {
        If $Data(^ChronosInstall("workflowSystemQuery"))||##class(%Dictionary.CompiledClass).%ExistsId("%ZChronos.Workflow.AccountQuery") Throw ##class(%Exception.General).%New("WORKFLOW_QUERY_COLLISION")
        Set marker={"schema":"chronos.workflow-system-query.v1","state":"LOADING","sourceSha256":(view.sourceSha256),"deploymentId":(id),"manifestSha256":(digest)}
        Set ^ChronosInstall("workflowSystemQuery")=marker.%ToJSON(),begun=1
        If (..WorkflowQuerySourceSHA256()'=view.sourceSha256)||##class(%Dictionary.CompiledClass).%ExistsId("%ZChronos.Workflow.AccountQuery") Throw ##class(%Exception.General).%New("WORKFLOW_QUERY_CHANGED")
        Set sc=$System.OBJ.Load("/opt/chronos/deployment/WorkflowAccountQuery.cls","ck") $$$ThrowOnError(sc)
        If (..WorkflowQuerySourceSHA256()'=view.sourceSha256)||'..WorkflowQueryMetadata() Throw ##class(%Exception.General).%New("WORKFLOW_QUERY_READBACK_FAILED")
        Set marker.state="READY",^ChronosInstall("workflowSystemQuery")=marker.%ToJSON()
        Set view=..WorkflowQueryStatus()
        If view.status'="OWNED_READY_SOURCE_MATCHED" Throw ##class(%Exception.General).%New("WORKFLOW_QUERY_MARKER_READBACK_FAILED")
    } Catch ex {
        If begun Set marker.state="PARTIAL_PRESERVED_NO_RETRY",^ChronosInstall("workflowSystemQuery")=marker.%ToJSON()
        Set sc=$$$ERROR($$$GeneralError,"WORKFLOW_QUERY_INSTALLATION_FAILED")
    }
    Return sc
}

/// Fresh-install-only helpers. Inspection never compiles or reuses these classes.
ClassMethod WorkflowDeliveryAbsent() As %Boolean [ Private ]
{
    For name="Chronos.Deployment.NativeWorkflowInspect","Chronos.Deployment.NativeWorkflowApply" {
        If ##class(%Dictionary.ClassDefinition).%ExistsId(name)||##class(%Dictionary.CompiledClass).%ExistsId(name) Return 0
    }
    Return 1
}

ClassMethod WorkflowDeliverySources() As %String [ Language = python, Private ]
{
    from pathlib import Path
    from hashlib import sha256
    import json,stat
    try:
        out={}
        for name in ('NativeWorkflowInspect','NativeWorkflowApply'):
            path=Path('/opt/chronos/deployment')/(name+'.cls')
            if any(p.is_symlink() for p in (path,*path.parents)):return ''
            before=path.stat()
            if not stat.S_ISREG(before.st_mode) or not 0<before.st_size<=1048576:return ''
            raw=path.read_bytes();raw.decode('utf-8','strict');after=path.stat()
            identity=lambda v:(v.st_dev,v.st_ino,v.st_size,v.st_mtime_ns)
            if identity(before)!=identity(after) or len(raw)!=before.st_size:return ''
            out['Chronos.Deployment.'+name]=sha256(raw).hexdigest()
        return json.dumps(out,sort_keys=True,separators=(',',':'))
    except Exception:return ''
}

/// Build154 metadata probe verified ClassDefinition.TimeChanged is RawString.
/// Compare exact strings; do not round, parse as a float or accept recompiled code.
ClassMethod WorkflowDeliveryTime(name As %String) As %String [ Private ]
{
    If '$ListFind($ListBuild("Chronos.Deployment.NativeWorkflowInspect","Chronos.Deployment.NativeWorkflowApply"),name) Return ""
    If '##class(%Dictionary.CompiledClass).%ExistsId(name) Return ""
    Set definition=##class(%Dictionary.ClassDefinition).%OpenId(name,0,.sc)
    If $$$ISERR(sc)||'$IsObject(definition) Return ""
    Return definition.TimeChanged
}

ClassMethod InstallWorkflowDelivery(id As %String, digest As %String) As %Status [ Private ]
{
    Set begun=0
    Try {
        If '..WorkflowDeliveryAbsent()||$Data(^ChronosInstall(id,"workflowDelivery")) Throw ##class(%Exception.General).%New("WORKFLOW_DELIVERY_COLLISION")
        Set raw=..WorkflowDeliverySources()
        If raw="" Throw ##class(%Exception.General).%New("WORKFLOW_DELIVERY_SOURCE_UNAVAILABLE")
        Set sources=##class(%DynamicObject).%FromJSON(raw)
        Set marker={"schema":"chronos.workflow-delivery.v1","state":"INSTALLING","deploymentId":(id),"baseBundleManifestSha256":(digest),"classes":{}}
        Set ^ChronosInstall(id,"workflowDelivery")=marker.%ToJSON(),begun=1
        For name="NativeWorkflowInspect","NativeWorkflowApply" {
            Set klass="Chronos.Deployment."_name
            If ##class(%Dictionary.ClassDefinition).%ExistsId(klass)||##class(%Dictionary.CompiledClass).%ExistsId(klass) Throw ##class(%Exception.General).%New("WORKFLOW_DELIVERY_CLASS_CHANGED")
            If ..WorkflowDeliverySources()'=raw Throw ##class(%Exception.General).%New("WORKFLOW_DELIVERY_SOURCE_CHANGED")
            Set sc=$System.OBJ.Load("/opt/chronos/deployment/"_name_".cls","ck") $$$ThrowOnError(sc)
            Set stamp=..WorkflowDeliveryTime(klass)
            If stamp="" Throw ##class(%Exception.General).%New("WORKFLOW_DELIVERY_METADATA_UNAVAILABLE")
            Do marker.classes.%Set(klass,{"sourceSha256":(sources.%Get(klass)),"timeChanged":(stamp)})
            Set ^ChronosInstall(id,"workflowDelivery")=marker.%ToJSON()
        }
        If ..WorkflowDeliverySources()'=raw Throw ##class(%Exception.General).%New("WORKFLOW_DELIVERY_SOURCE_CHANGED")
        Set marker.state="OWNED_READY",^ChronosInstall(id,"workflowDelivery")=marker.%ToJSON()
        Return $$$OK
    } Catch ex {
        If begun {
            Set marker.state="PARTIAL_PRESERVED_NO_RETRY",^ChronosInstall(id,"workflowDelivery")=marker.%ToJSON()
        }
        Return $$$ERROR($$$GeneralError,"WORKFLOW_DELIVERY_PROVISIONING_FAILED")
    }
}

/// Pure marker policy: exact metadata strings, fixed two-class closure, no reuse.
ClassMethod WorkflowDeliveryPolicy(id As %String, bundle As %String, markerJSON As %String, sourcesJSON As %String, metadataJSON As %String) As %Boolean [ Language = python, Private ]
{
    import json,re
    try:
        def pairs(items):
            out={}
            for k,v in items:
                if k in out:raise ValueError('DUPLICATE')
                out[k]=v
            return out
        def bad(_):raise ValueError('NONFINITE')
        def parse(raw):return json.loads(raw,object_pairs_hook=pairs,parse_constant=bad)
        if type(id)is not str or not re.fullmatch(r'[a-f0-9]{32}',id):return False
        if type(bundle)is not str or not re.fullmatch(r'[a-f0-9]{64}',bundle):return False
        marker=parse(markerJSON);sources=parse(sourcesJSON);metadata=parse(metadataJSON)
        names={'Chronos.Deployment.NativeWorkflowInspect','Chronos.Deployment.NativeWorkflowApply'}
        if type(marker)is not dict or set(marker)!={'schema','state','deploymentId','baseBundleManifestSha256','classes'}:return False
        if (marker['schema'],marker['state'],marker['deploymentId'],marker['baseBundleManifestSha256'])!=('chronos.workflow-delivery.v1','OWNED_READY',id,bundle):return False
        if any(type(v)is not dict or set(v)!=names for v in (marker['classes'],sources,metadata)):return False
        for name in names:
            row=marker['classes'][name]
            if type(row)is not dict or set(row)!={'sourceSha256','timeChanged'}:return False
            if type(sources[name])is not str or not re.fullmatch(r'[a-f0-9]{64}',sources[name]) or row['sourceSha256']!=sources[name]:return False
            if type(row['timeChanged'])is not str or type(metadata[name])is not str or not 0<len(metadata[name])<=128 or row['timeChanged']!=metadata[name]:return False
        return True
    except (ValueError,TypeError,KeyError,UnicodeError,OverflowError,RecursionError):return False
}

/// Console-only readback; no compilation, repair, account or production mutation.
ClassMethod WorkflowDeliveryStatus(id As %String) As %DynamicObject
{
    Set result={"status":"WORKFLOW_DELIVERY_UNAVAILABLE","ready":false,"verified":false,"modelCalls":0}
    If '..Context()||'..Match("\A[a-f0-9]{32}\z",id) Return result
    Try {
        If $Get(^ChronosInstall(id,"state"))'="NATIVE_INSTALLED_DISABLED" Return result
        Set raw=$Get(^ChronosInstall(id,"workflowDelivery"))
        If raw="" Return result
        Set sources=..WorkflowDeliverySources(),metadata={}
        If sources="" Return result
        For name="Chronos.Deployment.NativeWorkflowInspect","Chronos.Deployment.NativeWorkflowApply" {
            Do metadata.%Set(name,..WorkflowDeliveryTime(name),"string")
        }
        If '..WorkflowDeliveryPolicy(id,$Get(^ChronosInstall(id,"bundle")),raw,sources,metadata.%ToJSON()) Return result
        Return {"status":"OWNED_WORKFLOW_DELIVERY_READY","ready":false,"verified":true,"deploymentId":(id),"modelCalls":0}
    } Catch ex { Return result }
}

ClassMethod Inspect(id As %String, origin As %String, application As %String) As %String
{
    Set result={"status":"PREFLIGHT_REJECTED","applied":false,"ready":false,"rows":[]}
    If '..Context() Return result.%ToJSON()
    Try {
        Set s=..Spec(id,origin,application),result.spec=s,rows=result.rows
        Do ..Add(rows,"namespace",s.namespace,"Config.Namespaces","420")
        For i=0:1:2 { Set d=s.databases.%Get(i) Do ..Add(rows,"database",d.name,"Config.Databases","420") }
        For i=0:1:3 { Set role=s.roles.%Get(i) Do ..Add(rows,"role",role.name,"Security.Roles","883") }
        For i=0:1:1 { Set user=s.users.%Get(i) Do ..Add(rows,"user",user.name,"Security.Users","838") }
        For name=s.resource,s.tempResource,s.secondaryResource,s.access { Do ..Add(rows,"resource",name,"Security.Resources","892") }
        For name="Chronos_Read","Chronos_Approve" {
            Set status=..Lookup("Security.Resources",name,"892")
            If status="PRESENT" {
                Kill p Set sc=##class(Security.Resources).Get(name,.p)
                If $System.Status.IsError(sc)||($Get(p("PublicPermission"))'="")||'$ListFind($ListBuild("Owned Chronos HTTP laboratory","Chronos supervised recovery application"),$Get(p("Description"))) Set status="CONFLICT"
            }
            Do rows.%Push({"kind":"shared_resource","name":(name),"status":(status)})
        }
        For name="%Service_EmbeddedPython","%DB_IRISSYS" {
            Set status=..Lookup("Security.Resources",name,"892")
            If status="ABSENT" Set status="MISSING_REQUIRED"
            Do rows.%Push({"kind":"required_resource","name":(name),"status":(status)})
        }
        For name=s.defaultApplication,s.webPath { Do ..Add(rows,"application",name,"Security.Applications","869") }
        For path=s.root,s.destinations { Do rows.%Push({"kind":"directory","name":(path),"status":($Select(##class(%File).Exists(path):"CONFLICT",1:"ABSENT"))}) }
        For i=0:1:2 { Set path=s.databases.%Get(i).directory Do rows.%Push({"kind":"directory","name":(path),"status":($Select(##class(%File).Exists(path):"CONFLICT",1:"ABSENT"))}) }
        Set result.workflowSystemQuery=..WorkflowQueryStatus(),bad=0
        Set result.workflowDeliveryClassesAbsent=..WorkflowDeliveryAbsent()
        If 'result.workflowDeliveryClassesAbsent Set bad=bad+1
        If '$ListFind($ListBuild("ABSENT_AND_SOURCE_VERIFIED","OWNED_READY_SOURCE_MATCHED"),result.workflowSystemQuery.status) Set bad=bad+1
        For i=0:1:(rows.%Size()-1) { If '$ListFind($ListBuild("ABSENT","PRESENT"),rows.%Get(i).status) Set bad=bad+1 }
        If $Data(^ChronosInstall(id)) Set bad=bad+1
        Set result.conflicts=bad,result.intentExists=+$Data(^ChronosInstall(id))
        If bad=0 Set result.status="NAMES_CLEAR_NOT_AUTHORIZATION"
    } Catch ex { Set result.status="PREFLIGHT_FAILED" }
    Return result.%ToJSON()
}

ClassMethod SameList(actual As %String, expected As %String) As %Boolean [ Private ]
{
    If $Length(actual,",")'=$Length(expected,",") Return 0
    For i=1:1:$Length(actual,",") {
        Set part=$Piece(actual,",",i)
        If (part="")||$Data(seen(part))||'$ListFind($ListFromString(expected),part) Return 0
        Set seen(part)=1
    }
    Return 1
}

ClassMethod Database(d As %DynamicObject) As %Status [ Private ]
{
    If ##class(%File).Exists(d.directory) Return $$$ERROR($$$GeneralError,"DATABASE_PATH_EXISTS")
    If '##class(%File).CreateDirectoryChain(d.directory) Return $$$ERROR($$$GeneralError,"DIRECTORY_CREATE_FAILED")
    Set sc=##class(SYS.Database).CreateDatabase(d.directory,8,8192,0,d.resource,d.journal)
    If $$$ISERR(sc) Return sc
    Set p("Directory")=d.directory,p("MountAtStartup")=1
    Return ##class(Config.Databases).Create(d.name,.p)
}

ClassMethod DisableDefault(s As %DynamicObject, Output outcome As %String) As %Status [ Private ]
{
    Set outcome="DEFAULT_APP_CLOSURE_UNVERIFIED"
    Set status=..Lookup("Security.Applications",s.defaultApplication,"869")
    If status="ABSENT" Set outcome="DEFAULT_APP_ABSENT" Return $$$OK
    If status'="PRESENT" Return $$$ERROR($$$GeneralError,"DEFAULT_APP_LOOKUP_FAILED")
    // An intent alone does not prove ownership after a failed namespace create.
    Kill p Set sc=##class(Config.Namespaces).Get(s.namespace,.p) If $$$ISERR(sc) Return sc
    If ($Get(p("Globals"))'=s.namespace)||($Get(p("Routines"))'=s.namespace)||($Get(p("TempGlobals"))'=(s.namespace_"_TEMP")) Return $$$ERROR($$$GeneralError,"NAMESPACE_OWNERSHIP_UNVERIFIED")
    For i=0:1:1 {
        Set d=s.databases.%Get(i)
        If '$Get(^ChronosInstall(s.id,"createdDatabase",d.name)) Return $$$ERROR($$$GeneralError,"DATABASE_NOT_OWNED")
        Kill p Set sc=##class(Config.Databases).Get(d.name,.p) If $$$ISERR(sc) Return sc
        If $Get(p("Directory"))'=d.directory Return $$$ERROR($$$GeneralError,"DATABASE_DIRECTORY_CHANGED")
        Set db=##class(SYS.Database).%OpenId(d.directory)
        If '$IsObject(db)||(db.ResourceName'=d.resource) Return $$$ERROR($$$GeneralError,"DATABASE_RESOURCE_CHANGED")
    }
    Kill p Set sc=##class(Security.Applications).Get(s.defaultApplication,.p)
    If $$$ISERR(sc) Return sc
    If $ZConvert($Get(p("NameSpace")),"U")'=s.namespace Return $$$ERROR($$$GeneralError,"DEFAULT_APP_WRONG_NAMESPACE")
    Kill p Set p("Enabled")=0
    Set sc=##class(Security.Applications).Modify(s.defaultApplication,.p)
    If $$$ISERR(sc) Return sc
    Kill p Set sc=##class(Security.Applications).Get(s.defaultApplication,.p)
    If $$$ISERR(sc)||p("Enabled") Return $$$ERROR($$$GeneralError,"DEFAULT_APP_NOT_DISABLED")
    Set outcome="DEFAULT_APP_DISABLED"
    Return $$$OK
}

ClassMethod VerifyStorage(s As %DynamicObject) As %Status [ Private ]
{
    Kill p Set sc=##class(Config.Namespaces).Get(s.namespace,.p) If $$$ISERR(sc) Return sc
    If ($Get(p("Globals"))'=s.namespace)||($Get(p("Routines"))'=s.namespace)||($Get(p("TempGlobals"))'=(s.namespace_"_TEMP")) Return $$$ERROR($$$GeneralError,"NAMESPACE_STORAGE_CHANGED")
    For i=0:1:2 {
        Set d=s.databases.%Get(i)
        Kill p Set sc=##class(Config.Databases).Get(d.name,.p) If $$$ISERR(sc) Return sc
        If $Get(p("Directory"))'=d.directory Return $$$ERROR($$$GeneralError,"DATABASE_DIRECTORY_CHANGED")
        Set db=##class(SYS.Database).%OpenId(d.directory)
        If '$IsObject(db)||(db.ResourceName'=d.resource) Return $$$ERROR($$$GeneralError,"DATABASE_RESOURCE_READBACK_FAILED")
        If db.GlobalJournalState'=d.journal Return $$$ERROR($$$GeneralError,"JOURNAL_READBACK_FAILED")
    }
    If ##class(%SYS.Namespace).GetGlobalDest(s.namespace,"ChronosRuntime")'=("^"_s.databases.%Get(0).directory) Return $$$ERROR($$$GeneralError,"MAIN_MAPPING_READBACK_FAILED")
    For mapping="IRIS.Temp","IRIS.Temp.EnsJobStatus","IRIS.TempCSPLang" {
        If ##class(%SYS.Namespace).GetGlobalDest(s.namespace,mapping)'=("^"_s.databases.%Get(1).directory) Return $$$ERROR($$$GeneralError,"TEMP_MAPPING_READBACK_FAILED")
    }
    If ##class(%SYS.Namespace).GetGlobalDest(s.namespace,"Ens.SecondaryData")'=("^"_s.databases.%Get(2).directory) Return $$$ERROR($$$GeneralError,"SECONDARY_MAPPING_READBACK_FAILED")
    For name=s.resource,s.tempResource,s.secondaryResource,s.access,"Chronos_Read","Chronos_Approve" {
        Kill p Set sc=##class(Security.Resources).Get(name,.p) If $$$ISERR(sc) Return sc
        If $Get(p("PublicPermission"))'="" Return $$$ERROR($$$GeneralError,"RESOURCE_PUBLIC_READBACK_FAILED")
    }
    Return $$$OK
}

ClassMethod VerifyDisabled(s As %DynamicObject) As %Status [ Private ]
{
    Set sc=..VerifyStorage(s) If $$$ISERR(sc) Return sc
    For i=0:1:3 {
        Set role=s.roles.%Get(i)
        Kill p Set sc=##class(Security.Roles).Get(role.name,.p) $$$ThrowOnError(sc)
        If '..SameList(p("Resources"),role.resources)||($Get(p("GrantedRoles"))'="")||p("EscalationOnly") Return $$$ERROR($$$GeneralError,"ROLE_READBACK_FAILED")
    }
    For i=0:1:1 {
        Set user=s.users.%Get(i)
        Kill p Set sc=##class(Security.Users).Get(user.name,.p) $$$ThrowOnError(sc)
        If p("Enabled")||'..SameList(p("Roles"),user.roles)||($Get(p("EscalationRoles"))'="") Return $$$ERROR($$$GeneralError,"USER_READBACK_FAILED")
    }
    Kill p Set sc=##class(Security.Applications).Get(s.webPath,.p) $$$ThrowOnError(sc)
    If p("Enabled")||(p("Resource")'=s.access)||(p("AutheEnabled")'=32)||(p("MatchRoles")'=(s.prefix_"_Read:"_s.prefix_"_Python")) Return $$$ERROR($$$GeneralError,"APP_AUTH_READBACK_FAILED")
    If (p("DispatchClass")'="Chronos.Web.API")||(p("EventClass")'="Chronos.Web.Events")||(p("NameSpace")'=s.namespace)||(p("Timeout")'=3600) Return $$$ERROR($$$GeneralError,"APP_READBACK_FAILED")
    If (p("UseCookies")'=2)||(p("CookiePath")'=s.application)||(p("SessionScope")'=2)||(p("UserCookieScope")'=2)||p("GroupById")||'p("CSPZENEnabled") Return $$$ERROR($$$GeneralError,"COOKIE_READBACK_FAILED")
    Return ..DisableDefault(s)
}

ClassMethod EmptyCatalog(root As %String, module As %String) [ Language = python, Private ]
{
    import importlib
    # Module was obtained from the validated namespace-isolated product loader.
    importlib.import_module(module).Runtime(root,create=True)
}

ClassMethod ApplicationPhase(s As %DynamicObject) As %Status [ Private ]
{
    New $Namespace
    Set $Namespace=s.namespace
    Set sc=$System.OBJ.LoadDir("/opt/chronos/src/Chronos","ck",.errors,1)
    If $$$ISERR(sc) Return sc
    Set module=##class(Chronos.Runtime.Python).Module("/opt/chronos/src",$Namespace)
    Set $Namespace="%SYS"
    Do ..EmptyCatalog(s.destinations,module)
    Set $Namespace=s.namespace
    Set sc=##class(Chronos.Runtime.Bootstrap).Configure("Chronos.App.Production",s.destinations,"/opt/chronos/src")
    If $$$ISERR(sc) Return sc
    Set installationId=$ZConvert($System.Encryption.ToHex($System.Encryption.GenCryptRand(32,1)),"L")
    If $Length(installationId)'=64 Return $$$ERROR($$$GeneralError,"INSTALLATION_ID_FAILED")
    If $Data(^ChronosWeb("config")) Return $$$ERROR($$$GeneralError,"WEB_CONFIG_EXISTS")
    Set ^ChronosWeb("config")={"origin":(s.origin),"application":(s.application),"installationId":(installationId)}.%ToJSON()
    Return $$$OK
}

ClassMethod Install(id As %String, origin As %String, application As %String, digest As %String) As %String
{
    Set result={"status":"INSTALL_REJECTED","ready":false,"accountsEnabled":false,"modelCalls":0}
    If '..Context() Return result.%ToJSON()
    If '..Match("\A[a-f0-9]{64}\z",digest) Return result.%ToJSON()
    If $System.Util.GetEnviron("CHRONOS_INSTALL_APPROVED")'=(id_":"_digest) Return result.%ToJSON()
    Lock +^ChronosInstallLock:0
    If '$Test Set result.status="INSTALL_BUSY" Return result.%ToJSON()
    Set begun=0
    Try {
        Set check=##class(%DynamicObject).%FromJSON(..Inspect(id,origin,application))
        If check.status'="NAMES_CLEAR_NOT_AUTHORIZATION" Throw ##class(%Exception.General).%New("PREFLIGHT_CHANGED")
        Set s=check.spec,begun=1
        Set ^ChronosInstall(id,"state")="INSTALLING",^ChronosInstall(id,"spec")=s.%ToJSON(),^ChronosInstall(id,"bundle")=digest
        Set ^ChronosInstall(id,"phase")="WORKFLOW_SYSTEM_QUERY"
        Set sc=..InstallWorkflowQuery(id,digest,.query) $$$ThrowOnError(sc)
        Set result.workflowSystemQuery=query
        Set ^ChronosInstall(id,"phase")="WORKFLOW_DELIVERY"
        Set sc=..InstallWorkflowDelivery(id,digest) $$$ThrowOnError(sc)
        Set ^ChronosInstall(id,"phase")="RESOURCES"
        For name=s.resource,s.tempResource,s.secondaryResource,s.access,"Chronos_Read","Chronos_Approve" {
            Set status=..Lookup("Security.Resources",name,"892")
            If status="ABSENT" {
                Set sc=##class(Security.Resources).Create(name,"Chronos supervised recovery application","") $$$ThrowOnError(sc)
                Set ^ChronosInstall(id,"createdResource",name)=1
            } Else {
                If (status'="PRESENT")||'$ListFind($ListBuild("Chronos_Read","Chronos_Approve"),name) Throw ##class(%Exception.General).%New("RESOURCE_LOOKUP_OR_COLLISION")
                Kill p Set sc=##class(Security.Resources).Get(name,.p) $$$ThrowOnError(sc)
                If ($Get(p("PublicPermission"))'="")||'$ListFind($ListBuild("Owned Chronos HTTP laboratory","Chronos supervised recovery application"),$Get(p("Description"))) Throw ##class(%Exception.General).%New("SHARED_RESOURCE_CHANGED")
            }
        }
        For name=s.resource,s.tempResource,s.secondaryResource,s.access,"Chronos_Read","Chronos_Approve" {
            Kill p Set sc=##class(Security.Resources).Get(name,.p) $$$ThrowOnError(sc)
            If $Get(p("PublicPermission"))'="" Throw ##class(%Exception.General).%New("RESOURCE_PUBLIC_READBACK_FAILED")
        }
        Set ^ChronosInstall(id,"phase")="DATABASES"
        For i=0:1:1 {
            Set d=s.databases.%Get(i),sc=..Database(d) $$$ThrowOnError(sc)
            Set ^ChronosInstall(id,"createdDatabase",d.name)=1
        }
        Kill p Set p("Globals")=s.namespace,p("Routines")=s.namespace,p("TempGlobals")=s.namespace_"_TEMP",p("Interop")=1
        Set ^ChronosInstall(id,"phase")="NAMESPACE",^ChronosInstall(id,"namespaceIntent")=1
        Set sc=##class(Config.Namespaces).Create(s.namespace,.p)
        // Check/disable the automatically created route even on partial failure.
        Set ^ChronosInstall(id,"namespaceCreateOK")=+$System.Status.IsOK(sc),^ChronosInstall(id,"namespaceCreateCodes")=$System.Status.GetErrorCodes(sc)
        Set disable=..DisableDefault(s,.closure),^ChronosInstall(id,"defaultApplicationClosure")=closure
        $$$ThrowOnError(sc) $$$ThrowOnError(disable)
        Set ^ChronosInstall(id,"phase")="STORAGE_READBACK",^ChronosInstall(id,"namespaceCreated")=1
        // Build154 reuses the explicit private TEMP; SECONDARY is implicit.
        // Reject unexpected mappings/resources instead of repairing them here.
        Set sc=..VerifyStorage(s) $$$ThrowOnError(sc)
        Set ^ChronosInstall(id,"phase")="APPLICATION_CLASSES"
        Set sc=..ApplicationPhase(s) $$$ThrowOnError(sc)
        Set ^ChronosInstall(id,"phase")="ROLES"
        For i=0:1:3 {
            Set role=s.roles.%Get(i)
            Set sc=##class(Security.Roles).Create(role.name,"Chronos scoped application role",role.resources,"",0) $$$ThrowOnError(sc)
        }
        Set ^ChronosInstall(id,"phase")="DISABLED_USERS"
        For i=0:1:1 {
            Set user=s.users.%Get(i),password=$System.Encryption.ToHex($System.Encryption.GenCryptRand(32,1))
            If $Length(password)'=64 Throw ##class(%Exception.General).%New("EPHEMERAL_PASSWORD_FAILED")
            // Enabled=0 at creation, password exists only in this process memory.
            Set sc=##class(Security.Users).Create(user.name,user.roles,password,"Chronos application operator",s.namespace,"","",1,0,"Chronos disabled pending private setup",1,,,.attributes,1,0)
            Set password="" $$$ThrowOnError(sc)
            Set ^ChronosInstall(id,"createdUser",user.name)=1
        }
        Set ^ChronosInstall(id,"phase")="DISABLED_APPLICATION"
        Kill p
        Set p("NameSpace")=s.namespace,p("DispatchClass")="Chronos.Web.API",p("EventClass")="Chronos.Web.Events",p("Enabled")=0
        Set p("AutheEnabled")=32,p("UseCookies")=2,p("CookiePath")=s.application,p("SessionScope")=2,p("UserCookieScope")=2,p("GroupById")=0,p("Timeout")=3600
        Set p("Resource")=s.access,p("MatchRoles")=s.prefix_"_Read:"_s.prefix_"_Python",p("CSPZENEnabled")=1,p("Description")="Chronos supervised recovery application"
        Set sc=##class(Security.Applications).Create(s.webPath,.p) $$$ThrowOnError(sc)
        Set ^ChronosInstall(id,"createdApplication")=1
        Set ^ChronosInstall(id,"phase")="FINAL_READBACK"
        Set sc=..VerifyDisabled(s) $$$ThrowOnError(sc)
        Set ^ChronosInstall(id,"state")="NATIVE_INSTALLED_DISABLED"
        Set result.workflowDelivery=..WorkflowDeliveryStatus(id)
        If 'result.workflowDelivery.verified Throw ##class(%Exception.General).%New("WORKFLOW_DELIVERY_READBACK_FAILED")
        Set result.status="NATIVE_INSTALLED_DISABLED",result.spec=s
    } Catch ex {
        Set password=""
        If begun Set ^ChronosInstall(id,"state")="PARTIAL_INSTALL_PRESERVED"
        Set result.status=$Select(begun:"PARTIAL_INSTALL_PRESERVED",1:"PREFLIGHT_REJECTED")
        // No deletion, retry, quota reset or automatic account activation.
        // No exception arguments or details: Create may contain a password.
    }
    Lock -^ChronosInstallLock
    Return result.%ToJSON()
}
}
