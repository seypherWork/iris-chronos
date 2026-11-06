/// Internal message. No URLs, classes, credentials or model-generated authority.
Class Chronos.App.Request Extends Ens.Request
{
Property Command As %String(MAXLEN = 32);
Property OrderId As %String(MAXLEN = 128);
Property ShipmentVersion As %Integer;
Property OperationId As %String(MAXLEN = 128);
Property Generation As %String(MAXLEN = 64);
Property RequestId As %String(MAXLEN = 64);
Property TrialMode As %String(MAXLEN = 32) [ InitialExpression = "WITH_TRIALS" ];
/// Preserve the UTC precision through persistent Interoperability messages.
Property Deadline As %Numeric(SCALE = 9);
}
