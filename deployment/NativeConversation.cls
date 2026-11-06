Include %occStatus

/// Trusted C1/C2 configuration console only. No HTTP, accounts, production start or inference.
Class Chronos.Deployment.NativeConversation Extends %RegisteredObject
{
ClassMethod ProviderProfile(id As %String) As %String [ Private, Language = python ]
{
    import hashlib,importlib.util,json
    from pathlib import Path
    path=Path('/opt/chronos/deployment/conversation_provider.py')
    if path.resolve()!=path:raise ValueError('LINKED_PROVIDER_HELPER')
    name='chronos_native_conversation_'+hashlib.sha256(path.read_bytes()).hexdigest()
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return json.dumps(module.status(id),sort_keys=True,allow_nan=False)
}

ClassMethod Run(action As %String, id As %String, origin As %String, application As %String, digest As %String, profileHash As %String, requestedContract As %String = "chronos.case-conversation.v1") As %String
{
    New $Namespace
    Set locked=0
    Set r={"schema_version":"chronos.native-conversation.v1","status":"REJECTED","ready":false,"deployment_id":(id),"bundle_sha256":(digest),"profile_sha256":(profileHash),"model_configured":null,"native_state":"UNKNOWN","production_state":null,"e1_config_unchanged":null,"model_tested":false}
    If ($Namespace'="%SYS")||$TLevel||$Data(%request)||$Data(%session)||($Username'="irisowner") Return r.%ToJSON()
    If $ZVersion'["2026.3.0AI (Build 154U)" Return r.%ToJSON()
    If '$ListFind($ListBuild("configure","status"),action) Return r.%ToJSON()
    If '$ListFind($ListBuild("chronos.case-conversation.v1","chronos.case-explanation-plan.v1","chronos.case-explanation-plan.v2"),requestedContract) Return r.%ToJSON()
    For value=digest,profileHash { If ($Length(value)'=64)||($Translate(value,"0123456789abcdef")'="") Return r.%ToJSON() }
    Try {
        Set s=##class(Chronos.Deployment.NativeInstall).Spec(id,origin,application)
        If ($Get(^ChronosInstall(id,"state"))'="NATIVE_INSTALLED_DISABLED")||($Get(^ChronosInstall(id,"bundle"))'=digest)||($Get(^ChronosInstall(id,"spec"))'=s.%ToJSON()) Throw ##class(%Exception.General).%New("INSTALLATION_NOT_BOUND")
        Set destination="^"_s.root_"/db/"
        For global="ChronosJury","ChronosRuntime","ChronosWeb","ChronosAI18","ChronosConversation" {
            If ##class(%SYS.Namespace).GetGlobalDest(s.namespace,global)'=destination Throw ##class(%Exception.General).%New("DATABASE_MAPPING_CHANGED")
        }
        For pair="ChronosJury:conversationProvider","ChronosJury:providerLock","ChronosRuntime:bootLock","ChronosRuntime:config","ChronosWeb:config","ChronosAI18:config","ChronosConversation:model" {
            If ##class(%SYS.Namespace).GetGlobalDest(s.namespace,$Piece(pair,":",1),$Char(34)_$Piece(pair,":",2)_$Char(34))'=destination Throw ##class(%Exception.General).%New("SUBSCRIPT_MAPPING_CHANGED")
        }
        Set database=##class(SYS.Database).%OpenId(s.root_"/db/")
        If '$IsObject(database)||(database.ResourceName'=s.resource)||(database.GlobalJournalState'=3) Throw ##class(%Exception.General).%New("OWNED_JOURNALED_DATABASE_REQUIRED")
        Kill resource Set sc=##class(Security.Resources).Get(s.resource,.resource) $$$ThrowOnError(sc)
        If $Get(resource("PublicPermission"))'="" Throw ##class(%Exception.General).%New("PUBLIC_STORAGE_REJECTED")
        Set observed=##class(%DynamicObject).%FromJSON(..ProviderProfile(id)),profile=observed.profile
        Set responseContract=profile.%Get("response_contract")
        If responseContract'=requestedContract Throw ##class(%Exception.General).%New("CONVERSATION_CONTRACT_CHANGED")
        Set validPair=((profile.version=4)&&(responseContract="chronos.case-conversation.v1"))||((profile.version=5)&&(responseContract="chronos.case-explanation-plan.v1"))||((profile.version=6)&&(responseContract="chronos.case-explanation-plan.v2"))
        If (observed.%Get("profile_sha256")'=profileHash)||('validPair)||(profile.provider'="ollama")||(profile.%Get("deployment_id")'=id)||(profile.%Get("local_port")'=11434) Throw ##class(%Exception.General).%New("CONVERSATION_PROFILE_REQUIRED")
        Set authorization=action_":"_id_":"_digest_":"_profileHash
        If responseContract'="chronos.case-conversation.v1" Set authorization=authorization_":"_responseContract
        If action="configure",$System.Util.GetEnviron("CHRONOS_CONVERSATION_AUTHORIZED")'=authorization Throw ##class(%Exception.General).%New("EXPLICIT_ACTION_AUTHORIZATION_REQUIRED")
        Kill webProperties Set sc=##class(Security.Applications).Get(s.webPath,.webProperties) $$$ThrowOnError(sc)
        If (webProperties("NameSpace")'=s.namespace)||(webProperties("Resource")'=s.access)||(webProperties("DispatchClass")'="Chronos.Web.API") Throw ##class(%Exception.General).%New("WEB_OWNERSHIP_CHANGED")
        If action="configure",$Get(webProperties("Enabled"),1) Throw ##class(%Exception.General).%New("CONFIGURE_REQUIRES_DISABLED_WEB")
        Set $Namespace=s.namespace
        // Share the E1 installer/start fence without editing its record or quota.
        Lock +^ChronosJury("providerLock"):0
        If '$Test Set r.status="BUSY" Throw ##class(%Exception.General).%New("PROVIDER_BUSY")
        Set locked=1
        Set runtime=##class(%DynamicObject).%FromJSON($Get(^ChronosRuntime("config")))
        If (runtime.production'="Chronos.App.Production")||(runtime.dataRoot'=s.destinations)||(runtime.pythonRoot'="/opt/chronos/src") Throw ##class(%Exception.General).%New("RUNTIME_BINDING_CHANGED")
        Set web=##class(%DynamicObject).%FromJSON($Get(^ChronosWeb("config")))
        If (web.origin'=origin)||(web.application'=application)||($Length(web.installationId)'=64) Throw ##class(%Exception.General).%New("WEB_BINDING_CHANGED")
        Set e1Before=$Get(^ChronosAI18("config"))
        Set expected=##class(Chronos.Conversation.Model).Spec("http://127.0.0.1:11514/v1/",profile.model,profileHash,profile.%Get("reasoning_effort"),##class(Chronos.Conversation.Model).ContractSchema(responseContract).%ToJSON())
        Set checked=##class(%DynamicObject).%FromJSON(expected)
        If checked.schemaSha256'=profile.%Get("schema_sha256") Throw ##class(%Exception.General).%New("C1_SCHEMA_CHANGED")
        Set sc=##class(Ens.Director).GetProductionStatus(.name,.state,0) $$$ThrowOnError(sc)
        If '$ListFind($ListBuild(1,2,3,4),state) Throw ##class(%Exception.General).%New("UNKNOWN_PRODUCTION_STATE")
        Do r.%Set("production_state",state,"number")
        If action="configure",state'=2 Throw ##class(%Exception.General).%New("CONFIGURE_WHILE_STOPPED")
        Set raw=$Get(^ChronosJury("conversationProvider")),item="",actual=$Get(^ChronosConversation("model"))
        If raw'="" {
            Set item=##class(%DynamicObject).%FromJSON(raw)
            If (item.deploymentId'=id)||(item.bundle'=digest)||(item.profileSha256'=profileHash)||(item.installationId'=web.installationId)||(item.expectedConfig'=expected) Throw ##class(%Exception.General).%New("C1_BINDING_CHANGED")
            If '$ListFind($ListBuild("CONFIGURE_REQUESTED","CONFIGURED"),item.state) Throw ##class(%Exception.General).%New("C1_STATE_INVALID")
        } ElseIf actual'="" { Throw ##class(%Exception.General).%New("UNBOUND_C1_CONFIG_EXISTS") }
        If (action="configure")&&(raw="") {
            Set item={"deploymentId":(id),"bundle":(digest),"profileSha256":(profileHash),"installationId":(web.installationId),"expectedConfig":(expected),"state":"CONFIGURE_REQUESTED"}
            Set sc=##class(Chronos.Runtime.Durability).Check() $$$ThrowOnError(sc)
            Set ^ChronosJury("conversationProvider")=item.%ToJSON()
            Set sc=##class(Chronos.Runtime.Durability).Flush() $$$ThrowOnError(sc)
            Set sc=##class(Chronos.Conversation.Model).Configure("http://127.0.0.1:11514/v1/",profile.model,profileHash,profile.%Get("reasoning_effort"),responseContract) $$$ThrowOnError(sc)
        }
        Set actual=$Get(^ChronosConversation("model"))
        If $IsObject(item) {
            // Resolve only from current configuration; never repeat Configure for
            // an existing fence, even if it was interrupted before the first write.
            Set sc=##class(Chronos.Runtime.Durability).Flush() $$$ThrowOnError(sc)
            Do r.%Set("native_state",item.state)
            Set r.status="CONFIGURATION_UNCERTAIN"
            Do r.%Set("model_configured",0,"boolean")
            If actual=expected {
                Set sc=##class(Chronos.Conversation.Model).Current(.current) $$$ThrowOnError(sc)
                If current.%ToJSON()'=expected Throw ##class(%Exception.General).%New("C1_READBACK_MISMATCH")
                If (action="configure")&&(item.state="CONFIGURE_REQUESTED") {
                    Set item.state="CONFIGURED",^ChronosJury("conversationProvider")=item.%ToJSON()
                    Set sc=##class(Chronos.Runtime.Durability).Flush() $$$ThrowOnError(sc)
                }
                Do r.%Set("native_state",item.state)
                Do r.%Set("model_configured",1,"boolean")
                Set r.status="CONFIGURED"
            } ElseIf actual'="" { Throw ##class(%Exception.General).%New("C1_CONFIGURATION_CHANGED") }
        } Else {
            Set r.status="MODEL_NOT_CONFIGURED"
            Do r.%Set("native_state","ABSENT")
            Do r.%Set("model_configured",0,"boolean")
        }
        If $Get(^ChronosAI18("config"))'=e1Before Throw ##class(%Exception.General).%New("E1_CONFIGURATION_CHANGED")
        Do r.%Set("e1_config_unchanged",1,"boolean")
    } Catch ex {
        If r.status'="BUSY" Set r.status="REJECTED_STATE_PRESERVED"
        Do r.%Set("model_configured","","null")
        Do r.%Set("e1_config_unchanged","","null")
    }
    If locked Lock -^ChronosJury("providerLock")
    Return r.%ToJSON()
}
}
