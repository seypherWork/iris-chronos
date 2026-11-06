# Paired E1 evaluation

Offline evaluator for Chronos, using the current preference-extraction contract
and shared deterministic option selection. It does not call a model, IRIS, a
destination, or the network. It never supplies approval or execution authority.

A plan contains 12 scenario slots (four per CHR family), both trial modes, one
R0 round and three R1 rounds. There are 96 variant-round slots, **not 96 independent
scenarios**. Labels remain a separate evaluator-only input. Never send the plan
or labels to the model: only its prepared wire context and configured instructions.

## Inputs and evidence boundaries

- `plan`: cases prepared by a trusted collector, original-input digests,
  E1 context bindings, profile/source/label hashes, split and deadline.
- `labels`: admissible decisions, preferences and pertinent sources per case.
  Multiple admissible decisions stay paired: matching an action from one and
  the interpretation from another does not satisfy joint correctness.
- `captures`: each scheduled case/variant/round, plan/input/profile digests,
  response or precontrol, request ID, total elapsed time, finish reason and
  optional observed tokens/cost. Record one invocation at most per slot.
- `base_capture` creates an explicitly NOT_STARTED metadata template. It is not
  an execution receipt. Missing/NOT_STARTED rows keep the denominator and
  prevent execution-complete claims.
- Only the model collector can substantiate a request. Hashes detect drift
  and mismatching records; they do not authenticate their author or prove
  that a native AI Hub agent executed. Reports always say
  `native_origin_verified: false`; link separate native evidence afterwards.

Both trial modes must retain the original-input digest. E1 modes must match
their declared mode/status and preserve the same non-trial facts/evidence.
The negative mode contains no trial observations or trial citations. Analytical
calculations remain allowed. Precontrol-only plans still require the original
input digest; checking that digest against original bytes is the collector's job.

The JSON CLI verifies source-file hashes and denies path escapes, duplicate JSON
keys and overwriting output. The Python `assess` function is pure and does not
read files or verify source bytes: callers perform that verification themselves.
Checking a source directory is not proof that those exact bytes were the modules
loaded by a particular Python process. Keep the invocation/interpreter/checkout
and external collector evidence; the scorer does not authenticate loaded code.

## Scoring

Only completed structured responses with provider finish `stop`, valid E1
assembly, and **total operation time strictly below 30 seconds** receive decision
credit. A late but structurally correct response remains contract-valid and
decision-incorrect. Timeouts, refusals, transport errors and malformed responses
are failures, never correct semantic HOLDs. Model time is separate from total
time. A captured finish or latency remains an assertion until collector evidence
is checked.

Decision, interpretation/citation relevance, reason, contextual accuracy, HOLDs,
unsafe attempts and uncertainty are separate. A correct action by coincidence
does not rescue a wrong preference. Precontrols are not model understanding.
Safety inspection runs even on a failed/tardy capture when raw text is available;
invalid-contract/unparseable/missing raw text is **unassessable**, not proof of zero unsafe attempts.
The evaluator detects forbidden authority/action fields in E1 output; it does
not prove runtime authorization or complete adversarial safety.

Per-round comparisons and the full case table preserve regressions; there is no
best-of-three selection. Stability distinguishes all three joint-correct results
from the same correct action/disposition across all three rounds. Unknown tokens
and monetary cost remain null in each row, not zero. Currencies are not combined.

Acceptance, delivery, native recovery and executed violations remain null.
No dispatch does not mean 100% safe. The evaluator does not decide P0/P1/P2/P3
or release readiness. Those require actual runtime evidence, honest provenance,
a frozen independently authored heldout corpus, utility and all other protocol
conditions. `ai_advantage` and `trial_advantage` remain NOT_ESTABLISHED.

## Running

From the repository's `src` directory with Python 3.11+:

```text
python -B -m chronos_evaluation --source-root .. --plan PLAN.json --labels LABELS.json --captures CAPTURES.json --output NEW-REPORT.json
```

Absolute input paths are recommended. Existing output files are refused.

`probes/paired-evaluation-68/development.py` prepares only the existing 12
development cases and measures the unchanged stronger R0 interpreter with shared
E1 assembly. Its local elapsed interval covers preparation and rule decision,
not IRIS/browser/human latency. It deliberately supplies **no R1 captures**.
A profile file is read only for binding; it does not start a provider, grant
spending, enlarge/reset an allowance or authorize a 36-call campaign.
This is development tooling, not the frozen heldout experiment.

Tests in `tests/evaluation/test_paired.py` use synthetic responses as negative
and positive controls of scoring logic. They are not measured AI performance.
