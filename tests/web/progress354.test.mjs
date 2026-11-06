import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {createChronosClient,ChronosClientError} from '../../src/chronos_web/client.mjs';
const all=JSON.parse(fs.readFileSync(new URL('./fixtures/grounded262.json',import.meta.url),'utf8'));
const sample=()=>structuredClone(all.cases.find(c=>c.name==='compound').packet);
const read=async p=>{
 const client=createChronosClient({pageUrl:'https://chronos.example/ui',basePath:'/csp/chronos',timeoutMs:100,
 fetchImpl:async url=>new Response(JSON.stringify(url.endsWith('/session')?{code:'CONNECTED',authenticated:true,canRead:true,canApprove:true,canConverse:true,csrf:'a'.repeat(64)}:p),{status:200,headers:{'Content-Type':'application/json'}})});
 await client.connect();return client.readConversation(p.conversation.conversation_id,p.context.decision_id);
};
const invalid=e=>e instanceof ChronosClientError&&e.code==='INVALID_CONVERSATION_RESPONSE';
function extended(){
 const p=sample(),g=p.context.grounding,d=g.source_records.decision,o=g.source_records['current-operation'];
 const source={id:'case-progress',kind:'ONE_DECISION_WITH_OPERATION_READ',decision_id:d.decision_id,decision_digest:d.decision_digest,operation_id:o.operation_id,attempt_id:o.attempt_id,read_digest:o.read_digest};
 g.source_records['case-progress']=source;
 g.sources.DECISION_CHANGE=['decision','current-operation','case-progress'];
 // Explicit synthetic new answer using the old packet's already checked warning.
 const r=p.conversation.turns[0].response;
 const text='Only one historical decision is supplied. '+g.sections.OPERATION_STATUS.concise;
 g.sections.DECISION_CHANGE={concise:text,detailed:text};
 r.topics=['DECISION_CHANGE'];r.intent='ANSWER';r.preference=null;r.requires_new_evaluation=false;
 r.sections=[{topic:'DECISION_CHANGE',text,source_ids:g.sources.DECISION_CHANGE}];r.answer=text;
 r.source_ids=g.sources.DECISION_CHANGE;r.sources=r.source_ids.map(id=>structuredClone(g.source_records[id]));
 return p;
}
test('new progress source context and answer pass while historical packets stay unchanged',async()=>{
 const p=extended();assert.deepEqual(await read(p),p);
 const old=sample();assert.deepEqual(await read(old),old);
});
test('new source bindings, closed shapes and required dependencies reject tampering',async()=>{
 for(const where of ['context','reply'])for(const [field,value] of [['decision_id','foreign'],['decision_digest','0'.repeat(64)],['operation_id','foreign'],['attempt_id','foreign'],['read_digest','1'.repeat(64)],['read_digest',true],['kind','CURRENT_READ'],['dispatch_authorized',true]]){
  const p=extended(),s=where==='context'?p.context.grounding.source_records['case-progress']:p.conversation.turns[0].response.sources.find(s=>s.id==='case-progress');
  s[field]=value;await assert.rejects(read(p),invalid);
 }
 for(const where of ['context','reply'])for(const key of ['decision','current-operation']){
  const p=extended();if(where==='context')delete p.context.grounding.source_records[key];else{const r=p.conversation.turns[0].response;r.sources=r.sources.filter(s=>s.id!==key);r.source_ids=r.source_ids.filter(id=>id!==key);r.sections[0].source_ids=r.sections[0].source_ids.filter(id=>id!==key);}
  await assert.rejects(read(p),invalid);
 }
});
test('cannot combine historical comparison with single-decision progress',async()=>{
 const history=all.cases.find(c=>c.name==='native-review').packet.context.grounding.source_records['decision-change'];
 for(const where of ['context','reply']){
  const p=extended(),h=structuredClone(history);h.decision_id=p.context.decision_id;
  if(where==='context')p.context.grounding.source_records['decision-change']=h;
  else {const r=p.conversation.turns[0].response;r.sources.push(h);r.source_ids.push(h.id);r.sections[0].source_ids.push(h.id);}
  await assert.rejects(read(p),invalid);
 }
});
