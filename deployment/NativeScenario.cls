Include %occStatus

/// Trusted console-only first case. Compiled in %SYS, never an HTTP dispatch.
/// Source verification and explicit per-invocation permission are in jury_case.py.
Class Chronos.Deployment.NativeScenario Extends %RegisteredObject
{
ClassMethod Run(action As %String, id As %String, scenario As %String, origin As %String, application As %String, digest As %String) As %String
{
    New $Namespace
    Set order="jury-"_id_"-"_scenario,request=order,boot=0,locked=0
    Set r={"schema_version":"chronos.jury-case.v1","status":"REJECTED","ready":false,"deployment_id":(id),"case":(scenario),"order_id":(order),"decision_id":(request),"runtime_ready":null,"native_state":"ABSENT","decision_state":"NOT_FOUND","deterministic_code":"","workflow_requests":0,"inference_may_have_run":true,"dispatch_authorized":false,"recovery_submissions":0}
    If ($Namespace'="%SYS")||$TLevel||$Data(%request)||$Data(%session)||($Username'="irisowner") Return r.%ToJSON()
    If $ZVersion'["2026.3.0AI (Build 154U)" Return r.%ToJSON()
    If '$ListFind($ListBuild("inspect","prepare","propose","status"),action) Return r.%ToJSON()
    If '$ListFind($ListBuild("earliest","economy","ambiguous","queue_inventory","accepted","uncertain"),scenario) Return r.%ToJSON()
    If ($Length(digest)'=64)||($Translate(digest,"0123456789abcdef")'="") Return r.%ToJSON()
    Try {
        Set s=##class(Chronos.Deployment.NativeInstall).Spec(id,origin,application)
        If ($Get(^ChronosInstall(id,"state"))'="NATIVE_INSTALLED_DISABLED")||($Get(^ChronosInstall(id,"bundle"))'=digest) Throw ##class(%Exception.General).%New("INSTALLATION_NOT_BOUND")
        If $Get(^ChronosInstall(id,"spec"))'=s.%ToJSON() Throw ##class(%Exception.General).%New("INSTALLATION_SPEC_CHANGED")
        // Resolve actual globals, not only the namespace's default database.
        For global="ChronosJury","ChronosRuntime","ChronosAuthority14","ChronosDecision16","ChronosWeb","ChronosAI18" {
            If ##class(%SYS.Namespace).GetGlobalDest(s.namespace,global)'=("^"_s.root_"/db/") Throw ##class(%Exception.General).%New("DATABASE_MAPPING_CHANGED")
        }
        Set database=##class(SYS.Database).%OpenId(s.root_"/db/")
        If '$IsObject(database)||(database.ResourceName'=s.resource)||(database.GlobalJournalState'=3) Throw ##class(%Exception.General).%New("OWNED_JOURNALED_DATABASE_REQUIRED")
        Set $Namespace=s.namespace
        Set cfg=##class(%DynamicObject).%FromJSON($Get(^ChronosRuntime("config")))
        If (cfg.production'="Chronos.App.Production")||(cfg.dataRoot'=s.destinations)||(cfg.pythonRoot'="/opt/chronos/src") Throw ##class(%Exception.General).%New("RUNTIME_BINDING_CHANGED")
        Set web=##class(%DynamicObject).%FromJSON($Get(^ChronosWeb("config")))
        If (web.origin'=origin)||(web.application'=application)||($Length(web.installationId)'=64) Throw ##class(%Exception.General).%New("WEB_BINDING_CHANGED")
        Set raw=$Get(^ChronosJury("case",scenario)),hasCase=(raw'="")
        If hasCase {
            Set item=##class(%DynamicObject).%FromJSON(raw)
            If (item.deploymentId'=id)||(item.orderId'=order)||(item.requestId'=request)||(item.bundle'=digest)||(item.installationId'=web.installationId) Throw ##class(%Exception.General).%New("CASE_BINDING_CHANGED")
            If '$ListFind($ListBuild("PREPARING","PREPARED","REQUEST_ISSUED"),item.state) Throw ##class(%Exception.General).%New("CASE_STATE_INVALID")
            Do r.%Set("native_state",item.state)
            If item.state="REQUEST_ISSUED" Do r.%Set("inference_may_have_run",1,"boolean")
        }
        Do r.%Set("inference_may_have_run",(r.%Get("native_state")="REQUEST_ISSUED"),"boolean")
        If (action="prepare")||(action="propose") {
            If $System.Util.GetEnviron("CHRONOS_JURY_AUTHORIZED")'=(action_":"_id_":"_scenario_":"_digest) Throw ##class(%Exception.General).%New("ACTION_AUTHORIZATION_REQUIRED")
            Lock +^ChronosJury("lock",scenario):0
            If '$Test Set r.status="BUSY" Throw ##class(%Exception.General).%New("CASE_BUSY")
            Set locked=1
            // Re-read after locking: another CLI may have issued the request.
            Set raw=$Get(^ChronosJury("case",scenario)),hasCase=(raw'="")
            If hasCase {
                Set item=##class(%DynamicObject).%FromJSON(raw)
                If (item.deploymentId'=id)||(item.orderId'=order)||(item.requestId'=request)||(item.bundle'=digest)||(item.installationId'=web.installationId) Throw ##class(%Exception.General).%New("CASE_BINDING_CHANGED")
                If '$ListFind($ListBuild("PREPARING","PREPARED","REQUEST_ISSUED"),item.state) Throw ##class(%Exception.General).%New("CASE_STATE_INVALID")
                Do r.%Set("native_state",item.state)
            }
            If hasCase,item.state="REQUEST_ISSUED" {
                Do r.%Set("inference_may_have_run",1,"boolean")
            } Else {
                Lock +^ChronosRuntime("bootLock"):0
                If '$Test Set r.status="RUNTIME_NOT_READY" Throw ##class(%Exception.General).%New("BOOT_BUSY")
                Set boot=1
                Set sc=##class(Chronos.Runtime.Bootstrap).Ready(.ready) $$$ThrowOnError(sc)
                If 'ready.ready Set r.status="RUNTIME_NOT_READY" Throw ##class(%Exception.General).%New("RUNTIME_NOT_READY")
                Do r.%Set("runtime_ready",1,"boolean")
                If action="prepare" {
                    Set sc=##class(Chronos.Runtime.Bootstrap).Provider(.provider) $$$ThrowOnError(sc)
                    Set sc=provider.Snapshot(order,.snapshot) $$$ThrowOnError(sc)
                    If (snapshot.orderId'=order)||(snapshot.shipmentVersion'=1) Throw ##class(%Exception.General).%New("SNAPSHOT_IDENTITY_CHANGED")
                    Set opid=order_"-original",attempt=order_"-original-attempt"
                    Set query={"operationId":(opid),"attemptId":(attempt),"orderId":(order),"shipmentVersion":1,"target":"A","payload":(snapshot.payload)}
                    // Obtain evidence independently from the configured destination.
                    // No receipt supplied by the CLI/browser/model is accepted.
                    Set sc=provider.Query(query,.receipt) $$$ThrowOnError(sc)
                    Set expectedStatus=$Select(scenario="accepted":"ACCEPTED",scenario="uncertain":"UNKNOWN",1:"NOT_ACCEPTED_FINAL")
                    If (receipt.status'=expectedStatus)||(receipt.%GetTypeOf("closedForever")'="boolean") Throw ##class(%Exception.General).%New("ORIGINAL_HISTORY_CHANGED")
                    If (expectedStatus="NOT_ACCEPTED_FINAL")'=(receipt.closedForever=1) Throw ##class(%Exception.General).%New("ORIGINAL_CLOSURE_CHANGED")
                    If 'hasCase {
                        // No overwriting an unrelated effect or reusing a decision ID.
                        If $Data(^ChronosAuthority14("effect",order,1))||$Data(^ChronosAuthority14("operation",opid))||$Data(^ChronosAuthority14("attempt",attempt))||$Data(^ChronosDecision16("decision",request)) Throw ##class(%Exception.General).%New("CASE_ID_COLLISION")
                        Set item={"deploymentId":(id),"orderId":(order),"requestId":(request),"bundle":(digest),"installationId":(web.installationId),"state":"PREPARING"}
                        Set ^ChronosJury("case",scenario)=item.%ToJSON(),hasCase=1
                    }
                    If '$Data(^ChronosAuthority14("operation",opid)) {
                        // Only an owned PREPARING case may complete an interrupted
                        // registration. Native authority still rejects collisions.
                        If item.state'="PREPARING" Throw ##class(%Exception.General).%New("PREPARED_OPERATION_MISSING")
                        Set sc=##class(Chronos.Authority.Store).Apply("REGISTER",{"snapshot":(snapshot),"originalOperationId":(opid),"originalTarget":"A","originalAttemptId":(attempt)},.registered) $$$ThrowOnError(sc)
                        If registered.code'="REGISTERED_UNKNOWN" Throw ##class(%Exception.General).%New("REGISTER_NOT_OBSERVED")
                    }
                    Set sc=##class(Chronos.Authority.Store).Apply("READ_OPERATION",{"operationId":(opid)},.current) $$$ThrowOnError(sc)
                    Set op=current.operation,effect=current.effect
                    If (op.orderId'=order)||(op.shipmentVersion'=1)||(op.attemptId'=attempt)||(op.target'="A")||(op.payload'=snapshot.payload)||(effect.currentOperationId'=opid)||effect.quarantined Throw ##class(%Exception.General).%New("AUTHORITY_BINDING_CHANGED")
                    If (op.state'="UNKNOWN")&&(op.state'=expectedStatus) Throw ##class(%Exception.General).%New("AUTHORITY_HISTORY_CHANGED")
                    Set sc=##class(Chronos.Authority.Store).Apply("EVIDENCE",receipt,.evidence) $$$ThrowOnError(sc)
                    If '$ListFind($ListBuild("EVIDENCE_RECORDED","RECEIPT_ALREADY_APPLIED","TERMINAL_PRESERVED"),evidence.code) Throw ##class(%Exception.General).%New("EVIDENCE_NOT_RECORDED")
                    Set sc=##class(Chronos.Authority.Store).Apply("READ_OPERATION",{"operationId":(opid)},.confirmed) $$$ThrowOnError(sc)
                    Set expectedEffect=$Select(expectedStatus="NOT_ACCEPTED_FINAL":"OPEN",1:expectedStatus)
                    If (confirmed.operation.state'=expectedStatus)||(confirmed.effect.state'=expectedEffect)||confirmed.effect.quarantined||(confirmed.effect.currentOperationId'=opid) Throw ##class(%Exception.General).%New("READBACK_FAILED")
                    Set item.state="PREPARED",^ChronosJury("case",scenario)=item.%ToJSON()
                    Do r.%Set("native_state",item.state)
                } Else {
                    If 'hasCase Throw ##class(%Exception.General).%New("PREPARE_REQUIRED")
                    If item.state'="PREPARED" Throw ##class(%Exception.General).%New("PREPARE_REQUIRED")
                    // No model/guard/allowance configuration is performed here.
                    If '$Data(^ChronosAI18("config")) Throw ##class(%Exception.General).%New("MODEL_CONFIGURATION_REQUIRED")
                    Set sc=##class(Chronos.Agent.Decisions).Read(request,.prior) $$$ThrowOnError(sc)
                    If prior.code'="NOT_FOUND" Throw ##class(%Exception.General).%New("DECISION_ID_COLLISION")
                    // Durable fence BEFORE sending the workflow request. A timeout,
                    // error or absent ledger cannot grant a second request.
                    Set item.state="REQUEST_ISSUED",^ChronosJury("case",scenario)=item.%ToJSON()
                    Do r.%Set("native_state",item.state)
                    Do r.%Set("inference_may_have_run",1,"boolean")
                    // Queued workers acquire bootLock themselves. Never hold it
                    // while waiting for Entry.Call, or their work cannot proceed.
                    Lock -^ChronosRuntime("bootLock") Set boot=0
                    Do r.%Set("workflow_requests",1,"number")
                    Set sc=##class(Chronos.App.Entry).Call("PROPOSE",order,1,"",.answer,request,"WITH_TRIALS")
                    // A return/error is not evidence that the provider did not run.
                    // Read the durable ledger below; never echo raw answer/errors.
                }
                If boot Lock -^ChronosRuntime("bootLock") Set boot=0
            }
        }
        Set sc=##class(Chronos.Agent.Decisions).Read(request,.decision) $$$ThrowOnError(sc)
        // Reads do not wait on the case lock. Sample the fence AFTER the ledger:
        // a concurrent request can only advance to REQUEST_ISSUED. A newer fence
        // with no observed ledger is uncertainty, never permission to retry.
        Set latest=$Get(^ChronosJury("case",scenario))
        If latest'="" {
            Set observed=##class(%DynamicObject).%FromJSON(latest)
            If (observed.deploymentId'=id)||(observed.orderId'=order)||(observed.requestId'=request)||(observed.bundle'=digest)||(observed.installationId'=web.installationId) Throw ##class(%Exception.General).%New("CASE_BINDING_CHANGED")
            If '$ListFind($ListBuild("PREPARING","PREPARED","REQUEST_ISSUED"),observed.state) Throw ##class(%Exception.General).%New("CASE_STATE_INVALID")
            Do r.%Set("native_state",observed.state)
            Do r.%Set("inference_may_have_run",(observed.state="REQUEST_ISSUED"),"boolean")
        } ElseIf hasCase { Throw ##class(%Exception.General).%New("CASE_DISAPPEARED") }
        If decision.code'="NOT_FOUND" {
            Do r.%Set("inference_may_have_run",1,"boolean")
            If r.%Get("native_state")'="REQUEST_ISSUED" Throw ##class(%Exception.General).%New("UNOWNED_DECISION_COLLISION")
            If (decision.requestId'=request)||(decision.orderId'=order)||(decision.shipmentVersion'=1)||(decision.mode'="WITH_TRIALS") Throw ##class(%Exception.General).%New("DECISION_BINDING_CHANGED")
            If '$ListFind($ListBuild("PREPARED","IN_FLIGHT","VALIDATING","UNCERTAIN","UNCERTAIN_VALIDATION","COMPLETED"),decision.state) Throw ##class(%Exception.General).%New("DECISION_STATE_INVALID")
            Do r.%Set("decision_state",decision.state)
            // This means a ledger record exists, not that its result is successful.
            Set r.status="DECISION_AVAILABLE"
            If decision.%GetTypeOf("result")="object",decision.result.%Get("status")="DETERMINISTIC" {
                If (decision.state'="COMPLETED")||decision.%IsDefined("call")||'$ListFind($ListBuild("EXISTING_ACCEPTANCE","ACCEPTANCE_UNRESOLVED"),decision.result.%Get("code")) Throw ##class(%Exception.General).%New("INVALID_DETERMINISTIC_RESULT")
                If (decision.result.%GetTypeOf("dispatch_authorized")'="boolean")||decision.result.%Get("dispatch_authorized") Throw ##class(%Exception.General).%New("INVALID_DETERMINISTIC_AUTHORITY")
                Do r.%Set("deterministic_code",decision.result.code)
                Do r.%Set("inference_may_have_run",0,"boolean")
            }
        } ElseIf r.%Get("native_state")="REQUEST_ISSUED" {
            Set r.status="REQUEST_OUTCOME_UNCERTAIN"
        } ElseIf r.%Get("native_state")="PREPARED" {
            Set r.status="PREPARED"
        } ElseIf r.%Get("native_state")="PREPARING" {
            Set r.status="PREPARATION_PARTIAL"
        } Else {
            Set r.status="NOT_PREPARED"
        }
        If action="inspect" {
            Set sc=##class(Chronos.Runtime.Bootstrap).Ready(.inspection) $$$ThrowOnError(sc)
            Do r.%Set("runtime_ready",inspection.ready,"boolean")
            Set r.status="BOUND"
        }
    } Catch ex {
        // Preserve all state, do not leak exception args/private context/answers.
        // An unreadable case is not proof that no earlier inference occurred.
        Do r.%Set("deterministic_code","")
        Do r.%Set("inference_may_have_run",1,"boolean")
        If (r.status'="BUSY")&&(r.status'="RUNTIME_NOT_READY") Set r.status="REJECTED_STATE_PRESERVED"
    }
    If boot Lock -^ChronosRuntime("bootLock")
    If locked Lock -^ChronosJury("lock",scenario)
    Return r.%ToJSON()
}
}
