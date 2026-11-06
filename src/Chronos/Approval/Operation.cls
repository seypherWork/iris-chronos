Include %occStatus

/// In-process execution is mandatory: never replace the browser principal with
/// a queued worker account. Both native hosts reject another job/identity.
Class Chronos.Approval.Operation Extends Ens.BusinessOperation
{
Parameter ADAPTER = "";
Parameter INVOCATION = "InProc";

Method OnMessage(request As %Library.Persistent, Output response As %Library.Persistent) As %Status
{
    Set response=##class(Chronos.App.Response).%New()
    Set response.Code=##class(Chronos.Approval.Entry).Check(request)
    If response.Code'="OK" Return $$$OK
    Set args={}
    Do args.%Set(##class(Chronos.Approval.Entry).IdentifierField(request.Command),request.Identifier)
    If ##class(Chronos.Approval.Entry).NeedsCorrelation(request.Command) Set args.requestId=request.CorrelationId
    Set controller=##class(Chronos.Approval.Controller).%New()
    Set sc=controller.Handle(request.Command,args,.result)
    If $$$ISERR(sc) {
        Set response.Code="APPROVAL_RESULT_UNAVAILABLE"
        Set response.ResultJSON={"dispatchGranted":false,"readbackRequired":true}.%ToJSON()
        Return $$$OK
    }
    Set response.Code=result.code,response.ResultJSON=result.%ToJSON()
    Return $$$OK
}
}
