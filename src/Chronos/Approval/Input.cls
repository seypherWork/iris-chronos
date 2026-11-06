Include %occStatus

Class Chronos.Approval.Input Extends Ens.BusinessService
{
Parameter ADAPTER = "";

Method OnProcessInput(request As %RegisteredObject, Output response As %RegisteredObject, ByRef hint As %String) As %Status
{
    Set response=##class(Chronos.App.Response).%New()
    Set response.Code=##class(Chronos.Approval.Entry).Check(request)
    If response.Code'="OK" Return $$$OK
    Set remaining=request.Deadline-##class(Chronos.App.Entry).Now()
    If remaining<=0 Set response.Code="REQUEST_TIMEOUT" Return $$$OK
    Return ..SendRequestSync("Chronos.Approval.Operation",request,.response,remaining)
}
}
