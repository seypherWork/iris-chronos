Include %occStatus

/// Operational console resume, separate from initial installation/start.
/// Explicit recover may clean a troubled production and start it once; no model,
/// access changes, CleanProduction, fake OnStop or history resets.
Class Chronos.Deployment.NativeResume Extends %RegisteredObject
{
ClassMethod Identifier(value As %String) As %Boolean [ Private ]
{
    Return ($Length(value)>0)&&($Length(value)<=128)&&($Translate(value,"abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-")="")
}

ClassMethod Provider(id As %String, origin As %String, application As %String, digest As %String, profile As %String, binding As %String, allowBusy As %Boolean = 0) As %DynamicObject [ Private ]
{
    New $Namespace
    Set $Namespace="%SYS"
    Set value=##class(%DynamicObject).%FromJSON(##class(Chronos.Deployment.NativeProvider).Run("status",id,origin,application,digest,profile,binding,.readbackBusy))
    If (value.%Get("binding_sha256")'=binding)||'value.%Get("model_configured")||'value.%Get("start_requested")||(value.%Get("native_state")'="START_REQUESTED") Throw ##class(%Exception.General).%New("INITIAL_PROVIDER_NOT_VERIFIED")
    If allowBusy&&readbackBusy&&(value.status="REJECTED_STATE_PRESERVED") Return 0
    If '$ListFind($ListBuild("START_REQUEST_UNCERTAIN","RUNNING_NATIVE_ONLY"),value.status) Throw ##class(%Exception.General).%New("PROVIDER_NOT_VERIFIED")
    Return value
}

/// Embedded Python resolves the class in the current namespace. Console
/// helpers exist only in %SYS; restore the caller namespace before returning.
ClassMethod MonotonicMS() As %BigInt [ Private ]
{
    New $Namespace
    Set $Namespace="%SYS"
    Return ..SystemMonotonicMS()
}

ClassMethod SystemMonotonicMS() As %BigInt [ Language = python, Private ]
{
    import time
    return time.monotonic_ns() // 1000000
}

ClassMethod ClearObservation(r As %DynamicObject) [ Private ]
{
    Do r.%Set("runtime_ready","","null"),r.%Set("production_state","","null")
    Do r.%Set("runtime_state","UNKNOWN"),r.%Set("current_generation",""),r.%Set("generation_request_id","")
}

ClassMethod Observe(r As %DynamicObject, s As %DynamicObject, allowBusy As %Boolean = 0) As %Boolean [ Private ]
{
    New $Namespace
    // A busy observation must never leave readiness from a previous iteration.
    Do ..ClearObservation(r)
    Set $Namespace="%SYS"
    Kill p Set sc=##class(Security.Applications).Get(s.webPath,.p) $$$ThrowOnError(sc)
    If (p("NameSpace")'=s.namespace)||(p("Resource")'=s.access)||(p("DispatchClass")'="Chronos.Web.API") Throw ##class(%Exception.General).%New("WEB_OWNERSHIP_CHANGED")
    If (p("Enabled")'=0)&&(p("Enabled")'=1) Throw ##class(%Exception.General).%New("INVALID_WEB_STATE")
    Do r.%Set("web_enabled",p("Enabled"),"boolean")
    Set $Namespace=s.namespace
    Lock +^ChronosRuntime("bootLock"):0
    If '$Test {
        If allowBusy Return 0
        Throw ##class(%Exception.General).%New("BOOTSTRAP_BUSY")
    }
    Try {
    Set boot=##class(%DynamicObject).%FromJSON($Get(^ChronosRuntime("state")))
    If (boot.production'="Chronos.App.Production")||'..Identifier(boot.generation) Throw ##class(%Exception.General).%New("RUNTIME_BINDING_CHANGED")
    If '$ListFind($ListBuild("STOPPED","RECOVERED","RECOVERING","FAILED"),boot.state) Throw ##class(%Exception.General).%New("RUNTIME_STATE_UNSUPPORTED")
    If allowBusy&&(boot.state="FAILED") Throw ##class(%Exception.General).%New("RESUME_RUNTIME_FAILED")
    Set sc=##class(Ens.Director).GetProductionStatus(.name,.state,0)
    If allowBusy&&##class(Chronos.Runtime.Bootstrap).ProductionBusy(sc) {
        Lock -^ChronosRuntime("bootLock")
        Return 0
    }
    $$$ThrowOnError(sc)
    If '$ListFind($ListBuild(1,2,3,4),state) Throw ##class(%Exception.General).%New("PRODUCTION_STATE_UNSUPPORTED")
    If ((state=1)||(state=3)||(state=4))&&(name'="Chronos.App.Production") Throw ##class(%Exception.General).%New("OTHER_PRODUCTION_RUNNING")
    Set sc=##class(Chronos.Runtime.Bootstrap).Ready(.ready,boot.generation)
    If allowBusy&&##class(Chronos.Runtime.Bootstrap).ProductionBusy(sc) {
        Lock -^ChronosRuntime("bootLock")
        Return 0
    }
    $$$ThrowOnError(sc)
    If ready.ready,ready.generation'=boot.generation Throw ##class(%Exception.General).%New("READINESS_GENERATION_CHANGED")
    Do r.%Set("current_generation",boot.generation),r.%Set("runtime_state",boot.state)
    Do r.%Set("production_state",state,"number"),r.%Set("runtime_ready",ready.ready,"boolean")
    Do r.%Set("generation_request_id",$Get(^ChronosJury("resumeGeneration",boot.generation)))
    If (r.%Get("generation_request_id")'="")&&'..Identifier(r.%Get("generation_request_id")) Throw ##class(%Exception.General).%New("GENERATION_FENCE_INVALID")
    } Catch ex {
        Lock -^ChronosRuntime("bootLock")
        Throw ex
    }
    Lock -^ChronosRuntime("bootLock")
    Return 1
}

/// Observe bounded post-start settling; never call StartProduction again.
ClassMethod WaitObserved(r As %DynamicObject, s As %DynamicObject, oldGeneration As %String, oldWeb As %Boolean, oldFence As %String, oldModel As %String, deadline As %BigInt = 0) As %Boolean [ Private ]
{
    Set now=..MonotonicMS()
    If deadline=0 Set deadline=now+30000
    If (deadline>(now+30000))||(deadline<0) Throw ##class(%Exception.General).%New("INVALID_READBACK_DEADLINE")
    For attempt=1:1:301 {
        If ..MonotonicMS()>=deadline Do ..ClearObservation(r) Return 0
        If (^ChronosJury("provider")'=oldFence)||(^ChronosAI18("config")'=oldModel) Throw ##class(%Exception.General).%New("RESUME_CONFIG_CHANGED")
        Set observed=..Observe(r,s,1)
        If r.%Get("web_enabled")'=oldWeb Throw ##class(%Exception.General).%New("RESUME_WEB_CHANGED")
        If ..MonotonicMS()>=deadline Do ..ClearObservation(r) Return 0
        If observed {
            If r.%Get("runtime_state")="FAILED" Throw ##class(%Exception.General).%New("RESUME_RUNTIME_FAILED")
            If (r.%Get("production_state")=1)&&r.%Get("runtime_ready")&&(r.%Get("runtime_state")="RECOVERED")&&(r.%Get("current_generation")'=oldGeneration) Return 1
        }
        // Observe has released bootLock; providerLock remains with the caller.
        Hang 0.1
    }
    Do ..ClearObservation(r)
    Return 0
}

/// Hash exact UTF-8 configuration bytes; no raw configuration enters a receipt.
ClassMethod ConfigDigest(value As %String) As %String [ Private ]
{
    If value="" Throw ##class(%Exception.General).%New("EMPTY_RECOVERY_BINDING")
    Return $ZConvert($System.Encryption.ToHex($System.Encryption.SHAHash(256,$ZConvert(value,"O","UTF8"))),"L")
}

ClassMethod RecoveryBindings(item As %DynamicObject, r As %DynamicObject) [ Private ]
{
    If (..ConfigDigest($Get(^ChronosJury("provider")))'=item.providerDigest)||(..ConfigDigest($Get(^ChronosAI18("config")))'=item.modelDigest)||(..ConfigDigest($Get(^ChronosWeb("config")))'=item.webDigest)||(..ConfigDigest($Get(^ChronosRuntime("config")))'=item.runtimeConfigDigest) Throw ##class(%Exception.General).%New("RECOVERY_CONFIG_CHANGED")
    If r.%Get("web_enabled")'=item.webEnabled Throw ##class(%Exception.General).%New("RECOVERY_WEB_CHANGED")
    If $Get(^ChronosJury("resumeGeneration",item.previousGeneration))'=item.requestId Throw ##class(%Exception.General).%New("RECOVERY_GENERATION_FENCE_CHANGED")
}

/// Caller owns providerLock. Every phase commits and flushes before further I/O.
/// A recovered production can be stopped (2) OR suspended (3); never purge queues.
ClassMethod SaveRecovery(item As %DynamicObject, r As %DynamicObject, create As %Boolean = 0) [ Private ]
{
    If $TLevel Throw ##class(%Exception.General).%New("RECOVERY_REQUIRES_NO_TRANSACTION")
    If create {
        If $Data(^ChronosJury("resumeRequest",item.requestId))||$Data(^ChronosJury("resumeGeneration",item.previousGeneration)) Throw ##class(%Exception.General).%New("RECOVERY_FENCE_EXISTS")
        If (item.state'="REQUESTED")||(item.recoveryPhase'="RECOVER_REQUESTED") Throw ##class(%Exception.General).%New("INVALID_INITIAL_RECOVERY_PHASE")
    } Else {
        Set prior=##class(%DynamicObject).%FromJSON($Get(^ChronosJury("resumeRequest",item.requestId)))
        If (prior.%Get("requestKind")'="recover")||(prior.state'="REQUESTED") Throw ##class(%Exception.General).%New("RECOVERY_RECEIPT_CHANGED")
        For field="deploymentId","bundle","profileSha256","bindingSha256","installationId","requestId","previousGeneration","previousRuntimeState","providerDigest","modelDigest","webDigest","runtimeConfigDigest","webEnabled" {
            If prior.%Get(field)'=item.%Get(field) Throw ##class(%Exception.General).%New("RECOVERY_RECEIPT_BINDING_CHANGED")
        }
        If prior.recoveredProductionState'=item.recoveredProductionState {
            If (prior.recoveryPhase'="RECOVER_REQUESTED")||(prior.recoveredProductionState'=0)||(item.recoveryPhase'="RECOVERED_OBSERVED")||'$ListFind($ListBuild(2,3),item.recoveredProductionState) Throw ##class(%Exception.General).%New("RECOVERED_STATE_BINDING_CHANGED")
        }
        Set transition=prior.recoveryPhase_":"_item.recoveryPhase
        If '$ListFind($ListBuild("RECOVER_REQUESTED:RECOVERED_OBSERVED","RECOVERED_OBSERVED:START_REQUESTED","START_REQUESTED:VERIFIED"),transition) Throw ##class(%Exception.General).%New("RECOVERY_PHASE_CHANGED")
        If $Get(^ChronosJury("resumeGeneration",item.previousGeneration))'=item.requestId Throw ##class(%Exception.General).%New("RECOVERY_GENERATION_FENCE_CHANGED")
    }
    If item.%GetTypeOf("recoveredProductionState")'="number" Throw ##class(%Exception.General).%New("INVALID_RECOVERED_STATE")
    If item.recoveryPhase="RECOVER_REQUESTED" {
        If item.recoveredProductionState'=0 Throw ##class(%Exception.General).%New("UNOBSERVED_RECOVERY_STATE_REQUIRED")
    } Else {
        If '$ListFind($ListBuild(2,3),item.recoveredProductionState) Throw ##class(%Exception.General).%New("RECOVERED_STATE_REQUIRED")
    }
    Set sc=##class(Chronos.Runtime.Durability).Check() $$$ThrowOnError(sc)
    Try {
        TStart
        Set ^ChronosJury("resumeRequest",item.requestId)=item.%ToJSON()
        If create Set ^ChronosJury("resumeGeneration",item.previousGeneration)=item.requestId
        TCommit
    } Catch ex {
        If $TLevel TRollback 1
        Throw ex
    }
    Do r.%Set("request_kind","recover"),r.%Set("request_state","REQUESTED"),r.%Set("previous_generation",item.previousGeneration),r.%Set("recorded_generation","")
    Do r.%Set("recovery_phase",$Select(item.recoveryPhase="VERIFIED":"START_REQUESTED",1:item.recoveryPhase)),r.%Set("diagnostic_code","DURABILITY_UNCONFIRMED")
    Set r.status="REQUESTED_OUTCOME_UNCERTAIN"
    Set sc=##class(Chronos.Runtime.Durability).Flush() $$$ThrowOnError(sc)
    Do r.%Set("request_state",item.state),r.%Set("recovery_phase",item.recoveryPhase),r.%Set("diagnostic_code",item.diagnosticCode)
}

ClassMethod RecoveredState(item As %DynamicObject, r As %DynamicObject, s As %DynamicObject) [ Private ]
{
    Do ..Observe(r,s)
    Do ..RecoveryBindings(item,r)
    Set nativeState=r.%Get("production_state")
    If '$ListFind($ListBuild(2,3),nativeState)||r.%Get("runtime_ready")||(r.%Get("current_generation")'=item.previousGeneration)||(r.%Get("runtime_state")'=item.previousRuntimeState) Throw ##class(%Exception.General).%New("RECOVERY_STATE_CONDITION_REQUIRED")
    If item.recoveredProductionState=0 {
        If item.recoveryPhase'="RECOVER_REQUESTED" Throw ##class(%Exception.General).%New("RECOVERED_STATE_NOT_BOUND")
    } Else {
        If nativeState'=item.recoveredProductionState Throw ##class(%Exception.General).%New("RECOVERED_STATE_CHANGED")
    }
}

/// Resolution records the current condition, never causal ownership of a start.
ClassMethod VerifyRecovery(item As %DynamicObject, r As %DynamicObject, s As %DynamicObject, origin As %String, application As %String) [ Private ]
{
    Do ..RecoveryBindings(item,r)
    If (r.%Get("production_state")'=1)||'r.%Get("runtime_ready")||(r.%Get("runtime_state")'="RECOVERED")||(r.%Get("current_generation")=item.previousGeneration) Throw ##class(%Exception.General).%New("RECOVERY_READY_CONDITION_REQUIRED")
    Set observedGeneration=r.%Get("current_generation")
    Set base=..Provider(item.deploymentId,origin,application,item.bundle,item.profileSha256,item.bindingSha256)
    Do ..Observe(r,s)
    Do ..RecoveryBindings(item,r)
    If (r.%Get("production_state")'=1)||'r.%Get("runtime_ready")||(r.%Get("runtime_state")'="RECOVERED")||(r.%Get("current_generation")'=observedGeneration) Throw ##class(%Exception.General).%New("RECOVERY_READY_CONDITION_CHANGED")
    Set item.state="VERIFIED",item.recoveryPhase="VERIFIED",item.generation=observedGeneration,item.diagnosticCode="VERIFIED"
    Do ..SaveRecovery(item,r)
    Set found=..ReadRequest(r,item.requestId,s,item.bundle,item.profileSha256,item.bindingSha256,item.installationId)
}

ClassMethod StartRecovery(item As %DynamicObject, r As %DynamicObject, s As %DynamicObject, origin As %String, application As %String) [ Private ]
{
    If item.recoveryPhase'="RECOVERED_OBSERVED" Throw ##class(%Exception.General).%New("RECOVERY_START_PHASE_REQUIRED")
    Do ..RecoveredState(item,r,s)
    Set oldFence=^ChronosJury("provider"),oldModel=^ChronosAI18("config"),oldWeb=item.webEnabled
    Set item.recoveryPhase="START_REQUESTED",item.diagnosticCode="START_CALL_UNCERTAIN"
    Do ..SaveRecovery(item,r)
    // Recheck the SAME observed native state (2 or 3) after sync; never repeat Start.
    Do ..RecoveredState(item,r,s)
    Do r.%Set("start_requested_this_call",1,"boolean"),r.%Set("diagnostic_code","START_CALL_UNCERTAIN")
    Set sc=##class(Ens.Director).StartProduction("Chronos.App.Production") $$$ThrowOnError(sc)
    Do r.%Set("diagnostic_code","READBACK_REJECTED")
    Set deadline=..MonotonicMS()+30000,base=0
    For attempt=1:1:301 {
        If '..WaitObserved(r,s,item.previousGeneration,oldWeb,oldFence,oldModel,deadline) Quit
        Do ..RecoveryBindings(item,r)
        Set base=..Provider(item.deploymentId,origin,application,item.bundle,item.profileSha256,item.bindingSha256,1)
        If ..MonotonicMS()>=deadline Set base=0 Quit
        Quit:$IsObject(base)
        Hang .1
    }
    If '$IsObject(base) {
        Do r.%Set("diagnostic_code","READBACK_TIMEOUT")
        Throw ##class(%Exception.General).%New("RECOVERY_READBACK_TIMEOUT")
    }
    If '..WaitObserved(r,s,item.previousGeneration,oldWeb,oldFence,oldModel,deadline) {
        Do r.%Set("diagnostic_code","READBACK_TIMEOUT")
        Throw ##class(%Exception.General).%New("RECOVERY_FINAL_READBACK_TIMEOUT")
    }
    Do ..RecoveryBindings(item,r)
    Set item.state="VERIFIED",item.recoveryPhase="VERIFIED",item.generation=r.%Get("current_generation"),item.diagnosticCode="VERIFIED"
    Do ..SaveRecovery(item,r)
    Set found=..ReadRequest(r,item.requestId,s,item.bundle,item.profileSha256,item.bindingSha256,item.installationId)
}

ClassMethod NewRecovery(r As %DynamicObject, s As %DynamicObject, digest As %String, profile As %String, binding As %String, installation As %String, requestId As %String, expectedGeneration As %String, origin As %String, application As %String) [ Private ]
{
    If (r.status'="CRASH_RECOVERY_AVAILABLE")||(r.%Get("current_generation")'=expectedGeneration) Throw ##class(%Exception.General).%New("FRESH_TROUBLED_GENERATION_REQUIRED")
    Set item={"deploymentId":(s.id),"bundle":(digest),"profileSha256":(profile),"bindingSha256":(binding),"installationId":(installation),"requestId":(requestId),"previousGeneration":(expectedGeneration),"state":"REQUESTED","requestKind":"recover","recoveryPhase":"RECOVER_REQUESTED","diagnosticCode":"RECOVERY_CALL_UNCERTAIN","previousRuntimeState":(r.%Get("runtime_state")),"recoveredProductionState":0}
    Set item.providerDigest=..ConfigDigest($Get(^ChronosJury("provider"))),item.modelDigest=..ConfigDigest($Get(^ChronosAI18("config"))),item.webDigest=..ConfigDigest($Get(^ChronosWeb("config"))),item.runtimeConfigDigest=..ConfigDigest($Get(^ChronosRuntime("config")))
    Do item.%Set("webEnabled",r.%Get("web_enabled"),"boolean")
    Do ..SaveRecovery(item,r,1)
    Do ..Observe(r,s)
    Do ..RecoveryBindings(item,r)
    If (r.%Get("production_state")'=4)||r.%Get("runtime_ready")||(r.%Get("current_generation")'=expectedGeneration)||(r.%Get("runtime_state")'=item.previousRuntimeState) Throw ##class(%Exception.General).%New("TROUBLED_CONDITION_CHANGED")
    // Observe requires the exact production name for running, suspended or troubled.
    Do r.%Set("recover_requested_this_call",1,"boolean"),r.%Set("diagnostic_code","RECOVERY_CALL_UNCERTAIN")
    Set sc=##class(Ens.Director).RecoverProduction() $$$ThrowOnError(sc)
    Do r.%Set("diagnostic_code","READBACK_REJECTED")
    Do ..RecoveredState(item,r,s)
    Set item.recoveredProductionState=r.%Get("production_state"),item.recoveryPhase="RECOVERED_OBSERVED",item.diagnosticCode="RECOVERY_STATE_OBSERVED"
    Do ..SaveRecovery(item,r)
    Do ..StartRecovery(item,r,s,origin,application)
}

/// Rejecting an action does not invalidate a historical receipt. Do not project
/// its VERIFIED diagnostic as the result of a rejected action; status can read it.
ClassMethod RejectReceiptView(r As %DynamicObject) [ Private ]
{
    Do r.%Set("request_state","UNKNOWN"),r.%Set("request_kind","none"),r.%Set("recovery_phase","NONE")
    Do r.%Set("previous_generation",""),r.%Set("recorded_generation",""),r.%Set("diagnostic_code","READBACK_REJECTED")
}
ClassMethod ExistingRecovery(action As %String, r As %DynamicObject, s As %DynamicObject, origin As %String, application As %String) [ Private ]
{
    // An unconfirmed barrier can never be used as permission to continue.
    If r.%Get("diagnostic_code")="DURABILITY_UNCONFIRMED" Throw ##class(%Exception.General).%New("RECOVERY_DURABILITY_UNCONFIRMED")
    Set item=##class(%DynamicObject).%FromJSON(^ChronosJury("resumeRequest",r.%Get("request_id")))
    If item.%Get("requestKind")'="recover" Throw ##class(%Exception.General).%New("RECOVERY_REQUEST_REQUIRED")
    Set r.status="REJECTED_STATE_PRESERVED"
    Do ..RecoveryBindings(item,r)
    If action="continue-recovery" {
        If (item.state'="REQUESTED")||(item.recoveryPhase'="RECOVERED_OBSERVED") Throw ##class(%Exception.General).%New("RECOVERY_CONTINUATION_NOT_AVAILABLE")
        Set r.status="REQUESTED_OUTCOME_UNCERTAIN"
        Do ..StartRecovery(item,r,s,origin,application)
        Return
    }
    If action'="resolve-recovery" Throw ##class(%Exception.General).%New("INVALID_RECOVERY_ACTION")
    If item.state="VERIFIED" {
        Set found=..ReadRequest(r,item.requestId,s,item.bundle,item.profileSha256,item.bindingSha256,item.installationId)
        Return
    }
    Set r.status="REQUESTED_OUTCOME_UNCERTAIN"
    If item.recoveryPhase="RECOVER_REQUESTED" {
        If $ListFind($ListBuild(2,3),r.%Get("production_state"))&&'r.%Get("runtime_ready")&&(r.%Get("current_generation")=item.previousGeneration)&&(r.%Get("runtime_state")=item.previousRuntimeState) {
            Do ..RecoveredState(item,r,s)
            Set item.recoveredProductionState=r.%Get("production_state"),item.recoveryPhase="RECOVERED_OBSERVED",item.diagnosticCode="RECOVERY_STATE_OBSERVED"
            Do ..SaveRecovery(item,r)
        }
    } ElseIf item.recoveryPhase="START_REQUESTED" {
        If (r.%Get("production_state")=1)&&r.%Get("runtime_ready")&&(r.%Get("runtime_state")="RECOVERED")&&(r.%Get("current_generation")'=item.previousGeneration) Do ..VerifyRecovery(item,r,s,origin,application)
    }
    // RECOVERED_OBSERVED resolution is readback only. Only continue may start.
}
ClassMethod ReadRequest(r As %DynamicObject, requestId As %String, s As %DynamicObject, digest As %String, profile As %String, binding As %String, installation As %String) As %Boolean [ Private ]
{
    Set raw=$Get(^ChronosJury("resumeRequest",requestId))
    If raw="" Do r.%Set("request_state","ABSENT") Return 0
    Set item=##class(%DynamicObject).%FromJSON(raw)
    If (item.deploymentId'=s.id)||(item.bundle'=digest)||(item.profileSha256'=profile)||(item.bindingSha256'=binding)||(item.installationId'=installation)||(item.requestId'=requestId)||'..Identifier(item.previousGeneration) Throw ##class(%Exception.General).%New("RESUME_REQUEST_BINDING_CHANGED")
    If $Get(^ChronosJury("resumeGeneration",item.previousGeneration))'=requestId Throw ##class(%Exception.General).%New("RESUME_GENERATION_FENCE_CHANGED")
    If (r.%Get("expected_generation")'="")&&(item.previousGeneration'=r.%Get("expected_generation")) Throw ##class(%Exception.General).%New("EXPECTED_GENERATION_CHANGED")
    Set kind=item.%Get("requestKind","resume"),phase=item.%Get("recoveryPhase","NONE")
    If '$ListFind($ListBuild("resume","recover"),kind) Throw ##class(%Exception.General).%New("INVALID_REQUEST_KIND")
    If kind="resume" {
        If phase'="NONE" Throw ##class(%Exception.General).%New("INVALID_RESUME_PHASE")
    } Else {
        If '$ListFind($ListBuild("RECOVER_REQUESTED","RECOVERED_OBSERVED","START_REQUESTED","VERIFIED"),phase) Throw ##class(%Exception.General).%New("INVALID_RECOVERY_PHASE")
        If ((item.state="VERIFIED")'=(phase="VERIFIED")) Throw ##class(%Exception.General).%New("RECOVERY_STATE_PHASE_MISMATCH")
        For field="providerDigest","modelDigest","webDigest","runtimeConfigDigest" {
            If (item.%GetTypeOf(field)'="string")||($Length(item.%Get(field))'=64)||($Translate(item.%Get(field),"0123456789abcdef")'="") Throw ##class(%Exception.General).%New("INVALID_RECOVERY_BINDING")
        }
        If item.%GetTypeOf("webEnabled")'="boolean" Throw ##class(%Exception.General).%New("INVALID_RECOVERY_WEB_BINDING")
        If item.%GetTypeOf("recoveredProductionState")'="number" Throw ##class(%Exception.General).%New("INVALID_RECOVERED_STATE")
        If phase="RECOVER_REQUESTED" {
            If item.recoveredProductionState'=0 Throw ##class(%Exception.General).%New("UNOBSERVED_RECOVERY_STATE_REQUIRED")
        } Else {
            If '$ListFind($ListBuild(2,3),item.recoveredProductionState) Throw ##class(%Exception.General).%New("RECOVERED_STATE_REQUIRED")
        }
        If '$ListFind($ListBuild("STOPPED","RECOVERED","RECOVERING","FAILED"),item.%Get("previousRuntimeState")) Throw ##class(%Exception.General).%New("INVALID_RECOVERY_BOOT_BINDING")
    }
    If '$ListFind($ListBuild("REQUESTED","VERIFIED"),item.state) Throw ##class(%Exception.General).%New("INVALID_RESUME_REQUEST_STATE")
    Set diagnostic=item.%Get("diagnosticCode","LEGACY_RECEIPT")
    If '$ListFind($ListBuild("LEGACY_RECEIPT","START_CALL_UNCERTAIN","DURABILITY_UNCONFIRMED","READBACK_PENDING","READBACK_TIMEOUT","READBACK_REJECTED","VERIFIED","RECOVERY_CALL_UNCERTAIN","RECOVERY_STATE_OBSERVED"),diagnostic) Throw ##class(%Exception.General).%New("INVALID_RESUME_DIAGNOSTIC")
    If (kind="resume")&&$ListFind($ListBuild("RECOVERY_CALL_UNCERTAIN","RECOVERY_STATE_OBSERVED"),diagnostic) Throw ##class(%Exception.General).%New("INVALID_RESUME_DIAGNOSTIC_KIND")
    Do r.%Set("request_kind",kind),r.%Set("recovery_phase",phase),r.%Set("request_state",item.state),r.%Set("previous_generation",item.previousGeneration),r.%Set("diagnostic_code",diagnostic)
    If item.state="VERIFIED" {
        If '..Identifier(item.generation)||(item.generation=item.previousGeneration) Throw ##class(%Exception.General).%New("INVALID_RESUME_READBACK")
    }
    // Recovery phases may authorize explicit continuation: confirm their barrier too.
    If (item.state="VERIFIED")||(kind="recover") {
        Set sc=##class(Chronos.Runtime.Durability).Flush()
        If $$$ISERR(sc) {
            Do r.%Set("request_state","REQUESTED"),r.%Set("recorded_generation",""),r.%Set("diagnostic_code","DURABILITY_UNCONFIRMED")
            If (kind="recover")&&(phase="VERIFIED") Do r.%Set("recovery_phase","START_REQUESTED")
            Set r.status="REQUESTED_OUTCOME_UNCERTAIN"
            Return 1
        }
    }
    If item.state="VERIFIED" {
        Do r.%Set("recorded_generation",item.generation) Set r.status="RESUME_VERIFIED"
    } Else {
        Set r.status="REQUESTED_OUTCOME_UNCERTAIN"
    }
    Return 1
}
ClassMethod Run(action As %String, id As %String, origin As %String, application As %String, digest As %String, profile As %String, binding As %String, requestId As %String = "", expectedGeneration As %String = "") As %String
{
    New $Namespace
    Set locked=0,transaction=0,durabilityPending=0,diagnostic="NOT_ATTEMPTED"
    Set r={"schema_version":"chronos.native-resume.v2","deployment_id":(id),"profile_sha256":(profile),"binding_sha256":null,"status":"REJECTED","request_id":(requestId),"expected_generation":(expectedGeneration),"request_state":"UNKNOWN","previous_generation":"","recorded_generation":"","current_generation":"","generation_request_id":"","production_state":null,"runtime_state":"UNKNOWN","runtime_ready":null,"web_enabled":null,"start_requested_this_call":false,"recover_requested_this_call":false,"request_kind":"none","recovery_phase":"NONE","model_tested":false,"ready":false,"diagnostic_code":"NOT_ATTEMPTED"}
    If ($Namespace'="%SYS")||($Username'="irisowner")||$TLevel||$Data(%request)||$Data(%session) Return r.%ToJSON()
    If '$ListFind($ListBuild("inspect","resume","status","recover","resolve-recovery","continue-recovery"),action) Return r.%ToJSON()
    For value=digest,profile,binding { If ($Length(value)'=64)||($Translate(value,"0123456789abcdef")'="") Return r.%ToJSON() }
    If action="inspect",(requestId'="")||(expectedGeneration'="") Return r.%ToJSON()
    If action'="inspect",($Length(requestId)'=32)||($Translate(requestId,"0123456789abcdef")'="") Return r.%ToJSON()
    If $ListFind($ListBuild("resume","recover","resolve-recovery","continue-recovery"),action),'..Identifier(expectedGeneration) Return r.%ToJSON()
    If action="status",expectedGeneration'="" Return r.%ToJSON()
    Try {
        Set s=##class(Chronos.Deployment.NativeInstall).Spec(id,origin,application)
        Set base=..Provider(id,origin,application,digest,profile,binding)
        Do r.%Set("binding_sha256",base.%Get("binding_sha256"))
        If action="resume" {
            If $System.Util.GetEnviron("CHRONOS_RESUME_AUTHORIZED")'=(id_":"_digest_":"_profile_":"_binding_":"_requestId_":"_expectedGeneration) Throw ##class(%Exception.General).%New("EXPLICIT_RESUME_AUTHORIZATION_REQUIRED")
        }
        If $ListFind($ListBuild("recover","resolve-recovery","continue-recovery"),action) {
            If $System.Util.GetEnviron("CHRONOS_RECOVERY_AUTHORIZED")'=(action_":"_id_":"_digest_":"_profile_":"_binding_":"_requestId_":"_expectedGeneration) Throw ##class(%Exception.General).%New("EXPLICIT_RECOVERY_AUTHORIZATION_REQUIRED")
        }
        Set $Namespace=s.namespace
        // Readers share the fence: never expose a receipt while its sync is pending.
        // Reentrant provider status uses this same process-owned mutex.
        Lock +^ChronosJury("providerLock"):0
        If '$Test Set r.status="BUSY" Throw ##class(%Exception.General).%New("PROVIDER_BUSY")
        Set locked=1
        Set base=..Provider(id,origin,application,digest,profile,binding)
        Set web=##class(%DynamicObject).%FromJSON($Get(^ChronosWeb("config"))),installation=web.installationId
        Do ..Observe(r,s)
        Set existing=0
        If requestId'="" Set existing=..ReadRequest(r,requestId,s,digest,profile,binding,installation)
        If existing {
            If ((action="resume")&&(r.%Get("request_kind")'="resume"))||($ListFind($ListBuild("recover","resolve-recovery","continue-recovery"),action)&&(r.%Get("request_kind")'="recover")) {
                Set r.status="REJECTED_STATE_PRESERVED"
                Throw ##class(%Exception.General).%New("REQUEST_KIND_MISMATCH")
            }
            If $ListFind($ListBuild("resolve-recovery","continue-recovery"),action) Do ..ExistingRecovery(action,r,s,origin,application)
        }
        If 'existing {
            Set r.status="NOT_RESUMABLE"
            If (r.%Get("production_state")=2)&&(r.%Get("runtime_state")="STOPPED")&&'r.%Get("runtime_ready")&&(r.%Get("generation_request_id")="") Set r.status="STOPPED_RESUME_AVAILABLE"
            If (r.%Get("production_state")=4)&&'r.%Get("runtime_ready")&&(r.%Get("generation_request_id")="") Set r.status="CRASH_RECOVERY_AVAILABLE"
            If (r.%Get("production_state")=1)&&(r.%Get("runtime_state")="RECOVERED")&&r.%Get("runtime_ready") Set r.status="CURRENTLY_RUNNING"
            If r.%Get("generation_request_id")'="" Set r.status="GENERATION_ALREADY_REQUESTED"
            If $ListFind($ListBuild("status","resolve-recovery","continue-recovery"),action) Set r.status="REQUEST_NOT_FOUND"
            If action="recover" Do ..NewRecovery(r,s,digest,profile,binding,installation,requestId,expectedGeneration,origin,application)
            If action="resume" {
                If (r.status'="STOPPED_RESUME_AVAILABLE")||(r.%Get("current_generation")'=expectedGeneration) Throw ##class(%Exception.General).%New("FRESH_STOPPED_GENERATION_REQUIRED")
                Set oldFence=^ChronosJury("provider"),oldModel=^ChronosAI18("config"),oldWeb=r.%Get("web_enabled")
                Set item={"deploymentId":(id),"bundle":(digest),"profileSha256":(profile),"bindingSha256":(binding),"installationId":(installation),"requestId":(requestId),"previousGeneration":(expectedGeneration),"state":"REQUESTED","requestKind":"resume","recoveryPhase":"NONE","diagnosticCode":"START_CALL_UNCERTAIN"}
                Set sc=##class(Chronos.Runtime.Durability).Check() $$$ThrowOnError(sc)
                TStart
                Set transaction=1
                Set ^ChronosJury("resumeRequest",requestId)=item.%ToJSON(),^ChronosJury("resumeGeneration",expectedGeneration)=requestId
                TCommit
                Set transaction=0,durabilityPending=1,diagnostic="DURABILITY_UNCONFIRMED"
                Do r.%Set("request_state","REQUESTED"),r.%Set("previous_generation",expectedGeneration),r.%Set("request_kind","resume")
                Set sc=##class(Chronos.Runtime.Durability).Flush() $$$ThrowOnError(sc)
                Set durabilityPending=0
                Do r.%Set("start_requested_this_call",1,"boolean")
                Set diagnostic="START_CALL_UNCERTAIN"
                Set sc=##class(Ens.Director).StartProduction("Chronos.App.Production") $$$ThrowOnError(sc)
                // Persist only after the start call returned success. This is not
                // causal attribution of the current generation or model readiness.
                Set diagnostic="READBACK_REJECTED",item.diagnosticCode="READBACK_PENDING"
                Set ^ChronosJury("resumeRequest",requestId)=item.%ToJSON()
                Set readbackDeadline=..MonotonicMS()+30000
                Set base=0
                For readbackAttempt=1:1:301 {
                    If '..WaitObserved(r,s,expectedGeneration,oldWeb,oldFence,oldModel,readbackDeadline) Quit
                    // A runtime lock may become busy between the two reads.
                    // Recheck every binding on each iteration; never start again.
                    Set base=..Provider(id,origin,application,digest,profile,binding,1)
                    If ..MonotonicMS()>=readbackDeadline Set base=0 Quit
                    Quit:$IsObject(base)
                    Hang 0.1
                }
                If '$IsObject(base) {
                    Set diagnostic="READBACK_TIMEOUT"
                    Throw ##class(%Exception.General).%New("RESUME_READBACK_TIMEOUT")
                }
                // Final readiness shares the SAME deadline; a second transient
                // contention neither extends the wait nor triggers another start.
                If '..WaitObserved(r,s,expectedGeneration,oldWeb,oldFence,oldModel,readbackDeadline) {
                    Set diagnostic="READBACK_TIMEOUT"
                    Throw ##class(%Exception.General).%New("RESUME_FINAL_READBACK_TIMEOUT")
                }
                If (r.%Get("production_state")'=1)||'r.%Get("runtime_ready")||(r.%Get("runtime_state")'="RECOVERED")||(r.%Get("current_generation")=expectedGeneration)||(r.%Get("web_enabled")'=oldWeb)||(^ChronosJury("provider")'=oldFence)||(^ChronosAI18("config")'=oldModel) Throw ##class(%Exception.General).%New("RESUME_READBACK_UNVERIFIED")
                Set item.state="VERIFIED",item.generation=r.%Get("current_generation"),item.diagnosticCode="VERIFIED"
                Set ^ChronosJury("resumeRequest",requestId)=item.%ToJSON()
                Set durabilityPending=1,diagnostic="DURABILITY_UNCONFIRMED"
                Set sc=##class(Chronos.Runtime.Durability).Flush() $$$ThrowOnError(sc)
                Set durabilityPending=0
                Set existing=..ReadRequest(r,requestId,s,digest,profile,binding,installation)
            }
        }
        // Existing resume/recover/status requests never repeat lifecycle I/O.
        // Only separately authorized recovery resolution/continuation may advance.
    } Catch ex {
        If transaction TRollback 1 Set transaction=0
        If (r.%Get("request_kind")="recover")&&(r.status="REQUESTED_OUTCOME_UNCERTAIN") {
            // Recovery helpers preserve committed phases; a catch never rewinds them.
            If r.%Get("request_state")="VERIFIED" {
                Do r.%Set("request_state","REQUESTED"),r.%Set("recovery_phase","START_REQUESTED"),r.%Set("recorded_generation",""),r.%Set("diagnostic_code","READBACK_REJECTED")
            }
            Do ..ClearObservation(r)
        } ElseIf durabilityPending||r.%Get("start_requested_this_call") {
            // A sync failure leaves durability uncertain. Never promise rollback.
            // A successfully flushed request survives a start/readback failure.
            // Do not imply rollback, cancellation or permission to retry a new ID.
            Set r.status="REQUESTED_OUTCOME_UNCERTAIN"
            Do r.%Set("diagnostic_code",diagnostic)
            If $IsObject($Get(item)),item.state="REQUESTED" {
                Set item.diagnosticCode=diagnostic
                Set ^ChronosJury("resumeRequest",requestId)=item.%ToJSON()
            }
            Do r.%Set("runtime_ready","","null"),r.%Set("production_state","","null")
            Do r.%Set("runtime_state","UNKNOWN"),r.%Set("current_generation",""),r.%Set("generation_request_id","")
        } ElseIf r.status'="BUSY" { Set r.status="REJECTED_STATE_PRESERVED" }
    }
    If (r.status="REJECTED_STATE_PRESERVED")&&'r.%Get("start_requested_this_call")&&'r.%Get("recover_requested_this_call")&&(r.%Get("request_kind")'="none") Do ..RejectReceiptView(r)
    If locked Lock -^ChronosJury("providerLock")
    Return r.%ToJSON()
}
}
