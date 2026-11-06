Include %occStatus

/// Native CSP identity only. Never accept actor/roles/session IDs from JSON.
/// HTTP deployment/CSRF and disabled-account behavior still require live tests.
Class Chronos.Approval.Identity Extends %RegisteredObject
{
ClassMethod Digest(value As %String) As %String [ Private ]
{
    Return $ZConvert(##class(%xsd.hexBinary).LogicalToXSD($System.Encryption.SHAHash(256,value)),"L")
}

ClassMethod Current(permission As %String, Output result As %DynamicObject) As %Status
{
    Set result={"authenticated":false,"code":"NOT_AUTHENTICATED"}
    If (permission'="READ")&&(permission'="APPROVE") Return $$$ERROR($$$GeneralError,"INVALID_PERMISSION")
    If '$Data(%session)||'$Data(%request) Return $$$OK
    If '$IsObject(%session)||'$IsObject(%request) Return $$$OK
    Try {
        If '%session.%IsA("%CSP.Session")||'%request.%IsA("%CSP.Request") Return $$$OK
        Set user=$Username
        If (user="")||($ZConvert(user,"L")="unknownuser")||(%session.Username'=user)||%session.EndSession Return $$$OK
        // Query the current user's roles again. Do not check a BO/service user
        // on behalf of a browser, nor silently add Admin_Secure to do so.
        If '$System.Security.CheckUserPermission(user,"Chronos_Read","USE") {
            Set result.code="PERMISSION_DENIED"
            Return $$$OK
        }
        If permission="APPROVE",'$System.Security.CheckUserPermission(user,"Chronos_Approve","USE") {
            Set result.code="PERMISSION_DENIED"
            Return $$$OK
        }
        If (%session.Get("ChronosOwner","")'=user)||(%session.Get("ChronosBinding","")="") {
            Set %session.Data("ChronosOwner")=user
            Set %session.Data("ChronosBinding")=$System.Util.CreateGUID()
        }
        // An application nonce, not the native session ID/cookie or a login token.
        Set actor="principal-"_..Digest($ListBuild($Namespace,user))
        Set binding="session-"_..Digest($ListBuild($Namespace,user,%session.Get("ChronosBinding")))
        Set result={"authenticated":true,"code":"IDENTITY_CONFIRMED","actor":(actor),"sessionBinding":(binding)}
    } Catch ex {
        Set result={"authenticated":false,"code":"IDENTITY_UNAVAILABLE"}
    }
    Return $$$OK
}
}
