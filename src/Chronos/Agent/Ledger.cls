Include %occStatus

/// TRUSTED NATIVE CALLERS ONLY. No provider or model I/O here. Clarified
/// registration obtains separate original-CSP proof before entering locks/T.
/// Private context/tickets must not be exposed through public endpoints or traces.
Class Chronos.Agent.Ledger Extends %RegisteredObject
{
ClassMethod NowUS() As %Numeric
{
    Set stamp=$ZTimestamp
    // Build 154 can return nanoseconds. Truncate the fractional string before
    // epoch arithmetic, so durable microseconds are integral and never rounded up.
    Set seconds=$Piece(stamp,",",2),fraction=$Extract($Piece(seconds,".",2)_"000000",1,6)
    Return ((($Piece(stamp,",",1)-$ZDateH("1970-01-01",3))*86400+$Piece(seconds,".",1))*1000000)+fraction
}

ClassMethod ID(value As %String) As %Boolean [ Private ]
{
    Return ($Length(value)>0)&&($Length(value)<=128)&&($Translate(value,"abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.")="")
}

ClassMethod Shape(a As %DynamicObject, fields As %String) As %Boolean [ Private ]
{
    If '$IsObject(a) Return 0
    If 'a.%IsA("%DynamicObject") Return 0
    If a.%Size()'=$Length(fields,",") Return 0
    For i=1:1:$Length(fields,",") { If 'a.%IsDefined($Piece(fields,",",i)) Return 0 }
    Return 1
}

ClassMethod Hash(value As %String) As %Boolean [ Private ]
{
    Return ($Length(value)=64)&&($Translate(value,"0123456789abcdef")="")
}

/// Identical raw-string algorithm to Workflow.Store.Digest, including native
/// actor correlation. Never replace it with a JSON serialization hash.
ClassMethod RawDigest(value As %String) As %String [ Private ]
{
    Return $ZConvert(##class(%xsd.hexBinary).LogicalToXSD($System.Encryption.SHAHash(256,value)),"L")
}

/// Full authority stamp: both effect and operation, including snapshot nonce
/// and observation time. The two-field Workflow material exclusion is NOT used.
ClassMethod FullAuthorityDigest(raw As %String) As %String [ Language = python, Private ]
{
    import json
    from hashlib import sha256
    try:
        if type(raw) is not str or not 0<len(raw.encode('utf-8'))<=262144:return ''
        def pairs(items):
            out={}
            for key,value in items:
                if key in out:raise ValueError('DUPLICATE_JSON_FIELD')
                out[key]=value
            return out
        def invalid(_):raise ValueError('NONFINITE_JSON')
        a=json.loads(raw,object_pairs_hook=pairs,parse_constant=invalid)
        if type(a) is not dict or type(a.get('effect')) is not dict or type(a.get('operation')) is not dict:return ''
        encoded=json.dumps({'effect':a['effect'],'operation':a['operation']},sort_keys=True,
            ensure_ascii=False,separators=(',',':'),allow_nan=False).encode('utf-8')
        return sha256(encoded).hexdigest()
    except Exception:
        return ''
}

/// Called only inside the ledger transaction, after original-CSP proof and the
/// current full-authority read have finished. Only private globals and pure
/// structural/hash checks are permitted here; no Task/account/role I/O.
ClassMethod ValidateClarified(a As %DynamicObject, grant As %DynamicObject, verifiedAuthority As %String, now As %Numeric, Output anchor As %DynamicObject) As %Status [ Private ]
{
    Set anchor=""
    If '$TLevel Return $$$ERROR($$$GeneralError,"CLARIFIED_TRANSACTION_REQUIRED")
    If '..Shape(a,"requestId,orderId,shipmentVersion,mode,generation,prepared") Return $$$ERROR($$$GeneralError,"INVALID_CLARIFIED_REGISTRATION")
    If '..Shape(grant,"anchor,nativeRecordSha256,sourceDecisionSha256") Return $$$ERROR($$$GeneralError,"CSP_REGISTRATION_REQUIRED")
    If (grant.%GetTypeOf("anchor")'="object")||'..Shape(grant.anchor,"schema,requestId,clarificationId,user,actor,generation,referenceSha256,sourceSha256,createdUS,expiresUS") Return $$$ERROR($$$GeneralError,"INVALID_CLARIFICATION_ANCHOR")
    If (a.%GetTypeOf("prepared")'="object")||(a.prepared.%GetTypeOf("record")'="object")||(a.prepared.record.%GetTypeOf("clarification_binding")'="object") Return $$$ERROR($$$GeneralError,"CLARIFIED_CONTEXT_REQUIRED")
    Set reference=a.prepared.record.%Get("clarification_binding")
    If reference.%GetTypeOf("binding")'="object" Return $$$ERROR($$$GeneralError,"CLARIFIED_BINDING_REQUIRED")
    Set b=reference.binding
    If (b.%GetTypeOf("source_decision_id")'="string")||'..ID(b.%Get("source_decision_id")) Return $$$ERROR($$$GeneralError,"INVALID_SOURCE_DECISION")
    If (grant.anchor.%GetTypeOf("clarificationId")'="string")||'..ID(grant.anchor.clarificationId)||(grant.anchor.%GetTypeOf("user")'="string") Return $$$ERROR($$$GeneralError,"INVALID_CLARIFICATION_ANCHOR")
    If '..Hash(grant.%Get("nativeRecordSha256"))||'..Hash(grant.%Get("sourceDecisionSha256"))||'..Hash(verifiedAuthority) Return $$$ERROR($$$GeneralError,"INVALID_REGISTRATION_PROOF")
    Set handoffRaw=$Get(^ChronosDecision16("clarification","item",grant.anchor.clarificationId)),parentRaw=$Get(^ChronosDecision16("decision",b.%Get("source_decision_id")))
    If (handoffRaw="")||(parentRaw="") Return $$$ERROR($$$GeneralError,"REGISTRATION_SOURCE_DISAPPEARED")
    If (..RawDigest(handoffRaw)'=grant.nativeRecordSha256)||(..RawDigest(parentRaw)'=grant.sourceDecisionSha256)||(b.%Get("decision_digest")'=grant.sourceDecisionSha256) Return $$$ERROR($$$GeneralError,"REGISTRATION_SOURCE_CHANGED")
    Set priorRaw=$Get(^ChronosDecision16("decision",a.requestId)),indexRaw=$Get(^ChronosDecision16("clarificationAdoption",grant.anchor.clarificationId))
    If priorRaw'="" {
        Set prior=##class(%DynamicObject).%FromJSON(priorRaw)
        If prior.%GetTypeOf("clarificationAnchor")'="object" Return $$$ERROR($$$GeneralError,"REQUEST_CONTEXT_CONFLICT")
        If (indexRaw="")||(indexRaw'=prior.clarificationAnchor.%ToJSON()) Return $$$ERROR($$$GeneralError,"CLARIFICATION_INDEX_CHANGED")
    } ElseIf indexRaw'="" { Return $$$ERROR($$$GeneralError,"CLARIFICATION_ALREADY_REGISTERED") }
    Set expectedActor="principal-"_..RawDigest($ListBuild($Namespace,grant.anchor.user))
    Set envelope={"args":(a),"grant":(grant),"handoffJSON":(handoffRaw),"parentJSON":(parentRaw),"priorJSON":(priorRaw),"indexJSON":(indexRaw),"expectedActor":(expectedActor),"verifiedAuthority":(verifiedAuthority),"authorityScheme":(##class(Chronos.Workflow.Store).#AUTHORITYSCHEME),"nowUS":(now)}
    Set encoded=..ClarifiedMaterial(envelope.%ToJSON())
    If encoded="" Return $$$ERROR($$$GeneralError,"CLARIFIED_REGISTRATION_CHANGED")
    Set anchor=##class(%DynamicObject).%FromJSON(encoded)
    If '..Shape(anchor,"schema,requestId,clarificationId,user,actor,generation,referenceSha256,sourceSha256,createdUS,expiresUS") Return $$$ERROR($$$GeneralError,"INVALID_CLARIFICATION_ANCHOR")
    Return $$$OK
}

/// Pure transaction-time validation. sourceSha256 plus the record/completion
/// hashes are opaque attestations calculated by CSPRegistration, not a model
/// hash or client consent. The native caller has just compared BOTH raw private
/// snapshots. SourceForDecision rereads the actual task before later phases.
ClassMethod ClarifiedMaterial(raw As %String) As %String [ Language = python, Private ]
{
    import json,re
    from hashlib import sha256
    try:
        def need(value):
            if not value:raise ValueError('INVALID_CLARIFIED_MATERIAL')
        def pairs(items):
            result={}
            for key,value in items:
                need(key not in result);result[key]=value
            return result
        def invalid(_):raise ValueError('NONFINITE_JSON')
        def parse(value):
            need(type(value) is str and 0<len(value.encode('utf-8'))<=2097152)
            return json.loads(value,object_pairs_hook=pairs,parse_constant=invalid)
        def exact(value,fields):need(type(value) is dict and set(value)==set(fields.split()))
        def integer(value,minimum=0):need(type(value) is int and minimum<=value<=2**63-1)
        def match(value,pattern):need(type(value) is str and re.fullmatch(pattern,value) is not None)
        def canonical(value):return json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False)
        def digest(value):return sha256(canonical(value).encode('utf-8')).hexdigest()
        def same(left,right):need(canonical(left)==canonical(right))
        e=parse(raw)
        exact(e,'args grant handoffJSON parentJSON priorJSON indexJSON expectedActor verifiedAuthority authorityScheme nowUS')
        a,g=e['args'],e['grant'];integer(e['nowUS']);now=e['nowUS']
        exact(a,'requestId orderId shipmentVersion mode generation prepared')
        exact(g,'anchor nativeRecordSha256 sourceDecisionSha256');anchor=g['anchor']
        anchor_fields='schema requestId clarificationId user actor generation referenceSha256 sourceSha256 createdUS expiresUS'
        exact(anchor,anchor_fields)
        need(anchor['schema']=='chronos.clarification-registration.v1')
        for key in ('requestId','clarificationId'):match(anchor[key],r'[A-Za-z0-9_.-]{1,64}')
        match(anchor['generation'],r'[A-Za-z0-9_.:-]{1,128}')
        need(type(anchor['user']) is str and 1<=len(anchor['user'])<=256 and anchor['user'].lower()!='unknownuser')
        match(anchor['actor'],r'principal-[a-f0-9]{64}');need(anchor['actor']==e['expectedActor'])
        for key in ('referenceSha256','sourceSha256'):match(anchor[key],r'[a-f0-9]{64}')
        for key in ('nativeRecordSha256','sourceDecisionSha256'):match(g[key],r'[a-f0-9]{64}')
        match(e['verifiedAuthority'],r'[a-f0-9]{64}')
        integer(anchor['createdUS']);integer(anchor['expiresUS'],1)
        need(anchor['createdUS']<=now<anchor['expiresUS'])
        for key in ('requestId','orderId','generation'):match(a[key],r'[A-Za-z0-9_.-]{1,128}')
        integer(a['shipmentVersion'],1);need(a['mode'] in ('WITH_TRIALS','WITHOUT_TRIALS_ABLATION'))
        need(anchor['requestId']==a['requestId'] and anchor['generation']==a['generation'])
        p=a['prepared'];need(type(p) is dict and p.get('status')=='READY' and p.get('dispatch_authorized') is False)
        need(p.get('runtime_generation')==a['generation'] and type(p.get('record')) is dict)
        rec=p['record'];need('clarificationAnchor' not in p and 'clarificationAnchor' not in rec)
        need(type(rec.get('wire')) is dict and type(rec.get('clarification_binding')) is dict)
        w=rec['wire'];reference=rec['clarification_binding']
        exact(reference,'schema_version binding binding_sha256 record_sha256 native_completion_sha256 authority_material_sha256 expires_us message_sha256')
        need(reference['schema_version']=='chronos.clarification-reference.v1')
        b=reference['binding']
        exact(b,'clarification_id task_id source_decision_id order_id shipment_version generation decision_digest facts_id facts_digest authority_digest source_outcome reason_code preference_mode utc_origin_us valid_until_us')
        match(b['clarification_id'],r'[A-Za-z0-9_.-]{1,64}');match(b['task_id'],r'[1-9][0-9]{0,17}')
        for key in ('source_decision_id','order_id','generation'):match(b[key],r'[A-Za-z0-9_.:-]{1,128}')
        for key in ('decision_digest','facts_id','facts_digest','authority_digest'):match(b[key],r'[a-f0-9]{64}')
        integer(b['shipment_version'],1);integer(b['utc_origin_us']);integer(b['valid_until_us'],1)
        need(b['source_outcome']=='VALIDATED_HOLD' and b['reason_code'] in ('CONTEXT_AMBIGUOUS','CONTEXT_INCOMPLETE') and b['preference_mode']=='CONTEXT_REQUIRED')
        need(b['utc_origin_us']<b['valid_until_us'] and b['clarification_id']==anchor['clarificationId']
            and b['source_decision_id']!=a['requestId'] and b['order_id']==a['orderId']
            and b['shipment_version']==a['shipmentVersion'] and b['generation']==a['generation'])
        for key in ('binding_sha256','record_sha256','native_completion_sha256','authority_material_sha256','message_sha256'):match(reference[key],r'[a-f0-9]{64}')
        need(reference['binding_sha256']==digest(b) and reference['authority_material_sha256']==b['authority_digest'])
        integer(reference['expires_us'],1);need(reference['expires_us']==anchor['expiresUS'])
        need(digest(reference)==anchor['referenceSha256'])
        need(rec.get('authority_stamp')==e['verifiedAuthority'] and rec.get('review_authority_stamp')==b['authority_digest'])
        for key in ('started_us','deadline_us','review_deadline_us'):integer(rec.get(key))
        need(rec['started_us']<=now<rec['deadline_us']<=rec['started_us']+30000000
            and rec['deadline_us']<=rec['review_deadline_us']<=anchor['expiresUS'])
        for key,wkey in (('requestId','context_id'),('orderId','order_id'),('shipmentVersion','shipment_version'),('mode','trial_mode')):same(a[key],w.get(wkey))
        same(w.get('utc_origin_us'),b['utc_origin_us']);same(w.get('facts_id'),b['facts_id'])
        need(type(w.get('facts')) is dict and rec.get('facts_digest')==digest(w['facts']))
        need(w.get('context_digest')==digest({k:v for k,v in w.items() if k!='context_digest'}))
        handoff,parent=parse(e['handoffJSON']),parse(e['parentJSON'])
        need(type(handoff) is dict and handoff.get('schema')=='chronos.workflow-handoff.v1')
        need(e['authorityScheme']=='chronos.workflow-material-authority.v1' and handoff.get('authorityScheme')==e['authorityScheme'])
        need(handoff.get('state')!='EXPIRED' and handoff.get('role')=='Chronos.Clarifiers')
        for hkey,bkey in (('clarificationId','clarification_id'),('decisionId','source_decision_id'),('orderId','order_id'),('shipmentVersion','shipment_version'),('generation','generation'),('sourceDecisionSha256','decision_digest'),('sourceFactsId','facts_id'),('sourceFactsDigest','facts_digest'),('authorityDigest','authority_digest'),('utcOriginUS','utc_origin_us')):same(handoff.get(hkey),b[bkey])
        need(g['sourceDecisionSha256']==b['decision_digest'])
        integer(handoff.get('requestedUS'));integer(handoff.get('expiresUS'),1)
        need(handoff['expiresUS']==anchor['expiresUS'] and handoff['expiresUS']<=handoff['requestedUS']+600000000)
        need(type(parent) is dict and parent.get('state')=='COMPLETED' and parent.get('requestId')==b['source_decision_id'])
        for pkey,bkey in (('orderId','order_id'),('shipmentVersion','shipment_version'),('generation','generation')):same(parent.get(pkey),b[bkey])
        outcome=parent.get('result');need(type(outcome) is dict and outcome.get('status')=='VALIDATED_HOLD' and outcome.get('dispatch_authorized') is False)
        need(type(outcome.get('proposal')) is dict and outcome['proposal'].get('action')=='HOLD' and outcome['proposal'].get('reason_code')==b['reason_code'])
        pp=parent.get('prepared');need(type(pp) is dict and type(pp.get('record')) is dict)
        pr=pp['record'];pw=pr.get('wire');need(type(pw) is dict and type(pw.get('facts')) is dict)
        need(pr.get('review_authority_stamp')==b['authority_digest'] and pr.get('facts_digest')==b['facts_digest'])
        need(pw.get('facts_id')==b['facts_id'] and pw.get('context_digest')==handoff.get('sourceContextDigest'))
        need(pw.get('utc_origin_us')==b['utc_origin_us'] and pw['facts'].get('preference_mode')=='CONTEXT_REQUIRED')
        limits=[pw['facts'].get(k) for k in ('deadline','inventory_expires','offer_until')]
        for value in limits:integer(value)
        need(b['valid_until_us']==b['utc_origin_us']+min(limits))
        need(handoff['expiresUS']==min(handoff['requestedUS']+600000000,b['valid_until_us']))
        resolution=handoff.get('resolution');need(type(resolution) is dict)
        need(resolution.get('schema')=='chronos.workflow-csp-completion.v1' and resolution.get('state')=='VERIFIED_CSP'
            and resolution.get('ticketConsumed') is True and 'ticketSha256' not in resolution)
        proof=resolution.get('evidence');need(type(proof) is dict and proof.get('schema')=='chronos.workflow-csp-evidence.v1')
        need(proof.get('actorBasis')=='ORIGINAL_CSP_CALL_AND_NATIVE_READBACK' and proof.get('isNativeAssigneeCompleterProof') is False
            and proof.get('providerFactsVerified') is False)
        need(resolution.get('actor')==anchor['actor']==proof.get('actor') and resolution.get('taskId')==b['task_id']==proof.get('taskId'))
        need(resolution.get('taskRequestId')==handoff.get('taskRequestId')==proof.get('taskRequestId'))
        need(handoff.get('taskId') in ('',b['task_id']) and proof.get('role')=='Chronos.Clarifiers' and proof.get('action')=='Clarified')
        need(proof.get('generation')==b['generation'] and proof.get('sourceDecisionSha256')==b['decision_digest'])
        need(resolution.get('preference') in ('EARLIEST_ALLOWED','CHEAPEST_ON_TIME') and resolution['preference']==proof.get('preference'))
        for key in ('completedUS','verifiedUS'):integer(proof.get(key))
        integer(resolution.get('startedUS'));integer(resolution.get('verifiedUS'))
        need(proof['verifiedUS']==resolution['verifiedUS'] and handoff['requestedUS']<=resolution['startedUS']
            and (resolution['startedUS']//1000)*1000<=proof['completedUS']<=proof['verifiedUS']<=anchor['createdUS']<=now<handoff['expiresUS'])
        for key in ('payloadSha256','noteSha256'):match(resolution.get(key),r'[a-f0-9]{64}')
        need(proof.get('noteSha256')==resolution['noteSha256']);integer(resolution.get('noteBytes'),1)
        need(proof.get('noteBytes')==resolution['noteBytes'])
        oldfacts=pw['facts'];newfacts=w['facts']
        same({k:v for k,v in oldfacts.items() if k!='messages'},{k:v for k,v in newfacts.items() if k!='messages'})
        oldmessages=oldfacts.get('messages');messages=newfacts.get('messages')
        need(type(oldmessages) is list and type(messages) is list and 1<=len(messages)<=8)
        need(len(messages)==len(oldmessages)+1);same(messages[:-1],oldmessages)
        message=messages[-1];exact(message,'message_id source_id at order_link text')
        need(message['message_id']==message['source_id']=='clarification:'+b['clarification_id'] and message['order_link']=='VERIFIED_CURRENT')
        integer(message['at']);need(message['at']==proof['completedUS']-b['utc_origin_us'] and type(message['text']) is str)
        need(reference['message_sha256']==digest(message))
        prior=parse(e['priorJSON']) if e['priorJSON'] else None
        index=parse(e['indexJSON']) if e['indexJSON'] else None
        if prior is not None:
            need(type(prior) is dict and prior.get('requestId')==a['requestId'])
            old=prior.get('clarificationAnchor');exact(old,anchor_fields);need(type(index) is dict);same(old,index)
            for key in anchor:
                if key!='createdUS':same(old[key],anchor[key])
            integer(old['createdUS']);need(proof['completedUS']<=old['createdUS']<=anchor['createdUS'])
            anchor=old
        else:need(index is None)
        return canonical(anchor)
    except Exception:
        return ''
}

/// Lock order: bootLock (where needed), then ledger mutex, then transaction.
/// Readiness/authority reads finish BEFORE opening the ledger transaction.
ClassMethod Apply(command As %String, args As %DynamicObject, Output result As %DynamicObject) As %Status
{
    Set result={"code":"NOT_APPLIED","inferenceGranted":false,"validationGranted":false,"dispatch_authorized":false}
    If $TLevel Return $$$ERROR($$$GeneralError,"LEDGER_REQUIRES_NO_TRANSACTION")
    If ",REGISTER,REGISTER_CLARIFIED,RECORD_DETERMINISTIC,READ,INSPECT,PREVIOUS,CLAIM,BIND_CALL,BEGIN_FINISH,COMPLETE,CANCEL,RECOVER,RESOLVE,"'[(","_command_",") Return $$$ERROR($$$GeneralError,"UNKNOWN_LEDGER_COMMAND")
    Set clarificationGrant="",verifiedAuthority=""
    If command="REGISTER_CLARIFIED" {
        // CSP/task/membership reads must finish before bootLock, mutex or T.
        // The opaque grant is obtained here, never supplied in request JSON.
        Try {
            If '..Shape(args,"requestId,orderId,shipmentVersion,mode,generation,prepared") Throw ##class(%Exception.General).%New("INVALID_CLARIFIED_REGISTRATION")
            Set sc=##class(Chronos.Workflow.Store).CSPRegistration(args,.clarificationGrant) $$$ThrowOnError(sc)
            If '..Shape(clarificationGrant,"anchor,nativeRecordSha256,sourceDecisionSha256") Throw ##class(%Exception.General).%New("CSP_REGISTRATION_REQUIRED")
        } Catch ex { Return $$$ERROR($$$GeneralError,"CLARIFIED_REGISTRATION_UNAVAILABLE") }
    }
    Set needsBoot=",REGISTER,REGISTER_CLARIFIED,RECORD_DETERMINISTIC,CLAIM,BIND_CALL,COMPLETE,RECOVER,RESOLVE,"[(","_command_","),ready={"ready":false,"generation":""}
    If needsBoot {
        Lock +^ChronosRuntime("bootLock"):2
        If '$Test Return $$$ERROR($$$GeneralError,"RUNTIME_BUSY")
        Set sc=##class(Chronos.Runtime.Bootstrap).Ready(.ready)
        If $$$ISERR(sc) {
            If command'="COMPLETE" {
                Lock -^ChronosRuntime("bootLock")
                Return $$$ERROR($$$GeneralError,"RUNTIME_READINESS_UNAVAILABLE")
            }
            // A valid completion ticket may consume its result conservatively.
            // This internal marker can never authorize a proposal or a new call.
            // Lock/transaction/ticket/shape failures still retain uncertainty.
            Set ready={"ready":false,"generation":"","readinessUnavailable":true}
        }
    }
    If command="REGISTER_CLARIFIED" {
        Try {
            If ('ready.ready)||(args.generation'=ready.generation) Throw ##class(%Exception.General).%New("STALE_RUNTIME_GENERATION")
            Set sc=##class(Chronos.Authority.Store).Apply("READ",{"orderId":(args.orderId),"shipmentVersion":(args.shipmentVersion)},.authority) $$$ThrowOnError(sc)
            Set verifiedAuthority=..FullAuthorityDigest(authority.%ToJSON())
            If '..Hash(verifiedAuthority)||(args.prepared.record.%Get("authority_stamp")'=verifiedAuthority) Throw ##class(%Exception.General).%New("CLARIFIED_AUTHORITY_CHANGED")
        } Catch ex {
            Lock -^ChronosRuntime("bootLock")
            Return $$$ERROR($$$GeneralError,"CLARIFIED_REGISTRATION_NOT_VERIFIED")
        }
    }
    If command="RECORD_DETERMINISTIC" {
        // Reobserve through the trusted bridge before any ledger transaction.
        // This stores a historical precontrol, never permission to call or act.
        Try {
            Set sc=..DeterministicArgs(args)
            $$$ThrowOnError(sc)
            If ('ready.ready)||(args.generation'=ready.generation) Throw ##class(%Exception.General).%New("STALE_RUNTIME_GENERATION")
            Set sc=##class(Chronos.Agent.Context).Prepare(args.orderId,args.shipmentVersion,args.requestId,args.mode,.fresh,args.generation)
            $$$ThrowOnError(sc)
            If fresh.%ToJSON()'=args.result.%ToJSON() Throw ##class(%Exception.General).%New("PRECONTROL_CHANGED")
        } Catch ex {
            Lock -^ChronosRuntime("bootLock")
            Return $$$ERROR($$$GeneralError,"PRECONTROL_NOT_VERIFIED")
        }
    }
    Lock +^ChronosDecision16("mutex"):2
    If '$Test {
        If needsBoot Lock -^ChronosRuntime("bootLock")
        Return $$$ERROR($$$GeneralError,"DECISION_BUSY")
    }
    Set sc=$$$OK,durabilityPending=0
    Try {
        Set readOnly=(command="READ")||(command="INSPECT")||(command="PREVIOUS")
        If 'readOnly { Set sc=##class(Chronos.Runtime.Durability).Check() $$$ThrowOnError(sc) }
        TStart
        Set now=..NowUS()
        If 'readOnly,now<$Get(^ChronosDecision16("clockHighWater"),0) {
            Set sc=$$$ERROR($$$GeneralError,"CLOCK_MOVED_BACKWARD")
        } Else {
            Set sc=..Transition(command,args,now,ready,.result,clarificationGrant,verifiedAuthority)
        }
        If $$$ISERR(sc) {
            TRollback
            Set result={"code":"REJECTED","inferenceGranted":false,"validationGranted":false,"dispatch_authorized":false}
        } Else {
            If 'readOnly {
                Set ^ChronosDecision16("clockHighWater")=now
                Set seq=$Increment(^ChronosDecision16("sequence"))
                Set ^ChronosDecision16("audit",seq)={"command":(command),"requestId":(args.%Get("requestId")),"code":(result.code),"atUS":(now)}.%ToJSON()
            }
            TCommit
            If 'readOnly {
                Set durabilityPending=1
                Set sc=##class(Chronos.Runtime.Durability).Flush() $$$ThrowOnError(sc)
                Set durabilityPending=0
            }
        }
    } Catch ex {
        If $TLevel TRollback
        Set code=$Select(durabilityPending:"LEDGER_DURABILITY_UNCERTAIN",1:"LEDGER_ERROR")
        Set result={"code":(code),"inferenceGranted":false,"validationGranted":false,"dispatch_authorized":false}
        Set sc=$$$ERROR($$$GeneralError,code)
    }
    Lock -^ChronosDecision16("mutex")
    If needsBoot Lock -^ChronosRuntime("bootLock")
    Return sc
}

ClassMethod View(d As %DynamicObject, code As %String) As %DynamicObject [ Private ]
{
    Set r={"code":(code),"requestId":(d.requestId),"orderId":(d.orderId),"shipmentVersion":(d.shipmentVersion),"mode":(d.mode),"state":(d.state),"generation":(d.generation),"deadlineUS":(d.deadlineUS),"inferenceGranted":false,"validationGranted":false,"dispatch_authorized":false}
    If d.%IsDefined("result") Set r.result=d.result
    If d.%IsDefined("call") Set r.call=d.call
    If d.%IsDefined("resolution") Set r.resolution=d.resolution
    Return r
}

ClassMethod Save(d As %DynamicObject) [ Private ]
{
    Set ^ChronosDecision16("decision",d.requestId)=d.%ToJSON()
    // Keep the latest index, including terminal state; REGISTER replaces it only
    // after checking that its predecessor really is COMPLETED.
}

ClassMethod Terminal(d As %DynamicObject, status As %String, code As %String, now As %Numeric) [ Private ]
{
    Set d.state="COMPLETED",d.completedUS=now
    Set d.result={"status":(status),"code":(code),"dispatch_authorized":false}
    Do ..Save(d)
}

ClassMethod Transition(command As %String, a As %DynamicObject, now As %Numeric, ready As %DynamicObject, Output result As %DynamicObject, clarificationGrant As %DynamicObject = "", verifiedAuthority As %String = "") As %Status [ Private ]
{
    If '$IsObject(a) Return $$$ERROR($$$GeneralError,"ARGUMENT_OBJECT_REQUIRED")
    If 'a.%IsA("%DynamicObject") Return $$$ERROR($$$GeneralError,"ARGUMENT_OBJECT_REQUIRED")
    If a.%GetTypeOf("requestId")'="string" Return $$$ERROR($$$GeneralError,"INVALID_REQUEST_ID")
    If '..ID(a.requestId) Return $$$ERROR($$$GeneralError,"INVALID_REQUEST_ID")
    If (command="REGISTER")||(command="REGISTER_CLARIFIED")||(command="RECORD_DETERMINISTIC")||(command="CLAIM")||(command="RECOVER")||(command="RESOLVE") {
        If ('ready.ready)||(a.%Get("generation")'=ready.generation) Return $$$ERROR($$$GeneralError,"STALE_RUNTIME_GENERATION")
    }
    If command="REGISTER" Return ..Register(a,now,.result)
    If command="REGISTER_CLARIFIED" {
        Set sc=..ValidateClarified(a,clarificationGrant,verifiedAuthority,now,.anchor)
        If $$$ISERR(sc) Return sc
        Return ..Register(a,now,.result,anchor)
    }
    If command="RECORD_DETERMINISTIC" Return ..RecordDeterministic(a,now,.result)
    Set raw=$Get(^ChronosDecision16("decision",a.requestId))
    If raw="" {
        Set result={"code":"NOT_FOUND","inferenceGranted":false,"validationGranted":false,"dispatch_authorized":false}
        Return $$$OK
    }
    Set d=##class(%DynamicObject).%FromJSON(raw)
    Set result=..View(d,"EXISTING_DECISION")
    If command="RESOLVE" {
        Set result={"code":"RESOLUTION_NOT_APPLIED","inferenceGranted":false,"validationGranted":false,"dispatch_authorized":false}
        If '..Shape(a,"requestId,generation,orderId,shipmentVersion,mode") Return $$$ERROR($$$GeneralError,"INVALID_RESOLUTION")
        For field="generation","orderId","mode" { If a.%GetTypeOf(field)'="string" Return $$$ERROR($$$GeneralError,"INVALID_RESOLUTION") }
        If a.%GetTypeOf("shipmentVersion")'="number" Return $$$ERROR($$$GeneralError,"INVALID_RESOLUTION")
        If (a.orderId'=d.orderId)||(a.shipmentVersion'=d.shipmentVersion)||(a.mode'=d.mode) Return $$$ERROR($$$GeneralError,"DECISION_IDENTITY_MISMATCH")
        If now<d.createdUS Return $$$ERROR($$$GeneralError,"CLOCK_MOVED_BACKWARD")
        If d.state="COMPLETED" { Set result=..View(d,"EXISTING_DECISION") Return $$$OK }
        If ",PREPARED,IN_FLIGHT,VALIDATING,UNCERTAIN,UNCERTAIN_VALIDATION,"'[(","_d.state_",") Return $$$ERROR($$$GeneralError,"INVALID_DECISION_STATE")
        If now<d.deadlineUS { Set result=..View(d,"DECISION_PENDING") Return $$$OK }
        // Expiry closes the local decision only. It proves neither that the
        // provider stopped nor that no tokens were generated. Never invoke it.
        Set previous=d.state,code=$Select(previous="PREPARED":"CONTEXT_EXPIRED",1:"MODEL_OUTCOME_UNAVAILABLE")
        Set d.resolution={"previousState":(previous),"resolvedUS":(now),"inferenceMayHaveRun":(previous'="PREPARED"),"providerCancellationVerified":false}
        Do ..Terminal(d,"ERROR",code,now)
        Set result=..View(d,"DECISION_RESOLVED")
        Return $$$OK
    }
    If command="PREVIOUS" {
        If '..Shape(a,"requestId") Return $$$ERROR($$$GeneralError,"INVALID_READ")
        Set result={"code":"HISTORY_NOT_FOUND","dispatch_authorized":false},ident="",count=0,best="",bestAt=-1
        For {
            Set ident=$Order(^ChronosDecision16("decision",ident)) Quit:ident=""
            Set count=count+1
            If count>512 { Set result={"code":"HISTORY_SCAN_LIMIT","dispatch_authorized":false} Return $$$OK }
            Set item=##class(%DynamicObject).%FromJSON(^ChronosDecision16("decision",ident))
            If (item.requestId'=d.requestId)&&(item.orderId=d.orderId)&&(item.shipmentVersion=d.shipmentVersion)&&(item.state="COMPLETED") {
                If (item.%GetTypeOf("completedUS")="number")&&(item.completedUS<=d.createdUS)&&(item.completedUS>bestAt)&&(item.%GetTypeOf("prepared")="object")&&(item.%GetTypeOf("result")="object") {
                    If item.result.%GetTypeOf("proposal")="object" Set best=item,bestAt=item.completedUS
                }
            }
        }
        If $IsObject(best) Set result={"code":"PREVIOUS_DECISION_RECORDED","private":(best),"dispatch_authorized":false}
        Return $$$OK
    }
    If (command="READ")||(command="INSPECT") {
        If '..Shape(a,"requestId") Return $$$ERROR($$$GeneralError,"INVALID_READ")
        // INSPECT is an internal API for the trusted service, never the UI.
        If command="INSPECT" Set result.private=d
        Return $$$OK
    }
    If (command="CLAIM")||(command="RECOVER") {
        If '..Shape(a,"requestId,generation") Return $$$ERROR($$$GeneralError,"INVALID_GENERATION_REQUEST")
        If a.%GetTypeOf("generation")'="string" Return $$$ERROR($$$GeneralError,"INVALID_GENERATION")
        If '..ID(a.generation) Return $$$ERROR($$$GeneralError,"INVALID_GENERATION")
        If command="RECOVER" {
            If a.generation=d.generation Return $$$OK
            If d.state="PREPARED" {
                Do ..Terminal(d,"RECHECK_REQUIRED","RUNTIME_GENERATION_CHANGED",now)
            } ElseIf d.state="IN_FLIGHT" {
                Set d.state="UNCERTAIN" Do ..Save(d)
            } ElseIf d.state="VALIDATING" {
                Set d.state="UNCERTAIN_VALIDATION" Do ..Save(d)
            }
            Set result=..View(d,"RECOVERY_RECORDED")
            Return $$$OK
        }
        If d.state'="PREPARED" Return $$$OK
        If a.generation'=d.generation {
            Do ..Terminal(d,"RECHECK_REQUIRED","RUNTIME_GENERATION_CHANGED",now)
        } ElseIf (now<d.createdUS)||(now'<d.deadlineUS) {
            Do ..Terminal(d,"ERROR","CONTEXT_EXPIRED",now)
        } Else {
            Set d.state="IN_FLIGHT",d.claimedUS=now,d.claimId=$System.Util.CreateGUID(),d.transportId=$ZConvert($System.Util.CreateGUID(),"L")
            Do ..Save(d)
            Set result=..View(d,"INFERENCE_GRANTED")
            Do result.%Set("inferenceGranted",1,"boolean")
            Set result.claimId=d.claimId,result.transportId=d.transportId,result.inputJSON=d.prepared.%Get("input_json"),result.instructions=d.prepared.instructions
            If d.prepared.record.%Get("response_contract")="chronos.preference-extraction.v1" Set result.responseContract="chronos.preference-extraction.v1"
            Return $$$OK
        }
        Set result=..View(d,"DECISION_CLOSED")
        Return $$$OK
    }
    If command="CANCEL" {
        If '..Shape(a,"requestId") Return $$$ERROR($$$GeneralError,"INVALID_CANCEL")
        If d.state="PREPARED" Do ..Terminal(d,"RECHECK_REQUIRED","CONTEXT_INVALIDATED",now)
        Set result=..View(d,"EXISTING_DECISION")
        Return $$$OK
    }
    If command="BIND_CALL" {
        // Terminal precontrols deliberately have no prepared model context.
        If d.%GetTypeOf("prepared")'="object" Return $$$ERROR($$$GeneralError,"PREPARED_CONTEXT_REQUIRED")
        Set config="",expectedModel="qwen38:cyber-32k",expectedProfile="",expectedReasoning="none",fields="requestId,claimId,transportId,aiHubSessionId,interopSessionId,model"
        If $Data(^ChronosAI18("config")) {
            Set config=##class(%DynamicObject).%FromJSON(^ChronosAI18("config"))
            Set expectedModel=config.model,expectedProfile=config.%Get("profileSha256")
            If config.%IsDefined("reasoningEffort") Set expectedReasoning=config.reasoningEffort
        }
        Set expectedContract=##class(Chronos.Agent.Model).Contract()
        If d.prepared.record.%Get("response_contract","chronos.agent-proposal.v2")'=expectedContract Return $$$ERROR($$$GeneralError,"PREPARED_RESPONSE_CONTRACT_MISMATCH")
        If expectedContract="chronos.preference-extraction.v1" Set fields=fields_",responseContract"
        If expectedProfile'="" Set fields=fields_",profileSha256"
        If '..Shape(a,fields) Return $$$ERROR($$$GeneralError,"INVALID_CALL_BINDING")
        If expectedContract="chronos.preference-extraction.v1",a.%Get("responseContract")'=expectedContract Return $$$ERROR($$$GeneralError,"RESPONSE_CONTRACT_MISMATCH")
        If expectedProfile'="",(a.%GetTypeOf("profileSha256")'="string")||(a.profileSha256'=expectedProfile) Return $$$ERROR($$$GeneralError,"MODEL_PROFILE_MISMATCH")
        If (a.%GetTypeOf("claimId")'="string")||(a.claimId="")||(a.claimId'=d.%Get("claimId")) Return $$$ERROR($$$GeneralError,"CLAIM_MISMATCH")
        If (a.%GetTypeOf("transportId")'="string")||(a.transportId'=d.%Get("transportId")) Return $$$ERROR($$$GeneralError,"TRANSPORT_MISMATCH")
        If (a.%GetTypeOf("aiHubSessionId")'="string")||(a.aiHubSessionId'?1.18N) Return $$$ERROR($$$GeneralError,"INVALID_AI_SESSION")
        If (a.%GetTypeOf("interopSessionId")'="string")||(a.interopSessionId'?1.18N) Return $$$ERROR($$$GeneralError,"INVALID_INTEROP_SESSION")
        If (a.%GetTypeOf("model")'="string")||(a.model'=expectedModel) Return $$$ERROR($$$GeneralError,"MODEL_NOT_CONFIGURED")
        If d.%IsDefined("call")||(d.state'="IN_FLIGHT") Return $$$OK
        If ('ready.ready)||(ready.generation'=d.generation)||(now'<d.deadlineUS) Return $$$ERROR($$$GeneralError,"CALL_NO_LONGER_ELIGIBLE")
        Set d.call={"transportId":(d.transportId),"aiHubSessionId":(a.aiHubSessionId),"interopSessionId":(a.interopSessionId),"model":(a.model),"maxTokens":2048,"maxIterations":1,"temperature":0,"boundUS":(now),"sessionSnapshot":"BEFORE_CHAT"}
        Set d.call.reasoningEffort=expectedReasoning
        If expectedContract="chronos.preference-extraction.v1" {
            Set d.call.responseContract=expectedContract,d.call.interpretationOrigin="MODEL",d.call.selectionOrigin="DETERMINISTIC_CODE"
            If $IsObject(config),config.%Get("executionMode")="RECORDED_FIXTURE" {
                Set modeStatus=##class(Chronos.Agent.Model).CheckExecution(config.executionMode,config.model,expectedProfile,expectedReasoning,config.%Get("replayCorpusSha256"),config.%Get("replayFixtureSha256"))
                If $$$ISERR(modeStatus) Return modeStatus
                Set d.call.executionMode="RECORDED_FIXTURE",d.call.interpretationOrigin="RECORDED_MODEL"
                Set d.call.replayCorpusSha256=config.replayCorpusSha256,d.call.replayFixtureSha256=config.replayFixtureSha256
            }
        }
        If expectedProfile'="" Set d.call.profileSha256=expectedProfile
        Do ..Save(d)
        Set result=..View(d,"CALL_BOUND")
        Do result.%Set("chatGranted",1,"boolean")
        Return $$$OK
    }
    If command="BEGIN_FINISH" {
        If '..Shape(a,"requestId,claimId") Return $$$ERROR($$$GeneralError,"INVALID_COMPLETION")
        If (a.%GetTypeOf("claimId")'="string")||(a.claimId="")||(a.claimId'=d.%Get("claimId")) Return $$$ERROR($$$GeneralError,"CLAIM_MISMATCH")
        If (d.state'="IN_FLIGHT")&&(d.state'="UNCERTAIN") Return $$$OK
        Set d.state="VALIDATING",d.validatingUS=now,d.validationId=$System.Util.CreateGUID()
        Do ..Save(d)
        Set result=..View(d,"VALIDATION_GRANTED")
        Do result.%Set("validationGranted",1,"boolean")
        Set result.validationId=d.validationId,result.record=d.prepared.record
        Return $$$OK
    }
    If command="COMPLETE" {
        If '..Shape(a,"requestId,validationId,result") Return $$$ERROR($$$GeneralError,"INVALID_RESULT")
        If (a.%GetTypeOf("validationId")'="string")||(a.validationId="")||(a.validationId'=d.%Get("validationId")) Return $$$ERROR($$$GeneralError,"VALIDATION_MISMATCH")
        If (d.state'="VALIDATING")&&(d.state'="UNCERTAIN_VALIDATION") Return $$$OK
        If a.%GetTypeOf("result")'="object" Return $$$ERROR($$$GeneralError,"INVALID_RESULT")
        Set r=a.result
        If (r.%GetTypeOf("status")'="string")||(r.%GetTypeOf("code")'="string") Return $$$ERROR($$$GeneralError,"INVALID_RESULT")
        If (r.%GetTypeOf("dispatch_authorized")'="boolean")||r.%Get("dispatch_authorized") Return $$$ERROR($$$GeneralError,"RESULT_CANNOT_AUTHORIZE")
        Set it=r.%GetIterator()
        While it.%GetNext(.key,.value) {
            If ",status,code,dispatch_authorized,proposal,runtime_generation,explanation,"'[(","_key_",") Return $$$ERROR($$$GeneralError,"UNEXPECTED_RESULT_FIELD")
        }
        If ",VALIDATED_PROPOSAL,VALIDATED_HOLD,ERROR,REJECTED,RECHECK_REQUIRED,"'[(","_r.status_",") Return $$$ERROR($$$GeneralError,"INVALID_RESULT_STATUS")
        If $Length($ZConvert(r.%ToJSON(),"O","UTF8"))>8192 Return $$$ERROR($$$GeneralError,"RESULT_TOO_LARGE")
        If r.%IsDefined("explanation") {
            If (r.status'="VALIDATED_PROPOSAL")&&(r.status'="VALIDATED_HOLD") Return $$$ERROR($$$GeneralError,"UNEXPECTED_EXPLANATION")
            If r.%GetTypeOf("explanation")'="object" Return $$$ERROR($$$GeneralError,"INVALID_EXPLANATION")
            Set receipt=r.explanation
            If (receipt.%GetTypeOf("schema")'="string")||(receipt.schema'="chronos.decision-explanation.v1") Return $$$ERROR($$$GeneralError,"INVALID_EXPLANATION")
            If receipt.%GetTypeOf("finished_at_us")'="number" Return $$$ERROR($$$GeneralError,"INVALID_EXPLANATION_TIME")
            Set finished=receipt.%Get("finished_at_us")
            If (finished'=(finished\1))||(finished<d.createdUS)||(finished>now) Return $$$ERROR($$$GeneralError,"INVALID_EXPLANATION_TIME")
        }
        // Validation is trusted but its result may have sat in a queue. Never
        // commit it as valid after its fixed deadline or runtime generation.
        If ready.%Get("readinessUnavailable") {
            Do ..Terminal(d,"RECHECK_REQUIRED","RUNTIME_VALIDATION_UNAVAILABLE",now)
        } ElseIf ('ready.ready)||(ready.generation'=d.generation) {
            Do ..Terminal(d,"RECHECK_REQUIRED","RUNTIME_GENERATION_CHANGED",now)
        } ElseIf (now<d.createdUS)||(now'<d.deadlineUS) {
            Do ..Terminal(d,"ERROR","MODEL_TIMEOUT",now)
        } Else {
            Set d.state="COMPLETED",d.completedUS=now,d.result=r
            Do ..Save(d)
        }
        Set result=..View(d,"RESULT_RECORDED")
        Return $$$OK
    }
    Return $$$ERROR($$$GeneralError,"UNKNOWN_LEDGER_COMMAND")
}

/// Exact trusted bridge result; no caller-provided authority, prompt or grant.
ClassMethod DeterministicArgs(a As %DynamicObject) As %Status [ Private ]
{
    If '..Shape(a,"requestId,orderId,shipmentVersion,mode,generation,result") Return $$$ERROR($$$GeneralError,"INVALID_PRECONTROL")
    For field="requestId","orderId","generation" {
        If a.%GetTypeOf(field)'="string" Return $$$ERROR($$$GeneralError,"INVALID_IDENTITY")
        If '..ID(a.%Get(field)) Return $$$ERROR($$$GeneralError,"INVALID_IDENTITY")
    }
    If a.%GetTypeOf("shipmentVersion")'="number" Return $$$ERROR($$$GeneralError,"INVALID_VERSION")
    If (a.shipmentVersion<1)||(a.shipmentVersion'=(a.shipmentVersion\1)) Return $$$ERROR($$$GeneralError,"INVALID_VERSION")
    If a.%GetTypeOf("mode")'="string" Return $$$ERROR($$$GeneralError,"INVALID_MODE")
    If (a.mode'="WITH_TRIALS")&&(a.mode'="WITHOUT_TRIALS_ABLATION") Return $$$ERROR($$$GeneralError,"INVALID_MODE")
    If a.%GetTypeOf("result")'="object" Return $$$ERROR($$$GeneralError,"INVALID_PRECONTROL")
    Set p=a.result
    If '..Shape(p,"status,code,dispatch_authorized,runtime_generation") Return $$$ERROR($$$GeneralError,"INVALID_PRECONTROL")
    If (p.%GetTypeOf("status")'="string")||(p.status'="DETERMINISTIC") Return $$$ERROR($$$GeneralError,"INVALID_PRECONTROL")
    If p.%GetTypeOf("code")'="string" Return $$$ERROR($$$GeneralError,"INVALID_PRECONTROL")
    If '$ListFind($ListBuild("EXISTING_ACCEPTANCE","ACCEPTANCE_UNRESOLVED"),p.code) Return $$$ERROR($$$GeneralError,"INVALID_PRECONTROL")
    If (p.%GetTypeOf("dispatch_authorized")'="boolean")||p.%Get("dispatch_authorized") Return $$$ERROR($$$GeneralError,"RESULT_CANNOT_AUTHORIZE")
    If (p.%GetTypeOf("runtime_generation")'="string")||(p.%Get("runtime_generation")'=a.generation) Return $$$ERROR($$$GeneralError,"STALE_RUNTIME_GENERATION")
    Return $$$OK
}

ClassMethod RecordDeterministic(a As %DynamicObject, now As %Numeric, Output result As %DynamicObject) As %Status [ Private ]
{
    Set sc=..DeterministicArgs(a)
    If $$$ISERR(sc) Return sc
    Set prior=$Get(^ChronosDecision16("decision",a.requestId))
    If prior'="" {
        Set d=##class(%DynamicObject).%FromJSON(prior)
        If (d.orderId'=a.orderId)||(d.shipmentVersion'=a.shipmentVersion)||(d.mode'=a.mode) Return $$$ERROR($$$GeneralError,"REQUEST_ID_CONFLICT")
        If (d.generation'=a.generation)||(d.%Get("recordKind")'="DETERMINISTIC_PRECONTROL") Return $$$ERROR($$$GeneralError,"REQUEST_CONTEXT_CONFLICT")
        If (d.state'="COMPLETED")||(d.result.%ToJSON()'=a.result.%ToJSON()) Return $$$ERROR($$$GeneralError,"REQUEST_CONTEXT_CONFLICT")
        Set result=..View(d,"EXISTING_DECISION")
        Return $$$OK
    }
    Set active=$Get(^ChronosDecision16("active",a.orderId,a.shipmentVersion))
    If active'="" {
        Set d=##class(%DynamicObject).%FromJSON(^ChronosDecision16("decision",active))
        If d.state'="COMPLETED" Return $$$ERROR($$$GeneralError,"ACTIVE_DECISION_EXISTS")
    }
    // deadlineUS is the observation instant, not a renewable inference window.
    Set d={"requestId":(a.requestId),"orderId":(a.orderId),"shipmentVersion":(a.shipmentVersion),"mode":(a.mode),"generation":(a.generation),"createdUS":(now),"deadlineUS":(now),"completedUS":(now),"state":"COMPLETED","recordKind":"DETERMINISTIC_PRECONTROL","result":(a.result)}
    Do ..Save(d)
    Set ^ChronosDecision16("active",a.orderId,a.shipmentVersion)=a.requestId
    Set result=..View(d,"DETERMINISTIC_RECORDED")
    Return $$$OK
}

ClassMethod Register(a As %DynamicObject, now As %Numeric, Output result As %DynamicObject, clarificationAnchor As %DynamicObject = "") As %Status [ Private ]
{
    If '..Shape(a,"requestId,orderId,shipmentVersion,mode,generation,prepared") Return $$$ERROR($$$GeneralError,"INVALID_REGISTRATION")
    Set clarified=$IsObject(clarificationAnchor)
    If a.%GetTypeOf("prepared")="object" {
        If a.prepared.%IsDefined("clarificationAnchor") Return $$$ERROR($$$GeneralError,"UNEXPECTED_CLARIFICATION_ANCHOR")
        If a.prepared.%GetTypeOf("record")="object" {
            If a.prepared.record.%IsDefined("clarificationAnchor") Return $$$ERROR($$$GeneralError,"UNEXPECTED_CLARIFICATION_ANCHOR")
            If 'clarified,a.prepared.record.%IsDefined("clarification_binding") Return $$$ERROR($$$GeneralError,"CLARIFIED_REGISTRATION_REQUIRED")
        }
    }
    For field="orderId","generation" { If a.%GetTypeOf(field)'="string" Return $$$ERROR($$$GeneralError,"INVALID_IDENTITY")  If '..ID(a.%Get(field)) Return $$$ERROR($$$GeneralError,"INVALID_IDENTITY") }
    If a.%GetTypeOf("shipmentVersion")'="number" Return $$$ERROR($$$GeneralError,"INVALID_VERSION")
    If (a.shipmentVersion<1)||(a.shipmentVersion'=(a.shipmentVersion\1)) Return $$$ERROR($$$GeneralError,"INVALID_VERSION")
    If (a.mode'="WITH_TRIALS")&&(a.mode'="WITHOUT_TRIALS_ABLATION") Return $$$ERROR($$$GeneralError,"INVALID_MODE")
    Set prior=$Get(^ChronosDecision16("decision",a.requestId))
    If prior'="" {
        Set d=##class(%DynamicObject).%FromJSON(prior)
        If (d.orderId'=a.orderId)||(d.shipmentVersion'=a.shipmentVersion)||(d.mode'=a.mode) Return $$$ERROR($$$GeneralError,"REQUEST_ID_CONFLICT")
        If (d.%GetTypeOf("prepared")'="object")||(a.%GetTypeOf("prepared")'="object") Return $$$ERROR($$$GeneralError,"REQUEST_CONTEXT_CONFLICT")
        If (d.generation'=a.generation)||(d.prepared.%ToJSON()'=a.prepared.%ToJSON()) Return $$$ERROR($$$GeneralError,"REQUEST_CONTEXT_CONFLICT")
        Set result=..View(d,"EXISTING_DECISION")
        Return $$$OK
    }
    Set active=$Get(^ChronosDecision16("active",a.orderId,a.shipmentVersion))
    If active'="" {
        Set d=##class(%DynamicObject).%FromJSON(^ChronosDecision16("decision",active))
        If d.state'="COMPLETED" {
            Set result=..View(d,"ACTIVE_DECISION_EXISTS")
            Return $$$OK
        }
    }
    Set p=a.prepared,w=p.record.wire
    If p.status'="READY" Return $$$ERROR($$$GeneralError,"PREPARED_CONTEXT_REQUIRED")
    If p.record.%Get("response_contract","chronos.agent-proposal.v2")'=##class(Chronos.Agent.Model).Contract() Return $$$ERROR($$$GeneralError,"PREPARED_RESPONSE_CONTRACT_MISMATCH")
    If (w.%Get("context_id")'=a.requestId)||(w.%Get("order_id")'=a.orderId)||(w.%Get("shipment_version")'=a.shipmentVersion)||(w.%Get("trial_mode")'=a.mode)||(p.%Get("runtime_generation")'=a.generation) Return $$$ERROR($$$GeneralError,"CONTEXT_BINDING_MISMATCH")
    If (p.record.%GetTypeOf("deadline_us")'="number")||(p.record.%GetTypeOf("started_us")'="number") Return $$$ERROR($$$GeneralError,"INVALID_CONTEXT_TIME")
    Set deadline=p.record.%Get("deadline_us"),started=p.record.%Get("started_us")
    If (started>now)||(deadline<=now)||(deadline>(started+30000000)) Return $$$ERROR($$$GeneralError,"CONTEXT_EXPIRED")
    If $Length($ZConvert(p.%ToJSON(),"O","UTF8"))>262144 Return $$$ERROR($$$GeneralError,"CONTEXT_TOO_LARGE")
    Set d={"requestId":(a.requestId),"orderId":(a.orderId),"shipmentVersion":(a.shipmentVersion),"mode":(a.mode),"generation":(a.generation),"createdUS":(now),"deadlineUS":(deadline),"state":"PREPARED","prepared":(p)}
    If clarified Set d.clarificationAnchor=clarificationAnchor
    Do ..Save(d)
    If clarified Set ^ChronosDecision16("clarificationAdoption",clarificationAnchor.clarificationId)=d.clarificationAnchor.%ToJSON()
    Set ^ChronosDecision16("active",a.orderId,a.shipmentVersion)=a.requestId
    Set result=..View(d,"DECISION_PREPARED")
    Return $$$OK
}
}
