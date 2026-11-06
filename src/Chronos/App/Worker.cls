Include %occStatus

/// Fixed reads/reconciliation and decision control. No model call or Submit.
Class Chronos.App.Worker Extends Ens.BusinessOperation
{
Parameter ADAPTER = "";
Parameter INVOCATION = "Queue";

Method OnMessage(pRequest As %Library.Persistent, Output pResponse As %Library.Persistent) As %Status
{
    Set pResponse=##class(Chronos.App.Response).%New()
    Lock +^ChronosRuntime("bootLock"):0
    If '$Test Set pResponse.Code="RUNTIME_NOT_READY" Return $$$OK
    Try {
        Set sc=##class(Chronos.App.Entry).Check(pRequest,.code)
        If ",READ,TRIALS,RECONCILE,DECISION,RESOLVE_DECISION,"'[(","_pRequest.Command_",") Set code="INVALID_COMMAND"
        If code'="OK" {
            Set pResponse.Code=code
        } ElseIf (pRequest.Command="DECISION")||(pRequest.Command="RESOLVE_DECISION") {
            Set sc=..Decision(pRequest,pResponse)
            $$$ThrowOnError(sc)
        } Else {
            If pRequest.Command="RECONCILE" {
                Set sc=##class(Chronos.Authority.Store).Apply("READ_OPERATION",{"operationId":(pRequest.OperationId)},.current)
                $$$ThrowOnError(sc)
                If (current.operation.orderId'=pRequest.OrderId)||(current.operation.shipmentVersion'=pRequest.ShipmentVersion) Throw ##class(%Exception.General).%New("WRONG_OPERATION")
            } Else {
                Set sc=##class(Chronos.Authority.Store).Apply("READ",{"orderId":(pRequest.OrderId),"shipmentVersion":(pRequest.ShipmentVersion)},.current)
                $$$ThrowOnError(sc)
            }
            Set sc=##class(Chronos.Runtime.Bootstrap).Provider(.provider)
            $$$ThrowOnError(sc)
            If pRequest.Command="READ" {
                Set sc=provider.Snapshot(pRequest.OrderId,.snapshot)
                $$$ThrowOnError(sc)
                If snapshot.shipmentVersion'=pRequest.ShipmentVersion Throw ##class(%Exception.General).%New("WRONG_VERSION")
                Set payload={"authority":(current),"snapshot":(snapshot)}
            } ElseIf pRequest.Command="TRIALS" {
                Set sc=provider.Trials(pRequest.OrderId,.payload)
                $$$ThrowOnError(sc)
                If payload.snapshot.shipmentVersion'=pRequest.ShipmentVersion Throw ##class(%Exception.General).%New("WRONG_VERSION")
            } Else {
                Set coordinator=##class(Chronos.Recovery.Coordinator).%New(provider)
                Set sc=coordinator.Reconcile(pRequest.OperationId,.payload)
                $$$ThrowOnError(sc)
            }
            If ##class(Chronos.App.Entry).Now()'<pRequest.Deadline {
                Set pResponse.Code="REQUEST_TIMEOUT"
            } Else {
                Set encoded=payload.%ToJSON()
                If $Length($ZConvert(encoded,"O","UTF8"))>65536 {
                    Set pResponse.Code="RESULT_TOO_LARGE"
                } Else {
                    Set pResponse.Code="OK",pResponse.ResultJSON=encoded
                }
            }
        }
    } Catch ex {
        // No provider bodies or exception text enter the public result/log.
        Set pResponse.Code="OPERATION_UNAVAILABLE",pResponse.ResultJSON=""
    }
    Lock -^ChronosRuntime("bootLock")
    // Never return an operational failure as a BO error that could cause retry.
    Return $$$OK
}

Method Decision(request As Chronos.App.Request, response As Chronos.App.Response) As %Status [ Private ]
{
    Set sc=##class(Chronos.Agent.Decisions).Read(request.RequestId,.r)
    $$$ThrowOnError(sc)
    If r.code'="NOT_FOUND" {
        If (r.orderId'=request.OrderId)||(r.shipmentVersion'=request.ShipmentVersion)||(r.mode'=request.TrialMode) {
            Set response.Code="DECISION_IDENTITY_MISMATCH"
            Return $$$OK
        }
    }
    If request.Command="RESOLVE_DECISION" {
        Set sc=##class(Chronos.Agent.Decisions).Resolve(request.RequestId,request.OrderId,request.ShipmentVersion,request.TrialMode,.r,request.Generation)
        $$$ThrowOnError(sc)
    }
    If ##class(Chronos.App.Entry).Now()'<request.Deadline { Set response.Code="REQUEST_TIMEOUT" Return $$$OK }
    Set encoded=r.%ToJSON()
    If $Length($ZConvert(encoded,"O","UTF8"))>16384 { Set response.Code="RESULT_TOO_LARGE" Return $$$OK }
    Set response.Code=r.code,response.ResultJSON=encoded
    Return $$$OK
}
}
