Include %occStatus

/// Native composition with guarded AI proposals; authenticated approval pending.
Class Chronos.App.Production Extends Ens.Production
{
ClassMethod OnStart(pTimeStarted As %String) As %Status
{
    Return ##class(Chronos.Runtime.Bootstrap).Recover("Chronos.App.Production",pTimeStarted)
}

ClassMethod OnStop(pTimeStarted As %String, pForced As %Boolean)
{
    Set sc=##class(Chronos.Runtime.Bootstrap).Stopped("Chronos.App.Production",pTimeStarted,.outcome)
    If outcome.code="STOP_IGNORED" Return
    Set record={"at":(pTimeStarted),"code":(outcome.code)}
    Do record.%Set("gateCloseConfirmed",outcome.closed,"boolean")
    Set ^ChronosRuntime("lastStop")=record.%ToJSON()
}

XData ProductionDefinition
{
<Production Name="Chronos.App.Production" TestingEnabled="true" LogGeneralTraceEvents="false">
  <Description>Chronos supervised synthetic workflow; fixed provider, durable boot recovery</Description>
  <ActorPoolSize>1</ActorPoolSize>
  <Item Name="Chronos.App.Input" ClassName="Chronos.App.Input" PoolSize="0" Enabled="true" Foreground="false" />
  <Item Name="Chronos.App.Process" ClassName="Chronos.App.Process" PoolSize="1" Enabled="true" Foreground="false" />
  <Item Name="Chronos.App.Worker" ClassName="Chronos.App.Worker" PoolSize="1" Enabled="true" Foreground="false" />
  <Item Name="Chronos.Agent.Operation" ClassName="Chronos.Agent.Operation" PoolSize="1" Enabled="true" Foreground="false" />
  <Item Name="Chronos.Approval.Input" ClassName="Chronos.Approval.Input" PoolSize="0" Enabled="true" Foreground="false" />
  <Item Name="Chronos.Approval.Operation" ClassName="Chronos.Approval.Operation" PoolSize="0" Enabled="true" Foreground="false" />
</Production>
}
}
