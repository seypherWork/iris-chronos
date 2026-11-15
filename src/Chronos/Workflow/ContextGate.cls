Include %occStatus

/// Experimental native per-operation context, not a serializable grant/session.
/// Init probes the account BEFORE Task/boot locks and destroys its service OREF
/// before retaining either lock. The retained account observation is at most ONE
/// SECOND old from BEFORE that probe, never a claim of instantaneous revocation.
/// Under boot, Validate checks only this job-bound OREF, private anchor, clock
/// and current CSP identity/Read/Approve permissions. It sends NO IPC and never
/// refreshes the sample or the human clarification's absolute expiry.
/// Worker Claim/Finish continue to check current SQL account state separately.
/// Real Stop/revocation/expiry/latency tests remain required before integration.
Class Chronos.Workflow.ContextGate Extends %RegisteredObject
{
Property OwnerJob As %Integer [ Private ];
Property OwnerNamespace As %String [ Private ];
Property OwnerDecision As %String [ Private ];
Property OwnerActor As %String [ Private ];
Property OwnerSession As %String [ Private ];
Property OwnerGeneration As %String [ Private ];
Property AnchorJSON As %String(MAXLEN = 32768) [ Private ];
Property ProbeStartedUS As %Numeric [ Private ];
Property ProbeFinishedUS As %Numeric [ Private ];
Property ProbeExpiresUS As %Numeric [ Private ];
Property AnchorExpiresUS As %Numeric [ Private ];
Property TaskId As %String [ Private ];
Property TaskLocked As %Boolean [ Private ];
Property Initialized As %Boolean [ Private ];

ClassMethod SafeResult(raw As %String, Output result As %DynamicObject) As %Status
{
    Set result={"allowed":false,"code":"WORKFLOW_ACCOUNT_STATE_UNAVAILABLE"}
    Try {
        If ($Length(raw)<1)||($Length($ZConvert(raw,"O","UTF8"))>256) Return $$$OK
        Set r=##class(%DynamicObject).%FromJSON(raw)
        If r.%Size()'=2 Return $$$OK
        If (r.%GetTypeOf("allowed")'="boolean")||(r.%GetTypeOf("code")'="string") Return $$$OK
        If r.allowed&&(r.code="WORKFLOW_ACCOUNT_CURRENTLY_ALLOWED") Set result={"allowed":true,"code":"WORKFLOW_ACCOUNT_CURRENTLY_ALLOWED"}
    } Catch ex { Set result={"allowed":false,"code":"WORKFLOW_ACCOUNT_STATE_UNAVAILABLE"} }
    Return $$$OK
}

/// Pure arithmetic policy, NOT a native account or authentication check.
/// A reply taking one second or longer cannot establish a valid sample.
ClassMethod Window(started As %Numeric, finished As %Numeric, now As %Numeric, expires As %Numeric, humanExpires As %Numeric) As %Boolean
{
    For value=started,finished,now,expires,humanExpires {
        If (value<0)||(value'=(value\1)) Return 0
    }
    Return (started<=finished)&&(finished<=now)&&(finished<expires)&&(started<=now)&&(now<expires)&&(expires<=(started+1000000))&&(expires<=humanExpires)
}

Method ValidFor(requestId As %String) As %Boolean [ Private ]
{
    If '..Initialized||(..OwnerJob'=$Job)||(..OwnerNamespace'=$Namespace)||(..OwnerDecision'=requestId) Return 0
    Try {
        Set now=##class(Chronos.Agent.Ledger).NowUS()
        If '..Window(..ProbeStartedUS,..ProbeFinishedUS,now,..ProbeExpiresUS,..AnchorExpiresUS) Return 0
        Set sc=##class(Chronos.Approval.Identity).Current("APPROVE",.p) $$$ThrowOnError(sc)
        If 'p.%Get("authenticated")||(p.%Get("actor")'=..OwnerActor)||(p.%Get("sessionBinding")'=..OwnerSession) Return 0
        If '##class(Chronos.Workflow.AccountState).ReadAnchor(requestId,.current) Return 0
        If current.%ToJSON()'=..AnchorJSON Return 0
        Set state=##class(%DynamicObject).%FromJSON($Get(^ChronosRuntime("state"),"{}"))
        If (state.%Get("state")'="RECOVERED")||(state.%Get("generation")'=..OwnerGeneration) Return 0
        Set now=##class(Chronos.Agent.Ledger).NowUS()
        If '..Window(..ProbeStartedUS,..ProbeFinishedUS,now,..ProbeExpiresUS,..AnchorExpiresUS) Return 0
        Return 1
    } Catch ex { Return 0 }
}

/// Under Task/boot locks this is a bounded retained observation, NOT SQL/IPC.
Method AccountCheckRequestId(requestId As %String, Output result As %DynamicObject) As %Status
{
    Set result={"allowed":false,"code":"WORKFLOW_ACCOUNT_STATE_UNAVAILABLE"}
    If $TLevel||'..ValidFor(requestId) Return $$$OK
    Set result={"allowed":true,"code":"WORKFLOW_ACCOUNT_CURRENTLY_ALLOWED"}
    Return $$$OK
}

/// The approval controller must call this immediately before CONFIRM_RESERVE
/// and ADMIT as well as ordinary source reads. Expiry means NO shipment action.
Method Validate(Output result As %DynamicObject) As %Status
{
    Return ..AccountCheckRequestId(..OwnerDecision,.result)
}

/// Commit-time age fence ONLY, valid inside Authority's existing transaction.
/// It does not read identity/SQL/ledger or obtain a new account observation.
/// The controller/transition must separately retain the decision, preview,
/// actor and operation bindings. Recheck before Transition AND before TCommit;
/// failure must roll back and suppress every returned grant. This bounds the
/// observation at authorization commit, not at later I/O or journal-sync reply.
Method CommitWindow(decisionId As %String) As %Boolean
{
    If '..Initialized||'..TaskLocked||(..OwnerJob'=$Job)||(..OwnerNamespace'=$Namespace)||(decisionId'=..OwnerDecision) Return 0
    Try {
        Set state=##class(%DynamicObject).%FromJSON($Get(^ChronosRuntime("state"),"{}"))
        If (state.%Get("state")'="RECOVERED")||(state.%Get("generation")'=..OwnerGeneration) Return 0
        // Same Unix-microsecond basis as Ledger.NowUS, without calling Ledger
        // or acquiring any other lock while the authority transaction is open.
        Set stamp=$ZTimestamp,days=($Piece(stamp,",",1)-$ZDateH("1970-01-01",3))
        Set seconds=$Piece(stamp,",",2),whole=$Piece(seconds,".",1)
        Set fraction=$Extract($Piece(seconds,".",2)_"000000",1,6)
        Set now=(days*86400000000)+(whole*1000000)+fraction
        Return ..Window(..ProbeStartedUS,..ProbeFinishedUS,now,..ProbeExpiresUS,..AnchorExpiresUS)
    } Catch ex { Return 0 }
}

Method Init(requestId As %String, Output result As %DynamicObject) As %Status
{
    Set result={"ready":false,"code":"WORKFLOW_CONTEXT_GATE_UNAVAILABLE"},service=""
    If $TLevel||..Initialized Return $$$OK
    Try {
        Set sc=##class(Chronos.Workflow.Controller).Current(.p,.user,.nativeUser,.membership,.code) $$$ThrowOnError(sc)
        If code'="CSP_WORKFLOW_IDENTITY_CONFIRMED" Return $$$OK
        If '##class(Chronos.Workflow.AccountState).ReadAnchor(requestId,.anchor) Return $$$OK
        If (anchor.user'=user)||(anchor.actor'=p.actor) Return $$$OK
        Set sc=##class(Ens.Director).GetProductionStatus(.name,.state,0) $$$ThrowOnError(sc)
        Set cfg=##class(%DynamicObject).%FromJSON($Get(^ChronosRuntime("config"),"{}"))
        If (state'=1)||(name'=cfg.%Get("production")) Return $$$OK
        Set ..OwnerJob=$Job,..OwnerNamespace=$Namespace,..OwnerDecision=requestId
        Set ..OwnerActor=p.actor,..OwnerSession=p.sessionBinding,..OwnerGeneration=anchor.generation
        Set ..AnchorJSON=anchor.%ToJSON(),..AnchorExpiresUS=anchor.expiresUS
        // Load the immutable historical projection before starting the short
        // account sample. This performs no inference, provider I/O or approval.
        // Discard it: fresh source/identity/Review and commit checks below still
        // establish every authorization. Do not consume sample time on imports.
        Set sc=##class(Chronos.Agent.Ledger).Apply("INSPECT",{"requestId":(requestId)},.read) $$$ThrowOnError(sc)
        If read.%GetTypeOf("private")'="object" Throw ##class(%Exception.General).%New("DECISION_NOT_AVAILABLE")
        Set sc=##class(Chronos.Agent.Python).Detail(cfg.pythonRoot,read.private.%ToJSON(),requestId,.warm) $$$ThrowOnError(sc)
        If '$IsObject(warm) Throw ##class(%Exception.General).%New("INVALID_HISTORICAL_PROJECTION")
        If 'warm.%IsA("%DynamicObject") Throw ##class(%Exception.General).%New("INVALID_HISTORICAL_PROJECTION")
        If (warm.%Get("code")'="DECISION_DETAIL_RECORDED")||(warm.%Get("decisionId")'=requestId) Throw ##class(%Exception.General).%New("DECISION_DETAIL_UNAVAILABLE")
        For field="dispatchGranted","canConfirm","currentAuthorityVerified" {
            If (warm.%GetTypeOf(field)'="boolean")||warm.%Get(field) Throw ##class(%Exception.General).%New("INVALID_HISTORICAL_PROJECTION")
        }
        Set read="",warm=""
        // Service initialization can acquire production runtime locks. It must
        // happen here, before the caller enters bootLock, never lazily inside it.
        Set sc=##class(Ens.Director).CreateBusinessService("Chronos.Workflow.AccountService",.service) $$$ThrowOnError(sc)
        If '$IsObject(service)||(service.%ClassName(1)'="Chronos.Workflow.AccountService") Throw ##class(%Exception.General).%New("WRONG_FIXED_SERVICE")
        Set request=##class(Chronos.Workflow.Request).%New(),request.DecisionId=requestId
        // Start the maximum age BEFORE the worker can read account state.
        Set ..ProbeStartedUS=##class(Chronos.Agent.Ledger).NowUS()
        Set ..ProbeExpiresUS=(..ProbeStartedUS+1000000)
        If ..AnchorExpiresUS<..ProbeExpiresUS Set ..ProbeExpiresUS=..AnchorExpiresUS
        Set sc=service.ProcessInput(request,.response) $$$ThrowOnError(sc)
        Set ..ProbeFinishedUS=##class(Chronos.Agent.Ledger).NowUS()
        If '$IsObject(response)||(response.%ClassName(1)'="Chronos.App.Response") Throw ##class(%Exception.General).%New("NO_ACCOUNT_PROBE_RESPONSE")
        If response.Code'="WORKFLOW_ACCOUNT_CHECK_FINISHED" Throw ##class(%Exception.General).%New("ACCOUNT_PROBE_UNAVAILABLE")
        Set sc=..SafeResult(response.ResultJSON,.checked) $$$ThrowOnError(sc)
        If 'checked.allowed Throw ##class(%Exception.General).%New("ACCOUNT_PROBE_DENIED")
        // Explicitly release the service reference before SourceForDecision
        // can retain any Task row or boot lock. No service OREF is a property.
        Set service=""
        Set now=##class(Chronos.Agent.Ledger).NowUS()
        If '..Window(..ProbeStartedUS,..ProbeFinishedUS,now,..ProbeExpiresUS,..AnchorExpiresUS) Throw ##class(%Exception.General).%New("ACCOUNT_PROBE_TOO_OLD")
        Set ..Initialized=1
        New %ChronosWorkflowGate
        Set %ChronosWorkflowGate=$This
        Set sc=##class(Chronos.Workflow.Store).SourceForDecision(requestId,.source) $$$ThrowOnError(sc)
        If source.%GetTypeOf("expected_binding")'="object" Throw ##class(%Exception.General).%New("NO_VERIFIED_SOURCE")
        Set task=source.%Get("expected_binding").%Get("task_id")
        If ($Length(task)<1)||($Length(task)>18)||($Translate(task,"0123456789")'="")||(task<1) Throw ##class(%Exception.General).%New("INVALID_NATIVE_TASK")
        Set sc=##class(EnsLib.Workflow.TaskResponse).%LockId(task,1,2) $$$ThrowOnError(sc)
        Set ..TaskId=task,..TaskLocked=1
        Set sc=##class(Chronos.Workflow.Store).SourceForDecision(requestId,.fresh) $$$ThrowOnError(sc)
        If fresh.%GetTypeOf("expected_binding")'="object" Throw ##class(%Exception.General).%New("NO_FRESH_VERIFIED_SOURCE")
        If fresh.%Get("expected_binding").%Get("task_id")'=task Throw ##class(%Exception.General).%New("NATIVE_TASK_CHANGED")
        If '..ValidFor(requestId) Throw ##class(%Exception.General).%New("NATIVE_CONTEXT_CHANGED")
        Set result={"ready":true,"code":"WORKFLOW_CONTEXT_GATE_READY"}
    } Catch ex { Set result={"ready":false,"code":"WORKFLOW_CONTEXT_GATE_UNAVAILABLE"} }
    // Errors before the explicit release above still clean up outside locks.
    // Once TaskLocked is true this local must already be the empty string.
    If $IsObject(service) Set service=""
    If 'result.ready { Set ignored=..Release() }
    Return $$$OK
}

Method Release() As %Status
{
    Set sc=$$$OK
    If ..OwnerJob'=$Job Return $$$ERROR($$$GeneralError,"FOREIGN_CONTEXT_GATE_JOB")
    If ..TaskLocked {
        Try {
            New $Namespace
            Set $Namespace=..OwnerNamespace
            Set sc=##class(EnsLib.Workflow.TaskResponse).%UnlockId(..TaskId,1,1)
        } Catch ex { Set sc=$$$ERROR($$$GeneralError,"CONTEXT_GATE_RELEASE_UNAVAILABLE") }
        If $$$ISOK(sc) Set ..TaskLocked=0,..TaskId=""
    }
    Set ..Initialized=0,..AnchorJSON="",..ProbeExpiresUS=0
    Return sc
}

Method %OnClose() As %Status
{
    If ..OwnerJob=$Job { Set ignored=..Release() }
    Return $$$OK
}
}
