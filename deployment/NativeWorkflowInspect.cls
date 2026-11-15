Include %occStatus

/// Private console only; compile in %SYS after checking no foreign class exists.
/// Inspection reads selected account flags, never Security.Users.Get or secrets.
Class Chronos.Deployment.NativeWorkflowInspect Extends %RegisteredObject
{
Parameter PRODUCTION = "Chronos.App.Production";
Parameter ROLE = "Chronos.Clarifiers";
/// Verified from Include Ensemble on the exact AI Hub154 image, not guessed.
Parameter STOPPED = 2;

ClassMethod Context() As %Boolean
{
    Return ($Namespace="%SYS")&&($Username="irisowner")&&('$TLevel)&&('$Data(%request))&&('$Data(%session))&&($ZVersion["2026.3.0AI (Build 154U)")
}

ClassMethod Digest(value As %String) As %String
{
    Return $ZConvert(##class(%xsd.hexBinary).LogicalToXSD($System.Encryption.SHAHash(256,$ZConvert(value,"O","UTF8"))),"L")
}

/// Fixed scope projection. A digest binds review bytes; it is not authentication.
ClassMethod Validate(raw As %String) As %String [ Language = python ]
{
    import json,re
    try:
        if type(raw)is not str or not 0<len(raw.encode('utf-8'))<=32768:return ''
        def pairs(items):
            out={}
            for k,v in items:
                if k in out:raise ValueError('DUPLICATE')
                out[k]=v
            return out
        def bad(_):raise ValueError('NONFINITE')
        value=json.loads(raw,object_pairs_hook=pairs,parse_constant=bad)
        fields=set('schema deployment_id namespace operator reader origin application base_bundle_manifest_sha256 source_sha256 workflow_globals expected_before_items expected_after_items workflow_records required_build production security_accounts_to_create security_roles_to_create security_grants_to_add'.split())
        if type(value)is not dict or set(value)!=fields or value['schema']!='chronos.workflow-optin-apply-scope.v1':return ''
        ident=value['deployment_id']
        if type(ident)is not str or re.fullmatch(r'[a-f0-9]{32}',ident)is None:return ''
        prefix='Chronos_'+ident[:12]
        if (value['namespace'],value['operator'],value['reader'])!=('CHRONOS_'+ident[:12].upper(),prefix+'_Operator',prefix+'_Reader'):return ''
        if value['production']!='Chronos.App.Production' or value['required_build']!='2026.3.0AI.154.0' or value['application']!='/csp/chronos/':return ''
        if type(value['origin'])is not str or re.fullmatch(r'http://127\.0\.0\.1:[1-9][0-9]{0,4}',value['origin'])is None or int(value['origin'].rsplit(':',1)[1])>65535:return ''
        if type(value['base_bundle_manifest_sha256'])is not str or re.fullmatch(r'[a-f0-9]{64}',value['base_bundle_manifest_sha256'])is None:return ''
        if any(value[k]!=[] for k in ('security_accounts_to_create','security_roles_to_create','security_grants_to_add')):return ''
        def canonical(v):return json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False)
        def row(n,c,p):return dict(name=n,class_name=c,pool_size=p,enabled=True,foreground=False,settings=[dict(target='Host',name='AutoCreateRole',value='0')] if n=='Chronos.Clarifiers' else [])
        base=[row(n,n,p) for n,p in (('Chronos.App.Input',0),('Chronos.App.Process',1),('Chronos.App.Worker',1),('Chronos.Agent.Operation',1),('Chronos.Approval.Input',0),('Chronos.Approval.Operation',0))]
        extra=[row(n,c,p) for n,c,p in (('Chronos.Workflow.Input','Chronos.Workflow.Input',0),('Chronos.Workflow.Process','Chronos.Workflow.Process',1),('Chronos.Clarifiers','EnsLib.Workflow.Operation',1),('Chronos.Workflow.AccountService','Chronos.Workflow.AccountService',0),('Chronos.Workflow.AccountOperation','Chronos.Workflow.AccountOperation',1))]
        if canonical(value['expected_before_items'])!=canonical(base) or canonical(value['expected_after_items'])!=canonical(base+extra):return ''
        records=dict(role='Chronos.Clarifiers',user=prefix+'_Operator',membership_id='Chronos.Clarifiers||'+prefix+'_Operator',ranking=3,title='')
        if canonical(value['workflow_records'])!=canonical(records):return ''
        paths={'deployment/NativeInstall.cls','deployment/WorkflowAccountQuery.cls','src/Chronos/App/Production.cls'}|{'src/Chronos/Workflow/'+n+'.cls' for n in ('Request','Store','Process','Controller','AccountState','ContextGate','AccountOperation','AccountService','Decisions','Entry','Input','Policy','API')}
        pins=value['source_sha256']
        if type(pins)is not dict or set(pins)!=paths:return ''
        if any(type(v)is not str or re.fullmatch(r'[a-f0-9]{64}',v)is None for v in pins.values()):return ''
        globals_=sorted([stem+s for stem in ('EnsLib.W.RoleDefinition','EnsLib.W.UserDefinition','EnsLib.W.RoleMembership','EnsLib.W.Worklist','Ens.MessageBody','Ens.Config.Production','Ens.Config.Item') for s in ('D','I','S')]+['Ens.Conf.SettingS','ChronosRuntime','ChronosDecision16','ChronosAuthority14','ChronosWeb'])
        if value['workflow_globals']!=globals_:return ''
        return canonical(value)
    except (ValueError,TypeError,KeyError,UnicodeError,OverflowError,RecursionError):return ''
}

/// Standard library only; fixed relative source paths were checked by Validate.
/// Does not import product modules or touch the compiled application or runtime.
ClassMethod Sources(scopeJSON As %String) As %Boolean [ Language = python ]
{
    from pathlib import Path
    from hashlib import sha256
    import json,stat
    try:
        value=json.loads(scopeJSON);root=Path('/opt/chronos')
        for relative,digest in value['source_sha256'].items():
            path=root/relative
            for p in (path,*path.parents):
                if p.is_symlink():return False
            info=path.stat()
            if not stat.S_ISREG(info.st_mode) or not 0<info.st_size<=1048576:return False
            if sha256(path.read_bytes()).hexdigest()!=digest:return False
        return True
    except Exception:return False
}

ClassMethod Storage(spec As %DynamicObject, scope As %DynamicObject) As %Status
{
    Kill p Set sc=##class(Config.Namespaces).Get(spec.namespace,.p) If $$$ISERR(sc) Return sc
    If ($Get(p("Globals"))'=spec.namespace)||($Get(p("Routines"))'=spec.namespace)||($Get(p("TempGlobals"))'=(spec.namespace_"_TEMP")) Return $$$ERROR($$$GeneralError,"NAMESPACE_STORAGE_CHANGED")
    For i=0:1:2 {
        Set d=spec.databases.%Get(i)
        Kill p Set sc=##class(Config.Databases).Get(d.name,.p) If $$$ISERR(sc) Return sc
        If $Get(p("Directory"))'=d.directory Return $$$ERROR($$$GeneralError,"DATABASE_DIRECTORY_CHANGED")
        Set db=##class(SYS.Database).%OpenId(d.directory,0,.sc) If $$$ISERR(sc) Return sc
        If '$IsObject(db)||(db.ResourceName'=d.resource)||(db.GlobalJournalState'=d.journal) Return $$$ERROR($$$GeneralError,"PRIVATE_STORAGE_UNVERIFIED")
        Set db=""
    }
    Set main="^"_spec.databases.%Get(0).directory,secondary="^"_spec.databases.%Get(2).directory
    For i=0:1:(scope.%Get("workflow_globals").%Size()-1) {
        Set name=scope.%Get("workflow_globals").%Get(i),dest=##class(%SYS.Namespace).GetGlobalDest(spec.namespace,name)
        If ($Extract(name,1,7)="Chronos"),(dest'=main) Return $$$ERROR($$$GeneralError,"CHRONOS_GLOBAL_MAPPING_CHANGED")
        If (dest'=main)&&(dest'=secondary) Return $$$ERROR($$$GeneralError,"WORKFLOW_GLOBAL_NOT_PRIVATE_JOURNALED")
    }
    For name=spec.resource,spec.tempResource,spec.secondaryResource,spec.access,"Chronos_Read","Chronos_Approve" {
        Kill p Set sc=##class(Security.Resources).Get(name,.p) If $$$ISERR(sc) Return sc
        If $Get(p("PublicPermission"))'="" Return $$$ERROR($$$GeneralError,"PUBLIC_RESOURCE_PERMISSION")
    }
    Return $$$OK
}

ClassMethod AccountsAndRoute(spec As %DynamicObject) As %Status
{
    For i=0:1:1 {
        Set user=spec.users.%Get(i).name
        If '$Get(^ChronosInstall(spec.id,"createdUser",user)) Return $$$ERROR($$$GeneralError,"ACCOUNT_OWNERSHIP_UNVERIFIED")
        Set sc=##class(%ZChronos.Workflow.AccountQuery).ReadFlags(user,.flags) If $$$ISERR(sc) Return sc
        If 'flags.%Get("available")||flags.%Get("enabled") Return $$$ERROR($$$GeneralError,"DISABLED_ACCOUNTS_REQUIRED")
    }
    If '$Get(^ChronosInstall(spec.id,"createdApplication")) Return $$$ERROR($$$GeneralError,"APPLICATION_OWNERSHIP_UNVERIFIED")
    Kill p Set sc=##class(Security.Applications).Get(spec.webPath,.p) If $$$ISERR(sc) Return sc
    If $Get(p("Enabled"))||($Get(p("NameSpace"))'=spec.namespace)||($Get(p("Resource"))'=spec.access)||($Get(p("DispatchClass"))'="Chronos.Web.API") Return $$$ERROR($$$GeneralError,"DISABLED_APPLICATION_REQUIRED")
    Return $$$OK
}

/// Requires the exact clean stopped installation. No production loader is called:
/// an absent config row is rejected, never silently created by an inspection.
ClassMethod NamespaceChecks(spec As %DynamicObject, scope As %DynamicObject, after As %Boolean = 0, Output view As %DynamicObject) As %Status
{
    New $Namespace
    Set $Namespace=spec.namespace,view={}
    Set sc=##class(Ens.Director).GetProductionStatus(.name,.state,0) If $$$ISERR(sc) Return sc
    // Do not invoke this %SYS helper's own routines after the namespace switch.
    // Fixed literals below are the verified154 constants and exact scope only.
    If (state'=2)||((name'="")&&(name'="Chronos.App.Production")) Return $$$ERROR($$$GeneralError,"STOPPED_OWNED_PRODUCTION_REQUIRED")
    If '##class(%Dictionary.CompiledMethod).%ExistsId("Chronos.App.Production||OnStart")||'##class(%Dictionary.CompiledMethod).%ExistsId("Chronos.App.Production||OnStop") Return $$$ERROR($$$GeneralError,"PRODUCTION_CALLBACK_MISSING")
    If '##class(Ens.Config.Production).%ExistsId("Chronos.App.Production") Return $$$ERROR($$$GeneralError,"PRODUCTION_ROW_UNAVAILABLE")
    Set production=##class(Ens.Config.Production).%OpenId("Chronos.App.Production",0,.sc) If $$$ISERR(sc) Return sc
    If '$IsObject(production)||(production.Name'="Chronos.App.Production")||production.Settings.Count() Return $$$ERROR($$$GeneralError,"UNEXPECTED_PRODUCTION_CONFIGURATION")
    Set expected=$Select(after:scope.%Get("expected_after_items"),1:scope.%Get("expected_before_items")),actual=[]
    If production.Items.Count()'=expected.%Size() Return $$$ERROR($$$GeneralError,"PRODUCTION_ITEM_COUNT_CHANGED")
    For i=1:1:production.Items.Count() {
        Set item=production.Items.GetAt(i),want=expected.%Get(i-1),settings=[]
        If (item.Name'=want.name)||(item.ClassName'=want.%Get("class_name"))||(item.PoolSize'=want.%Get("pool_size"))||(item.Enabled'=want.enabled)||(item.Foreground'=want.foreground) Return $$$ERROR($$$GeneralError,"PRODUCTION_ITEM_CHANGED")
        If item.Settings.Count()'=want.settings.%Size() Return $$$ERROR($$$GeneralError,"PRODUCTION_ITEM_SETTINGS_CHANGED")
        For j=1:1:item.Settings.Count() {
            Set setting=item.Settings.GetAt(j),ws=want.settings.%Get(j-1)
            If (setting.Target'=ws.target)||(setting.Name'=ws.name)||(setting.Value'=ws.value) Return $$$ERROR($$$GeneralError,"PRODUCTION_SETTING_CHANGED")
            Do settings.%Push({"target":(setting.Target),"name":(setting.Name),"value":(setting.Value)})
        }
        Set row={"name":(item.Name),"class_name":(item.ClassName),"pool_size":(+item.PoolSize),"enabled":false,"foreground":false,"settings":(settings)}
        Do row.%Set("enabled",item.Enabled,"boolean"),row.%Set("foreground",item.Foreground,"boolean"),actual.%Push(row)
    }
    Set roleExists=##class(EnsLib.Workflow.RoleDefinition).%ExistsId("Chronos.Clarifiers")
    Set operatorExists=##class(EnsLib.Workflow.UserDefinition).%ExistsId(scope.operator)
    Set memberExists=##class(EnsLib.Workflow.RoleMembership).%ExistsId(scope.%Get("workflow_records").%Get("membership_id"))
    If 'after {
        If roleExists||operatorExists||memberExists Return $$$ERROR($$$GeneralError,"WORKFLOW_RECORD_COLLISION")
    } Else {
        If 'roleExists||'operatorExists||'memberExists Return $$$ERROR($$$GeneralError,"WORKFLOW_READBACK_MISSING")
        Set role=##class(EnsLib.Workflow.RoleDefinition).%OpenId("Chronos.Clarifiers",0,.sc) If $$$ISERR(sc) Return sc
        Set user=##class(EnsLib.Workflow.UserDefinition).%OpenId(scope.operator,0,.sc) If $$$ISERR(sc) Return sc
        Set member=##class(EnsLib.Workflow.RoleMembership).%OpenId(scope.%Get("workflow_records").%Get("membership_id"),0,.sc) If $$$ISERR(sc) Return sc
        If '$IsObject(role)||'$IsObject(user)||'$IsObject(member) Return $$$ERROR($$$GeneralError,"WORKFLOW_READBACK_UNAVAILABLE")
        If (role.Name'="Chronos.Clarifiers")||(user.Name'=scope.operator)||'user.IsActive Return $$$ERROR($$$GeneralError,"WORKFLOW_IDENTITY_READBACK_FAILED")
        If (member.RoleGetObjectId()'="Chronos.Clarifiers")||(member.UserGetObjectId()'=scope.operator)||(member.Ranking'=3)||(member.Title'="") Return $$$ERROR($$$GeneralError,"MEMBERSHIP_READBACK_FAILED")
    }
    If ##class(EnsLib.Workflow.RoleMembership).%ExistsId("Chronos.Clarifiers||"_scope.reader) Return $$$ERROR($$$GeneralError,"READER_MUST_NOT_BE_CLARIFIER")
    Set config=##class(%DynamicObject).%FromJSON($Get(^ChronosRuntime("config"),"{}"))
    Set runtime=##class(%DynamicObject).%FromJSON($Get(^ChronosRuntime("state"),"{}"))
    If (config.%Get("production")'="Chronos.App.Production")||(config.%Get("dataRoot")'=spec.destinations)||(config.%Get("pythonRoot")'="/opt/chronos/src") Return $$$ERROR($$$GeneralError,"RUNTIME_CONFIGURATION_CHANGED")
    If runtime.%Get("state")'="CONFIGURED" Return $$$ERROR($$$GeneralError,"UNSTARTED_FRESH_RUNTIME_REQUIRED")
    Set view={"productionStopped":true,"productionItems":(actual),"businessRecordsPresent":false,"callbacksExist":true,"callbackSourceEquivalenceVerified":false,"workerAuthorityVerified":false,"tasksTested":false}
    Do view.%Set("businessRecordsPresent",after,"boolean")
    Return $$$OK
}

ClassMethod Check(scope As %DynamicObject, after As %Boolean = 0, Output result As %DynamicObject) As %Status
{
    Set result={"status":"OPTIN_PREFLIGHT_REJECTED","applied":false,"ready":false,"workerAuthorityVerified":false,"phase":"CONTEXT"}
    If '..Context() Return $$$ERROR($$$GeneralError,"PRIVATE_CONSOLE_CONTEXT_REQUIRED")
    Set result.phase="BASE_OWNERSHIP"
    Set spec=##class(Chronos.Deployment.NativeInstall).Spec(scope.%Get("deployment_id"),scope.origin,scope.application)
    If (spec.namespace'=scope.namespace)||(spec.users.%Get(1).name'=scope.operator)||(spec.users.%Get(0).name'=scope.reader) Return $$$ERROR($$$GeneralError,"DERIVED_SCOPE_CHANGED")
    If ($Get(^ChronosInstall(spec.id,"state"))'="NATIVE_INSTALLED_DISABLED")||($Get(^ChronosInstall(spec.id,"bundle"))'=scope.%Get("base_bundle_manifest_sha256"))||($Get(^ChronosInstall(spec.id,"spec"))'=spec.%ToJSON()) Return $$$ERROR($$$GeneralError,"BASE_INSTALLATION_OWNERSHIP_CHANGED")
    Set result.phase="SOURCE_PINS"
    If '..Sources(scope.%ToJSON()) Return $$$ERROR($$$GeneralError,"SOURCE_BYTES_CHANGED")
    Set result.phase="STORAGE"
    Set sc=..Storage(spec,scope) If $$$ISERR(sc) Return sc
    Set result.phase="DISABLED_ACCOUNTS_AND_ROUTE"
    Set sc=..AccountsAndRoute(spec) If $$$ISERR(sc) Return sc
    Set result.phase="OPTIN_OWNERSHIP"
    If 'after,$Data(^ChronosInstall(spec.id,"workflowOptIn")) Return $$$ERROR($$$GeneralError,"OPTIN_INTENT_EXISTS_NO_RETRY")
    If after {
        Set marker=$Get(^ChronosInstall(spec.id,"workflowOptIn","state"))
        If ((marker'="VERIFYING_DISABLED")&&(marker'="APPLIED_DISABLED"))||($Get(^ChronosInstall(spec.id,"workflowOptIn","scope"))'=..Digest(scope.%ToJSON())) Return $$$ERROR($$$GeneralError,"OPTIN_READBACK_OWNERSHIP_CHANGED")
    }
    Set result.phase="NAMESPACE_CONFIGURATION"
    Set sc=..NamespaceChecks(spec,scope,after,.view) If $$$ISERR(sc) Return sc
    Set result={"status":($Select(after:"OPTIN_APPLIED_DISABLED_READBACK",1:"OPTIN_PREFLIGHT_CLEAR")),"applied":false,"ready":false,"scopeSha256":(..Digest(scope.%ToJSON())),"sourceHashesMatched":true,"privateJournaledStorageVerified":true,"accountsAndRouteDisabled":true,"nativeView":(view),"workerAuthorityVerified":false,"tasksTested":false,"modelCalls":0}
    Do result.%Set("applied",after,"boolean")
    Return $$$OK
}

ClassMethod Inspect(scopeJSON As %String, after As %Boolean = 0) As %String
{
    Set result={"status":"OPTIN_PREFLIGHT_REJECTED","applied":false,"ready":false,"workerAuthorityVerified":false}
    If '..Context() Return result.%ToJSON()
    Try {
        Set normalized=..Validate(scopeJSON)
        If normalized="" Return result.%ToJSON()
        Set scope=##class(%DynamicObject).%FromJSON(normalized)
        Set sc=..Check(scope,after,.result)
        If $$$ISERR(sc) {
            Set result.status="OPTIN_PREFLIGHT_REJECTED",result.errorCodes=$System.Status.GetErrorCodes(sc)
            // Numeric status codes/phase only; never arbitrary exception text.
        }
    } Catch ex { Set result={"status":"OPTIN_PREFLIGHT_REJECTED","applied":false,"ready":false,"workerAuthorityVerified":false,"phase":"INSPECTION_UNAVAILABLE"} }
    Return result.%ToJSON()
}
}
