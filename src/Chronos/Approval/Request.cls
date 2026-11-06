/// Native message contains routing context and public IDs only, never grants,
/// CSP session IDs, CSRF values, passwords or client-supplied identity/roles.
Class Chronos.Approval.Request Extends Ens.Request
{
Property Command As %String(MAXLEN = 32);
Property Identifier As %String(MAXLEN = 128);
/// Public request correlation only; never an authentication or creation grant.
Property CorrelationId As %String(MAXLEN = 128) [ InitialExpression = "" ];
Property OriginJob As %Integer;
Property OriginFingerprint As %String(MAXLEN = 64);
Property Deadline As %Numeric(SCALE = 9);
}
