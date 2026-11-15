Include %occStatus

/// Opt-in original-CSP controller. This is NOT a route or a shipment approval.
/// Native Workflow reports the assignee, not who invoked CompleteTask. Only a
/// successful call here can add separate CSP-actor evidence to the private log.
Class Chronos.Workflow.Controller Extends %RegisteredObject
{
ClassMethod Matches(pattern As %String, value As %String) As %Boolean [ Private ]
{
    Set m=##class(%Regex.Matcher).%New(pattern),m.Text=value,m.OperationLimit=10000
    Return m.Locate()
}

ClassMethod ExpectedRole(role As %String) As %Boolean
{
    Return role=##class(Chronos.Workflow.Store).#ROLE
}

/// Bounded inert form data. Known credential markers are rejected; this is not
/// a promise that arbitrary text can be classified as secret/nonsecret.
ClassMethod Form(preference As %String, note As %String, Output code As %String) As %Boolean
{
    Set code="INVALID_CLARIFICATION_PREFERENCE"
    If '$ListFind($ListBuild("EARLIEST_ALLOWED","CHEAPEST_ON_TIME"),preference) Return 0
    Set code="INVALID_CLARIFICATION_NOTE"
    If ($Length(note)<1)||($Length(note)>240) Return 0
    // No controls, invisible format characters, surrogate code points, edge
    // whitespace or JSON escapes. Reject escapes instead of decoding notes.
    If ..Matches("\A\s|\s\z|[\p{C}\\]",note) Return 0
    Set code="SENSITIVE_CLARIFICATION_NOTE"
    If ..Matches("(?i)(?:password|passwd|api[_ -]?key|client[_ -]?secret|access[_ -]?token)\s*['""]?\s*[:=]\s*\S+|authorization\s*['""]?\s*:\s*['""]?\s*(?:bearer|basic)\s+\S+|-----BEGIN [^-]*PRIVATE KEY-----",note) Return 0
    If ..Matches("(?i)['""]\s*(?:password|passwd|api[_ -]?key|client[_ -]?secret|access[_ -]?token|authorization|private[_ -]?key)\s*['""]\s*:",note) Return 0
    Set code="VALID_CLARIFICATION_FORM"
    Return 1
}

/// No caller-supplied identity. Shared retained native user/member references
/// are returned only to the current native composition, never to HTTP.
ClassMethod Current(Output principal As %DynamicObject, Output user As %String, Output userObject As EnsLib.Workflow.UserDefinition, Output membership As EnsLib.Workflow.RoleMembership, Output code As %String) As %Status
{
    Set principal={},user="",userObject="",membership="",code="NOT_AUTHENTICATED"
    Set sc=##class(Chronos.Approval.Identity).Current("APPROVE",.principal)
    If $$$ISERR(sc)||'principal.%Get("authenticated") Return $$$OK
    Try {
        Set code="SESSION_UNAVAILABLE"
        If '$Data(%request)||'$Data(%session) Return $$$OK
        If '$IsObject(%request)||'$IsObject(%session) Return $$$OK
        If '%request.%IsA("%CSP.Request")||'%session.%IsA("%CSP.Session") Return $$$OK
        Set user=$Username
        If (user="")||(%session.Username'=user)||%session.EndSession Return $$$OK
        If %request.GetCgiEnv("QUERY_STRING")'="" Return $$$OK
        If '%session.EventClassExists("Chronos.Web.Events",$Namespace) Return $$$OK
        Set config=##class(%DynamicObject).%FromJSON($Get(^ChronosWeb("config"),"{}"))
        If (config.%GetTypeOf("origin")'="string")||(config.%GetTypeOf("application")'="string") Return $$$OK
        If '##class(Chronos.Web.NativePolicy).ValidOrigin(config.origin) Return $$$OK
        If (%request.Application'=config.application)||(%request.GetCgiEnv("HTTP_HOST")'=$Piece(config.origin,"://",2)) Return $$$OK
        If %request.Secure'=($Extract(config.origin,1,8)="https://") Return $$$OK
        Set code="CROSS_SITE_REQUEST"
        If (%request.Method'="POST")||(%request.GetCgiEnv("HTTP_ORIGIN")'=config.origin) Return $$$OK
        Set fetch=%request.GetCgiEnv("HTTP_SEC_FETCH_SITE")
        If (fetch'="")&&(fetch'="same-origin") Return $$$OK
        Set encoding=%request.GetCgiEnv("HTTP_CONTENT_ENCODING")
        If (encoding'="")&&(encoding'="identity") Return $$$OK
        If '..Matches("\Aapplication/json(?:[ \t]*;[ \t]*charset=utf-8)?\z",$ZConvert(%request.GetCgiEnv("CONTENT_TYPE"),"L")) Return $$$OK
        Set code="CSRF_REJECTED",expected=%session.Get("ChronosCSRF"),supplied=%request.GetCgiEnv("HTTP_X_CHRONOS_CSRF")
        If (%session.Get("ChronosCSRFBinding")'=principal.sessionBinding)||($Length(expected)'=64)||($Length(supplied)'=64) Return $$$OK
        If ($Translate(expected,"0123456789abcdef")'="")||($Translate(supplied,"0123456789abcdef")'="") Return $$$OK
        Set difference=0
        For i=1:1:64 { Set difference=difference+($ASCII(expected,i)'=$ASCII(supplied,i)) }
        If difference Return $$$OK
        Set code="WORKFLOW_MEMBERSHIP_REQUIRED"
        If '..ExpectedRole(##class(Chronos.Workflow.Store).#ROLE) Return $$$OK
        If '##class(EnsLib.Workflow.RoleDefinition).%ExistsId(##class(Chronos.Workflow.Store).#ROLE) Return $$$OK
        Set userObject=##class(EnsLib.Workflow.UserDefinition).%OpenId(user,3,.sc) $$$ThrowOnError(sc)
        If '$IsObject(userObject)||'userObject.IsActive Return $$$OK
        Set membership=##class(EnsLib.Workflow.RoleMembership).%OpenId(##class(Chronos.Workflow.Store).#ROLE_"||"_user,3,.sc) $$$ThrowOnError(sc)
        If '$IsObject(membership) Return $$$OK
        If (membership.UserGetObjectId()'=user)||(membership.RoleGetObjectId()'=##class(Chronos.Workflow.Store).#ROLE) Return $$$OK
        Set code="CSP_WORKFLOW_IDENTITY_CONFIRMED"
    } Catch ex {
        Set code="WORKFLOW_IDENTITY_UNAVAILABLE",userObject="",membership=""
    }
    Return $$$OK
}

/// Use the public native UTC conversion, then explicit parenthesized products.
/// IRIS evaluates binary arithmetic left-to-right; Unix microseconds are not a
/// raw UTC property, a local timestamp or an unparenthesized multiplication.
ClassMethod UTCToUS(value As %String, Output us As %Numeric, Output code As %String) As %Boolean
{
    Set us=0,code="INVALID_NATIVE_UTC"
    Try {
        If ($Length(value)>40)||'..Matches("\A[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,9})?\z",value) Return 0
        Set utch=##class(Ens.DataType.UTC).timeUTCtoUTCH(value)
        Set roundtrip=##class(Ens.DataType.UTC).timeUTCHtoUTC(utch)
        If ##class(Ens.DataType.UTC).Normalize(value)'=##class(Ens.DataType.UTC).Normalize(roundtrip) Return 0
        Set days=$Piece(utch,",",1),seconds=$Piece(utch,",",2),whole=$Piece(seconds,".",1)
        If ($Length(utch,",")'=2)||'..Matches("\A[0-9]{1,7}\z",days)||'..Matches("\A[0-9]{1,5}(?:\.[0-9]{1,9})?\z",seconds) Return 0
        If (days<$ZDateH("1970-01-01",3))||(whole>=86400) Return 0
        Set fraction=$Extract($Piece(seconds,".",2)_"000000",1,6)
        Set us=((days-$ZDateH("1970-01-01",3))*86400000000)+(whole*1000000)+fraction
        If (us<0)||(us'=(us\1)) Return 0
        Set code="NATIVE_UTC_CONVERTED"
        Return 1
    } Catch ex { Return 0 }
}

/// Native READ and fixed local CSP scope, without requiring a running
/// production. Historical task visibility must survive a normal production stop.
/// No namespace, identity, application or SQL is accepted from request JSON.
ClassMethod QueryReader(Output principal As %DynamicObject, Output namespace As %String, Output user As %String) As %Boolean [ Private ]
{
    Set principal={},namespace="",user=""
    Try {
        Set sc=##class(Chronos.Approval.Identity).Current("READ",.principal)
        If $$$ISERR(sc)||'principal.%Get("authenticated") Return 0
        If '$Data(%request)||'$Data(%session) Return 0
        If '$IsObject(%request)||'$IsObject(%session) Return 0
        If '%request.%IsA("%CSP.Request")||'%session.%IsA("%CSP.Session") Return 0
        Set namespace=$Namespace,user=$Username
        If (user="")||(%session.Username'=user)||%session.EndSession Return 0
        If %request.GetCgiEnv("QUERY_STRING")'="" Return 0
        If '%session.EventClassExists("Chronos.Web.Events",namespace) Return 0
        Set config=##class(%DynamicObject).%FromJSON($Get(^ChronosWeb("config"),"{}"))
        If (config.%GetTypeOf("origin")'="string")||(config.%GetTypeOf("application")'="string") Return 0
        If '##class(Chronos.Web.NativePolicy).ValidOrigin(config.origin) Return 0
        If (%request.Application'=config.application)||(%request.GetCgiEnv("HTTP_HOST")'=$Piece(config.origin,"://",2)) Return 0
        If %request.Secure'=($Extract(config.origin,1,8)="https://") Return 0
        Return 1
    } Catch ex { Return 0 }
}

ClassMethod SameQueryReader(expected As %DynamicObject, namespace As %String, user As %String) As %Boolean [ Private ]
{
    If '..QueryReader(.current,.currentNamespace,.currentUser) Return 0
    Return (currentNamespace=namespace)&&(currentUser=user)&&(current.%Get("actor")=expected.%Get("actor"))&&(current.%Get("sessionBinding")=expected.%Get("sessionBinding"))
}

/// Private ledger correlation restricts the fixed native lookup to one actual
/// Chronos handoff. No expiry/BootReady check: this is also a historical read.
ClassMethod QueryAnchor(clarificationId As %String, requestId As %String, Output record As %DynamicObject) As %Boolean [ Private ]
{
    Set record={}
    If '##class(Chronos.Workflow.Store).ID(clarificationId) Return 0
    If ($Length(requestId)<1)||($Length(requestId)>18)||($Translate(requestId,"0123456789")'="")||(requestId<1) Return 0
    Try {
        Set sc=##class(Chronos.Workflow.Store).Inspect(clarificationId,.inspection)
        If $$$ISERR(sc)||(inspection.%Get("code")'="WORKFLOW_RECORDED")||(inspection.%GetTypeOf("record")'="object") Return 0
        Set record=inspection.record
        Return (record.%GetTypeOf("clarificationId")="string")&&(record.%Get("clarificationId")=clarificationId)&&(record.%GetTypeOf("taskRequestId")="string")&&(record.%Get("taskRequestId")=requestId)
    } Catch ex { Set record={} Return 0 }
}

/// Only these two literal parameterized SELECTs bypass SQL prepare privileges.
/// Application authorization and private correlation are checked before/after;
/// the accounts receive no general SELECT grants on native Workflow tables.
ClassMethod TaskForRequest(requestId As %String, Output taskId As %String, clarificationId As %String = "") As %Status
{
    Set taskId=""
    If '..QueryReader(.principal,.namespace,.user) Return $$$ERROR($$$GeneralError,"WORKFLOW_TASK_UNAVAILABLE")
    If '..QueryAnchor(clarificationId,requestId,.record) Return $$$ERROR($$$GeneralError,"WORKFLOW_TASK_UNAVAILABLE")
    Try {
        Set stmt=##class(%SQL.Statement).%New()
        Set sc=stmt.%Prepare("SELECT ID FROM EnsLib_Workflow.TaskResponse WHERE TaskStatus_Request=?",0) $$$ThrowOnError(sc)
        Set rows=stmt.%Execute(requestId),count=0,candidate=""
        If rows.%SQLCODE<0 Throw ##class(%Exception.General).%New("TASK_QUERY_FAILED")
        While rows.%Next() {
            Set count=count+1
            If count>1 Throw ##class(%Exception.General).%New("AMBIGUOUS_NATIVE_TASK")
            Set candidate=rows.%Get("ID")
            If ($Length(candidate)<1)||($Length(candidate)>18)||($Translate(candidate,"0123456789")'="")||(candidate<1) Throw ##class(%Exception.General).%New("INVALID_NATIVE_TASK")
        }
        If rows.%SQLCODE<0 Throw ##class(%Exception.General).%New("TASK_QUERY_FAILED")
        If '..QueryAnchor(clarificationId,requestId,.again) Throw ##class(%Exception.General).%New("WORKFLOW_ANCHOR_CHANGED")
        If (again.%Get("taskId")'="")&&(again.%Get("taskId")'=candidate) Throw ##class(%Exception.General).%New("WORKFLOW_TASK_CHANGED")
        If '..SameQueryReader(principal,namespace,user) Throw ##class(%Exception.General).%New("WORKFLOW_IDENTITY_CHANGED")
        Set taskId=candidate
    } Catch ex { Set taskId="" Return $$$ERROR($$$GeneralError,"WORKFLOW_TASK_UNAVAILABLE") }
    Return $$$OK
}

ClassMethod WorklistForTask(taskId As %String, user As %String, Output worklistId As %String, clarificationId As %String = "") As %Status
{
    Set worklistId=""
    If ($Length(taskId)<1)||($Length(taskId)>18)||($Translate(taskId,"0123456789")'="")||(taskId<1) Return $$$ERROR($$$GeneralError,"WORKFLOW_WORKLIST_UNAVAILABLE")
    If '##class(Chronos.Workflow.Store).ID(clarificationId) Return $$$ERROR($$$GeneralError,"WORKFLOW_WORKLIST_UNAVAILABLE")
    Set sc=..Current(.principal,.currentUser,.nativeUser,.membership,.code)
    If $$$ISERR(sc)||(code'="CSP_WORKFLOW_IDENTITY_CONFIRMED")||(user'=currentUser) Return $$$ERROR($$$GeneralError,"WORKFLOW_WORKLIST_UNAVAILABLE")
    Set namespace=$Namespace
    Try {
        Set sc=##class(Chronos.Workflow.Store).Inspect(clarificationId,.inspection) $$$ThrowOnError(sc)
        If (inspection.%Get("code")'="WORKFLOW_RECORDED")||(inspection.%GetTypeOf("record")'="object") Throw ##class(%Exception.General).%New("NO_HANDOFF")
        Set requestId=inspection.record.%Get("taskRequestId")
        Set sc=..TaskForRequest(requestId,.correlatedTask,clarificationId) $$$ThrowOnError(sc)
        If correlatedTask'=taskId Throw ##class(%Exception.General).%New("WRONG_NATIVE_TASK")
        Set stmt=##class(%SQL.Statement).%New()
        Set sc=stmt.%Prepare("SELECT ID FROM EnsLib_Workflow.Worklist WHERE Task=? AND UserName=?",0) $$$ThrowOnError(sc)
        Set rows=stmt.%Execute(taskId,currentUser),count=0,candidate=""
        If rows.%SQLCODE<0 Throw ##class(%Exception.General).%New("WORKLIST_QUERY_FAILED")
        While rows.%Next() {
            Set count=count+1
            If count>1 Throw ##class(%Exception.General).%New("AMBIGUOUS_WORKLIST")
            Set candidate=rows.%Get("ID")
            // Worklist has a composite Task/User IdKey, unlike TaskResponse.
            // Verify its native object instead of assuming a numeric row ID.
            If ($Length(candidate)<1)||($Length(candidate)>512) Throw ##class(%Exception.General).%New("INVALID_NATIVE_WORKLIST")
            Set item=##class(EnsLib.Workflow.Worklist).%OpenId(candidate,0,.sc) $$$ThrowOnError(sc)
            If '$IsObject(item)||(item.TaskGetObjectId()'=taskId)||(item.UserGetObjectId()'=currentUser)||(item.RoleGetObjectId()'=##class(Chronos.Workflow.Store).#ROLE) Throw ##class(%Exception.General).%New("WRONG_WORKLIST")
        }
        If rows.%SQLCODE<0 Throw ##class(%Exception.General).%New("WORKLIST_QUERY_FAILED")
        If '..QueryAnchor(clarificationId,requestId,.againRecord) Throw ##class(%Exception.General).%New("WORKFLOW_ANCHOR_CHANGED")
        If (againRecord.%Get("taskId")'="")&&(againRecord.%Get("taskId")'=taskId) Throw ##class(%Exception.General).%New("WORKFLOW_TASK_CHANGED")
        Set sc=..Current(.again,.sameUser,.againUser,.againMembership,.code) $$$ThrowOnError(sc)
        If (code'="CSP_WORKFLOW_IDENTITY_CONFIRMED")||(sameUser'=currentUser)||($Namespace'=namespace)||(again.%Get("actor")'=principal.%Get("actor"))||(again.%Get("sessionBinding")'=principal.%Get("sessionBinding")) Throw ##class(%Exception.General).%New("WORKFLOW_IDENTITY_CHANGED")
        Set worklistId=candidate
    } Catch ex { Set worklistId="" Return $$$ERROR($$$GeneralError,"WORKFLOW_WORKLIST_UNAVAILABLE") }
    Return $$$OK
}

/// Never return native rows, ticket, session binding, username, note or errors.
ClassMethod Public(result As %DynamicObject) As %DynamicObject [ Private ]
{
    Set out={"code":(result.%Get("code")),"actorVerified":false,"completionVerified":false,"canUseClarification":false,"dispatch_authorized":false}
    For field="clarificationId","completionId","state","expiresUS","completedUS" {
        If result.%IsDefined(field) Do out.%Set(field,result.%Get(field),result.%GetTypeOf(field))
    }
    If result.%Get("code")="WORKFLOW_CLARIFICATION_RECORDED" {
        Do out.%Set("actorVerified",1,"boolean"),out.%Set("completionVerified",1,"boolean")
    }
    // Adoption requires a separate new decision and fresh native proof.
    // A successful completion reply itself never permits adoption or a send.
    Return out
}

/// Read the original completion only. A missing/NEW result is not proof that
/// an earlier request cannot arrive later; never fence or invoke Engine here.
ClassMethod ReadCompletion(clarificationId As %String, completionId As %String, preference As %String, note As %String, Output result As %DynamicObject) As %Status
{
    Set result={"code":"WORKFLOW_RESOLUTION_UNAVAILABLE","actorVerified":false,"completionVerified":false,"canUseClarification":false,"dispatch_authorized":false}
    If $TLevel Return $$$ERROR($$$GeneralError,"WORKFLOW_REQUIRES_NO_TRANSACTION")
    Set sc=##class(Chronos.Workflow.Store).ResolutionStatus(clarificationId,completionId,preference,note,.status)
    If $$$ISERR(sc) Return $$$OK
    Set result=..Public(status)
    Return $$$OK
}

ClassMethod Complete(clarificationId As %String, completionId As %String, preference As %String, note As %String, Output result As %DynamicObject) As %Status
{
    Set result={"code":"WORKFLOW_RESOLUTION_UNAVAILABLE","actorVerified":false,"completionVerified":false,"canUseClarification":false,"dispatch_authorized":false}
    If $TLevel Return $$$ERROR($$$GeneralError,"WORKFLOW_REQUIRES_NO_TRANSACTION")
    If '##class(Chronos.Workflow.Store).ID(clarificationId)||'##class(Chronos.Workflow.Store).ID(completionId) Set result.code="INVALID_WORKFLOW_ID" Return $$$OK
    If '..Form(preference,note,.code) Set result.code=code Return $$$OK
    Set sc=..Current(.principal,.user,.userObject,.membership,.code) $$$ThrowOnError(sc)
    If code'="CSP_WORKFLOW_IDENTITY_CONFIRMED" Set result.code=code Return $$$OK
    Set serialized=0,itemLocked=0,taskLocked=0,taskId="",worklistId="",cleanupFailed=0
    Try {
        // A verified historical completion remains readable without requiring a
        // surviving Worklist. It never re-enters Engine or recreates its ticket.
        Set sc=##class(Chronos.Workflow.Store).ResolutionStatus(clarificationId,completionId,preference,note,.status) $$$ThrowOnError(sc)
        If status.code'="WORKFLOW_RESOLUTION_NEW" { Set result=..Public(status) }
        Else {
            Set sc=##class(Chronos.Workflow.Store).Inspect(clarificationId,.inspection) $$$ThrowOnError(sc)
            If inspection.%GetTypeOf("record")'="object" Throw ##class(%Exception.General).%New("NO_HANDOFF")
            Set sc=..TaskForRequest(inspection.record.taskRequestId,.taskId,clarificationId) $$$ThrowOnError(sc)
            If taskId="" { Set result.code="WORKFLOW_TASK_NOT_CREATED" }
            Else {
                // Serialize Chronos completers BEFORE any Worklist/Task lock.
                // Distinct user Worklist rows otherwise allow a lock cycle when
                // native AssignTask deletes the other users' Worklist entries.
                Lock +^ChronosDecision16("workflowTaskMutex",taskId):2
                If '$Test Throw ##class(%Exception.General).%New("WORKFLOW_TASK_BUSY")
                Set serialized=1
                Set sc=..WorklistForTask(taskId,user,.worklistId,clarificationId) $$$ThrowOnError(sc)
                If worklistId="" { Set result.code="WORKFLOW_TASK_NOT_OWNED" }
                Else {
                    // Native portal callers do not share our mutex. Bound the
                    // explicit native lock acquisition, then reread at mode 4.
                    // This is not a claim that all native SQL waits are bounded
                    // by this timeout or that cross-portal races are tested.
                    Set sc=##class(EnsLib.Workflow.Worklist).%LockId(worklistId,0,2) $$$ThrowOnError(sc)
                    Set itemLocked=1
                    Set sc=##class(EnsLib.Workflow.TaskResponse).%LockId(taskId,0,2) $$$ThrowOnError(sc)
                    Set taskLocked=1
                    Set sc=..CompleteSerialized(clarificationId,completionId,preference,note,taskId,worklistId,.result) $$$ThrowOnError(sc)
                }
            }
        }
    } Catch ex {
        Set result={"code":"WORKFLOW_RESOLUTION_UNAVAILABLE","actorVerified":false,"completionVerified":false,"canUseClarification":false,"dispatch_authorized":false}
    }
    // No returns occur after acquisition above. All inner references unwind
    // before releasing these separate explicit native locks and our mutex.
    If taskLocked {
        Try { Set release=##class(EnsLib.Workflow.TaskResponse).%UnlockId(taskId,0,1) If $$$ISERR(release) Set cleanupFailed=1 } Catch ex { Set cleanupFailed=1 }
    }
    If itemLocked {
        Try { Set release=##class(EnsLib.Workflow.Worklist).%UnlockId(worklistId,0,1) If $$$ISERR(release) Set cleanupFailed=1 } Catch ex { Set cleanupFailed=1 }
    }
    If serialized Lock -^ChronosDecision16("workflowTaskMutex",taskId)
    If cleanupFailed {
        Set result={"code":"WORKFLOW_RESOLUTION_UNCERTAIN","actorVerified":false,"completionVerified":false,"canUseClarification":false,"dispatch_authorized":false}
        Return $$$ERROR($$$GeneralError,"WORKFLOW_LOCK_RELEASE_UNCERTAIN")
    }
    Return $$$OK
}

/// Private worker: caller owns the per-task mutex and bounded explicit native
/// locks. Every task/worklist correlation is checked again before a side effect.
ClassMethod CompleteSerialized(clarificationId As %String, completionId As %String, preference As %String, note As %String, expectedTaskId As %String, expectedWorklistId As %String, Output result As %DynamicObject) As %Status [ Private ]
{
    Set result={"code":"WORKFLOW_RESOLUTION_UNAVAILABLE","actorVerified":false,"completionVerified":false,"canUseClarification":false,"dispatch_authorized":false},fenced=0,fenceAttempted=0,ticket=""
    If $TLevel Return $$$ERROR($$$GeneralError,"WORKFLOW_REQUIRES_NO_TRANSACTION")
    If '##class(Chronos.Workflow.Store).ID(clarificationId)||'##class(Chronos.Workflow.Store).ID(completionId) Set result.code="INVALID_WORKFLOW_ID" Return $$$OK
    If '..Form(preference,note,.code) Set result.code=code Return $$$OK
    Set sc=..Current(.principal,.user,.userObject,.membership,.code) $$$ThrowOnError(sc)
    If code'="CSP_WORKFLOW_IDENTITY_CONFIRMED" Set result.code=code Return $$$OK
    Try {
        Set sc=##class(Chronos.Workflow.Store).ResolutionStatus(clarificationId,completionId,preference,note,.status) $$$ThrowOnError(sc)
        If status.code'="WORKFLOW_RESOLUTION_NEW" { Set result=..Public(status) Return $$$OK }
        Set sc=##class(Chronos.Workflow.Store).Inspect(clarificationId,.inspection) $$$ThrowOnError(sc)
        If inspection.%GetTypeOf("record")'="object" Throw ##class(%Exception.General).%New("NO_HANDOFF")
        Set record=inspection.record
        If (record.taskRequestId="")||(##class(Chronos.Agent.Ledger).NowUS()'<record.expiresUS) Throw ##class(%Exception.General).%New("EXPIRED_HANDOFF")
        Set sc=..TaskForRequest(record.taskRequestId,.taskId,clarificationId) $$$ThrowOnError(sc)
        If taskId="" Set result.code="WORKFLOW_TASK_NOT_CREATED" Return $$$OK
        If taskId'=expectedTaskId Throw ##class(%Exception.General).%New("WORKFLOW_TASK_CHANGED")
        Set sc=..WorklistForTask(taskId,user,.worklistId,clarificationId) $$$ThrowOnError(sc)
        If worklistId="" Set result.code="WORKFLOW_TASK_NOT_OWNED" Return $$$OK
        If worklistId'=expectedWorklistId Throw ##class(%Exception.General).%New("WORKFLOW_ITEM_CHANGED")
        // Same retained-lock order as the native Workflow form. Never hold our
        // decision mutex while waiting for a Workflow object lock.
        Set item=##class(EnsLib.Workflow.Worklist).%OpenId(worklistId,4,.sc) $$$ThrowOnError(sc)
        If '$IsObject(item)||(item.UserGetObjectId()'=user)||(item.TaskGetObjectId()'=taskId)||(item.RoleGetObjectId()'=##class(Chronos.Workflow.Store).#ROLE) Throw ##class(%Exception.General).%New("WRONG_WORKLIST")
        Set task=##class(EnsLib.Workflow.TaskResponse).%OpenId(taskId,4,.sc) $$$ThrowOnError(sc)
        If '$IsObject(task)||'$IsObject(task.%TaskStatus)||'$IsObject(task.%TaskStatus.Request)||'$IsObject(task.%TaskStatus.Role) Throw ##class(%Exception.General).%New("NO_NATIVE_TASK")
        If (task.%TaskStatus.Request.%Id()'=record.taskRequestId)||(task.%TaskStatus.Request.%Command'=clarificationId)||(task.%TaskStatus.Role.Name'=##class(Chronos.Workflow.Store).#ROLE)||task.%TaskStatus.IsComplete Throw ##class(%Exception.General).%New("WRONG_NATIVE_TASK")
        // Build154 ItemExistsForTask declares an object but uses it as a
        // global ID subscript. Check the exact persistent row instead; the
        // retained item above already proves Task/User/Role under native locks.
        If '##class(EnsLib.Workflow.Worklist).%ExistsId(worklistId) Throw ##class(%Exception.General).%New("NO_WORKLIST")
        If task.%TaskStatus.AssignedTo="" {
            Set sc=##class(EnsLib.Workflow.Engine).%TakeOwnershipForTask(worklistId,user,.message) $$$ThrowOnError(sc)
            If message'="" Throw ##class(%Exception.General).%New("OWNERSHIP_DECLINED")
            Set task=##class(EnsLib.Workflow.TaskResponse).%OpenId(taskId,4,.sc) $$$ThrowOnError(sc)
        }
        If task.%TaskStatus.AssignedTo'=user Throw ##class(%Exception.General).%New("WRONG_ASSIGNEE")
        Set sc=..Current(.again,.sameUser,.againUser,.againMembership,.code) $$$ThrowOnError(sc)
        If (code'="CSP_WORKFLOW_IDENTITY_CONFIRMED")||(sameUser'=user)||(again.actor'=principal.actor)||(again.sessionBinding'=principal.sessionBinding) Throw ##class(%Exception.General).%New("IDENTITY_CHANGED")
        Set fenceAttempted=1
        Set sc=##class(Chronos.Workflow.Store).ResolutionFence(clarificationId,completionId,taskId,worklistId,preference,note,.fence,.ticket) $$$ThrowOnError(sc)
        If fence.code'="WORKFLOW_RESOLUTION_FENCED" { Set result=..Public(fence) Return $$$OK }
        Set fenced=1
        Do task.%FormValues.SetAt(preference,"Preference"),task.%FormValues.SetAt(note,"Note")
        Set sc=task.%Save() $$$ThrowOnError(sc)
        If ##class(Chronos.Agent.Ledger).NowUS()'<fence.expiresUS Throw ##class(%Exception.General).%New("CLARIFICATION_EXPIRED")
        // pUserName is not authorization in this native API. Authorization and
        // retained owner/task locks were checked independently above.
        Set sc=##class(EnsLib.Workflow.Engine).%ProcessAction("Clarified",worklistId,user,.message) $$$ThrowOnError(sc)
        If message'="" Throw ##class(%Exception.General).%New("COMPLETION_DECLINED")
        Set sc=##class(Chronos.Workflow.Store).VerifyResolution(clarificationId,completionId,ticket,.verified) $$$ThrowOnError(sc)
        Set result=..Public(verified),ticket=""
    } Catch ex {
        Set ticket=""
        If fenced { Try { Set ignored=##class(Chronos.Workflow.Store).ResolutionUncertain(clarificationId,completionId,.uncertain) } Catch ignoredEx {} }
        Set result={"code":($Select(fenceAttempted:"WORKFLOW_RESOLUTION_UNCERTAIN",1:"WORKFLOW_RESOLUTION_REJECTED")),"actorVerified":false,"completionVerified":false,"canUseClarification":false,"dispatch_authorized":false}
    }
    Return $$$OK
}

/// Pure contract checks plus the actual absence of CSP when run at the terminal.
/// No native task, membership, approval or recovery is fabricated or changed.
ClassMethod CheckContract(Output result As %DynamicObject) As %Status
{
    Set result={"scope":"PURE_CONTROLLER_CONTRACT_ONLY","checks":0,"passed":false,"actorVerified":false,"dispatch_authorized":false}
    If '..Form("EARLIEST_ALLOWED","Customer explicitly prioritizes earlier arrival.",.code) Return $$$ERROR($$$GeneralError,"WORKFLOW_CONTROLLER_CHECK_FAILED")
    Set result.checks=1
    If ..Form("APPROVE","Customer instruction",.code) Return $$$ERROR($$$GeneralError,"WORKFLOW_CONTROLLER_CHECK_FAILED")
    Set result.checks=2
    If ..Form("CHEAPEST_ON_TIME","",.code)||..Form("CHEAPEST_ON_TIME",$Justify("",241),.code)||..Form("CHEAPEST_ON_TIME","leading "_$Char(10)_"line",.code) Return $$$ERROR($$$GeneralError,"WORKFLOW_CONTROLLER_CHECK_FAILED")
    Set result.checks=3
    If ..Form("CHEAPEST_ON_TIME","password=not-a-real-secret",.code)||..Form("CHEAPEST_ON_TIME","\u0070assword=not-a-real-secret",.code) Return $$$ERROR($$$GeneralError,"WORKFLOW_CONTROLLER_CHECK_FAILED")
    Set result.checks=4
    If ..ExpectedRole("Unknown.Workflow.Role") Return $$$ERROR($$$GeneralError,"WORKFLOW_CONTROLLER_CHECK_FAILED")
    Set result.checks=5
    If '..UTCToUS("1970-01-01 00:00:00.000",.us,.code)||(us'=0) Return $$$ERROR($$$GeneralError,"WORKFLOW_CONTROLLER_CHECK_FAILED")
    Set result.checks=6
    If '..UTCToUS("1970-01-02 01:02:03.004",.us,.code)||(us'=90123004000) Return $$$ERROR($$$GeneralError,"WORKFLOW_CONTROLLER_CHECK_FAILED")
    Set result.checks=7
    If ..UTCToUS("2026-99-99 99:99:99.999",.us,.code)||..UTCToUS("1970-01-01T00:00:00Z",.us,.code) Return $$$ERROR($$$GeneralError,"WORKFLOW_CONTROLLER_CHECK_FAILED")
    Set result.checks=8
    If '$Data(%request),'$Data(%session) {
        Set sc=..Current(.p,.u,.uo,.m,.code) $$$ThrowOnError(sc)
        If code="CSP_WORKFLOW_IDENTITY_CONFIRMED" Return $$$ERROR($$$GeneralError,"WORKFLOW_CONTROLLER_CHECK_FAILED")
        Set result.checks=9
        // Even an administrative terminal cannot use the scoped lookup as a
        // generic SQL privilege bypass. These checks create/read no native task.
        Set taskId="unexpected",sc=..TaskForRequest("1",.taskId,"contract-no-csp")
        If $$$ISOK(sc)||(taskId'="") Return $$$ERROR($$$GeneralError,"WORKFLOW_CONTROLLER_CHECK_FAILED")
        Set result.checks=10
        Set worklistId="unexpected",sc=..WorklistForTask("1",$Username,.worklistId,"contract-no-csp")
        If $$$ISOK(sc)||(worklistId'="") Return $$$ERROR($$$GeneralError,"WORKFLOW_CONTROLLER_CHECK_FAILED")
        Set result.checks=11
    }
    Do result.%Set("passed",1,"boolean")
    Return $$$OK
}
}
