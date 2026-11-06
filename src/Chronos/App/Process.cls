/// Queue-safe BP: waits asynchronously for the worker and has a finite timer.
Class Chronos.App.Process Extends Ens.BusinessProcess
{
/// Handle belongs only to this BP instance; never accepted from a caller.
Property DeadlineAlarmHandle As %String;

Method OnRequest(request As %Library.Persistent, Output response As %Library.Persistent) As %Status
{
    Set response=##class(Chronos.App.Response).%New()
    Set sc=##class(Chronos.App.Entry).Check(request,.code)
    If code'="OK" Set response.Code=code Return $$$OK
    Set remaining=request.Deadline-##class(Chronos.App.Entry).Now()
    If remaining<=0 Set response.Code="REQUEST_TIMEOUT" Return $$$OK
    // Read/resolve remain available when the separate inference worker is busy.
    Set target=$Select(request.Command="PROPOSE":"Chronos.Agent.Operation",1:"Chronos.App.Worker")
    Set sc=..SendRequestAsync(target,request,1,"worker")
    If $$$ISERR(sc) Return sc
    Set sc=..SetTimer(remaining,"deadline",$ListBuild("worker"),.handle)
    If $$$ISOK(sc) Set ..DeadlineAlarmHandle=handle
    Return sc
}

Method OnResponse(request As %Library.Persistent, ByRef response As %Library.Persistent, callrequest As %Library.Persistent, callresponse As %Library.Persistent, pCompletionKey As %String) As %Status
{
    If pCompletionKey'="worker" Return $$$OK
    Set response=callresponse
    If ##class(Chronos.App.Entry).Now()'<request.Deadline {
        Set response=##class(Chronos.App.Response).%New(),response.Code="REQUEST_TIMEOUT"
    }
    Return $$$OK
}

Method OnTimeout(request As %Library.Persistent, ByRef response As %Library.Persistent, callrequest As %Library.Persistent, pCompletionKey As %String) As %Status
{
    Set ..DeadlineAlarmHandle=""
    Set response=##class(Chronos.App.Response).%New(),response.Code="REQUEST_TIMEOUT"
    Return $$$OK
}

Method ReleaseDeadline() As %Status [ Private ]
{
    If ..DeadlineAlarmHandle="" Return $$$OK
    // Completing a BP clears its pending timer response, but kit154 leaves the
    // alarm scheduled. Interrupt only our own timer through the public message
    // API; never delete alarm globals or purge suspended business messages.
    Set trigger=##class(Ens.AlarmTriggerRequest).%New()
    Set trigger.AlarmHandle=..DeadlineAlarmHandle
    Set sc=..SendRequestAsync("Ens.Alarm",trigger,0,"release-deadline")
    If $$$ISOK(sc) Set ..DeadlineAlarmHandle=""
    Return sc
}

Method OnComplete(request As %Library.Persistent, ByRef response As %Library.Persistent) As %Status
{
    Return ..ReleaseDeadline()
}

Method OnError(request As %Library.Persistent, ByRef response As %Library.Persistent, callrequest As %Library.Persistent, pErrorStatus As %Status, pCompletionKey As %String) As %Status
{
    Set sc=..ReleaseDeadline()
    Return $$$ADDSC(pErrorStatus,sc)
}
}
