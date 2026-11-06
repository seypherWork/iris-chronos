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
  setAttribute(k,v){this.attrs[k]=v;}focus(){this.ownerDocument.focused=this;}
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
      wire.turns.push({turn_id:f.turnId,user_text:f.text,state:wire.state,error:null,response:wire.state==="COMPLETED"?{
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

const fixtures=JSON.parse(fs.readFileSync(new URL('./fixtures/grounded262.json',import.meta.url),'utf8')).cases;
async function openFixture(name,mutate=()=>{}){
 const s=setup(),p=structuredClone(fixtures.find(x=>x.name===name).packet);s.chosen.id=p.context.decision_id;
 mutate(p);
 s.client.openConversation=async id=>{p.conversation.conversation_id=id;for(const t of p.conversation.turns)t.response.conversation_id=id;return p;};
 await s.open();return {s,p};
}
test('compound sections remain complete, ordered and separately headed',async()=>{
 const {s,p}=await openFixture('compound'),r=p.conversation.turns[0].response;
 const paragraphs=flat(s.root).filter(e=>e.className==='chronos-chat-answer-text').map(e=>e.textContent);
 assert.deepEqual(paragraphs,r.sections.map(x=>x.text));assert.ok(paragraphs.join('\n\n').length>2048);
 assert.match(s.root.textContent,/Before confirming/);assert.match(s.root.textContent,/could duplicate/);assert.equal(s.calls.includes('RECORD'),false);s.panel.destroy();
});
test('new evidence types keep useful labels without invented missing-operation claims',async()=>{
 for(const [name,expected] of [['native-review',/Earlier decision: earlier262/],['simulator',/Owned simulator operation recovery261: DELIVERED_SIMULATED/],['preferences',/Not applied/],['history-limit',/reached its limit/],['ablation',/ABLATION_NOT_ACTIONABLE/]]){
  const {s}=await openFixture(name);assert.match(s.root.textContent,expected);
  if(name==='simulator')assert.match(s.root.textContent,/does not prove physical delivery/);
  assert.equal(s.calls.includes('RECORD'),false);s.panel.destroy();
 }
});
test('clarification and proposed priorities retain distinct provenance',async()=>{
 for(const name of ['clarify','preferences']){
  const {s}=await openFixture(name);assert.match(s.root.textContent,name==='clarify'?/Clarification needed · no decision or action/:/Model-interpreted preference · not applied/);s.panel.destroy();
 }
});

test('approval redirect does not invite confirming an unresolved compound answer',async()=>{
 const {s}=await openFixture('compound');
 const boundary=flat(s.root).find(e=>e.className==='chronos-chat-boundary');
 assert.ok(boundary);assert.match(boundary.textContent,/Resolve any uncertainty or stated blockers/);
 assert.match(boundary.textContent,/cannot override/);
 assert.doesNotMatch(boundary.textContent,/confirm the recovery/);
 assert.equal(s.calls.includes('RECORD'),false);s.panel.destroy();
});

test('archived timing evidence shows its own values instead of an absent-operation warning',async()=>{
 const {s}=await openFixture('simulator',p=>{
  const r=p.conversation.turns[0].response;r.source_ids.push('timing');
  r.sources.push({id:'timing',kind:'ARCHIVED_TIMING_SNAPSHOT',observed_at:1234567,
   options:{A:{cost:3,available_at:0,queue_duration:420000000,travel_duration:480000000},B:{cost:6,available_at:0,queue_duration:0,travel_duration:540000000}},
   policy:{inventory_expires:360000000,deadline:1200000000,offer_until:1800000000}});
 });
 assert.match(s.root.textContent,/Original timing snapshot at approximately 0.02 min \(1234567 microseconds\)/);
 assert.match(s.root.textContent,/A: cost 3 synthetic units; available at 0 min; base queue 7 min; travel 8 min/);
 assert.match(s.root.textContent,/Inventory expires at 6 min; delivery deadline 20 min/);
 assert.match(s.root.textContent,/Historical inputs, not a current shipment result/);
 assert.doesNotMatch(s.root.textContent,/No current operation read was supplied/);
 assert.equal(s.calls.includes('RECORD'),false);s.panel.destroy();
});
