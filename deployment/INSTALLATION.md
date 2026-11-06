# Chronos installation preparation

This component reference describes the installation tools. Follow [the ordered
jury route](JURY-ROUTE.md) to install and evaluate the application. See the
[native rehearsal and scope](EVIDENCE.md#final-native-rehearsal) for observed results.

This folder contains source, prompts, schemas, browser files, a verifier and
the native installer. A manifest proves file identity; it is not permission to
configure accounts, expose a port, start a model or spend money. Do not substitute
a new digest over an existing installation.

## What is included

- Native Chronos classes, including the business service/process, AI Hub operation,
  durable authority, recovery, approvals and authenticated web API. The API also
  serves a fixed allowlist of UI files; serving does not grant READ or APPROVE.
- Embedded Python simulator, E1 interpretation/selection contract and review
  projection. Destinations are owned synthetic systems: acceptance and simulated
  delivery are not physical delivery.
- Optional local provider guard with immutable profile binding and persistent
  request allowance. The packaged source tree keeps its expected relative layout.
- Browser files with one explicit same-origin API path, set when bundling.
- Validated installation planning, new-directory staging and read-only native
  preflight tools. These are included with their matching source hashes; none
  applies native account policy or starts services.
- Compose infrastructure, read-only engine/native health and a fixed synthetic
  history seed; see [the Compose guide](COMPOSE.md) for their current scope.
- Offline paired evaluator. Historical lab fixtures and experiments are not
  bundled; tests and measured evidence remain in the development repository.

There are no EAP images, model weights, credentials, profiles, SQLite databases,
IRIS databases, test accounts, personal files or copied runtime directories.
InterSystems image access/licensing remains a separate prerequisite. The required
kit for this project is Community 2026.3.0AI.154.0; an arbitrary IRIS image is not
an interchangeable substitute. This source bundle does not redistribute that kit.
The organizer also permits109, but this candidate has not validated it; see
[the declared engine build](../README.md#tested-engine-build) before selecting an image.

## Inspect and verify first

From the bundle root:

```text
python -B tools/application_bundle.py verify . --manifest-sha256 EXPECTED_SHA256
python -B src/chronos_transport/guard.py --help
```

Use the externally recorded SHA-256 emitted by the trusted build. A manifest
copied together with changed files does not authenticate them. The verifier
detects byte changes, missing/unlisted files, links and unapproved index changes;
it does not establish trust in a malicious verifier or prove code execution.

The builder checks the closed static import styles used by the current client.
Dynamic imports, re-exports and unrecognized/comment-interleaved import syntax
are rejected for explicit review; this is not a general JavaScript parser.

Verification is for the pristine bundle **before installation**. Preserve that
bundle and create a separate installation staging tree with the bundled helper.
Runtime state
created afterwards is intentionally absent from the distributable. Keep the
original bundle/evidence and the installed mutable runtime distinguishable.

## Local installation staging (native host paths, configuration v3)

Keep model storage and the model home directory **outside the staging root**,
not just outside `app/`, `data/` and `guard/`. The staging root has an exact
allowlist of entries; adding an empty `model-home/`, logs or screenshots there
invalidates its pristine check. Use a separate sibling directory for model home.

The helper creates a NEW root with a hash-identical `app/`, separate empty
`data/` and `guard/` directories, non-secret `profile.json`/`config.json`, and a
completion receipt written last. Paths must be absolute local paths in the host
OS format: drive-letter paths on Windows or rooted POSIX paths on Linux/macOS.
Use short checkout, bundle and stage paths on Windows, for example under
`D:\ChronosLab`. A deeply nested path can exceed the Win32 limit. If this
happens during staging, preserve the partial tree and choose a shorter unused
path before starting any services.
Our own project and runtime remain on D:. It refuses traversal, UNC paths,
existing targets, links, changed inputs, replaced directories, used state and partial
outputs. It never deletes, resumes a partial copy or resets an allowance.

    python -B tools/installation_stage.py create --help
    python -B tools/installation_stage.py verify --help

Use the separately trusted bundle SHA, a new target and a version3 E1 profile.
Local Ollama uses port11434. The optional cloud route additionally requires the
exact non-secret `--cloud-plan`; staging retains its byte and semantic hashes
without creating an allowance. See [CLOUD-PROVIDER.md](CLOUD-PROVIDER.md). The guard URL must be
`http://127.0.0.1:11512/v1/`; this describes the opt-in Compose shared loopback
layout, not a host relay. Configuration v3 binds the corrected three-database layout and keeps `host_guard_state`. Old v1/v2
configs/receipts are rejected: retain their original tools and evidence rather
than relabelling them or silently migrating their data.

The generated plan names the 25 targets in `NativeInstall.Spec/Inspect` for
build154: three databases (main, private TEMP and SECONDARY), their resources and
directories, the namespace, roles/users and both web routes. The namespace's
implicit route is closed AFTER namespace creation; the plan promises a required
disabled final state, not that it is never initially enabled. No web port is
published by the base Compose file.

Map `app/` to `CHRONOS_APP`, `data/` to `CHRONOS_DATA` and `guard/` to
`CHRONOS_GUARD_STATE`; [COMPOSE.md](COMPOSE.md) gives the full contract. Code is
read-only; all persistent IRIS data goes under `/durable`, and guard state under
`/opt/chronos/runtime/local-provider` or the explicitly selected `cloud-provider`. Staging does NOT prepare that state,
initialize an allowance, create accounts or run Compose.

**Verify the pristine stage BEFORE starting the engine.** Afterwards
`data/iris` legitimately exists, so `installation_stage.py verify` and the
auxiliary preflight's `--stage-root` must reject it as no longer pristine.
For the actual running Compose instance, use the separate, bundled
`deployment/native_install.py inspect` command in [COMPOSE.md](COMPOSE.md).
Do not weaken the empty-directory check or erase data to pass it.

The [auxiliary preflight](PREFLIGHT.md) can inspect names on an already available
owned laboratory engine, but does not verify the target Compose mounts, health,
installation intent or readiness. A plan/receipt/snapshot is not authorization or
a reservation. The native installer must revalidate immediately before changes.
Filesystem administrators can alter local files; staging is not an adversarial
filesystem transaction.

## Delivery evidence and remaining gates (2 November 2026)

Earlier immutable candidates have real AI Hub154 installation, lifecycle and
workflow evidence. Candidate129 passed a fresh disabled installation and the
packaged configure/start/stop/resume route. Candidate119/run126 completed three
known synthetic model cases and two separately approved recoveries with
independent acceptance readback. A later packaged run131 on129 rejected an
invalid source citation in the economy case; two of four request slots were
consumed and the remaining cases were not attempted. That failure is preserved.

Later immutable candidate134 completed four native/model/browser cases in135.
Browser response-loss test138 and engine interruption tests149/150 preserve
separate evidence; reserved comparison166 and real elapsed expiry167 are summarized
in [EVIDENCE.md](EVIDENCE.md). Those observations belong to their recorded revisions,
not automatically to the final revised source.
Full Linux/macOS IRIS bootstrap and two clean installations of the final same
artifact remain pending. `docker compose up` starts the selected services; it
is not a promise that private installation, identity setup and model evaluation
have already succeeded. See [COMPOSE.md](COMPOSE.md) and [JURY-ROUTE.md](JURY-ROUTE.md).

Load and tag the authorized 2026.3.0AI.154.0 image locally. Never publish it or a
derived image. The application source is provided under the [MIT licence](../LICENSE).

The [first-case CLI](JURY-CASE.md) registers a known synthetic history, makes one
native workflow request and consults its stable decision ID. Real native calls
exist for earlier recorded candidates. It cannot approve or dispatch recovery.
The [final native rehearsal](EVIDENCE.md#final-native-rehearsal) records the
fresh installation, proposal, human approval and destination readback on 460.
Reserved comparison166 completed on12 synthetic cases with a bounded observed
advantage; it is not generalization or native benchmark proof. Interruption
and expiry evidence are recorded separately. Portable reproduction and the two
fresh final-artifact installations remain open.

### Reproduce installation without reusing another laboratory's state

1. Obtain the exact licensed AI Hub image and verify its local identity.
2. Allocate unique private directories, deployment ID and loopback port; preserve
   other projects, existing databases and earlier evidence.
3. Stage and verify the exact source artifact before starting the engine.
4. Compile/install it through the packaged native helper and inspect the private
   database resources, namespace, roles and disabled accounts/routes.
5. Prepare one immutable provider profile and initialize its new persistent
   allowance only for this first installation. The native configure step requires
   that state. On restart keep the original allowance and operation identities.
6. Configure the native provider against that prepared state. Establish credentials
   directly in the private application; never put them in a public artifact.
7. Check provider/production readiness before requesting a case. A connection
   label or HTTP200 alone does not prove a valid model decision.
8. Verify review, authorization, recovery and readback separately; retain failures.
9. Repeat with a second clean installation of the same final artifact before
   declaring that final installation route reproducible.

## Provider and state limits

The current guard CLI supports an authorized **local** Ollama-compatible provider
through an immutable non-secret profile and the E1 schema. The separate opt-in
cloud source requires an explicit plan, private console and budget; no paid
execution has occurred. Naming a cloud model does not prove its actual support.
Do not insert an API key into files, arguments, IRIS messages or public traces.
No remote compatibility or paid budget is authorized by packaging.

The standalone guard retains its relative `runtime/` lookup. Compose mounts
that writable path separately at `/opt/chronos/runtime`; the source bundle stays
pristine at `/opt/chronos/bundle`. The new local-model route shares IRIS loopback
instead of using the old laboratory host relay. Do not broaden listener binds,
open a firewall or disable TLS verification to make an install appear
successful. Packaged networking/model execution has been observed in run131, including its
recorded invalid-source failure. For current results see the
[local native rehearsal](EVIDENCE.md#final-native-rehearsal).

Credentials, persistent state and provider profiles are runtime inputs, never
distribution assets. Keep them outside a public source release. Account setup
and public deployment require the appropriate explicit approval.

## Meaning of successful checks

STAGED_FILES_ONLY_NOT_INSTALLED means only that a new directory contains the expected,
hash-verified source bytes. Two identical staged directories are not two clean
IRIS installations. Python imports and guard help prove local dependency/layout
checks only. They prove neither native workflow success nor model usefulness.


## Optional local-provider source route

See [LOCAL-PROVIDER.md](LOCAL-PROVIDER.md) for explicit E1 profile/allowance
preparation and the opt-in model/guard Compose file. The base file stays unchanged.
No model/image is downloaded, no request is made during preparation, and existing
allowances are never reset. Earlier candidates have real local provider/native
evidence, including a failed repeatability case. Validate the exact new artifact
and provider; preparation alone does not run the model.

The [native provider helper](NATIVE-PROVIDER.md) supplies configure, initial-start
and status commands; [native_resume.py](native_resume.py) handles operational
resumption. The packaged route passed on installation129.
Source132/133 must still be validated as a combined installed artifact. Simulated
driver tests alone do not establish working provider integration.

## Explicit native web access

[WEB-ACCESS.md](WEB-ACCESS.md) describes the status/enable/disable helper, private
native account setup and opt-in loopback browser mapping. No password/account
mutation is performed by the helper. An enabled route is not a tested login or
workflow. The [native rehearsal](EVIDENCE.md#final-native-rehearsal) includes
Reader/Operator separation, one approved recovery and browser readback.
Choose any loopback publication before first startup; do not recreate a live
network namespace without coordinated model/guard/production recovery.

## Judge-owned cloud provider status

[CLOUD-BUDGET.md](CLOUD-BUDGET.md) documents the offline monetary-authorization
component. [CLOUD-PROVIDER.md](CLOUD-PROVIDER.md) covers the separate launcher,
private key input and cloud plan bound into staging/native configuration source.
The local guard remains local-only. Native compilation, actual provider/TLS and
clean-install checks are pending; this is not a working cloud delivery claim.
Do not supply keys or claim a working cloud installation from these tests.
