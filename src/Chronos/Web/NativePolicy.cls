Include %occStatus

/// Native web validation: no %Service_EmbeddedPython grant for web identities.
/// Accepts exact command/id objects, plus requestId only for correlated commands,
/// with duplicate detection before materialization. Origin/token are server state.
Class Chronos.Web.NativePolicy Extends %RegisteredObject
{
ClassMethod Deny(code As %String) As %String [ Private ]
{
    Return {"allowed":false,"code":(code)}.%ToJSON()
}

ClassMethod Matches(pattern As %String, value As %String) As %Boolean [ Private ]
{
    Set m=##class(%Regex.Matcher).%New(pattern),m.Text=value,m.OperationLimit=10000
    Return m.Locate()
}

/// Public pure validator shared by the authenticated API and fixed asset server.
/// Does not authenticate a request or grant application permissions.
ClassMethod ValidOrigin(value As %String) As %Boolean
{
    Return ..Origin(value)
}

ClassMethod Origin(value As %String) As %Boolean [ Private ]
{
    If ($Length(value)>256)||(value="") Return 0
    // Deliberately supports DNS/IPv4 and IPv6 loopback only. Other literal IPv6
    // deployment addresses are rejected rather than normalized ambiguously.
    Set m=##class(%Regex.Matcher).%New("\A(https?)://([a-z0-9.-]+|\[::1\])(?::([1-9][0-9]{0,4}))?\z"),m.Text=value,m.OperationLimit=10000
    If 'm.Locate() Return 0
    Set scheme=m.Group(1),host=m.Group(2),port=m.Group(3)
    If (port'="")&&((port>65535)||(port=$Select(scheme="https":443,1:80))) Return 0
    If scheme="http",(host'="localhost")&&(host'="127.0.0.1")&&(host'="[::1]") Return 0
    Return 1
}

ClassMethod Space(text As %String, ByRef cursor As %Integer) [ Private ]
{
    While (cursor<=$Length(text))&&($Char(9,10,13,32)[$Extract(text,cursor)) { Set cursor=cursor+1 }
}

/// A strict JSON string token. Return its quoted spelling, not decoded content.
ClassMethod StringToken(text As %String, ByRef cursor As %Integer, Output token As %String) As %Boolean [ Private ]
{
    Set token="",start=cursor
    If $Extract(text,cursor)'=$Char(34) Return 0
    Set cursor=cursor+1
    While cursor<=$Length(text) {
        Set ch=$Extract(text,cursor)
        If $ASCII(ch)<32 Return 0
        If ch=$Char(34) {
            Set token=$Extract(text,start,cursor),cursor=cursor+1
            Return 1
        }
        If ch=$Char(92) {
            Set cursor=cursor+1,ch=$Extract(text,cursor)
            If ch="" Return 0
            If ch="u" {
                Set hex=$Extract(text,cursor+1,cursor+4)
                If ($Length(hex)'=4)||($Translate(hex,"0123456789abcdefABCDEF")'="") Return 0
                Set cursor=cursor+4
            } ElseIf ($Char(34,92)_"/bfnrt")'[ch { Return 0 }
        }
        Set cursor=cursor+1
    }
    Return 0
}

ClassMethod Command(text As %String, Output command As %String, Output id As %String, family As %String, Output correlation As %String) As %Boolean [ Private ]
{
    Set command="",id="",correlation="",cursor=1,count=0
    Do ..Space(text,.cursor)
    If $Extract(text,cursor)'="{" Return 0
    Set cursor=cursor+1
    For {
        Do ..Space(text,.cursor)
        If '..StringToken(text,.cursor,.keyToken) Return 0
        Do ..Space(text,.cursor)
        If $Extract(text,cursor)'=":" Return 0
        Set cursor=cursor+1
        Do ..Space(text,.cursor)
        If '..StringToken(text,.cursor,.valueToken) Return 0
        // Materialize exactly one validated pair, never a duplicate-bearing
        // full object. Escaped names decode before duplicate/name checks.
        Set pair=##class(%DynamicObject).%FromJSON("{"_keyToken_":"_valueToken_"}")
        If pair.%Size()'=1 Return 0
        Set it=pair.%GetIterator()
        If 'it.%GetNext(.key,.value) Return 0
        If (key'="command")&&(key'="id")&&(key'="requestId") Return 0
        If pair.%GetTypeOf(key)'="string" Return 0
        If $Data(seen(key)) Return 0
        Set seen(key)=1,count=count+1
        If key="command" Set command=value
        If key="id" Set id=value
        If key="requestId" Set correlation=value
        Do ..Space(text,.cursor)
        Set ch=$Extract(text,cursor),cursor=cursor+1
        If ch="}" Quit
        If (ch'=",")||(count>=3) Return 0
    }
    Do ..Space(text,.cursor)
    If cursor'=($Length(text)+1) Return 0
    Set commands=$Select(family="decision":$ListBuild("DECISION","DECISION_DETAIL","DECISION_OPERATION","RESOLVE_DECISION"),1:$ListBuild("PREVIEW","READ","REJECT","CONFIRM","RECONCILE","READ_OPERATION","RECONCILE_OPERATION","PREVIEW_REQUEST","READ_PREPARATION","CLOSE_PREPARATION"))
    If '$ListFind(commands,command) Return 0
    Set correlated=##class(Chronos.Approval.Entry).NeedsCorrelation(command)
    If (count'=(2+correlated))||'$Data(seen("command"))||'$Data(seen("id")) Return 0
    If correlated {
        If '$Data(seen("requestId"))||'##class(Chronos.App.Entry).ValidID(correlation) Return 0
    } Else {
        If $Data(seen("requestId")) Return 0
    }
    Return ##class(Chronos.App.Entry).ValidID(id)
}

ClassMethod Validate(method As %String, contentType As %String, contentEncoding As %String, origin As %String, fetchSite As %String, csrf As %String, expectedOrigin As %String, expectedCSRF As %String, body As %String, family As %String = "approval") As %String
{
    Try {
        If (family'="approval")&&(family'="decision") Return ..Deny("SERVER_POLICY_UNAVAILABLE")
        If '..Origin(expectedOrigin) Return ..Deny("SERVER_POLICY_UNAVAILABLE")
        If ($Length(expectedCSRF)'=64)||($Translate(expectedCSRF,"0123456789abcdef")'="") Return ..Deny("SESSION_POLICY_UNAVAILABLE")
        If method'="POST" Return ..Deny("METHOD_NOT_ALLOWED")
        If (origin'=expectedOrigin)||((fetchSite'="")&&(fetchSite'="same-origin")) Return ..Deny("CROSS_SITE_REQUEST")
        If ($Length(csrf)'=64)||($Translate(csrf,"0123456789abcdef")'="") Return ..Deny("CSRF_REJECTED")
        // Compare all64 positions without a mismatch-dependent early return.
        Set difference=0
        For i=1:1:64 { Set difference=difference+($ASCII(csrf,i)'=$ASCII(expectedCSRF,i)) }
        If difference Return ..Deny("CSRF_REJECTED")
        If ($Length(contentType)>128)||'..Matches("\Aapplication/json(?:[ \t]*;[ \t]*charset=utf-8)?\z",$ZConvert(contentType,"L")) Return ..Deny("UNSUPPORTED_MEDIA_TYPE")
        If (contentEncoding'="")&&(contentEncoding'="identity") Return ..Deny("UNSUPPORTED_ENCODING")
        If ($Length(body)>4096)||($Length($ZConvert(body,"O","UTF8"))>4096) Return ..Deny("REQUEST_TOO_LARGE")
        If '..Command(body,.command,.id,family,.correlation) Return ..Deny("INVALID_REQUEST")
        Set field=##class(Chronos.Approval.Entry).IdentifierField(command),args={}
        Do args.%Set(field,id)
        If ##class(Chronos.Approval.Entry).NeedsCorrelation(command) Set args.requestId=correlation
        Return {"allowed":true,"code":"VALID_REQUEST","command":(command),"args":(args)}.%ToJSON()
    } Catch ex {
        Return ..Deny("INVALID_REQUEST")
    }
}
}
