import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import {mountWorkflowPanel} from "../../src/chronos_web/workflow-panel.mjs";
import {ChronosClientError} from "../../src/chronos_web/client.mjs";

// Same deliberately small DOM pattern as conversation-panel.test.mjs. This
// exercises the real panel/controller with simulated native responses, not CSP,
// Workflow, a model, browser layout or shipment execution.
class Element {
  constructor(tag,doc){this.tag=tag;this.ownerDocument=doc;this.children=[];this.attrs={};this.listeners=new Map();this.value="";this.checked=false;this._text="";}
  set textContent(value){this._text=String(value);this.children=[];}
  get textContent(){return this._text+this.children.map(x=>x.textContent).join("");}
  set innerHTML(_){throw Error("HTML forbidden");}
  appendChild(child){this.children.push(child);return child;}
  replaceChildren(...children){this.children=children;this._text="";}
  setAttribute(key,value){this.attrs[key]=String(value);}
  focus(){this.ownerDocument.focused=this;this.ownerDocument.activeElement=this;}
  addEventListener(type,fn){if(!this.listeners.has(type))this.listeners.set(type,[]);this.listeners.get(type).push(fn);}
  removeEventListener(type,fn){this.listeners.set(type,(this.listeners.get(type)??[]).filter(x=>x!==fn));}
  async dispatch(type){for(const fn of this.listeners.get(type)??[])await fn({preventDefault(){}});}
}
const flat=root=>[root,...root.children.flatMap(flat)];
const deferred=()=>{let resolve;const promise=new Promise(r=>resolve=r);return {promise,resolve};};
const clone=value=>structuredClone(value);

function setup({approve=true,mode="LIVE_MODEL"}={}){
  let connected=false,actor="principal-"+"a".repeat(64),clock=1_800_000_000_000,seq=0;
  const calls=[],activation=[],busy=[],decisions=[];
  const wire={state:"NOT_FOUND",clarificationId:"",newDecisionId:"",taskReady:false,
    completionRecorded:false,expiresUS:null,completeError:null,completeCode:"WORKFLOW_CLARIFICATION_RECORDED",
    holdComplete:null,holdRead:null};
  const packet=()=>({code:"WORKFLOW_STATUS_READ",decisionId:"held-decision",clarificationId:wire.clarificationId,
    newDecisionId:wire.newDecisionId,state:wire.state,expiresUS:wire.expiresUS,taskReady:wire.taskReady,
    completionRecorded:wire.completionRecorded,canUseClarification:false,dispatch_authorized:false});
  const receipt=(id=wire.lastCompletionId)=>({code:wire.completeCode,
    actorVerified:wire.completeCode==="WORKFLOW_CLARIFICATION_RECORDED",
    completionVerified:wire.completeCode==="WORKFLOW_CLARIFICATION_RECORDED",
    canUseClarification:false,dispatch_authorized:false,clarificationId:wire.clarificationId,completionId:id});
  const client={
    connect:async()=>{calls.push({kind:"SESSION"});connected=true;return client.sessionStatus();},
    disconnect:()=>{calls.push({kind:"DISCONNECT"});connected=false;},
    sessionStatus:()=>({connected,canRead:connected,canApprove:connected&&approve}),
    sessionIdentity:()=>({available:connected,actor,actorScope:"b".repeat(64),applicationUrl:"https://chronos.example/csp/chronos/"}),
    sessionExecution:()=>({mode}),
    readClarification:async id=>{calls.push({kind:"READ",id});return wire.holdRead?wire.holdRead.promise:packet();},
    startClarification:async id=>{calls.push({kind:"START",id});wire.state="QUEUED";return packet();},
    completeClarification:async(c,id,form)=>{
      calls.push({kind:"COMPLETE",clarificationId:c,id,form:clone(form)});wire.lastCompletionId=id;
      if(wire.holdComplete)return wire.holdComplete.promise;
      if(wire.completeError)throw new ChronosClientError(wire.completeError);
      if(wire.completeCode==="WORKFLOW_CLARIFICATION_RECORDED")wire.completionRecorded=true;
      return receipt(id);
    },
    readClarificationCompletion:async(c,id,form)=>{
      calls.push({kind:"RECEIPT",clarificationId:c,id,form:clone(form)});
      return receipt(id);
    },
    reevaluateClarification:async(c,id)=>{
      calls.push({kind:"REEVALUATE",clarificationId:c,id});wire.newDecisionId=id;
      return {code:"WORKFLOW_REEVALUATION_REQUESTED",decisionId:id,readbackRequired:true,dispatch_authorized:false};
    },
  };
  for(const name of ["preview","preparePreview","confirmPreview","reconcilePreview","reconcileOperation","dispatch","submitRecovery"]){
    client[name]=()=>assert.fail("Workflow panel cannot invoke shipment action: "+name);
  }
  const doc={createElement(tag){return new Element(tag,this);}},root=new Element("div",doc);
  const chosen={kind:"decision",id:"held-decision"};
  const panel=mountWorkflowPanel(root,{client,selection:()=>chosen,newId:()=>"workflow-id-"+(++seq),now:()=>clock,
    onActivate:()=>activation.push("ACTIVATE"),onBusy:value=>busy.push(value),onDecision:id=>decisions.push(id)});
  const button=name=>flat(root).find(e=>e.tag==="button"&&e.textContent===name);
  const field=name=>flat(root).find(e=>e.attrs["aria-label"]===name);
  const count=kind=>calls.filter(x=>x.kind===kind).length;
  return {root,panel,client,calls,wire,activation,busy,decisions,chosen,packet,receipt,button,field,count,
    setActor:value=>{actor=value;},setClock:value=>{clock=value;},
    async open(){await button("Inspect selected clarification").dispatch("click");},
    ready(){wire.state="SENT";wire.clarificationId="clarification-1";wire.taskReady=true;wire.expiresUS=(clock+600_000)*1000;},
    async read(){await button("Read original status").dispatch("click");},
    async form(note="The customer confirms earlier arrival within the current budget.",preference="EARLIEST_ALLOWED",ack=true){
      field("Customer instruction").value=note;field("Customer priority").value=preference;
      field("Clarification records information only").checked=ack;
      await field("Clarification records information only").dispatch("change");
      await field("Record customer clarification").dispatch("submit");
    },
  };
}

async function ready(options){const s=setup(options);await s.open();s.ready();await s.read();return s;}

test("mount is offline; labels and acknowledgement describe information rather than approval",()=>{
  const s=setup();assert.deepEqual(s.calls,[]);assert.deepEqual(s.activation,[]);
  assert.deepEqual(s.busy,[false]);assert.equal(s.root.attrs["aria-label"],"Native human clarification");
  for(const label of ["Customer priority","Customer instruction","Clarification records information only","Record customer clarification"])
    assert.ok(s.field(label),label);
  const status=flat(s.root).find(e=>e.attrs.role==="status");assert.equal(status.attrs["aria-live"],"polite");
  assert.equal(s.field("Customer instruction").autocomplete,"off");
  assert.equal(s.button("Record clarification").disabled,true);
  assert.match(s.root.textContent,/This does not approve or send a shipment/);
  s.panel.destroy();
});

test("full explicit native-status route ends in a separate new-decision read callback, never shipment",async()=>{
  const s=setup();await s.open();assert.equal(s.count("READ"),1);assert.equal(s.count("START"),0);
  assert.equal(s.button("Request a human clarification").disabled,false);
  await s.button("Request a human clarification").dispatch("click");
  assert.equal(s.count("START"),1);assert.match(s.root.textContent,/task may still be creating/);
  assert.equal(s.field("Customer instruction").disabled,true);
  await Promise.resolve();await Promise.resolve();assert.equal(s.count("READ"),1);
  s.ready();await s.read();assert.equal(s.count("READ"),2);assert.equal(s.field("Customer instruction").disabled,false);
  await s.form();assert.equal(s.count("COMPLETE"),1);assert.equal(s.field("Customer instruction").value,"");
  assert.match(s.root.textContent,/historical completion receipt is recorded/i);
  assert.equal(s.button("Request a new agent decision").disabled,false);
  await s.button("Request a new agent decision").dispatch("click");
  assert.equal(s.count("REEVALUATE"),1);assert.deepEqual(s.decisions,[]);
  assert.match(s.root.textContent,/Do not request another model run/);
  await s.read();assert.match(s.root.textContent,/new decision reference is registered/i);
  await s.button("Read new decision").dispatch("click");
  assert.deepEqual(s.decisions,[s.calls.find(x=>x.kind==="REEVALUATE").id]);
  assert.equal(s.count("START"),1);assert.equal(s.count("COMPLETE"),1);assert.equal(s.count("REEVALUATE"),1);
  assert.deepEqual(s.activation,["ACTIVATE"]);assert.ok(s.busy.includes(true));s.panel.destroy();
});

test("missing acknowledgement prevents completion; note and priority edits perform no action",async()=>{
  const s=await ready();const before=clone(s.calls);
  await s.form("Prefer the earlier arrival.","EARLIEST_ALLOWED",false);
  assert.deepEqual(s.calls,before);assert.equal(s.button("Record clarification").disabled,true);
  assert.equal(s.field("Customer instruction").value,"Prefer the earlier arrival.");s.panel.destroy();
});

test("invalid local submissions preserve the draft and acknowledgement without an outgoing request",async()=>{
  for(const note of ["", " ", "x".repeat(241), "🙂".repeat(241), "x".repeat(239)+"🙂🙂", "bad\nnote", "bad\\note"]){
    const s=await ready(),before=clone(s.calls);
    await s.form(note);assert.equal(s.field("Customer instruction").value,note);
    assert.equal(s.field("Clarification records information only").checked,true);
    assert.deepEqual(s.calls,before);s.panel.destroy();
  }
});

test("an invalid priority value cannot silently erase an otherwise valid instruction",async()=>{
  const s=await ready(),before=clone(s.calls),note="The current customer still needs an earlier arrival.";
  await s.form(note,"UNKNOWN_PRIORITY");
  assert.deepEqual(s.calls,before);assert.equal(s.field("Customer instruction").value,note);
  assert.equal(s.field("Clarification records information only").checked,true);s.panel.destroy();
});

test("an explicit native form rejection preserves editable note instead of suggesting receipt recovery",async()=>{
  const s=await ready();s.wire.completeCode="INVALID_CLARIFICATION_NOTE";
  await s.form("The current customer instruction must be checked.");
  assert.equal(s.count("COMPLETE"),1);assert.equal(s.field("Customer instruction").value,"The current customer instruction must be checked.");
  assert.match(s.root.textContent,/note is not valid/);
  assert.equal(s.field("Customer instruction").disabled,false);assert.equal(s.button("Read original completion receipt").disabled,true);
  s.panel.destroy();
});

test("a lost completion reply uses its original receipt and frozen form, not another completion",async()=>{
  const s=await ready();s.wire.completeError="REQUEST_TIMEOUT";
  await s.form("Earlier arrival is the current customer priority.","EARLIEST_ALLOWED");
  assert.equal(s.count("COMPLETE"),1);assert.equal(s.button("Record clarification").disabled,true);
  assert.equal(s.button("Close clarification view").disabled,true);
  await s.form("Changed draft must not be sent.");assert.equal(s.count("COMPLETE"),1);
  await s.button("Read original completion receipt").dispatch("click");
  assert.equal(s.count("RECEIPT"),1);assert.equal(s.count("COMPLETE"),1);
  const sent=s.calls.find(x=>x.kind==="COMPLETE"),read=s.calls.find(x=>x.kind==="RECEIPT");
  assert.equal(read.id,sent.id);assert.deepEqual(read.form,sent.form);
  assert.equal(s.button("Request a new agent decision").disabled,false);s.panel.destroy();
});

test("busy completion disables every competing action and never turns callbacks into requests",async()=>{
  const s=await ready();s.wire.holdComplete=deferred();const pending=s.form("Current earlier-arrival priority.");
  for(let n=0;n<8&&s.count("COMPLETE")===0;n++)await Promise.resolve();
  assert.equal(s.count("COMPLETE"),1);assert.equal(s.busy.at(-1),true);
  for(const name of ["Read original status","Request a human clarification","Record clarification",
      "Read original completion receipt","Request a new agent decision","Read new decision","Close clarification view"])
    assert.equal(s.button(name).disabled,true,name);
  const before=clone(s.calls);
  await s.button("Read original status").dispatch("click");
  await s.button("Request a new agent decision").dispatch("click");
  assert.deepEqual(s.calls,before);assert.deepEqual(s.decisions,[]);
  s.wire.holdComplete.resolve(s.receipt());await pending;assert.equal(s.busy.at(-1),false);
  assert.equal(s.count("COMPLETE"),1);s.panel.destroy();
});

test("unverified normal completion receipt remains uncertain until its explicit verified read",async()=>{
  const s=await ready();s.wire.completeCode="WORKFLOW_COMPLETION_UNCERTAIN";
  await s.form();assert.equal(s.count("COMPLETE"),1);
  assert.equal(s.button("Request a new agent decision").disabled,true);
  assert.equal(s.button("Record clarification").disabled,true);
  assert.match(s.root.textContent,/Completion is not confirmed/);
  s.wire.completeCode="WORKFLOW_CLARIFICATION_RECORDED";
  await s.button("Read original completion receipt").dispatch("click");
  assert.equal(s.count("RECEIPT"),1);assert.equal(s.count("COMPLETE"),1);
  assert.equal(s.button("Request a new agent decision").disabled,false);s.panel.destroy();
});

test("Reader may explicitly inspect native status but cannot start, complete or reevaluate",async()=>{
  const s=await ready({approve:false});
  for(const name of ["Request a human clarification","Record clarification","Request a new agent decision"])
    assert.equal(s.button(name).disabled,true,name);
  for(const label of ["Customer priority","Customer instruction","Clarification records information only"])
    assert.equal(s.field(label).disabled,true,label);
  await s.form();await s.button("Request a human clarification").dispatch("click");
  assert.equal(s.count("START"),0);assert.equal(s.count("COMPLETE"),0);assert.equal(s.count("REEVALUATE"),0);s.panel.destroy();
});

test("recorded mode permits native information recording but explicitly blocks a new model decision",async()=>{
  const s=await ready({mode:"RECORDED_FIXTURE"});await s.form();
  assert.equal(s.count("COMPLETE"),1);assert.equal(s.button("Request a new agent decision").disabled,true);
  await s.button("Request a new agent decision").dispatch("click");assert.equal(s.count("REEVALUATE"),0);
  assert.match(s.root.textContent,/Recorded fixture mode cannot interpret a new clarification/);
  assert.match(s.root.textContent,/live provider is needed/);s.panel.destroy();
});

test("expiry disables the form and reevaluation without initiating a request",async()=>{
  const s=await ready();s.setClock(s.wire.expiresUS/1000);const before=clone(s.calls);s.panel.setAvailable(true);
  assert.equal(s.field("Customer instruction").disabled,true);assert.equal(s.button("Record clarification").disabled,true);
  assert.equal(s.button("Request a new agent decision").disabled,true);assert.deepEqual(s.calls,before);s.panel.destroy();
});

test("account change and deactivation erase former drafts and references",async()=>{
  for(const action of ["account","deactivate","unavailable"]){
    const s=await ready();s.field("Customer instruction").value="PREVIOUS_ACTOR_PRIVATE_NOTE";
    if(action==="account"){s.setActor("principal-"+"f".repeat(64));s.panel.setAvailable(true);}
    else if(action==="deactivate")s.panel.deactivate();else s.panel.setAvailable(false);
    assert.equal(s.field("Customer instruction").value,"");assert.equal(s.field("Clarification records information only").checked,false);
    assert.equal(s.root.textContent.includes("Original decision: held-decision"),false);
    assert.equal(s.field("Customer instruction").disabled,true);s.panel.destroy();
  }
});

test("a changed account cannot read the old private clarification after reconnect",async()=>{
  const s=await ready(),reads=s.count("READ");s.field("Customer instruction").value="OLD_PRIVATE_DRAFT";
  s.setActor("principal-"+"f".repeat(64));await s.read();
  assert.equal(s.count("READ"),reads);assert.equal(s.field("Customer instruction").value,"");
  assert.equal(s.root.textContent.includes("Original decision: held-decision"),false);
  assert.match(s.root.textContent,/account or installation changed/);s.panel.destroy();
});

test("late completion cannot repaint a deactivated or destroyed view",async()=>{
  for(const action of ["deactivate","destroy"]){
    const s=await ready();s.wire.holdComplete=deferred();const pending=s.form("Private instruction sent once.");
    for(let n=0;n<8&&s.count("COMPLETE")===0;n++)await Promise.resolve();
    assert.equal(s.count("COMPLETE"),1);s.field("Customer instruction").value="PRIVATE_DRAFT_AFTER_SEND";
    s.panel[action]();s.wire.holdComplete.resolve(s.receipt());await pending;
    assert.equal(s.root.textContent.includes("PRIVATE_DRAFT_AFTER_SEND"),false);
    assert.equal(s.root.textContent.includes("Original decision: held-decision"),false);
    if(action==="destroy")assert.equal(s.root.children.length,0);else assert.equal(s.field("Customer instruction").value,"");
    s.panel.destroy();
  }
});

test("literal business text cannot create HTML and browser storage is never used",async t=>{
  const keys=["localStorage","sessionStorage"],prior=new Map(keys.map(key=>[key,Object.getOwnPropertyDescriptor(globalThis,key)]));
  for(const key of keys)Object.defineProperty(globalThis,key,{configurable:true,get(){throw Error("Browser storage forbidden");}});
  t.after(()=>{for(const key of keys){const old=prior.get(key);if(old)Object.defineProperty(globalThis,key,old);else delete globalThis[key];}});
  const s=await ready(),note='<img src=x onerror="alert(1)">';await s.form(note);
  assert.equal(s.calls.find(x=>x.kind==="COMPLETE").form.note,note);
  assert.equal(flat(s.root).some(e=>["img","script","iframe","a"].includes(e.tag)),false);
  s.panel.destroy();
});

test("invalid selection creates no network work; lifecycle callbacks never start background polling",async()=>{
  const s=setup();s.chosen.kind="operation";await s.open();assert.deepEqual(s.calls,[]);
  assert.deepEqual(s.activation,[]);
  s.panel.setAvailable(false);s.panel.setAvailable(true);await Promise.resolve();assert.deepEqual(s.calls,[]);
  for(const name of ["workflow-panel.mjs","workflow-controller.mjs"]){
    const source=fs.readFileSync(new URL('../../src/chronos_web/'+name,import.meta.url),'utf8');
    assert.doesNotMatch(source,/\b(?:setInterval|setTimeout|requestAnimationFrame)\s*\(/);
    assert.doesNotMatch(source,/\b(?:localStorage|sessionStorage|indexedDB)\b/);
  }
  s.panel.destroy();
});
