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
    // A completed Workflow task is read before bootLock, never while waiting
    // on a native Task owned by a completer that itself needs bootLock.
    // This read is not a grant: the private decision and current full authority
    // are compared again under bootLock before the one-use ledger CLAIM.
    Set clarified=0,prior="",fresh={}
    Set sc=##class(Chronos.Agent.Ledger).Apply("INSPECT",{"requestId":(requestId)},.initial)
    If $$$ISERR(sc) Return sc
    If initial.%GetTypeOf("private")="object" {
        Set seed=initial.private
        If (seed.%Get("state")="PREPARED")&&(seed.%GetTypeOf("prepared")="object") {
            If seed.prepared.%GetTypeOf("record")="object" {
                If seed.prepared.record.%IsDefined("clarification_binding")||seed.%IsDefined("clarificationAnchor") {
                    Set clarified=1,prior=seed.%ToJSON()
                    Set sc=##class(Chronos.Agent.Context).Reprepare(requestId,.fresh)
                    If $$$ISERR(sc) {
                        Set result={"code":"CLAIM_UNAVAILABLE","inferenceGranted":false,"dispatch_authorized":false}
                        Return sc
                    }
                }
            }
        }
    }
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
                Set hasReference=d.prepared.record.%IsDefined("clarification_binding")||d.%IsDefined("clarificationAnchor")
                If hasReference {
                    If 'clarified||(d.%ToJSON()'=prior) Throw ##class(%Exception.General).%New("CLARIFIED_DECISION_CHANGED")
                } Else {
                    If clarified Throw ##class(%Exception.General).%New("CLARIFICATION_DISAPPEARED")
                    Set sc=##class(Chronos.Agent.Context).Prepare(d.orderId,d.shipmentVersion,d.requestId,d.mode,.fresh)
                    $$$ThrowOnError(sc)
                }
                Set matched=0
                If fresh.status="READY" {
                    Set old=d.prepared.record,new=fresh.record
                    Set matched=(fresh.%Get("runtime_generation")=d.generation)&&(old.%Get("authority_stamp")=new.%Get("authority_stamp"))&&(old.%Get("facts_digest")=new.%Get("facts_digest"))&&(old.%Get("runtime_binding").%ToJSON()=new.%Get("runtime_binding").%ToJSON())
                    If hasReference,matched {
                        If (old.%GetTypeOf("clarification_binding")'="object")||(new.%GetTypeOf("clarification_binding")'="object") {
                            Set matched=0
                        } ElseIf old.%Get("clarification_binding").%ToJSON()'=new.%Get("clarification_binding").%ToJSON() {
                            Set matched=0
                        }
                        If matched {
                            Set sc=##class(Chronos.Authority.Store).Apply("READ",{"orderId":(d.orderId),"shipmentVersion":(d.shipmentVersion)},.authority)
                            $$$ThrowOnError(sc)
                            Set matched=..AuthorityMatches(new.%Get("authority_stamp"),authority.%ToJSON())
                        }
                    }
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

/// Full inference stamp, including the current observation nonce. The two
/// Workflow preference-renewal exclusions never apply to a model CLAIM.
ClassMethod AuthorityMatches(authorityStamp As %String, authorityJSON As %String) As %Boolean [ Language = python, Private ]
{
    import json
    from hashlib import sha256
    try:
        def pairs(items):
            out={}
            for key,value in items:
                if key in out:raise ValueError('DUPLICATE_FIELD')
                out[key]=value
            return out
        def invalid(_):raise ValueError('NONFINITE_JSON')
        def parse(raw):
            if type(raw) is not str or not 0<len(raw.encode('utf-8'))<=32768:raise ValueError('INVALID_JSON_SIZE')
            return json.loads(raw,object_pairs_hook=pairs,parse_constant=invalid)
        if type(authorityStamp) is not str or len(authorityStamp)!=64 or any(c not in '0123456789abcdef' for c in authorityStamp):return False
        authority=parse(authorityJSON)
        if type(authority) is not dict:return False
        if type(authority.get('effect')) is not dict or type(authority.get('operation')) is not dict:return False
        encoded=json.dumps({'effect':authority['effect'],'operation':authority['operation']},sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode('utf-8')
        return authorityStamp==sha256(encoded).hexdigest()
    except Exception:
        return False
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
