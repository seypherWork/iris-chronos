# IRIS Chronos

**Recover a shipment without sending it twice.**

An IRIS AI Hub agent interprets the customer's request inside an InterSystems
Interoperability production. Chronos checks cost, timing, inventory and prior
acceptance. The operator approves one recovery and can reopen its receipt.

## For judges

[Watch the 62-second recording](https://seypherwork.github.io/iris-chronos/) · [Download the MP4](https://seypherwork.github.io/iris-chronos/chronos-proof.mp4) · [Run the live case on IRIS 154](deployment/JURY-ROUTE.md#short-acceptance-checklist)

| Start here | What to look for |
| --- | --- |
| [Review the native proof](deployment/EVIDENCE.md#exact-package-rehearsal-on-467) | Reader was denied, three questions were answered and one synthetic B recovery produced the same receipt after reload. |
| [Compare the two recorded receipts](deployment/EVIDENCE.md#two-native-receipt-checks) | In the separate HTTP 503 experiment, A costs 3 and goes from UNKNOWN to ACCEPTED through one reconciliation of the same attempt. |
| [Open the native Visual Trace](deployment/EVIDENCE.md#visual-trace-on-407r2) | The agent's stored response shows 2,164 tokens and a 2,479 ms SDK call interval in the recorded run. |

For the live walkthrough, start with `queue_inventory` and ask **Why did you
recommend B?** A's seven-minute queue exceeds six minutes of inventory validity.
Review the preview, confirm once as Operator and reopen the receipt. The
[acceptance checklist](deployment/JURY-ROUTE.md#short-acceptance-checklist)
also covers the Reader's permissions and the expected results.

## Install and run

### Tested engine build

The verified setup uses **IRIS AI Hub Community 2026.3.0AI.154.0 x64**, Windows
PowerShell, Docker Compose, Python 3.11+ and a GPU with 16 GiB VRAM. Obtain the
licensed image through the [Early Access portal](https://evaluation.intersystems.com/Eval/early-access/AIHub) or your authorized InterSystems access, then load it locally.
Keep the image outside the repository. The [contest clarification](https://community.intersystems.com/post/intersystems-programming-contest-ai-agents-interoperability-workflows) also permits build 109. Chronos was validated on 154.

1. [Load and check the IRIS image](deployment/COMPOSE.md#licensed-image-and-isolated-storage)
   and [prepare the pinned Qwen model](deployment/MODEL-RECIPE.md) before starting a timed case.
2. [Build the source bundle](deployment/JURY-ROUTE.md#obtain-the-source-bundle-before-staging),
   [stage both profiles](deployment/JURY-ROUTE.md#1-plan-both-profiles-and-stage-once)
   and [configure Compose](deployment/JURY-ROUTE.md#2-fix-the-complete-compose-layout-before-engine-creation).
3. [Install with access disabled](deployment/JURY-ROUTE.md#3-install-disabled-and-prepare-private-access),
   [configure both contracts](deployment/JURY-ROUTE.md#4-prepare-two-allowances-once-and-configure-both-contracts)
   and [warm up and sign in](deployment/JURY-ROUTE.md#5-warm-up-first-start-production-and-log-in-before-any-case).
   [Run the cases](deployment/JURY-ROUTE.md#6-six-cases-one-at-a-time) and
   [close the deployment](deployment/JURY-ROUTE.md#7-close-access-and-stop-only-this-deployment).

### Install the ObjectScript module with IPM

Use a fresh Interoperability-enabled namespace on IRIS AI Hub build 154 with
[IPM 0.10.10](https://github.com/intersystems/ipm/releases/tag/v0.10.10) available
in that namespace. Load the repository folder containing `module.xml`, or load
the package archive if you have it.

```objectscript
zpm "load /path/to/iris-chronos/ -nodev"
```

```objectscript
zpm "load /path/to/iris-chronos-1.0.2.tgz -nodev"
```

Run `zpm "list"` and check for `iris-chronos 1.0.2`. Once this version is
published in your configured IPM registry, use `zpm "install iris-chronos 1.0.2"`.
The module installs the production definition and its ObjectScript classes.
For a runnable deployment with the Python components, web assets, isolated
storage, access controls and model, follow the
[Docker Compose walkthrough](https://github.com/seypherWork/iris-chronos/blob/0636167fc0aca72ca12d78d16ac0fec764887ac2/deployment/JURY-ROUTE.md).

## Evidence and limits

The [exact-package rehearsal](deployment/EVIDENCE.md#exact-package-rehearsal-on-467) ran
`queue_inventory` on 467. The [six-case matrix](deployment/EVIDENCE.md#final-native-rehearsal)
ran on 463 with the same application code. Both used the same Windows workstation.
The video and trace graph show the earlier 407r2 run.
A separate [native adapter run](deployment/EVIDENCE.md#custom-outbound-adapter) verified a real decision and same-ID replay.
The case data and destinations are synthetic. Acceptance means the destination
recorded a receipt. A planned or simulated arrival is a separate state.

The [Visual Trace example](deployment/JURY-ROUTE.md#inspect-the-original-native-trace)
addresses [DPI-I-689](https://ideas.intersystems.com/ideas/DPI-I-689). Chronos
keeps the decision's metrics with the native message. [Langfuse](https://langfuse.com/docs/observability/overview)
supports broader observability across services. The case chat uses its own session.

[Validation and benchmark](deployment/EVIDENCE.md) · [Case contracts](deployment/JURY-CASE.md) ·
[Provider setup](deployment/CONVERSATION-PROVIDER.md) · [Scoped access](deployment/WEB-ACCESS.md)
