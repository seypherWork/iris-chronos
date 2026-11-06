import {ChronosClientError} from "./client.mjs";

const ID = /^[A-Za-z0-9_.-]{1,128}$/;
const DIGEST = /^[a-f0-9]{64}$/;
const BUSY = new Set(["CONNECTING", "OPENING", "READING", "SENDING"]);
const PENDING = new Set(["RECORDED", "PROCESSING", "UNCERTAIN"]);
const SAFE = new Set(["SESSION_REQUIRED", "PERMISSION_DENIED", "INVALID_SESSION", "CONVERSATION_UNAVAILABLE",
  "REFERENCE_SCOPE_CHANGED", "CONNECTION_CHANGED", "REQUEST_TIMEOUT", "TRANSPORT_UNAVAILABLE",
  "INVALID_CONVERSATION_RESPONSE", "INVALID_REQUEST", "PRESENTATION_FAILED"]);
const copy = value => value === null ? null : JSON.parse(JSON.stringify(value));
const canonical = value => JSON.stringify(value, (_key, item) => item && typeof item==="object" && !Array.isArray(item) ?
  Object.fromEntries(Object.keys(item).sort().map(key=>[key,item[key]])) : item);
const failure = code => new ChronosClientError(code);
const publicCode = error => error instanceof ChronosClientError && SAFE.has(error.code) ? error.code : "CONVERSATION_UNAVAILABLE";

/** Explicit conversation gestures only. No timer, approval, retry or dispatch.
 * The installation-owned client validates every server envelope. This controller
 * keeps references and identity across lost replies and ignores late UI results.
 */
export function createConversationController({client, newId=()=>globalThis.crypto.randomUUID(), onChange=()=>{}}={}) {
  for (const method of ["connect", "disconnect", "sessionIdentity", "sessionStatus", "conversationAvailable",
    "openConversation", "readConversation", "recordConversation"]) {
    if (typeof client?.[method] !== "function") throw new TypeError("INVALID_CONVERSATION_CLIENT");
  }
  if (typeof newId !== "function" || typeof onChange !== "function") throw new TypeError("INVALID_CONVERSATION_CONTROLLER");
  let epoch=0, context=null, destroyed=false, renderBlocked=false;
  let state={phase:"IDLE", code:"", view:null};
  function identity() {
    const access=client.sessionStatus(), actor=client.sessionIdentity();
    if (!access.connected || !access.canRead) throw failure("SESSION_REQUIRED");
    if (!client.conversationAvailable()) throw failure("CONVERSATION_UNAVAILABLE");
    if (!actor.available || !/^principal-[a-f0-9]{64}$/.test(actor.actor) || !DIGEST.test(actor.actorScope) ||
        typeof actor.applicationUrl !== "string" || !actor.applicationUrl) throw failure("INVALID_SESSION");
    return JSON.stringify([actor.actor, actor.actorScope, actor.applicationUrl]);
  }
  function same(version, ctx) {
    if (destroyed || version !== epoch || context !== ctx) throw failure("CONNECTION_CHANGED");
    if (identity() !== ctx.identity) throw failure("REFERENCE_SCOPE_CHANGED");
  }
  function snapshot() {
    let connected=false;
    try {connected=Boolean(context && identity()===context.identity);} catch {}
    return Object.freeze({...state,view:connected?copy(state.view):null,decisionId:connected?context.decisionId:"",
      conversationId:connected?context.conversationId:"",turnId:connected?context.turnId:"",
      canOpen:!destroyed && !context && !BUSY.has(state.phase),
      canRead:!destroyed && Boolean(context) && !BUSY.has(state.phase),
      canSend:!destroyed && !renderBlocked && connected && state.phase==="READY" &&
        Boolean(context?.packet) && context.packet.conversation.turns.length<6,
      canClose:!destroyed && Boolean(context) && !BUSY.has(state.phase) && !context.unresolved});
  }
  function publish(phase,code="",view=null,version=epoch) {
    if (destroyed || version!==epoch) return false;
    state={phase,code,view};
    try {
      const rendered=onChange(snapshot());
      if (rendered && typeof rendered.then==="function") {
        Promise.resolve(rendered).catch(()=>{});throw failure("PRESENTATION_FAILED");
      }
      return !destroyed && version===epoch;
    } catch {
      if (destroyed || version!==epoch) return false;
      renderBlocked=true;state={phase:"ERROR",code:"PRESENTATION_FAILED",view:null};return false;
    }
  }
  function accept(packet,version,ctx) {
    same(version,ctx);
    if (!packet || packet.conversation?.conversation_id!==ctx.conversationId ||
        packet.context?.decision_id!==ctx.decisionId || !DIGEST.test(packet.context_digest) ||
        !Array.isArray(packet.conversation.turns) || packet.conversation.turns.length>6 ||
        packet.conversation.revision!==packet.conversation.turns.length+1 ||
        packet.dispatch_authorized!==false || packet.inference_granted!==false ||
        packet.conversation.dispatch_authorized!==false || packet.conversation.confirmation_granted!==false) {
      throw failure("INVALID_CONVERSATION_RESPONSE");
    }
    if (ctx.packet) {
      const old=ctx.packet.conversation, next=packet.conversation;
      if (next.case_id!==old.case_id || next.shipment_version!==old.shipment_version || next.revision<old.revision ||
          old.turns.some((turn,index)=>next.turns[index]?.turn_id!==turn.turn_id || next.turns[index]?.user_text!==turn.user_text ||
            turn.state==="COMPLETED" && canonical(next.turns[index])!==canonical(turn))) {
        throw failure("INVALID_CONVERSATION_RESPONSE");
      }
    }
    // An empty read does not prove a timed-out RECORD cannot arrive later.
    const unseen=Boolean(ctx.pendingTurnId && !packet.conversation.turns.some(t=>t.turn_id===ctx.pendingTurnId));
    if (!unseen) ctx.pendingTurnId="";
    ctx.packet=copy(packet);ctx.unresolved=unseen || packet.conversation.turns.some(t=>PENDING.has(t.state));
    ctx.turnId=ctx.pendingTurnId || packet.conversation.turns.at(-1)?.turn_id || "";
    renderBlocked=false;
    publish(unseen?"UNCERTAIN":ctx.unresolved?"PENDING":"READY","",packet,version);
  }
  function failed(error,version,ctx) {
    if (destroyed || version!==epoch) return;
    const code=publicCode(error);
    // Only this client's exact pre-dispatch rejection proves RECORD never left.
    // Generic errors, lost replies and foreign identifiers retain uncertainty.
    if (ctx && ctx===context && error instanceof ChronosClientError &&
        error.command==="CONVERSATION_RECORD" && error.id===ctx.conversationId &&
        error.decisionId===ctx.decisionId && ctx.pendingTurnId && error.turnId===ctx.pendingTurnId &&
        error.mayHaveApplied===false &&
        ["REQUEST_IN_PROGRESS","SESSION_REQUIRED","CONVERSATION_UNAVAILABLE","INVALID_REQUEST"].includes(error.code)) {
      ctx.pendingTurnId="";ctx.turnId=ctx.packet?.conversation.turns.at(-1)?.turn_id??"";
      ctx.unresolved=Boolean(ctx.packet?.conversation.turns.some(t=>PENDING.has(t.state)));
    }
    if (code==="REFERENCE_SCOPE_CHANGED") {
      // Never expose the former account's case IDs or transcript to a new actor.
      context=null;publish("BLOCKED",code,null,version);return;
    }
    publish(ctx?.unresolved?"UNCERTAIN":"ERROR",code,null,version);
  }
  async function open(decisionId) {
    if (!snapshot().canOpen) return false;
    if (typeof decisionId!=="string" || !ID.test(decisionId)) {publish("ERROR","INVALID_REQUEST");return false;}
    const version=++epoch;let ctx=null;
    if (!publish("CONNECTING","",null,version)) return false;
    try {
      await client.connect();if (destroyed || version!==epoch) return false;
      const key=identity(),conversationId=newId();
      if (typeof conversationId!=="string" || !ID.test(conversationId)) throw failure("INVALID_REQUEST");
      ctx={decisionId,conversationId,identity:key,packet:null,turnId:"",pendingTurnId:"",unresolved:false};context=ctx;
      if (!publish("OPENING","",null,version)) return false;
      same(version,ctx);
      ctx.unresolved=true;
      const value=await client.openConversation(conversationId,decisionId);
      accept(value,version,ctx);return true;
    } catch (error) {failed(error,version,ctx);return false;}
  }
  async function read() {
    if (!snapshot().canRead) return false;
    const ctx=context,version=++epoch;
    if (!publish("CONNECTING","",null,version)) return false;
    try {
      await client.connect();same(version,ctx);
      if (!publish("READING","",null,version)) return false;
      same(version,ctx);
      const value=await client.readConversation(ctx.conversationId,ctx.decisionId);
      accept(value,version,ctx);return true;
    } catch (error) {failed(error,version,ctx);return false;}
  }
  async function send(text) {
    if (!snapshot().canSend) return false;
    if (typeof text!=="string" || !text.trim() || new TextEncoder().encode(text).length>2048 ||
        /[\u0000-\u0008\u000b-\u001f]/.test(text) ||
        [...text].some(ch=>ch.codePointAt(0)>=0xd800 && ch.codePointAt(0)<=0xdfff)) {
      return false;
    }
    const ctx=context,version=++epoch;
    try {
      same(version,ctx);const turnId=newId();
      if (typeof turnId!=="string" || !ID.test(turnId) || ctx.packet.conversation.turns.some(t=>t.turn_id===turnId)) throw failure("INVALID_REQUEST");
      const fields=Object.freeze({turnId,expectedRevision:ctx.packet.conversation.revision,
        expectedContextDigest:ctx.packet.context_digest,text});
      if (!publish("SENDING","",ctx.packet,version)) return false;
      same(version,ctx);
      ctx.turnId=turnId;ctx.pendingTurnId=turnId;ctx.unresolved=true;
      const value=await client.recordConversation(ctx.conversationId,ctx.decisionId,fields);
      accept(value,version,ctx);return true;
    } catch (error) {failed(error,version,ctx);return false;}
  }
  function deactivate() {
    if (destroyed) return;
    epoch++;client.disconnect();
    publish(context?.unresolved?"UNCERTAIN":"HIDDEN","CONNECTION_CHANGED");
  }
  function close() {
    if (!snapshot().canClose) return false;
    epoch++;context=null;renderBlocked=false;publish("IDLE");return true;
  }
  return Object.freeze({snapshot,open,read,send,close,deactivate,
    destroy() {if (destroyed) return;destroyed=true;epoch++;context=null;state={phase:"IDLE",code:"",view:null};client.disconnect();}});
}
