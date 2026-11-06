Include %occStatus

/// AI Hub 154, installation-pinned local guard. Never caller-controlled settings.
Class Chronos.Agent.Model Extends %RegisteredObject
{
ClassMethod Configure(baseURL As %String, model As %String = "qwen38:cyber-32k", profileSha256 As %String = "", reasoningEffort As %String = "none", responseContract As %String = "chronos.agent-proposal.v2") As %Status
{
    If $TLevel Return $$$ERROR($$$GeneralError,"MODEL_CONFIG_REQUIRES_NO_TRANSACTION")
    Set host=$Piece(baseURL,":",1,2),tail=$Piece(baseURL,":",3),port=$Piece(tail,"/",1)
    If (host'="http://127.0.0.1")&&(host'="http://host.docker.internal") Return $$$ERROR($$$GeneralError,"LOCAL_GUARD_REQUIRED")
    If (port'?1.5N)||(port<1024)||(port>65535)||(baseURL'=(host_":"_port_"/v1/")) Return $$$ERROR($$$GeneralError,"INVALID_GUARD_URL")
    If (model="")||($Length(model)>128)||($Extract(model,1)'?1AN)||($Translate(model,"abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.:-")'="") Return $$$ERROR($$$GeneralError,"INVALID_MODEL")
    If profileSha256="" {
        If model'="qwen38:cyber-32k" Return $$$ERROR($$$GeneralError,"MODEL_PROFILE_REQUIRED")
    } Else {
        If ($Length(profileSha256)'=64)||($Translate(profileSha256,"0123456789abcdef")'="") Return $$$ERROR($$$GeneralError,"INVALID_MODEL_PROFILE")
    }
    If (reasoningEffort'="none")&&(reasoningEffort'="low")&&(reasoningEffort'="medium") Return $$$ERROR($$$GeneralError,"INVALID_REASONING_EFFORT")
    If (reasoningEffort'="none")&&(profileSha256="") Return $$$ERROR($$$GeneralError,"REASONING_PROFILE_REQUIRED")
    If (responseContract'="chronos.agent-proposal.v2")&&(responseContract'="chronos.preference-extraction.v1") Return $$$ERROR($$$GeneralError,"UNSUPPORTED_RESPONSE_CONTRACT")
    If (responseContract="chronos.preference-extraction.v1")&&(profileSha256="") Return $$$ERROR($$$GeneralError,"EXTRACTION_PROFILE_REQUIRED")
    Set cfg={"baseURL":(baseURL),"model":(model),"contract":(responseContract)}
    If reasoningEffort'="none" Set cfg.reasoningEffort=reasoningEffort
    If profileSha256'="" Set cfg.profileSha256=profileSha256
    Lock +^ChronosRuntime("bootLock"):0
    If '$Test Return $$$ERROR($$$GeneralError,"RUNTIME_BUSY")
    Set sc=$$$OK
    Try {
        Set prior=$Get(^ChronosAI18("config"))
        If prior'="" {
            If prior'=cfg.%ToJSON() Set sc=$$$ERROR($$$GeneralError,"MODEL_CONFIG_IMMUTABLE")
        } Else {
            Set sc=##class(Ens.Director).GetProductionStatus(.name,.state,0)
            $$$ThrowOnError(sc)
            If state'=2 Set sc=$$$ERROR($$$GeneralError,"CONFIGURE_WHILE_STOPPED")
            If $$$ISOK(sc) Set ^ChronosAI18("config")=cfg.%ToJSON()
        }
    } Catch ex { Set sc=$$$ERROR($$$GeneralError,"MODEL_CONFIG_UNAVAILABLE") }
    Lock -^ChronosRuntime("bootLock")
    Return sc
}

/// One grant -> one Chat invocation. Closing SDK objects is not model cancellation.
ClassMethod Run(adapter As Chronos.Agent.GuardAdapter, requestId As %String, traceId As %String, deadlineUS As %Numeric, Output result As %DynamicObject, expectedGeneration As %String = "", Output traceMetrics As %DynamicObject = "") As %Status
{
    Set traceMetrics="",traceUsage="",chatEndedUS=0,result={"code":"MODEL_NOT_CONFIGURED","dispatch_authorized":false}
    If $TLevel Return $$$ERROR($$$GeneralError,"MODEL_REQUIRES_NO_TRANSACTION")
    If '$Data(^ChronosAI18("config")) Return $$$OK
    If '$IsObject(adapter) Return $$$ERROR($$$GeneralError,"MODEL_ADAPTER_UNAVAILABLE")
    Set provider="",agent="",session="",claimed=0,text="",status="error",chatGranted=0,deadline=deadlineUS
    Try {
        Set cfg=##class(%DynamicObject).%FromJSON(^ChronosAI18("config")),reasoning="none",contract=..Contract()
        If cfg.%IsDefined("reasoningEffort") Set reasoning=cfg.reasoningEffort
        Set sc=##class(Chronos.Agent.Decisions).Claim(requestId,.grant,expectedGeneration)
        $$$ThrowOnError(sc)
        Set result=grant
        If grant.%Get("inferenceGranted") {
            Set claimed=1
            If grant.%Get("responseContract","chronos.agent-proposal.v2")'=contract Throw ##class(%Exception.General).%New("RESPONSE_CONTRACT_MISMATCH")
            Set deadline=grant.deadlineUS If deadlineUS<deadline Set deadline=deadlineUS
            Set remaining=(deadline-##class(Chronos.Agent.Ledger).NowUS())\1000000
            If remaining<1 {
                Set status="timeout"
            } Else {
                Set options={"max_iterations":1,"max_tokens":2048,"temperature":0,"timeout_ms":(remaining*1000),"response_format":{"type":"json_schema","json_schema":{"name":($Select(contract="chronos.preference-extraction.v1":"chronos_e1",1:"chronos_a1")),"strict":true,"schema":(..Schema(contract))}},"extra_params":{"reasoning_effort":(reasoning),"user":(grant.transportId),"chronos_deadline_us":(deadline\1)}}
                If cfg.%IsDefined("profileSha256") Do options.%Get("extra_params").%Set("chronos_profile_sha256",cfg.profileSha256)
                Set sc=adapter.OpenAgentSession(cfg.baseURL,cfg.model,grant.instructions,remaining,options,.provider,.agent,.session)
                $$$ThrowOnError(sc)
                // Kit154 %OnAddToSaveSet exports Rust history. Save only BEFORE
                // Chat; never save rejected/raw completion or reasoning afterward.
                Set sc=session.%Save()
                $$$ThrowOnError(sc)
                Set sid=session.%Id()
                Set binding={"requestId":(requestId),"claimId":(grant.claimId),"transportId":(grant.transportId),"model":(cfg.model)}
                If cfg.%IsDefined("profileSha256") Set binding.profileSha256=cfg.profileSha256
                If contract="chronos.preference-extraction.v1" Set binding.responseContract=contract
                Do binding.%Set("aiHubSessionId",sid,"string"),binding.%Set("interopSessionId",traceId,"string")
                Set sc=##class(Chronos.Agent.Ledger).Apply("BIND_CALL",binding,.bound)
                $$$ThrowOnError(sc)
                Set chatGranted=bound.%Get("chatGranted")
                If chatGranted {
                    Set chatStartedUS=##class(Chronos.Agent.Ledger).NowUS()
                    If (deadline-chatStartedUS)<1000000 {
                        Set status="timeout"
                    } Else {
                        Set response=adapter.Exchange(agent,session,grant.inputJSON)
                        Try { Set chatEndedUS=##class(Chronos.Agent.Ledger).NowUS() } Catch traceEndError { Set chatEndedUS=0 }
                        Set receipt=response.Extra.%Get("chronos_transport"),verified=0
                        If $IsObject(receipt) {
                            Set verified=(receipt.%Get("version")=1)&&(receipt.%Get("request_id")=grant.transportId)&&(receipt.%Get("finish_reason")="stop")&&(receipt.%Get("model")=cfg.model)
                            If cfg.%IsDefined("profileSha256"),receipt.%Get("profile_sha256")'=cfg.profileSha256 Set verified=0
                            If contract="chronos.preference-extraction.v1",receipt.%Get("response_contract")'=contract Set verified=0
                        }
                        If verified {
                            Set hasTools=0 If $IsObject(response.ToolCalls) Set hasTools=(response.ToolCalls.%Size()>0)
                            If ('hasTools)&&($Length($ZConvert(response.Content,"O","UTF8"))<=4096) {
                                Set text=response.Content,status="ok"
                                // Trace collection is optional and has no authority over the decision.
                                Try { Set traceUsage=response.Usage } Catch traceUsageError { Set traceUsage="" }
                            }
                        }
                    }
                }
            }
        }
    } Catch ex {
        Set status="error",text=""
        Set result={"code":"MODEL_CALL_UNAVAILABLE","dispatch_authorized":false}
    }
    For owned=session,agent,provider {
        If $IsObject(owned) {
            Try { Set closeSC=owned.%Close() If $$$ISERR(closeSC) Set status="error",text="" } Catch closeError { Set status="error",text="" }
        }
    }
    If claimed {
        If ##class(Chronos.Agent.Ledger).NowUS()'<deadline Set status="timeout",text=""
        // No private grant/raw content becomes an Interoperability message.
        Set sc=##class(Chronos.Agent.Decisions).Finish(requestId,grant.claimId,text,status,.result)
        If $$$ISERR(sc) {
            Set result={"code":"MODEL_RESULT_UNCERTAIN","dispatch_authorized":false}
        } ElseIf status="ok" {
            Try { Set traceMetrics=..BuildTraceMetrics(traceUsage,chatStartedUS,chatEndedUS) } Catch traceError { Set traceMetrics="" }
        }
    }
    Return $$$OK
}

/// Return only bounded counters and the elapsed wall-clock interval around Chat.
/// SDK timing includes transport and processing. Counters are provider declarations.
ClassMethod BuildTraceMetrics(usage As %DynamicObject, startedUS As %Numeric, endedUS As %Numeric) As %DynamicObject
{
    Set metrics={"schema":"chronos.trace-metrics.v1"}
    Set elapsed=endedUS-startedUS
    If (startedUS>0)&&(elapsed'<0)&&(elapsed'>120000000) Set metrics.sdkWallClockMs=elapsed\1000
    If $IsObject(usage) {
        If (usage.%GetTypeOf("prompt_tokens")="number")&&(usage.%GetTypeOf("completion_tokens")="number") {
            Set prompt=usage.%Get("prompt_tokens"),completion=usage.%Get("completion_tokens")
            If (prompt'<0)&&(prompt'>1000000)&&(completion'<0)&&(completion'>2048) {
                Set total=prompt+completion
                If (prompt=(prompt\1))&&(completion=(completion\1))&&(total'>1000000) {
                    If ('usage.%IsDefined("total_tokens"))||((usage.%GetTypeOf("total_tokens")="number")&&(usage.%Get("total_tokens")=total)) {
                        Set metrics.promptTokens=prompt,metrics.completionTokens=completion,metrics.totalTokens=total
                    }
                }
            }
        }
    }
    If ('metrics.%IsDefined("sdkWallClockMs"))&&('metrics.%IsDefined("totalTokens")) Return ""
    Return metrics
}

/// Trusted immutable installation selector; never an HTTP/message option.
ClassMethod Contract() As %String
{
    Set contract="chronos.agent-proposal.v2"
    If $Data(^ChronosAI18("config")) {
        Set cfg=##class(%DynamicObject).%FromJSON(^ChronosAI18("config")),contract=cfg.contract
        If (contract="chronos.preference-extraction.v1")&&(cfg.%Get("profileSha256")="") Throw ##class(%Exception.General).%New("EXTRACTION_PROFILE_REQUIRED")
    }
    If (contract'="chronos.agent-proposal.v2")&&(contract'="chronos.preference-extraction.v1") Throw ##class(%Exception.General).%New("UNSUPPORTED_RESPONSE_CONTRACT")
    Return contract
}

ClassMethod Schema(contract As %String = "chronos.agent-proposal.v2") As %DynamicObject
{
    If contract="chronos.preference-extraction.v1" Return {"type":"object","properties":{"schema_version":{"type":"string","enum":["chronos.preference-extraction.v1"]},"interpreted_preference":{"type":"string","enum":["CHEAPEST_ON_TIME","EARLIEST_ALLOWED","UNRESOLVED"]},"reason_code":{"type":"string","enum":["PREFERENCE_MATCH","CONTEXT_AMBIGUOUS","CONFLICTING_EVIDENCE","CONTEXT_INCOMPLETE"]},"source_ids":{"type":"array","minItems":1,"maxItems":16,"uniqueItems":true,"items":{"type":"string","minLength":1,"maxLength":256}},"rationale":{"type":"string","minLength":1,"maxLength":240},"clarification":{"anyOf":[{"type":"null"},{"type":"string","minLength":1,"maxLength":160}]}},"required":["schema_version","interpreted_preference","reason_code","source_ids","rationale","clarification"],"additionalProperties":false}
    If contract'="chronos.agent-proposal.v2" Throw ##class(%Exception.General).%New("UNSUPPORTED_RESPONSE_CONTRACT")
    Return {"type":"object","properties":{"context_id":{"type":"string","minLength":1,"maxLength":256},"order_id":{"type":"string","minLength":1,"maxLength":256},"schema_version":{"type":"string","enum":["chronos.agent-proposal.v2"]},"context_digest":{"type":"string","pattern":"^[a-f0-9]{64}$"},"shipment_version":{"type":"integer","minimum":0},"state_revision":{"type":"integer","minimum":0},"action":{"type":"string","enum":["RETRY_A","FAILOVER_B","HOLD"]},"option_id":{"enum":["opt-a","opt-b",null]},"interpreted_preference":{"type":"string","enum":["CHEAPEST_ON_TIME","EARLIEST_ALLOWED","UNRESOLVED","NOT_USED"]},"source_ids":{"type":"array","minItems":1,"maxItems":16,"uniqueItems":true,"items":{"type":"string","minLength":1,"maxLength":256}},"reason_code":{"type":"string","enum":["PREFERENCE_MATCH","ACCEPTANCE_UNRESOLVED","CONTEXT_AMBIGUOUS","CONFLICTING_EVIDENCE","NO_FEASIBLE_OPTION","CONTEXT_INCOMPLETE"]},"rationale":{"type":"string","minLength":1,"maxLength":600},"clarification":{"anyOf":[{"type":"null"},{"type":"string","minLength":1,"maxLength":240}]}},"required":["context_id","order_id","schema_version","context_digest","shipment_version","state_revision","action","option_id","interpreted_preference","source_ids","reason_code","rationale","clarification"],"additionalProperties":false}
}
}
