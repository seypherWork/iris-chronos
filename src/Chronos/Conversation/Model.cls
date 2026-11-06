Include %occStatus

/// Local C1/C2 AI Hub154 caller. No shipment action, API credentials or background authority.
Class Chronos.Conversation.Model Extends %RegisteredObject
{
/// Exact model subscript must remain in the private journaled runtime database.
ClassMethod Storage(Output destination As %String) As %Status [ Private ]
{
    Set destination=""
    Try {
        Set expected=##class(%SYS.Namespace).GetGlobalDest($Namespace)
        If ($Piece(expected,"^",1)'="")||($Piece(expected,"^",2)="") Throw ##class(%Exception.General).%New("LOCAL_PRIVATE_STORAGE_REQUIRED")
        If expected=##class(%SYS.Namespace).GetGlobalDest($Namespace,"IRIS.Temp") Throw ##class(%Exception.General).%New("TEMPORARY_STORAGE_REJECTED")
        If expected'=##class(%SYS.Namespace).GetGlobalDest($Namespace,"ChronosRuntime") Throw ##class(%Exception.General).%New("RUNTIME_STORAGE_CHANGED")
        If expected'=##class(%SYS.Namespace).GetGlobalDest($Namespace,"ChronosConversation",$Char(34)_"model"_$Char(34)) Throw ##class(%Exception.General).%New("MODEL_STORAGE_CHANGED")
        Set journalStatus=##class(Chronos.Runtime.Durability).JournaledStorage(expected) $$$ThrowOnError(journalStatus)
        Set destination=expected
    } Catch ex { Return $$$ERROR($$$GeneralError,"CONVERSATION_MODEL_STORAGE_UNVERIFIED") }
    Return $$$OK
}

/// Trusted installation only. No HTTP configuration route; immutable once written.
ClassMethod Configure(baseURL As %String, model As %String, profileSha256 As %String, reasoningEffort As %String = "low", responseContract As %String = "chronos.case-conversation.v1") As %Status
{
    If $TLevel Return $$$ERROR($$$GeneralError,"MODEL_CONFIG_REQUIRES_NO_TRANSACTION")
    Lock +^ChronosRuntime("bootLock"):0
    If '$Test Return $$$ERROR($$$GeneralError,"RUNTIME_BUSY")
    Set sc=$$$OK
    Try {
        Set cfg=..Spec(baseURL,model,profileSha256,reasoningEffort,..ContractSchema(responseContract).%ToJSON())
        Set sc=##class(Ens.Director).GetProductionStatus(.name,.state,0) $$$ThrowOnError(sc)
        If state'=2 Throw ##class(%Exception.General).%New("CONFIGURE_WHILE_STOPPED")
        Set sc=..Storage(.destination) $$$ThrowOnError(sc)
        Set prior=$Get(^ChronosConversation("model"))
        If prior'="" {
            If prior'=cfg Throw ##class(%Exception.General).%New("MODEL_CONFIG_IMMUTABLE")
        } Else {
            Set sc=##class(Chronos.Runtime.Durability).Check() $$$ThrowOnError(sc)
            TStart
            Set ^ChronosConversation("model")=cfg
            TCommit
        }
        Set sc=##class(Chronos.Runtime.Durability).Flush() $$$ThrowOnError(sc)
        Set sc=..Storage(.afterDestination) $$$ThrowOnError(sc)
        If destination'=afterDestination Throw ##class(%Exception.General).%New("MODEL_STORAGE_CHANGED")
    } Catch ex {
        If $TLevel TRollback
        Set sc=$$$ERROR($$$GeneralError,"CONVERSATION_MODEL_CONFIG_UNAVAILABLE")
    }
    Lock -^ChronosRuntime("bootLock")
    Return sc
}

/// Configuration presence is not proof the provider is running or has quota.
ClassMethod Current(Output cfg As %DynamicObject) As %Status
{
    Set cfg=""
    Try {
        Set raw=$Get(^ChronosConversation("model"))
        If raw="" Throw ##class(%Exception.General).%New("NOT_CONFIGURED")
        Set storageStatus=..Storage(.destination) $$$ThrowOnError(storageStatus)
        Set candidate=##class(%DynamicObject).%FromJSON(raw)
        If 'candidate.%IsA("%DynamicObject") Throw ##class(%Exception.General).%New("INVALID_CONFIGURATION")
        Set checked=..Spec(candidate.baseURL,candidate.model,candidate.profileSha256,candidate.reasoningEffort,..ContractSchema(candidate.contract).%ToJSON())
        If checked'=raw Throw ##class(%Exception.General).%New("MODEL_CONFIGURATION_CHANGED")
        Set cfg=candidate
    } Catch ex {
        Return $$$ERROR($$$GeneralError,"CONVERSATION_MODEL_NOT_CONFIGURED")
    }
    Return $$$OK
}

ClassMethod Available() As %Boolean
{
    Try { Set sc=..Current(.cfg) Return $$$ISOK(sc) } Catch ex { Return 0 }
}

/// Exact schema/profile fingerprint; no network and no runtime modifications.
ClassMethod Spec(baseURL As %String, model As %String, profileSha256 As %String, reasoningEffort As %String, schemaJSON As %String) As %String [ Language = python ]
{
    import hashlib,json,re
    if type(baseURL) is not str:raise ValueError('LOCAL_GUARD_REQUIRED')
    match=re.fullmatch(r'http://(?:127\.0\.0\.1|host\.docker\.internal):([1-9][0-9]{3,4})/v1/',baseURL)
    if match is None or not 1024<=int(match.group(1))<=65535:raise ValueError('LOCAL_GUARD_REQUIRED')
    if type(model) is not str or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}',model):raise ValueError('INVALID_MODEL')
    if type(profileSha256) is not str or not re.fullmatch(r'[a-f0-9]{64}',profileSha256):raise ValueError('MODEL_PROFILE_REQUIRED')
    if type(reasoningEffort) is not str or reasoningEffort not in ('none','low','medium'):raise ValueError('INVALID_REASONING_EFFORT')
    if type(schemaJSON) is not str or len(schemaJSON.encode('utf-8'))>16384:raise ValueError('INVALID_CONVERSATION_SCHEMA')
    schema=json.loads(schemaJSON)
    if type(schema) is not dict:raise ValueError('INVALID_CONVERSATION_SCHEMA')
    marker=schema.get('properties',{}).get('schema',{}).get('enum')
    if marker not in (['chronos.case-conversation.v1'],['chronos.case-explanation-plan.v1'],['chronos.case-explanation-plan.v2']):raise ValueError('INVALID_CONVERSATION_SCHEMA')
    canonical=lambda x:json.dumps(x,sort_keys=True,separators=(',',':'),ensure_ascii=True)
    return canonical(dict(baseURL=baseURL,model=model,profileSha256=profileSha256,
        reasoningEffort=reasoningEffort,contract=marker[0],
        schemaSha256=hashlib.sha256(canonical(schema).encode()).hexdigest()))
}

/// One new recorded turn -> one durable reservation -> at most one Chat invocation.
ClassMethod Run(conversationId As %String, decisionId As %String, turnId As %String) As %Status
{
    If $TLevel Return $$$ERROR($$$GeneralError,"MODEL_REQUIRES_NO_TRANSACTION")
    For id=conversationId,decisionId,turnId {
        If '##class(Chronos.App.Entry).ValidID(id) Return $$$ERROR($$$GeneralError,"INVALID_CONVERSATION_ID")
    }
    Set provider="",agent="",session="",scope="",claimed=0,eligible=0
    Set text="",status="error",receipt={},grant="",sc=$$$OK
    Try {
        Set sc=##class(Chronos.Conversation.Context).Snapshot(decisionId,1,.initial) $$$ThrowOnError(sc)
        Set scope=initial.scope,expected={"actor":(scope.actor),"sessionBinding":(scope.%Get("session_binding"))}
        Set sc=##class(Chronos.Conversation.Ledger).Apply("READ",conversationId,scope,{},.stored) $$$ThrowOnError(sc)
        Set eligible=0
        For i=0:1:stored.public.turns.%Size()-1 {
            Set turn=stored.public.turns.%Get(i)
            If turn.%Get("turn_id")=turnId Set eligible=(turn.state="RECORDED")
        }
        If eligible {
            Set sc=..Current(.cfg) $$$ThrowOnError(sc)
            Set sc=##class(Chronos.Conversation.Context).Snapshot(decisionId,stored.public.revision,.fresh,conversationId) $$$ThrowOnError(sc)
            If fresh.scope.%ToJSON()'=scope.%ToJSON() Throw ##class(%Exception.General).%New("CONVERSATION_SCOPE_CHANGED")
            Set runtime=##class(%DynamicObject).%FromJSON(^ChronosRuntime("config"))
            Set sc=##class(Chronos.Agent.Python).ConversationModule(runtime.pythonRoot,.module) $$$ThrowOnError(sc)
            Set prompt=##class(Chronos.Conversation.Python).Prompt(module,$Namespace,cfg.contract)
            Set began=##class(Chronos.Agent.Ledger).NowUS(),deadline=began+30000000
            Set transportId=$ZConvert($System.Util.CreateGUID(),"L"),claimId=$ZConvert($System.Util.CreateGUID(),"L")
            Set settings={"api_key":"ollama","base_url":(cfg.baseURL),"http_config":{"connect_timeout_secs":1,"request_timeout_secs":28}}
            Set provider=##class(%AI.Provider).Create("openai",settings),agent=##class(%AI.Agent).%New(provider)
            Set agent.Model=cfg.model,agent.SystemPrompt=prompt,agent.Temperature=0
            Set formatName=$Select(cfg.contract="chronos.case-explanation-plan.v2":"chronos_c2_v2",cfg.contract="chronos.case-explanation-plan.v1":"chronos_c2",1:"chronos_c1")
            Set options={"max_iterations":1,"max_tokens":2048,"temperature":0,"timeout_ms":28000,"response_format":{"type":"json_schema","json_schema":{"name":(formatName),"strict":true,"schema":(..ContractSchema(cfg.contract))}},"extra_params":{"reasoning_effort":(cfg.reasoningEffort),"user":(transportId),"chronos_deadline_us":(deadline),"chronos_profile_sha256":(cfg.profileSha256)}}
            Set session=agent.CreateSession(options)
            // AI Hub154 exports Rust history on save: save BEFORE Chat only.
            Set sc=session.%Save() $$$ThrowOnError(sc)
            Set binding={"transport_id":(transportId),"model":(cfg.model),"profile_sha256":(cfg.profileSha256),"schema_sha256":(cfg.schemaSha256),"reasoning_effort":(cfg.reasoningEffort),"deadline_us":(deadline),"response_contract":(cfg.contract)}
            Do binding.%Set("ai_hub_session_id",session.%Id(),"string")
            Set sc=##class(Chronos.Conversation.Context).Snapshot(decisionId,stored.public.revision,.fresh,conversationId) $$$ThrowOnError(sc)
            If fresh.scope.%ToJSON()'=scope.%ToJSON() Throw ##class(%Exception.General).%New("CONVERSATION_SCOPE_CHANGED")
            Set args={"turn_id":(turnId),"claim_id":(claimId),"context":(fresh.context),"call":(binding)}
            Set sc=##class(Chronos.Conversation.Ledger).Apply("CLAIM",conversationId,scope,args,.grant) $$$ThrowOnError(sc)
            If grant.%Get("inference_granted") {
                Set claimed=1
                Set sc=##class(Chronos.Conversation.Context).SamePrincipal(expected) $$$ThrowOnError(sc)
                Set sc=..Current(.currentCfg) $$$ThrowOnError(sc)
                If currentCfg.%ToJSON()'=cfg.%ToJSON() Throw ##class(%Exception.General).%New("MODEL_CONFIGURATION_CHANGED")
                Set sc=##class(Chronos.Conversation.Context).Snapshot(decisionId,stored.public.revision,.precall,conversationId) $$$ThrowOnError(sc)
                Set input=##class(%DynamicObject).%FromJSON(grant.%Get("private_provider_request").%Get("input_json"))
                If (precall.scope.%ToJSON()'=scope.%ToJSON())||(precall.%Get("context_digest")'=input.%Get("context_digest")) Throw ##class(%Exception.General).%New("CONVERSATION_CONTEXT_CHANGED")
                Set now=##class(Chronos.Agent.Ledger).NowUS()
                If (now<grant.%Get("private_call").%Get("claimed_at_us"))||(now'<deadline) {
                    Set status="timeout"
                } Else {
                    // The input comes only from the committed, bound native ledger.
                    Set response=agent.Chat(session,grant.%Get("private_provider_request").%Get("input_json"))
                    Set hasTools=0 If $IsObject(response.ToolCalls) Set hasTools=(response.ToolCalls.%Size()>0)
                    Set withinLimit=($Length($ZConvert(response.Content,"O","UTF8"))<=32768)
                    If $ListFind($ListBuild("chronos.case-explanation-plan.v1","chronos.case-explanation-plan.v2"),cfg.contract) Set withinLimit=($Length($ZConvert(response.Content,"O","UTF8"))<=8192)
                    If ('hasTools)&&withinLimit {
                        If $IsObject(response.Extra) {
                            Set candidate=response.Extra.%Get("chronos_transport")
                            If $IsObject(candidate) {
                                Set receipt=##class(%DynamicObject).%FromJSON(candidate.%ToJSON())
                                Set text=response.Content,status="ok"
                            }
                        }
                    }
                }
            }
        }
    } Catch ex { Set text="",receipt={},status="error",sc=$$$ERROR($$$GeneralError,"CONVERSATION_MODEL_UNAVAILABLE") }
    For owned=session,agent,provider {
        If $IsObject(owned) {
            Try { Set closeSC=owned.%Close() If $$$ISERR(closeSC) Set status="error",text="",receipt={} } Catch closeError { Set status="error",text="",receipt={} }
        }
    }
    // Never persist raw provider output, exception text or SDK objects.
    Try {
        If eligible,$IsObject(scope) {
            If claimed {
                Set sc=##class(Chronos.Conversation.Context).Snapshot(decisionId,stored.public.revision,.latest,conversationId) $$$ThrowOnError(sc)
                If latest.scope.%ToJSON()'=scope.%ToJSON() Throw ##class(%Exception.General).%New("CONVERSATION_SCOPE_CHANGED")
                Set args={"turn_id":(turnId),"claim_id":(claimId),"context":(latest.context),"raw":(text),"provider_status":(status),"receipt":(receipt)}
                Set sc=##class(Chronos.Conversation.Ledger).Apply("COMPLETE",conversationId,scope,args,.closed) $$$ThrowOnError(sc)
            } Else {
                // If CLAIM committed but its reply was lost, DECLINE is a no-op.
                Set sc=##class(Chronos.Conversation.Ledger).Apply("DECLINE",conversationId,scope,{"turn_id":(turnId)},.closed) $$$ThrowOnError(sc)
            }
        }
    } Catch finishError { Set sc=$$$ERROR($$$GeneralError,"CONVERSATION_RESULT_UNCERTAIN") }
    Set text="",receipt={},grant="",response="",candidate=""
    Return sc
}

ClassMethod ContractSchema(responseContract As %String) As %DynamicObject
{
    If responseContract="chronos.case-conversation.v1" Return ..Schema()
    If responseContract="chronos.case-explanation-plan.v1" Return ..PlanSchema()
    If responseContract="chronos.case-explanation-plan.v2" Return ..PlanV2Schema()
    Throw ##class(%Exception.General).%New("INVALID_CONVERSATION_CONTRACT")
}

ClassMethod PlanSchema() As %DynamicObject
{
    Return {"type":"object","properties":{"schema":{"type":"string","enum":["chronos.case-explanation-plan.v1"]},"conversation_id":{"type":"string","minLength":1,"maxLength":128,"pattern":"^[A-Za-z0-9_.-]{1,128}$"},"turn_id":{"type":"string","minLength":1,"maxLength":128,"pattern":"^[A-Za-z0-9_.-]{1,128}$"},"context_digest":{"type":"string","minLength":64,"maxLength":64,"pattern":"^[a-f0-9]{64}$"},"catalog_digest":{"type":"string","minLength":64,"maxLength":64,"pattern":"^[a-f0-9]{64}$"},"topic":{"type":"string","enum":["DECISION","COMPARISON","OPERATION_STATUS","PHYSICAL_DELIVERY","PREFERENCE_CHANGE","APPROVAL_REQUIREMENTS","CLARIFY"]},"detail":{"type":"string","enum":["concise","detailed"]},"preference":{"anyOf":[{"type":"null"},{"type":"string","enum":["CHEAPEST_ON_TIME","EARLIEST_ALLOWED"]}]}},"required":["schema","conversation_id","turn_id","context_digest","catalog_digest","topic","detail","preference"],"additionalProperties":false}
}


ClassMethod Schema() As %DynamicObject
{
    Return {"type":"object","properties":{"schema":{"type":"string","enum":["chronos.case-conversation.v1"]},"conversation_id":{"type":"string","minLength":1,"maxLength":128,"pattern":"^[A-Za-z0-9_.-]{1,128}$"},"turn_id":{"type":"string","minLength":1,"maxLength":128,"pattern":"^[A-Za-z0-9_.-]{1,128}$"},"context_digest":{"type":"string","pattern":"^[a-f0-9]{64}$","minLength":64,"maxLength":64},"intent":{"type":"string","enum":["ANSWER","PREFERENCE_PROPOSAL","RESULT_QUERY","APPROVAL_REDIRECT"]},"answer":{"type":"string","minLength":1,"maxLength":2048},"source_ids":{"type":"array","minItems":0,"maxItems":16,"uniqueItems":true,"items":{"type":"string","minLength":1,"maxLength":128,"pattern":"^[A-Za-z0-9_.-]{1,128}$"}},"preference":{"anyOf":[{"type":"null"},{"type":"string","enum":["CHEAPEST_ON_TIME","EARLIEST_ALLOWED"]}]}},"required":["schema","conversation_id","turn_id","context_digest","intent","answer","source_ids","preference"],"additionalProperties":false}
}
ClassMethod PlanV2Schema() As %DynamicObject
{
    Return {"type":"object","properties":{"schema":{"type":"string","enum":["chronos.case-explanation-plan.v2"]},"conversation_id":{"type":"string","minLength":1,"maxLength":128,"pattern":"^[A-Za-z0-9_.-]{1,128}$"},"turn_id":{"type":"string","minLength":1,"maxLength":128,"pattern":"^[A-Za-z0-9_.-]{1,128}$"},"context_digest":{"type":"string","minLength":64,"maxLength":64,"pattern":"^[a-f0-9]{64}$"},"catalog_digest":{"type":"string","minLength":64,"maxLength":64,"pattern":"^[a-f0-9]{64}$"},"detail":{"type":"string","enum":["concise","detailed"]},"preference":{"anyOf":[{"type":"null"},{"type":"string","enum":["CHEAPEST_ON_TIME","EARLIEST_ALLOWED"]}]},"renderer_version":{"type":"string","enum":["chronos.explanation-renderer.v2"]},"topics":{"type":"array","minItems":1,"maxItems":4,"uniqueItems":true,"items":{"type":"string","enum":["DECISION","COMPARISON","OPERATION_STATUS","PHYSICAL_DELIVERY","PREFERENCE_CHANGE","APPROVAL_REQUIREMENTS","CLARIFY","CHAT_EFFECT","CURRENT_REVIEW","DECISION_CHANGE","DESTINATION_SIMULATION"]}}},"required":["schema","conversation_id","turn_id","context_digest","catalog_digest","detail","preference","renderer_version","topics"],"additionalProperties":false}
}

}
