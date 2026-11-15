/// Opt-in native handoff request. No actor, deadline, role or effect permission.
Class Chronos.Workflow.Request Extends Ens.Request
{
Property DecisionId As %String(MAXLEN = 128);
}
