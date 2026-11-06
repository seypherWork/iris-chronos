import {createPreparationReferences} from "../../src/chronos_web/preparation-references.mjs";
import test from "node:test";
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {createConsentController} from "../../src/chronos_web/consent-controller.mjs";
import {createChronosClient} from "../../src/chronos_web/client.mjs";
import {createSessionRecoveryReferences} from "../../src/chronos_web/session-references.mjs";
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
function setup({name="proposal",evidence="LIVE",timeoutMs=250,onChange=()=>{},newRequestId}={}){
  const f=fixture(name);f.preview.data.actor=ACTOR;
  const storage={data:new Map(),getItem(k){return this.data.get(k)??null;},setItem(k,v){this.data.set(k,v);}};
  const wire={receipts:new Map(),requests:[],calls:[],hook:null,actor:ACTOR,scope:SCOPE,canRead:true,canApprove:true,identity:true};
  const clock={now:f.ctx.nowUnixMs};
  const client=createChronosClient({basePath:"/csp/chronos",pageUrl:"https://chronos.example/web",timeoutMs,
    fetchImpl:async(url,options)=>{
      const request=options.body?JSON.parse(options.body):{};
      wire.requests.push(request);
      const command=options.method==="GET"?"SESSION":JSON.parse(options.body).command;
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
  const references=createSessionRecoveryReferences({client,storage});
  const preparations=createPreparationReferences({client,storage});
  const controller=createConsentController({client,references,preparations,evidence,now:()=>clock.now,onChange,...(newRequestId?{newRequestId}:{})});
  return {f,storage,wire,clock,client,references,preparations,controller,decisionId:f.detail.data.decisionId};
}
const count=(s,command)=>s.wire.calls.filter(x=>x===command).length;
const ready=async s=>{await s.controller.prepare(s.decisionId);assert.equal(s.controller.snapshot().phase,"READY");return s.controller.snapshot().reviewKey;};

test("prepare displays exact consent only after scoped decision and preview IDs are saved",async()=>{
  const s=setup();assert.equal(s.wire.calls.length,0);
  const key=await ready(s),state=s.controller.snapshot();
  assert.ok(key);assert.equal(state.canConfirm,true);assert.equal(state.view.canConfirm,false);
  assert.match([...s.storage.data.values()][0],/prep-preview42/);
  assert.deepEqual(s.wire.calls,["SESSION","DECISION_DETAIL","PREVIEW_REQUEST","READ"]);
  assert.equal(state.view.binding.actor,ACTOR);
  assert.equal(state.view.binding.snapshot.payload,s.f.detail.data.payloadJSON);
});

test("non-live provenance, absent identity and read-only users cannot create previews",async()=>{
  for(const evidence of ["UNVERIFIED","LOCAL_FIXTURE","REPLAY"]){
    const s=setup({evidence});await s.controller.prepare(s.decisionId);
    assert.equal(s.controller.snapshot().code,"NOT_LIVE");assert.equal(s.wire.calls.length,0);
  }
  for(const changed of ["canApprove","identity"]){
    const s=setup();s.wire[changed]=false;await s.controller.prepare(s.decisionId);
    assert.equal(count(s,"PREVIEW_REQUEST"),0);assert.equal(s.controller.snapshot().canConfirm,false);
  }
});

test("HOLD and ablation never request a preview",async()=>{
  for(const name of ["hold","ablation"]){
    const s=setup({name});await s.controller.prepare(s.decisionId);
    assert.equal(s.controller.snapshot().code,"DECISION_NOT_ACTIONABLE");
    assert.equal(count(s,"PREVIEW_REQUEST"),0);
  }
});

test("missing acknowledgement or wrong review key sends no confirmation",async()=>{
  const s=setup(),key=await ready(s),before=s.wire.calls.length;
  for(const [k,ack]of[[key,false],[key,"true"],["wrong",true]]){
    await assert.rejects(s.controller.confirm(k,ack),e=>e.code==="CONSENT_REQUIRED");
  }
  assert.equal(s.wire.calls.length,before);assert.equal(s.controller.snapshot().canConfirm,true);
});

test("confirm sends once only after rereading original preview then verifies outcome separately",async()=>{
  const s=setup(),key=await ready(s);
  await s.controller.confirm(key,true);
  assert.deepEqual(s.wire.calls,["SESSION","DECISION_DETAIL","PREVIEW_REQUEST","READ","SESSION","READ","CONFIRM","READ"]);
  const state=s.controller.snapshot();
  assert.equal(state.phase,"RESULT");assert.equal(state.code,"CONFIRMATION_RECORDED");
  assert.equal(state.canConfirm,false);assert.equal(state.view.operation.title,"Acceptance recorded");
  assert.match(state.view.operation.summary,/not proof.*delivery/);
  await assert.rejects(s.controller.confirm(key,true),e=>e.code==="CONSENT_REQUIRED");
  assert.equal(count(s,"CONFIRM"),1);
});

test("double click consumes intent before awaiting session refresh",async()=>{
  const s=setup(),key=await ready(s),pending=deferred();
  s.wire.hook=command=>command==="SESSION"?pending.promise:null;
  const first=s.controller.confirm(key,true);
  await assert.rejects(s.controller.confirm(key,true),e=>e.code==="CONSENT_REQUIRED");
  s.controller.disconnect();pending.resolve(json({code:"anything"}));await first;
  assert.equal(count(s,"CONFIRM"),0);
});

test("actor, installation or permission change after review blocks confirmation",async()=>{
  for(const change of [s=>s.wire.actor="principal-"+"b".repeat(64),
    s=>s.wire.scope="b".repeat(64),s=>s.wire.canApprove=false]){
    const s=setup(),key=await ready(s);change(s);
    await s.controller.confirm(key,true);
    assert.equal(count(s,"CONFIRM"),0);assert.equal(s.controller.snapshot().canConfirm,false);
    assert.equal(s.controller.snapshot().view,null);
  }
});

test("changed exact effect on the pre-confirm read is blocked without a new preview",async()=>{
  for(const change of [p=>p.snapshot.offers[p.target].cost+=1,p=>p.snapshot.payload="changed",
    p=>p.snapshotId++,p=>p.generation="changed",p=>p.state="REJECTED"]){
    const s=setup(),key=await ready(s);change(s.f.preview.data);
    await s.controller.confirm(key,true);
    assert.equal(s.controller.snapshot().code,"PREVIEW_CHANGED");
    assert.equal(count(s,"CONFIRM"),0);assert.equal(count(s,"PREVIEW_REQUEST"),1);
  }
});

test("expiry and backwards browser clock disable confirmation without network",async()=>{
  for(const change of [s=>s.clock.now+=60000,s=>s.clock.now-=1]){
    const s=setup(),key=await ready(s),before=s.wire.calls.length;change(s);
    assert.equal(s.controller.snapshot().canConfirm,false);s.controller.tick();
    assert.equal(s.controller.snapshot().phase,"BLOCKED");
    await assert.rejects(s.controller.confirm(key,true),e=>e.code==="CONSENT_REQUIRED");
    assert.equal(s.wire.calls.length,before);
  }
});

test("preview bookmark persistence is verified again immediately before confirm",async()=>{
  const s=setup(),key=await ready(s);
  s.storage.getItem=()=>{throw Error("PRIVATE_STORAGE");};
  await s.controller.confirm(key,true);
  assert.equal(s.controller.snapshot().code,"REFERENCE_NOT_SAVED");
  assert.equal(count(s,"CONFIRM"),0);
  assert.equal(JSON.stringify(s.controller.snapshot()).includes("PRIVATE_STORAGE"),false);
});

test("initial preview write failure never enables confirmation or loses the known ID",async()=>{
  const s=setup();
  const original=s.storage.setItem.bind(s.storage);
  s.storage.setItem=(k,v)=>{if(v.includes("prep-preview42"))throw Error("blocked");original(k,v);};
  await s.controller.prepare(s.decisionId);
  assert.equal(s.controller.snapshot().code,"REFERENCE_NOT_SAVED");
  assert.equal(s.controller.snapshot().previewId,"prep-preview42");
  assert.equal(s.controller.snapshot().canConfirm,false);
  assert.equal(count(s,"CONFIRM"),0);
});

test("lost initial preview reply stays explicit and never fabricates an ID or retries",async()=>{
  const s=setup({timeoutMs:10});s.wire.hook=c=>c==="PREVIEW_REQUEST"?new Promise(()=>{}):null;
  await s.controller.prepare(s.decisionId);
  const state=s.controller.snapshot();
  assert.equal(state.phase,"PREVIEW_UNCERTAIN");assert.equal(state.previewId,"");
  assert.equal(state.decisionId,s.decisionId);assert.equal(count(s,"PREVIEW_REQUEST"),1);
  assert.equal(state.canReadOutcome,false);assert.equal(count(s,"CONFIRM"),0);
  assert.equal([...s.storage.data.values()][0].includes(s.decisionId),true);
});

test("lost confirm reply retains original ID; a pending read never restores consent",async()=>{
  const s=setup({timeoutMs:10}),key=await ready(s);
  s.wire.hook=c=>c==="CONFIRM"?new Promise(()=>{}):null;
  await s.controller.confirm(key,true);
  assert.equal(s.controller.snapshot().phase,"OUTCOME_UNCERTAIN");
  assert.equal(s.controller.snapshot().previewId,"prep-preview42");
  s.wire.hook=null;await s.controller.readOutcome();
  assert.equal(s.controller.snapshot().code,"STILL_PENDING_NO_RETRY");
  assert.equal(s.controller.snapshot().canConfirm,false);
  await assert.rejects(s.controller.confirm(key,true),e=>e.code==="CONSENT_REQUIRED");
  assert.equal(count(s,"CONFIRM"),1);
});

test("HTTP success without confirmed readback is not reported as confirmation",async()=>{
  const s=setup(),key=await ready(s);
  s.wire.hook=c=>c==="CONFIRM"?json({code:"RECHECK_REQUIRED",data:{code:"RECHECK_REQUIRED",dispatchGranted:false}}):null;
  await s.controller.confirm(key,true);
  assert.equal(s.controller.snapshot().code,"STILL_PENDING_NO_RETRY");
  assert.equal(s.controller.snapshot().canConfirm,false);
});

test("wrong operation or generation on readback cannot be displayed as acceptance",async()=>{
  for(const change of [p=>p.operationId="foreign-operation",p=>p.generation="foreign-generation"]){
    const s=setup(),key=await ready(s);
    s.wire.hook=c=>{
      if(c==="READ"&&count(s,"CONFIRM")===1){
        change(s.f.preview.data);const p=structuredClone(s.f.preview);p.code=p.data.code="READ_ONLY";return json(p);
      }return null;
    };
    await s.controller.confirm(key,true);
    assert.equal(s.controller.snapshot().phase,"OUTCOME_UNCERTAIN");
    assert.equal(s.controller.snapshot().code,"OUTCOME_UNAVAILABLE");
    assert.equal(s.controller.snapshot().view,null);
  }
});

test("reject is explicit, consumes intent and reads its own result without confirming",async()=>{
  const s=setup(),key=await ready(s);await s.controller.reject(key);
  assert.equal(s.controller.snapshot().code,"REJECTION_RECORDED");
  assert.equal(count(s,"REJECT"),1);assert.equal(count(s,"CONFIRM"),0);
  assert.equal(count(s,"READ"),3);assert.equal(s.controller.snapshot().canConfirm,false);
});

test("renderer failure and asynchronous renderer cannot proceed to native mutations",async()=>{
  for(const onChange of [state=>{if(state.phase==="READY")throw Error("PRIVATE_RENDER");},
    state=>{if(state.phase==="READY")return Promise.reject(Error("PRIVATE_ASYNC"));}]){
    const s=setup({onChange});await s.controller.prepare(s.decisionId);
    assert.equal(s.controller.snapshot().code,"PRESENTATION_FAILED");
    assert.equal(s.controller.snapshot().canConfirm,false);assert.equal(count(s,"CONFIRM"),0);
    assert.equal(JSON.stringify(s.controller.snapshot()).includes("PRIVATE_"),false);
  }
});

test("disconnect while confirmation waits invalidates its late UI but preserves saved recovery ID",async()=>{
  const s=setup(),key=await ready(s),pending=deferred();
  s.wire.hook=c=>c==="CONFIRM"?pending.promise:null;
  const first=s.controller.confirm(key,true);
  for(let i=0;i<30&&count(s,"CONFIRM")===0;i++)await new Promise(r=>setImmediate(r));
  assert.equal(count(s,"CONFIRM"),1);s.controller.disconnect();
  pending.resolve(json({code:"READBACK_RECORDED",data:{}}));await first;
  assert.equal(s.controller.snapshot().phase,"IDLE");assert.equal(s.controller.snapshot().view,null);
  assert.equal([...s.storage.data.values()][0].includes("prep-preview42"),true);
});

test("scope change during persistence prevents confirmation even if a bookmark write occurred",async()=>{
  const s=setup(),key=await ready(s);
  const original=s.storage.getItem.bind(s.storage);let reads=0;
  s.storage.getItem=k=>{const value=original(k);if(++reads===1)s.client.disconnect();return value;};
  await s.controller.confirm(key,true);
  assert.equal(count(s,"CONFIRM"),0);
  assert.equal(s.controller.snapshot().canConfirm,false);
});

test("expiry while waiting for the pre-confirm read blocks the remote mutation",async()=>{
  const s=setup(),key=await ready(s);
  s.wire.hook=c=>{
    if(c==="READ"){s.clock.now+=60000;const p=structuredClone(s.f.preview);p.code=p.data.code="READ_ONLY";return json(p);}
    return null;
  };
  await s.controller.confirm(key,true);
  assert.equal(s.controller.snapshot().code,"PREVIEW_EXPIRED");assert.equal(count(s,"CONFIRM"),0);
});

test("same actor after re-login cannot bypass native pending-preview session denial",async()=>{
  const s=setup(),key=await ready(s);
  s.wire.hook=c=>c==="READ"?json({code:"PREVIEW_NOT_AVAILABLE",data:{code:"PREVIEW_NOT_AVAILABLE",dispatchGranted:false}}):null;
  await s.controller.confirm(key,true);
  assert.equal(count(s,"CONFIRM"),0);assert.equal(count(s,"PREVIEW_REQUEST"),1);
  assert.equal(s.controller.snapshot().code,"PREVIEW_CHANGED");
});

test("recorded confirmation with unknown or quarantined outcome is never acceptance success",async()=>{
  for(const changed of [op=>{op.state="UNKNOWN";op.reference="";},op=>op.quarantined=true]){
    const s=setup(),key=await ready(s);
    s.wire.hook=c=>{
      if(c==="READ"&&count(s,"CONFIRM")===1){
        changed(s.f.preview.data.operation);const p=structuredClone(s.f.preview);p.code=p.data.code="READ_ONLY";return json(p);
      }return null;
    };
    await s.controller.confirm(key,true);
    assert.equal(s.controller.snapshot().code,"CONFIRMATION_RECORDED");
    assert.notEqual(s.controller.snapshot().view.operation.tone,"success");
    assert.equal(s.controller.snapshot().canConfirm,false);
  }
});

test("confirmed preview without an operation readback stays uncertain",async()=>{
  const s=setup(),key=await ready(s);
  s.wire.hook=c=>{
    if(c==="READ"&&count(s,"CONFIRM")===1){
      const p=structuredClone(s.f.preview);delete p.data.operation;p.code=p.data.code="READ_ONLY";return json(p);
    }return null;
  };
  await s.controller.confirm(key,true);
  assert.equal(s.controller.snapshot().phase,"OUTCOME_UNCERTAIN");
  assert.equal(s.controller.snapshot().code,"OUTCOME_UNAVAILABLE");
});

test("lost rejection reply is queried with the original ID without another rejection",async()=>{
  const s=setup({timeoutMs:10}),key=await ready(s);
  s.wire.hook=c=>c==="REJECT"?new Promise(()=>{}):null;
  await s.controller.reject(key);
  assert.equal(s.controller.snapshot().phase,"OUTCOME_UNCERTAIN");
  s.wire.hook=null;await s.controller.readOutcome();
  assert.equal(s.controller.snapshot().code,"STILL_PENDING_NO_RETRY");
  await assert.rejects(s.controller.reject(key),e=>e.code==="CONSENT_REQUIRED");
  assert.equal(count(s,"REJECT"),1);
});

test("full reference store blocks preview creation before a recovery ID could be lost",async()=>{
  const s=setup();await s.client.connect();
  for(let i=0;i<32;i++)assert.equal(s.references.remember({kind:"decision",id:"prior-"+i}).ok,true);
  await s.controller.prepare(s.decisionId);
  assert.equal(s.controller.snapshot().code,"REFERENCE_NOT_SAVED");
  assert.equal(count(s,"PREVIEW_REQUEST"),0);assert.equal(count(s,"DECISION_DETAIL"),0);
});

test("reentrant disconnect from the confirming render prevents mutation",async()=>{
  let controller;
  const s=setup({onChange:state=>{if(state.phase==="CONFIRMING")controller.disconnect();}});
  controller=s.controller;const key=await ready(s);
  await controller.confirm(key,true);
  assert.equal(controller.snapshot().phase,"IDLE");assert.equal(count(s,"CONFIRM"),0);
});

test("account switch hides original consent references while preserving old scoped bookmarks",async()=>{
  for(const mode of ["confirm","readOutcome","reader-only"]){
    const s=setup({timeoutMs:10}),key=await ready(s),stored=[...s.storage.data];
    if(mode==="readOutcome"){
      s.wire.hook=c=>c==="CONFIRM"?new Promise(()=>{}):null;
      await s.controller.confirm(key,true);s.wire.hook=null;
    }
    s.wire.actor="principal-"+"b".repeat(64);s.wire.scope="b".repeat(64);
    if(mode==="reader-only")s.wire.canApprove=false;
    const beforeConfirm=count(s,"CONFIRM"),beforeRead=count(s,"READ");
    if(mode==="readOutcome")await s.controller.readOutcome();else await s.controller.confirm(key,true);
    const state=s.controller.snapshot();
    assert.equal(state.decisionId,"");assert.equal(state.previewId,"");
    assert.equal(state.view,null);assert.equal(state.canReadOutcome,false);
    assert.equal(count(s,"CONFIRM"),beforeConfirm);assert.equal(count(s,"READ"),beforeRead);
    assert.deepEqual([...s.storage.data],stored);
  }
});

test("revocation during a command and invalid bootstrap hide IDs without erasing recovery bookmarks",async()=>{
  for(const point of ["READ","CONFIRM","INVALID_BOOTSTRAP"]){
    const s=setup(),key=await ready(s),before=[...s.storage.data];
    s.wire.hook=c=>{
      if(c===point)return json({code:"PERMISSION_DENIED",data:{code:"PERMISSION_DENIED",dispatchGranted:false}});
      if(point==="INVALID_BOOTSTRAP"&&c==="SESSION")return json({code:"CONNECTED",authenticated:true,csrf:"invalid"});
      return null;
    };
    await s.controller.confirm(key,true);
    const state=s.controller.snapshot();
    assert.ok(["SESSION_REQUIRED","INVALID_SESSION"].includes(state.code));
    assert.equal(state.decisionId,"");assert.equal(state.previewId,"");
    assert.equal(state.canReadOutcome,false);assert.equal(state.view,null);
    assert.equal(count(s,"CONFIRM"),point==="CONFIRM"?1:0);
    assert.deepEqual([...s.storage.data],before);
  }
});

const receiptFor=(s,request,state="RECORDED")=>({
  code:"PREPARATION_"+state,dispatchGranted:false,canConfirm:false,requestId:request.requestId,
  actor:s.wire.actor,decisionId:request.id,previewId:state==="CLOSED_NO_PREVIEW"?"":"prep-preview42",state
});
test("preparation correlation is saved and verified before sending the first request",async()=>{
  const s=setup({newRequestId:()=>"owned-request"});
  s.wire.hook=(c,r)=>{
    if(c==="PREVIEW_REQUEST"){
      assert.equal(r.requestId,"owned-request");
      assert.deepEqual(s.preparations.list().items,[{requestId:"owned-request",decisionId:s.decisionId}]);
    }
    return null;
  };
  await ready(s);assert.equal(s.controller.snapshot().requestId,"owned-request");
  assert.equal(count(s,"PREVIEW_REQUEST"),1);
});
test("preparation persistence failure blocks network creation without exposing storage errors",async()=>{
  const s=setup();
  const save=s.storage.setItem.bind(s.storage);
  s.storage.setItem=(k,v)=>{if(k.startsWith("chronos.preparations"))throw Error("PRIVATE");save(k,v);};
  await s.controller.prepare(s.decisionId);
  assert.equal(s.controller.snapshot().code,"REFERENCE_NOT_SAVED");
  assert.equal(count(s,"PREVIEW_REQUEST"),0);assert.equal(s.controller.snapshot().canConfirm,false);
  assert.equal(JSON.stringify(s.controller.snapshot()).includes("PRIVATE"),false);
});
test("existing preparation id cannot be reused as a newly approved creation intent",async()=>{
  const s=setup({newRequestId:()=>"collision"});await s.client.connect();
  assert.equal(s.preparations.remember({requestId:"collision",decisionId:s.decisionId}).ok,true);
  await s.controller.prepare(s.decisionId);
  assert.equal(s.controller.snapshot().code,"REFERENCE_NOT_SAVED");assert.equal(count(s,"PREVIEW_REQUEST"),0);
});
test("lost creation followed by NOT_FOUND does not prove absence or enable another preparation",async()=>{
  const s=setup({timeoutMs:10});
  s.wire.hook=c=>c==="PREVIEW_REQUEST"?new Promise(()=>{}):null;
  await s.controller.prepare(s.decisionId);const requestId=s.controller.snapshot().requestId;
  s.wire.hook=null;await s.controller.readPreparation();
  const state=s.controller.snapshot();
  assert.equal(state.code,"PREPARATION_NOT_FOUND");assert.equal(state.phase,"PREPARATION_PENDING");
  assert.equal(state.canPrepare,false);assert.equal(state.canConfirm,false);assert.equal(state.canClosePreparation,true);
  assert.equal(state.requestId,requestId);assert.equal(count(s,"PREVIEW_REQUEST"),1);assert.equal(count(s,"CLOSE_PREPARATION"),0);
  await s.controller.closePreparation();
  assert.equal(s.controller.snapshot().phase,"PREPARATION_CLOSED");
  assert.equal(s.controller.snapshot().canPrepare,true);assert.equal(count(s,"PREVIEW_REQUEST"),1);
  assert.equal(s.wire.receipts.get(requestId).state,"CLOSED_NO_PREVIEW");
});
test("lost recorded preparation recovers its exact preview by reading without resubmission",async()=>{
  const s=setup({timeoutMs:10});
  s.wire.hook=(c,r)=>{
    if(c==="PREVIEW_REQUEST"){s.wire.receipts.set(r.requestId,receiptFor(s,r));return new Promise(()=>{});}
    return null;
  };
  await s.controller.prepare(s.decisionId);s.wire.hook=null;
  await s.controller.readPreparation();
  assert.equal(s.controller.snapshot().phase,"READY");assert.equal(s.controller.snapshot().previewId,"prep-preview42");
  assert.equal(count(s,"PREVIEW_REQUEST"),1);assert.equal(count(s,"CONFIRM"),0);
  assert.equal(s.wire.requests.filter(r=>r.command==="READ").at(-1).id,"prep-preview42");
});
test("started preparation is never confused with a completed preview",async()=>{
  const s=setup();s.wire.hook=(c,r)=>c==="PREVIEW_REQUEST"?json({code:"PREPARATION_STARTED",data:receiptFor(s,r,"STARTED")}):null;
  await s.controller.prepare(s.decisionId);
  assert.equal(s.controller.snapshot().phase,"PREPARATION_PENDING");assert.equal(s.controller.snapshot().canConfirm,false);
  assert.equal(s.controller.snapshot().previewId,"");assert.equal(count(s,"READ"),0);
});
test("receipt actor decision reference grants state and extra fields are strictly checked",async()=>{
  for(const mutate of [
    p=>p.actor="principal-"+"b".repeat(64),p=>p.decisionId="other",p=>p.requestId="other",
    p=>p.dispatchGranted=true,p=>p.canConfirm=true,p=>p.extra="hidden",
    p=>p.previewId="foreign",p=>p.state="UNKNOWN",p=>p.code="PREPARATION_STARTED",
    p=>{p.state="NOT_FOUND";p.code="PREPARATION_NOT_FOUND";}
  ]){
    const s=setup();s.wire.hook=(c,r)=>{
      if(c!=="PREVIEW_REQUEST")return null;
      const p=receiptFor(s,r);mutate(p);return json({code:p.code,data:p});
    };
    await s.controller.prepare(s.decisionId);
    assert.equal(s.controller.snapshot().phase,"PREVIEW_UNCERTAIN");
    assert.equal(s.controller.snapshot().canConfirm,false);assert.equal(count(s,"READ"),0);
  }
});
test("reopened recorded preparation is inspect-only even if its preview remains pending",async()=>{
  const s=setup();await ready(s);const scope=s.preparations.scope(),pair=s.preparations.list().items[0];
  s.controller.disconnect();
  const reopened=createConsentController({client:s.client,references:s.references,preparations:s.preparations,evidence:"LIVE",now:()=>s.clock.now});
  await reopened.listPreparations();
  assert.deepEqual(reopened.snapshot().preparations,[pair]);
  await reopened.reopenPreparation(pair,scope);
  assert.equal(reopened.snapshot().phase,"RECOVERED");assert.equal(reopened.snapshot().canConfirm,false);
  assert.equal(reopened.snapshot().canReject,false);assert.equal(reopened.snapshot().canReadOutcome,true);
  await assert.rejects(reopened.confirm(reopened.snapshot().reviewKey,true),e=>e.code==="CONSENT_REQUIRED");
  await reopened.readOutcome();assert.equal(reopened.snapshot().code,"STILL_PENDING_NO_RETRY");
  await reopened.readPreparation();assert.equal(reopened.snapshot().canConfirm,false);
  assert.equal(count(s,"PREVIEW_REQUEST"),1);assert.equal(count(s,"CONFIRM"),0);
});
test("reopening a saved preparation for another account hides ids and sends no lookup",async()=>{
  const s=setup();await ready(s);const scope=s.preparations.scope(),pair=s.preparations.list().items[0],before=[...s.storage.data];
  s.controller.disconnect();s.wire.actor="principal-"+"b".repeat(64);s.wire.scope="b".repeat(64);
  await s.controller.reopenPreparation(pair,scope);
  assert.equal(s.controller.snapshot().code,"REFERENCE_SCOPE_CHANGED");
  assert.equal(s.controller.snapshot().requestId,"");assert.equal(s.controller.snapshot().decisionId,"");
  assert.equal(count(s,"READ_PREPARATION"),0);assert.deepEqual([...s.storage.data],before);
});
test("unknown confirmation cannot become another confirmation through receipt recovery",async()=>{
  const s=setup({timeoutMs:10}),key=await ready(s);
  s.wire.hook=c=>c==="CONFIRM"?new Promise(()=>{}):null;await s.controller.confirm(key,true);
  assert.equal(s.controller.snapshot().canReadPreparation,false);
  await assert.rejects(s.controller.readPreparation(),e=>e.code==="ORIGINAL_PREPARATION_REQUIRED");
  s.wire.hook=null;await s.controller.listPreparations();
  const state=s.controller.snapshot();await s.controller.reopenPreparation(state.preparations[0],state.preparationScope);
  assert.equal(s.controller.snapshot().phase,"RECOVERED");assert.equal(s.controller.snapshot().canConfirm,false);
  assert.equal(count(s,"CONFIRM"),1);assert.equal(count(s,"PREVIEW_REQUEST"),1);
});
test("close losing the race to recorded creation reads the existing preview without a second creation",async()=>{
  const s=setup({timeoutMs:10});let request;
  s.wire.hook=(c,r)=>{if(c==="PREVIEW_REQUEST"){request=r;return new Promise(()=>{});}return null;};
  await s.controller.prepare(s.decisionId);
  s.wire.receipts.set(request.requestId,receiptFor(s,request));s.wire.hook=null;
  await s.controller.closePreparation();
  assert.equal(s.controller.snapshot().phase,"READY");assert.equal(s.controller.snapshot().previewId,"prep-preview42");
  assert.equal(count(s,"PREVIEW_REQUEST"),1);assert.equal(count(s,"CLOSE_PREPARATION"),1);assert.equal(count(s,"CONFIRM"),0);
});
test("changing account while recovering a receipt suppresses old reference display",async()=>{
  const s=setup({timeoutMs:10});s.wire.hook=c=>c==="PREVIEW_REQUEST"?new Promise(()=>{}):null;
  await s.controller.prepare(s.decisionId);const before=[...s.storage.data];
  s.wire.hook=null;s.wire.actor="principal-"+"b".repeat(64);s.wire.scope="b".repeat(64);
  await s.controller.readPreparation();
  assert.equal(s.controller.snapshot().requestId,"");assert.equal(s.controller.snapshot().decisionId,"");
  assert.equal(count(s,"READ_PREPARATION"),0);assert.deepEqual([...s.storage.data],before);
});

test("a STARTED reservation cannot change or disappear during recovery",async()=>{
  for(const next of ["other","missing","closed-other"]){
    const s=setup();let request;
    s.wire.hook=(c,r)=>{
      if(c==="PREVIEW_REQUEST"){
        request=r;const p=receiptFor(s,r,"STARTED");p.previewId="prep-reserved";
        return json({code:p.code,data:p});
      }
      if(c==="READ_PREPARATION"){
        const p=receiptFor(s,request,next==="missing"?"NOT_FOUND":next==="closed-other"?"CLOSED_NO_PREVIEW":"RECORDED");
        if(next==="missing"){p.decisionId="";p.previewId="";}
        return json({code:p.code,data:p});
      }
      return null;
    };
    await s.controller.prepare(s.decisionId);assert.equal(s.controller.snapshot().canClosePreparation,true);
    await s.controller.readPreparation();
    assert.equal(s.controller.snapshot().code,"PREPARATION_RESPONSE_UNCERTAIN");
    assert.equal(s.controller.snapshot().canConfirm,false);assert.equal(count(s,"READ"),0);
  }
});
test("STARTED can close with the same reserved id but closed state cannot reopen",async()=>{
  const s=setup();let request;
  s.wire.hook=(c,r)=>{
    if(c==="PREVIEW_REQUEST"){request=r;const p=receiptFor(s,r,"STARTED");s.wire.receipts.set(r.requestId,p);return json({code:p.code,data:p});}
    return null;
  };
  await s.controller.prepare(s.decisionId);await s.controller.closePreparation();
  assert.equal(s.controller.snapshot().phase,"PREPARATION_CLOSED");
  s.wire.receipts.set(request.requestId,receiptFor(s,request));
  await s.controller.readPreparation();
  assert.equal(s.controller.snapshot().code,"PREPARATION_RESPONSE_UNCERTAIN");
  assert.equal(s.controller.snapshot().canConfirm,false);
});

test("failed uniqueness check never restores consent by reading a colliding older request",async()=>{
  const s=setup({newRequestId:()=>"prior-request"});await s.client.connect();
  s.preparations.remember({requestId:"prior-request",decisionId:s.decisionId});
  s.wire.receipts.set("prior-request",receiptFor(s,{requestId:"prior-request",id:s.decisionId}));
  await s.controller.prepare(s.decisionId);
  assert.equal(count(s,"PREVIEW_REQUEST"),0);
  await s.controller.readPreparation();
  assert.equal(s.controller.snapshot().phase,"RECOVERED");
  assert.equal(s.controller.snapshot().canConfirm,false);
  await assert.rejects(s.controller.confirm(s.controller.snapshot().reviewKey,true),e=>e.code==="CONSENT_REQUIRED");
  assert.equal(count(s,"CONFIRM"),0);
});


test("reopening a confirmed preparation shows recorded acceptance without restoring consent",async()=>{
  const s=setup(),key=await ready(s);await s.controller.confirm(key,true);
  await s.controller.listPreparations();const listed=s.controller.snapshot();
  await s.controller.reopenPreparation(listed.preparations[0],listed.preparationScope);
  const state=s.controller.snapshot();
  assert.equal(state.phase,"RECOVERED");assert.equal(state.canConfirm,false);assert.equal(state.canReject,false);
  assert.equal(state.view.title,"Confirmation recorded");assert.equal(state.view.operation.title,"Acceptance recorded");
  assert.equal(state.view.operation.available,true);assert.equal(state.reviewKey,"");
  assert.equal(count(s,"PREVIEW_REQUEST"),1);assert.equal(count(s,"CONFIRM"),1);
  await assert.rejects(s.controller.confirm(state.reviewKey,true),e=>e.code==="CONSENT_REQUIRED");
});

test("recovered confirmed outcomes reject missing or mismatched operation evidence",async()=>{
  for(const kind of ["missing","wrong-operation","wrong-digest","wrong-generation"]){
    const s=setup(),key=await ready(s);await s.controller.confirm(key,true);
    if(kind==="missing")delete s.f.preview.data.operation;
    if(kind==="wrong-operation")s.f.preview.data.operation.operationId="other-operation";
    if(kind==="wrong-digest")s.f.preview.data.decisionDigest="b".repeat(64);
    if(kind==="wrong-generation")s.f.preview.data.generation="other-generation";
    await s.controller.listPreparations();const listed=s.controller.snapshot();
    await s.controller.reopenPreparation(listed.preparations[0],listed.preparationScope);
    const state=s.controller.snapshot();
    assert.equal(state.canConfirm,false);assert.equal(state.canReject,false);assert.equal(state.view,null);
    assert.equal(count(s,"CONFIRM"),1);assert.equal(count(s,"PREVIEW_REQUEST"),1);
  }
});
