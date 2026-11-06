Include %occStatus

/// Application dispatcher core; internal authenticated/trusted callers only.
/// Actor is supplied by a future authenticated boundary, never by model output.
/// Fixed installed Provider injection is a composition responsibility, not a URL.
/// No automatic dispatch retry, timeout release, or implicit human approval.
Class Chronos.Recovery.Coordinator Extends %RegisteredObject
{
Property Provider As Chronos.Recovery.Provider [ Private ];

Method %OnNew(provider As Chronos.Recovery.Provider) As %Status
{
    If '$IsObject(provider) Return $$$ERROR($$$GeneralError,"TRUSTED_PROVIDER_REQUIRED")
    If 'provider.%IsA("Chronos.Recovery.Provider") Return $$$ERROR($$$GeneralError,"TRUSTED_PROVIDER_REQUIRED")
    Set ..Provider=provider
    Return $$$OK
}

/// Reserves once, releases the IRIS transaction, then attempts exactly one call.
/// Replay returns recorded state. It never calls Submit a second time.
Method Execute(approvalId As %String, actor As %String, Output result As %DynamicObject) As %Status
{
    Set result={"code":"NOT_DISPATCHED","dispatchGranted":false}
    Set sc=##class(Chronos.Authority.Store).Apply("RESERVE_BEGIN",{"approvalId":(approvalId),"actor":(actor)},.ticket)
    If $$$ISERR(sc) Return sc
    Return ..DispatchReservation(ticket,actor,.result)
}

/// Internal live continuation only, never a browser/deserialized ticket endpoint.
/// CONFIRM_RESERVE returns this private reservation once in the caller's process.
Method DispatchReservation(ticket As %DynamicObject, actor As %String, Output result As %DynamicObject) As %Status
{
    Set result={"code":"NOT_DISPATCHED","dispatchGranted":false}
    If '$IsObject(ticket) Return $$$ERROR($$$GeneralError,"RESERVATION_REQUIRED")
    If 'ticket.%IsA("%DynamicObject") Return $$$ERROR($$$GeneralError,"RESERVATION_REQUIRED")
    If ticket.%GetTypeOf("operationId")'="string" Return $$$ERROR($$$GeneralError,"RESERVATION_REQUIRED")
    Set operationId=ticket.operationId
    If 'ticket.%Get("reservationGranted") Return ..Finish(operationId,"EXISTING_OPERATION",.result)
    Try {
        If $TLevel Throw ##class(%Exception.General).%New("NO_TRANSACTION_DURING_IO")
        Set sc=##class(Chronos.Authority.Store).Apply("ADMIT",{"operationId":(operationId),"attemptId":(ticket.attemptId),"actor":(actor),"claimId":(ticket.claimId)},.admitted)
        $$$ThrowOnError(sc)
        If 'admitted.dispatchGranted Return ..Uncertain(operationId,.result)
        Return ..DispatchAdmitted(admitted,.result)
    } Catch ex {
        Return ..Uncertain(operationId,.result)
    }
}

/// Internal live continuation only. Never persist this grant in a message or
/// accept it from HTTP/READ. Caller releases lifecycle locks after ADMIT commit.
Method DispatchAdmitted(admitted As %DynamicObject, Output result As %DynamicObject) As %Status
{
    Set result={"code":"NOT_DISPATCHED","dispatchGranted":false}
    If '$IsObject(admitted) Return $$$ERROR($$$GeneralError,"ADMISSION_REQUIRED")
    If 'admitted.%IsA("%DynamicObject") Return $$$ERROR($$$GeneralError,"ADMISSION_REQUIRED")
    If (admitted.%GetTypeOf("dispatchGranted")'="boolean")||'admitted.%Get("dispatchGranted")||(admitted.%Get("code")'="DISPATCH_ADMITTED") Return $$$ERROR($$$GeneralError,"ADMISSION_REQUIRED")
    Set operationId=admitted.operationId
    Try {
        If $TLevel Throw ##class(%Exception.General).%New("NO_TRANSACTION_DURING_IO")
        Set expected=##class(%DynamicObject).%FromJSON(admitted.operation.%ToJSON())
        Set sc=..Provider.Submit(admitted.operation,admitted.ticket,.receipt)
        $$$ThrowOnError(sc)
        If '..Matches(receipt,expected) Throw ##class(%Exception.General).%New("RECEIPT_NOT_FOR_REQUEST")
        Set sc=##class(Chronos.Authority.Store).Apply("EVIDENCE",receipt,.recorded)
        $$$ThrowOnError(sc)
        Return ..Finish(operationId,"RESULT_RECORDED",.result)
    } Catch ex {
        // Do not expose provider responses, payloads or exception text.
        Return ..Uncertain(operationId,.result)
    }
}

/// Safe readback projection; no claim, admission grant or provider call.
ClassMethod Observe(operationId As %String, Output result As %DynamicObject) As %Status
{
    Return ..Finish(operationId,"READ_ONLY",.result)
}

/// Query only. This path cannot obtain a dispatch ticket or invoke Submit.
Method Reconcile(operationId As %String, Output result As %DynamicObject) As %Status
{
    Set result={"code":"NOT_RECONCILED","dispatchGranted":false}
    Set sc=##class(Chronos.Authority.Store).Apply("RECOVER",{"operationId":(operationId)},.recovered)
    If $$$ISERR(sc) Return sc
    Set sc=##class(Chronos.Authority.Store).Apply("READ_OPERATION",{"operationId":(operationId)},.read)
    If $$$ISERR(sc) Return sc
    Set expected=##class(%DynamicObject).%FromJSON(read.operation.%ToJSON())
    Try {
        If $TLevel Throw ##class(%Exception.General).%New("NO_TRANSACTION_DURING_IO")
        Set sc=..Provider.Query(read.operation,.receipt)
        $$$ThrowOnError(sc)
        If '..Matches(receipt,expected) Throw ##class(%Exception.General).%New("RECEIPT_NOT_FOR_REQUEST")
    } Catch ex {
        Return ..Uncertain(operationId,.result)
    }
    // Persistence/rejection errors are not disguised as provider uncertainty.
    // A recovery sweep must not ACK its page on an authority error.
    Set sc=##class(Chronos.Authority.Store).Apply("EVIDENCE",receipt,.recorded)
    If $$$ISERR(sc) Return sc
    Return ..Finish(operationId,"READBACK_RECORDED",.result)
}

Method Uncertain(operationId As %String, Output result As %DynamicObject) As %Status [ Private ]
{
    Set result={"code":"RECOVERY_REQUIRED","operationId":(operationId),"dispatchGranted":false}
    Set sc=##class(Chronos.Authority.Store).Apply("RECOVER",{"operationId":(operationId)},.recovered)
    If $$$ISERR(sc) Return sc
    Return ..Finish(operationId,"RESULT_UNCERTAIN",.result)
}

Method Matches(receipt As %DynamicObject, operation As %DynamicObject) As %Boolean [ Private ]
{
    If '$IsObject(receipt) Return 0
    If 'receipt.%IsA("%DynamicObject") Return 0
    For field="operationId","attemptId","orderId","shipmentVersion","target" {
        If receipt.%GetTypeOf(field)'=operation.%GetTypeOf(field) Return 0
        If receipt.%Get(field)'=operation.%Get(field) Return 0
    }
    Return 1
}

ClassMethod Finish(operationId As %String, code As %String, Output result As %DynamicObject) As %Status [ Private ]
{
    Set sc=##class(Chronos.Authority.Store).Apply("READ_OPERATION",{"operationId":(operationId)},.read)
    If $$$ISERR(sc) Return sc
    // Terminal evidence remains terminal even if a later query fails.
    If (code="RESULT_UNCERTAIN"),((read.operation.state="ACCEPTED")||(read.operation.state="NOT_ACCEPTED_FINAL")) Set code="TERMINAL_RESULT_PRESERVED"
    If read.effect.quarantined Set code="CONTRADICTORY_EVIDENCE"
    Set result={"code":(code),"operationId":(operationId),"attemptId":(read.operation.attemptId),"state":(read.operation.state),"reference":(read.operation.reference),"quarantined":(read.effect.quarantined),"dispatchGranted":false}
    Do result.%Set("quarantined",read.effect.quarantined,"boolean")
    Return $$$OK
}
}
