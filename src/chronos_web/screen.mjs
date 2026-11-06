import {mountConversationPanel} from "./conversation-panel.mjs";
import {createPreparationReferences} from "./preparation-references.mjs";
import {appendDetailSections, appendResultRows} from "./detail.mjs";
import {mountConsentPanel} from "./consent-panel.mjs";
import {createResultController} from "./controller.mjs";
import {createSessionRecoveryReferences} from "./session-references.mjs";

const ID = /^[A-Za-z0-9_.-]{1,128}$/;
const PROVENANCE = Object.freeze({
  LIVE: "Live server data — synthetic laboratory",
  REPLAY: "Replay — recorded data, not current server state",
  LOCAL_FIXTURE: "Local fixture — no IRIS execution",
  UNVERIFIED: "Source not verified",
});
const MESSAGES = Object.freeze({
  DISCONNECTED: "Disconnected. Enter an existing reference to read its current result.",
  CONNECTING: "Checking the IRIS session…",
  LOADING: "Reading the existing result. No recovery is submitted.",
  READY: "Result read. Acceptance is not delivery.",
  REFERENCES_READY: "Saved references loaded. Reopening performs a fresh read; it does not repeat a change.",
  ERROR: "Result unavailable. Keep the original reference; do not repeat a change.",
  LOGGING_OUT: "Ending the IRIS session…",
  LOGGED_OUT: "IRIS confirmed that the session ended.",
  LOGOUT_UNCONFIRMED: "Session ending was not confirmed. Results are hidden; sign out in IRIS before leaving this device.",
});
const ERROR_MESSAGES = Object.freeze({
  RECOVERY_UNAVAILABLE: "Saved references are unavailable. Keep the original ID; no change has been repeated.",
  REFERENCE_SCOPE_CHANGED: "The signed-in account or installation changed. Load its saved references again.",
  SESSION_REQUIRED: "An IRIS session is required. Sign in through your installation, then read again.",
  PERMISSION_DENIED: "This IRIS session does not permit the requested read.",
  REQUEST_TIMEOUT: "The request timed out. Read the same reference again; do not repeat a change.",
  PRESENTATION_FAILED: "The result could not be displayed. Previous results have been removed.",
});

// Presentation only: a highlighted section grants no authority or delivery claim.
export function workflowSection(model) {
  if (!model || model.available === false) return null;
  if (["decision", "detail"].includes(model.kind)) return 0;
  if (model.kind === "consent") return 1;
  if (model.kind === "preview") return model.operation ? 2 : 1;
  if (model.kind === "operation" && model.tone === "success") return 2;
  return null;
}

/** Mount one read/reconcile screen. No session starts until an explicit lookup or sign-out.
 * client and evidence are installation-owned, never taken from URL query text.
 * This consumer renders controller-projected values as text, not raw envelopes.
 */
export function mountResultScreen(root, {client, storage = null, evidence = "UNVERIFIED",
  now = Date.now, schedule = setTimeout, cancel = clearTimeout} = {}) {
  const document = root.ownerDocument;
  const references = storage && typeof client.sessionIdentity === "function" &&
    typeof client.sessionStatus === "function" ? createSessionRecoveryReferences({client, storage}) : null;
  const mode = Object.hasOwn(PROVENANCE, evidence) ? evidence : "UNVERIFIED";
  const consentEnabled = mode === "LIVE" && references && ["connect","disconnect","sessionStatus",
    "sessionIdentity","readDecisionDetail","preparePreview","readPreparation","closePreparation","readPreview","confirmPreview","rejectPreview"]
      .every(method => typeof client[method] === "function");
  const conversationEnabled = mode === "LIVE" && ["connect","disconnect","sessionStatus","sessionIdentity",
    "conversationAvailable","openConversation","readConversation","recordConversation"].every(m=>typeof client[m]==="function");
  const create = (tag, text, parent) => {
    const element = document.createElement(tag);
    if (text !== undefined) element.textContent = text;
    if (parent) parent.appendChild(element);
    return element;
  };
  const shell = create("main"); shell.className = "chronos-shell";
  const sidebar = create("aside", undefined, shell); sidebar.className = "chronos-nav";
  const navInner = create("div", undefined, sidebar); navInner.className = "chronos-nav-inner";
  const mark = create("span", undefined, navInner); mark.className = "chronos-mark"; mark.setAttribute("aria-hidden", "true");
  create("p", "IRIS\nCHRONOS", navInner).className = "chronos-brand";
  const nav = create("nav", undefined, navInner); nav.setAttribute("aria-label", "Workspace navigation");
  const navButtons = ["Overview", "Cases", "History"].map((name, index) => {
    const b = create("button", undefined, nav); b.type = "button";
    b.setAttribute("aria-label", name);
    const icon = create("span", ["▦", "▱", "↶"][index], b); icon.className = "chronos-nav-icon"; icon.setAttribute("aria-hidden", "true");
    create("span", name, b); return b;
  });
  create("p", "Synthetic laboratory • Human supervised", navInner).className = "chronos-nav-note";
  const frame = create("div", undefined, shell); frame.className = "chronos-workspace";
  const outcomeNotice = consentEnabled ? create("aside", undefined, frame) : null;
  let outcomeJump = null;
  if (outcomeNotice) {
    outcomeNotice.className = "chronos-outcome-notice";
    outcomeNotice.setAttribute("aria-label", "Recovery outcome needs verification");
    outcomeNotice.hidden = true;
    create("p", "Confirmation reply unavailable. Check the original outcome before taking further action.", outcomeNotice);
    outcomeJump = create("button", "Find original outcome", outcomeNotice);
    outcomeJump.type = "button";
  }
  const header = create("header", undefined, frame); header.className = "chronos-hero"; header.tabIndex = -1;
  create("p", "IRIS CHRONOS / SUPERVISED RECOVERY", header).className = "eyebrow";
  create("h1", "RECOVER.\nWITHOUT DUPLICATES.", header);
  create("p", "The agent proposes. You stay in control.", header).className = "chronos-tagline";
  const art = create("div", undefined, header); art.className = "chronos-route-art"; art.setAttribute("aria-hidden", "true");
  for (const cls of ["chronos-track", "chronos-arc", "chronos-node", "chronos-node chronos-node--blocked", "chronos-node chronos-node--end"]) {
    create("span", cls.includes("blocked") ? "×" : undefined, art).className = cls;
  }
  create("p", PROVENANCE[mode], header).className = "chronos-provenance";
  create("p", consentEnabled ? "Inspect original evidence, prepare an exact preview and explicitly approve or reject it." :
    "Inspect an existing decision or preview. This screen cannot approve or send a recovery.", header).className = "hint";
  const stages = create("ol", undefined, frame); stages.className = "chronos-stages"; stages.setAttribute("aria-label", "Workflow section, not authorization or delivery status");
  const stageItems = [];
  for (const [index, name] of ["Proposal", "Verification", "Confirmation"].entries()) {
    const step = create("li", undefined, stages); stageItems.push(step); create("strong", "0" + (index + 1), step); create("span", name, step);
  }
  const showSection = index => stageItems.forEach((step, i) => {
    step.className = i === index ? "is-current" : "";
    step.setAttribute("aria-current", i === index ? "step" : "false");
  });
  showSection(null);
  const form = create("form", undefined, frame); form.noValidate = true; form.tabIndex = -1; form.setAttribute("aria-label", "Read a case");
  const kindLabel = create("label", "Reference type", form);
  const kind = create("select", undefined, kindLabel);
  kind.setAttribute("aria-label", "Reference type");
  for (const [value, label] of [["decision", "Decision"], ["preview", "Approval preview"], ["operation", "Operation"]]) {
    const option = create("option", label, kind); option.value = value;
  }
  kind.value = "decision";
  const idLabel = create("label", "Existing reference", form);
  const id = create("input", undefined, idLabel);
  id.type = "text"; id.maxLength = 128; id.autocomplete = "off"; id.spellcheck = false;
  id.setAttribute("aria-label", "Existing reference");
  id.setAttribute("aria-describedby", "chronos-reference-help");
  const help = create("p", "Use the original decision, preview or operation ID. Never enter passwords or tokens.", form);
  help.id = "chronos-reference-help"; help.className = "hint";
  const actions = create("div", undefined, form); actions.className = "actions";
  const lookup = create("button", "Read existing result", actions); lookup.type = "submit";
  const detail = create("button", "Read historical details", actions); detail.type = "button"; detail.disabled = true;
  const currentOperation = create("button", "Read current shipment operation", actions);
  currentOperation.type = "button"; currentOperation.disabled = true;
  const reconcile = create("button", "Query destination outcome", actions);
  reconcile.type = "button"; reconcile.disabled = true;
  const sessionActions = create("div", undefined, form); sessionActions.className = "actions chronos-session-actions";
  const disconnect = create("button", "Disconnect this screen", sessionActions); disconnect.type = "button";
  const logout = create("button", "Sign out of IRIS", sessionActions); logout.type = "button";
  const status = create("p", undefined, frame); status.className = "chronos-screen-status";
  status.setAttribute("role", "status"); status.setAttribute("aria-live", "polite");
  const recoveryPanel = create("section"); recoveryPanel.tabIndex = -1;
  recoveryPanel.setAttribute("aria-label", "Saved references"); recoveryPanel.className = "chronos-recovery";
  create("h2", "Saved references in this tab", recoveryPanel);
  create("p", "Only decision, preview and operation IDs are saved. No passwords, payloads or results. Removing a bookmark does not delete IRIS history. Keep the original ID for unresolved operations.", recoveryPanel);
  const savedLabel = create("label", "Saved reference", recoveryPanel);
  const saved = create("select", undefined, savedLabel);
  saved.setAttribute("aria-label", "Saved reference"); saved.disabled = true;
  const recoveryActions = create("div", undefined, recoveryPanel); recoveryActions.className = "actions";
  const loadSaved = create("button", "Load saved references", recoveryActions); loadSaved.type = "button";
  const reopen = create("button", "Reopen saved result", recoveryActions); reopen.type = "button"; reopen.disabled = true;
  const forget = create("button", "Remove bookmark", recoveryActions); forget.type = "button"; forget.disabled = true;
  const recovery = create("p", "Browser recovery references are not configured.", recoveryPanel);
  recovery.className = "hint"; recovery.setAttribute("role", "status");
  const result = create("section", undefined, frame);
  result.setAttribute("aria-label", "Current result");
  const chatRoot = conversationEnabled ? create("section", undefined, frame) : null;
  const consentRoot = consentEnabled ? create("section", undefined, frame) : null;
  frame.appendChild(recoveryPanel);
  const limits = create("aside", undefined, frame); limits.className = "chronos-limits";
  create("h2", "Scope of this screen", limits);
  create("p", "A proposal is not approval. Approval is not acceptance. Acceptance is not delivery. Unknown outcomes must be queried using the original operation, never replaced by a new submission.", limits);
  create("p", "Historical proposal and branch details are available for completed decisions. Saved references can be reopened explicitly after a reload. " +
    (consentEnabled ? "Approval requires a fresh, unexpired preview, the current IRIS permissions and an explicit acknowledgement. " :
      "Approval requires a configured live installation and session-bound recovery storage. ") +
    "This screen alone does not demonstrate a real-model run.", limits);
  root.replaceChildren(shell);
  let destroyed = false, controller, consentPanel = null, conversationPanel = null, activeMode = "read";
  const setActiveMode = value => {
    activeMode = value;
    if (outcomeNotice) outcomeNotice.hidden = true;
    if (chatRoot) chatRoot.hidden = value === "consent";
  };
  const clearResults = () => {
    // Fallback clears stale DOM if building/replacing a new card failed.
    try { result.replaceChildren(); } catch { result.textContent = ""; }
  };
  const clearSavedOptions = () => {
    try { saved.replaceChildren(); } catch { saved.textContent = ""; }
  };
  const renderModel = (model, nested = false) => {
    const card = create("section");
    const tone = ["notice", "warning", "error", "success"].includes(model.tone) ? model.tone : "notice";
    card.className = "chronos-result chronos-result--" + tone;
    create("p", model.evidenceLabel, card).className = "chronos-provenance";
    create("h2", model.title, card);
    create("p", model.summary, card);
    if (model.kind !== "detail") appendResultRows(document, card, model);
    appendDetailSections(document, card, model.sections);
    if (model.kind === "detail") appendResultRows(document, card, model);
    if (model.operation) card.appendChild(renderModel(model.operation, true));
    if (!nested) showSection(workflowSection(model));
    return card;
  };
  const paint = state => {
    if (destroyed || activeMode !== "read") return;
    try {
      clearResults(); showSection(null);
      const busy = ["CONNECTING", "LOADING", "LOGGING_OUT"].includes(state.phase);
      lookup.disabled = busy;
      conversationPanel?.setAvailable(!busy && !["LOGGED_OUT","LOGOUT_UNCONFIRMED"].includes(state.phase));
      consentPanel?.setPreparationBlock(controller.preparationBlockReason());
      consentPanel?.setAvailable(!busy && !["LOGGED_OUT","LOGOUT_UNCONFIRMED"].includes(state.phase));
      currentOperation.disabled = !controller.canReadCurrentOperation();
      if (state.phase === "READY" && state.selection?.kind === "operation") {
        kind.value = "operation"; id.value = state.selection.id;
      }
      reconcile.disabled = !controller.canReconcile();
      detail.disabled = !controller.canReadDetail();
      logout.disabled = state.phase === "LOGGING_OUT" || state.phase === "LOGGED_OUT";
      result.setAttribute("aria-busy", busy ? "true" : "false");
      status.textContent = state.phase === "LOGOUT_UNCONFIRMED" ? MESSAGES.LOGOUT_UNCONFIRMED :
        ERROR_MESSAGES[state.code] ?? MESSAGES[state.phase] ?? MESSAGES.ERROR;
      const available = controller.canUseSaved(), selectedValue = saved.value;
      clearSavedOptions();
      for (const [index, item] of state.savedReferences.entries()) {
        const option = create("option", item.kind + ": " + item.id, saved); option.value = String(index);
      }
      saved.value = selectedValue !== "" && state.savedReferences[Number(selectedValue)] ? selectedValue : state.savedReferences.length ? "0" : "";
      saved.disabled = busy || !available || !state.savedReferences.length;
      loadSaved.disabled = busy || !references;
      reopen.disabled = saved.disabled; forget.disabled = saved.disabled;
      recovery.textContent = !references ? "Browser recovery references are not configured. Keep the original ID." :
        state.referenceStatus === "REFERENCE_NOT_SAVED" ? "This ID could not be saved. Keep the original reference." :
        ["REFERENCE_STORE_INVALID", "REFERENCE_STORE_FULL", "REFERENCE_WRITE_UNCONFIRMED",
          "STORAGE_UNAVAILABLE", "RECOVERY_IDENTITY_UNAVAILABLE", "REFERENCE_SCOPE_CHANGED"].includes(state.referenceStatus) ?
          "Browser recovery is unavailable (" + state.referenceStatus + "). Existing storage was not automatically cleared. Keep the original ID." :
        state.referenceStatus === "REFERENCE_FORGOTTEN" ? "The selected local bookmark was removed. IRIS history is unchanged." :
        available ? state.savedReferences.length + " saved reference(s). Reopen to read current server state." :
        "Load references after checking the IRIS session. No automatic read or resend.";
      if (state.view) result.appendChild(renderModel(state.view));
    } catch {
      clearResults(); showSection(null); clearSavedOptions(); saved.disabled = true;
      loadSaved.disabled = true; reopen.disabled = true; forget.disabled = true;
      lookup.disabled = true; reconcile.disabled = true; detail.disabled = true; currentOperation.disabled = true;
      consentPanel?.setAvailable(false); conversationPanel?.setAvailable(false);
      status.textContent = ERROR_MESSAGES.PRESENTATION_FAILED;
      throw new Error("PRESENTATION_FAILED");
    }
  };
  if (consentRoot) consentPanel = mountConsentPanel(consentRoot, {
    client, references, preparations:createPreparationReferences({client,storage}), evidence: mode, now, schedule, cancel, renderModel,
    selection: () => ({kind:kind.value,id:id.value}),
    preparationBlock: () => controller.preparationBlockReason(),
    onActivate() {
      setActiveMode("consent"); conversationPanel?.deactivate(); controller.disconnect(); clearResults(); clearSavedOptions();
      saved.disabled = true; reopen.disabled = true; forget.disabled = true;
      detail.disabled = true; reconcile.disabled = true; currentOperation.disabled = true;
      showSection(1);
      status.textContent = "Approval review and recorded results are shown below.";
      recovery.textContent = "Original IDs remain in scoped storage. Load saved references to leave this review.";
    },
    onOutcomeWarning(show) {
      if (destroyed || activeMode !== "consent" || !outcomeNotice) return;
      outcomeNotice.hidden = !show;
    },
    onBusy(busy) {
      if (destroyed || activeMode !== "consent") return;
      lookup.disabled = busy;
      conversationPanel?.setAvailable(!busy); loadSaved.disabled = busy || !references;
      // Logout remains available to invalidate an in-flight action; this cannot undo a sent change.
      logout.disabled = false;
    },
  });
  if (chatRoot) conversationPanel = mountConversationPanel(chatRoot, {
    client, selection:()=>({kind:kind.value,id:id.value}),
    onActivate() {
      setActiveMode("conversation"); consentPanel?.deactivate(); controller.disconnect(); clearResults(); clearSavedOptions();
      saved.disabled=true; reopen.disabled=true; forget.disabled=true;
      detail.disabled=true; reconcile.disabled=true; currentOperation.disabled=true;
      showSection(0);
      status.textContent="Case conversation is active below. Approval remains a separate action.";
      recovery.textContent="The conversation remains in this tab. Read the original conversation after an uncertain reply.";
    },
    onBusy(busy) {
      if(destroyed||activeMode!=="conversation")return;
      lookup.disabled=busy;loadSaved.disabled=busy||!references;logout.disabled=false;
      consentPanel?.setAvailable(!busy);
    },
  });
  const enterReadMode = () => {
    if (activeMode === "read") return;
    setActiveMode("read"); conversationPanel?.deactivate(); consentPanel?.deactivate(); controller.disconnect();
  };
  const invalidate = () => {
    setActiveMode("read"); conversationPanel?.deactivate(); consentPanel?.deactivate(); controller.disconnect();
  };
  controller = createResultController({client, references, evidence: mode, onChange: paint});
  paint(controller.snapshot());
  const listeners = [];
  const listen = (element, type, handler) => {
    element.addEventListener(type, handler); listeners.push([element, type, handler]);
  };
  for (const [index, target] of [header, form, recoveryPanel].entries()) {
    listen(navButtons[index], "click", () => {
      if (destroyed) return;
      navButtons.forEach((b, i) => { b.className = i === index ? "is-active" : ""; });
      target.scrollIntoView?.({block: "start", behavior: "auto"}); target.focus();
    });
  }
  navButtons[1].className = "is-active";
  if (outcomeJump) listen(outcomeJump, "click", () => {
    if (!destroyed && activeMode === "consent" && !outcomeNotice.hidden) consentPanel.focusOriginalOutcome();
  });
  const act = async action => {
    if (destroyed) return;
    try { await action(); }
    catch {
      if (destroyed) return;
      invalidate();
      status.textContent = "The request could not be started. Check the original reference.";
    }
  };
  listen(form, "submit", async event => {
    event.preventDefault();
    if (destroyed || lookup.disabled) return;
    if (!ID.test(id.value) || !["decision", "preview", "operation"].includes(kind.value)) {
      invalidate(); status.textContent = "Enter a valid original reference (1–128 letters, digits, dots, underscores or hyphens).";
      id.focus(); return;
    }
    enterReadMode();
    await act(() => controller.select(kind.value, id.value));
  });
  listen(loadSaved, "click", () => {
    if (loadSaved.disabled) return;
    enterReadMode();
    return act(() => controller.loadReferences());
  });
  listen(reopen, "click", () => {
    if (reopen.disabled || saved.value === "") return;
    return act(() => controller.reopenReference(Number(saved.value)));
  });
  listen(forget, "click", () => {
    if (forget.disabled || saved.value === "") return;
    return act(() => controller.forgetReference(Number(saved.value)));
  });
  listen(detail, "click", () => {
    if (detail.disabled) return;
    return act(() => controller.readSelectedDetail());
  });
  listen(currentOperation, "click", () => {
    if (currentOperation.disabled) return;
    return act(() => controller.readCurrentOperation());
  });
  listen(reconcile, "click", () => {
    if (reconcile.disabled) return;
    return act(() => controller.reconcileSelected());
  });
  listen(disconnect, "click", () => {
    if (!destroyed) invalidate();
  });
  listen(logout, "click", () => {
    if (logout.disabled) return;
    enterReadMode();
    return act(() => controller.logout());
  });
  for (const [element, type] of [[id, "input"], [kind, "change"]]) {
    listen(element, type, () => { if (!destroyed) invalidate(); });
  }
  return Object.freeze({
    destroy() {
      if (destroyed) return;
      destroyed = true; conversationPanel?.destroy(); consentPanel?.destroy(); controller.disconnect(); clearResults();
      for (const [element, type, handler] of listeners) element.removeEventListener(type, handler);
      root.replaceChildren();
    },
  });
}
