Include %occStatus

/// Opt-in original-CSP handoff/status composition. No route is installed here.
/// A queue acknowledgement is NOT creation, completion, adoption or permission
/// to send. Store.Claim in the separate BP supplies the durable one-task fence.
Class Chronos.Workflow.Entry Extends %RegisteredObject
{
ClassMethod View(code As %String, decisionId As %String) As %DynamicObject [ Private ]
{
    Return {"code":(code),"decisionId":(decisionId),"clarificationId":"","state":"UNAVAILABLE","expiresUS":null,"taskReady":false,"completionRecorded":false,"newDecisionId":"","canUseClarification":false,"dispatch_authorized":false}
}

/// Historical correlation, not a permission or a claim that inference finished.
/// Reopening the original HOLD can recover the exact registered new ID without
/// resubmitting an uncertain model request or retaining human notes in storage.
ClassMethod RecordedDecision(record As %DynamicObject) As %String [ Private ]
{
    Try {
        Set raw=$Get(^ChronosDecision16("clarificationAdoption",record.clarificationId))
        If raw="" Return ""
        Set anchor=##class(%DynamicObject).%FromJSON(raw)
        If (anchor.%Size()'=10)||(anchor.%Get("schema")'="chronos.clarification-registration.v1")||(anchor.%Get("clarificationId")'=record.clarificationId) Return ""
        Set id=anchor.%Get("requestId")
        If '##class(Chronos.Workflow.Store).ID(id)||(id=record.decisionId) Return ""
        Set sc=##class(Chronos.Agent.Ledger).Apply("INSPECT",{"requestId":(id)},.read) $$$ThrowOnError(sc)
        If read.%GetTypeOf("private")'="object" Return ""
        Set d=read.private
        If (d.%Get("requestId")'=id)||(d.%Get("orderId")'=record.orderId)||(d.%Get("shipmentVersion")'=record.shipmentVersion)||(d.%Get("generation")'=record.generation) Return ""
        If (d.%GetTypeOf("clarificationAnchor")'="object")||(d.clarificationAnchor.%ToJSON()'=raw) Return ""
        If (d.%GetTypeOf("prepared")'="object")||(d.prepared.%GetTypeOf("record")'="object") Return ""
        If d.prepared.record.%GetTypeOf("clarification_binding")'="object" Return ""
        Set reference=d.prepared.record.%Get("clarification_binding")
        If reference.%GetTypeOf("binding")'="object" Return ""
        If (reference.binding.%Get("source_decision_id")'=record.decisionId)||(reference.binding.%Get("clarification_id")'=record.clarificationId) Return ""
        If $Get(^ChronosDecision16("clarificationAdoption",record.clarificationId))'=raw Return ""
        Return id
    } Catch ex { Return "" }
}

/// Private lookup only. Retain the index mutex across Store.Inspect's nested
/// read, but release it before any native Task query or production call.
ClassMethod Lookup(decisionId As %String, Output inspection As %DynamicObject, Output exists As %Boolean) As %Status [ Private ]
{
    Set inspection={},exists=0
    Lock +^ChronosDecision16("mutex"):2 If '$Test Return $$$ERROR($$$GeneralError,"WORKFLOW_BUSY")
    Set sc=$$$OK
    Try {
        Set id=$Get(^ChronosDecision16("clarification","byDecision",decisionId))
        If id'="" {
            If '##class(Chronos.Workflow.Store).ID(id) Throw ##class(%Exception.General).%New("INVALID_HANDOFF_INDEX")
            Set sc=##class(Chronos.Workflow.Store).Inspect(id,.inspection) $$$ThrowOnError(sc)
            If (inspection.%Get("code")'="WORKFLOW_RECORDED")||(inspection.%GetTypeOf("record")'="object") Throw ##class(%Exception.General).%New("HANDOFF_RECORD_UNAVAILABLE")
            If (inspection.record.%Get("decisionId")'=decisionId)||(inspection.record.%Get("clarificationId")'=id) Throw ##class(%Exception.General).%New("HANDOFF_INDEX_CHANGED")
            Set exists=1
        }
    } Catch ex { Set inspection={},exists=0,sc=$$$ERROR($$$GeneralError,"WORKFLOW_LOOKUP_UNAVAILABLE") }
    Lock -^ChronosDecision16("mutex")
    Return sc
}

/// Explicit allowlist. taskReady means that the fixed native request query
/// confirmed a task ID; false also covers unavailable read access. It never
/// derives actor proof or clarification authority from native IsComplete.
ClassMethod PublicStatus(decisionId As %String, inspection As %DynamicObject) As %DynamicObject [ Private ]
{
    Set out=..View("WORKFLOW_STATUS_UNAVAILABLE",decisionId)
    Try {
        If '$IsObject(inspection)||'inspection.%IsA("%DynamicObject") Return out
        If (inspection.%Get("code")'="WORKFLOW_RECORDED")||(inspection.%GetTypeOf("record")'="object") Return out
        Set record=inspection.record
        If (record.%GetTypeOf("clarificationId")'="string")||'##class(Chronos.Workflow.Store).ID(record.clarificationId) Return out
        If record.%Get("decisionId")'=decisionId Return out
        If '$ListFind($ListBuild("SEND_FENCED","SENT","CREATION_UNCERTAIN","RESPONSE_UNVERIFIED","EXPIRED"),record.%Get("state")) Return out
        If (record.%GetTypeOf("expiresUS")'="number")||(record.expiresUS<0)||(record.expiresUS'=(record.expiresUS\1)) Return out
        For field="taskRequestId","taskId" {
            If record.%GetTypeOf(field)'="string" Return out
            Set nativeId=record.%Get(field)
            If nativeId'="",(($Length(nativeId)>18)||($Translate(nativeId,"0123456789")'="")||(nativeId<1)) Return out
        }
        Set out.code="WORKFLOW_STATUS_RECORDED",out.clarificationId=record.clarificationId,out.state=record.state,out.expiresUS=record.expiresUS
        // Use only the Store view, never the raw resolution, as an authority
        // signal. Its current conservative value is false even after completion.
        If inspection.%GetTypeOf("canUseClarification")="boolean" Do out.%Set("canUseClarification",inspection.%Get("canUseClarification"),"boolean")
        If inspection.%GetTypeOf("completionRecorded")="boolean" Do out.%Set("completionRecorded",inspection.%Get("completionRecorded"),"boolean")
        If out.completionRecorded Set out.newDecisionId=..RecordedDecision(record)
        If record.%GetTypeOf("taskRequestId")="string",record.taskRequestId'="" {
            Set sc=##class(Chronos.Workflow.Controller).TaskForRequest(record.taskRequestId,.taskId,record.clarificationId)
            If $$$ISOK(sc),taskId'="" {
                If (record.%GetTypeOf("taskId")="string"),(record.taskId'=""),(record.taskId'=taskId) Return ..View("WORKFLOW_STATUS_UNAVAILABLE",decisionId)
                Do out.%Set("taskReady",1,"boolean")
            }
        }
    } Catch ex { Set out=..View("WORKFLOW_STATUS_UNAVAILABLE",decisionId) }
    Return out
}

ClassMethod SameReader(expected As %DynamicObject) As %Boolean [ Private ]
{
    Set sc=##class(Chronos.Approval.Identity).Current("READ",.current)
    If $$$ISERR(sc)||'current.%Get("authenticated") Return 0
    Return (current.%Get("actor")=expected.%Get("actor"))&&(current.%Get("sessionBinding")=expected.%Get("sessionBinding"))
}

/// Historical read; no Runtime.Ready, renewal, task mutation or actor inference.
/// Chronos_Read is namespace-wide read access, not per-decision ownership.
ClassMethod Status(decisionId As %String, Output result As %DynamicObject) As %Status
{
    Set result=..View("WORKFLOW_STATUS_UNAVAILABLE","")
    If $TLevel||'##class(Chronos.Workflow.Store).ID(decisionId) Return $$$OK
    Set result.decisionId=decisionId
    Try {
        Set sc=##class(Chronos.Approval.Identity).Current("READ",.principal) $$$ThrowOnError(sc)
        If 'principal.%Get("authenticated") Return $$$OK
        Set sc=..Lookup(decisionId,.inspection,.exists) $$$ThrowOnError(sc)
        If exists {
            Set candidate=..PublicStatus(decisionId,inspection)
        } Else { Set candidate=..View("WORKFLOW_NOT_FOUND",decisionId),candidate.state="NOT_FOUND" }
        If '..SameReader(principal) Return $$$OK
        Set result=candidate
    } Catch ex { Set result=..View("WORKFLOW_STATUS_UNAVAILABLE",decisionId) }
    Return $$$OK
}

/// At most one ProcessInput per call. Two concurrent callers may enqueue two
/// BPs; the durable Store.Claim fence, not this entry, limits native task creation.
ClassMethod Handoff(decisionId As %String, Output result As %DynamicObject) As %Status
{
    Set result=..View("WORKFLOW_HANDOFF_UNAVAILABLE",""),service=""
    If $TLevel||'##class(Chronos.Workflow.Store).ID(decisionId) Return $$$OK
    Set result.decisionId=decisionId
    Try {
        Set sc=##class(Chronos.Workflow.Controller).Current(.principal,.user,.nativeUser,.membership,.code) $$$ThrowOnError(sc)
        If code'="CSP_WORKFLOW_IDENTITY_CONFIRMED" Return $$$OK
        Set sc=##class(Chronos.Agent.Ledger).Apply("INSPECT",{"requestId":(decisionId)},.held) $$$ThrowOnError(sc)
        If held.%GetTypeOf("private")'="object" Return $$$OK
        // Existing/expired handoffs are historical reads, never another queue.
        Set sc=..Lookup(decisionId,.inspection,.exists) $$$ThrowOnError(sc)
        If exists {
            If '..SameReader(principal) Return $$$OK
            Set result=..PublicStatus(decisionId,inspection)
            Return $$$OK
        }
        Set source=held.private
        Set sc=##class(Chronos.Workflow.Store).Eligible(source,##class(Chronos.Agent.Ledger).NowUS(),.eligible) $$$ThrowOnError(sc)
        If eligible.%Get("code")'="WORKFLOW_SOURCE_ELIGIBLE" {
            If eligible.%Get("code")="WORKFLOW_SOURCE_EXPIRED" {
                Set result.code="WORKFLOW_SOURCE_EXPIRED"
            } Else { Set result.code="WORKFLOW_SOURCE_NOT_ELIGIBLE" }
            Return $$$OK
        }
        Set sc=##class(Chronos.Runtime.Bootstrap).Ready(.ready,source.generation) $$$ThrowOnError(sc)
        If 'ready.ready Return $$$OK
        Set sc=##class(Ens.Director).GetProductionStatus(.production,.state,0) $$$ThrowOnError(sc)
        Set config=##class(%DynamicObject).%FromJSON($Get(^ChronosRuntime("config"),"{}"))
        If (state'=1)||(production'=config.%Get("production")) Return $$$OK
        Set sc=##class(Ens.Director).CreateBusinessService("Chronos.Workflow.Input",.service) $$$ThrowOnError(sc)
        If '$IsObject(service)||(service.%ClassName(1)'="Chronos.Workflow.Input") Throw ##class(%Exception.General).%New("WRONG_FIXED_WORKFLOW_SERVICE")
        Set sc=##class(Chronos.Workflow.Controller).Current(.again,.sameUser,.againUser,.againMembership,.code) $$$ThrowOnError(sc)
        If (code'="CSP_WORKFLOW_IDENTITY_CONFIRMED")||(sameUser'=user)||(again.actor'=principal.actor)||(again.sessionBinding'=principal.sessionBinding) Return $$$OK
        Set request=##class(Chronos.Workflow.Request).%New(),request.DecisionId=decisionId
        // No actor/role/source/deadline is copied into this native request.
        Set sc=service.ProcessInput(request,.response) $$$ThrowOnError(sc)
        If '$IsObject(response)||(response.%ClassName(1)'="Chronos.App.Response") Throw ##class(%Exception.General).%New("NO_HANDOFF_RESPONSE")
        If response.Code'="WORKFLOW_HANDOFF_QUEUED" {
            Set result=..View("WORKFLOW_HANDOFF_UNCERTAIN",decisionId)
        } Else {
            Set result=..View("WORKFLOW_HANDOFF_QUEUED",decisionId),result.state="QUEUED"
        }
    } Catch ex { Set result=..View("WORKFLOW_HANDOFF_UNCERTAIN",decisionId) }
    // Service references never enter a durable BP or a public response.
    Set service=""
    Return $$$OK
}
}
