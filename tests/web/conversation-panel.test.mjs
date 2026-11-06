import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import {mountConversationPanel} from "../../src/chronos_web/conversation-panel.mjs";
import {mountResultScreen} from "../../src/chronos_web/screen.mjs";
import {ChronosClientError} from "../../src/chronos_web/client.mjs";
class Element {
  constructor(tag,doc){this.tag=tag;this.ownerDocument=doc;this.children=[];this.attrs={};this.listeners=new Map();this.value="";this._text="";}
  set textContent(v){this._text=String(v);this.children=[];}get textContent(){return this._text+this.children.map(c=>c.textContent).join("");}
  set innerHTML(_){throw Error("HTML forbidden");}
  appendChild(c){this.children.push(c);return c;}replaceChildren(...c){this.children=c;this._text="";}
  setAttribute(k,v){this.attrs[k]=v;}focus(){this.ownerDocument.focused=this;this.ownerDocument.activeElement=this;}
  addEventListener(k,f){if(!this.listeners.has(k))this.listeners.set(k,[]);this.listeners.get(k).push(f);}
  removeEventListener(k,f){this.listeners.set(k,(this.listeners.get(k)??[]).filter(x=>x!==f));}
  async dispatch(k){for(const f of this.listeners.get(k)??[])await f({preventDefault(){}});}
}
const flat=e=>[e,...e.children.flatMap(flat)];
const deferred=()=>{let resolve;const promise=new Promise(r=>resolve=r);return {resolve,promise};};
const hash="b".repeat(64);
function setup({screen=false,mode="LIVE"}={}){
  let connected=false,actor="principal-"+"a".repeat(64),available=true,sequence=0;
  const calls=[],wire={hold:null,fail:false,digest:hash,answer:"B met the delivery deadline within the budget. Acceptance is not delivery.",
    intent:"ANSWER",source:"B cost 6 units; budget 8 units.",turns:[],conv:"chat1",decision:"decision1",state:"COMPLETED"};
  const packet=()=>({code:"CONVERSATION_READ",inference_granted:false,dispatch_authorized:false,context_digest:wire.digest,
    conversation:{conversation_id:wire.conv,case_id:"case1",shipment_version:1,revision:wire.turns.length+1,turn_limit:6,
      turns:structuredClone(wire.turns),preference_events:[],dispatch_authorized:false,confirmation_granted:false},
    context:{decision_id:wire.decision,revision:1,conversation_revision:wire.turns.length+1,generation:"gen1",operation_id:null,
      result_scope:"CURRENT_SHIPMENT",evidence:[{id:"original-choice",text:wire.source,provenance:"HISTORICAL_DECISION"}]}});
  const client={
    connect:async()=>{calls.push("SESSION");connected=true;return client.sessionStatus();},
    disconnect:()=>{calls.push("DISCONNECT");connected=false;},
    sessionStatus:()=>({connected,canRead:connected,canApprove:connected}),
    sessionIdentity:()=>({available:connected,actor,actorScope:"c".repeat(64),applicationUrl:"https://chronos.example/csp/chronos/"}),
    conversationAvailable:()=>available,
    openConversation:async(c,d)=>{calls.push("OPEN");wire.conv=c;wire.decision=d;return packet();},
    readConversation:async()=>{calls.push("READ");return packet();},
    recordConversation:async(c,d,f)=>{
      calls.push("RECORD");if(wire.hold)return wire.hold.promise;if(wire.fail)throw new ChronosClientError("REQUEST_TIMEOUT");
      wire.turns.push({turn_id:f.turnId,user_text:f.text,state:wire.state,error:wire.error??null,response:wire.state==="COMPLETED"?{
        schema:"chronos.case-conversation.v1",conversation_id:c,turn_id:f.turnId,context_digest:wire.digest,intent:wire.intent,
        answer:wire.answer,source_ids:["original-choice"],preference:wire.intent==="PREFERENCE_PROPOSAL"?"EARLIEST_ALLOWED":null,
        origin:"MODEL_INTERPRETATION",dispatch_authorized:false,confirmation_granted:false,requires_new_evaluation:wire.intent==="PREFERENCE_PROPOSAL"}:null});
      return packet();
    },
    readDecision:async()=>{calls.push("DECISION");throw new ChronosClientError("PERMISSION_DENIED");},
    readPreview:async()=>{calls.push("PREVIEW");throw new ChronosClientError("PERMISSION_DENIED");},
    reconcilePreview:()=>assert.fail("Chat cannot reconcile"),
    logout:async()=>{connected=false;calls.push("LOGOUT");return {code:"SESSION_ENDED"};},
  };
  const doc={createElement(tag){if(this.failTag===tag){this.failTag=null;throw Error("PRIVATE_RENDER_ERROR");}return new Element(tag,this);}};
  const root=new Element("div",doc),chosen={kind:"decision",id:"decision1"};
  const panel=screen?mountResultScreen(root,{client,evidence:mode}):mountConversationPanel(root,{client,selection:()=>chosen,newId:()=>sequence++?"turn"+sequence:"chat1"});
  const button=name=>flat(root).find(e=>e.tag==="button"&&e.textContent===name);
  const field=name=>flat(root).find(e=>e.attrs["aria-label"]===name);
  return {root,doc,client,calls,wire,panel,chosen,packet,button,field,setActor:v=>{actor=v;},setAvailable:v=>{available=v;},
    async open(){if(screen)field("Existing reference").value="decision1";await button("Open case conversation").dispatch("click");},
    async ask(text="Why B?"){field("Question for Chronos").value=text;await field("Ask about this case").dispatch("submit");}};
}
test("panel mount is offline; suggestions only prefill; one submit sends one record",async()=>{
  const s=setup();assert.deepEqual(s.calls,[]);assert.equal(s.button("Ask Chronos").disabled,true);
  await s.open();await s.button("Why was this decision made?").dispatch("click");assert.equal(s.calls.includes("RECORD"),false);
  await s.ask();assert.equal(s.calls.filter(x=>x==="RECORD").length,1);
  assert.match(s.root.textContent,/Model interpretation/);assert.match(s.root.textContent,/Historical decision/);
  assert.match(s.root.textContent,/6 units/);s.panel.destroy();
});

test("rejected questions explain the verified failure category without retrying or exposing raw errors",async()=>{
  const cases=[
    ["MODEL_NOT_STARTED",/did not start a model call/],
    ["CONTEXT_CHANGED",/could not confirm that the case context still matched/],
    ["PROVIDER_REFUSED",/provider declined to answer/],
    ["COMPLETION_REJECTED",/could not validate the reply/],
    ["PRIVATE_DETAIL_SHOULD_NOT_BE_DISPLAYED",/could not produce an accepted answer/],
    ["constructor",/could not produce an accepted answer/]
  ];
  for(const [error,message] of cases){
    const s=setup();s.wire.state="REJECTED";s.wire.error=error;
    await s.open();await s.ask();
    assert.match(s.root.textContent,message);
    assert.equal(s.root.textContent.includes(error),false);
    assert.deepEqual(s.calls,["SESSION","OPEN","RECORD"]);
    s.panel.destroy();
  }
});

test("an uncertain reply cannot be presented as a definitive refusal",async()=>{
  const s=setup();s.wire.state="UNCERTAIN";s.wire.error="PROVIDER_OUTCOME_UNCERTAIN";
  await s.open();await s.ask();
  assert.match(s.root.textContent,/Answer pending or uncertain/);
  assert.equal(s.root.textContent.includes("provider declined"),false);
  assert.equal(s.button("Ask Chronos").disabled,true);
  await s.ask("Try again");
  assert.equal(s.calls.filter(x=>x==="RECORD").length,1);
  s.panel.destroy();
});
test("all model and evidence content is literal text; no links, HTML or actions are generated",async()=>{
  const s=setup();s.wire.answer='<img src=x onerror="alert(1)"> https://attacker.example';s.wire.source='<script>dispatch()</script>';
  await s.open();await s.ask('<b>Why B?</b>');
  assert.match(s.root.textContent,/<img src=x/);assert.match(s.root.textContent,/<script>/);
  assert.equal(flat(s.root).some(e=>["img","script","a","iframe"].includes(e.tag)),false);s.panel.destroy();
});
test("old answer citations are never associated with new current evidence",async()=>{
  const s=setup();await s.open();await s.ask();s.wire.digest="d".repeat(64);s.wire.source="NEW_EVIDENCE_SENTINEL";
  await s.button("Read original conversation").dispatch("click");
  assert.match(s.root.textContent,/earlier evidence snapshot/);assert.equal(s.root.textContent.includes("NEW_EVIDENCE_SENTINEL"),false);s.panel.destroy();
});
test("preferences and approval questions only explain separate actions",async()=>{
  for(const intent of ["PREFERENCE_PROPOSAL","APPROVAL_REDIRECT"]){
    const s=setup();s.wire.intent=intent;await s.open();await s.ask("Please send it");
    assert.match(s.root.textContent,intent==="PREFERENCE_PROPOSAL"?/No preference has been applied/:/Exact human approval cannot override/);
    assert.deepEqual(s.calls,["SESSION","OPEN","RECORD"]);s.panel.destroy();
  }
});
test("lost reply blocks another question; empty original read cannot release a late request",async()=>{
  const s=setup();await s.open();s.wire.fail=true;await s.ask();
  assert.equal(s.button("Ask Chronos").disabled,true);assert.equal(s.button("Close conversation view").disabled,true);
  await s.button("Read original conversation").dispatch("click");assert.equal(s.button("Ask Chronos").disabled,true);
  assert.equal(s.calls.filter(x=>x==="RECORD").length,1);s.panel.destroy();
});
test("deactivation and destruction hide late answers and erase the draft",async()=>{
  for(const action of ["deactivate","destroy"]){
    const s=setup();await s.open();s.wire.hold=deferred();const sent=s.ask();
    s.field("Question for Chronos").value="PRIVATE_DRAFT";s.panel[action]();s.wire.hold.resolve(s.packet());await sent;
    assert.equal(s.root.textContent.includes("PRIVATE_DRAFT"),false);assert.equal(s.root.textContent.includes("6 units"),false);
    if(action==="deactivate")assert.equal(s.field("Question for Chronos").value,"");s.panel.destroy();
  }
});
test("render failure clears partial transcript and blocks sending",async()=>{
  const s=setup();await s.open();s.doc.failTag="details";await s.ask();
  assert.equal(s.field("Conversation transcript").textContent,"");assert.equal(s.button("Ask Chronos").disabled,true);
  assert.equal(s.root.textContent.includes("PRIVATE_RENDER_ERROR"),false);s.panel.destroy();
});
test("invalid selections and oversized multibyte input make no outgoing request",async()=>{
  const s=setup();s.chosen.kind="operation";await s.open();assert.deepEqual(s.calls,[]);
  s.chosen.kind="decision";await s.open();await s.ask("é".repeat(1025));assert.equal(s.calls.includes("RECORD"),false);s.panel.destroy();
});
test("account change removes former transcript before reconnect rendering",async()=>{
  const s=setup();await s.open();await s.ask();s.field("Question for Chronos").value="PREVIOUS_ACTOR_PRIVATE_DRAFT";s.setActor("principal-"+"f".repeat(64));s.panel.setAvailable(true);
  assert.equal(s.field("Question for Chronos").value,"");
  assert.equal(s.field("Conversation transcript").textContent,"");await s.button("Read original conversation").dispatch("click");
  assert.equal(s.calls.includes("READ"),false);assert.equal(s.root.textContent.includes("Decision: decision1"),false);s.panel.destroy();
});
test("screen exposes chat only in LIVE; mount still sends no request",()=>{
  for(const mode of ["LIVE","REPLAY","LOCAL_FIXTURE","UNVERIFIED"]){
    const s=setup({screen:true,mode});assert.equal(Boolean(s.field("Case conversation")),mode==="LIVE");
    assert.deepEqual(s.calls,[]);s.panel.destroy();
  }
});
test("screen reference edits and logout invalidate pending chat and hide its late answer",async()=>{
  for(const action of ["edit","logout"]){
    const s=setup({screen:true});await s.open();s.wire.hold=deferred();const pending=s.ask();
    assert.equal(s.button("Read existing result").disabled,true);
    if(action==="edit"){s.field("Existing reference").value="decision2";await s.field("Existing reference").dispatch("input");}
    else await s.button("Sign out of IRIS").dispatch("click");
    s.wire.hold.resolve(s.packet());await pending;
    assert.equal(s.field("Conversation transcript").textContent,"");assert.equal(s.button("Ask Chronos").disabled,true);
    assert.equal(s.calls.filter(x=>x==="RECORD").length,1);s.panel.destroy();
  }
});

const groundedPackets=JSON.parse(fs.readFileSync(new URL('./fixtures/grounded256.json',import.meta.url),'utf8')).cases;
async function groundedPanel(topic='DECISION',mutate=()=>{}){
  const s=setup(),p=structuredClone(groundedPackets.find(x=>x.topic===topic).packet);
  s.chosen.id=p.context.decision_id;mutate(p);
  s.client.openConversation=async id=>{
    p.conversation.conversation_id=id;
    for(const turn of p.conversation.turns)turn.response.conversation_id=id;
    return p;
  };
  await s.open();return s;
}
test('C2 panel distinguishes host evidence from model interpretation and original selection',async()=>{
  const s=await groundedPanel();
  assert.match(s.root.textContent,/Explanation from checked case records/);
  assert.match(s.root.textContent,/question interpreted by the model/);
  assert.match(s.root.textContent,/Original selection snapshot/);
  assert.match(s.root.textContent,/Recorded simulations/);
  assert.equal(s.root.textContent.includes('Final validation snapshot'),false);
  s.panel.destroy();
});
test('archived C2 sources remain visible without substituting current evidence',async()=>{
  const s=await groundedPanel('DECISION',p=>{
    p.context_digest='f'.repeat(64);p.context.evidence[0].text='NEW_EVIDENCE_SENTINEL';
  });
  assert.match(s.root.textContent,/Archived evidence for this answer/);
  assert.match(s.root.textContent,/Original selection snapshot/);
  assert.equal(s.root.textContent.includes('NEW_EVIDENCE_SENTINEL'),false);s.panel.destroy();
});
test('ablation sources do not claim that simulations were executed',async()=>{
  const s=await groundedPanel('COMPARISON',p=>{
    const source=p.conversation.turns[0].response.sources.find(x=>x.id==='finish');
    source.trial_mode='WITHOUT_TRIALS_ABLATION';source.receipt.selection_basis='FRESH_FINISH';
  });
  assert.match(s.root.textContent,/Final validation snapshot/);
  assert.match(s.root.textContent,/Analytical estimates without executed simulations/);
  assert.equal(s.root.textContent.includes('Recorded simulations'),false);s.panel.destroy();
});
test('C2 preference remains unadopted and UNKNOWN keeps its explicit boundary',async()=>{
  for(const topic of ['PREFERENCE_CHANGE','OPERATION_STATUS']){
    const s=await groundedPanel(topic);
    assert.match(s.root.textContent,topic==='PREFERENCE_CHANGE'?/No preference has been applied/:/UNKNOWN/);
    if(topic==='PREFERENCE_CHANGE'){
      assert.match(s.root.textContent,/Model-interpreted preference/);
      assert.match(s.root.textContent,/not evidence of a recorded change/);
      assert.equal(s.root.textContent.includes('Explanation from checked case records'),false);
    }
    assert.equal(s.calls.includes('RECORD'),false);s.panel.destroy();
  }
});

test("bounded history remains keyboard-addressable; composer and request authority are unchanged",async()=>{
  const s=setup(),history=s.field("Conversation transcript"),composer=s.field("Ask about this case");
  assert.equal(history.attrs.role,"region");assert.equal(history.attrs.tabindex,"0");
  assert.match(history.attrs["aria-description"],/arrow keys/);
  assert.equal(flat(history).includes(composer),false);assert.deepEqual(s.calls,[]);
  await s.open();for(let n=0;n<6;n++)await s.ask("Question "+(n+1));
  assert.equal(flat(history).filter(e=>e.className==="chronos-chat-answer").length,6);
  assert.equal(flat(history).filter(e=>e.tag==="details").length,6);
  assert.equal(s.button("Ask Chronos").disabled,true);
  const before=s.calls.slice();history.focus();assert.deepEqual(s.calls,before);
  await s.button("Read original conversation").dispatch("click");
  assert.equal(s.calls.filter(x=>x==="RECORD").length,6);
  assert.equal(s.calls.filter(x=>x==="READ").length,1);
  assert.equal(flat(history).filter(e=>e.className==="chronos-chat-answer").length,6);
  s.panel.deactivate();assert.equal(history.textContent,"");assert.equal(s.button("Ask Chronos").disabled,true);
  s.panel.destroy();
});


test("new reply follows the end without moving focus or adding requests",async()=>{
  const s=setup();await s.open();await s.ask();
  const h=s.field("Conversation transcript");h.scrollHeight=1000;h.clientHeight=100;h.scrollTop=900;
  s.field("Question for Chronos").focus();const focused=s.doc.focused;
  await s.ask("Second question");
  assert.equal(h.scrollTop,1000);assert.equal(s.doc.focused,focused);
  assert.equal(s.button("Show latest reply").hidden,true);
  assert.deepEqual(s.calls,["SESSION","OPEN","RECORD","RECORD"]);s.panel.destroy();
});
test("scrolling to history during pending reply preserves position and exposes keyboard button",async()=>{
  const s=setup();await s.open();await s.ask();
  const h=s.field("Conversation transcript");h.scrollHeight=1000;h.clientHeight=100;h.scrollTop=900;
  s.wire.hold=deferred();const sent=s.ask("Second question");
  h.scrollTop=150;await h.dispatch("scroll");h.focus();
  const turn=structuredClone(s.wire.turns[0]);turn.turn_id="turn3";turn.user_text="Second question";turn.response.turn_id="turn3";
  s.wire.turns.push(turn);s.wire.hold.resolve(s.packet());await sent;
  assert.equal(h.scrollTop,150);assert.equal(s.doc.focused,h);
  assert.equal(s.button("Show latest reply").hidden,false);assert.match(s.root.textContent,/New reply available/);
  const calls=s.calls.slice();await s.button("Show latest reply").dispatch("click");
  assert.equal(h.scrollTop,1000);assert.equal(s.doc.focused,h);assert.equal(s.button("Show latest reply").hidden,true);
  assert.deepEqual(s.calls,calls);s.panel.destroy();
});
test("sending from history retains disclosure state and resets notice on invalidation",async()=>{
  const s=setup();await s.open();await s.ask();
  const h=s.field("Conversation transcript");h.scrollHeight=1000;h.clientHeight=100;h.scrollTop=70;
  flat(h).find(e=>e.tag==="details").open=true;
  await s.ask("Second question");
  assert.equal(h.scrollTop,70);assert.equal(flat(h).find(e=>e.tag==="details").open,true);
  assert.equal(s.button("Show latest reply").hidden,false);
  s.panel.setAvailable(false);assert.equal(s.button("Show latest reply").hidden,true);
  s.panel.deactivate();assert.equal(h.textContent,"");assert.equal(s.button("Show latest reply").hidden,true);
  assert.equal(s.calls.filter(x=>x==="RECORD").length,2);s.panel.destroy();
});
test("explicit original read does not auto-jump to final turn or announce old reply as new",async()=>{
  const s=setup();await s.open();await s.ask();await s.ask("Second question");
  const h=s.field("Conversation transcript");h.scrollHeight=1000;h.clientHeight=100;h.scrollTop=50;
  await s.button("Read original conversation").dispatch("click");
  assert.equal(h.scrollTop,0);assert.equal(s.button("Show latest reply").hidden,true);
  assert.equal(s.calls.filter(x=>x==="RECORD").length,2);assert.equal(s.calls.filter(x=>x==="READ").length,1);s.panel.destroy();
});

test("pending completion restores the previously focused citation summary by turn identity",async()=>{
  const s=setup();await s.open();await s.ask();const h=s.field("Conversation transcript");
  h.scrollHeight=1000;h.clientHeight=100;h.scrollTop=900;s.wire.hold=deferred();const sent=s.ask("Second question");
  h.scrollTop=120;await h.dispatch("scroll");const original=flat(h).find(e=>e.tag==="summary");original.focus();
  const t=structuredClone(s.wire.turns[0]);t.turn_id="turn3";t.user_text="Second question";t.response.turn_id="turn3";
  s.wire.turns.push(t);s.wire.hold.resolve(s.packet());await sent;
  const restored=flat(h).find(e=>e.tag==="summary");assert.notEqual(restored,original);assert.equal(s.doc.activeElement,restored);
  assert.equal(h.scrollTop,120);assert.equal(s.button("Show latest reply").hidden,false);s.panel.destroy();
});
test("lost response followed by explicit read cannot reuse a stale follow request",async()=>{
  const s=setup();await s.open();await s.ask();const h=s.field("Conversation transcript");
  h.scrollHeight=1000;h.clientHeight=100;h.scrollTop=900;s.wire.fail=true;await s.ask("Second question");
  assert.equal(h.textContent,"");
  const t=structuredClone(s.wire.turns[0]);t.turn_id="turn3";t.user_text="Second question";t.response.turn_id="turn3";s.wire.turns.push(t);
  await s.button("Read original conversation").dispatch("click");
  assert.equal(h.scrollTop,0);assert.equal(s.button("Show latest reply").hidden,true);
  assert.equal(s.calls.filter(x=>x==="RECORD").length,2);assert.equal(s.calls.filter(x=>x==="READ").length,1);s.panel.destroy();
});
