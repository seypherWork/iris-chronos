Include %occStatus

/// Source only until explicitly installed in an isolated authenticated webapp.
/// IRIS performs login. No passwords, cookies or grants enter workflow messages.
Class Chronos.Web.API Extends %CSP.REST
{
Parameter UseSession = 1;
Parameter HandleCorsRequest = 0;

XData UrlMap
{
<Routes>
  <Route Url="/session" Method="GET" Call="Session" />
  <Route Url="/approval" Method="POST" Call="Approval" />
  <Route Url="/decision" Method="POST" Call="Decision" />
  <Route Url="/conversation" Method="POST" Call="Conversation" />
  <Route Url="/logout" Method="POST" Call="Logout" />
  <Route Url="/" Method="GET" Call="Index" />
  <Route Url="/:asset" Method="GET" Call="Asset" />
</Routes>
}

ClassMethod Index() As %Status
{
    Return ##class(Chronos.Web.Assets).Serve("index.html")
}

ClassMethod Asset(asset As %String) As %Status
{
    Return ##class(Chronos.Web.Assets).Serve(asset)
}

ClassMethod Reply(result As %DynamicObject, status As %String = "200 OK") As %Status [ Private ]
{
    Set %response.Status=status,%response.ContentType="application/json",%response.CharSet="utf-8"
    Do %response.SetHeader("Cache-Control","no-store")
    Do %response.SetHeader("Pragma","no-cache")
    Do %response.SetHeader("X-Content-Type-Options","nosniff")
    Do %response.SetHeader("Referrer-Policy","no-referrer")
    Write result.%ToJSON()
    Return $$$OK
}

/// Expected values are fixed installation config and the current CSP session.
/// Never derive the expected origin from Host/Forwarded or a request body.
ClassMethod Context(Output principal As %DynamicObject, Output origin As %String, Output csrf As %String, Output code As %String, ending As %Boolean = 0, sessionOnly As %Boolean = 0) As %Status [ Private ]
{
    Set principal={},origin="",csrf="",code="SESSION_UNAVAILABLE"
    Try {
        If '$Data(%request)||'$Data(%session) Return $$$OK
        If '$IsObject(%request)||'$IsObject(%session) Return $$$OK
        If '%request.%IsA("%CSP.Request")||'%session.%IsA("%CSP.Session") Return $$$OK
        If %request.GetCgiEnv("QUERY_STRING")'="" Set code="INVALID_REQUEST" Return $$$OK
        If '%session.EventClassExists("Chronos.Web.Events",$Namespace) Return $$$OK
        Set config=##class(%DynamicObject).%FromJSON($Get(^ChronosWeb("config"),"{}"))
        If (config.%GetTypeOf("origin")'="string")||(config.%GetTypeOf("application")'="string") Set code="WEB_NOT_CONFIGURED" Return $$$OK
        Set origin=config.origin
        If (%request.Application'=config.application)||(origin="") Set code="WRONG_APPLICATION" Return $$$OK
        // Checking Host against fixed configuration also rejects DNS rebinding.
        Set authority=$Piece(origin,"://",2),secure=($Extract(origin,1,8)="https://")
        If (%request.GetCgiEnv("HTTP_HOST")'=authority)||(%request.Secure'=secure) Set code="WRONG_ORIGIN" Return $$$OK
        If ending {
            // Revocation of application READ must not prevent ending an already
            // authenticated session. Reuse its existing token; create no consent.
            If '..CanEnd($Username,%session.Username,%session.EndSession,%session.Get("ChronosOwner"),%session.Get("ChronosBinding"),%session.Get("ChronosCSRFBinding"),%session.Get("ChronosCSRF")) Return $$$OK
            Set csrf=%session.Get("ChronosCSRF"),code="OK"
            Return $$$OK
        }
        If sessionOnly {
            // Bootstrap an authenticated session even after READ was revoked.
            // IRIS may invoke OnLogin after a role change and clear the old
            // token. Issuing a new logout token must not restore READ/APPROVE.
            Set user=$Username
            If (user="")||($ZConvert(user,"L")="unknownuser")||(%session.Username'=user)||%session.EndSession Return $$$OK
            If (%session.Get("ChronosOwner")'=user)||(%session.Get("ChronosBinding")="") {
                Set %session.Data("ChronosOwner")=user,%session.Data("ChronosBinding")=$System.Util.CreateGUID()
            }
            Set binding="session-"_$ZConvert(##class(%xsd.hexBinary).LogicalToXSD($System.Encryption.SHAHash(256,$ListBuild($Namespace,user,%session.Get("ChronosBinding")))),"L")
            Set actor="principal-"_$ZConvert(##class(%xsd.hexBinary).LogicalToXSD($System.Encryption.SHAHash(256,$ListBuild($Namespace,user))),"L")
            Set principal={"authenticated":true,"actor":(actor),"sessionBinding":(binding)}
        } Else {
            Set sc=##class(Chronos.Approval.Identity).Current("READ",.principal)
            If $$$ISERR(sc)||'principal.%Get("authenticated") Set code="PERMISSION_DENIED" Return $$$OK
        }
        If (%session.Get("ChronosCSRFBinding")'=principal.sessionBinding)||(%session.Get("ChronosCSRF")="") {
            Set token=$ZConvert($System.Encryption.ToHex($System.Encryption.GenCryptRand(32,1)),"L")
            If $Length(token)'=64 Return $$$OK
            Set %session.Data("ChronosCSRF")=token,%session.Data("ChronosCSRFBinding")=principal.sessionBinding
        }
        Set csrf=%session.Get("ChronosCSRF"),code="OK"
    } Catch ex {
        Set principal={},origin="",csrf="",code="SESSION_UNAVAILABLE"
    }
    Return $$$OK
}

/// Pure consistency check for server session state, not authentication itself.
/// The caller above obtains every value from IRIS, never from request fields.
ClassMethod CanEnd(user As %String, sessionUser As %String, ended As %Boolean, owner As %String, binding As %String, csrfBinding As %String, csrf As %String) As %Boolean
{
    If ended||(user="")||($ZConvert(user,"L")="unknownuser")||(sessionUser'=user)||(owner'=user)||(binding="") Return 0
    If ($Length(csrf)'=64)||($Translate(csrf,"0123456789abcdef")'="") Return 0
    Set expected="session-"_$ZConvert(##class(%xsd.hexBinary).LogicalToXSD($System.Encryption.SHAHash(256,$ListBuild($Namespace,user,binding))),"L")
    Return csrfBinding=expected
}

/// Read at most 4097 stream units; JSON's permitted command/IDs are ASCII.
/// Gateway request-size settings must additionally bound pre-application input.
ClassMethod Body(Output body As %String, Output code As %String) As %Status
{
    Set body="",code="INVALID_REQUEST"
    Try {
        If '$Data(%request)||'$IsObject(%request) Return $$$OK
        If '$IsObject(%request.Content) Return $$$OK
        Do %request.Content.Rewind()
        Set body=%request.Content.Read(4097)
        If ($Length(body)>4096)||'%request.Content.AtEnd Set body="",code="REQUEST_TOO_LARGE" Return $$$OK
        Set code="OK"
    } Catch ex {
        Set body="",code="INVALID_REQUEST"
    }
    Return $$$OK
}

ClassMethod Validate(body As %String, origin As %String, csrf As %String, Output checked As %DynamicObject, family As %String = "approval") As %Status [ Private ]
{
    Try {
        Set checked=##class(%DynamicObject).%FromJSON(##class(Chronos.Web.NativePolicy).Validate(%request.Method,%request.GetCgiEnv("CONTENT_TYPE"),%request.GetCgiEnv("HTTP_CONTENT_ENCODING"),%request.GetCgiEnv("HTTP_ORIGIN"),%request.GetCgiEnv("HTTP_SEC_FETCH_SITE"),%request.GetCgiEnv("HTTP_X_CHRONOS_CSRF"),origin,csrf,body,family))
    } Catch ex {
        Set checked={"allowed":false,"code":"INVALID_REQUEST"}
    }
    Return $$$OK
}

/// Non-secret recovery discriminator, never authority or a login credential.
/// Inputs must be obtained from native identity and fixed installer config.
/// Missing/legacy installation config disables recovery; it is never repaired
/// or generated by an HTTP request. A cloned DB must rotate installationId.
ClassMethod PublicIdentity(reader As %DynamicObject, binding As %String, config As %DynamicObject) As %DynamicObject
{
    Set unavailable={"version":1,"available":false}
    Try {
        If '$IsObject(reader)||'$IsObject(config) Return unavailable
        If 'reader.%IsA("%DynamicObject")||'config.%IsA("%DynamicObject") Return unavailable
        If (reader.%GetTypeOf("authenticated")'="boolean")||'reader.%Get("authenticated") Return unavailable
        If (reader.%Get("code")'="IDENTITY_CONFIRMED")||(reader.%Get("sessionBinding")'=binding) Return unavailable
        Set actor=reader.%Get("actor"),installation=config.%Get("installationId")
        If ($Extract(binding,1,8)'="session-")||'..Hex64($Extract(binding,9,*)) Return unavailable
        If (reader.%GetTypeOf("actor")'="string")||($Extract(actor,1,10)'="principal-")||'..Hex64($Extract(actor,11,*)) Return unavailable
        If (config.%GetTypeOf("installationId")'="string")||'..Hex64(installation) Return unavailable
        If (config.%GetTypeOf("origin")'="string")||(config.%GetTypeOf("application")'="string") Return unavailable
        If (config.origin="")||(config.application="") Return unavailable
        Set scope=$ZConvert(##class(%xsd.hexBinary).LogicalToXSD($System.Encryption.SHAHash(256,$ListBuild("chronos-recovery-v1",$Namespace,installation,config.origin,config.application,actor))),"L")
        Return {"version":1,"available":true,"actor":(actor),"actorScope":(scope),"applicationUrl":(config.origin_config.application)}
    } Catch ex {
        Return unavailable
    }
}

ClassMethod Hex64(value As %String) As %Boolean [ Private ]
{
    Return ($Length(value)=64)&&($Translate(value,"0123456789abcdef")="")
}

ClassMethod Session() As %Status
{
    Do ..Context(.principal,.origin,.csrf,.code,0,1)
    If code'="OK" Return ..Reply({"code":(code)},"403 Forbidden")
    Set suppliedOrigin=%request.GetCgiEnv("HTTP_ORIGIN"),site=%request.GetCgiEnv("HTTP_SEC_FETCH_SITE")
    If (suppliedOrigin'="")&&(suppliedOrigin'=origin) Return ..Reply({"code":"CROSS_SITE_REQUEST"},"403 Forbidden")
    If (site'="")&&(site'="same-origin")&&(site'="none") Return ..Reply({"code":"CROSS_SITE_REQUEST"},"403 Forbidden")
    Set sc=##class(Chronos.Approval.Identity).Current("READ",.reader)
    Set canRead=$$$ISOK(sc)&&reader.%Get("authenticated")
    Set sc=##class(Chronos.Approval.Identity).Current("APPROVE",.approver)
    Set canApprove=$$$ISOK(sc)&&approver.%Get("authenticated")
    // Do not combine two users/bindings if identity changed during bootstrap.
    If '..CanEnd($Username,%session.Username,%session.EndSession,%session.Get("ChronosOwner"),%session.Get("ChronosBinding"),%session.Get("ChronosCSRFBinding"),csrf) Return ..Reply({"code":"SESSION_UNAVAILABLE"},"403 Forbidden")
    If canRead {
        If (reader.%Get("sessionBinding")'=principal.sessionBinding)||(reader.%Get("actor")'=principal.actor) Return ..Reply({"code":"SESSION_UNAVAILABLE"},"403 Forbidden")
    }
    If canApprove {
        If 'canRead Return ..Reply({"code":"SESSION_UNAVAILABLE"},"403 Forbidden")
        If (approver.%Get("actor")'=principal.actor)||(approver.%Get("sessionBinding")'=principal.sessionBinding) Return ..Reply({"code":"SESSION_UNAVAILABLE"},"403 Forbidden")
    }
    Set identity={"version":1,"available":false}
    If canRead {
        Try {
            Set config=##class(%DynamicObject).%FromJSON($Get(^ChronosWeb("config"),"{}"))
            If (config.%Get("origin")'=origin)||(config.%Get("application")'=%request.Application) Return ..Reply({"code":"WEB_CONFIG_CHANGED"},"403 Forbidden")
            Set identity=..PublicIdentity(reader,principal.sessionBinding,config)
        } Catch ex {
            // Authenticated reads/logout remain possible on a legacy config.
            Set identity={"version":1,"available":false}
        }
    }
    Set result={"code":($Select(canRead:"CONNECTED",1:"ACCESS_REVOKED")),"authenticated":true,"csrf":(csrf),"identity":(identity)}
    Do result.%Set("canRead",canRead,"boolean")
    Do result.%Set("canApprove",canApprove,"boolean")
    Set canConverse=0
    If canRead {
        Set chatStatus=##class(Chronos.Conversation.Context).Principal(.chatIdentity)
        If $$$ISOK(chatStatus) {
            Set canConverse=(chatIdentity.actor=principal.actor)&&(chatIdentity.sessionBinding=principal.sessionBinding)&&##class(Chronos.Conversation.Model).Available()
        }
    }
    Do result.%Set("canConverse",canConverse,"boolean")
    If '..CanEnd($Username,%session.Username,%session.EndSession,%session.Get("ChronosOwner"),%session.Get("ChronosBinding"),%session.Get("ChronosCSRFBinding"),csrf) Return ..Reply({"code":"SESSION_UNAVAILABLE"},"403 Forbidden")
    Return ..Reply(result)
}

ClassMethod Approval() As %Status
{
    Do ..Context(.principal,.origin,.csrf,.code)
    If code'="OK" Return ..Reply({"code":(code)},"403 Forbidden")
    Do ..Body(.body,.code)
    If code'="OK" Return ..Reply({"code":(code)},$Select(code="REQUEST_TOO_LARGE":"413 Payload Too Large",1:"400 Bad Request"))
    Do ..Validate(body,origin,csrf,.checked)
    If 'checked.allowed Return ..Reply({"code":(checked.code)},"400 Bad Request")
    // Use only the normalized policy output. The original body is never parsed
    // again or sent to an Interoperability host.
    Set id=checked.args.%Get(##class(Chronos.Approval.Entry).IdentifierField(checked.command))
    Set correlation=$Select(##class(Chronos.Approval.Entry).NeedsCorrelation(checked.command):checked.args.%Get("requestId"),1:"")
    Set sc=##class(Chronos.Approval.Entry).Call(checked.command,id,.result,correlation)
    If $$$ISERR(sc) Return ..Reply({"code":"APPROVAL_RESULT_UNAVAILABLE","readbackRequired":true},"503 Service Unavailable")
    Return ..Reply(result)
}

/// Laboratory READ is namespace-wide. This is not a per-owner decision inbox.
ClassMethod Decision() As %Status
{
    Do ..Context(.principal,.origin,.csrf,.code)
    If code'="OK" Return ..Reply({"code":(code)},"403 Forbidden")
    Do ..Body(.body,.code)
    If code'="OK" Return ..Reply({"code":(code)},$Select(code="REQUEST_TOO_LARGE":"413 Payload Too Large",1:"400 Bad Request"))
    Do ..Validate(body,origin,csrf,.checked,"decision")
    If 'checked.allowed Return ..Reply({"code":(checked.code)},"400 Bad Request")
    Set sc=##class(Chronos.Approval.Entry).Call(checked.command,checked.args.decisionId,.result)
    If $$$ISERR(sc) Return ..Reply({"code":"DECISION_RESULT_UNAVAILABLE","readbackRequired":true},"503 Service Unavailable")
    Return ..Reply(result)
}

ClassMethod Logout() As %Status
{
    Do ..Context(.principal,.origin,.csrf,.code,1)
    If code'="OK" Return ..Reply({"code":(code)},"403 Forbidden")
    Do ..Body(.body,.code)
    If (code'="OK")||($Translate(body,$Char(9,10,13,32))'="{}") Return ..Reply({"code":"INVALID_REQUEST"},"400 Bad Request")
    // The logout body is exactly an empty object. Reuse the header/session
    // policy with an internal constant; this never invokes the controller.
    Do ..Validate({"command":"READ","id":"session"}.%ToJSON(),origin,csrf,.checked)
    If 'checked.allowed Return ..Reply({"code":(checked.code)},"400 Bad Request")
    Try {
        Do ##class(Chronos.Web.Events).Clear()
        Set %session.EndSession=1
        Do %session.Logout(1)
    } Catch ex {
        Return ..Reply({"code":"SESSION_END_REQUIRED"},"503 Service Unavailable")
    }
    Return ..Reply({"code":"SESSION_ENDED"})
}

/// New RECORD may invoke one internal C1 inference; READ/replay never retry it.
/// Does not forward raw body, scope, actor or session credentials to the ledger.
ClassMethod Conversation() As %Status
{
    Do ..Context(.principal,.origin,.csrf,.code)
    If code'="OK" Return ..Reply({"code":(code)},"403 Forbidden")
    // Reuse the existing fixed-origin/header policy with a constant harmless
    // shape. This validates headers only; no approval controller is invoked.
    Do ..Validate({"command":"READ","id":"conversation"}.%ToJSON(),origin,csrf,.headers)
    If 'headers.allowed Return ..Reply({"code":(headers.code)},"400 Bad Request")
    Set sc=##class(Chronos.Conversation.Context).Principal(.current)
    If $$$ISERR(sc) Return ..Reply({"code":"CONVERSATION_CAPABILITY_UNAVAILABLE"},"403 Forbidden")
    If (current.actor'=principal.actor)||(current.sessionBinding'=principal.sessionBinding) Return ..Reply({"code":"SESSION_UNAVAILABLE"},"403 Forbidden")
    Set body=""
    Try {
        // Default CSP input is binary. Fail closed if a subclass changes that
        // contract; do not double-decode or alter the existing ASCII routes.
        If ..#CONVERTINPUTSTREAM'=0 Return ..Reply({"code":"INPUT_STREAM_POLICY_CHANGED"},"503 Service Unavailable")
        If '$IsObject(%request.Content) Return ..Reply({"code":"INVALID_REQUEST"},"400 Bad Request")
        Do %request.Content.Rewind()
        Set body=%request.Content.Read(16385)
        If ($Length(body)>16384)||'%request.Content.AtEnd Return ..Reply({"code":"REQUEST_TOO_LARGE"},"413 Payload Too Large")
        Set config=##class(%DynamicObject).%FromJSON($Get(^ChronosRuntime("config"),"{}"))
        Set sc=##class(Chronos.Agent.Python).ConversationModule(config.pythonRoot,.module) $$$ThrowOnError(sc)
        // Hex is only an internal byte-preserving bridge, never a log or output.
        Set bodyHex=$System.Encryption.ToHex(body)
        Set checked=##class(%DynamicObject).%FromJSON(##class(Chronos.Conversation.Python).Request(module,$Namespace,bodyHex))
    } Catch ex {
        Return ..Reply({"code":"CONVERSATION_REQUEST_UNAVAILABLE"},"400 Bad Request")
    }
    If 'checked.allowed Return ..Reply({"code":(checked.code)},$Select(checked.code="REQUEST_TOO_LARGE":"413 Payload Too Large",1:"400 Bad Request"))
    Set sc=##class(Chronos.Conversation.Context).SamePrincipal(principal)
    If $$$ISERR(sc) Return ..Reply({"code":"SESSION_UNAVAILABLE"},"403 Forbidden")
    Set sc=##class(Chronos.Conversation.Controller).Handle(checked.command,checked.args,.result)
    If $$$ISERR(sc) {
        Set readback=checked.command'="READ"
        Set denied={"code":"CONVERSATION_UNAVAILABLE"}
        Do denied.%Set("readbackRequired",readback,"boolean")
        Return ..Reply(denied,"503 Service Unavailable")
    }
    Return ..Reply(result)
}
}
