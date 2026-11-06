import test from "node:test";
import assert from "node:assert/strict";
import {createConversationController} from "../../src/chronos_web/conversation-controller.mjs";
import {ChronosClientError} from "../../src/chronos_web/client.mjs";
const clone=x=>JSON.parse(JSON.stringify(x));
const hash="b".repeat(64);
const identity=()=>({available:true,actor:"principal-"+"a".repeat(64),actorScope:"c".repeat(64),applicationUrl:"https://chronos.example/csp/chronos/"});
const wait=()=>{let resolve,reject;const promise=new Promise((r,j)=>{resolve=r;reject=j;});return {promise,resolve,reject};};
function packet(turns=[],digest=hash) {
  return {code:"CONVERSATION_READ",inference_granted:false,dispatch_authorized:false,context_digest:digest,
    conversation:{conversation_id:"chat1",case_id:"case1",shipment_version:1,revision:turns.length+1,
      turn_limit:6,turns,preference_events:[],dispatch_authorized:false,confirmation_granted:false},
    context:{decision_id:"decision1",revision:1,conversation_revision:turns.length+1,generation:"gen1",
      operation_id:null,result_scope:"CURRENT_SHIPMENT",evidence:[{id:"history",text:"Historical choice B.",provenance:"HISTORICAL_DECISION"}]}};
}
function turn(id="turn1",state="COMPLETED",text="Why B?") {
  return {turn_id:id,user_text:text,state,error:null,response:state==="COMPLETED"?{
    schema:"chronos.case-conversation.v1",conversation_id:"chat1",turn_id:id,context_digest:hash,
    intent:"ANSWER",answer:"B was proposed. Acceptance is not delivery.",source_ids:["history"],preference:null,
    origin:"MODEL_INTERPRETATION",dispatch_authorized:false,confirmation_granted:false,requires_new_evaluation:false}:null};
}
function setup(options={}) {
  let connected=false,key=identity(),available=true,number=0,current=packet();const calls=[];
  const client={
    connect:async()=>{calls.push(["connect"]);connected=true;return client.sessionStatus();},
    disconnect:()=>{calls.push(["disconnect"]);connected=false;},
    sessionStatus:()=>({connected,canRead:connected,canApprove:connected}),
    sessionIdentity:()=>key,conversationAvailable:()=>available,
    openConversation:async(...args)=>{calls.push(["OPEN",...args]);return clone(current);},
    readConversation:async(...args)=>{calls.push(["READ",...args]);return clone(current);},
    recordConversation:async(...args)=>{calls.push(["RECORD",...args]);current=packet([turn(args[2].turnId,"COMPLETED",args[2].text)]);return clone(current);},
    confirmPreview:()=>assert.fail("Chat must never approve"),preparePreview:()=>assert.fail("Chat must never prepare approval"),
    ...options.client};
  const controller=createConversationController({client,newId:()=>number++===0?"chat1":"turn"+number,...options.controller});
  return {controller,client,calls,setIdentity:v=>{key=v;},setAvailable:v=>{available=v;},setPacket:v=>{current=v;}};
}
test("mount performs no work; opening is one explicit session check and one OPEN",async()=>{
  const s=setup();assert.deepEqual(s.calls,[]);assert.equal(s.controller.snapshot().canOpen,true);
  await s.controller.open("decision1");assert.deepEqual(s.calls,[["connect"],["OPEN","chat1","decision1"]]);
  assert.equal(s.controller.snapshot().canSend,true);assert.equal(await s.controller.open("another"),false);
});
test("one send is bound to original conversation revision and digest; no approval calls",async()=>{
  const s=setup();await s.controller.open("decision1");await s.controller.send("Why B?");
  const sent=s.calls.find(x=>x[0]==="RECORD");assert.equal(sent[1],"chat1");assert.equal(sent[2],"decision1");
  assert.deepEqual(sent[3],{turnId:"turn2",expectedRevision:1,expectedContextDigest:hash,text:"Why B?"});
  assert.equal(s.controller.snapshot().view.conversation.turns[0].response.dispatch_authorized,false);
  assert.equal(s.calls.filter(x=>x[0]==="RECORD").length,1);
});
test("double send is blocked and no polling or read is started automatically",async()=>{
  const deferred=wait();const s=setup({client:{recordConversation:()=>deferred.promise}});
  await s.controller.open("decision1");const first=s.controller.send("Why B?");
  assert.equal(await s.controller.send("Again"),false);assert.equal(s.controller.snapshot().canClose,false);
  deferred.resolve(packet([turn("turn2","PROCESSING")]));await first;
  assert.equal(s.controller.snapshot().phase,"PENDING");assert.equal(s.controller.snapshot().canSend,false);
  assert.equal(s.calls.some(x=>x[0]==="READ"),false);
});
test("lost record keeps original turn; empty read cannot release an unseen late request",async()=>{
  let attempts=0;const s=setup({client:{recordConversation:async()=>{attempts++;throw new ChronosClientError("REQUEST_TIMEOUT");}}});
  await s.controller.open("decision1");await s.controller.send("Why B?");
  assert.equal(s.controller.snapshot().phase,"UNCERTAIN");assert.equal(s.controller.snapshot().turnId,"turn2");
  await s.controller.read();assert.equal(s.controller.snapshot().phase,"UNCERTAIN");
  assert.equal(s.controller.snapshot().turnId,"turn2");assert.equal(s.controller.snapshot().canSend,false);
  assert.equal(s.controller.snapshot().canClose,false);assert.equal(attempts,1);
  s.setPacket(packet([turn("turn2")]));await s.controller.read();assert.equal(s.controller.snapshot().phase,"READY");
  assert.equal(s.controller.snapshot().canSend,true);assert.equal(attempts,1);
  assert.deepEqual(s.calls.filter(x=>x[0]==="READ"),[["READ","chat1","decision1"],["READ","chat1","decision1"]]);
});
test("lost OPEN only allows reading the same ID, never reopening as automatic recovery",async()=>{
  const s=setup({client:{openConversation:async()=>{throw new ChronosClientError("TRANSPORT_UNAVAILABLE");}}});
  await s.controller.open("decision1");assert.equal(s.controller.snapshot().canOpen,false);
  assert.equal(await s.controller.open("decision1"),false);await s.controller.read();
  assert.equal(s.controller.snapshot().conversationId,"chat1");assert.equal(s.controller.snapshot().phase,"READY");
});
test("late answer after deactivation cannot restore transcript or enable send",async()=>{
  const deferred=wait();const s=setup({client:{recordConversation:()=>deferred.promise}});
  await s.controller.open("decision1");const pending=s.controller.send("Why B?");s.controller.deactivate();
  deferred.resolve(packet([turn("turn2")]));await pending;
  assert.equal(s.controller.snapshot().view,null);assert.equal(s.controller.snapshot().canSend,false);
  assert.equal(s.controller.snapshot().conversationId,"");assert.equal(s.controller.snapshot().phase,"UNCERTAIN");
});
test("changed actor or installation hides former references without a native read",async()=>{
  for (const delta of [{actor:"principal-"+"d".repeat(64)},{actorScope:"e".repeat(64)},
      {applicationUrl:"https://other.example/csp/chronos/"}]) {
    const s=setup();await s.controller.open("decision1");s.setIdentity({...identity(),...delta});await s.controller.read();
    const snapshot=s.controller.snapshot();assert.equal(snapshot.code,"REFERENCE_SCOPE_CHANGED");
    assert.equal(snapshot.view,null);assert.equal(snapshot.conversationId,"");assert.equal(snapshot.decisionId,"");
    assert.equal(s.calls.some(x=>x[0]==="READ"),false);
  }
});
test("revoked capability disables sends and rejects opening before OPEN",async()=>{
  const s=setup();s.setAvailable(false);await s.controller.open("decision1");
  assert.equal(s.calls.some(x=>x[0]==="OPEN"),false);assert.equal(s.controller.snapshot().canSend,false);
  s.setAvailable(true);await s.controller.open("decision1");s.setAvailable(false);
  assert.equal(await s.controller.send("Why B?"),false);assert.equal(s.calls.some(x=>x[0]==="RECORD"),false);
});
test("invalid user text and generated identifiers never reach record",async()=>{
  const s=setup();await s.controller.open("decision1");
  for (const text of ["", " ","é".repeat(1025),"\u0000","\ud800",{}]) assert.equal(await s.controller.send(text),false);
  assert.equal(s.calls.some(x=>x[0]==="RECORD"),false);
  const bad=setup({controller:{newId:()=>"../bad"}});await bad.controller.open("decision1");
  assert.equal(bad.calls.some(x=>x[0]==="OPEN"),false);
});
test("renderer failure blocks outgoing mutation and does not expose private errors",async()=>{
  let fail=false;const s=setup({controller:{onChange:()=>{if(fail)throw Error("PRIVATE_SENTINEL");}}});
  await s.controller.open("decision1");fail=true;await s.controller.send("Why B?");
  assert.equal(s.calls.some(x=>x[0]==="RECORD"),false);assert.equal(s.controller.snapshot().canSend,false);
  assert.equal(s.controller.snapshot().code,"PRESENTATION_FAILED");
  assert.equal(JSON.stringify(s.controller.snapshot()).includes("PRIVATE_SENTINEL"),false);
});
test("snapshots cannot mutate private context or transcript used by the next send",async()=>{
  const s=setup();await s.controller.open("decision1");const v=s.controller.snapshot();v.view.context_digest="e".repeat(64);
  v.view.conversation.revision=6;await s.controller.send("Why B?");
  const fields=s.calls.find(x=>x[0]==="RECORD")[3];assert.equal(fields.expectedRevision,1);assert.equal(fields.expectedContextDigest,hash);
});
test("stale conversation revisions and changed completed turns cannot replace history",async()=>{
  const s=setup();await s.controller.open("decision1");await s.controller.send("Why B?");
  s.setPacket(packet());await s.controller.read();assert.equal(s.controller.snapshot().view,null);
  assert.equal(s.controller.snapshot().canSend,false);
  const changed=turn("turn2");changed.response.answer="Changed silently";s.setPacket(packet([changed]));
  await s.controller.read();assert.equal(s.controller.snapshot().view,null);
});
test("new evidence digest never relabels historical answer as current",async()=>{
  const s=setup();await s.controller.open("decision1");await s.controller.send("Why B?");
  s.setPacket(packet([turn("turn2")],"d".repeat(64)));await s.controller.read();
  const v=s.controller.snapshot().view;assert.equal(v.context_digest,"d".repeat(64));
  assert.equal(v.conversation.turns[0].response.context_digest,hash);
});
test("turn limit, explicit close and destroyed controller do not invoke a model",async()=>{
  const s=setup();await s.controller.open("decision1");s.setPacket(packet(Array.from({length:6},(_,i)=>turn("t"+i))));
  await s.controller.read();assert.equal(s.controller.snapshot().canSend,false);assert.equal(s.controller.snapshot().canRead,true);
  assert.equal(s.controller.close(),true);assert.equal(s.controller.snapshot().conversationId,"");
  s.controller.destroy();const before=s.calls.length;await s.controller.open("decision1");await s.controller.read();
  assert.equal(s.calls.length,before);assert.equal(s.controller.snapshot().canOpen,false);
});

test("identity changes hide all transcript and references before reconnect or renderer notification",async()=>{
  const seen=[];const s=setup({controller:{onChange:v=>seen.push(v)}});
  await s.controller.open("decision1");await s.controller.send("Why B?");
  s.setIdentity({...identity(),actor:"principal-"+"f".repeat(64)});
  const hidden=s.controller.snapshot();assert.equal(hidden.view,null);
  for(const key of ["conversationId","decisionId","turnId"])assert.equal(hidden[key],"");
  seen.length=0;await s.controller.read();
  for(const v of seen){assert.equal(v.view,null);assert.equal(v.conversationId,"");assert.equal(v.decisionId,"");}
  assert.equal(s.calls.some(x=>x[0]==="READ"),false);
});
test("synchronous renderer disposal or deactivation cancels each next IO boundary",async()=>{
  for(const phase of ["CONNECTING","OPENING","READING","SENDING"]){
    for(const method of ["destroy","deactivate"]){
      let armed=false,s;
      s=setup({controller:{onChange:v=>{if(armed && v.phase===phase){armed=false;s.controller[method]();}}}});
      if(["READING","SENDING"].includes(phase))await s.controller.open("decision1");
      const before=s.calls.length;armed=true;
      const ok=phase==="SENDING"?await s.controller.send("Why B?"):phase==="READING"?await s.controller.read():await s.controller.open("decision1");
      assert.equal(ok,false,phase+method);
      const calls=s.calls.slice(before);
      assert.equal(calls.some(x=>["OPEN","READ","RECORD"].includes(x[0])),false,phase+method);
      if(phase==="CONNECTING")assert.equal(calls.some(x=>x[0]==="connect"),false);
      assert.equal(s.controller.snapshot().view,null);assert.equal(s.controller.snapshot().canSend,false);
    }
  }
});
test("renderer identity switch at dispatch boundary never sends old account references",async()=>{
  for(const phase of ["OPENING","READING","SENDING"]){
    let armed=false,s;
    s=setup({controller:{onChange:v=>{if(armed && v.phase===phase)s.setIdentity({...identity(),actorScope:"f".repeat(64)});}}});
    if(phase!=="OPENING")await s.controller.open("decision1");
    const before=s.calls.length;armed=true;
    if(phase==="SENDING")await s.controller.send("Why B?");else if(phase==="READING")await s.controller.read();else await s.controller.open("decision1");
    assert.equal(s.calls.slice(before).some(x=>["OPEN","READ","RECORD"].includes(x[0])),false);
    assert.equal(s.controller.snapshot().view,null);assert.equal(s.controller.snapshot().conversationId,"");
  }
});

test("a bound local RECORD rejection can recover by read without an impossible pending turn",async()=>{
  for(const code of ["REQUEST_IN_PROGRESS","SESSION_REQUIRED","CONVERSATION_UNAVAILABLE","INVALID_REQUEST"]){
    let attempts=0;
    const s=setup({client:{recordConversation:async(c,d,f)=>{attempts++;const e=new ChronosClientError(code,{command:"CONVERSATION_RECORD",id:c,mayHaveApplied:false});e.decisionId=d;e.turnId=f.turnId;throw e;}}});
    await s.controller.open("decision1");assert.equal(await s.controller.send("Why B?"),false);
    assert.equal(s.controller.snapshot().phase,"ERROR");assert.equal(s.controller.snapshot().canClose,true);
    await s.controller.read();assert.equal(s.controller.snapshot().phase,"READY");
    assert.equal(s.controller.snapshot().canSend,true);assert.equal(attempts,1);
  }
});
test("unbound, attempted or generic local-looking errors never release an uncertain RECORD",async()=>{
  for(const fault of ["attempted","other-turn","other-decision","other-conversation","generic","transport"]){
    const s=setup({client:{recordConversation:async(c,d,f)=>{
      if(fault==="generic")throw Error("REQUEST_IN_PROGRESS");
      const e=new ChronosClientError(fault==="transport"?"REQUEST_TIMEOUT":"REQUEST_IN_PROGRESS",{command:"CONVERSATION_RECORD",id:fault==="other-conversation"?"foreign":c,mayHaveApplied:fault==="attempted"});
      e.decisionId=fault==="other-decision"?"foreign":d;e.turnId=fault==="other-turn"?"foreign":f.turnId;throw e;
    }}});
    await s.controller.open("decision1");await s.controller.send("Why B?");await s.controller.read();
    assert.equal(s.controller.snapshot().phase,"UNCERTAIN",fault);assert.equal(s.controller.snapshot().canClose,false,fault);
  }
});
