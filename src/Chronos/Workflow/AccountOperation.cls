Include %occStatus

/// Queue is mandatory: this job uses only its existing bounded worker authority.
/// No boot/task locks, login, grants, provider calls, source body or model calls.
Class Chronos.Workflow.AccountOperation Extends Ens.BusinessOperation
{
Parameter ADAPTER = "";
Parameter INVOCATION = "Queue";

Method OnMessage(pRequest As %Library.Persistent, Output pResponse As %Library.Persistent) As %Status
{
    New %ChronosWorkflowGate
    Set pResponse=##class(Chronos.App.Response).%New(),pResponse.Code="WORKFLOW_ACCOUNT_CHECK_FINISHED"
    Set pResponse.ResultJSON={"allowed":false,"code":"WORKFLOW_ACCOUNT_STATE_UNAVAILABLE"}.%ToJSON()
    If $TLevel Return $$$OK
    Try {
        If '$IsObject(pRequest)||(pRequest.%ClassName(1)'="Chronos.Workflow.Request") Return $$$OK
        If '$System.Security.Check("%Admin_Secure","USE")||'$System.Security.Check("%DB_IRISSYS","READ") Return $$$OK
        Set id=pRequest.DecisionId
        If ($Length(id)<1)||($Length(id)>64)||($Translate(id,"abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-")'="") Return $$$OK
        Set sc=##class(Chronos.Workflow.AccountState).ForDecision(id,.r) $$$ThrowOnError(sc)
        Set sc=##class(Chronos.Workflow.ContextGate).SafeResult(r.%ToJSON(),.checked) $$$ThrowOnError(sc)
        Set pResponse.ResultJSON=checked.%ToJSON()
    } Catch ex {
        Set pResponse.ResultJSON={"allowed":false,"code":"WORKFLOW_ACCOUNT_STATE_UNAVAILABLE"}.%ToJSON()
    }
    Return $$$OK
}
}
