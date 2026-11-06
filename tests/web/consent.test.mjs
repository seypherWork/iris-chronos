import {renderResult} from "../../src/chronos_web/render.mjs";
import test from "node:test";
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {consentView} from "../../src/chronos_web/consent.mjs";
const dataset=JSON.parse(readFileSync(new URL("./fixtures/detail41.json",import.meta.url),"utf8"));
const OFFSET=4070908800;
function fixture(name="proposal"){
  const detail=structuredClone(dataset.cases.find(x=>x.name===name).envelope),d=detail.data,w=d.context,f=w.facts;
  const sec=relative=>(w.utc_origin_us+relative)/1000000+OFFSET;
  const created=d.completedUS/1000000+OFFSET+1;
  const target=d.proposal.action==="FAILOVER_B"?"B":"A";
  const snapshot={orderId:w.order_id,shipmentVersion:w.shipment_version,revision:w.state_revision,
    policyRevision:w.policy_revision,quantity:f.payload.quantity,payload:d.payloadJSON,maxCost:f.budget,
    observedAt:created,inventoryUntil:sec(f.inventory_expires),deliveryDeadline:sec(f.deadline),
    offers:Object.fromEntries(["A","B"].map(t=>[t,{target:t,cost:f.options[t].cost,availableAt:sec(f.options[t].available_at),
      queueSeconds:f.options[t].queue_duration/1000000,travelSeconds:f.options[t].travel_duration/1000000,
      validUntil:sec(f.offer_until),capacity:f.payload.quantity+1}]))};
  const o=snapshot.offers[target],preview={code:"PREVIEW_RECORDED",data:{
    code:"PREVIEW_RECORDED",dispatchGranted:false,previewId:"preview42",orderId:w.order_id,
    shipmentVersion:w.shipment_version,snapshotId:17,decisionId:d.decisionId,decisionDigest:d.decisionDigest,
    option:d.proposal.action,target,actor:"principal-test42",generation:d.generation,operationId:"preview-op-preview42",
    createdAt:created,expiresAt:Math.min(created+60,d.reviewDeadlineUS/1000000+OFFSET),
    reviewDeadlineUS:d.reviewDeadlineUS,state:"PENDING",snapshot,
    predictedArrival:Math.max(created,o.availableAt)+o.queueSeconds+o.travelSeconds}};
  const ctx={expectedDecisionId:d.decisionId,expectedPreviewId:"preview42",expectedActor:"principal-test42",
    nowUnixMs:Math.round((created-OFFSET)*1000)+1000,evidence:"LIVE"};
  return {detail,preview,ctx};
}
const view=f=>consentView({detail:f.detail,preview:f.preview},f.ctx);
test("matching proposal and fresh preview show exact effect but never grant dispatch",()=>{
  const f=fixture(),v=view(f);assert.equal(v.available,true);assert.equal(v.reviewable,true);
  assert.equal(v.canConfirm,false);assert.equal(v.status,"REVIEWABLE");assert.notEqual(v.tone,"success");
  const values=v.sections[0].rows.map(x=>x.value);
  assert.ok(values.includes(f.detail.data.payloadJSON));
  for(const label of ["Action to authorize","Operation","Order","Shipment version","Data revision","Policy revision","Quantity","Exact payload JSON","Cost units","Destination"]){
    assert.ok(v.sections[0].rows.some(r=>r.label===label),label);
  }
  assert.ok(v.sections.some(s=>s.title==="Recorded proposal"));assert.ok(v.sections.some(s=>s.title==="Source catalog"));
});
test("canonical float payload remains byte-for-byte unchanged in the consent view",()=>{
  const f=fixture("finite-floats"),v=view(f);assert.equal(v.available,true);
  assert.equal(v.sections[0].rows.find(x=>x.label==="Exact payload JSON").value,f.detail.data.payloadJSON);
  assert.match(v.binding.snapshot.payload,/1e\+20/);
});
test("HOLD and ablation cannot enter actionable consent",()=>{
  for(const name of ["hold","ablation"]){const v=view(fixture(name));assert.equal(v.reviewable,false);assert.equal(v.status,"NOT_ACTIONABLE");assert.equal(v.binding,null);}
});
test("recorded, fixture and unknown provenance cannot enable live review",()=>{
  for(const evidence of ["REPLAY","LOCAL_FIXTURE","UNVERIFIED","forged"]){
    const f=fixture();f.ctx.evidence=evidence;const v=view(f);
    assert.equal(v.available,true);assert.equal(v.reviewable,false);assert.equal(v.status,"NOT_LIVE");
    assert.equal(v.canConfirm,false);
  }
});
test("missing actor/IDs and permission-like fields cannot create consent",()=>{
  for(const key of ["expectedActor","expectedDecisionId","expectedPreviewId"]){
    const f=fixture();delete f.ctx[key];assert.equal(view(f).available,false);
  }
  const f=fixture();f.preview.data.canConfirm=true;assert.equal(view(f).available,false);
});
test("decision, actor, generation, digest and operation references are bound exactly",()=>{
  for(const [key,value] of [["decisionId","other"],["actor","other"],["generation","other"],["decisionDigest","a".repeat(64)],["operationId","another-op"],["previewId","other"],["reviewDeadlineUS",1]]){
    const f=fixture();f.preview.data[key]=value;assert.equal(view(f).available,false,key);
  }
});
test("order, version, chosen branch, target and payload cannot cross previews",()=>{
  const mutations=[
    f=>f.preview.data.orderId="other",
    f=>f.preview.data.shipmentVersion++,
    f=>f.preview.data.option="FAILOVER_B",
    f=>f.preview.data.target="B",
    f=>f.preview.data.snapshot.payload='{"quantity":999}',
    f=>f.preview.data.snapshot.quantity++,
    f=>f.preview.data.snapshot.revision=0,
    f=>f.preview.data.snapshot.policyRevision=0,
  ];
  for(const change of mutations){const f=fixture();change(f);assert.equal(view(f).available,false);}
});
test("unknown private fields in preview/snapshot/offer never enter the model",()=>{
  for(const path of [[],["snapshot"],["snapshot","offers","A"]]){
    const f=fixture();let at=f.preview.data;for(const key of path)at=at[key];at.secret="PRIVATE_SENTINEL";
    const v=view(f);assert.equal(v.available,false);assert.equal(JSON.stringify(v).includes("PRIVATE_SENTINEL"),false);
  }
});
test("expired preview and human deadline are rejected at the boundary",()=>{
  for(const delta of [0,1,60000]){
    const f=fixture();f.ctx.nowUnixMs=Math.ceil((f.preview.data.expiresAt-OFFSET)*1000)+delta;
    assert.equal(view(f).status,"EXPIRED");
  }
});
test("backward, missing, nonfinite and string clocks never authorize review",()=>{
  for(const value of [undefined,NaN,Infinity,"1790000000000",-1,0]){
    const f=fixture();f.ctx.nowUnixMs=value;const v=view(f);
    assert.equal(v.reviewable,false);assert.equal(v.status,"CLOCK_UNVERIFIED");
  }
});
test("impossible expiry, stale observation and reversed prediction fail closed",()=>{
  const changes=[
    p=>p.expiresAt=p.createdAt,p=>p.expiresAt=p.createdAt+61,
    p=>p.snapshot.observedAt=p.createdAt+1,p=>p.snapshot.observedAt=p.createdAt-61,
    p=>p.snapshot.offers.A.validUntil=p.createdAt-1,
    p=>p.snapshot.inventoryUntil=p.createdAt-1,
    p=>p.predictedArrival=p.createdAt-1,p=>p.predictedArrival=p.snapshot.deliveryDeadline+1,
    p=>p.createdAt-=100,
  ];
  for(const mutate of changes){const f=fixture();mutate(f.preview.data);assert.equal(view(f).available,false);}
});
test("over-budget or insufficient-capacity offer does not become consent",()=>{
  for(const key of ["cost","capacity"]){
    const f=fixture(),offer=f.preview.data.snapshot.offers[f.preview.data.target];
    offer[key]=key==="cost"?f.preview.data.snapshot.maxCost+1:0;
    assert.equal(view(f).available,false);
  }
});
test("confirmed or rejected preview never becomes a new confirmation",()=>{
  for(const state of ["CONFIRMED","REJECTED"]){const f=fixture();f.preview.code=f.preview.data.code="READ_ONLY";f.preview.data.state=state;assert.equal(view(f).status,"NOT_ACTIONABLE");}
});
test("comparison is immutable and changes with every presented exact effect",()=>{
  const f=fixture(),v=view(f);assert.equal(Object.isFrozen(v.binding.snapshot.offers.A),true);
  f.preview.data.snapshot.payload="changed";assert.notEqual(v.binding.snapshot.payload,"changed");
  const changed=fixture();changed.preview.data.snapshotId++;
  assert.notEqual(view(changed).comparisonKey,v.comparisonKey);
  const changedCost=fixture();changedCost.preview.data.snapshot.offers.A.cost++;
  assert.notEqual(view(changedCost).comparisonKey,v.comparisonKey);
});
test("payload text that is numerically equivalent but differently serialized still requires exact review",()=>{
  const f=fixture("finite-floats");f.preview.data.snapshot.payload=JSON.stringify(JSON.parse(f.detail.data.payloadJSON));
  assert.notEqual(f.preview.data.snapshot.payload,f.detail.data.payloadJSON);
  assert.equal(view(f).available,false);
});
test("fresh-preview scalar fields reject malformed types rather than coercing",()=>{
  for(const [path,value] of [[["snapshot","quantity"],true],[["snapshotId"],"17"],[["snapshot","maxCost"],NaN],
    [["snapshot","offers","A","capacity"],"10"],[["dispatchGranted"],0]]){
    const f=fixture();let p=f.preview.data;for(const key of path.slice(0,-1))p=p[key];p[path.at(-1)]=value;
    assert.equal(view(f).available,false);
  }
});

test("comparison key ignores JSON property order but preserves every exact value",()=>{
  const f=fixture(),original=view(f).comparisonKey;
  f.preview.data.snapshot=Object.fromEntries(Object.entries(f.preview.data.snapshot).reverse());
  f.preview.data.snapshot.offers=Object.fromEntries(Object.entries(f.preview.data.snapshot.offers).reverse());
  assert.equal(view(f).comparisonKey,original);
});
test("a non-native outcome code cannot masquerade as a reviewable decision",()=>{
  const f=fixture();f.detail.data.outcome.code="OTHER_SUCCESS";
  assert.equal(view(f).available,false);
});
test("equivalent recorded expiry reaches EXPIRED at the first whole browser millisecond",()=>{
  const f=fixture(),cutoff=(f.preview.data.expiresAt-OFFSET)*1000;
  f.ctx.nowUnixMs=Math.ceil(cutoff);
  assert.equal(view(f).status,"EXPIRED");
  f.ctx.nowUnixMs=Math.ceil(cutoff)-1;
  assert.equal(view(f).reviewable,true);
});
class Element{
  constructor(tag,doc){this.tag=tag;this.ownerDocument=doc;this.children=[];this.attrs={};this._text="";}
  set textContent(x){this._text=String(x);this.children=[];}get textContent(){return this._text+this.children.map(x=>x.textContent).join("");}
  set innerHTML(_){throw Error("HTML forbidden");}
  appendChild(x){this.children.push(x);return x;}replaceChildren(...xs){this.children=xs;}
  setAttribute(k,v){this.attrs[k]=v;}
}
test("consent renderer shows effect and sources as inert text without action controls",()=>{
  const f=fixture(),tags=[],doc={createElement(tag){tags.push(tag);return new Element(tag,this);}},root=new Element("main",doc);
  const result=renderResult(root,"consent",{detail:f.detail,preview:f.preview},f.ctx);
  assert.equal(result.reviewable,true);assert.equal(result.canConfirm,false);
  for(const text of ["Fresh server preview","Exact payload JSON","Before confirming","Recorded proposal","Source catalog","preview-op-preview42"])assert.ok(root.textContent.includes(text));
  for(const forbidden of ["button","input","script","a","iframe"])assert.equal(tags.includes(forbidden),false);
});

test("attribution is visible during consent without changing the exact effect binding",()=>{
  const f=fixture(),legacy=view(f);f.detail.data.schema="chronos.review-detail.v2";
  f.detail.data.attribution={responseContract:"chronos.preference-extraction.v1",interpretationOrigin:"MODEL",selectionOrigin:"DETERMINISTIC_CODE"};
  const current=view(f);assert.equal(current.available,true);assert.equal(current.reviewable,true);assert.equal(current.canConfirm,false);
  assert.equal(current.comparisonKey,legacy.comparisonKey);assert.deepEqual(current.binding,legacy.binding);
  assert.match(JSON.stringify(current.sections.find(s=>s.title==="How this proposal was produced")),/Deterministic code/);
  f.detail.data.attribution.selectionOrigin="MODEL";assert.equal(view(f).reviewable,false);
});

test("consent shows the updated price and expiry before the historical alternative cards",()=>{
  const f=fixture(),target=f.preview.data.target;
  const oldCost=f.detail.data.context.facts.options[target].cost;
  f.preview.data.snapshot.offers[target].cost=oldCost+1;
  const doc={createElement(tag){return new Element(tag,this);}},root=new Element("main",doc);
  const result=renderResult(root,"consent",{detail:f.detail,preview:f.preview},f.ctx);
  assert.equal(result.reviewable,true);
  const walk=e=>[e,...e.children.flatMap(walk)],nodes=walk(root);
  const fresh=nodes.find(e=>e.tag==="section"&&e.children.some(x=>x.tag==="h3"&&x.textContent==="Fresh server preview"));
  const historical=nodes.find(e=>e.className?.split(" ").includes("chronos-option"));
  assert.ok(fresh&&historical);assert.ok(nodes.indexOf(fresh)<nodes.indexOf(historical));
  const list=fresh.children.find(e=>e.tag==="dl"),cost=list.children.findIndex(e=>e.tag==="dt"&&e.textContent==="Cost units");
  assert.equal(list.children[cost+1].textContent,String(oldCost+1));
  const summary=nodes.find(e=>e.className==="chronos-exact-summary");
  assert.ok(summary);assert.ok(summary.textContent.includes(String(oldCost+1)+" cost units"));
  assert.ok(nodes.indexOf(summary)<nodes.indexOf(historical));
  assert.ok(root.textContent.indexOf("Preview expires (UTC)")<root.textContent.indexOf("Fresh server preview"));
  assert.ok(root.textContent.indexOf("Actor")<root.textContent.indexOf("Fresh server preview"));
  assert.equal(nodes.some(e=>e.tag==="details"&&e.textContent.includes("Fresh server preview")),false);
});

test("original trace v3 does not change consent or comparison binding",()=>{
  const f=fixture(),legacy=view(f);f.detail.data.schema="chronos.review-detail.v3";
  f.detail.data.attribution={responseContract:"chronos.preference-extraction.v1",interpretationOrigin:"MODEL",selectionOrigin:"DETERMINISTIC_CODE"};
  f.detail.data.nativeTrace={aiHubSessionId:"999999999999999999",interopSessionId:"18",namespace:"CHRONOS_LAB",sessionSnapshot:"BEFORE_CHAT"};
  const current=view(f);assert.equal(current.available,true);assert.equal(current.reviewable,true);assert.equal(current.canConfirm,false);
  assert.equal(current.comparisonKey,legacy.comparisonKey);assert.deepEqual(current.binding,legacy.binding);
  assert.ok(current.sections.some(s=>s.title==="Original IRIS execution"));
  f.detail.data.nativeTrace.interopSessionId=18;assert.equal(view(f).reviewable,false);
});
