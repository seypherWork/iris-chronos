# Recorded fixture evidence

Eight real model completions were captured through the AI Hub SDK on IRIS AI Hub Community 2026.3.0AI.154.0: four fixed shipment preferences and four neutral explanation questions. The local provider was `chronos-qwen35:8k-full` (the pinned Qwen3.5 9B Q8_0 recipe). The corpus preserves the original completions.

These captures used synthetic inputs. They did **not** execute the installed application workflow, create application accounts or dispatch a recovery. A separate native application and browser rehearsal is required before claiming that route works.

## What replay does

`RECORDED_FIXTURE` reuses the captured interpretation for the exact shipped case or question. It does not call a model, generate fresh model tokens or support arbitrary chat. Current simulation, validation, authentication, preview, approval, dispatch fencing and readback must still run in the application. A recorded explanation plan selects subjects; current evidence supplies the displayed facts.

The four shipment cases are `economy`, `earliest`, `ambiguous` and `queue_inventory`. Accepted or uncertain original operations continue to use the existing deterministic safety controls. Questions outside the four declared prompts are unsupported in replay; use a configured live model for general interpretation.

## Inspect the saved records

Run `python -B deployment/evidence/fixture-bank-154-20261112/verify.py` from the source tree. This reads local files only; it does not start IRIS, Docker or a model. It checks the captured inputs, completions, receipt bindings, evidence hashes and closed fixture coverage. A successful result proves consistency of these saved records, not a new execution of IRIS or third-party attestation.

`corpus.json` is pinned by SHA-256 in the deployment profile. `evidence-allowlist.json` is an explicit independently supplied allowlist; the loader never creates trust from the corpus's own claims. `captures/` contains the synthetic SDK capture records used to review that allowlist. `summary.json` states the actual scope and limitations.
