import {createConversationController} from "./conversation-controller.mjs";

const BUSY=new Set(["CONNECTING","OPENING","READING","SENDING"]);
const TEXT={IDLE:"Open a completed decision to discuss its evidence.",CONNECTING:"Checking your IRIS session…",
  OPENING:"Opening this case conversation…",READING:"Reading the original conversation. No question is repeated.",
  SENDING:"Waiting for an explanation. No recovery is authorized by this question.",
  READY:"Ask about the decision or what happened to the shipment.",
  PENDING:"This question has no final answer yet. Read its original status; do not resend it.",
  UNCERTAIN:"The response is uncertain. Read the original conversation to resolve it. No automatic retry.",
  ERROR:"The conversation is unavailable. Read its original status before continuing.",
  BLOCKED:"The account or installation changed. Previous conversation details are hidden.",
  HIDDEN:"Conversation hidden. Resume to check your session and read the original conversation."};
const CODES={SESSION_REQUIRED:"Sign in through IRIS before continuing.",PERMISSION_DENIED:"This session cannot read the conversation.",
  CONVERSATION_UNAVAILABLE:"Conversation is unavailable in this installation or session.",
  INVALID_REQUEST:"Select a valid completed decision first.",PRESENTATION_FAILED:"The conversation could not be displayed. Sending is blocked.",
  REFERENCE_SCOPE_CHANGED:TEXT.BLOCKED};
const LABELS={CURRENT_READ:"Current server evidence",HISTORICAL_DECISION:"Historical decision",SIMULATION:"Synthetic laboratory evidence"};
const REJECTED_MESSAGES=Object.freeze({
  MODEL_NOT_STARTED:"Chronos did not start a model call for this question before its start window closed.",
  CONTEXT_CHANGED:"Chronos could not confirm that the case context still matched this question, so the model was not started.",
  PROVIDER_REFUSED:"The model provider declined to answer this question. No answer was accepted.",
  COMPLETION_REJECTED:"Chronos could not validate the reply against this case and its required format. It was not accepted as an answer."
});
const TOPIC_LABELS={DECISION:"Why this option",COMPARISON:"Comparing the options",OPERATION_STATUS:"Recorded operation",PHYSICAL_DELIVERY:"Delivery evidence",PREFERENCE_CHANGE:"Proposed priority",APPROVAL_REQUIREMENTS:"Before confirming",CLARIFY:"Clarification needed",CHAT_EFFECT:"What the chat changed",CURRENT_REVIEW:"Current review",DECISION_CHANGE:"What changed between decisions",DESTINATION_SIMULATION:"Simulator result"};

/** Plain-text English case discussion. Never grants approval or applies preferences. */
export function mountConversationPanel(root,{client,selection,onActivate=()=>{},onBusy=()=>{},newId}={}) {
  const doc=root.ownerDocument, listeners=[];
  const make=(tag,text,parent=root)=>{const e=doc.createElement(tag);if(text!==undefined)e.textContent=text;parent.appendChild(e);return e;};
  root.className="chronos-conversation";root.setAttribute("aria-label","Case conversation");
  make("p","UNDERSTAND THE DECISION",root).className="eyebrow";
  make("h2","Ask Chronos");
  make("p","Explore the evidence behind a proposal. A chat message cannot approve a recovery or change your preferences.").className="hint";
  const tools=make("div");tools.className="actions";
  const open=make("button","Open case conversation",tools);open.type="button";
  const read=make("button","Read original conversation",tools);read.type="button";
  const close=make("button","Close conversation view",tools);close.type="button";
  const status=make("p");status.setAttribute("role","status");status.setAttribute("aria-live","polite");
  const refs=make("p");refs.className="hint chronos-chat-refs";
  make("p","Message history — scroll inside to read all replies and cited evidence.").className="hint";
  const transcript=make("div");transcript.className="chronos-chat-transcript";transcript.setAttribute("aria-label","Conversation transcript");
  transcript.setAttribute("role","region");transcript.setAttribute("tabindex","0");
  transcript.setAttribute("aria-description","Scrollable message history. Use the arrow keys to read earlier answers and Tab to reach cited evidence or the question field.");
  const replyNotice=make("div");replyNotice.className="actions";
  const replyStatus=make("span",undefined,replyNotice);replyStatus.setAttribute("role","status");replyStatus.setAttribute("aria-live","polite");
  const latest=make("button","Show latest reply",replyNotice);latest.type="button";latest.hidden=true;
  const prompts=make("div");prompts.className="actions chronos-chat-prompts";
  const starters=["Why was this decision made?","What happened to the shipment?","What is still uncertain?"].map(q=>{
    const b=make("button",q,prompts);b.type="button";return b;
  });
  const form=make("form");form.className="chronos-chat-composer";form.setAttribute("aria-label","Ask about this case");
  const label=make("label","Your question",form);
  const input=make("textarea",undefined,label);input.rows=3;input.maxLength=2048;input.autocomplete="off";
  input.setAttribute("aria-label","Question for Chronos");input.setAttribute("aria-describedby","chronos-chat-help");
  const hint=make("p","English · up to 2,048 UTF-8 bytes · six questions per conversation. Never include passwords or tokens.",form);
  hint.className="hint";hint.id="chronos-chat-help";
  const send=make("button","Ask Chronos",form);send.type="submit";
  const count=make("p");count.className="hint";
  let active=false,available=true,destroyed=false,controller;
  let lastConversation="",lastReply="",sourceNodes=[],summaryNodes=new Map(),latestQuestion=null,followPending=null,phase="IDLE";
  const atBottom=()=>Math.max(0,(transcript.scrollHeight??0)-(transcript.clientHeight??0)-(transcript.scrollTop??0))<=24;
  function clearNotice(){replyStatus.textContent="";latest.hidden=true;}
  function revealLatest(){
    if(!latestQuestion)return;
    const target=latestQuestion.getBoundingClientRect?.(),history=transcript.getBoundingClientRect?.();
    transcript.scrollTop=target&&history?Math.max(0,(transcript.scrollTop??0)+target.top-history.top):(transcript.scrollHeight??0);
    clearNotice();
  }
  function paint(v){
    if(destroyed)return;
    const busy=BUSY.has(v.phase),allowed=active&&available&&v.canSend;
    const oldTop=transcript.scrollTop??0,oldOpen=sourceNodes.map(e=>e.open===true);
    const focusedTurn=[...summaryNodes].find(([,node])=>node===doc.activeElement)?.[0]??null;
    const sameConversation=Boolean(v.conversationId&&v.conversationId===lastConversation);
    phase=v.phase;
    if(!active||!available||!v.view||!sameConversation){clearNotice();if(!sameConversation||!v.view)followPending=null;}
    sourceNodes=[];summaryNodes=new Map();latestQuestion=null;
    open.disabled=!available||busy||(!v.canOpen&&!v.canRead);
    open.textContent=v.canOpen?"Open case conversation":"Resume conversation";
    read.disabled=!available||busy||!v.canRead;
    close.disabled=!active||!v.canClose;
    if(!v.conversationId)input.value="";
    input.disabled=!allowed;send.disabled=!allowed;
    starters.forEach(b=>{b.disabled=!allowed;});
    transcript.replaceChildren();refs.textContent="";count.textContent="";
    if(!active){lastConversation="";lastReply="";status.textContent=TEXT.IDLE;return;}
    status.textContent=CODES[v.code]??TEXT[v.phase]??TEXT.ERROR;
    if(v.conversationId)refs.textContent="Decision: "+v.decisionId+" · Conversation: "+v.conversationId+(v.turnId?" · Last question: "+v.turnId:"");
    const packet=v.view;
    if(packet){
      const turns=packet.conversation.turns;
      count.textContent=turns.length+" / 6 questions recorded"+(turns.length===6?". Conversation limit reached; existing answers remain readable.":"");
      if(!turns.length)make("p","The case is open. Choose a question below or write your own.",transcript).className="hint";
      for(const turn of turns){
        const question=make("article",undefined,transcript);question.className="chronos-chat-question";
        latestQuestion=question;
        make("h3","You",question);make("p",turn.user_text,question);
        const reply=make("article",undefined,transcript);reply.className="chronos-chat-answer";
        make("h3","Chronos",reply);
        if(!turn.response){
          const rejected=Object.hasOwn(REJECTED_MESSAGES,turn.error)?REJECTED_MESSAGES[turn.error]:"This question could not produce an accepted answer.";
          make("p",turn.state==="REJECTED"?rejected:
            "Answer pending or uncertain. Read the original conversation before asking again.",reply);
          continue;
        }
        const response=turn.response;
        const topics=response.topics??[response.topic];
        const origin=response.answer_origin !== "DETERMINISTIC_EVIDENCE" ? "Model interpretation · check the evidence" :
          topics.includes("PREFERENCE_CHANGE") ? "Model-interpreted preference · not applied" :
          topics.includes("CLARIFY") ? "Clarification needed · no decision or action" :
          "Explanation from checked case records · question interpreted by the model";
        make("p",origin,reply).className="chronos-provenance";
        if(response.schema==="chronos.case-explanation.v2"){
          for(const section of response.sections){
            make("h4",TOPIC_LABELS[section.topic],reply);
            make("p",section.text,reply).className="chronos-chat-answer-text";
          }
        }else make("p",response.answer,reply).className="chronos-chat-answer-text";
        if(response.intent==="PREFERENCE_PROPOSAL")make("p","Suggested preference: "+response.preference+
          ". A separate new evaluation is required. No preference has been applied.",reply).className="chronos-chat-boundary";
        if(response.intent==="APPROVAL_REDIRECT")make("p","Resolve any uncertainty or stated blockers before requesting a fresh preview. Exact human approval cannot override them.",reply).className="chronos-chat-boundary";
        const sources=make("details",undefined,reply);sources.className="chronos-fold";
        if(sameConversation)sources.open=oldOpen[sourceNodes.length]===true;
        sourceNodes.push(sources);
        const summary=make("summary",response.answer_origin === "DETERMINISTIC_EVIDENCE" && !response.source_ids.length ?
          "About this interpretation" : "Evidence cited ("+response.source_ids.length+")",sources);
        summaryNodes.set(turn.turn_id,summary);
        if(response.answer_origin === "DETERMINISTIC_EVIDENCE"){
          if(!response.source_ids.length)make("p",topics.includes("PREFERENCE_CHANGE") ?
            "This is a proposed interpretation of your message, not evidence of a recorded change." :
            "No supporting record is available for these topics. The answer states that limitation; it is not proof of an outcome.",sources);
          if(response.context_digest!==packet.context_digest)make("p","Archived evidence for this answer. Current case changes do not rewrite its sources.",sources).className="hint";
          for(const item of response.sources){
            make("h4",item.id,sources);
            if(item.kind === "HISTORICAL_DECISION")make("p","Recorded proposal: "+item.action+" · preference: "+item.interpreted_preference+". Historical evidence; this does not prove execution.",sources);
            else if(item.kind === "ARCHIVED_FINISH_VALIDATION"){
              const snapshot=item.receipt.selection_basis === "BOUND_PREPARE" ? "Original selection snapshot" : "Final validation snapshot";
              const evidence=item.trial_mode === "WITHOUT_TRIALS_ABLATION" ? "Analytical estimates without executed simulations" : "Recorded simulations";
              const time=t=>t%60000000===0 ? (t/60000000)+" min" : t+" microseconds";
              make("p",snapshot+" · "+evidence+". Costs are synthetic units; times share the case timeline. This does not establish physical delivery.",sources);
              for(const row of item.receipt.selection_available)make("p",row.action+": cost "+row.cost+" synthetic units; predicted arrival at "+time(row.arrival)+" on the case timeline.",sources);
              make("p","Budget: "+item.policy.budget+" synthetic units. Deadline: "+time(item.policy.deadline)+".",sources);
            }else if(item.kind === "ARCHIVED_TIMING_SNAPSHOT"){
              const time=t=>t%60000000===0?(t/60000000)+" min":"approximately "+(t/60000000).toFixed(2)+" min ("+t+" microseconds)";
              make("p","Original timing snapshot at "+time(item.observed_at)+" on the case timeline. Historical inputs, not a current shipment result.",sources);
              for(const key of ["A","B"]){const row=item.options[key];make("p",key+": cost "+row.cost+" synthetic units; available at "+time(row.available_at)+"; base queue "+time(row.queue_duration)+"; travel "+time(row.travel_duration)+".",sources);}
              make("p","Inventory expires at "+time(item.policy.inventory_expires)+"; delivery deadline "+time(item.policy.deadline)+"; offer expires at "+time(item.policy.offer_until)+". Base queue excludes additional queue-change events. Consult final validation separately.",sources);
            }else if(item.kind === "CURRENT_READ")make("p","Operation "+item.operation_id+": "+item.state+(item.quarantined?" · conflicting evidence; blocked":"")+". This is the read saved with this answer; acceptance is not physical delivery.",sources);
            else if(item.kind==="CODE_POLICY")make("p","Chat can explain and propose a priority. It cannot apply that priority, confirm a recovery or send a shipment.",sources);
            else if(item.kind==="CHECKED_CHAT_HISTORY")make("p","Checked conversation history: no proposed priority was recorded in this snapshot. This does not change the case.",sources);
            else if(item.kind==="RECORDED_CHAT_PREFERENCES"){
              for(const event of item.proposals)make("p","Question "+event.turn_id+": proposed "+event.preference+". Not applied.",sources);
            }else if(item.kind==="ONE_DECISION_WITH_OPERATION_READ"){
              make("p","One historical decision and the separately supplied operation read: "+item.operation_id+", attempt "+item.attempt_id+". These linked records do not prove a change between two decisions, physical delivery or an action by this chat.",sources);
            }else if(item.kind==="VALIDATED_HISTORICAL_COMPARISON"){
              make("p","Earlier decision: "+item.previous_decision_id+". Priority then: "+item.previous_preference+"; priority in this decision: "+item.current_preference+". These are checked historical records, not a new instruction.",sources);
              make("p",item.newly_observed_changes.length+" newly observed case changes recorded in the comparison.",sources);
            }else if(["CURRENT_REVALIDATION_RESULT","CURRENT_READ_ONLY_REVALIDATION"].includes(item.kind)){
              make("p",item.status==="REVIEWABLE"?"The read-only review passed at this answer's snapshot. A separate fresh preview and human confirmation are still required.":"The read-only review did not authorize the proposal. Recorded reason: "+item.code+". Review the explanation before a separate new evaluation.",sources);
            }else if(["OWNED_SIMULATOR_RESULT","OWNED_SIMULATOR_OPERATION_RESULT"].includes(item.kind)){
              make("p","Owned simulator operation "+item.operation_id+": "+item.state+". This describes the synthetic destination only; it does not prove physical delivery.",sources);
            }else make("p","No current operation read was supplied for this answer. No execution or delivery conclusion follows from that absence.",sources);
          }
        }else if(response.context_digest!==packet.context_digest){
          make("p","This answer refers to an earlier evidence snapshot. Its cited IDs are retained; current evidence is not substituted for that snapshot.",sources);
          response.source_ids.forEach(id=>make("p",id,sources));
        }else{
          for(const id of response.source_ids){
            const item=packet.context.evidence.find(e=>e.id===id);
            make("h4",id,sources);
            make("p",item?LABELS[item.provenance]??"Evidence provenance unavailable":"Cited evidence is unavailable in this snapshot.",sources).className="hint";
            if(item)make("p",item.text,sources);
          }
        }
      }
    }
    const finalTurn=packet?.conversation.turns.at(-1);
    const replyKey=finalTurn?.response?finalTurn.turn_id+":"+finalTurn.state:"";
    const arrived=sameConversation&&Boolean(replyKey)&&replyKey!==lastReply;
    transcript.scrollTop=sameConversation?oldTop:0;
    if(arrived){
      if(followPending===true&&focusedTurn===null)revealLatest();
      else {replyStatus.textContent="New reply available.";latest.hidden=false;}
      followPending=null;
    }
    // Restore only a citation summary that actually held focus before this render.
    // Match its stable turn identity; never steal focus from the composer/page.
    if(sameConversation&&focusedTurn!==null&&summaryNodes.has(focusedTurn)){
      summaryNodes.get(focusedTurn).focus({preventScroll:true});transcript.scrollTop=oldTop;
    }
    lastConversation=packet?v.conversationId:"";lastReply=replyKey;
    onBusy(busy);
  }
  function render(v){
    try {paint(v);}
    catch {
      try {transcript.replaceChildren();} catch {transcript.textContent="";}
      clearNotice();followPending=null;lastConversation="";lastReply="";
      refs.textContent="";input.value="";count.textContent="";
      for(const e of [open,read,close,input,send,...starters])e.disabled=true;
      status.textContent=CODES.PRESENTATION_FAILED;
      throw new Error("PRESENTATION_FAILED");
    }
  }
  const listen=(e,event,fn)=>{e.addEventListener(event,fn);listeners.push([e,event,fn]);};
  listen(transcript,"scroll",()=>{
    if(phase==="SENDING"&&followPending===true&&!atBottom())followPending=false;
    if(atBottom())clearNotice();
  });
  listen(latest,"click",()=>{if(destroyed||latest.hidden)return;revealLatest();transcript.focus();});
  controller=createConversationController({client,...(newId?{newId}:{}),onChange:render});
  function activate(){
    if(active)return;
    onActivate();if(destroyed)return;
    active=true;input.value="";
  }
  listen(open,"click",async()=>{
    if(destroyed||open.disabled)return;
    const v=controller.snapshot();
    if(v.canRead){activate();if(!destroyed)await controller.read();return;}
    const chosen=selection();
    if(chosen?.kind!=="decision"||!/^[A-Za-z0-9_.-]{1,128}$/.test(chosen.id??"")){
      status.textContent="Select the original completed decision ID above.";return;
    }
    activate();if(!destroyed)await controller.open(chosen.id);
  });
  listen(read,"click",async()=>{if(destroyed||read.disabled)return;activate();if(!destroyed)await controller.read();});
  listen(close,"click",()=>{if(destroyed||close.disabled)return;input.value="";controller.close();});
  starters.forEach(b=>listen(b,"click",()=>{if(destroyed||b.disabled)return;input.value=b.textContent;input.focus();}));
  listen(form,"submit",async event=>{
    event.preventDefault();if(destroyed||!active||send.disabled)return;
    const question=input.value;
    if(!question.trim()||new TextEncoder().encode(question).length>2048||/[\u0000-\u0008\u000b-\u001f\ud800-\udfff]/u.test(question)){
      status.textContent="Enter a question within 2,048 UTF-8 bytes, without control characters.";return;
    }
    followPending=atBottom();clearNotice();input.value="";await controller.send(question);
  });
  render(controller.snapshot());
  return Object.freeze({
    setAvailable(value){available=value===true;render(controller.snapshot());},
    deactivate(){if(destroyed)return;active=false;input.value="";controller.deactivate();},
    destroy(){if(destroyed)return;destroyed=true;active=false;input.value="";controller.destroy();
      for(const [e,event,fn]of listeners)e.removeEventListener(event,fn);root.replaceChildren();},
  });
}
