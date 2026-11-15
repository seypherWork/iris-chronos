import test from "node:test";
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {createChronosClient,RECORDED_QUESTIONS} from "../../src/chronos_web/client.mjs";
import {decisionDetailView} from "../../src/chronos_web/detail.mjs";
import {mountResultScreen} from "../../src/chronos_web/screen.mjs";
import {mountConversationPanel} from "../../src/chronos_web/conversation-panel.mjs";

const base="https://chronos.example/csp/chronos/", hash="b".repeat(64);
const replay=()=>({mode:"RECORDED_FIXTURE",model:"chronos-recorded-fixture-v1",
  replayCorpusSha256:hash,replayFixtureSha256:"c".repeat(64),supportedQuestions:[...RECORDED_QUESTIONS]});
const session=execution=>({code:"CONNECTED",authenticated:true,canRead:true,canApprove:false,
  canConverse:true,csrf:"a".repeat(64),...(execution===undefined?{}:{execution})});
function api(execution){
  const calls=[];
  const client=createChronosClient({basePath:"/csp/chronos",pageUrl:base+"web/index.html",
    fetchImpl:async(url,options)=>{calls.push({url,options});return new Response(JSON.stringify(
      url.endsWith("/session")?session(execution):{code:"READ_ONLY",data:{},traceSessionId:"1"}),
      {headers:{"Content-Type":"application/json"}});}});
  return {client,calls};
}

test("legacy execution remains unverified and cannot add approval authority",async()=>{
  const {client}=api();await client.connect();
  assert.equal(client.sessionExecution().mode,"UNVERIFIED");
  assert.deepEqual(client.sessionStatus(),{connected:true,canRead:true,canApprove:false});
  await assert.rejects(client.confirmPreview("p1"),e=>e.code==="PERMISSION_DENIED");
});

test("recorded session exposes frozen bounded metadata and clears it on disconnect",async()=>{
  const x=replay(),{client}=api(x);await client.connect();
  assert.deepEqual(client.sessionExecution(),x);
  assert.ok(Object.isFrozen(client.sessionExecution()));
  assert.ok(Object.isFrozen(client.sessionExecution().supportedQuestions));
  x.supportedQuestions[0]="changed";
  assert.equal(client.sessionExecution().supportedQuestions[0],RECORDED_QUESTIONS[0]);
  client.disconnect();assert.equal(client.sessionExecution().mode,"UNVERIFIED");
});

test("live and unconfigured modes never inherit recorded hashes or questions",async()=>{
  for(const x of [{mode:"LIVE_MODEL",model:"local-model",replayCorpusSha256:null,replayFixtureSha256:null,supportedQuestions:[]},
    {mode:"NOT_CONFIGURED",model:null,replayCorpusSha256:null,replayFixtureSha256:null,supportedQuestions:[]}]){
    const {client}=api(x);await client.connect();assert.deepEqual(client.sessionExecution(),x);
  }
});

test("malformed mode, corpus, fixture, question bank and HTML metadata fail closed",async()=>{
  const changes=[x=>{x.mode="LIVE_MODEL";},x=>{x.mode="UNVERIFIED";},x=>{x.model="other";},
    x=>{x.replayCorpusSha256="g".repeat(64);},x=>{x.replayFixtureSha256=null;},
    x=>{x.supportedQuestions.pop();},x=>{x.supportedQuestions.reverse();},
    x=>{x.supportedQuestions[0]='<img src=x onerror="alert(1)">';},x=>{x.extra=true;}];
  for(const change of changes){const x=replay();change(x);const {client,calls}=api(x);
    await assert.rejects(client.connect(),e=>e.code==="INVALID_SESSION");
    assert.equal(client.sessionStatus().connected,false);assert.equal(client.sessionExecution().mode,"UNVERIFIED");
    assert.equal(calls.length,1);
  }
  for(const x of [null,[],"RECORDED_FIXTURE"]){const {client}=api(x);await assert.rejects(client.connect(),e=>e.code==="INVALID_SESSION");}
});

test("unsupported recorded question is refused before any POST and keeps the session usable",async()=>{
  const {client,calls}=api(replay());await client.connect();
  for(const text of ["Change my priority",RECORDED_QUESTIONS[0]+" ",'<script>alert("x")</script>']){
    await assert.rejects(client.recordConversation("chat1","decision1",{turnId:"turn1",expectedRevision:1,
      expectedContextDigest:hash,text}),e=>e.code==="RECORDED_INPUT_UNSUPPORTED"&&e.mayHaveApplied===false);
  }
  assert.equal(calls.length,1);assert.equal(client.sessionStatus().connected,true);
});

test("historical recorded attribution labels SDK session without claiming new inference",()=>{
  const all=JSON.parse(readFileSync(new URL("./fixtures/detail41.json",import.meta.url),"utf8"));
  const envelope=structuredClone(all.cases.find(c=>c.name==="proposal").envelope),d=envelope.data;
  d.schema="chronos.review-detail.v3";
  d.attribution={responseContract:"chronos.preference-extraction.v1",interpretationOrigin:"RECORDED_MODEL",selectionOrigin:"DETERMINISTIC_CODE"};
  d.nativeTrace={aiHubSessionId:"22",interopSessionId:"33",namespace:"CHRONOS_LAB",sessionSnapshot:"BEFORE_CHAT"};
  const view=decisionDetailView(envelope,{expectedId:d.decisionId,evidence:"LIVE"});
  assert.equal(view.available,true);assert.equal(view.canConfirm,false);
  const text=JSON.stringify(view);
  assert.match(text,/sealed recorded interpretation/);assert.match(text,/0 fresh inference calls/);
  assert.match(text,/not the original capture's inference session/);
  d.attribution.selectionOrigin="MODEL";
  assert.equal(decisionDetailView(envelope,{expectedId:d.decisionId,evidence:"LIVE"}).available,false);
});

class Element{
  constructor(tag,doc){this.tag=tag;this.ownerDocument=doc;this.children=[];this.attrs={};this.listeners=new Map();this.value="";this._text="";}
  set textContent(v){this._text=String(v);this.children=[];}get textContent(){return this._text+this.children.map(c=>c.textContent).join("");}
  set innerHTML(_){throw Error("HTML forbidden");}appendChild(c){this.children.push(c);return c;}
  replaceChildren(...c){this.children=c;this._text="";}setAttribute(k,v){this.attrs[k]=v;}
  focus(){this.ownerDocument.activeElement=this;}
  addEventListener(k,f){if(!this.listeners.has(k))this.listeners.set(k,[]);this.listeners.get(k).push(f);}
  removeEventListener(k,f){this.listeners.set(k,(this.listeners.get(k)??[]).filter(x=>x!==f));}
  async dispatch(k){for(const f of this.listeners.get(k)??[])await f({preventDefault(){}});}
}
const flat=e=>[e,...e.children.flatMap(flat)];
function panelSetup({screen=false}={}){
  const calls=[],turns=[];let connected=false,sequence=0;
  const packet=()=>({code:"CONVERSATION_READ",inference_granted:false,dispatch_authorized:false,context_digest:hash,
    conversation:{conversation_id:"chat1",case_id:"case1",shipment_version:1,revision:turns.length+1,turn_limit:6,
      turns:structuredClone(turns),preference_events:[],dispatch_authorized:false,confirmation_granted:false},
    context:{decision_id:"decision1",revision:1,conversation_revision:turns.length+1,generation:"gen1",operation_id:null,
      result_scope:"CURRENT_SHIPMENT",evidence:[{id:"record1",text:'Checked evidence with literal "quotes" and <unsafe> text.',provenance:"CURRENT_READ"}]}});
  const client={connect:async()=>{calls.push("SESSION");connected=true;},disconnect:()=>{connected=false;},
    sessionStatus:()=>({connected,canRead:connected,canApprove:false}),
    sessionIdentity:()=>({available:connected,actor:"principal-"+hash,actorScope:hash,applicationUrl:base}),
    sessionExecution:()=>replay(),conversationAvailable:()=>true,
    openConversation:async()=>{calls.push("OPEN");return packet();},readConversation:async()=>packet(),
    recordConversation:async(c,d,f)=>{calls.push("RECORD");turns.push({turn_id:f.turnId,user_text:f.text,state:"COMPLETED",error:null,
      response:{schema:"chronos.case-conversation.v1",conversation_id:c,turn_id:f.turnId,context_digest:hash,intent:"ANSWER",
        answer:'A checked "answer" with <unsafe> literal text.',source_ids:["record1"],preference:null,origin:"MODEL_INTERPRETATION",
        dispatch_authorized:false,confirmation_granted:false,requires_new_evaluation:false}});return packet();},
    readDecision:async()=>({code:"READ_ONLY",data:{}}),readPreview:async()=>({code:"READ_ONLY",data:{}}),
    reconcilePreview:()=>assert.fail("must not reconcile"),logout:async()=>({code:"SESSION_ENDED"})};
  const doc={createElement(tag){return new Element(tag,this);}},root=new Element("div",doc);
  const panel=screen?mountResultScreen(root,{client,evidence:"LIVE"}):mountConversationPanel(root,{client,selection:()=>({kind:"decision",id:"decision1"}),newId:()=>sequence++?"turn"+sequence:"chat1"});
  return{root,panel,calls,button:name=>flat(root).find(n=>n.tag==="button"&&n.textContent===name),
    field:name=>flat(root).find(n=>n.attrs["aria-label"]===name)};
}

test("screen permanently separates real IRIS reads from recorded interpretation without starting work",()=>{
  const s=panelSetup({screen:true});
  const badge=s.field("Agent execution mode");assert.ok(badge);assert.match(badge.textContent,/Recorded interpretation/);
  assert.match(badge.textContent,/current IRIS checks/);assert.match(badge.textContent,/0 fresh inference/);
  assert.deepEqual(s.calls,[]);s.panel.destroy();
});

test("recorded chips only prefill; unsupported text does not record and answers remain plain text",async()=>{
  const s=panelSetup();assert.deepEqual(s.calls,[]);
  await s.button("Open case conversation").dispatch("click");
  for(const q of RECORDED_QUESTIONS)assert.ok(s.button(q));
  await s.button(RECORDED_QUESTIONS[0]).dispatch("click");assert.equal(s.calls.includes("RECORD"),false);
  s.field("Question for Chronos").value='<img src=x onerror="alert(1)">';
  await s.field("Ask about this case").dispatch("submit");
  assert.equal(s.calls.includes("RECORD"),false);assert.match(s.root.textContent,/only the four questions/);
  s.field("Question for Chronos").value=RECORDED_QUESTIONS[0];
  await s.field("Ask about this case").dispatch("submit");
  assert.equal(s.calls.filter(c=>c==="RECORD").length,1);
  assert.match(s.root.textContent,/0 fresh inference calls/);assert.match(s.root.textContent,/<unsafe>/);
  assert.equal(flat(s.root).some(n=>["script","img"].includes(n.tag)),false);s.panel.destroy();
});
