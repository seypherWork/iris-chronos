import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {createChronosClient,ChronosClientError} from '../../src/chronos_web/client.mjs';
// Synthetic Python-produced packets: validates the cross-language contract only.
const fixtures=JSON.parse(fs.readFileSync(new URL('./fixtures/clarified-chat-111.json',import.meta.url),'utf8'));
const read=async packet=>{
 const client=createChronosClient({pageUrl:'https://chronos.example/ui',basePath:'/csp/chronos',fetchImpl:async url=>new Response(JSON.stringify(url.endsWith('/session')?{code:'CONNECTED',authenticated:true,canRead:true,canApprove:true,canConverse:true,csrf:'a'.repeat(64)}:packet),{status:200,headers:{'Content-Type':'application/json'}})});
 await client.connect();return client.openConversation(packet.conversation.conversation_id,packet.context.decision_id);
};
test('Python clarified-case explanation opens while remaining informational',async()=>{
 const packet=fixtures.clarified;
 assert.equal(packet.context.grounding.source_records['current-review'].code,'CLARIFICATION_SOURCE_REQUIRED');
 assert.equal(packet.context.grounding.source_records['current-review'].status,'ERROR');
 assert.equal((await read(packet)).dispatch_authorized,false);
});
test('ordinary Python case packet is preserved',async()=>assert.deepEqual(await read(fixtures.ordinary),fixtures.ordinary));
for(const [name,change] of [
 ['rejected status',s=>s.status='REJECTED'],['recheck status',s=>s.status='RECHECK_REQUIRED'],
 ['reviewable status',s=>s.status='REVIEWABLE'],['dispatch claim',s=>s.dispatch_authorized=true],
 ['missing binding',s=>delete s.semantic_digest],['foreign decision',s=>s.decision_id='foreign-decision'],
 ['unknown error',s=>s.code='UNKNOWN_FAILURE']]){
 test('clarification explanation rejects '+name,async()=>{
  const packet=structuredClone(fixtures.clarified);change(packet.context.grounding.source_records['current-review']);
  await assert.rejects(read(packet),e=>e instanceof ChronosClientError&&e.code==='INVALID_CONVERSATION_RESPONSE');
 });
}
