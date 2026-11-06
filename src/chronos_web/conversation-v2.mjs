/** Closed wire validation only. Authenticated server records establish evidence. */
export const PLAN_V2="chronos.case-explanation-plan.v2";
export const REPLY_V2="chronos.case-explanation.v2";
const RENDERER="chronos.explanation-renderer.v2";
const BASE=["decision","finish","current-operation","current-read-missing"];
const EXTRA=["chat-policy","chat-effect","decision-change","current-review","simulator-result","timing","case-progress"];
const TOPICS=["DECISION","COMPARISON","OPERATION_STATUS","PHYSICAL_DELIVERY","PREFERENCE_CHANGE","APPROVAL_REQUIREMENTS","CLARIFY","CHAT_EFFECT","CURRENT_REVIEW","DECISION_CHANGE","DESTINATION_SIMULATION"];
const REASONS=["ABLATION_NOT_ACTIONABLE","STALE_CONTEXT","REVIEW_EXPIRED","RANKING_MISMATCH","OPTION_NOT_FEASIBLE","RUNTIME_GENERATION_CHANGED","AUTHORITY_REFRESH_REQUIRED","EXISTING_ACCEPTANCE","ACCEPTANCE_RECONCILIATION_REQUIRED","ACCEPTANCE_UNRESOLVED","CONFLICTING_EVIDENCE","NO_FEASIBLE_OPTION","DECISION_NOT_ACTIONABLE","RECOVERY_IN_PROGRESS"];
const same=(a,b)=>{
  if(a===b)return true;
  if(a===null||b===null||typeof a!=="object"||typeof b!=="object"||Array.isArray(a)!==Array.isArray(b))return false;
  const keys=Object.keys(a).sort(),other=Object.keys(b).sort();
  return keys.length===other.length&&keys.every((k,i)=>k===other[i]&&same(a[k],b[k]));
};
export function conversationV2({exact,record,validText,validAnswer,hash,ident,integer,prefs,optionRows,source,grounding,decisionId,conversationId}){
  const v2source=s=>{
    if(!record(s)||s.decision_id!==decisionId)return false;
    if(BASE.includes(s.id))return source(s);
    if(s.id==="timing")return exact(s,["id","kind","decision_id","decision_digest","context_digest","observed_at","time_unit","options","policy"])&&s.kind==="ARCHIVED_TIMING_SNAPSHOT"&&s.time_unit==="relative_microseconds"&&hash(s.decision_digest)&&hash(s.context_digest)&&integer(s.observed_at)&&exact(s.options,["A","B"])&&Object.values(s.options).every(row=>exact(row,["cost","available_at","queue_duration","travel_duration"])&&Object.values(row).every(integer))&&exact(s.policy,["inventory_expires","deadline","offer_until"])&&Object.values(s.policy).every(integer);
    if(s.id==="case-progress")return exact(s,["id","kind","decision_id","decision_digest","operation_id","attempt_id","read_digest"])&&s.kind==="ONE_DECISION_WITH_OPERATION_READ"&&hash(s.decision_digest)&&ident(s.operation_id)&&ident(s.attempt_id)&&hash(s.read_digest);
    if(s.id==="chat-policy")return exact(s,["id","kind","renderer_version","decision_id","dispatch_authorized","confirmation_granted"])&&s.kind==="CODE_POLICY"&&s.renderer_version===RENDERER&&s.dispatch_authorized===false&&s.confirmation_granted===false;
    if(s.id==="chat-effect"){
      const common=["id","kind","decision_id","conversation_id","revision"];
      if(s.conversation_id!==conversationId||!integer(s.revision)||s.revision<1||s.revision>7)return false;
      if(s.kind==="CHECKED_CHAT_HISTORY")return exact(s,[...common,"ledger_digest","preference_proposals"])&&hash(s.ledger_digest)&&s.preference_proposals===0;
      return s.kind==="RECORDED_CHAT_PREFERENCES"&&exact(s,[...common,"proposals"])&&Array.isArray(s.proposals)&&s.proposals.length>=1&&s.proposals.length<=6&&new Set(s.proposals.map(e=>e?.turn_id)).size===s.proposals.length&&s.proposals.every(e=>exact(e,["decision_id","turn_id","preference","adopted","event_digest"])&&ident(e.decision_id)&&ident(e.turn_id)&&prefs.includes(e.preference)&&e.adopted===false&&hash(e.event_digest));
    }
    if(s.id==="decision-change")return exact(s,["id","kind","decision_id","previous_decision_id","previous_digest","decision_digest","previous_preference","current_preference","newly_observed_changes","previous_available","current_available"])&&s.kind==="VALIDATED_HISTORICAL_COMPARISON"&&ident(s.previous_decision_id)&&s.previous_decision_id!==decisionId&&hash(s.previous_digest)&&hash(s.decision_digest)&&[...prefs,"UNRESOLVED"].includes(s.previous_preference)&&[...prefs,"UNRESOLVED"].includes(s.current_preference)&&[s.previous_available,s.current_available].every(rows=>rows===null||optionRows(rows))&&Array.isArray(s.newly_observed_changes)&&s.newly_observed_changes.length<=8&&new Set(s.newly_observed_changes.map(e=>e?.event_id)).size===s.newly_observed_changes.length&&s.newly_observed_changes.every(e=>exact(e,["event_id","at","kind","target","value","observed_at"])&&ident(e.event_id)&&e.kind==="DELAY_QUEUE"&&["A","B","*"].includes(e.target)&&[e.at,e.value,e.observed_at].every(integer));
    if(s.id==="current-review"){
      const common=["id","kind","decision_id","status","code","dispatch_authorized"];
      const bound=s.kind==="CURRENT_REVALIDATION_RESULT"?exact(s,[...common,"semantic_digest"])&&hash(s.semantic_digest):s.kind==="CURRENT_READ_ONLY_REVALIDATION"&&exact(s,[...common,"observed_us","input_digest"])&&integer(s.observed_us)&&s.observed_us>0&&hash(s.input_digest);
      return bound&&s.dispatch_authorized===false&&((s.status==="REVIEWABLE"&&s.code==="HUMAN_PREVIEW_REQUIRED")||(["REJECTED","RECHECK_REQUIRED","ERROR"].includes(s.status)&&REASONS.includes(s.code)));
    }
    if(s.id==="simulator-result"){
      const common=["id","kind","decision_id","operation_id","attempt_id","state","arrival","result_digest","time_unit","physical_delivery"];
      const bound=s.kind==="OWNED_SIMULATOR_RESULT"?exact(s,[...common,"semantic_digest"])&&hash(s.semantic_digest):s.kind==="OWNED_SIMULATOR_OPERATION_RESULT"&&exact(s,[...common,"observed_at","observation_digest"])&&integer(s.observed_at)&&hash(s.observation_digest);
      return bound&&ident(s.operation_id)&&ident(s.attempt_id)&&hash(s.result_digest)&&s.physical_delivery===false&&s.time_unit==="relative_microseconds"&&["QUEUED","BLOCKED","NOT_ACCEPTED_FINAL","ACCEPTED","DELIVERED_SIMULATED"].includes(s.state)&&(s.arrival===null||integer(s.arrival))&&(s.state!=="DELIVERED_SIMULATED"||(s.arrival!==null&&(!Object.hasOwn(s,"observed_at")||s.arrival<=s.observed_at)));
    }
    return false;
  };
  const timingBinding=records=>{
    const t=records.timing,d=records.decision,f=records.finish;
    return !!d&&!!f&&t.decision_digest===d.decision_digest&&t.decision_digest===f.decision_digest&&t.context_digest===d.context_digest&&Object.keys(t.policy).every(k=>t.policy[k]===f.policy[k]);
  };
  const progressBinding=records=>{
    const p=records["case-progress"],d=records.decision,o=records["current-operation"];
    return !!d&&!!o&&!records["decision-change"]&&p.decision_digest===d.decision_digest&&["operation_id","attempt_id","read_digest"].every(k=>p[k]===o[k]);
  };
  const context=value=>{
    const g=value.grounding,sections=TOPICS.filter(t=>t!=="PREFERENCE_CHANGE");
    if(value.response_contract!==PLAN_V2||value.renderer_version!==RENDERER||!exact(g,["decision_digest","sections","sources","source_records","operation_missing","quarantined","blocking_notice"])||!hash(g.decision_digest)||!exact(g.sections,sections)||!exact(g.sources,sections)||!record(g.source_records))return false;
    const records=g.source_records,ids=Object.keys(records);
    if(!ids.includes("chat-policy")||ids.some(id=>![...BASE,...EXTRA].includes(id)||records[id]?.id!==id||!v2source(records[id])))return false;
    if(!sections.every(t=>exact(g.sections[t],["concise","detailed"])&&Object.values(g.sections[t]).every(validAnswer)&&Array.isArray(g.sources[t])&&new Set(g.sources[t]).size===g.sources[t].length&&g.sources[t].every(id=>ids.includes(id))))return false;
    const oldSections=TOPICS.slice(0,7).filter(t=>t!=="PREFERENCE_CHANGE");
    const legacy={...value,response_contract:"chronos.case-explanation-plan.v1",renderer_version:"chronos.explanation-renderer.v1",grounding:{...g,
      sections:Object.fromEntries(oldSections.map(t=>[t,g.sections[t].concise])),sources:Object.fromEntries(oldSections.map(t=>[t,g.sources[t].filter(id=>BASE.includes(id))])),source_records:Object.fromEntries(ids.filter(id=>BASE.includes(id)).map(id=>[id,records[id]]))}};
    if(!grounding(legacy))return false;
    const expected={COMPARISON:["decision",...(records.finish?["finish"]:[]),...(records.timing?["timing"]:[])],CHAT_EFFECT:["chat-policy",...(records["chat-effect"]?["chat-effect"]:[])],CURRENT_REVIEW:records["current-review"]?["current-review"]:[],DECISION_CHANGE:records["decision-change"]?["decision-change"]:records["case-progress"]?["decision","current-operation","case-progress"]:[],DESTINATION_SIMULATION:records["simulator-result"]?["simulator-result"]:[]};
    if(!Object.entries(expected).every(([t,refs])=>same(refs,g.sources[t])))return false;
    if(records.timing&&!timingBinding(records))return false;
    if(records["case-progress"]&&!progressBinding(records))return false;
    const history=records["chat-effect"],change=records["decision-change"],sim=records["simulator-result"],op=records["current-operation"];
    if(history&&![value.conversation_revision,value.conversation_revision-1].includes(history.revision))return false;
    if(change&&(change.decision_digest!==g.decision_digest||change.current_preference!==records.decision.interpreted_preference||records.finish&&!same(change.current_available,records.finish.receipt.selection_available)))return false;
    if(sim&&(!op||sim.operation_id!==op.operation_id||sim.attempt_id!==op.attempt_id||op.state!==({DELIVERED_SIMULATED:"ACCEPTED",ACCEPTED:"ACCEPTED",NOT_ACCEPTED_FINAL:"NOT_ACCEPTED_FINAL"}[sim.state]??"UNKNOWN")))return false;
    return true;
  };
  const reply=(r,turnId)=>{
    if(!exact(r,["schema","renderer_version","conversation_id","turn_id","context_digest","catalog_digest","topics","detail","intent","answer","sections","source_ids","sources","preference","plan_origin","answer_origin","dispatch_authorized","confirmation_granted","requires_new_evaluation"])||r.schema!==REPLY_V2||r.renderer_version!==RENDERER||r.conversation_id!==conversationId||r.turn_id!==turnId||!hash(r.context_digest)||!hash(r.catalog_digest)||r.plan_origin!=="MODEL_INTERPRETATION"||r.answer_origin!=="DETERMINISTIC_EVIDENCE"||r.dispatch_authorized!==false||r.confirmation_granted!==false||!Array.isArray(r.topics)||r.topics.length<1||r.topics.length>4||new Set(r.topics).size!==r.topics.length||!r.topics.every(t=>TOPICS.includes(t))||r.topics.includes("CLARIFY")&&r.topics.length!==1||!["concise","detailed"].includes(r.detail)||!validText(r.answer,40992)||[...r.answer].length>10248)return false;
    if(!Array.isArray(r.sections)||![r.topics.length,r.topics.length+1].includes(r.sections.length)||r.sections.length>5||!r.sections.every((s,i)=>exact(s,["topic","text","source_ids"])&&s.topic===(r.topics[i]??"OPERATION_STATUS")&&validAnswer(s.text)&&Array.isArray(s.source_ids)&&new Set(s.source_ids).size===s.source_ids.length)||r.answer!==r.sections.map(s=>s.text).join("\n\n"))return false;
    if(!Array.isArray(r.sources)||r.sources.length>9||!r.sources.every(v2source)||!Array.isArray(r.source_ids)||r.source_ids.length!==r.sources.length||new Set(r.source_ids).size!==r.source_ids.length||r.sources.some((s,i)=>s.id!==r.source_ids[i]))return false;
    const refs=[...new Set(r.sections.flatMap(s=>s.source_ids))];if(!same(refs,r.source_ids))return false;
    // Archived sources must agree with each other, not with today's context.
    const records=Object.fromEntries(r.sources.map(s=>[s.id,s])),sim=records["simulator-result"],op=records["current-operation"],decision=records.decision,finish=records.finish,change=records["decision-change"];
    if(records.timing&&!timingBinding(records))return false;
    if(records["case-progress"]&&!progressBinding(records))return false;
    if(sim&&op&&(sim.operation_id!==op.operation_id||sim.attempt_id!==op.attempt_id||op.state!==({DELIVERED_SIMULATED:"ACCEPTED",ACCEPTED:"ACCEPTED",NOT_ACCEPTED_FINAL:"NOT_ACCEPTED_FINAL"}[sim.state]??"UNKNOWN")))return false;
    if(decision&&finish&&decision.decision_digest!==finish.decision_digest)return false;
    if(change&&((decision&&(change.decision_digest!==decision.decision_digest||change.current_preference!==decision.interpreted_preference))||(finish&&(change.decision_digest!==finish.decision_digest||!same(change.current_available,finish.receipt.selection_available)))))return false;
    if(op&&records["current-read-missing"])return false;
    const current=op?"current-operation":"current-read-missing";
    const references={DECISION:["decision",...(finish?["finish"]:[])],COMPARISON:["decision",...(finish?["finish"]:[]),...(records.timing?["timing"]:[])],
      OPERATION_STATUS:[current],PHYSICAL_DELIVERY:[...(sim?["simulator-result"]:[]),current],APPROVAL_REQUIREMENTS:[current],
      PREFERENCE_CHANGE:["chat-policy"],CHAT_EFFECT:["chat-policy",...(records["chat-effect"]?["chat-effect"]:[])],
      CURRENT_REVIEW:records["current-review"]?["current-review"]:[],DECISION_CHANGE:change?["decision-change"]:records["case-progress"]?["decision","current-operation","case-progress"]:[],
      DESTINATION_SIMULATION:sim?["simulator-result"]:[],CLARIFY:decision?["decision"]:[]};
    if(!r.sections.every(s=>same(s.source_ids,references[s.topic])))return false;
    if(r.topics.includes("CLARIFY")&&decision&&(decision.action!=="HOLD"||decision.reason_code!=="CONFLICTING_EVIDENCE"))return false;
    const hasExtra=r.sections.length>r.topics.length,blocked=op&&(op.quarantined||["UNKNOWN","IN_FLIGHT"].includes(op.state));
    if(hasExtra&&(!blocked||r.topics.includes("OPERATION_STATUS")))return false;
    if(blocked){
      const notice=op.quarantined?"The current read is quarantined because evidence conflicts. No settled outcome can be claimed, and confirmation cannot override this block.":
        (op.state==="UNKNOWN"?"At this read the operation outcome is UNKNOWN. This is not proof of failure and does not authorize another attempt. Query the same operation separately to resolve its result.":
          "At this read the operation is IN_FLIGHT. This records a reservation before external submission; it does not by itself prove that a destination call occurred.")+" Another submission could duplicate the effect if the earlier attempt has already been accepted.";
      if(!r.sections.some(s=>s.text.includes(notice))||(hasExtra&&r.sections.at(-1).text!==notice))return false;
    }
    const pref=r.topics.includes("PREFERENCE_CHANGE"),approval=r.topics.includes("APPROVAL_REQUIREMENTS");
    if(r.requires_new_evaluation!==pref||(pref?!prefs.includes(r.preference):r.preference!==null))return false;
    return pref?r.intent==="PREFERENCE_PROPOSAL":approval?r.intent==="APPROVAL_REDIRECT":r.topics.includes("OPERATION_STATUS")?["ANSWER","RESULT_QUERY"].includes(r.intent):r.intent==="ANSWER";
  };
  return {context,reply};
}
