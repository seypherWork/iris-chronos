import test from "node:test";
import assert from "node:assert/strict";
import {createChronosClient} from "../../src/chronos_web/client.mjs";
import {createSessionRecoveryReferences} from "../../src/chronos_web/session-references.mjs";
import {createResultController} from "../../src/chronos_web/controller.mjs";
import {mountResultScreen} from "../../src/chronos_web/screen.mjs";

const base = "https://chronos.example/csp/chronos/";
const identity = letter => ({version: 1, available: true, actor: "principal-" + letter.repeat(64),
  actorScope: letter.repeat(64), applicationUrl: base});
const response = data => new Response(JSON.stringify(data), {headers: {"Content-Type": "application/json"}});
const decision = id => ({code: "EXISTING_DECISION", traceSessionId: 1, data: {
  code: "EXISTING_DECISION", requestId: id, orderId: "order-1", shipmentVersion: 1,
  mode: "WITH_TRIALS", generation: "g1", state: "COMPLETED", deadlineUS: 1793296800000000,
  dispatchGranted: false, inferenceGranted: false, dispatch_authorized: false,
  outcome: {status: "VALIDATED_HOLD", dispatch_authorized: false},
}});
const deferred = () => {let resolve; const promise = new Promise(r => {resolve = r;}); return {promise, resolve};};
function memory() {
  const data = new Map(); let reads = 0, writes = 0;
  return {data, get reads() {return reads;}, get writes() {return writes;},
    getItem(key) {reads++; return data.get(key) ?? null;},
    setItem(key, value) {writes++; data.set(key, value);},
    clear() {throw Error("never clear unrelated storage");}};
}
function setup({storage = memory(), onChange = () => {}, timeoutMs = 250} = {}) {
  const wire = {calls: [], metadata: identity("a"), canRead: true, hook: null};
  const client = createChronosClient({pageUrl: base + "web", basePath: "/csp/chronos", timeoutMs,
    fetchImpl: async (url, options) => {
      wire.calls.push({url, options});
      if (wire.hook) {const value = wire.hook(url, options); if (value) return value;}
      if (url.endsWith("/session")) return response({code: wire.canRead ? "CONNECTED" : "ACCESS_REVOKED",
        authenticated: true, csrf: "c".repeat(64), canRead: wire.canRead, canApprove: false,
        identity: wire.canRead ? wire.metadata : {version: 1, available: false}});
      if (url.endsWith("/logout")) return response({code: "SESSION_ENDED"});
      const body = JSON.parse(options.body);
      assert.equal(body.command, "DECISION", "recovery must not submit a mutation");
      return response(decision(body.id));
    }});
  const references = createSessionRecoveryReferences({client, storage});
  const controller = createResultController({client, references, onChange, evidence: "LOCAL_FIXTURE"});
  return {wire, client, references, controller, storage};
}
const ref = id => ({kind: "decision", id});
const posts = wire => wire.calls.filter(c => c.options.method === "POST");

test("construction touches neither storage nor server; load only bootstraps and lists", async () => {
  const s = setup();
  assert.equal(s.wire.calls.length, 0); assert.equal(s.storage.reads, 0);
  await s.controller.loadReferences();
  assert.equal(s.controller.snapshot().phase, "REFERENCES_READY");
  assert.deepEqual(s.controller.snapshot().savedReferences, []);
  assert.equal(s.wire.calls.length, 1);
  assert.equal(posts(s.wire).length, 0); assert.equal(s.storage.writes, 0);
});

test("manual verified lookup saves IDs; reconstructed controller reopens with fresh read only", async () => {
  const s = setup();
  await s.controller.select("decision", "original");
  assert.deepEqual(s.controller.snapshot().savedReferences, [ref("original")]);
  assert.match([...s.storage.data.values()][0], /original/);
  s.controller.disconnect();
  assert.deepEqual(s.controller.snapshot().savedReferences, []);
  const next = setup({storage: s.storage});
  await next.controller.loadReferences();
  assert.deepEqual(next.controller.snapshot().savedReferences, [ref("original")]);
  await next.controller.reopenReference(0);
  assert.equal(next.controller.snapshot().selection.id, "original");
  assert.deepEqual(posts(next.wire).map(c => JSON.parse(c.options.body)), [{command: "DECISION", id: "original"}]);
  assert.equal(next.wire.calls.filter(c => c.url.endsWith("session")).length, 2);
});

test("account or installation changed after display blocks old ID before any read", async () => {
  for (const metadata of [identity("b"), {...identity("a"), actorScope: "b".repeat(64)},
    {...identity("a"), actor: "principal-" + "b".repeat(64)}]) {
    const s = setup(); await s.controller.select("decision", "private-reference");
    const before = posts(s.wire).length, writes = s.storage.writes;
    s.wire.metadata = metadata;
    await s.controller.reopenReference(0);
    assert.equal(s.controller.snapshot().code, "REFERENCE_SCOPE_CHANGED");
    assert.equal(s.controller.snapshot().selection, null);
    assert.deepEqual(s.controller.snapshot().savedReferences, []);
    assert.equal(posts(s.wire).length, before);
    assert.equal(s.storage.writes, writes);
    assert.equal(JSON.stringify(s.controller.snapshot()).includes("private-reference"), false);
  }
});

test("forget reconnects to same scope and changes only selected local ID, never IRIS history", async () => {
  const s = setup(); await s.controller.select("decision", "one");
  await s.controller.select("decision", "two");
  s.storage.data.set("unrelated", "preserve");
  const before = posts(s.wire).length;
  await s.controller.forgetReference(0);
  assert.deepEqual(s.controller.snapshot().savedReferences, [ref("two")]);
  assert.equal(s.controller.snapshot().referenceStatus, "REFERENCE_FORGOTTEN");
  assert.equal(posts(s.wire).length, before);
  assert.equal(s.storage.data.get("unrelated"), "preserve");
});

test("account change before forgetting leaves all storage unchanged", async () => {
  const s = setup(); await s.controller.select("decision", "keep");
  const before = [...s.storage.data];
  s.wire.metadata = identity("b");
  await s.controller.forgetReference(0);
  assert.equal(s.controller.snapshot().code, "REFERENCE_SCOPE_CHANGED");
  assert.deepEqual([...s.storage.data], before);
  assert.deepEqual(s.controller.snapshot().savedReferences, []);
});

test("logout and permission revocation clear displayed IDs but preserve recovery storage", async () => {
  for (const action of ["logout", "revoke"]) {
    const s = setup(); await s.controller.select("decision", "keep");
    const before = [...s.storage.data];
    if (action === "logout") await s.controller.logout();
    else {s.wire.canRead = false; await s.controller.loadReferences();}
    assert.deepEqual(s.controller.snapshot().savedReferences, []);
    assert.deepEqual([...s.storage.data], before);
  }
});

test("legacy unavailable identity never reads browser storage or fabricates recovery", async () => {
  const s = setup(); s.wire.metadata = {version: 1, available: false};
  await s.controller.loadReferences();
  assert.equal(s.controller.snapshot().code, "RECOVERY_UNAVAILABLE");
  assert.equal(s.storage.reads, 0); assert.equal(s.storage.writes, 0);
  await s.controller.select("decision", "manual");
  assert.equal(s.controller.snapshot().view.available, true);
  assert.equal(s.controller.snapshot().referenceStatus, "REFERENCE_NOT_SAVED");
  assert.equal(s.storage.writes, 0);
});

test("corrupt and unavailable storage preserve original bytes and expose no raw exceptions", async () => {
  const s = setup(); await s.controller.select("decision", "keep");
  const key = [...s.storage.data.keys()][0]; s.storage.data.set(key, "CORRUPT_PRIVATE_BYTES");
  const before = s.storage.writes;
  await s.controller.loadReferences();
  assert.equal(s.controller.snapshot().referenceStatus, "REFERENCE_STORE_INVALID");
  assert.equal(s.storage.data.get(key), "CORRUPT_PRIVATE_BYTES");
  assert.equal(s.storage.writes, before);
  assert.equal(JSON.stringify(s.controller.snapshot()).includes("CORRUPT_PRIVATE"), false);
  s.storage.getItem = () => {throw Error("PRIVATE_STORAGE_ERROR");};
  await s.controller.loadReferences();
  assert.equal(s.controller.snapshot().referenceStatus, "STORAGE_UNAVAILABLE");
  assert.equal(JSON.stringify(s.controller.snapshot()).includes("PRIVATE_STORAGE_ERROR"), false);
});

test("a full store does not evict an unresolved ID or claim the new one was saved", async () => {
  const s = setup(); await s.client.connect();
  for (let i = 0; i < 32; i++) assert.equal(s.references.remember(ref("old-" + i)).ok, true);
  const writes = s.storage.writes;
  await s.controller.select("decision", "new");
  assert.equal(s.controller.snapshot().referenceStatus, "REFERENCE_NOT_SAVED");
  assert.equal(s.controller.snapshot().savedReferences.length, 32);
  assert.equal(s.storage.writes, writes);
});

test("session changes during getItem prevent stale listing and pre-write mutation", async () => {
  const s = setup(); await s.client.connect();
  s.references.remember(ref("one"));
  const original = s.storage.getItem.bind(s.storage), before = s.storage.writes;
  s.storage.getItem = key => {const value = original(key); s.client.disconnect(); return value;};
  assert.equal(s.references.list().code, "REFERENCE_SCOPE_CHANGED");
  await s.client.connect();
  assert.equal(s.references.remember(ref("two")).code, "REFERENCE_SCOPE_CHANGED");
  assert.equal(s.storage.writes, before);
});

test("identity change after setItem is uncertain, never falsely claimed not written", async () => {
  const s = setup(); await s.client.connect();
  const original = s.storage.setItem.bind(s.storage);
  s.storage.setItem = (key, value) => {original(key, value); s.client.disconnect();};
  const result = s.references.remember(ref("may-be-saved"));
  assert.equal(result.ok, false);
  assert.equal(result.code, "REFERENCE_SCOPE_CHANGED");
  assert.equal([...s.storage.data.values()][0].includes("may-be-saved"), true);
  assert.deepEqual(result.items, []);
});

test("list response after disconnect cannot restore old visible references", async () => {
  const s = setup(); await s.controller.select("decision", "one");
  const pending = deferred();
  s.wire.hook = url => url.endsWith("session") ? pending.promise : null;
  const running = s.controller.loadReferences();
  s.controller.disconnect();
  pending.resolve(response({code: "CONNECTED", authenticated: true, canRead: true, canApprove: false,
    csrf: "c".repeat(64), identity: identity("a")}));
  await running;
  assert.equal(s.controller.snapshot().phase, "DISCONNECTED");
  assert.deepEqual(s.controller.snapshot().savedReferences, []);
});

test("lost reopened read does not erase the reference or send another command", async () => {
  const s = setup({timeoutMs: 10}); await s.controller.select("decision", "keep");
  const before = posts(s.wire).length;
  s.wire.hook = url => url.endsWith("decision") ? new Promise(() => {}) : null;
  await s.controller.reopenReference(0);
  assert.equal(s.controller.snapshot().code, "REQUEST_TIMEOUT");
  assert.equal(posts(s.wire).length, before + 1);
  assert.equal([...s.storage.data.values()][0].includes("keep"), true);
});

class Element {
  constructor(tag, doc) {this.tag=tag;this.ownerDocument=doc;this.children=[];this.attrs={};this.listeners=new Map();this.value="";this._text="";}
  set textContent(v) {this._text=String(v);this.children=[];}
  get textContent() {return this._text+this.children.map(c=>c.textContent).join("");}
  set innerHTML(_) {throw Error("HTML forbidden");}
  appendChild(child) {this.children.push(child);return child;}
  replaceChildren(...children) {this.children=children;this._text="";}
  setAttribute(k,v) {this.attrs[k]=v;}
  addEventListener(k,fn) {if(!this.listeners.has(k))this.listeners.set(k,[]);this.listeners.get(k).push(fn);}
  removeEventListener(k,fn) {this.listeners.set(k,(this.listeners.get(k)??[]).filter(x=>x!==fn));}
  focus() {}
  async dispatch(k) {for(const fn of this.listeners.get(k)??[])await fn({preventDefault(){}});}
}
const flatten = root => [root,...root.children.flatMap(flatten)];
function screen(s) {
  const document = {failTag: null, createElement(tag) {
    if(this.failTag===tag){this.failTag=null;throw Error("RENDER_PRIVATE");}return new Element(tag,this);}};
  const root = new Element("div",document);
  const mounted = mountResultScreen(root,{client:s.client,storage:s.storage,evidence:"LOCAL_FIXTURE"});
  const find = f=>flatten(root).find(f);
  return {root,document,mounted,button:label=>find(e=>e.tag==="button"&&e.textContent===label),
    saved:find(e=>e.attrs["aria-label"]==="Saved reference"),input:find(e=>e.tag==="input"),
    form:find(e=>e.tag==="form"),result:find(e=>e.attrs["aria-label"]==="Current result")};
}

test("screen supports explicit load/reopen after remount, with no automatic read or mutation", async () => {
  const s = setup(), first = screen(s);
  assert.equal(s.wire.calls.length,0);assert.equal(s.storage.reads,0);
  first.input.value="screen-id";await first.form.dispatch("submit");
  assert.equal(first.saved.value,"0");
  assert.equal(first.button("Reopen saved result").disabled,false);
  first.mounted.destroy();
  const second = screen(s), before=s.wire.calls.length;
  assert.equal(s.wire.calls.length,before);
  await second.button("Load saved references").dispatch("click");
  assert.match(second.saved.textContent,/screen-id/);
  assert.equal(second.saved.value,"0");
  await second.button("Reopen saved result").dispatch("click");
  assert.match(second.result.textContent,/screen-id/);
  const count=posts(s.wire).length;
  await second.button("Remove bookmark").dispatch("click");
  assert.equal(second.saved.children.length,0);
  assert.equal(posts(s.wire).length,count);
  assert.match(second.root.textContent,/selected local bookmark was removed/);
});

test("screen clears previous user's list on changed account and does not read its ID", async () => {
  const s=setup(), ui=screen(s);ui.input.value="account-a";await ui.form.dispatch("submit");
  const before=posts(s.wire).length;s.wire.metadata=identity("b");
  await ui.button("Reopen saved result").dispatch("click");
  assert.equal(posts(s.wire).length,before);
  assert.equal(ui.saved.children.length,0);
  assert.equal(ui.result.textContent,"");
  assert.match(ui.root.textContent,/account or installation changed/);
});

test("failed option rendering clears partial saved IDs and old result content", async () => {
  const s=setup(), ui=screen(s);ui.input.value="first";await ui.form.dispatch("submit");
  ui.document.failTag="option";
  await ui.button("Load saved references").dispatch("click");
  assert.equal(ui.saved.textContent,"");assert.equal(ui.result.textContent,"");
  assert.equal(ui.button("Reopen saved result").disabled,true);
  assert.equal(ui.root.textContent.includes("RENDER_PRIVATE"),false);
});

test("storage absent keeps manual reads usable and disables load controls", async () => {
  const s=setup();s.storage=null;const ui=screen(s);
  assert.equal(ui.button("Load saved references").disabled,true);
  ui.input.value="manual";await ui.form.dispatch("submit");
  assert.match(ui.result.textContent,/manual/);
});

test("boot with blocked sessionStorage still mounts manual-read screen without network", async () => {
  const names=["document","location","addEventListener","fetch","sessionStorage"];
  const prior=new Map(names.map(k=>[k,Object.getOwnPropertyDescriptor(globalThis,k)]));
  let mountedEvents;
  try {
    for(const [name,available] of [["blocked",false],["enabled",true]]) {
      const s=setup(), doc={createElement:tag=>new Element(tag,doc)}, root=new Element("div",doc);
      doc.getElementById=()=>root;doc.querySelector=()=>({content:"/csp/chronos"});
      mountedEvents=new Map();
      Object.defineProperty(globalThis,"document",{configurable:true,value:doc});
      Object.defineProperty(globalThis,"location",{configurable:true,value:{href:base+"web"}});
      Object.defineProperty(globalThis,"addEventListener",{configurable:true,value:(k,fn)=>mountedEvents.set(k,fn)});
      let calls=0;
      Object.defineProperty(globalThis,"fetch",{configurable:true,value:()=>{calls++;throw Error("NETWORK_FORBIDDEN");}});
      Object.defineProperty(globalThis,"sessionStorage",{configurable:true,get(){
        if(!available)throw Error("STORAGE_PRIVATE_BLOCKED");return s.storage;
      }});
      await import("../../src/chronos_web/boot.mjs?session-recovery44="+name);
      assert.match(root.textContent,/Disconnected/);
      assert.equal(root.textContent.includes("STORAGE_PRIVATE_BLOCKED"),false);
      const load=flatten(root).find(e=>e.tag==="button"&&e.textContent==="Load saved references");
      assert.equal(load.disabled,!available);
      assert.equal(s.storage.reads,0);assert.equal(s.storage.writes,0);assert.equal(calls,0);
      mountedEvents.get("pagehide")();assert.equal(root.textContent,"");
      mountedEvents.get("pageshow")({persisted:true});
      assert.match(root.textContent,/Disconnected/);
      assert.equal(s.storage.reads,0);assert.equal(calls,0);
      mountedEvents.get("pagehide")();
    }
  } finally {
    for(const [key,descriptor] of prior) {
      if(descriptor)Object.defineProperty(globalThis,key,descriptor);else delete globalThis[key];
    }
  }
});

test("a business-level detail rejection hides prior saved IDs without deleting recovery data", async () => {
  const s=setup();await s.controller.select("decision","keep");
  const before=[...s.storage.data];
  s.wire.hook=(url,options)=>url.endsWith("decision")&&JSON.parse(options.body).command==="DECISION_DETAIL" ?
    response({code:"RECHECK_REQUIRED",traceSessionId:2,data:{code:"RECHECK_REQUIRED",dispatchGranted:false}}):null;
  await s.controller.readSelectedDetail();
  assert.equal(s.controller.snapshot().phase,"ERROR");
  assert.deepEqual(s.controller.snapshot().savedReferences,[]);
  assert.deepEqual([...s.storage.data],before);
});

test("screen removes saved options after business-level detail denial", async () => {
  const s=setup(),ui=screen(s);ui.input.value="keep";await ui.form.dispatch("submit");
  s.wire.hook=(url,options)=>url.endsWith("decision")&&JSON.parse(options.body).command==="DECISION_DETAIL" ?
    response({code:"RECHECK_REQUIRED",traceSessionId:2,data:{code:"RECHECK_REQUIRED",dispatchGranted:false}}):null;
  await ui.button("Read historical details").dispatch("click");
  assert.equal(ui.saved.textContent,"");
  assert.equal(ui.button("Reopen saved result").disabled,true);
  assert.equal([...s.storage.data.values()][0].includes("keep"),true);
});

test("a rejected reconciliation clears saved preview IDs without removing their bookmarks", async () => {
  const s=setup();
  const t=5864205600;
  const p={code:"READ_ONLY",traceSessionId:1,data:{
    code:"READ_ONLY",dispatchGranted:false,previewId:"p1",state:"CONFIRMED",decisionId:"d1",
    decisionDigest:"a".repeat(64),orderId:"o1",shipmentVersion:1,operationId:"op1",
    actor:"fixture",generation:"g1",snapshotId:2,option:"FAILOVER_B",target:"B",
    createdAt:t,expiresAt:t+60,reviewDeadlineUS:1793297100000000,predictedArrival:t+120,
    snapshot:{orderId:"o1",shipmentVersion:1,revision:1,policyRevision:1,quantity:1,payload:"synthetic",
      maxCost:8,observedAt:t,inventoryUntil:t+300,deliveryDeadline:t+600,
      offers:Object.fromEntries(["A","B"].map(target=>[target,{target,cost:2,availableAt:t,
        queueSeconds:0,travelSeconds:120,validUntil:t+300,capacity:2}]))}
  }};
  s.wire.hook=(url,options)=>{
    if(!url.endsWith("approval"))return null;
    const command=JSON.parse(options.body).command;
    return response(command==="READ"?p:{code:"RECHECK_REQUIRED",traceSessionId:2,
      data:{code:"RECHECK_REQUIRED",dispatchGranted:false}});
  };
  await s.controller.select("preview","p1");
  assert.equal(s.controller.canReconcile(),true);
  assert.equal(s.controller.snapshot().savedReferences.length,1);
  const before=[...s.storage.data];
  await s.controller.reconcileSelected();
  assert.equal(s.controller.snapshot().phase,"ERROR");
  assert.deepEqual(s.controller.snapshot().savedReferences,[]);
  assert.deepEqual([...s.storage.data],before);
});
