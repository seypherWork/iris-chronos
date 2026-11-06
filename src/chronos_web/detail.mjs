import {unixMicrosecondsUTC} from "./presentation.mjs";

// Historical display only. The native server authenticates and validates hashes;
// this consumer checks the public schema/identity and never authorizes an effect.
const object = x => x !== null && typeof x === "object" && !Array.isArray(x);
function need(ok) { if (!ok) throw new Error("INVALID_DETAIL"); }
const num = x => { need(Number.isSafeInteger(x) && x >= 0); return x; };
const positive = x => { num(x); need(x > 0); return x; };
const txt = (max, pattern = null, empty = false) => x => {
  need(typeof x === "string" && [...x].length <= max && (empty || x.length > 0));
  if (pattern) need(pattern.test(x));
  return x;
};
const id = txt(128, /^[A-Za-z0-9_.:-]+$/);
const hash = txt(64, /^[a-f0-9]{64}$/);
const code = txt(128, /^[A-Z0-9_]*$/, true);
const choice = (...allowed) => x => { need(allowed.includes(x)); return x; };
const nullable = check => x => x === null ? null : check(x);
const bool = x => { need(typeof x === "boolean"); return x; };
const fields = schema => x => {
  need(object(x) && Object.keys(x).length === Object.keys(schema).length);
  return Object.fromEntries(Object.entries(schema).map(([key, check]) => {
    need(Object.hasOwn(x, key)); return [key, check(x[key])];
  }));
};
const list = (check, max) => x => { need(Array.isArray(x) && x.length <= max); return x.map(check); };
const forbiddenKey = /^(?:password|passwd|api[_ -]?key|client[_ -]?secret|access[_ -]?token|authorization|private[_ -]?key)$/i;
const secretText = /(?:password|passwd|api[_ -]?key|client[_ -]?secret|access[_ -]?token)\s*[:=]\s*\S+|authorization\s*:\s*(?:bearer|basic)\s+\S+|-----BEGIN [^-]*PRIVATE KEY-----/i;
function businessPayload(raw) {
  let nodes = 0;
  function visit(x, depth = 0) {
    need(depth <= 12 && ++nodes <= 65536);
    if (x === null || typeof x === "boolean") return x;
    if (typeof x === "number") { need(Number.isFinite(x)); return x; }
    if (typeof x === "string") return txt(65536, null, true)(x);
    if (Array.isArray(x)) { need(x.length <= 128); return x.map(v => visit(v, depth + 1)); }
    need(object(x) && Object.keys(x).length <= 128);
    return Object.fromEntries(Object.entries(x).map(([k,v]) => {
      txt(128)(k); need(!forbiddenKey.test(k)); return [k, visit(v, depth + 1)];
    }));
  }
  need(object(raw)); positive(raw.quantity);
  return visit(raw);
}
const offer = fields({cost:num, available_at:num, queue_duration:num, travel_duration:num});
const message = fields({message_id:id,source_id:id,at:num,
  order_link:choice("VERIFIED_CURRENT","VERIFIED_OTHER","UNRESOLVED"),text:txt(2000)});
const change = fields({event_id:id,at:num,kind:choice("DELAY_QUEUE"),target:choice("A","B","*"),value:num,observed_at:num});
const facts = fields({payload:businessPayload,budget:num,deadline:num,inventory_expires:num,offer_until:num,
  preference_mode:choice("STRUCTURED","CONTEXT_REQUIRED"),
  structured_preference:nullable(choice("CHEAPEST_ON_TIME","EARLIEST_ALLOWED")),
  messages:list(message,8),known_changes:list(change,64),options:fields({A:offer,B:offer})});
const receipt = fields({source_id:id,operationId:id,attemptId:id,target:choice("A","B"),
  status:choice("ACCEPTED","UNKNOWN","NOT_ACCEPTED_FINAL"),closedForever:bool});
const trace = x => { need(Array.isArray(x) && x.length === 2); return [num(x[0]),txt(256)(x[1])]; };
const trial = fields({trial_id:id,option_id:choice("opt-a","opt-b"),observations:fields({
  action:choice("RETRY_A","FAILOVER_B"),state:choice("QUEUED","BLOCKED","NOT_ACCEPTED_FINAL","ACCEPTED","DELIVERED_SIMULATED"),
  reason:code,accepted_at:nullable(num),arrival:nullable(num),cost:num,trace:list(trace,30)})});
const wire = fields({schema_version:choice("chronos.agent-input.v2"),context_id:id,context_digest:hash,
  order_id:id,shipment_version:positive,state_revision:positive,policy_revision:positive,
  observation_id:id,facts_id:hash,clock_kind:choice("relative_microseconds"),ticks_per_minute:positive,
  utc_origin_us:num,observed_at:num,valid_until:num,trial_horizon:positive,facts,evidence:list(receipt,64),
  source_catalog:list(fields({id,kind:choice("fact","message","known_change","evidence","trial")}),128),
  trial_mode:choice("WITH_TRIALS","WITHOUT_TRIALS_ABLATION"),trial_status:choice("COMPLETE","NOT_REQUESTED"),trials:list(trial,2)});
const proposal = fields({schema_version:choice("chronos.agent-proposal.v2"),context_id:id,context_digest:hash,
  order_id:id,shipment_version:positive,state_revision:positive,action:choice("RETRY_A","FAILOVER_B","HOLD"),
  option_id:nullable(choice("opt-a","opt-b")),
  interpreted_preference:choice("CHEAPEST_ON_TIME","EARLIEST_ALLOWED","UNRESOLVED","NOT_USED"),
  source_ids:list(id,16),reason_code:code,rationale:txt(600),clarification:nullable(txt(240))});
const detailFields = {code:choice("DECISION_DETAIL_RECORDED"),schema:choice("chronos.review-detail.v1"),
  dispatchGranted:choice(false),canConfirm:choice(false),currentAuthorityVerified:choice(false),historical:choice(true),
  decisionId:id,decisionDigest:hash,generation:id,completedUS:num,reviewDeadlineUS:num,
  outcome:fields({status:choice("VALIDATED_PROPOSAL","VALIDATED_HOLD"),code:code}),proposal,context:wire,payloadJSON:txt(131072)};
const attributionSchema = fields({responseContract:choice("chronos.preference-extraction.v1","chronos.agent-proposal.v2"),
  interpretationOrigin:choice("MODEL","NOT_RECORDED"),selectionOrigin:choice("DETERMINISTIC_CODE","NOT_RECORDED")});
const legacyDetail = fields(detailFields);
const currentDetail = fields({...detailFields,schema:choice("chronos.review-detail.v2"),attribution:attributionSchema});
const nativeTraceSchema = fields({aiHubSessionId:txt(18,/^[0-9]{1,18}$/),
  interopSessionId:txt(18,/^[0-9]{1,18}$/),namespace:nullable(txt(64,/^[A-Za-z%][A-Za-z0-9_%-]{0,63}$/)),
  sessionSnapshot:choice("BEFORE_CHAT")});
const tracedDetail = fields({...detailFields,schema:choice("chronos.review-detail.v3"),attribution:attributionSchema,nativeTrace:nativeTraceSchema});
function detailSchema(raw) {
  if (raw?.schema === "chronos.review-detail.v1") return legacyDetail(raw);
  const d=raw?.schema === "chronos.review-detail.v3" ? tracedDetail(raw) : currentDetail(raw),a=d.attribution;
  if(a.responseContract==="chronos.preference-extraction.v1")need(a.interpretationOrigin==="MODEL"&&a.selectionOrigin==="DETERMINISTIC_CODE");
  else need(a.interpretationOrigin==="NOT_RECORDED"&&a.selectionOrigin==="NOT_RECORDED");
  return d;
}
const LABELS = Object.freeze({LIVE:"Live server data — synthetic laboratory",
  REPLAY:"Replay — recorded data, not current server state",LOCAL_FIXTURE:"Local fixture — no IRIS execution",
  UNVERIFIED:"Source not verified"});
const HOLD = {CONTEXT_AMBIGUOUS:["UNRESOLVED"],CONFLICTING_EVIDENCE:["UNRESOLVED","NOT_USED"],
  CONTEXT_INCOMPLETE:["NOT_USED"],NO_FEASIBLE_OPTION:["NOT_USED"]};
const row = (label,value) => Object.freeze({label,value:String(value)});
function freeze(x) { if (object(x) || Array.isArray(x)) { for (const value of Object.values(x)) freeze(value); Object.freeze(x); } return x; }
function card(evidence, available, rows = [], sections = [], hold = false) {
  const source = Object.hasOwn(LABELS,evidence) ? evidence : "UNVERIFIED";
  return freeze({kind:"detail",available,canConfirm:false,evidence:source,evidenceLabel:LABELS[source],
    tone:available ? (hold ? "warning" : "notice") : "error",
    title:available ? (hold ? "Historical HOLD decision" : "Historical recovery proposal") : "Decision detail unavailable",
    summary:available ? "Recorded evidence, not current authorization. A fresh server preview and explicit human consent are still required. Branch trials are simulations, not deliveries." :
      "The detail is missing, inconsistent or belongs to another decision. No change was submitted; keep the original reference.",
    rows,sections,operation:null});
}
function section(title,note,rows = [],table = null) { return {title,note,rows,table}; }
function byteLength(x) { return new TextEncoder().encode(JSON.stringify(x)).length; }
function containsSensitive(x) {
  if (typeof x === "string") return secretText.test(x);
  if (Array.isArray(x)) return x.some(containsSensitive);
  if (object(x)) return Object.entries(x).some(([k,v])=>containsSensitive(k)||containsSensitive(v));
  return false;
}
function stable(x) {
  if (Array.isArray(x)) return "["+x.map(stable).join(",")+"]";
  if (object(x)) return "{"+Object.keys(x).sort().map(k=>JSON.stringify(k)+":"+stable(x[k])).join(",")+"}";
  return JSON.stringify(x);
}


export function decisionDetailView(envelope,{expectedId,expectedGeneration,expectedOutcome,expectedOrder,expectedShipmentVersion,evidence="UNVERIFIED"} = {}) {
  try {
    need(typeof expectedId === "string" && /^[A-Za-z0-9_.-]{1,128}$/.test(expectedId));
    need(object(envelope) && envelope.code === "DECISION_DETAIL_RECORDED");
    const d=detailSchema(envelope.data),w=d.context,p=d.proposal,f=w.facts;
    need(d.decisionId === expectedId && w.context_id === expectedId);
    if (expectedGeneration !== undefined) need(d.generation === expectedGeneration);
    if (expectedOutcome !== undefined) need(d.outcome.status === expectedOutcome);
    if (expectedOrder !== undefined) need(w.order_id === expectedOrder);
    if (expectedShipmentVersion !== undefined) need(w.shipment_version === expectedShipmentVersion);
    for (const key of ["context_id","context_digest","order_id","shipment_version","state_revision"]) need(p[key] === w[key]);
    need(d.completedUS < d.reviewDeadlineUS && w.observed_at < w.valid_until);
    need(w.ticks_per_minute === 60000000 && w.trial_horizon === 1800000000);
    // Server's canonical byte limits are not recomputed with a different JSON
    // serializer. The client already bounds the full transport to512KiB.
    need(byteLength(d) <= 524288 && !containsSensitive(d));
    // Use the trusted server serialization for exact numeric spelling. Parsing
    // below is a consistency check only; it never rewrites the displayed payload.
    const serializedPayload = businessPayload(JSON.parse(d.payloadJSON));
    need(stable(serializedPayload) === stable(f.payload));
    const expected=new Map([["fact:order","fact"],["fact:policy","fact"],["option:A","fact"],["option:B","fact"]]);
    const add=(key,kind) => { need(!expected.has(key)); expected.set(key,kind); };
    for (const m of f.messages) { need(m.at <= w.observed_at); add(m.message_id,"message"); }
    for (const c of f.known_changes) { need(c.observed_at <= w.observed_at && w.observed_at <= c.at); add(c.event_id,"known_change"); }
    for (const e of w.evidence) add(e.source_id,"evidence");
    if (w.trial_mode === "WITH_TRIALS") {
      need(w.trial_status === "COMPLETE" && w.trials.length === 2);
      const seen=new Set();
      for (const t of w.trials) {
        need(t.option_id === (t.observations.action === "RETRY_A" ? "opt-a" : "opt-b"));
        need(t.trial_id === "trial:"+t.option_id && !seen.has(t.option_id)); seen.add(t.option_id); add(t.trial_id,"trial");
      }
    } else need(w.trial_status === "NOT_REQUESTED" && w.trials.length === 0);
    need(w.source_catalog.length === expected.size && new Set(w.source_catalog.map(x=>x.id)).size === expected.size);
    for (const item of w.source_catalog) need(expected.get(item.id) === item.kind);
    need(p.source_ids.length > 0 && new Set(p.source_ids).size === p.source_ids.length);
    for (const source of p.source_ids) need(expected.has(source));
    need(p.rationale.trim().length > 0);
    need((f.preference_mode === "CONTEXT_REQUIRED") === (f.structured_preference === null));
    const hold=p.action === "HOLD";
    need(hold === (d.outcome.status === "VALIDATED_HOLD"));
    if (hold) {
      need(p.option_id === null && Object.hasOwn(HOLD,p.reason_code) && HOLD[p.reason_code].includes(p.interpreted_preference));
    } else {
      need(p.option_id === (p.action === "RETRY_A" ? "opt-a" : "opt-b") && p.reason_code === "PREFERENCE_MATCH");
      need(["CHEAPEST_ON_TIME","EARLIEST_ALLOWED"].includes(p.interpreted_preference));
      if (f.preference_mode === "STRUCTURED") need(p.interpreted_preference === f.structured_preference);
      else need(f.messages.some(m=>m.order_link === "VERIFIED_CURRENT" && p.source_ids.includes(m.message_id)));
    }
    if (p.clarification !== null) need(p.clarification.trim() && hold && ["CONTEXT_AMBIGUOUS","CONTEXT_INCOMPLETE"].includes(p.reason_code));
    const absolute = value => { const sum=w.utc_origin_us+num(value); need(Number.isSafeInteger(sum)); const t=unixMicrosecondsUTC(sum); need(t !== null); return t; };
    const seconds = value => String(num(value)/1000000)+" s";
    const utc = value => { const t=unixMicrosecondsUTC(value); need(t !== null); return t; };
    const e1=d.attribution?.responseContract==="chronos.preference-extraction.v1";
    const attributionSection=e1 ? section("How this proposal was produced",
      "The model interpreted the preference and cited evidence. Code selected among the checked options and assembled the proposal. HOLD fields can be supplied or normalized by code; this is not a verbatim model transcript.",[
        row("Response contract",d.attribution.responseContract),
        row("Preference interpretation","Model — compare with the original messages and policy below"),
        row("Option selection","Deterministic code — applies the interpreted preference to the checked options"),
        row("Identity and constraints","Code binds the original context and validates the proposal; a fresh server check is still required"),
      ]) : section("How this proposal was produced",
      "This older record does not contain explicit model/code attribution. No split is inferred from the final proposal schema or the current installation.",[
        row("Attribution","Not recorded"),
        row("Response contract",d.attribution?.responseContract ?? "Not recorded in this detail version"),
      ]);
    const t=d.nativeTrace;
    const traceSection=t ? section("Original IRIS execution",
      "Original IDs bound before the model call, not the session of this page request. The AI Hub snapshot was saved BEFORE Chat; it is not a completion transcript. Message availability and portal access are checked by IRIS separately.",[
        row("IRIS namespace",t.namespace ?? "Not supplied by this evidence source"),
        row("Interoperability session",t.interopSessionId),row("AI Hub session",t.aiHubSessionId),
        row("Find the original messages","In the IRIS Management Portal, select this namespace and open Interoperability > Message Viewer. Filter by the interoperability session ID, then open its Visual Trace. Portal permissions may differ from Chronos read access."),
      ]) : section("Original IRIS execution",
      "No native session binding was recorded in this detail version. IDs are not inferred from a later read or from simulated branch events.",[row("Native trace","Not recorded")]);
    const sections=[
      attributionSection,traceSection,
      section("Recorded proposal","Review the interpreted preference against the original evidence. Schema and citation checks do not prove that the interpretation is correct.",[
        row("Action",p.action),row("Option",p.option_id ?? "None — HOLD"),row("Interpreted preference",p.interpreted_preference),
        row("Reason",p.reason_code),row("Rationale",p.rationale),row("Clarification",p.clarification ?? "None requested"),
        row("Cited sources",p.source_ids.join("\n"))]),
      section("Effect payload","Exact server-serialized historical JSON, preserving numeric spelling. A fresh preview must verify the actual effect before consent.",[
        row("Payload (JSON)",d.payloadJSON)]),
      section("Constraints at observation","Times are UTC; costs use the laboratory's cost units, not a real currency.",[
        row("Budget",f.budget),row("Delivery deadline",absolute(f.deadline)),row("Inventory expires",absolute(f.inventory_expires)),
        row("Offers valid until",absolute(f.offer_until)),row("Preference mode",f.preference_mode),
        row("Structured preference",f.structured_preference ?? "Not supplied — contextual interpretation")]),
      section("Recorded alternatives","These offers were observed earlier. This view does not rerank them or certify current feasibility.",[],{
        headers:["Target","Action","Cost units","Available (UTC)","Queue duration","Travel duration"],
        rows:["A","B"].map(target=>{const o=f.options[target];return [target,target==="A"?"RETRY_A":"FAILOVER_B",String(o.cost),absolute(o.available_at),seconds(o.queue_duration),seconds(o.travel_duration)];})}),
      section("Observed messages","Other-order and unresolved messages are explicitly labeled; they are not evidence of a current-order instruction.",
        f.messages.length ? f.messages.flatMap(m=>[row(m.message_id+" / "+m.order_link,"Source: "+m.source_id+" | "+absolute(m.at)),row("Message text",m.text)]) : [row("Messages","None recorded")]),
      section("Known future changes","Only changes known at the recorded observation are shown.",
        f.known_changes.length ? f.known_changes.map(c=>row(c.event_id,c.kind+" | "+c.target+" | value "+seconds(c.value)+" | effective "+absolute(c.at)+" | observed "+absolute(c.observed_at))) : [row("Changes","None recorded")]),
      section("Destination evidence","Acceptance is not delivery. UNKNOWN does not permit sending again.",
        w.evidence.length ? w.evidence.map(e=>row(e.source_id,e.status+" | target "+e.target+" | operation "+e.operationId+" | attempt "+e.attemptId+" | closed forever: "+(e.closedForever?"Yes":"No"))) : [row("Evidence","None recorded")]),
    ];
    for (const t of w.trials) {
      const o=t.observations;
      sections.push(section("Counterfactual trial: "+t.option_id,"Simulated branch from the recorded context. No real shipment was sent by this trial.",[
        row("Source",t.trial_id),row("Action",o.action),row("Simulated state",o.state),row("Reason",o.reason || "Not recorded"),
        row("Cost units",o.cost),row("Simulated acceptance (UTC)",o.accepted_at === null ? "Not recorded" : absolute(o.accepted_at)),
        row("Simulated arrival (UTC)",o.arrival === null ? "Not recorded" : absolute(o.arrival)),
        ...o.trace.map(([at,event])=>row("Simulated event at "+absolute(at),event))]));
    }
    if (!w.trials.length) sections.push(section("Counterfactual trials","Trials were not requested for this recorded ablation. No trial result is invented.",[row("Mode",w.trial_mode)]));
    sections.push(section("Source catalog","IDs identify evidence inside this record; they are not external links.",
      w.source_catalog.map(s=>row(s.id,s.kind+(p.source_ids.includes(s.id)?" — cited by proposal":"")))));
    return card(evidence,true,[
      row("Decision",d.decisionId),row("Order",w.order_id),row("Shipment version",w.shipment_version),
      row("State revision",w.state_revision),row("Policy revision",w.policy_revision),row("Observation",w.observation_id),
      row("Observed (UTC)",absolute(w.observed_at)),row("Context valid until (UTC)",absolute(w.valid_until)),
      row("Decision completed (UTC)",utc(d.completedUS)),row("Original review deadline (UTC)",utc(d.reviewDeadlineUS)),
      row("Runtime generation",d.generation),row("Trial mode",w.trial_mode),
      row("Decision digest",d.decisionDigest),row("Context digest",w.context_digest),row("Facts digest",w.facts_id)],sections,hold);
  } catch { return card(evidence,false); }
}

// Used only with frozen sections produced by decisionDetailView/controller.
export function appendDetailSections(document,parent,sections = []) {
  const make=(tag,text,owner)=>{const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(owner)owner.appendChild(e);return e;};
  const proposal = sections.find(x => x.title === "Recorded proposal");
  const proposedAction = proposal?.rows.find(x => x.label === "Action")?.value;
  // Consent must show the fresh exact effect before older offers, whose cost
  // and revision may legitimately differ. Historical browsing is not consent.
  const consent = sections.some(x => x.title === "Fresh server preview");
  const titles = consent
    ? ["Fresh server preview", "Before confirming", "Recorded alternatives", "Recorded proposal", "Constraints at observation", "Observed messages"]
    : ["Recorded alternatives", "Recorded proposal", "Constraints at observation", "Observed messages"];
  const priority = new Map(titles.map((name,i)=>[name,i]));
  const ordered = [...sections].sort((a,b)=>(priority.get(a.title)??20)-(priority.get(b.title)??20));
  let history;
  for (const model of ordered) {
    let owner=parent;
    if(consent && !["Fresh server preview","Before confirming"].includes(model.title)) {
      if(!history) {
        history=make("details",undefined,parent);history.className="chronos-fold";
        make("summary","Recorded decision and supporting evidence",history);
      }
      owner=history;
    }
    const folded = model.title === "Source catalog" || model.title === "Known future changes" || model.title.startsWith("Counterfactual trial");
    const s=make(folded ? "details" : "section",undefined,owner);s.className="chronos-detail-section"+(folded ? " chronos-fold" : "");
    const headingParent = folded ? make("summary",undefined,s) : s;
    make("h3",model.title,headingParent);make("p",model.note,s);
    if(model.title === "Recorded alternatives" && model.table) {
      const options = make("div",undefined,s); options.className="chronos-options";
      for(const cells of model.table.rows) {
        const selected=cells[1]===proposedAction;
        const option=make("section",undefined,options); option.className="chronos-option"+(selected?" chronos-option--proposed":"");
        make("h4","Option "+cells[0],option);
        if(selected)make("span","Recorded proposal",option).className="chronos-option-badge";
        const list=make("dl",undefined,option);
        for(const [label,value] of [["Cost units",cells[2]],["Queue duration",cells[4]],["Travel duration",cells[5]]]) {
          make("dt",label,list);const valueNode=make("dd",value,list);if(label==="Cost units")valueNode.className="chronos-cost";
        }
        make("small","Historical offer · current eligibility requires a fresh preview",option);
      }
    }
    if(model.rows.length){const dl=make("dl",undefined,s);for(const item of model.rows){make("dt",item.label,dl);make("dd",item.value,dl);}}
    if(model.table){
      const tableOwner=model.title==="Recorded alternatives"?make("details",undefined,s):s;
      if(tableOwner!==s){tableOwner.className="chronos-fold";make("summary","Complete recorded offer table (UTC)",tableOwner);}
      const wrap=make("div",undefined,tableOwner);wrap.className="chronos-table-scroll";wrap.tabIndex=0;
      wrap.setAttribute("aria-label",model.title+" table");
      const table=make("table",undefined,wrap);make("caption",model.title,table);
      const head=make("tr",undefined,make("thead",undefined,table));
      for(const label of model.table.headers){const th=make("th",label,head);th.scope="col";}
      const body=make("tbody",undefined,table);
      for(const cells of model.table.rows){const tr=make("tr",undefined,body);for(const cell of cells)make("td",cell,tr);}
    }
  }
}

// Keep approval/operation rows expanded. Only historical record identifiers are
// progressively disclosed, with decision/order/version still visible above them.
export function appendResultRows(document, parent, model) {
  const make=(tag,text,owner)=>{const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(owner)owner.appendChild(e);return e;};
  const rows=model.rows ?? [];
  const draw=(items,owner)=>{if(!items.length)return;const list=make("dl",undefined,owner);for(const item of items){make("dt",item.label,list);make("dd",item.value,list);}};
  if(model.kind === "consent" && model.available) {
    const fresh=model.sections?.find(x=>x.title==="Fresh server preview");
    if(fresh){
      const value=label=>fresh.rows.find(x=>x.label===label)?.value;
      const summary=make("section",undefined,parent);summary.className="chronos-exact-summary";
      make("h3","Current recovery · destination "+value("Destination"),summary);
      const cards=make("div",undefined,summary);cards.className="chronos-options";
      for(const [label,amount,secondary] of [
        ["Cost to authorize",value("Cost units")+" cost units","Budget: "+value("Maximum cost units")+" cost units"],
        ["Predicted arrival (UTC)",value("Predicted arrival (UTC, not guaranteed)"),"Deadline: "+value("Delivery deadline (UTC)")],
      ]){
        const tile=make("div",undefined,cards);tile.className="chronos-current-value";
        make("p",label,tile);make("strong",amount,tile);make("small",secondary,tile);
      }
      make("p","Fresh preview values. Arrival is a prediction, not delivery. Review the complete bound effect below.",summary).className="hint";
    }
  }
  if(model.kind !== "detail"){draw(rows,parent);return;}
  const prominent=new Set(["Decision","Order","Shipment version"]);
  draw(rows.filter(x=>prominent.has(x.label)),parent);
  const rest=rows.filter(x=>!prominent.has(x.label));
  if(rest.length){const fold=make("details",undefined,parent);fold.className="chronos-fold";make("summary","Record identity and timestamps",fold);draw(rest,fold);}
}
