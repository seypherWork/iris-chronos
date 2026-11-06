import {readFileSync} from "node:fs";
import test from "node:test";
import assert from "node:assert/strict";
import {mountResultScreen} from "../../src/chronos_web/screen.mjs";
import {ChronosClientError, createChronosClient} from "../../src/chronos_web/client.mjs";

class Element {
  constructor(tag, doc) { this.tag = tag; this.ownerDocument = doc; this.children = []; this.attrs = {}; this.listeners = new Map(); this.value = ""; this._text = ""; }
  set textContent(value) { this._text = String(value); this.children = []; }
  get textContent() { return this._text + this.children.map(c => c.textContent).join(""); }
  set innerHTML(_) { throw Error("HTML forbidden"); }
  appendChild(child) { this.children.push(child); return child; }
  replaceChildren(...children) { this.children = children; this._text = ""; }
  setAttribute(name, value) { this.attrs[name] = value; }
  addEventListener(name, fn) { if (!this.listeners.has(name)) this.listeners.set(name, []); this.listeners.get(name).push(fn); }
  removeEventListener(name, fn) { this.listeners.set(name, (this.listeners.get(name) ?? []).filter(x => x !== fn)); }
  focus() { this.ownerDocument.focused = this; }
  async dispatch(name) {
    let prevented = false;
    for (const fn of this.listeners.get(name) ?? []) await fn({preventDefault() { prevented = true; }});
    return prevented;
  }
}
const flatten = root => [root, ...root.children.flatMap(flatten)];
const find = (root, predicate) => flatten(root).find(predicate);
const deferred = () => { let resolve, reject; const promise = new Promise((r, j) => {resolve = r; reject = j;}); return {promise, resolve, reject}; };
const tick = () => new Promise(resolve => setImmediate(resolve));
const decision = id => ({code: "EXISTING_DECISION", data: {
  code: "EXISTING_DECISION", dispatchGranted: false, inferenceGranted: false, dispatch_authorized: false,
  requestId: id, orderId: "order-1", shipmentVersion: 1, generation: "g1",
  deadlineUS: Date.parse("2026-10-29T18:00:00Z") * 1000, mode: "WITH_TRIALS", state: "COMPLETED",
  outcome: {status: "VALIDATED_PROPOSAL", code: "HUMAN_REVIEW_REQUIRED", dispatch_authorized: false},
}});
const preview = () => {
  const t = 4070908800 + Date.parse("2026-10-29T18:00:00Z") / 1000;
  return {code: "READ_ONLY", data: {
    code: "READ_ONLY", dispatchGranted: false, previewId: "p1", state: "CONFIRMED",
    decisionId: "d1", decisionDigest: "a".repeat(64), orderId: "o1", shipmentVersion: 1,
    operationId: "op1", actor: "fixture-operator", generation: "g1", snapshotId: 2,
    option: "FAILOVER_B", target: "B", createdAt: t, expiresAt: t + 60,
    reviewDeadlineUS: (t - 4070908800 + 300) * 1e6, predictedArrival: t + 120,
    snapshot: {orderId: "o1", shipmentVersion: 1, revision: 2, policyRevision: 1,
      quantity: 1, payload: "<img src=x onerror=alert(1)>", maxCost: 8, observedAt: t,
      inventoryUntil: t + 300, deliveryDeadline: t + 600,
      offers: Object.fromEntries(["A", "B"].map(target => [target, {
        target, cost: 3, availableAt: t, queueSeconds: 0, travelSeconds: 120, validUntil: t + 300, capacity: 2,
      }]))},
    operation: {code: "RESULT_UNCERTAIN", dispatchGranted: false, operationId: "op1",
      attemptId: "a1", state: "UNKNOWN", reference: "", quarantined: false},
  }};
};
function setup(overrides = {}) {
  const calls = [];
  const client = {
    connect: async () => {calls.push(["connect"]); return {connected: true, canRead: true};},
    disconnect: () => calls.push(["disconnect"]),
    readDecision: async id => {calls.push(["decision", id]); return decision(id);},
    readPreview: async id => {calls.push(["preview", id]); return preview();},
    reconcilePreview: async id => {calls.push(["reconcile", id]); return {code: "RESULT_UNCERTAIN", data: {
      code: "RESULT_UNCERTAIN", operationId: "op1", attemptId: "a1", state: "UNKNOWN",
      reference: "", quarantined: false, dispatchGranted: false,
    }};},
    logout: async () => {calls.push(["logout"]); return {code: "SESSION_ENDED"};},
    ...overrides,
  };
  const document = {createElement(tag) {
    if (this.failTag === tag) { this.failTag = null; throw new Error("PRIVATE_RENDER"); }
    return new Element(tag, this);
  }};
  const root = new Element("div", document);
  const screen = mountResultScreen(root, {client, evidence: "LOCAL_FIXTURE"});
  return {root, document, screen, calls,
    form: find(root, e => e.tag === "form"),
    input: find(root, e => e.tag === "input"),
    kind: find(root, e => e.tag === "select"),
    status: find(root, e => e.attrs.role === "status"),
    result: find(root, e => e.attrs["aria-label"] === "Current result"),
    button: label => find(root, e => e.tag === "button" && e.textContent === label),
  };
}
test("mount is disconnected, labeled as fixture, and starts no work", () => {
  const s = setup();
  assert.equal(s.calls.length, 0);
  assert.match(s.root.textContent, /Local fixture/);
  assert.match(s.status.textContent, /Disconnected/);
  assert.equal(s.button("Query destination outcome").disabled, true);
  assert.equal(flatten(s.root).some(e => ["iframe", "img", "a"].includes(e.tag)), false);
  assert.match(s.root.textContent, /cannot approve or send/);
});
test("empty or malformed input never reaches client, receives focus", async () => {
  for (const id of ["", "a/b", "a ".repeat(100), "<script>"]) {
    const s = setup(); s.input.value = id;
    assert.equal(await s.form.dispatch("submit"), true);
    assert.equal(s.calls.some(c => c[0] === "connect"), false);
    assert.equal(s.document.focused, s.input);
    assert.match(s.status.textContent, /valid original reference/);
  }
});
test("explicit decision lookup renders the identified result as unapproved", async () => {
  const s = setup(); s.input.value = "d1"; await s.form.dispatch("submit");
  assert.match(s.result.textContent, /Proposal requires human review/);
  assert.equal(s.button("Query destination outcome").disabled, true);
  assert.deepEqual(s.calls, [["disconnect"], ["connect"], ["decision", "d1"]]);
});
test("double submit while pending never duplicates the read", async () => {
  const wait = deferred(); let count = 0;
  const s = setup({readDecision: () => {count++; return wait.promise;}});
  s.input.value = "d1"; const first = s.form.dispatch("submit"); await tick();
  await s.form.dispatch("submit");
  assert.equal(count, 1);
  assert.equal(s.result.attrs["aria-busy"], "true");
  wait.resolve(decision("d1")); await first;
  assert.equal(s.result.attrs["aria-busy"], "false");
});
test("editing reference invalidates an earlier pending result", async () => {
  const wait = deferred();
  const s = setup({readDecision: () => wait.promise});
  s.input.value = "old"; const pending = s.form.dispatch("submit"); await tick();
  s.input.value = "new"; await s.input.dispatch("input");
  wait.resolve(decision("old")); await pending;
  assert.equal(s.result.textContent, "");
  assert.match(s.status.textContent, /Disconnected/);
});
test("changing reference type clears an earlier result without another read", async () => {
  const s = setup(); s.input.value = "d1"; await s.form.dispatch("submit");
  s.kind.value = "preview"; await s.kind.dispatch("change");
  assert.equal(s.result.textContent, "");
  assert.equal(s.calls.filter(c => c[0] === "decision").length, 1);
});
test("confirmed preview enables query only and hostile payload remains plain text", async () => {
  const s = setup(); s.kind.value = "preview"; s.input.value = "p1"; await s.form.dispatch("submit");
  assert.match(s.result.textContent, /<img src=x onerror=alert\(1\)>/);
  assert.equal(flatten(s.result).some(e => e.tag === "img"), false);
  assert.equal(s.button("Query destination outcome").disabled, false);
  assert.equal(s.calls.some(c => c[0] === "reconcile"), false);
  await s.button("Query destination outcome").dispatch("click");
  assert.deepEqual(s.calls.at(-1), ["reconcile", "p1"]);
  assert.match(s.result.textContent, /Operation outcome unknown/);
  assert.equal(s.calls.some(c => ["confirm", "submit", "previewCreate"].includes(c[0])), false);
});
test("expired authentication clears the earlier result and explains required session", async () => {
  let first = true;
  const s = setup({readDecision: async id => {
    if (first) { first = false; return decision(id); }
    throw new ChronosClientError("SESSION_REQUIRED");
  }});
  s.input.value = "d1"; await s.form.dispatch("submit");
  await s.form.dispatch("submit");
  assert.equal(s.result.textContent, "");
  assert.match(s.status.textContent, /IRIS session is required/);
});
test("failed render removes old DOM and blocks lookup until explicit disconnect", async () => {
  const s = setup(); s.input.value = "old"; await s.form.dispatch("submit");
  s.document.failTag = "h2"; s.input.value = "new"; await s.form.dispatch("submit");
  assert.equal(s.result.textContent, "");
  assert.match(s.status.textContent, /could not be displayed/);
  assert.equal(s.root.textContent.includes("PRIVATE_RENDER"), false);
  assert.equal(s.button("Read existing result").disabled, true);
  await s.button("Disconnect this screen").dispatch("click");
  assert.equal(s.button("Read existing result").disabled, false);
});
test("logout does not claim ended when the server did not confirm it", async () => {
  const s = setup({logout: async () => {throw new ChronosClientError("LOGOUT_UNCONFIRMED");}});
  s.input.value = "d1"; await s.form.dispatch("submit");
  await s.button("Sign out of IRIS").dispatch("click");
  assert.equal(s.result.textContent, "");
  assert.match(s.status.textContent, /not confirmed/);
  assert.equal(s.status.textContent.includes("confirmed that the session ended"), false);
});
test("confirmed logout is distinguishable and disables repeated logout", async () => {
  const s = setup(); await s.button("Sign out of IRIS").dispatch("click");
  assert.match(s.status.textContent, /confirmed that the session ended/);
  await s.button("Sign out of IRIS").dispatch("click");
  assert.equal(s.calls.filter(c => c[0] === "logout").length, 1);
});
test("destroy removes listeners and suppresses delayed result rendering", async () => {
  const wait = deferred(); const s = setup({readDecision: () => wait.promise});
  s.input.value = "d1"; const pending = s.form.dispatch("submit"); await tick();
  s.screen.destroy(); s.screen.destroy(); wait.resolve(decision("d1")); await pending;
  assert.equal(s.root.textContent, "");
  assert.equal([...s.form.listeners.values()].flat().length, 0);
});

test("boot rejects missing/unsafe routes and restores disconnected after page cache", async () => {
  const saved = new Map(["document", "location", "addEventListener", "fetch"].map(k =>
    [k, Object.getOwnPropertyDescriptor(globalThis, k)]));
  try {
    for (const [suffix, basePath, configured] of [
      ["missing", "", false], ["unsafe", "https://elsewhere.example/api", false], ["valid", "/csp/chronos", true],
    ]) {
      let network = 0;
      const doc = {createElement: tag => new Element(tag, doc)};
      const root = new Element("div", doc);
      doc.getElementById = () => root;
      doc.querySelector = () => ({content: basePath});
      const events = new Map();
      globalThis.document = doc;
      globalThis.location = {href: "https://chronos.example/web/index.html?basePath=https://attacker.example"};
      globalThis.addEventListener = (type, fn) => events.set(type, fn);
      globalThis.fetch = () => {network++; throw new Error("NETWORK_FORBIDDEN");};
      await import("../../src/chronos_web/boot.mjs?test=" + suffix);
      assert.equal(network, 0);
      if (configured) {
        assert.match(root.textContent, /Disconnected/);
        events.get("pagehide")();
        assert.equal(root.textContent, "");
        events.get("pageshow")({persisted: true});
        assert.match(root.textContent, /Disconnected/);
        assert.equal(flatten(root).filter(e => e.tag === "form").length, 2);
        assert.equal(flatten(root).filter(e => e.attrs["aria-label"] === "Read a case").length, 1);
        assert.equal(flatten(root).filter(e => e.attrs["aria-label"] === "Ask about this case").length, 1);
        assert.equal(network, 0);
      } else {
        assert.equal(flatten(root).some(e => e.tag === "form"), false);
        assert.match(root.textContent, /not configured|could not initialize/);
      }
      events.get("pagehide")();
    }
  } finally {
    for (const [key, descriptor] of saved) {
      if (descriptor) Object.defineProperty(globalThis, key, descriptor);
      else delete globalThis[key];
    }
  }
});

test("real client signs out from initial, edited and revoked-access screens", async () => {
  for (const scenario of ["initial", "edited", "revoked"]) {
    const requests = [];
    const json = data => new Response(JSON.stringify(data), {headers: {"Content-Type": "application/json"}});
    const actual = createChronosClient({basePath: "/csp/chronos", pageUrl: "https://chronos.example/ui",
      fetchImpl: (url, options) => {
        requests.push({url, options});
        if (url.endsWith("/session")) return json({code: scenario === "revoked" ? "ACCESS_REVOKED" : "CONNECTED",
          authenticated: true, csrf: "c".repeat(64), canRead: scenario !== "revoked", canApprove: false});
        if (url.endsWith("/decision")) return json(decision(JSON.parse(options.body).id));
        if (url.endsWith("/logout")) return json({code: "SESSION_ENDED"});
        throw new Error("Unexpected endpoint");
      }});
    const s = setup(actual);
    if (scenario === "edited") {
      s.input.value = "d1"; await s.form.dispatch("submit");
      s.input.value = "d2"; await s.input.dispatch("input");
    }
    const before = requests.length;
    await s.button("Sign out of IRIS").dispatch("click");
    assert.match(s.status.textContent, /confirmed that the session ended/);
    assert.deepEqual(requests.slice(before).map(r => [r.options.method, new URL(r.url).pathname]), [
      ["GET", "/csp/chronos/session"], ["POST", "/csp/chronos/logout"],
    ]);
    assert.equal(requests.at(-1).options.headers["X-Chronos-CSRF"], "c".repeat(64));
  }
});
test("failed session bootstrap during logout is explicitly unconfirmed and does not POST", async () => {
  const requests = [];
  const actual = createChronosClient({basePath: "/csp/chronos", pageUrl: "https://chronos.example/ui",
    fetchImpl: (url, options) => {requests.push({url, options}); return new Response("", {status: 401});}});
  const s = setup(actual);
  await s.button("Sign out of IRIS").dispatch("click");
  assert.match(s.status.textContent, /Session ending was not confirmed/);
  assert.deepEqual(requests.map(r => r.options.method), ["GET"]);
  assert.equal(s.result.textContent, "");
});

const detailFixture = () => JSON.parse(readFileSync(new URL("./fixtures/detail41.json", import.meta.url), "utf8")).cases[0].envelope;
function statusForDetail(e) {
  const reply = decision(e.data.decisionId);
  Object.assign(reply.data, {generation:e.data.generation, orderId:e.data.context.order_id,
    shipmentVersion:e.data.context.shipment_version, mode:e.data.context.trial_mode,
    outcome:{...e.data.outcome, dispatch_authorized:false}});
  return reply;
}
test("explicit details button renders complete sections without another effect", async () => {
  const e = detailFixture(), reads = [];
  const s = setup({readDecision:async()=>statusForDetail(e), readDecisionDetail:async id=>{reads.push(id);return e;}});
  assert.equal(s.button("Read historical details").disabled,true);
  s.input.value=e.data.decisionId;await s.form.dispatch("submit");
  assert.equal(reads.length,0);assert.equal(s.button("Read historical details").disabled,false);
  await s.button("Read historical details").dispatch("click");
  for (const label of ["Recorded proposal","Effect payload","Recorded alternatives","Source catalog","Counterfactual trial: opt-a"]) {
    assert.ok(s.result.textContent.includes(label));
  }
  assert.deepEqual(reads,[e.data.decisionId]);
  assert.equal(s.button("Read historical details").disabled,true);
  assert.equal(s.button("Query destination outcome").disabled,true);
  assert.equal(flatten(s.root).some(x=>["script","iframe","img","a"].includes(x.tag)),false);
});
test("editing during a detail read clears prior DOM and suppresses the late response", async () => {
  const e=detailFixture(),wait=deferred();let reads=0;
  const s=setup({readDecision:async()=>statusForDetail(e),readDecisionDetail:()=>{reads++;return wait.promise;}});
  s.input.value=e.data.decisionId;await s.form.dispatch("submit");
  const pending=s.button("Read historical details").dispatch("click");
  await s.button("Read historical details").dispatch("click");
  assert.equal(reads,1);assert.equal(s.result.textContent,"");
  s.input.value="other-decision";await s.input.dispatch("input");wait.resolve(e);await pending;
  assert.equal(s.result.textContent,"");assert.equal(s.button("Read historical details").disabled,true);
});
test("detail table renderer failure clears all partial and old results", async () => {
  const e=detailFixture(),s=setup({readDecision:async()=>statusForDetail(e),readDecisionDetail:async()=>e});
  s.input.value=e.data.decisionId;await s.form.dispatch("submit");
  s.document.failTag="table";
  await s.button("Read historical details").dispatch("click");
  assert.equal(s.result.textContent,"");assert.match(s.status.textContent,/could not be displayed/);
  assert.equal(s.button("Read historical details").disabled,true);
  assert.equal(s.button("Read existing result").disabled,true);
});
test("real client with mocked HTTP carries an explicit detail read through the full screen", async () => {
  const e=detailFixture(),requests=[];
  const json=value=>new Response(JSON.stringify(value),{headers:{"Content-Type":"application/json"}});
  const client=createChronosClient({pageUrl:"https://chronos.example/ui",basePath:"/csp/chronos",
    fetchImpl:async(url,options)=>{
      requests.push([url,options]);
      if(url.endsWith("/session"))return json({code:"CONNECTED",authenticated:true,csrf:"a".repeat(64),canRead:true,canApprove:false});
      const body=JSON.parse(options.body);
      if(body.command==="DECISION")return json(statusForDetail(e));
      if(body.command==="DECISION_DETAIL")return json(e);
      throw Error("unexpected mutation");
    }});
  const document={createElement(tag){return new Element(tag,this);}},root=new Element("div",document);
  const screen=mountResultScreen(root,{client,evidence:"LOCAL_FIXTURE"});
  const input=find(root,x=>x.tag==="input"),form=find(root,x=>x.tag==="form");
  input.value=e.data.decisionId;await form.dispatch("submit");
  await find(root,x=>x.tag==="button"&&x.textContent==="Read historical details").dispatch("click");
  assert.match(root.textContent,/Historical recovery proposal/);
  assert.deepEqual(requests.slice(1).map(x=>JSON.parse(x[1].body).command),["DECISION","DECISION_DETAIL"]);
  assert.equal(requests.length,3);screen.destroy();
});


test("current operation selection displays the exact reference and keeps query separate",async()=>{
  const op={code:"READ_ONLY",operationId:"op114",attemptId:"a114",state:"UNKNOWN",reference:"",quarantined:false,dispatchGranted:false};
  let reads=0,queries=[];
  const s=setup({
    readDecisionOperation:async id=>{reads++;return {code:"DECISION_OPERATION_RECORDED",data:{code:"DECISION_OPERATION_RECORDED",dispatchGranted:false,decisionId:id,orderId:"order-1",shipmentVersion:1,operation:op}};},
    readOperation:async id=>({code:"READ_ONLY",data:{...op,operationId:id}}),
    reconcileOperation:async id=>{queries.push(id);return {code:"RESULT_UNCERTAIN",data:{...op,code:"RESULT_UNCERTAIN",operationId:id}};}
  });
  s.input.value="d1";await s.form.dispatch("submit");
  assert.equal(s.button("Read current shipment operation").disabled,false);
  assert.equal(s.button("Query destination outcome").disabled,true);
  await s.button("Read current shipment operation").dispatch("click");
  assert.equal(reads,1);assert.deepEqual(queries,[]);
  assert.equal(s.kind.value,"operation");assert.equal(s.input.value,"op114");
  assert.match(s.result.textContent,/not the historical outcome/);
  await s.button("Query destination outcome").dispatch("click");
  assert.deepEqual(queries,["op114"]);assert.match(s.result.textContent,/outcome unknown/);
  s.input.value="other";await s.input.dispatch("input");
  assert.equal(s.button("Query destination outcome").disabled,true);s.screen.destroy();
});


test("workspace navigation only focuses its local section and never calls a service",async()=>{
  const s=setup();
  const history=find(s.root,e=>e.tag==="button"&&e.attrs["aria-label"]==="History");
  await history.dispatch("click");
  assert.equal(s.document.focused.attrs["aria-label"],"Saved references");
  assert.deepEqual(s.calls,[]);
  const cases=find(s.root,e=>e.tag==="button"&&e.attrs["aria-label"]==="Cases");
  await cases.dispatch("click");assert.equal(s.document.focused,s.form);assert.deepEqual(s.calls,[]);
  assert.match(s.root.textContent,/Workflow|Proposal/);
});
