import test from "node:test";
import assert from "node:assert/strict";
import {createRecoveryReferences} from "../../src/chronos_web/references.mjs";
import {createResultController} from "../../src/chronos_web/controller.mjs";
import {createChronosClient, ChronosClientError} from "../../src/chronos_web/client.mjs";

const scope = "a".repeat(64);
const refConfig = {applicationUrl: "https://chronos.example/csp/chronos", actorScope: scope};
function memory() {
  const values = new Map(); let writes = 0;
  return {values, get writes() {return writes;},
    getItem(key) {return values.get(key) ?? null;},
    setItem(key, value) {writes += 1; values.set(key, value);},
    clear() {throw new Error("must not clear browser storage");}};
}
const ref = (id, kind = "preview") => ({kind, id});
const deferred = () => {
  let resolve, reject;
  const promise = new Promise((yes, no) => {resolve = yes; reject = no;});
  return {promise, resolve, reject};
};
const decision = id => ({code: "EXISTING_DECISION", traceSessionId: 1, data: {
  code: "EXISTING_DECISION", requestId: id, orderId: "o1", shipmentVersion: 1,
  mode: "WITH_TRIALS", generation: "g1", state: "COMPLETED", deadlineUS: 1793296800000000,
  dispatchGranted: false, inferenceGranted: false, dispatch_authorized: false,
  outcome: {status: "VALIDATED_HOLD", dispatch_authorized: false},
}});
const packet = data => ({code: data.code, traceSessionId: 1, data});
const preview = () => packet({
  code: "READ_ONLY", dispatchGranted: false, previewId: "p1", state: "CONFIRMED",
  decisionId: "d1", decisionDigest: "a".repeat(64), orderId: "o1", shipmentVersion: 1,
  operationId: "op1", actor: "fixture", generation: "g1", snapshotId: 2,
  option: "FAILOVER_B", target: "B", createdAt: 5864205600, expiresAt: 5864205660,
  reviewDeadlineUS: 1793297100000000, predictedArrival: 5864205720,
  snapshot: {orderId: "o1", shipmentVersion: 1, revision: 1, policyRevision: 1, quantity: 1,
    payload: "synthetic", maxCost: 8, observedAt: 5864205600, inventoryUntil: 5864205900,
    deliveryDeadline: 5864206200,
    offers: Object.fromEntries(["A", "B"].map(target => [target, {target, cost: 2,
      availableAt: 5864205600, queueSeconds: 0, travelSeconds: 120, validUntil: 5864205900, capacity: 2}]))},
});
function clientDouble(overrides = {}) {
  const calls = [];
  const client = {
    connect: async () => {calls.push(["connect"]); return {connected: true, canRead: true, canApprove: false};},
    disconnect: () => {calls.push(["disconnect"]);},
    readDecision: async id => {calls.push(["readDecision", id]); return decision(id);},
    readPreview: async id => {calls.push(["readPreview", id]); return preview();},
    reconcilePreview: async id => {calls.push(["reconcilePreview", id]); return packet({
      code: "READBACK_RECORDED", dispatchGranted: false, operationId: "op1", attemptId: "a1",
      state: "UNKNOWN", reference: "", quarantined: false});},
    logout: async () => {calls.push(["logout"]); return {code: "SESSION_ENDED"};},
    ...overrides,
  };
  return {client, calls};
}
const tick = () => new Promise(resolve => setImmediate(resolve));

test("references survive store reconstruction and contain only version/kind/id", () => {
  const storage = memory();
  const store = createRecoveryReferences({...refConfig, storage});
  assert.equal(store.remember(ref("p1")).ok, true);
  assert.equal(store.remember(ref("d1", "decision")).ok, true);
  const again = createRecoveryReferences({...refConfig, storage});
  assert.deepEqual(again.list().items, [ref("p1"), ref("d1", "decision")]);
  const saved = JSON.parse([...storage.values.values()][0]);
  assert.deepEqual(saved, {version: 1, items: [ref("p1"), ref("d1", "decision")]});
  const writes = storage.writes;
  assert.equal(again.remember(ref("p1")).code, "ALREADY_REMEMBERED");
  assert.equal(storage.writes, writes);
});

test("application and actor scopes do not read each other's reference keys", () => {
  const storage = memory();
  const a = createRecoveryReferences({...refConfig, storage});
  a.remember(ref("p1"));
  const b = createRecoveryReferences({...refConfig, storage, actorScope: "b".repeat(64)});
  const c = createRecoveryReferences({...refConfig, storage, applicationUrl: "https://chronos.example/csp/other"});
  assert.equal(b.list().items.length, 0);
  assert.equal(c.list().items.length, 0);
  assert.equal(a.list().items.length, 1);
});

test("missing server actor scope or malformed application cannot create a reference store", () => {
  for (const actorScope of [undefined, "", "user-name", "A".repeat(64)]) {
    assert.throws(() => createRecoveryReferences({...refConfig, storage: memory(), actorScope}), TypeError);
  }
  for (const applicationUrl of ["https://u:p@chronos.example/api", "https://chronos.example/api?q=1",
    "http://chronos.example/api", "file:///api", "https://chronos.example/a%2fb"]) {
    assert.throws(() => createRecoveryReferences({...refConfig, storage: memory(), applicationUrl}), TypeError);
  }
});

test("foreign fields, credentials, payloads and invalid IDs are rejected before storage", () => {
  const storage = memory(), store = createRecoveryReferences({...refConfig, storage});
  for (const item of [null, {kind: "preview", id: "p1", csrf: "SENTINEL"},
    {kind: "preview", id: "p1", payload: "SENTINEL"}, ref("../p"), ref("p", "unknown-kind"),
    ref(""), ref("x".repeat(129))]) {
    assert.equal(store.remember(item).code, "INVALID_REFERENCE");
  }
  assert.equal(storage.values.size, 0);
});

test("corrupt, duplicate, oversized or foreign storage is preserved without silent repair", () => {
  const storage = memory(), store = createRecoveryReferences({...refConfig, storage});
  store.remember(ref("p1"));
  const key = [...storage.values.keys()][0];
  for (const raw of [
    "{", JSON.stringify({version: 2, items: []}),
    '{"version":1,"items":[{"kind":"preview","id":"p1"}],"items":[]}',
    JSON.stringify({version: 1, items: [ref("p1"), ref("p1")]}),
    JSON.stringify({version: 1, items: [{...ref("p1"), payload: "PRIVATE"}]}),
    "x".repeat(8193),
  ]) {
    storage.values.set(key, raw);
    assert.equal(store.list().ok, false);
    assert.equal(store.remember(ref("p2")).ok, false);
    assert.equal(store.forget(ref("p1")).ok, false);
    assert.equal(storage.values.get(key), raw);
  }
});

test("full reference store never evicts an earlier possibly unresolved operation", () => {
  const storage = memory(), store = createRecoveryReferences({...refConfig, storage});
  for (let i = 0; i < 32; i += 1) assert.equal(store.remember(ref("p" + i)).ok, true);
  const before = [...storage.values.values()][0];
  assert.equal(store.remember(ref("p32")).code, "REFERENCE_STORE_FULL");
  assert.equal([...storage.values.values()][0], before);
  assert.equal(store.list().items[0].id, "p0");
});

test("explicit forgetting touches only the selected record, no global clear", () => {
  const storage = memory(), store = createRecoveryReferences({...refConfig, storage});
  storage.values.set("unrelated", "KEEP");
  store.remember(ref("p1")); store.remember(ref("p2"));
  assert.equal(store.forget(ref("p1")).code, "REFERENCE_FORGOTTEN");
  assert.deepEqual(store.list().items, [ref("p2")]);
  assert.equal(storage.values.get("unrelated"), "KEEP");
});

test("blocked storage or unconfirmed writes remain failures without leaking exception details", () => {
  const denied = createRecoveryReferences({...refConfig, storage: {
    getItem() {throw new Error("PRIVATE");}, setItem() {throw new Error("PRIVATE");}}});
  assert.equal(denied.list().code, "STORAGE_UNAVAILABLE");
  const writeDenied = createRecoveryReferences({...refConfig, storage: {
    getItem() {return null;}, setItem() {throw new Error("PRIVATE");}}});
  const result = writeDenied.remember(ref("p1"));
  assert.equal(result.code, "REFERENCE_WRITE_UNCONFIRMED");
  assert.equal(JSON.stringify(result).includes("PRIVATE"), false);
});

test("detected storage changes do not trigger a blind overwrite or retry", () => {
  let reads = 0, writes = 0;
  const changed = createRecoveryReferences({...refConfig, storage: {
    getItem() {reads += 1; return reads === 1 ? null : JSON.stringify({version: 1, items: [ref("other")]});},
    setItem() {writes += 1;},
  }});
  assert.equal(changed.remember(ref("p1")).code, "REFERENCE_STORE_CHANGED");
  assert.equal(writes, 0);
});

test("controller construction does not read storage, connect or start work", () => {
  const {client, calls} = clientDouble();
  const controller = createResultController({client});
  assert.equal(controller.snapshot().phase, "DISCONNECTED");
  assert.equal(calls.length, 0);
  assert.equal(controller.confirmPreview, undefined);
  assert.equal(controller.preview, undefined);
});

test("controller reads explicit selection and reports unavailable recovery storage honestly", async () => {
  const {client, calls} = clientDouble();
  const controller = createResultController({client, evidence: "LOCAL_FIXTURE"});
  const state = await controller.select("decision", "d1");
  assert.equal(state.phase, "READY");
  assert.equal(state.selection.id, "d1");
  assert.equal(state.referenceStatus, "NOT_CONFIGURED");
  assert.equal(state.view.canConfirm, false);
  assert.deepEqual(calls, [["disconnect"], ["connect"], ["readDecision", "d1"]]);
});

test("late result cannot replace the newly selected case", async () => {
  const old = deferred();
  const {client} = clientDouble({readDecision: id => id === "old" ? old.promise : Promise.resolve(decision(id))});
  const rendered = [];
  const controller = createResultController({client, onChange: state => {rendered.push(state);}});
  const first = controller.select("decision", "old"); await tick();
  await controller.select("decision", "new");
  old.resolve(decision("old")); await first;
  assert.equal(controller.snapshot().selection.id, "new");
  assert.equal(controller.snapshot().view.rows.find(row => row.label === "Decision").value, "new");
  assert.equal(rendered.filter(state => state.phase === "READY" && state.selection.id === "old").length, 0);
});

test("late failure cannot clear a newer successful case", async () => {
  const old = deferred();
  const {client} = clientDouble({readDecision: id => id === "old" ? old.promise : Promise.resolve(decision(id))});
  const controller = createResultController({client});
  const first = controller.select("decision", "old"); await tick();
  await controller.select("decision", "new");
  old.reject(new Error("private old failure")); await first;
  assert.equal(controller.snapshot().phase, "READY");
  assert.equal(controller.snapshot().selection.id, "new");
});

test("disconnect clears visible data and suppresses a pending result", async () => {
  const old = deferred();
  const {client} = clientDouble({readDecision: () => old.promise});
  const controller = createResultController({client});
  const pending = controller.select("decision", "d1"); await tick();
  controller.disconnect(); old.resolve(decision("d1")); await pending;
  assert.equal(controller.snapshot().phase, "DISCONNECTED");
  assert.equal(controller.snapshot().selection, null);
  assert.equal(controller.snapshot().view, null);
});

test("observer-triggered selection invalidates the older flow before its read", async () => {
  const {client, calls} = clientDouble();
  let controller, latest;
  controller = createResultController({client, onChange: state => {
    if (state.phase === "CONNECTING" && state.selection.id === "old") latest = controller.select("decision", "new");
  }});
  await controller.select("decision", "old"); await latest;
  assert.equal(calls.some(call => call[0] === "readDecision" && call[1] === "old"), false);
  assert.equal(controller.snapshot().selection.id, "new");
});

test("render failure clears visible results without exposing raw exception text", async () => {
  const {client, calls} = clientDouble();
  const controller = createResultController({client, onChange: state => {
    if (state.phase === "READY") throw new Error("PRIVATE");
  }});
  await controller.select("decision", "d1");
  assert.equal(controller.snapshot().code, "PRESENTATION_FAILED");
  assert.equal(controller.snapshot().view, null);
  assert.equal(JSON.stringify(controller.snapshot()).includes("PRIVATE"), false);
  assert.equal(calls.at(-1)[0], "disconnect");
});

test("read-only access rejection never reaches the decision read", async () => {
  const {client, calls} = clientDouble({connect: async () => ({connected: true, canRead: false})});
  const controller = createResultController({client});
  const state = await controller.select("decision", "d1");
  assert.equal(state.code, "PERMISSION_DENIED");
  assert.equal(calls.some(call => call[0] === "readDecision"), false);
});

test("bad identity is not remembered and old screen contents are removed", async () => {
  let saves = 0;
  const {client} = clientDouble({readDecision: async () => decision("wrong")});
  const controller = createResultController({client, references: {remember() {saves += 1; return {ok: true};}}});
  const state = await controller.select("decision", "d1");
  assert.equal(state.phase, "ERROR");
  assert.equal(state.view.available, false);
  assert.equal(saves, 0);
});

test("storage failures do not masquerade as saved recovery references", async () => {
  const {client} = clientDouble();
  const controller = createResultController({client, references: {remember() {return {ok: false};}}});
  const state = await controller.select("decision", "d1");
  assert.equal(state.referenceStatus, "REFERENCE_NOT_SAVED");
  assert.equal(state.view.canConfirm, false);
});

test("reconcile is explicit and only uses the already confirmed preview reference", async () => {
  const {client, calls} = clientDouble();
  const controller = createResultController({client, evidence: "LOCAL_FIXTURE"});
  await assert.rejects(controller.reconcileSelected(), TypeError);
  await controller.select("preview", "p1");
  assert.equal(calls.filter(call => call[0] === "reconcilePreview").length, 0);
  const state = await controller.reconcileSelected();
  assert.equal(state.view.kind, "operation");
  assert.equal(state.view.title, "Operation outcome unknown");
  assert.deepEqual(calls.at(-1), ["reconcilePreview", "p1"]);
  assert.equal(state.view.canConfirm, false);
});

test("logout invalidates pending screen updates and distinguishes unconfirmed session ending", async () => {
  const pending = deferred();
  const {client} = clientDouble({
    readDecision: () => pending.promise,
    logout: async () => {throw new ChronosClientError("LOGOUT_UNCONFIRMED");},
  });
  const controller = createResultController({client});
  const read = controller.select("decision", "d1"); await tick();
  await controller.logout();
  pending.resolve(decision("d1")); await read;
  assert.equal(controller.snapshot().phase, "LOGOUT_UNCONFIRMED");
  assert.equal(controller.snapshot().selection, null);
  assert.equal(controller.snapshot().view, null);
});

test("actual client plus controller ignores obsolete fetch completion", async () => {
  const old = deferred(); const calls = [];
  const json = data => new Response(JSON.stringify(data), {headers: {"Content-Type": "application/json"}});
  const client = createChronosClient({basePath: "/csp/chronos", pageUrl: "https://chronos.example/ui",
    fetchImpl: (url, options) => {
      calls.push({url, options});
      if (url.endsWith("/session")) return json({code: "CONNECTED", authenticated: true, csrf: "b".repeat(64), canRead: true, canApprove: false});
      const {id} = JSON.parse(options.body);
      return id === "old" ? old.promise : json(decision(id));
    }});
  const controller = createResultController({client});
  const first = controller.select("decision", "old"); await tick();
  await controller.select("decision", "new");
  old.resolve(json(decision("old"))); await first; await tick();
  assert.equal(controller.snapshot().selection.id, "new");
  assert.equal(controller.snapshot().phase, "READY");
  assert.equal(calls.filter(call => call.options.method === "POST").length, 2);
});

test("asynchronous renderer is rejected before reads and rejection is consumed", async () => {
  for (const rejects of [false, true]) {
    const {client, calls} = clientDouble();
    const controller = createResultController({client, onChange: async () => {
      if (rejects) throw new Error("PRIVATE_ASYNC");
    }});
    await controller.select("decision", "d1");
    await tick();
    assert.equal(controller.snapshot().code, "PRESENTATION_FAILED");
    assert.equal(controller.snapshot().view, null);
    assert.equal(calls.some(call => call[0] === "readDecision"), false);
    assert.equal(JSON.stringify(controller.snapshot()).includes("PRIVATE_ASYNC"), false);
  }
});
