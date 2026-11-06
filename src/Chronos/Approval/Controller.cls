Include %occStatus

/// Server composition only. No HTTP route is installed by this class.
/// HTTP must additionally enforce method/origin/CSRF, authenticated sessions,
/// request size and strict JSON parsing. Fixed production class, never user-selected.
Class Chronos.Approval.Controller Extends %RegisteredObject
{
/// Native identity only. Override exists solely in opt-in isolated test classes.
Method Principal(permission As %String, Output principal As %DynamicObject) As %Status
{
    Return ##class(Chronos.Approval.Identity).Current(permission,.principal)
}

/// Fixed installed provider. No class, URL or data root comes from the request.
Method GetProvider(Output provider As Chronos.Recovery.Provider) As %Status
{
    Return ##class(Chronos.Runtime.Bootstrap).Provider(.provider)
}

Method Denied(code As %String) As %DynamicObject [ Private ]
{
    Return {"code":(code),"dispatchGranted":false}
}

Method SamePrincipal(expected As %DynamicObject, permission As %String) As %Status [ Private ]
{
    Set sc=..Principal(permission,.current)
    If $$$ISERR(sc) Return sc
    If 'current.%Get("authenticated") Return $$$ERROR($$$GeneralError,"IDENTITY_CHANGED")
    If (current.actor'=expected.actor)||(current.sessionBinding'=expected.sessionBinding) Return $$$ERROR($$$GeneralError,"IDENTITY_CHANGED")
    Return $$$OK
}

Method Valid(command As %String, args As %DynamicObject) As %Boolean [ Private ]
{
    If '$ListFind($ListBuild("PREVIEW_REQUEST","READ_PREPARATION","CLOSE_PREPARATION","PREVIEW","READ","REJECT","CONFIRM","RECONCILE","DECISION","DECISION_DETAIL","DECISION_OPERATION","READ_OPERATION","RECONCILE_OPERATION","RESOLVE_DECISION"),command) Return 0
    If '$IsObject(args) Return 0
    If 'args.%IsA("%DynamicObject") Return 0
    Set field=##class(Chronos.Approval.Entry).IdentifierField(command)
    Set extra=##class(Chronos.Approval.Entry).NeedsCorrelation(command)
    If (args.%Size()'=(1+extra))||(args.%GetTypeOf(field)'="string") Return 0
    If extra {
        If (args.%GetTypeOf("requestId")'="string")||'##class(Chronos.App.Entry).ValidID(args.requestId) Return 0
    }
    Set value=args.%Get(field)
    If ($Length(value)<1)||($Length(value)>128) Return 0
    Return $Translate(value,"abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.")=""
}

/// Only decision/preview IDs enter. All grants remain local variables, never
/// Ens messages, response JSON or log material. Double clicks are readback only.
Method Handle(command As %String, args As %DynamicObject, Output result As %DynamicObject) As %Status
{
    Set result=..Denied("INVALID_REQUEST")
    If $TLevel Return $$$OK
    If '..Valid(command,args) Return $$$OK
    Set args=##class(%DynamicObject).%FromJSON(args.%ToJSON())
    Set permission=$Select((command="READ_PREPARATION")||(command="READ")||(command="RECONCILE")||(command="DECISION")||(command="DECISION_DETAIL")||(command="DECISION_OPERATION")||(command="READ_OPERATION")||(command="RECONCILE_OPERATION"):"READ",1:"APPROVE")
    Set sc=..Principal(permission,.principal)
    If $$$ISERR(sc) Set result=..Denied("IDENTITY_UNAVAILABLE") Return $$$OK
    If 'principal.%Get("authenticated") Set result=..Denied("PERMISSION_DENIED") Return $$$OK
    Set principal={"actor":(principal.actor),"sessionBinding":(principal.sessionBinding)}
    Lock +^ChronosRuntime("bootLock"):0
    If '$Test Set result=..Denied("RUNTIME_BUSY") Return $$$OK
    Set reservedId="",admitted="",coordinator="",queryId=""
    Try {
        Set sc=..RunLocked(command,args,principal,permission,.result,.reservedId,.admitted,.coordinator,.queryId)
        $$$ThrowOnError(sc)
    } Catch ex {
        Set admitted="",queryId=""
        Set result=..Denied("RECHECK_REQUIRED")
        If reservedId'="" {
            // No grant is returned even if cleanup/readback itself fails.
            Set result.operationId=reservedId,result.code="RECOVERY_REQUIRED"
            Set recovered=##class(Chronos.Authority.Store).Apply("RECOVER",{"operationId":(reservedId)},.ignored)
            If $$$ISOK(recovered),$IsObject(coordinator) {
                Set readStatus=coordinator.Observe(reservedId,.safe)
                If $$$ISOK(readStatus) Set result=safe,result.code="RESERVED_WITHOUT_SEND"
            }
        }
    }
    Lock -^ChronosRuntime("bootLock")
    If queryId'="" {
        // Fresh READ before query and before projection; no dispatch authority.
        Set sc=..SamePrincipal(principal,"READ")
        If $$$ISERR(sc) {
            Set result=..Denied("PERMISSION_DENIED")
        } Else {
            Set sc=coordinator.Reconcile(queryId,.result)
            If $$$ISERR(sc) Set result=..Denied("RECOVERY_REQUIRED"),result.operationId=queryId
            Set identityStatus=..SamePrincipal(principal,"READ")
            If $$$ISERR(identityStatus) Set result=..Denied("PERMISSION_DENIED")
        }
    }
    If $IsObject(admitted) {
        // One live continuation after lifecycle/gate/identity checked at ADMIT.
        // Subsequent closure cannot revoke an already committed admission.
        Set sc=coordinator.DispatchAdmitted(admitted,.result)
        If $$$ISERR(sc) Set result=..Denied("RECOVERY_REQUIRED"),result.operationId=reservedId
    }
    Return $$$OK
}

Method RunLocked(command As %String, args As %DynamicObject, principal As %DynamicObject, permission As %String, Output result As %DynamicObject, Output reservedId As %String, Output admitted As %DynamicObject, Output coordinator As Chronos.Recovery.Coordinator, Output queryId As %String) As %Status [ Private ]
{
    Set reservedId="",admitted="",queryId="",result=..Denied("RECHECK_REQUIRED")
    If $ListFind($ListBuild("PREVIEW_REQUEST","READ_PREPARATION","CLOSE_PREPARATION"),command) Return ..Preparation(command,args,principal,.result)
    If command="DECISION_OPERATION" Return ..DecisionOperation(args.decisionId,principal,.result)
    If (command="READ_OPERATION")||(command="RECONCILE_OPERATION") {
        Set sc=##class(Chronos.Recovery.Coordinator).Observe(args.operationId,.result)
        If $$$ISERR(sc) Set result=..Denied("OPERATION_UNAVAILABLE") Return $$$OK
        Set sc=..SamePrincipal(principal,"READ") If $$$ISERR(sc) Return sc
        If command="READ_OPERATION" Return $$$OK
        Set sc=..GetProvider(.provider) If $$$ISERR(sc) Return sc
        Set sc=##class(Chronos.Runtime.Bootstrap).Ready(.ready) If $$$ISERR(sc) Return sc
        If 'ready.ready Set result=..Denied("RUNTIME_NOT_READY") Return $$$OK
        Set sc=..SamePrincipal(principal,"READ") If $$$ISERR(sc) Return sc
        Set coordinator=##class(Chronos.Recovery.Coordinator).%New(provider)
        // Never substitute a newer currentOperationId for the exact supplied ID.
        Set queryId=args.operationId
        Return $$$OK
    }
    If command="DECISION_DETAIL" Return ..DecisionDetail(args.decisionId,principal,.result)
    If (command="DECISION")||(command="RESOLVE_DECISION") Return ..Decision(command,args.decisionId,principal,permission,.result)
    If command="PREVIEW" Return ..CreatePreview(args.decisionId,principal,.result)
    Set owner={"previewId":(args.previewId),"actor":(principal.actor),"sessionBinding":(principal.sessionBinding)}
    Set sc=##class(Chronos.Authority.Store).Apply("READ_PREVIEW",owner,.p)
    If $$$ISERR(sc),((command="READ")||(command="RECONCILE")),($System.Status.GetErrorText(sc)["PREVIEW_NOT_AVAILABLE") {
        Set sc=##class(Chronos.Authority.Store).Apply("READ_CONFIRMED_PREVIEW",{"previewId":(args.previewId),"actor":(principal.actor)},.p)
    }
    If $$$ISERR(sc) Set result=..Denied("PREVIEW_NOT_AVAILABLE") Return $$$OK
    If command="REJECT" {
        Set sc=..SamePrincipal(principal,"APPROVE") If $$$ISERR(sc) Return sc
        Return ##class(Chronos.Authority.Store).Apply("REJECT_PREVIEW",owner,.result)
    }
    If command="READ" {
        Set result=p
        If p.state="CONFIRMED" {
            Set sc=##class(Chronos.Recovery.Coordinator).Observe(p.operationId,.safe) If $$$ISERR(sc) Return sc
            Set result.operation=safe
        }
        Return $$$OK
    }
    If (command="RECONCILE")&&(p.state'="CONFIRMED") Set result=..Denied("NO_CONFIRMED_OPERATION") Return $$$OK
    If (command="CONFIRM")&&(p.state="CONFIRMED") Return ##class(Chronos.Recovery.Coordinator).Observe(p.operationId,.result)
    Set sc=..GetProvider(.provider) If $$$ISERR(sc) Return sc
    Set coordinator=##class(Chronos.Recovery.Coordinator).%New(provider)
    If '$IsObject(coordinator) Return $$$ERROR($$$GeneralError,"NO_COORDINATOR")
    Set expectedGeneration=$Select(command="RECONCILE":"",1:p.generation)
    Set sc=##class(Chronos.Runtime.Bootstrap).Ready(.ready,expectedGeneration) If $$$ISERR(sc) Return sc
    If 'ready.ready Set result=..Denied("RUNTIME_NOT_READY") Return $$$OK
    If command="RECONCILE" {
        Set sc=..SamePrincipal(principal,"READ") If $$$ISERR(sc) Return sc
        Set queryId=p.operationId
        Return $$$OK
    }
    If p.state'="PENDING" Set result=..Denied("PREVIEW_NOT_PENDING") Return $$$OK
    // Never REFRESH a preview at confirmation. Check its original exact binding
    // against a fresh semantic observation; changed consent needs a new preview.
    Set sc=##class(Chronos.Agent.Context).Review(p.decisionId,.review) If $$$ISERR(sc) Return sc
    If review.%Get("status")'="REVIEWABLE" Set result=..Denied(review.%Get("code","RECHECK_REQUIRED")) Return $$$OK
    Set b=review.binding
    For field="decisionId","decisionDigest","orderId","shipmentVersion","option","generation","reviewDeadlineUS" {
        If (b.%GetTypeOf(field)'=p.%GetTypeOf(field))||(b.%Get(field)'=p.%Get(field)) Return $$$ERROR($$$GeneralError,"PREVIEW_CHANGED")
    }
    If b.expectedSnapshotId'=p.snapshotId Return $$$ERROR($$$GeneralError,"PREVIEW_SNAPSHOT_CHANGED")
    Set sc=..SamePrincipal(principal,"APPROVE") If $$$ISERR(sc) Return sc
    Set owner.generation=p.generation
    Set sc=##class(Chronos.Authority.Store).Apply("CONFIRM_RESERVE",owner,.reservation) If $$$ISERR(sc) Return sc
    If 'reservation.%Get("reservationGranted") Return coordinator.Observe(p.operationId,.result)
    Set reservedId=reservation.operationId
    Set sc=..SamePrincipal(principal,"APPROVE") If $$$ISERR(sc) Return sc
    Set sc=##class(Chronos.Runtime.Bootstrap).Ready(.ready,p.generation) If $$$ISERR(sc) Return sc
    If 'ready.ready Return $$$ERROR($$$GeneralError,"RUNTIME_CHANGED")
    Set sc=##class(Chronos.Authority.Store).Apply("ADMIT",{"operationId":(reservedId),"attemptId":(reservation.attemptId),"actor":(principal.actor),"claimId":(reservation.claimId)},.grant)
    If $$$ISERR(sc) Return sc
    If 'grant.%Get("dispatchGranted") Return $$$ERROR($$$GeneralError,"NO_ADMISSION")
    Set admitted=grant
    Return $$$OK
}

/// Public receipt projection. Internal creation authority never enters a native
/// message or HTTP response. RECORDED means preview recorded, not approved.
Method PublicPreparation(receipt As %DynamicObject) As %DynamicObject [ Private ]
{
    Set result={"dispatchGranted":false,"canConfirm":false}
    For field="code","requestId","actor","decisionId","previewId","state" {
        If receipt.%GetTypeOf(field)'="string" Return ..Denied("PREPARATION_UNAVAILABLE")
        Do result.%Set(field,receipt.%Get(field))
    }
    Return result
}

/// Called under bootLock in the authenticated job. Duplicate creation requests
/// are reads only, before any Snapshot, REFRESH or semantic Review can run.
Method Preparation(command As %String, args As %DynamicObject, principal As %DynamicObject, Output result As %DynamicObject) As %Status [ Private ]
{
    Set permission=$Select(command="READ_PREPARATION":"READ",1:"APPROVE")
    Set sc=..SamePrincipal(principal,permission) If $$$ISERR(sc) Return sc
    Set owner={"actor":(principal.actor),"requestId":(args.requestId)}
    If command="CLOSE_PREPARATION" {
        Set owner.decisionId=args.decisionId
        Set sc=##class(Chronos.Authority.Store).Apply("CLOSE_PREPARATION",owner,.receipt) If $$$ISERR(sc) Return sc
    } Else {
        Set sc=##class(Chronos.Authority.Store).Apply("READ_PREPARATION",owner,.receipt) If $$$ISERR(sc) Return sc
    }
    Set sc=..SamePrincipal(principal,permission) If $$$ISERR(sc) Return sc
    If command'="PREVIEW_REQUEST" Set result=..PublicPreparation(receipt) Return $$$OK
    If receipt.state'="NOT_FOUND" {
        If receipt.decisionId'=args.decisionId Set result=..Denied("PREPARATION_ID_CONFLICT") Return $$$OK
        Set result=..PublicPreparation(receipt)
        Return $$$OK
    }
    Set sc=##class(Chronos.Runtime.Bootstrap).Ready(.ready) If $$$ISERR(sc) Return sc
    If 'ready.ready Set result=..Denied("RUNTIME_NOT_READY") Return $$$OK
    // A known nonactionable decision must not leave a STARTED receipt. Existing
    // receipts were returned above unchanged, including an uncertain creation.
    Set sc=##class(Chronos.Agent.Decisions).Read(args.decisionId,.decision) If $$$ISERR(sc) Return sc
    Set sc=..SamePrincipal(principal,"APPROVE") If $$$ISERR(sc) Return sc
    If decision.%Get("state")'="COMPLETED" Set result=..Denied("DECISION_NOT_ACTIONABLE") Return $$$OK
    If decision.%GetTypeOf("result")'="object" Set result=..Denied("DECISION_NOT_ACTIONABLE") Return $$$OK
    If decision.result.%Get("status")'="VALIDATED_PROPOSAL" Set result=..Denied("DECISION_NOT_ACTIONABLE") Return $$$OK
    Set sc=..SamePrincipal(principal,"APPROVE") If $$$ISERR(sc) Return sc
    Set beginArgs={"actor":(principal.actor),"sessionBinding":(principal.sessionBinding),"generation":(ready.generation),"requestId":(args.requestId),"decisionId":(args.decisionId)}
    Set sc=##class(Chronos.Authority.Store).Apply("BEGIN_PREPARATION",beginArgs,.receipt) If $$$ISERR(sc) Return sc
    If (receipt.%GetTypeOf("preparationGranted")="boolean")&&receipt.preparationGranted {
        // If this call fails or its response is lost, the durable receipt wins.
        // Do not retry creation or close automatically. Explicit READ/CLOSE
        // can inspect/fence the original request even after runtime renewal.
        Try {
            Set creationStatus=..CreatePreview(args.decisionId,principal,.ignored,receipt.previewId)
        } Catch ex {
            Set creationStatus=$$$ERROR($$$GeneralError,"PREPARATION_INTERRUPTED")
        }
    }
    Set sc=..SamePrincipal(principal,"APPROVE") If $$$ISERR(sc) Return sc
    Set sc=##class(Chronos.Authority.Store).Apply("READ_PREPARATION",owner,.receipt) If $$$ISERR(sc) Return sc
    Set sc=..SamePrincipal(principal,"APPROVE") If $$$ISERR(sc) Return sc
    Set result=..PublicPreparation(receipt)
    Return $$$OK
}

/// Historical detail only. Called under bootLock in the original authenticated
/// job. Never accept a ledger record, source root or module name from the caller.
Method DecisionDetail(id As %String, principal As %DynamicObject, Output result As %DynamicObject) As %Status [ Private ]
{
    Set result=..Denied("DECISION_DETAIL_UNAVAILABLE")
    Set sc=..SamePrincipal(principal,"READ") If $$$ISERR(sc) Return sc
    Set sc=##class(Chronos.Runtime.Bootstrap).Ready(.ready) If $$$ISERR(sc) Return sc
    If 'ready.ready Set result=..Denied("RUNTIME_NOT_READY") Return $$$OK
    Set config=##class(%DynamicObject).%FromJSON(^ChronosRuntime("config"))
    Set sc=##class(Chronos.Agent.Ledger).Apply("INSPECT",{"requestId":(id)},.stored)
    If $$$ISERR(sc) Return sc
    Set sc=..SamePrincipal(principal,"READ") If $$$ISERR(sc) Return sc
    If 'stored.%IsDefined("private") {
        Set result=..Denied($Select(stored.code="NOT_FOUND":"NOT_FOUND",1:"DECISION_DETAIL_UNAVAILABLE"))
        Return $$$OK
    }
    Set sc=##class(Chronos.Agent.Python).Detail(config.pythonRoot,stored.private.%ToJSON(),id,.candidate)
    If $$$ISERR(sc) Return sc
    Set sc=..SamePrincipal(principal,"READ") If $$$ISERR(sc) Return sc
    Set sc=##class(Chronos.Runtime.Bootstrap).Ready(.again,ready.generation) If $$$ISERR(sc) Return sc
    If 'again.ready Return $$$ERROR($$$GeneralError,"REVIEW_RUNTIME_CHANGED")
    If '$IsObject(candidate) Return $$$ERROR($$$GeneralError,"INVALID_REVIEW_PROJECTION")
    If 'candidate.%IsA("%DynamicObject") Return $$$ERROR($$$GeneralError,"INVALID_REVIEW_PROJECTION")
    For field="dispatchGranted","canConfirm","currentAuthorityVerified" {
        If (candidate.%GetTypeOf(field)'="boolean")||candidate.%Get(field) Return $$$ERROR($$$GeneralError,"INVALID_REVIEW_PROJECTION")
    }
    If '$ListFind($ListBuild("DECISION_DETAIL_RECORDED","DECISION_DETAIL_UNAVAILABLE"),candidate.%Get("code")) Return $$$ERROR($$$GeneralError,"INVALID_REVIEW_PROJECTION")
    If candidate.code="DECISION_DETAIL_RECORDED",candidate.%Get("decisionId")'=id Return $$$ERROR($$$GeneralError,"REVIEW_IDENTITY_MISMATCH")
    Set result=candidate
    Return $$$OK
}

/// CURRENT operation at this read, not the decision's historical observation.
/// No provider I/O. All private authority fields remain inside this method.
Method DecisionOperation(id As %String, principal As %DynamicObject, Output result As %DynamicObject) As %Status [ Private ]
{
    Set result=..Denied("OPERATION_UNAVAILABLE")
    Set sc=##class(Chronos.Agent.Decisions).Read(id,.decision) If $$$ISERR(sc) Return sc
    If decision.%Get("code")="NOT_FOUND" Return $$$OK
    Set sc=##class(Chronos.Authority.Store).Apply("READ",{"orderId":(decision.orderId),"shipmentVersion":(decision.shipmentVersion)},.current) If $$$ISERR(sc) Return sc
    Set operationId=current.effect.%Get("currentOperationId")
    If (current.effect.%GetTypeOf("currentOperationId")'="string")||'##class(Chronos.App.Entry).ValidID(operationId) Return $$$OK
    Set sc=##class(Chronos.Authority.Store).Apply("READ_OPERATION",{"operationId":(operationId)},.read) If $$$ISERR(sc) Return sc
    If (read.operation.orderId'=decision.orderId)||(read.operation.shipmentVersion'=decision.shipmentVersion) Return $$$ERROR($$$GeneralError,"OPERATION_BINDING_MISMATCH")
    Set sc=##class(Chronos.Recovery.Coordinator).Observe(operationId,.safe) If $$$ISERR(sc) Return sc
    Set sc=..SamePrincipal(principal,"READ") If $$$ISERR(sc) Return sc
    Set result={"code":"DECISION_OPERATION_RECORDED","dispatchGranted":false,"decisionId":(id),"orderId":(decision.orderId),"shipmentVersion":(decision.shipmentVersion),"operation":(safe)}
    Return $$$OK
}

/// Status only: do not forward Ledger.View, its call metadata or full result.
/// READ is namespace-wide laboratory access, not per-decision ownership.
ClassMethod DecisionView(decision As %DynamicObject) As %DynamicObject
{
    Set result={"code":(decision.code),"dispatchGranted":false,"inferenceGranted":false,"dispatch_authorized":false}
    For field="requestId","orderId","shipmentVersion","mode","state","generation","deadlineUS" {
        If decision.%IsDefined(field) Do result.%Set(field,decision.%Get(field),decision.%GetTypeOf(field))
    }
    If decision.%GetTypeOf("result")="object" {
        Set source=decision.result,outcome={"dispatch_authorized":false}
        For field="status","code" {
            If source.%GetTypeOf(field)="string" Do outcome.%Set(field,source.%Get(field))
        }
        Set result.outcome=outcome
    }
    If decision.%GetTypeOf("resolution")="object" {
        Set source=decision.resolution,resolution={}
        For field="previousState","resolvedUS","inferenceMayHaveRun","providerCancellationVerified" {
            If source.%IsDefined(field) Do resolution.%Set(field,source.%Get(field),source.%GetTypeOf(field))
        }
        Set result.resolution=resolution
    }
    Return result
}

/// Called under bootLock, in the original CSP job and identity. No queued
/// inference/dispatch path; derive all effect bindings from the stored decision.
Method Decision(command As %String, id As %String, principal As %DynamicObject, permission As %String, Output result As %DynamicObject) As %Status [ Private ]
{
    Set sc=##class(Chronos.Agent.Decisions).Read(id,.decision)
    If $$$ISERR(sc) Return sc
    Set sc=..SamePrincipal(principal,permission)
    If $$$ISERR(sc) Return sc
    If (command="RESOLVE_DECISION")&&(decision.code'="NOT_FOUND") {
        Set sc=##class(Chronos.Runtime.Bootstrap).Ready(.ready)
        If $$$ISERR(sc) Return sc
        If 'ready.ready Set result=..Denied("RUNTIME_NOT_READY") Return $$$OK
        // Use the CURRENT generation to close an old expired decision after a
        // restart, never renew its original decision deadline or retry inference.
        Set sc=..SamePrincipal(principal,"APPROVE")
        If $$$ISERR(sc) Return sc
        Set sc=##class(Chronos.Agent.Decisions).Resolve(id,decision.orderId,decision.shipmentVersion,decision.mode,.resolved,ready.generation)
        If $$$ISERR(sc) Return sc
        Set decision=resolved
    }
    Set result=..DecisionView(decision)
    Return $$$OK
}

Method CreatePreview(decisionId As %String, principal As %DynamicObject, Output result As %DynamicObject, previewId As %String = "") As %Status [ Private ]
{
    Set result=..Denied("DECISION_NOT_ACTIONABLE")
    Set sc=##class(Chronos.Runtime.Bootstrap).Ready(.ready) If $$$ISERR(sc) Return sc
    If 'ready.ready Set result=..Denied("RUNTIME_NOT_READY") Return $$$OK
    Set sc=##class(Chronos.Agent.Decisions).Read(decisionId,.decision) If $$$ISERR(sc) Return sc
    If decision.%Get("state")'="COMPLETED" Return $$$OK
    // Terminal precontrols and HOLD have no actionable proposal or prepared
    // inference context. Refuse before touching current authority snapshots.
    If decision.%GetTypeOf("result")'="object" Return $$$OK
    If decision.result.%Get("status")'="VALIDATED_PROPOSAL" Return $$$OK
    Set sc=..GetProvider(.provider) If $$$ISERR(sc) Return sc
    Set sc=##class(Chronos.Authority.Store).Apply("READ",{"orderId":(decision.orderId),"shipmentVersion":(decision.shipmentVersion)},.prior) If $$$ISERR(sc) Return sc
    Set sc=provider.Snapshot(decision.orderId,.snapshot) If $$$ISERR(sc) Return sc
    Set sc=##class(Chronos.Authority.Store).Apply("REFRESH",{"snapshot":(snapshot),"expectedSnapshotId":(prior.effect.snapshotId)},.fresh) If $$$ISERR(sc) Return sc
    // Review after REFRESH, never reuse a validation of different observations.
    Set sc=##class(Chronos.Agent.Context).Review(decisionId,.review) If $$$ISERR(sc) Return sc
    If review.%Get("status")'="REVIEWABLE" Set result=..Denied(review.%Get("code","RECHECK_REQUIRED")) Return $$$OK
    If (review.binding.generation'=ready.generation)||(review.binding.expectedSnapshotId'=fresh.snapshotId) Return $$$ERROR($$$GeneralError,"REVIEW_CHANGED")
    Set sc=..SamePrincipal(principal,"APPROVE") If $$$ISERR(sc) Return sc
    Set request=##class(%DynamicObject).%FromJSON(review.binding.%ToJSON())
    If previewId="" Set previewId=$System.Util.CreateGUID()
    Set request.previewId=previewId,request.actor=principal.actor,request.sessionBinding=principal.sessionBinding
    Return ##class(Chronos.Authority.Store).Apply("PREVIEW",request,.result)
}
}
