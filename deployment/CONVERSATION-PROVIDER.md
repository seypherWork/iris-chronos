# Case conversation provider: current C2v2 candidate

## Current candidate: E1 and C2v2

**Configuration reference.** Execute setup once in [JURY-ROUTE.md](JURY-ROUTE.md).
The [final native rehearsal](EVIDENCE.md#final-native-rehearsal) covers one C2v2
question and its effect on the active case. The [eight-question test](EVIDENCE.md#latest-private-audit-5-november)
retains its own frozen source and scope.
Use one verified Qwen3.5-9B Q8_0 alias `chronos-qwen35:8k-full`, context 8192,
Ollama 0.40.13, reasoning `none`. Decision E1 and chat C2v2 have distinct immutable
profiles and allowances. Current local results do not validate arbitrary models
or the cloud route. The historical C1/C2v1 commands below are not this recipe.

Before staging, plan both profiles without starting services or granting quota:

```text
python -B deployment/local_provider.py plan --deployment-id DEPLOYMENT_ID --model chronos-qwen35:8k-full --request-limit 12 --reasoning-effort none
python -B deployment/conversation_provider.py plan --deployment-id DEPLOYMENT_ID --model chronos-qwen35:8k-full --request-limit 24 --reasoning-effort none --contract c2-v2
```

Save each successful JSON output separately. Use the E1 profile for installation
staging. Keep both model names, limits, deployment IDs and schema hashes exactly
matched during preparation. Example limits 12/24 are explicit operator choices,
not the counts of a previously executed test. Do not reuse a spent directory.

Retain the local model, web and conversation Compose files from the first engine
start, plus the explicit GPU override if selected. Set
`CHRONOS_CONVERSATION_CONTRACT=c2-v2` in the non-secret Compose environment and
use a separate empty `CHRONOS_CONVERSATION_STATE`. The CLI and Compose defaults
remain C1 for compatibility: omitting the explicit selector is not a migration.

This is the **only allowance preparation sequence** for the current combined
route. Do not execute E1 `prepare` in another guide first. If either allowance
already exists, stop and inspect its stored profile/status; do not repeat
preparation, delete state or substitute fresh directories to conceal an attempt.

After the disabled native installation, run inside its owned IRIS container:

```text
/usr/bin/python3 -B /opt/chronos/deployment/local_provider.py prepare --deployment-id DEPLOYMENT_ID --authorize-id DEPLOYMENT_ID --model chronos-qwen35:8k-full --request-limit 12 --reasoning-effort none
/usr/bin/python3 -B /opt/chronos/deployment/conversation_provider.py prepare --deployment-id DEPLOYMENT_ID --authorize-id DEPLOYMENT_ID --model chronos-qwen35:8k-full --request-limit 24 --reasoning-effort none --contract c2-v2
/usr/bin/python3 -B /opt/chronos/deployment/local_provider.py status --deployment-id DEPLOYMENT_ID
/usr/bin/python3 -B /opt/chronos/deployment/conversation_provider.py status --deployment-id DEPLOYMENT_ID
```

Compare each profile hash with its separate planned profile before proceeding.
With production stopped and web disabled, configure E1 once using
[NATIVE-PROVIDER.md](NATIVE-PROVIDER.md): run its `status` and `configure` steps
with the E1 hash, but do not start production yet. Then configure C2v2:

```text
/usr/bin/python3 -B /opt/chronos/deployment/native_conversation.py status --deployment-id DEPLOYMENT_ID --origin http://127.0.0.1:WEB_PORT --application /csp/chronos/ --manifest-sha256 BUNDLE_SHA256 --profile-sha256 C2_PROFILE_SHA256 --contract c2-v2
/usr/bin/python3 -B /opt/chronos/deployment/native_conversation.py configure --deployment-id DEPLOYMENT_ID --origin http://127.0.0.1:WEB_PORT --application /csp/chronos/ --manifest-sha256 BUNDLE_SHA256 --profile-sha256 C2_PROFILE_SHA256 --contract c2-v2 --authorize-id DEPLOYMENT_ID
```

Replace every uppercase placeholder with this installation's verified binding.
Compare prepared profile digests with the planned profiles before continuing.
The profile status command reads its stored contract; it has no `--contract`
option. The native status/configure commands do require `--contract c2-v2`.
Keep production stopped and web disabled until both configurations are checked.
Do not configure E1 a second time after this sequence. Return to
[jury step 5](JURY-ROUTE.md#5-warm-up-first-start-production-and-log-in-before-any-case):
start the model and both guards with the complete Compose layout, perform the
neutral warmup, then perform the first production start. Configuration is not inference
or login proof. Neither chat nor an interpreter answer grants shipment authority.

Both guards call the same native Ollama endpoint internally with `shift:false`
and `truncate:false`; the packaged neutral warmup now shares that policy. Their
AI Hub-facing URLs remain distinct (E1:11512, C2v2:11514), as do their quotas.
Completed native observations include two cited historical-case turns and a
fresh queue/inventory decision with chat, explicit confirmation, acceptance,
readback and reload on earlier frozen 311, followed by the frozen 333 journeys indexed in EVIDENCE. Two isolated same-host installs/configurations are recorded; this does not establish independent hardware or every final-release check. Earlier observer failures and synthetic-host measurements retain
their original scope. See [native evidence](EVIDENCE.md#native-flow) and
[shared transport](EVIDENCE.md#shared-model-transport-4-november).

## Compatibility and evidence boundary

C1 and C2v1 remain compatibility contracts in the implementation; they are not
additional setup steps or alternatives to silently select for this jury route.
Their original recipes and observations remain preserved with the earlier
source snapshots. The [evidence index](EVIDENCE.md#earlier-development-records)
keeps their historical scope separate from the current C2v2 results.

The current C2v2 guard uses its own private state, immutable profile and finite
allowance. It cannot borrow E1 quota, approve a recovery, change an existing
shipment or claim freshness beyond its bound context. Status reads the stored
contract. Do not reset an allowance or change a model/profile to recover a lost
answer; read the same conversation instead. Cloud C2v2 is not implemented.

For a concrete current walkthrough, including private login, exact model
warmup, question limits, lost replies and closure, use only
[JURY-ROUTE.md](JURY-ROUTE.md). Source tests and valid JSON are not a claim of
semantic correctness for every question or a replacement model.
