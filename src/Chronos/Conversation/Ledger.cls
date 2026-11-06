Include %occStatus

/// TRUSTED CONTROLLER ONLY. Not an authenticated endpoint. No provider I/O.
/// Controller supplies fresh scope/context and must never expose private grants.
Class Chronos.Conversation.Ledger Extends %RegisteredObject
{
ClassMethod Storage(conversationId As %String, Output destination As %String) As %Status [ Private ]
{
    Set destination=""
    Try {
        Set expected=##class(%SYS.Namespace).GetGlobalDest($Namespace)
        If ($Piece(expected,"^",1)'="")||($Piece(expected,"^",2)="") Throw ##class(%Exception.General).%New("LOCAL_PRIVATE_STORAGE_REQUIRED")
        If expected=##class(%SYS.Namespace).GetGlobalDest($Namespace,"IRIS.Temp") Throw ##class(%Exception.General).%New("TEMPORARY_STORAGE_REJECTED")
        If expected'=##class(%SYS.Namespace).GetGlobalDest($Namespace,"ChronosRuntime") Throw ##class(%Exception.General).%New("RUNTIME_STORAGE_CHANGED")
        For branch="record","binding","mutex" {
            Set subs=$Char(34)_branch_$Char(34)_","_$Char(34)_conversationId_$Char(34)
            If expected'=##class(%SYS.Namespace).GetGlobalDest($Namespace,"ChronosConversation",subs) Throw ##class(%Exception.General).%New("CONVERSATION_MAPPING_CHANGED")
        }
        Set journalStatus=##class(Chronos.Runtime.Durability).JournaledStorage(expected) $$$ThrowOnError(journalStatus)
        Set destination=expected
    } Catch ex {
        Return $$$ERROR($$$GeneralError,"CONVERSATION_STORAGE_UNVERIFIED")
    }
    Return $$$OK
}

ClassMethod Apply(command As %String, conversationId As %String, scope As %DynamicObject, args As %DynamicObject, Output result As %DynamicObject) As %Status
{
    Set result={"code":"CONVERSATION_UNAVAILABLE","inference_granted":false,"dispatch_authorized":false}
    If $TLevel Return $$$ERROR($$$GeneralError,"CONVERSATION_REQUIRES_NO_TRANSACTION")
    If ($Length(conversationId)<1)||($Length(conversationId)>128)||($Translate(conversationId,"abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.")'="") Return $$$ERROR($$$GeneralError,"INVALID_CONVERSATION_ID")
    If ",OPEN,READ,INSPECT,RECORD,DECLINE,CLAIM,COMPLETE,RECOVER,"'[(","_command_",") Return $$$ERROR($$$GeneralError,"INVALID_CONVERSATION_COMMAND")
    Lock +^ChronosRuntime("bootLock"):2
    If '$Test Return $$$ERROR($$$GeneralError,"RUNTIME_BUSY")
    Set locked=0,sc=$$$OK,committed=0
    Try {
        If '$IsObject(scope)||'$IsObject(args) Throw ##class(%Exception.General).%New("INVALID_ARGUMENTS")
        If 'scope.%IsA("%DynamicObject")||'args.%IsA("%DynamicObject") Throw ##class(%Exception.General).%New("INVALID_ARGUMENTS")
        Set config=##class(%DynamicObject).%FromJSON($Get(^ChronosRuntime("config"),"{}"))
        If (config.%GetTypeOf("pythonRoot")'="string")||(config.pythonRoot="") Throw ##class(%Exception.General).%New("RUNTIME_NOT_CONFIGURED")
        Set web=##class(%DynamicObject).%FromJSON($Get(^ChronosWeb("config"),"{}"))
        If (web.%GetTypeOf("installationId")'="string")||(scope.%Get("installation_id")'=web.installationId) Throw ##class(%Exception.General).%New("INSTALLATION_CHANGED")
        If (command'="READ")&&(command'="INSPECT") {
            Set sc=##class(Chronos.Runtime.Bootstrap).Ready(.ready) $$$ThrowOnError(sc)
            If 'ready.ready Throw ##class(%Exception.General).%New("RUNTIME_NOT_READY")
            If ",RECORD,CLAIM,COMPLETE,"[(","_command_",") {
                If args.%GetTypeOf("context")'="object" Throw ##class(%Exception.General).%New("CONTEXT_REQUIRED")
                If args.context.%Get("generation")'=ready.generation Throw ##class(%Exception.General).%New("GENERATION_CHANGED")
            }
        }
        If command="OPEN",args.%Get("conversation_id")'=conversationId Throw ##class(%Exception.General).%New("CONVERSATION_ID_CHANGED")
        // Verify exact subscript destinations and actual database journaling.
        Set sc=..Storage(conversationId,.destination) $$$ThrowOnError(sc)
        Set sc=##class(Chronos.Agent.Python).ConversationModule(config.pythonRoot,.module) $$$ThrowOnError(sc)
        Lock +^ChronosConversation("mutex",conversationId):2
        If '$Test Throw ##class(%Exception.General).%New("CONVERSATION_BUSY")
        Set locked=1
        Set previous=$Get(^ChronosConversation("record",conversationId),"")
        If previous'="",$Get(^ChronosConversation("binding",conversationId))'=module Throw ##class(%Exception.General).%New("CONVERSATION_CODE_CHANGED")
        If previous'="" {
            Set stored=##class(%DynamicObject).%FromJSON(previous)
            If stored.%Get("conversation_id")'=conversationId Throw ##class(%Exception.General).%New("STORED_CONVERSATION_CHANGED")
        }
        If (command'="READ")&&(command'="INSPECT") { Set sc=##class(Chronos.Runtime.Durability).Check() $$$ThrowOnError(sc) }
        Set verifyBrowser=1
        // All current conversation operations belong to the live CSP principal.
        // A background worker cannot reuse these private scope values.
        If verifyBrowser {
            Set expected={"actor":(scope.actor),"sessionBinding":(scope.%Get("session_binding"))}
            Set sc=##class(Chronos.Conversation.Context).SamePrincipal(expected) $$$ThrowOnError(sc)
        }
        Set args=##class(%DynamicObject).%FromJSON(args.%ToJSON())
        If $ListFind($ListBuild("RECORD","CLAIM","COMPLETE"),command),args.context.%Get("response_contract")="chronos.case-explanation-plan.v2" {
            Set sc=##class(Chronos.Conversation.Context).Snapshot(args.context.%Get("decision_id"),args.context.%Get("conversation_revision"),.lockedFresh,conversationId) $$$ThrowOnError(sc)
            If lockedFresh.scope.%ToJSON()'=scope.%ToJSON() Throw ##class(%Exception.General).%New("CONVERSATION_SCOPE_CHANGED")
            Set args.context=lockedFresh.context
        }
        If $ListFind($ListBuild("RECORD","CLAIM","COMPLETE","RECOVER"),command) {
            // Ignore caller clock; timestamp after locks AND fresh evidence reads.
            Do args.%Set("now_us",##class(Chronos.Agent.Ledger).NowUS(),"number")
        }
        TStart
        Set evaluateCommand=$Select(command="INSPECT":"READ",1:command)
        Set candidate=##class(%DynamicObject).%FromJSON(##class(Chronos.Conversation.Python).Evaluate(module,$Namespace,previous,evaluateCommand,scope.%ToJSON(),args.%ToJSON()))
        If verifyBrowser {
            Set sc=##class(Chronos.Conversation.Context).SamePrincipal(expected) $$$ThrowOnError(sc)
        }
        If candidate.changed {
            If (command="READ")||(command="INSPECT") Throw ##class(%Exception.General).%New("READ_CHANGED_STATE")
            Set ^ChronosConversation("record",conversationId)=candidate.stateJSON
            Set ^ChronosConversation("binding",conversationId)=module
        }
        // A commit error may leave its outcome uncertain. Never return a grant
        // or describe a potentially committed write as a known rollback.
        Set committed=candidate.changed
        TCommit
        If candidate.changed {
            Set sc=##class(Chronos.Runtime.Durability).Flush() $$$ThrowOnError(sc)
            Set sc=..Storage(conversationId,.afterDestination) $$$ThrowOnError(sc)
            If destination'=afterDestination Throw ##class(%Exception.General).%New("CONVERSATION_STORAGE_CHANGED")
        }
        If verifyBrowser {
            Set sc=##class(Chronos.Conversation.Context).SamePrincipal(expected) $$$ThrowOnError(sc)
        }
        // Expose inference grant only after committed state has passed Sync.
        // Sync/identity checks may consume the remaining call deadline.
        Set finalNow=##class(Chronos.Agent.Ledger).NowUS()
        If candidate.result.%Get("inference_granted"),((finalNow<candidate.result.%Get("private_call").%Get("claimed_at_us"))||(finalNow'<candidate.result.%Get("private_call").%Get("deadline_us"))) {
            Set result={"code":"CALL_CLOCK_OR_DEADLINE_INVALID","inference_granted":false,"dispatch_authorized":false}
        } Else {
            Set result=candidate.result
            If command="INSPECT" Set result.privateJSON=previous
        }
        Set committed=0
    } Catch ex {
        If $TLevel TRollback
        Set code=$Select(committed:"CONVERSATION_DURABILITY_UNCERTAIN",1:"CONVERSATION_REJECTED")
        Set result={"code":(code),"inference_granted":false,"dispatch_authorized":false}
        Set sc=$$$ERROR($$$GeneralError,code)
    }
    If locked Lock -^ChronosConversation("mutex",conversationId)
    Lock -^ChronosRuntime("bootLock")
    Return sc
}
}
