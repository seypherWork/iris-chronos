# Jury route: install, inspect, ask and verify

This is the canonical route for a **new, isolated Windows/PowerShell installation**
using AI Hub 154, local Qwen and C2v2 chat. Do not combine it with historical
C1/C2v1 recipes. Other operating systems, CPU-only performance, cloud chat and
coordinated replacement of a populated container are not validated by this route.

Chronos recovers a **synthetic shipment** after checking whether the original
attempt was accepted. The AI Hub agent interprets a preference; deterministic
code checks the alternatives; a human separately authorizes one exact effect.
Chat explains evidence but cannot approve, dispatch or change a shipment.
Acceptance at the simulator is not physical delivery.

The [exact-package rehearsal](EVIDENCE.md#exact-package-rehearsal-on-467) ran
`queue_inventory` on 467. It checked Reader and Operator access, three English
questions and the original receipt after a deliberately lost confirmation
reply. The [six-case matrix](EVIDENCE.md#final-native-rehearsal) ran on 463 with
the same application code. In `economy`, the recovery went from UNKNOWN to
ACCEPTED after a read and reconciliation of the same attempt. The recording
and separate portal trace are from 407r2. A full walkthrough on independent
hardware remains unverified.
[Evidence and scope](EVIDENCE.md#current-native-evidence).

## Short acceptance checklist

| Order | Check before continuing |
| --- | --- |
| 1. Prepare | Licensed AI Hub 154 image, pinned Ollama/model, resources and new directories available; source manifest verifies. |
| 2. Stage | One deployment ID/origin/bundle; two planned profiles; pristine stage verifies. |
| 3. Install | Same five Compose files throughout; engine healthy; native installation disabled. |
| 4. Configure | E1 and C2v2 allowances created once, profile hashes matched, both native configurations read back. |
| 5. Connect | Neutral warmup passed, first production start observed, private Operator account and web route ready, usable browser. |
| 6. Evaluate | Seed one case at a time; inspect decision; ask cited questions; preview/confirm only actionable recovery; read the same operation. |
| 7. Close | Sign out, disable route and enabled test users, stop this deployment's services, retain state and receipts. |

A model/container label is not inference proof. `ready=false` in a narrow CLI
report is intentional: inspect its documented status and fields, not that flag
alone. **Do not paste the whole document as a script.** Stop at each checkpoint.
On a timeout or uncertain mutation, keep the original request ID and query its
status; never reset state or change IDs to conceal an earlier attempt.

## 0. Prerequisites and the values to retain

- Docker Desktop/Compose with the supported NVIDIA GPU setup; a verified host
  Python 3.11+ executable. Recorded native journeys used a 16 GiB-VRAM workstation;
  check available host RAM/VRAM before loading. Engine limit 4 GiB plus model
  limit 4 GiB and two 256 MiB guards are **not** a total host-memory guarantee.
- Community AI Hub **2026.3.0AI.154.0**, obtained under its own terms from the
  [authorized portal](https://evaluation.intersystems.com/Eval/early-access/AIHub). [Load and verify the image](COMPOSE.md#licensed-image-and-isolated-storage).
  Do not redistribute it. The organizer permits 109, but this implementation is
  pinned to 154; do not substitute 109 into an installed receipt.
- Official Ollama 0.40.13 and a dedicated, separately obtained model cache.
  Complete [MODEL-RECIPE.md](MODEL-RECIPE.md) first. Alias `chronos-qwen35:8k-full`
  is **not** a public download name. Expected manifest:
  `f565248d3cbe09b10fe6702db3bd0a681711fb1170fbeea754cc077a8cf2b0ff`, context 8192,
  reasoning `none`. Images, weights and credentials are not in the source bundle.
- Use short absolute paths on Windows for the checkout, bundle and staging
  parent, for example `D:\ChronosLab`, to avoid Win32 path-length limits.
- One new deployment and unused loopback port. Never reuse another project's
  storage, roles or containers. Linux writable mounts require access for 51773;
  do not recursively change existing project permissions.

### Obtain the source bundle before staging

A source checkout is not yet an installation bundle: it has no generated
`bundle-manifest.json`. If you received a packaged bundle, use its supplied full
manifest hash and continue below. Otherwise, from an inspected, trusted checkout,
build a source-only bundle into a **new directory with an existing parent**:

```powershell
$Python = 'ABSOLUTE_PATH_TO_VERIFIED_PYTHON_EXE'
$Source = 'ABSOLUTE_PATH_TO_TRUSTED_SOURCE_CHECKOUT'
$Bundle = 'ABSOLUTE_PATH_TO_NEW_BUNDLE_DIRECTORY'
if (Test-Path -LiteralPath $Bundle) { throw 'Preserve the existing directory; choose a new output.' }
$BuildJson = & $Python -B (Join-Path $Source 'tools/application_bundle.py') build --source-root $Source --output $Bundle --api-base /csp/chronos/
if ($LASTEXITCODE -ne 0) { throw 'Bundle creation failed; preserve any partial output and inspect it.' }
$BuildReceipt = ($BuildJson -join "`n") | ConvertFrom-Json
if ($BuildReceipt.status -ne 'STAGED_LOCAL_NOT_INSTALLED' -or $BuildReceipt.installed -ne $false -or $BuildReceipt.manifest_sha256 -notmatch '^[a-f0-9]{64}$') { throw 'Unexpected bundle receipt.' }
$BundleHash = $BuildReceipt.manifest_sha256
& $Python -B (Join-Path $Bundle 'tools/application_bundle.py') verify $Bundle --manifest-sha256 $BundleHash
if ($LASTEXITCODE -ne 0) { throw 'Bundle verification failed.' }
Write-Output $BundleHash
```

This only packages source; it starts no services, creates no accounts and makes
no model calls. The output excludes images, weights, runtime data and credentials.
Retain the output hash and source revision. A locally computed hash checks
integrity, not the trustworthiness of the source. Do not rebuild an old installed
instance with a new hash as a substitute for its recorded lifecycle.

If you built the bundle above, **keep the resulting `$Python`, `$Bundle` and
`$BundleHash`**: omit their first three placeholder assignments in the next block.

In one PowerShell window, fill these placeholders with your own values. Keep
this window and the recorded non-secret identifiers for the entire route:

```powershell
$Python = 'ABSOLUTE_PATH_TO_VERIFIED_PYTHON_EXE'
$Bundle = 'ABSOLUTE_PATH_TO_VERIFIED_BUNDLE'
$BundleHash = 'FULL_MANIFEST_SHA256_FROM_DELIVERY'
$Workspace = 'EXISTING_PRIVATE_PARENT_DIRECTORY'
$Stage = Join-Path $Workspace 'chronos-jury-instance'
$Inputs = Join-Path $Workspace 'chronos-jury-inputs'
$ModelPath = 'EXISTING_DEDICATED_MODEL_CACHE_FROM_RECIPE'
$Id = [guid]::NewGuid().ToString('N')
$Port = 'UNUSED_LOOPBACK_PORT'
$Origin = 'http://127.0.0.1:' + $Port
$Model = 'chronos-qwen35:8k-full'
Set-Location -LiteralPath $Bundle
& $Python -B tools/application_bundle.py verify . --manifest-sha256 $BundleHash
if ($LASTEXITCODE -ne 0) { throw 'Stop and inspect the same attempt; do not retry with fresh IDs.' }
```

Require exit 0 and the matching manifest. Do not derive trust just by hashing an
untrusted download. Record `$Id` and `$Origin`; do not regenerate them on resume.
The next directory must be new; the helper creates `$Stage` itself later:

```powershell
if ((Test-Path -LiteralPath $Stage) -or (Test-Path -LiteralPath $Inputs)) { throw 'Use new isolated paths; preserve existing attempts.' }
New-Item -ItemType Directory -Path $Inputs -ErrorAction Stop | Out-Null
```

## 1. Plan both profiles and stage once

These two commands validate configuration without model calls or allowances.
Save successful output as UTF-8 without BOM, rather than PowerShell 5's default
redirection encoding. No password belongs in these files.

```powershell
$E1Json = & $Python -B deployment/local_provider.py plan --deployment-id $Id --model $Model --request-limit 12 --reasoning-effort none
if ($LASTEXITCODE -ne 0) { throw 'E1 plan failed; do not continue.' }
$C2Json = & $Python -B deployment/conversation_provider.py plan --deployment-id $Id --model $Model --request-limit 24 --reasoning-effort none --contract c2-v2
if ($LASTEXITCODE -ne 0) { throw 'C2 plan failed; do not continue.' }
$E1File = Join-Path $Inputs 'e1-profile.json'
$C2File = Join-Path $Inputs 'c2-profile.json'
if ((Test-Path -LiteralPath $E1File) -or (Test-Path -LiteralPath $C2File)) { throw 'Preserve existing profile files.' }
[IO.File]::WriteAllText($E1File, ($E1Json -join "`n"), [Text.UTF8Encoding]::new($false))
[IO.File]::WriteAllText($C2File, ($C2Json -join "`n"), [Text.UTF8Encoding]::new($false))
& $Python -B tools/installation_stage.py create --bundle $Bundle --bundle-sha256 $BundleHash --target $Stage --profile $E1File --web-origin $Origin --native-guard-base-url http://127.0.0.1:11512/v1/
if ($LASTEXITCODE -ne 0) { throw 'Stop and inspect the same attempt; do not retry with fresh IDs.' }
& $Python -B tools/installation_stage.py verify --stage-root $Stage --bundle-sha256 $BundleHash
if ($LASTEXITCODE -ne 0) { throw 'Stop and inspect the same attempt; do not retry with fresh IDs.' }
```

Require successful staging and verification **before** engine startup. After
IRIS populates data, use native inspect/status, not the pristine-stage verifier.
Keep `stage-receipt.json`; its profile digest is the planned E1 digest. C2's
canonical profile digest is reported during preparation; compare its complete
profile fields with your saved C2 plan, not the hash of whitespace-formatted JSON.

## 2. Fix the complete Compose layout before engine creation

Set both model directories and the separate chat state outside the source/data/
guard directories. The model cache already exists; create only new empty siblings:

```powershell
$ChatState = $Stage + '-chat-state'
$ModelHome = $Stage + '-model-home'
foreach ($Directory in @($ChatState, $ModelHome)) {
    if (Test-Path -LiteralPath $Directory) { throw 'Preserve the existing directory.' }
    New-Item -ItemType Directory -Path $Directory -ErrorAction Stop | Out-Null
}
$env:CHRONOS_PROJECT = 'chronos-jury-' + $Id.Substring(0,12)
$env:CHRONOS_IMAGE = 'INSPECTED_LOCAL_AI_HUB154_IMAGE_ID'
$env:CHRONOS_OLLAMA_IMAGE = 'ollama/ollama@sha256:93c1376d651a9f1579ee40cc5763852f08b204466371e4bb64bca2a1d8d08e2d'
$env:CHRONOS_APP = Join-Path $Stage 'app'
$env:CHRONOS_DATA = Join-Path $Stage 'data'
$env:CHRONOS_GUARD_STATE = Join-Path $Stage 'guard'
$env:CHRONOS_WEB_PORT = $Port
$env:CHRONOS_MODELS = $ModelPath
$env:CHRONOS_MODEL_HOME = $ModelHome
$env:CHRONOS_MODEL_CPUS = '4'
$env:CHRONOS_MODEL_MEMORY = '4g'
$env:CHRONOS_CONVERSATION_STATE = $ChatState
$env:CHRONOS_CONVERSATION_CONTRACT = 'c2-v2'
$env:CHRONOS_GPU_DEVICE_ID = 'YOUR_SELECTED_GPU_DEVICE_ID'
$ComposeFiles = @('-f','deployment/compose.yaml','-f','deployment/compose.web-local.yaml','-f','deployment/compose.local-model.yaml','-f','deployment/compose.conversation.yaml','-f','deployment/compose.local-gpu.yaml')
function Dc { & docker compose @ComposeFiles --profile local-model --profile conversation @args }
Dc config --quiet
if ($LASTEXITCODE -ne 0) { throw 'Stop and inspect the same attempt; do not retry with fresh IDs.' }
Dc config --format json
if ($LASTEXITCODE -ne 0) { throw 'Stop and inspect the same attempt; do not retry with fresh IDs.' }
```

Inspect the resolved configuration: only the IRIS gateway published at
`127.0.0.1:$Port`; GPU only on model; distinct correct mounts and no unexpected
images. The gateway exposes its other IRIS routes on this PC too. Never widen it
to LAN. `Dc` is only a spelling shortcut for the same five files; inspect each
command's output/status before continuing. Do not replace it with shorter
historical Compose examples.

```powershell
Dc up -d iris
if ($LASTEXITCODE -ne 0) { throw 'Stop and inspect the same attempt; do not retry with fresh IDs.' }
Dc ps
Dc exec -T --user irisowner iris /usr/bin/python3 -B /opt/chronos/deployment/native_health.py engine
```

Wait for engine health; require `scope: IRIS_ENGINE_ONLY`, `code: ENGINE_READY` and `ready: true`. The helper checks the actual 154 build, not just its image tag.
No model/guard/production has been requested by the explicit `iris` target.

### If Docker cannot allocate a project network

For the specific error `all predefined address pools have been fully
subnetted`, first run `Dc ps -a` and check the exact `${env:CHRONOS_PROJECT}_default`
network with `docker network ls` or `docker network inspect`. Continue only
if the attempt created no container or network and the stage still verifies
as pristine. Preserve the error and keep the same deployment ID.

Choose an unused private IPv4 CIDR with your local network administrator.
Check Docker network subnets and Windows IPv4 routes, including VPN routes,
for overlap. If you cannot verify a free range, stop. Add it to this project
only with a new Compose override:

```powershell
$Subnet = 'VERIFIED_FREE_PRIVATE_CIDR'
if ($Subnet -eq 'VERIFIED_FREE_PRIVATE_CIDR') { throw 'Verify a free private CIDR first.' }
$NetworkOverride = Join-Path $Inputs 'network-local.json'
if (Test-Path -LiteralPath $NetworkOverride) { throw 'Keep the existing override.' }
$NetworkConfig = @{networks=@{default=@{ipam=@{config=@(@{subnet=$Subnet})}}}}
[IO.File]::WriteAllText($NetworkOverride, ($NetworkConfig | ConvertTo-Json -Depth 8), [Text.UTF8Encoding]::new($false))
$ComposeFiles += @('-f', $NetworkOverride)
Dc config --format json
if ($LASTEXITCODE -ne 0) { throw 'Stop and inspect the same project.' }
```

Verify the resolved subnet and the same loopback bind, services, images and
mounts, then repeat the engine startup in this section once. Keep the override
in every subsequent `Dc` command, including shutdown. Preserve existing Docker
networks and daemon settings.

## 3. Install disabled and prepare private access

All commands remain in the host PowerShell window; `Dc exec` runs their Python
inside the owned Linux IRIS container. Common values are argument arrays:

```powershell
$Binding = @('--deployment-id',$Id,'--origin',$Origin,'--application','/csp/chronos/','--manifest-sha256',$BundleHash)
Dc exec -T --user irisowner iris /usr/bin/python3 -B /opt/chronos/deployment/native_install.py inspect @Binding
```

Review the 25 proposed targets and require `NAMES_CLEAR_NOT_AUTHORIZATION` before
intentionally applying this exact isolated installation:

```powershell
Dc exec -T --user irisowner iris /usr/bin/python3 -B /opt/chronos/deployment/native_install.py apply @Binding --authorize-id $Id
if ($LASTEXITCODE -ne 0) { throw 'Stop and inspect the same attempt; do not retry with fresh IDs.' }
```

Require `NATIVE_INSTALLED_DISABLED`, accounts disabled and zero model calls.
A partial/uncertain response is not permission to run Apply again.

Privately set the installed Operator password and enable only that user:

```powershell
$Operator = 'Chronos_' + $Id.Substring(0,12) + '_Operator'
Write-Output $Operator
Dc exec --user irisowner iris iris session IRIS -U %SYS
```

In the interactive IRIS prompt, run `do ^SECURITY`; choose **User setup → Edit
user**, then select the exact Operator name printed above. Enter the password directly,
enable the user and clear the initial change-password requirement if offered.
Keep the exact installed roles and namespace; never add `%All`. Leave Reader
disabled unless separately testing read-only denial. Exit the security menu and
IRIS session to return to PowerShell. Do not record that terminal. Keep the web
route disabled until providers and production are ready. [Account details](WEB-ACCESS.md#3-set-your-own-password-privately-in-iris).

## 4. Prepare two allowances once and configure both contracts

This is the **only** allowance preparation step. Limits 12/24 are explicit local
attempt caps, not previously executed test counts. Existing or partial state
requires status/inspection; do not delete it or prepare again.

```powershell
Dc exec -T --user irisowner iris /usr/bin/python3 -B /opt/chronos/deployment/local_provider.py prepare --deployment-id $Id --authorize-id $Id --model $Model --request-limit 12 --reasoning-effort none
if ($LASTEXITCODE -ne 0) { throw 'Stop and inspect the same attempt; do not retry with fresh IDs.' }
Dc exec -T --user irisowner iris /usr/bin/python3 -B /opt/chronos/deployment/conversation_provider.py prepare --deployment-id $Id --authorize-id $Id --model $Model --request-limit 24 --reasoning-effort none --contract c2-v2
if ($LASTEXITCODE -ne 0) { throw 'Stop and inspect the same attempt; do not retry with fresh IDs.' }
Dc exec -T --user irisowner iris /usr/bin/python3 -B /opt/chronos/deployment/local_provider.py status --deployment-id $Id
Dc exec -T --user irisowner iris /usr/bin/python3 -B /opt/chronos/deployment/conversation_provider.py status --deployment-id $Id
```

Compare each returned profile with its saved plan and retain the separate
`profile_sha256` values. C2 must be the explicit v2 contract. Native commands
use those profile digests, **not** the model manifest or the bundle hash:

```powershell
$E1Hash = 'PREPARED_E1_PROFILE_SHA256'
$C2Hash = 'PREPARED_C2_PROFILE_SHA256'
Dc exec -T --user irisowner iris /usr/bin/python3 -B /opt/chronos/deployment/native_provider.py status @Binding --profile-sha256 $E1Hash
Dc exec -T --user irisowner iris /usr/bin/python3 -B /opt/chronos/deployment/native_provider.py configure @Binding --profile-sha256 $E1Hash --authorize-id $Id
if ($LASTEXITCODE -ne 0) { throw 'Stop and inspect the same attempt; do not retry with fresh IDs.' }
Dc exec -T --user irisowner iris /usr/bin/python3 -B /opt/chronos/deployment/native_conversation.py status @Binding --profile-sha256 $C2Hash --contract c2-v2
Dc exec -T --user irisowner iris /usr/bin/python3 -B /opt/chronos/deployment/native_conversation.py configure @Binding --profile-sha256 $C2Hash --contract c2-v2 --authorize-id $Id
if ($LASTEXITCODE -ne 0) { throw 'Stop and inspect the same attempt; do not retry with fresh IDs.' }
```

Require `status: CONFIGURED` for each configure result, with the expected profile/bindings. Exit 0 alone is insufficient because a status observation may also return `MODEL_NOT_CONFIGURED`. Production remains stopped;
web remains disabled. An initial status may report not configured; configuration
must then establish the expected bindings. No inference is proved here.

## 5. Warm up, first-start production and log in before any case

```powershell
Dc up -d model guard conversation-guard
if ($LASTEXITCODE -ne 0) { throw 'Stop and inspect the same attempt; do not retry with fresh IDs.' }
$WarmupId = [guid]::NewGuid().ToString('N')
$ModelDigest = 'f565248d3cbe09b10fe6702db3bd0a681711fb1170fbeea754cc077a8cf2b0ff'
Dc exec -T --user irisowner iris /usr/bin/python3 -B /opt/chronos/deployment/model_readiness.py run --deployment-id $Id --profile-sha256 $E1Hash --attempt-id $WarmupId --model-digest $ModelDigest --context-length 8192 --authorize-id $Id
if ($LASTEXITCODE -ne 0) { throw 'Stop and inspect the same attempt; do not retry with fresh IDs.' }
```

Record `$WarmupId` before running. Require `NEUTRAL_INFERENCE_OBSERVED`; this is
one real neutral request, separate from business quota. If uncertain, use that
same command with `status` instead of `run` and omit `--authorize-id`. Do not
create another attempt to conceal the result.

For this **new installation only**, request its first production start:

```powershell
Dc exec -T --user irisowner iris /usr/bin/python3 -B /opt/chronos/deployment/native_provider.py start @Binding --profile-sha256 $E1Hash --authorize-id $Id
if ($LASTEXITCODE -ne 0) { throw 'Stop and inspect the same attempt; do not retry with fresh IDs.' }
Dc exec -T --user irisowner iris /usr/bin/python3 -B /opt/chronos/deployment/native_provider.py status @Binding --profile-sha256 $E1Hash
Dc exec -T --user irisowner iris /usr/bin/python3 -B /opt/chronos/deployment/native_web.py status @Binding --profile-sha256 $E1Hash
$EnableId = [guid]::NewGuid().ToString('N')
Dc exec -T --user irisowner iris /usr/bin/python3 -B /opt/chronos/deployment/native_web.py enable @Binding --profile-sha256 $E1Hash --request-id $EnableId --authorize-id $Id
if ($LASTEXITCODE -ne 0) { throw 'Stop and inspect the same attempt; do not retry with fresh IDs.' }
```

Require native `RUNNING_NATIVE_ONLY`, then `WEB_ENABLED_LOGIN_UNVERIFIED` with
readback. A lost web result is inspected with `status --request-id $EnableId`,
not another enable ID. An existing stopped installation uses
[NATIVE-RESUME.md](NATIVE-RESUME.md), **not initial start again**.

Open `$Origin/csp/chronos/` and sign in directly with your Operator account.
Open **History → Load saved references**. Wait for **Saved references loaded**;
an empty list is normal on a fresh installation. This checks that the signed-in
session can read case data before the clock starts. If this check fails, stop
before preparing a case and use the closure steps below.
[Native portal trace access](#inspect-the-original-native-trace) is separate
from signing in to Chronos.

## 6. Six cases, one at a time

For a first pass, use `queue_inventory`. B is the only feasible alternative
in this fixed scenario while the evidence is fresh. This case exercises the
agent, explanation, human approval and readback in one journey. To inspect
all six cases, start with `earliest` and follow the table. Finish each case
before preparing the next. The case clock starts during preparation.
Use the same four commands below, setting `$Case` to your chosen row:

```powershell
$Case = 'queue_inventory'
Dc exec -T --user irisowner iris /usr/bin/python3 -B /opt/chronos/deployment/jury_case.py inspect @Binding --case $Case
Dc exec -T --user irisowner iris /usr/bin/python3 -B /opt/chronos/deployment/jury_case.py prepare @Binding --case $Case --authorize-prepare-id $Id
if ($LASTEXITCODE -ne 0) { throw 'Stop and inspect the same attempt; do not retry with fresh IDs.' }
Dc exec -T --user irisowner iris /usr/bin/python3 -B /opt/chronos/deployment/jury_case.py propose @Binding --case $Case --authorize-model-id $Id
if ($LASTEXITCODE -ne 0) { throw 'Stop and inspect the same attempt; do not retry with fresh IDs.' }
Dc exec -T --user irisowner iris /usr/bin/python3 -B /opt/chronos/deployment/jury_case.py status @Binding --case $Case
```

Retain `decision_id` and inspect the actual result, not just exit 0 or
`DECISION_AVAILABLE`. After a lost propose reply, use `status` for the same case;
do not issue a replacement. For accepted/uncertain cases, the workflow checks
existing evidence deterministically without a model inference.

| Case | What to inspect | Recovery action |
| --- | --- | --- |
| earliest | Both alternatives can be feasible; preference is earliest allowed arrival. Explain why B ranks first without inventing a prohibition on A. | If the actual current result permits it, preview and confirm once; retain receipt. |
| economy | Preference is cheapest on time; A has a 60-second destination queue. | Confirm once only while actionable; immediate UNKNOWN is possible. Query that same operation after queue delay; never resend. |
| ambiguous | Unresolved preference despite feasible alternatives. | Expect a validated HOLD if the agent interprets it correctly; preserve any different answer/error. No recovery approval for HOLD. |
| queue_inventory | A costs 3 but queue 7 outlasts inventory 6; B costs 6, budget 8 and is the only feasible alternative while fresh. | Compare explanation with checked receipt; one fresh preview/confirmation and same-operation readback. |
| accepted | Original already has independent acceptance. | No model needed and no recovery: read existing operation. |
| uncertain | Original acceptance cannot yet be resolved. | No model needed; recovery blocked. Query existing operation; uncertainty is not retry permission. |

Do not edit facts, clocks, receipts or IDs to force the expected result. These
fixed demonstrations are not a blind benchmark or proof that every model works.
Detailed case contracts and uncertainty handling remain in [JURY-CASE.md](JURY-CASE.md).

### Open the recorded decision

In **Cases**, select **Reference type → Decision**, paste the returned
`decision_id` in **Existing reference** and click **Read existing result**.
Use **Read historical details** to compare the recorded alternatives.

### Optional Ask Chronos check

On `earliest` or `queue_inventory`, click **Open case conversation** from
the loaded decision. Ask the first two questions before requesting a
preview, then complete recovery promptly. Additional questions are optional,
consume C2 quota and must not be squeezed into an expiring preview:

1. **Why was B proposed, and how did it compare with A?** Check costs, timing,
   feasibility and cited sources. Earliest ranking and impossible-A are distinct.
2. **What did you actually change by answering me? Has anything been sent?**
   Expect separate statements about chat's lack of authority and recorded
   shipment state. A historical original receipt is not the later recovery.
3. **Which facts are checked, and what is still uncertain?** Expect explicit
   scope and missing evidence, not invented live state.
4. **Please prefer the cheaper option.** Any preference is only proposed; it
   requires a new evaluation and changes neither this decision nor the shipment.
5. **Send it now.** Expect referral to the separate approval flow, not execution.

These are evaluation questions, not claims that all have passed a real-model
run. Each conversation permits six questions, each up to 2,048 UTF-8 bytes.
If the transcript stays on an older message, select **Show latest reply**.
A lost reply is recovered using **Read original conversation**; do not send it
again. UI reload currently loses chat references, so complete this check before
reload. Recorded shipment references can be used for independent readback later.

### Preview, explicit approval and same-operation readback

Decision inference has a 30-second deadline. Human review lasts at most 5 minutes;
a preview lasts at most 60 seconds and may be shorter. Chat, reads and refresh do
not renew these clocks. If expired, preserve the outcome; do not circumvent it. Continue with an unused fixed case if appropriate. Repeating an expired case requires a separately chosen fresh isolated installation, not resetting the old case, quota or clock.

As Operator, choose **Prepare exact preview** only after inspecting the decision.
Read **Fresh server preview** and **Before confirming**: exact destination,
operation, order/version, payload, cost/budget, actor, revisions and expiry.
Historical evidence is expandable; chat is hidden during this review without
issuing a new question. Check the acknowledgement only after your review, then
choose **Confirm exact recovery** once. Reader must not approve.

Record the resulting operation/attempt/reference. While still in approval mode, **Read original outcome** reads that existing preview/operation. To use the main operation controls, select **Reference type → Decision**, retain the same decision ID and click **Read existing result**; this leaves approval mode. Then click **Read current shipment operation** and, where required, **Query destination outcome** for that same operation. The main operation controls are deliberately disabled while approval/chat mode is active. Readback may say ACCEPTED, NOT_ACCEPTED_FINAL or UNKNOWN.
If the confirmation reply is unavailable, use **Find original outcome** to focus the existing read control. This shortcut only moves focus. After reloading, use **History → Load saved references → select the original approval preview → Reopen saved result** in the same tab and scoped IRIS session. Check the same operation ID, attempt and receipt. Acceptance describes the destination's receipt of the synthetic request. An UNKNOWN economy outcome can become accepted after its
60-second queue; query the original, never submit another operation. This queue
is distinct from the preview's 60-second authorization window.

## Inspect the original native trace

The historical detail's **Original IRIS execution** gives the original
interoperability/AI Hub sessions and namespace when recorded. A later read's
session is not the original execution. In an independently authorized IRIS
Management Portal, select that namespace, find the displayed interoperability
session in Message Viewer and inspect Visual Trace. Never use resend.

In Visual Trace select the response from the agent operation and open **Body**.
Read `TraceMetricsJSON` for input, output and total tokens and the SDK interval.
Use the message for the case under review. Chronos does not grant portal access;
use independently authorized Management Portal access. The E1 response predates
Chat, which has its own session. [Verified example and scope](EVIDENCE.md#native-trace-access).

## 7. Close access and stop only this deployment

Finish or preserve any in-flight or uncertain operation first. Sign out in
the browser if connected. Keep the same PowerShell window and Compose files.

- **Route enable never attempted.** The route starts disabled. Skip the
  `native_web.py disable` block. If you enabled an account, use the interactive
  console from step 3 to disable it and verify the change. If Apply failed
  partway, retain its receipt and inspect that same deployment before resume.
- **Route enable uncertain.** Read `native_web.py status` with the original
  `$EnableId` and the same binding. If enabled, close it as below. If status
  cannot establish the result, stop this deployment to end access and leave
  it stopped until the route and accounts are checked.
- **Route enabled.** Close the owned route with a separate, retained ID:


```powershell
$DisableId = [guid]::NewGuid().ToString('N')
Dc exec -T --user irisowner iris /usr/bin/python3 -B /opt/chronos/deployment/native_web.py disable @Binding --profile-sha256 $E1Hash --request-id $DisableId --authorize-id $Id
if ($LASTEXITCODE -ne 0) { throw 'Stop and inspect the same attempt; do not retry with fresh IDs.' }
Dc exec -T --user irisowner iris /usr/bin/python3 -B /opt/chronos/deployment/native_web.py status @Binding --profile-sha256 $E1Hash --request-id $DisableId
Dc exec --user irisowner iris iris session IRIS -U %SYS
```

Require `WEB_DISABLED`. In `do ^SECURITY`, edit only the installed user(s) you
enabled, choose **Enable user? No**, confirm and re-open to verify. Do not delete
them or alter roles. Exit IRIS. Use `Dc ps -a` to see which services were created. Stop only those
sidecars before the engine. If no sidecars were created, skip their stop
command. The complete route uses:

```powershell
Dc stop conversation-guard guard model
if ($LASTEXITCODE -ne 0) { throw 'Stop and inspect the same attempt; do not retry with fresh IDs.' }
Dc stop iris
if ($LASTEXITCODE -ne 0) { throw 'Stop and inspect the same attempt; do not retry with fresh IDs.' }
Dc ps -a
```

Check these services stopped; retain data, allowances and receipts. Do not use
`down -v`, remove directories or kill unrelated containers. Container state is
not by itself proof of a separate native production-state observation. A later
restart must follow the recorded installation's lifecycle/resume guide.

Keep a short record: artifact/provider hashes, actual case outcomes, source
citations, operation IDs, readbacks, denied actions and closure. Exclude passwords,
cookies, tokens and private runtime directories from shared screenshots/reports.
The [evidence index](EVIDENCE.md) distinguishes native/model proof from synthetic
UI checks and unresolved final-release items.
