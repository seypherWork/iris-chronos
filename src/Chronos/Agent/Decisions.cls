Include %occStatus

/// Internal orchestration for the future AI Hub BO. No model call in this class.
/// Completion/Claim/Inspect are NOT public APIs. Caller identity is not auth.
Class Chronos.Agent.Decisions Extends %RegisteredObject
{
ClassMethod Prepare(requestId As %String, orderId As %String, version As %Integer, mode As %String, Output result As %DynamicObject, expectedGeneration As %String = "") As %Status
{
    Set sc=..Read(requestId,.result)
    If $$$ISERR(sc) Return sc
    If result.code'="NOT_FOUND" {
        If (result.orderId'=orderId)||(result.shipmentVersion'=version)||(result.mode'=mode) Return $$$ERROR($$$GeneralError,"REQUEST_ID_CONFLICT")
        If (expectedGeneration'="")&&(result.generation'=expectedGeneration) Return $$$ERROR($$$GeneralError,"STALE_REQUEST_GENERATION")
        Return $$$OK
    }
    Set sc=##class(Chronos.Agent.Context).Prepare(orderId,version,requestId,mode,.p,expectedGeneration)
    If $$$ISERR(sc) Set result=p Return sc
    If p.status="DETERMINISTIC",$ListFind($ListBuild("EXISTING_ACCEPTANCE","ACCEPTANCE_UNRESOLVED"),p.code) {
        Return ##class(Chronos.Agent.Ledger).Apply("RECORD_DETERMINISTIC",{"requestId":(requestId),"orderId":(orderId),"shipmentVersion":(version),"mode":(mode),"generation":(p.%Get("runtime_generation")),"result":(p)},.result)
    }
    If p.status'="READY" Set result=p Return $$$OK
    Return ##class(Chronos.Agent.Ledger).Apply("REGISTER",{"requestId":(requestId),"orderId":(orderId),"shipmentVersion":(version),"mode":(mode),"generation":(p.%Get("runtime_generation")),"prepared":(p)},.result)
}

ClassMethod Read(requestId As %String, Output result As %DynamicObject) As %Status
{
    Return ##class(Chronos.Agent.Ledger).Apply("READ",{"requestId":(requestId)},.result)
}

ClassMethod Claim(requestId As %String, Output result As %DynamicObject, expectedGeneration As %String = "") As %Status
{
    Set result={"code":"RUNTIME_NOT_READY","inferenceGranted":false,"dispatch_authorized":false}
    If $TLevel Return $$$ERROR($$$GeneralError,"DECISION_REQUIRES_NO_TRANSACTION")
    Lock +^ChronosRuntime("bootLock"):0
    If '$Test Return $$$OK
    Set sc=$$$OK
    Try {
        If expectedGeneration'="" {
            Set sc=##class(Chronos.Runtime.Bootstrap).Ready(.requestReady,expectedGeneration)
            $$$ThrowOnError(sc)
            If 'requestReady.ready Throw ##class(%Exception.General).%New("STALE_REQUEST_GENERATION")
        }
        Set sc=##class(Chronos.Agent.Ledger).Apply("INSPECT",{"requestId":(requestId)},.read)
        $$$ThrowOnError(sc)
        Set result=read
        If read.code'="NOT_FOUND" Set d=read.private
        Do result.%Remove("private")
        If read.code'="NOT_FOUND" {
            If (expectedGeneration'="")&&(d.generation'=expectedGeneration) Throw ##class(%Exception.General).%New("STALE_REQUEST_GENERATION")
            If d.state="PREPARED" {
                Set sc=##class(Chronos.Agent.Context).Prepare(d.orderId,d.shipmentVersion,d.requestId,d.mode,.fresh)
                $$$ThrowOnError(sc)
                Set matched=0
                If fresh.status="READY" {
                    Set old=d.prepared.record,new=fresh.record
                    Set matched=(fresh.%Get("runtime_generation")=d.generation)&&(old.%Get("authority_stamp")=new.%Get("authority_stamp"))&&(old.%Get("facts_digest")=new.%Get("facts_digest"))&&(old.%Get("runtime_binding").%ToJSON()=new.%Get("runtime_binding").%ToJSON())
                }
                If 'matched {
                    Set sc=##class(Chronos.Agent.Ledger).Apply("CANCEL",{"requestId":(requestId)},.result)
                } Else {
                    Set sc=##class(Chronos.Agent.Ledger).Apply("CLAIM",{"requestId":(requestId),"generation":(d.generation)},.result)
                }
                $$$ThrowOnError(sc)
            }
        }
    } Catch ex {
        Set result={"code":"CLAIM_UNAVAILABLE","inferenceGranted":false,"dispatch_authorized":false}
        Set sc=$$$ERROR($$$GeneralError,"CLAIM_UNAVAILABLE")
    }
    Lock -^ChronosRuntime("bootLock")
    Return sc
}

ClassMethod Finish(requestId As %String, claimId As %String, responseText As %String, providerStatus As %String, Output result As %DynamicObject) As %Status
{
    Set sc=##class(Chronos.Agent.Ledger).Apply("BEGIN_FINISH",{"requestId":(requestId),"claimId":(claimId)},.work)
    Set result=work
    If $$$ISERR(sc)||'work.validationGranted Return sc
    // Consume even malformed/oversized completions. A second response cannot
    // replace a failed first one. Do not persist or echo raw model text.
    Try {
        Set valid={"status":"ERROR","code":"INVALID_COMPLETION","dispatch_authorized":false}
        If ($Length($ZConvert(responseText,"O","UTF8"))<=4096)&&(",ok,timeout,refusal,error,"[(","_providerStatus_",")) {
            Set checked=##class(Chronos.Agent.Context).Finish(work.orderId,work.shipmentVersion,work.record,work.generation,responseText,providerStatus,.valid)
            If $$$ISERR(checked) Set valid={"status":"ERROR","code":"VALIDATION_UNAVAILABLE","dispatch_authorized":false}
        }
        Set sc=##class(Chronos.Agent.Ledger).Apply("COMPLETE",{"requestId":(requestId),"validationId":(work.validationId),"result":(valid)},.result)
    } Catch ex {
        Set result={"code":"VALIDATION_UNCERTAIN","inferenceGranted":false,"validationGranted":false,"dispatch_authorized":false}
        Set sc=$$$ERROR($$$GeneralError,"VALIDATION_UNCERTAIN")
    }
    Return sc
}

ClassMethod Recover(requestId As %String, Output result As %DynamicObject) As %Status
{
    Set result={"code":"RUNTIME_NOT_READY","inferenceGranted":false,"dispatch_authorized":false}
    Set sc=##class(Chronos.Runtime.Bootstrap).Ready(.ready)
    If $$$ISERR(sc)||'ready.ready Return sc
    Return ##class(Chronos.Agent.Ledger).Apply("RECOVER",{"requestId":(requestId),"generation":(ready.generation)},.result)
}

/// Explicit resolution, not read, provider cancellation or inference retry.
ClassMethod Resolve(requestId As %String, orderId As %String, version As %Integer, mode As %String, Output result As %DynamicObject, expectedGeneration As %String = "") As %Status
{
    Set result={"code":"RUNTIME_NOT_READY","inferenceGranted":false,"dispatch_authorized":false}
    Set sc=##class(Chronos.Runtime.Bootstrap).Ready(.ready,expectedGeneration)
    If $$$ISERR(sc)||'ready.ready Return sc
    Return ##class(Chronos.Agent.Ledger).Apply("RESOLVE",{"requestId":(requestId),"orderId":(orderId),"shipmentVersion":(version),"mode":(mode),"generation":(ready.generation)},.result)
}
}
