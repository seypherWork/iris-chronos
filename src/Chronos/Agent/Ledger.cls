Include %occStatus

/// TRUSTED NATIVE CALLERS ONLY. No authentication or provider I/O here.
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

/// Lock order: bootLock (where needed), then ledger mutex, then transaction.
/// Readiness/authority reads finish BEFORE opening the ledger transaction.
ClassMethod Apply(command As %String, args As %DynamicObject, Output result As %DynamicObject) As %Status
{
    Set result={"code":"NOT_APPLIED","inferenceGranted":false,"validationGranted":false,"dispatch_authorized":false}
    If $TLevel Return $$$ERROR($$$GeneralError,"LEDGER_REQUIRES_NO_TRANSACTION")
    If ",REGISTER,RECORD_DETERMINISTIC,READ,INSPECT,PREVIOUS,CLAIM,BIND_CALL,BEGIN_FINISH,COMPLETE,CANCEL,RECOVER,RESOLVE,"'[(","_command_",") Return $$$ERROR($$$GeneralError,"UNKNOWN_LEDGER_COMMAND")
    Set needsBoot=",REGISTER,RECORD_DETERMINISTIC,CLAIM,BIND_CALL,COMPLETE,RECOVER,RESOLVE,"[(","_command_","),ready={"ready":false,"generation":""}
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
            Set sc=..Transition(command,args,now,ready,.result)
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

ClassMethod Transition(command As %String, a As %DynamicObject, now As %Numeric, ready As %DynamicObject, Output result As %DynamicObject) As %Status [ Private ]
{
    If '$IsObject(a) Return $$$ERROR($$$GeneralError,"ARGUMENT_OBJECT_REQUIRED")
    If 'a.%IsA("%DynamicObject") Return $$$ERROR($$$GeneralError,"ARGUMENT_OBJECT_REQUIRED")
    If a.%GetTypeOf("requestId")'="string" Return $$$ERROR($$$GeneralError,"INVALID_REQUEST_ID")
    If '..ID(a.requestId) Return $$$ERROR($$$GeneralError,"INVALID_REQUEST_ID")
    If (command="REGISTER")||(command="RECORD_DETERMINISTIC")||(command="CLAIM")||(command="RECOVER")||(command="RESOLVE") {
        If ('ready.ready)||(a.%Get("generation")'=ready.generation) Return $$$ERROR($$$GeneralError,"STALE_RUNTIME_GENERATION")
    }
    If command="REGISTER" Return ..Register(a,now,.result)
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
        Set expectedModel="qwen38:cyber-32k",expectedProfile="",expectedReasoning="none",fields="requestId,claimId,transportId,aiHubSessionId,interopSessionId,model"
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

ClassMethod Register(a As %DynamicObject, now As %Numeric, Output result As %DynamicObject) As %Status [ Private ]
{
    If '..Shape(a,"requestId,orderId,shipmentVersion,mode,generation,prepared") Return $$$ERROR($$$GeneralError,"INVALID_REGISTRATION")
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
    Do ..Save(d)
    Set ^ChronosDecision16("active",a.orderId,a.shipmentVersion)=a.requestId
    Set result=..View(d,"DECISION_PREPARED")
    Return $$$OK
}
}
