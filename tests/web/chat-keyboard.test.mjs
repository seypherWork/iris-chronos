import test from 'node:test';import assert from 'node:assert/strict';
import {mountConversationPanel} from '../../src/chronos_web/conversation-panel.mjs';
class Element{
 constructor(tag,doc){this.tag=tag;this.ownerDocument=doc;this.children=[];this.attrs={};this.listeners=new Map();this.value='';this._text='';}
 set textContent(v){this._text=String(v);this.children=[];}get textContent(){return this._text+this.children.map(x=>x.textContent).join('');}
 appendChild(x){this.children.push(x);return x;}replaceChildren(...x){this.children=x;this._text='';}
 setAttribute(k,v){this.attrs[k]=v;}focus(){this.ownerDocument.activeElement=this;}
 addEventListener(k,v){this.listeners.set(k,[...(this.listeners.get(k)??[]),v]);}
 removeEventListener(k,v){this.listeners.set(k,(this.listeners.get(k)??[]).filter(x=>x!==v));}
 async dispatch(k,event={}){for(const f of this.listeners.get(k)??[])await f({preventDefault(){},...event});}
}
const flat=n=>[n,...n.children.flatMap(flat)];
function setup(){
 const doc={createElement:tag=>new Element(tag,doc)},root=new Element('div',doc),turns=[],calls=[];
 let connected=false,cid='',sequence=0,release=null;
 const state={hold:false,fail:false};
 const packet=()=>({code:'CONVERSATION_READ',context_digest:'b'.repeat(64),inference_granted:false,dispatch_authorized:false,
  conversation:{conversation_id:cid,case_id:'case1',shipment_version:1,revision:turns.length+1,turn_limit:6,turns:structuredClone(turns),preference_events:[],dispatch_authorized:false,confirmation_granted:false},
  context:{decision_id:'d1',conversation_revision:turns.length+1,evidence:[{id:'e1',text:'Checked fixture.',provenance:'HISTORICAL_DECISION'}]}});
 const client={connect:async()=>{connected=true;return client.sessionStatus();},disconnect:()=>{connected=false;},
  sessionStatus:()=>({connected,canRead:connected}),sessionIdentity:()=>({available:connected,actor:'principal-'+'a'.repeat(64),actorScope:'c'.repeat(64),applicationUrl:'https://chronos.example/'}),
  sessionExecution:()=>({mode:'LIVE_MODEL'}),conversationAvailable:()=>true,
  openConversation:async id=>{cid=id;return packet();},readConversation:async()=>packet(),
  recordConversation:async(c,d,f)=>{calls.push(f);if(state.hold)await new Promise(r=>{release=r;});if(state.fail)throw Error('SYNTHETIC_TIMEOUT');
   turns.push({turn_id:f.turnId,user_text:f.text,state:'COMPLETED',response:{schema:'chronos.case-conversation.v1',conversation_id:c,turn_id:f.turnId,
    context_digest:'b'.repeat(64),intent:'ANSWER',answer:'Checked fixture explanation.',source_ids:['e1'],origin:'MODEL_INTERPRETATION',dispatch_authorized:false,confirmation_granted:false}});return packet();}};
 const panel=mountConversationPanel(root,{client,selection:()=>({kind:'decision',id:'d1'}),newId:()=> 'id'+(++sequence)});
 const field=()=>flat(root).find(e=>e.attrs['aria-label']==='Question for Chronos');
 return {root,panel,calls,state,field,release:()=>release?.(),
  open:()=>flat(root).find(e=>e.tag==='button'&&e.textContent==='Open case conversation').dispatch('click'),
  key:event=>field().dispatch('keydown',event)};
}
test('Enter sends one actual controller turn and clears only the submitted draft',async()=>{
 const s=setup();await s.open();s.field().value='Why this choice?';let prevented=0;
 await s.key({key:'Enter',preventDefault(){prevented++;}});
 assert.equal(prevented,1);assert.equal(s.calls.length,1);assert.equal(s.calls[0].text,'Why this choice?');assert.equal(s.field().value,'');s.panel.destroy();
});
test('Shift Enter, IME composition, legacy229 and autorepeat never submit',async()=>{
 for(const event of [{key:'Enter',shiftKey:true},{key:'Enter',isComposing:true},{key:'Enter',keyCode:229},{key:'Enter',repeat:true}]){
  const s=setup();await s.open();s.field().value='Keep draft';await s.key(event);
  assert.equal(s.calls.length,0);assert.equal(s.field().value,'Keep draft');s.panel.destroy();
 }
});
test('pending request shows working state and another Enter cannot queue a turn',async()=>{
 const s=setup();await s.open();s.state.hold=true;s.field().value='One request';const pending=s.key({key:'Enter'});
 assert.equal(s.calls.length,1);assert.equal(s.field().disabled,true);
 const indicator=flat(s.root).find(e=>e.className==='chronos-chat-pending');assert.equal(indicator.hidden,false);
 await s.key({key:'Enter'});assert.equal(s.calls.length,1);s.release();await pending;
 assert.equal(indicator.hidden,true);s.panel.destroy();
});
test('uncertain result retains original turn boundary and cannot resend with Enter',async()=>{
 const s=setup();await s.open();s.state.fail=true;s.field().value='Original';await s.key({key:'Enter'});
 s.field().value='Do not resend';await s.key({key:'Enter'});assert.equal(s.calls.length,1);assert.equal(s.field().disabled,true);
 const setupNode=flat(s.root).find(e=>e.className==='chronos-fold chronos-chat-setup');assert.equal(setupNode.open,true);s.panel.destroy();
});
