Include %occStatus

/// Fixed application assets only. IRIS authenticates the enclosing CSP app.
/// Does not grant READ/APPROVE; the shell must remain usable after data revocation.
Class Chronos.Web.Assets Extends %RegisteredObject
{
ClassMethod Mime(name As %String) As %String
{
    If name="index.html" Return "text/html"
    If name="screen.css" Return "text/css"
    Set scripts=$ListBuild("boot.mjs","client.mjs","consent-controller.mjs","consent-panel.mjs","consent.mjs","controller.mjs","conversation-controller.mjs","conversation-panel.mjs","conversation-v2.mjs","detail.mjs","preparation-references.mjs","presentation.mjs","references.mjs","render.mjs","screen.mjs","session-references.mjs")
    If $ListFind(scripts,name) Return "text/javascript"
    Return ""
}

ClassMethod Read(name As %String, Output body As %String, Output mime As %String) As %Status
{
    Set body="",mime=..Mime(name)
    If mime="" Return $$$ERROR($$$GeneralError,"ASSET_NOT_FOUND")
    Try {
        Set stream=##class(%Stream.FileCharacter).%New()
        Set stream.TranslateTable="UTF8"
        Set sc=stream.LinkToFile("/opt/chronos/src/chronos_web/"_name)
        $$$ThrowOnError(sc)
        While 'stream.AtEnd {
            Set length=32000,chunk=stream.Read(.length,.sc)
            $$$ThrowOnError(sc)
            If (chunk="")&&'stream.AtEnd Throw ##class(%Exception.General).%New("ASSET_READ_STALLED")
            Set body=body_chunk
            If $Length(body)>262144 Throw ##class(%Exception.General).%New("ASSET_TOO_LARGE")
        }
        If body="" Throw ##class(%Exception.General).%New("ASSET_EMPTY")
    } Catch ex {
        Set body="",mime=""
        Return $$$ERROR($$$GeneralError,"ASSET_UNAVAILABLE")
    }
    Return $$$OK
}

ClassMethod Serve(name As %String) As %Status
{
    Set %response.ContentType="text/plain",%response.CharSet="utf-8"
    Do %response.SetHeader("Cache-Control","no-store")
    Do %response.SetHeader("X-Content-Type-Options","nosniff")
    Do %response.SetHeader("Referrer-Policy","no-referrer")
    Do %response.SetHeader("Content-Security-Policy","default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
    Try {
        Set config=##class(%DynamicObject).%FromJSON($Get(^ChronosWeb("config"),"{}"))
        If (config.%GetTypeOf("origin")'="string")||(config.%GetTypeOf("application")'="string") Throw ##class(%Exception.General).%New("CONFIG")
        If '##class(Chronos.Web.NativePolicy).ValidOrigin(config.origin) Throw ##class(%Exception.General).%New("ORIGIN")
        Set appMatcher=##class(%Regex.Matcher).%New("\A/(?:[A-Za-z0-9_-]+/)*[A-Za-z0-9_-]+/\z"),appMatcher.Text=config.application,appMatcher.OperationLimit=10000
        If ($Length(config.application)>256)||'appMatcher.Locate() Throw ##class(%Exception.General).%New("APPLICATION_CONFIG")
        If (%request.Application'=config.application)||(%request.GetCgiEnv("QUERY_STRING")'="") Throw ##class(%Exception.General).%New("APPLICATION")
        If (%request.GetCgiEnv("HTTP_HOST")'=$Piece(config.origin,"://",2))||(%request.Secure'=($Extract(config.origin,1,8)="https://")) Throw ##class(%Exception.General).%New("HOST")
        If ..Mime(name)="" {
            Set %response.Status="404 Not Found"
            Write "Not found."
            Return $$$OK
        }
        Set sc=..Read(name,.body,.mime)
        $$$ThrowOnError(sc)
        If name="index.html" {
            // The packaged screen is bound to one installation, never to Host.
            Set q=$Char(34),key="name="_q_"chronos-api-base"_q
            Set marker="<meta "_key_" content="_q_config.application_q_">"
            Set noSlash="<meta "_key_" content="_q_$Extract(config.application,1,*-1)_q_">"
            If ($Length(body,key)'=2)||(($Length(body,marker)'=2)&&($Length(body,noSlash)'=2)) Throw ##class(%Exception.General).%New("SCREEN_ROUTE_MISMATCH")
        }
        Set %response.Status="200 OK",%response.ContentType=mime
        Write body
    } Catch ex {
        Set %response.Status="503 Service Unavailable"
        Write "Chronos interface unavailable."
    }
    Return $$$OK
}
}
