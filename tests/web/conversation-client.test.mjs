import test from 'node:test';
import assert from 'node:assert/strict';
import {createChronosClient,ChronosClientError} from '../../src/chronos_web/client.mjs';
const config={pageUrl:'https://chronos.example/ui',basePath:'/csp/chronos',timeoutMs:100};
const token='a'.repeat(64),digest='b'.repeat(64);
const session=(extra={})=>({code:'CONNECTED',authenticated:true,canRead:true,canApprove:true,canConverse:true,csrf:token,...extra});
const json=(value,status=200)=>new Response(JSON.stringify(value),{status,headers:{'Content-Type':'application/json; charset=utf-8'}});
const fields=()=>({turnId:'t1',expectedRevision:1,expectedContextDigest:digest,text:'Why B? é 🙂'});
function packet(command='OPEN',record=fields()){
  const turns=command==='RECORD'?[{turn_id:record.turnId,user_text:record.text,state:'RECORDED',response:null,error:null}]:[];
  return {code:{OPEN:'CONVERSATION_OPENED',READ:'CONVERSATION_READ',RECORD:'TURN_RECORDED'}[command],
    inference_granted:false,dispatch_authorized:false,context_digest:digest,
    conversation:{conversation_id:'c1',case_id:'case1',shipment_version:1,revision:turns.length+1,
      turn_limit:6,turns,preference_events:[],dispatch_authorized:false,confirmation_granted:false},
    context:{decision_id:'d1',revision:1,conversation_revision:turns.length+1,generation:'g1',
      operation_id:null,result_scope:'CURRENT_SHIPMENT',evidence:[{id:'history',text:'Recorded proposal B.',provenance:'HISTORICAL_DECISION'}]}};
}
function wire(handler){const calls=[];return {calls,fetchImpl:(url,options)=>{calls.push({url,options});return handler(url,options,calls.length);}};}
const errorIs=(code,applied=false)=>e=>e instanceof ChronosClientError&&e.code===code&&e.mayHaveApplied===applied;
test('legacy or absent capability disables only conversation and does not expose token',async()=>{
  for(const canConverse of [undefined,false]){
    const w=wire(()=>json(session({canConverse})));const c=createChronosClient({...config,...w});
    await c.connect();assert.equal(c.conversationAvailable(),false);
    assert.deepEqual(c.sessionStatus(),{connected:true,canRead:true,canApprove:true});
    await assert.rejects(c.openConversation('c1','d1'),errorIs('CONVERSATION_UNAVAILABLE'));
    assert.equal(w.calls.length,1);assert.equal(JSON.stringify(c.sessionStatus()).includes(token),false);
  }
});
test('malformed or contradictory capability is not accepted',async()=>{
  for(const extra of [{canConverse:1},{canConverse:'true'},
    {code:'ACCESS_REVOKED',canRead:false,canApprove:false,canConverse:true}]){
    const c=createChronosClient({...config,fetchImpl:()=>json(session(extra))});
    await assert.rejects(c.connect(),errorIs('INVALID_SESSION'));assert.equal(c.conversationAvailable(),false);
  }
});
test('conversation sends exact same-origin route with UTF-8 text and no other command',async()=>{
  const w=wire((url,opts)=>json(url.endsWith('/session')?session():packet(JSON.parse(opts.body).command)));
  const c=createChronosClient({...config,...w});await c.connect();assert.equal(c.conversationAvailable(),true);
  await c.openConversation('c1','d1');await c.readConversation('c1','d1');await c.recordConversation('c1','d1',fields());
  assert.equal(w.calls.length,4);
  assert.deepEqual(w.calls.slice(1).map(x=>JSON.parse(x.options.body)),[
    {command:'OPEN',conversationId:'c1',decisionId:'d1'},
    {command:'READ',conversationId:'c1',decisionId:'d1'},
    {command:'RECORD',conversationId:'c1',decisionId:'d1',...fields()}]);
  for(const call of w.calls.slice(1)){
    assert.equal(call.url,'https://chronos.example/csp/chronos/conversation');
    assert.equal(call.options.credentials,'same-origin');assert.equal(call.options.redirect,'error');
    assert.equal(call.options.headers['X-Chronos-CSRF'],token);assert.equal(call.options.body.includes(token),false);
  }
});
test('malformed input never reaches fetch or clears valid session',async()=>{
  const w=wire(()=>json(session()));const c=createChronosClient({...config,...w});await c.connect();
  for(const patch of [{text:'é'.repeat(1025)},{text:'\ud800'},{text:'\u0000'},
    {text:''},{expectedRevision:true},{expectedRevision:7},{expectedContextDigest:'bad'},
    {turnId:'../x'},{actor:'forged'}]){
    await assert.rejects(c.recordConversation('c1','d1',{...fields(),...patch}),errorIs('INVALID_REQUEST'));
  }
  await assert.rejects(c.openConversation('../x','d1'),errorIs('INVALID_REQUEST'));
  assert.equal(w.calls.length,1);assert.equal(c.conversationAvailable(),true);
});
test('lost response preserves original identifiers and never retries',async()=>{
  for(const command of ['OPEN','READ','RECORD']){
    const w=wire(url=>{if(url.endsWith('/session'))return json(session());throw Error('private transport detail');});
    const c=createChronosClient({...config,...w});await c.connect();
    const sent=command==='OPEN'?c.openConversation('c1','d1'):command==='READ'?c.readConversation('c1','d1'):c.recordConversation('c1','d1',fields());
    await assert.rejects(sent,e=>errorIs('TRANSPORT_UNAVAILABLE',command!=='READ')(e)&&e.id==='c1'&&e.decisionId==='d1'&&e.turnId===(command==='RECORD'?'t1':''));
    assert.equal(w.calls.length,2);assert.equal(c.conversationAvailable(),false);
  }
});
test('late response from disconnected session is not returned',async()=>{
  let resolve;const waiting=new Promise(r=>resolve=r);
  const w=wire(url=>url.endsWith('/session')?json(session()):waiting);
  const c=createChronosClient({...config,...w});await c.connect();
  const sent=c.recordConversation('c1','d1',fields());
  const checked=assert.rejects(sent,errorIs('CONNECTION_CHANGED',true));
  c.disconnect();resolve(json(packet('RECORD')));await checked;
  assert.equal(w.calls.length,2);assert.equal(c.conversationAvailable(),false);
});
test('busy conversation prevents a second send or concurrent approval',async()=>{
  let resolve;const waiting=new Promise(r=>resolve=r);
  const w=wire(url=>url.endsWith('/session')?json(session()):waiting);
  const c=createChronosClient({...config,...w});await c.connect();const sent=c.recordConversation('c1','d1',fields());
  await assert.rejects(c.recordConversation('c1','d1',fields()),errorIs('REQUEST_IN_PROGRESS'));
  await assert.rejects(c.confirmPreview('p1'),errorIs('REQUEST_IN_PROGRESS'));
  resolve(json(packet('RECORD')));await sent;assert.equal(w.calls.length,2);
});
test('wrong identifiers, private fields, authorization and malformed receipts are rejected',async()=>{
  const mutations=[p=>p.conversation.conversation_id='other',p=>p.context.decision_id='other',
    p=>p.dispatch_authorized=true,p=>p.inference_granted=true,p=>p.private_provider_request={},
    p=>p.conversation.confirmation_granted=true,p=>p.conversation.revision=3,
    p=>p.context.evidence[0].provenance='CURRENT_GUESS',p=>p.conversation.turns[0].user_text='different'];
  for(const mutate of mutations){
    const response=packet('RECORD');mutate(response);
    const w=wire(url=>json(url.endsWith('/session')?session():response));const c=createChronosClient({...config,...w});await c.connect();
    await assert.rejects(c.recordConversation('c1','d1',fields()),errorIs('INVALID_CONVERSATION_RESPONSE',true));
    assert.equal(w.calls.length,2);
  }
});
test('a completed answer remains interpretation with no execution authority',async()=>{
  const p=packet('RECORD');p.code='CONVERSATION_READ';p.conversation.turns[0].state='COMPLETED';
  p.conversation.turns[0].response={schema:'chronos.case-conversation.v1',conversation_id:'c1',turn_id:'t1',
    context_digest:'c'.repeat(64),intent:'ANSWER',answer:'B was the recorded preference.',source_ids:['history'],
    preference:null,origin:'MODEL_INTERPRETATION',dispatch_authorized:false,confirmation_granted:false,requires_new_evaluation:false};
  const w=wire(url=>json(url.endsWith('/session')?session():p));const c=createChronosClient({...config,...w});await c.connect();
  const result=await c.readConversation('c1','d1');assert.equal(result.conversation.turns[0].response.origin,'MODEL_INTERPRETATION');
  assert.equal(w.calls.length,2);
});

test('completed answers count Unicode code points and preserve their text',async()=>{
  for(const char of ['a','é','漢','🙂']){
    const answer=char.repeat(2048),p=packet('RECORD');
    p.code='CONVERSATION_READ';p.conversation.turns[0].state='COMPLETED';
    p.conversation.turns[0].response={schema:'chronos.case-conversation.v1',conversation_id:'c1',turn_id:'t1',
      context_digest:digest,intent:'ANSWER',answer,source_ids:['history'],preference:null,
      origin:'MODEL_INTERPRETATION',dispatch_authorized:false,confirmation_granted:false,requires_new_evaluation:false};
    const w=wire(url=>json(url.endsWith('/session')?session():p));
    const c=createChronosClient({...config,...w});await c.connect();
    const response=await c.readConversation('c1','d1');
    assert.equal(response.conversation.turns[0].response.answer,answer);
    assert.equal(response.dispatch_authorized,false);assert.equal(w.calls.length,2);
  }
});

test('answer expansion cannot admit oversized text, malformed Unicode or relaxed input',async()=>{
  for(const answer of ['a'.repeat(2049),'é'.repeat(2049),'🙂'.repeat(2049),'\ud800','\udfff','\u0000',' ']){
    const p=packet('RECORD');p.code='CONVERSATION_READ';p.conversation.turns[0].state='COMPLETED';
    p.conversation.turns[0].response={schema:'chronos.case-conversation.v1',conversation_id:'c1',turn_id:'t1',
      context_digest:digest,intent:'ANSWER',answer,source_ids:['history'],preference:null,
      origin:'MODEL_INTERPRETATION',dispatch_authorized:false,confirmation_granted:false,requires_new_evaluation:false};
    const w=wire(url=>json(url.endsWith('/session')?session():p));
    const c=createChronosClient({...config,...w});await c.connect();
    await assert.rejects(c.readConversation('c1','d1'),errorIs('INVALID_CONVERSATION_RESPONSE'));
  }
  for(const field of ['user_text','evidence']){
    const p=packet('RECORD');p.code='CONVERSATION_READ';
    if(field==='user_text')p.conversation.turns[0].user_text='é'.repeat(1025);
    else p.context.evidence[0].text='é'.repeat(1025);
    const c=createChronosClient({...config,fetchImpl:url=>json(url.endsWith('/session')?session():p)});
    await c.connect();await assert.rejects(c.readConversation('c1','d1'),errorIs('INVALID_CONVERSATION_RESPONSE'));
  }
});
test('mutating form fields while waiting cannot change sent turn or readback reference',async()=>{
  for(const lost of [false,true]){
    let resolve,reject;const waiting=new Promise((res,rej)=>{resolve=res;reject=rej;});
    const w=wire(url=>url.endsWith('/session')?json(session()):waiting);
    const c=createChronosClient({...config,...w});await c.connect();
    const input=fields();const sent=c.recordConversation('c1','d1',input);
    input.turnId='edited';input.text='Changed while waiting';input.expectedRevision=6;
    assert.equal(JSON.parse(w.calls[1].options.body).turnId,'t1');
    if(lost){
      const checked=assert.rejects(sent,e=>errorIs('TRANSPORT_UNAVAILABLE',true)(e)&&e.turnId==='t1');
      reject(Error('lost'));await checked;
    }else{
      resolve(json(packet('RECORD')));const result=await sent;
      assert.equal(result.conversation.turns[0].turn_id,'t1');assert.equal(c.sessionStatus().connected,true);
    }
    assert.equal(w.calls.length,2);
  }
});
test('a receipt must correspond to the original message revision',async()=>{
  const p=packet('RECORD');p.code='TURN_REPLAY';
  const w=wire(url=>json(url.endsWith('/session')?session():p));const c=createChronosClient({...config,...w});await c.connect();
  await assert.rejects(c.recordConversation('c1','d1',{...fields(),expectedRevision:2}),errorIs('INVALID_CONVERSATION_RESPONSE',true));
  assert.equal(w.calls.length,2);
});
