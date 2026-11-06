# Compose infrastructure and native installation

> Installation command order: follow [JURY-ROUTE.md](JURY-ROUTE.md). This is a
> component reference, not an additional setup pass. Do not prepare allowances or
> perform initial production start again after completing the canonical route.

Start with [JURY-ROUTE.md](JURY-ROUTE.md). Earlier immutable candidates completed
native installation, provider startup and authenticated browser/model flows on
AI Hub 154. [EVIDENCE.md](EVIDENCE.md) identifies those revisions and limits.
Bootstrap, production health, model readiness and an accepted recovery are
different observations; none alone proves the complete application.

## Licensed image and isolated storage

Obtain Community `2026.3.0AI.154.0` through the [Early Access portal](https://evaluation.intersystems.com/Eval/early-access/AIHub) or your authorized InterSystems access,
accept its terms personally, then load/tag it locally as directed by the organizer.
Never redistribute the image or a derivative. Inspect and pin the local image ID.
Compose uses `pull_policy: never` and does not build or download an image.
The candidate still targets 154; [contest permission for 109](../README.md#tested-engine-build)
does not make 109 interchangeable with this implementation.

After obtaining the licensed 154 archive, load and identify it locally:

```powershell
docker image load -i iris-community-2026.3.0AI.154.0-docker.tar.gz
if ($LASTEXITCODE -ne 0) { throw 'Could not load the IRIS image.' }
docker image ls --no-trunc
if ($LASTEXITCODE -ne 0) { throw 'Could not list local images.' }
```

Replace `LOADED_IMAGE_ID` below with the loaded image's ID. The label check must
pass before tagging the image:

```powershell
$LoadedImage = 'LOADED_IMAGE_ID'
$LabelsJson = docker image inspect $LoadedImage --format '{{json .Config.Labels}}'
if ($LASTEXITCODE -ne 0) { throw 'Could not inspect the loaded IRIS image.' }
$Labels = ($LabelsJson -join [Environment]::NewLine) | ConvertFrom-Json -ErrorAction Stop
if ($Labels.'com.intersystems.platform-version' -ne '2026.3.0AI.154.0com') { throw 'Expected AI Hub Community 154.' }
$Labels.'com.intersystems.platform-version'
docker image tag $LoadedImage iris-community:2026.3.0AI.154.0
if ($LASTEXITCODE -ne 0) { throw 'Could not tag the verified IRIS image.' }
```

Use the verified image ID as `CHRONOS_IMAGE`. A tag alone does not prove the build. Image labels are followed
by the real engine/version health check after startup. If 154 is unavailable to
you, follow the access guidance above rather than silently using a different kit.

Set these non-secret variables in the current terminal before any Compose command:

| Variable | Value |
| --- | --- |
| `CHRONOS_PROJECT` | A new unique Compose project name |
| `CHRONOS_IMAGE` | Inspected local image ID for the licensed build 154 |
| `CHRONOS_APP` | Verified stage's absolute `app/` path, without trailing slash |
| `CHRONOS_DATA` | That stage's new, dedicated `data/` directory |
| `CHRONOS_GUARD_STATE` | That stage's separate `guard/` directory |
| `CHRONOS_WEB_PORT` | An unused loopback port, identical to the staged origin |

Use D: on this workstation; other hosts may use their own absolute local paths.
Source, data and guard folders must be separate and already exist. Do not use
another project's data, a shared model store or personal folders. Run from the
verified bundle root. After staging, `CHRONOS_APP` points to the staged copy,
not an editable source checkout. See [INSTALLATION.md](INSTALLATION.md).

The complete source and its `src`, `deployment` and `tools` aliases are mounted
read-only. `data/iris` contains Durable %SYS; `data/chronos/<deployment-id>`
contains application data. Guard profiles and allowances remain in `guard/`,
outside the source bundle. Verify a pristine stage before startup; once IRIS
writes its data, use native inspection rather than the empty-stage verifier.

## Select the complete layout before the first start

All commands below show the **local E1 + C2v2 + loopback web + GPU** layout. Set its
additional model variables from [LOCAL-PROVIDER.md](LOCAL-PROVIDER.md) first.
The examples already include conversation and the explicit GPU override; set their variables and do not append either file twice. For the separately chosen cloud branch, use [CLOUD-PROVIDER.md](CLOUD-PROVIDER.md) instead of these commands. It does not support this combined C2v2 route; do not retain local-model/conversation/GPU overlays as a cloud shortcut.

Validate, without starting services:

```text
docker compose -f deployment/compose.yaml -f deployment/compose.web-local.yaml -f deployment/compose.local-model.yaml -f deployment/compose.conversation.yaml -f deployment/compose.local-gpu.yaml --profile local-model --profile conversation config --quiet
```

Inspect the merged configuration before startup. Only the IRIS gateway may be
published, bound to `127.0.0.1:CHRONOS_WEB_PORT`. This exposes the gateway's other
routes on this PC too; it is not a path-only proxy. Model/guard ports stay internal.
Do not widen the bind or change the staged origin.

Start **only** the engine:

```text
docker compose -f deployment/compose.yaml -f deployment/compose.web-local.yaml -f deployment/compose.local-model.yaml -f deployment/compose.conversation.yaml -f deployment/compose.local-gpu.yaml --profile local-model --profile conversation up -d iris
```

Selecting a profile does not authorize starting all of its services. Keep the
explicit `iris` target here. No Chronos account, provider allowance, production
or model is initialized by this command. The engine is capped at 4 GiB/2 CPUs;
model memory is additional. There is no privileged mode or Docker socket mount.

Keep the same project, directories and file set for later commands. Do not add
web/GPU overrides by casually recreating a populated engine. Model and guard
share its network namespace; replacing it requires coordinated recovery.
Never run `down -v`, clear queues/data or reset an allowance to rescue a test.
Keep partial and failed attempts for inspection.

## Engine and production health are separate

The engine health check runs every 30 seconds after a 120-second startup period.
It requires the exact Community 154 build, a running engine and official system
health `ok` or `warn`; it does not hide an `alert` or restart the engine.

After native installation, inspect the actual namespace printed by the installer:

```text
docker compose -f deployment/compose.yaml -f deployment/compose.web-local.yaml -f deployment/compose.local-model.yaml -f deployment/compose.conversation.yaml -f deployment/compose.local-gpu.yaml --profile local-model --profile conversation exec -T iris /usr/bin/python3 -B /opt/chronos/deployment/native_health.py native --namespace INSTALLED_NAMESPACE
```

`IRIS_ENGINE_ONLY` proves the engine check. `NATIVE_PRODUCTION_ONLY` additionally
requires the configured production, recovered state and open recovery gate.
Neither proves model inference, browser login or destination acceptance.
Failures and `ready=false` must be investigated rather than renamed as success.

## Install disabled, then inspect readback

Replace every uppercase placeholder with the same staged values, including the
chosen `WEB_PORT`. Run the helper in the owned engine:

```text
docker compose -f deployment/compose.yaml -f deployment/compose.web-local.yaml -f deployment/compose.local-model.yaml -f deployment/compose.conversation.yaml -f deployment/compose.local-gpu.yaml --profile local-model --profile conversation exec -T iris /usr/bin/python3 -B /opt/chronos/deployment/native_install.py inspect --deployment-id DEPLOYMENT_ID --origin http://127.0.0.1:WEB_PORT --application /csp/chronos/ --manifest-sha256 BUNDLE_SHA256
```

Inspection compiles the trusted installer into `%SYS` and reads the proposed
25-target scope. It creates no application database, namespace, account or role.
`NAMES_CLEAR_NOT_AUTHORIZATION` is an observation, not permission to apply it.

After approving that exact scope, replace `inspect` with `apply` and append
`--authorize-id DEPLOYMENT_ID`. Apply rechecks names under a lock, creates the
private databases/resources and four minimal roles, compiles the application,
initializes its owned catalog and creates Reader/Operator users. **Users and
the owned web route remain disabled.** Random passwords stay in native memory;
the helper never prints them. The application-only Python role is not assigned
directly to either user; the Base role has no SECONDARY database access.

The automatically created namespace route is closed and checked immediately
after namespace creation. A configuration/readback failure preserves partial
objects and reports `PARTIAL_INSTALL_PRESERVED`. Timeout or incomplete output
is uncertain: inspect the same attempt, do not issue another Apply or delete it.

`NATIVE_INSTALLED_DISABLED` proves bootstrap readback only. Continue with private
account setup, ONE provider, production startup and web activation in the order
in [JURY-ROUTE.md](JURY-ROUTE.md). Use [WEB-ACCESS.md](WEB-ACCESS.md) for private
password entry; there is no default Chronos password and no need for `%All`.

## Stable identity and lifecycle

New Compose installations use `hostname: chronos-iris`. Keep this internal name
stable with the same durable data. An older installation must retain its own
original hostname; applying the new default to old data can itself cause a
node-change warning. Separate installations still need distinct projects,
networks and storage. Do not edit metadata or clear alerts to pass health checks.

Controlled engine restart/recovery was observed in tests 149/150; a coordinated
replacement of a populated container is a different operation and remains
unverified. [NATIVE-RESUME.md](NATIVE-RESUME.md) covers explicit lifecycle recovery.
The first-start provider command is not a general restart controller.

## First incident and remaining proof

Use [JURY-CASE.md](JURY-CASE.md) after provider readiness and browser login,
before seeding any timed scenario. Its inspect/prepare/propose/status commands
preserve the original case identity, deadlines and request fence. The lower-level
`first_case.py` creates simulator history only and is not the jury workflow:
it makes zero model calls or recovery submissions but does write the original
synthetic attempt and its final rejection. Do not run it separately as a
supposed no-effect warmup. Use [MODEL-DIAGNOSTICS.md](MODEL-DIAGNOSTICS.md) instead.

Native flow 135 and browser interruption 138 verified their recorded revisions;
temporal 167 checked real elapsed expiry without a browser or new proposal.
The [final native rehearsal](EVIDENCE.md#final-native-rehearsal) covers the
tested Windows workstation. Independent hardware remains outside its scope. Optional cloud
provider/TLS/workflow execution remains unverified and requires separately
approved credentials/budget; source preparation alone grants no spending.
