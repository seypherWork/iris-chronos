/**
 * Same-origin client for Chronos.Web.API. No login credentials, storage, logging,
 * polling or retries. Authentication is performed by IRIS, not by this module.
 * Source/tests only until the final web application installs and verifies it.
 */
import {conversationV2,PLAN_V2,REPLY_V2} from "./conversation-v2.mjs";
const ID = /^[A-Za-z0-9_.-]{1,128}$/;
const CODE = /^[A-Z0-9_]{1,80}$/;
const CSRF = /^[0-9a-f]{64}$/;
const MAX_BYTES = 512 * 1024;
const COMMANDS = Object.freeze({
  DECISION: ["decision", "read"], DECISION_DETAIL: ["decision", "read"], DECISION_OPERATION: ["decision", "read"], RESOLVE_DECISION: ["decision", "approve"],
  PREVIEW: ["approval", "approve"], READ: ["approval", "read"],
  PREVIEW_REQUEST: ["approval", "approve"], READ_PREPARATION: ["approval", "read"],
  CLOSE_PREPARATION: ["approval", "approve"],
  CONFIRM: ["approval", "approve"], REJECT: ["approval", "approve"],
  RECONCILE: ["approval", "read"], READ_OPERATION: ["approval", "read"], RECONCILE_OPERATION: ["approval", "read"],
});
const CORRELATED = new Set(["PREVIEW_REQUEST", "CLOSE_PREPARATION"]);
const MAY_CHANGE = new Set(["PREVIEW_REQUEST", "CLOSE_PREPARATION", "PREVIEW", "CONFIRM", "REJECT", "RECONCILE", "RECONCILE_OPERATION",
  "RESOLVE_DECISION", "LOGOUT", "CONVERSATION_OPEN", "CONVERSATION_RECORD"]);
const SESSION_CODES = new Set(["PERMISSION_DENIED", "IDENTITY_UNAVAILABLE",
  "SESSION_UNAVAILABLE", "ACCESS_REVOKED", "CSRF_REJECTED", "CALL_CONTEXT_CHANGED"]);

export class ChronosClientError extends Error {
  constructor(code, {command = "", id = "", mayHaveApplied = false} = {}) {
    super(code);
    this.name = "ChronosClientError";
    this.code = code;
    this.command = command;
    this.id = id;
    this.mayHaveApplied = mayHaveApplied;
    // These IDs are references for an explicit read; they are not permission.
    this.readbackRequired = mayHaveApplied;
  }
}

const record = value => value !== null && typeof value === "object" && !Array.isArray(value);
const status = (connected = false, canRead = false, canApprove = false) =>
  Object.freeze({connected, canRead, canApprove});

const unavailableIdentity = () => Object.freeze({
  available: false, actor: "", actorScope: "", applicationUrl: "",
});
function sessionIdentity(value, canRead, base) {
  // Legacy servers still permit reads/logout; absent identity cannot activate
  // durable recovery or consent. Present malformed metadata is not legacy.
  if (!Object.hasOwn(value, "identity")) return unavailableIdentity();
  const identity = value.identity;
  const exact = keys => record(identity) &&
    Object.keys(identity).sort().join(",") === [...keys].sort().join(",");
  if (exact(["version", "available"]) && identity.version === 1 && identity.available === false) {
    return unavailableIdentity();
  }
  if (!canRead || !exact(["version", "available", "actor", "actorScope", "applicationUrl"]) ||
      identity.version !== 1 || identity.available !== true ||
      typeof identity.actor !== "string" || !/^principal-[0-9a-f]{64}$/.test(identity.actor) ||
      typeof identity.actorScope !== "string" || !/^[0-9a-f]{64}$/.test(identity.actorScope) ||
      identity.applicationUrl !== base) throw new ChronosClientError("INVALID_SESSION");
  return Object.freeze({available: true, actor: identity.actor,
    actorScope: identity.actorScope, applicationUrl: identity.applicationUrl});
}

function installation(pageUrl, basePath) {
  let page;
  try { page = new URL(pageUrl); } catch { throw new ChronosClientError("INVALID_INSTALLATION"); }
  if (page.username || page.password ||
      !(page.protocol === "https:" || (page.protocol === "http:" &&
        ["127.0.0.1", "[::1]", "localhost"].includes(page.hostname))) ||
      typeof basePath !== "string" ||
      !/^\/(?:[A-Za-z0-9_-]+\/)*[A-Za-z0-9_-]+\/?$/.test(basePath)) {
    throw new ChronosClientError("INVALID_INSTALLATION");
  }
  return page.origin + basePath.replace(/\/$/, "") + "/";
}

async function boundedJSON(response, url, signal, fail) {
  const reject = code => {
    try { void response?.body?.cancel().catch(() => {}); } catch { /* Already closed/locked. */ }
    return fail(code);
  };
  if (signal.aborted) throw reject(signal.reason);
  if (!response || typeof response.status !== "number") throw reject("INVALID_RESPONSE");
  if (response.status === 401 || response.status === 403 ||
      (response.status >= 300 && response.status < 400)) throw reject("SESSION_REQUIRED");
  if (response.redirected || (response.url && response.url !== url)) throw reject("UNEXPECTED_RESPONSE_URL");
  if (!/^application\/json(?:\s*;\s*charset=utf-8)?$/i.test(response.headers?.get("content-type") ?? "")) {
    throw reject("INVALID_RESPONSE");
  }
  const declared = response.headers.get("content-length");
  if (declared !== null && (!/^\d+$/.test(declared) || Number(declared) > MAX_BYTES)) {
    throw reject("RESPONSE_TOO_LARGE");
  }
  if (!response.body?.getReader) throw reject("INVALID_RESPONSE");
  const reader = response.body.getReader();
  const cancel = () => { void reader.cancel().catch(() => {}); };
  signal.addEventListener("abort", cancel, {once: true});
  const chunks = [];
  let size = 0, complete = false;
  try {
    while (true) {
      if (signal.aborted) throw fail(signal.reason);
      const item = await reader.read();
      if (item.done) { complete = true; break; }
      size += item.value.byteLength;
      if (size > MAX_BYTES) { cancel(); throw fail("RESPONSE_TOO_LARGE"); }
      chunks.push(item.value);
    }
    const bytes = new Uint8Array(size);
    let offset = 0;
    for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
    let parsed;
    try { parsed = JSON.parse(new TextDecoder("utf-8", {fatal: true}).decode(bytes)); }
    catch { throw fail("INVALID_RESPONSE"); }
    if (!record(parsed) || typeof parsed.code !== "string" || !CODE.test(parsed.code)) {
      throw fail("INVALID_RESPONSE");
    }
    if (!response.ok) throw fail("SERVER_" + parsed.code);
    return parsed;
  } finally {
    if (!complete) cancel();
    signal.removeEventListener("abort", cancel);
    reader.releaseLock();
  }
}

/**
 * basePath is fixed trusted installer configuration (for example /csp/chronos).
 * pageUrl/fetchImpl are injectable for local tests, never form or query inputs.
 * Only the native cookie is sent by the browser. The CSRF token is private memory.
 */
export function createChronosClient({
  basePath, pageUrl = globalThis.location?.href,
  fetchImpl = globalThis.fetch?.bind(globalThis), timeoutMs = 35000,
} = {}) {
  const base = installation(pageUrl, basePath);
  if (typeof fetchImpl !== "function" || !Number.isInteger(timeoutMs) ||
      timeoutMs < 1 || timeoutMs > 40000) throw new ChronosClientError("INVALID_INSTALLATION");
  let epoch = 0, csrf = "", capabilities = status(), identity = unavailableIdentity(), busy = false, canConverse = false;
  const active = new Set();

  function clear(reason = "CONNECTION_CHANGED") {
    epoch += 1;
    csrf = "";
    capabilities = status();
    canConverse = false;
    identity = unavailableIdentity();
    busy = false;
    for (const controller of active) controller.abort(reason);
    active.clear();
  }

  async function exchange(endpoint, method, body, token, command, id, version) {
    const url = base + endpoint, controller = new AbortController();
    let attempted = false;
    const fail = code => new ChronosClientError(code, {
      command, id, mayHaveApplied: attempted && MAY_CHANGE.has(command),
    });
    active.add(controller);
    const aborted = new Promise((_, reject) => {
      controller.signal.addEventListener("abort",
        () => reject(fail(controller.signal.reason)), {once: true});
    });
    const timer = setTimeout(() => controller.abort("REQUEST_TIMEOUT"), timeoutMs);
    try {
      const headers = {"Accept": "application/json"};
      if (method === "POST") {
        headers["Content-Type"] = "application/json";
        headers["X-Chronos-CSRF"] = token;
      }
      const operation = (async () => {
        attempted = true;
        const response = await fetchImpl(url, {
          method, headers, ...(method === "POST" ? {body: JSON.stringify(body)} : {}),
          credentials: "same-origin", mode: "same-origin", cache: "no-store",
          redirect: "error", referrerPolicy: "no-referrer", signal: controller.signal,
        });
        return boundedJSON(response, url, controller.signal, fail);
      })();
      const value = await Promise.race([operation, aborted]);
      if (version !== epoch) throw fail("CONNECTION_CHANGED");
      return value;
    } catch (error) {
      if (!controller.signal.aborted) controller.abort("REQUEST_FAILED");
      if (error instanceof ChronosClientError) throw error;
      // No response, exception text or provider message enters application logs.
      throw fail("TRANSPORT_UNAVAILABLE");
    } finally {
      clearTimeout(timer);
      active.delete(controller);
    }
  }

  async function connect() {
    clear();
    const version = epoch;
    busy = true;
    try {
      const value = await exchange("session", "GET", null, "", "SESSION", "", version);
      if (version !== epoch) throw new ChronosClientError("CONNECTION_CHANGED");
      if (value.authenticated !== true || typeof value.csrf !== "string" || !CSRF.test(value.csrf) ||
          typeof value.canRead !== "boolean" || typeof value.canApprove !== "boolean" ||
          (value.canApprove && !value.canRead) ||
          !(value.code === "CONNECTED" && value.canRead ||
            value.code === "ACCESS_REVOKED" && !value.canRead && !value.canApprove)) {
        throw new ChronosClientError("INVALID_SESSION");
      }
      if (value.canConverse !== undefined && (typeof value.canConverse !== "boolean" || value.canConverse && !value.canRead)) {
        throw new ChronosClientError("INVALID_SESSION");
      }
      canConverse = value.canConverse === true;
      identity = sessionIdentity(value, value.canRead, base);
      csrf = value.csrf;
      capabilities = status(true, value.canRead, value.canApprove);
      return capabilities;
    } catch (error) {
      if (version === epoch) clear();
      throw error;
    } finally {
      if (version === epoch) busy = false;
    }
  }

  async function request(command, id, requestId) {
    if (!Object.hasOwn(COMMANDS, command) || typeof id !== "string" || !ID.test(id) ||
        (CORRELATED.has(command) ? typeof requestId !== "string" || !ID.test(requestId) : requestId !== undefined)) {
      throw new ChronosClientError("INVALID_REQUEST");
    }
    if (busy) throw new ChronosClientError("REQUEST_IN_PROGRESS");
    const [endpoint, permission] = COMMANDS[command];
    if (!capabilities.connected || !csrf) throw new ChronosClientError("SESSION_REQUIRED");
    if (!capabilities.canRead || (permission === "approve" && !capabilities.canApprove)) {
      throw new ChronosClientError("PERMISSION_DENIED");
    }
    const version = epoch;
    busy = true;
    try {
      const body = CORRELATED.has(command) ? {command, id, requestId} : {command, id};
      const value = await exchange(endpoint, "POST", body, csrf, command, id, version);
      if (version !== epoch) throw new ChronosClientError("CONNECTION_CHANGED",
        {command, id, mayHaveApplied: MAY_CHANGE.has(command)});
      if (SESSION_CODES.has(value.code) || SESSION_CODES.has(value.data?.code)) {
        clear();
        throw new ChronosClientError("SESSION_REQUIRED", {command, id,
          mayHaveApplied: MAY_CHANGE.has(command)});
      }
      if (value.data !== undefined && value.data !== null && !record(value.data)) {
        throw new ChronosClientError("INVALID_RESPONSE", {command, id,
          mayHaveApplied: MAY_CHANGE.has(command)});
      }
      const trace = value.traceSessionId ?? "";
      if (!(typeof trace === "string" && trace.length <= 128 ||
            Number.isSafeInteger(trace) && trace >= 0)) {
        throw new ChronosClientError("INVALID_RESPONSE", {command, id,
          mayHaveApplied: MAY_CHANGE.has(command)});
      }
      // Business ERROR/HOLD/UNKNOWN remain server results, never coerced to success.
      // Render data as untrusted text; this is not a domain-schema validator.
      return {code: value.code, traceSessionId: trace, data: value.data ?? null};
    } catch (error) {
      if (version === epoch) clear();
      throw error;
    } finally {
      if (version === epoch) busy = false;
    }
  }


  async function conversationRequest(command, conversationId, decisionId, fields) {
    const fail = (code, applied = false) => {
      const error = new ChronosClientError(code, {command: "CONVERSATION_" + command,
        id: conversationId, mayHaveApplied: applied});
      error.decisionId = decisionId;
      error.turnId = typeof fields?.turnId === "string" ? fields.turnId : "";
      return error;
    };
    const exact = (value, keys) => record(value) &&
      Object.keys(value).sort().join(",") === [...keys].sort().join(",");
    const validText = (value, maxBytes = 2048) => typeof value === "string" && value.trim().length > 0 &&
      !/[\u0000-\u0008\u000b-\u001f]/.test(value) &&
      ![...value].some(ch => ch.codePointAt(0) >= 0xd800 && ch.codePointAt(0) <= 0xdfff) &&
      new TextEncoder().encode(value).length <= maxBytes;
    // Schema length is in code points; user/evidence byte limits remain unchanged.
    const validAnswer = value => validText(value, 8192) && [...value].length <= 2048;

    // Structural checks for authenticated host-rendered replies. The browser
    // does not independently establish the truth of a native ledger record.
    const planContract = "chronos.case-explanation-plan.v1", replyContract = "chronos.case-explanation.v1";
    const rendererVersion = "chronos.explanation-renderer.v1";
    const topics = ["DECISION","COMPARISON","OPERATION_STATUS","PHYSICAL_DELIVERY","PREFERENCE_CHANGE","APPROVAL_REQUIREMENTS","CLARIFY"];
    const hash = x => typeof x === "string" && CSRF.test(x);
    const ident = x => typeof x === "string" && ID.test(x);
    const integer = x => Number.isSafeInteger(x) && x >= 0;
    const prefs = ["CHEAPEST_ON_TIME","EARLIEST_ALLOWED"];
    const optionRows = rows => Array.isArray(rows) && rows.length <= 2 && new Set(rows.map(r=>r?.action)).size === rows.length &&
      rows.every(r=>exact(r,["action","cost","accepted_at","arrival"]) && ["RETRY_A","FAILOVER_B"].includes(r.action) &&
        [r.cost,r.accepted_at,r.arrival].every(integer) && r.arrival >= r.accepted_at);
    const receipt = r => exact(r,["schema","context_digest","proposal_digest","source_contract","selection_basis","selection_available",
      "validation_observed_at","validation_available","validation_trials","finished_at_us"]) &&
      r.schema === "chronos.decision-explanation.v1" && hash(r.context_digest) && hash(r.proposal_digest) &&
      ["chronos.agent-proposal.v2","chronos.preference-extraction.v1"].includes(r.source_contract) &&
      r.selection_basis === (r.source_contract === "chronos.preference-extraction.v1" ? "BOUND_PREPARE" : "FRESH_FINISH") &&
      optionRows(r.selection_available) && optionRows(r.validation_available) && integer(r.validation_observed_at) && integer(r.finished_at_us) &&
      Array.isArray(r.validation_trials) && r.validation_trials.length <= 2 &&
      new Set(r.validation_trials.map(t=>t?.action)).size === r.validation_trials.length &&
      r.validation_trials.every(t=>exact(t,["action","state","reason","cost","accepted_at","arrival","rejected_at"]) &&
        ["RETRY_A","FAILOVER_B"].includes(t.action) && ["QUEUED","BLOCKED","NOT_ACCEPTED_FINAL","ACCEPTED","DELIVERED_SIMULATED"].includes(t.state) &&
        typeof t.reason === "string" && /^[A-Z0-9_]{0,128}$/.test(t.reason) && integer(t.cost) &&
        [t.accepted_at,t.arrival,t.rejected_at].every(x=>x===null||integer(x)));
    const source = s => {
      if (!record(s) || s.decision_id !== decisionId) return false;
      if (s.id === "decision") return exact(s,["id","kind","decision_id","decision_digest","context_digest","action","option_id","interpreted_preference","reason_code","attribution"]) &&
        s.kind === "HISTORICAL_DECISION" && hash(s.decision_digest) && hash(s.context_digest) &&
        ["RETRY_A","FAILOVER_B","HOLD"].includes(s.action) && (s.action === "HOLD" ? s.option_id===null : ident(s.option_id)) &&
        [...prefs,"UNRESOLVED"].includes(s.interpreted_preference) && typeof s.reason_code === "string" && CODE.test(s.reason_code) &&
        exact(s.attribution,["responseContract","interpretationOrigin","selectionOrigin"]) &&
        ["chronos.agent-proposal.v2","chronos.preference-extraction.v1"].includes(s.attribution.responseContract) &&
        ["MODEL","NOT_RECORDED"].includes(s.attribution.interpretationOrigin) && ["DETERMINISTIC_CODE","NOT_RECORDED"].includes(s.attribution.selectionOrigin);
      if (s.id === "finish") return exact(s,["id","kind","decision_id","decision_digest","receipt","receipt_digest","policy","trial_mode","time_unit","cost_unit"]) &&
        s.kind === "ARCHIVED_FINISH_VALIDATION" && hash(s.decision_digest) && hash(s.receipt_digest) && receipt(s.receipt) &&
        exact(s.policy,["budget","deadline","inventory_expires","offer_until"]) && Object.values(s.policy).every(integer) &&
        ["WITH_TRIALS","WITHOUT_TRIALS_ABLATION"].includes(s.trial_mode) && s.time_unit === "relative_microseconds" && s.cost_unit === "synthetic_units";
      if (s.id === "current-operation") return exact(s,["id","kind","decision_id","operation_id","attempt_id","state","quarantined","read_digest"]) &&
        s.kind === "CURRENT_READ" && ident(s.operation_id) && ident(s.attempt_id) &&
        ["IN_FLIGHT","UNKNOWN","ACCEPTED","NOT_ACCEPTED_FINAL"].includes(s.state) && typeof s.quarantined === "boolean" && hash(s.read_digest);
      return s.id === "current-read-missing" && exact(s,["id","kind","decision_id","context_digest"]) && s.kind === "READ_NOT_SUPPLIED" && hash(s.context_digest);
    };
    const grounding = context => {
      const g = context.grounding, sections = topics.filter(t=>t!=="PREFERENCE_CHANGE");
      if (context.response_contract !== planContract || context.renderer_version !== rendererVersion ||
          !exact(g,["decision_digest","sections","sources","source_records","operation_missing","quarantined","blocking_notice"]) ||
          !hash(g.decision_digest) || !exact(g.sections,sections) || !exact(g.sources,sections) || !record(g.source_records) ||
          typeof g.operation_missing !== "boolean" || typeof g.quarantined !== "boolean") return false;
      const ids = Object.keys(g.source_records), current = g.operation_missing ? "current-read-missing" : "current-operation";
      if (!ids.includes("decision") || !ids.includes(current) || ids.some(id=>!["decision","finish",current].includes(id)) ||
          ids.some(id=>g.source_records[id]?.id!==id || !source(g.source_records[id])) ||
          ["decision","finish"].some(id=>g.source_records[id] && g.source_records[id].decision_digest!==g.decision_digest)) return false;
      if (!sections.every(t=>validAnswer(g.sections[t]) && Array.isArray(g.sources[t]) &&
          g.sources[t].every(id=>ids.includes(id)) && new Set(g.sources[t]).size===g.sources[t].length)) return false;
      const op = g.source_records[current], blocked = !g.operation_missing && (op.quarantined || ["UNKNOWN","IN_FLIGHT"].includes(op.state));
      return g.sources.OPERATION_STATUS.length===1 && g.sources.OPERATION_STATUS[0]===current &&
        (g.operation_missing ? !g.quarantined : op.quarantined===g.quarantined && op.operation_id===context.operation_id) &&
        (blocked ? g.blocking_notice===g.sections.OPERATION_STATUS : g.blocking_notice===null);
    };
    const groundedReply = (r, turnId) => {
      if (!exact(r,["schema","conversation_id","turn_id","context_digest","catalog_digest","topic","detail","renderer_version","intent","answer",
          "source_ids","preference","sources","plan_origin","answer_origin","dispatch_authorized","confirmation_granted","requires_new_evaluation"]) ||
          r.schema!==replyContract || r.conversation_id!==conversationId || r.turn_id!==turnId || !hash(r.context_digest) || !hash(r.catalog_digest) ||
          !topics.includes(r.topic) || !["concise","detailed"].includes(r.detail) || r.renderer_version!==rendererVersion || !validAnswer(r.answer) ||
          r.plan_origin!=="MODEL_INTERPRETATION" || r.answer_origin!=="DETERMINISTIC_EVIDENCE" ||
          r.dispatch_authorized!==false || r.confirmation_granted!==false || r.requires_new_evaluation!==(r.topic==="PREFERENCE_CHANGE") ||
          !Array.isArray(r.sources) || r.sources.length>4 || !r.sources.every(source) || !Array.isArray(r.source_ids) ||
          r.source_ids.length!==r.sources.length || new Set(r.source_ids).size!==r.source_ids.length ||
          r.sources.some((s,i)=>s.id!==r.source_ids[i]) || (r.source_ids.length===0 && !["CLARIFY","PREFERENCE_CHANGE"].includes(r.topic))) return false;
      if (r.topic === "PREFERENCE_CHANGE") return r.intent === "PREFERENCE_PROPOSAL" && prefs.includes(r.preference);
      if (r.preference !== null) return false;
      return r.topic === "APPROVAL_REQUIREMENTS" ? r.intent === "APPROVAL_REDIRECT" :
        r.topic === "OPERATION_STATUS" ? ["ANSWER","RESULT_QUERY"].includes(r.intent) : r.intent === "ANSWER";
    };

    const v2=conversationV2({exact,record,validText,validAnswer,hash,ident,integer,prefs,optionRows,source,grounding,decisionId,conversationId});
    if (!["OPEN","READ","RECORD"].includes(command) ||
        typeof conversationId !== "string" || !ID.test(conversationId) ||
        typeof decisionId !== "string" || !ID.test(decisionId)) throw fail("INVALID_REQUEST");
    if (command === "RECORD") {
      if (!exact(fields, ["turnId","expectedRevision","expectedContextDigest","text"]) ||
          typeof fields.turnId !== "string" || !ID.test(fields.turnId) ||
          !Number.isSafeInteger(fields.expectedRevision) || fields.expectedRevision < 1 || fields.expectedRevision > 6 ||
          typeof fields.expectedContextDigest !== "string" || !CSRF.test(fields.expectedContextDigest) ||
          !validText(fields.text)) throw fail("INVALID_REQUEST");
    } else if (fields !== undefined) throw fail("INVALID_REQUEST");
    // Keep response validation and lost-reply references bound to what was sent,
    // even if a form/controller mutates its input object during the await.
    if (command === "RECORD") fields = Object.freeze({...fields});
    if (busy) throw fail("REQUEST_IN_PROGRESS");
    if (!capabilities.connected || !csrf) throw fail("SESSION_REQUIRED");
    if (!capabilities.canRead || !canConverse) throw fail("CONVERSATION_UNAVAILABLE");
    const body = {command, conversationId, decisionId, ...(fields ?? {})};
    const version = epoch, mayChange = command !== "READ";
    busy = true;
    try {
      const value = await exchange("conversation", "POST", body, csrf,
        "CONVERSATION_" + command, conversationId, version);
      if (version !== epoch) throw fail("CONNECTION_CHANGED", mayChange);
      if (!exact(value, ["code","conversation","context","context_digest","inference_granted","dispatch_authorized"]) ||
          value.inference_granted !== false || value.dispatch_authorized !== false ||
          typeof value.context_digest !== "string" || !CSRF.test(value.context_digest)) {
        throw fail("INVALID_CONVERSATION_RESPONSE", mayChange);
      }
      const allowed = command === "OPEN" ? ["CONVERSATION_OPENED","CONVERSATION_EXISTS"] :
        command === "READ" ? ["CONVERSATION_READ"] : ["TURN_RECORDED","TURN_REPLAY"];
      const conv = value.conversation, context = value.context;
      const isGrounded = record(context) && Object.hasOwn(context,"response_contract");
      const contextKeys = ["decision_id","revision","conversation_revision","generation","operation_id","result_scope","evidence",
        ...(isGrounded ? ["response_contract","renderer_version","grounding"] : [])];
      if (!allowed.includes(value.code) ||
          !exact(conv, ["conversation_id","case_id","shipment_version","revision","turn_limit","turns",
            "preference_events","dispatch_authorized","confirmation_granted"]) ||
          conv.conversation_id !== conversationId || typeof conv.case_id !== "string" || !ID.test(conv.case_id) ||
          !Number.isSafeInteger(conv.shipment_version) || conv.shipment_version < 1 ||
          conv.dispatch_authorized !== false || conv.confirmation_granted !== false || conv.turn_limit !== 6 ||
          !Array.isArray(conv.turns) || conv.turns.length > 6 || conv.revision !== conv.turns.length + 1 ||
          !Array.isArray(conv.preference_events) || conv.preference_events.length > conv.turns.length ||
          !exact(context, contextKeys) || (isGrounded && !(context.response_contract===PLAN_V2?v2.context(context):grounding(context))) ||
          context.decision_id !== decisionId || context.conversation_revision !== conv.revision ||
          !Number.isSafeInteger(context.revision) || context.revision < 1 ||
          typeof context.generation !== "string" || !ID.test(context.generation) ||
          !(context.operation_id === null || typeof context.operation_id === "string" && ID.test(context.operation_id)) ||
          context.result_scope !== "CURRENT_SHIPMENT" || !Array.isArray(context.evidence) ||
          context.evidence.length < 1 || context.evidence.length > 16 ||
          new TextEncoder().encode(JSON.stringify(context)).length > (context.response_contract===PLAN_V2?98304:isGrounded ? 65536 : 16384)) throw fail("INVALID_CONVERSATION_RESPONSE", mayChange);
      const evidenceIds = new Set(), turnIds = new Set();
      for (const row of context.evidence) {
        if (!exact(row, ["id","text","provenance"]) || typeof row.id !== "string" || !ID.test(row.id) ||
            evidenceIds.has(row.id) || !validText(row.text) ||
            !["CURRENT_READ","HISTORICAL_DECISION","SIMULATION"].includes(row.provenance)) throw fail("INVALID_CONVERSATION_RESPONSE", mayChange);
        evidenceIds.add(row.id);
      }
      for (const turn of conv.turns) {
        if (!exact(turn, ["turn_id","user_text","state","response","error"]) ||
            typeof turn.turn_id !== "string" || !ID.test(turn.turn_id) || turnIds.has(turn.turn_id) ||
            !validText(turn.user_text) || !["RECORDED","PROCESSING","UNCERTAIN","REJECTED","COMPLETED"].includes(turn.state) ||
            !(turn.error === null || typeof turn.error === "string" && CODE.test(turn.error))) throw fail("INVALID_CONVERSATION_RESPONSE", mayChange);
        turnIds.add(turn.turn_id);
        const response = turn.response;
        if (turn.state !== "COMPLETED") {
          if (response !== null) throw fail("INVALID_CONVERSATION_RESPONSE", mayChange);
          continue;
        }
        if (response?.schema === REPLY_V2) {
          if (!v2.reply(response,turn.turn_id)) throw fail("INVALID_CONVERSATION_RESPONSE",mayChange);
          continue;
        }
        if (response?.schema === replyContract) {
          if (!groundedReply(response,turn.turn_id)) throw fail("INVALID_CONVERSATION_RESPONSE",mayChange);
          continue;
        }
        if (!exact(response, ["schema","conversation_id","turn_id","context_digest","intent","answer","source_ids","preference",
              "origin","dispatch_authorized","confirmation_granted","requires_new_evaluation"]) ||
            response.schema !== "chronos.case-conversation.v1" || response.conversation_id !== conversationId ||
            response.turn_id !== turn.turn_id || typeof response.context_digest !== "string" || !CSRF.test(response.context_digest) ||
            !["ANSWER","PREFERENCE_PROPOSAL","RESULT_QUERY","APPROVAL_REDIRECT"].includes(response.intent) ||
            !validAnswer(response.answer) || response.origin !== "MODEL_INTERPRETATION" ||
            response.dispatch_authorized !== false || response.confirmation_granted !== false ||
            response.requires_new_evaluation !== (response.intent === "PREFERENCE_PROPOSAL") ||
            !Array.isArray(response.source_ids) || response.source_ids.length > 16 ||
            response.source_ids.some(id => typeof id !== "string" || !ID.test(id)) ||
            new Set(response.source_ids).size !== response.source_ids.length ||
            (!response.source_ids.length && response.intent !== "APPROVAL_REDIRECT") ||
            (response.intent === "PREFERENCE_PROPOSAL" ? !["CHEAPEST_ON_TIME","EARLIEST_ALLOWED"].includes(response.preference) : response.preference !== null)) {
          throw fail("INVALID_CONVERSATION_RESPONSE", mayChange);
        }
      }
      const eventIds = new Set(), eventTurns = new Set();
      for (const event of conv.preference_events) {
        const turn = conv.turns.find(t => t.turn_id === event?.turn_id);
        if (!exact(event, ["kind","turn_id","decision_id","context_digest","preference","adopted","event_id"]) ||
            event.kind !== "OPERATOR_PREFERENCE_PROPOSAL" || event.adopted !== false ||
            typeof event.decision_id !== "string" || !ID.test(event.decision_id) ||
            typeof event.event_id !== "string" || !CSRF.test(event.event_id) || eventIds.has(event.event_id) || eventTurns.has(event.turn_id) ||
            turn?.response?.intent !== "PREFERENCE_PROPOSAL" || event.preference !== turn.response.preference ||
            event.context_digest !== turn.response.context_digest) throw fail("INVALID_CONVERSATION_RESPONSE", mayChange);
        eventIds.add(event.event_id); eventTurns.add(event.turn_id);
      }
      if (eventTurns.size !== conv.turns.filter(t => t.response?.intent === "PREFERENCE_PROPOSAL").length) throw fail("INVALID_CONVERSATION_RESPONSE", mayChange);
      if (command === "RECORD") {
        const index = conv.turns.findIndex(t => t.turn_id === fields.turnId), original = conv.turns[index];
        if (!original || original.user_text !== fields.text || index + 1 !== fields.expectedRevision ||
            value.code === "TURN_RECORDED" && (conv.revision !== fields.expectedRevision + 1 || index !== conv.turns.length - 1)) {
          throw fail("INVALID_CONVERSATION_RESPONSE", true);
        }
      }
      // This is a bound server record, not factual validation of model prose.
      // No source text is interpreted as HTML, approval or another request.
      return value;
    } catch (error) {
      if (version === epoch) clear();
      if (error instanceof ChronosClientError) {
        error.decisionId = decisionId;
        error.turnId = typeof fields?.turnId === "string" ? fields.turnId : "";
      }
      throw error;
    } finally {
      if (version === epoch) busy = false;
    }
  }

  async function logout() {
    const token = csrf;
    clear();
    if (!token) throw new ChronosClientError("SESSION_REQUIRED");
    const version = epoch;
    busy = true;
    try {
      const value = await exchange("logout", "POST", {}, token, "LOGOUT", "", version);
      if (version !== epoch) throw new ChronosClientError("CONNECTION_CHANGED",
        {command: "LOGOUT", mayHaveApplied: true});
      if (value.code !== "SESSION_ENDED") throw new ChronosClientError("LOGOUT_UNCONFIRMED",
        {command: "LOGOUT", mayHaveApplied: true});
      return {code: "SESSION_ENDED"};
    } finally {
      if (version === epoch) busy = false;
    }
  }

  return Object.freeze({
    connect, logout, disconnect: () => clear(), sessionStatus: () => capabilities,
    sessionIdentity: () => identity,
    conversationAvailable: () => canConverse,
    openConversation: (conversationId, decisionId) => conversationRequest("OPEN", conversationId, decisionId),
    readConversation: (conversationId, decisionId) => conversationRequest("READ", conversationId, decisionId),
    recordConversation: (conversationId, decisionId, fields) => conversationRequest("RECORD", conversationId, decisionId, fields),
    readDecision: id => request("DECISION", id),
    readDecisionDetail: id => request("DECISION_DETAIL", id),
    readDecisionOperation: id => request("DECISION_OPERATION", id),
    readOperation: id => request("READ_OPERATION", id),
    reconcileOperation: id => request("RECONCILE_OPERATION", id),
    resolveDecision: id => request("RESOLVE_DECISION", id),
    preview: id => request("PREVIEW", id),
    preparePreview: (id, requestId) => request("PREVIEW_REQUEST", id, requestId),
    readPreparation: requestId => request("READ_PREPARATION", requestId),
    closePreparation: (id, requestId) => request("CLOSE_PREPARATION", id, requestId),
    readPreview: id => request("READ", id),
    confirmPreview: id => request("CONFIRM", id),
    rejectPreview: id => request("REJECT", id),
    reconcilePreview: id => request("RECONCILE", id),
  });
}
