# Native provider binding and first production start

> Installation command order: follow [JURY-ROUTE.md](JURY-ROUTE.md). This is a
> component reference, not an additional setup pass. Do not prepare allowances or
> perform initial production start again after completing the canonical route.

**Development route with native configuration and lifecycle evidence.**
Initial configuration/start checks first passed in laboratory 95. Later fresh
installations exercised the packaged lifecycle, and run 135 completed the native
model/browser workflow. Controlled engine-interruption checks 149/150 are separate
evidence on installation 145. See [validation scope](EVIDENCE.md).
Current installation/journey observations and remaining release checks are indexed in [EVIDENCE.md](EVIDENCE.md); older stage-specific pending statements are not current verdicts.
Never reset this command's initial-start fence; use [operational resume](NATIVE-RESUME.md)
for an existing installation.

This command completes the source link between [local provider preparation](LOCAL-PROVIDER.md) or the explicit
[cloud plan](CLOUD-PROVIDER.md) and [the first synthetic case](JURY-CASE.md). It is a trusted installation-console
tool. It does not enable users/web applications, publish ports, start model
containers, initialize/reset allowances or submit a workflow/recovery.

The executable examples below use the local E1 + C2v2 + loopback web + GPU layout.
Keep the complete file set chosen in [JURY-ROUTE.md](JURY-ROUTE.md): the examples already include conversation and GPU; do not append either twice. For cloud, follow [CLOUD-PROVIDER.md](CLOUD-PROVIDER.md) instead; do not retain the local-model/conversation/GPU overlay set. Use the original project, environment and bindings.


## Preconditions

- A new successful native installation using this exact bundle, recorded manifest
  digest, deployment ID, origin and application path. A receipt from another
  bundle is rejected; do not overwrite its digest.
- Exactly one immutable version 3 E1 provider and allowance prepared for that ID.
  Local mode uses the profile digest; cloud mode additionally binds the approved
  complete plan, including monetary policy. Keep the reported profile SHA-256;
  no credentials belong in these native commands. No fallback provider is used.
- Configuration and first-start actions require the owned web application to
  remain disabled. Existing database mappings, resource and journal setting,
  runtime source/data roots and web binding must still match.
- The CLI runs inside the owned Linux IRIS container. The native helper is compiled
  into `%SYS` and rejects web sessions, transactions, a different build or an
  identity other than the trusted `irisowner` console user.

The driver verifies the complete source bundle and mounted aliases first. The
native helper independently reads the actual installed provider/allowance before
using its model, reasoning setting and profile digest. It does not accept a
provider URL or model supplied by a browser. The native guard URL is fixed to
`http://127.0.0.1:11512/v1/`.

The driver carries its first observed `binding_sha256` into the native call and
exact action authorization. The helper compares it with a fresh observation
before its first configuration/start write; it never silently substitutes a new
same-model budget plan. It stores that binding in the durable provider fence and
checks current readback against it. The driver rereads provider state after the
call too. A changed observation is uncertain, not a reason to retry or roll back.
Native report schema v2 includes this observed binding; legacy fences are not
migrated. Read-only status from the web helper can inspect the current binding
without authorizing a mutation.

## Three separate actions

Use the same values obtained during installation/preparation. These actions
were executed with laboratory 95 bindings; the placeholders below are examples
for a new installation, not instructions to repeat its consumed first start.

Inspect, without an application configuration/start mutation:

```text
docker compose -f deployment/compose.yaml -f deployment/compose.web-local.yaml -f deployment/compose.local-model.yaml -f deployment/compose.conversation.yaml -f deployment/compose.local-gpu.yaml --profile local-model --profile conversation exec -T iris /usr/bin/python3 -B /opt/chronos/deployment/native_provider.py status --deployment-id DEPLOYMENT_ID --origin http://127.0.0.1:WEB_PORT --application /csp/chronos/ --manifest-sha256 BUNDLE_SHA256 --profile-sha256 PROFILE_SHA256
```

After explicitly approving this installation's configuration:

```text
docker compose -f deployment/compose.yaml -f deployment/compose.web-local.yaml -f deployment/compose.local-model.yaml -f deployment/compose.conversation.yaml -f deployment/compose.local-gpu.yaml --profile local-model --profile conversation exec -T iris /usr/bin/python3 -B /opt/chronos/deployment/native_provider.py configure --deployment-id DEPLOYMENT_ID --origin http://127.0.0.1:WEB_PORT --application /csp/chronos/ --manifest-sha256 BUNDLE_SHA256 --profile-sha256 PROFILE_SHA256 --authorize-id DEPLOYMENT_ID
```

After explicitly approving its first production start:

```text
docker compose -f deployment/compose.yaml -f deployment/compose.web-local.yaml -f deployment/compose.local-model.yaml -f deployment/compose.conversation.yaml -f deployment/compose.local-gpu.yaml --profile local-model --profile conversation exec -T iris /usr/bin/python3 -B /opt/chronos/deployment/native_provider.py start --deployment-id DEPLOYMENT_ID --origin http://127.0.0.1:WEB_PORT --application /csp/chronos/ --manifest-sha256 BUNDLE_SHA256 --profile-sha256 PROFILE_SHA256 --authorize-id DEPLOYMENT_ID
```

`status` does compile the fixed trusted console helpers and reads local SQLite
state; it is not a promise of zero filesystem writes. It does not require the
engine health gate used before mutation, but the IRIS process and correct source
binding must still be available. It never starts a stopped production.

`configure` writes a durable CONFIGURE_REQUESTED fence, invokes the existing
immutable `Chronos.Agent.Model.Configure` and reads back the complete configuration.
It never overwrites a different native model configuration. If only its final
confirmation was lost, a later explicit configure can finish from matching
readback without calling Configure again. A fence with no matching configuration
remains uncertain; no destructive repair/reset is exposed.

`start` is the **initial installation start**, not a restart controller. It requires
a stopped production, untouched CONFIGURED bootstrap state, no prepared jury case
and no recorded decision. It commits START_REQUESTED before calling
`Ens.Director.StartProduction("Chronos.App.Production")`. OnStart runs the existing
recovery logic; this tool does not hold the bootstrap lock across that callback.
A repeated command with that fence only observes current state, even if a later
stop occurred. It never force-restarts, clears queues, enables auto-start or
rewrites the fence. Operational restart remains a separate lifecycle action;
this installer does not remove that requirement from the full project scope.

## Interpret the result accurately

| Result | Meaning |
|---|---|
| MODEL_NOT_CONFIGURED | No bound model configuration was observed. |
| CONFIGURED | The complete expected native model configuration was read back. No inference verified. Check native_state too; CONFIGURE_REQUESTED means its confirmation still needs resolution. |
| CONFIGURATION_UNCERTAIN | Configuration fence exists but matching native configuration was not established. Preserve and inspect. |
| START_REQUEST_UNCERTAIN | A durable start request exists; successful recovered production was not established. Do not replay the start. |
| RUNNING_NATIVE_ONLY | Correct native production is running and the existing bootstrap recovery gate is ready, with matching configuration and start fence. Model connectivity, inference and UI are NOT proved. |
| OUTCOME_UNCERTAIN_USE_STATUS | CLI timed out or could not trust the native response. The server may have continued; consult status. |
| PROVIDER_PROFILE_CHANGED_USE_STATUS | The provider changed/became unreadable across the call. Preserve both sides and inspect; never retry automatically. |
| REJECTED_STATE_PRESERVED / other rejection | A binding/check failed. No success claim; preserve any committed state. |

`ready=false` and `model_tested=false` remain explicit for every result. Boolean
observations may be null when not established. Production state is a native
snapshot, not proof that a model is available. The profile is checked again after
the native response; a lost client response never implies execution was cancelled.

The driver deadline is90s and applies to waiting for the console subprocess.
It is not a verified server-side cancellation or a new model inference timeout.
The existing28s transport/30s workflow limits are unchanged.

## Final-artifact validation required before jury use

Earlier native and integrated proofs are summarized in [EVIDENCE.md](EVIDENCE.md).
Repeat the relevant checks against the exact final artifact on Community AI Hub 154: wrong identity/build/web/transaction,
source/receipt/profile changes, actual global/resource/journal mappings, disabled
web gate, immutable configuration, concurrent configure/start, interruption before
and after each fence, readback-only completion, and proof of one StartProduction
call. Verify status while production is stopped, busy, starting and recovered.
Test actual provider sidecars and then native AI Hub -> authenticated browser ->
explicit human approval -> owned synthetic effect -> independent readback.

The API reference used for the lifecycle calls is
[Ens.Director](https://docs.intersystems.com/irislatest/csp/documatic/%25CSP.Documatic.cls?CLASSNAME=Ens.Director&LIBRARY=ENSLIB).
That public reference is not a replacement for build 154 runtime validation.


Cloud budget validity and listener/model readiness remain separate. Neither
CONFIGURED nor RUNNING_NATIVE_ONLY contacts the cloud provider or proves a key,
TLS, listener or inference works. The cloud listener requires its own approved
plan and hidden-console startup; these source changes do not activate it.
