import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {createChronosClient,ChronosClientError} from '../../src/chronos_web/client.mjs';
const fixtures=JSON.parse(fs.readFileSync(new URL('./fixtures/grounded262.json',import.meta.url),'utf8'));
const json=v=>new Response(JSON.stringify(v),{status:200,headers:{'Content-Type':'application/json'}});
const session={code:'CONNECTED',authenticated:true,canRead:true,canApprove:true,canConverse:true,csrf:'a'.repeat(64)};
const read=async p=>{const calls=[];const c=createChronosClient({pageUrl:'https://chronos.example/ui',basePath:'/csp/chronos',timeoutMs:100,fetchImpl:(url,opt)=>{calls.push({url,opt});return json(url.endsWith('/session')?session:p);}});await c.connect();return {value:await c.readConversation(p.conversation.conversation_id,p.context.decision_id),calls};};
const sample=name=>structuredClone(fixtures.cases.find(c=>c.name===name).packet);
const invalid=e=>e instanceof ChronosClientError&&e.code==='INVALID_CONVERSATION_RESPONSE';
test('all real Python v2 packet shapes remain intact in the browser client',async()=>{
  assert.equal(fixtures.evidence,'SYNTHETIC_PYTHON_LEDGER_OUTPUT_NOT_REAL_MODEL');
  for(const {packet} of fixtures.cases){const {value,calls}=await read(packet);assert.deepEqual(value,packet);assert.equal(calls.length,2);assert.equal(value.dispatch_authorized,false);}
  assert.ok(sample('compound').conversation.turns[0].response.answer.length>2048);
});
test('typed source swaps, authority claims, false delivery and history changes are rejected',async()=>{
  const mutations=[
    ['native-review',p=>p.context.grounding.source_records['current-review'].dispatch_authorized=true],
    ['native-review',p=>p.context.grounding.source_records['current-review'].semantic_digest='bad'],
    ['native-review',p=>p.context.grounding.source_records['current-review'].code='INVENTED'],
    ['native-review',p=>p.context.grounding.source_records['decision-change'].decision_digest='0'.repeat(64)],
    ['native-review',p=>p.context.grounding.source_records['decision-change'].previous_decision_id=p.context.decision_id],
    ['native-review',p=>p.context.grounding.source_records['decision-change'].current_preference='EARLIEST_ALLOWED'],
    ['native-review',p=>p.context.grounding.source_records['chat-effect'].conversation_id='foreign'],
    ['native-review',p=>p.context.grounding.source_records['chat-effect'].revision=7],
    ['preferences',p=>p.context.grounding.source_records['chat-effect'].proposals[0].adopted=true],
    ['simulator',p=>p.context.grounding.source_records['simulator-result'].physical_delivery=true],
    ['simulator',p=>p.context.grounding.source_records['simulator-result'].operation_id='foreign'],
    ['simulator',p=>p.context.grounding.source_records['simulator-result'].arrival=null],
    ['simulator',p=>p.context.grounding.source_records['current-operation'].state='UNKNOWN'],
    ['compound',p=>p.context.grounding.blocking_notice=null],
    ['ablation',p=>p.context.grounding.source_records['current-review'].status='REVIEWABLE'],
  ];
  for(const [name,mutate] of mutations){const p=sample(name);mutate(p);await assert.rejects(read(p),invalid);}
});
test('compound answers keep their exact section order, citations and versioned limits',async()=>{
  const mutations=[r=>r.answer+=' extra',r=>r.sections.reverse(),r=>r.topics.push('CLARIFY'),r=>r.topics=['UNKNOWN'],
    r=>r.sections[0].source_ids.push('foreign'),r=>r.source_ids.reverse(),r=>r.sources[0].decision_id='foreign',r=>r.sources[0].raw_ledger={},
    r=>r.confirmation_granted=true,r=>r.plan_origin='DETERMINISTIC_EVIDENCE',r=>r.renderer_version='chronos.explanation-renderer.v1',
    r=>{r.sections[0].text='🙂'.repeat(2049);r.answer=r.sections.map(s=>s.text).join('\n\n');},
    r=>{r.sections[0].text='\ud800';r.answer=r.sections.map(s=>s.text).join('\n\n');}];
  for(const mutate of mutations){const p=sample('compound');mutate(p.conversation.turns[0].response);await assert.rejects(read(p),invalid);}
});
test('model changes and fresh reads never rewrite archived v2 preference answers',async()=>{
  const p=sample('preferences'),old=structuredClone(p.conversation.turns);p.context_digest='f'.repeat(64);p.context.revision+=1;
  const {value}=await read(p);assert.deepEqual(value.conversation.turns,old);assert.equal(value.conversation.preference_events.length,1);
  for(const mutate of [r=>r.preference=null,r=>r.requires_new_evaluation=false,r=>r.intent='ANSWER']){
    const bad=sample('preferences');mutate(bad.conversation.turns[0].response);await assert.rejects(read(bad),invalid);
  }
});
test('legacy reply and input limits are not enlarged by enabling v2 context',async()=>{
  const p=sample('compound');const t=p.conversation.turns[0];
  t.response={schema:'chronos.case-conversation.v1',conversation_id:p.conversation.conversation_id,turn_id:t.turn_id,context_digest:'d'.repeat(64),intent:'ANSWER',answer:'a'.repeat(2049),source_ids:['old'],preference:null,origin:'MODEL_INTERPRETATION',dispatch_authorized:false,confirmation_granted:false,requires_new_evaluation:false};
  await assert.rejects(read(p),invalid);t.response.answer='Legacy interpretation';await read(p);
  t.user_text='é'.repeat(1025);await assert.rejects(read(p),invalid);
});
test('object key order does not invalidate equal recorded predictions',async()=>{
  const p=sample('native-review');const change=p.context.grounding.source_records['decision-change'];
  change.current_available=change.current_available.map(row=>Object.fromEntries(Object.entries(row).reverse()));
  const {value}=await read(p);assert.deepEqual(value,p);
});
test('archived simulator sources must agree with each other while retaining their own snapshot',async()=>{
  const original=sample('simulator');
  for(const field of ['operation_id','attempt_id','state']){
    const p=structuredClone(original),sim=p.conversation.turns[0].response.sources.find(s=>s.id==='simulator-result');
    sim[field]=field==='state'?'NOT_ACCEPTED_FINAL':'foreign-valid-id';await assert.rejects(read(p),invalid);
  }
  original.context_digest='e'.repeat(64);original.context.revision+=1;
  await read(original);
});
test('an additional section cannot invent a result or replace the mandatory uncertainty notice',async()=>{
  const p=sample('clarify'),r=p.conversation.turns[0].response;
  r.sections.push({topic:'OPERATION_STATUS',text:'The shipment has been delivered.',source_ids:[]});r.answer=r.sections.map(s=>s.text).join('\n\n');
  await assert.rejects(read(p),invalid);
  const blocked=sample('compound'),b=blocked.conversation.turns[0].response;
  b.sections.at(-1).text='The shipment has been delivered.';b.answer=b.sections.map(s=>s.text).join('\n\n');
  await assert.rejects(read(blocked),invalid);
});
test('each answer section cites the correct kind of archived evidence',async()=>{
  const p=sample('native-review'),r=p.conversation.turns[0].response;
  [r.sections[0].source_ids,r.sections[1].source_ids]=[r.sections[1].source_ids,r.sections[0].source_ids];
  const records=Object.fromEntries(r.sources.map(s=>[s.id,s]));r.source_ids=[...new Set(r.sections.flatMap(s=>s.source_ids))];r.sources=r.source_ids.map(id=>records[id]);
  await assert.rejects(read(p),invalid);
});
test('removing the extra uncertainty section cannot silently remove the mandatory warning',async()=>{
  const p=sample('compound'),r=p.conversation.turns[0].response;
  r.sections.pop();r.answer=r.sections.map(s=>s.text).join('\n\n');await assert.rejects(read(p),invalid);
});

// Synthetic extension of an archived packet; this is not a new model response.
function withTiming(){
  const p=sample('compound'),records=p.context.grounding.source_records;
  const timing={id:'timing',kind:'ARCHIVED_TIMING_SNAPSHOT',decision_id:p.context.decision_id,
    decision_digest:records.decision.decision_digest,context_digest:records.decision.context_digest,
    observed_at:0,time_unit:'relative_microseconds',
    options:{A:{cost:3,available_at:0,queue_duration:120000000,travel_duration:780000000},B:{cost:6,available_at:0,queue_duration:0,travel_duration:540000000}},
    policy:Object.fromEntries(['inventory_expires','deadline','offer_until'].map(k=>[k,records.finish.policy[k]]))};
  records.timing=timing;p.context.grounding.sources.COMPARISON.push('timing');
  const r=p.conversation.turns[0].response;
  r.sections.find(s=>s.topic==='COMPARISON').source_ids.push('timing');
  const sources=Object.fromEntries([...r.sources,timing].map(s=>[s.id,s]));
  r.source_ids=[...new Set(r.sections.flatMap(s=>s.source_ids))];r.sources=r.source_ids.map(id=>structuredClone(sources[id]));
  return p;
}
test('optional timing evidence is bound and rejected when malformed in context or archived response',async()=>{
  const p=withTiming();assert.deepEqual((await read(p)).value,p);
  const mutations=[s=>s.decision_id='foreign',s=>s.decision_digest='0'.repeat(64),s=>s.context_digest='0'.repeat(64),
    s=>s.observed_at=true,s=>s.time_unit='minutes',s=>s.options.A.cost=2.5,s=>s.options.B.queue_duration=-1,
    s=>s.policy.deadline++,s=>delete s.options.B,s=>s.options.A.dispatch_authorized=true,s=>s.extra='unknown'];
  for(const location of ['context','reply'])for(const mutate of mutations){
    const bad=withTiming();mutate(location==='context'?bad.context.grounding.source_records.timing:bad.conversation.turns[0].response.sources.find(s=>s.id==='timing'));
    await assert.rejects(read(bad),invalid);
  }
  const bad=withTiming();bad.context.grounding.sources.COMPARISON.pop();await assert.rejects(read(bad),invalid);
  const old=sample('compound');assert.deepEqual((await read(old)).value,old);
});
