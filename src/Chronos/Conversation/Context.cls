Include %occStatus

/// Internal authenticated read composition. No HTTP route, model or provider I/O.
/// Result contains private scope and must not be returned wholesale to a browser.
Class Chronos.Conversation.Context Extends %RegisteredObject
{
ClassMethod Principal(Output principal As %DynamicObject) As %Status
{
    Set sc=##class(Chronos.Approval.Identity).Current("READ",.principal)
    If $$$ISERR(sc) Return sc
    If 'principal.%Get("authenticated") Return $$$ERROR($$$GeneralError,"CONVERSATION_PERMISSION_DENIED")
    // READ is freshly checked above. Python may be granted only by CSP MatchRoles.
    // Check the current process capability without granting permanent user roles.
    If '$System.Security.Check("%Service_EmbeddedPython","USE") Return $$$ERROR($$$GeneralError,"CONVERSATION_CAPABILITY_UNAVAILABLE")
    Return $$$OK
}

ClassMethod SamePrincipal(expected As %DynamicObject) As %Status
{
    Set sc=..Principal(.current) If $$$ISERR(sc) Return sc
    If (current.actor'=expected.actor)||(current.sessionBinding'=expected.sessionBinding) Return $$$ERROR($$$GeneralError,"CONVERSATION_IDENTITY_CHANGED")
    Return $$$OK
}

ClassMethod Snapshot(decisionId As %String, conversationRevision As %Integer, Output result As %DynamicObject, conversationId As %String = "") As %Status
{
    Set result={"code":"CONVERSATION_CONTEXT_UNAVAILABLE","dispatch_authorized":false}
    If $TLevel Return $$$ERROR($$$GeneralError,"CONVERSATION_REQUIRES_NO_TRANSACTION")
    If '##class(Chronos.App.Entry).ValidID(decisionId) Return $$$ERROR($$$GeneralError,"INVALID_DECISION_ID")
    If (conversationRevision<1)||(conversationRevision>7)||(conversationRevision\1'=conversationRevision) Return $$$ERROR($$$GeneralError,"INVALID_CONVERSATION_REVISION")
    Set sc=..Principal(.principal) If $$$ISERR(sc) Return sc
    Lock +^ChronosRuntime("bootLock"):0
    If '$Test Return $$$ERROR($$$GeneralError,"RUNTIME_BUSY")
    Set sc=$$$OK
    Try {
        Set sc=##class(Chronos.Runtime.Bootstrap).Ready(.ready) $$$ThrowOnError(sc)
        If 'ready.ready Throw ##class(%Exception.General).%New("RUNTIME_NOT_READY")
        Set config=##class(%DynamicObject).%FromJSON($Get(^ChronosRuntime("config"),"{}"))
        Set web=##class(%DynamicObject).%FromJSON($Get(^ChronosWeb("config"),"{}"))
        If (web.%GetTypeOf("installationId")'="string")||($Length(web.installationId)'=64)||($Translate(web.installationId,"0123456789abcdef")'="") Throw ##class(%Exception.General).%New("WEB_NOT_CONFIGURED")
        If (web.%Get("application")'=%request.Application) Throw ##class(%Exception.General).%New("WRONG_APPLICATION")
        Set controller=##class(Chronos.Approval.Controller).%New()
        Set sc=controller.Handle("DECISION_DETAIL",{"decisionId":(decisionId)},.detail) $$$ThrowOnError(sc)
        If detail.%Get("code")'="DECISION_DETAIL_RECORDED" Throw ##class(%Exception.General).%New("HISTORY_UNAVAILABLE")
        Set sc=..SamePrincipal(principal) $$$ThrowOnError(sc)
        Set query={"orderId":(detail.context.%Get("order_id")),"shipmentVersion":(detail.context.%Get("shipment_version"))}
        Set sc=##class(Chronos.Authority.Store).Apply("READ",query,.before) $$$ThrowOnError(sc)
        Set sc=controller.Handle("DECISION_OPERATION",{"decisionId":(decisionId)},.operation) $$$ThrowOnError(sc)
        Set sc=..SamePrincipal(principal) $$$ThrowOnError(sc)
        Set currentJSON=""
        If operation.%Get("code")="DECISION_OPERATION_RECORDED" {
            If operation.operation.%Get("operationId")'=before.effect.%Get("currentOperationId") Throw ##class(%Exception.General).%New("OPERATION_CHANGED")
            Set currentJSON=operation.%ToJSON()
        } Else {
            // A failed read must not silently become a successful missing read.
            If (operation.%Get("code")'="OPERATION_UNAVAILABLE")||(before.effect.%Get("currentOperationId")'="") Throw ##class(%Exception.General).%New("OPERATION_UNAVAILABLE")
        }
        Set sc=##class(Chronos.Authority.Store).Apply("READ",query,.after) $$$ThrowOnError(sc)
        If before.%ToJSON()'=after.%ToJSON() Throw ##class(%Exception.General).%New("AUTHORITY_CHANGED_DURING_READ")
        Set scope={"installation_id":(web.installationId),"actor":(principal.actor),"session_binding":(principal.sessionBinding),"case_id":(query.orderId),"shipment_version":(query.shipmentVersion)}
        Set sc=##class(Chronos.Agent.Python).ConversationModule(config.pythonRoot,.module) $$$ThrowOnError(sc)
        // Contract is installation-owned and immutable, never browser selected.
        Set responseContract="chronos.case-conversation.v1"
        If $Get(^ChronosConversation("model"))'="" {
            Set sc=##class(Chronos.Conversation.Model).Current(.modelConfig) $$$ThrowOnError(sc)
            Set responseContract=modelConfig.contract
        }
        If responseContract="chronos.case-explanation-plan.v2",conversationId'="" {
            If '##class(Chronos.App.Entry).ValidID(conversationId) Throw ##class(%Exception.General).%New("INVALID_CONVERSATION_ID")
            Set sc=##class(Chronos.Conversation.Ledger).Apply("INSPECT",conversationId,scope,{},.history) $$$ThrowOnError(sc)
            Set sc=##class(Chronos.Agent.Ledger).Apply("INSPECT",{"requestId":(decisionId)},.stored) $$$ThrowOnError(sc)
            Set sc=##class(Chronos.Agent.Ledger).Apply("PREVIOUS",{"requestId":(decisionId)},.prior) $$$ThrowOnError(sc)
            Set previousJSON=""
            If prior.%Get("code")="PREVIOUS_DECISION_RECORDED" {
                Set previousJSON=prior.private.%ToJSON()
            } ElseIf '$ListFind($ListBuild("HISTORY_NOT_FOUND","HISTORY_SCAN_LIMIT"),prior.%Get("code")) {
                Throw ##class(%Exception.General).%New("HISTORY_UNAVAILABLE")
            }
            Set sc=..SamePrincipal(principal) $$$ThrowOnError(sc)
            Set sc=##class(Chronos.Agent.Python).GroundedV2Context(config.pythonRoot,config.dataRoot,stored.private.%ToJSON(),detail.%ToJSON(),scope.%ToJSON(),currentJSON,before.%ToJSON(),history.privateJSON,previousJSON,prior.%Get("code"),ready.generation,before.effect.snapshotId,conversationRevision,.candidate) $$$ThrowOnError(sc)
        } ElseIf responseContract="chronos.case-explanation-plan.v1" {
            Set sc=##class(Chronos.Agent.Ledger).Apply("INSPECT",{"requestId":(decisionId)},.stored) $$$ThrowOnError(sc)
            Set sc=..SamePrincipal(principal) $$$ThrowOnError(sc)
            Set sc=##class(Chronos.Agent.Python).GroundedContext(config.pythonRoot,stored.private.%ToJSON(),detail.%ToJSON(),scope.%ToJSON(),currentJSON,ready.generation,before.effect.snapshotId,conversationRevision,.candidate) $$$ThrowOnError(sc)
        } ElseIf (responseContract="chronos.case-conversation.v1")||((responseContract="chronos.case-explanation-plan.v2")&&(conversationId="")) {
            Set candidate=##class(%DynamicObject).%FromJSON(##class(Chronos.Conversation.Python).Context(module,$Namespace,detail.%ToJSON(),scope.%ToJSON(),currentJSON,ready.generation,before.effect.snapshotId,conversationRevision))
        } Else { Throw ##class(%Exception.General).%New("INVALID_CONVERSATION_CONTRACT") }
        Set sc=..SamePrincipal(principal) $$$ThrowOnError(sc)
        Set sc=##class(Chronos.Runtime.Bootstrap).Ready(.again,ready.generation) $$$ThrowOnError(sc)
        If 'again.ready Throw ##class(%Exception.General).%New("RUNTIME_CHANGED")
        Set sc=##class(Chronos.Authority.Store).Apply("READ",query,.final) $$$ThrowOnError(sc)
        If after.%ToJSON()'=final.%ToJSON() Throw ##class(%Exception.General).%New("AUTHORITY_CHANGED_DURING_READ")
        Set sc=..SamePrincipal(principal) $$$ThrowOnError(sc)
        Set result=candidate
    } Catch ex {
        Set result={"code":"CONVERSATION_CONTEXT_UNAVAILABLE","dispatch_authorized":false}
        Set sc=$$$ERROR($$$GeneralError,"CONVERSATION_CONTEXT_UNAVAILABLE")
    }
    Lock -^ChronosRuntime("bootLock")
    Return sc
}
}
