Include %occStatus

/// Fixed read-only delegation. Initialize this native service BEFORE bootLock.
/// Body contains only a private decision key, response only {allowed,code}.
Class Chronos.Workflow.AccountService Extends Ens.BusinessService
{
Parameter ADAPTER = "";

Method OnProcessInput(pInput As %RegisteredObject, Output pOutput As %RegisteredObject, ByRef pHint As %String) As %Status
{
    Set pOutput=##class(Chronos.App.Response).%New(),pOutput.Code="WORKFLOW_ACCOUNT_CHECK_UNAVAILABLE"
    Set pOutput.ResultJSON={"allowed":false,"code":"WORKFLOW_ACCOUNT_STATE_UNAVAILABLE"}.%ToJSON()
    If $TLevel Return $$$OK
    Try {
        If '$IsObject(pInput)||(pInput.%ClassName(1)'="Chronos.Workflow.Request") Return $$$OK
        Set id=pInput.DecisionId
        If ($Length(id)<1)||($Length(id)>64)||($Translate(id,"abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-")'="") Return $$$OK
        Set sc=##class(Ens.Director).GetProductionStatus(.name,.state,0) $$$ThrowOnError(sc)
        Set config=##class(%DynamicObject).%FromJSON($Get(^ChronosRuntime("config"),"{}"))
        If (state'=1)||(name'=config.%Get("production")) Return $$$OK
        Set started=##class(Chronos.Agent.Ledger).NowUS()
        Set sc=..SendRequestSync("Chronos.Workflow.AccountOperation",pInput,.response,2) $$$ThrowOnError(sc)
        If (##class(Chronos.Agent.Ledger).NowUS()-started)>2000000 Return $$$OK
        If '$IsObject(response)||(response.%ClassName(1)'="Chronos.App.Response") Return $$$OK
        If response.Code'="WORKFLOW_ACCOUNT_CHECK_FINISHED" Return $$$OK
        Set sc=##class(Chronos.Workflow.ContextGate).SafeResult(response.ResultJSON,.checked) $$$ThrowOnError(sc)
        Set pOutput.Code="WORKFLOW_ACCOUNT_CHECK_FINISHED",pOutput.ResultJSON=checked.%ToJSON()
    } Catch ex {
        Set pOutput.Code="WORKFLOW_ACCOUNT_CHECK_UNAVAILABLE"
        Set pOutput.ResultJSON={"allowed":false,"code":"WORKFLOW_ACCOUNT_STATE_UNAVAILABLE"}.%ToJSON()
    }
    // Operational failures never request a retry or disclose a native exception.
    Return $$$OK
}
}
