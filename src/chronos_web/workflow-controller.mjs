import {ChronosClientError} from "./client.mjs";

const ID=/^[A-Za-z0-9_.-]{1,128}$/;
const HASH=/^[a-f0-9]{64}$/;
const BUSY=new Set(["CONNECTING","READING","STARTING","COMPLETING","READING_COMPLETION","REEVALUATING"]);
const copy=value=>value===null?null:JSON.parse(JSON.stringify(value));
const fail=code=>new ChronosClientError(code);
const verified=r=>r?.code==="WORKFLOW_CLARIFICATION_RECORDED"&&r.actorVerified===true&&r.completionVerified===true&&r.dispatch_authorized===false;

/** Explicit human gestures. No polling, automatic retries, persistence of notes,
 * shipment confirmation or send. Historical metadata is never an action grant.
 */
export function createWorkflowController({client,newId=()=>globalThis.crypto.randomUUID(),now=Date.now,onChange=()=>{}}={}) {
  for(const name of ["connect","disconnect","sessionStatus","sessionIdentity","startClarification","readClarification",
    "completeClarification","readClarificationCompletion","reevaluateClarification"]) {
    if(typeof client?.[name]!=="function")throw new TypeError("INVALID_WORKFLOW_CLIENT");
  }
  if(typeof newId!=="function"||typeof now!=="function"||typeof onChange!=="function")throw new TypeError("INVALID_WORKFLOW_CONTROLLER");
  let context=null,epoch=0,destroyed=false,blocked=false,state={phase:"IDLE",code:"",view:null};
  function key(){
    const access=client.sessionStatus(),identity=client.sessionIdentity();
    if(!access.connected||!access.canRead)throw fail("SESSION_REQUIRED");
    if(!identity.available||!/^principal-[a-f0-9]{64}$/.test(identity.actor)||!HASH.test(identity.actorScope)||
      typeof identity.applicationUrl!=="string"||!identity.applicationUrl)throw fail("INVALID_SESSION");
    return JSON.stringify([identity.actor,identity.actorScope,identity.applicationUrl]);
  }
  function connected(){try{return Boolean(context?.identity&&key()===context.identity);}catch{return false;}}
  function live(){try{return client.sessionExecution?.().mode==="LIVE_MODEL";}catch{return false;}}
  function snapshot(){
    const visible=connected(),busy=BUSY.has(state.phase),ctx=visible?context:null;
    const expires=ctx?.packet?.expiresUS;
    const expired=Number.isSafeInteger(expires)&&Number.isFinite(now())&&now()*1000>=expires;
    const approve=visible&&client.sessionStatus().canApprove===true;
    return Object.freeze({...state,view:visible?copy(state.view):null,decisionId:ctx?.decisionId??"",
      clarificationId:ctx?.clarificationId??"",completionId:ctx?.completionId??"",newDecisionId:ctx?.newDecisionId??"",
      connected:visible,canOpen:!destroyed&&!context&&!busy,canRead:!destroyed&&Boolean(context)&&!busy,
      canStart:!blocked&&!busy&&approve&&ctx?.packet?.state==="NOT_FOUND"&&!ctx.handoffRequested,
      canComplete:!blocked&&!busy&&approve&&!expired&&Boolean(ctx?.clarificationId)&&ctx?.packet?.taskReady===true&&
        !ctx.packet.completionRecorded&&!ctx.completionPending&&!ctx.completionId&&!ctx.newDecisionId,
      canReadCompletion:!busy&&approve&&Boolean(ctx?.completionId&&ctx?.completionFields),
      canReevaluate:!blocked&&!busy&&approve&&!expired&&live()&&ctx?.completionRecorded===true&&
        !ctx.completionPending&&!ctx.newDecisionId&&!ctx.reevaluationRequested,
      canReadDecision:!busy&&visible&&Boolean(ctx?.newDecisionId),
      canClose:!destroyed&&Boolean(context)&&!busy&&!context.completionPending&&!context.reevaluationPending&&!context.handoffPending});
  }
  function publish(phase,code="",view=null,version=epoch){
    if(destroyed||version!==epoch)return false;
    state={phase,code,view};
    try{const r=onChange(snapshot());if(r&&typeof r.then==="function"){Promise.resolve(r).catch(()=>{});throw fail("PRESENTATION_FAILED");}return !destroyed&&version===epoch;}
    catch{blocked=true;state={phase:"ERROR",code:"PRESENTATION_FAILED",view:null};return false;}
  }
  function same(version,ctx){
    if(destroyed||version!==epoch||context!==ctx)throw fail("CONNECTION_CHANGED");
    if(key()!==ctx.identity)throw fail("REFERENCE_SCOPE_CHANGED");
  }
  function status(packet,version,ctx){
    same(version,ctx);
    if(!packet||packet.decisionId!==ctx.decisionId||packet.dispatch_authorized!==false||packet.canUseClarification!==false||
      typeof packet.completionRecorded!=="boolean"||typeof packet.newDecisionId!=="string")throw fail("INVALID_WORKFLOW_RESPONSE");
    if(ctx.clarificationId&&packet.clarificationId&&ctx.clarificationId!==packet.clarificationId)throw fail("INVALID_WORKFLOW_RESPONSE");
    // These fixed native responses occur before ProcessInput. Other missing
    // results, including NOT_FOUND after a lost reply, retain uncertainty.
    if(["WORKFLOW_HANDOFF_UNAVAILABLE","WORKFLOW_SOURCE_NOT_ELIGIBLE","WORKFLOW_SOURCE_EXPIRED"].includes(packet.code)) {
      ctx.handoffPending=false;
    }
    if(packet.clarificationId){ctx.clarificationId=packet.clarificationId;ctx.handoffPending=false;}
    if(packet.newDecisionId){
      if(ctx.newDecisionId&&ctx.newDecisionId!==packet.newDecisionId)throw fail("INVALID_WORKFLOW_RESPONSE");
      ctx.newDecisionId=packet.newDecisionId;ctx.reevaluationPending=false;ctx.reevaluationRequested=true;
      ctx.completionFields=null;ctx.completionPending=false;
    }
    ctx.packet=copy(packet);ctx.completionRecorded=packet.completionRecorded;blocked=false;
    const phase=ctx.reevaluationPending?"EVALUATION_UNCERTAIN":ctx.newDecisionId?"DECISION_REGISTERED":ctx.completionPending?"COMPLETION_UNCERTAIN":
      packet.state==="EXPIRED"?"EXPIRED":packet.completionRecorded?"RECORDED":packet.taskReady?"NEEDS_INPUT":
      packet.state==="NOT_FOUND"?(ctx.handoffPending?"HANDOFF_UNCERTAIN":"EMPTY"):
      packet.state==="UNAVAILABLE"?"ERROR":
      packet.state==="CREATION_UNCERTAIN"?"HANDOFF_UNCERTAIN":"WAITING";
    publish(phase,packet.code,packet,version);
  }
  function failed(error,version,ctx){
    if(destroyed||version!==epoch)return;
    if(error?.code==="REFERENCE_SCOPE_CHANGED"){context=null;publish("BLOCKED","REFERENCE_SCOPE_CHANGED",null,version);return;}
    const known=new Set(["SESSION_REQUIRED","PERMISSION_DENIED","REFERENCE_SCOPE_CHANGED","CONNECTION_CHANGED","REQUEST_TIMEOUT",
      "INVALID_REQUEST","INVALID_SESSION","RECORDED_INPUT_UNSUPPORTED","INVALID_WORKFLOW_RESPONSE","PRESENTATION_FAILED"]);
    const code=error instanceof ChronosClientError&&known.has(error.code)?error.code:"WORKFLOW_UNAVAILABLE";
    publish(ctx?.reevaluationPending?"EVALUATION_UNCERTAIN":ctx?.completionPending?"COMPLETION_UNCERTAIN":
      ctx?.handoffPending?"HANDOFF_UNCERTAIN":"ERROR",code,null,version);
  }
  async function run(phase,action){
    if(destroyed||!context||BUSY.has(state.phase))return false;
    const ctx=context,version=++epoch;
    if(!publish("CONNECTING","",null,version))return false;
    try{
      await client.connect();if(destroyed||version!==epoch||context!==ctx)return false;
      if(!ctx.identity)ctx.identity=key();same(version,ctx);
      if(!publish(phase,"",null,version))return false;
      same(version,ctx);
      await action(ctx,version);return true;
    }catch(error){failed(error,version,ctx);return false;}
  }
  async function open(decisionId){
    if(!snapshot().canOpen||typeof decisionId!=="string"||!ID.test(decisionId))return false;
    context={identity:"",decisionId,clarificationId:"",completionId:"",completionFields:null,completionPending:false,
      completionRecorded:false,newDecisionId:"",reevaluationRequested:false,reevaluationPending:false,
      handoffRequested:false,handoffPending:false,packet:null};
    return run("READING",async(ctx,v)=>status(await client.readClarification(ctx.decisionId),v,ctx));
  }
  const read=()=>snapshot().canRead?run("READING",async(ctx,v)=>status(await client.readClarification(ctx.decisionId),v,ctx)):Promise.resolve(false);
  const start=()=>snapshot().canStart?run("STARTING",async(ctx,v)=>{
    if(!client.sessionStatus().canApprove)throw fail("PERMISSION_DENIED");same(v,ctx);
    ctx.handoffRequested=true;ctx.handoffPending=true;
    status(await client.startClarification(ctx.decisionId),v,ctx);
  }):Promise.resolve(false);
  async function complete(preference,note){
    if(!snapshot().canComplete||!["EARLIEST_ALLOWED","CHEAPEST_ON_TIME"].includes(preference)||
      typeof note!=="string"||!note.trim()||[...note].length>240||note!==note.trim()||/[\\\p{C}]/u.test(note))return false;
    return run("COMPLETING",async(ctx,v)=>{
      if(!client.sessionStatus().canApprove)throw fail("PERMISSION_DENIED");same(v,ctx);
      const completionId=newId();if(typeof completionId!=="string"||!ID.test(completionId))throw fail("INVALID_REQUEST");
      ctx.completionId=completionId;ctx.completionFields=Object.freeze({preference,note});ctx.completionPending=true;
      const receipt=await client.completeClarification(ctx.clarificationId,completionId,ctx.completionFields);same(v,ctx);
      if(verified(receipt)){ctx.completionPending=false;ctx.completionRecorded=true;ctx.completionFields=null;}
      if(["INVALID_WORKFLOW_ID","INVALID_CLARIFICATION_PREFERENCE","INVALID_CLARIFICATION_NOTE","SENSITIVE_CLARIFICATION_NOTE"].includes(receipt.code)) {
        ctx.completionPending=false;ctx.completionFields=null;ctx.completionId="";
        publish("NEEDS_INPUT",receipt.code,receipt,v);return;
      }
      publish(verified(receipt)?"RECORDED":"COMPLETION_UNCERTAIN",receipt.code,receipt,v);
    });
  }
  const readCompletion=()=>snapshot().canReadCompletion?run("READING_COMPLETION",async(ctx,v)=>{
    if(!client.sessionStatus().canApprove)throw fail("PERMISSION_DENIED");same(v,ctx);
    const receipt=await client.readClarificationCompletion(ctx.clarificationId,ctx.completionId,ctx.completionFields);same(v,ctx);
    if(verified(receipt)){ctx.completionPending=false;ctx.completionRecorded=true;ctx.completionFields=null;}
    // NEW is not proof that a lost original request cannot still arrive.
    publish(verified(receipt)?"RECORDED":"COMPLETION_UNCERTAIN",receipt.code,receipt,v);
  }):Promise.resolve(false);
  const reevaluate=()=>snapshot().canReevaluate?run("REEVALUATING",async(ctx,v)=>{
    if(!client.sessionStatus().canApprove)throw fail("PERMISSION_DENIED");if(!live())throw fail("RECORDED_INPUT_UNSUPPORTED");same(v,ctx);
    const id=newId();if(typeof id!=="string"||!ID.test(id)||id.length>64)throw fail("INVALID_REQUEST");
    ctx.newDecisionId=id;ctx.reevaluationRequested=true;ctx.reevaluationPending=true;
    const r=await client.reevaluateClarification(ctx.clarificationId,id);same(v,ctx);
    if(r?.decisionId!==id||r.dispatch_authorized!==false||r.readbackRequired!==true)throw fail("INVALID_WORKFLOW_RESPONSE");
    // Only an explicit status/decision read resolves whether registration and
    // inference finished; even a normal envelope is not a proposal/approval.
    publish("EVALUATION_UNCERTAIN",r.code,r,v);
  }):Promise.resolve(false);
  function deactivate(){if(destroyed)return;epoch++;client.disconnect();publish("HIDDEN","CONNECTION_CHANGED");}
  function close(){if(!snapshot().canClose)return false;epoch++;context=null;blocked=false;publish("IDLE");return true;}
  return Object.freeze({snapshot,open,read,start,complete,readCompletion,reevaluate,close,deactivate,
    destroy(){if(destroyed)return;destroyed=true;epoch++;context=null;state={phase:"IDLE",code:"",view:null};client.disconnect();}});
}
