Include %occStatus

/// Original CSP composition for one new clarified proposal. No shipment grant,
/// caller-supplied source, identity, policy, prepared context or retry loop.
Class Chronos.Workflow.Decisions Extends %RegisteredObject
{
ClassMethod Propose(clarificationId As %String, requestId As %String, Output result As %DynamicObject) As %Status
{
    Set result={"code":"CLARIFIED_DECISION_UNAVAILABLE","dispatch_authorized":false}
    If $TLevel||'##class(Chronos.Workflow.Store).ID(clarificationId)||'##class(Chronos.App.Entry).ValidID(requestId)||($Length(requestId)>64) Return $$$OK
    Try {
        Set sc=##class(Chronos.Workflow.Controller).Current(.principal,.user,.nativeUser,.membership,.code) $$$ThrowOnError(sc)
        If code'="CSP_WORKFLOW_IDENTITY_CONFIRMED" Return $$$OK
        // Retries are reads BEFORE fresh context/time generation. They never
        // call the model, refresh the sample or renew the first human expiry.
        Set sc=##class(Chronos.Agent.Ledger).Apply("INSPECT",{"requestId":(requestId)},.read) $$$ThrowOnError(sc)
        If read.%Get("code")'="NOT_FOUND" {
            If read.%GetTypeOf("private")'="object" Throw ##class(%Exception.General).%New("NO_PRIVATE_DECISION")
            Set d=read.private
            If d.%GetTypeOf("clarificationAnchor")'="object" Throw ##class(%Exception.General).%New("REQUEST_ID_CONFLICT")
            Set anchor=d.clarificationAnchor
            If (anchor.%Get("requestId")'=requestId)||(anchor.%Get("clarificationId")'=clarificationId)||(anchor.%Get("user")'=user)||(anchor.%Get("actor")'=principal.actor) Throw ##class(%Exception.General).%New("REQUEST_ID_CONFLICT")
            If $Get(^ChronosDecision16("clarificationAdoption",clarificationId))'=anchor.%ToJSON() Throw ##class(%Exception.General).%New("REGISTRATION_CHANGED")
            Return ##class(Chronos.Agent.Decisions).Read(requestId,.result)
        }
        Set sc=##class(Chronos.Workflow.Store).ReadAdoptionSource(clarificationId,.source) $$$ThrowOnError(sc)
        If (source.%GetTypeOf("expected_binding")'="object")||(source.%GetTypeOf("record")'="object") Return $$$OK
        Set binding=source.%Get("expected_binding")
        // Mode and order originate only in the immutable private HOLD.
        Set sc=##class(Chronos.Agent.Ledger).Apply("INSPECT",{"requestId":(binding.%Get("source_decision_id"))},.held) $$$ThrowOnError(sc)
        If held.%GetTypeOf("private")'="object" Throw ##class(%Exception.General).%New("SOURCE_HOLD_UNAVAILABLE")
        Set parent=held.private
        If (parent.%Get("orderId")'=binding.%Get("order_id"))||(parent.%Get("shipmentVersion")'=binding.%Get("shipment_version"))||(parent.%Get("generation")'=binding.%Get("generation")) Throw ##class(%Exception.General).%New("SOURCE_HOLD_CHANGED")
        Set sc=##class(Chronos.Agent.Context).Prepare(parent.orderId,parent.shipmentVersion,requestId,parent.mode,.prepared,parent.generation,clarificationId) $$$ThrowOnError(sc)
        If prepared.%Get("status")'="READY" { Set result=prepared Return $$$OK }
        Set args={"requestId":(requestId),"orderId":(parent.orderId),"shipmentVersion":(parent.shipmentVersion),"mode":(parent.mode),"generation":(parent.generation),"prepared":(prepared)}
        Set sc=##class(Chronos.Agent.Ledger).Apply("REGISTER_CLARIFIED",args,.registered) $$$ThrowOnError(sc)
        Set result=registered
        If registered.%Get("code")'="DECISION_PREPARED" Return $$$OK
        Set sc=##class(Chronos.Approval.Identity).Current("APPROVE",.again) $$$ThrowOnError(sc)
        If 'again.%Get("authenticated")||(again.%Get("actor")'=principal.actor)||(again.%Get("sessionBinding")'=principal.sessionBinding) Return $$$OK
        // Exactly one ordinary proposal entry call. Its private worker re-reads
        // account/source and claims the already registered ID before inference.
        // Error/timeout is uncertain, never an automatic second call.
        Set sc=##class(Chronos.App.Entry).Call("PROPOSE",parent.orderId,parent.shipmentVersion,"",.proposed,requestId,parent.mode)
        If $$$ISERR(sc) {
            Set result={"code":"CLARIFIED_DECISION_PENDING","requestId":(requestId),"dispatch_authorized":false}
        } Else {
            Set result=proposed
        }
    } Catch ex {
        Set result={"code":"CLARIFIED_DECISION_UNAVAILABLE","requestId":(requestId),"dispatch_authorized":false}
    }
    Return $$$OK
}
}
