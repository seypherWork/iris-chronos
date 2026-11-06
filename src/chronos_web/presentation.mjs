/**
 * Read-only presentation of current native projections. Never authorizes a
 * command. Evidence labels come from the trusted UI controller, not API fields.
 */
const ID = /^[A-Za-z0-9_.-]{1,128}$/;
const CODE = /^[A-Z0-9_]{1,80}$/;
const HASH = /^[0-9a-f]{64}$/i;
const EVIDENCE = Object.freeze({
  LIVE: "Live server data — synthetic laboratory",
  REPLAY: "Replay — recorded data, not current server state",
  LOCAL_FIXTURE: "Local fixture — no IRIS execution",
  UNVERIFIED: "Source not verified",
});
const DECISION_CODES = new Set(["EXISTING_DECISION", "DECISION_PENDING", "DECISION_RESOLVED"]);
const PREVIEW_CODES = new Set(["PREVIEW_RECORDED", "EXISTING_PREVIEW", "READ_ONLY",
  "PREVIEW_REJECTED", "PREVIEW_ALREADY_CONFIRMED", "PREVIEW_CONFIRMED"]);
const OPERATION_CODES = new Set(["READ_ONLY", "RESULT_RECORDED", "READBACK_RECORDED",
  "RESULT_UNCERTAIN", "TERMINAL_RESULT_PRESERVED", "CONTRADICTORY_EVIDENCE",
  "EXISTING_OPERATION", "RESERVED_WITHOUT_SEND"]);
const PENDING = Object.freeze({
  PREPARED: ["Awaiting model", "No model result is recorded yet."],
  IN_FLIGHT: ["Model result pending", "The inference may be running. Do not retry it automatically."],
  VALIDATING: ["Validating reply", "A reply is being checked; no approval is established."],
  UNCERTAIN: ["Model outcome uncertain", "An earlier inference may have run; reading does not repeat it."],
  UNCERTAIN_VALIDATION: ["Validation outcome uncertain", "Consult the stored decision; do not assume validation succeeded."],
});
const DETERMINISTIC = Object.freeze({
  EXISTING_ACCEPTANCE: ["Existing acceptance recorded", "The checks found an acceptance for the observed operation. No model was invoked and this decision cannot authorize another send. Read the current shipment operation separately; this historical decision does not identify which operation is current now.", "notice"],
  ACCEPTANCE_UNRESOLVED: ["Acceptance remains unresolved", "The observed operation was unresolved when checked. Recovery is blocked; no model was invoked. Read the current shipment operation separately, then query its exact reference. Do not submit another recovery.", "warning"],
});
const OUTCOMES = Object.freeze({
  VALIDATED_PROPOSAL: ["Proposal requires human review", "Structure was validated. Meaning, evidence and the exact effect still need human review.", "notice"],
  VALIDATED_HOLD: ["Recovery held", "No recovery action is proposed by this decision. This does not prove that an earlier operation was not accepted.", "warning"],
  ERROR: ["Agent error", "The inference or its validation failed. This is not a successful HOLD decision.", "error"],
  REJECTED: ["Proposal rejected", "The reply was not accepted as a valid proposal.", "error"],
  RECHECK_REQUIRED: ["State recheck required", "The recorded context is no longer sufficient for action.", "warning"],
});
// Fixed explanations only. Provider text and exception arguments never supply
// these messages; this display mapping does not change any command permission.
const ERROR_DIAGNOSTICS = Object.freeze({
  INVALID_PROPOSAL: ["The reply could not be validated. No more specific cause was recorded.",
    "Keep this decision reference and inspect the validation diagnostics before requesting a new decision."],
  INVALID_EXTRACTION: ["The interpretation does not meet the required size, type or preference rules.",
    "Check the configured response contract before a separately requested model attempt."],
  INVALID_EXTRACTION_JSON: ["The interpretation is not valid JSON under the strict parser.",
    "Check structured-output support. Do not edit the rejected reply into an approved result."],
  EXTRACTION_CONTRACT_MISMATCH: ["The interpretation uses the wrong schema or an unexpected set of fields.",
    "Check that the model profile and response schema use the same contract."],
  INCONSISTENT_EXTRACTION: ["The interpreted preference and its reason are inconsistent.",
    "Review the preference interpretation; this decision cannot be approved."],
  INVALID_SOURCES: ["Evidence references are missing, repeated, malformed or outside this decision's source catalog.",
    "Compare the cited IDs with the original source catalog before requesting a new decision."],
  INVALID_SOURCES_LIST: ["Evidence references are not a list.",
    "Check the response format. This rejected interpretation cannot be approved."],
  INVALID_SOURCES_COUNT: ["The reply must cite between 1 and 16 evidence references.",
    "Review the citation format before requesting a separate new decision."],
  INVALID_SOURCES_TYPE: ["An evidence reference is not text.",
    "Citations must be literal text IDs from the original source catalog."],
  INVALID_SOURCES_UNKNOWN: ["An evidence reference is outside this decision's source catalog.",
    "Review the citation instructions. Provenance labels are not substitutes for catalog IDs."],
  INVALID_SOURCES_DUPLICATE: ["An evidence reference is repeated.",
    "Review the citation format; the application does not repair the rejected reply."],
  CURRENT_SOURCE_REQUIRED: ["The interpretation does not cite an applicable message for this order.",
    "Review the current-order evidence; an unrelated source cannot support this preference."],
  CONFLICT_SOURCES_REQUIRED: ["The reported conflict does not cite applicable current-order evidence.",
    "Review the evidence for the conflict before requesting a new decision."],
  INVALID_RATIONALE: ["The explanation is missing, blank, too long or not text.",
    "Check the explanation format and limit; the rejected text is not displayed here."],
  INVALID_CLARIFICATION: ["The clarification is incompatible with the reason or violates its format or length limit.",
    "Review whether clarification is needed and check its response contract."],
  STRUCTURED_POLICY_MISMATCH: ["The interpretation conflicts with the structured preference for this order.",
    "Review the original policy; a model reply cannot replace the structured constraint."],
  SENSITIVE_OUTPUT: ["Sensitive-looking content was detected in the reply and rejected.",
    "Inspect the authorized configuration without copying private values into reports or screenshots."],
  CONTEXT_DIGEST_MISMATCH: ["The context does not match its recorded integrity digest.",
    "Inspect the stored context and source version. Do not repair this completed decision in place."],
  CALL_CONTEXT_MISMATCH: ["The extraction is not bound to the expected original context.",
    "Inspect the request and context bindings before starting a new decision."],
  BOUND_CONTEXT_CHANGED: ["The bound context or available options no longer match their recorded digest.",
    "Preserve this result and inspect the binding; do not substitute a different context."],
  INVALID_AVAILABLE: ["The independently computed option data failed validation.",
    "Inspect the option calculation and data types before involving the model again."],
  DUPLICATE_AVAILABLE: ["The available option set contains a repeated action.",
    "Correct the option calculation before requesting a new decision."],
  UNKNOWN_PREFERENCE_MODE: ["The input uses an unsupported preference mode.",
    "Check the input contract and configured workflow version."],
  MODEL_TIMEOUT: ["A model result was not validated within the original decision deadline.",
    "Inspect the original request. A timeout does not prove that provider execution was cancelled."],
  MODEL_ERROR: ["The provider result could not be verified successfully.",
    "Inspect provider availability and transport diagnostics; do not treat this as a HOLD decision."],
  MODEL_REFUSAL: ["The provider reported a refusal rather than a usable interpretation.",
    "Review the request and provider constraints; this decision cannot authorize an operation."],
});
const object = value => value !== null && typeof value === "object" && !Array.isArray(value);
const text = (value, max) => typeof value === "string" && value.length <= max;
const identifier = value => typeof value === "string" && ID.test(value);
const integer = (value, min = 0) => Number.isSafeInteger(value) && value >= min;
const number = value => typeof value === "number" && Number.isFinite(value) && value >= 0;
function require(condition) { if (!condition) throw new Error("INVALID_DISPLAY_DATA"); }
function row(label, value) { return Object.freeze({label, value: String(value)}); }

function card(kind, evidence, title, summary, tone, rows = [], operation = null, available = true) {
  const provenance = Object.hasOwn(EVIDENCE, evidence) ? evidence : "UNVERIFIED";
  return Object.freeze({kind, available, title, summary,
    tone: tone === "success" && provenance !== "LIVE" ? "notice" : tone,
    evidence: provenance, evidenceLabel: EVIDENCE[provenance],
    canConfirm: false, rows: Object.freeze(rows), operation});
}
function unavailable(kind, evidence) {
  return card(kind, evidence, "Result unavailable",
    "The response is incomplete, inconsistent or does not match the requested identity. Consult the original reference; do not repeat a change.",
    "error", [], null, false);
}
function unwrap(envelope, codes) {
  require(object(envelope) && object(envelope.data));
  const data = envelope.data;
  require(codes.has(envelope.code) && data.code === envelope.code);
  require(data.dispatchGranted === false);
  return data;
}

// IRIS $ZTIMESTAMP day zero is 1840-12-31; Ledger uses UNIX microseconds.
// Formatting is display-only (milliseconds); it never determines authorization.
const IRIS_UNIX_SECONDS = 4070908800;
export function unixMicrosecondsUTC(value) {
  if (!integer(value)) return null;
  const date = new Date(Math.floor(value / 1000));
  return Number.isFinite(date.valueOf()) ? date.toISOString() : null;
}
export function irisSecondsUTC(value) {
  if (!number(value)) return null;
  const milliseconds = Math.round((value - IRIS_UNIX_SECONDS) * 1000);
  const date = new Date(milliseconds);
  return Number.isSafeInteger(milliseconds) && Number.isFinite(date.valueOf()) ? date.toISOString() : null;
}

export function decisionView(envelope, {expectedId, evidence = "UNVERIFIED"} = {}) {
  try {
    require(identifier(expectedId));
    // NOT_FOUND is not proof of non-acceptance of any earlier business operation.
    if (envelope?.code === "NOT_FOUND" && envelope.data?.code === "NOT_FOUND") {
      return card("decision", evidence, "Decision not found",
        "This decision is not available. An earlier business operation may still exist.",
        "warning", [row("Requested decision", expectedId)]);
    }
    const d = unwrap(envelope, DECISION_CODES);
    require(d.requestId === expectedId && identifier(d.orderId) && integer(d.shipmentVersion, 1));
    require(identifier(d.generation) && ["WITH_TRIALS", "WITHOUT_TRIALS_ABLATION"].includes(d.mode));
    require(d.inferenceGranted === false && d.dispatch_authorized === false);
    const deadline = unixMicrosecondsUTC(d.deadlineUS);
    require(deadline !== null);
    const rows = [row("Decision", d.requestId), row("Order", d.orderId),
      row("Shipment version", d.shipmentVersion), row("Trial mode", d.mode),
      row("Original deadline (UTC)", deadline), row("Runtime generation", d.generation)];
    let title, summary, tone;
    if (d.state === "COMPLETED") {
      require(object(d.outcome));
      require(d.outcome.dispatch_authorized === false);
      if (d.outcome.status === "DETERMINISTIC") {
        require(Object.hasOwn(DETERMINISTIC, d.outcome.code) && d.resolution === undefined);
        [title, summary, tone] = DETERMINISTIC[d.outcome.code];
        rows[4] = row("Check recorded (UTC)", deadline);
        rows.push(row("Decision method", "Deterministic checks — no model invocation"));
      } else {
        require(Object.hasOwn(OUTCOMES, d.outcome.status));
        [title, summary, tone] = OUTCOMES[d.outcome.status];
      }
      rows.push(row("Outcome", d.outcome.status));
      if (d.outcome.code !== undefined) {
        require(typeof d.outcome.code === "string" && CODE.test(d.outcome.code));
        rows.push(row("Diagnostic code", d.outcome.code));
        if (d.outcome.status === "ERROR" && Object.hasOwn(ERROR_DIAGNOSTICS, d.outcome.code)) {
          const [diagnosis, nextStep] = ERROR_DIAGNOSTICS[d.outcome.code];
          rows.push(row("What this means", diagnosis), row("Suggested next step", nextStep));
        }
      }
    } else {
      require(Object.hasOwn(PENDING, d.state) && d.outcome === undefined);
      [title, summary] = PENDING[d.state]; tone = "warning";
    }
    if (d.resolution !== undefined) {
      const r = d.resolution;
      require(d.state === "COMPLETED" && object(r) && Object.hasOwn(PENDING, r.previousState));
      // Native ObjectScript comparison expressions may serialize this field as 0/1.
      // Compatibility is limited to this display flag, never session permissions.
      require((typeof r.inferenceMayHaveRun === "boolean" || r.inferenceMayHaveRun === 0 ||
        r.inferenceMayHaveRun === 1) && r.providerCancellationVerified === false);
      const resolved = unixMicrosecondsUTC(r.resolvedUS);
      require(resolved !== null);
      rows.push(row("Resolution recorded (UTC)", resolved),
        row("Inference may have run", (r.inferenceMayHaveRun === true || r.inferenceMayHaveRun === 1) ? "Yes" : "No, according to the recorded state"),
        row("Provider cancellation", "Not verified"));
    }
    return card("decision", evidence, title, summary, tone, rows);
  } catch { return unavailable("decision", evidence); }
}

// Keep a fresh shipment observation separate from its historical decision.
export function decisionOperationView(envelope, {expectedId, expectedOrder, expectedShipmentVersion, evidence = "UNVERIFIED"} = {}) {
  try {
    require(identifier(expectedId) && identifier(expectedOrder) && integer(expectedShipmentVersion, 1));
    const d = unwrap(envelope, new Set(["DECISION_OPERATION_RECORDED"]));
    require(d.decisionId === expectedId && d.orderId === expectedOrder && d.shipmentVersion === expectedShipmentVersion);
    require(object(d.operation) && identifier(d.operation.operationId));
    const operation = operationView({code:d.operation.code, data:d.operation}, {expectedId:d.operation.operationId, evidence});
    require(operation.available);
    return card("decision-operation", evidence, "Current shipment operation observed",
      "This is the shipment's current operation at this read, not the historical outcome of the decision. Further queries use exactly the displayed operation ID; no recovery is submitted.",
      "notice", [row("Decision reference", expectedId), row("Order", expectedOrder), row("Shipment version", expectedShipmentVersion)], operation);
  } catch { return unavailable("decision-operation", evidence); }
}

export function operationView(envelope, {expectedId, evidence = "UNVERIFIED"} = {}) {
  try {
    require(identifier(expectedId));
    const d = unwrap(envelope, OPERATION_CODES);
    require(d.operationId === expectedId && identifier(d.attemptId) && typeof d.quarantined === "boolean");
    require(["IN_FLIGHT", "UNKNOWN", "ACCEPTED", "NOT_ACCEPTED_FINAL"].includes(d.state));
    require(text(d.reference, 256) && (d.state !== "ACCEPTED" || d.reference.length > 0));
    require(d.code !== "CONTRADICTORY_EVIDENCE" || d.quarantined);
    require(d.code !== "RESULT_UNCERTAIN" || !["ACCEPTED", "NOT_ACCEPTED_FINAL"].includes(d.state));
    let title, summary, tone;
    if (d.quarantined) {
      title = "Conflicting evidence — operation quarantined";
      summary = "Do not treat the recorded terminal state as a clean result or send another operation.";
      tone = "error";
    } else if (d.state === "ACCEPTED") {
      title = "Acceptance recorded";
      summary = "The laboratory destination reported acceptance. This is not proof of simulated or physical delivery.";
      tone = "success";
    } else if (d.state === "NOT_ACCEPTED_FINAL") {
      title = "Final non-acceptance recorded";
      summary = "This operation was closed without acceptance. Any new action needs a new current-state check and explicit approval.";
      tone = "notice";
    } else {
      title = d.state === "IN_FLIGHT" ? "Operation in flight" : "Operation outcome unknown";
      summary = "Acceptance may already have happened. Read or reconcile this same operation; do not resend.";
      tone = "warning";
    }
    return card("operation", evidence, title, summary, tone, [
      row("Operation", d.operationId), row("Attempt", d.attemptId),
      row("Recorded state", d.state), row("Reference", d.reference || "Not recorded"),
      row("Result code", d.code),
    ]);
  } catch { return unavailable("operation", evidence); }
}

export function previewView(envelope, {expectedId, evidence = "UNVERIFIED"} = {}) {
  try {
    require(identifier(expectedId));
    const d = unwrap(envelope, PREVIEW_CODES);
    require(d.previewId === expectedId && ["PENDING", "CONFIRMED", "REJECTED"].includes(d.state));
    const fixedState = {PREVIEW_RECORDED: "PENDING", PREVIEW_REJECTED: "REJECTED",
      PREVIEW_CONFIRMED: "CONFIRMED", PREVIEW_ALREADY_CONFIRMED: "CONFIRMED"};
    require(!Object.hasOwn(fixedState, d.code) || fixedState[d.code] === d.state);
    for (const field of ["decisionId", "orderId", "operationId", "actor", "generation"]) require(identifier(d[field]));
    require(integer(d.shipmentVersion, 1) && integer(d.snapshotId, 1) && HASH.test(d.decisionDigest));
    require(d.option === "RETRY_A" && d.target === "A" || d.option === "FAILOVER_B" && d.target === "B");
    const s = d.snapshot;
    require(object(s) && s.orderId === d.orderId && s.shipmentVersion === d.shipmentVersion);
    for (const field of ["revision", "policyRevision", "quantity"]) require(integer(s[field], 1));
    require(typeof s.payload === "string" && s.payload.length > 0 &&
      new TextEncoder().encode(s.payload).length <= 65536 && number(s.maxCost));
    require(object(s.offers));
    for (const target of ["A", "B"]) {
      const offer = s.offers[target];
      require(object(offer) && offer.target === target && integer(offer.capacity));
      for (const field of ["cost", "availableAt", "queueSeconds", "travelSeconds", "validUntil"]) require(number(offer[field]));
    }
    const times = {};
    for (const field of ["createdAt", "expiresAt", "predictedArrival"]) {
      times[field] = irisSecondsUTC(d[field]); require(times[field] !== null);
    }
    for (const field of ["observedAt", "inventoryUntil", "deliveryDeadline"]) {
      times[field] = irisSecondsUTC(s[field]); require(times[field] !== null);
    }
    const reviewDeadline = unixMicrosecondsUTC(d.reviewDeadlineUS);
    require(reviewDeadline !== null && d.expiresAt >= d.createdAt);
    const rows = [
      row("Preview", d.previewId), row("Decision", d.decisionId),
      row("Operation reference", d.operationId), row("Order", d.orderId),
      row("Shipment version", d.shipmentVersion), row("Snapshot", d.snapshotId),
      row("Data revision", s.revision), row("Policy revision", s.policyRevision),
      row("Option", d.option), row("Destination", d.target), row("Actor", d.actor),
      row("Quantity", s.quantity), row("Cost units", s.offers[d.target].cost),
      row("Maximum cost units", s.maxCost), row("Observed (UTC)", times.observedAt),
      row("Preview created (UTC)", times.createdAt), row("Preview expires (UTC)", times.expiresAt),
      row("Human review deadline (UTC)", reviewDeadline),
      row("Predicted arrival (UTC, not guaranteed)", times.predictedArrival),
      row("Delivery deadline (UTC)", times.deliveryDeadline),
      row("Exact payload (JSON string)", JSON.stringify(s.payload)),
    ];
    require(d.operation === undefined || d.state === "CONFIRMED");
    const operation = d.operation === undefined ? null :
      operationView({code: d.operation.code, data: d.operation}, {expectedId: d.operationId, evidence});
    const title = d.state === "CONFIRMED" ? "Confirmation recorded" :
      d.state === "REJECTED" ? "Preview rejected" : "Preview awaiting review";
    const summary = d.state === "CONFIRMED" ?
      "Confirmation is not acceptance. Consult the operation result below or read it back explicitly." :
      d.state === "REJECTED" ? "This preview was rejected. It does not establish the state of any other operation." :
      "Display only: the complete proposal, sources and interpretation must be presented before human consent. Expiry and eligibility are enforced by the server.";
    return card("preview", evidence, title, summary, "notice", rows, operation);
  } catch { return unavailable("preview", evidence); }
}
