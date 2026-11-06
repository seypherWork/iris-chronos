Include %occStatus

/// Queued native AI operation. Request contains only identities, not prompts/tickets.
Class Chronos.Agent.Operation Extends Ens.BusinessOperation
{
Parameter ADAPTER = "Chronos.Agent.GuardAdapter";
Parameter INVOCATION = "Queue";

Method OnMessage(request As %Library.Persistent, Output response As %Library.Persistent) As %Status
{
    Set response=##class(Chronos.App.Response).%New(),traceMetrics=""
    Try {
        Set sc=##class(Chronos.App.Entry).Check(request,.code)
        $$$ThrowOnError(sc)
        If code'="OK" { Set response.Code=code Return $$$OK }
        If (request.Command'="PROPOSE")&&(request.Command'="DECISION") { Set response.Code="INVALID_COMMAND" Return $$$OK }
        If request.Command="PROPOSE" {
            If '$Data(^ChronosAI18("config")) { Set response.Code="MODEL_NOT_CONFIGURED" Return $$$OK }
            Set sc=##class(Chronos.Agent.Decisions).Prepare(request.RequestId,request.OrderId,request.ShipmentVersion,request.TrialMode,.result,request.Generation)
            $$$ThrowOnError(sc)
            If result.%Get("state")="PREPARED" {
                // Convert fixed IRIS UTC request deadline to Unix microseconds.
                Set deadlineUS=(request.Deadline-($ZDateH("1970-01-01",3)*86400))*1000000
                Set sc=##class(Chronos.Agent.Model).Run(..Adapter,request.RequestId,..%SessionId,deadlineUS,.result,request.Generation,.traceMetrics)
                $$$ThrowOnError(sc)
            }
        } Else {
            Set sc=##class(Chronos.Agent.Decisions).Read(request.RequestId,.result)
            $$$ThrowOnError(sc)
            If result.code'="NOT_FOUND" {
                If (result.orderId'=request.OrderId)||(result.shipmentVersion'=request.ShipmentVersion)||(result.mode'=request.TrialMode) {
                    Set response.Code="DECISION_IDENTITY_MISMATCH"
                    Return $$$OK
                }
            }
        }
        Set response.Code=result.code,response.ResultJSON=result.%ToJSON()
        If $Length($ZConvert(response.ResultJSON,"O","UTF8"))>16384 Set response.Code="RESULT_TOO_LARGE",response.ResultJSON=""
        If $IsObject(traceMetrics) {
            // Store metrics on the native message, outside the application result.
            Try { Set response.TraceMetricsJSON=traceMetrics.%ToJSON() } Catch traceError { Set response.TraceMetricsJSON="" }
        }
    } Catch ex {
        Set response.Code="AGENT_OPERATION_UNAVAILABLE",response.ResultJSON=""
    }
    // Return operational failures as data: never request BO automatic retries.
    Return $$$OK
}
}
