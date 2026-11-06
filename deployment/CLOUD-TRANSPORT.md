# Cloud transport source — application integration pending

src/chronos_transport/cloud_transport.py provides the CHR-I07 transport.
The optional [cloud launcher](CLOUD-PROVIDER.md) now supplies a private-console
entry point and separate Compose overlay. Neither has been validated with a real
provider or native AI Hub cloud workflow. The local guard CLI stays local-only; native provider source now binds the
separate cloud plan, with compilation/runtime validation still pending. No real key or paid request has been used.

## Implemented source behavior

OpenAITransport requires an already-created CloudAllowance, a privately supplied
ApiKey object, and the exact approved policy digest. It reads the bundled E1
schema and binds its digest to the profile. Its accepted protocol requires an exact
model supporting Chat Completions, strict JSON schema, reasoning_effort=none,
temperature=0 and max_completion_tokens. No default model, model substitution or
fallback exists. A model identifier does NOT establish live availability. The launcher restricts
selection to documented IDs and reviewed rate/context limits; actual provider
validation remains pending.
Local Qwen behavior and its accepted reasoning settings are unchanged.

The native request is validated before consuming a slot. Provider wire output
contains only two text messages, exact model/settings, a projected strict E1
schema, max_completion_tokens=2048, n=1, stream=false, store=false and
service_tier=default. Internal deadline/profile/request identifiers are not
sent to the provider. No tools, attachments, premium-tier opt-in or streaming.
Store=false is not a promise of zero provider retention.

The provider schema keeps required fields, types, enums and additionalProperties
false. Length, count and uniqueness constraints are omitted only on that wire
projection and re-applied to the received E1 object locally. The full native
semantic/freshness/citation/A1 validation remains required; this library does
not authorize business effects or prove that a proposal is correct.

## Network and interruption boundary

The endpoint is fixed to https://api.openai.com:443/v1/chat/completions. There is
no endpoint/CA override, proxy-environment support, certificate bypass, redirect
follow or retry. Default trust store, hostname checking and TLS1.2 minimum are
required. A private/loopback DNS destination is refused. One public address and
one connection are used; an unreachable chosen address fails without fallback.

DNS resolution runs in at most one worker per process. The caller can time out
while the OS resolver is still blocked; that worker has no credential and can
never send HTTP. Another resolver is rejected as busy until it finishes. Network
operations share an absolute deadline and a disconnect watchdog. A duplicated
raw socket, acquired before TLS wrapping, permits cancellation of the connection.
A cancelled request may nevertheless have been received/billed by the provider.

The ledger reserves request count and money before I/O. After DNS/TCP/TLS, the
library rechecks authorization, deadline, exact pending reservation and durable
halt immediately before POST. It rechecks time after persistence as well.
SQLite/filesystem stalls may delay the function's return; the library rejects
late success rather than promising hard real-time completion during disk stalls.

A halt already observed at that final admission prevents a pending send. A halt
committed AFTER admission cannot revoke admitted or already sent requests. No
database transaction is held over network I/O. Repeated request IDs never gain
another reservation or trigger another send through send().

## Response, keys and accounting

Only one complete stop response for the exact model is accepted. Refusals,
function/tool calls, invalid JSON, wrong fields, excessive size, duplicate HTTP
headers, conflicting framing and incomplete bodies are rejected. A new response
is reconstructed; upstream reasoning/extra fields/spoofed receipts are discarded.
Known provider tier and usage mismatches persist a halt BEFORE validating the
content, so an incomplete answer cannot hide a simultaneous accounting problem.

A halted ledger remains halted after reopen. There is no reset/refund API. Old
experimental ledgers without the new control table are refused, never migrated
or repaired automatically. No production ledger exists yet for this cloud path.

ApiKey hides its value from str/repr and refuses pickle; only the HTTPS header
uses it. Exact echoed keys are rejected in both the outer JSON and decoded E1,
including Unicode escapes. It is not a vault or protection from a privileged
process debugger. close() drops the reference but cannot promise secure memory
erasure in Python or prevent OS paging/core dumps. Never put real keys in source,
arguments, screenshots or test fixtures. Tests use an explicitly fake key.

VERIFIED_STOP records a verified provider response, not delivery to the caller,
business approval or billing proof. If the terminal commit crosses the deadline,
the caller receives an error; the verified historical result stays recorded and
the reservation stays spent. IN_FLIGHT/UNCERTAIN likewise never authorize replay.
See CLOUD-BUDGET.md for the declared-rate reservation limits and approval scope.

## Evidence and remaining gates

Executed locally without real network: protocol/schema/redaction/expiry tests,
real SQLite and two-client halt race, current TLS-context flags, a stubbed DNS
worker, and the real HTTP wrapper driven by synthetic sockets/responses. The
synthetic certificate-error test is NOT a real handshake/certificate-validation
claim. No claim of actual API-model compatibility, actual provider billing or
native AI Hub interoperability is made.

Still needed: reviewed available model/capability/rate setup; private key input
and owner approval; packaged launcher/Compose/native integration; real TLS/error
proof and a specifically funded provider test; two clean IRIS154 installations;
judge login/decision/approval/destination/readback and comparative evaluation.
Keep remote UI capability disabled until those paths are implemented and proven.

Official protocol sources inspected30October2026:
- https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create
- https://developers.openai.com/api/docs/guides/structured-outputs
No model inspected in this step was selected as the user's runtime default.
