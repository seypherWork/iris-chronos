Include %occStatus

/// Fixed native gateway, not an HTTP adapter or authentication substitute.
/// It acknowledges queue submission without waiting for the human Workflow BP.
Class Chronos.Workflow.Input Extends Ens.BusinessService
{
Parameter ADAPTER = "";

Method OnProcessInput(pInput As %RegisteredObject, Output pOutput As %RegisteredObject, ByRef pHint As %String) As %Status
{
    Set pOutput=##class(Chronos.App.Response).%New(),pOutput.Code="WORKFLOW_HANDOFF_UNAVAILABLE",pOutput.ResultJSON=""
    If $TLevel Return $$$OK
    Try {
        If '$IsObject(pInput)||(pInput.%ClassName(1)'="Chronos.Workflow.Request") Return $$$OK
        If '##class(Chronos.Workflow.Store).ID(pInput.DecisionId) Return $$$OK
        Set sc=##class(Ens.Director).GetProductionStatus(.production,.state,0) $$$ThrowOnError(sc)
        Set config=##class(%DynamicObject).%FromJSON($Get(^ChronosRuntime("config"),"{}"))
        If (state'=1)||(production'=config.%Get("production")) Return $$$OK
        // Exactly one attempt and no reply requested. Store.Claim in the BP
        // is the durable fence for native TaskRequest creation, not this ack.
        Set sc=..SendRequestAsync("Chronos.Workflow.Process",pInput,0) $$$ThrowOnError(sc)
        Set pOutput.Code="WORKFLOW_HANDOFF_QUEUED"
    } Catch ex { Set pOutput.Code="WORKFLOW_HANDOFF_UNCERTAIN",pOutput.ResultJSON="" }
    // Returning OK prevents a framework retry after an uncertain queue result.
    Return $$$OK
}
}
