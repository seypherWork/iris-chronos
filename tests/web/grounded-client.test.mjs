import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {createChronosClient,ChronosClientError} from '../../src/chronos_web/client.mjs';
const fixtures=JSON.parse(fs.readFileSync(new URL('./fixtures/grounded256.json',import.meta.url),'utf8'));
const config={pageUrl:'https://chronos.example/ui',basePath:'/csp/chronos',timeoutMs:100};
const session={code:'CONNECTED',authenticated:true,canRead:true,canApprove:true,canConverse:true,csrf:'a'.repeat(64)};
const json=value=>new Response(JSON.stringify(value),{status:200,headers:{'Content-Type':'application/json'}});
const make=packet=>{const calls=[];const client=createChronosClient({...config,fetchImpl:(url,opt)=>{
  calls.push({url,opt});return json(url.endsWith('/session')?session:packet);
}});return {client,calls};};
const read=async packet=>{const {client,calls}=make(packet);await client.connect();
  return {value:await client.readConversation(packet.conversation.conversation_id,packet.context.decision_id),calls,client};};
const invalid=e=>e instanceof ChronosClientError && e.code==='INVALID_CONVERSATION_RESPONSE';

test('actual Python ledger packets for every C2 topic are consumed without a model call or authority',async()=>{
  assert.equal(fixtures.evidence,'SYNTHETIC_PYTHON_LEDGER_OUTPUT_NOT_REAL_MODEL');
  for(const {packet,topic} of fixtures.cases){
    const {value,calls}=await read(packet);assert.deepEqual(value,packet,topic);
    assert.equal(calls.length,2);assert.equal(value.dispatch_authorized,false);
    assert.equal(value.conversation.turns[0].response.answer_origin,'DETERMINISTIC_EVIDENCE');
  }
});
test('C2 does not accept wrong case, origins, versions, authority, raw data or unknown source fields',async()=>{
  const mutations=[p=>p.context.response_contract='unknown',p=>p.context.renderer_version='unknown',
    p=>p.context.grounding.raw_ledger={},p=>p.context.grounding.source_records.decision.decision_id='other',
    p=>p.context.grounding.sources.DECISION.push('foreign'),p=>p.context.grounding.source_records.finish.receipt.password='secret-sentinel',
    p=>p.context.grounding.source_records.finish.receipt.selection_available[0].cost=-1,
    p=>p.conversation.turns[0].response.plan_origin='DETERMINISTIC_EVIDENCE',
    p=>p.conversation.turns[0].response.answer_origin='MODEL_INTERPRETATION',
    p=>p.conversation.turns[0].response.dispatch_authorized=true,
    p=>p.conversation.turns[0].response.sources[0].decision_id='other',
    p=>p.conversation.turns[0].response.source_ids.reverse(),
    p=>p.conversation.turns[0].response.sources[1].receipt.validation_available[0].arrival=Infinity,
    p=>p.conversation.turns[0].response.extra='unexpected'];
  for(const mutate of mutations){const p=structuredClone(fixtures.cases[0].packet);mutate(p);await assert.rejects(read(p),invalid);}
});
test('a malformed blocking notice cannot make UNKNOWN look settled',async()=>{
  for(const mutate of [p=>p.context.grounding.blocking_notice=null,
    p=>p.context.grounding.source_records['current-operation'].state='DELIVERED',
    p=>p.context.grounding.quarantined=true]){
    const p=structuredClone(fixtures.cases.find(x=>x.topic==='OPERATION_STATUS').packet);mutate(p);await assert.rejects(read(p),invalid);
  }
});
test('empty preference citations are permitted but cannot invent approval or adopted preference',async()=>{
  const original=fixtures.cases.find(x=>x.topic==='PREFERENCE_CHANGE').packet;
  assert.equal(original.conversation.turns[0].response.source_ids.length,0);await read(original);
  for(const mutate of [r=>r.confirmation_granted=true,r=>r.requires_new_evaluation=false,r=>r.preference=null,r=>r.intent='ANSWER']){
    const p=structuredClone(original);mutate(p.conversation.turns[0].response);await assert.rejects(read(p),invalid);
  }
});
test('historical C1 reply retains its identity in a C2 current context',async()=>{
  const p=structuredClone(fixtures.cases[0].packet);const t=p.conversation.turns[0];
  t.response={schema:'chronos.case-conversation.v1',conversation_id:p.conversation.conversation_id,turn_id:t.turn_id,
    context_digest:'d'.repeat(64),intent:'ANSWER',answer:'Historical model interpretation.',source_ids:['old-evidence'],preference:null,
    origin:'MODEL_INTERPRETATION',dispatch_authorized:false,confirmation_granted:false,requires_new_evaluation:false};
  const {value}=await read(p);assert.equal(value.conversation.turns[0].response.schema,'chronos.case-conversation.v1');
});
test('historical C2 sources are retained even when current context revision changes',async()=>{
  const p=structuredClone(fixtures.cases[0].packet),before=structuredClone(p.conversation.turns[0].response);
  p.context.revision+=1;p.context_digest='e'.repeat(64);
  const {value}=await read(p);assert.deepEqual(value.conversation.turns[0].response,before);
});
