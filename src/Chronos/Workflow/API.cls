Include %occStatus

/// Fixed native composition only; the Web API enforces HTTP and strict body
/// policy. Every target separately authenticates its actual CSP caller.
/// No direct send, confirmation, model endpoint, actor or role is accepted.
Class Chronos.Workflow.API Extends %RegisteredObject
{
ClassMethod Call(command As %String, args As %DynamicObject, Output result As %DynamicObject) As %Status
{
    Set result={"code":"INVALID_WORKFLOW_REQUEST","dispatch_authorized":false}
    If $TLevel||'$IsObject(args) Return $$$OK
    If 'args.%IsA("%DynamicObject") Return $$$OK
    Try {
        // Reuse the strict normalizer even for trusted native composition.
        // This prevents a future caller forwarding extra identity/source fields.
        Set body=##class(%DynamicObject).%FromJSON(args.%ToJSON())
        If body.%IsDefined("command") Return $$$OK
        Set body.command=command
        Set policy=##class(%DynamicObject).%FromJSON(##class(Chronos.Workflow.Policy).Parse(body.%ToJSON()))
        If 'policy.%Get("allowed") Return $$$OK
        Set a=policy.args
        If command="START_CLARIFICATION" {
            Set sc=##class(Chronos.Workflow.Entry).Handoff(a.decisionId,.result)
        } ElseIf command="READ_CLARIFICATION" {
            Set sc=##class(Chronos.Workflow.Entry).Status(a.decisionId,.result)
        } ElseIf command="COMPLETE_CLARIFICATION" {
            Set sc=##class(Chronos.Workflow.Controller).Complete(a.clarificationId,a.completionId,a.preference,a.note,.result)
        } ElseIf command="READ_CLARIFICATION_COMPLETION" {
            Set sc=##class(Chronos.Workflow.Controller).ReadCompletion(a.clarificationId,a.completionId,a.preference,a.note,.result)
        } ElseIf command="REEVALUATE_CLARIFICATION" {
            Set sc=##class(Chronos.Workflow.Decisions).Propose(a.clarificationId,a.requestId,.native)
            // The first call returns an App.Entry envelope, whereas a retry is
            // a ledger view. Return only a bounded code and the requested ID.
            // The ordinary decision endpoint supplies the actual public result.
            Set code=native.%Get("code","CLARIFIED_DECISION_UNAVAILABLE")
            If (native.%GetTypeOf("data")="object") Set code=native.data.%Get("code",code)
            If ($Length(code)<1)||($Length(code)>128)||($Translate(code,"ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_")'="") Set code="CLARIFIED_DECISION_UNAVAILABLE"
            Set result={"code":(code),"decisionId":(a.requestId),"readbackRequired":true,"dispatch_authorized":false}
        } Else { Return $$$OK }
        If $$$ISERR(sc) Set result={"code":"WORKFLOW_RESULT_UNAVAILABLE","readbackRequired":true,"dispatch_authorized":false}
    } Catch ex {
        Set result={"code":"WORKFLOW_RESULT_UNAVAILABLE","readbackRequired":true,"dispatch_authorized":false}
    }
    Return $$$OK
}
}
