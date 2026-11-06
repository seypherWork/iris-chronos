# Local provider preparation (experimental)

**Experimental local route, with real integration evidence and remaining delivery work.**

The executable Compose examples below use the current **local E1 + C2v2 +
loopback web + NVIDIA GPU** candidate, with the complete file set in every
command. Set its conversation state/contract and explicit GPU device variables
before the first engine creation. Do not append duplicate overrides.
For a separately selected CPU-only trial, omit only the GPU file from **every**
command from the beginning; CPU-only performance remains unverified. For cloud,
follow [CLOUD-PROVIDER.md](CLOUD-PROVIDER.md) instead and do not execute these
local preparation, startup or readiness commands. Keep project identity and
bindings unchanged throughout a deployment.

## Current shared model candidate — 4 November 2026

The current development profile is Qwen3.5-9B Q8_0, local alias
`chronos-qwen35:8k-full`, context 8192, reasoning effort `none`, with Ollama 0.40.13.
The reproducible candidate alias has manifest digest
`f565248d3cbe09b10fe6702db3bd0a681711fb1170fbeea754cc077a8cf2b0ff`.
Use that full digest and context length8192 in the readiness command below after
following the [portable alias recipe](MODEL-RECIPE.md). It is a local alias, not
a public download name. The recipe's metadata was verified and its first real
neutral inference passed; semantic regression 304 and native journeys 337/338+342 are separate observations indexed in [EVIDENCE.md](EVIDENCE.md). Do not treat the alias recipe alone as their proof.

Historical298/302 used manifest
`59819759534ba21294cbd1b42eb4bf92f2fb9da6521560ba9975871e4f31c814`.
Its weights and parsed parameters match, but the manifests differ. Do not attach
historical results to the new digest or silently substitute either identity.
An alias name alone proves neither model identity nor GPU residency.

Stage 298 ran one neutral warmup, one real E1 extraction and two real C2v2 turns
without reloading the model. All33/33 layers were on GPU. It is a real-model,
synthetic-host check, not the complete native AI Hub/browser route. The model
container had4 GiB RAM/4 CPUs; the supervising machine also needed adequate free
host RAM and VRAM. Those limits are not universal model requirements.
Use the explicit [E1/C2v2 sequence](CONVERSATION-PROVIDER.md#current-candidate-e1-and-c2v2)
and retain the historical evidence below separately.

## Evidence and earlier configurations

Use [EVIDENCE.md](EVIDENCE.md) for the scoped native, model and UI observations.
Earlier GPT-OSS, partial-loading and SSD experiments are preserved as historical
records there; they are not commands or performance claims for this Qwen route.

## Layout

The optional `compose.local-model.yaml` file adds an Ollama service and the
existing bounded transport guard. Both join the IRIS service's network namespace.
The model binds only `127.0.0.1:11434` and the guard only `127.0.0.1:11512`.
The native AI Hub agent would call `http://127.0.0.1:11512/v1/`. Nothing publishes
either endpoint to Windows, the LAN or a browser. No host relay or firewall
change is required by this design. The three services share loopback access:
use trusted images; this is not a security boundary between those containers.

The ordinary `compose.yaml` stays unchanged. The additional file is opt-in and
requires explicit model memory/CPU limits, existing dedicated storage, and a
locally loaded official Ollama image. It never pulls images or models. There
is no GPU passthrough in the default local profile. An explicitly selected
NVIDIA device can be added with the optional override below. CPU-only performance and other hardware still require measurement; Windows-native model evidence
is not proof of container compatibility or latency.

The guard reuses the authorized local AI Hub image solely for OS Python, with
its entrypoint replaced. It does not launch another IRIS engine or redistribute
that image. A private, writable guard directory holds the durable allowance.
The model does not mount IRIS data, the Docker socket or the guard allowance.

## Prerequisites, before any service start

1. Use a NEW isolated deployment and verified complete source bundle, never a
   prior installed receipt with a different bundle hash.
2. Obtain the authorized Community AI Hub 154 image and the official Ollama image
   separately. Inspect and pin their local IDs/digests. Neither is downloaded
   by these files; acceptance of terms/downloads is a separate operator action.
3. Prepare the base Compose variables in [COMPOSE.md](COMPOSE.md). Also set:
   `CHRONOS_OLLAMA_IMAGE`, `CHRONOS_MODEL_CPUS`, `CHRONOS_MODEL_MEMORY`,
   `CHRONOS_MODELS` and `CHRONOS_MODEL_HOME`. For the current combined route also
   set `CHRONOS_CONVERSATION_CONTRACT=c2-v2`, `CHRONOS_CONVERSATION_STATE` and
   `CHRONOS_GPU_DEVICE_ID`. Create the separate conversation-state directory
   empty before Compose validation; staging does not create it. The two model
   directories must be distinct,
   dedicated, existing folders, outside other projects and separate from every
   source/data/guard mount. The guard-runtime root must be empty before preparation;
   legacy state is rejected rather than granting a fresh allowance. Do not point at a shared model store.
4. Supply the chosen model through an explicitly approved import/download into
   that dedicated store. There is no bundled model and no implicit download.
   Verify its identity/license, JSON schema/reasoning support and time budget.
   Cloud features are disabled via `OLLAMA_NO_CLOUD=1`.
5. On Linux, provide access to the dedicated writable folders for UID/GID51773,
   without recursively changing ownership of existing projects. Windows bind
   permissions and actual image startup still require runtime validation.

Validate configuration without starting an engine:

```text
docker compose -f deployment/compose.yaml -f deployment/compose.web-local.yaml -f deployment/compose.local-model.yaml -f deployment/compose.conversation.yaml -f deployment/compose.local-gpu.yaml --profile local-model --profile conversation config --quiet
```

The services share IRIS's network namespace. If IRIS is replaced, the model and
guard must be stopped and recreated with it as a coordinated deployment. Do
not leave services attached to the old namespace. A plain restart is not proof
of correct rebinding. Do not clear durable data, profiles, fences or allowances.

## Offline profile before staging

The `plan` command prints a directly stageable non-secret profile, without
accessing runtime state, creating a request allowance or contacting a model:

```text
python -B deployment/local_provider.py plan --deployment-id DEPLOYMENT_ID --model LOCAL_MODEL_NAME --request-limit 12 --reasoning-effort none
```

Check successful exit and save stdout as a NEW UTF-8 profile file outside the
bundle. Use that file for installation staging; later `prepare` must use those
same values. Planning grants no initialization authorization. The output is only
a version 3 E1 Profile, not a runtime/readiness report. It reads the packaged schema.
See [JURY-ROUTE.md](JURY-ROUTE.md) for the full intended order and pending proof.

## Optional NVIDIA GPU, with explicit device selection

The base Compose defaults remain CPU-only. The current candidate examples
explicitly include the GPU override. Set `CHRONOS_GPU_DEVICE_ID` to one
deliberately chosen ID from `nvidia-smi` (for example `0`); do not add a second
GPU override. Inspect this complete configuration:

```text
docker compose -f deployment/compose.yaml -f deployment/compose.web-local.yaml -f deployment/compose.local-model.yaml -f deployment/compose.conversation.yaml -f deployment/compose.local-gpu.yaml --profile local-model --profile conversation config --format json
```

Inspect the merged JSON before any startup. Only `model` may reserve the one
selected NVIDIA device; `iris` and `guard` must have none. Retain exactly the
same approved file set and environment in later commands. Empty/missing device
selection rejects. This override changes no host ports, model/guard paths,
provider quotas, account permissions, CPU/RAM limits or image pulling policy.
The example includes web-local for the jury browser route; retain it from the first start.

On Windows this requires Docker Desktop's WSL2 backend with supported NVIDIA
GPU-PV. Do not install a Linux driver in Windows, modify Docker settings or run
unrelated benchmarks as an implicit part of Chronos startup. Check the official
host prerequisites, then validate the authorized model in isolation.

**GPU selection grants access, not exclusive use or a VRAM limit.** Docker
`mem_limit` limits ordinary container memory, not graphics memory. Check host
RAM, WSL's total memory, GPU free memory and competing workloads before loading;
monitor all three during validation. A container memory limit is not a host
availability check. Context/offload settings, identity, warmup time and actual
inference latency must be recorded. No automatic CPU fallback, changed deadline
or replacement model may be counted as the originally requested experiment.

Rollback: stop only the dedicated model service and preserve its data/evidence.
Omit the GPU override for a later, separately reviewed CPU-only deployment.
Do not recreate services attached to a live IRIS network namespace piecemeal.
The original loading/probe records are summarized in
[EVIDENCE.md](EVIDENCE.md#earlier-development-records). Current candidate
observations do not establish CPU-only or other-hardware performance.

## Explicit allowance preparation, no model request

Install the matching native application disabled first. For the current
E1 + C2v2 route, perform preparation **once for each component**, exclusively in
the [combined sequence](CONVERSATION-PROVIDER.md#current-candidate-e1-and-c2v2).
This section does not contain a second E1 `prepare` command. Do not execute the
historical C1 preparation recipe as an additional step. Existing or partial
state must be inspected and preserved, never initialized again.

The E1 preparation creates `/opt/chronos/runtime/local-provider`, a version 3 E1
profile and an immutable SQLite request allowance. It makes no inference,
starts no service and configures no native model/account. Missing authorization,
wrong identity or existing/partial state rejects. It never repairs a failed
initialization by deleting or resetting evidence. Profile JSON contains no keys
or passwords. The limit counts attempted requests; it is not a money budget.

Read back the profile digest and consumed/remaining allowance:

```text
docker compose -f deployment/compose.yaml -f deployment/compose.web-local.yaml -f deployment/compose.local-model.yaml -f deployment/compose.conversation.yaml -f deployment/compose.local-gpu.yaml --profile local-model --profile conversation exec -T iris /usr/bin/python3 -B /opt/chronos/deployment/local_provider.py status --deployment-id DEPLOYMENT_ID
```

`CONFIGURED_NOT_PROBED` deliberately reports `ready=false` and `model_tested=false`.
It reads the local SQLite state and may use SQLite's journal/shared-memory files;
it does not probe the server. A spent or uncertain request stays spent. A profile
edit that disagrees with the immutable database rejects.

## Explicit runtime activation and neutral inference check

After both preparations and native configurations, start the providers once
using the same complete layout as the engine. This is the same activation step
as [jury-route step 5](JURY-ROUTE.md#5-warm-up-first-start-production-and-log-in-before-any-case):

```text
docker compose -f deployment/compose.yaml -f deployment/compose.web-local.yaml -f deployment/compose.local-model.yaml -f deployment/compose.conversation.yaml -f deployment/compose.local-gpu.yaml --profile local-model --profile conversation up -d model guard conversation-guard
```

Their entrypoints never initialize or reset an allowance. A missing/corrupt allowance prevents the guard from starting.
`ollama list` health means the model API responds, not that a model is loaded,
supports this schema or can finish inference in time. The guard does not expose
a readiness endpoint; a running container alone is not model readiness. Its
inherited IRIS engine healthcheck is explicitly disabled because this Python
service does not start an IRIS engine.

The native model configuration must bind the same model, E1 contract, deployment
and profile digest before starting Chronos production. That automatic native
configuration/start route is now implemented in the experimental
[native-provider console helper](NATIVE-PROVIDER.md), with a durable initial-start
fence and readback/status. Native configuration and initial start passed
on 154 in laboratory 95. Later laboratories verified restart and the integrated
route within their recorded scope. The packaged Compose services were exercised in 135 as described above. New
source changes require their own evidence; a successful older bundle does not
verify them.

The existing guard keeps the 28s transport deadline inside the 30s workflow
deadline. No timeout increase, retry, quota refund, remote provider, human
approval or recovery submission is introduced. CPU-only cold starts may exceed
this budget; do not label them successful or replay a consumed workflow.

## Runtime evidence

The [final native rehearsal](EVIDENCE.md#final-native-rehearsal) records the
local startup, AI Hub decision, case conversation and synthetic receipt.
Follow the [canonical jury route](JURY-ROUTE.md) for the complete sequence.
Coordinated replacement of a populated network namespace and independent
hardware remain outside the tested scope.

Sources consulted30October2026:
- [Docker Compose network mode](https://docs.docker.com/reference/compose-file/services/#network_mode)
- [Official Ollama Docker guide](https://docs.ollama.com/docker)
- [Ollama environment settings](https://docs.ollama.com/faq)

These sources establish configuration mechanisms, not successful Chronos runtime.


- [Explicit GPU device selection in Compose](https://docs.docker.com/compose/how-tos/gpu-support/)
- [Docker Desktop Windows GPU prerequisites](https://docs.docker.com/desktop/features/gpu/)


### Check local inference before starting timed scenarios

Keep the exact Compose files, environment and project used to start this isolated
installation. After preparing the immutable provider profile and starting the
model service, run the packaged helper inside `iris`. It is explicit: status,
installation, native start and business requests never trigger it automatically.
Do this before seeding a case; cold model loading can exceed the business request
window. The business window and request allowance are not relaxed.

The command below assumes your shell's Compose command already uses that same
configuration (include its approved `-f`, `--project-directory`, `--env-file` and
profile arguments before `exec` when required). Replace capital placeholders:

```text
docker compose -f deployment/compose.yaml -f deployment/compose.web-local.yaml -f deployment/compose.local-model.yaml -f deployment/compose.conversation.yaml -f deployment/compose.local-gpu.yaml --profile local-model --profile conversation exec -T iris /usr/bin/python3 -B /opt/chronos/deployment/model_readiness.py run --deployment-id DEPLOYMENT_ID --profile-sha256 PROFILE_SHA256 --attempt-id ATTEMPT_ID --model-digest MODEL_DIGEST --context-length CONTEXT_LENGTH --authorize-id DEPLOYMENT_ID
```

`PROFILE_SHA256` is the prepared profile's exact SHA256. `MODEL_DIGEST` is the
full64-character digest of the operator-approved local Ollama model manifest,
not the model image or the profile hash. `CONTEXT_LENGTH` is its configured
context. `ATTEMPT_ID` is a fresh32-character lowercase hex UUID; record it before
execution, for example generate it with `python -c "import uuid;print(uuid.uuid4().hex)"`.
The helper checks model identity before inference. It never downloads or starts
anything and has no alternate destination or caller-supplied prompt.

One neutral request is permitted per attempt, with a total240s deadline,
128 output tokens maximum, fixed JSON schema and no automatic retries. It checks
normal completion, token counts and matching resident model/context. Only hashes,
timing, counts and fixed status codes are retained under
`/durable/chronos/DEPLOYMENT_ID/model-readiness/ATTEMPT_ID`. No generated text or
reasoning is stored. The business profile and quota are read without modification.

`NEUTRAL_INFERENCE_OBSERVED` means that particular neutral inference succeeded
at `observed_at`; it does not guarantee continuing availability, case correctness,
AI Hub connectivity or acceptance. The model can unload later. Check the actual
case separately and retain its failures in the evaluation.

On timeout, lost output or process interruption, query the SAME attempt:

```text
docker compose -f deployment/compose.yaml -f deployment/compose.web-local.yaml -f deployment/compose.local-model.yaml -f deployment/compose.conversation.yaml -f deployment/compose.local-gpu.yaml --profile local-model --profile conversation exec -T iris /usr/bin/python3 -B /opt/chronos/deployment/model_readiness.py status --deployment-id DEPLOYMENT_ID --profile-sha256 PROFILE_SHA256 --attempt-id ATTEMPT_ID --model-digest MODEL_DIGEST --context-length CONTEXT_LENGTH
```

Status performs no network request. Repeating `run` with the same ID only reads
its prior record. `RESERVED_OUTCOME_UNCERTAIN` is not permission to resend:
`performed_request=false` then describes this readback invocation, not whether
the previous invocation reached Ollama. A dead client or released lock does not
prove server cancellation. Inspect and stop the owned model service if needed
before explicitly deciding on a distinct attempt; preserve the previous record.
A new ID represents an additional inference, never recovery of the old attempt.
Do not delete records, reset allowances or modify model parameters to reuse them.
