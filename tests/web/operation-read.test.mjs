import test from "node:test";
import assert from "node:assert/strict";
import {createResultController} from "../../src/chronos_web/controller.mjs";
import {decisionOperationView} from "../../src/chronos_web/presentation.mjs";
import {createRecoveryReferences} from "../../src/chronos_web/references.mjs";
import {ChronosClientError} from "../../src/chronos_web/client.mjs";
const packet=data=>({code:data.code,data});
const decision=id=>packet({code:"EXISTING_DECISION",dispatchGranted:false,inferenceGranted:false,dispatch_authorized:false,
 requestId:id,orderId:"order114",shipmentVersion:1,generation:"g1",deadlineUS:1793296800000000,mode:"WITH_TRIALS",state:"COMPLETED",
 outcome:{status:"DETERMINISTIC",code:"ACCEPTANCE_UNRESOLVED",dispatch_authorized:false}});
const op=(id="original114",state="UNKNOWN")=>({code:"READ_ONLY",dispatchGranted:false,operationId:id,attemptId:"attempt114",state,reference:state==="ACCEPTED"?"synthetic-acceptance":"",quarantined:false});
const current=(id="original114")=>packet({code:"DECISION_OPERATION_RECORDED",dispatchGranted:false,decisionId:"d114",orderId:"order114",shipmentVersion:1,operation:op(id)});
const deferred=()=>{let resolve;let promise=new Promise(r=>resolve=r);return {promise,resolve};};
function setup(overrides={}){
 const calls=[],saved=[],client={
  connect:async()=>({connected:true,canRead:true,canApprove:false}),disconnect(){},
  readDecision:async id=>decision(id),readPreview:async()=>{throw Error("no preview");},
  reconcilePreview:async()=>{throw Error("no preview");},logout:async()=>({code:"SESSION_ENDED"}),
  readDecisionOperation:async id=>{calls.push(["current",id]);return current();},
  readOperation:async id=>{calls.push(["read",id]);return packet(op(id));},
  reconcileOperation:async id=>{calls.push(["query",id]);return packet({...op(id),code:"READBACK_RECORDED"});},
  ...overrides};
 const c=createResultController({client,references:{remember:v=>{saved.push(v);return {ok:true};}},evidence:"LOCAL_FIXTURE"});
 return {c,client,calls,saved};
}
test("historical decision and current operation are separate; queries stay pinned despite current change",async()=>{
 const s=setup();await s.c.select("decision","d114");assert.equal(s.c.canReconcile(),false);
 await s.c.readCurrentOperation();assert.equal(s.c.snapshot().selection.kind,"operation");
 assert.equal(s.c.snapshot().selection.id,"original114");assert.equal(s.c.preparationBlockReason(),"DECISION_REQUIRED");
 s.client.readDecisionOperation=async()=>current("replacement114");
 await s.c.reconcileSelected();assert.deepEqual(s.calls,[["current","d114"],["query","original114"]]);
 assert.deepEqual(s.saved,[{kind:"decision",id:"d114"},{kind:"operation",id:"original114"}]);
});
test("current operation cannot be adopted from another decision, order, version or unsafe grant",()=>{
 for(const [key,value] of [["decisionId","other"],["orderId","other"],["shipmentVersion",2],["dispatchGranted",true]]){
  const p=current();p.data[key]=value;
  assert.equal(decisionOperationView(p,{expectedId:"d114",expectedOrder:"order114",expectedShipmentVersion:1}).available,false);
 }
 const p=current();p.data.operation.dispatchGranted=true;
 assert.equal(decisionOperationView(p,{expectedId:"d114",expectedOrder:"order114",expectedShipmentVersion:1}).available,false);
});
test("unknown or missing outcome never becomes acceptance and can reopen exact operation",async()=>{
 const s=setup({reconcileOperation:async()=>packet({code:"OPERATION_UNAVAILABLE",dispatchGranted:false})});
 await s.c.select("operation","original114");assert.match(s.c.snapshot().view.title,/unknown/);
 await s.c.reconcileSelected();assert.equal(s.c.snapshot().phase,"ERROR");assert.equal(s.c.canReconcile(),false);
 await s.c.select("operation","original114");assert.deepEqual(s.calls,[["read","original114"],["read","original114"]]);
 assert.match(s.c.snapshot().view.title,/unknown/);
});
test("permission revocation hides previous outcome and cannot enable a retry",async()=>{
 const s=setup({reconcileOperation:async()=>{throw new ChronosClientError("PERMISSION_DENIED");}});
 await s.c.select("operation","original114");await s.c.reconcileSelected();
 assert.equal(s.c.snapshot().phase,"ERROR");assert.equal(s.c.snapshot().view,null);assert.equal(s.c.canReconcile(),false);
});
test("double query while pending is rejected and late response after switch is ignored",async()=>{
 const wait=deferred();let count=0;
 const s=setup({reconcileOperation:async()=>{count++;return wait.promise;}});
 await s.c.select("operation","original114");const query=s.c.reconcileSelected();
 await assert.rejects(s.c.reconcileSelected());assert.equal(count,1);
 await s.c.select("decision","other");wait.resolve(packet(op("original114","ACCEPTED")));await query;
 assert.equal(s.c.snapshot().selection.id,"other");assert.doesNotMatch(s.c.snapshot().view.title,/Acceptance recorded/);
});
test("late current-operation response cannot replace a newly selected decision",async()=>{
 const wait=deferred(),s=setup({readDecisionOperation:()=>wait.promise});
 await s.c.select("decision","d114");const pending=s.c.readCurrentOperation();
 await s.c.select("decision","other");wait.resolve(current());await pending;
 assert.equal(s.c.snapshot().selection.id,"other");assert.equal(s.c.canReconcile(),false);
});
test("operation bookmark survives remount and contains only a typed exact ID",()=>{
 const m=new Map(),storage={getItem:k=>m.get(k)??null,setItem:(k,v)=>m.set(k,v)},config={storage,applicationUrl:"https://chronos.example/csp/chronos",actorScope:"a".repeat(64)};
 const a=createRecoveryReferences(config);assert.equal(a.remember({kind:"operation",id:"original114"}).ok,true);
 assert.deepEqual(createRecoveryReferences(config).list().items,[{kind:"operation",id:"original114"}]);
 assert.deepEqual(JSON.parse([...m.values()][0]),{version:1,items:[{kind:"operation",id:"original114"}]});
});

test("scope changes during operation bookmark storage hide stale data and disable query",async()=>{
 for(const during of ["remember","list"]){
  let scope="A",armed=false;const saved=[];
  const refs={scope:()=>scope,forget:()=>({ok:true}),
   remember:item=>{saved.push(item);if(armed&&during==="remember")scope="B";return {ok:scope==="A"};},
   list:()=>{if(armed&&during==="list")scope="B";return {ok:true,scope,code:"REFERENCES_READ",items:saved};}};
  const s=setup(),c=createResultController({client:s.client,references:refs});
  await c.select("decision","d114");armed=true;await c.readCurrentOperation();
  assert.equal(c.snapshot().phase,"ERROR");assert.equal(c.snapshot().view,null);
  assert.equal(c.canReconcile(),false);assert.equal(c.snapshot().code,"REFERENCE_SCOPE_CHANGED");
 }
});
