Include %occStatus

/// Called only after the HTTP adapter authenticates and validates origin/CSRF.
/// The controller authenticates again. This method does not install a route.
Class Chronos.Approval.Entry Extends %RegisteredObject
{
ClassMethod IdentifierField(command As %String) As %String
{
    Return $Select(command="READ_PREPARATION":"requestId",(command="PREVIEW")||..NeedsCorrelation(command)||(command="DECISION")||(command="DECISION_DETAIL")||(command="DECISION_OPERATION")||(command="RESOLVE_DECISION"):"decisionId",(command="READ_OPERATION")||(command="RECONCILE_OPERATION"):"operationId",1:"previewId")
}

ClassMethod NeedsCorrelation(command As %String) As %Boolean
{
    Return (command="PREVIEW_REQUEST")||(command="CLOSE_PREPARATION")
}

ClassMethod Fingerprint() As %String
{
    Return $ZConvert(##class(%xsd.hexBinary).LogicalToXSD($System.Encryption.SHAHash(256,$ListBuild($Namespace,$Username))),"L")
}

ClassMethod Check(request As Chronos.Approval.Request) As %String
{
    If $TLevel Return "TRANSACTION_NOT_ALLOWED"
    If '$IsObject(request) Return "INVALID_REQUEST"
    If 'request.%IsA("Chronos.Approval.Request") Return "INVALID_REQUEST"
    If '$ListFind($ListBuild("PREVIEW_REQUEST","READ_PREPARATION","CLOSE_PREPARATION","PREVIEW","READ","REJECT","CONFIRM","RECONCILE","DECISION","DECISION_DETAIL","DECISION_OPERATION","READ_OPERATION","RECONCILE_OPERATION","RESOLVE_DECISION"),request.Command) Return "INVALID_REQUEST"
    If '##class(Chronos.App.Entry).ValidID(request.Identifier) Return "INVALID_REQUEST"
    If ..NeedsCorrelation(request.Command) {
        If '##class(Chronos.App.Entry).ValidID(request.CorrelationId) Return "INVALID_REQUEST"
    } Else {
        If request.CorrelationId'="" Return "INVALID_REQUEST"
    }
    If (request.OriginJob'=$Job)||(request.OriginFingerprint'=..Fingerprint()) Return "CALL_CONTEXT_CHANGED"
    Set now=##class(Chronos.App.Entry).Now()
    If (request.Deadline<=now)||(request.Deadline>(now+30)) Return "REQUEST_TIMEOUT"
    Return "OK"
}

ClassMethod Call(command As %String, identifier As %String, Output result As %DynamicObject, correlationId As %String = "") As %Status
{
    Set result={"code":"INVALID_REQUEST","traceSessionId":"","data":null}
    Set request=##class(Chronos.Approval.Request).%New()
    Set request.Command=command,request.Identifier=identifier,request.CorrelationId=correlationId,request.OriginJob=$Job
    Set request.OriginFingerprint=..Fingerprint(),request.Deadline=##class(Chronos.App.Entry).Now()+30
    Set code=..Check(request)
    If code'="OK" Set result.code=code Return $$$OK
    Try {
        Set sc=##class(Ens.Director).CreateBusinessService("Chronos.Approval.Input",.service)
        $$$ThrowOnError(sc)
        Set sc=service.ProcessInput(request,.response)
        Set result.traceSessionId=service.%SessionId
        $$$ThrowOnError(sc)
        If '$IsObject(response) Throw ##class(%Exception.General).%New("NO_RESPONSE")
        If 'response.%IsA("Chronos.App.Response") Throw ##class(%Exception.General).%New("WRONG_RESPONSE")
        Set result.code=response.Code
        If response.ResultJSON'="" Set result.data=##class(%DynamicObject).%FromJSON(response.ResultJSON)
    } Catch ex {
        // A lost/failed response is not evidence of non-acceptance. The caller
        // must query the original preview, never manufacture a new confirmation.
        Set result.code="APPROVAL_RESULT_UNAVAILABLE",result.data={"dispatchGranted":false,"readbackRequired":true}
    }
    Return $$$OK
}
}
