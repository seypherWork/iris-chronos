Include %occStatus

/// Authenticated case conversation. New RECORD may call the pinned C1 model once.
/// HTTP adapter enforces origin/CSRF; no shipment execution is available here.
Class Chronos.Conversation.Controller Extends %RegisteredObject
{
ClassMethod Valid(command As %String, args As %DynamicObject) As %Boolean [ Private ]
{
    If '$ListFind($ListBuild("OPEN","READ","RECORD"),command) Return 0
    If '$IsObject(args) Return 0
    If 'args.%IsA("%DynamicObject") Return 0
    Set count=$Select(command="RECORD":6,1:2)
    If args.%Size()'=count Return 0
    For field="conversationId","decisionId" {
        If (args.%GetTypeOf(field)'="string")||'##class(Chronos.App.Entry).ValidID(args.%Get(field)) Return 0
    }
    If command="RECORD" {
        If (args.%GetTypeOf("turnId")'="string")||'##class(Chronos.App.Entry).ValidID(args.turnId) Return 0
        If (args.%GetTypeOf("expectedRevision")'="number")||(args.expectedRevision<1)||(args.expectedRevision>6)||(args.expectedRevision\1'=args.expectedRevision) Return 0
        If (args.%GetTypeOf("expectedContextDigest")'="string")||($Length(args.expectedContextDigest)'=64)||($Translate(args.expectedContextDigest,"0123456789abcdef")'="") Return 0
        If (args.%GetTypeOf("text")'="string")||($Length($ZConvert(args.text,"O","UTF8"))>2048) Return 0
    }
    Return 1
}

ClassMethod Handle(command As %String, args As %DynamicObject, Output result As %DynamicObject) As %Status
{
    Set result={"code":"CONVERSATION_UNAVAILABLE","inference_granted":false,"dispatch_authorized":false}
    If $TLevel Return $$$ERROR($$$GeneralError,"CONVERSATION_REQUIRES_NO_TRANSACTION")
    If '..Valid(command,args) Return $$$ERROR($$$GeneralError,"INVALID_CONVERSATION_REQUEST")
    Set args=##class(%DynamicObject).%FromJSON(args.%ToJSON())
    Lock +^ChronosRuntime("bootLock"):0
    If '$Test Return $$$ERROR($$$GeneralError,"RUNTIME_BUSY")
    Set sc=$$$OK,mayHaveWritten=0,newTurn=0
    Try {
        // Derive every scope field from current native identity and stored case.
        Set sc=##class(Chronos.Conversation.Context).Snapshot(args.decisionId,1,.initial) $$$ThrowOnError(sc)
        Set scope=initial.scope
        If command="OPEN" {
            Set mayHaveWritten=1
            Set sc=##class(Chronos.Conversation.Ledger).Apply("OPEN",args.conversationId,scope,{"conversation_id":(args.conversationId)},.stored) $$$ThrowOnError(sc)
        } Else {
            Set sc=##class(Chronos.Conversation.Ledger).Apply("READ",args.conversationId,scope,{},.stored) $$$ThrowOnError(sc)
        }
        If command="READ",stored.public.turns.%Size()>0 {
            Set last=stored.public.turns.%Get(stored.public.turns.%Size()-1)
            If (last.state="PROCESSING")||(last.state="RECORDED") {
                // Observation only: can expire a call, never dispatch or retry it.
                Set mayHaveWritten=1
                Set sc=##class(Chronos.Conversation.Ledger).Apply("RECOVER",args.conversationId,scope,{"turn_id":(last.%Get("turn_id"))},.stored) $$$ThrowOnError(sc)
                Set stored.code="CONVERSATION_READ"
            }
        }
        Set sc=##class(Chronos.Conversation.Context).Snapshot(args.decisionId,stored.public.revision,.fresh,args.conversationId) $$$ThrowOnError(sc)
        If fresh.scope.%ToJSON()'=scope.%ToJSON() Throw ##class(%Exception.General).%New("CONVERSATION_SCOPE_CHANGED")
        If command="RECORD" {
            Set replay=0
            For i=0:1:stored.public.turns.%Size()-1 {
                Set oldTurn=stored.public.turns.%Get(i)
                If oldTurn.%Get("turn_id")=args.turnId Set replay=1
            }
            If 'replay,'##class(Chronos.Conversation.Model).Available() Throw ##class(%Exception.General).%New("CONVERSATION_MODEL_NOT_CONFIGURED")
            Set record={"turn_id":(args.turnId),"expected_revision":(args.expectedRevision),"expected_context_digest":(args.expectedContextDigest),"user_text":(args.text),"context":(fresh.context)}
            Set mayHaveWritten=1
            Set sc=##class(Chronos.Conversation.Ledger).Apply("RECORD",args.conversationId,scope,record,.stored) $$$ThrowOnError(sc)
            Set newTurn=(stored.code="TURN_RECORDED")
            // A repeated turn only returns its durable record. No retry or call.
            Set sc=##class(Chronos.Conversation.Context).Snapshot(args.decisionId,stored.public.revision,.fresh,args.conversationId) $$$ThrowOnError(sc)
            If fresh.scope.%ToJSON()'=scope.%ToJSON() Throw ##class(%Exception.General).%New("CONVERSATION_SCOPE_CHANGED")
        }
        If stored.%Get("inference_granted")||stored.%Get("dispatch_authorized") Throw ##class(%Exception.General).%New("UNEXPECTED_CONVERSATION_GRANT")
        Set expected={"actor":(scope.actor),"sessionBinding":(scope.%Get("session_binding"))}
        Set sc=##class(Chronos.Conversation.Context).SamePrincipal(expected) $$$ThrowOnError(sc)
        // Whitelist response fields; private identity/claim/prompt never escapes.
        Set result={"code":(stored.code),"conversation":(stored.public),"context":(fresh.context),"context_digest":(fresh.%Get("context_digest")),"inference_granted":false,"dispatch_authorized":false}
    } Catch ex {
        Set result={"code":"CONVERSATION_UNAVAILABLE","readbackRequired":(mayHaveWritten),"inference_granted":false,"dispatch_authorized":false}
        Do result.%Set("readbackRequired",mayHaveWritten,"boolean")
        Set sc=$$$ERROR($$$GeneralError,"CONVERSATION_UNAVAILABLE")
    }
    Lock -^ChronosRuntime("bootLock")
    If $$$ISOK(sc),newTurn {
        // Never hold the global startup lock while waiting for the model.
        Try {
            Set modelStatus=##class(Chronos.Conversation.Model).Run(args.conversationId,args.decisionId,args.turnId)
            // Always observe the committed outcome; model failure is not success.
            Set sc=..Handle("READ",{"conversationId":(args.conversationId),"decisionId":(args.decisionId)},.result)
            If $$$ISOK(sc) Set result.code="TURN_RECORDED"
        } Catch modelError {
            Set result={"code":"CONVERSATION_UNAVAILABLE","readbackRequired":true,"inference_granted":false,"dispatch_authorized":false}
            Set sc=$$$ERROR($$$GeneralError,"CONVERSATION_UNAVAILABLE")
        }
    }
    Return sc
}
}
