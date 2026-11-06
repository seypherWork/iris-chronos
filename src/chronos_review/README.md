# Historical review detail projection

The trusted native bridge and browser review flow were verified in the earlier
native and browser milestones. Historical evidence does not grant authority.
Current candidate65 adds versioned model/code attribution; its native and visual
validation is recorded separately in planning/candidates/attribution65-20261030.

Candidate175 adds `chronos.review-detail.v3` when the original private call
contains valid AI Hub and interoperability session IDs, BEFORE_CHAT and a binding
timestamp within the decision lifetime. Only those IDs and the namespace from the
trusted native loader are exposed. No claim/transport ID, credential, prompt or
model response is copied. The HTTP reader's session ID is never substituted.
The AI Hub snapshot was saved before Chat and is not a completion transcript.
Native message retention and portal access remain separate checks. Missing both
IDs retains v2; partial or malformed bindings make the detail unavailable.
The browser keeps v1/v2 support and labels missing original trace explicitly.
The candidate bridge compiled under isolated test class names on AI Hub154 and
projected four unchanged original native records. Each bound interoperability
session retained seven message headers. This is read-only historical validation,
not a new model run or final installation. Authenticated portal traversal is pending.

Output `chronos.review-detail.v2` includes an enum-only `attribution` object.
E1 requires a matching frozen extraction binding and native call metadata:
preference interpretation MODEL; option selection DETERMINISTIC_CODE. The code
also binds identity and may normalize HOLD fields, so the final proposal is not
a verbatim model transcript. The original decision/consent digest is unchanged.
Legacy A1 records declare NOT_RECORDED; the client also accepts strict detailv1
without inventing attribution. Contradictory or partial E1 metadata is unavailable.
Only historical binding integrity is checked here: alternatives are not reranked.

## Input and output contract

project(decision_json, expected_id) accepts a private immutable ledger record
ONLY when loaded by a trusted native adapter. A browser must supply an ID, never
the record, its digest, a filesystem root, module name or serialized proposal.

For completed VALIDATED_PROPOSAL/VALIDATED_HOLD records it extracts:
- proposal action, interpreted preference, rationale, clarification and cited IDs;
- public recorded facts, source catalogue, provenance-tagged messages, known
  changes, destination evidence and the two recorded synthetic trial branches;
- original identities, timestamps, review deadline and the same immutable
  decision digest formula used by contract.review.

The result explicitly sets historical=true, currentAuthorityVerified=false,
canConfirm=false and dispatchGranted=false. HOLD and ablation remain non-authority.
A read does not establish the semantic correctness of an interpretation, current
feasibility, current permission, destination acceptance or delivery.
Malformed, inconsistent, oversized or secret-pattern-containing public material
returns a constant DECISION_DETAIL_UNAVAILABLE, without an exception/raw record.

Private instructions, input_json, runtime bindings/paths, authority stamps, claim,
transport and validation IDs are not copied. Public wire objects have exact
allowlisted schemas. Business payload remains extensible: additional bounded
JSON fields are retained rather than silently omitted from the effect.
Known credential keys/patterns are rejected; this is not a universal secret
detector. The product scope remains synthetic laboratory data only.

## Historical versus fresh validation

FINISH validates against freshly observed alternatives. Those can differ from
PREPARE solely because time advanced, without changed material facts. Therefore
this projector validates structure, identity, source membership and immutable
digest, but MUST NOT rerun proposal.check against prepared.record.available,
invent alternatives to pass a check, or declare the old branches current.

A native human preview still needs Context.Review with current observations,
runtime/authority checks and the original immutable decision binding. Rendering
a historical proposal does not satisfy CHR-H01 by itself.

## Required native integration (pending)

1. Extend the existing authenticated decision command family with a separate
   detail-read command under the same origin/CSRF/body and READ permission rules.
   Current READ is namespace-wide laboratory access, not a per-owner inbox.
2. Load the immutable record from Ledger INSPECT within trusted native composition,
   never HTTP JSON. Recheck identity/READ permission before and after projection.
3. Add a manifest-bound isolated loader for this package and its pinned proposal/
   model helpers. Current standalone absolute imports are suitable for local
   tests, NOT proof of compatibility with native namespace-specific module aliases.
   Do not loosen the existing agent package allowlist or globally patch sys.path.
4. Return only this public projection through the bounded API wrapper. Keep full
   record/instructions out of errors, Visual Trace, browser storage and logs.
5. Test native authorized/revoked readers, mismatched identity, repeated read,
   completed HOLD/error/pending decisions, private sentinels and response loss.
6. Connect the UI to this historical detail plus fresh preview; display times,
   provenance and citations as inert text. Full consent remains a separate action.

No loader, API, native installation or frontend detail consumer was changed by
this milestone. Do not mark complete review, permission enforcement or delivery
validated from these local tests.

## Local verification

Run the verified Python with -B tests/review/test_projection.py -v.
20 tests passed in0.016s. Inputs use a frozen development wire and explicitly
synthetic native-shaped records, not a new IRIS or model run.
Independent review reproduced the time-crossing defect with real pure
prepare/finish functions locally: PREPARE favored B, FINISH validated A, old
projection incorrectly returned unavailable. The committed local regression
reproduced RED16pass1fail; the fix no longer reranks historical data.
See probes/review-projection-38/evidence/20261029T185704Z-local/tests.txt.

## Isolated native loader source (milestone 39)

src/Chronos/Review/Python.cls now contains a candidate bridge. Its Python
Module/Evaluate bodies are tested locally from the exact class source.
Project rejects an active transaction and a namespace different from $Namespace;
these ObjectScript checks have NOT yet been compiled or executed in IRIS.

Module requires namespace/root-bound aliases from the existing simulator and
agent loaders, verifies their closed module graphs and source origins, and binds
the projection package manifest to both dependency manifests. It injects the six
specific helper objects; projection.py does not import global agent/simulator
packages when loaded this way. Names, roots or helpers must never come from HTTP.

Only __init__.py, projection.py and README.md belong to this package manifest.
The README is hashed but never executed. Changed files create a distinct alias;
old complete versions remain cached. Partial/foreign graphs, changed helper
bindings, unexpected files and origin changes fail closed. Failed compilation
removes only the new loader-owned alias. Trusted installation code and Python
interpreter integrity are assumptions; this is not a sandbox against arbitrary
code already executing inside the interpreter.

This class is not installed, compiled or called by Agent.Python, Approval.Entry
or Web.API yet. It does not itself authenticate, read the ledger, enforce READ
permission or establish current authority. The authenticated adapter and native
tests in the preceding integration checklist are still required. Existing
native agent/simulator sources and their manifests have not been changed.

The local loader tests create small owned copies under
runtime/review-loader39-tests and retain them for diagnosis; no container, model,
service or real external data is involved. Namespace simulation in a regular
Python process is not a claim of native IRIS execution.

## Trusted native adapter source (milestone 40)

Controller.DecisionDetail is called under the runtime boot lock. Its only
external argument is decisionId. It loads config.pythonRoot and Ledger INSPECT
internally, rechecks native READ/actor/session around the read and projection,
and checks current runtime generation again. This does not refresh a historical
proposal or make it actionable. READ remains namespace-wide laboratory access.

Agent.Python.Detail acquires the existing trusted simulator/agent aliases then
calls Review.Python.Project. Entry and both policy implementations accept the
separate DECISION_DETAIL read. The destination15 native runner stages this
package and loads Review.Python before Agent.Python. All this is uncompiled source.

Independent review found a real size mismatch: a valid 66,412-character detail
exceeded the previous 65,536-character Ens response property. The regression
failed locally before increasing Response.ResultJSON capacity to524288, allowing
JSON escaping of the bounded128KiB UTF-8 projection without truncation. Capacity
is not permission to return private material. ASCII and Unicode local fixtures
now pass; native persistence/readback tests remain NOT RUN.

The older run_http.py deliberately pins historical parent/backend evidence.
It will reject SOURCE_DRIFT with these changed sources. Do not bypass that check
or overwrite old reports: compile/test a new isolated backend and generate a new
verified installation chain first. No route has been enabled by this work.

Detailed checkpoint: planning/DETAIL-ADAPTER-40-20261029.md.

## Exact payload serialization for the UI (candidate milestone 41)

The public detail now also includes payloadJSON, produced by the server's
canonical(payload). It preserves numeric spelling and is rendered as inert text.
The typed context.payload remains available for comparison; the UI does not
rewrite payloadJSON through JavaScript Number/JSON.stringify. A cross-language
fixture with finite floats1e20 and1.25e-20 reproduced an earlier display rejection
and now retains the exact server JSON. Integer IDs/revisions/timestamps remain
bounded safe integers; only the extensible business payload accepts finite floats.

The added serialization duplicates bounded business data intentionally. Public
projection limit is now262144 UTF-8 bytes; context remains65536. Response storage
capacity remains524288 characters and the browser transport cap512KiB. Boundary
tests exercise ASCII, Unicode, quotes, backslashes and escaped control characters.
The server still never exposes private ledger/claim/session material. There is
no native install/compile/persistence claim for these source changes.
