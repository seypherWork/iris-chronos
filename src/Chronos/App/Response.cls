Class Chronos.App.Response Extends Ens.Response
{
Property Code As %String(MAXLEN = 64) [ InitialExpression = "NO_RESPONSE" ];
/// Candidate detail includes exact payloadJSON alongside its 64-KiB context.
/// Public projection is bounded to 256 KiB canonical UTF-8 before transport.
/// Leave room for JSON escaping; boundary regressions include Unicode/quotes.
/// This is a storage capacity, not permission to return private ledger content.
Property ResultJSON As %String(MAXLEN = 524288);

/// Optional telemetry for the native Visual Trace message body.
Property TraceMetricsJSON As %String(MAXLEN = 512);
}
