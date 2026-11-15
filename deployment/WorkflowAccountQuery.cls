Include %occStatus

/// Compile ONLY in %SYS after verifying no foreign class is overwritten.
/// Internal selective query for an already privileged native worker. No route,
/// role escalation, writes, object-open or bulk Security.Users property getter.
Class %ZChronos.Workflow.AccountQuery Extends %RegisteredObject
{
/// Required by the native Security.SQLQuery generator. Keep the same explicit
/// resource as Security.Users; never use an empty resource to bypass its gate.
Parameter RESOURCEREQUIRED = "%Admin_Secure";

/// Public Security.SQLQuery API; exactly one parameter and three return fields.
/// Logical select mode preserves ExpirationDate as the documented $H date.
Query ReadOne(user As %String) As Security.SQLQuery(ROWSPEC = "Enabled:%Boolean,ExpirationDate:%Date,AccountNeverExpires:%Boolean", SELECTMODE = "LOGICAL")
{
SELECT Enabled,ExpirationDate,AccountNeverExpires
FROM Security.Users
WHERE Name=:user
}

ClassMethod ReadFlags(user As %String, Output result As %DynamicObject) As %Status
{
    Set result={"available":false,"code":"WORKFLOW_ACCOUNT_STATE_UNAVAILABLE"},rs=""
    Try {
        If $Namespace'="%SYS" Return $$$OK
        If '$System.Security.Check("%Admin_Secure","USE") Return $$$OK
        If '$System.Security.Check("%DB_IRISSYS","READ") Return $$$OK
        If ($Length(user)<1)||($Length(user)>128) Return $$$OK
        Set matcher=##class(%Regex.Matcher).%New("[\p{C}]"),matcher.Text=user,matcher.OperationLimit=10000
        If matcher.Locate() Return $$$OK
        Set rs=##class(%ResultSet).%New("%ZChronos.Workflow.AccountQuery:ReadOne"),rs.RuntimeMode=0
        Set sc=rs.Execute(user) $$$ThrowOnError(sc)
        If rs.GetColumnCount()'=3 Throw ##class(%Exception.General).%New("INVALID_ACCOUNT_QUERY_COLUMNS")
        If ($ZConvert(rs.GetColumnName(1),"U")'="ENABLED")||($ZConvert(rs.GetColumnName(2),"U")'="EXPIRATIONDATE")||($ZConvert(rs.GetColumnName(3),"U")'="ACCOUNTNEVEREXPIRES") Throw ##class(%Exception.General).%New("INVALID_ACCOUNT_QUERY_COLUMNS")
        Set next=rs.Next(.sc) $$$ThrowOnError(sc)
        If 'next Throw ##class(%Exception.General).%New("ACCOUNT_UNAVAILABLE")
        Set enabled=rs.GetData(1),date=rs.GetData(2),never=rs.GetData(3)
        If ((enabled'=0)&&(enabled'=1))||((never'=0)&&(never'=1)) Throw ##class(%Exception.General).%New("INVALID_ACCOUNT_FLAGS")
        If date'="" {
            If ($Translate(date,"0123456789")'="")||($Length(date)>7)||(date<0)||(date'=(date\1)) Throw ##class(%Exception.General).%New("INVALID_ACCOUNT_DATE")
        }
        Set next=rs.Next(.sc) $$$ThrowOnError(sc)
        If next Throw ##class(%Exception.General).%New("AMBIGUOUS_ACCOUNT")
        Set result={"available":true,"code":"WORKFLOW_ACCOUNT_FLAGS_READ","enabled":false,"expirationDate":null,"accountNeverExpires":false}
        Do result.%Set("enabled",(enabled=1),"boolean")
        Do result.%Set("accountNeverExpires",(never=1),"boolean")
        If date'="" Do result.%Set("expirationDate",date,"number")
    } Catch ex { Set result={"available":false,"code":"WORKFLOW_ACCOUNT_STATE_UNAVAILABLE"} }
    If $IsObject(rs) { Set ignored=rs.Close() }
    Return $$$OK
}
}
