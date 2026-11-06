# Evidence and evaluation limits

Start with [the jury route](JURY-ROUTE.md). This page summarizes the observed runs;
the [preserved audit history](EVIDENCE-HISTORY.md) retains earlier successes,
failures, source versions and detailed measurements. All shipments are synthetic.

## Current native evidence

### Exact-package rehearsal on 467

The Windows PowerShell 5.1 guide rebuilt the private ZIP, staged the MIT licence
and verified the 154-file bundle. A fresh IRIS AI Hub 154 installation ran the
complete `queue_inventory` case with local Qwen. Reader's direct approval
preview request was denied by IRIS. An Operator asked three questions in the
same English conversation:

| Question | Observed answer |
| --- | --- |
| Why was B chosen when A cost less? | Only B was eligible. A cost 3, but its seven-minute queue outlasted six minutes of inventory validity. B cost 6, within the budget of 8. The answer cited the decision, validation and timing. |
| What happened to the original shipment attempt? | The destination closed the attempt without accepting it. The answer cited the current operation read. |
| Can you approve and send B for me? | Chat required a separate authenticated preview and human confirmation. The operation was unchanged after every chat turn. |

The Operator confirmed B once. The test withheld the browser response after
IRIS observed acceptance. A reload recovered the same operation, attempt and
reference. The synthetic destination recorded one B submission. All access was
disabled and the four services stopped with exit 0. The tested bundle manifest
was `9b9583e18027363b11c782a1a057d571074391f151d1f726b33fb1eae4365b6c`.
This handoff updates the written evidence and preserves the tested application
and installation code. The six-case matrix and recording retain their own scopes.

### Final native rehearsal

Bundle 463 ran all six fixed cases in two fresh installations on the same
Windows workstation, with IRIS AI Hub Community 154 and local Qwen. The
installation guide built the bundle in Windows PowerShell 5.1. The model
recipe downloaded the weights into a fresh cache and verified the pinned alias.

| Case | Observed result |
| --- | --- |
| `queue_inventory` | The agent interpreted preference, checks selected B, and the chat explained why with citations. Reader's direct preview request was denied. Operator confirmed once. Reload recovered the same attempt and receipt after the test lost the browser reply. |
| `earliest` | One approved recovery to B, cost 6 within 8. The independent destination matched the browser receipt. |
| `economy` | One approved recovery to A, cost 3 within 8. One reconciliation resolved acceptance on the same attempt. |
| `ambiguous` | HOLD for clarification. Zero recovery submissions. |
| `accepted` | Original acceptance found. Zero recovery submissions. |
| `uncertain` | Original remained unresolved. Zero recovery submissions. |

Each accepted recovery had one destination submission and one attempt.
All lab accounts and routes were disabled after both runs, and all services
stopped with exit 0. The tested native manifest is
`26dce20f8fa1e0bd36cd3e05bbd4417b6a6acaedbf5dea6940184a25825a5c02`. The delivery keeps the same application runtime and installation commands.
It updates these notes and carries the MIT licence through bundle creation
and staging. The video is from 407r2.

### Earlier validation on 460

Bundle 460, manifest `358116d3cd87ac8af476e80bb33f3885c4a351354154a09b707fa495fe40d29b`,
ran on IRIS AI Hub Community 154 x64 with local Qwen. Reader and Operator
used separate accounts. Reader saw the approval preview control disabled.
The E1 decision used the custom outbound adapter. In one real C2 turn,
the chat explained why B fit even though A cost less. A cost 3, but its
seven-minute queue outlasted six minutes of inventory validity. B cost 6
within a budget of 8.

Operator confirmed once. The test cut the browser reply after IRIS observed
acceptance. At 390 px the warning stayed visible while scrolling, and its
shortcut focused the original outcome control. After reload, the operation,
attempt, receipt and ACCEPTED state matched the synthetic destination.
The destination recorded one B recovery and the original rejected A. The
accounts and route were disabled and all four services stopped with exit 0.

The delivery makes the tested read-only model-cache mount the default. The
resolved Compose configuration matches the native rehearsal. The recording
below shows the earlier 407r2 run. This evidence covers the tested workstation
and case. Independent hardware, build 109 and live hosting remain unverified.

### Six-case evidence on 407r2

The frozen 407r2 bundle manifest is
`dd22c04429bd9a9c1b85f67a3eeeb5ee30423102be553d11f3dad8ee6b5dc1cf`.
Two clean 407r2 installations completed on AI Hub Community 154 on the same
Windows workstation. One ran the mobile loss experiment below. The other
verified disabled installation, then resumed the production after a clean
stop, verified a new generation and ran the other five cases. The exact
candidate therefore covers all six fixed cases across two installations on
the same host. The more extensive English questions retain their earlier
source revision.

| Exact 407r2 case | Observed decision and result |
| --- | --- |
| `earliest` | Earlier arrival selected B, cost 6. One accepted recovery and the same receipt after reload. |
| `economy` | Lower cost selected A, cost 3. A single confirmation returned UNKNOWN while queued. One reconciliation recovered ACCEPTED for the same attempt, and the receipt matched after reload. |
| `ambiguous` | HOLD with clarification. Preview disabled and zero recovery submissions. |
| `accepted` | Original acceptance found. Preview disabled and zero recovery submissions. |
| `uncertain` | Original remained UNKNOWN. Preview disabled and zero recovery submissions. |
| `queue_inventory` | One accepted B recovery, induced HTTP reply loss and the original receipt after reload. Separate mobile test below. |

The five-case run used three E1 calls, zero C2 calls, two confirmations and
one reconciliation. The independent destination recorded five originals and
two recoveries, each with one submission and one attempt. The separate
queue/inventory experiment included the real English C2 question.

## Custom outbound adapter

The recorded 407r2 browser, receipt and chat runs above are earlier evidence.
The adapter changes the E1 model connection. C2 keeps its separate connection.
The adapter proof used the IRIS 154 bundle
`f69bf5be596b01871417c3b890b2c2df22c68cf1cf28b8af39502fc84be68b5c`. The release bundle retains the tested adapter and adds SIGTERM handling at the guard CLI entry point.

In a fresh, separate Windows installation, a queued `queue_inventory` request
called AI Hub through `Chronos.Agent.GuardAdapter`, an `Ens.OutboundAdapter`
declared on `Chronos.Agent.Operation`. The validated proposal was B. The
native response in Interoperability session 2 recorded
2,161 tokens and 2,269 ms around the SDK call.

A direct second submission of the same identifier reached the Agent Operation
in session 9 and returned `EXISTING_DECISION`. It preserved the
result and original call record. Ollama logged one warmup and one business
inference. The guard's single completed claim was unchanged after replay.
The destination retained its original rejected attempt and zero recoveries.

This run kept both accounts and routes disabled and stopped all three services.
The guard exited with code 137 after the stop request
with no out-of-memory event. A later Docker test used the corrected guard as PID 1
in separate E1 and C2-v2 containers. The normal Docker stop returned exit code 0
in both cases and each synthetic in-flight claim remained spent.
This adapter run validates the changed E1 path and same-ID replay. The
[final native rehearsal](#final-native-rehearsal) separately exercised the
adapter alongside chat and confirmation.

## Latest private audit: 5 November

The 354 native journey used frozen source **354** on **IRIS AI Hub Community
2026.3.0AI.154.0**, local **Qwen3.5-9B Q8_0**, context8192, reasoning `none`.
It completed a fresh isolated installation, scoped Reader/Operator login,
neutral model warmup, one queue/inventory decision, one explicit recovery
confirmation, destination readback and reopening the same operation after reload.

Original A remained `NOT_ACCEPTED_FINAL`; recovery B became `ACCEPTED`.
There were two operations and two submissions total: one original and one
recovery. Sixteen reads around the chat preserved that operation; asking a
question created no new shipment. Acceptance is not physical delivery.

Eight real-model questions were asked in two conversations:

| Question | Observed answer |
| --- | --- |
| Why B when A was cheaper? | Distinguishes cost from A's inventory-related infeasibility. |
| What happened; sent or delivered? | Separates the recorded acceptance from delivery. |
| Does accepted mean delivered? | No; the supplied read does not establish delivery. |
| Which queue, travel, inventory and deadline times matter? | Cites A queue7/travel8, B queue0/travel9, inventory6 and deadline20 minutes. |
| What changed since the decision and by chatting? | Separates the recorded proposal, current acceptance and chat's lack of action. |
| Send it again now. | Refuses execution through chat; accepted operations must not be resent. |
| Rephrased timing question | Uses the same checked timing facts. |
| Rephrased progress question | Preserves the acceptance/action distinction. |

The exact progress question exposed an omission in353 and passed after the354
correction. Independent semantic review found no new P2 defect in these eight
answers. This is one case and eight questions, not universal accuracy. The
seventh submission to one six-turn conversation was blocked by the UI; that is
not a new direct server-quota test. No console or observation errors were seen.
Accounts/routes, production and all four services were closed; no OOM was observed.

## Source and test boundaries

| Artifact | What its evidence covers |
| --- | --- |
| Native354, manifest `3e4a07a7f351f09fdea5fcb064668291f2a7cef7aa59aa62f938fb3d83a08822` | The actual IRIS/model/browser journey above;151 source files. |
| Private355, manifest `a57533c2326d9249be97db6413d1ef984ebfc9616f50abde207ee17c41401de6` | Later chat-panel and four documentation changes; not another native installation. |
| 355 documentation reorganization | Splits this index from its history and includes that history in packaging; no application/runtime logic changes. Its package requires its own manifest. |

The 355 manifest above identifies the frozen snapshot, not this edited document.
Local regression results were216 existing conversation tests plus5 new tests,
and382 web tests after the UI follow-up. Overlapping subsets are not additional
unique tests. The [history](EVIDENCE-HISTORY.md) records intermediate failures and
source-specific results; none is silently converted into a pass.

## Chat navigation follow-up 355

The panel follows a new answer only when the reader remains at the end; otherwise
it retains the reading position and offers **Show latest reply**. Citation focus
and disclosure state are preserved without stealing focus from the question.
The correction passed Chrome replay at1440×900 and390×844 using saved native354
answers. This was an offline UI check, not new inference. Long answers and a long
mobile confirmation page remain usability observations.

## Native flow

The earlier333 candidate covered six fixed cases across initial run338 and
continuation342, preserving the economy operation after its initially uncertain
response. It was not an uninterrupted six-case run. Two333 installations on the
same host/cache passed installation/configuration; that does not prove two
complete jury journeys, independent hardware or a new user's manual installation.
See [case-by-case history](EVIDENCE-HISTORY.md#native-flow).

## Native trace access

Start with the [verified 407r2 example](#visual-trace-on-407r2). The earlier
rehearsal below records the separate 387r2 run and access setup.

In the 387r2 example, a temporary authorized reader opened InterSystems Message
Viewer, the original Interoperability session 2 and agent response header 5.
Visual Trace rendered the graph. The message Body showed `TraceMetricsJSON`:
2,061 input tokens, 87 output tokens, 2,148 total tokens and 2,199 ms around
the SDK call. An independent persisted-message read matched those values. The
test withdrew the temporary access and restored the portal configuration.

A separate native read of the 407r2 experiment found E1 session 2, AI Hub
session 1 and response header 5: 2,077 input tokens, 87 output tokens, 2,164
total tokens and 2,479 ms around the SDK call. The same read found one native
confirmation request and response in session 37. Its operation, attempt and
reference matched the recovered destination receipt. These session numbers are
local to their own deployments. The E1 response predates the English C2 question.

Use the session displayed by the current case when repeating the procedure.
Chronos does not grant Management Portal access. The [older attempts](EVIDENCE-HISTORY.md#native-trace-access)
record the access and rendering failures that preceded the successful example.

## Clean engine rehearsal

On the frozen 152-file bundle 373, the PowerShell guide verified the bundle,
planned both profiles, staged a pristine copy and resolved all five Compose
files. Docker could not allocate an automatic network. After confirming the
failed attempt left neither a container nor a network, the same stage was
started with a verified free subnet scoped to that project. Build 154 health
passed and the native installer inspected 25 available targets. Only IRIS
started and it stopped cleanly. No Apply, account changes, model or recovery
ran during this rehearsal.

## Engine interruption and delivery state

Recorded checks cover same-operation recovery after an engine interruption,
unknown acceptance, a lost browser response and a two-operation race with one
effective recovery. They belong to their recorded revisions; component reuse
requires matching source hashes. They do not prove every possible crash or
physical delivery. [Interruption history](EVIDENCE-HISTORY.md#engine-interruption-and-delivery-state)
and [concurrency evidence](EVIDENCE-HISTORY.md#distinct-operation-concurrency-check-334).

## Shared model transport (4 November)

The supported recipe uses native Ollama transport, finite allowances and separate
E1 decision/C2v2 conversation contracts. Full33/33GPU layers were observed on the
tested16GiB workstation. CPU-only, smaller GPUs, cloud C2v2 and build109 are not
validated by this route. [Transport evidence](EVIDENCE-HISTORY.md#shared-model-transport-4-november)
and [model recipe](MODEL-RECIPE.md).

## Earlier development records

The Qwen comparison319 used12 already-known synthetic scenarios: R1 scored12/12
versus R0's10/12 in each mode, with16 model calls and separate deterministic
precontrols. Trials/no-Trials tied; no extra benefit from Trials is established.
This is local regression evidence, not a fresh blind test or native AI Hub
execution of the benchmark. Historical GPT-OSS results and partial chat replies
remain distinct. [Full comparison](EVIDENCE-HISTORY.md#current-qwen-decision-comparison--5-november)
and [earlier records](EVIDENCE-HISTORY.md#earlier-development-records).

## Evidence boundaries

- The source is distributed under the [MIT licence](../LICENSE).
  Public availability, registration and organizer accreditation are separate checks.
- Keep approval and failure evidence scoped. The local checks cover stale
  consent, rejection versus late acceptance and terminal reference preservation.
  The native loss experiment covers the recorded HTTP interruption and readback.
- The recorded walkthrough and the earlier six-case run keep their own
  revision labels. Other hosts, build 109, CPU inference and cloud C2 remain
  outside the verified installation scope. Bonus credit follows organizer review.

## Confirmation response loss

The exact 407r2 bundle ran `queue_inventory` on AI Hub Community 154. Reader
and Operator authenticated independently. A guarded local Qwen call supplied
the decision and the operator asked one English question. A's seven-minute
queue outlasted six minutes of inventory validity. B cost 6 within a budget of 8.

One confirmation reached IRIS. The test interrupted the HTTP response after
acceptance, before the browser received it. At 390 px the warning stayed visible
while scrolling. **Find original outcome** moved focus without another approval
request. Confirmation stayed disabled and the acknowledgement was cleared.

After reload, the saved approval preview returned the same operation, attempt,
receipt and ACCEPTED state. The native confirmation message and independent
synthetic destination matched. The destination recorded one B recovery submission
and a separately rejected A. The lab closed its two accounts, web route,
production and four services. An earlier 387r2 test reproduced the HTTP-loss
and same-receipt behavior separately.

## Two native receipt checks

The `queue_inventory` experiment interrupted the confirmation response after the
synthetic destination accepted B and IRIS recorded the result. In the separate
HTTP 503 experiment, a local test fixture emitted the 503 for the original.
Chronos read the same definitive receipt through its installed Embedded Python
destination and processed the recovery through its native IRIS production.
A qualified at cost 3 against a maximum of 8. The automated browser test made
one confirmation in an authenticated Operator session. It returned UNKNOWN
while A queued. One reconciliation of
the same operation and attempt returned ACCEPTED. Reloading returned the same
reference as the independent destination read. The simulator admitted A at minute
3 and estimated arrival at minute 15 against a deadline at minute 20. The
acceptance and the planned arrival are separate observations.

The projection below was checked against IRIS confirmation and readback records
and independent destination records. The short hashes of the synthetic references
make the equality visible without exposing internal identifiers. The full local
records also match each operation and attempt before computing these digests.
Each experiment had one original submission and one recovery submission.

```json
{
  "build": "2026.3.0AI.154.0",
  "synthetic": true,
  "runtimeManifestSha256": "dd22c04429bd9a9c1b85f67a3eeeb5ee30423102be553d11f3dad8ee6b5dc1cf",
  "queue_inventory": {
    "authenticatedOperatorConfirmations": 1,
    "responseInterruptedAfterAcceptance": true,
    "confirmStateAtIris": "ACCEPTED",
    "reopenedState": "ACCEPTED",
    "target": "B",
    "cost": 6,
    "maxCost": 8,
    "referenceDigest16AtIris": "06df5d2829240785",
    "referenceDigest16AfterReload": "06df5d2829240785",
    "referenceDigest16AtDestination": "06df5d2829240785",
    "recoverySubmissions": 1
  },
  "literal_503": {
    "initialHttpStatus": 503,
    "originalState": "NOT_ACCEPTED_FINAL",
    "authenticatedOperatorConfirmations": 1,
    "stateOnConfirmation": "UNKNOWN",
    "reconciliations": 1,
    "reopenedState": "ACCEPTED",
    "target": "A",
    "cost": 3,
    "maxCost": 8,
    "referenceDigest16OnReconciliation": "c23faf61d3472af4",
    "referenceDigest16AfterReload": "c23faf61d3472af4",
    "referenceDigest16AtDestination": "c23faf61d3472af4",
    "recoverySubmissions": 1,
    "acceptedAtSimulatedMinute": 3,
    "plannedArrivalAtSimulatedMinute": 15,
    "deadlineAtSimulatedMinute": 20
  }
}
```

## Visual Trace on 407r2

The native InterSystems graph opened the recorded `queue_inventory` session 2.
Selecting the E1 response at message ID 5 and opening **Body → TraceMetricsJSON**
showed 2,077 input tokens, 87 output tokens and 2,164 total tokens.
The SDK call interval was 2,479 ms. The viewer and the native readback of the
stored message agreed. The graph row number and the message ID are separate.
Reproduced runs have their own session, message and
metrics. The English case conversation uses a separate session. The read-only
review preserved all three synthetic destination stores and closed its access.

See [how to inspect the original native trace](JURY-ROUTE.md#inspect-the-original-native-trace).

## Review by criterion

| Criterion | Evidence |
| --- | --- |
| Complexity | [Native AI Hub workflow](#final-native-rehearsal), with the AI Hub decision, checked approval and independent receipt. |
| Clarity of instructions | [English installation prerequisites](JURY-ROUTE.md#0-prerequisites-and-the-values-to-retain). |
| Developer experience | [Isolated Compose layout](JURY-ROUTE.md#2-fix-the-complete-compose-layout-before-engine-creation) and [bundle build](JURY-ROUTE.md#obtain-the-source-bundle-before-staging). |
| Applicability | [Two recovery experiments](#two-native-receipt-checks), with one recovery submission per experiment. |
| Usability | [Preview, approval and readback](JURY-ROUTE.md#preview-explicit-approval-and-same-operation-readback), an English case explanation and the 390 px mobile test. |

## Evaluation details

The paired synthetic benchmark compared frozen rules and the local agent with
the same inputs and deterministic checks. Action and interpretation matched
12/12 for the agent versus 10/12 for the rules. Including exact reason, the
results were 11/12 and 9/12. The trial modes tied. The model repetitions reuse
the same twelve inputs and the benchmark ran outside IRIS. The separate native
journey proves the 407r2 recovery path on the declared setup.

See the [review and preview time limits](JURY-ROUTE.md#preview-explicit-approval-and-same-operation-readback)
and [model preparation and provider settings](MODEL-RECIPE.md). Chat references
are held in page memory for the current session. Chat can ask for a new
evaluation and has no approval or dispatch authority. Setup uses scoped access
and loopback bindings. See [local web access and closure](WEB-ACCESS.md).
