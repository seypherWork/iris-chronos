Include %occStatus

/// OPT-IN ONLY. A separate durable BP waits for a Workflow task, never for a
/// model or shipment. The ordinary application's 30-second BP is unchanged.
Class Chronos.Workflow.Process Extends Ens.BusinessProcess
{
Property ClarificationId As %String(MAXLEN = 128);
Property NativeTaskRequest As EnsLib.Workflow.TaskRequest;
Property DeadlineAlarmHandle As %String;

Method OnRequest(request As %Library.Persistent, Output response As %Library.Persistent) As %Status
{
    Set response=##class(Chronos.App.Response).%New()
    If '$IsObject(request)||'request.%IsA("Chronos.Workflow.Request") { Set response.Code="INVALID_WORKFLOW_REQUEST" Return $$$OK }
    Set ..ClarificationId="",attempted=0
    Try {
        Set sc=##class(Chronos.Workflow.Store).Claim(request.DecisionId,.claim) $$$ThrowOnError(sc)
        Set response.Code=claim.code,response.ResultJSON=claim.%ToJSON()
        If 'claim.%Get("handoffGranted") Return $$$OK
        Set ..ClarificationId=claim.clarificationId
        Set task=##class(EnsLib.Workflow.TaskRequest).%New(),..NativeTaskRequest=task
        Set task.%Subject="Clarify shipment priority: "_claim.orderId,task.%Command=..ClarificationId
        Set task.%Message="Preference must be EARLIEST_ALLOWED or CHEAPEST_ON_TIME; add a short Note explaining the current customer instruction. This records information only; it does not approve or send a recovery."
        Set task.%Actions="Clarified,UnableToClarify",task.%FormFields="Preference,Note"
        Set sc=task.%Save() $$$ThrowOnError(sc)
        Set sc=##class(Chronos.Workflow.Store).AttachRequest(..ClarificationId,task.%Id(),.attached) $$$ThrowOnError(sc)
        Set seconds=(claim.expiresUS-##class(Chronos.Agent.Ledger).NowUS())/1000000
        If seconds<=0 Throw ##class(%Exception.General).%New("WORKFLOW_EXPIRED")
        // The durable fence and native request correlation precede this one
        // queue attempt. Neither an error nor a restarted BP may resend it.
        Set attempted=1
        Set sc=..SendRequestAsync("Chronos.Clarifiers",task,1,"clarification") $$$ThrowOnError(sc)
        Set sc=##class(Chronos.Workflow.Store).Sent(..ClarificationId,.sent) $$$ThrowOnError(sc)
        Set seconds=(claim.expiresUS-##class(Chronos.Agent.Ledger).NowUS())/1000000
        If seconds<=0 Throw ##class(%Exception.General).%New("WORKFLOW_EXPIRED")
        Set sc=..SetTimer(seconds,"workflow-deadline",$ListBuild("clarification"),.handle) $$$ThrowOnError(sc)
        Set ..DeadlineAlarmHandle=handle
        Set response.Code="WORKFLOW_WAITING",response.ResultJSON=sent.%ToJSON()
    } Catch ex {
        Do ..MarkUncertain()
        // A queue attempt followed by a failed fence/timer update must not
        // leave a deliberately unbounded task. Cancellation is best effort;
        // its outcome is never represented as verified task completion.
        If attempted { Try { Set sc=..CancelPending() } Catch cancelEx {} }
        Set response.Code="WORKFLOW_HANDOFF_UNCERTAIN",response.ResultJSON=""
    }
    // Never request an automatic BO/BP retry for an uncertain queue result.
    Return $$$OK
}

Method OnResponse(request As %Library.Persistent, ByRef response As %Library.Persistent, callrequest As %Library.Persistent, callresponse As %Library.Persistent, pCompletionKey As %String) As %Status
{
    If pCompletionKey'="clarification" Return $$$OK
    Set response=##class(Chronos.App.Response).%New()
    Try {
        If '..NativeTaskRequest.%IsA("EnsLib.Workflow.TaskRequest") Throw ##class(%Exception.General).%New("NO_NATIVE_REQUEST")
        If '$IsObject(callrequest)||'callrequest.%IsA("EnsLib.Workflow.TaskRequest") Throw ##class(%Exception.General).%New("BAD_REQUEST")
        If callrequest.%Id()'=..NativeTaskRequest.%Id() Throw ##class(%Exception.General).%New("WRONG_REQUEST")
        If '$IsObject(callresponse)||'callresponse.%IsA("EnsLib.Workflow.TaskResponse") Throw ##class(%Exception.General).%New("BAD_RESPONSE")
        Set sc=##class(Chronos.Workflow.Store).RecordResponse(..ClarificationId,callresponse.%Id(),.recorded) $$$ThrowOnError(sc)
        Set response.Code=recorded.code,response.ResultJSON=recorded.%ToJSON()
    } Catch ex {
        Do ..MarkUncertain()
        Set response.Code="WORKFLOW_RESPONSE_UNVERIFIED",response.ResultJSON=""
    }
    Return $$$OK
}

Method OnTimeout(request As %Library.Persistent, ByRef response As %Library.Persistent, callrequest As %Library.Persistent, pCompletionKey As %String) As %Status
{
    Set ..DeadlineAlarmHandle="",response=##class(Chronos.App.Response).%New()
    Try {
        Set sc=##class(Chronos.Workflow.Store).Expire(..ClarificationId,.expired) $$$ThrowOnError(sc)
        If expired.code'="WORKFLOW_RECORDED" Throw ##class(%Exception.General).%New("EXPIRY_NOT_RECORDED")
        Set sc=..CancelPending() $$$ThrowOnError(sc)
        Set response.Code=$Select(expired.state="RESPONSE_UNVERIFIED":"WORKFLOW_RESPONSE_UNVERIFIED",1:"WORKFLOW_EXPIRED_UNVERIFIED"),response.ResultJSON=""
    } Catch ex {
        Do ..MarkUncertain()
        Set response.Code="WORKFLOW_HANDOFF_UNCERTAIN",response.ResultJSON=""
    }
    Return $$$OK
}

Method CancelPending() As %Status [ Private ]
{
    If '$IsObject(..NativeTaskRequest) Return $$$OK
    If '..NativeTaskRequest.%IsA("EnsLib.Workflow.TaskRequest") Return $$$ERROR($$$GeneralError,"INVALID_NATIVE_REQUEST")
    If ..NativeTaskRequest.%Command'=..ClarificationId Return $$$ERROR($$$GeneralError,"WRONG_NATIVE_REQUEST")
    Return ##class(EnsLib.Workflow.Engine).%CancelRequest(..NativeTaskRequest)
}

Method MarkUncertain() [ Private ]
{
    Try {
        If ..ClarificationId'="" Set sc=##class(Chronos.Workflow.Store).Uncertain(..ClarificationId,.ignored)
    } Catch ex {}
}

Method ReleaseDeadline() As %Status [ Private ]
{
    If ..DeadlineAlarmHandle="" Return $$$OK
    Set trigger=##class(Ens.AlarmTriggerRequest).%New(),trigger.AlarmHandle=..DeadlineAlarmHandle
    Set sc=..SendRequestAsync("Ens.Alarm",trigger,0,"release-workflow-deadline")
    If $$$ISOK(sc) Set ..DeadlineAlarmHandle=""
    Return sc
}

Method OnComplete(request As %Library.Persistent, ByRef response As %Library.Persistent) As %Status
{
    Return ..ReleaseDeadline()
}

Method OnError(request As %Library.Persistent, ByRef response As %Library.Persistent, callrequest As %Library.Persistent, pErrorStatus As %Status, pCompletionKey As %String) As %Status
{
    Do ..MarkUncertain()
    Set response=##class(Chronos.App.Response).%New(),response.Code="WORKFLOW_HANDOFF_UNCERTAIN"
    Try { Set sc=..CancelPending() } Catch cancelEx {}
    Try { Set sc=..ReleaseDeadline() } Catch ex {}
    Return $$$OK
}
}
