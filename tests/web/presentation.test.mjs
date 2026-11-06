import test from "node:test";
import assert from "node:assert/strict";
import {decisionView, operationView, previewView, irisSecondsUTC, unixMicrosecondsUTC}
  from "../../src/chronos_web/presentation.mjs";
import {renderResult} from "../../src/chronos_web/render.mjs";

const unixMs = Date.parse("2026-10-29T18:00:00.000Z");
const irisSeconds = 4070908800 + unixMs / 1000;
const ctx = {expectedId: "d1", evidence: "LOCAL_FIXTURE"};
const packet = data => ({code: data.code, traceSessionId: 7, data});
const decision = () => ({
  code: "EXISTING_DECISION", dispatchGranted: false, inferenceGranted: false, dispatch_authorized: false,
  requestId: "d1", orderId: "o1", shipmentVersion: 1, generation: "gen1",
  deadlineUS: (unixMs + 30000) * 1000, mode: "WITH_TRIALS", state: "COMPLETED",
  outcome: {status: "VALIDATED_PROPOSAL", code: "SEMANTICS_AND_HUMAN_REVIEW_REQUIRED", dispatch_authorized: false},
});
const operation = () => ({code: "READ_ONLY", dispatchGranted: false, operationId: "op1",
  attemptId: "attempt1", state: "ACCEPTED", reference: "simulated-receipt-1", quarantined: false});
const preview = () => ({
  code: "READ_ONLY", dispatchGranted: false, previewId: "p1", state: "PENDING",
  decisionId: "d1", decisionDigest: "a".repeat(64), orderId: "o1", shipmentVersion: 1,
  operationId: "op1", actor: "fixture-operator", generation: "gen1", snapshotId: 2,
  option: "FAILOVER_B", target: "B", createdAt: irisSeconds, expiresAt: irisSeconds + 60,
  reviewDeadlineUS: (unixMs + 300000) * 1000, predictedArrival: irisSeconds + 120,
  snapshot: {orderId: "o1", shipmentVersion: 1, revision: 2, policyRevision: 1,
    quantity: 1, payload: "synthetic shipment", maxCost: 8, observedAt: irisSeconds,
    inventoryUntil: irisSeconds + 300, deliveryDeadline: irisSeconds + 600,
    offers: Object.fromEntries(["A", "B"].map(target => [target, {
      target, cost: target === "A" ? 2 : 5, availableAt: irisSeconds, queueSeconds: 0,
      travelSeconds: 120, validUntil: irisSeconds + 300, capacity: 2,
    }]))},
});
const values = view => view.rows.map(row => row.value).join("\n");

test("IRIS seconds and Unix microseconds display the same UTC instant", () => {
  assert.equal(irisSecondsUTC(4070908800), "1970-01-01T00:00:00.000Z");
  assert.equal(irisSecondsUTC(irisSeconds), "2026-10-29T18:00:00.000Z");
  assert.equal(unixMicrosecondsUTC(unixMs * 1000), "2026-10-29T18:00:00.000Z");
  assert.equal(unixMicrosecondsUTC(unixMs * 1000 + 999), "2026-10-29T18:00:00.000Z");
  assert.equal(irisSecondsUTC(irisSeconds + 0.5), "2026-10-29T18:00:00.500Z");
});

test("invalid time types, overflow and nonfinite values do not get fabricated dates", () => {
  for (const bad of [-1, Infinity, NaN, "123", null, {}, Number.MAX_VALUE]) {
    assert.equal(irisSecondsUTC(bad), null);
    assert.equal(unixMicrosecondsUTC(bad), null);
  }
  assert.equal(unixMicrosecondsUTC(1.5), null);
});

test("a validated proposal is explicitly review-required, never approved or dispatched", () => {
  const view = decisionView(packet(decision()), ctx);
  assert.equal(view.available, true);
  assert.equal(view.title, "Proposal requires human review");
  assert.equal(view.canConfirm, false);
  assert.notEqual(view.tone, "success");
  assert.equal(view.evidenceLabel, "Local fixture — no IRIS execution");
  assert.match(view.summary, /Meaning, evidence/);
});

test("every nonterminal decision state remains pending or uncertain", () => {
  for (const state of ["PREPARED", "IN_FLIGHT", "VALIDATING", "UNCERTAIN", "UNCERTAIN_VALIDATION"]) {
    const d = decision(); d.state = state; delete d.outcome;
    const view = decisionView(packet(d), ctx);
    assert.equal(view.available, true);
    assert.equal(view.tone, "warning");
    assert.equal(view.canConfirm, false);
  }
});

test("HOLD is distinct from technical ERROR, rejection and recheck", () => {
  const titles = new Set();
  for (const status of ["VALIDATED_HOLD", "ERROR", "REJECTED", "RECHECK_REQUIRED"]) {
    const d = decision(); d.outcome.status = status;
    const view = decisionView(packet(d), ctx);
    assert.equal(view.available, true);
    assert.equal(view.canConfirm, false);
    assert.notEqual(view.tone, "success");
    titles.add(view.title);
  }
  assert.equal(titles.size, 4);
});

test("deterministic precontrols are historical, model-free and never actionable", () => {
  for (const code of ["EXISTING_ACCEPTANCE", "ACCEPTANCE_UNRESOLVED"]) {
    const d=decision(); d.outcome={status:"DETERMINISTIC",code,dispatch_authorized:false};
    const view=decisionView(packet(d),ctx);
    assert.equal(view.available,true);
    assert.equal(view.canConfirm,false);
    assert.notEqual(view.tone,"success");
    assert.match(view.summary,/no model was invoked|No model was invoked/);
    assert.match(values(view),/no model invocation/);
    assert.ok(view.rows.some(r=>r.label==="Check recorded (UTC)"));
    assert.equal(view.rows.some(r=>r.label==="Original deadline (UTC)"),false);
    d.outcome.code="UNREVIEWED_CODE";
    assert.equal(decisionView(packet(d),ctx).available,false);
  }
  const d=decision(); d.outcome={status:"DETERMINISTIC",code:"EXISTING_ACCEPTANCE",dispatch_authorized:false};
  d.resolution={previousState:"IN_FLIGHT",resolvedUS:unixMs*1000,inferenceMayHaveRun:true,providerCancellationVerified:false};
  assert.equal(decisionView(packet(d),ctx).available,false);
});

test("status resolution does not imply provider cancellation or a new inference", () => {
  const d = decision(); d.code = "DECISION_RESOLVED"; d.outcome.status = "ERROR";
  d.resolution = {previousState: "IN_FLIGHT", resolvedUS: unixMs * 1000,
    inferenceMayHaveRun: true, providerCancellationVerified: false};
  const view = decisionView(packet(d), ctx);
  assert.equal(view.available, true);
  assert.match(values(view), /Not verified/);
  d.resolution.providerCancellationVerified = true; // Not supported by current native contract.
  assert.equal(decisionView(packet(d), ctx).available, false);
});

test("known extraction failures explain the recorded rejection without enabling approval", () => {
  const examples = [
    ["INVALID_SOURCES", /source catalog/],
    ["INVALID_SOURCES_LIST", /list/],
    ["INVALID_SOURCES_COUNT", /1.*16/],
    ["INVALID_SOURCES_TYPE", /text/],
    ["INVALID_SOURCES_UNKNOWN", /source catalog/],
    ["INVALID_SOURCES_DUPLICATE", /repeated/],
    ["CURRENT_SOURCE_REQUIRED", /applicable message/],
    ["STRUCTURED_POLICY_MISMATCH", /structured preference/],
    ["EXTRACTION_CONTRACT_MISMATCH", /wrong schema/],
    ["CALL_CONTEXT_MISMATCH", /original context/],
    ["INVALID_AVAILABLE", /option data/],
    ["SENSITIVE_OUTPUT", /Sensitive-looking content/],
  ];
  for (const [code, meaning] of examples) {
    const d = decision(); d.outcome = {status: "ERROR", code, dispatch_authorized: false};
    d.outcome.detail = "PRIVATE_SENTINEL"; d.outcome.rationale = "PRIVATE_SENTINEL";
    const view = decisionView(packet(d), ctx);
    assert.equal(view.available, true);
    assert.equal(view.title, "Agent error");
    assert.equal(view.tone, "error");
    assert.equal(view.canConfirm, false);
    assert.match(view.rows.find(r => r.label === "What this means").value, meaning);
    assert.ok(view.rows.some(r => r.label === "Suggested next step"));
    assert.equal(JSON.stringify(view).includes("PRIVATE_SENTINEL"), false);
  }
});

test("an old generic error does not acquire a guessed specific cause", () => {
  const d = decision(); d.outcome = {status: "ERROR", code: "INVALID_PROPOSAL", dispatch_authorized: false};
  const view = decisionView(packet(d), ctx);
  assert.match(values(view), /No more specific cause was recorded/);
  assert.doesNotMatch(values(view), /wrong schema|outside this decision's source catalog/);
  assert.equal(view.canConfirm, false);
});

test("a timeout explanation never claims the provider was cancelled", () => {
  const d = decision(); d.outcome = {status: "ERROR", code: "MODEL_TIMEOUT", dispatch_authorized: false};
  const view = decisionView(packet(d), ctx);
  assert.match(values(view), /does not prove that provider execution was cancelled/);
  assert.equal(view.canConfirm, false);
});

test("unknown codes and other outcome states do not receive invented explanations", () => {
  for (const [status, code] of [["ERROR", "NEW_UNKNOWN_CODE"], ["VALIDATED_HOLD", "INVALID_SOURCES"],
    ["VALIDATED_PROPOSAL", "INVALID_SOURCES"]]) {
    const d = decision(); d.outcome = {status, code, dispatch_authorized: false};
    const view = decisionView(packet(d), ctx);
    assert.equal(view.rows.some(r => r.label === "What this means"), false);
    assert.equal(view.rows.some(r => r.label === "Suggested next step"), false);
    assert.equal(view.canConfirm, false);
  }
});

test("unknown and contradictory decision records are unavailable rather than successful", () => {
  for (const mutate of [
    d => {d.requestId = "other";}, d => {d.state = "SUCCESS";},
    d => {d.outcome.status = "APPROVED";}, d => {d.inferenceGranted = true;},
    d => {d.shipmentVersion = "1";}, d => {d.mode = "LIVE";},
    d => {d.state = "PREPARED";}, d => {delete d.outcome;},
    d => {d.outcome.dispatch_authorized = true;},
  ]) {
    const d = decision(); mutate(d);
    assert.equal(decisionView(packet(d), ctx).available, false);
  }
});

test("a missing decision never implies that an earlier effect did not happen", () => {
  const view = decisionView(packet({code: "NOT_FOUND"}), ctx);
  assert.match(view.summary, /earlier business operation may still exist/);
  assert.notEqual(view.tone, "success");
  assert.equal(view.canConfirm, false);
});

test("operation acceptance needs bound identity, attempt, reference and nonquarantined data", () => {
  const view = operationView(packet(operation()), {expectedId: "op1", evidence: "LIVE"});
  assert.equal(view.available, true);
  assert.equal(view.title, "Acceptance recorded");
  assert.match(view.summary, /not proof of simulated or physical delivery/);
  assert.equal(view.canConfirm, false);
  for (const mutate of [
    d => {d.operationId = "other";}, d => {delete d.attemptId;}, d => {d.reference = "";},
    d => {d.quarantined = 0;}, d => {d.dispatchGranted = true;}, d => {d.state = "DELIVERED";},
  ]) {
    const d = operation(); mutate(d);
    assert.equal(operationView(packet(d), {expectedId: "op1"}).available, false);
  }
});

test("contradictory evidence overrides recorded ACCEPTED state", () => {
  const d = operation(); d.quarantined = true; d.code = "CONTRADICTORY_EVIDENCE";
  const view = operationView(packet(d), {expectedId: "op1", evidence: "LIVE"});
  assert.equal(view.available, true);
  assert.equal(view.tone, "error");
  assert.match(view.title, /quarantined/);
  d.quarantined = false;
  assert.equal(operationView(packet(d), {expectedId: "op1"}).available, false);
});

test("UNKNOWN, IN_FLIGHT and final nonacceptance cannot authorize another dispatch", () => {
  for (const state of ["UNKNOWN", "IN_FLIGHT", "NOT_ACCEPTED_FINAL"]) {
    const d = operation(); d.state = state; d.reference = "";
    const view = operationView(packet(d), {expectedId: "op1", evidence: "LIVE"});
    assert.equal(view.available, true);
    assert.equal(view.canConfirm, false);
    assert.notEqual(view.tone, "success");
    assert.match(view.summary, state === "NOT_ACCEPTED_FINAL" ? /new current-state check/ : /do not resend/);
  }
});

test("an outer failure cannot conceal an inner success-shaped object", () => {
  const envelope = packet(operation()); envelope.code = "APPROVAL_RESULT_UNAVAILABLE";
  assert.equal(operationView(envelope, {expectedId: "op1"}).available, false);
});

test("replay, fixture and unverified provenance remain visible even for acceptance", () => {
  for (const evidence of ["REPLAY", "LOCAL_FIXTURE", "UNVERIFIED", "invalid"]) {
    const d = operation(); d.evidence = "LIVE";
    const view = operationView(packet(d), {expectedId: "op1", evidence});
    assert.notEqual(view.evidence, "LIVE");
    assert.notEqual(view.tone, "success");
    assert.ok(view.evidenceLabel);
  }
});

test("preview preserves exact payload and cost units without inventing currency or permission", () => {
  const d = preview(); d.snapshot.payload = "line 1\n<not HTML>\u0000";
  const view = previewView(packet(d), {expectedId: "p1", evidence: "LOCAL_FIXTURE"});
  assert.equal(view.available, true);
  assert.equal(view.canConfirm, false);
  assert.equal(view.rows.find(row => row.label === "Exact payload (JSON string)").value, JSON.stringify(d.snapshot.payload));
  assert.equal(view.rows.find(row => row.label === "Cost units").value, "5");
  assert.match(view.summary, /complete proposal, sources/);
  assert.match(values(view), /2026-10-29T18:01:00.000Z/);
});

test("preview identity and snapshot cannot silently cross an order, revision or destination", () => {
  for (const mutate of [
    d => {d.previewId = "other";}, d => {d.snapshot.orderId = "different";},
    d => {d.snapshot.shipmentVersion = 2;}, d => {d.target = "A";},
    d => {d.snapshot.offers.B.target = "A";}, d => {d.decisionDigest = "bad";},
    d => {d.expiresAt = d.createdAt - 1;}, d => {d.snapshot.offers.B.cost = "5";},
    d => {d.snapshot.payload = "x".repeat(65537);}, d => {d.snapshot.payload = "界".repeat(22000);},
    d => {d.operation = operation();},
  ]) {
    const d = preview(); mutate(d);
    assert.equal(previewView(packet(d), {expectedId: "p1"}).available, false);
  }
});

test("confirmed preview is not acceptance and missing operation readback remains explicit", () => {
  const d = preview(); d.state = "CONFIRMED";
  const view = previewView(packet(d), {expectedId: "p1", evidence: "LIVE"});
  assert.equal(view.available, true);
  assert.equal(view.title, "Confirmation recorded");
  assert.match(view.summary, /not acceptance/);
  assert.equal(view.operation, null);
  assert.notEqual(view.tone, "success");
});

test("nested operation must match the confirmed preview operation reference", () => {
  const d = preview(); d.state = "CONFIRMED"; d.operation = operation();
  const view = previewView(packet(d), {expectedId: "p1", evidence: "LOCAL_FIXTURE"});
  assert.equal(view.operation.available, true);
  d.operation.operationId = "different";
  assert.equal(previewView(packet(d), {expectedId: "p1"}).operation.available, false);
});

test("private fields and unknown nested content never enter the display model", () => {
  const d = preview();
  d.sessionBinding = "SECRET_SENTINEL"; d.claimId = "SECRET_SENTINEL";
  d.snapshot.secret = "SECRET_SENTINEL"; d.snapshot.offers.A.private = "SECRET_SENTINEL";
  const view = previewView(packet(d), {expectedId: "p1"});
  assert.equal(JSON.stringify(view).includes("SECRET_SENTINEL"), false);
  d.snapshot.payload = "changed later";
  assert.equal(values(view).includes("changed later"), false);
  assert.ok(Object.isFrozen(view) && Object.isFrozen(view.rows));
});

class Element {
  constructor(tag, document) { this.tag = tag; this.ownerDocument = document; this.children = []; this.attrs = {}; this.value = ""; }
  set textContent(text) { this.value = String(text); this.children = []; }
  get textContent() { return this.value + this.children.map(child => child.textContent).join(""); }
  set innerHTML(_) { throw new Error("HTML parsing forbidden"); }
  insertAdjacentHTML() { throw new Error("HTML parsing forbidden"); }
  appendChild(child) { this.children.push(child); return child; }
  replaceChildren(...children) { this.children = children; }
  setAttribute(name, value) { assert.equal(name, "aria-label"); this.attrs[name] = value; }
}
function target() {
  const tags = [];
  const document = {createElement(tag) { tags.push(tag); return new Element(tag, document); }};
  return {container: new Element("main", document), tags};
}

test("renderer uses text-only DOM nodes for hostile payload/reference values", () => {
  const {container, tags} = target();
  const d = preview();
  d.snapshot.payload = '<img src=x onerror="steal()">javascript:alert(1)';
  d.state = "CONFIRMED"; d.operation = operation();
  d.operation.reference = '<script>evil()</script>';
  renderResult(container, "preview", packet(d), {expectedId: "p1", evidence: "LOCAL_FIXTURE"});
  assert.match(container.textContent, /<script>evil\(\)<\/script>/);
  assert.match(container.textContent, /<img/);
  assert.equal(tags.some(tag => ["script", "img", "a", "iframe", "button", "input"].includes(tag)), false);
  assert.equal(container.children.length, 1);
  assert.match(container.textContent, /Local fixture/);
  renderResult(container, "operation", packet({...operation(), state: "UNKNOWN"}),
    {expectedId: "op1", evidence: "LOCAL_FIXTURE"});
  assert.equal(container.children.length, 1);
  assert.equal(container.textContent.includes("evil()"), false);
});

test("renderer cannot accept attacker-chosen tag kinds or prebuilt success views", () => {
  const {container} = target();
  assert.throws(() => renderResult(container, "<script>", {}, {}), TypeError);
  const view = renderResult(container, "operation", {title: "Approved", tone: "success"}, {expectedId: "op1"});
  assert.equal(view.available, false);
  assert.equal(container.textContent.includes("Approved"), false);
});

test("native resolution supports exact numeric 0/1 as well as booleans, never coercive strings", () => {
  for (const value of [0, 1, false, true]) {
    const d = decision(); d.code = "DECISION_RESOLVED"; d.outcome.status = "ERROR";
    d.resolution = {previousState: "IN_FLIGHT", resolvedUS: unixMs * 1000,
      inferenceMayHaveRun: value, providerCancellationVerified: false};
    const view = decisionView(packet(d), ctx);
    assert.equal(view.available, true, "native flag " + String(value));
    assert.equal(view.rows.find(row => row.label === "Inference may have run").value,
      value === 1 || value === true ? "Yes" : "No, according to the recorded state");
  }
  for (const value of ["1", 2, -1, null, {}]) {
    const d = decision(); d.code = "DECISION_RESOLVED"; d.outcome.status = "ERROR";
    d.resolution = {previousState: "IN_FLIGHT", resolvedUS: unixMs * 1000,
      inferenceMayHaveRun: value, providerCancellationVerified: false};
    assert.equal(decisionView(packet(d), ctx).available, false);
  }
});

test("uncertain result code paired with terminal acceptance must not render success", () => {
  const d = operation(); d.code = "RESULT_UNCERTAIN";
  const view = operationView(packet(d), {expectedId: "op1", evidence: "LIVE"});
  assert.equal(view.available, false);
  assert.notEqual(view.tone, "success");
});

test("preview result codes and states must agree", () => {
  for (const [code, state] of [
    ["PREVIEW_REJECTED", "PENDING"], ["PREVIEW_RECORDED", "CONFIRMED"],
    ["PREVIEW_ALREADY_CONFIRMED", "PENDING"], ["PREVIEW_CONFIRMED", "REJECTED"],
  ]) {
    const d = preview(); d.code = code; d.state = state;
    assert.equal(previewView(packet(d), {expectedId: "p1"}).available, false, code + "/" + state);
  }
});
