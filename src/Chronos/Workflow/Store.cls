Include %occStatus

/// Trusted native composition only. No HTTP authentication or recovery authority.
/// Workflow callbacks alone remain UNVERIFIED. A separate original-CSP
/// completion may attach native actor/time evidence; it never approves a send.
Class Chronos.Workflow.Store Extends %RegisteredObject
{
Parameter ROLE = "Chronos.Clarifiers";
Parameter AUTHORITYSCHEME = "chronos.workflow-material-authority.v1";

ClassMethod ID(value As %String) As %Boolean
{
    Return ($Length(value)>0)&&($Length(value)<=128)&&($Translate(value,"abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.")="")
}

ClassMethod NativeID(value As %String) As %Boolean [ Private ]
{
    Return ($Length(value)>0)&&($Length(value)<=18)&&($Translate(value,"0123456789")="")&&(value>0)
}

ClassMethod Digest(value As %String) As %String [ Private ]
{
    Return $ZConvert(##class(%xsd.hexBinary).LogicalToXSD($System.Encryption.SHAHash(256,value)),"L")
}

ClassMethod Hash(value As %String) As %Boolean [ Private ]
{
    Return ($Length(value)=64)&&($Translate(value,"0123456789abcdef")="")
}

/// Exact material contract shared with the pure clarification adapter. This is
/// correlation/integrity, never authentication or shipment consent. Exclude
/// only the effect's observation nonce and its snapshot observation time;
/// operation identity/state and every business constraint remain unchanged.
ClassMethod AuthorityMaterialDigest(authorityJSON As %String) As %String [ Language = python, Private ]
{
    import json
    from copy import deepcopy
    from hashlib import sha256
    try:
        if type(authorityJSON) is not str or not 0<len(authorityJSON.encode('utf-8'))<=65536:return ''
        def pairs(items):
            out={}
            for key,value in items:
                if key in out:raise ValueError('DUPLICATE_AUTHORITY_FIELD')
                out[key]=value
            return out
        def invalid(_):raise ValueError('NONFINITE_AUTHORITY_JSON')
        a=json.loads(authorityJSON,object_pairs_hook=pairs,parse_constant=invalid)
        if type(a) is not dict or type(a.get('effect')) is not dict or type(a.get('operation')) is not dict:return ''
        effect=deepcopy(a['effect'])
        if type(effect.get('snapshot')) is not dict or 'observedAt' not in effect['snapshot']:return ''
        del effect['snapshotId']
        del effect['snapshot']['observedAt']
        encoded=json.dumps({'effect':effect,'operation':a['operation']},sort_keys=True,
            ensure_ascii=False,separators=(',',':'),allow_nan=False).encode('utf-8')
        return sha256(encoded).hexdigest()
    except Exception:
        return ''
}

ClassMethod View(record As %DynamicObject, code As %String) As %DynamicObject [ Private ]
{
    Set out={"code":(code),"handoffGranted":false,"actorVerified":false,"completionVerified":false,"canUseClarification":false,"completionRecorded":false,"dispatch_authorized":false}
    For field="clarificationId","decisionId","orderId","shipmentVersion","generation","state","requestedUS","expiresUS","taskRequestId","taskId" {
        If record.%IsDefined(field) Do out.%Set(field,record.%Get(field),record.%GetTypeOf(field))
    }
    // Historical metadata only. This is not a fresh task/account read or an
    // adoption grant. New decisions still re-read the complete native proof.
    Set historical=..ResolutionView(record)
    If historical.%Get("code")="WORKFLOW_CLARIFICATION_RECORDED" Do out.%Set("completionRecorded",1,"boolean")
    Return out
}

/// Pure eligibility/expiry check; this is NOT authentication or a fresh read.
/// The caller below obtains d only from the private native decision ledger.
ClassMethod Eligible(d As %DynamicObject, requestedUS As %Numeric, Output out As %DynamicObject) As %Status
{
    Set out={"code":"WORKFLOW_SOURCE_NOT_ELIGIBLE","dispatch_authorized":false}
    Try {
        If '$IsObject(d) Return $$$OK
        If 'd.%IsA("%DynamicObject") Return $$$OK
        If d.%Get("state")'="COMPLETED" Return $$$OK
        If (d.%GetTypeOf("result")'="object")||(d.%GetTypeOf("prepared")'="object") Return $$$OK
        Set r=d.result
        If (r.%Get("status")'="VALIDATED_HOLD")||(r.%GetTypeOf("dispatch_authorized")'="boolean")||r.%Get("dispatch_authorized") Return $$$OK
        If r.%GetTypeOf("proposal")'="object" Return $$$OK
        Set proposal=r.proposal
        If proposal.%Get("action")'="HOLD" Return $$$OK
        If '$ListFind($ListBuild("CONTEXT_AMBIGUOUS","CONTEXT_INCOMPLETE"),proposal.%Get("reason_code")) Return $$$OK
        If d.prepared.%GetTypeOf("record")'="object" Return $$$OK
        Set p=d.prepared.record
        If p.%GetTypeOf("wire")'="object" Return $$$OK
        Set w=p.wire
        If (w.%GetTypeOf("facts")'="object")||(w.facts.%Get("preference_mode")'="CONTEXT_REQUIRED") Return $$$OK
        // The verified human message must fit without dropping any original
        // evidence or enlarging the eight-message inference contract.
        If w.facts.%GetTypeOf("messages")'="array" Return $$$OK
        If w.facts.messages.%Size()>=8 Return $$$OK
        For field="requestId","orderId","generation" {
            If (d.%GetTypeOf(field)'="string")||'..ID(d.%Get(field)) Return $$$OK
        }
        If (d.%GetTypeOf("shipmentVersion")'="number")||(d.shipmentVersion<1)||(d.shipmentVersion'=(d.shipmentVersion\1)) Return $$$OK
        If (w.%Get("context_id")'=d.requestId)||(w.%Get("order_id")'=d.orderId)||(w.%Get("shipment_version")'=d.shipmentVersion) Return $$$OK
        If (w.%Get("clock_kind")'="relative_microseconds")||(w.%Get("ticks_per_minute")'=60000000) Return $$$OK
        For field="utc_origin_us","state_revision","policy_revision" {
            If (w.%GetTypeOf(field)'="number")||(w.%Get(field)<0)||(w.%Get(field)'=(w.%Get(field)\1)) Return $$$OK
        }
        For field="facts_id","context_digest" { If (w.%GetTypeOf(field)'="string")||'..Hash(w.%Get(field)) Return $$$OK }
        If (p.%GetTypeOf("facts_digest")'="string")||'..Hash(p.%Get("facts_digest")) Return $$$OK
        For field="deadline","inventory_expires","offer_until" {
            If (w.facts.%GetTypeOf(field)'="number")||(w.facts.%Get(field)<0)||(w.facts.%Get(field)'=(w.facts.%Get(field)\1)) Return $$$OK
        }
        If (requestedUS<0)||(requestedUS'=(requestedUS\1)) Return $$$OK
        If (d.%GetTypeOf("completedUS")'="number")||(requestedUS<d.completedUS) Return $$$OK
        Set expires=requestedUS+600000000
        For field="deadline","inventory_expires","offer_until" {
            Set bound=w.%Get("utc_origin_us")+w.facts.%Get(field)
            If bound<expires Set expires=bound
        }
        // Never use the inference wire.valid_until or its 30-second deadline.
        If expires<=requestedUS { Set out.code="WORKFLOW_SOURCE_EXPIRED" Return $$$OK }
        Set out={"code":"WORKFLOW_SOURCE_ELIGIBLE","decisionId":(d.requestId),"orderId":(d.orderId),"shipmentVersion":(d.shipmentVersion),"generation":(d.generation),"sourceDecisionSha256":(..Digest(d.%ToJSON())),"sourceContextDigest":(w.%Get("context_digest")),"sourceFactsId":(w.%Get("facts_id")),"sourceFactsDigest":(p.%Get("facts_digest")),"utcOriginUS":(w.%Get("utc_origin_us")),"requestedUS":(requestedUS),"expiresUS":(expires),"dispatch_authorized":false}
    } Catch ex {
        Set out={"code":"WORKFLOW_SOURCE_NOT_ELIGIBLE","dispatch_authorized":false}
    }
    Return $$$OK
}

/// Caller owns bootLock, outside a transaction. Provider facts are not read by
/// this handoff-only piece; a future adoption path must revalidate them afresh.
ClassMethod Source(decisionId As %String, requestedUS As %Numeric, Output out As %DynamicObject) As %Status [ Private ]
{
    Set out={"code":"WORKFLOW_SOURCE_UNAVAILABLE","dispatch_authorized":false}
    Set sc=##class(Chronos.Agent.Ledger).Apply("INSPECT",{"requestId":(decisionId)},.read) If $$$ISERR(sc) Return sc
    If read.%GetTypeOf("private")'="object" Return $$$OK
    Set d=read.private
    Set sc=..Eligible(d,requestedUS,.out) If $$$ISERR(sc) Return sc
    If out.code'="WORKFLOW_SOURCE_ELIGIBLE" Return $$$OK
    Set sc=##class(Chronos.Runtime.Bootstrap).Ready(.ready,d.generation) If $$$ISERR(sc) Return sc
    If 'ready.ready { Set out={"code":"RUNTIME_NOT_READY","dispatch_authorized":false} Return $$$OK }
    Set sc=##class(Chronos.Authority.Store).Apply("READ",{"orderId":(d.orderId),"shipmentVersion":(d.shipmentVersion)},.current) If $$$ISERR(sc) Return sc
    Try {
        If (current.%GetTypeOf("effect")'="object")||(current.%GetTypeOf("operation")'="object") Throw ##class(%Exception.General).%New("NO_AUTHORITY")
        Set effect=current.effect,operation=current.operation,w=d.prepared.record.wire,snapshot=effect.snapshot
        If effect.quarantined||(effect.state'="OPEN")||(operation.state'="NOT_ACCEPTED_FINAL") Throw ##class(%Exception.General).%New("SOURCE_BLOCKED")
        If (operation.orderId'=d.orderId)||(operation.shipmentVersion'=d.shipmentVersion)||(effect.currentOperationId'=operation.operationId) Throw ##class(%Exception.General).%New("WRONG_OPERATION")
        If (snapshot.orderId'=d.orderId)||(snapshot.shipmentVersion'=d.shipmentVersion)||(snapshot.revision'=w.%Get("state_revision"))||(snapshot.policyRevision'=w.%Get("policy_revision")) Throw ##class(%Exception.General).%New("SOURCE_CHANGED")
        // Human preference is not approval for a particular snapshot nonce.
        // Compare every material field with the ORIGINAL immutable HOLD below.
        Set epoch=$ZDateH("1970-01-01",3)*86400
        If (snapshot.maxCost'=w.facts.budget)||(((snapshot.deliveryDeadline-epoch)*1000000)'=(w.%Get("utc_origin_us")+w.facts.deadline))||(((snapshot.inventoryUntil-epoch)*1000000)'=(w.%Get("utc_origin_us")+w.facts.%Get("inventory_expires"))) Throw ##class(%Exception.General).%New("CONSTRAINTS_CHANGED")
        For target="A","B" {
            Set offer=snapshot.offers.%Get(target),option=w.facts.options.%Get(target)
            If (offer.cost'=option.cost)||(((offer.availableAt-epoch)*1000000)'=(w.%Get("utc_origin_us")+option.%Get("available_at")))||((offer.queueSeconds*1000000)'=option.%Get("queue_duration"))||((offer.travelSeconds*1000000)'=option.%Get("travel_duration"))||(((offer.validUntil-epoch)*1000000)'=(w.%Get("utc_origin_us")+w.facts.%Get("offer_until"))) Throw ##class(%Exception.General).%New("OFFER_CHANGED")
        }
        // Same two exclusions as review_authority_stamp. A refresh cannot
        // renew actor, generation, facts, policy or the original human expiry.
        If (d.prepared.record.%GetTypeOf("review_authority_stamp")'="string")||'..Hash(d.prepared.record.%Get("review_authority_stamp")) Throw ##class(%Exception.General).%New("ORIGINAL_AUTHORITY_MATERIAL_UNAVAILABLE")
        Set material=..AuthorityMaterialDigest(current.%ToJSON())
        If '..Hash(material)||(material'=d.prepared.record.%Get("review_authority_stamp")) Throw ##class(%Exception.General).%New("ORIGINAL_AUTHORITY_MATERIAL_CHANGED")
        Set out.authorityDigest=material,out.authorityScheme=..#AUTHORITYSCHEME
        Do out.%Set("providerFactsVerified",0,"boolean")
    } Catch ex {
        Set out={"code":"WORKFLOW_SOURCE_CHANGED","dispatch_authorized":false}
    }
    Return $$$OK
}

/// Retain the decision mutex until the commit's journal barrier is confirmed.
ClassMethod Save(record As %DynamicObject, command As %String, now As %Numeric, index As %Boolean = 0) As %Status [ Private ]
{
    If $TLevel Return $$$ERROR($$$GeneralError,"WORKFLOW_REQUIRES_NO_TRANSACTION")
    Set sc=##class(Chronos.Runtime.Durability).Check() If $$$ISERR(sc) Return sc
    If now<$Get(^ChronosDecision16("clarification","clockHighWater"),0) Return $$$ERROR($$$GeneralError,"WORKFLOW_CLOCK_MOVED_BACKWARD")
    Set encoded=record.%ToJSON()
    If $Length($ZConvert(encoded,"O","UTF8"))>32768 Return $$$ERROR($$$GeneralError,"WORKFLOW_RECORD_TOO_LARGE")
    Set committed=0
    Try {
        TStart
        Set ^ChronosDecision16("clarification","item",record.clarificationId)=encoded
        If index Set ^ChronosDecision16("clarification","byDecision",record.decisionId)=record.clarificationId
        Set sequence=$Increment(^ChronosDecision16("clarification","sequence"))
        Set ^ChronosDecision16("clarification","audit",sequence)={"command":(command),"clarificationId":(record.clarificationId),"state":(record.state),"atUS":(now)}.%ToJSON()
        Set ^ChronosDecision16("clarification","clockHighWater")=now
        TCommit
        Set committed=1
        // Flush failure leaves the durable fence uncertain and consumable only
        // by inspection. It must never issue a second handoff grant.
        Return ##class(Chronos.Runtime.Durability).Flush()
    } Catch ex {
        If $TLevel TRollback
        Return $$$ERROR($$$GeneralError,$Select(committed:"WORKFLOW_DURABILITY_UNCERTAIN",1:"WORKFLOW_WRITE_FAILED"))
    }
}

/// One durable handoff fence per immutable HOLD. This is not a shipment grant.
ClassMethod Claim(decisionId As %String, Output result As %DynamicObject) As %Status
{
    Set result={"code":"WORKFLOW_UNAVAILABLE","handoffGranted":false,"actorVerified":false,"completionVerified":false,"canUseClarification":false,"dispatch_authorized":false}
    If $TLevel||'..ID(decisionId) Return $$$ERROR($$$GeneralError,"INVALID_WORKFLOW_REQUEST")
    Lock +^ChronosRuntime("bootLock"):2 If '$Test Return $$$ERROR($$$GeneralError,"RUNTIME_BUSY")
    Set sc=$$$OK,locked=0
    Try {
        If '##class(EnsLib.Workflow.RoleDefinition).%ExistsId(..#ROLE) { Set result.code="WORKFLOW_NOT_CONFIGURED" }
        Else {
            Set now=##class(Chronos.Agent.Ledger).NowUS()
            Set sc=..Source(decisionId,now,.source) $$$ThrowOnError(sc)
            If source.code'="WORKFLOW_SOURCE_ELIGIBLE" { Set result.code=source.code }
            Else {
                Lock +^ChronosDecision16("mutex"):2 If '$Test Throw ##class(%Exception.General).%New("WORKFLOW_BUSY")
                Set locked=1,existing=$Get(^ChronosDecision16("clarification","byDecision",decisionId))
                If existing'="" {
                    Set raw=$Get(^ChronosDecision16("clarification","item",existing))
                    If raw="" Throw ##class(%Exception.General).%New("WORKFLOW_CORRELATION_MISSING")
                    Set record=##class(%DynamicObject).%FromJSON(raw)
                    If (record.decisionId'=decisionId)||(record.clarificationId'=existing) Throw ##class(%Exception.General).%New("WORKFLOW_CORRELATION_MISMATCH")
                    If (record.%GetTypeOf("authorityScheme")'="string")||(record.%Get("authorityScheme")'=..#AUTHORITYSCHEME) {
                        Set result=..View(record,"WORKFLOW_SOURCE_UNAVAILABLE")
                    } Else { Set result=..View(record,"WORKFLOW_EXISTING_HANDOFF") }
                } Else {
                    Set raw=$Get(^ChronosDecision16("decision",decisionId))
                    If raw="" Throw ##class(%Exception.General).%New("SOURCE_DISAPPEARED")
                    Set reread=##class(%DynamicObject).%FromJSON(raw)
                    If ..Digest(reread.%ToJSON())'=source.sourceDecisionSha256 Throw ##class(%Exception.General).%New("SOURCE_CHANGED")
                    Set id=$System.Util.CreateGUID()
                    If '..ID(id) Throw ##class(%Exception.General).%New("INVALID_GENERATED_ID")
                    If $Data(^ChronosDecision16("clarification","item",id)) Throw ##class(%Exception.General).%New("WORKFLOW_ID_COLLISION")
                    Set record=##class(%DynamicObject).%FromJSON(source.%ToJSON())
                    Do record.%Remove("code")
                    Set record.schema="chronos.workflow-handoff.v1",record.clarificationId=id,record.role=..#ROLE,record.state="SEND_FENCED",record.taskRequestId="",record.taskId=""
                    Do record.%Set("actorVerified",0,"boolean"),record.%Set("completionVerified",0,"boolean"),record.%Set("canUseClarification",0,"boolean")
                    Set sc=..Save(record,"FENCE_HANDOFF",now,1) $$$ThrowOnError(sc)
                    Set result=..View(record,"WORKFLOW_HANDOFF_FENCED")
                    Do result.%Set("handoffGranted",1,"boolean")
                }
            }
        }
    } Catch ex {
        If $TLevel TRollback
        Set result={"code":"WORKFLOW_HANDOFF_UNCERTAIN","handoffGranted":false,"actorVerified":false,"completionVerified":false,"canUseClarification":false,"dispatch_authorized":false}
        Set sc=$$$ERROR($$$GeneralError,"WORKFLOW_HANDOFF_UNCERTAIN")
    }
    If locked Lock -^ChronosDecision16("mutex")
    Lock -^ChronosRuntime("bootLock")
    Return sc
}

/// Internal inspection only; never return record/envelope directly from HTTP.
ClassMethod Inspect(clarificationId As %String, Output result As %DynamicObject) As %Status
{
    Set result={"code":"WORKFLOW_NOT_FOUND","dispatch_authorized":false}
    If $TLevel||'..ID(clarificationId) Return $$$ERROR($$$GeneralError,"INVALID_WORKFLOW_ID")
    Lock +^ChronosDecision16("mutex"):2 If '$Test Return $$$ERROR($$$GeneralError,"WORKFLOW_BUSY")
    Set sc=$$$OK
    Try {
        Set raw=$Get(^ChronosDecision16("clarification","item",clarificationId))
        If raw'="" {
            Set record=##class(%DynamicObject).%FromJSON(raw)
            If record.clarificationId'=clarificationId Throw ##class(%Exception.General).%New("BAD_RECORD")
            Set result=..View(record,"WORKFLOW_RECORDED"),result.record=record
        }
    } Catch ex { Set sc=$$$ERROR($$$GeneralError,"WORKFLOW_READ_UNAVAILABLE") }
    Lock -^ChronosDecision16("mutex")
    Return sc
}

ClassMethod AttachRequest(clarificationId As %String, taskRequestId As %String, Output result As %DynamicObject) As %Status
{
    If '..NativeID(taskRequestId) Return $$$ERROR($$$GeneralError,"INVALID_WORKFLOW_TASK_REQUEST")
    Return ..Change("ATTACH_REQUEST",clarificationId,{"taskRequestId":(taskRequestId)},.result)
}

ClassMethod Sent(clarificationId As %String, Output result As %DynamicObject) As %Status
{
    Return ..Change("SENT",clarificationId,{},.result)
}

ClassMethod Uncertain(clarificationId As %String, Output result As %DynamicObject) As %Status
{
    Return ..Change("UNCERTAIN",clarificationId,{},.result)
}

ClassMethod Expire(clarificationId As %String, Output result As %DynamicObject) As %Status
{
    Return ..Change("EXPIRE",clarificationId,{},.result)
}

/// Reload the real saved response. No actor is accepted from a queued envelope.
/// Even complete/consistent native metadata does NOT verify current CSP rights.
ClassMethod RecordResponse(clarificationId As %String, taskId As %String, Output result As %DynamicObject) As %Status
{
    Set result={"code":"WORKFLOW_RESPONSE_UNAVAILABLE","actorVerified":false,"completionVerified":false,"canUseClarification":false,"dispatch_authorized":false}
    If $TLevel||'..NativeID(taskId) Return $$$ERROR($$$GeneralError,"INVALID_WORKFLOW_TASK")
    Try {
        Set task=##class(EnsLib.Workflow.TaskResponse).%OpenId(taskId)
        If '$IsObject(task) Throw ##class(%Exception.General).%New("NO_TASK")
        If '$IsObject(task.%TaskStatus)||'$IsObject(task.%TaskStatus.Request)||'$IsObject(task.%TaskStatus.Role) Throw ##class(%Exception.General).%New("NO_STATUS")
        Set request=task.%TaskStatus.Request,requestId=request.%Id()
        If '..NativeID(requestId)||'..ID(request.%Command) Throw ##class(%Exception.General).%New("BAD_TASK_REQUEST")
        If (request.%Command'=clarificationId)||(task.%TaskStatus.Role.Name'=..#ROLE) Throw ##class(%Exception.General).%New("WRONG_TASK")
        If 'task.%TaskStatus.IsComplete Throw ##class(%Exception.General).%New("INCOMPLETE_TASK")
        If '$ListFind($ListBuild("Clarified","UnableToClarify"),task.%Action) Throw ##class(%Exception.General).%New("UNSUPPORTED_ACTION")
        Set user=task.%UserName,actor=""
        If (user'="")&&($ZConvert(user,"L")'="unknownuser") Set actor="principal-"_..Digest($ListBuild($Namespace,user))
        Set created=task.%TaskStatus.TimeCreated,completed=task.%TaskStatus.TimeCompleted
        If ($Length(created)>64)||($Length(completed)>64) Throw ##class(%Exception.General).%New("BAD_NATIVE_TIME")
        Set preference=task.%FormValues.GetAt("Preference"),note=task.%FormValues.GetAt("Note"),acceptedPreference=""
        If $ListFind($ListBuild("EARLIEST_ALLOWED","CHEAPEST_ON_TIME"),preference) Set acceptedPreference=preference
        If $Length($ZConvert(note,"O","UTF8"))>4096 Throw ##class(%Exception.General).%New("FORM_TOO_LARGE")
        // Do not copy unverified note text, identity or task messages into logs.
        Set envelope={"schema":"chronos.workflow-native-envelope.v1","taskId":(taskId),"taskRequestId":(requestId),"role":(..#ROLE),"action":(task.%Action),"reportedActor":(actor),"timeCreatedUTC":(created),"timeCompletedUTC":(completed),"preference":(acceptedPreference),"noteSha256":(..Digest($ZConvert(note,"O","UTF8"))),"noteBytes":($Length($ZConvert(note,"O","UTF8")))}
        Do envelope.%Set("isComplete",1,"boolean")
        Return ..Change("RESPONSE",clarificationId,{"taskRequestId":(requestId),"taskId":(taskId),"envelope":(envelope)},.result)
    } Catch ex {
        Return $$$ERROR($$$GeneralError,"WORKFLOW_RESPONSE_UNVERIFIED")
    }
}

/// Queue callbacks are trusted native composition, but cannot accept actor
/// proof, resolve consent, retry inference or dispatch a recovery.
ClassMethod Change(command As %String, clarificationId As %String, args As %DynamicObject, Output result As %DynamicObject) As %Status [ Private ]
{
    Set result={"code":"WORKFLOW_NOT_APPLIED","handoffGranted":false,"actorVerified":false,"completionVerified":false,"canUseClarification":false,"dispatch_authorized":false}
    If $TLevel||'..ID(clarificationId) Return $$$ERROR($$$GeneralError,"INVALID_WORKFLOW_ID")
    If '$ListFind($ListBuild("ATTACH_REQUEST","SENT","UNCERTAIN","EXPIRE","RESPONSE"),command) Return $$$ERROR($$$GeneralError,"INVALID_WORKFLOW_COMMAND")
    Lock +^ChronosDecision16("mutex"):2 If '$Test Return $$$ERROR($$$GeneralError,"WORKFLOW_BUSY")
    Set sc=$$$OK
    Try {
        Set raw=$Get(^ChronosDecision16("clarification","item",clarificationId))
        If raw'="" {
            Set record=##class(%DynamicObject).%FromJSON(raw),now=##class(Chronos.Agent.Ledger).NowUS()
            If record.clarificationId'=clarificationId Throw ##class(%Exception.General).%New("BAD_RECORD")
            If command="ATTACH_REQUEST" {
                If record.state'="SEND_FENCED" Throw ##class(%Exception.General).%New("FENCE_REQUIRED")
                If record.taskRequestId'="",record.taskRequestId'=args.taskRequestId Throw ##class(%Exception.General).%New("REQUEST_ALREADY_BOUND")
                If now'<record.expiresUS Throw ##class(%Exception.General).%New("HANDOFF_EXPIRED")
                Set task=##class(EnsLib.Workflow.TaskRequest).%OpenId(args.taskRequestId)
                If '$IsObject(task)||(task.%Command'=clarificationId) Throw ##class(%Exception.General).%New("WRONG_NATIVE_REQUEST")
                Set record.taskRequestId=args.taskRequestId
            } ElseIf command="SENT" {
                If (record.state'="SEND_FENCED")||(record.taskRequestId="") Throw ##class(%Exception.General).%New("FENCE_REQUIRED")
                Set record.state="SENT"
            } ElseIf command="UNCERTAIN" {
                If '$ListFind($ListBuild("RESPONSE_UNVERIFIED","EXPIRED"),record.state) Set record.state="CREATION_UNCERTAIN"
            } ElseIf command="EXPIRE" {
                If now<record.expiresUS Throw ##class(%Exception.General).%New("NOT_EXPIRED")
                If record.state'="RESPONSE_UNVERIFIED" Set record.state="EXPIRED"
            } Else {
                If (record.taskRequestId="")||(record.taskRequestId'=args.taskRequestId) Throw ##class(%Exception.General).%New("RESPONSE_CORRELATION_MISMATCH")
                If (record.taskId'="")&&(record.taskId'=args.taskId) Throw ##class(%Exception.General).%New("RESPONSE_ALREADY_BOUND")
                If record.%IsDefined("envelope") {
                    If record.envelope.%ToJSON()'=args.envelope.%ToJSON() Throw ##class(%Exception.General).%New("RESPONSE_CHANGED")
                }
                Set record.taskId=args.taskId,record.envelope=args.envelope,record.state="RESPONSE_UNVERIFIED"
                Do record.%Set("responseAfterExpiry",now'<record.expiresUS,"boolean")
            }
            // None of these transitions verifies a human principal or UTC time.
            Set sc=..Save(record,command,now) $$$ThrowOnError(sc)
            Set result=..View(record,$Select(command="RESPONSE":"WORKFLOW_RESPONSE_UNVERIFIED",1:"WORKFLOW_RECORDED"))
        }
    } Catch ex {
        If $TLevel TRollback
        Set result={"code":"WORKFLOW_WRITE_UNCERTAIN","handoffGranted":false,"actorVerified":false,"completionVerified":false,"canUseClarification":false,"dispatch_authorized":false}
        Set sc=$$$ERROR($$$GeneralError,"WORKFLOW_WRITE_UNCERTAIN")
    }
    Lock -^ChronosDecision16("mutex")
    Return sc
}

ClassMethod FormDigest(preference As %String, note As %String) As %String [ Private ]
{
    Return ..Digest($ZConvert({"preference":(preference),"note":(note)}.%ToJSON(),"O","UTF8"))
}

ClassMethod ResolutionView(record As %DynamicObject) As %DynamicObject [ Private ]
{
    Set out={"code":"WORKFLOW_RESOLUTION_NEW","clarificationId":(record.clarificationId),"state":"NEW","expiresUS":(record.expiresUS),"actorVerified":false,"completionVerified":false,"canUseClarification":false,"dispatch_authorized":false}
    If (record.%GetTypeOf("authorityScheme")'="string")||(record.%Get("authorityScheme")'=..#AUTHORITYSCHEME) { Set out.code="WORKFLOW_RESOLUTION_UNAVAILABLE" Return out }
    If record.%GetTypeOf("resolution")'="object" Return out
    Set resolution=record.resolution
    Set out.completionId=resolution.completionId,out.state=resolution.state,out.code="WORKFLOW_RESOLUTION_UNCERTAIN"
    If resolution.state="VERIFIED_CSP" {
        If (resolution.%GetTypeOf("evidence")'="object")||'resolution.%Get("ticketConsumed") Return out
        If resolution.evidence.actor'=resolution.actor Return out
        Set out.code="WORKFLOW_CLARIFICATION_RECORDED",out.completedUS=resolution.evidence.completedUS
        Do out.%Set("actorVerified",1,"boolean"),out.%Set("completionVerified",1,"boolean")
    }
    // Human data has not yet been adopted into a new context/decision. Native
    // actor evidence is not a source freshness check or a shipment permission.
    Return out
}

ClassMethod FreshResolution(record As %DynamicObject, now As %Numeric, Output fresh As %DynamicObject) As %Status [ Private ]
{
    Set fresh={"code":"WORKFLOW_SOURCE_CHANGED","dispatch_authorized":false}
    If (record.%GetTypeOf("authorityScheme")'="string")||(record.%Get("authorityScheme")'=..#AUTHORITYSCHEME) Return $$$ERROR($$$GeneralError,"WORKFLOW_AUTHORITY_SCHEME_UNAVAILABLE")
    If (now'<record.expiresUS)||(now<record.requestedUS)||(record.state="EXPIRED") Return $$$ERROR($$$GeneralError,"WORKFLOW_CLARIFICATION_EXPIRED")
    Set sc=..Source(record.decisionId,now,.fresh) If $$$ISERR(sc) Return sc
    If fresh.code'="WORKFLOW_SOURCE_ELIGIBLE" Return $$$ERROR($$$GeneralError,"WORKFLOW_SOURCE_CHANGED")
    For field="decisionId","orderId","shipmentVersion","generation","sourceDecisionSha256","sourceContextDigest","sourceFactsId","sourceFactsDigest","utcOriginUS","authorityDigest","authorityScheme" {
        If (record.%GetTypeOf(field)'=fresh.%GetTypeOf(field))||(record.%Get(field)'=fresh.%Get(field)) Return $$$ERROR($$$GeneralError,"WORKFLOW_SOURCE_CHANGED")
    }
    Return $$$OK
}

/// Original CSP plus current native membership is required even for idempotent
/// lookup. A fresh session of the same actor can inspect an old completion but
/// cannot obtain its ephemeral ticket or repeat an incomplete Engine call.
ClassMethod ResolutionStatus(clarificationId As %String, completionId As %String, preference As %String, note As %String, Output result As %DynamicObject) As %Status
{
    Set result={"code":"WORKFLOW_RESOLUTION_UNAVAILABLE","actorVerified":false,"completionVerified":false,"canUseClarification":false,"dispatch_authorized":false}
    If $TLevel||'..ID(clarificationId)||'..ID(completionId) Return $$$ERROR($$$GeneralError,"INVALID_WORKFLOW_RESOLUTION")
    If '##class(Chronos.Workflow.Controller).Form(preference,note,.code) Return $$$ERROR($$$GeneralError,"INVALID_WORKFLOW_FORM")
    Set sc=##class(Chronos.Workflow.Controller).Current(.principal,.user,.nativeUser,.membership,.code) If $$$ISERR(sc) Return sc
    If code'="CSP_WORKFLOW_IDENTITY_CONFIRMED" Return $$$ERROR($$$GeneralError,"WORKFLOW_IDENTITY_REQUIRED")
    Lock +^ChronosDecision16("mutex"):2 If '$Test Return $$$ERROR($$$GeneralError,"WORKFLOW_BUSY")
    Set sc=$$$OK,record="",checkFresh=0
    Try {
        Set raw=$Get(^ChronosDecision16("clarification","item",clarificationId))
        If raw="" Throw ##class(%Exception.General).%New("NO_CLARIFICATION")
        Set record=##class(%DynamicObject).%FromJSON(raw)
        If record.clarificationId'=clarificationId Throw ##class(%Exception.General).%New("WRONG_CLARIFICATION")
        If (record.%GetTypeOf("authorityScheme")'="string")||(record.%Get("authorityScheme")'=..#AUTHORITYSCHEME) Throw ##class(%Exception.General).%New("WORKFLOW_AUTHORITY_SCHEME_UNAVAILABLE")
        If record.%GetTypeOf("resolution")="object" {
            Set resolution=record.resolution
            If (resolution.completionId'=completionId)||(resolution.actor'=principal.actor)||(resolution.payloadSha256'=..FormDigest(preference,note)) Throw ##class(%Exception.General).%New("RESOLUTION_CONFLICT")
            // If the prior commit's journal barrier was uncertain, a new
            // successful barrier can confirm persistence without repeating AI,
            // Engine, task assignment or task completion.
            If resolution.state="VERIFIED_CSP" {
                Set sc=##class(Chronos.Runtime.Durability).Check() $$$ThrowOnError(sc)
                Set sc=##class(Chronos.Runtime.Durability).Flush() $$$ThrowOnError(sc)
            }
        } Else { Set checkFresh=1 }
        Set result=..ResolutionView(record)
    } Catch ex {
        Set sc=$$$ERROR($$$GeneralError,"WORKFLOW_RESOLUTION_UNAVAILABLE")
    }
    Lock -^ChronosDecision16("mutex")
    If $$$ISERR(sc) Return sc
    If checkFresh {
        // Authority/ledger reads finish outside our decision mutex.
        Lock +^ChronosRuntime("bootLock"):2 If '$Test Return $$$ERROR($$$GeneralError,"RUNTIME_BUSY")
        Try { Set sc=..FreshResolution(record,##class(Chronos.Agent.Ledger).NowUS(),.fresh) } Catch ex { Set sc=$$$ERROR($$$GeneralError,"WORKFLOW_SOURCE_CHANGED") }
        Lock -^ChronosRuntime("bootLock")
    }
    Return sc
}

/// One completion attempt for a clarification. The clear ticket is generated
/// from 32 cryptographic random bytes, returned only to the current native CSP
/// call and never stored, traced, sent to HTTP or included in a task message.
ClassMethod ResolutionFence(clarificationId As %String, completionId As %String, taskId As %String, worklistId As %String, preference As %String, note As %String, Output result As %DynamicObject, Output ticket As %String) As %Status
{
    Set ticket="",result={"code":"WORKFLOW_RESOLUTION_UNAVAILABLE","actorVerified":false,"completionVerified":false,"canUseClarification":false,"dispatch_authorized":false}
    If $TLevel||'..ID(clarificationId)||'..ID(completionId)||'..NativeID(taskId)||($Length(worklistId)>256)||(worklistId="") Return $$$ERROR($$$GeneralError,"INVALID_WORKFLOW_RESOLUTION")
    If '##class(Chronos.Workflow.Controller).Form(preference,note,.code) Return $$$ERROR($$$GeneralError,"INVALID_WORKFLOW_FORM")
    Set sc=##class(Chronos.Workflow.Controller).Current(.principal,.user,.nativeUser,.membership,.code) If $$$ISERR(sc) Return sc
    If code'="CSP_WORKFLOW_IDENTITY_CONFIRMED" Return $$$ERROR($$$GeneralError,"WORKFLOW_IDENTITY_REQUIRED")
    // Worklist then Task is the native lock order, and the controller retains
    // both references across the entire completion call.
    Set item=##class(EnsLib.Workflow.Worklist).%OpenId(worklistId,4,.sc) If $$$ISERR(sc) Return sc
    If '$IsObject(item)||(item.UserGetObjectId()'=user)||(item.TaskGetObjectId()'=taskId)||(item.RoleGetObjectId()'=..#ROLE) Return $$$ERROR($$$GeneralError,"WRONG_WORKFLOW_ITEM")
    Set task=##class(EnsLib.Workflow.TaskResponse).%OpenId(taskId,4,.sc) If $$$ISERR(sc) Return sc
    If '$IsObject(task)||'$IsObject(task.%TaskStatus)||'$IsObject(task.%TaskStatus.Request)||'$IsObject(task.%TaskStatus.Role) Return $$$ERROR($$$GeneralError,"WRONG_WORKFLOW_TASK")
    If task.%TaskStatus.IsComplete||(task.%TaskStatus.AssignedTo'=user)||(task.%TaskStatus.Role.Name'=..#ROLE)||(task.%TaskStatus.Request.%Command'=clarificationId) Return $$$ERROR($$$GeneralError,"WRONG_WORKFLOW_TASK")
    Lock +^ChronosRuntime("bootLock"):2 If '$Test Return $$$ERROR($$$GeneralError,"RUNTIME_BUSY")
    Set sc=$$$OK,locked=0,issued=""
    Try {
        Set sc=..Inspect(clarificationId,.inspection) $$$ThrowOnError(sc)
        If inspection.%GetTypeOf("record")'="object" Throw ##class(%Exception.General).%New("NO_CLARIFICATION")
        Set observed=inspection.record,now=##class(Chronos.Agent.Ledger).NowUS()
        Set sc=..FreshResolution(observed,now,.fresh) $$$ThrowOnError(sc)
        Lock +^ChronosDecision16("mutex"):2 If '$Test Throw ##class(%Exception.General).%New("WORKFLOW_BUSY")
        Set locked=1,raw=$Get(^ChronosDecision16("clarification","item",clarificationId))
        If raw="" Throw ##class(%Exception.General).%New("NO_CLARIFICATION")
        Set record=##class(%DynamicObject).%FromJSON(raw)
        Set now=##class(Chronos.Agent.Ledger).NowUS()
        If (now'<record.expiresUS)||(now<observed.requestedUS) Throw ##class(%Exception.General).%New("WORKFLOW_CLARIFICATION_EXPIRED")
        If (record.clarificationId'=clarificationId)||(record.taskRequestId'=task.%TaskStatus.Request.%Id()) Throw ##class(%Exception.General).%New("WRONG_NATIVE_REQUEST")
        If (record.taskId'="")&&(record.taskId'=taskId) Throw ##class(%Exception.General).%New("WRONG_NATIVE_TASK")
        For field="decisionId","orderId","shipmentVersion","generation","sourceDecisionSha256","sourceContextDigest","sourceFactsId","sourceFactsDigest","utcOriginUS","authorityDigest","authorityScheme","requestedUS","expiresUS" {
            If (record.%GetTypeOf(field)'=observed.%GetTypeOf(field))||(record.%Get(field)'=observed.%Get(field)) Throw ##class(%Exception.General).%New("HANDOFF_CHANGED")
        }
        If record.%GetTypeOf("resolution")="object" {
            Set previous=record.resolution
            If (previous.completionId'=completionId)||(previous.actor'=principal.actor)||(previous.payloadSha256'=..FormDigest(preference,note)) Throw ##class(%Exception.General).%New("RESOLUTION_CONFLICT")
            Set result=..ResolutionView(record)
        } Else {
            Set issued=$ZConvert($System.Encryption.ToHex($System.Encryption.GenCryptRand(32,1)),"L")
            If '..Hash(issued) Throw ##class(%Exception.General).%New("TICKET_UNAVAILABLE")
            Set resolution={"schema":"chronos.workflow-csp-completion.v1","completionId":(completionId),"state":"FENCED","actor":(principal.actor),"sessionBinding":(principal.sessionBinding),"taskId":(taskId),"taskRequestId":(record.taskRequestId),"worklistId":(worklistId),"preference":(preference),"noteSha256":(..Digest($ZConvert(note,"O","UTF8"))),"noteBytes":($Length($ZConvert(note,"O","UTF8"))),"payloadSha256":(..FormDigest(preference,note)),"ticketSha256":(..Digest(issued)),"startedUS":(now),"ticketConsumed":false}
            Set record.resolution=resolution
            Set sc=..Save(record,"FENCE_CSP_COMPLETION",now) $$$ThrowOnError(sc)
            Set result=..ResolutionView(record),result.code="WORKFLOW_RESOLUTION_FENCED",ticket=issued
        }
    } Catch ex {
        If $TLevel TRollback
        Set ticket="",sc=$$$ERROR($$$GeneralError,"WORKFLOW_RESOLUTION_UNCERTAIN")
    }
    Set issued=""
    If locked Lock -^ChronosDecision16("mutex")
    Lock -^ChronosRuntime("bootLock")
    Return sc
}

/// Called only immediately after successful Engine completion in the original
/// CSP call. A saved native assignee alone never satisfies this proof.
ClassMethod VerifyResolution(clarificationId As %String, completionId As %String, ticket As %String, Output result As %DynamicObject) As %Status
{
    Set result={"code":"WORKFLOW_RESOLUTION_UNCERTAIN","actorVerified":false,"completionVerified":false,"canUseClarification":false,"dispatch_authorized":false}
    If $TLevel||'..ID(clarificationId)||'..ID(completionId)||'..Hash(ticket) Return $$$ERROR($$$GeneralError,"INVALID_WORKFLOW_PROOF")
    Set sc=##class(Chronos.Workflow.Controller).Current(.principal,.user,.nativeUser,.membership,.code) If $$$ISERR(sc) Return sc
    If code'="CSP_WORKFLOW_IDENTITY_CONFIRMED" Return $$$ERROR($$$GeneralError,"WORKFLOW_IDENTITY_REQUIRED")
    Set sc=..Inspect(clarificationId,.inspection) If $$$ISERR(sc) Return sc
    If inspection.%GetTypeOf("record")'="object" Return $$$ERROR($$$GeneralError,"NO_CLARIFICATION")
    Set observed=inspection.record
    If (observed.%GetTypeOf("authorityScheme")'="string")||(observed.%Get("authorityScheme")'=..#AUTHORITYSCHEME) Return $$$ERROR($$$GeneralError,"WORKFLOW_AUTHORITY_SCHEME_UNAVAILABLE")
    If observed.%GetTypeOf("resolution")'="object" Return $$$ERROR($$$GeneralError,"NO_COMPLETION_FENCE")
    Set fence=observed.resolution
    If (fence.state'="FENCED")||(fence.completionId'=completionId)||(fence.actor'=principal.actor)||(fence.sessionBinding'=principal.sessionBinding)||(fence.ticketSha256'=..Digest(ticket)) Return $$$ERROR($$$GeneralError,"WRONG_COMPLETION_PROOF")
    // The controller still holds the native TaskResponse exclusively. Opening
    // at concurrency 4 forces a fresh read without surrendering that lock.
    Set task=##class(EnsLib.Workflow.TaskResponse).%OpenId(fence.taskId,4,.sc) If $$$ISERR(sc) Return sc
    If '$IsObject(task)||'$IsObject(task.%TaskStatus)||'$IsObject(task.%TaskStatus.Request)||'$IsObject(task.%TaskStatus.Role) Return $$$ERROR($$$GeneralError,"NATIVE_COMPLETION_UNAVAILABLE")
    If 'task.%TaskStatus.IsComplete||(task.%Action'="Clarified")||(task.%RoleName'=..#ROLE)||(task.%TaskStatus.Role.Name'=..#ROLE) Return $$$ERROR($$$GeneralError,"NATIVE_COMPLETION_MISMATCH")
    If (task.%TaskStatus.Request.%Id()'=observed.taskRequestId)||(task.%TaskStatus.Request.%Command'=clarificationId)||(task.%TaskStatus.AssignedTo'=user)||(task.%UserName'=user) Return $$$ERROR($$$GeneralError,"NATIVE_COMPLETION_MISMATCH")
    Set preference=task.%FormValues.GetAt("Preference"),note=task.%FormValues.GetAt("Note")
    If '##class(Chronos.Workflow.Controller).Form(preference,note,.code) Return $$$ERROR($$$GeneralError,"NATIVE_FORM_MISMATCH")
    If ..FormDigest(preference,note)'=fence.payloadSha256 Return $$$ERROR($$$GeneralError,"NATIVE_FORM_MISMATCH")
    If '##class(Chronos.Workflow.Controller).UTCToUS(task.%TaskStatus.TimeCompleted,.completedUS,.code) Return $$$ERROR($$$GeneralError,"INVALID_NATIVE_COMPLETION_TIME")
    Set now=##class(Chronos.Agent.Ledger).NowUS()
    // build154 Workflow UTC is millisecond precision; a just-created native
    // completion can therefore precede startedUS by <1000us after truncation.
    If (completedUS<((fence.startedUS\1000)*1000))||(completedUS>now)||(now<fence.startedUS)||(now'<observed.expiresUS) Return $$$ERROR($$$GeneralError,"WORKFLOW_COMPLETION_OUTSIDE_WINDOW")
    Lock +^ChronosRuntime("bootLock"):2 If '$Test Return $$$ERROR($$$GeneralError,"RUNTIME_BUSY")
    Set sc=$$$OK,locked=0
    Try {
        Set sc=..FreshResolution(observed,now,.fresh) $$$ThrowOnError(sc)
        Set sc=##class(Chronos.Workflow.Controller).Current(.again,.sameUser,.againUser,.againMembership,.code) $$$ThrowOnError(sc)
        If (code'="CSP_WORKFLOW_IDENTITY_CONFIRMED")||(sameUser'=user)||(again.actor'=fence.actor)||(again.sessionBinding'=fence.sessionBinding) Throw ##class(%Exception.General).%New("IDENTITY_CHANGED")
        Lock +^ChronosDecision16("mutex"):2 If '$Test Throw ##class(%Exception.General).%New("WORKFLOW_BUSY")
        Set locked=1,raw=$Get(^ChronosDecision16("clarification","item",clarificationId))
        If raw="" Throw ##class(%Exception.General).%New("NO_CLARIFICATION")
        Set record=##class(%DynamicObject).%FromJSON(raw)
        If (record.%GetTypeOf("resolution")'="object")||(record.resolution.%ToJSON()'=fence.%ToJSON()) Throw ##class(%Exception.General).%New("COMPLETION_FENCE_CHANGED")
        If (record.clarificationId'=clarificationId)||(record.taskRequestId'=fence.taskRequestId)||(record.expiresUS'=observed.expiresUS) Throw ##class(%Exception.General).%New("HANDOFF_CHANGED")
        // Re-entrant ledger reads run before Save opens its transaction. Retain
        // both boot/decision locks while checking the final durable bindings.
        // The earlier timestamp cannot authorize a commit after a lock wait.
        Set now=##class(Chronos.Agent.Ledger).NowUS()
        Set sc=..FreshResolution(record,now,.finalFresh) $$$ThrowOnError(sc)
        // Source reads can themselves wait. Read the clock once more immediately
        // before consuming the ticket; never extend the original expiry.
        Set now=##class(Chronos.Agent.Ledger).NowUS()
        If (now'<record.expiresUS)||(now<fence.startedUS)||(completedUS>now)||(completedUS<((fence.startedUS\1000)*1000)) Throw ##class(%Exception.General).%New("WORKFLOW_COMPLETION_OUTSIDE_WINDOW")
        Set resolution=record.resolution
        Set resolution.state="VERIFIED_CSP",resolution.verifiedUS=now
        Do resolution.%Set("ticketConsumed",1,"boolean"),resolution.%Remove("ticketSha256")
        Set resolution.evidence={"schema":"chronos.workflow-csp-evidence.v1","actor":(principal.actor),"taskId":(fence.taskId),"taskRequestId":(fence.taskRequestId),"role":(..#ROLE),"action":"Clarified","completedUTC":(task.%TaskStatus.TimeCompleted),"completedUS":(completedUS),"verifiedUS":(now),"preference":(preference),"noteSha256":(fence.noteSha256),"noteBytes":(fence.noteBytes),"sourceDecisionSha256":(record.sourceDecisionSha256),"generation":(record.generation),"actorBasis":"ORIGINAL_CSP_CALL_AND_NATIVE_READBACK","isNativeAssigneeCompleterProof":false,"providerFactsVerified":false}
        Set record.resolution=resolution
        Set sc=..Save(record,"VERIFY_CSP_COMPLETION",now) $$$ThrowOnError(sc)
        Set result=..ResolutionView(record)
    } Catch ex {
        If $TLevel TRollback
        Set sc=$$$ERROR($$$GeneralError,"WORKFLOW_RESOLUTION_UNCERTAIN")
    }
    If locked Lock -^ChronosDecision16("mutex")
    Lock -^ChronosRuntime("bootLock")
    Return sc
}

/// Private, read-only composition for a NEW decision. This does not adopt the
/// clarification, invoke an agent, refresh provider facts or approve a send.
/// The original-CSP evidence remains the actor proof; native assignee/name
/// fields are only additional correlations with that independently saved proof.
ClassMethod ReadAdoptionSource(clarificationId As %String, Output source As %DynamicObject) As %Status
{
    Set source={"code":"WORKFLOW_ADOPTION_SOURCE_UNAVAILABLE","canUseClarification":false,"dispatch_authorized":false}
    If $TLevel||'..ID(clarificationId) Return $$$OK
    Set sc=##class(Chronos.Workflow.Controller).Current(.principal,.user,.nativeUser,.membership,.code)
    If $$$ISERR(sc)||(code'="CSP_WORKFLOW_IDENTITY_CONFIRMED") Return $$$OK
    Set sc=..ReadVerified(clarificationId,principal.actor,user,.candidate) If $$$ISERR(sc) Return sc
    Set sc=##class(Chronos.Workflow.Controller).Current(.again,.sameUser,.againUser,.againMembership,.code)
    If $$$ISERR(sc)||(code'="CSP_WORKFLOW_IDENTITY_CONFIRMED") Return $$$OK
    If (sameUser'=user)||(again.actor'=principal.actor)||(again.sessionBinding'=principal.sessionBinding) Return $$$OK
    Set source=candidate
    Return $$$OK
}

/// Two trusted wrappers choose the principal: current original CSP above, or
/// the protected atomic registration anchor in SourceForDecision below. Native
/// task usernames are never a replacement for either source of authority.
ClassMethod ReadVerified(clarificationId As %String, expectedActor As %String, user As %String, Output source As %DynamicObject) As %Status [ Private ]
{
    Set source={"code":"WORKFLOW_ADOPTION_SOURCE_UNAVAILABLE","canUseClarification":false,"dispatch_authorized":false}
    If $TLevel||'..ID(clarificationId)||(user="")||($Length(user)>256)||($ZConvert(user,"L")="unknownuser") Return $$$OK
    If expectedActor'=("principal-"_..Digest($ListBuild($Namespace,user))) Return $$$OK
    Set bootLocked=0,locked=0,sc=$$$OK,task=""
    Try {
        Set sc=..Inspect(clarificationId,.inspection) $$$ThrowOnError(sc)
        If inspection.%GetTypeOf("record")'="object" Throw ##class(%Exception.General).%New("NO_CLARIFICATION")
        Set observed=inspection.record
        If (observed.clarificationId'=clarificationId)||(observed.%GetTypeOf("resolution")'="object") Throw ##class(%Exception.General).%New("NO_COMPLETION")
        If (observed.%GetTypeOf("authorityScheme")'="string")||(observed.%Get("authorityScheme")'=..#AUTHORITYSCHEME) Throw ##class(%Exception.General).%New("WORKFLOW_AUTHORITY_SCHEME_UNAVAILABLE")
        Set resolution=observed.resolution
        If (resolution.%Get("schema")'="chronos.workflow-csp-completion.v1")||(resolution.%Get("state")'="VERIFIED_CSP") Throw ##class(%Exception.General).%New("UNVERIFIED_COMPLETION")
        If (resolution.%GetTypeOf("ticketConsumed")'="boolean")||'resolution.ticketConsumed||resolution.%IsDefined("ticketSha256") Throw ##class(%Exception.General).%New("TICKET_NOT_CONSUMED")
        If (resolution.%GetTypeOf("evidence")'="object")||(resolution.%Get("actor")'=expectedActor) Throw ##class(%Exception.General).%New("WRONG_CSP_ACTOR")
        If '..NativeID(resolution.%Get("taskId"))||'..NativeID(resolution.%Get("taskRequestId")) Throw ##class(%Exception.General).%New("BAD_NATIVE_CORRELATION")
        If (resolution.taskRequestId'=observed.taskRequestId)||((observed.taskId'="")&&(observed.taskId'=resolution.taskId)) Throw ##class(%Exception.General).%New("WRONG_TASK")
        // Acquire the shared native task reference BEFORE boot/decision locks.
        // A completer must not wait for our task reference while owning bootLock.
        Set task=##class(EnsLib.Workflow.TaskResponse).%OpenId(resolution.taskId,3,.sc) $$$ThrowOnError(sc)
        If '$IsObject(task)||'$IsObject(task.%TaskStatus)||'$IsObject(task.%TaskStatus.Request)||'$IsObject(task.%TaskStatus.Role) Throw ##class(%Exception.General).%New("NO_NATIVE_TASK")
        If 'task.%TaskStatus.IsComplete||(task.%Action'="Clarified")||(task.%RoleName'=..#ROLE)||(task.%TaskStatus.Role.Name'=..#ROLE) Throw ##class(%Exception.General).%New("WRONG_NATIVE_COMPLETION")
        If (task.%TaskStatus.Request.%Id()'=observed.taskRequestId)||(task.%TaskStatus.Request.%Command'=clarificationId) Throw ##class(%Exception.General).%New("WRONG_NATIVE_REQUEST")
        // These values cannot establish authentication. They must agree with
        // the original-CSP evidence AND the currently authenticated principal.
        Set actor="principal-"_..Digest($ListBuild($Namespace,task.%UserName))
        If (task.%UserName'=user)||(task.%TaskStatus.AssignedTo'=user)||(actor'=expectedActor)||(resolution.actor'=actor) Throw ##class(%Exception.General).%New("NATIVE_ACTOR_CORRELATION_CHANGED")
        Set evidence=resolution.evidence
        If (evidence.%Get("schema")'="chronos.workflow-csp-evidence.v1")||(evidence.%Get("actorBasis")'="ORIGINAL_CSP_CALL_AND_NATIVE_READBACK") Throw ##class(%Exception.General).%New("NO_ORIGINAL_CSP_EVIDENCE")
        If (evidence.%GetTypeOf("isNativeAssigneeCompleterProof")'="boolean")||evidence.isNativeAssigneeCompleterProof||(evidence.%GetTypeOf("providerFactsVerified")'="boolean")||evidence.providerFactsVerified Throw ##class(%Exception.General).%New("UNSUPPORTED_EVIDENCE_CLAIM")
        If (evidence.%Get("actor")'=actor)||(evidence.%Get("taskId")'=resolution.taskId)||(evidence.%Get("taskRequestId")'=observed.taskRequestId)||(evidence.%Get("role")'=..#ROLE)||(evidence.%Get("action")'="Clarified") Throw ##class(%Exception.General).%New("COMPLETION_EVIDENCE_CHANGED")
        If (evidence.%Get("sourceDecisionSha256")'=observed.sourceDecisionSha256)||(evidence.%Get("generation")'=observed.generation) Throw ##class(%Exception.General).%New("COMPLETION_SOURCE_CHANGED")
        Set preference=task.%FormValues.GetAt("Preference"),note=task.%FormValues.GetAt("Note")
        If '##class(Chronos.Workflow.Controller).Form(preference,note,.code) Throw ##class(%Exception.General).%New("INVALID_NATIVE_FORM")
        If (preference'=resolution.%Get("preference"))||(preference'=evidence.%Get("preference"))||(..FormDigest(preference,note)'=resolution.%Get("payloadSha256")) Throw ##class(%Exception.General).%New("NATIVE_FORM_CHANGED")
        Set noteHash=..Digest($ZConvert(note,"O","UTF8")),noteBytes=$Length($ZConvert(note,"O","UTF8"))
        If (noteHash'=resolution.%Get("noteSha256"))||(noteHash'=evidence.%Get("noteSha256"))||(noteBytes'=resolution.%Get("noteBytes"))||(noteBytes'=evidence.%Get("noteBytes")) Throw ##class(%Exception.General).%New("NATIVE_NOTE_CHANGED")
        If '##class(Chronos.Workflow.Controller).UTCToUS(task.%TaskStatus.TimeCompleted,.completedUS,.code) Throw ##class(%Exception.General).%New("INVALID_NATIVE_COMPLETION_TIME")
        If '##class(Chronos.Workflow.Controller).UTCToUS(task.%TaskStatus.TimeCreated,.createdUS,.code) Throw ##class(%Exception.General).%New("INVALID_NATIVE_CREATION_TIME")
        If (evidence.%Get("completedUTC")'=task.%TaskStatus.TimeCompleted)||(evidence.%GetTypeOf("completedUS")'="number")||(evidence.completedUS'=completedUS)||(createdUS>completedUS)||(createdUS<((observed.requestedUS\1000)*1000)) Throw ##class(%Exception.General).%New("NATIVE_TIME_CHANGED")
        For field="startedUS","verifiedUS" {
            If (resolution.%GetTypeOf(field)'="number")||(resolution.%Get(field)<0)||(resolution.%Get(field)'=(resolution.%Get(field)\1)) Throw ##class(%Exception.General).%New("INVALID_COMPLETION_WINDOW")
        }
        If (evidence.%GetTypeOf("verifiedUS")'="number")||(evidence.verifiedUS'=resolution.verifiedUS)||(resolution.startedUS<observed.requestedUS)||(completedUS<observed.requestedUS)||(completedUS<((resolution.startedUS\1000)*1000))||(resolution.verifiedUS<completedUS)||(resolution.verifiedUS<resolution.startedUS)||(resolution.verifiedUS'<observed.expiresUS) Throw ##class(%Exception.General).%New("INVALID_COMPLETION_WINDOW")
        Lock +^ChronosRuntime("bootLock"):2 If '$Test Throw ##class(%Exception.General).%New("RUNTIME_BUSY")
        Set bootLocked=1,now=##class(Chronos.Agent.Ledger).NowUS()
        Set sc=..FreshResolution(observed,now,.fresh) $$$ThrowOnError(sc)
        Set sc=##class(Chronos.Agent.Ledger).Apply("INSPECT",{"requestId":(observed.decisionId)},.held) $$$ThrowOnError(sc)
        If held.%GetTypeOf("private")'="object" Throw ##class(%Exception.General).%New("ORIGINAL_HOLD_UNAVAILABLE")
        Set d=held.private
        If ..Digest(d.%ToJSON())'=observed.sourceDecisionSha256 Throw ##class(%Exception.General).%New("ORIGINAL_HOLD_CHANGED")
        Lock +^ChronosDecision16("mutex"):2 If '$Test Throw ##class(%Exception.General).%New("WORKFLOW_BUSY")
        Set locked=1,raw=$Get(^ChronosDecision16("clarification","item",clarificationId))
        If (raw="")||(raw'=observed.%ToJSON()) Throw ##class(%Exception.General).%New("CLARIFICATION_CHANGED")
        Set now=##class(Chronos.Agent.Ledger).NowUS()
        Set sc=..FreshResolution(observed,now,.finalFresh) $$$ThrowOnError(sc)
        Set now=##class(Chronos.Agent.Ledger).NowUS()
        If (now'<observed.expiresUS)||(now<resolution.verifiedUS)||(now<completedUS) Throw ##class(%Exception.General).%New("CLARIFICATION_EXPIRED")
        Set w=d.prepared.record.wire,limit=(w.%Get("utc_origin_us")+w.facts.deadline)
        For field="inventory_expires","offer_until" { Set bound=(w.%Get("utc_origin_us")+w.facts.%Get(field)) If bound<limit Set limit=bound }
        If observed.expiresUS>limit Throw ##class(%Exception.General).%New("EXPIRY_EXCEEDS_ORIGINAL_CONSTRAINTS")
        Set binding={"clarification_id":(observed.clarificationId),"task_id":(resolution.taskId),"source_decision_id":(observed.decisionId),"order_id":(observed.orderId),"shipment_version":(observed.shipmentVersion),"generation":(observed.generation),"decision_digest":(observed.sourceDecisionSha256),"facts_id":(observed.sourceFactsId),"facts_digest":(observed.sourceFactsDigest),"authority_digest":(observed.authorityDigest),"source_outcome":(d.result.status),"reason_code":(d.result.proposal.%Get("reason_code")),"preference_mode":(w.facts.%Get("preference_mode")),"utc_origin_us":(observed.utcOriginUS),"valid_until_us":(limit)}
        Set expected={"clarification_id":(clarificationId),"task_id":(task.%Id()),"source_decision_id":(d.requestId),"order_id":(d.orderId),"shipment_version":(d.shipmentVersion),"generation":(d.generation),"decision_digest":(..Digest(d.%ToJSON())),"facts_id":(w.%Get("facts_id")),"facts_digest":(d.prepared.record.%Get("facts_digest")),"authority_digest":(finalFresh.authorityDigest),"source_outcome":(d.result.status),"reason_code":(d.result.proposal.%Get("reason_code")),"preference_mode":(w.facts.%Get("preference_mode")),"utc_origin_us":(w.%Get("utc_origin_us")),"valid_until_us":(limit)}
        Set completion={"clarification_id":(task.%TaskStatus.Request.%Command),"task_id":(task.%Id()),"role":(task.%TaskStatus.Role.Name),"completed":true,"action":(task.%Action),"actor":(evidence.actor),"completed_us":(completedUS),"preference":(preference),"note":(note)}
        Set input={"stored_binding":(binding),"expected_binding":(expected),"completion":(completion),"created_us":(observed.requestedUS),"expires_us":(observed.expiresUS),"now_us":(now)}
        Set projected=..AdoptionProjection(input.%ToJSON())
        If projected="" Throw ##class(%Exception.General).%New("ADOPTION_PROJECTION_UNAVAILABLE")
        Set source=##class(%DynamicObject).%FromJSON(projected)
    } Catch ex {
        Set source={"code":"WORKFLOW_ADOPTION_SOURCE_UNAVAILABLE","canUseClarification":false,"dispatch_authorized":false}
    }
    If locked Lock -^ChronosDecision16("mutex")
    If bootLocked Lock -^ChronosRuntime("bootLock")
    Return $$$OK
}

/// Called before the registrar acquires boot/decision locks. The argument is
/// trusted prepared output, never an HTTP-supplied actor, source or grant.
/// This method does not write: Ledger atomically stores the returned anchor
/// together with the exact prepared decision and clarification adoption index.
ClassMethod CSPRegistration(args As %DynamicObject, Output grant As %DynamicObject) As %Status
{
    Set grant={"code":"WORKFLOW_REGISTRATION_UNAVAILABLE","registrationGranted":false,"dispatch_authorized":false}
    If $TLevel||'$IsObject(args) Return $$$OK
    Set sc=##class(Chronos.Workflow.Controller).Current(.principal,.user,.nativeUser,.membership,.code)
    If $$$ISERR(sc)||(code'="CSP_WORKFLOW_IDENTITY_CONFIRMED") Return $$$OK
    Try {
        If (args.%GetTypeOf("requestId")'="string")||'..ID(args.requestId)||($Length(args.requestId)>64) Throw ##class(%Exception.General).%New("INVALID_NEW_DECISION_ID")
        If (args.%GetTypeOf("prepared")'="object")||(args.prepared.%GetTypeOf("record")'="object") Throw ##class(%Exception.General).%New("NO_PREPARED_CONTEXT")
        Set p=args.prepared.record
        If (p.%GetTypeOf("clarification_binding")'="object")||(p.%GetTypeOf("wire")'="object") Throw ##class(%Exception.General).%New("NO_CLARIFICATION_REFERENCE")
        Set reference=p.%Get("clarification_binding")
        If reference.%GetTypeOf("binding")'="object" Throw ##class(%Exception.General).%New("NO_CLARIFICATION_BINDING")
        Set clarificationId=reference.binding.%Get("clarification_id")
        If '..ID(clarificationId)||(reference.binding.%Get("source_decision_id")=args.requestId) Throw ##class(%Exception.General).%New("INVALID_ADOPTION_IDENTITY")
        Set sc=..ReadAdoptionSource(clarificationId,.source) $$$ThrowOnError(sc)
        If source.%GetTypeOf("record")'="object" Throw ##class(%Exception.General).%New("ADOPTION_SOURCE_UNAVAILABLE")
        Set b=source.%Get("expected_binding"),w=p.wire
        If (args.%Get("orderId")'=b.%Get("order_id"))||(args.%GetTypeOf("shipmentVersion")'="number")||(args.shipmentVersion'=b.%Get("shipment_version"))||(args.%Get("generation")'=b.generation) Throw ##class(%Exception.General).%New("ADOPTION_REQUEST_MISMATCH")
        If (w.%Get("context_id")'=args.requestId)||(w.%Get("order_id")'=args.orderId)||(w.%Get("shipment_version")'=args.shipmentVersion)||(args.prepared.%Get("runtime_generation")'=args.generation) Throw ##class(%Exception.General).%New("ADOPTION_CONTEXT_MISMATCH")
        If '$ListFind($ListBuild("WITH_TRIALS","WITHOUT_TRIALS_ABLATION"),args.%Get("mode"))||(w.%Get("trial_mode")'=args.mode) Throw ##class(%Exception.General).%New("ADOPTION_MODE_MISMATCH")
        If (p.%Get("review_authority_stamp")'=b.%Get("authority_digest"))||(source.record.actor'=principal.actor) Throw ##class(%Exception.General).%New("ADOPTION_AUTHORITY_MISMATCH")
        Set encoded=..SourceReferenceDigests(source.%ToJSON(),reference.%ToJSON())
        If encoded="" Throw ##class(%Exception.General).%New("ADOPTION_REFERENCE_MISMATCH")
        Set hashes=##class(%DynamicObject).%FromJSON(encoded)
        Set sc=##class(Chronos.Workflow.Controller).Current(.again,.sameUser,.againUser,.againMembership,.code) $$$ThrowOnError(sc)
        If (code'="CSP_WORKFLOW_IDENTITY_CONFIRMED")||(sameUser'=user)||(again.actor'=principal.actor)||(again.sessionBinding'=principal.sessionBinding) Throw ##class(%Exception.General).%New("CSP_IDENTITY_CHANGED")
        Set now=##class(Chronos.Agent.Ledger).NowUS()
        If (now<source.record.%Get("resolved_us"))||(now'<source.record.%Get("expires_us")) Throw ##class(%Exception.General).%New("ADOPTION_SOURCE_EXPIRED")
        If (p.%GetTypeOf("deadline_us")'="number")||(p.%GetTypeOf("review_deadline_us")'="number")||(p.%Get("deadline_us")'>now)||(p.%Get("deadline_us")>source.record.%Get("expires_us"))||(p.%Get("review_deadline_us")>source.record.%Get("expires_us")) Throw ##class(%Exception.General).%New("ADOPTION_CONTEXT_EXPIRED")
        // ReadAdoptionSource has returned: its native Task references are gone.
        // Snapshot only private JSON under our ledger mutex. The registrar can
        // compare these two raw hashes again inside its atomic transaction.
        Set sc=..RegistrationSnapshot(clarificationId,source,.snapshot) $$$ThrowOnError(sc)
        If snapshot.%GetTypeOf("nativeRecordSha256")'="string" Throw ##class(%Exception.General).%New("REGISTRATION_SNAPSHOT_UNAVAILABLE")
        Set anchor={"schema":"chronos.clarification-registration.v1","requestId":(args.requestId),"clarificationId":(clarificationId),"user":(user),"actor":(principal.actor),"generation":(args.generation),"referenceSha256":(hashes.referenceSha256),"sourceSha256":(hashes.sourceSha256),"createdUS":(now),"expiresUS":(source.record.%Get("expires_us"))}
        Set grant={"anchor":(anchor),"nativeRecordSha256":(snapshot.nativeRecordSha256),"sourceDecisionSha256":(snapshot.sourceDecisionSha256)}
    } Catch ex {
        Set grant={"code":"WORKFLOW_REGISTRATION_UNAVAILABLE","registrationGranted":false,"dispatch_authorized":false}
    }
    Return $$$OK
}

/// No Task, membership or account read is performed while this mutex is held.
/// All compared source values came from the earlier verified native read.
ClassMethod RegistrationSnapshot(clarificationId As %String, source As %DynamicObject, Output snapshot As %DynamicObject) As %Status [ Private ]
{
    Set snapshot={}
    If $TLevel Return $$$OK
    Lock +^ChronosDecision16("mutex"):2 If '$Test Return $$$OK
    Try {
        Set b=source.%Get("expected_binding"),c=source.%Get("native_completion"),r=source.record
        Set raw=$Get(^ChronosDecision16("clarification","item",clarificationId)),heldRaw=$Get(^ChronosDecision16("decision",b.%Get("source_decision_id")))
        If (raw="")||(heldRaw="") Throw ##class(%Exception.General).%New("NO_PRIVATE_REGISTRATION_SOURCE")
        Set handoff=##class(%DynamicObject).%FromJSON(raw),d=##class(%DynamicObject).%FromJSON(heldRaw)
        If (handoff.%Get("authorityScheme")'=..#AUTHORITYSCHEME)||(handoff.%GetTypeOf("resolution")'="object") Throw ##class(%Exception.General).%New("PRIVATE_HANDOFF_CHANGED")
        If (handoff.clarificationId'=clarificationId)||(handoff.clarificationId'=b.%Get("clarification_id"))||(handoff.decisionId'=b.%Get("source_decision_id"))||(handoff.orderId'=b.%Get("order_id"))||(handoff.shipmentVersion'=b.%Get("shipment_version"))||(handoff.generation'=b.generation) Throw ##class(%Exception.General).%New("PRIVATE_SOURCE_IDENTITY_CHANGED")
        If (handoff.sourceDecisionSha256'=b.%Get("decision_digest"))||(handoff.sourceFactsId'=b.%Get("facts_id"))||(handoff.sourceFactsDigest'=b.%Get("facts_digest"))||(handoff.authorityDigest'=b.%Get("authority_digest"))||(handoff.utcOriginUS'=b.%Get("utc_origin_us")) Throw ##class(%Exception.General).%New("PRIVATE_SOURCE_BINDING_CHANGED")
        If (handoff.requestedUS'=r.%Get("created_us"))||(handoff.expiresUS'=r.%Get("expires_us"))||(..Digest(heldRaw)'=b.%Get("decision_digest")) Throw ##class(%Exception.General).%New("PRIVATE_SOURCE_TIME_OR_HOLD_CHANGED")
        Set sc=..Eligible(d,handoff.requestedUS,.eligible) $$$ThrowOnError(sc)
        If eligible.%Get("code")'="WORKFLOW_SOURCE_ELIGIBLE" Throw ##class(%Exception.General).%New("ORIGINAL_HOLD_UNAVAILABLE")
        For field="decisionId","orderId","shipmentVersion","generation","sourceDecisionSha256","sourceContextDigest","sourceFactsId","sourceFactsDigest","utcOriginUS","requestedUS","expiresUS" {
            If (handoff.%GetTypeOf(field)'=eligible.%GetTypeOf(field))||(handoff.%Get(field)'=eligible.%Get(field)) Throw ##class(%Exception.General).%New("ORIGINAL_HOLD_CHANGED")
        }
        Set resolution=handoff.resolution
        If (resolution.%Get("state")'="VERIFIED_CSP")||(resolution.%GetTypeOf("ticketConsumed")'="boolean")||'resolution.ticketConsumed||resolution.%IsDefined("ticketSha256")||(resolution.%GetTypeOf("evidence")'="object") Throw ##class(%Exception.General).%New("PRIVATE_COMPLETION_CHANGED")
        Set e=resolution.evidence
        If (resolution.actor'=r.actor)||(e.%Get("actor")'=r.actor)||(resolution.taskId'=b.%Get("task_id"))||(e.%Get("taskId")'=resolution.taskId)||(e.%Get("taskRequestId")'=handoff.taskRequestId) Throw ##class(%Exception.General).%New("PRIVATE_ACTOR_OR_TASK_CHANGED")
        If (e.%Get("schema")'="chronos.workflow-csp-evidence.v1")||(e.%Get("actorBasis")'="ORIGINAL_CSP_CALL_AND_NATIVE_READBACK")||(e.%GetTypeOf("isNativeAssigneeCompleterProof")'="boolean")||e.isNativeAssigneeCompleterProof||(e.%GetTypeOf("providerFactsVerified")'="boolean")||e.providerFactsVerified Throw ##class(%Exception.General).%New("PRIVATE_PROOF_CHANGED")
        If (e.%Get("sourceDecisionSha256")'=handoff.sourceDecisionSha256)||(e.%Get("generation")'=handoff.generation)||(e.%Get("role")'=c.role)||(e.%Get("action")'=c.action)||(e.%Get("completedUS")'=c.%Get("completed_us"))||(c.%Get("completed_us")'=r.%Get("resolved_us")) Throw ##class(%Exception.General).%New("PRIVATE_NATIVE_COMPLETION_CHANGED")
        If (resolution.%Get("preference")'=r.preference)||(e.%Get("preference")'=r.preference)||(c.preference'=r.preference)||(c.note'=r.note) Throw ##class(%Exception.General).%New("PRIVATE_FORM_CHANGED")
        Set noteHash=..Digest($ZConvert(r.note,"O","UTF8")),noteBytes=$Length($ZConvert(r.note,"O","UTF8"))
        If (resolution.%Get("payloadSha256")'=..FormDigest(r.preference,r.note))||(resolution.%Get("noteSha256")'=noteHash)||(e.%Get("noteSha256")'=noteHash)||(resolution.%Get("noteBytes")'=noteBytes)||(e.%Get("noteBytes")'=noteBytes) Throw ##class(%Exception.General).%New("PRIVATE_FORM_CHANGED")
        Set now=##class(Chronos.Agent.Ledger).NowUS()
        If (now<r.%Get("resolved_us"))||(now'<r.%Get("expires_us")) Throw ##class(%Exception.General).%New("PRIVATE_REGISTRATION_EXPIRED")
        Set snapshot={"nativeRecordSha256":(..Digest(raw)),"sourceDecisionSha256":(..Digest(heldRaw))}
    } Catch ex { Set snapshot={} }
    Lock -^ChronosDecision16("mutex")
    Return $$$OK
}

/// Background readers supply only the decision ID. The actor/user are derived
/// from the exact private CSP registration and its atomic adoption index, not
/// from BO identity, request JSON, a saved role list or a native task username.
ClassMethod SourceForDecision(requestId As %String, Output source As %DynamicObject) As %Status
{
    Set source={"code":"WORKFLOW_ADOPTION_SOURCE_UNAVAILABLE","canUseClarification":false,"dispatch_authorized":false}
    If $TLevel||'..ID(requestId)||($Length(requestId)>64) Return $$$OK
    Set locked=0
    Try {
        Set sc=##class(Chronos.Agent.Ledger).Apply("INSPECT",{"requestId":(requestId)},.read) $$$ThrowOnError(sc)
        If read.%Get("code")="NOT_FOUND" { Set source={"code":"WORKFLOW_ADOPTION_ABSENT","canUseClarification":false,"dispatch_authorized":false} Return $$$OK }
        If read.%GetTypeOf("private")'="object" Throw ##class(%Exception.General).%New("NO_PRIVATE_DECISION")
        Set d=read.private,hasReference=0,hasAnchor=d.%IsDefined("clarificationAnchor")
        If (d.%GetTypeOf("prepared")="object"),(d.prepared.%GetTypeOf("record")="object") Set hasReference=d.prepared.record.%IsDefined("clarification_binding")
        If 'hasReference,'hasAnchor { Set source={"code":"WORKFLOW_ADOPTION_ABSENT","canUseClarification":false,"dispatch_authorized":false} Return $$$OK }
        If 'hasReference||'hasAnchor||(d.%GetTypeOf("clarificationAnchor")'="object") Throw ##class(%Exception.General).%New("PARTIAL_REGISTRATION")
        Set anchor=d.clarificationAnchor
        If anchor.%Size()'=10 Throw ##class(%Exception.General).%New("INVALID_REGISTRATION_ANCHOR")
        For field="schema","requestId","clarificationId","user","actor","generation","referenceSha256","sourceSha256" {
            If anchor.%GetTypeOf(field)'="string" Throw ##class(%Exception.General).%New("INVALID_REGISTRATION_ANCHOR")
        }
        For field="createdUS","expiresUS" {
            If (anchor.%GetTypeOf(field)'="number")||(anchor.%Get(field)<0)||(anchor.%Get(field)'=(anchor.%Get(field)\1)) Throw ##class(%Exception.General).%New("INVALID_REGISTRATION_WINDOW")
        }
        If (anchor.schema'="chronos.clarification-registration.v1")||(anchor.requestId'=requestId)||(d.requestId'=requestId)||(anchor.generation'=d.generation)||'..ID(anchor.clarificationId)||'..Hash(anchor.referenceSha256)||'..Hash(anchor.sourceSha256) Throw ##class(%Exception.General).%New("REGISTRATION_IDENTITY_CHANGED")
        If (anchor.user="")||($Length(anchor.user)>256)||(anchor.actor'=("principal-"_..Digest($ListBuild($Namespace,anchor.user)))) Throw ##class(%Exception.General).%New("REGISTRATION_ACTOR_CHANGED")
        Set reference=d.prepared.record.%Get("clarification_binding")
        If '$IsObject(reference)||(reference.%GetTypeOf("binding")'="object") Throw ##class(%Exception.General).%New("NO_REGISTERED_REFERENCE")
        If (reference.binding.%Get("clarification_id")'=anchor.clarificationId)||(reference.binding.%Get("generation")'=anchor.generation)||(reference.binding.%Get("order_id")'=d.orderId)||(reference.binding.%Get("shipment_version")'=d.shipmentVersion) Throw ##class(%Exception.General).%New("REGISTRATION_SOURCE_CHANGED")
        Lock +^ChronosDecision16("mutex"):2 If '$Test Throw ##class(%Exception.General).%New("WORKFLOW_BUSY")
        Set locked=1,index=$Get(^ChronosDecision16("clarificationAdoption",anchor.clarificationId))
        If (index="")||(index'=anchor.%ToJSON()) Throw ##class(%Exception.General).%New("REGISTRATION_INDEX_CHANGED")
        Lock -^ChronosDecision16("mutex") Set locked=0
        // AccountState performs a narrow read of the SAVED target account and
        // current permissions/membership; it never impersonates that account.
        Set sc=##class(Chronos.Workflow.AccountState).ForDecision(requestId,.allowed) $$$ThrowOnError(sc)
        If (allowed.%Size()'=2)||(allowed.%GetTypeOf("allowed")'="boolean")||'allowed.allowed||(allowed.%Get("code")'="WORKFLOW_ACCOUNT_CURRENTLY_ALLOWED") Throw ##class(%Exception.General).%New("REGISTERED_ACCOUNT_NOT_ALLOWED")
        Set now=##class(Chronos.Agent.Ledger).NowUS()
        If (now<anchor.createdUS)||(now'<anchor.expiresUS) Throw ##class(%Exception.General).%New("REGISTRATION_EXPIRED")
        Set sc=..ReadVerified(anchor.clarificationId,anchor.actor,anchor.user,.candidate) $$$ThrowOnError(sc)
        If candidate.%GetTypeOf("record")'="object" Throw ##class(%Exception.General).%New("REGISTERED_SOURCE_UNAVAILABLE")
        Set encoded=..SourceReferenceDigests(candidate.%ToJSON(),reference.%ToJSON())
        If encoded="" Throw ##class(%Exception.General).%New("REGISTERED_REFERENCE_CHANGED")
        Set hashes=##class(%DynamicObject).%FromJSON(encoded)
        If (hashes.referenceSha256'=anchor.referenceSha256)||(hashes.sourceSha256'=anchor.sourceSha256)||(candidate.record.actor'=anchor.actor)||(candidate.record.%Get("expires_us")'=anchor.expiresUS) Throw ##class(%Exception.General).%New("REGISTERED_SOURCE_CHANGED")
        // Do not retain our decision mutex while waiting for task/member rows.
        Set sc=##class(Chronos.Workflow.AccountState).ForDecision(requestId,.againAllowed) $$$ThrowOnError(sc)
        If (againAllowed.%Size()'=2)||(againAllowed.%GetTypeOf("allowed")'="boolean")||'againAllowed.allowed||(againAllowed.%Get("code")'="WORKFLOW_ACCOUNT_CURRENTLY_ALLOWED") Throw ##class(%Exception.General).%New("REGISTERED_ACCOUNT_REVOKED")
        Set sc=##class(Chronos.Agent.Ledger).Apply("INSPECT",{"requestId":(requestId)},.again) $$$ThrowOnError(sc)
        If again.%GetTypeOf("private")'="object" Throw ##class(%Exception.General).%New("REGISTERED_DECISION_DISAPPEARED")
        Set current=again.private
        If (current.%GetTypeOf("clarificationAnchor")'="object")||(current.clarificationAnchor.%ToJSON()'=anchor.%ToJSON()) Throw ##class(%Exception.General).%New("REGISTRATION_CHANGED_DURING_READ")
        If (current.%GetTypeOf("prepared")'="object")||(current.prepared.%GetTypeOf("record")'="object")||(current.prepared.record.%GetTypeOf("clarification_binding")'="object") Throw ##class(%Exception.General).%New("REFERENCE_DISAPPEARED")
        Set final=..SourceReferenceDigests(candidate.%ToJSON(),current.prepared.record.%Get("clarification_binding").%ToJSON())
        If final'=encoded Throw ##class(%Exception.General).%New("REGISTRATION_CHANGED_DURING_READ")
        Lock +^ChronosDecision16("mutex"):2 If '$Test Throw ##class(%Exception.General).%New("WORKFLOW_BUSY")
        Set locked=1
        If $Get(^ChronosDecision16("clarificationAdoption",anchor.clarificationId))'=index Throw ##class(%Exception.General).%New("REGISTRATION_INDEX_CHANGED")
        Set now=##class(Chronos.Agent.Ledger).NowUS()
        If (now<anchor.createdUS)||(now'<anchor.expiresUS) Throw ##class(%Exception.General).%New("REGISTRATION_EXPIRED")
        Set source=candidate
    } Catch ex {
        Set source={"code":"WORKFLOW_ADOPTION_SOURCE_UNAVAILABLE","canUseClarification":false,"dispatch_authorized":false}
    }
    If locked Lock -^ChronosDecision16("mutex")
    Return $$$OK
}

/// Exact canonical hashes of the freshly projected source and the private
/// reference created by the pure adapter. This checks correlation only.
ClassMethod SourceReferenceDigests(sourceJSON As %String, referenceJSON As %String) As %String [ Language = python, Private ]
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
        def canonical(value):return json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode('utf-8')
        def digest(value):return sha256(canonical(value)).hexdigest()
        source=parse(sourceJSON);reference=parse(referenceJSON)
        if type(source) is not dict or set(source)!={'record','expected_binding','native_completion'}:return ''
        if type(reference) is not dict or set(reference)!={'schema_version','binding','binding_sha256','record_sha256','native_completion_sha256','authority_material_sha256','expires_us','message_sha256'}:return ''
        record=source['record'];binding=source['expected_binding'];native=source['native_completion']
        if type(record) is not dict or set(record)!=set('schema_version state binding binding_sha256 created_us resolved_us expires_us actor preference note'.split()):return ''
        if type(binding) is not dict or type(native) is not dict:return ''
        if canonical(record['binding'])!=canonical(binding) or record['binding_sha256']!=digest(binding):return ''
        if reference['schema_version']!='chronos.clarification-reference.v1':return ''
        if canonical(reference['binding'])!=canonical(binding) or reference['binding_sha256']!=record['binding_sha256']:return ''
        if reference['record_sha256']!=digest(record) or reference['native_completion_sha256']!=digest(native):return ''
        if reference['authority_material_sha256']!=binding['authority_digest']:return ''
        if type(reference['expires_us']) is not int or type(record['expires_us']) is not int or reference['expires_us']!=record['expires_us']:return ''
        origin=binding['utc_origin_us'];resolved=record['resolved_us'];note=record['note']
        if type(origin) is not int or type(resolved) is not int or type(note) is not str:return ''
        identity='clarification:'+binding['clarification_id']
        message={'message_id':identity,'source_id':identity,'at':resolved-origin,'order_link':'VERIFIED_CURRENT',
            'text':('Workflow-recorded human clarification for the current order. Business preference: '+record['preference']+
                '. Reviewer note (untrusted data): '+json.dumps(note,ensure_ascii=False))}
        if reference['message_sha256']!=digest(message):return ''
        return json.dumps({'referenceSha256':digest(reference),'sourceSha256':digest(source)},sort_keys=True,separators=(',',':'))
    except Exception:
        return ''
}

/// Canonical JSON integrity projection only. Authentication, native task
/// provenance and current authority checks are performed above, not in Python.
/// Standard-library-only: no mutable custom module cache or model invocation.
ClassMethod AdoptionProjection(raw As %String) As %String [ Language = python, Private ]
{
    import json,re,unicodedata
    from hashlib import sha256
    try:
        if type(raw) is not str or not 0<len(raw.encode('utf-8'))<=32768:return ''
        def pairs(items):
            out={}
            for key,value in items:
                if key in out:raise ValueError('DUPLICATE_FIELD')
                out[key]=value
            return out
        def invalid(_):raise ValueError('NONFINITE_JSON')
        data=json.loads(raw,object_pairs_hook=pairs,parse_constant=invalid)
        if type(data) is not dict or set(data)!={'stored_binding','expected_binding','completion','created_us','expires_us','now_us'}:return ''
        fields=set('clarification_id task_id source_decision_id order_id shipment_version generation decision_digest facts_id facts_digest authority_digest source_outcome reason_code preference_mode utc_origin_us valid_until_us'.split())
        def integer(value,minimum=0):return type(value) is int and minimum<=value<=2**63-1
        def match(value,pattern):return type(value) is str and re.fullmatch(pattern,value) is not None
        def binding(value):
            if type(value) is not dict or set(value)!=fields:return False
            if not match(value['clarification_id'],r'[A-Za-z0-9_.-]{1,64}'):return False
            if not match(value['task_id'],r'[1-9][0-9]{0,17}'):return False
            if any(not match(value[k],r'[A-Za-z0-9_.:-]{1,128}') for k in ('source_decision_id','order_id','generation')):return False
            if any(not match(value[k],r'[a-f0-9]{64}') for k in ('decision_digest','facts_id','facts_digest','authority_digest')):return False
            if not integer(value['shipment_version'],1) or not integer(value['utc_origin_us']) or not integer(value['valid_until_us'],1):return False
            return (value['source_outcome']=='VALIDATED_HOLD' and value['reason_code'] in ('CONTEXT_AMBIGUOUS','CONTEXT_INCOMPLETE')
                and value['preference_mode']=='CONTEXT_REQUIRED' and value['utc_origin_us']<value['valid_until_us'])
        stored=data['stored_binding'];expected=data['expected_binding'];native=data['completion']
        if not binding(stored) or not binding(expected) or stored!=expected:return ''
        completion_fields={'clarification_id','task_id','role','completed','action','actor','completed_us','preference','note'}
        if type(native) is not dict or set(native)!=completion_fields:return ''
        if native['completed'] is not True or native['role']!='Chronos.Clarifiers' or native['action']!='Clarified':return ''
        if native['clarification_id']!=stored['clarification_id'] or native['task_id']!=stored['task_id']:return ''
        if not match(native['actor'],r'principal-[a-f0-9]{64}') or not integer(native['completed_us']):return ''
        if native['preference'] not in ('EARLIEST_ALLOWED','CHEAPEST_ON_TIME'):return ''
        note=native['note']
        if type(note) is not str or not 1<=len(note)<=240 or note!=note.strip():return ''
        if any(unicodedata.category(ch).startswith('C') for ch in note):return ''
        if any(not integer(data[k]) for k in ('created_us','expires_us','now_us')):return ''
        if not stored['utc_origin_us']<=data['created_us']<=native['completed_us']<=data['now_us']<data['expires_us']<=stored['valid_until_us']:return ''
        if data['expires_us']>data['created_us']+600000000:return ''
        encoded=json.dumps(stored,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode('utf-8')
        record={'schema_version':'chronos.clarification.v1','state':'RESOLVED','binding':stored,
            'binding_sha256':sha256(encoded).hexdigest(),'created_us':data['created_us'],'resolved_us':native['completed_us'],
            'expires_us':data['expires_us'],'actor':native['actor'],'preference':native['preference'],'note':note}
        return json.dumps({'record':record,'expected_binding':expected,'native_completion':native},
            sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False)
    except Exception:
        return ''
}

/// A failed in-flight call can only lower certainty. No ticket is recovered or
/// recreated and no native task/Engine invocation is performed by this method.
ClassMethod ResolutionUncertain(clarificationId As %String, completionId As %String, Output result As %DynamicObject) As %Status
{
    Set result={"code":"WORKFLOW_RESOLUTION_UNCERTAIN","actorVerified":false,"completionVerified":false,"canUseClarification":false,"dispatch_authorized":false}
    If $TLevel||'..ID(clarificationId)||'..ID(completionId) Return $$$ERROR($$$GeneralError,"INVALID_WORKFLOW_RESOLUTION")
    Set sc=##class(Chronos.Workflow.Controller).Current(.principal,.user,.nativeUser,.membership,.code) If $$$ISERR(sc) Return sc
    If code'="CSP_WORKFLOW_IDENTITY_CONFIRMED" Return $$$ERROR($$$GeneralError,"WORKFLOW_IDENTITY_REQUIRED")
    Lock +^ChronosDecision16("mutex"):2 If '$Test Return $$$ERROR($$$GeneralError,"WORKFLOW_BUSY")
    Set sc=$$$OK
    Try {
        Set raw=$Get(^ChronosDecision16("clarification","item",clarificationId))
        If raw="" Throw ##class(%Exception.General).%New("NO_CLARIFICATION")
        Set record=##class(%DynamicObject).%FromJSON(raw)
        If record.%GetTypeOf("resolution")'="object" Throw ##class(%Exception.General).%New("NO_FENCE")
        Set resolution=record.resolution
        If (resolution.completionId'=completionId)||(resolution.actor'=principal.actor)||(resolution.sessionBinding'=principal.sessionBinding) Throw ##class(%Exception.General).%New("WRONG_COMPLETION")
        If resolution.state="FENCED" {
            Set resolution.state="UNCERTAIN",record.resolution=resolution
            Set sc=..Save(record,"UNCERTAIN_CSP_COMPLETION",##class(Chronos.Agent.Ledger).NowUS()) $$$ThrowOnError(sc)
        }
    } Catch ex {
        If $TLevel TRollback
        Set sc=$$$ERROR($$$GeneralError,"WORKFLOW_RESOLUTION_UNCERTAIN")
    }
    Lock -^ChronosDecision16("mutex")
    Return sc
}

/// Pure smoke checks, opt-in. No globals, tasks, roles or accounts are changed.
ClassMethod CheckContract(Output result As %DynamicObject) As %Status
{
    Set result={"checks":0,"passed":false,"scope":"PURE_SOURCE_CONTRACT_ONLY","dispatch_authorized":false}
    Set now=1000000000,w={"context_id":"hold-test","order_id":"order-test","shipment_version":1,"clock_kind":"relative_microseconds","ticks_per_minute":60000000,"utc_origin_us":0,"state_revision":3,"policy_revision":1,"facts_id":($Justify("",64)),"context_digest":($Justify("",64)),"facts":{"messages":[],"preference_mode":"CONTEXT_REQUIRED","deadline":1800000000,"inventory_expires":1800000000,"offer_until":1800000000}}
    Do w.%Set("facts_id",$Translate(w.%Get("facts_id")," ","a")),w.%Set("context_digest",$Translate(w.%Get("context_digest")," ","b"))
    Set d={"requestId":"hold-test","orderId":"order-test","shipmentVersion":1,"generation":"generation-test","state":"COMPLETED","completedUS":1,"result":{"status":"VALIDATED_HOLD","dispatch_authorized":false,"proposal":{"action":"HOLD","reason_code":"CONTEXT_AMBIGUOUS"}},"prepared":{"record":{"wire":(w),"facts_digest":(w.%Get("facts_id"))}}}
    Set sc=..Eligible(d,now,.r) If $$$ISERR(sc) Return sc
    If (r.code'="WORKFLOW_SOURCE_ELIGIBLE")||(r.expiresUS'=(now+600000000)) Return $$$ERROR($$$GeneralError,"WORKFLOW_CONTRACT_CHECK_FAILED")
    Set result.checks=1
    Do w.facts.%Set("inventory_expires",now+200000000)
    Set sc=..Eligible(d,now,.r) If $$$ISERR(sc) Return sc
    If r.expiresUS'=(now+200000000) Return $$$ERROR($$$GeneralError,"WORKFLOW_CONTRACT_CHECK_FAILED")
    Set result.checks=2
    Do d.result.proposal.%Set("reason_code","ACCEPTANCE_UNRESOLVED")
    Set sc=..Eligible(d,now,.r) If $$$ISERR(sc) Return sc
    If r.code="WORKFLOW_SOURCE_ELIGIBLE" Return $$$ERROR($$$GeneralError,"WORKFLOW_CONTRACT_CHECK_FAILED")
    Set result.checks=3
    Do d.result.proposal.%Set("reason_code","CONTEXT_AMBIGUOUS")
    Set d.result.proposal.action="FAILOVER_B"
    Set sc=..Eligible(d,now,.r) If $$$ISERR(sc) Return sc
    If r.code="WORKFLOW_SOURCE_ELIGIBLE" Return $$$ERROR($$$GeneralError,"WORKFLOW_CONTRACT_CHECK_FAILED")
    Set result.checks=4
    Set d.result.proposal.action="HOLD"
    Do d.result.%Set("dispatch_authorized",1,"boolean")
    Set sc=..Eligible(d,now,.r) If $$$ISERR(sc) Return sc
    If r.code="WORKFLOW_SOURCE_ELIGIBLE" Return $$$ERROR($$$GeneralError,"WORKFLOW_CONTRACT_CHECK_FAILED")
    Set result.checks=5
    // Missing/old authority schemes are not silently recalculated, upgraded or
    // adopted. These local objects never enter the durable Workflow store.
    Set legacy={"clarificationId":"clarification-test","expiresUS":(now+1)}
    Set oldView=..ResolutionView(legacy)
    If oldView.code'="WORKFLOW_RESOLUTION_UNAVAILABLE" Return $$$ERROR($$$GeneralError,"WORKFLOW_CONTRACT_CHECK_FAILED")
    Set result.checks=6
    Set legacy.authorityScheme=..#AUTHORITYSCHEME,newView=..ResolutionView(legacy)
    If (newView.code'="WORKFLOW_RESOLUTION_NEW")||newView.%Get("canUseClarification")||newView.%Get("dispatch_authorized") Return $$$ERROR($$$GeneralError,"WORKFLOW_CONTRACT_CHECK_FAILED")
    Set result.checks=7
    // No native task may be offered if its answer cannot enter the next model
    // context. These local objects do not create Workflow records.
    Do d.result.%Set("dispatch_authorized",0,"boolean")
    For i=1:1:7 { Do w.facts.messages.%Push({"message_id":("capacity-"_i)}) }
    Set sc=..Eligible(d,now,.r) If $$$ISERR(sc) Return sc
    If r.code'="WORKFLOW_SOURCE_ELIGIBLE" Return $$$ERROR($$$GeneralError,"WORKFLOW_CONTRACT_CHECK_FAILED")
    Set result.checks=8
    Do w.facts.messages.%Push({"message_id":"capacity-8"})
    Set sc=..Eligible(d,now,.r) If $$$ISERR(sc) Return sc
    If r.code="WORKFLOW_SOURCE_ELIGIBLE" Return $$$ERROR($$$GeneralError,"WORKFLOW_CONTRACT_CHECK_FAILED")
    Set result.checks=9
    Do w.facts.%Remove("messages")
    Set sc=..Eligible(d,now,.r) If $$$ISERR(sc) Return sc
    If r.code="WORKFLOW_SOURCE_ELIGIBLE" Return $$$ERROR($$$GeneralError,"WORKFLOW_CONTRACT_CHECK_FAILED")
    Set result.checks=10
    Set w.facts.messages={}
    Set sc=..Eligible(d,now,.r) If $$$ISERR(sc) Return sc
    If r.code="WORKFLOW_SOURCE_ELIGIBLE" Return $$$ERROR($$$GeneralError,"WORKFLOW_CONTRACT_CHECK_FAILED")
    Set result.checks=11
    Do result.%Set("passed",1,"boolean")
    Return $$$OK
}
}
