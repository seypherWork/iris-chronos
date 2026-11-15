import test from "node:test";
import assert from "node:assert/strict";
import {createWorkflowController} from "../../src/chronos_web/workflow-controller.mjs";
import {ChronosClientError} from "../../src/chronos_web/client.mjs";

const clone = value => structuredClone(value);
const note = "NOTE_RAM_ONLY customer explicitly prefers earlier arrival.";
const identity = () => ({available: true, actor: "principal-" + "a".repeat(64),
  actorScope: "b".repeat(64), applicationUrl: "https://chronos.example/csp/chronos/"});
const baseNow = 1800000000000;
const status = (patch = {}) => ({code: "WORKFLOW_STATUS_RECORDED", decisionId: "held-1",
  clarificationId: "clarify-1", newDecisionId: "", state: "RESPONSE_UNVERIFIED", expiresUS: baseNow * 1000 + 600000000,
  taskReady: true, completionRecorded: false, canUseClarification: false, dispatch_authorized: false, ...patch});
const empty = () => status({code: "WORKFLOW_NOT_FOUND", clarificationId: "", state: "NOT_FOUND",
  expiresUS: null, taskReady: false});
const receipt = (completionId = "generated-1", patch = {}) => ({code: "WORKFLOW_CLARIFICATION_RECORDED",
  clarificationId: "clarify-1", completionId, state: "VERIFIED_CSP", expiresUS: baseNow * 1000 + 600000000,
  completedUS: baseNow * 1000, actorVerified: true, completionVerified: true,
  canUseClarification: false, dispatch_authorized: false, ...patch});
const deferred = () => {let resolve, reject; const promise = new Promise((r, j) => {resolve = r; reject = j;}); return {promise, resolve, reject};};
const count = (s, command) => s.calls.filter(c => c[0] === command).length;

function setup({packet = status(), approve = true, mode = "LIVE_MODEL", hooks = {}, options = {}} = {}) {
  let connected = false, currentIdentity = identity(), counter = 0, clock = baseNow, currentPacket = clone(packet);
  const calls = [];
  const invoke = (name, fallback) => async (...args) => {
    calls.push([name, ...clone(args)]);
    return Object.hasOwn(hooks, name) ? hooks[name](...args) : fallback(...args);
  };
  const client = {
    connect: invoke("CONNECT", async () => {connected = true; return client.sessionStatus();}),
    disconnect: () => {calls.push(["DISCONNECT"]); connected = false;},
    sessionStatus: () => ({connected, canRead: connected, canApprove: connected && approve}),
    sessionIdentity: () => clone(currentIdentity), sessionExecution: () => ({mode}),
    readClarification: invoke("READ", () => clone(currentPacket)),
    startClarification: invoke("START", () => clone(currentPacket)),
    completeClarification: invoke("COMPLETE", (_, id) => receipt(id)),
    readClarificationCompletion: invoke("READ_COMPLETION", (_, id) => receipt(id)),
    reevaluateClarification: invoke("REEVALUATE", (_, id) => ({code: "DECISION_PREPARED", decisionId: id,
      readbackRequired: true, dispatch_authorized: false})),
    readDecision: invoke("READ_DECISION", id => ({code: "READ_ONLY", data: {decisionId: id, state: "PREPARED"}})),
    confirmPreview: () => assert.fail("Clarification must not confirm a shipment"),
    preparePreview: () => assert.fail("Clarification must not prepare shipment consent"),
    reconcileOperation: () => assert.fail("Clarification must not resolve a shipment effect"),
  };
  const controller = createWorkflowController({client, newId: () => "generated-" + (++counter), now: () => clock, ...options});
  return {client, controller, calls, hooks,
    setPacket(value) {currentPacket = clone(value);}, setIdentity(value) {currentIdentity = clone(value);},
    setApprove(value) {approve = value;}, setMode(value) {mode = value;}, setNow(value) {clock = value;},
    connectDirect() {connected = true;}};
}

test("opening is one authenticated read, without creating a native task or calling the model", async () => {
  const s = setup();
  assert.deepEqual(s.calls, []);
  assert.equal(s.controller.snapshot().canOpen, true);
  await s.controller.open("held-1");
  assert.deepEqual(s.calls, [["CONNECT"], ["READ", "held-1"]]);
  assert.equal(s.controller.snapshot().phase, "NEEDS_INPUT");
  assert.equal(s.controller.snapshot().canComplete, true);
  assert.equal(await s.controller.open("other-held"), false);
  assert.equal(count(s, "START"), 0);
});

test("a task can be started only once from EMPTY by a current approver", async () => {
  const s = setup({packet: empty()});
  await s.controller.open("held-1");
  assert.equal(s.controller.snapshot().canStart, true);
  s.setPacket(status({code: "WORKFLOW_HANDOFF_QUEUED", clarificationId: "", state: "QUEUED", taskReady: false, expiresUS: null}));
  await s.controller.start();
  assert.equal(count(s, "START"), 1);
  assert.equal(s.controller.snapshot().phase, "WAITING");
  assert.equal(await s.controller.start(), false);
  assert.equal(count(s, "START"), 1);
  assert.equal(count(s, "READ"), 1);
});

test("completion requires an actual task and a verified native receipt; it never performs shipment approval", async () => {
  const s = setup();
  await s.controller.open("held-1");
  await s.controller.complete("EARLIEST_ALLOWED", note);
  assert.deepEqual(s.calls.find(c => c[0] === "COMPLETE"),
    ["COMPLETE", "clarify-1", "generated-1", {preference: "EARLIEST_ALLOWED", note}]);
  const snapshot = s.controller.snapshot();
  assert.equal(snapshot.phase, "RECORDED");
  assert.equal(snapshot.canComplete, false);
  assert.equal(snapshot.canReevaluate, true);
  assert.equal(snapshot.view.dispatch_authorized, false);
  assert.equal(snapshot.view.canUseClarification, false);
  assert.equal(await s.controller.complete("EARLIEST_ALLOWED", note), false);
  assert.equal(count(s, "COMPLETE"), 1);
  assert.equal(count(s, "REEVALUATE"), 0);
});

test("a queue acknowledgement or incomplete native flags cannot be relabelled a verified completion", async () => {
  for (const value of [receipt("generated-1", {code: "WORKFLOW_RESOLUTION_UNCERTAIN", actorVerified: false, completionVerified: false}),
    receipt("generated-1", {actorVerified: false}), receipt("generated-1", {completionVerified: false})]) {
    const s = setup({hooks: {COMPLETE: () => value}});
    await s.controller.open("held-1");
    await s.controller.complete("EARLIEST_ALLOWED", note);
    assert.equal(s.controller.snapshot().phase, "COMPLETION_UNCERTAIN");
    assert.equal(s.controller.snapshot().canReevaluate, false);
    assert.equal(s.controller.snapshot().canClose, false);
  }
});

test("a missing task, invalid form and invalid generated identifier cannot reach completion", async () => {
  const waiting = setup({packet: status({taskReady: false})});
  await waiting.controller.open("held-1");
  assert.equal(await waiting.controller.complete("EARLIEST_ALLOWED", note), false);
  assert.equal(count(waiting, "COMPLETE"), 0);
  const s = setup(); await s.controller.open("held-1");
  for (const [preference, text] of [["SEND", note], ["EARLIEST_ALLOWED", ""], ["EARLIEST_ALLOWED", " leading"],
    ["EARLIEST_ALLOWED", "bad\nline"], ["EARLIEST_ALLOWED", "bad\u202eformat"], ["EARLIEST_ALLOWED", "🙂".repeat(241)]]) {
    assert.equal(await s.controller.complete(preference, text), false);
  }
  assert.equal(count(s, "CONNECT"), 1); assert.equal(count(s, "COMPLETE"), 0);
  const bad = setup({options: {newId: () => "../bad"}}); await bad.controller.open("held-1");
  await bad.controller.complete("EARLIEST_ALLOWED", note);
  assert.equal(count(bad, "COMPLETE"), 0);
});

test("a lost completion reply keeps uncertainty and an explicit NEW read never repeats the original call", async () => {
  const s = setup({hooks: {COMPLETE: () => {throw new ChronosClientError("REQUEST_TIMEOUT");},
    READ_COMPLETION: () => ({code: "WORKFLOW_RESOLUTION_NEW", actorVerified: false, completionVerified: false,
      canUseClarification: false, dispatch_authorized: false})}});
  await s.controller.open("held-1"); await s.controller.complete("EARLIEST_ALLOWED", note);
  assert.equal(s.controller.snapshot().phase, "COMPLETION_UNCERTAIN");
  assert.equal(s.controller.snapshot().canReadCompletion, true);
  assert.equal(count(s, "READ_COMPLETION"), 0);
  await s.controller.readCompletion();
  assert.equal(s.controller.snapshot().phase, "COMPLETION_UNCERTAIN");
  assert.equal(s.controller.snapshot().completionId, "generated-1");
  assert.equal(s.controller.snapshot().canComplete, false);
  assert.equal(s.controller.snapshot().canClose, false);
  assert.equal(count(s, "COMPLETE"), 1);
  assert.deepEqual(s.calls.find(c => c[0] === "READ_COMPLETION"),
    ["READ_COMPLETION", "clarify-1", "generated-1", {preference: "EARLIEST_ALLOWED", note}]);
});

test("a later explicit verified completion read resolves the original ID and clears its private note", async () => {
  const s = setup({hooks: {COMPLETE: () => {throw new ChronosClientError("REQUEST_TIMEOUT");}}});
  await s.controller.open("held-1"); await s.controller.complete("EARLIEST_ALLOWED", note);
  await s.controller.readCompletion();
  assert.equal(s.controller.snapshot().phase, "RECORDED");
  assert.equal(s.controller.snapshot().canReadCompletion, false);
  assert.equal(s.controller.snapshot().canReevaluate, true);
  assert.equal(s.controller.snapshot().canClose, true);
  assert.equal(count(s, "COMPLETE"), 1);
});

test("a lost reevaluation reply remains uncertain if the original status has no registered decision reference", async () => {
  const s = setup({packet: status({completionRecorded: true}), hooks: {REEVALUATE: () => {throw new ChronosClientError("REQUEST_TIMEOUT");}}});
  await s.controller.open("held-1"); await s.controller.reevaluate();
  assert.equal(s.controller.snapshot().phase, "EVALUATION_UNCERTAIN");
  await s.controller.read();
  assert.equal(s.controller.snapshot().phase, "EVALUATION_UNCERTAIN");
  assert.equal(s.controller.snapshot().canReevaluate, false);
  assert.equal(s.controller.snapshot().canClose, false);
  assert.equal(count(s, "REEVALUATE"), 1);
});

test("lost reevaluation can resolve by historical registration reference without another evaluation", async () => {
  const s = setup({packet: status({completionRecorded: true}), hooks: {REEVALUATE: () => {throw new ChronosClientError("REQUEST_TIMEOUT");}}});
  await s.controller.open("held-1"); await s.controller.reevaluate();
  s.setPacket(status({completionRecorded: true, newDecisionId: "generated-1"}));
  await s.controller.read();
  assert.equal(s.controller.snapshot().phase, "DECISION_REGISTERED");
  assert.equal(s.controller.snapshot().newDecisionId, "generated-1");
  assert.equal(s.controller.snapshot().canReadDecision, true);
  assert.equal(s.controller.snapshot().canReevaluate, false);
  assert.equal(s.controller.snapshot().canClose, true);
  assert.equal(await s.controller.reevaluate(), false);
  assert.equal(count(s, "REEVALUATE"), 1);
  assert.equal(count(s, "READ_DECISION"), 0);
});

test("the note and raw errors never appear in any snapshot or presentation callback", async () => {
  const seen = [];
  const s = setup({options: {onChange: value => seen.push(value)}, hooks: {
    COMPLETE: () => {throw new Error(note + " PRIVATE_ERROR_SENTINEL");}}});
  await s.controller.open("held-1"); await s.controller.complete("EARLIEST_ALLOWED", note);
  await s.controller.readCompletion();
  for (const value of [...seen, s.controller.snapshot()]) {
    assert.equal(JSON.stringify(value).includes(note), false);
    assert.equal(JSON.stringify(value).includes("PRIVATE_ERROR_SENTINEL"), false);
  }
});

test("actor, namespace scope and installation changes hide references immediately and clear the old context on read", async () => {
  for (const change of [{actor: "principal-" + "c".repeat(64)}, {actorScope: "d".repeat(64)},
    {applicationUrl: "https://other.example/csp/chronos/"}]) {
    const s = setup(); await s.controller.open("held-1");
    s.setIdentity({...identity(), ...change});
    const hidden = s.controller.snapshot();
    assert.equal(hidden.view, null);
    for (const key of ["decisionId", "clarificationId", "completionId", "newDecisionId"]) assert.equal(hidden[key], "");
    await s.controller.read();
    assert.equal(s.controller.snapshot().code, "REFERENCE_SCOPE_CHANGED");
    assert.equal(s.controller.snapshot().view, null);
    assert.equal(s.controller.snapshot().canOpen, true);
    assert.equal(count(s, "READ"), 1);
  }
});

test("read-only access cannot start, complete or reevaluate a task", async () => {
  for (const packet of [empty(), status(), status({completionRecorded: true})]) {
    const s = setup({packet, approve: false}); await s.controller.open("held-1");
    assert.equal(s.controller.snapshot().canStart, false);
    assert.equal(s.controller.snapshot().canComplete, false);
    assert.equal(s.controller.snapshot().canReevaluate, false);
    assert.equal(await s.controller.start(), false);
    assert.equal(await s.controller.complete("EARLIEST_ALLOWED", note), false);
    assert.equal(await s.controller.reevaluate(), false);
    assert.equal(count(s, "START") + count(s, "COMPLETE") + count(s, "REEVALUATE"), 0);
    assert.equal(s.controller.snapshot().canRead, true);
  }
});

test("revoking approver capability disables the original completion read that also requires APPROVE", async () => {
  const s = setup({hooks: {COMPLETE: () => {throw new ChronosClientError("REQUEST_TIMEOUT");}}});
  await s.controller.open("held-1"); await s.controller.complete("EARLIEST_ALLOWED", note);
  s.setApprove(false);
  assert.equal(s.controller.snapshot().canReadCompletion, false);
  assert.equal(await s.controller.readCompletion(), false);
  assert.equal(count(s, "READ_COMPLETION"), 0);
  assert.equal(s.controller.snapshot().canRead, true);
});

test("approver permission is rechecked after reconnect before reading an original completion", async () => {
  const s = setup({hooks: {COMPLETE: () => {throw new ChronosClientError("REQUEST_TIMEOUT");}}});
  await s.controller.open("held-1"); await s.controller.complete("EARLIEST_ALLOWED", note);
  assert.equal(s.controller.snapshot().canReadCompletion, true);
  s.hooks.CONNECT = async () => {s.connectDirect(); s.setApprove(false); return s.client.sessionStatus();};
  assert.equal(await s.controller.readCompletion(), false);
  assert.equal(count(s, "READ_COMPLETION"), 0);
  assert.equal(s.controller.snapshot().code, "PERMISSION_DENIED");
});

test("recorded mode prevents reevaluation while retaining read-only inspection", async () => {
  const s = setup({packet: status({completionRecorded: true}), mode: "RECORDED_FIXTURE"});
  await s.controller.open("held-1");
  assert.equal(s.controller.snapshot().canReevaluate, false);
  assert.equal(await s.controller.reevaluate(), false);
  await s.controller.read(); assert.equal(count(s, "READ"), 2);
  assert.equal(count(s, "REEVALUATE"), 0);
});

test("an expired UI context blocks mutations but still permits historical reads", async () => {
  const s = setup(); await s.controller.open("held-1");
  s.setNow(baseNow + 600000);
  assert.equal(s.controller.snapshot().canComplete, false);
  assert.equal(await s.controller.complete("EARLIEST_ALLOWED", note), false);
  assert.equal(s.controller.snapshot().canRead, true);
  s.setPacket(status({state: "EXPIRED"})); await s.controller.read();
  assert.equal(s.controller.snapshot().phase, "EXPIRED"); assert.equal(count(s, "COMPLETE"), 0);
  const recorded = setup({packet: status({completionRecorded: true})}); await recorded.controller.open("held-1");
  recorded.setNow(baseNow + 600000);
  assert.equal(recorded.controller.snapshot().canReevaluate, false);
  assert.equal(await recorded.controller.reevaluate(), false);
});

test("late network results after deactivation cannot restore view or references", async () => {
  const pending = deferred();
  const s = setup({hooks: {READ: () => pending.promise}});
  const opening = s.controller.open("held-1");
  await new Promise(resolve => setImmediate(resolve));
  s.controller.deactivate(); pending.resolve(status()); await opening;
  const hidden = s.controller.snapshot();
  assert.equal(hidden.phase, "HIDDEN"); assert.equal(hidden.view, null);
  assert.equal(hidden.decisionId, ""); assert.equal(hidden.clarificationId, "");
  assert.equal(hidden.canComplete, false); assert.equal(count(s, "READ"), 1);
});

test("synchronous presentation failure blocks outgoing completion without exposing exception text", async () => {
  let broken = false;
  const s = setup({options: {onChange: value => {
    if (broken && value.phase === "COMPLETING") throw new Error("PRIVATE_RENDER_ERROR");
  }}});
  await s.controller.open("held-1"); broken = true;
  assert.equal(await s.controller.complete("EARLIEST_ALLOWED", note), false);
  assert.equal(count(s, "COMPLETE"), 0);
  assert.equal(s.controller.snapshot().code, "PRESENTATION_FAILED");
  assert.equal(s.controller.snapshot().canComplete, false);
  assert.equal(JSON.stringify(s.controller.snapshot()).includes("PRIVATE_RENDER_ERROR"), false);
});

test("deactivation or disposal inside a presentation callback stops every next I/O boundary", async () => {
  for (const phase of ["CONNECTING", "READING"]) {
    for (const action of ["deactivate", "destroy"]) {
      let s, armed = true;
      s = setup({options: {onChange: value => {
        if (armed && value.phase === phase) {armed = false; s.controller[action]();}
      }}});
      const result = await s.controller.open("held-1");
      assert.equal(result, false, phase + ":" + action);
      assert.equal(count(s, "READ"), 0, phase + ":" + action);
      if (phase === "CONNECTING") assert.equal(count(s, "CONNECT"), 0, phase + ":" + action);
      assert.equal(s.controller.snapshot().view, null);
    }
  }
});

test("closing is blocked during a pending request and after an uncertain mutation", async () => {
  const pending = deferred(); const s = setup({hooks: {COMPLETE: () => pending.promise}});
  await s.controller.open("held-1"); const completing = s.controller.complete("EARLIEST_ALLOWED", note);
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(s.controller.snapshot().canClose, false); assert.equal(s.controller.close(), false);
  pending.reject(new ChronosClientError("REQUEST_TIMEOUT")); await completing;
  assert.equal(s.controller.close(), false);
  assert.equal(count(s, "COMPLETE"), 1);
});

test("explicit actions never start polling, repeated handoffs, model calls or recovery calls automatically", async () => {
  const s = setup({packet: empty(), hooks: {START: () => {throw new ChronosClientError("REQUEST_TIMEOUT");}}});
  await s.controller.open("held-1"); await s.controller.start();
  const before = s.calls.length;
  await new Promise(resolve => setTimeout(resolve, 15));
  assert.equal(s.calls.length, before);
  s.setPacket(empty()); await s.controller.read();
  assert.equal(s.controller.snapshot().phase, "HANDOFF_UNCERTAIN");
  assert.equal(s.controller.snapshot().canStart, false); assert.equal(s.controller.close(), false);
  assert.equal(count(s, "START"), 1); assert.equal(count(s, "READ"), 2);
});

test("destroyed controllers make no later requests, and snapshots cannot rewrite private status", async () => {
  const s = setup(); await s.controller.open("held-1");
  const view = s.controller.snapshot(); view.view.taskReady = false; view.view.clarificationId = "other";
  assert.equal(s.controller.snapshot().canComplete, true);
  assert.equal(s.controller.snapshot().clarificationId, "clarify-1");
  s.controller.destroy(); const before = s.calls.length;
  assert.equal(await s.controller.open("held-1"), false);
  assert.equal(await s.controller.read(), false);
  assert.equal(await s.controller.complete("EARLIEST_ALLOWED", note), false);
  assert.equal(s.calls.length, before);
});
