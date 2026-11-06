Class Chronos.App.Input Extends Ens.BusinessService
{
Parameter ADAPTER = "";

Method OnProcessInput(pInput As %RegisteredObject, Output pOutput As %RegisteredObject, ByRef pHint As %String) As %Status
{
    Set pOutput=##class(Chronos.App.Response).%New()
    Set sc=##class(Chronos.App.Entry).Check(pInput,.code)
    If code'="OK" Set pOutput.Code=code Return $$$OK
    Set remaining=pInput.Deadline-##class(Chronos.App.Entry).Now()
    If remaining<=0 Set pOutput.Code="REQUEST_TIMEOUT" Return $$$OK
    Return ..SendRequestSync("Chronos.App.Process",pInput,.pOutput,remaining)
}
}
