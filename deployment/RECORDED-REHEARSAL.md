# Recorded rehearsal on real IRIS

**IRIS Chronos 1.1.0 - model-free local route.**
The native earliest rehearsal and four exact questions were exercised on IRIS 154, with authenticated desktop/mobile reads of its decision and receipt. The evidence index separates that run from wider case coverage. This isolated route uses real IRIS state and
captured model interpretations without loading a model or using a GPU. It is
not an online demo and does not establish an online-demo bonus. The
[live-model route](JURY-ROUTE.md) remains separate.

## What the reviewer can check

| Recorded | Must execute in the local application |
| --- | --- |
| Interpretation of four shipped customer messages | Current simulations, eligibility and selection |
| Explanation plans for four exact questions | Current evidence rendering and receipt reads |
| Original model completions and provenance | IRIS authentication, fresh preview, explicit approval and dispatch fencing |

The [eight SDK captures](evidence/fixture-bank-154-20261113/README.md) ran on AI
Hub 154 using synthetic inputs. Those captures did not run the installed
workflow or a browser journey. Replay generates no fresh model tokens. A new
AI Hub SDK session represents replay transport, not the original inference.
Acceptance at the synthetic destination does not prove physical delivery.

Supported cases: `economy`, `earliest`, `ambiguous`, `queue_inventory`.
The recorded interpretation does not dictate an action: native code computes
which options remain eligible. Changed wording or business facts are unsupported;
only the declared identifier/time adaptation is permitted.

Supported questions, exactly:

1. Why was this option recommended?
2. What is the current operation status?
3. Does acceptance prove physical delivery?
4. What can I do next?

Question buttons only prefill; submit explicitly. This mode does not interpret
free text or change preferences.

## 1. Prepare and verify files only

Use a trusted checkout, Python 3.11+ and a locally loaded, authorized AI Hub
154 image. Obtain the image through your own authorized InterSystems access
under its applicable terms; this route does not download or redistribute it.
See [image inspection and isolated storage](COMPOSE.md#licensed-image-and-isolated-storage).
Choose a new workspace with an existing parent, outside other projects, and
an unused loopback web port. Keep paths short on Windows.

In a new PowerShell window, fill these placeholders:

```powershell
$Python = 'ABSOLUTE_PATH_TO_VERIFIED_PYTHON_EXE'
$Source = 'ABSOLUTE_PATH_TO_TRUSTED_PRIVATE_CHECKOUT'
$Workspace = 'ABSOLUTE_PATH_TO_NEW_ISOLATED_WORKSPACE'
$Image = 'sha256:FULL_LOCALLY_INSPECTED_AI_HUB_154_IMAGE_ID'
$Port = 53135 # Replace if this loopback port is already in use.
$Evidence = Join-Path $Source 'deployment/evidence/fixture-bank-154-20261113'
$CorpusHash = '660b3bdd62126d8ca9f85ea48ceaca8359b29aec06f4b838575696c7bedeac1c'
$FixtureHash = 'a8a57eebd73547c0f2169f9f9f0dbe12662ec075507b91f3df198c798041287f'
if (Test-Path -LiteralPath $Workspace) { throw 'Preserve the existing workspace; do not overwrite it.' }
& $Python -B (Join-Path $Evidence 'verify.py')
if ($LASTEXITCODE -ne 0) { throw 'Capture evidence did not verify.' }
& $Python -B (Join-Path $Source 'deployment/jury_setup.py') prepare-recorded --workspace $Workspace --image $Image --port $Port --corpus (Join-Path $Evidence 'corpus.json') --corpus-sha256 $CorpusHash --capture-allowlist (Join-Path $Evidence 'evidence-allowlist.json')
if ($LASTEXITCODE -ne 0) { throw 'Stop and inspect this attempt; preserve partial output.' }
& $Python -B (Join-Path $Source 'deployment/jury_setup.py') verify --workspace $Workspace
if ($LASTEXITCODE -ne 0) { throw 'The prepared workspace did not verify.' }
```

Require `FILES_PREPARED_NOT_INSTALLED` and `RECORDED_FIXTURE_SETUP_ONLY`.
These commands create source/staging files and two planned profiles. They start
no services, create no accounts and initialize no quotas. The capture allowlist
is reviewed separately from the corpus. Hashes do not independently prove the
historical inference took place.

The workspace contains `bundle`, `stage`, `profiles`, `fixtures`, `chat-state`
and `jury-workspace.json`. There is no model cache or model-home directory.
The pristine verifier is for unused files only; it deliberately rejects a
workspace after runtime state has been created.

## 2. Inspect the exact Compose layout

After successful pristine verification, retain the receipt and inspect its
non-secret environment. Set only the verified bindings:

```powershell
$Receipt = Get-Content -LiteralPath (Join-Path $Workspace 'jury-workspace.json') -Raw | ConvertFrom-Json
$Receipt.environment | Format-List
foreach ($Setting in $Receipt.environment.PSObject.Properties) {
    Set-Item -LiteralPath ('Env:' + $Setting.Name) -Value ([string]$Setting.Value)
}
$Id = $Receipt.deployment_id
$Origin = $Receipt.origin
$BundleHash = $Receipt.bundle_manifest_sha256
$Bundle = Join-Path $Workspace 'bundle'
$Stage = Join-Path $Workspace 'stage'
$Inputs = Join-Path $Workspace 'profiles'
$E1Hash = $Receipt.e1_profile_sha256
$C2Hash = $Receipt.c2_profile_sha256
Set-Location -LiteralPath $Bundle
$ComposeFiles = @('-f','deployment/compose.yaml','-f','deployment/compose.web-local.yaml','-f','deployment/compose.replay.yaml')
function Dc { & docker compose @ComposeFiles --profile recorded-fixture @args }
Dc config --quiet
if ($LASTEXITCODE -ne 0) { throw 'Compose configuration failed; do not start it.' }
Dc config --format json
if ($LASTEXITCODE -ne 0) { throw 'Could not inspect the resolved configuration.' }
```

Inspect the result: exactly `iris`, `guard` and `conversation-guard`; no model
service, GPU reservation, Docker socket or privileged container. Code mounts
are read-only. `CHRONOS_REPLAY_FIXTURES` is mounted read-only in IRIS; the guards
use separate owned state directories. Their listeners stay on IRIS's loopback.
Only the web gateway is published, on `127.0.0.1:$Port`; other IRIS gateway
routes are also reachable on this PC. Keep these same three Compose files and
deployment bindings in every subsequent command.

## 3. Install disabled, then initialize two quotas once

This step intentionally changes from file preparation to a native laboratory
installation. Start only the IRIS engine and require `ENGINE_READY` from the
[engine-health check](JURY-ROUTE.md#2-fix-the-complete-compose-layout-before-engine-creation).
Use **this guide's `Dc` function**, not the live route's five-file definition.

Follow [native inspect/apply and private access](JURY-ROUTE.md#3-install-disabled-and-prepare-private-access)
with the retained `$Id`, `$Origin`, `$BundleHash` and `$Stage`. Require
`NATIVE_INSTALLED_DISABLED`. Set credentials directly in IRIS; do not put them
in guides, receipts, recordings or chat. Keep the web route disabled during
configuration.

Replace the live route's Ollama allowance commands with these preparations.
The limits are replay request caps, not inference counts:

```powershell
$ReplayEvidence = @('--corpus','/opt/chronos/fixtures/corpus.json','--evidence-allowlist','/opt/chronos/fixtures/evidence-allowlist.json','--corpus-sha256',$CorpusHash,'--fixture-sha256',$FixtureHash)
Dc exec -T --user irisowner iris /usr/bin/python3 -B /opt/chronos/deployment/replay_provider.py prepare --deployment-id $Id --authorize-id $Id --request-limit 12 --contract e1 --runtime /opt/chronos/runtime @ReplayEvidence
if ($LASTEXITCODE -ne 0) { throw 'Inspect the retained E1 state; do not initialize it again.' }
Dc exec -T --user irisowner iris /usr/bin/python3 -B /opt/chronos/deployment/replay_provider.py prepare --deployment-id $Id --authorize-id $Id --request-limit 24 --contract c2-v2 --runtime /opt/chronos/conversation-runtime @ReplayEvidence
if ($LASTEXITCODE -ne 0) { throw 'Inspect the retained C2 state; do not initialize it again.' }
Dc exec -T --user irisowner iris /usr/bin/python3 -B /opt/chronos/deployment/replay_provider.py status --deployment-id $Id --contract e1 --runtime /opt/chronos/runtime
Dc exec -T --user irisowner iris /usr/bin/python3 -B /opt/chronos/deployment/replay_provider.py status --deployment-id $Id --contract c2-v2 --runtime /opt/chronos/conversation-runtime
```

Require each returned profile hash to match `$E1Hash` or `$C2Hash`. E1 owns
`fixture-provider`; C2 owns `fixture-conversation-provider` in its separate
runtime. Existing or partial state must be inspected, never deleted or reset
to obtain a fresh allowance. Status is not inference or readiness proof.

Use the existing [native provider and chat configuration commands](JURY-ROUTE.md#4-prepare-two-allowances-once-and-configure-both-contracts)
with those hashes. Configure E1 before C2. Require `CONFIGURED` and the expected
deployment/profile hashes from each native configuration. Those receipts do not
include the execution mode or corpus hashes: check `mode: RECORDED_FIXTURE` and
the matching corpus/fixture hashes in each `replay_provider.py status` result's
`native_configuration`, then check the signed-in session's execution evidence.
Do not execute that section's live `local_provider.py` or
`conversation_provider.py` preparations.

Start only the two recorded transports:

```powershell
Dc up -d guard conversation-guard
if ($LASTEXITCODE -ne 0) { throw 'Inspect the existing services; do not change mode or bindings.' }
```

No model warmup applies to this mode. Continue with the **first production start
and native web enable** commands in [the connection section](JURY-ROUTE.md#5-warm-up-first-start-production-and-log-in-before-any-case),
omitting its model startup and `model_readiness.py` warmup block. Require the
documented native/web readbacks, then sign in directly in the browser.
For an existing stopped deployment, use [native resume](NATIVE-RESUME.md)
instead of requesting its first start again.

## 4. Run the limited rehearsal and close it

Use the [case inspection/preparation/proposal sequence](JURY-ROUTE.md#6-six-cases-one-at-a-time)
with one of the four supported cases. The clock still runs; expiry, changed
facts or unsupported input must be refused. Start with `queue_inventory`.
The signed-in interface must state **Recorded interpretation · current IRIS
checks · 0 fresh inference calls**. Ask only the four questions above.

Check the actual decision and evidence. For an actionable proposal, obtain a
fresh preview and confirm once as Operator. Read the same operation and receipt.
An ambiguous priority remains HOLD. Reader must not approve; a stale preview
must not submit; an uncertain original acceptance must block recovery. Repeated
confirmation must not create another accepted effect. These are acceptance
checks to execute, not claims that this new route already passed them.

Finally use the [shared sign-out, account/route closure and service shutdown block](JURY-ROUTE.md#7-close-access-and-stop-only-this-deployment)
with **this guide's `Dc` function** and the original deployment bindings.
It discovers only this deployment's created sidecars and always attempts to
stop IRIS. This recorded layout has **no `model` service**; do not add the live
Compose files or select a model to close it. If access closure is uncertain,
leave the deployment stopped until account and route states are checked.

Retain the original state and receipts; never use `down -v` or another project's
containers/storage. A stopped container is not proof of disabled accounts or
routes. The full recorded native and browser route remains pending until
observed results are preserved.
