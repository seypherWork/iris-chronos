# Optional cloud provider: explicit budget and private console

**Experimental source. Native AI Hub cloud compilation/runtime proof is pending.**
The installer and native helper now bind an explicit cloud plan in source. The
existing local guard remains local-only; the cloud route uses its separate
launcher. This is not proof that the complete application works with OpenAI yet. No real
key, paid request, live TLS exchange or native cloud workflow has been tested.
Use the local route for its existing evidence; never present a synthetic reply
as an agent result. This is CHR-I07 work, not a ready release.

## Model and spend review before activation

No model or budget is selected automatically. The current reviewed protocol IDs
are `gpt-6-luna` and `gpt-6-sol`: Chat Completions, text JSON schema, effort `none`
and temperature 0. The names are exact IDs documented on 30 October 2026; they do
not have date suffixes. Responses must match the selected ID exactly. No aliases
are resolved and no fallback is used. Other IDs need a separate protocol review.
These references establish documented compatibility, not account access, measured
quality, performance, future availability or a provider price guarantee.

Reservations deliberately cover the entire 1,050,000-token context plus 2,048
output tokens. Reviewed rate floors include long-context, cache-write and regional
premiums at Standard service. They do not use cached-input discounts. Per-request
reservations are 290,440 micro-USD (Luna) or 5,808,792 micro-USD (Sol). These are
conservative allowance reservations, **not estimates of a small request's bill**.
One USD is 1,000,000 micro-USD. Failed/uncertain calls keep their reservations.
Check the current official prices before authorizing; higher explicit ceilings
can be supplied. Taxes, provider price changes and other applications are outside
this ledger. Set provider-side spending controls too. Zero budget admits no call.

References: [Luna](https://developers.openai.com/api/docs/models/gpt-6-luna),
[Sol](https://developers.openai.com/api/docs/models/gpt-6-sol),
[parameter compatibility](https://developers.openai.com/api/docs/guides/latest-model).

## Preparation without a credential or model call

1. Generate a non-secret plan using the packaged `deployment/cloud_provider.py`
   `plan` command. All of `--deployment-id`, `--model`, `--request-limit`,
   `--budget-micro-usd` and `--valid-for-seconds` are mandatory. Validity is 60 to
   86,400 seconds; it starts when the plan is made. Optional `--input-rate-micro`
   and `--output-rate-micro` can raise reviewed rate floors. Save stdout as a NEW
   plan file; do not put a key into any file, command argument or environment.
2. Run `inspect-plan --plan /absolute/path/plan.json`. Review the actual model,
   context, rates, maximum admitted requests, expiry and `plan_sha256`.
   This digest is public and identifies the plan; it is not proof of consent.
3. The owner must approve that exact model, ceiling, validity and transfer of
   the case's two text messages to OpenAI. Approval to develop code is not approval
   to make paid requests. The operator then supplies the approved digest.
4. In the dedicated private guard runtime, `prepare --plan ...
   --authorize-plan-sha256 ...` creates only `cloud-provider/plan.json` and its
   SQLite allowance. It refuses existing/mixed state. It never repairs, replaces
   or resets a partial ledger. `status --deployment-id ...` observes that state.
   Do not delete it to renew funding; renewed authorization is a separate pending
   lifecycle. Expiry does not prevent status inspection.

## Bind the same plan into a fresh installation

Pass the saved non-secret cloud plan with `--cloud-plan` to
`tools/installation_plan.py`, `tools/installation_stage.py create`, and a direct
`tools/installation_preflight.py` invocation. Supply the exact profile object
from that plan as the separate `--profile` JSON file. Local Ollama profiles reject
an attached cloud plan; cloud profiles refuse to proceed without one.

A cloud staging tree additionally preserves `cloud-plan.json` outside the empty
`guard/` runtime. Its receipt binds both original bytes and the canonical plan
hash. The plan displays the monetary policy, but staging does not initialize any
allowance or grant spending. Use the staged cloud-plan file for
`CHRONOS_CLOUD_PLAN`; prepare it later with the separately approved exact digest.
The validity window is not renewed by copying or installing. An expired plan
cannot activate spending. Preserve the old stage rather than silently editing it.

`deployment/provider_state.py` reads exactly one installed provider. A missing,
partial or mixed provider is refused, never replaced with another one. Its report
separates configuration, budget validity and remaining allowance from transport
or model testing. The native console binds the full cloud plan hash (the profile
hash alone would omit the budget). It passes the expected hash into IRIS and
checks it before writing native state, then compares it again after the call.

Native response schema is now `chronos.native-provider.v2`. Prior installation
fences without the new binding are not migrated; retain their original bundle
and evidence. This is a fresh-install path, not authorization to replace old data.

## Intended isolated Compose use (not yet runtime verified)

Merge `compose.yaml`, `compose.web-local.yaml` and `compose.cloud.yaml` for the jury browser route, explicitly using the
`cloud-provider` profile. Do not combine with `compose.local-model.yaml`; they
use the same internal guard port. Set the base Compose variables and these
non-secret values: `CHRONOS_CLOUD_PLAN`, `CHRONOS_CLOUD_APPROVED_PLAN_SHA256`,
`CHRONOS_DEPLOYMENT_ID`, `CHRONOS_APP_MANIFEST_SHA256`. `CHRONOS_APP` must contain
the verified source bundle. `CHRONOS_GUARD_STATE` must be dedicated to this plan,
owned by UID 51773 and not writable by another user. No provider key is an env var.

The cloud-guard uses OS Python from the already authorized local AI Hub154 image,
not a second IRIS engine. It is limited to 256 MiB and half a CPU, has no GPU,
no restart, disabled inherited healthcheck and no published port. Source is read
only. Core dumps are disabled in the container. The private key is entered by the
owner at an attached hidden terminal; the launcher refuses redirected stdin or
getpass's echo fallback. Start interactively, never detached or through a recorded
terminal. Intended command after the owned IRIS service is healthy:

```text
docker compose -f deployment/compose.yaml -f deployment/compose.web-local.yaml -f deployment/compose.cloud.yaml --profile cloud-provider run --rm --no-deps cloud-guard
```

To prepare first, override the service command with `prepare --plan
/opt/chronos/cloud-plan.json --authorize-plan-sha256 <approved digest>`.
No accounts, resources, roles or native configurations are changed by this sidecar.
The source bundle and mounted aliases are verified before the key prompt. A key
lives only in process memory; this is not a secure-erasure or anti-paging guarantee.
Exiting, budget exhaustion, a durable halt or expiry stops the launcher. Starting
again requires private key entry and reuses the same remaining allowance.

## Trust boundary and proof still required

Port 11512 binds only to loopback **inside the private IRIS network namespace**.
There is no per-request password on this listener: every process in that namespace
is trusted to spend the approved allowance. Do not run it on a shared host, publish
11512, add a reverse proxy or place untrusted containers in the namespace. UID and
path checks do not prove network isolation; the deployment operator must check it.
This is not a public inference service or a multi-tenant budget boundary.

HTTP validates framing, fixed route, JSON content type, the native E1 request and
profile/deadline before the transport reserves money. Up to four short incoming
handlers are allowed; paid work is serialized. Header/body and operation deadlines
close stalled clients. Error bodies do not echo supplied values. There is no retry.
Final durable dispatch admission and all upstream checks remain in the transport.
Disk/OS stalls can delay shutdown; a closed client is not proof of no upstream bill.

Required next: native compilation and configuration/start validation, actual
private-terminal/no-echo and container isolation checks, real TLS negatives, an
explicitly funded tiny provider test, AI Hub154 end-to-end proof and a fresh jury
installation. The optional source cannot be used to claim those checks passed.
