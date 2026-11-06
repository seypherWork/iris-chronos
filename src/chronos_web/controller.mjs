import {decisionDetailView} from "./detail.mjs";
import {decisionView, decisionOperationView, previewView, operationView} from "./presentation.mjs";
import {ChronosClientError} from "./client.mjs";

const ID = /^[A-Za-z0-9_.-]{1,128}$/;
const ERRORS = new Set(["SESSION_REQUIRED", "PERMISSION_DENIED", "REQUEST_TIMEOUT",
  "CONNECTION_CHANGED", "TRANSPORT_UNAVAILABLE", "INVALID_RESPONSE",
  "RESPONSE_TOO_LARGE", "LOGOUT_UNCONFIRMED", "INVALID_SESSION",
  "REFERENCE_SCOPE_CHANGED", "RECOVERY_UNAVAILABLE"]);
const errorCode = error => error instanceof ChronosClientError && ERRORS.has(error.code) ?
  error.code : "RESULT_UNAVAILABLE";
const reference = (kind, id) => Object.freeze({kind, id});

/**
 * Read/explicit-reconcile controller only. No confirm, preview creation, reject,
 * resolve, inference, polling or retries. A separate consent flow remains pending.
 * onChange must synchronously render trusted state, not cache raw server replies.
 */
export function createResultController({client, onChange = () => {}, references = null,
  evidence = "UNVERIFIED"} = {}) {
  for (const method of ["connect", "disconnect", "readDecision", "readPreview", "reconcilePreview", "logout"]) {
    if (typeof client?.[method] !== "function") throw new TypeError("INVALID_CLIENT");
  }
  if (typeof onChange !== "function" ||
      references !== null && typeof references.remember !== "function") throw new TypeError("INVALID_CONTROLLER");
  let epoch = 0;
  let state = Object.freeze({phase: "DISCONNECTED", selection: null, view: null,
    code: "", referenceStatus: "NOT_CONFIGURED", savedReferences: Object.freeze([])});
  let confirmedOperation = null, detailSelection = null, preparationObservation = null, operationSelection = null;
  let savedReferences = Object.freeze([]), savedScope = "";
  const recoveryEnabled = references && ["list", "forget", "scope"].every(name => typeof references[name] === "function");
  function clearSaved() { savedReferences = Object.freeze([]); savedScope = ""; }
  function refreshSaved() {
    clearSaved();
    if (!recoveryEnabled) return "NOT_CONFIGURED";
    const list = references.list();
    if (!list.ok || !list.scope || list.scope !== references.scope()) return list.code;
    savedReferences = Object.freeze(list.items.map(item => reference(item.kind, item.id)));
    savedScope = list.scope;
    return list.code;
  }
  function checkScope(expected) {
    if (!recoveryEnabled || !expected || references.scope() !== expected) {
      throw new ChronosClientError("REFERENCE_SCOPE_CHANGED");
    }
  }
  function savedItem(index) {
    if (!["READY", "REFERENCES_READY"].includes(state.phase) ||
        !Number.isInteger(index) || index < 0 || index >= savedReferences.length) {
      throw new TypeError("SAVED_REFERENCE_REQUIRED");
    }
    return {item: savedReferences[index], scope: savedScope};
  }

  function emit(update, version) {
    if (version !== epoch) return false;
    if (update.phase === "ERROR") clearSaved();
    state = Object.freeze({...update, savedReferences});
    try {
      const rendered = onChange(state);
      if (rendered !== null && (typeof rendered === "object" || typeof rendered === "function") &&
          typeof rendered.then === "function") {
        // Rendering must finish before any subsequent read can be admitted.
        // Consume a rejected Promise without exposing its potentially private error.
        Promise.resolve(rendered).catch(() => {});
        throw new TypeError("ASYNCHRONOUS_RENDERER_UNSUPPORTED");
      }
    }
    catch {
      if (version === epoch) {
        epoch += 1; client.disconnect(); confirmedOperation = null; detailSelection = null; preparationObservation = null; operationSelection = null; clearSaved();
        state = Object.freeze({...state, phase: "ERROR", view: null, savedReferences, code: "PRESENTATION_FAILED"});
      }
      return false;
    }
    return version === epoch;
  }
  function fail(error, selected, version) {
    if (version === epoch) { detailSelection = null; preparationObservation = null; operationSelection = null; clearSaved(); }
    emit({phase: "ERROR", selection: selected, view: null, code: errorCode(error),
      referenceStatus: state.referenceStatus}, version);
    return state;
  }
  function remember(selected) {
    if (!references) return "NOT_CONFIGURED";
    try { return references.remember(selected).ok ? "REFERENCE_REMEMBERED" : "REFERENCE_NOT_SAVED"; }
    catch { return "REFERENCE_NOT_SAVED"; }
  }
  function invalidate() {
    epoch += 1;
    client.disconnect();
    confirmedOperation = null; detailSelection = null; preparationObservation = null; operationSelection = null; clearSaved();
    return epoch;
  }

  async function select(kind, id, expectedScope = "") {
    if (!["decision", "preview", "operation"].includes(kind) || typeof id !== "string" || !ID.test(id)) {
      throw new TypeError("INVALID_SELECTION");
    }
    const selected = reference(kind, id), version = invalidate();
    if (!emit({phase: "CONNECTING", selection: expectedScope ? null : selected, view: null, code: "",
      referenceStatus: references ? "NOT_SAVED" : "NOT_CONFIGURED"}, version)) return state;
    try {
      // One explicit session bootstrap per user selection; not a retry of a read.
      const access = await client.connect();
      if (version !== epoch) return state;
      if (access.connected !== true || access.canRead !== true) throw new ChronosClientError("PERMISSION_DENIED");
      if (expectedScope) checkScope(expectedScope);
      const readScope = recoveryEnabled ? references.scope() : "";
      if (!emit({...state, phase: "LOADING", selection: selected}, version)) return state;
      const reply = await (kind === "decision" ? client.readDecision(id) : kind === "preview" ? client.readPreview(id) : client.readOperation(id));
      if (version !== epoch) return state;
      const view = (kind === "decision" ? decisionView : kind === "preview" ? previewView : operationView)(reply, {expectedId: id, evidence});
      const referenceStatus = view.available ? remember(selected) : state.referenceStatus;
      if (view.available && recoveryEnabled) refreshSaved();
      if (readScope) checkScope(readScope);
      if (version !== epoch) return state;
      confirmedOperation = kind === "preview" && view.available && reply.data.state === "CONFIRMED" ?
        reply.data.operationId : kind === "operation" && view.available ? id : null;
      operationSelection = kind === "decision" && view.available && reply.data?.requestId === id &&
        typeof client.readDecisionOperation === "function" ? Object.freeze({expectedId:id,
          expectedOrder:reply.data.orderId, expectedShipmentVersion:reply.data.shipmentVersion}) : null;
      // Display-only negative evidence; never confers permission or consent.
      preparationObservation = kind === "decision" && view.available ? Object.freeze({
        id, identity: typeof client.sessionIdentity === "function" ? client.sessionIdentity() : null,
        blocked: reply.data?.state !== "COMPLETED" || reply.data?.outcome?.status !== "VALIDATED_PROPOSAL",
      }) : null;
      detailSelection = kind === "decision" && view.available && reply.data?.state === "COMPLETED" &&
        ["VALIDATED_PROPOSAL", "VALIDATED_HOLD"].includes(reply.data?.outcome?.status) &&
        typeof client.readDecisionDetail === "function" ? Object.freeze({
          expectedId: id, expectedGeneration: reply.data.generation, expectedOutcome: reply.data.outcome.status,
          expectedOrder: reply.data.orderId, expectedShipmentVersion: reply.data.shipmentVersion,
        }) : null;
      emit({phase: view.available ? "READY" : "ERROR", selection: selected, view,
        code: view.available ? "" : "RESULT_UNAVAILABLE", referenceStatus}, version);
      return state;
    } catch (error) { return fail(error, expectedScope ? null : selected, version); }
  }

  async function loadReferences() {
    const version = invalidate();
    if (!emit({phase: "CONNECTING", selection: null, view: null, code: "",
      referenceStatus: "CHECKING_SESSION"}, version)) return state;
    try {
      if (!recoveryEnabled) throw new ChronosClientError("RECOVERY_UNAVAILABLE");
      const access = await client.connect();
      if (version !== epoch) return state;
      if (access.connected !== true || access.canRead !== true) throw new ChronosClientError("PERMISSION_DENIED");
      const code = refreshSaved();
      emit({phase: savedScope ? "REFERENCES_READY" : "ERROR", selection: null, view: null,
        code: savedScope ? "" : "RECOVERY_UNAVAILABLE", referenceStatus: code}, version);
      return state;
    } catch (error) { return fail(error, null, version); }
  }

  async function reopenReference(index) {
    const {item, scope} = savedItem(index);
    // select reconnects and checks the original scope before issuing any ID read.
    return select(item.kind, item.id, scope);
  }

  async function forgetReference(index) {
    const {item, scope} = savedItem(index), version = invalidate();
    if (!emit({phase: "CONNECTING", selection: null, view: null, code: "",
      referenceStatus: "CHECKING_SESSION"}, version)) return state;
    try {
      const access = await client.connect();
      if (version !== epoch) return state;
      if (access.connected !== true || access.canRead !== true) throw new ChronosClientError("PERMISSION_DENIED");
      checkScope(scope);
      const result = references.forget(item);
      if (version !== epoch) return state;
      checkScope(scope);
      const refreshed = refreshSaved();
      emit({phase: result.ok && savedScope ? "REFERENCES_READY" : "ERROR", selection: null, view: null,
        code: result.ok && savedScope ? "" : "RECOVERY_UNAVAILABLE",
        referenceStatus: result.ok ? result.code : refreshed === "REFERENCES_READ" ? result.code : refreshed}, version);
      return state;
    } catch (error) { return fail(error, null, version); }
  }

  async function readSelectedDetail() {
    if (state.phase !== "READY" || state.selection?.kind !== "decision" || !detailSelection) {
      throw new TypeError("COMPLETED_DECISION_REQUIRED");
    }
    const version = epoch, selected = state.selection, binding = detailSelection;
    detailSelection = null; // duplicate click is not a second request
    if (!emit({...state, phase: "LOADING", view: null, code: ""}, version)) return state;
    try {
      const reply = await client.readDecisionDetail(selected.id);
      if (version !== epoch) return state;
      const view = decisionDetailView(reply, {...binding, evidence});
      emit({...state, phase: view.available ? "READY" : "ERROR", view,
        code: view.available ? "" : "RESULT_UNAVAILABLE"}, version);
      return state;
    } catch (error) { return fail(error, selected, version); }
  }

  async function readCurrentOperation() {
    if (state.phase !== "READY" || state.selection?.kind !== "decision" || !operationSelection) {
      throw new TypeError("DECISION_REQUIRED");
    }
    const version = epoch, selected = state.selection, binding = operationSelection;
    const readScope = recoveryEnabled ? references.scope() : "";
    operationSelection = null; detailSelection = null;
    if (!emit({...state, phase:"LOADING", view:null, code:""}, version)) return state;
    try {
      const reply = await client.readDecisionOperation(selected.id);
      if (version !== epoch) return state;
      if (readScope) checkScope(readScope);
      const view = decisionOperationView(reply, {...binding, evidence});
      const operation = view.available ? reference("operation", reply.data.operation.operationId) : null;
      const referenceStatus = operation ? remember(operation) : state.referenceStatus;
      if (operation && recoveryEnabled) refreshSaved();
      if (readScope) checkScope(readScope);
      if (version !== epoch) return state;
      confirmedOperation = operation?.id ?? null;
      preparationObservation = null;
      emit({...state, phase:view.available ? "READY" : "ERROR", selection:operation ?? selected,
        view, code:view.available ? "" : "RESULT_UNAVAILABLE", referenceStatus}, version);
      return state;
    } catch (error) { return fail(error, selected, version); }
  }

  async function reconcileSelected() {
    if (state.phase !== "READY" || !["preview", "operation"].includes(state.selection?.kind) || !confirmedOperation) {
      throw new TypeError("CONFIRMED_PREVIEW_REQUIRED");
    }
    const version = epoch, selected = state.selection, operationId = confirmedOperation;
    if (!emit({...state, phase: "LOADING", view: null, code: ""}, version)) return state;
    try {
      const reply = await (selected.kind === "operation" ? client.reconcileOperation(operationId) : client.reconcilePreview(selected.id));
      if (version !== epoch) return state;
      const view = operationView(reply, {expectedId: operationId, evidence});
      emit({...state, phase: view.available ? "READY" : "ERROR", view,
        code: view.available ? "" : "RESULT_UNAVAILABLE"}, version);
      return state;
    } catch (error) { return fail(error, selected, version); }
  }

  async function logout() {
    const version = ++epoch;
    confirmedOperation = null; detailSelection = null; preparationObservation = null; operationSelection = null; clearSaved();
    if (!emit({phase: "LOGGING_OUT", selection: null, view: null, code: "",
      referenceStatus: "NOT_CONFIGURED"}, version)) return state;
    try {
      // Explicit sign-out must work even after a local disconnect removed CSRF.
      // Bootstrap once on the user's action; no read permission or automatic retry.
      const access = await client.connect();
      if (version !== epoch) return state;
      if (access.connected !== true) throw new ChronosClientError("SESSION_REQUIRED");
      const reply = await client.logout();
      if (version !== epoch) return state;
      if (reply.code !== "SESSION_ENDED") throw new ChronosClientError("LOGOUT_UNCONFIRMED");
      emit({...state, phase: "LOGGED_OUT", code: "SESSION_ENDED"}, version);
      return state;
    } catch (error) {
      if (version === epoch) client.disconnect();
      emit({...state, phase: "LOGOUT_UNCONFIRMED", view: null, code: errorCode(error)}, version);
      return state;
    }
  }
  return Object.freeze({
    snapshot: () => state, select: (kind, id) => select(kind, id), readSelectedDetail, readCurrentOperation, reconcileSelected, logout,
    loadReferences, reopenReference, forgetReference,
    canUseSaved: () => ["READY", "REFERENCES_READY"].includes(state.phase) &&
      Boolean(savedScope) && recoveryEnabled && savedScope === references.scope(),
    preparationBlockReason() {
      const access = typeof client.sessionStatus === "function" ? client.sessionStatus() : null;
      if (access?.connected === true && access.canApprove !== true) return "APPROVAL_PERMISSION_REQUIRED";
      if (state.phase === "READY" && ["preview", "operation"].includes(state.selection?.kind)) return "DECISION_REQUIRED";
      const identity = typeof client.sessionIdentity === "function" ? client.sessionIdentity() : null;
      if (state.phase === "READY" && state.selection?.kind === "decision" &&
          preparationObservation?.id === state.selection.id && preparationObservation.blocked &&
          preparationObservation.identity === identity) return "DECISION_NOT_ACTIONABLE";
      return "";
    },
    canReadDetail: () => state.phase === "READY" && state.selection?.kind === "decision" && Boolean(detailSelection),
    canReadCurrentOperation: () => state.phase === "READY" && state.selection?.kind === "decision" && Boolean(operationSelection),
    canReconcile: () => state.phase === "READY" && ["preview", "operation"].includes(state.selection?.kind) && Boolean(confirmedOperation) &&
      (state.selection.kind === "preview" || typeof client.reconcileOperation === "function"),
    disconnect() {
      const version = invalidate();
      emit({phase: "DISCONNECTED", selection: null, view: null, code: "",
        referenceStatus: "NOT_CONFIGURED"}, version);
      return state;
    },
  });
}
