import test from "node:test";
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {mountResultScreen, workflowSection} from "../../src/chronos_web/screen.mjs";
import {createChronosClient} from "../../src/chronos_web/client.mjs";

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
    code:"PREVIEW_RECORDED",dispatchGranted:false,previewId:"prep-preview42",orderId:w.order_id,
    shipmentVersion:w.shipment_version,snapshotId:17,decisionId:d.decisionId,decisionDigest:d.decisionDigest,
    option:d.proposal.action,target,actor:"principal-test42",generation:d.generation,operationId:"preview-op-prep-preview42",
    createdAt:created,expiresAt:Math.min(created+60,d.reviewDeadlineUS/1000000+OFFSET),
    reviewDeadlineUS:d.reviewDeadlineUS,state:"PENDING",snapshot,
    predictedArrival:Math.max(created,o.availableAt)+o.queueSeconds+o.travelSeconds}};
  const ctx={expectedDecisionId:d.decisionId,expectedPreviewId:"prep-preview42",expectedActor:"principal-test42",
    nowUnixMs:Math.round((created-OFFSET)*1000)+1000,evidence:"LIVE"};
  return {detail,preview,ctx};
}

const ACTOR="principal-"+"a".repeat(64),SCOPE="a".repeat(64);
const json=x=>new Response(JSON.stringify(x),{headers:{"Content-Type":"application/json"}});
const deferred=()=>{let resolve;const promise=new Promise(r=>resolve=r);return {promise,resolve};};
function setup({name="proposal",evidence="LIVE",timeoutMs=250,onChange=()=>{}}={}){
  const f=fixture(name);f.preview.data.actor=ACTOR;
  const storage={data:new Map(),getItem(k){return this.data.get(k)??null;},setItem(k,v){this.data.set(k,v);}};
  const wire={receipts:new Map(),requests:[],calls:[],hook:null,actor:ACTOR,scope:SCOPE,canRead:true,canApprove:true,identity:true};
  const clock={now:f.ctx.nowUnixMs};
  const client=createChronosClient({basePath:"/csp/chronos",pageUrl:"https://chronos.example/web",timeoutMs,
    fetchImpl:async(url,options)=>{
      const request=options.body?JSON.parse(options.body):{};
      wire.requests.push(request);
      const command=options.method==="GET"?"SESSION":new URL(url).pathname.endsWith("/logout")?"LOGOUT":JSON.parse(options.body).command;
      wire.calls.push(command);
      if(wire.hook){const result=wire.hook(command,request);if(result)return result;}
      if(command==="SESSION")return json({code:wire.canRead?"CONNECTED":"ACCESS_REVOKED",authenticated:true,
        csrf:"c".repeat(64),canRead:wire.canRead,canApprove:wire.canRead&&wire.canApprove,
        identity:wire.canRead&&wire.identity?{version:1,available:true,actor:wire.actor,actorScope:wire.scope,
          applicationUrl:"https://chronos.example/csp/chronos/"}:{version:1,available:false}});
      if(command==="DECISION_DETAIL")return json(f.detail);
      if(["PREVIEW_REQUEST","READ_PREPARATION","CLOSE_PREPARATION"].includes(command)){
        const rid=command==="READ_PREPARATION"?request.id:request.requestId;
        let p=wire.receipts.get(rid);
        if(!p&&command!=="READ_PREPARATION"){
          p={code:command==="CLOSE_PREPARATION"?"PREPARATION_CLOSED_NO_PREVIEW":"PREPARATION_RECORDED",
            dispatchGranted:false,canConfirm:false,requestId:rid,actor:wire.actor,decisionId:request.id,
            previewId:command==="CLOSE_PREPARATION"?"":f.preview.data.previewId,
            state:command==="CLOSE_PREPARATION"?"CLOSED_NO_PREVIEW":"RECORDED"};
          wire.receipts.set(rid,p);
        }
        if(p&&command==="CLOSE_PREPARATION"&&p.state==="STARTED"){
          p.state="CLOSED_NO_PREVIEW";p.code="PREPARATION_CLOSED_NO_PREVIEW";
        }
        p??={code:"PREPARATION_NOT_FOUND",dispatchGranted:false,canConfirm:false,requestId:rid,
          actor:wire.actor,decisionId:"",previewId:"",state:"NOT_FOUND"};
        return json({code:p.code,data:structuredClone(p)});
      }
      if(command==="READ"){const p=structuredClone(f.preview);p.code=p.data.code="READ_ONLY";return json(p);}
      if(command==="CONFIRM"){
        f.preview.data.state="CONFIRMED";
        f.preview.data.operation={code:"READBACK_RECORDED",dispatchGranted:false,operationId:f.preview.data.operationId,
          attemptId:"owned-attempt",state:"ACCEPTED",reference:"owned-receipt",quarantined:false};
        return json({code:"READBACK_RECORDED",data:f.preview.data.operation});
      }
      if(command==="REJECT"){f.preview.data.state="REJECTED";return json({code:"PREVIEW_REJECTED",data:{...f.preview.data,code:"PREVIEW_REJECTED"}});}
      throw Error("UNEXPECTED_COMMAND");
    }});
  const document={createElement(tag){if(this.failTag===tag){this.failTag=null;throw Error("PRIVATE_RENDER");}return new Element(tag,this);}};
  const root=new Element("div",document),timers=new Map();let timerId=0;
  const screen=mountResultScreen(root,{client,storage,evidence,now:()=>clock.now,
    schedule:fn=>{const id=++timerId;timers.set(id,fn);return id;},cancel:id=>timers.delete(id)});
  const button=label=>find(root,e=>e.tag==="button"&&e.textContent===label);
  return {f,storage,wire,clock,client,screen,root,document,timers,button,decisionId:f.detail.data.decisionId,
    input:find(root,e=>e.attrs["aria-label"]==="Existing reference"),
    kind:find(root,e=>e.attrs["aria-label"]==="Reference type"),
    ack:find(root,e=>e.type==="checkbox"),
    body:find(root,e=>e.attrs["aria-label"]==="Approval evidence"),
    consent:find(root,e=>e.attrs["aria-label"]==="Exact human approval"),
    fireTimer(){const [id,fn]=[...timers.entries()][0];timers.delete(id);fn();},
    sessionResponse:()=>json({code:"CONNECTED",authenticated:true,csrf:"c".repeat(64),canRead:true,canApprove:true,
      identity:{version:1,available:true,actor:wire.actor,actorScope:wire.scope,applicationUrl:"https://chronos.example/csp/chronos/"}})};
}

const count=(s,command)=>s.wire.calls.filter(x=>x===command).length;
const prepare=async s=>{
  s.input.value=s.decisionId;await s.button("Prepare exact preview").dispatch("click");
  assert.equal(s.ack.disabled,false,s.root.textContent);
};
const accept=async s=>{s.ack.checked=true;await s.ack.dispatch("change");};
const tick=()=>new Promise(r=>setImmediate(r));

test("mount does no work; only configured LIVE with bookmarks exposes consent",()=>{
  for(const evidence of ["LIVE","REPLAY","LOCAL_FIXTURE","UNVERIFIED"]){
    const s=setup({evidence});assert.equal(s.wire.calls.length,0);assert.equal(s.timers.size,0);
    assert.equal(Boolean(s.button("Prepare exact preview")),evidence==="LIVE");s.screen.destroy();
  }
});
test("invalid decision/type cannot create a preview",async()=>{
  const s=setup();
  for(const value of ["","a/b","<img>"]){
    s.input.value=value;await s.button("Prepare exact preview").dispatch("click");
  }
  s.input.value=s.decisionId;s.kind.value="preview";await s.button("Prepare exact preview").dispatch("click");
  assert.equal(s.wire.calls.length,0);s.screen.destroy();
});
test("full evidence renders as text before unchecked acknowledgement and exactly one confirmation",async()=>{
  const s=setup();await prepare(s);
  assert.ok(s.body.textContent.includes(s.f.detail.data.payloadJSON));
  assert.match(s.body.textContent,/Evidence|evidence/);
  assert.equal(s.ack.checked,false);assert.equal(s.button("Confirm exact recovery").disabled,true);
  await s.button("Confirm exact recovery").dispatch("click");assert.equal(count(s,"CONFIRM"),0);
  await accept(s);await s.button("Confirm exact recovery").dispatch("click");
  assert.equal(count(s,"CONFIRM"),1);
  assert.match(s.body.textContent,/Acceptance recorded/);assert.match(s.body.textContent,/not proof.*delivery/);
  assert.equal(s.ack.checked,false);assert.equal(s.ack.disabled,true);assert.equal(s.timers.size,0);
  await s.button("Confirm exact recovery").dispatch("click");assert.equal(count(s,"CONFIRM"),1);
  assert.equal(flatten(s.body).some(e=>["script","img","iframe"].includes(e.tag)),false);
  s.screen.destroy();
});
test("reject is explicit and never calls CONFIRM",async()=>{
  const s=setup();await prepare(s);await s.button("Reject this preview").dispatch("click");
  assert.equal(count(s,"REJECT"),1);assert.equal(count(s,"CONFIRM"),0);assert.equal(s.ack.checked,false);
  s.screen.destroy();
});
test("local expiry clears acknowledgement and disables confirmation without network",async()=>{
  const s=setup();await prepare(s);await accept(s);
  const before=s.wire.calls.length;s.clock.now=Math.ceil((s.f.preview.data.expiresAt-OFFSET)*1000);
  s.fireTimer();
  assert.equal(s.ack.checked,false);assert.equal(s.button("Confirm exact recovery").disabled,true);
  assert.equal(s.wire.calls.length,before);assert.equal(s.timers.size,0);
  await s.button("Confirm exact recovery").dispatch("click");assert.equal(count(s,"CONFIRM"),0);
  s.screen.destroy();
});
test("reference edit, type edit, disconnect and destroy erase consent and stop timer",async()=>{
  for(const action of ["input","kind","disconnect","destroy"]){
    const s=setup();await prepare(s);await accept(s);const callbacks=[...s.timers.values()];
    if(action==="input"){s.input.value="another";await s.input.dispatch("input");}
    if(action==="kind"){s.kind.value="preview";await s.kind.dispatch("change");}
    if(action==="disconnect")await s.button("Disconnect this screen").dispatch("click");
    if(action==="destroy")s.screen.destroy();
    assert.equal(s.timers.size,0);assert.equal(s.body.textContent,"");
    const before=s.wire.calls.length;for(const cb of callbacks)cb();
    assert.equal(s.wire.calls.length,before);assert.equal(count(s,"CONFIRM"),0);
    s.screen.destroy();
  }
});
test("late prepared preview after edited selection cannot reactivate consent",async()=>{
  const s=setup(),wait=deferred();s.wire.hook=cmd=>cmd==="PREVIEW_REQUEST"?wait.promise:null;
  s.input.value=s.decisionId;const pending=s.button("Prepare exact preview").dispatch("click");await tick();
  s.input.value="new";await s.input.dispatch("input");
  wait.resolve(json(s.f.preview));await pending;
  assert.equal(s.body.textContent,"");assert.equal(s.ack.disabled,true);assert.equal(s.timers.size,0);
  assert.equal(count(s,"CONFIRM"),0);s.screen.destroy();
});
test("double confirmation while reconnect waits sends one request",async()=>{
  const s=setup();await prepare(s);await accept(s);const wait=deferred();
  s.wire.hook=cmd=>cmd==="SESSION"?wait.promise:null;
  const first=s.button("Confirm exact recovery").dispatch("click");await tick();
  await s.button("Confirm exact recovery").dispatch("click");
  assert.equal(s.ack.checked,false);
  s.wire.hook=null;wait.resolve(await s.sessionResponse());await first;
  assert.equal(count(s,"CONFIRM"),1);s.screen.destroy();
});
test("changing reference during final recheck prevents confirmation",async()=>{
  const s=setup();await prepare(s);await accept(s);const wait=deferred();
  s.wire.hook=cmd=>cmd==="READ"?wait.promise:null;
  const first=s.button("Confirm exact recovery").dispatch("click");await tick();
  s.input.value="other";await s.input.dispatch("input");
  const r=structuredClone(s.f.preview);r.code=r.data.code="READ_ONLY";wait.resolve(json(r));await first;
  assert.equal(count(s,"CONFIRM"),0);assert.equal(s.body.textContent,"");s.screen.destroy();
});
test("changed server preview blocks old acknowledgement",async()=>{
  const s=setup();await prepare(s);await accept(s);s.f.preview.data.snapshot.maxCost+=1;
  await s.button("Confirm exact recovery").dispatch("click");
  assert.equal(count(s,"CONFIRM"),0);assert.equal(s.ack.checked,false);assert.equal(s.body.textContent,"");
  s.screen.destroy();
});
test("uncertain confirmation exposes original read only and never re-enables confirmation",async()=>{
  const s=setup({timeoutMs:250});await prepare(s);await accept(s);
  const notice=find(s.root,e=>e.attrs["aria-label"]==="Recovery outcome needs verification");
  assert.equal(notice.hidden,true);
  s.wire.hook=cmd=>cmd==="CONFIRM"?Promise.reject(new Error("PRIVATE_NETWORK")):null;
  await s.button("Confirm exact recovery").dispatch("click");
  assert.equal(count(s,"CONFIRM"),1);assert.match(s.root.textContent,/outcome is uncertain/i);
  assert.equal(s.button("Prepare exact preview").disabled,true);
  assert.equal(s.button("Read original outcome").disabled,false);assert.equal(s.ack.checked,false);
  assert.equal(notice.hidden,false);
  const requests=s.wire.calls.length;
  await s.button("Find original outcome").dispatch("click");
  assert.equal(s.document.focused,s.button("Read original outcome"));
  assert.equal(s.wire.calls.length,requests);
  s.wire.hook=null;await s.button("Read original outcome").dispatch("click");
  assert.match(s.root.textContent,/still pending/i);assert.equal(s.button("Confirm exact recovery").disabled,true);
  assert.equal(count(s,"PREVIEW_REQUEST"),1);assert.equal(count(s,"CONFIRM"),1);
  assert.doesNotMatch(s.root.textContent,/PRIVATE_NETWORK/);s.screen.destroy();
});
test("lost initial preview provides explicit original preparation lookup without resending",async()=>{
  const s=setup();s.wire.hook=cmd=>cmd==="PREVIEW_REQUEST"?Promise.reject(Error("PRIVATE")):null;
  s.input.value=s.decisionId;await s.button("Prepare exact preview").dispatch("click");
  assert.match(s.root.textContent,/Read the original preparation below/);
  assert.equal(s.button("Prepare exact preview").disabled,true);
  assert.equal(s.button("Read original outcome").disabled,true);
  assert.equal(count(s,"PREVIEW_REQUEST"),1);s.screen.destroy();
});
test("account switch at confirmation hides all old evidence and references",async()=>{
  const s=setup();await prepare(s);await accept(s);s.wire.actor="principal-"+"b".repeat(64);s.wire.scope="b".repeat(64);
  await s.button("Confirm exact recovery").dispatch("click");
  assert.equal(count(s,"CONFIRM"),0);assert.equal(s.body.textContent,"");
  assert.doesNotMatch(s.consent.textContent,new RegExp(s.decisionId));s.screen.destroy();
});
test("switch to explicit saved reads clears consent and keeps original bookmarks",async()=>{
  const s=setup();await prepare(s);await accept(s);
  await s.button("Load saved references").dispatch("click");
  assert.equal(s.body.textContent,"");assert.equal(s.ack.checked,false);assert.equal(s.timers.size,0);
  assert.match([...s.storage.data.values()][0],/prep-preview42/);
  assert.equal(s.button("Reopen saved result").disabled,false);
  assert.equal(count(s,"PREVIEW_REQUEST"),1);assert.equal(count(s,"CONFIRM"),0);s.screen.destroy();
});
test("logout invalidates pending consent and hides it even if native logout is unconfirmed",async()=>{
  const s=setup();await prepare(s);await accept(s);
  await s.button("Sign out of IRIS").dispatch("click");
  assert.equal(s.body.textContent,"");assert.equal(s.ack.checked,false);assert.equal(s.timers.size,0);
  assert.equal(s.button("Prepare exact preview").disabled,true);
  assert.equal(count(s,"CONFIRM"),0);s.screen.destroy();
});
test("render failure clears evidence and keeps confirmation disabled",async()=>{
  const s=setup();s.document.failTag="dl";s.input.value=s.decisionId;
  await s.button("Prepare exact preview").dispatch("click");
  assert.equal(s.body.textContent,"");assert.equal(s.ack.checked,false);
  assert.equal(s.button("Confirm exact recovery").disabled,true);assert.equal(s.timers.size,0);
  assert.equal(count(s,"CONFIRM"),0);s.screen.destroy();
});

test("read-only or unavailable native identity cannot enable confirmation",async()=>{
  for(const field of ["canApprove","identity"]){
    const s=setup();s.wire[field]=false;s.input.value=s.decisionId;
    await s.button("Prepare exact preview").dispatch("click");
    assert.equal(count(s,"PREVIEW_REQUEST"),0);assert.equal(s.ack.disabled,true);
    assert.equal(s.body.textContent,"");s.screen.destroy();
  }
});
test("same-session revocation observed locally invalidates ready evidence on next tick",async()=>{
  const s=setup();await prepare(s);await accept(s);s.client.disconnect();s.fireTimer();
  assert.equal(s.body.textContent,"");assert.equal(s.ack.checked,false);
  assert.equal(s.button("Confirm exact recovery").disabled,true);assert.equal(s.timers.size,0);
  assert.doesNotMatch(s.consent.textContent,new RegExp(s.decisionId));s.screen.destroy();
});
test("confirmed logout after review is reported and does not claim mutation rollback",async()=>{
  const s=setup();await prepare(s);await accept(s);
  s.wire.hook=cmd=>cmd==="LOGOUT"?json({code:"SESSION_ENDED"}):null;
  await s.button("Sign out of IRIS").dispatch("click");
  assert.match(s.root.textContent,/IRIS confirmed that the session ended/);
  assert.equal(s.body.textContent,"");assert.equal(s.timers.size,0);
  assert.equal(count(s,"CONFIRM"),0);s.screen.destroy();
});
test("leaving after confirmation has been sent hides late result but preserves reference",async()=>{
  const s=setup();await prepare(s);await accept(s);const wait=deferred();
  s.wire.hook=cmd=>cmd==="CONFIRM"?wait.promise:null;
  const first=s.button("Confirm exact recovery").dispatch("click");await tick();
  assert.equal(count(s,"CONFIRM"),1);
  await s.button("Disconnect this screen").dispatch("click");
  wait.resolve(json({code:"RESULT_UNCERTAIN",data:{}}));await first;
  assert.equal(s.body.textContent,"");assert.equal(s.ack.checked,false);
  assert.match([...s.storage.data.values()][0],/prep-preview42/);assert.equal(count(s,"CONFIRM"),1);
  s.screen.destroy();
});
test("an old cancelled expiry callback cannot duplicate timers after a new review",async()=>{
  const s=setup();await prepare(s);const old=[...s.timers.values()][0];
  s.input.value="changed";await s.input.dispatch("input");
  await prepare(s);assert.equal(s.timers.size,1);
  old();assert.equal(s.timers.size,1);
  s.screen.destroy();assert.equal(s.timers.size,0);
});

test("lost preparation can be read and fenced using explicit screen controls",async()=>{
  const s=setup({timeoutMs:10});s.input.value=s.decisionId;
  s.wire.hook=c=>c==="PREVIEW_REQUEST"?new Promise(()=>{}):null;
  await s.button("Prepare exact preview").dispatch("click");s.wire.hook=null;
  assert.equal(s.button("Prepare exact preview").disabled,true);
  assert.equal(s.button("Read original preparation").disabled,false);
  await s.button("Read original preparation").dispatch("click");
  assert.equal(s.button("Prepare exact preview").disabled,true);assert.equal(count(s,"PREVIEW_REQUEST"),1);
  await s.button("Close unfinished preparation").dispatch("click");
  assert.match(s.root.textContent,/does not cancel a recovery/);
  assert.equal(s.button("Prepare exact preview").disabled,false);
  assert.equal(s.button("Confirm exact recovery").disabled,true);assert.equal(count(s,"CONFIRM"),0);
  s.screen.destroy();
});
test("saved preparation selector reads original evidence without restoring acknowledgement",async()=>{
  const s=setup();await prepare(s);await accept(s);
  await s.button("Load saved preparations").dispatch("click");
  const select=find(s.root,e=>e.attrs["aria-label"]==="Saved preparations");
  assert.equal(select.disabled,false);assert.equal(s.button("Read saved preparation").disabled,true);
  select.value="0";await select.dispatch("change");
  await s.button("Read saved preparation").dispatch("click");
  assert.match(s.root.textContent,/inspection only/);assert.equal(s.ack.disabled,true);assert.equal(s.ack.checked,false);
  assert.equal(s.button("Confirm exact recovery").disabled,true);assert.equal(count(s,"PREVIEW_REQUEST"),1);
  assert.equal(s.button("Read original outcome").disabled,false);
  await s.button("Read original outcome").dispatch("click");
  assert.match(s.root.textContent,/does not prove an earlier/);assert.equal(count(s,"CONFIRM"),0);
  s.screen.destroy();
});

test("preparation lookup cannot interrupt logout or hide its verified completion",async()=>{
  const s=setup();await prepare(s);const pending=deferred();
  s.wire.hook=c=>c==="LOGOUT"?pending.promise:null;
  const logout=s.button("Sign out of IRIS").dispatch("click");
  for(let i=0;i<20&&count(s,"LOGOUT")===0;i++)await tick();
  assert.equal(count(s,"LOGOUT"),1);
  const sessions=count(s,"SESSION");
  assert.equal(s.button("Load saved preparations").disabled,true);
  await s.button("Load saved preparations").dispatch("click");
  assert.equal(count(s,"SESSION"),sessions);
  pending.resolve(json({code:"SESSION_ENDED"}));await logout;
  assert.match(s.root.textContent,/IRIS confirmed that the session ended/);
  assert.equal(s.client.sessionStatus().connected,false);
  assert.equal(s.button("Load saved preparations").disabled,true);s.screen.destroy();
});
test("preparation lookup cannot hide unconfirmed logout",async()=>{
  const s=setup({timeoutMs:10});await prepare(s);
  s.wire.hook=c=>c==="LOGOUT"?new Promise(()=>{}):null;
  await s.button("Sign out of IRIS").dispatch("click");
  assert.match(s.root.textContent,/Session ending was not confirmed/);
  assert.equal(s.button("Load saved preparations").disabled,true);
  const before=s.wire.calls.length;await s.button("Load saved preparations").dispatch("click");
  assert.equal(s.wire.calls.length,before);s.screen.destroy();
});

// Presentation eligibility is distinct from native permission and consent.
function status110(s, status="VALIDATED_PROPOSAL", code="HUMAN_REVIEW_REQUIRED", state="COMPLETED") {
  const d=s.f.detail.data;
  return {code:"EXISTING_DECISION",data:{code:"EXISTING_DECISION",dispatchGranted:false,
    inferenceGranted:false,dispatch_authorized:false,requestId:d.decisionId,orderId:d.context.order_id,
    shipmentVersion:d.context.shipment_version,generation:d.generation,deadlineUS:d.completedUS,
    mode:"WITH_TRIALS",state,...(state==="COMPLETED"?{outcome:{status,code,dispatch_authorized:false}}:{})}};
}
async function read110(s, response) {
  s.wire.hook=command=>command==="DECISION"?json(response):null;
  s.input.value=s.decisionId;
  await find(s.root,e=>e.tag==="form").dispatch("submit");
}

test("observed nonactionable decisions block only new preparation for both roles",async()=>{
  for(const approve of [true,false])for(const [status,code,state] of [
    ["VALIDATED_HOLD","SEMANTICS_AND_HUMAN_REVIEW_REQUIRED","COMPLETED"],
    ["DETERMINISTIC","EXISTING_ACCEPTANCE","COMPLETED"],
    ["DETERMINISTIC","ACCEPTANCE_UNRESOLVED","COMPLETED"],
    ["ERROR","MODEL_ERROR","COMPLETED"],
    ["VALIDATED_PROPOSAL","HUMAN_REVIEW_REQUIRED","IN_FLIGHT"],
  ]){
    const s=setup();s.wire.canApprove=approve;await read110(s,status110(s,status,code,state));
    assert.equal(s.button("Prepare exact preview").disabled,true,status+"/"+approve);
    assert.match(s.consent.textContent,approve?/selected decision.*actionable/i:/does not permit.*prepar/i);
    assert.equal(s.button("Load saved preparations").disabled,false);
    s.button("Prepare exact preview").disabled=false; // handler must also enforce the presentation block
    await s.button("Prepare exact preview").dispatch("click");
    assert.equal(count(s,"PREVIEW_REQUEST"),0);assert.equal(count(s,"DECISION_DETAIL"),0);
    assert.equal(s.ack.disabled,true);assert.equal(count(s,"CONFIRM"),0);s.screen.destroy();
  }
});

test("known reader cannot prepare a proposal; operator still must obtain fresh consent",async()=>{
  for(const approve of [true,false]){
    const s=setup();s.wire.canApprove=approve;await read110(s,status110(s));
    assert.equal(s.button("Prepare exact preview").disabled,!approve);
    assert.equal(s.button("Confirm exact recovery").disabled,true);
    assert.equal(s.ack.checked,false);
    if(approve){await prepare(s);assert.equal(count(s,"PREVIEW_REQUEST"),1);assert.equal(s.ack.checked,false);}
    s.screen.destroy();
  }
});

test("HOLD detail read keeps its preparation block after consuming the detail latch",async()=>{
  const s=setup({name:"hold"});await read110(s,status110(s,"VALIDATED_HOLD","SEMANTICS_AND_HUMAN_REVIEW_REQUIRED"));
  await s.button("Read historical details").dispatch("click");
  assert.equal(s.button("Read historical details").disabled,true);
  assert.equal(s.button("Prepare exact preview").disabled,true);
  assert.equal(s.button("Load saved preparations").disabled,false);s.screen.destroy();
});

test("saved preparation recovery remains usable from a nonactionable decision",async()=>{
  const s=setup();await prepare(s);
  await read110(s,status110(s,"VALIDATED_HOLD","SEMANTICS_AND_HUMAN_REVIEW_REQUIRED"));
  assert.equal(s.button("Prepare exact preview").disabled,true);
  await s.button("Load saved preparations").dispatch("click");
  const select=find(s.root,e=>e.attrs["aria-label"]==="Saved preparations");
  select.value="0";await select.dispatch("change");await s.button("Read saved preparation").dispatch("click");
  assert.match(s.root.textContent,/inspection only/);assert.equal(s.ack.checked,false);
  assert.equal(s.button("Confirm exact recovery").disabled,true);
  assert.equal(count(s,"PREVIEW_REQUEST"),1);assert.equal(count(s,"CONFIRM"),0);s.screen.destroy();
});

test("editing selection removes the old block and a stale HOLD reply cannot restore it",async()=>{
  const s=setup();await read110(s,status110(s,"DETERMINISTIC","EXISTING_ACCEPTANCE"));
  s.input.value="not-yet-read";await s.input.dispatch("input");
  assert.equal(s.button("Prepare exact preview").disabled,false);
  assert.doesNotMatch(s.consent.textContent,/selected decision.*actionable/i);
  const pending=deferred();s.wire.hook=c=>c==="DECISION"?pending.promise:null;
  s.input.value=s.decisionId;const read=find(s.root,e=>e.tag==="form").dispatch("submit");await tick();
  s.input.value="different-new-id";await s.input.dispatch("input");
  pending.resolve(json(status110(s,"VALIDATED_HOLD","SEMANTICS_AND_HUMAN_REVIEW_REQUIRED")));await read;
  assert.equal(s.button("Prepare exact preview").disabled,false);
  assert.doesNotMatch(s.consent.textContent,/selected decision.*actionable/i);s.screen.destroy();
});

test("read error and logout invalidate old presentation eligibility",async()=>{
  const s=setup();await read110(s,status110(s,"DETERMINISTIC","ACCEPTANCE_UNRESOLVED"));
  await read110(s,{code:"EXISTING_DECISION",data:{}});
  assert.doesNotMatch(s.consent.textContent,/selected decision.*actionable/i);
  s.wire.hook=c=>c==="LOGOUT"?json({code:"SESSION_ENDED"}):null;
  await s.button("Sign out of IRIS").dispatch("click");
  assert.equal(s.button("Prepare exact preview").disabled,true);
  assert.doesNotMatch(s.consent.textContent,/selected decision.*actionable/i);s.screen.destroy();
});

test("a changed session cannot reuse old nonactionable display metadata",async()=>{
  const s=setup();await read110(s,status110(s,"DETERMINISTIC","EXISTING_ACCEPTANCE"));
  s.wire.actor="principal-"+"b".repeat(64);s.wire.scope="b".repeat(64);
  await s.client.connect();
  // A later explicit lookup must derive the new session and decision result.
  await read110(s,status110(s));
  assert.equal(s.button("Prepare exact preview").disabled,false);
  assert.equal(s.button("Confirm exact recovery").disabled,true);
  s.screen.destroy();
});

test("preparation gesture rechecks a newly observed reader session without another render",async()=>{
  const s=setup();await read110(s,status110(s));
  assert.equal(s.button("Prepare exact preview").disabled,false);
  s.wire.canApprove=false;await s.client.connect();
  await s.button("Prepare exact preview").dispatch("click");
  assert.equal(s.button("Prepare exact preview").disabled,true);
  assert.match(s.consent.textContent,/does not permit.*prepar/i);
  assert.equal(count(s,"DECISION_DETAIL"),0);assert.equal(count(s,"PREVIEW_REQUEST"),0);
  assert.equal(count(s,"CONFIRM"),0);s.screen.destroy();
});


test("Reader and nonactionable idle hints do not invite a blocked preparation",async()=>{
  for(const reader of [true,false]){
    const s=setup();s.wire.canApprove=!reader;
    await read110(s,status110(s,"DETERMINISTIC","ACCEPTANCE_UNRESOLVED"));
    assert.equal(s.button("Prepare exact preview").disabled,true);
    assert.doesNotMatch(s.consent.textContent,/Choose a completed decision and prepare/);
    assert.match(s.consent.textContent,/remain available for inspection/);
    assert.equal(s.button("Load saved preparations").disabled,false);s.screen.destroy();
  }
});



test("accepted preview read blocks new preparation while original query remains available",async()=>{
  const s=setup();await prepare(s);await accept(s);
  await s.button("Confirm exact recovery").dispatch("click");
  assert.equal(count(s,"CONFIRM"),1);
  s.kind.value="preview";await s.kind.dispatch("change");
  s.input.value=s.f.preview.data.previewId;await s.input.dispatch("input");
  await find(s.root,e=>e.tag==="form").dispatch("submit");
  assert.match(s.root.textContent,/Acceptance recorded/);
  assert.equal(s.button("Prepare exact preview").disabled,true);
  assert.match(s.consent.textContent,/reference.*read or queried/);
  assert.equal(s.button("Confirm exact recovery").disabled,true);
  assert.equal(s.button("Query destination outcome").disabled,false);
  assert.equal(s.button("Load saved preparations").disabled,false);
  s.button("Prepare exact preview").disabled=false;
  await s.button("Prepare exact preview").dispatch("click");
  assert.equal(count(s,"PREVIEW_REQUEST"),1);
  assert.equal(count(s,"CONFIRM"),1);
  s.kind.value="decision";await s.kind.dispatch("change");
  s.input.value="another-decision";await s.input.dispatch("input");
  assert.equal(s.button("Prepare exact preview").disabled,false);
  s.screen.destroy();
});

test("322 workflow section reflects preview and confirmed outcome without another request",async()=>{
  const s=setup();const current=()=>flatten(s.root).filter(e=>e.tag==='li'&&e.attrs['aria-current']==='step').map(e=>e.textContent);
  assert.deepEqual(current(),[]);
  await prepare(s);assert.deepEqual(current(),['02Verification']);
  await accept(s);await s.button('Confirm exact recovery').dispatch('click');
  assert.deepEqual(current(),['03Confirmation']);assert.equal(count(s,'CONFIRM'),1);
  await s.button('Read original outcome').dispatch('click');
  assert.deepEqual(current(),['03Confirmation']);assert.equal(count(s,'CONFIRM'),1);
  await s.button('Disconnect this screen').dispatch('click');assert.deepEqual(current(),[]);
  s.screen.destroy();
});
test("322 section projection never implies delivery or permission",()=>{
  assert.equal(workflowSection({kind:'decision',available:true}),0);
  assert.equal(workflowSection({kind:'detail',available:true}),0);
  assert.equal(workflowSection({kind:'consent',available:true}),1);
  assert.equal(workflowSection({kind:'preview',available:true,operation:null}),1);
  assert.equal(workflowSection({kind:'preview',available:true,operation:{tone:'warning'}}),2);
  assert.equal(workflowSection({kind:'operation',available:true,tone:'success'}),2);
  assert.equal(workflowSection({kind:'operation',available:true,tone:'warning'}),null);
  assert.equal(workflowSection({kind:'preview',available:false}),null);
  assert.equal(workflowSection(null),null);
});
test("322 CSS highlights only the current section, not the first child",()=>{
  const css=readFileSync(new URL('../../src/chronos_web/screen.css',import.meta.url),'utf8');
  assert(css.includes('.chronos-stages li.is-current'));assert(!css.includes('.chronos-stages li:first-child'));
});

test("approval banner stays truthful before and after a recorded acceptance",async()=>{
  const s=setup();await prepare(s);
  const banner="Approval review and recorded results are shown below.";
  assert.ok(s.root.textContent.includes(banner));
  assert.ok(!s.root.textContent.includes("Exact approval review is active below."));
  assert.equal(s.button("Confirm exact recovery").disabled,true);
  assert.equal(count(s,"CONFIRM"),0);
  await accept(s);await s.button("Confirm exact recovery").dispatch("click");
  assert.ok(s.root.textContent.includes(banner));
  assert.ok(!s.root.textContent.includes("Exact approval review is active below."));
  assert.match(s.body.textContent,/Acceptance recorded/);
  assert.equal(s.button("Confirm exact recovery").disabled,true);
  assert.equal(count(s,"CONFIRM"),1);
  s.screen.destroy();
});


test("approval view hides only chat and restores it for every existing read/invalidation exit",async()=>{
  for(const exit of ["input","kind","disconnect","saved","logout"]){
    const s=setup(),chat=find(s.root,e=>e.attrs["aria-label"]==="Case conversation");
    assert.ok(chat);assert.equal(Boolean(chat.hidden),false);
    await prepare(s);assert.equal(chat.hidden,true);
    assert.equal(Boolean(s.body.hidden),false);assert.equal(Boolean(s.consent.hidden),false);
    assert.equal(s.ack.checked,false);assert.equal(count(s,"CONFIRM"),0);
    const before=s.wire.calls.length;
    if(exit==="input")await s.input.dispatch("input");
    if(exit==="kind")await s.kind.dispatch("change");
    if(exit==="disconnect")await s.button("Disconnect this screen").dispatch("click");
    if(exit==="saved")await s.button("Load saved references").dispatch("click");
    if(exit==="logout"){
      s.wire.hook=command=>command==="LOGOUT"?json({code:"SESSION_ENDED"}):null;
      await s.button("Sign out of IRIS").dispatch("click");
    }
    assert.equal(chat.hidden,false,exit);assert.equal(s.ack.checked,false);
    for(const command of ["OPEN","RECORD","CONFIRM"])assert.equal(count(s,command),0);
    if(["input","kind","disconnect"].includes(exit))assert.equal(s.wire.calls.length,before);
    s.screen.destroy();
  }
});

test("hidden chat preserves its original conversation and resumes by explicit read without another question",async()=>{
  const s=setup(),chat=find(s.root,e=>e.attrs["aria-label"]==="Case conversation");
  const digest="b".repeat(64);let conversationId;
  s.wire.hook=(command,request)=>{
    if(command==="SESSION")return json({code:"CONNECTED",authenticated:true,csrf:"c".repeat(64),canRead:true,canApprove:true,canConverse:true,
      identity:{version:1,available:true,actor:ACTOR,actorScope:SCOPE,applicationUrl:"https://chronos.example/csp/chronos/"}});
    if(command==="OPEN"||command==="READ"&&request.conversationId){
      if(command==="OPEN")conversationId=request.conversationId;
      assert.equal(request.conversationId,conversationId);
      return json({code:command==="OPEN"?"CONVERSATION_OPENED":"CONVERSATION_READ",inference_granted:false,dispatch_authorized:false,context_digest:digest,
        conversation:{conversation_id:conversationId,case_id:"case1",shipment_version:1,revision:2,turn_limit:6,
          turns:[{turn_id:"retained-turn",user_text:"Why this choice?",state:"COMPLETED",error:null,response:{
            schema:"chronos.case-conversation.v1",conversation_id:conversationId,turn_id:"retained-turn",context_digest:digest,
            intent:"ANSWER",answer:"Recorded explanation retained.",source_ids:["history"],preference:null,origin:"MODEL_INTERPRETATION",
            dispatch_authorized:false,confirmation_granted:false,requires_new_evaluation:false}}],
          preference_events:[],dispatch_authorized:false,confirmation_granted:false},
        context:{decision_id:s.decisionId,revision:1,conversation_revision:2,generation:"g1",operation_id:null,result_scope:"CURRENT_SHIPMENT",
          evidence:[{id:"history",text:"Recorded proposal.",provenance:"HISTORICAL_DECISION"}]}});
    }
  };
  s.input.value=s.decisionId;await s.button("Open case conversation").dispatch("click");
  assert.equal(Boolean(chat.hidden),false);assert.match(chat.textContent,/Recorded explanation retained/);
  await prepare(s);assert.equal(chat.hidden,true);
  await accept(s);await s.button("Confirm exact recovery").dispatch("click");
  assert.equal(chat.hidden,true);assert.match(s.body.textContent,/Acceptance recorded/);
  const before=s.wire.calls.length;await s.button("Disconnect this screen").dispatch("click");
  assert.equal(chat.hidden,false);assert.equal(s.wire.calls.length,before);
  await s.button("Resume conversation").dispatch("click");
  assert.equal(chat.hidden,false);assert.match(chat.textContent,/Recorded explanation retained/);
  assert.equal(count(s,"OPEN"),1);assert.equal(count(s,"RECORD"),0);assert.equal(count(s,"CONFIRM"),1);
  assert.equal(s.wire.requests.filter(q=>q.command==="READ"&&q.conversationId===conversationId).length,1);
  s.screen.destroy();
});
