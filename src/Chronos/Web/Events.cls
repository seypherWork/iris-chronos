Include %occStatus

/// Must be configured as this application's native CSP session event class.
/// These callbacks invalidate application consent/CSRF state, never native roles.
Class Chronos.Web.Events Extends %CSP.SessionEvents
{
ClassMethod Clear()
{
    If '$Data(%session) Quit
    If '$IsObject(%session) Quit
    If '%session.%IsA("%CSP.Session") Quit
    Kill %session.Data("ChronosOwner"),%session.Data("ChronosBinding")
    Kill %session.Data("ChronosCSRF"),%session.Data("ChronosCSRFBinding")
}

ClassMethod OnStartSession()
{
    Do ..Clear()
}

ClassMethod OnLogin() As %Status
{
    Do ..Clear()
    Return $$$OK
}

ClassMethod OnLogout() As %Status
{
    Do ..Clear()
    If $Data(%session),$IsObject(%session) Set %session.EndSession=1
    Return $$$OK
}

ClassMethod OnApplicationChange(oldapp As %String, newapp As %String) As %Status
{
    If oldapp'=newapp Do ..Clear()
    Return $$$OK
}

ClassMethod OnTimeout()
{
    Do ..Clear()
}

ClassMethod OnEndSession()
{
    Do ..Clear()
}
}
