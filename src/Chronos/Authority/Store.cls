Include %occStatus

/// INTERNAL TRUSTED CALLERS ONLY. Runtime evidence is linked in the checkpoint.
/// No endpoint, authentication implementation, provider verification or network I/O.
Class Chronos.Authority.Store Extends %RegisteredObject
{
/// UTC is authoritative here; callers cannot replace this clock.
/// A backwards clock blocks mutations instead of extending approvals silently.
ClassMethod Now() As %Numeric [ Private ]
{
    Set stamp=$ZTimestamp
    Set seconds=$Piece(stamp,",",2),fraction=$Extract($Piece(seconds,".",2)_"000000",1,6)
    Return ($Piece(stamp,",",1)*86400)+$Piece(seconds,".",1)+(fraction/1000000)
}

/// Sole mutation entry point. Caller must authenticate humans and verify receipts.
/// ADMIT returns dispatch permission only AFTER commit, confirmed journal sync and lock release.
/// RESERVE_BEGIN alone protects the effect but cannot authorize provider I/O.
/// A lost reply never permits replay: use READ/RECOVER and reconcile the same op.
ClassMethod Apply(pCommand As %String, pArgs As %DynamicObject, Output pResult As %DynamicObject) As %Status
{
    Set pResult={"dispatchGranted":false,"code":"NOT_APPLIED"}
    If $TLevel Return $$$ERROR($$$GeneralError,"CALL_REQUIRES_NO_OPEN_TRANSACTION")
    If ",REGISTER,REFRESH,APPROVE,RESERVE_BEGIN,ADMIT,BEGIN_PREPARATION,READ_PREPARATION,CLOSE_PREPARATION,PREVIEW,READ_PREVIEW,READ_CONFIRMED_PREVIEW,REJECT_PREVIEW,CONFIRM_RESERVE,EVIDENCE,RECOVER,READ,READ_OPERATION,RECOVERY_STATUS,RECOVERY_BEGIN,RECOVERY_BATCH,RECOVERY_ACK,"'[(","_pCommand_",") Return $$$ERROR($$$GeneralError,"UNKNOWN_COMMAND")
    Lock +^ChronosAuthority14("mutex"):5
    If '$Test Return $$$ERROR($$$GeneralError,"AUTHORITY_BUSY")
    Set sc=$$$OK,durabilityPending=0
    Try {
        Set readOnly=(pCommand="READ_PREPARATION")||(pCommand="READ")||(pCommand="READ_OPERATION")||(pCommand="RECOVERY_STATUS")||(pCommand="READ_PREVIEW")||(pCommand="READ_CONFIRMED_PREVIEW")
        If 'readOnly { Set sc=##class(Chronos.Runtime.Durability).Check() $$$ThrowOnError(sc) }
        TStart
        Set now=..Now()
        If 'readOnly,now<$Get(^ChronosAuthority14("clockHighWater"),0) {
            Set sc=$$$ERROR($$$GeneralError,"CLOCK_MOVED_BACKWARD")
        } Else {
            Set sc=..Transition(pCommand,pArgs,now,.pResult)
        }
        If $$$ISERR(sc) {
            TRollback
            Set pResult={"dispatchGranted":false,"code":"REJECTED"}
        } Else {
            If 'readOnly {
                Set ^ChronosAuthority14("clockHighWater")=now
                Set sequence=$Increment(^ChronosAuthority14("auditSequence"))
                Set audit={"command":(pCommand),"at":(now),"code":(pResult.%Get("code")),"operationId":(pResult.%Get("operationId"))}
                Set ^ChronosAuthority14("audit",sequence)=audit.%ToJSON()
            }
            TCommit
            If 'readOnly {
                Set durabilityPending=1
                Set sc=##class(Chronos.Runtime.Durability).Flush() $$$ThrowOnError(sc)
                Set durabilityPending=0
            }
        }
    } Catch ex {
        If $TLevel TRollback
        // A post-commit sync failure is uncertainty, never a claimed rollback.
        Set code=$Select(durabilityPending:"AUTHORITY_DURABILITY_UNCERTAIN",1:"AUTHORITY_ERROR")
        Set pResult={"dispatchGranted":false,"code":(code)}
        Set sc=$$$ERROR($$$GeneralError,code)
    }
    Lock -^ChronosAuthority14("mutex")
    Return sc
}

ClassMethod ID(pValue As %String) As %Boolean [ Private ]
{
    If ($Length(pValue)<1)!($Length(pValue)>128) Return 0
    Return $Translate(pValue,"abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.")=""
}

ClassMethod TextID(pObject As %DynamicObject, pField As %String) As %Boolean [ Private ]
{
    If pObject.%GetTypeOf(pField)'="string" Return 0
    Return ..ID(pObject.%Get(pField))
}

ClassMethod Shape(pObject As %DynamicObject, pFields As %String) As %Boolean [ Private ]
{
    If '$IsObject(pObject) Return 0
    If 'pObject.%IsA("%DynamicObject") Return 0
    If pObject.%Size()'=$Length(pFields,",") Return 0
    For n=1:1:$Length(pFields,",") {
        If 'pObject.%IsDefined($Piece(pFields,",",n)) Return 0
    }
    Return 1
}

ClassMethod Integer(pObject As %DynamicObject, pField As %String, pMinimum As %Integer = 0) As %Boolean [ Private ]
{
    If pObject.%GetTypeOf(pField)'="number" Return 0
    Set value=pObject.%Get(pField)
    Return (value>=pMinimum)&&(value=(value\1))
}

ClassMethod SnapshotOK(s As %DynamicObject, now As %Numeric) As %Boolean [ Private ]
{
    If '..Shape(s,"orderId,shipmentVersion,revision,policyRevision,payload,quantity,maxCost,deliveryDeadline,inventoryUntil,observedAt,offers") Return 0
    If s.%GetTypeOf("orderId")'="string" Return 0
    If '..ID(s.orderId) Return 0
    For field="shipmentVersion","revision","policyRevision","quantity" {
        If '..Integer(s,field,1) Return 0
    }
    If s.%GetTypeOf("payload")'="string" Return 0
    If (s.payload="")!($Length($ZConvert(s.payload,"O","UTF8"))>65536) Return 0
    For field="maxCost","deliveryDeadline","inventoryUntil","observedAt" {
        If s.%GetTypeOf(field)'="number" Return 0
        If s.%Get(field)<0 Return 0
    }
    If (s.observedAt>now)!((now-s.observedAt)>60) Return 0
    If '..Shape(s.offers,"A,B") Return 0
    For target="A","B" {
        Set offer=s.offers.%Get(target)
        If '..Shape(offer,"target,cost,availableAt,queueSeconds,travelSeconds,validUntil,capacity") Return 0
        If (offer.%GetTypeOf("target")'="string")!(offer.target'=target) Return 0
        For field="cost","availableAt","queueSeconds","travelSeconds","validUntil","capacity" {
            If offer.%GetTypeOf(field)'="number" Return 0
            If offer.%Get(field)<0 Return 0
        }
        If '..Integer(offer,"capacity",0) Return 0
    }
    Return 1
}

/// Recompute from current time, not a remembered trial ETA.
/// The authoritative state adapter must refresh physical observations independently.
ClassMethod Eligible(s As %DynamicObject, target As %String, now As %Numeric, acceptanceUntil As %Numeric = 0) As %Boolean [ Private ]
{
    If '..SnapshotOK(s,now) Return 0
    If (target'="A")&&(target'="B") Return 0
    Set offer=s.offers.%Get(target)
    Set admission=$Select(now>offer.availableAt:now,1:offer.availableAt)+offer.queueSeconds
    Set arrival=admission+offer.travelSeconds
    If acceptanceUntil,admission'<acceptanceUntil Return 0
    Return (now<offer.validUntil)&&(admission<offer.validUntil)&&(admission<s.inventoryUntil)&&(arrival<=s.deliveryDeadline)&&(offer.cost<=s.maxCost)&&(offer.capacity>=s.quantity)
}

ClassMethod LoadEffect(order As %String, version As %Integer, Output effect As %DynamicObject) As %Status [ Private ]
{
    Set value=$Get(^ChronosAuthority14("effect",order,version))
    If value="" Return $$$ERROR($$$GeneralError,"UNKNOWN_EFFECT")
    Set effect=##class(%DynamicObject).%FromJSON(value)
    Return $$$OK
}

ClassMethod SaveEffect(effect As %DynamicObject) [ Private ]
{
    Set ^ChronosAuthority14("effect",effect.snapshot.orderId,effect.snapshot.shipmentVersion)=effect.%ToJSON()
}

ClassMethod Transition(command As %String, a As %DynamicObject, now As %Numeric, Output result As %DynamicObject) As %Status [ Private ]
{
    Set result={"dispatchGranted":false,"code":"NO_CHANGE"}
    If '$IsObject(a) Return $$$ERROR($$$GeneralError,"ARGUMENT_OBJECT_REQUIRED")
    If 'a.%IsA("%DynamicObject") Return $$$ERROR($$$GeneralError,"ARGUMENT_OBJECT_REQUIRED")
    If ",RECOVERY_STATUS,RECOVERY_BEGIN,RECOVERY_BATCH,RECOVERY_ACK,"[(","_command_",") Return ..Recovery(command,a,.result)
    If ",REGISTER,REFRESH,APPROVE,RESERVE_BEGIN,ADMIT,BEGIN_PREPARATION,PREVIEW,CONFIRM_RESERVE,"[(","_command_",") {
        If ..RecoveryBlocked() Return $$$ERROR($$$GeneralError,"STARTUP_RECOVERY_IN_PROGRESS")
    }
    If ",BEGIN_PREPARATION,READ_PREPARATION,CLOSE_PREPARATION,"[(","_command_",") Return ..Preparation(command,a,now,.result)
    If a.%IsDefined("orderId") {
        If ('..TextID(a,"orderId"))!('..Integer(a,"shipmentVersion",1)) Return $$$ERROR($$$GeneralError,"INVALID_EFFECT_IDENTITY")
    }
    If command="REGISTER" Return ..Register(a,now,.result)
    If command="REFRESH" Return ..Refresh(a,now,.result)
    If command="APPROVE" Return ..Approve(a,now,.result)
    If command="RESERVE_BEGIN" Return ..Reserve(a,now,.result)
    If command="ADMIT" Return ..Admit(a,now,.result)
    If ",PREVIEW,READ_PREVIEW,READ_CONFIRMED_PREVIEW,REJECT_PREVIEW,CONFIRM_RESERVE,"[(","_command_",") Return ..Preview(command,a,now,.result)
    If command="EVIDENCE" Return ..Evidence(a,now,.result)
    If command="RECOVER" Return ..Recover(a,now,.result)
    If command="READ_OPERATION" {
        If '..Shape(a,"operationId") Return $$$ERROR($$$GeneralError,"BAD_OPERATION_READ")
        If '..TextID(a,"operationId") Return $$$ERROR($$$GeneralError,"BAD_OPERATION_ID")
        Set raw=$Get(^ChronosAuthority14("operation",a.operationId))
        If raw="" Return $$$ERROR($$$GeneralError,"UNKNOWN_OPERATION")
        Set op=##class(%DynamicObject).%FromJSON(raw)
        Set sc=..LoadEffect(op.orderId,op.shipmentVersion,.effect)
        If $$$ISERR(sc) Return sc
        Set result={"dispatchGranted":false,"code":"READ_ONLY","operation":(op),"effect":(effect),"recoveryBlocked":(..RecoveryBlocked())}
        Return $$$OK
    }
    If command="READ" {
        If '..Shape(a,"orderId,shipmentVersion") Return $$$ERROR($$$GeneralError,"BAD_READ")
        Set sc=..LoadEffect(a.orderId,a.shipmentVersion,.effect)
        If $$$ISERR(sc) Return sc
        Set result={"dispatchGranted":false,"code":"READ_ONLY","effect":(effect)}
        If effect.currentOperationId'="" {
            Do result.%Set("operation",##class(%DynamicObject).%FromJSON(^ChronosAuthority14("operation",effect.currentOperationId)))
        }
        Return $$$OK
    }
    Return $$$ERROR($$$GeneralError,"UNKNOWN_COMMAND")
}

ClassMethod Register(a As %DynamicObject, now As %Numeric, Output result As %DynamicObject) As %Status [ Private ]
{
    If '..Shape(a,"snapshot,originalOperationId,originalTarget,originalAttemptId") Return $$$ERROR($$$GeneralError,"BAD_REGISTER")
    Set s=a.snapshot
    If '..SnapshotOK(s,now) Return $$$ERROR($$$GeneralError,"BAD_SNAPSHOT")
    If ('..TextID(a,"originalOperationId"))!('..TextID(a,"originalAttemptId")) Return $$$ERROR($$$GeneralError,"BAD_OPERATION_ID")
    If (a.originalTarget'="A")&&(a.originalTarget'="B") Return $$$ERROR($$$GeneralError,"UNREGISTERED_TARGET")
    If $Data(^ChronosAuthority14("effect",s.orderId,s.shipmentVersion)) Return $$$ERROR($$$GeneralError,"EFFECT_EXISTS")
    If $Data(^ChronosAuthority14("operation",a.originalOperationId)) Return $$$ERROR($$$GeneralError,"OPERATION_EXISTS")
    If $Data(^ChronosAuthority14("attempt",a.originalAttemptId)) Return $$$ERROR($$$GeneralError,"ATTEMPT_EXISTS")
    Set ^ChronosAuthority14("attempt",a.originalAttemptId)=a.originalOperationId
    Set snapshotId=$Increment(^ChronosAuthority14("snapshotSequence"))
    Set effect={"snapshot":(s),"snapshotId":(snapshotId),"state":"UNKNOWN","currentOperationId":(a.originalOperationId),"quarantined":false}
    Set operation={"operationId":(a.originalOperationId),"attemptId":(a.originalAttemptId),"orderId":(s.orderId),"shipmentVersion":(s.shipmentVersion),"target":(a.originalTarget),"payload":(s.payload),"idempotencyKey":(a.originalOperationId),"revision":(s.revision),"policyRevision":(s.policyRevision),"snapshotId":(snapshotId),"state":"UNKNOWN","reference":"","approvalId":"","actor":"","observedAt":(s.observedAt)}
    Set ^ChronosAuthority14("operation",a.originalOperationId)=operation.%ToJSON()
    Do ..SaveEffect(effect)
    Set result={"dispatchGranted":false,"code":"REGISTERED_UNKNOWN","snapshotId":(snapshotId),"operationId":(a.originalOperationId)}
    Return $$$OK
}

ClassMethod Refresh(a As %DynamicObject, now As %Numeric, Output result As %DynamicObject) As %Status [ Private ]
{
    If '..Shape(a,"snapshot,expectedSnapshotId") Return $$$ERROR($$$GeneralError,"BAD_REFRESH")
    Set s=a.snapshot
    If '..SnapshotOK(s,now) Return $$$ERROR($$$GeneralError,"BAD_SNAPSHOT")
    If '..Integer(a,"expectedSnapshotId",1) Return $$$ERROR($$$GeneralError,"BAD_SNAPSHOT_ID")
    Set sc=..LoadEffect(s.orderId,s.shipmentVersion,.effect)
    If $$$ISERR(sc) Return sc
    If a.expectedSnapshotId'=effect.snapshotId Return $$$ERROR($$$GeneralError,"STALE_SNAPSHOT")
    If (effect.state="ACCEPTED")!effect.quarantined Return $$$ERROR($$$GeneralError,"EFFECT_TERMINAL")
    Set prior=effect.snapshot
    If (s.revision<prior.revision)!(s.policyRevision<prior.policyRevision) Return $$$ERROR($$$GeneralError,"REVISION_REGRESSION")
    If (s.payload'=prior.payload)&&(s.revision=prior.revision) Return $$$ERROR($$$GeneralError,"PAYLOAD_REQUIRES_NEW_REVISION")
    Set effect.snapshot=s,effect.snapshotId=$Increment(^ChronosAuthority14("snapshotSequence"))
    Do ..SaveEffect(effect)
    Set result={"dispatchGranted":false,"code":"SNAPSHOT_REFRESHED","snapshotId":(effect.snapshotId)}
    Return $$$OK
}

/// INTERNAL human-approval bridge only. actor is trusted identity, NOT authentication.
/// The bridge must show the exact expected snapshot and authenticate the approver.
ClassMethod Approve(a As %DynamicObject, now As %Numeric, Output result As %DynamicObject, reviewDeadlineUS As %Numeric = 0) As %Status [ Private ]
{
    If '..Shape(a,"orderId,shipmentVersion,expectedSnapshotId,operationId,option,actor") Return $$$ERROR($$$GeneralError,"BAD_APPROVAL")
    If ('..TextID(a,"operationId"))!('..TextID(a,"actor")) Return $$$ERROR($$$GeneralError,"BAD_IDENTITY")
    If '..Integer(a,"expectedSnapshotId",1) Return $$$ERROR($$$GeneralError,"BAD_SNAPSHOT_ID")
    If (a.option'="RETRY_A")&&(a.option'="FAILOVER_B") Return $$$ERROR($$$GeneralError,"OPTION_NOT_ALLOWED")
    Set sc=..LoadEffect(a.orderId,a.shipmentVersion,.effect)
    If $$$ISERR(sc) Return sc
    If (a.expectedSnapshotId'=effect.snapshotId)!effect.quarantined Return $$$ERROR($$$GeneralError,"STALE_OR_QUARANTINED")
    If effect.state'="OPEN" Return $$$ERROR($$$GeneralError,"PRIOR_ATTEMPT_NOT_CLOSED")
    Set target=$Select(a.option="RETRY_A":"A",1:"B"),s=effect.snapshot
    If '..Eligible(s,target,now) Return $$$ERROR($$$GeneralError,"HARD_LIMIT_OR_FRESHNESS")
    If $Data(^ChronosAuthority14("operation",a.operationId)) Return $$$ERROR($$$GeneralError,"OPERATION_EXISTS")
    Set approvalId="approval-"_$Increment(^ChronosAuthority14("approvalSequence"))
    Set expires=s.observedAt+300,offer=s.offers.%Get(target)
    If offer.validUntil<expires Set expires=offer.validUntil
    If reviewDeadlineUS {
        Set deadline=..ReviewDeadline(reviewDeadlineUS)
        If now'<deadline Return $$$ERROR($$$GeneralError,"HUMAN_REVIEW_EXPIRED")
        If deadline<expires Set expires=deadline
    }
    If '..Eligible(s,target,now,expires) Return $$$ERROR($$$GeneralError,"HUMAN_WINDOW_INFEASIBLE")
    Set approval={"approvalId":(approvalId),"orderId":(a.orderId),"shipmentVersion":(a.shipmentVersion),"operationId":(a.operationId),"snapshotId":(effect.snapshotId),"revision":(s.revision),"policyRevision":(s.policyRevision),"option":(a.option),"target":(target),"payload":(s.payload),"actor":(a.actor),"observedAt":(s.observedAt),"approvedAt":(now),"validUntil":(expires)}
    If reviewDeadlineUS Set approval.reviewDeadlineUS=reviewDeadlineUS
    Set ^ChronosAuthority14("approval",approvalId)=approval.%ToJSON()
    Set result={"dispatchGranted":false,"code":"APPROVAL_RECORDED","approval":(approval)}
    Return $$$OK
}

ClassMethod Reserve(a As %DynamicObject, now As %Numeric, Output result As %DynamicObject) As %Status [ Private ]
{
    If '..Shape(a,"approvalId,actor") Return $$$ERROR($$$GeneralError,"BAD_RESERVATION")
    If ('..TextID(a,"approvalId"))!('..TextID(a,"actor")) Return $$$ERROR($$$GeneralError,"BAD_IDENTITY")
    Set raw=$Get(^ChronosAuthority14("approval",a.approvalId))
    If raw="" Return $$$ERROR($$$GeneralError,"APPROVAL_NOT_FOUND")
    Set approval=##class(%DynamicObject).%FromJSON(raw)
    If a.actor'=approval.actor Return $$$ERROR($$$GeneralError,"ACTOR_MISMATCH")
    Set sc=..LoadEffect(approval.orderId,approval.shipmentVersion,.effect)
    If $$$ISERR(sc) Return sc
    If $Data(^ChronosAuthority14("operation",approval.operationId)) {
        Set op=##class(%DynamicObject).%FromJSON(^ChronosAuthority14("operation",approval.operationId))
        If op.approvalId'=approval.approvalId Return $$$ERROR($$$GeneralError,"IMMUTABLE_OPERATION_CONFLICT")
        Set result={"dispatchGranted":false,"code":"EXISTING_OPERATION","operationId":(op.operationId),"state":(op.state)}
        Return $$$OK
    }
    If (effect.state'="OPEN")!effect.quarantined Return $$$ERROR($$$GeneralError,"EFFECT_RESERVED_OR_TERMINAL")
    Set s=effect.snapshot
    If (approval.snapshotId'=effect.snapshotId)!(approval.revision'=s.revision)!(approval.policyRevision'=s.policyRevision)!(approval.payload'=s.payload)!(approval.observedAt'=s.observedAt) Return $$$ERROR($$$GeneralError,"APPROVAL_BINDING_CHANGED")
    If now'<approval.validUntil Return $$$ERROR($$$GeneralError,"APPROVAL_EXPIRED")
    If approval.%IsDefined("reviewDeadlineUS") {
        If '..Integer(approval,"reviewDeadlineUS",1) Return $$$ERROR($$$GeneralError,"HUMAN_REVIEW_BINDING_INVALID")
        Set deadline=..ReviewDeadline(approval.reviewDeadlineUS)
        If (now'<deadline)||(approval.validUntil>deadline) Return $$$ERROR($$$GeneralError,"HUMAN_REVIEW_EXPIRED")
    }
    If '..Eligible(s,approval.target,now,approval.validUntil) Return $$$ERROR($$$GeneralError,"HARD_LIMIT_OR_FRESHNESS")
    Set attemptId="attempt-"_$Increment(^ChronosAuthority14("attemptSequence"))
    While $Data(^ChronosAuthority14("attempt",attemptId)) {
        Set attemptId="attempt-"_$Increment(^ChronosAuthority14("attemptSequence"))
    }
    Set ^ChronosAuthority14("attempt",attemptId)=approval.operationId
    Set op={"operationId":(approval.operationId),"attemptId":(attemptId),"orderId":(approval.orderId),"shipmentVersion":(approval.shipmentVersion),"target":(approval.target),"payload":(approval.payload),"idempotencyKey":(approval.operationId),"revision":(approval.revision),"policyRevision":(approval.policyRevision),"snapshotId":(approval.snapshotId),"approvalId":(approval.approvalId),"actor":(approval.actor),"observedAt":(approval.observedAt),"dispatchAt":(now),"state":"IN_FLIGHT","reference":""}
    Do op.%Set("validUntil",approval.validUntil)
    If approval.%IsDefined("reviewDeadlineUS") Set op.reviewDeadlineUS=approval.reviewDeadlineUS
    Set ^ChronosAuthority14("approvalUse",approval.approvalId)=op.operationId
    Set effect.state="IN_FLIGHT",effect.currentOperationId=op.operationId
    // Snapshot identity covers the authority state as well as observations.
    // Winning a reservation invalidates every other approval from that state.
    Set effect.snapshotId=$Increment(^ChronosAuthority14("snapshotSequence"))
    Set op.reservationSnapshotId=effect.snapshotId
    Set ^ChronosAuthority14("operation",op.operationId)=op.%ToJSON()
    Set claim=$System.Util.CreateGUID()
    Set ^ChronosAuthority14("dispatchClaim",op.operationId)=claim
    Do ..SaveEffect(effect)
    // A lost reservation reply is uncertain; READ/replay never returns the claim.
    Set result={"dispatchGranted":false,"reservationGranted":true,"code":"IN_FLIGHT_COMMITTED","operationId":(op.operationId),"attemptId":(op.attemptId),"idempotencyKey":(op.idempotencyKey),"claimId":(claim)}
    Return $$$OK
}

/// Final local admission is serialized with quarantine/recovery gate changes.
/// Closure after this commit prevents NEW admissions; it cannot revoke this one.
ClassMethod Admit(a As %DynamicObject, now As %Numeric, Output result As %DynamicObject) As %Status [ Private ]
{
    If '..Shape(a,"operationId,attemptId,actor,claimId") Return $$$ERROR($$$GeneralError,"BAD_ADMISSION")
    For field="operationId","attemptId","actor","claimId" {
        If '..TextID(a,field) Return $$$ERROR($$$GeneralError,"BAD_ADMISSION_IDENTITY")
    }
    Set raw=$Get(^ChronosAuthority14("operation",a.operationId)),claim=$Get(^ChronosAuthority14("dispatchClaim",a.operationId))
    If (raw="")||(claim="")||(claim'=a.claimId) Return $$$ERROR($$$GeneralError,"ADMISSION_CLAIM_UNAVAILABLE")
    Set op=##class(%DynamicObject).%FromJSON(raw)
    If (op.actor'=a.actor)||(op.attemptId'=a.attemptId) Return $$$ERROR($$$GeneralError,"ADMISSION_IDENTITY_MISMATCH")
    If op.%IsDefined("admissionId") {
        Set result={"dispatchGranted":false,"code":"ADMISSION_ALREADY_CONSUMED","operationId":(op.operationId),"state":(op.state)}
        Return $$$OK
    }
    Set gateRaw=$Get(^ChronosAuthority14("recoveryGate"))
    If gateRaw="" Return $$$ERROR($$$GeneralError,"ADMISSION_GATE_UNCONFIGURED")
    If ##class(%DynamicObject).%FromJSON(gateRaw).state'="OPEN" Return $$$ERROR($$$GeneralError,"ADMISSION_GATE_CLOSED")
    Set sc=..LoadEffect(op.orderId,op.shipmentVersion,.effect)
    If $$$ISERR(sc) Return sc
    If effect.quarantined||(effect.currentOperationId'=op.operationId)||(effect.state'="IN_FLIGHT")||(op.state'="IN_FLIGHT") Return $$$ERROR($$$GeneralError,"ADMISSION_STATE_CHANGED")
    If op.%Get("reservationSnapshotId")'=effect.snapshotId Return $$$ERROR($$$GeneralError,"ADMISSION_SNAPSHOT_CHANGED")
    Set s=effect.snapshot
    If (op.revision'=s.revision)||(op.policyRevision'=s.policyRevision)||(op.payload'=s.payload)||(op.observedAt'=s.observedAt) Return $$$ERROR($$$GeneralError,"ADMISSION_BINDING_CHANGED")
    If (now'<op.validUntil)||('..Eligible(s,op.target,now,op.validUntil)) Return $$$ERROR($$$GeneralError,"ADMISSION_EXPIRED_OR_INELIGIBLE")
    If op.%IsDefined("reviewDeadlineUS") {
        If '..Integer(op,"reviewDeadlineUS",1) Return $$$ERROR($$$GeneralError,"HUMAN_REVIEW_BINDING_INVALID")
        Set deadline=..ReviewDeadline(op.reviewDeadlineUS)
        If (now'<deadline)||(op.validUntil>deadline) Return $$$ERROR($$$GeneralError,"HUMAN_REVIEW_EXPIRED")
    }
    Set op.admissionId="admission-"_$Increment(^ChronosAuthority14("admissionSequence")),op.admittedAt=now
    Set ^ChronosAuthority14("operation",op.operationId)=op.%ToJSON()
    Set ticket={"dispatchGranted":true,"code":"DISPATCH_ADMITTED","operationId":(op.operationId),"attemptId":(op.attemptId),"target":(op.target),"payload":(op.payload),"idempotencyKey":(op.idempotencyKey),"validUntil":(op.validUntil),"dispatchAt":(op.dispatchAt),"admissionId":(op.admissionId),"admittedAt":(op.admittedAt)}
    If op.%IsDefined("reviewDeadlineUS") Set ticket.reviewDeadlineUS=op.reviewDeadlineUS
    Set result={"dispatchGranted":true,"code":"DISPATCH_ADMITTED","operationId":(op.operationId),"operation":(op),"ticket":(ticket)}
    Return $$$OK
}

/// Correlation receipts for an explicitly requested preview. Internal callers
/// derive actor/session/generation; requestId is a public identifier, not a grant.
/// Creation is allowed once. Reading absence never proves a request cannot arrive.
ClassMethod Preparation(command As %String, a As %DynamicObject, now As %Numeric, Output result As %DynamicObject) As %Status [ Private ]
{
    Set fields=$Select(command="BEGIN_PREPARATION":"actor,sessionBinding,generation,requestId,decisionId",command="CLOSE_PREPARATION":"actor,requestId,decisionId",1:"actor,requestId")
    If '..Shape(a,fields) Return $$$ERROR($$$GeneralError,"INVALID_PREPARATION_REQUEST")
    For field="actor","requestId" {
        If '..TextID(a,field) Return $$$ERROR($$$GeneralError,"INVALID_PREPARATION_IDENTITY")
    }
    If command'="READ_PREPARATION",'..TextID(a,"decisionId") Return $$$ERROR($$$GeneralError,"INVALID_PREPARATION_DECISION")
    If command="BEGIN_PREPARATION" {
        For field="sessionBinding","generation" {
            If '..TextID(a,field) Return $$$ERROR($$$GeneralError,"INVALID_PREPARATION_BINDING")
        }
    }
    Set raw=$Get(^ChronosAuthority14("preparation",a.actor,a.requestId))
    If raw'="" {
        Set receipt=##class(%DynamicObject).%FromJSON(raw)
        Set sc=..PreparationValid(receipt,a.actor,a.requestId) If $$$ISERR(sc) Return sc
        If command'="READ_PREPARATION",receipt.decisionId'=a.decisionId Return $$$ERROR($$$GeneralError,"PREPARATION_ID_CONFLICT")
        If (command="CLOSE_PREPARATION")&&(receipt.state="STARTED") {
            // This fence and PREVIEW's receipt check share the authority mutex.
            // A delayed producer cannot create the reserved preview after close.
            Set receipt.state="CLOSED_NO_PREVIEW",receipt.finishedAt=now
            Set ^ChronosAuthority14("preparation",a.actor,a.requestId)=receipt.%ToJSON()
        }
        Set result=..PreparationView(receipt)
        Return $$$OK
    }
    If command="READ_PREPARATION" {
        Set result={"code":"PREPARATION_NOT_FOUND","dispatchGranted":false,"preparationGranted":false,"requestId":(a.requestId),"actor":(a.actor),"decisionId":"","previewId":"","state":"NOT_FOUND"}
        Return $$$OK
    }
    Set receipt={"requestId":(a.requestId),"actor":(a.actor),"decisionId":(a.decisionId),"sessionBinding":"","generation":"","previewId":"","state":"CLOSED_NO_PREVIEW","createdAt":(now),"finishedAt":(now)}
    If command="BEGIN_PREPARATION" {
        Set previewId="prep-"_$System.Util.CreateGUID()
        If '$Data(^ChronosAuthority14("preview",previewId)),'$Data(^ChronosAuthority14("preparationPreview",previewId)) {
            Set receipt.previewId=previewId,receipt.sessionBinding=a.sessionBinding,receipt.generation=a.generation
            Set receipt.state="STARTED",receipt.finishedAt=0
            Set ^ChronosAuthority14("preparationPreview",previewId)=$ListBuild(a.actor,a.requestId)
        } Else {
            Return $$$ERROR($$$GeneralError,"PREPARATION_PREVIEW_CONFLICT")
        }
    }
    // CLOSE on an absent ID is a durable tombstone. A delayed BEGIN with that
    // actor/ID can only read it; it must not allocate a different preview.
    Set ^ChronosAuthority14("preparation",a.actor,a.requestId)=receipt.%ToJSON()
    Set result=..PreparationView(receipt)
    If command="BEGIN_PREPARATION" Do result.%Set("preparationGranted",1,"boolean")
    Return $$$OK
}

ClassMethod PreparationValid(r As %DynamicObject, actor As %String, requestId As %String) As %Status [ Private ]
{
    If '..Shape(r,"requestId,actor,decisionId,sessionBinding,generation,previewId,state,createdAt,finishedAt") Return $$$ERROR($$$GeneralError,"PREPARATION_CORRUPT")
    For field="requestId","actor","decisionId" {
        If '..TextID(r,field) Return $$$ERROR($$$GeneralError,"PREPARATION_CORRUPT")
    }
    If (r.actor'=actor)||(r.requestId'=requestId) Return $$$ERROR($$$GeneralError,"PREPARATION_CORRUPT")
    If (r.%GetTypeOf("createdAt")'="number")||(r.%GetTypeOf("finishedAt")'="number") Return $$$ERROR($$$GeneralError,"PREPARATION_CORRUPT")
    If (r.createdAt<0)||(r.finishedAt<0) Return $$$ERROR($$$GeneralError,"PREPARATION_CORRUPT")
    If '$ListFind($ListBuild("STARTED","RECORDED","CLOSED_NO_PREVIEW"),r.%Get("state")) Return $$$ERROR($$$GeneralError,"PREPARATION_CORRUPT")
    For field="previewId","sessionBinding","generation" {
        If r.%GetTypeOf(field)'="string" Return $$$ERROR($$$GeneralError,"PREPARATION_CORRUPT")
    }
    If r.previewId="" {
        If (r.state'="CLOSED_NO_PREVIEW")||(r.sessionBinding'="")||(r.generation'="") Return $$$ERROR($$$GeneralError,"PREPARATION_CORRUPT")
    } Else {
        For field="previewId","sessionBinding","generation" {
            If '..TextID(r,field) Return $$$ERROR($$$GeneralError,"PREPARATION_CORRUPT")
        }
        If $Get(^ChronosAuthority14("preparationPreview",r.previewId))'=$ListBuild(actor,requestId) Return $$$ERROR($$$GeneralError,"PREPARATION_CORRUPT")
        Set preview=$Get(^ChronosAuthority14("preview",r.previewId))
        If r.state="RECORDED" {
            If preview="" Return $$$ERROR($$$GeneralError,"PREPARATION_CORRUPT")
            Set p=##class(%DynamicObject).%FromJSON(preview)
            For field="previewId","actor","decisionId","sessionBinding","generation" {
                If (p.%GetTypeOf(field)'="string")||(p.%Get(field)'=r.%Get(field)) Return $$$ERROR($$$GeneralError,"PREPARATION_CORRUPT")
            }
        } Else {
            If preview'="" Return $$$ERROR($$$GeneralError,"PREPARATION_CORRUPT")
        }
    }
    If (r.state="STARTED")&&(r.finishedAt'=0) Return $$$ERROR($$$GeneralError,"PREPARATION_CORRUPT")
    If (r.state'="STARTED")&&(r.finishedAt<r.createdAt) Return $$$ERROR($$$GeneralError,"PREPARATION_CORRUPT")
    Return $$$OK
}

ClassMethod PreparationView(r As %DynamicObject) As %DynamicObject [ Private ]
{
    // No original session binding, grant, payload or diagnostic reaches the view.
    Return {"code":("PREPARATION_"_r.state),"dispatchGranted":false,"preparationGranted":false,"requestId":(r.requestId),"actor":(r.actor),"decisionId":(r.decisionId),"previewId":(r.previewId),"state":(r.state)}
}

/// Trusted approval service only. The caller derives actor/session/generation
/// from authenticated runtime context and verifies the stored decision first.
/// No raw session cookie or authentication/CSRF token may be passed or stored.
ClassMethod Preview(command As %String, a As %DynamicObject, now As %Numeric, Output result As %DynamicObject) As %Status [ Private ]
{
    Set fields=$Select(command="PREVIEW":"previewId,orderId,shipmentVersion,expectedSnapshotId,decisionId,decisionDigest,option,actor,sessionBinding,generation,reviewDeadlineUS",command="CONFIRM_RESERVE":"previewId,actor,sessionBinding,generation",command="READ_CONFIRMED_PREVIEW":"previewId,actor",1:"previewId,actor,sessionBinding")
    If '..Shape(a,fields) Return $$$ERROR($$$GeneralError,"INVALID_PREVIEW_REQUEST")
    For field="previewId","actor" {
        If '..TextID(a,field) Return $$$ERROR($$$GeneralError,"INVALID_PREVIEW_IDENTITY")
    }
    If command'="READ_CONFIRMED_PREVIEW",'..TextID(a,"sessionBinding") Return $$$ERROR($$$GeneralError,"INVALID_PREVIEW_IDENTITY")
    If (command="PREVIEW")||(command="CONFIRM_RESERVE") {
        If '..TextID(a,"generation") Return $$$ERROR($$$GeneralError,"INVALID_PREVIEW_GENERATION")
    }
    Set preparation=""
    If command="PREVIEW" {
        Set pointer=$Get(^ChronosAuthority14("preparationPreview",a.previewId))
        If ($Extract(a.previewId,1,5)="prep-")&&(pointer="") Return $$$ERROR($$$GeneralError,"PREPARATION_CORRUPT")
        If pointer'="" {
            If $ListLength(pointer)'=2 Return $$$ERROR($$$GeneralError,"PREPARATION_CORRUPT")
            Set preparationActor=$ListGet(pointer,1),preparationId=$ListGet(pointer,2)
            Set preparationRaw=$Get(^ChronosAuthority14("preparation",preparationActor,preparationId))
            If preparationRaw="" Return $$$ERROR($$$GeneralError,"PREPARATION_CORRUPT")
            Set preparation=##class(%DynamicObject).%FromJSON(preparationRaw)
            Set sc=..PreparationValid(preparation,preparationActor,preparationId) If $$$ISERR(sc) Return sc
            For field="previewId","actor","decisionId","sessionBinding","generation" {
                If (a.%GetTypeOf(field)'="string")||(a.%Get(field)'=preparation.%Get(field)) Return $$$ERROR($$$GeneralError,"PREPARATION_BINDING_CHANGED")
            }
            If preparation.state="CLOSED_NO_PREVIEW" Return $$$ERROR($$$GeneralError,"PREPARATION_CLOSED")
        }
    }
    Set raw=$Get(^ChronosAuthority14("preview",a.previewId))
    If raw'="" {
        Set p=##class(%DynamicObject).%FromJSON(raw)
        If p.actor'=a.actor Return $$$ERROR($$$GeneralError,"PREVIEW_NOT_AVAILABLE")
        If command="READ_CONFIRMED_PREVIEW" {
            // Same authenticated owner may query committed history after login
            // or runtime renewal. This can never authorize/confirm any action.
            If p.state'="CONFIRMED" Return $$$ERROR($$$GeneralError,"PREVIEW_NOT_AVAILABLE")
        } Else {
            If p.sessionBinding'=a.sessionBinding Return $$$ERROR($$$GeneralError,"PREVIEW_NOT_AVAILABLE")
        }
    }
    If command="PREVIEW" {
        For field="decisionId","decisionDigest" {
            If '..TextID(a,field) Return $$$ERROR($$$GeneralError,"INVALID_DECISION_BINDING")
        }
        If '..Integer(a,"expectedSnapshotId",1) Return $$$ERROR($$$GeneralError,"INVALID_PREVIEW_SNAPSHOT")
        If '..Integer(a,"reviewDeadlineUS",1) Return $$$ERROR($$$GeneralError,"INVALID_REVIEW_DEADLINE")
        If (a.option'="RETRY_A")&&(a.option'="FAILOVER_B") Return $$$ERROR($$$GeneralError,"HOLD_CANNOT_AUTHORIZE")
        If raw'="" {
            If (p.orderId'=a.orderId)||(p.shipmentVersion'=a.shipmentVersion)||(p.snapshotId'=a.expectedSnapshotId)||(p.decisionId'=a.decisionId)||(p.decisionDigest'=a.decisionDigest)||(p.option'=a.option)||(p.generation'=a.generation)||(p.%Get("reviewDeadlineUS")'=a.reviewDeadlineUS) Return $$$ERROR($$$GeneralError,"PREVIEW_ID_CONFLICT")
            Set result=..PreviewView(p,"EXISTING_PREVIEW")
            Return $$$OK
        }
        Set deadline=..ReviewDeadline(a.reviewDeadlineUS)
        If (now'<deadline)||(deadline>(now+300)) Return $$$ERROR($$$GeneralError,"INVALID_REVIEW_WINDOW")
        Set sc=..LoadEffect(a.orderId,a.shipmentVersion,.effect)
        If $$$ISERR(sc) Return sc
        If (effect.snapshotId'=a.expectedSnapshotId)||(effect.state'="OPEN")||effect.quarantined Return $$$ERROR($$$GeneralError,"PREVIEW_STATE_CHANGED")
        Set target=$Select(a.option="RETRY_A":"A",1:"B"),s=effect.snapshot
        If '..Eligible(s,target,now,deadline) Return $$$ERROR($$$GeneralError,"PREVIEW_INELIGIBLE")
        Set operationId="preview-op-"_a.previewId
        If '..ID(operationId) Return $$$ERROR($$$GeneralError,"PREVIEW_ID_TOO_LONG")
        If $Data(^ChronosAuthority14("operation",operationId)) Return $$$ERROR($$$GeneralError,"PREVIEW_OPERATION_CONFLICT")
        Set expires=now+60,offer=s.offers.%Get(target)
        If s.observedAt+60<expires Set expires=s.observedAt+60
        If offer.validUntil<expires Set expires=offer.validUntil
        If deadline<expires Set expires=deadline
        Set arrival=$Select(now>offer.availableAt:now,1:offer.availableAt)+offer.queueSeconds+offer.travelSeconds
        Set p={"previewId":(a.previewId),"orderId":(a.orderId),"shipmentVersion":(a.shipmentVersion),"snapshotId":(effect.snapshotId),"decisionId":(a.decisionId),"decisionDigest":(a.decisionDigest),"option":(a.option),"target":(target),"actor":(a.actor),"sessionBinding":(a.sessionBinding),"generation":(a.generation),"operationId":(operationId),"createdAt":(now),"expiresAt":(expires),"state":"PENDING","snapshot":(s),"predictedArrival":(arrival)}
        Set p.reviewDeadlineUS=a.reviewDeadlineUS
        Set ^ChronosAuthority14("preview",a.previewId)=p.%ToJSON()
        If $IsObject(preparation) {
            Set preparation.state="RECORDED",preparation.finishedAt=now
            Set ^ChronosAuthority14("preparation",preparation.actor,preparation.requestId)=preparation.%ToJSON()
        }
        Set result=..PreviewView(p,"PREVIEW_RECORDED")
        Return $$$OK
    }
    If raw="" Return $$$ERROR($$$GeneralError,"PREVIEW_NOT_AVAILABLE")
    If (command="READ_PREVIEW")||(command="READ_CONFIRMED_PREVIEW") {
        Set result=..PreviewView(p,"READ_ONLY")
        Return $$$OK
    }
    If command="REJECT_PREVIEW" {
        If p.state="CONFIRMED" Return $$$ERROR($$$GeneralError,"CONFIRMED_OPERATION_CANNOT_BE_REJECTED")
        If p.state="PENDING" {
            Set p.state="REJECTED",p.rejectedAt=now
            Set ^ChronosAuthority14("preview",p.previewId)=p.%ToJSON()
        }
        Set result=..PreviewView(p,"PREVIEW_REJECTED")
        Return $$$OK
    }
    If p.state="CONFIRMED" {
        // Lost response/double click reveals state, never a claim or new grant.
        Set result=..PreviewView(p,"PREVIEW_ALREADY_CONFIRMED")
        Return $$$OK
    }
    If p.state'="PENDING" Return $$$ERROR($$$GeneralError,"PREVIEW_NOT_PENDING")
    // Old records without this binding cannot acquire a new dispatch grant.
    If '..Integer(p,"reviewDeadlineUS",1) Return $$$ERROR($$$GeneralError,"HUMAN_REVIEW_BINDING_INVALID")
    If (a.generation'=p.generation)||(now<p.createdAt)||(now'<p.expiresAt) Return $$$ERROR($$$GeneralError,"PREVIEW_STALE_OR_EXPIRED")
    If now'<..ReviewDeadline(p.reviewDeadlineUS) Return $$$ERROR($$$GeneralError,"HUMAN_REVIEW_EXPIRED")
    Set consent={"orderId":(p.orderId),"shipmentVersion":(p.shipmentVersion),"expectedSnapshotId":(p.snapshotId),"operationId":(p.operationId),"option":(p.option),"actor":(p.actor)}
    Set sc=..Approve(consent,now,.approval,p.reviewDeadlineUS)
    If $$$ISERR(sc) Return sc
    Set sc=..Reserve({"approvalId":(approval.approval.approvalId),"actor":(p.actor)},now,.reserved)
    If $$$ISERR(sc) Return sc
    If 'reserved.%Get("reservationGranted") Return $$$ERROR($$$GeneralError,"PREVIEW_RESERVATION_CONFLICT")
    Set p.state="CONFIRMED",p.confirmedAt=now,p.approvalId=approval.approval.approvalId
    Set ^ChronosAuthority14("preview",p.previewId)=p.%ToJSON()
    Set result=reserved,result.code="PREVIEW_CONFIRMED_RESERVED",result.preview=..PreviewView(p,"PREVIEW_CONFIRMED")
    Return $$$OK
}

ClassMethod PreviewView(p As %DynamicObject, code As %String) As %DynamicObject [ Private ]
{
    // Explicit public fields; session binding and grant material remain private.
    Return {"dispatchGranted":false,"code":(code),"previewId":(p.previewId),"orderId":(p.orderId),"shipmentVersion":(p.shipmentVersion),"snapshotId":(p.snapshotId),"decisionId":(p.decisionId),"decisionDigest":(p.decisionDigest),"option":(p.option),"target":(p.target),"actor":(p.actor),"generation":(p.generation),"operationId":(p.operationId),"createdAt":(p.createdAt),"expiresAt":(p.expiresAt),"reviewDeadlineUS":(p.%Get("reviewDeadlineUS",0)),"state":(p.state),"snapshot":(p.snapshot),"predictedArrival":(p.predictedArrival)}
}

/// Exact decimal conversion. UTC seconds since 1840, not local time or a float.
ClassMethod ReviewDeadline(microseconds As %Numeric) As %Numeric [ Private ]
{
    Return (microseconds/1000000)+($ZDateH("1970-01-01",3)*86400)
}

/// TRUST BOUNDARY: receipt must come from an authenticated authoritative adapter.
/// A bool or a JSON status from an LLM/browser is NEVER verification.
/// Finality proof enforcement at the remote destination remains an integration gate.
ClassMethod Evidence(a As %DynamicObject, now As %Numeric, Output result As %DynamicObject) As %Status [ Private ]
{
    If '..Shape(a,"operationId,attemptId,orderId,shipmentVersion,target,status,reference,receiptId,closedForever") Return $$$ERROR($$$GeneralError,"BAD_RECEIPT")
    If ('..TextID(a,"receiptId"))!('..TextID(a,"operationId"))!('..TextID(a,"attemptId")) Return $$$ERROR($$$GeneralError,"BAD_RECEIPT_ID")
    If (a.status'="ACCEPTED")&&(a.status'="NOT_ACCEPTED_FINAL")&&(a.status'="UNKNOWN") Return $$$ERROR($$$GeneralError,"UNSUPPORTED_EVIDENCE")
    If (a.%GetTypeOf("reference")'="string")!($Length(a.reference)>256) Return $$$ERROR($$$GeneralError,"INVALID_REFERENCE")
    If a.%GetTypeOf("closedForever")'="boolean" Return $$$ERROR($$$GeneralError,"FINALITY_TYPE")
    If (a.status="NOT_ACCEPTED_FINAL"),'a.closedForever Return $$$ERROR($$$GeneralError,"FINALITY_REQUIRED")
    If (a.status="ACCEPTED"),((a.%GetTypeOf("reference")'="string")!(a.reference="")) Return $$$ERROR($$$GeneralError,"ACCEPTANCE_REFERENCE_REQUIRED")
    Set raw=$Get(^ChronosAuthority14("operation",a.operationId))
    If raw="" Return $$$ERROR($$$GeneralError,"UNKNOWN_OPERATION")
    Set op=##class(%DynamicObject).%FromJSON(raw)
    If (a.orderId'=op.orderId)!(a.shipmentVersion'=op.shipmentVersion)!(a.target'=op.target)!(a.attemptId'=op.attemptId) Return $$$ERROR($$$GeneralError,"EVIDENCE_IDENTITY_MISMATCH")
    Set sc=..LoadEffect(op.orderId,op.shipmentVersion,.effect)
    If $$$ISERR(sc) Return sc
    Set priorReceipt=$Get(^ChronosAuthority14("receipt",a.receiptId))
    If priorReceipt'="" {
        If priorReceipt'=a.%ToJSON() Return $$$ERROR($$$GeneralError,"RECEIPT_ID_REUSED")
        Set result={"dispatchGranted":false,"code":"RECEIPT_ALREADY_APPLIED","operationId":(op.operationId)}
        Return $$$OK
    }
    Set ^ChronosAuthority14("receipt",a.receiptId)=a.%ToJSON()
    If (op.state="ACCEPTED")||(op.state="NOT_ACCEPTED_FINAL") {
        If (a.status="UNKNOWN")||(a.status=op.state) {
            If (op.state="ACCEPTED"),(a.status="ACCEPTED"),(a.reference'=op.reference) {
                Set effect.quarantined=1,effect.snapshotId=$Increment(^ChronosAuthority14("snapshotSequence"))
                Do ..SaveEffect(effect)
                Set result={"dispatchGranted":false,"code":"TERMINAL_REFERENCE_CONTRADICTION","operationId":(op.operationId)}
            } Else {
                Set result={"dispatchGranted":false,"code":"TERMINAL_PRESERVED","operationId":(op.operationId)}
            }
            Return $$$OK
        }
        Set effect.quarantined=1,effect.snapshotId=$Increment(^ChronosAuthority14("snapshotSequence"))
        Do ..SaveEffect(effect)
        Set result={"dispatchGranted":false,"code":"TERMINAL_CONTRADICTION","operationId":(op.operationId)}
        Return $$$OK
    }
    If op.operationId'=effect.currentOperationId Return $$$ERROR($$$GeneralError,"NONCURRENT_OPERATION")
    Set op.state=a.status,op.reference=a.reference,op.lastReceiptId=a.receiptId,op.evidenceAt=now
    Set ^ChronosAuthority14("operation",op.operationId)=op.%ToJSON()
    Set effect.state=$Select(a.status="NOT_ACCEPTED_FINAL":"OPEN",1:a.status)
    Set effect.snapshotId=$Increment(^ChronosAuthority14("snapshotSequence"))
    Do ..SaveEffect(effect)
    Set result={"dispatchGranted":false,"code":"EVIDENCE_RECORDED","operationId":(op.operationId),"state":(op.state),"snapshotId":(effect.snapshotId)}
    Return $$$OK
}

/// Invoke at startup for every persisted IN_FLIGHT operation, and after uncertain I/O.
/// No lease expiry, approval expiry or restart frees the effect.
ClassMethod Recover(a As %DynamicObject, now As %Numeric, Output result As %DynamicObject) As %Status [ Private ]
{
    If '..Shape(a,"operationId") Return $$$ERROR($$$GeneralError,"BAD_RECOVERY")
    If '..TextID(a,"operationId") Return $$$ERROR($$$GeneralError,"BAD_OPERATION_ID")
    Set raw=$Get(^ChronosAuthority14("operation",a.operationId))
    If raw="" Return $$$ERROR($$$GeneralError,"UNKNOWN_OPERATION")
    Set op=##class(%DynamicObject).%FromJSON(raw)
    Set sc=..LoadEffect(op.orderId,op.shipmentVersion,.effect)
    If $$$ISERR(sc) Return sc
    If op.state="IN_FLIGHT" {
        Set op.state="UNKNOWN",op.recoveredAt=now
        Set ^ChronosAuthority14("operation",op.operationId)=op.%ToJSON()
        If effect.currentOperationId=op.operationId Set effect.state="UNKNOWN",effect.snapshotId=$Increment(^ChronosAuthority14("snapshotSequence"))
        Do ..SaveEffect(effect)
    }
    Set result={"dispatchGranted":false,"code":"RECONCILE_SAME_OPERATION","operationId":(op.operationId),"state":(op.state),"target":(op.target),"idempotencyKey":(op.idempotencyKey)}
    Return $$$OK
}

ClassMethod RecoveryBlocked() As %Boolean [ Private ]
{
    Set raw=$Get(^ChronosAuthority14("recoveryGate"))
    If raw="" Return 0
    Return ##class(%DynamicObject).%FromJSON(raw).state'="OPEN"
}

/// Internal boot controller only. A missing gate is legacy/unconfigured, not ready.
/// Cursor commits only after ACK; a crash repeats query work, never dispatch work.
ClassMethod Recovery(command As %String, a As %DynamicObject, Output result As %DynamicObject) As %Status [ Private ]
{
    Set raw=$Get(^ChronosAuthority14("recoveryGate"))
    Set gate=$Select(raw="":"",1:raw)
    If raw'="" Set gate=##class(%DynamicObject).%FromJSON(raw)
    If command="RECOVERY_STATUS" {
        If a.%Size()'=0 Return $$$ERROR($$$GeneralError,"BAD_RECOVERY_STATUS")
        If raw="" Set gate={"state":"UNCONFIGURED","runId":""}
        Set result={"dispatchGranted":false,"code":"RECOVERY_STATUS","gate":(gate)}
        Return $$$OK
    }
    If '..TextID(a,"runId") Return $$$ERROR($$$GeneralError,"INVALID_RECOVERY_RUN")
    If command="RECOVERY_BEGIN" {
        If '..Shape(a,"runId") Return $$$ERROR($$$GeneralError,"BAD_RECOVERY_BEGIN")
        If raw'="",gate.state="RUNNING" {
            If gate.runId'=a.runId Return $$$ERROR($$$GeneralError,"RECOVERY_ALREADY_RUNNING")
        } Else {
            Set gate={"state":"RUNNING","runId":(a.runId),"cursor":"","hasBatch":false,"batchId":"","items":[],"nextCursor":"","atEnd":false}
        }
    } Else {
        If raw="" Return $$$ERROR($$$GeneralError,"RECOVERY_NOT_STARTED")
        If (gate.state'="RUNNING")||(gate.runId'=a.runId) Return $$$ERROR($$$GeneralError,"RECOVERY_RUN_MISMATCH")
        If command="RECOVERY_BATCH" {
            If '..Shape(a,"runId,limit") Return $$$ERROR($$$GeneralError,"BAD_RECOVERY_BATCH")
            If '..Integer(a,"limit",1) Return $$$ERROR($$$GeneralError,"BAD_BATCH_LIMIT")
            If a.limit>100 Return $$$ERROR($$$GeneralError,"BAD_BATCH_LIMIT")
            If 'gate.hasBatch {
                Set cursor=gate.cursor,count=0,items=[]
                While count<a.limit {
                    Set key=$Order(^ChronosAuthority14("operation",cursor))
                    If key="" Quit
                    Set cursor=key,count=count+1
                    Set op=##class(%DynamicObject).%FromJSON(^ChronosAuthority14("operation",key))
                    If (op.state="IN_FLIGHT")||(op.state="UNKNOWN") Do items.%Push(key)
                }
                Set gate.nextCursor=cursor,gate.items=items,gate.batchId="recovery-batch-"_$Increment(^ChronosAuthority14("recoveryBatchSequence"))
                Do gate.%Set("hasBatch",1,"boolean")
                Do gate.%Set("atEnd",($Order(^ChronosAuthority14("operation",cursor))=""),"boolean")
            }
        } ElseIf command="RECOVERY_ACK" {
            If '..Shape(a,"runId,batchId") Return $$$ERROR($$$GeneralError,"BAD_RECOVERY_ACK")
            If '..TextID(a,"batchId") Return $$$ERROR($$$GeneralError,"BAD_BATCH_ID")
            If ('gate.hasBatch)||(a.batchId'=gate.batchId) Return $$$ERROR($$$GeneralError,"STALE_RECOVERY_ACK")
            For n=0:1:gate.items.%Size()-1 {
                Set op=##class(%DynamicObject).%FromJSON(^ChronosAuthority14("operation",gate.items.%Get(n)))
                If op.state="IN_FLIGHT" Return $$$ERROR($$$GeneralError,"BATCH_STILL_IN_FLIGHT")
            }
            Set gate.cursor=gate.nextCursor
            Do gate.%Set("hasBatch",0,"boolean")
            If gate.atEnd Set gate.state="OPEN"
        }
    }
    Set ^ChronosAuthority14("recoveryGate")=gate.%ToJSON()
    Set result={"dispatchGranted":false,"code":(command),"gate":(gate)}
    Return $$$OK
}
}
