Include %occStatus

/// Internal, read-only account revalidation for a private native decision.
/// No HTTP identity, login, impersonation, role escalation or account mutation.
/// This does not assert that a password or every external login policy is valid.
Class Chronos.Workflow.AccountState Extends %RegisteredObject
{
Parameter ROLE = "Chronos.Clarifiers";

ClassMethod Digest(value As %String) As %String [ Private ]
{
    Return $ZConvert(##class(%xsd.hexBinary).LogicalToXSD($System.Encryption.SHAHash(256,value)),"L")
}

/// Pure consistency check only. The caller obtains BOTH objects from the private
/// ledger/index. Hashes are not authentication or proof of a live CSP session.
ClassMethod AnchorProof(packetJSON As %String) As %Boolean [ Language = python, Private ]
{
    import hashlib,json,re,unicodedata
    try:
        if type(packetJSON) is not str or len(packetJSON.encode('utf-8'))>65536:return False
        def pairs(items):
            out={}
            for key,value in items:
                if key in out:raise ValueError('DUPLICATE')
                out[key]=value
            return out
        def invalid(value):raise ValueError('NONFINITE')
        value=json.loads(packetJSON,object_pairs_hook=pairs,parse_constant=invalid)
        if type(value) is not dict or set(value)!={'anchor','reference','index','requestId','generation','actor','nowUS'}:return False
        a=value['anchor'];r=value['reference'];idx=value['index']
        keys=set('schema requestId clarificationId user actor generation referenceSha256 sourceSha256 createdUS expiresUS'.split())
        if type(a) is not dict or set(a)!=keys or type(idx) is not dict or a!=idx:return False
        if a['schema']!='chronos.clarification-registration.v1':return False
        def match(text,pattern):return type(text) is str and re.fullmatch(pattern,text) is not None
        for key in ('requestId','clarificationId','generation'):
            if not match(a[key],r'[A-Za-z0-9_.:-]{1,128}'):return False
        if (a['requestId'],a['generation'],a['actor'])!=(value['requestId'],value['generation'],value['actor']):return False
        if not match(a['actor'],r'principal-[a-f0-9]{64}'):return False
        user=a['user']
        if type(user) is not str or not 1<=len(user)<=128 or any(unicodedata.category(c).startswith('C') for c in user):return False
        for key in ('referenceSha256','sourceSha256'):
            if not match(a[key],r'[a-f0-9]{64}'):return False
        for field in ('createdUS','expiresUS'):
            if type(a[field]) is not int or not 0<=a[field]<2**63:return False
        now=value['nowUS']
        if type(now) is not int or not 0<=now<2**63:return False
        if not a['createdUS']<=now<a['expiresUS']<=a['createdUS']+600000000:return False
        fields=set('schema_version binding binding_sha256 record_sha256 native_completion_sha256 authority_material_sha256 expires_us message_sha256'.split())
        if type(r) is not dict or set(r)!=fields or r['schema_version']!='chronos.clarification-reference.v1':return False
        if type(r['binding']) is not dict:return False
        if (r['binding'].get('clarification_id'),r['binding'].get('generation'),r['expires_us'])!=(a['clarificationId'],a['generation'],a['expiresUS']):return False
        if type(r['expires_us']) is not int:return False
        for field in fields-{'schema_version','binding','expires_us'}:
            if not match(r[field],r'[a-f0-9]{64}'):return False
        raw=json.dumps(r,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode('utf-8')
        return hashlib.sha256(raw).hexdigest()==a['referenceSha256']
    except (ValueError,TypeError,KeyError,OverflowError,UnicodeError,RecursionError):return False
}

/// Native composition only; never project this private anchor through HTTP.
ClassMethod ReadAnchor(requestId As %String, Output anchor As %DynamicObject) As %Boolean
{
    Set anchor={}
    Try {
        If ($Length(requestId)<1)||($Length(requestId)>128)||($Translate(requestId,"abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.:-")'="") Return 0
        Set sc=##class(Chronos.Agent.Ledger).Apply("INSPECT",{"requestId":(requestId)},.read) $$$ThrowOnError(sc)
        If read.%GetTypeOf("private")'="object" Return 0
        Set d=read.private
        If (d.%Get("requestId")'=requestId)||(d.%GetTypeOf("clarificationAnchor")'="object") Return 0
        If d.%GetTypeOf("prepared")'="object" Return 0
        If d.prepared.%GetTypeOf("record")'="object" Return 0
        If d.prepared.record.%GetTypeOf("clarification_binding")'="object" Return 0
        Set candidate=d.clarificationAnchor
        If (candidate.%GetTypeOf("user")'="string")||(candidate.%GetTypeOf("clarificationId")'="string") Return 0
        Set raw=$Get(^ChronosDecision16("clarificationAdoption",candidate.clarificationId))
        If (raw="")||(raw'=candidate.%ToJSON()) Return 0
        Set actor="principal-"_..Digest($ListBuild($Namespace,candidate.user))
        Set packet={"anchor":(candidate),"reference":(d.prepared.record.%Get("clarification_binding")),"index":(##class(%DynamicObject).%FromJSON(raw)),"requestId":(requestId),"generation":(d.%Get("generation")),"actor":(actor),"nowUS":(##class(Chronos.Agent.Ledger).NowUS())}
        If '..AnchorProof(packet.%ToJSON()) Return 0
        Set anchor=##class(%DynamicObject).%FromJSON(candidate.%ToJSON())
        Return 1
    } Catch ex { Return 0 }
}

/// Never accepts a user name from HTTP. This input is a private ledger key.
/// Reads only the anchored account's three flags through a selective %SYS API.
ClassMethod AccountFlags(user As %String, Output flags As %DynamicObject) As %Status [ Private ]
{
    Set flags={"available":false,"code":"WORKFLOW_ACCOUNT_STATE_UNAVAILABLE"}
    Try {
        New $Namespace
        Set $Namespace="%SYS"
        If '##class(%Dictionary.CompiledClass).%ExistsId("%ZChronos.Workflow.AccountQuery") Return $$$OK
        Set sc=##class(%ZChronos.Workflow.AccountQuery).ReadFlags(user,.flags)
        If $$$ISERR(sc) Set flags={"available":false,"code":"WORKFLOW_ACCOUNT_STATE_UNAVAILABLE"}
    } Catch ex { Set flags={"available":false,"code":"WORKFLOW_ACCOUNT_STATE_UNAVAILABLE"} }
    Return $$$OK
}

/// Native date policy is deliberately conservative at the boundary day:
/// when AccountNeverExpires is false, an explicit expiry must be strictly
/// later than today's IRIS $HOROLOG day. Honor the native never-expire flag.
/// Disabled/past/today/future account tests are still needed;
/// it must not be described as a complete replacement for IRIS authentication.
ClassMethod FlagsAllow(flags As %DynamicObject) As %Boolean [ Private ]
{
    Try {
        If flags.%Size()'=5 Return 0
        If (flags.%GetTypeOf("available")'="boolean")||'flags.available||(flags.%Get("code")'="WORKFLOW_ACCOUNT_FLAGS_READ") Return 0
        If (flags.%GetTypeOf("enabled")'="boolean")||'flags.enabled Return 0
        If flags.%GetTypeOf("accountNeverExpires")'="boolean" Return 0
        If flags.%GetTypeOf("expirationDate")="null" Return 1
        If flags.%GetTypeOf("expirationDate")'="number" Return 0
        Set day=flags.expirationDate
        If (day<0)||(day'=(day\1)) Return 0
        // IRIS returns logical date0 for a real never-expiring account. The
        // native AccountNeverExpires flag overrides the stored date; it does
        // not override Enabled or malformed flag/date types checked above.
        If flags.accountNeverExpires Return 1
        Return day>+$Horolog
    } Catch ex { Return 0 }
}

/// Fixed pure regression vectors only. This neither queries a real account nor
/// accepts caller-supplied flags, creates an identity or grants any permission.
ClassMethod CheckContract(Output result As %DynamicObject) As %Status
{
    Set today=+$Horolog
    Set cases=[{"enabled":true,"day":0,"never":true,"expected":true},{"enabled":true,"day":0,"never":false,"expected":false},{"enabled":true,"day":(today+1),"never":false,"expected":true},{"enabled":true,"day":(today),"never":false,"expected":false},{"enabled":true,"day":(today-1),"never":false,"expected":false},{"enabled":true,"day":(today-1),"never":true,"expected":true},{"enabled":false,"day":0,"never":true,"expected":false},{"enabled":true,"day":-1,"never":true,"expected":false},{"enabled":true,"day":null,"never":false,"expected":true},{"enabled":true,"day":"invalid","never":true,"expected":false},{"enabled":true,"day":0.5,"never":true,"expected":false}]
    Set passed=1
    For i=0:1:cases.%Size()-1 {
        Set c=cases.%Get(i),flags={"available":true,"code":"WORKFLOW_ACCOUNT_FLAGS_READ","enabled":(c.enabled),"expirationDate":(c.day),"accountNeverExpires":(c.never)}
        Do flags.%Set("enabled",c.enabled,"boolean"),flags.%Set("accountNeverExpires",c.never,"boolean")
        Do flags.%Set("expirationDate",c.day,c.%GetTypeOf("day"))
        If ..FlagsAllow(flags)'=c.expected Set passed=0
    }
    Set result={"scope":"PURE_ACCOUNT_FLAG_POLICY_ONLY","checks":(cases.%Size()),"passed":false,"dispatch_authorized":false}
    Do result.%Set("passed",passed,"boolean")
    Return $$$OK
}

/// SQL reads prevent a previously retained Workflow object from masking a
/// deletion or IsActive change in the same worker. No user list is returned.
ClassMethod WorkflowAllowed(user As %String) As %Boolean [ Private ]
{
    Try {
        If '##class(EnsLib.Workflow.RoleDefinition).%ExistsId(..#ROLE) Return 0
        Set stmt=##class(%SQL.Statement).%New(0)
        Set sc=stmt.%Prepare("SELECT IsActive FROM EnsLib_Workflow.UserDefinition WHERE Name=?") $$$ThrowOnError(sc)
        Set rows=stmt.%Execute(user)
        If rows.%SQLCODE<0 Return 0
        If 'rows.%Next() Return 0
        If rows.%Get("IsActive")'=1 Return 0
        If rows.%Next() Return 0
        If rows.%SQLCODE<0 Return 0
        Set stmt=##class(%SQL.Statement).%New(0)
        Set sc=stmt.%Prepare("SELECT 1 AS BoundMembership FROM EnsLib_Workflow.RoleMembership WHERE RoleName=? AND UserName=?") $$$ThrowOnError(sc)
        Set rows=stmt.%Execute(..#ROLE,user)
        If rows.%SQLCODE<0 Return 0
        If 'rows.%Next() Return 0
        If rows.%Get("BoundMembership")'=1 Return 0
        If rows.%Next() Return 0
        If rows.%SQLCODE<0 Return 0
        Return 1
    } Catch ex { Return 0 }
}

ClassMethod ForDecision(requestId As %String, Output result As %DynamicObject) As %Status
{
    Set result={"allowed":false,"code":"WORKFLOW_ACCOUNT_STATE_UNAVAILABLE"}
    If $TLevel Return $$$OK
    Try {
        If '..ReadAnchor(requestId,.anchor) Return $$$OK
        // A CSP caller keeps its own limited privileges. Only a gate created in
        // THIS native job/namespace may supply its pre-Boot account observation
        // (maximum age 1s), never an IPC call while Boot/Task locks are retained.
        // The queued worker never receives this object or a browser identity.
        If '$System.Security.Check("%Admin_Secure","USE")||'$System.Security.Check("%DB_IRISSYS","READ") {
            If '$Data(%ChronosWorkflowGate)||'$IsObject(%ChronosWorkflowGate) Return $$$OK
            If %ChronosWorkflowGate.%ClassName(1)'="Chronos.Workflow.ContextGate" Return $$$OK
            Set sc=%ChronosWorkflowGate.AccountCheckRequestId(requestId,.delegated) $$$ThrowOnError(sc)
            If (delegated.%Size()'=2)||(delegated.%GetTypeOf("allowed")'="boolean")||'delegated.allowed||(delegated.%Get("code")'="WORKFLOW_ACCOUNT_CURRENTLY_ALLOWED") Return $$$OK
            If '..ReadAnchor(requestId,.afterDelegate) Return $$$OK
            If afterDelegate.%ToJSON()'=anchor.%ToJSON() Return $$$OK
            Set sc=%ChronosWorkflowGate.Validate(.stillCurrent) $$$ThrowOnError(sc)
            If (stillCurrent.%Size()'=2)||(stillCurrent.%GetTypeOf("allowed")'="boolean")||'stillCurrent.allowed||(stillCurrent.%Get("code")'="WORKFLOW_ACCOUNT_CURRENTLY_ALLOWED") Return $$$OK
            Set result={"allowed":true,"code":"WORKFLOW_ACCOUNT_CURRENTLY_ALLOWED"}
            Return $$$OK
        }
        Set user=anchor.user
        Set sc=..AccountFlags(user,.flags) $$$ThrowOnError(sc)
        If '..FlagsAllow(flags) Return $$$OK
        If $System.Security.CheckUserPermission(user,"Chronos_Read","USE")'=1 Return $$$OK
        If $System.Security.CheckUserPermission(user,"Chronos_Approve","USE")'=1 Return $$$OK
        If '..WorkflowAllowed(user) Return $$$OK
        // The caller also revalidates before/after adopting the resolution.
        // This local reread rejects changed/expired ledger anchors meanwhile.
        If '..ReadAnchor(requestId,.again) Return $$$OK
        If again.%ToJSON()'=anchor.%ToJSON() Return $$$OK
        If '..FlagsAllow(flags) Return $$$OK
        Set result={"allowed":true,"code":"WORKFLOW_ACCOUNT_CURRENTLY_ALLOWED"}
    } Catch ex { Set result={"allowed":false,"code":"WORKFLOW_ACCOUNT_STATE_UNAVAILABLE"} }
    Return $$$OK
}
}
