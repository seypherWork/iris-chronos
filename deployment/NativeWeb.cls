Include %occStatus

/// Trusted console control for the one installed Chronos web application.
/// Never edits users, roles, passwords, ports, provider allowance or business state.
Class Chronos.Deployment.NativeWeb Extends %RegisteredObject
{
ClassMethod SameList(actual As %String, expected As %String) As %Boolean [ Private ]
{
    If $Length(actual,",")'=$Length(expected,",") Return 0
    For i=1:1:$Length(actual,",") {
        Set part=$Piece(actual,",",i)
        If (part="")||$Data(seen(part))||'$ListFind($ListFromString(expected),part) Return 0
        Set seen(part)=1
    }
    Return 1
}

/// Security.Users exposes role properties as native collections, not comma strings.
/// Reject absent/wrong collections, extras and duplicates; an empty expected set
/// still requires a real empty collection (used for escalation roles).
ClassMethod SameRoles(actual As %RegisteredObject, expected As %String) As %Boolean [ Private ]
{
    If '$IsObject(actual) Return 0
    If 'actual.%IsA("%Collection.ListOfDT") Return 0
    Set count=$Select(expected="":0,1:$Length(expected,","))
    If actual.Count()'=count Return 0
    For i=1:1:count {
        Set part=actual.GetAt(i)
        If (part="")||$Data(seen(part))||'$ListFind($ListFromString(expected),part) Return 0
        Set seen(part)=1
    }
    Return 1
}

/// MatchRoles contains conditional and unconditional application grants.
ClassMethod WebAuthMatches(authentication As %Integer, grants As %String, prefix As %String) As %Boolean [ Private ]
{
    Return (authentication=32)&&(grants=(prefix_"_Read:"_prefix_"_Python"))
}

ClassMethod Owned(s As %DynamicObject, Output enabled As %Boolean) [ Private ]
{
    Kill p Set sc=##class(Security.Applications).Get(s.webPath,.p) $$$ThrowOnError(sc)
    If (p("NameSpace")'=s.namespace)||(p("Resource")'=s.access)||(p("DispatchClass")'="Chronos.Web.API") Throw ##class(%Exception.General).%New("WEB_OWNERSHIP_CHANGED")
    Set enabled=p("Enabled")
    If (enabled'=0)&&(enabled'=1) Throw ##class(%Exception.General).%New("WEB_STATE_INVALID")
}

/// Inspects only expected objects; no password/hash/salt property is accessed.
ClassMethod Policy(s As %DynamicObject, Output prepared As %Boolean) [ Private ]
{
    Set prepared=0
    Set temp=s.databases.%Get(1),db=##class(SYS.Database).%OpenId(temp.directory)
    If '$IsObject(db)||(db.ResourceName'=s.tempResource) Throw ##class(%Exception.General).%New("TEMP_DATABASE_RESOURCE_CHANGED")
    If ##class(%SYS.Namespace).GetGlobalDest(s.namespace,"IRIS.TempCSPLang")'=("^"_temp.directory) Throw ##class(%Exception.General).%New("TEMP_LANGUAGE_MAPPING_CHANGED")
    For name=s.resource,s.tempResource,s.secondaryResource,s.access,"Chronos_Read","Chronos_Approve" {
        Kill p Set sc=##class(Security.Resources).Get(name,.p) $$$ThrowOnError(sc)
        If p("PublicPermission")'="" Throw ##class(%Exception.General).%New("PUBLIC_RESOURCE_CHANGED")
    }
    For i=0:1:3 {
        Set role=s.roles.%Get(i)
        Kill p Set sc=##class(Security.Roles).Get(role.name,.p) $$$ThrowOnError(sc)
        If '..SameList(p("Resources"),role.resources)||(p("GrantedRoles")'="")||p("EscalationOnly") Throw ##class(%Exception.General).%New("ROLE_POLICY_CHANGED")
    }
    For i=0:1:1 {
        Set expected=s.users.%Get(i),sc=0,user=""
        Set exists=##class(Security.Users).Exists(expected.name,.user,.sc) $$$ThrowOnError(sc)
        If 'exists||'$IsObject(user) Throw ##class(%Exception.General).%New("USER_MISSING")
        If '..SameRoles(user.Roles,expected.roles)||'..SameRoles(user.EscalationRoles,"")||user.SuperUser||(user.NameSpace'=s.namespace) Throw ##class(%Exception.General).%New("USER_POLICY_CHANGED")
        If user.Enabled&&'user.ChangePassword Set prepared=1
        Set user=""
    }
    Kill p Set sc=##class(Security.Applications).Get(s.webPath,.p) $$$ThrowOnError(sc)
    // Get returns every conditional AND unconditional grant in MatchRoles.
    // AddedRoles belongs to the Detail query, not the Get property contract.
    If '..WebAuthMatches(p("AutheEnabled"),p("MatchRoles"),s.prefix) Throw ##class(%Exception.General).%New("WEB_AUTH_CHANGED")
    If (p("EventClass")'="Chronos.Web.Events")||(p("Timeout")'=3600)||(p("UseCookies")'=2)||(p("CookiePath")'=s.application) Throw ##class(%Exception.General).%New("WEB_SESSION_CHANGED")
    If (p("SessionScope")'=2)||(p("UserCookieScope")'=2)||p("GroupById")||'p("CSPZENEnabled") Throw ##class(%Exception.General).%New("WEB_SESSION_CHANGED")
    Set sc=0,exists=##class(Security.Applications).Exists(s.defaultApplication,,.sc)
    If exists {
        $$$ThrowOnError(sc)
        Kill p Set sc=##class(Security.Applications).Get(s.defaultApplication,.p) $$$ThrowOnError(sc)
        If (p("NameSpace")'=s.namespace)||p("Enabled") Throw ##class(%Exception.General).%New("DEFAULT_ROUTE_NOT_CLOSED")
    } Else {
        If $System.Status.IsOK(sc)||($System.Status.GetErrorCodes(sc)'="869") Throw ##class(%Exception.General).%New("DEFAULT_ROUTE_LOOKUP_FAILED")
    }
}

ClassMethod BindWeb(s As %DynamicObject) As %String [ Private ]
{
    New $Namespace
    If ##class(%SYS.Namespace).GetGlobalDest(s.namespace,"ChronosWeb")'=("^"_s.root_"/db/") Throw ##class(%Exception.General).%New("WEB_MAPPING_CHANGED")
    Set $Namespace=s.namespace
    Set web=##class(%DynamicObject).%FromJSON($Get(^ChronosWeb("config")))
    If (web.origin'=s.origin)||(web.application'=s.application)||($Length(web.installationId)'=64)||($Translate(web.installationId,"0123456789abcdef")'="") Throw ##class(%Exception.General).%New("WEB_BINDING_CHANGED")
    Return web.installationId
}

ClassMethod Run(action As %String, id As %String, origin As %String, application As %String, digest As %String, profileHash As %String, requestId As %String) As %String
{
    Set locked=0
    Set r={"schema_version":"chronos.native-web.v1","status":"REJECTED","ready":false,"deployment_id":(id),"profile_sha256":(profileHash),"request_id":(requestId),"web_enabled":null,"policy_verified":null,"identity_prepared":null,"native_ready":null,"mutation_requested":null,"request_state":"UNKNOWN","login_tested":false}
    If ($Namespace'="%SYS")||$TLevel||$Data(%request)||$Data(%session)||($Username'="irisowner") Return r.%ToJSON()
    If $ZVersion'["2026.3.0AI (Build 154U)" Return r.%ToJSON()
    If '$ListFind($ListBuild("enable","disable","status"),action) Return r.%ToJSON()
    For value=digest,profileHash { If ($Length(value)'=64)||($Translate(value,"0123456789abcdef")'="") Return r.%ToJSON() }
    If ($Length(requestId)'=32)||($Translate(requestId,"0123456789abcdef")'="") Return r.%ToJSON()
    Try {
        Set s=##class(Chronos.Deployment.NativeInstall).Spec(id,origin,application)
        If ($Get(^ChronosInstall(id,"state"))'="NATIVE_INSTALLED_DISABLED")||($Get(^ChronosInstall(id,"bundle"))'=digest)||($Get(^ChronosInstall(id,"spec"))'=s.%ToJSON())||'$Get(^ChronosInstall(id,"createdApplication")) Throw ##class(%Exception.General).%New("INSTALLATION_NOT_BOUND")
        If action'="status" {
            If $System.Util.GetEnviron("CHRONOS_WEB_AUTHORIZED")'=(action_":"_id_":"_digest_":"_profileHash_":"_requestId) Throw ##class(%Exception.General).%New("EXPLICIT_ACTION_AUTHORIZATION_REQUIRED")
        }
        // A nonblocking shared installer lock serializes this helper's snapshots/actions.
        Lock +^ChronosInstallLock:0
        If '$Test Set r.status="BUSY" Throw ##class(%Exception.General).%New("WEB_BUSY")
        Set locked=1,installation=..BindWeb(s)
        Do ..Owned(s,.enabled)
        Do r.%Set("web_enabled",enabled,"boolean")
        Set prior=$Get(^ChronosInstall(id,"webRequest",requestId)),existing=0
        If prior'="" {
            Set item=##class(%DynamicObject).%FromJSON(prior)
            If (item.bundle'=digest)||(item.profileSha256'=profileHash)||(item.installationId'=installation)||'$ListFind($ListBuild("enable","disable"),item.action)||'$ListFind($ListBuild("REQUESTED","VERIFIED"),item.state) Throw ##class(%Exception.General).%New("REQUEST_BINDING_CHANGED")
            If (action'="status")&&(item.action'=action) Throw ##class(%Exception.General).%New("REQUEST_ACTION_CHANGED")
            Set existing=1 Do r.%Set("request_state",item.state)
            Do r.%Set("mutation_requested",1,"boolean")
        } Else { Do r.%Set("request_state","ABSENT"),r.%Set("mutation_requested",0,"boolean") }
        // Closing access never depends on model health or role-policy availability.
        If action'="disable" {
            Do ..Policy(s,.prepared)
            Do r.%Set("policy_verified",1,"boolean"),r.%Set("identity_prepared",prepared,"boolean")
            Set provider=##class(%DynamicObject).%FromJSON(##class(Chronos.Deployment.NativeProvider).Run("status",id,origin,application,digest,profileHash))
            Set nativeReady=(provider.status="RUNNING_NATIVE_ONLY")&&provider.%Get("runtime_ready")
            Do r.%Set("native_ready",nativeReady,"boolean")
            If action="enable",('prepared||'nativeReady) Set r.status="ENABLE_PREREQUISITES_NOT_MET" Throw ##class(%Exception.General).%New("ENABLE_PREREQUISITES_NOT_MET")
        }
        If (action'="status")&&'existing {
            // Recheck ownership and access policy immediately before opening.
            If action="enable" { Do ..Policy(s,.prepared) If 'prepared Throw ##class(%Exception.General).%New("IDENTITY_CHANGED") }
            Do ..Owned(s,.enabled)
            Set wanted=(action="enable")
            Set item={"bundle":(digest),"profileSha256":(profileHash),"installationId":(installation),"action":(action),"state":"REQUESTED","previousEnabled":(enabled)}
            // Persist BEFORE any native mutation. Reuse of this request never repeats it.
            Set ^ChronosInstall(id,"webRequest",requestId)=item.%ToJSON()
            Do r.%Set("mutation_requested",1,"boolean")
            Do r.%Set("request_state","REQUESTED")
            If enabled'=wanted {
                Kill change Set change("Enabled")=wanted
                Set sc=##class(Security.Applications).Modify(s.webPath,.change) $$$ThrowOnError(sc)
            }
            Do ..Owned(s,.enabled)
            If enabled'=wanted Throw ##class(%Exception.General).%New("WEB_READBACK_CHANGED")
            If action="enable" { Do ..Policy(s,.prepared) If 'prepared Throw ##class(%Exception.General).%New("IDENTITY_CHANGED") }
            Set item.state="VERIFIED",^ChronosInstall(id,"webRequest",requestId)=item.%ToJSON()
            Do r.%Set("request_state","VERIFIED")
        }
        Do ..Owned(s,.enabled)
        Do r.%Set("web_enabled",enabled,"boolean")
        Set r.status=$Select(enabled:"WEB_ENABLED_LOGIN_UNVERIFIED",1:"WEB_DISABLED")
        If existing {
            // Current state is observable; it does not rewrite the original outcome.
            If item.state="REQUESTED" {
                Set r.status="REQUEST_UNCERTAIN_USE_STATUS"
            } ElseIf enabled'=(item.action="enable") {
                Set r.status="STATE_CHANGED_SINCE_REQUEST"
            }
        }
    } Catch ex {
        If '$ListFind($ListBuild("BUSY","ENABLE_PREREQUISITES_NOT_MET"),r.status) {
            Set r.status="REJECTED_STATE_PRESERVED"
            // Any failed observation may precede or follow a native change.
            Do r.%Set("mutation_requested","","null"),r.%Set("request_state","UNKNOWN")
            Do r.%Set("web_enabled","","null")
        }
        Set user=""
    }
    If locked Lock -^ChronosInstallLock
    Return r.%ToJSON()
}
}
