# Model startup and decision diagnostics

Keep the original request and decision references when a test fails. Do not reset
an allowance, delete a consumed request, edit the original result, or infer that
a timeout cancelled execution. These instructions do not authorize a new model
request, account change or recovery operation.

## Read the stages separately

| Observation | What it establishes | What still needs checking |
| --- | --- | --- |
| Model appears in the runtime inventory | The model is loaded | A completed, valid response |
| Neutral warmup succeeds | The model answered a bounded readiness request | The business interpretation and all workflow checks |
| Transport records `VERIFIED_STOP` | Model/shape/completion controls passed at the transport boundary | Citations, preference, original context binding and fresh state |
| CLI reports `DECISION_AVAILABLE`, state `COMPLETED` | A terminal decision can be read | Its outcome may still be `ERROR`, `REJECTED` or `VALIDATED_HOLD` |
| Outcome `VALIDATED_PROPOSAL` | The proposal passed application checks | Human interpretation review, fresh preview, explicit consent and independent readback |
| Destination reports `ACCEPTED` | The owned destination accepted that operation | Simulated delivery is separate; no physical shipment is demonstrated |

The real attempt96 reached the fourth row and ended with `ERROR / INVALID_PROPOSAL`.
Its raw completion was discarded, so its precise validation failure cause cannot be recovered
from that generic code. A later diagnostic improvement must not relabel the old result.

Fresh case98 subsequently passed native validation and reached one authorized
synthetic acceptance. Its lab observer applied the frozen E1 checker to the
sanitized response, stored only a bounded diagnostic/hash, and returned the
response unchanged. This successful new case does not recover the cause of96.
See [the real case checkpoint](EVIDENCE.md#earlier-development-records).

## Known rejection codes

The source candidate preserves bounded E1 error codes and the UI gives fixed
explanations. It never displays provider exception arguments or the rejected reply.

| Code family | Inspect before a separately authorized new decision |
| --- | --- |
| `INVALID_SOURCES`, `CURRENT_SOURCE_REQUIRED`, `CONFLICT_SOURCES_REQUIRED` | Exact source IDs and whether the cited messages apply to the current order |
| `EXTRACTION_CONTRACT_MISMATCH`, `INVALID_EXTRACTION_JSON`, `INVALID_EXTRACTION` | Model profile, structured-output contract and output limits |
| `INCONSISTENT_EXTRACTION`, `STRUCTURED_POLICY_MISMATCH` | Preference/reason consistency and the original structured policy |
| `INVALID_RATIONALE`, `INVALID_CLARIFICATION` | Required explanation/clarification shape and length |
| `CONTEXT_DIGEST_MISMATCH`, `CALL_CONTEXT_MISMATCH`, `BOUND_CONTEXT_CHANGED` | Original request/context integrity and source version; do not rewrite the failed record |
| `INVALID_AVAILABLE`, `DUPLICATE_AVAILABLE`, `UNKNOWN_PREFERENCE_MODE` | The input and deterministic option computation |
| `SENSITIVE_OUTPUT` | Authorized configuration, without copying private values into reports |
| `MODEL_TIMEOUT`, `MODEL_ERROR`, `MODEL_REFUSAL` | Original provider/transport outcome; no automatic resend or fallback |
| `INVALID_PROPOSAL` or an unfamiliar code | Preserve the generic failure. Do not guess a more specific cause |

## Local model startup

Check resources after IRIS and the provider services start, before loading weights.
Cold loading, neutral warmup and business inference are separate measurements.
In the owned Windows laboratory, attempt96 used a bounded combined cold/warm
request and a ten-minute keep-alive, with an independent resource monitor and
automatic stop. This is evidence for that experiment, not a universal model or
deployment requirement and not permission to widen the business decision deadline.

Before another business call, verify the actual model digest, context size, bound
profile, live transport guard and remaining authorized request budget. An old
loaded-model observation is not proof that the model is still resident.

## Evidence boundary

Bundle95 and the failed decision96 remain unchanged. The source diagnostic fix has
local/synthetic test evidence and still requires validation in the next installed
candidate. A reference extraction accepted in an offline test is not a replacement
for the model's rejected response. See the [checkpoint96](EVIDENCE.md#earlier-development-records).

## Bounded local transport rejection diagnostics

The local guard emits best-effort JSON diagnostics for rejected requests: a fixed
event name, validated request UUID (or null before reservation), allowlisted error
code and bounded elapsed milliseconds. It never records prompts, responses,
reasoning, configuration or exception text. Delivery uses a queue of at most32
events and one daemon writer; a blocked log sink cannot block the HTTP handler.
Full queues and shutdown may discard events. These diagnostics are not durable
audit evidence and do not change the durable allowance or authorize a retry.

A terminal native decision containing JSON status ERROR is a valid failed result,
not itself an IRIS console exception. Check the process status and console text
outside the uniquely marked JSON object separately. Do not promote ERROR to HOLD.

Attempt117 retained two validated proposals and one MODEL_ERROR at28seconds.
The new diagnostics cannot retrospectively recover that third rejection's cause.
