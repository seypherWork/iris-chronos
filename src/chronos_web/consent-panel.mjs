import {createConsentController} from "./consent-controller.mjs";

const ID = /^[A-Za-z0-9_.-]{1,128}$/;
const BUSY = new Set(["PREPARING","CONFIRMING","REJECTING","READING_OUTCOME","READING_PREPARATION","CLOSING_PREPARATION","LOADING_PREPARATIONS"]);
const TEXT = Object.freeze({
  IDLE:"Choose a completed decision and prepare its exact approval preview.",
  PREPARING:"Reading evidence and preparing a preview. This does not approve the recovery.",
  READY:"Review the complete effect in this preview. Confirm only if it matches your intent.",
  BLOCKED:"Approval is blocked. No automatic resubmission will occur.",
  ERROR:"The review could not be prepared. Check your session and original reference.",
  PREVIEW_UNCERTAIN:"The preview reply was lost or invalid. Keep the original decision ID. Read the original preparation below; do not create another preview as recovery.",
  PREPARATION_PENDING:"The original preparation has no recorded preview yet. Read it again explicitly or close this preparation; no retry is sent.",
  PREPARATION_CLOSED:"This preparation is closed. A delayed request cannot create its preview. This does not cancel a recovery or shipment.",
  PREPARATIONS_LIST:"Saved preparations loaded for this account and installation. Select one to read its original outcome.",
  READING_PREPARATION:"Reading the original preparation without submitting another request.",
  CLOSING_PREPARATION:"Closing only this preparation against a delayed creation request.",
  LOADING_PREPARATIONS:"Checking your session and loading the saved references in this tab.",
  RECOVERED:"Original preview recovered for inspection only. Previous consent is not restored.",
  CONFIRMING:"Checking the same preview again, then submitting your single confirmation.",
  REJECTING:"Checking the same preview again, then recording rejection.",
  READING_OUTCOME:"Reading the original preview. No confirmation or recovery is repeated.",
  OUTCOME_UNCERTAIN:"The outcome is uncertain. Read the original outcome; do not repeat confirmation.",
  RESULT:"Current outcome read. Acceptance is not delivery.",
});
const CODES = Object.freeze({
  PREVIEW_EXPIRED:"The preview expired. The previous acknowledgement is invalid.",
  EXPIRED:"The preview expired. The previous acknowledgement is invalid.",
  PREVIEW_CHANGED:"The server preview changed. Your previous acknowledgement cannot authorize it.",
  REFERENCE_SCOPE_CHANGED:"The account or installation changed. Previous evidence and consent are hidden.",
  SESSION_REQUIRED:"Sign in through IRIS before continuing.",
  PERMISSION_DENIED:"The current session does not permit this action.",
  INVALID_SESSION:"The current session identity could not be verified.",
  REFERENCE_NOT_SAVED:"The original reference could not be saved and verified. No further mutation was sent.",
  PREPARATION_RESPONSE_UNCERTAIN:"The receipt could not be bound to the original request. No approval is available.",
  PRESENTATION_FAILED:"Evidence could not be displayed. Consent has been invalidated.",
  CLOCK_UNVERIFIED:"Time could not be verified. Consent is blocked.",
  STILL_PENDING_NO_RETRY:"The original preview is still pending. This does not prove an earlier confirmation cannot arrive; no retry is enabled.",
});

/** Local rendering and explicit gestures only. No network/polling at mount.
 * now/schedule/cancel are installation/test dependencies, never URL input.
 */
export function mountConsentPanel(root,{client,references,preparations,evidence,selection,onActivate,onBusy,
  renderModel,onOutcomeWarning=()=>{},preparationBlock=()=>"",now=Date.now,schedule=setTimeout,cancel=clearTimeout}={}) {
  const doc=root.ownerDocument;
  const controls=doc.createElement("div"); controls.className="chronos-consent-controls"; root.appendChild(controls);
  const make=(tag,text,parent=controls)=>{
    const e=doc.createElement(tag);if(text!==undefined)e.textContent=text;
    parent.appendChild(e);return e;
  };
  root.className="chronos-consent";
  root.setAttribute("aria-label","Exact human approval");
  make("h2","Exact human approval");
  make("p","Preparing a preview records a review in IRIS. Only an explicit confirmation can authorize the displayed recovery.");
  const prepare=make("button","Prepare exact preview");prepare.type="button";prepare.className="chronos-primary";
  const prepareReason=make("p");prepareReason.setAttribute("role","status");
  const loadPreparations=make("button","Load saved preparations");loadPreparations.type="button";
  const preparationLabel=make("label","Saved preparation");preparationLabel.className="chronos-preparation-select";
  const savedPreparations=make("select",undefined,preparationLabel);savedPreparations.setAttribute("aria-label","Saved preparations");savedPreparations.disabled=true;
  const reopenPreparation=make("button","Read saved preparation");reopenPreparation.type="button";reopenPreparation.disabled=true;
  const status=make("p");status.setAttribute("role","status");status.setAttribute("aria-live","polite");
  const refs=make("p");refs.className="hint";
  const body=make("div",undefined,root);body.className="chronos-consent-body";body.setAttribute("aria-label","Approval evidence");
  const expiry=make("p");expiry.className="hint";
  const label=make("label");label.className="chronos-consent-ack";
  const ack=make("input",undefined,label);ack.type="checkbox";ack.checked=false;
  ack.setAttribute("aria-label","I reviewed and authorize this exact recovery");
  make("span","I reviewed the evidence and authorize exactly this recovery, destination, payload and cost.",label);
  const actions=make("div");actions.className="actions";
  const confirm=make("button","Confirm exact recovery",actions);confirm.type="button";confirm.className="chronos-primary";
  const reject=make("button","Reject this preview",actions);reject.type="button";
  const read=make("button","Read original outcome",actions);read.type="button";
  const readPreparation=make("button","Read original preparation",actions);readPreparation.type="button";
  const closePreparation=make("button","Close unfinished preparation",actions);closePreparation.type="button";
  root.replaceChildren(body,controls);
  let listed=[],listedScope="";
  const clearListed=()=>{listed=[];listedScope="";savedPreparations.replaceChildren();savedPreparations.value="";savedPreparations.disabled=true;reopenPreparation.disabled=true;};
  let controller,active=false,destroyed=false,available=true,prepareBlock="",timer=null,timerGeneration=0,key="",view=null;
  const stopTimer=()=>{timerGeneration++;if(timer!==null){cancel(timer);timer=null;}};
  const clear=()=>{try{body.replaceChildren();}catch{body.textContent="";}};
  const disable=()=>{ack.checked=false;ack.disabled=true;confirm.disabled=true;reject.disabled=true;read.disabled=true;readPreparation.disabled=true;closePreparation.disabled=true;};
  const expiryText=state=>{
    expiry.textContent=state.phase==="READY" && Number.isFinite(state.view?.expiresAtMs)?
      "Preview expires at "+new Date(state.view.expiresAtMs).toISOString()+". Time remaining: "+
      Math.max(0,Math.ceil((state.view.expiresAtMs-now())/1000))+" seconds.":"";
  };
  const arm=()=>{
    stopTimer();
    const generation=timerGeneration;
    timer=schedule(()=>{
      if(generation!==timerGeneration)return;
      timer=null;if(destroyed||!active)return;
      const state=controller.tick();
      if(state.phase==="READY"){
        expiryText(state);
        if(!state.canConfirm){disable();}
        arm();
      }
    },1000);
    timer?.unref?.();
  };
  const paint=state=>{
    if(destroyed||!active)return;
    try{
      stopTimer();
      if(state.phase!=="READY"||key!==state.reviewKey)ack.checked=false;
      key=state.reviewKey;
      // Build first, but discard all old content if any projection/DOM operation fails.
      if(view!==state.view){clear();if(state.view)body.appendChild(renderModel(state.view));view=state.view;}
      ack.disabled=!state.canConfirm;
      confirm.disabled=!state.canConfirm||ack.checked!==true;
      reject.disabled=!state.canReject;
      read.disabled=!state.canReadOutcome;
      prepare.disabled=!available||Boolean(prepareBlock)||!state.canPrepare;
      readPreparation.disabled=!state.canReadPreparation;
      closePreparation.disabled=!state.canClosePreparation;
      loadPreparations.disabled=!available||BUSY.has(state.phase);
      clearListed();
      if(state.phase==="PREPARATIONS_LIST"){
        listed=state.preparations??[];listedScope=state.preparationScope??"";
        make("option","Choose a saved preparation",savedPreparations).value="";
        listed.forEach((item,index)=>{make("option",item.decisionId+" · "+item.requestId,savedPreparations).value=String(index);});
        savedPreparations.value="";savedPreparations.disabled=!available||listed.length===0;
      }
      status.textContent=CODES[state.code]??TEXT[state.phase]??TEXT.ERROR;
      refs.textContent=[state.decisionId&&"Decision: "+state.decisionId,
        state.requestId&&"Preparation: "+state.requestId,
        state.previewId&&"Original preview: "+state.previewId].filter(Boolean).join(" · ");
      body.setAttribute("aria-busy",BUSY.has(state.phase)?"true":"false");
      expiryText(state);
      onOutcomeWarning(state.canReadOutcome && (state.phase === "OUTCOME_UNCERTAIN" || state.code === "STILL_PENDING_NO_RETRY"));
      onBusy(BUSY.has(state.phase));
      if(state.phase==="READY")arm();
    }catch{
      stopTimer();key="";view=null;clear();disable();prepare.disabled=true;
      clearListed();loadPreparations.disabled=true;refs.textContent="";expiry.textContent="";status.textContent=CODES.PRESENTATION_FAILED;
      onOutcomeWarning(false);onBusy(false);throw new Error("PRESENTATION_FAILED");
    }
  };
  controller=createConsentController({client,references,preparations,evidence,now,onChange:paint});
  disable();status.textContent=TEXT.IDLE;
  const listeners=[];
  const listen=(e,type,fn)=>{e.addEventListener(type,fn);listeners.push([e,type,fn]);};
  const run=async fn=>{
    try{await fn();}
    catch{
      if(destroyed||!active)return;
      controller.tick();
      const state=controller.snapshot();
      if(state.code==="PRESENTATION_FAILED")return;
      ack.checked=false;confirm.disabled=true;
      status.textContent="Consent was not accepted. Review the current original preview before acting.";
    }
  };
  const setPreparationBlock=code=>{
    prepareBlock=["DECISION_NOT_ACTIONABLE","APPROVAL_PERMISSION_REQUIRED","DECISION_REQUIRED"].includes(code)?code:"";
    prepareReason.textContent=prepareBlock==="DECISION_NOT_ACTIONABLE"?
      "The selected decision has no actionable proposal. A new preview cannot be prepared from this result.":
      prepareBlock==="APPROVAL_PERMISSION_REQUIRED"?
      "The current session does not permit preparing an approval preview. Existing preparations can still be read.":
      prepareBlock==="DECISION_REQUIRED"?"A preview or operation reference can be read or queried. Preparing an approval requires an actionable decision.":"";
    prepare.disabled=!available||Boolean(prepareBlock)||(active&&!controller.snapshot().canPrepare);
    if(!active || controller.snapshot().phase==="IDLE") {
      status.textContent=prepareBlock?"Existing results and saved preparations remain available for inspection.":TEXT.IDLE;
    }
  };
  listen(prepare,"click",async()=>{
    if(destroyed||!available)return;
    // Re-read current presentation/session metadata at the gesture, too.
    setPreparationBlock(preparationBlock());
    if(prepare.disabled)return;
    const chosen=selection();
    if(chosen.kind!=="decision"||typeof chosen.id!=="string"||!ID.test(chosen.id)){
      status.textContent="Select Decision and enter a valid original decision ID.";return;
    }
    onActivate();active=true;key="";view=null;ack.checked=false;clear();
    await run(()=>controller.prepare(chosen.id));
  });
  listen(loadPreparations,"click",()=>{
    if(destroyed||!available||loadPreparations.disabled)return;
    onActivate();active=true;key="";view=null;ack.checked=false;clear();
    return run(()=>controller.listPreparations());
  });
  listen(savedPreparations,"change",()=>{
    const index=savedPreparations.value;
    reopenPreparation.disabled=destroyed||!available||!active||!/^\d+$/.test(index)||!listed[Number(index)];
  });
  listen(reopenPreparation,"click",()=>{
    if(destroyed||!available||!active||reopenPreparation.disabled)return;
    const pair=listed[Number(savedPreparations.value)],scope=listedScope;
    if(!pair)return;
    return run(()=>controller.reopenPreparation(pair,scope));
  });
  listen(readPreparation,"click",()=>{
    if(destroyed||!active||readPreparation.disabled)return;
    return run(()=>controller.readPreparation());
  });
  listen(closePreparation,"click",()=>{
    if(destroyed||!active||closePreparation.disabled)return;
    return run(()=>controller.closePreparation());
  });
  listen(ack,"change",()=>{
    if(destroyed||!active||ack.disabled){ack.checked=false;return;}
    const state=controller.tick();
    confirm.disabled=!state.canConfirm||state.reviewKey!==key||ack.checked!==true;
    if(!state.canConfirm)ack.checked=false;
  });
  listen(confirm,"click",()=>{
    if(destroyed||!active||confirm.disabled)return;
    return run(()=>controller.confirm(key,ack.checked===true));
  });
  listen(reject,"click",()=>{
    if(destroyed||!active||reject.disabled)return;
    return run(()=>controller.reject(key));
  });
  listen(read,"click",()=>{
    if(destroyed||!active||read.disabled)return;
    return run(()=>controller.readOutcome());
  });
  return Object.freeze({
    setPreparationBlock,
    focusOriginalOutcome() {
      if (destroyed || !active || !available || read.disabled) return;
      read.scrollIntoView?.({block:"center",behavior:"auto"});
      read.focus();
    },
    setAvailable(value){
      available=value===true;
      prepare.disabled=!available||Boolean(prepareBlock)||(active&&!controller.snapshot().canPrepare);
      loadPreparations.disabled=!available||BUSY.has(controller.snapshot().phase);
      if(!available){savedPreparations.disabled=true;reopenPreparation.disabled=true;}
    },
    deactivate(){
      active=false;stopTimer();controller.disconnect();key="";view=null;
      clear();disable();clearListed();loadPreparations.disabled=!available;refs.textContent="";expiry.textContent="";status.textContent=TEXT.IDLE;
      prepare.disabled=!available||Boolean(prepareBlock);
    },
    destroy(){
      destroyed=true;active=false;stopTimer();controller.disconnect();
      clear();disable();clearListed();loadPreparations.disabled=true;key="";view=null;refs.textContent="";expiry.textContent="";prepareReason.textContent="";
      for(const [e,type,fn]of listeners)e.removeEventListener(type,fn);
      root.replaceChildren();
    },
  });
}
