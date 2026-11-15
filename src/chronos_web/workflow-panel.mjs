import {createWorkflowController} from "./workflow-controller.mjs";

const BUSY=new Set(["CONNECTING","READING","STARTING","COMPLETING","READING_COMPLETION","REEVALUATING"]);
const TEXT=Object.freeze({
  IDLE:"Inspect the selected decision before requesting a human clarification.",
  CONNECTING:"Checking your IRIS session…",READING:"Reading the original clarification. No request is repeated.",
  EMPTY:"No clarification is recorded for this decision. Only an eligible HOLD can create a native task.",
  STARTING:"Requesting one native clarification handoff…",WAITING:"The native task may still be creating. Read its original status explicitly.",
  NEEDS_INPUT:"A native task is available. Record the customer's actual current instruction.",
  COMPLETING:"Recording the human clarification. This does not approve a shipment.",
  READING_COMPLETION:"Reading the original completion receipt. The task is not completed again.",
  RECORDED:"A historical completion receipt is recorded. A new decision still requires fresh native checks.",
  HANDOFF_UNCERTAIN:"The handoff outcome is uncertain. Read the original status; do not request another handoff.",
  COMPLETION_UNCERTAIN:"Completion is not confirmed for this view. Read the original receipt; do not submit the form again.",
  REEVALUATING:"Requesting a separately registered agent decision…",
  EVALUATION_UNCERTAIN:"Read the new decision reference or the original clarification status. Do not request another model run.",
  DECISION_REGISTERED:"A new decision reference is registered. Read it to check whether inference and validation finished.",
  EXPIRED:"The clarification expired. It cannot authorize a new decision or shipment.",
  HIDDEN:"Clarification view hidden. Resume with a fresh session to read its original status.",
  BLOCKED:"The account or installation changed. Previous clarification details are hidden.",
  ERROR:"Clarification is unavailable. Check the installation, current permissions and original reference.",
});
const ERRORS=Object.freeze({
  INVALID_REQUEST:"Use a valid decision and a short customer instruction without credentials or control characters.",
  INVALID_CLARIFICATION_NOTE:"The note is not valid. Use up to 240 characters without credentials or control characters.",
  SENSITIVE_CLARIFICATION_NOTE:"The note resembles a credential. Remove private values before recording business information.",
  PERMISSION_DENIED:"An authorized Operator and native Workflow membership are required for this action.",
  SESSION_REQUIRED:"Sign in to IRIS before continuing.",
  RECORDED_INPUT_UNSUPPORTED:"The four recorded fixtures do not cover a new human instruction. Configure a live provider to reevaluate it.",
  PRESENTATION_FAILED:"The clarification could not be displayed. New actions are blocked.",
});

/** Plain-text human clarification. Notes stay in memory, never browser storage. */
export function mountWorkflowPanel(root,{client,selection,onActivate=()=>{},onBusy=()=>{},onDecision=()=>{},newId,now}={}) {
  const doc=root.ownerDocument,listeners=[];
  const make=(tag,text,parent=root)=>{const e=doc.createElement(tag);if(text!==undefined)e.textContent=text;parent.appendChild(e);return e;};
  root.className="chronos-workflow";root.setAttribute("aria-label","Native human clarification");
  make("p","NATIVE HUMAN WORKFLOW").className="eyebrow";
  make("h2","Clarify a held decision");
  make("p","Resolve missing or conflicting customer intent through an IRIS Workflow task. The original HOLD is preserved; shipment approval remains separate.").className="hint";
  const tools=make("div");tools.className="actions";
  const open=make("button","Inspect selected clarification",tools);open.type="button";
  const read=make("button","Read original status",tools);read.type="button";
  const close=make("button","Close clarification view",tools);close.type="button";
  const status=make("p");status.setAttribute("role","status");status.setAttribute("aria-live","polite");
  const refs=make("p");refs.className="hint chronos-workflow-refs";
  const expiry=make("p");expiry.className="hint";
  const start=make("button","Request a human clarification");start.type="button";
  const form=make("form");form.className="chronos-workflow-form";form.setAttribute("aria-label","Record customer clarification");
  const prefLabel=make("label","Current customer priority",form);
  const pref=make("select",undefined,prefLabel);pref.setAttribute("aria-label","Customer priority");
  for(const [value,text] of [["EARLIEST_ALLOWED","Earliest permitted arrival"],["CHEAPEST_ON_TIME","Lowest cost arriving on time"]]) {
    const option=make("option",text,pref);option.value=value;
  }
  pref.value="EARLIEST_ALLOWED";
  const noteLabel=make("label","Customer instruction",form);
  // Native maxlength counts UTF-16 units and can truncate a valid Unicode note.
  // Validate 240 code points on submit, preserving the original draft.
  const note=make("textarea",undefined,noteLabel);note.rows=2;note.autocomplete="off";
  note.setAttribute("aria-label","Customer instruction");
  make("p","English · up to 240 characters · business information only. Never include passwords, tokens or private keys.",form).className="hint";
  const ackLabel=make("label",undefined,form);ackLabel.className="chronos-workflow-ack";
  const ack=make("input",undefined,ackLabel);ack.type="checkbox";
  ack.setAttribute("aria-label","Clarification records information only");
  make("span","I am recording current customer intent. This does not approve or send a shipment.",ackLabel);
  const complete=make("button","Record clarification",form);complete.type="submit";
  const resultActions=make("div");resultActions.className="actions";
  const readCompletion=make("button","Read original completion receipt",resultActions);readCompletion.type="button";
  const reevaluate=make("button","Request a new agent decision",resultActions);reevaluate.type="button";
  const readDecision=make("button","Read new decision",resultActions);readDecision.type="button";
  const boundary=make("p");boundary.className="hint chronos-provenance";
  make("p","After a lost reply, use the original references. Reading never repeats completion, inference or shipment. Closing this view does not cancel a native task.").className="hint";
  let controller,active=false,available=true,destroyed=false;
  function paint(v){
    if(destroyed)return;
    const busy=BUSY.has(v.phase),visible=active&&available&&v.connected;
    open.disabled=!available||busy||(!v.canOpen&&!v.canRead);
    open.textContent=v.canOpen?"Inspect selected clarification":"Resume original clarification";
    read.disabled=!available||busy||!v.canRead;close.disabled=!active||!v.canClose;
    start.disabled=!visible||!v.canStart;pref.disabled=!visible||!v.canComplete;
    note.disabled=!visible||!v.canComplete;ack.disabled=!visible||!v.canComplete;
    complete.disabled=!visible||!v.canComplete||!ack.checked;
    readCompletion.disabled=!visible||!v.canReadCompletion;
    reevaluate.disabled=!visible||!v.canReevaluate;readDecision.disabled=!visible||!v.canReadDecision;
    if(!visible){note.value="";ack.checked=false;refs.textContent="";expiry.textContent="";}
    else{
      refs.textContent="Original decision: "+v.decisionId+(v.clarificationId?" · Clarification: "+v.clarificationId:"")+
        (v.completionId?" · Completion: "+v.completionId:"")+(v.newDecisionId?" · New decision: "+v.newDecisionId:"");
      const us=v.view?.expiresUS;
      expiry.textContent=Number.isSafeInteger(us)?"Recorded expiry: "+new Date(us/1000).toISOString()+". The server enforces validity.":"";
    }
    let recorded=false;try{recorded=client.sessionExecution?.().mode==="RECORDED_FIXTURE";}catch{}
    boundary.textContent=recorded?"Recorded fixture mode cannot interpret a new clarification. Existing native receipts remain readable; a live provider is needed for the new decision.":
      "Recording intent is not adoption or approval. The new model decision must pass current checks and separate Operator preview/confirmation.";
    status.textContent=!active?TEXT.IDLE:ERRORS[v.code]??TEXT[v.phase]??TEXT.ERROR;
    onBusy(busy);
  }
  controller=createWorkflowController({client,newId,now,onChange:paint});
  const listen=(e,type,handler)=>{e.addEventListener(type,handler);listeners.push([e,type,handler]);};
  const act=async operation=>{if(destroyed)return;try{await operation();}catch{controller.deactivate();}paint(controller.snapshot());};
  listen(open,"click",()=>{
    if(open.disabled)return;
    const selected=selection?.();
    if(controller.snapshot().canOpen&&(selected?.kind!=="decision"||typeof selected.id!=="string"||!/^[A-Za-z0-9_.-]{1,128}$/.test(selected.id))) {
      status.textContent="Select a valid decision reference first. No clarification was requested.";return;
    }
    active=true;onActivate();
    return act(()=>controller.snapshot().canOpen?controller.open(selected.id):controller.read());
  });
  listen(read,"click",()=>{if(!read.disabled)return act(()=>controller.read());});
  listen(start,"click",()=>{if(!start.disabled)return act(()=>controller.start());});
  listen(form,"submit",event=>{
    event.preventDefault();if(complete.disabled||!ack.checked)return;
    const instruction=note.value,preference=pref.value;
    if(!["EARLIEST_ALLOWED","CHEAPEST_ON_TIME"].includes(preference)||
      typeof instruction!=="string"||!instruction.trim()||[...instruction].length>240||instruction!==instruction.trim()||/[\\\p{C}]/u.test(instruction)) {
      status.textContent=ERRORS.INVALID_REQUEST;note.focus();return;
    }
    // The controller freezes the original form for a lost-reply receipt read.
    // The DOM holds no submitted note after this explicit gesture.
    note.value="";ack.checked=false;
    return act(async()=>{
      await controller.complete(preference,instruction);
      const v=controller.snapshot();
      // A definitive pre-fence form rejection permits editing the same draft.
      // Uncertain replies and sensitive-looking values stay out of the DOM.
      if(active&&available&&v.connected&&v.canComplete&&
        ["INVALID_CLARIFICATION_NOTE","INVALID_CLARIFICATION_PREFERENCE","INVALID_WORKFLOW_ID"].includes(v.code)) {
        note.value=instruction;pref.value=preference;ack.checked=false;
      }
    });
  });
  listen(ack,"change",()=>paint(controller.snapshot()));
  listen(readCompletion,"click",()=>{if(!readCompletion.disabled)return act(()=>controller.readCompletion());});
  listen(reevaluate,"click",()=>{if(!reevaluate.disabled)return act(()=>controller.reevaluate());});
  listen(readDecision,"click",()=>{if(readDecision.disabled)return;const id=controller.snapshot().newDecisionId;if(id)onDecision(id);});
  listen(close,"click",()=>{if(!close.disabled&&controller.close()){active=false;paint(controller.snapshot());}});
  paint(controller.snapshot());
  return Object.freeze({setAvailable(value){available=Boolean(value);paint(controller.snapshot());},
    deactivate(){if(destroyed)return;active=false;controller.deactivate();paint(controller.snapshot());},
    destroy(){if(destroyed)return;destroyed=true;controller.destroy();for(const[e,t,h]of listeners)e.removeEventListener(t,h);root.replaceChildren();}});
}
