Include %occStatus

/// Internal stable-read bridge. Does not persist/consume a decision or invoke AI.
/// Caller is trusted native composition; no browser-supplied authority or roots.
Class Chronos.Agent.Context Extends %RegisteredObject
{
ClassMethod Prepare(orderId As %String, version As %Integer, contextId As %String, mode As %String, Output result As %DynamicObject, expectedGeneration As %String = "") As %Status
{
    Return ..Run("PREPARE",orderId,version,{"contextId":(contextId),"mode":(mode)},expectedGeneration,.result)
}

ClassMethod Finish(orderId As %String, version As %Integer, record As %DynamicObject, generation As %String, responseText As %String, providerStatus As %String, Output result As %DynamicObject) As %Status
{
    If (generation="")||($Length($ZConvert(responseText,"O","UTF8"))>4096) {
        Set result={"status":"ERROR","code":"INVALID_COMPLETION","dispatch_authorized":false}
        Return $$$OK
    }
    Return ..Run("FINISH",orderId,version,{"record":(record),"responseText":(responseText),"providerStatus":(providerStatus)},generation,.result)
}

/// Trusted internal only. Load the durable decision here, never from HTTP JSON.
/// The inference window is fixed; fresh human review is a separate validation.
ClassMethod Review(requestId As %String, Output result As %DynamicObject) As %Status
{
    Set result={"status":"RECHECK_REQUIRED","code":"DECISION_NOT_COMPLETED","dispatch_authorized":false}
    If $TLevel Return $$$ERROR($$$GeneralError,"AGENT_REQUIRES_NO_TRANSACTION")
    Set sc=##class(Chronos.Agent.Ledger).Apply("INSPECT",{"requestId":(requestId)},.read)
    If $$$ISERR(sc) Return sc
    If 'read.%IsDefined("private") Return $$$OK
    Set decision=read.private
    If decision.state'="COMPLETED" Return $$$OK
    // Historical nonproposals have no actionable model context. Reject before
    // provider observation or the Python bridge; never synthesize prepared data.
    Set result={"status":"REJECTED","code":"DECISION_NOT_ACTIONABLE","dispatch_authorized":false}
    If decision.%GetTypeOf("result")'="object" Return $$$OK
    If decision.result.%Get("status")'="VALIDATED_PROPOSAL" Return $$$OK
    Return ..Run("REVIEW",decision.orderId,decision.shipmentVersion,{"decision":(decision),"generation":(decision.generation)},decision.generation,.result)
}

ClassMethod Run(command As %String, orderId As %String, version As %Integer, args As %DynamicObject, generation As %String, Output result As %DynamicObject) As %Status [ Private ]
{
    Set result={"status":"RECHECK_REQUIRED","code":"RUNTIME_NOT_READY","dispatch_authorized":false}
    If $TLevel Return $$$ERROR($$$GeneralError,"AGENT_REQUIRES_NO_TRANSACTION")
    Lock +^ChronosRuntime("bootLock"):0
    If '$Test Return $$$OK
    Set sc=$$$OK
    Try {
        Set sc=##class(Chronos.Runtime.Bootstrap).Ready(.ready,generation)
        $$$ThrowOnError(sc)
        If ready.ready {
            Set config=##class(%DynamicObject).%FromJSON(^ChronosRuntime("config"))
            Set query={"orderId":(orderId),"shipmentVersion":(version)}
            Set sc=##class(Chronos.Authority.Store).Apply("READ",query,.before)
            $$$ThrowOnError(sc)
            Set args.authority=before,args.orderId=orderId,args.responseContract=##class(Chronos.Agent.Model).Contract()
            Set sc=##class(Chronos.Agent.Python).Run(config.pythonRoot,config.dataRoot,command,args,.candidate)
            $$$ThrowOnError(sc)
            Set sc=##class(Chronos.Authority.Store).Apply("READ",query,.after)
            $$$ThrowOnError(sc)
            // Neither store is called atomic with the other. Changed native
            // state during the provider read invalidates this whole result.
            If before.%ToJSON()'=after.%ToJSON() {
                Set result={"status":"RECHECK_REQUIRED","code":"AUTHORITY_CHANGED_DURING_READ","dispatch_authorized":false}
            } Else {
                Set sc=##class(Chronos.Runtime.Bootstrap).Ready(.again,ready.generation)
                $$$ThrowOnError(sc)
                If again.ready {
                    Set result=candidate
                    Do result.%Set("runtime_generation",ready.generation)
                }
            }
        }
    } Catch ex {
        Set result={"status":"ERROR","code":"AGENT_CONTEXT_UNAVAILABLE","dispatch_authorized":false}
        Set sc=$$$ERROR($$$GeneralError,"AGENT_CONTEXT_UNAVAILABLE")
    }
    Lock -^ChronosRuntime("bootLock")
    Return sc
}
}
