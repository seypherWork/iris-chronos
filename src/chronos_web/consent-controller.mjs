import {consentView} from "./consent.mjs";
import {decisionDetailView} from "./detail.mjs";
import {previewView} from "./presentation.mjs";
import {ChronosClientError} from "./client.mjs";

const ID = /^[A-Za-z0-9_.-]{1,128}$/;
const PREVIEW_IDENTITY = ["previewId","decisionId","decisionDigest","actor","generation",
  "orderId","shipmentVersion","snapshotId","operationId","option","target"];
const copy = value => JSON.parse(JSON.stringify(value));
const BUSY = new Set(["PREPARING", "CONFIRMING", "REJECTING", "READING_OUTCOME","READING_PREPARATION","CLOSING_PREPARATION","LOADING_PREPARATIONS"]);
const SAFE_CODES = new Set(["SESSION_REQUIRED","PERMISSION_DENIED","INVALID_SESSION",
  "REQUEST_TIMEOUT","CONNECTION_CHANGED","TRANSPORT_UNAVAILABLE","INVALID_RESPONSE",
  "RESPONSE_TOO_LARGE","REFERENCE_SCOPE_CHANGED","REFERENCE_NOT_SAVED",
  "DECISION_NOT_ACTIONABLE","PREVIEW_RESPONSE_UNCERTAIN","PREVIEW_CHANGED",
  "PREVIEW_EXPIRED","CLOCK_UNVERIFIED","OUTCOME_UNAVAILABLE","PRESENTATION_FAILED","PREPARATION_RESPONSE_UNCERTAIN"]);
const failure = code => new ChronosClientError(code);
const publicCode = error => error instanceof ChronosClientError && SAFE_CODES.has(error.code) ?
  error.code : "RESULT_UNAVAILABLE";

/**
 * Exact-consent orchestration for the configured live screen. Native identity,
 * authorization and effect authority remain in IRIS.
 * Every mutation is explicit. Unknown outcomes never trigger another mutation.
 */
export function createConsentController({client, references, preparations, newRequestId=()=>globalThis.crypto.randomUUID(), onChange = () => {},
  now = Date.now, evidence = "UNVERIFIED"} = {}) {
  for (const method of ["connect","disconnect","sessionStatus","sessionIdentity",
    "readDecisionDetail","preparePreview","readPreparation","closePreparation","readPreview","confirmPreview","rejectPreview"]) {
    if (typeof client?.[method] !== "function") throw new TypeError("INVALID_CONSENT_CLIENT");
  }
  if (typeof references?.remember !== "function" || typeof references?.scope !== "function" ||
      typeof preparations?.remember!=="function" || typeof preparations?.list!=="function" || typeof preparations?.scope!=="function" || typeof newRequestId!=="function" ||
      typeof onChange !== "function" || typeof now !== "function") throw new TypeError("INVALID_CONSENT_CONTROLLER");
  let epoch = 0, context = null, lastTime = 0;
  let state = Object.freeze({phase:"IDLE",code:"",decisionId:"",previewId:"",reviewKey:"",view:null});

  function clock() {
    const value = now();
    if (!Number.isSafeInteger(value) || value < 0 || value < lastTime) throw failure("CLOCK_UNVERIFIED");
    lastTime = value;
    return value;
  }
  function currentIdentity(approve = false) {
    const access = client.sessionStatus(), identity = client.sessionIdentity();
    if (!access.connected || !access.canRead || approve && !access.canApprove) throw failure("PERMISSION_DENIED");
    if (!identity.available || !/^principal-[0-9a-f]{64}$/.test(identity.actor) ||
        !/^[0-9a-f]{64}$/.test(identity.actorScope) || !references.scope()) throw failure("INVALID_SESSION");
    return identity;
  }
  function same(version, ctx, approve = false) {
    if (version !== epoch || ctx !== context) throw failure("CONNECTION_CHANGED");
    const identity = currentIdentity(false);
    if (identity.actor !== ctx.actor || references.scope() !== ctx.scope || preparations.scope()!==ctx.scope) throw failure("REFERENCE_SCOPE_CHANGED");
    if (approve && !client.sessionStatus().canApprove) throw failure("PERMISSION_DENIED");
  }
  function model(ctx, preview = ctx.preview) {
    return consentView({detail:ctx.detail,preview}, {expectedDecisionId:ctx.decisionId,
      expectedPreviewId:ctx.previewId,expectedActor:ctx.actor,nowUnixMs:clock(),evidence});
  }
  function actionable() {
    if (state.phase !== "READY" || !context || context.attempted || !context.view?.reviewable) return false;
    try {same(epoch,context,true); return model(context).reviewable;}
    catch {return false;}
  }
  function snapshot() {
    const ready = actionable();
    return Object.freeze({...state,canConfirm:ready,canReject:ready,
      canPrepare:!BUSY.has(state.phase)&&(!context?.requestId||context.preparationClosed===true)&&["IDLE","ERROR","BLOCKED","PREPARATION_CLOSED"].includes(state.phase),
      canReadOutcome:Boolean(context?.previewId&&context?.previewIdentity) && !BUSY.has(state.phase),
      requestId:context?.requestId??"",canReadPreparation:Boolean(context?.requestId&&!BUSY.has(state.phase)&&(!context.attempted||context.recoveryOnly)),
      canClosePreparation:Boolean(context?.requestId)&&!context.previewId&&!context.preparationClosed&&!BUSY.has(state.phase)});
  }
  function publish(update,version) {
    if (version !== epoch) return false;
    state = Object.freeze(update);
    try {
      const rendered = onChange(snapshot());
      if (rendered && typeof rendered.then === "function") {
        Promise.resolve(rendered).catch(() => {});
        throw failure("PRESENTATION_FAILED");
      }
    } catch {
      if (version === epoch) {
        epoch++; client.disconnect(); context=null;
        state=Object.freeze({phase:"ERROR",code:"PRESENTATION_FAILED",decisionId:"",previewId:"",reviewKey:"",view:null});
      }
      return false;
    }
    return version === epoch;
  }
  function saved(version,ctx,kind,id) {
    same(version,ctx);
    const result=references.remember({kind,id});
    same(version,ctx);
    if (!result.ok || result.scope !== ctx.scope ||
        !result.items?.some(item=>item.kind===kind&&item.id===id)) throw failure("REFERENCE_NOT_SAVED");
  }
  function fail(error,version,ctx,phase="ERROR") {
    if (version !== epoch) return snapshot();
    // A different account must not see the previous account's IDs. The original
    // scoped bookmarks stay intact for a later authenticated recovery.
    const code = publicCode(error);
    if (["REFERENCE_SCOPE_CHANGED","SESSION_REQUIRED","INVALID_SESSION"].includes(code) ||
        code === "PERMISSION_DENIED" && !client.sessionStatus().canRead) {
      context = null; ctx = null;
    }
    // Preserve only original references for explicit recovery. No stale payload
    // or previously enabled consent is kept on an error screen.
    if (ctx) {ctx.detail=null;ctx.preview=null;ctx.view=null;ctx.reviewKey="";}
    publish({phase,code:publicCode(error),decisionId:ctx?.decisionId??"",
      previewId:ctx?.previewId??"",reviewKey:"",view:null},version);
    return snapshot();
  }


  function receipt(reply,ctx) {
    const p=reply?.data, keys=["code","dispatchGranted","canConfirm","requestId","actor","decisionId","previewId","state"];
    if (!p || typeof p!=="object" || Array.isArray(p) ||
        Object.keys(p).sort().join(",")!==keys.sort().join(",") ||
        p.dispatchGranted!==false || p.canConfirm!==false ||
        !["NOT_FOUND","STARTED","RECORDED","CLOSED_NO_PREVIEW"].includes(p.state) ||
        p.code!=="PREPARATION_"+p.state || reply.code!==p.code ||
        p.requestId!==ctx.requestId || p.actor!==ctx.actor ||
        typeof p.previewId!=="string" ||
        (p.previewId!=="" && (!ID.test(p.previewId)||!p.previewId.startsWith("prep-"))) ||
        (p.state==="NOT_FOUND" ? p.decisionId!==""||p.previewId!=="" :
          p.decisionId!==ctx.decisionId || (["STARTED","RECORDED"].includes(p.state)&&p.previewId===""))) {
      throw failure("PREPARATION_RESPONSE_UNCERTAIN");
    }
    if(ctx.previewId && (p.state!=="RECORDED"||p.previewId!==ctx.previewId))throw failure("PREPARATION_RESPONSE_UNCERTAIN");
    // A reservation already observed in STARTED is immutable even before its
    // preview can be read. Keep it separate so STARTED remains closable.
    if(ctx.reservedPreviewId && p.previewId!==ctx.reservedPreviewId ||
        ctx.preparationClosed && p.state!=="CLOSED_NO_PREVIEW")throw failure("PREPARATION_RESPONSE_UNCERTAIN");
    if(p.previewId)ctx.reservedPreviewId=p.previewId;
    ctx.preparationClosed=p.state==="CLOSED_NO_PREVIEW";
    return p;
  }
  function savePreparation(version,ctx) {
    same(version,ctx,true);
    const result=preparations.remember({requestId:ctx.requestId,decisionId:ctx.decisionId});
    same(version,ctx,true);
    if (!result.ok || result.code!=="REFERENCE_REMEMBERED" || result.scope!==ctx.scope ||
        !result.items?.some(x=>x.requestId===ctx.requestId&&x.decisionId===ctx.decisionId)) {
      throw failure("REFERENCE_NOT_SAVED");
    }
  }
  async function detailFor(version,ctx,approve=false) {
    const detail=copy(await client.readDecisionDetail(ctx.decisionId));same(version,ctx,approve);
    const display=decisionDetailView(detail,{expectedId:ctx.decisionId,evidence});
    if (!display.available || detail.data.outcome.status!=="VALIDATED_PROPOSAL" ||
        detail.data.outcome.code!=="SEMANTICS_AND_HUMAN_REVIEW_REQUIRED" ||
        detail.data.context.trial_mode!=="WITH_TRIALS") throw failure("DECISION_NOT_ACTIONABLE");
    ctx.detail=detail;
  }
  async function useReceipt(reply,version,ctx) {
    same(version,ctx);
    const p=receipt(reply,ctx);
    if (p.state!=="RECORDED") {
      publish({phase:p.state==="CLOSED_NO_PREVIEW"?"PREPARATION_CLOSED":"PREPARATION_PENDING",
        code:p.code,decisionId:ctx.decisionId,previewId:"",reviewKey:"",view:null},version);
      return snapshot();
    }
    ctx.previewId=p.previewId;
    saved(version,ctx,"preview",ctx.previewId);
    if(!ctx.detail)await detailFor(version,ctx);
    const preview=copy(await client.readPreview(ctx.previewId));same(version,ctx);
    const v=preview.data;
    if(!v || v.previewId!==ctx.previewId || v.actor!==ctx.actor || v.decisionId!==ctx.decisionId ||
        v.operationId!=="preview-op-"+ctx.previewId)throw failure("PREVIEW_RESPONSE_UNCERTAIN");
    ctx.operationId=v.operationId;ctx.preview=preview;
    ctx.previewIdentity=Object.fromEntries(PREVIEW_IDENTITY.map(k=>[k,v[k]]));
    let view;
    if(ctx.recoveryOnly) {
      // A saved reference authorizes inspection only. Completed previews have an
      // operation, so they must use the outcome projection, not the pending-only
      // consent projection. Retain identity and decision binding before display.
      const d=ctx.detail.data,w=d.context;
      if(v.decisionDigest!==d.decisionDigest || v.generation!==d.generation ||
          v.reviewDeadlineUS!==d.reviewDeadlineUS || v.orderId!==w.order_id ||
          v.shipmentVersion!==w.shipment_version || v.option!==d.proposal.action ||
          v.snapshot?.payload!==d.payloadJSON)throw failure("OUTCOME_UNAVAILABLE");
      view=previewView(preview,{expectedId:ctx.previewId,evidence});
      if(!view.available || v.state==="CONFIRMED"&&!view.operation?.available)throw failure("OUTCOME_UNAVAILABLE");
    } else view=model(ctx);
    ctx.view=view;ctx.reviewKey=version+":"+ctx.previewId;
    // Reloaded references are inspect-only: local storage cannot prove that an
    // earlier confirmation was never sent. Never restore consent from a bookmark.
    const ready=view.reviewable&&!ctx.recoveryOnly&&!ctx.attempted;
    publish({phase:ready?"READY":ctx.recoveryOnly?"RECOVERED":"BLOCKED",
      code:ctx.recoveryOnly?"RECOVERED_READ_ONLY":view.status,decisionId:ctx.decisionId,
      previewId:ctx.previewId,reviewKey:ready?ctx.reviewKey:"",view},version);
    return snapshot();
  }
  async function inspectPreparation(close=false) {
    if(!context?.requestId||BUSY.has(state.phase)||context.attempted&&!context.recoveryOnly)throw failure("ORIGINAL_PREPARATION_REQUIRED");
    const version=epoch,ctx=context;
    if(close&&(ctx.previewId||ctx.preparationClosed))throw failure("PREPARATION_CANNOT_CLOSE");
    if(!publish({...state,phase:close?"CLOSING_PREPARATION":"READING_PREPARATION",code:"",reviewKey:"",view:null},version))return snapshot();
    try {
      await client.connect();same(version,ctx,close);
      const reply=copy(close?await client.closePreparation(ctx.decisionId,ctx.requestId):
        await client.readPreparation(ctx.requestId));
      same(version,ctx,close);return await useReceipt(reply,version,ctx);
    }catch(error){return fail(error,version,ctx,"PREVIEW_UNCERTAIN");}
  }
  async function listPreparations() {
    const version=++epoch;client.disconnect();context=null;lastTime=0;
    if(evidence!=="LIVE"){publish({phase:"BLOCKED",code:"NOT_LIVE",decisionId:"",previewId:"",reviewKey:"",view:null},version);return snapshot();}
    if(!publish({phase:"LOADING_PREPARATIONS",code:"",decisionId:"",previewId:"",reviewKey:"",view:null},version))return snapshot();
    try {
      await client.connect();if(version!==epoch)return snapshot();
      currentIdentity();const scope=references.scope(),result=preparations.list();
      if(version!==epoch)return snapshot();
      if(!result.ok||result.scope!==scope||references.scope()!==scope||preparations.scope()!==scope)throw failure("REFERENCE_SCOPE_CHANGED");
      publish({phase:"PREPARATIONS_LIST",code:"",decisionId:"",previewId:"",reviewKey:"",view:null,
        preparations:result.items,preparationScope:scope},version);
      return snapshot();
    }catch(error){return fail(error,version,null);}
  }
  async function reopenPreparation(reference,scope) {
    if(!reference||typeof reference.requestId!=="string"||!ID.test(reference.requestId)||
        typeof reference.decisionId!=="string"||!ID.test(reference.decisionId)||
        typeof scope!=="string"||scope==="")throw failure("INVALID_PREPARATION_REFERENCE");
    // Copy public identifiers before any asynchronous or user-controlled work.
    const pair={requestId:reference.requestId,decisionId:reference.decisionId};
    const version=++epoch;client.disconnect();context=null;lastTime=0;
    if(evidence!=="LIVE"){publish({phase:"BLOCKED",code:"NOT_LIVE",decisionId:"",previewId:"",reviewKey:"",view:null},version);return snapshot();}
    if(!publish({phase:"READING_PREPARATION",code:"",decisionId:"",previewId:"",reviewKey:"",view:null},version))return snapshot();
    let ctx=null;
    try {
      await client.connect();if(version!==epoch)return snapshot();
      const identity=currentIdentity(),stored=preparations.list();
      if(!stored.ok||stored.scope!==scope||references.scope()!==scope||preparations.scope()!==scope||
          !stored.items.some(x=>x.requestId===pair.requestId&&x.decisionId===pair.decisionId))throw failure("REFERENCE_SCOPE_CHANGED");
      ctx={...pair,actor:identity.actor,scope,previewId:"",operationId:"",attempted:true,recoveryOnly:true,
        preparationClosed:false,detail:null,preview:null,view:null,reviewKey:""};
      context=ctx;
      const reply=copy(await client.readPreparation(ctx.requestId));same(version,ctx);
      return await useReceipt(reply,version,ctx);
    }catch(error){return fail(error,version,ctx,"PREVIEW_UNCERTAIN");}
  }

  async function prepare(decisionId) {
    if (typeof decisionId !== "string" || !ID.test(decisionId)) throw new TypeError("INVALID_DECISION_ID");
    const version=++epoch;client.disconnect();context=null;lastTime=0;
    if (evidence !== "LIVE") {
      publish({phase:"BLOCKED",code:"NOT_LIVE",decisionId,previewId:"",reviewKey:"",view:null},version);
      return snapshot();
    }
    if (!publish({phase:"PREPARING",code:"",decisionId,previewId:"",reviewKey:"",view:null},version)) return snapshot();
    let ctx=null, previewRequested=false;
    try {
      await client.connect();
      if (version !== epoch) return snapshot();
      const identity=currentIdentity(true);
      ctx={decisionId,actor:identity.actor,scope:references.scope(),previewId:"",operationId:"",
        attempted:false,detail:null,preview:null,view:null,reviewKey:""};
      context=ctx;
      saved(version,ctx,"decision",decisionId);
      await detailFor(version,ctx,true);
      const requestId=newRequestId();
      if(typeof requestId!=="string"||!ID.test(requestId))throw failure("REFERENCE_NOT_SAVED");
      ctx.requestId=requestId;
      // Until uniqueness and persistence are verified this could be an older
      // reference whose prior confirmation status we cannot reconstruct.
      ctx.recoveryOnly=true;ctx.attempted=true;
      savePreparation(version,ctx);
      ctx.recoveryOnly=false;ctx.attempted=false;
      previewRequested=true;
      const reply=copy(await client.preparePreview(decisionId,ctx.requestId));
      same(version,ctx,true);
      return await useReceipt(reply,version,ctx);
    } catch(error) {
      return fail(error,version,ctx,previewRequested&&!ctx?.previewId?"PREVIEW_UNCERTAIN":"ERROR");
    }
  }

  async function observe(version,ctx) {
    const reply=copy(await client.readPreview(ctx.previewId));
    same(version,ctx);
    const p=reply.data,view=previewView(reply,{expectedId:ctx.previewId,evidence});
    if (!view.available || PREVIEW_IDENTITY.some(key=>p[key]!==ctx.previewIdentity[key]) ||
        p.actor!==ctx.actor || p.decisionId!==ctx.decisionId ||
        p.operationId!==ctx.operationId ||
        p.state==="CONFIRMED" && !view.operation?.available) throw failure("OUTCOME_UNAVAILABLE");
    const code=p.state==="CONFIRMED"?"CONFIRMATION_RECORDED":
      p.state==="REJECTED"?"REJECTION_RECORDED":"STILL_PENDING_NO_RETRY";
    // A pending read does not prove an earlier in-flight confirmation will not
    // arrive. Never restore READY or clear the attempted latch after observing.
    publish({phase:"RESULT",code,decisionId:ctx.decisionId,previewId:ctx.previewId,reviewKey:"",view},version);
    return snapshot();
  }

  async function act(kind,key,acknowledged) {
    if (!actionable() || key!==state.reviewKey || kind==="CONFIRM"&&acknowledged!==true) {
      throw failure("CONSENT_REQUIRED");
    }
    const version=epoch,ctx=context,originalKey=ctx.view.comparisonKey;
    // Consume the user's action before calling any renderer, storage or await.
    // A rejected/stale/uncertain attempt requires a separate explicit review.
    ctx.attempted=true;
    if (!publish({...state,phase:kind==="CONFIRM"?"CONFIRMING":"REJECTING",code:"",reviewKey:""},version)) return snapshot();
    let attemptedRemote=false;
    try {
      await client.connect();same(version,ctx,true);
      const reply=copy(await client.readPreview(ctx.previewId));same(version,ctx,true);
      const fresh=model(ctx,reply);
      if (!fresh.reviewable) throw failure(fresh.status==="EXPIRED"?"PREVIEW_EXPIRED":
        fresh.status==="CLOCK_UNVERIFIED"?"CLOCK_UNVERIFIED":"PREVIEW_CHANGED");
      if (fresh.comparisonKey!==originalKey) throw failure("PREVIEW_CHANGED");
      saved(version,ctx,"preview",ctx.previewId);
      same(version,ctx,true);
      // Storage/render time also counts; expiration is checked again immediately
      // before the request. Native IRIS performs its own authoritative checks.
      if (!model(ctx,reply).reviewable) throw failure("PREVIEW_EXPIRED");
      attemptedRemote=true;
      if (kind==="CONFIRM") await client.confirmPreview(ctx.previewId);
      else await client.rejectPreview(ctx.previewId);
      same(version,ctx,true);
      return await observe(version,ctx);
    } catch(error) {
      return fail(error,version,ctx,attemptedRemote?"OUTCOME_UNCERTAIN":"BLOCKED");
    }
  }

  async function readOutcome() {
    if (!context?.previewId || BUSY.has(state.phase)) throw failure("ORIGINAL_PREVIEW_REQUIRED");
    const version=epoch,ctx=context;
    if (!publish({...state,phase:"READING_OUTCOME",code:"",reviewKey:"",view:null},version)) return snapshot();
    try {
      await client.connect();same(version,ctx);
      return await observe(version,ctx);
    } catch(error) {return fail(error,version,ctx,"OUTCOME_UNCERTAIN");}
  }

  function tick() {
    if (state.phase!=="READY" || !context) return snapshot();
    try {
      same(epoch,context,true);
      const view=model(context);
      if (!view.reviewable) publish({...state,phase:"BLOCKED",code:view.status,reviewKey:"",view},epoch);
    } catch(error) {fail(error,epoch,context,"BLOCKED");}
    return snapshot();
  }
  return Object.freeze({
    prepare,listPreparations,reopenPreparation,readPreparation:()=>inspectPreparation(false),closePreparation:()=>inspectPreparation(true),confirm:(key,acknowledged)=>act("CONFIRM",key,acknowledged),
    reject:key=>act("REJECT",key,false),readOutcome,tick,snapshot,
    disconnect() {
      epoch++;client.disconnect();context=null;lastTime=0;
      publish({phase:"IDLE",code:"",decisionId:"",previewId:"",reviewKey:"",view:null},epoch);
      return snapshot();
    },
  });
}
