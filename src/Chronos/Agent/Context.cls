Include %occStatus

/// Internal stable-read bridge. Does not persist/consume a decision or invoke AI.
/// Caller is trusted native composition; no browser-supplied authority or roots.
Class Chronos.Agent.Context Extends %RegisteredObject
{
ClassMethod Prepare(orderId As %String, version As %Integer, contextId As %String, mode As %String, Output result As %DynamicObject, expectedGeneration As %String = "", clarificationId As %String = "") As %Status
{
    Set args={"contextId":(contextId),"mode":(mode)}
    If clarificationId'="" Set args.clarificationId=clarificationId
    Return ..Run("PREPARE",orderId,version,args,expectedGeneration,.result)
}

/// Native worker path. The new decision, not an HTTP/model-provided source,
/// supplies the immutable adoption anchor for the fresh PREPARE comparison.
ClassMethod Reprepare(requestId As %String, Output result As %DynamicObject) As %Status
{
    Set result={"status":"ERROR","code":"CLARIFIED_DECISION_UNAVAILABLE","dispatch_authorized":false}
    If $TLevel||'..ID(requestId) Return $$$ERROR($$$GeneralError,"INVALID_CLARIFIED_DECISION")
    Set sc=##class(Chronos.Agent.Ledger).Apply("INSPECT",{"requestId":(requestId)},.read) If $$$ISERR(sc) Return sc
    If read.%GetTypeOf("private")'="object" Return $$$OK
    Set d=read.private
    If (d.%Get("requestId")'=requestId)||(d.%Get("state")'="PREPARED") Return $$$OK
    If d.%GetTypeOf("prepared")'="object" Return $$$OK
    If d.prepared.%GetTypeOf("record")'="object" Return $$$OK
    If d.prepared.record.%GetTypeOf("clarification_binding")'="object" Return $$$OK
    Return ..Run("PREPARE",d.orderId,d.shipmentVersion,{"contextId":(d.requestId),"mode":(d.mode),"clarificationDecisionId":(d.requestId)},d.generation,.result)
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

ClassMethod ID(value As %String) As %Boolean [ Private ]
{
    Return ($Length(value)>0)&&($Length(value)<=128)&&($Translate(value,"abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.")="")
}

/// Resolve only identifiers. A raw source object in args is always forbidden.
/// FINISH's provisional wire context ID is merely a lookup key until its
/// complete record is compared with the PRIVATE ledger entry obtained here.
ClassMethod SourcePlan(command As %String, orderId As %String, version As %Integer, generation As %String, args As %DynamicObject, Output kind As %String, Output identifier As %String, Output clarificationId As %String) As %Status [ Private ]
{
    Set kind="",identifier="",clarificationId="",record="",decision=""
    If args.%IsDefined("clarificationSource") Return $$$ERROR($$$GeneralError,"CALLER_SOURCE_FORBIDDEN")
    If command="PREPARE" {
        If args.%IsDefined("clarificationId") {
            If args.%IsDefined("clarificationDecisionId") Return $$$ERROR($$$GeneralError,"AMBIGUOUS_CLARIFICATION_SOURCE")
            If (args.%GetTypeOf("clarificationId")'="string")||'..ID(args.clarificationId) Return $$$ERROR($$$GeneralError,"INVALID_CLARIFICATION_ID")
            Set kind="CSP",identifier=args.clarificationId,clarificationId=identifier
            Return $$$OK
        }
        If args.%IsDefined("clarificationDecisionId") {
            If (args.%GetTypeOf("clarificationDecisionId")'="string")||'..ID(args.clarificationDecisionId) Return $$$ERROR($$$GeneralError,"INVALID_CLARIFIED_DECISION")
            Set identifier=args.clarificationDecisionId
        }
    } ElseIf command="FINISH" {
        If args.%GetTypeOf("record")'="object" Return $$$OK
        Set record=args.record
        If 'record.%IsDefined("clarification_binding") Return $$$OK
        If (record.%GetTypeOf("clarification_binding")'="object")||(record.%GetTypeOf("wire")'="object") Return $$$ERROR($$$GeneralError,"INVALID_CLARIFICATION_REFERENCE")
        If (record.wire.%GetTypeOf("context_id")'="string")||'..ID(record.wire.%Get("context_id")) Return $$$ERROR($$$GeneralError,"INVALID_CLARIFIED_DECISION")
        Set identifier=record.wire.%Get("context_id")
    } ElseIf command="REVIEW" {
        If args.%GetTypeOf("decision")'="object" Return $$$OK
        Set decision=args.decision
        If decision.%GetTypeOf("prepared")'="object" Return $$$OK
        If decision.prepared.%GetTypeOf("record")'="object" Return $$$OK
        If 'decision.prepared.record.%IsDefined("clarification_binding") Return $$$OK
        If decision.prepared.record.%GetTypeOf("clarification_binding")'="object" Return $$$ERROR($$$GeneralError,"INVALID_CLARIFICATION_REFERENCE")
        If (decision.%GetTypeOf("requestId")'="string")||'..ID(decision.requestId) Return $$$ERROR($$$GeneralError,"INVALID_CLARIFIED_DECISION")
        Set identifier=decision.requestId
    }
    If identifier="" Return $$$OK
    Set sc=##class(Chronos.Agent.Ledger).Apply("INSPECT",{"requestId":(identifier)},.read) If $$$ISERR(sc) Return sc
    If read.%GetTypeOf("private")'="object" Return $$$ERROR($$$GeneralError,"CLARIFIED_DECISION_UNAVAILABLE")
    Set d=read.private
    If (d.%Get("requestId")'=identifier)||(d.%Get("orderId")'=orderId)||(d.%Get("shipmentVersion")'=version)||(d.%Get("generation")'=generation) Return $$$ERROR($$$GeneralError,"CLARIFIED_DECISION_SCOPE_MISMATCH")
    If (d.%GetTypeOf("prepared")'="object") Return $$$ERROR($$$GeneralError,"CLARIFIED_DECISION_UNAVAILABLE")
    If d.prepared.%GetTypeOf("record")'="object" Return $$$ERROR($$$GeneralError,"CLARIFIED_DECISION_UNAVAILABLE")
    Set privateRecord=d.prepared.record
    If privateRecord.%GetTypeOf("clarification_binding")'="object" Return $$$ERROR($$$GeneralError,"CLARIFICATION_ANCHOR_REQUIRED")
    If privateRecord.%Get("clarification_binding").%GetTypeOf("binding")'="object" Return $$$ERROR($$$GeneralError,"INVALID_CLARIFICATION_REFERENCE")
    Set clarificationId=privateRecord.%Get("clarification_binding").binding.%Get("clarification_id")
    If '..ID(clarificationId) Return $$$ERROR($$$GeneralError,"INVALID_CLARIFICATION_REFERENCE")
    If command="FINISH" {
        If (d.state'="VALIDATING")&&(d.state'="UNCERTAIN_VALIDATION") Return $$$ERROR($$$GeneralError,"PRIVATE_COMPLETION_NOT_VALIDATING")
        If privateRecord.%ToJSON()'=record.%ToJSON() Return $$$ERROR($$$GeneralError,"PRIVATE_COMPLETION_RECORD_CHANGED")
    } ElseIf command="REVIEW" {
        If (d.state'="COMPLETED")||(d.%ToJSON()'=decision.%ToJSON()) Return $$$ERROR($$$GeneralError,"PRIVATE_REVIEW_DECISION_CHANGED")
    } Else {
        If (d.state'="PREPARED")||(d.requestId'=args.contextId)||(d.mode'=args.mode) Return $$$ERROR($$$GeneralError,"PRIVATE_PREPARATION_CHANGED")
    }
    Set kind="DECISION"
    Return $$$OK
}

ClassMethod ReadSource(kind As %String, identifier As %String, clarificationId As %String, orderId As %String, version As %Integer, generation As %String, Output source As %DynamicObject) As %Status [ Private ]
{
    Set source={}
    If kind="CSP" {
        Set sc=##class(Chronos.Workflow.Store).ReadAdoptionSource(identifier,.source)
    } ElseIf kind="DECISION" {
        Set sc=##class(Chronos.Workflow.Store).SourceForDecision(identifier,.source)
    } Else { Return $$$ERROR($$$GeneralError,"INVALID_CLARIFICATION_SOURCE_KIND") }
    If $$$ISERR(sc) Return sc
    If '$IsObject(source) Return $$$ERROR($$$GeneralError,"CLARIFICATION_SOURCE_UNAVAILABLE")
    If 'source.%IsA("%DynamicObject") Return $$$ERROR($$$GeneralError,"CLARIFICATION_SOURCE_UNAVAILABLE")
    If source.%Size()'=3 Return $$$ERROR($$$GeneralError,"CLARIFICATION_SOURCE_UNAVAILABLE")
    For field="record","expected_binding","native_completion" {
        If source.%GetTypeOf(field)'="object" Return $$$ERROR($$$GeneralError,"CLARIFICATION_SOURCE_UNAVAILABLE")
    }
    Set binding=source.%Get("expected_binding")
    If (binding.%Get("clarification_id")'=clarificationId)||(binding.%Get("order_id")'=orderId)||(binding.%Get("shipment_version")'=version) Return $$$ERROR($$$GeneralError,"CLARIFICATION_SOURCE_SCOPE_MISMATCH")
    If (generation'="")&&(binding.%Get("generation")'=generation) Return $$$ERROR($$$GeneralError,"CLARIFICATION_SOURCE_SCOPE_MISMATCH")
    Return $$$OK
}

ClassMethod Run(command As %String, orderId As %String, version As %Integer, args As %DynamicObject, generation As %String, Output result As %DynamicObject) As %Status [ Private ]
{
    Set result={"status":"RECHECK_REQUIRED","code":"RUNTIME_NOT_READY","dispatch_authorized":false}
    If $TLevel Return $$$ERROR($$$GeneralError,"AGENT_REQUIRES_NO_TRANSACTION")
    // Workflow readers acquire a retained Task reference before bootLock. Do
    // not invert that order while a completer owns Task and needs bootLock.
    Set kind="",identifier="",clarificationId="",sourceBefore={},stable=0
    Try {
        Set sc=..SourcePlan(command,orderId,version,generation,args,.kind,.identifier,.clarificationId) $$$ThrowOnError(sc)
        If kind'="" {
            Set sc=..ReadSource(kind,identifier,clarificationId,orderId,version,generation,.sourceBefore) $$$ThrowOnError(sc)
        }
    } Catch sourceError {
        Set result={"status":"ERROR","code":"CLARIFICATION_SOURCE_UNAVAILABLE","dispatch_authorized":false}
        Return $$$ERROR($$$GeneralError,"CLARIFICATION_SOURCE_UNAVAILABLE")
    }
    Lock +^ChronosRuntime("bootLock"):0
    If '$Test Return $$$OK
    Set sc=$$$OK
    Try {
        Set sc=##class(Chronos.Runtime.Bootstrap).Ready(.ready,generation)
        $$$ThrowOnError(sc)
        If ready.ready {
            If kind'="" {
                If sourceBefore.%Get("expected_binding").%Get("generation")'=ready.generation Throw ##class(%Exception.General).%New("CLARIFICATION_GENERATION_CHANGED")
            }
            Set config=##class(%DynamicObject).%FromJSON(^ChronosRuntime("config"))
            Set query={"orderId":(orderId),"shipmentVersion":(version)}
            Set sc=##class(Chronos.Authority.Store).Apply("READ",query,.before)
            $$$ThrowOnError(sc)
            Set args.authority=before,args.orderId=orderId,args.responseContract=##class(Chronos.Agent.Model).Contract()
            If kind'="" Set args.clarificationSource=sourceBefore
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
                    Set stable=1
                }
            }
        }
    } Catch ex {
        Set result={"status":"ERROR","code":"AGENT_CONTEXT_UNAVAILABLE","dispatch_authorized":false}
        Set sc=$$$ERROR($$$GeneralError,"AGENT_CONTEXT_UNAVAILABLE")
    }
    Lock -^ChronosRuntime("bootLock")
    If (kind'="")&&stable&&$$$ISOK(sc) {
        Set relocked=0
        Try {
            Set sc=..ReadSource(kind,identifier,clarificationId,orderId,version,ready.generation,.sourceAfter) $$$ThrowOnError(sc)
            If sourceBefore.%ToJSON()'=sourceAfter.%ToJSON() {
                Set result={"status":"RECHECK_REQUIRED","code":"CLARIFICATION_CHANGED_DURING_READ","dispatch_authorized":false}
            } Else {
                // Close the brief gap left by reading Workflow outside boot.
                // This does not make the separate stores a single transaction.
                Lock +^ChronosRuntime("bootLock"):0 If '$Test Throw ##class(%Exception.General).%New("RUNTIME_BUSY")
                Set relocked=1
                Set sc=##class(Chronos.Runtime.Bootstrap).Ready(.lastReady,ready.generation) $$$ThrowOnError(sc)
                Set sc=##class(Chronos.Authority.Store).Apply("READ",query,.lastAuthority) $$$ThrowOnError(sc)
                If 'lastReady.ready||(lastAuthority.%ToJSON()'=before.%ToJSON()) {
                    Set result={"status":"RECHECK_REQUIRED","code":"AUTHORITY_CHANGED_DURING_READ","dispatch_authorized":false}
                }
            }
        } Catch sourceError {
            Set result={"status":"ERROR","code":"CLARIFICATION_RECHECK_UNAVAILABLE","dispatch_authorized":false}
            Set sc=$$$ERROR($$$GeneralError,"CLARIFICATION_RECHECK_UNAVAILABLE")
        }
        If relocked Lock -^ChronosRuntime("bootLock")
    }
    Return sc
}
}
