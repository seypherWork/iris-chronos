Include %occStatus

/// Trusted first-install console only, compiled in %SYS; no HTTP endpoint.
/// Configure immutable E1 model, request initial production start once, or read.
Class Chronos.Deployment.NativeProvider Extends %RegisteredObject
{
ClassMethod ProviderProfile(id As %String) As %String [ Private, Language = python ]
{
    import hashlib, importlib.util, json
    from pathlib import Path
    path=Path("/opt/chronos/deployment/provider_state.py")
    if path.resolve()!=path:raise ValueError("LINKED_PROVIDER_HELPER")
    name="chronos_native_provider_"+hashlib.sha256(path.read_bytes()).hexdigest()
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return json.dumps(module.status(id),sort_keys=True,allow_nan=False)
}

ClassMethod Run(action As %String, id As %String, origin As %String, application As %String, digest As %String, profileHash As %String, expectedBinding As %String = "", Output readbackBusy As %Boolean = 0) As %String
{
    New $Namespace
    Set locked=0,item="",readbackBusy=0
    Set r={"schema_version":"chronos.native-provider.v2","status":"REJECTED","ready":false,"deployment_id":(id),"profile_sha256":(profileHash),"model_configured":null,"native_state":"UNKNOWN","production_state":null,"runtime_ready":null,"start_requested":null,"model_tested":false,"binding_sha256":null}
    If ($Namespace'="%SYS")||$TLevel||$Data(%request)||$Data(%session)||($Username'="irisowner") Return r.%ToJSON()
    If $ZVersion'["2026.3.0AI (Build 154U)" Return r.%ToJSON()
    If '$ListFind($ListBuild("configure","start","status"),action) Return r.%ToJSON()
    For value=digest,profileHash { If ($Length(value)'=64)||($Translate(value,"0123456789abcdef")'="") Return r.%ToJSON() }
    If (expectedBinding'="")&&(($Length(expectedBinding)'=64)||($Translate(expectedBinding,"0123456789abcdef")'="")) Return r.%ToJSON()
    If (action'="status")&&(expectedBinding="") Return r.%ToJSON()
    Try {
        Set s=##class(Chronos.Deployment.NativeInstall).Spec(id,origin,application)
        If ($Get(^ChronosInstall(id,"state"))'="NATIVE_INSTALLED_DISABLED")||($Get(^ChronosInstall(id,"bundle"))'=digest) Throw ##class(%Exception.General).%New("INSTALLATION_NOT_BOUND")
        If $Get(^ChronosInstall(id,"spec"))'=s.%ToJSON() Throw ##class(%Exception.General).%New("INSTALLATION_SPEC_CHANGED")
        For global="ChronosJury","ChronosRuntime","ChronosAuthority14","ChronosDecision16","ChronosWeb","ChronosAI18" {
            If ##class(%SYS.Namespace).GetGlobalDest(s.namespace,global)'=("^"_s.root_"/db/") Throw ##class(%Exception.General).%New("DATABASE_MAPPING_CHANGED")
        }
        Set database=##class(SYS.Database).%OpenId(s.root_"/db/")
        If '$IsObject(database)||(database.ResourceName'=s.resource)||(database.GlobalJournalState'=3) Throw ##class(%Exception.General).%New("OWNED_JOURNALED_DATABASE_REQUIRED")
        // Reload actual installed provider/allowance; never infer a fallback.
        Set observed=##class(%DynamicObject).%FromJSON(..ProviderProfile(id))
        If observed.%Get("profile_sha256")'=profileHash Throw ##class(%Exception.General).%New("PROVIDER_PROFILE_CHANGED")
        Set profile=observed.profile
        If (profile.version'=3)||(profile.%Get("deployment_id")'=id)||(profile.%Get("response_contract")'="chronos.preference-extraction.v1") Throw ##class(%Exception.General).%New("E1_PROFILE_REQUIRED")
        If profile.provider="ollama" {
            If profile.%Get("local_port")'=11434 Throw ##class(%Exception.General).%New("LOCAL_PORT_CHANGED")
        } ElseIf profile.provider="openai-chat-json" {
            If (profile.%GetTypeOf("local_port")'="null")||(profile.%Get("reasoning_effort")'="none") Throw ##class(%Exception.General).%New("CLOUD_PROFILE_CHANGED")
        } Else { Throw ##class(%Exception.General).%New("UNSUPPORTED_PROVIDER") }
        If observed.%Get("provider_kind")'=profile.provider Throw ##class(%Exception.General).%New("PROVIDER_KIND_CHANGED")
        Set binding=observed.%Get("binding_sha256")
        If ($Length(binding)'=64)||($Translate(binding,"0123456789abcdef")'="") Throw ##class(%Exception.General).%New("PROVIDER_BINDING_REQUIRED")
        If (expectedBinding'="")&&(binding'=expectedBinding) Throw ##class(%Exception.General).%New("EXPECTED_PROVIDER_BINDING_CHANGED")
        Do r.%Set("binding_sha256",binding)
        Set expected={"baseURL":"http://127.0.0.1:11512/v1/","model":(profile.model),"contract":"chronos.preference-extraction.v1"}
        Set effort=profile.%Get("reasoning_effort")
        If effort'="none" Set expected.reasoningEffort=effort
        Set expected.profileSha256=profileHash
        If action'="status" {
            If $System.Util.GetEnviron("CHRONOS_PROVIDER_AUTHORIZED")'=(action_":"_id_":"_digest_":"_profileHash_":"_expectedBinding) Throw ##class(%Exception.General).%New("EXPLICIT_ACTION_AUTHORIZATION_REQUIRED")
            Kill webProperties Set sc=##class(Security.Applications).Get(s.webPath,.webProperties) $$$ThrowOnError(sc)
            If $Get(webProperties("Enabled"),1) Throw ##class(%Exception.General).%New("INITIAL_INSTALL_REQUIRES_DISABLED_WEB")
        }
        Set $Namespace=s.namespace
        Set runtime=##class(%DynamicObject).%FromJSON($Get(^ChronosRuntime("config")))
        If (runtime.production'="Chronos.App.Production")||(runtime.dataRoot'=s.destinations)||(runtime.pythonRoot'="/opt/chronos/src") Throw ##class(%Exception.General).%New("RUNTIME_BINDING_CHANGED")
        Set web=##class(%DynamicObject).%FromJSON($Get(^ChronosWeb("config")))
        If (web.origin'=origin)||(web.application'=application)||($Length(web.installationId)'=64) Throw ##class(%Exception.General).%New("WEB_BINDING_CHANGED")
        // Status participates in the same fence as configure/start/resume.
        Lock +^ChronosJury("providerLock"):0
        If '$Test Set r.status="BUSY" Throw ##class(%Exception.General).%New("PROVIDER_BUSY")
        Set locked=1
        Set raw=$Get(^ChronosJury("provider"))
        If raw'="" {
            Set item=##class(%DynamicObject).%FromJSON(raw)
            If (item.deploymentId'=id)||(item.bundle'=digest)||(item.profileSha256'=profileHash)||(item.bindingSha256'=binding)||(item.installationId'=web.installationId) Throw ##class(%Exception.General).%New("PROVIDER_BINDING_CHANGED")
            If '$ListFind($ListBuild("CONFIGURE_REQUESTED","CONFIGURED","START_REQUESTED"),item.state) Throw ##class(%Exception.General).%New("PROVIDER_STATE_INVALID")
        }
        If (action="configure")&&(raw="") {
            If $Data(^ChronosAI18("config")) Throw ##class(%Exception.General).%New("UNBOUND_MODEL_CONFIG_EXISTS")
            Set sc=##class(Ens.Director).GetProductionStatus(.name,.state,0) $$$ThrowOnError(sc)
            If state'=2 Throw ##class(%Exception.General).%New("PRODUCTION_NOT_STOPPED")
            Set item={"deploymentId":(id),"bundle":(digest),"profileSha256":(profileHash),"bindingSha256":(binding),"installationId":(web.installationId),"state":"CONFIGURE_REQUESTED"}
            Set sc=##class(Chronos.Runtime.Durability).Check() $$$ThrowOnError(sc)
            Set ^ChronosJury("provider")=item.%ToJSON()
            Set sc=##class(Chronos.Runtime.Durability).Flush() $$$ThrowOnError(sc)
            Set sc=##class(Chronos.Agent.Model).Configure(expected.baseURL,expected.model,profileHash,effort,expected.contract) $$$ThrowOnError(sc)
            If $Get(^ChronosAI18("config"))'=expected.%ToJSON() Throw ##class(%Exception.General).%New("MODEL_READBACK_MISMATCH")
            Set item.state="CONFIGURED",^ChronosJury("provider")=item.%ToJSON()
            Set sc=##class(Chronos.Runtime.Durability).Flush() $$$ThrowOnError(sc)
        } ElseIf (action="configure")&&$IsObject(item) {
            // If only the confirmation was lost, finish from current readback;
            // never repeat Model.Configure for an existing request fence.
            If (item.state="CONFIGURE_REQUESTED")&&($Get(^ChronosAI18("config"))=expected.%ToJSON()) {
                Set item.state="CONFIGURED",^ChronosJury("provider")=item.%ToJSON()
                Set sc=##class(Chronos.Runtime.Durability).Flush() $$$ThrowOnError(sc)
            }
        }
        If action="start" {
            If '$IsObject(item) Throw ##class(%Exception.General).%New("CONFIGURATION_REQUIRED")
            If item.state="CONFIGURED" {
                If $Get(^ChronosAI18("config"))'=expected.%ToJSON() Throw ##class(%Exception.General).%New("MODEL_CONFIG_CHANGED")
                Set sc=##class(Ens.Director).GetProductionStatus(.name,.state,0) $$$ThrowOnError(sc)
                Set boot=##class(%DynamicObject).%FromJSON($Get(^ChronosRuntime("state")))
                If (state'=2)||(boot.state'="CONFIGURED")||$Data(^ChronosJury("case"))||$Data(^ChronosDecision16("decision")) Throw ##class(%Exception.General).%New("INITIAL_START_ONLY")
                // Durable fence BEFORE the call. A repeated start only observes.
                Set sc=##class(Chronos.Runtime.Durability).Check() $$$ThrowOnError(sc)
                Set item.state="START_REQUESTED",^ChronosJury("provider")=item.%ToJSON()
                Set sc=##class(Chronos.Runtime.Durability).Flush() $$$ThrowOnError(sc)
                Do r.%Set("start_requested",1,"boolean")
                // Do not hold bootLock: OnStart must acquire it for recovery.
                Set sc=##class(Ens.Director).StartProduction("Chronos.App.Production") $$$ThrowOnError(sc)
            } ElseIf item.state'="START_REQUESTED" {
                Throw ##class(%Exception.General).%New("CONFIGURATION_UNCERTAIN")
            }
        }
        // Read config first, then reread the fence so concurrent readers cannot
        // attribute a new config/start to an earlier absent installation record.
        Set actual=$Get(^ChronosAI18("config")),raw=$Get(^ChronosJury("provider"))
        Do r.%Set("model_configured",0,"boolean")
        Do r.%Set("start_requested",0,"boolean")
        Do r.%Set("native_state","ABSENT")
        Set r.status="MODEL_NOT_CONFIGURED"
        If raw'="" {
            Set item=##class(%DynamicObject).%FromJSON(raw)
            If (item.deploymentId'=id)||(item.bundle'=digest)||(item.profileSha256'=profileHash)||(item.bindingSha256'=binding)||(item.installationId'=web.installationId) Throw ##class(%Exception.General).%New("PROVIDER_READBACK_BINDING_CHANGED")
            If '$ListFind($ListBuild("CONFIGURE_REQUESTED","CONFIGURED","START_REQUESTED"),item.state) Throw ##class(%Exception.General).%New("PROVIDER_READBACK_STATE_INVALID")
            // Confirm persistence even if an earlier call ended at a failed sync.
            Set sc=##class(Chronos.Runtime.Durability).Flush() $$$ThrowOnError(sc)
            Do r.%Set("native_state",item.state)
            Do r.%Set("start_requested",(item.state="START_REQUESTED"),"boolean")
            Set r.status="CONFIGURATION_UNCERTAIN"
            If actual=expected.%ToJSON() {
                Do r.%Set("model_configured",1,"boolean")
                Set r.status="CONFIGURED"
                If item.state="START_REQUESTED" Set r.status="START_REQUEST_UNCERTAIN"
            } ElseIf actual'="" { Throw ##class(%Exception.General).%New("MODEL_READBACK_CHANGED") }
        } ElseIf actual'="" { Throw ##class(%Exception.General).%New("UNBOUND_MODEL_CONFIG_EXISTS") }
        Set sc=##class(Ens.Director).GetProductionStatus(.name,.state,0)
        // Internal signal only after all configuration and binding checks above.
        Set readbackBusy=##class(Chronos.Runtime.Bootstrap).ProductionBusy(sc)
        $$$ThrowOnError(sc)
        If '$ListFind($ListBuild(1,2,3,4),state) Throw ##class(%Exception.General).%New("UNKNOWN_PRODUCTION_STATE")
        Do r.%Set("production_state",state,"number")
        Set sc=##class(Chronos.Runtime.Bootstrap).Ready(.ready)
        Set readbackBusy=##class(Chronos.Runtime.Bootstrap).ProductionBusy(sc)
        $$$ThrowOnError(sc)
        Do r.%Set("runtime_ready",ready.ready,"boolean")
        If ready.ready&&(name="Chronos.App.Production")&&(state=1)&&r.%Get("model_configured")&&r.%Get("start_requested") Set r.status="RUNNING_NATIVE_ONLY"
    } Catch ex {
        If r.status'="BUSY" Set r.status="REJECTED_STATE_PRESERVED"
        Do r.%Set("runtime_ready","","null")
    }
    If locked Lock -^ChronosJury("providerLock")
    Return r.%ToJSON()
}
}
