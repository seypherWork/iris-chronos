import test from "node:test";
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {decisionDetailView} from "../../src/chronos_web/detail.mjs";
import {renderResult} from "../../src/chronos_web/render.mjs";
import {createResultController} from "../../src/chronos_web/controller.mjs";
import {ChronosClientError} from "../../src/chronos_web/client.mjs";
const fixtures=JSON.parse(readFileSync(new URL("./fixtures/detail41.json",import.meta.url),"utf8"));
const sample=(name="proposal")=>structuredClone(fixtures.cases.find(c=>c.name===name).envelope);
const context=e=>({expectedId:e.data.decisionId,evidence:"LOCAL_FIXTURE"});
const dump=v=>JSON.stringify(v);
const project=e=>decisionDetailView(e,context(e));
const deferred=()=>{let resolve,reject;const promise=new Promise((r,j)=>{resolve=r;reject=j;});return{promise,resolve,reject};};

test("all Python public projection fixtures display with provenance and no authority",()=>{
  for(const f of fixtures.cases){
    const view=project(f.envelope);
    assert.equal(view.available,true,f.name);
    assert.equal(view.canConfirm,false);assert.notEqual(view.tone,"success");
    assert.equal(view.evidenceLabel,"Local fixture — no IRIS execution");
    assert.ok(Object.isFrozen(view)&&Object.isFrozen(view.sections)&&Object.isFrozen(view.sections[0].rows));
    assert.match(view.summary,/not current authorization/);
  }
});
test("full payload, constraints, sources and both counterfactual branches remain visible",()=>{
  const e=sample(),view=project(e),text=dump(view);
  for(const key of ["Effect payload","Recorded alternatives","Destination evidence","Source catalog","Counterfactual trial: opt-a","Counterfactual trial: opt-b"]) assert.ok(text.includes(key));
  const payload=view.sections.find(s=>s.title==="Effect payload").rows[0].value;
  assert.deepEqual(JSON.parse(payload),e.data.context.facts.payload);
  assert.match(text,/Simulated state/);assert.match(text,/not deliveries/);
  assert.equal(view.sections.find(s=>s.title==="Recorded alternatives").table.rows.length,2);
});
test("HOLD and ablation do not invent actions, alternatives trials or approval",()=>{
  const hold=project(sample("hold"));assert.equal(hold.title,"Historical HOLD decision");
  assert.match(dump(hold),/None — HOLD/);assert.match(dump(hold),/Which delivery constraint applies/);
  const without=project(sample("ablation"));
  assert.equal(without.sections.some(s=>s.title.startsWith("Counterfactual trial:")),false);
  assert.match(dump(without),/Trials were not requested/);
});
test("messages retain current, other and unresolved provenance and citation links",()=>{
  const text=dump(project(sample("messages-and-hostile-text")));
  for(const word of ["VERIFIED_CURRENT","VERIFIED_OTHER","UNRESOLVED","m:verified_current","cited by proposal"])assert.ok(text.includes(word));
});
test("large payload is not truncated and later response mutations cannot change display",()=>{
  const e=sample("large-payload"),view=project(e);
  assert.equal(JSON.parse(view.sections.find(s=>s.title==="Effect payload").rows[0].value).description.length,55000);
  e.data.context.facts.payload.description="mutated";assert.equal(dump(view).includes("mutated"),false);
});
test("wrong envelope, identity, authority flags and types fail without exposing partial values",()=>{
  const mutate=[
    e=>e.code="EXISTING_DECISION",e=>e.data.decisionId="other",e=>e.data.context.context_id="other",
    e=>e.data.proposal.context_digest="b".repeat(64),e=>e.data.canConfirm=true,
    e=>e.data.dispatchGranted=0,e=>e.data.currentAuthorityVerified=true,e=>e.data.historical=false,
    e=>e.data.proposal.shipment_version="1",e=>e.data.completedUS=Infinity,
    e=>e.data.proposal.rationale=" ",e=>e.data.context.ticks_per_minute=60000,
    e=>e.data.context.facts.budget=-1,e=>e.data.schema="future",e=>e.data.outcome.status="ERROR",
  ];
  for(const change of mutate){const e=sample();const c=context(e);change(e);const v=decisionDetailView(e,c);assert.equal(v.available,false);assert.deepEqual(v.sections,[]);}
});
test("same decision with changed generation/order/outcome is not silently combined",()=>{
  const e=sample(),c=context(e);
  for(const wrong of [{expectedGeneration:"wrong"},{expectedOrder:"wrong"},{expectedShipmentVersion:999},{expectedOutcome:"VALIDATED_HOLD"}]){
    assert.equal(decisionDetailView(e,{...c,...wrong}).available,false);
  }
});
test("unknown private fields anywhere in the fixed schema are never displayed",()=>{
  for(const path of [[],["context"],["proposal"],["outcome"],["context","facts"],["context","facts","options","A"],["context","trials",0,"observations"]]){
    const e=sample();let at=e.data;for(const key of path)at=at[key];at.claimId="PRIVATE_SENTINEL";
    const v=project(e);assert.equal(v.available,false);assert.equal(dump(v).includes("PRIVATE_SENTINEL"),false);
  }
});
test("known credential keys and credential-shaped strings fail closed",()=>{
  for(const mode of ["key","rationale","message"]){
    const e=sample("messages-and-hostile-text");
    if(mode==="key")e.data.context.facts.payload.client_secret="PRIVATE_SENTINEL";
    if(mode==="rationale")e.data.proposal.rationale="password=PRIVATE_SENTINEL";
    if(mode==="message")e.data.context.facts.messages[0].text="authorization: Bearer PRIVATE_SENTINEL";
    const v=project(e);assert.equal(v.available,false);assert.equal(dump(v).includes("PRIVATE_SENTINEL"),false);
  }
});
test("missing/duplicate sources, branch mismatch and future observations are rejected",()=>{
  const changes=[
    e=>e.data.proposal.source_ids=["missing"],e=>e.data.proposal.source_ids.push(e.data.proposal.source_ids[0]),
    e=>e.data.context.source_catalog.push(e.data.context.source_catalog[0]),
    e=>e.data.context.trials[0].observations.action="FAILOVER_B",
    e=>e.data.context.trials[0].trial_id="trial:foreign",
    e=>e.data.context.facts.messages[0].at=e.data.context.observed_at+1,
    e=>e.data.context.source_catalog[0].kind="message",
    e=>e.data.context.trials.pop(),
  ];
  for(const mutate of changes){const e=sample("messages-and-hostile-text");mutate(e);assert.equal(project(e).available,false);}
});
test("payload prototype-looking keys remain inert JSON and deep/oversize payloads are rejected",()=>{
  const e=sample();e.data.context.facts.payload=JSON.parse('{"quantity":1,"__proto__":{"note":"ordinary data"}}');
  e.data.payloadJSON=JSON.stringify(e.data.context.facts.payload);
  assert.equal(project(e).available,true);assert.equal({}.note,undefined);
  let node=e.data.context.facts.payload;for(let i=0;i<15;i++){node.child={};node=node.child;}
  assert.equal(project(e).available,false);
});
test("clock sums cannot overflow or fabricate dates",()=>{
  const e=sample();e.data.context.utc_origin_us=Number.MAX_SAFE_INTEGER;
  assert.equal(project(e).available,false);
});
class Element{
  constructor(tag,doc){this.tag=tag;this.ownerDocument=doc;this.children=[];this.attrs={};this._text="";}
  set textContent(x){this._text=String(x);this.children=[];}get textContent(){return this._text+this.children.map(x=>x.textContent).join("");}
  set innerHTML(x){throw new Error("HTML forbidden");}
  appendChild(x){this.children.push(x);return x;}replaceChildren(...xs){this.children=xs;}
  setAttribute(k,v){this.attrs[k]=v;}
}
test("detail renderer emits inert text, table headings and simulated events, never links/scripts",()=>{
  const tags=[];const doc={createElement(tag){tags.push(tag);return new Element(tag,this);}};
  const root=new Element("main",doc),e=sample("messages-and-hostile-text");
  const v=renderResult(root,"detail",e,context(e));assert.equal(v.available,true);
  assert.match(root.textContent,/<img src=x onerror=/);assert.match(root.textContent,/<script>inert sentinel/);
  assert.ok(tags.includes("table")&&tags.includes("th")&&tags.includes("caption"));
  for(const forbidden of ["script","img","a","iframe","input","button"])assert.equal(tags.includes(forbidden),false);
});
function controllerFixture(overrides={}){
  const e=sample(),id=e.data.decisionId,calls=[];
  const client={
    connect:async()=>({connected:true,canRead:true,canApprove:false}),disconnect:()=>calls.push("disconnect"),
    readDecision:async()=>({code:"EXISTING_DECISION",data:{code:"EXISTING_DECISION",dispatchGranted:false,inferenceGranted:false,dispatch_authorized:false,
      requestId:id,orderId:e.data.context.order_id,shipmentVersion:e.data.context.shipment_version,generation:e.data.generation,
      deadlineUS:e.data.completedUS+1000000,mode:e.data.context.trial_mode,state:"COMPLETED",
      outcome:{...e.data.outcome,dispatch_authorized:false}}}),
    readDecisionDetail:async ref=>{calls.push(["detail",ref]);return e;},
    readPreview:async()=>{throw Error("not used");},reconcilePreview:async()=>{throw Error("not used");},
    logout:async()=>({code:"SESSION_ENDED"}),...overrides,
  };
  const changes=[];const controller=createResultController({client,evidence:"LOCAL_FIXTURE",onChange:s=>changes.push(s)});
  return{controller,e,id,calls,changes,client};
}
test("detail requires a completed selected decision and is an explicit one-shot read",async()=>{
  const f=controllerFixture();
  await assert.rejects(f.controller.readSelectedDetail(),/COMPLETED_DECISION_REQUIRED/);
  await f.controller.select("decision",f.id);assert.equal(f.controller.canReadDetail(),true);
  assert.equal(f.calls.some(x=>Array.isArray(x)),false);
  await f.controller.readSelectedDetail();assert.equal(f.controller.snapshot().view.kind,"detail");
  assert.equal(f.controller.canReadDetail(),false);assert.equal(f.controller.snapshot().view.canConfirm,false);
  assert.equal(f.calls.filter(Array.isArray).length,1);
  await assert.rejects(f.controller.readSelectedDetail(),/COMPLETED_DECISION_REQUIRED/);
});
test("disconnect suppresses a late historical response and does not remember its contents",async()=>{
  const wait=deferred(),f=controllerFixture({readDecisionDetail:()=>wait.promise});
  await f.controller.select("decision",f.id);const pending=f.controller.readSelectedDetail();
  assert.equal(f.controller.snapshot().view,null);
  f.controller.disconnect();wait.resolve(f.e);await pending;
  assert.equal(f.controller.snapshot().phase,"DISCONNECTED");assert.equal(f.controller.snapshot().view,null);
});
test("changed session/generation response does not replace the selected decision",async()=>{
  const f=controllerFixture();await f.controller.select("decision",f.id);
  f.e.data.generation="different-runtime";await f.controller.readSelectedDetail();
  assert.equal(f.controller.snapshot().phase,"ERROR");assert.equal(f.controller.snapshot().view.available,false);
});
test("detail permission loss hides the original proposal and cannot dispatch/retry",async()=>{
  const f=controllerFixture({readDecisionDetail:async()=>{throw new ChronosClientError("PERMISSION_DENIED");}});
  await f.controller.select("decision",f.id);await f.controller.readSelectedDetail();
  assert.equal(f.controller.snapshot().phase,"ERROR");assert.equal(f.controller.snapshot().view,null);
  assert.equal(f.controller.canReadDetail(),false);assert.equal(f.controller.canReconcile(),false);
});
test("a reentrant disconnect at detail LOADING prevents making the request",async()=>{
  const f=controllerFixture();let controller;
  controller=createResultController({client:f.client,onChange:s=>{if(s.phase==="LOADING"&&s.view===null&&controller?.canReadDetail()===false&&armed)controller.disconnect();}});
  let armed=false;await controller.select("decision",f.id);armed=true;
  await controller.readSelectedDetail();assert.equal(f.calls.filter(Array.isArray).length,0);
  assert.equal(controller.snapshot().phase,"DISCONNECTED");
});

test("credential-shaped multiline text does not enter the display",()=>{
  for(const value of ["password"+String.fromCharCode(10)+"=PRIVATE_SENTINEL",
    "authorization:"+String.fromCharCode(10)+"Bearer PRIVATE_SENTINEL"]){
    const e=sample();e.data.proposal.rationale=value;
    const view=project(e);assert.equal(view.available,false);
    assert.equal(dump(view).includes("PRIVATE_SENTINEL"),false);
  }
});
test("finite floating business values retain the server's exact JSON spelling",()=>{
  const e=sample("finite-floats"),v=project(e);assert.equal(v.available,true);
  const raw=v.sections.find(s=>s.title==="Effect payload").rows[0].value;
  assert.equal(raw,e.data.payloadJSON);assert.match(raw,/1e\+20/);assert.match(raw,/1\.25e-20/);
});
test("inconsistent payload serialization cannot silently replace historical values",()=>{
  const e=sample();e.data.payloadJSON='{"quantity":999}';
  assert.equal(project(e).available,false);
});

const asE1=e=>{e.data.schema="chronos.review-detail.v2";e.data.attribution={responseContract:"chronos.preference-extraction.v1",interpretationOrigin:"MODEL",selectionOrigin:"DETERMINISTIC_CODE"};return e;};
test("E1 explains model versus code and keeps historical evidence separate from authority",()=>{
  const e=asE1(sample()),v=project(e);assert.equal(v.available,true);assert.equal(v.canConfirm,false);
  const a=v.sections.find(s=>s.title==="How this proposal was produced");
  assert.match(dump(a),/Deterministic code/);assert.match(dump(a),/Model/);
  assert.match(a.note,/not a verbatim model transcript/);
  assert.equal(v.sections.find(s=>s.title==="Recorded proposal").rows.find(r=>r.label==="Action").value,e.data.proposal.action);
  const hold=project(asE1(sample("hold")));assert.equal(hold.available,true);assert.equal(hold.canConfirm,false);
});
test("legacy detail and current A1 never invent explicit E1 attribution",()=>{
  const old=sample(),current=sample();current.data.schema="chronos.review-detail.v2";
  current.data.attribution={responseContract:"chronos.agent-proposal.v2",interpretationOrigin:"NOT_RECORDED",selectionOrigin:"NOT_RECORDED"};
  for(const e of [old,current]){const v=project(e);assert.equal(v.available,true);assert.match(dump(v.sections[0]),/Not recorded/);assert.doesNotMatch(dump(v.sections[0]),/Deterministic code/);}
});
test("missing, mixed, unexpected and legacy attribution fields fail closed",()=>{
  const changes=[e=>delete e.data.attribution,e=>delete e.data.attribution.selectionOrigin,
    e=>e.data.attribution.responseContract="unknown",e=>e.data.attribution.selectionOrigin="MODEL",
    e=>e.data.attribution.interpretationOrigin="NOT_RECORDED",e=>e.data.attribution.responseContract="chronos.agent-proposal.v2",
    e=>e.data.attribution.private="SENTINEL",e=>e.data.schema="chronos.review-detail.v1"];
  for(const change of changes){const e=asE1(sample());change(e);const v=project(e);assert.equal(v.available,false);assert.deepEqual(v.sections,[]);}
});

test("alternative cards use only validated recorded offers, never euros or fabricated checks",()=>{
  const doc={createElement(tag){return new Element(tag,this);}},root=new Element("div",doc),e=sample();
  renderResult(root,"detail",e,context(e));
  const walk=e=>[e,...e.children.flatMap(walk)],nodes=walk(root);
  const cards=nodes.filter(x=>x.className?.split(" ").includes("chronos-option"));
  assert.equal(cards.length,2);assert.equal(cards.filter(x=>x.className.includes("--proposed")).length,1);
  const selected=cards.find(x=>x.className.includes("--proposed"));
  assert.match(selected.textContent,new RegExp("Option "+(e.data.proposal.action==="FAILOVER_B"?"B":"A")));
  assert.equal(root.textContent.includes("€"),false);
  assert.match(selected.textContent,/current eligibility requires a fresh preview/);
  const fold=nodes.find(x=>x.tag==="details"&&x.textContent.includes("Record identity and timestamps"));
  assert.ok(fold);assert.match(fold.textContent,/Context digest/);
  const unavailable=sample();unavailable.data.proposal.option_id="foreign";
  renderResult(root,"detail",unavailable,context(unavailable));
  assert.equal(walk(root).some(x=>x.className?.includes("chronos-option")),false);
});


const traced175=()=>{const e=asE1(sample());e.data.schema="chronos.review-detail.v3";
  e.data.nativeTrace={aiHubSessionId:"999999999999999999",interopSessionId:"18",namespace:"CHRONOS_LAB",sessionSnapshot:"BEFORE_CHAT"};return e;};
test("original native trace stays textual and never uses the read request session",()=>{
  const e=traced175();e.traceSessionId="777777";const v=project(e);
  assert.equal(v.available,true);assert.equal(v.canConfirm,false);
  const t=v.sections.find(s=>s.title==="Original IRIS execution");
  assert.match(dump(t),/999999999999999999/);assert.match(dump(t),/BEFORE Chat/);
  assert.ok(!dump(t).includes("777777"));assert.ok(!dump(t).includes("href"));
  assert.equal(t.rows.find(r=>r.label==="Interoperability session").value,"18");
  assert.equal(e.data.decisionDigest,sample().data.decisionDigest);
});
test("trace corruption rejects detail while legacy never invents bindings",()=>{
  for(const [key,value] of [["aiHubSessionId",18],["interopSessionId","١٨"],["interopSessionId","1".repeat(19)],
    ["aiHubSessionId","<script>"],["sessionSnapshot","AFTER_CHAT"],["namespace","../other"]]){
    const e=traced175();e.data.nativeTrace[key]=value;assert.equal(project(e).available,false,key);
  }
  const e=traced175();delete e.data.nativeTrace.interopSessionId;assert.equal(project(e).available,false);
  const old=sample();old.traceSessionId="777777";
  assert.match(dump(project(old).sections.find(s=>s.title==="Original IRIS execution")),/Not recorded/);
});
