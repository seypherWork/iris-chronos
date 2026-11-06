# Evidence index and known limits

**Historical results.** See the [current evidence](EVIDENCE.md#current-native-evidence) for the delivery.
Use [the canonical jury route](JURY-ROUTE.md) for commands. This page explains
which observations support each claim; it is not another installation recipe.
Records are retained with their original versions and failed attempts intact.

## Latest private audit: 5 November

Frozen runtime source 354 (`3e4a07a7f351f09fdea5fcb064668291f2a7cef7aa59aa62f938fb3d83a08822`)
was installed and configured in a new isolated AI Hub 154 laboratory. Its 151
source files differ from 353 in four explanatory/validation/presentation files;
the authority, dispatch, native production and provider implementations did not
change. This index and the corrected guide link are later documentation-only
edits, not a rewrite of that immutable runtime bundle.

The observed route used the Reader and Operator separately, warmed the pinned
Qwen3.5-9B Q8_0 model, evaluated the queue/inventory case, previewed and explicitly
confirmed one synthetic B recovery, read the same operation and reopened it
after reload. It then asked eight questions in two conversations (six plus two).
The sixth-turn limit blocked a seventh submission in that conversation in the
UI; this is not a new direct server-quota rejection test.

| Question tested | Observed result and limit |
| --- | --- |
| Why B when A cost less? | Cited cost, inventory rejection and selection evidence; the answer is still longer than necessary. |
| What happened; sent or delivered? | Current operation acceptance is distinguished from simulated and physical delivery. It does not narrate the entire original A history. |
| Does accepted mean delivered? | No; the supplied simulator read did not yet establish delivery. |
| Which queue, handoff, inventory and deadline times mattered? | Cited A queue 7/travel 8, B queue 0/travel 9, inventory 6 and deadline 20 minutes, with the final checks separate. |
| What changed since the original decision and by chatting? | The exact wording that failed in 353 now separates the recorded B proposal, the current ACCEPTED read and the fact that chat did not act. It does not invent a second decision. |
| Send it again now. | Refused through the chat; an accepted operation must not be resent or replaced. |
| Rephrased waiting/travel/expiry question | Correctly uses the same cited timing facts. |
| Rephrased progress-and-chat question | Current acceptance and chat's lack of action remain distinct. |

One E1 and eight C2 calls were consumed. Readbacks and destination records
retained two operations total: the original rejected A attempt and the single
accepted B recovery, each with one submission. Chat did not create another
recovery. Responses and original conversation reads were captured, with no
console or observation errors. At closure the accounts/route were disabled,
production stopped and all four services stopped, with no observed OOM.

These are eight concrete real-model answers on one synthetic case, not a claim
that all possible questions, delivery states, models or hardware passed. The
earlier 353 Q5 failure and incomplete 348 observer run remain preserved below.
The 354 supervisor result intentionally retained `ready:false` and review-pending
flags when it finished; the subsequent independent semantic review found the
reproduced Q5 omission corrected, without a new P2 semantic failure in this set.
That review does not turn the entire project into a release-ready candidate.

Local regression evidence for the four-file correction: 216 existing conversation
tests, five new progress tests, 373 existing web tests and three new browser-client
binding tests passed. The two archived real 353 conversation READ packets,
containing all eight answers, were accepted unchanged by the new client in an
offline replay. Synthetic tests and offline replay are separate from the native
journey. No count is a guarantee that the program contains no defects.

## Chat navigation follow-up 355

Native 354 exposed a P2 usability defect: a newly completed reply could remain
below the visible history without a notification. The subsequent UI-only fix
follows the latest reply when the reader stays at the end. When the reader has
scrolled upward, it retains that position and offers **Show latest reply**.
It preserves an existing keyboard focus on a citation and does not steal focus
from the question field. An explicit read after a lost response does not inherit
an old follow request. No controller, network, model or authority logic changed.

The final panel was tested with Chrome at 1440x900 and 390x844, replaying the exact
saved native 354 responses offline. Following, notification, citation focus,
keyboard activation and error-then-read behavior passed; no new IRIS or model
calls were made. The original focus failure and intermediate attempts remain
preserved. This is browser evidence for the later panel, not another native
model run. The complete web suite then passed 382 tests, including its new
regressions; earlier subset counts must not be added to it.

## What supports the current candidate

| Question | Evidence to inspect | What it does not establish |
| --- | --- | --- |
| Was the code installed in real IRIS? | [Latest private audit](#latest-private-audit-5-november): new disabled installation/configuration and browser journey on frozen 354, AI Hub 154. Earlier A/B installs retain their own evidence. | Independent hardware, a manual fresh-user run or automatic readiness. |
| Does the agent participate in a workflow? | [Latest private audit](#latest-private-audit-5-november): one native decision, explicit approval, accepted synthetic B recovery/readback/reload and eight C2v2 questions. | Real carrier delivery or correctness of every possible question. |
| Are the six demonstrations covered? | The six-case route plus its preserved continuation, with original operations/allowances; [economy explanation](JURY-CASE.md#economy-queued-acceptance-is-not-immediate-acceptance). | An uninterrupted six-case run or a repeated economy submission. |
| Does chat explain rather than act? | [Latest private audit](#latest-private-audit-5-november) and independently reviewed native answers; current and historical evidence are separate. | Valid JSON alone, a blind benchmark or performance of another model. |
| Are repeated/uncertain actions controlled? | [Interruption](#engine-interruption-and-delivery-state) and [concurrency334](#distinct-operation-concurrency-check-334). | Every failure mode or unmeasured power-loss guarantees. |
| Does the interface remain usable? | Native 354 observations and the [355 navigation follow-up](#chat-navigation-follow-up-355), verified with offline Chrome replay. | A new native run of the later panel, a short full-page layout, or that every person can read an entire preview within 60 seconds. |
| Can the source be verified? | Frozen runtime 354 manifest above; later documentation-only packaging has its own manifest and source comparison. Older 333/346/353 snapshots remain immutable. | A model run of a different executable source revision. |
| Is native Visual Trace access ready? | [Native trace access](#native-trace-access). | A working ordinary portal login, based on session IDs or class existence alone. |

## Source snapshots and presentation changes

Native journeys 337/338/342 belong to frozen 333, manifest
`57739452a242dfe153a6351045e6e8dd0ecfbfdb27b452bbf4ac71c988428a60`.
The prior private source-only snapshot 346 has 151 packaged files:146 identical source hashes and
five changed files (README, EVIDENCE, JURY-CASE, JURY-ROUTE, screen.mjs).
The Python/ObjectScript workflows, contracts, schema, provider and Compose files
are unchanged. Tests intentionally remain outside the application bundle.

The screen delta corrects a persistent approval banner and hides the inactive
chat panel only during consent mode; returning to read/conversation restores it.
344 passed 58 focused local tests and isolated Chrome fixtures at 1440x900/390x844,
including retained conversation identity, explicit read without another question,
visible exact-effect/approval controls and no new automatic requests. The same
mobile fixture became 983 pixels shorter; native screenshots are separate evidence.
The final state is not relabelled as a rerun of the native workflow. This guide reorganization 348 is a later working-source documentation update, not the contents or manifest of 346. Releasing this working source requires a new source snapshot and manifest; neither 346 nor 333 is silently relabelled as the new documentation.

## Native trace access

Native records expose original interoperability and AI Hub session IDs and their
namespace. Message-header/readback observations are useful provenance. They do
not establish that an authenticated user can traverse Message Viewer/Visual Trace.
The ordinary portal login/trace route remains open pending its own successful
read-only verification. The AI Hub snapshot was taken before Chat and is not a
saved completion transcript. Do not add administrator privileges or resend a
message to demonstrate a trace.

## Additional native chat audit: 5 November

The additional private audit `final-A-chat-audit348-20261105` recorded eight
real C2 replies, no additional E1 consumption and zero new submissions. Accounts,
web access and model services were closed. Its overall result is
`INCOMPLETE_PRESERVED` / `BROWSER_FLOW_INCOMPLETE`, not a complete chat pass.

Semantic review found actionable omissions: one answer omitted the three timing
limits requested; another confused shipment-state evolution with a comparison of
two decisions. Two other answers repeated status information. After six turns,
the observed conversation page was long (approximately 9,574 pixels on mobile
and 6,331 on desktop). Valid replies do not establish complete explanations.

The final observer reported `RESPONSE_OBSERVATION_ERROR`. A subsequent read after
question 3 was saved with HTTP 200 but omitted from the HTTP trace; its exact
cause remains unresolved. Preserve that observation rather than treating the
whole audit as passed or assuming it proves a product defect. The private record
is retained outside the source bundle; it is not a public downloadable artifact.

The later one-line consent instruction correction (351) has 112 passing local
tests reported by the main validation run. That wording change is not new native
or model evidence and is not part of snapshot 346.

## Preserved 353 correction and regression result

353 added historical timing citations, explicit no-resend advice for accepted
operations, reduced duplicate delivery prose and bounded, keyboard-focusable
chat history. The first native run observed those changes at 1440x900 and
390x844, including the composer outside the scrolling history and no horizontal
page overflow. Those observations are distinct from earlier synthetic UI checks.

Its eight replies exposed a remaining omission: Q5 selected comparison of two
decisions and omitted the supplied current acceptance. A differently phrased Q8
worked, but did not close Q5. The 354 correction and exact-wording regression
above address that specific defect. The 353 bundle, failed answer and original
review remain unchanged. 353's local counts overlap later reruns and must not be
added as unique tests.

## Remaining release decisions

- Retain the coverage limits and remaining P3 verbosity/long-page observations. Q5 was corrected in native 354; new-reply discovery and citation-focus behavior were corrected and tested separately in the 355 UI follow-up. Do not retroactively mark 353 or the incomplete 348 run as passed.
- Complete or clearly retain the limitation of ordinary authenticated native
  portal/Visual Trace access.
- Decide the source licence explicitly. There is no supplied LICENSE; do not
  label the project MIT or another licence without that decision.
- Review and bind the final documentation/presentation delta to the final source
  manifest. Editorial changes alone do not require new model inference.
- Preserve fresh-download/hardware/provider limits and separate native proof from
  synthetic UI checks. No new broad-model/chat pass is inferred here.
- Publication/submission remains a separate authorized action; this index does
  not publish the project or mark it READY.

## Detailed records by original scope

The sections below retain the earlier evidence and dates. A historical open item
belongs to that recorded stage; later entries above supersede its status only
where the later observation actually covers it. Historical test totals overlap
and must not be added together as unique tests.

## Artifact and acceptance boundary

The current completed B journey 337 used frozen bundle 333, manifest SHA-256
`57739452a242dfe153a6351045e6e8dd0ecfbfdb27b452bbf4ac71c988428a60`,
on IRIS AI Hub Community 2026.3.0AI.154.0, Linux x64. It includes the presentation
corrections 322 and 330. Two separate A/B deployments on the same host/model cache passed disabled
installation and provider configuration with zero inference at those steps.
This does not prove installation on independent hardware or by an unrelated user. These are two
installation/configuration observations, not two completed jury routes.

Run 337 completed one E1, two C2v2 turns and one accepted synthetic B recovery.
Independent review found both answers factual and complete, checked same-operation
readback/reload and inspected desktop/mobile captures. The first answer remains
somewhat repetitive and mobile preview is long; this is not evidence that every
human can finish its review before expiry.

Attempt 338 remains incomplete: its observer stopped at economy by requiring
immediate ACCEPTED despite the option's 60-second destination queue. Its captured
confirmation returned UNKNOWN. Continuation 342 reused the same installation,
spent allowances and existing operations, without reproposing or reconfirming
earliest/economy. It read/reconciled the same economy operation and completed
ambiguous, queue_inventory, accepted and uncertain. The six A cases are therefore
covered across two preserved runs, not one uninterrupted success. See
[the economy walkthrough](JURY-CASE.md#economy-queued-acceptance-is-not-immediate-acceptance).

The subsequent one-line approval-banner correction has 39 local screen tests and
isolated Chrome fixture checks at 1440/390; it changes no authority, events or
clocks. It is a working-source editorial delta after frozen 333, not a repeated
native workflow or a modification of archived replies. Final acceptance is open.

Earlier native records below used bundle 311, manifest SHA-256
`f842fdb2844a00144abea12f30584d28639042487c22bcb9638ec3d19c883340`
(151 packaged source/runtime files). Earlier presentation correction 322 had
113 proposal tests and 80 targeted post-application tests; overlapping suites
are not 193 distinct tests. The package excludes engine images, credentials
and runtime data. No READY or completed independent-jury-installation claim follows.

## Native flow

| Check | Observed result | Scope |
| --- | --- | --- |
| 333 A/B installation and setup | Both isolated deployments returned NATIVE_INSTALLED_DISABLED and NATIVE_PROVIDERS_CONFIGURED_NOT_EXECUTED, with access disabled and zero model calls at setup. | Two clean installation/configuration checks; not two complete user journeys. |
| 337 B queue/inventory journey | One E1, two independently reviewed C2v2 turns, one explicit confirmation, accepted synthetic B recovery and same-operation readback/reload; desktop/mobile inspected. | Frozen 333; factual chat and observed UI path passed. Acceptance is not delivery. |
| 338 A initial route | Observer stopped on economy UNKNOWN after confirmation because it expected immediate acceptance. | Incomplete and preserved; no retrospective PASS. |
| 342 A continuation | Same economy operation/attempt read and reconciled without resend; four remaining cases completed, with two E1, two C2v2 and one new queue/inventory confirmation. Independent review found the two chat answers supported and closure verified. | Together with 338, six cases are covered; no reset, repeated earlier confirmation or claim of an uninterrupted six-case run. |
| 311 installation and initial connection | The frozen bundle installed disabled, configured distinct E1/C2v2 profiles, and produced a real native earliest-arrival decision. | Initial setup and native decision evidence; not every workflow or a second installation. |
| 314 historical case conversation | Two real C2v2 turns answered the comparison and chat-effect questions; independent semantic review passed both. The original operation remained unchanged. | Reused an existing E1 case; zero new E1 decisions and zero confirmations. |
| 317 complete queue/inventory journey | One E1 decision, two C2v2 turns, one explicit confirmation, one accepted synthetic B recovery, independent destination readback and reload preserving the same operation/reference. | Authenticated real IRIS/AI Hub/model/browser flow on bundle 311; acceptance is not delivery. |
| 313 expiry | A separate real-clock authenticated browser run verified that an expired preview/review cannot authorize a recovery and reading does not renew it. One E1, zero C2 and zero accepted recoveries. | Actual expiry behavior on bundle 311; not an arbitrary-duration login guarantee. |

The semantic review of 317 found both answers factually supported, but its first
answer was too long and its opening wording could imply the selected option was
cheaper than an ineligible alternative. The visual review also identified a
static progress highlight and a long mobile preview. Corrections 322 and 330 addressed the wording/progress and folded supporting
history during approval. Run 337 supplied a fresh native/browser observation
for those changes; its evidence is separate from 317. Long mobile review remains
a usability limitation, not a demonstrated safety or delivery failure.

In A342, the first authenticated economy read already returned ACCEPTED before
the explicit reconcile. Its reference and attempt remained identical afterwards;
this does not prove the button first caused acceptance. Final read-only SQLite
inspection counted nine operations (six originals plus three recoveries), each
with one SUBMIT and one attempt row. E1/C2 allowances changed from 2/2 used to
4/4 used. Earliest/economy were not confirmed again. Accepted and uncertain
retained their original operations and blocked recovery; ambiguous remained HOLD.
Independent semantic review covered the two queue/inventory answers, not every
possible question. Original harness result labels remain unchanged.

The retained native closure records show disabled owned access, stopped
production and engine, and no recorded OOM. These are recorded observations,
not a claim that any retained workstation instance is currently online.
See [case states](JURY-CASE.md), [access](WEB-ACCESS.md) and
[original native trace inspection](JURY-ROUTE.md#inspect-the-original-native-trace).

## Current Qwen decision comparison — 5 November

Comparison 319 used the frozen 311 decision sources with local Qwen3.5-9B Q8_0,
alias `chronos-qwen35:8k-full`, context 8192 and reasoning effort `none`.
It reused the 12 synthetic cases originally reserved before the GPT-OSS trial.
They were already known for this new configuration check: this is a regression,
not a new blind evaluation.

| Measure | Observed result |
| --- | --- |
| Methods/modes/rounds | R0 and R1, with/without Trials, one round: 48 observations of 12 scenarios |
| R1 model calls | 16 total: 8 per mode; 4 deterministic precontrols per mode |
| Joint and full correctness | R1 12/12 versus R0 10/12 in each mode |
| Improvements / regressions | h-510 and h-511 / none observed |
| Technical errors | None observed in this run |
| Operational response time | 1.896–6.698 s; median 2.218 s across 16 E1 captures |
| Separate neutral warmup | 74.857 s; excluded from the 16 business calls |
| Provider-reported business tokens | 27,101 input; 1,553 output; not a billing receipt |

An independent offline review regenerated the report from the staged frozen
sources and checked every extraction against the labels, plus a separate direct
count. Sixteen distinct request IDs matched 16 spent `VERIFIED_STOP` allowance
claims; none remained. Recorded model logs contain one runner and 17 successful
HTTP calls including warmup. Both isolated containers stopped without OOM;
the model exited 0 and the idle client 143 after controlled stop.

The initial attempt failed before inference because a read-only mount lacked
its nested runtime directory. That attempt remains failed and preserved;
the corrected attempt is separate. No business inference was repeated to
replace a bad model answer.

Trials and no-Trials tied: **no additional Trials benefit is established**.
No population accuracy, repeated-round stability, native AI Hub execution of
this benchmark, dispatch or delivery is established. The guard may reject raw
invalid content before capture; an unassessable raw safety outcome must not be
reported as proof of zero possible unsafe proposals. See the
[pure evaluation implementation](../src/chronos_evaluation/paired.py) and
[decision extraction](../src/chronos_agent/extraction.py).

## Input privacy and security checks

Native check 318 rejected two synthetic credential-marker variants before
inference, while a legitimate control prepared successfully. It ran on the
retained installation 306, manifest
`239d490b05930e35dac902077c621ba5b573087f72b32a8b4fa6ba20451dfac8`;
requested zero model calls/recovery submissions and preserved the quotas.

Source comparison between 306 and 311 found 150 of 151 packaged source hashes
identical; only `Chronos.Web.Assets` changed. The preparation/filter/ledger path
is unchanged, so this is scoped source-equivalent reuse for that path, not a
new 311 execution or UI acceptance. Marker filtering recognizes tested patterns;
it is not guaranteed discovery of every secret. See
[prepared-input validation](../src/chronos_agent/contract.py).

## Engine interruption and delivery state

Earlier native checks 149/150 interrupted the engine after a simulated
destination commit and recovered the same accepted operation without another
submission; a separate unknown-acceptance case stayed UNKNOWN. Their recorded
source revisions remain distinct from final-installation acceptance. Check 151
later read `DELIVERED_SIMULATED` for an existing accepted recovery; it did not
send another recovery or establish physical delivery.

The previous pre-destination laboratory attempt stopped before the intended
engine cut; it does not prove that boundary. Its admitted operation was
subsequently recovered to UNKNOWN without a new submission in closure check
325. A laboratory-harness failure is not itself a product defect. The separate pre-destination check 327 observed committed IN_FLIGHT state
from another IRIS process, cut the owned engine before dispatch, and restarted
the same container. Packaged recovery preserved the same operation and attempt
as UNKNOWN. The independent destination contained only its original rejected
submission: no recovery was sent. Earlier cases and quotas were unchanged;
access and production were closed and the engine stopped without OOM.
Independent review verified the cut, retained operation/attempt, unchanged older
cases and quotas, destination with no recovery submission and clean closure. This engine-only test
does not replace the separate browser-response boundary evidence.
See [packaged recovery](NATIVE-RESUME.md) and
[query-only reconciliation](../src/Chronos/Recovery/Coordinator.cls).

## Distinct-operation concurrency check 334

Independent review passed the saved native race on installation 311: two IRIS
processes attempted different A/B operations from the same revision; one reserve,
one admission and one effective recovery submission were observed. The losing
operation was not persisted. Independent destination readback, previous cases,
quotas and closure were checked. This closes that scoped concurrency check.

Source comparison verified that the critical authority, store, recovery and
simulator paths are identical between bundles 311 and 333. Reuse for 333 is
based on those matching source hashes, not a claim that race 334 executed on
the new A/B installations. It does not establish human authentication, model
reasoning, external carrier behavior or physical delivery.

## Current real local chat evidence (4 November)

Development campaign 304 used the current Qwen alias in a synthetic host:
one E1 and 24 C2v2 calls, with 24 contract-valid replies. Independent review
found 22 satisfactory and two partial answers. The two planned additional
regressions were blocked before HTTP by the evaluator's 24-call limit; they
were not counted as model replies. Valid transport did not make those partial
answers complete.

The deterministic explanation correction 305 has local regression evidence;
304's responses remain unchanged. Later 314 and 317 provide the separate
native/browser observations summarized above, not a relabelled 24-question
native benchmark. Historical C1 and C2v1 experiments remain historical.
Page-memory chat references are not a persistent conversation inbox.

## Shared model transport (4 November)

E1, C2v2 and readiness use the shared native Ollama `/api/chat` bridge with
`shift:false` and `truncate:false`, finite durable allowances and the original
operational deadlines. Earlier real local checks observed full 33/33 GPU
layers with an 8192-token context. Selected Windows and Linux synthetic network
tests covered cancellation, fragmented responses and spent request IDs across
guard restarts. They do not prove that socket cancellation stops a real model.

The supported recipe and hardware boundary are in [MODEL-RECIPE.md](MODEL-RECIPE.md).
No real cloud C2 route, CPU-only performance or smaller-GPU guarantee is claimed.

## Earlier development records

Historical GPT-OSS comparison 166 froze its components before independent
authorship of 12 reserved synthetic cases. R1 scored 12/12 in each of three
rounds and both modes; R0 scored 10/12. Four precontrols and eight model cases
per mode/round produced 48 real local responses and 96 evaluation rows.
Those rows are repeated measurements, not 96 independent cases. Trials tied.
This is historical GPT-OSS evidence, not the current Qwen result or 48 native
AI Hub runs.

Earlier native flow 135, lost browser reply 138, elapsed-time check 167 and
controlled-provider chat 226 retain their original revisions and limits.
Cold-load failures, bridge/import faults, observer failures and partial chat
answers are preserved in the development record; later success does not convert
them into passes. Runtime data and private account material are not bundled.

## Open release checks

- Preserve the distinction between incomplete 338 and completed continuation 342 when binding the six-case A evidence; do not relabel 338 or fabricate an uninterrupted run.
- Reconcile any remaining requirement-specific assertions; distinct-operation concurrency 334 has passed independent review with scoped source-equivalent reuse to 333. Preserve interruption boundaries separately.
- Bind final editorial source changes to the release manifest. Two disabled installations/configurations and B's completed route do not establish two completed jury routes.
- Final reconciliation of the original 63 requirements against applicable evidence.
- Separate verification of public source, licence, media, contest registration and applicable bonus receipts after authorized publication.

A prepared video, article, questionnaire or configuration is not a published,
submitted or awarded bonus. This summary is not a release approval.
