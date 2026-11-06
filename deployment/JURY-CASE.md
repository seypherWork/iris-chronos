# First decision and recovery walkthrough

> Installation command order: follow [JURY-ROUTE.md](JURY-ROUTE.md). This is a
> component reference, not an additional setup pass. Do not prepare allowances or
> perform initial production start again after completing the canonical route.

The fixed synthetic incident seed is connected to native authority and one
AI Hub interoperability request. The recorded four-case run 135 exercised the
native model and authenticated browser; see [validation evidence](EVIDENCE.md#native-flow).
On frozen bundle 333, run 337 separately completed the queue/inventory journey
with independent semantic and visual review. Both A/B disabled installations and
provider setups passed on the same host/model cache. A covered the six cases
across incomplete attempt 338 and continuation 342, preserving existing effects
and quotas. This was not a single uninterrupted run. Commands retain their
fixed case identities: they never reset an earlier failed or expired scenario.

## Prerequisites

Use a new isolated deployment installed from this exact verified source bundle.
The receipt must match the manifest, application, origin and private database.
Inspect the selected frozen bundle for this helper; these commands do not upgrade it.
Do not substitute a new digest over an old installation.

Separately configure the owned provider, its original request allowance and
running `Chronos.App.Production`. The CLI configures or starts none of them.
The measured route uses the local guard. The separate optional cloud route has
not completed real provider/TLS/workflow validation. Keep credentials out of command arguments/reports.

Run as the existing trusted `irisowner` console user inside the owned container.
There is no public seed/proposal endpoint or arbitrary order/path input.
The original fixed cases `earliest` and `economy` have different synthetic customer
preferences. These two walkthrough cases are not a comparative benchmark.

The available cases below have fixed synthetic facts. Prior accepted/uncertain
workflow checks and nonactionable browser denials were verified on their recorded
installations; the earliest, economy, ambiguous and queue/inventory flows later
completed in run 135. Historical UI defects 109/110 and their original receipts
remain preserved. Repeat the relevant checks on the final artifact before release.

| Case | Owned original history | Expected kind of result, subject to actual checks |
| --- | --- | --- |
| ambiguous | Real final rejection, both offers feasible, preference unresolved | Native model may produce a validated HOLD; retain any error or different answer |
| queue_inventory | Final closure of a synthetic original; A queue 7, inventory 6, travel 8; B queue 0, travel 9; budget 8, deadline 20 | The shared temporal engine rejects A for inventory expiry; only B is feasible while fresh. Historical native/model/UI flow in run 135; repeated on frozen bundle 333 in run 337 with explicit confirmation and same-operation readback |
| accepted | Immediate simulator acceptance, independently queried, never closed | Durable deterministic EXISTING_ACCEPTANCE; no model call and no new send |
| uncertain | Actual queued original, independently UNKNOWN, never forcibly closed | Durable deterministic ACCEPTANCE_UNRESOLVED; no model call, recovery blocked |

The uncertain queue is30 minutes with a 25-minute case deadline. Its actual state
can later change; preparation refuses changed history rather than resetting the
clock. A deterministic result records what checks observed at that moment, not
current permission or model understanding. Query the same operation for current
state. These results have no prepared inference context, claim or action window;
PREVIEW rejects them before refreshing authority. Missing ledger after an issued
request remains uncertain and never permits replay.

The following `sh` examples run **inside the owned Linux container**, not in
Windows PowerShell. Open its shell using the same complete Compose layout.
For the current local/web/C2v2/GPU route (the full file set is included):

```text
docker compose -f deployment/compose.yaml -f deployment/compose.web-local.yaml -f deployment/compose.local-model.yaml -f deployment/compose.conversation.yaml -f deployment/compose.local-gpu.yaml --profile local-model --profile conversation exec --user irisowner iris /bin/bash
```

For cloud, use the separate [CLOUD-PROVIDER.md](CLOUD-PROVIDER.md) layout; do not mix it with this local C2v2/GPU command.
Inside that shell, set the four non-secret values from this installation
(replace the uppercase placeholders before running):

~~~sh
export DEPLOYMENT_ID='YOUR_32_LOWERCASE_HEX_ID'
export ORIGIN='http://127.0.0.1:WEB_PORT'
export APPLICATION='/csp/chronos/'
export BUNDLE_SHA256='YOUR_64_CHARACTER_BUNDLE_HASH'
~~~

These variables are not inherited automatically from the host. Keep this shell
for the commands below. Use `exit` when finished; this does not stop the engine.

## 1. Inspect before creating a case

~~~sh
python3 -B /opt/chronos/deployment/jury_case.py inspect \
  --deployment-id "$DEPLOYMENT_ID" --case earliest \
  --origin "$ORIGIN" --application "$APPLICATION" \
  --manifest-sha256 "$BUNDLE_SHA256"
~~~

The wrapper verifies the source manifest and all read-only aliases, then compiles
the two console helpers into %SYS. Inspection reads application state and creates
no accounts, orders or model requests. BOUND means matching installation bindings;
runtime_ready must be true before seeding. Null means readiness was not sampled.
Actual global mappings, private database resource and journaling are checked.

## 2. Explicitly prepare owned synthetic history

~~~sh
python3 -B /opt/chronos/deployment/jury_case.py prepare \
  --deployment-id "$DEPLOYMENT_ID" --case earliest \
  --origin "$ORIGIN" --application "$APPLICATION" \
  --manifest-sha256 "$BUNDLE_SHA256" \
  --authorize-prepare-id "$DEPLOYMENT_ID"
~~~

Preparation writes one original simulator attempt, closes it as finally rejected
and queries it again. The native helper independently obtains the configured
provider's snapshot and receipt, registers the effect and verifies its final
rejection. No browser/model receipt is trusted. PREPARED is not an AI decision.

Repeating an already prepared/issued case reads existing state without reseeding.
An owned partial preparation may finish the same registration/evidence step;
conflicting, accepted or extended history cannot be overwritten. No clock, catalog,
quota or state is reset, and partial records remain available for inspection.

## 3. Request one proposal, explicitly

~~~sh
python3 -B /opt/chronos/deployment/jury_case.py propose \
  --deployment-id "$DEPLOYMENT_ID" --case earliest \
  --origin "$ORIGIN" --application "$APPLICATION" \
  --manifest-sha256 "$BUNDLE_SHA256" \
  --authorize-model-id "$DEPLOYMENT_ID"
~~~

This can consume the selected provider allowance, including the explicitly
approved monetary budget for the optional cloud route. It does not approve a
recovery. REQUEST_ISSUED is recorded before calling the queued workflow; the
runtime lifecycle lock is released before waiting for its worker. The decision
ID is stable for the deployment/case, including after a lost or delayed response.

workflow_requests counts calls made by this invocation to the workflow entry,
not actual model requests or tokens. Null means the command outcome was not
observed. inference_may_have_run preserves uncertainty; true does not prove
successful inference. Neither field grants dispatch authority.

## 4. Read the same decision after an uncertain response

~~~sh
python3 -B /opt/chronos/deployment/jury_case.py status \
  --deployment-id "$DEPLOYMENT_ID" --case earliest \
  --origin "$ORIGIN" --application "$APPLICATION" \
  --manifest-sha256 "$BUNDLE_SHA256"
~~~

Status reads the ledger without requiring a running production/open recovery gate.
It still requires the correct IRIS instance and source/installation binding.
It neither reclaims an inference ticket nor resolves a decision, renews an
allowance or submits a recovery.

REQUEST_OUTCOME_UNCERTAIN means a fenced request has no observed ledger result.
Absence never permits a retry. OUTCOME_UNCERTAIN_USE_STATUS means the command's
own response was unavailable/untrustworthy. REJECTED_STATE_PRESERVED and
PREPARATION_PARTIAL require inspection, not deletion.

DECISION_AVAILABLE only means a ledger record exists: it may be pending, blocked,
expired or completed with an error. Exit zero means an observation was returned,
not that AI succeeded. Use decision_id in the authenticated review screen and
inspect the actual result. Only the separate human review/confirmation path may
approve a recovery and verify synthetic acceptance/delivery. There is no approval,
reservation or Submit command here.

## Evidence boundary

Offline tests simulate native-process replies for CLI behavior and use real local
SQLite for the seed. They do not prove native compilation or locks/fences in IRIS.
Before jury delivery, test the final bundle on IRIS154: binding failures,
preparation/readback, interrupted preparation, simultaneous requests, lost replies
before/after workflow dispatch, reads concurrent with issuance, stopped-production
status, accepted/extended history and real-provider -> human -> effect -> readback.
No power-loss durability or end-to-end success is claimed by this source change.

## Queue and inventory case (introduced in source 125)

Use `--case queue_inventory` in the same inspect/prepare/propose/status route.
It is CHR-C02 from the agreed scope. At introduction in source 125, the case had
only local SQLite/controlled-clock checks and native/UI validation was pending;
frozen 119 remains unchanged. Later run 135 supplied that historical native/UI
evidence. Run 337 repeated this case on frozen bundle 333 with one E1, two C2v2
turns, explicit confirmation and accepted synthetic B recovery read back after
reload. Neither later run rewrites the earlier records or proves physical delivery.

A costs 3 and would arrive at minute 15, within the deadline 20, but its queue 7
outlives inventory 6. B costs 6 within budget 8, accepts immediately if still fresh
and arrives9 minutes after its actual start. The branch engine computes the
inventory failure. Initial seeded history is deliberately closed before acceptance;
it is not evidence that a real original request waited7 minutes and lost inventory.

Do not wait until minute 7 to approve B: inventory already expires at 6. Preserve
the ordinary5-minute consent window and revalidate actual time. A delayed start
must shift the predicted arrival. After inventory expiry, neither old preview nor
re-seeding grants permission. Acceptance is distinct from simulated delivery;
local controlled-clock tests are not real elapsed-time/native runtime proof.


## Economy: queued acceptance is not immediate acceptance

The fixed `economy` case can select A, whose destination queue is 60 seconds.
After explicit confirmation, `UNKNOWN` with an empty reference is an admissible
observation while that original attempt is queued; it is not permission to retry.
Retain the returned operation and attempt IDs. Use **Read current shipment
operation** and **Query destination outcome** for the SAME operation after the
queue has elapsed; preserve uncertainty if a final outcome is still unavailable.
Do not repeat confirmation, seed another case or create a replacement operation.

The preview also has at most 60 seconds of validity, but that is a separate
authorization clock. Its expiry does not cancel a submission already admitted
to the destination. A read/query does not renew the preview or authorize dispatch.

Run 338's six-case observer stopped after economy confirmation because it
incorrectly required immediate ACCEPTED; the captured response was UNKNOWN.
That attempt remains incomplete. In continuation 342, the first authenticated
read already reported ACCEPTED; a subsequent explicit reconcile and readback
retained the same operation, attempt and non-empty reference. The readback did
not establish that the reconcile button first caused acceptance. Final independent
SQLite inspection found exactly one SUBMIT for that operation, with no reconfirmation.
The original failed observer record remains intact.
