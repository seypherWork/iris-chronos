Include %occStatus

/// Trusted internal composition only. HTTP authentication is not implemented here.
/// No public route, approval or dispatch command is exposed by this entry point.
Class Chronos.App.Entry Extends %RegisteredObject
{
ClassMethod Now() As %Numeric
{
    Set stamp=$ZTimestamp
    Return $Piece(stamp,",",1)*86400+$Piece(stamp,",",2)
}

ClassMethod ValidID(value As %String) As %Boolean
{
    Return ($Length(value)>0)&&($Length(value)<=128)&&($Translate(value,"abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.")="")
}

ClassMethod Check(request As Chronos.App.Request, Output code As %String) As %Status
{
    Set code="INVALID_REQUEST"
    If '$IsObject(request) Return $$$OK
    If 'request.%IsA("Chronos.App.Request") Return $$$OK
    If ",READ,TRIALS,RECONCILE,PROPOSE,DECISION,RESOLVE_DECISION,"'[(","_request.Command_",") Set code="INVALID_COMMAND" Return $$$OK
    If '..ValidID(request.OrderId) Return $$$OK
    If (request.ShipmentVersion<1)||(request.ShipmentVersion'=(request.ShipmentVersion\1)) Return $$$OK
    If '..ValidID(request.RequestId) Return $$$OK
    If $Length(request.RequestId)>64 Return $$$OK
    If (request.TrialMode'="WITH_TRIALS")&&(request.TrialMode'="WITHOUT_TRIALS_ABLATION") Return $$$OK
    If request.Command="RECONCILE" {
        If '..ValidID(request.OperationId) Return $$$OK
    } ElseIf request.OperationId'="" { Return $$$OK }
    Set now=..Now()
    If (request.Deadline<=now)||(request.Deadline>(now+30)) Set code="REQUEST_TIMEOUT" Return $$$OK
    If request.Generation="" Set code="RUNTIME_NOT_READY" Return $$$OK
    Set sc=##class(Chronos.Runtime.Bootstrap).Ready(.ready,request.Generation)
    If $$$ISERR(sc)||'ready.ready Set code="RUNTIME_NOT_READY" Return $$$OK
    Set code="OK"
    Return $$$OK
}

ClassMethod Call(command As %String, order As %String, version As %Integer, operation As %String, Output result As %DynamicObject, requestId As %String = "", mode As %String = "WITH_TRIALS") As %Status
{
    Set result={"code":"RUNTIME_NOT_READY","traceSessionId":"","data":null}
    If $TLevel Return $$$ERROR($$$GeneralError,"ENTRY_REQUIRES_NO_TRANSACTION")
    Set sc=##class(Chronos.Runtime.Bootstrap).Ready(.ready)
    If $$$ISERR(sc)||'ready.ready Return $$$OK
    Set request=##class(Chronos.App.Request).%New()
    Set request.Command=command,request.OrderId=order,request.ShipmentVersion=version,request.OperationId=operation
    If (requestId="")&&((command="PROPOSE")||(command="DECISION")||(command="RESOLVE_DECISION")) Set result.code="REQUEST_ID_REQUIRED" Return $$$OK
    If requestId="" Set requestId=$System.Util.CreateGUID()
    Set request.Generation=ready.generation,request.RequestId=requestId,request.Deadline=..Now()+30,request.TrialMode=mode
    Set sc=..Check(request,.code)
    If code'="OK" Set result.code=code Return $$$OK
    Try {
        Set sc=##class(Ens.Director).CreateBusinessService("Chronos.App.Input",.service)
        $$$ThrowOnError(sc)
        Set sc=service.ProcessInput(request,.response)
        Set result.traceSessionId=service.%SessionId
        $$$ThrowOnError(sc)
        If ..Now()'<request.Deadline {
            Set result.code="REQUEST_TIMEOUT"
        } ElseIf '$IsObject(response) {
            Set result.code="NO_RESPONSE"
        } Else {
            Set result.code=response.Code
            If response.ResultJSON'="" Set result.data=##class(%DynamicObject).%FromJSON(response.ResultJSON)
        }
    } Catch ex {
        Set result.code="WORKFLOW_ERROR",result.data=""
    }
    Return $$$OK
}
}
