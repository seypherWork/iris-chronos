import {decisionDetailView} from "./detail.mjs";
import {previewView, irisSecondsUTC} from "./presentation.mjs";

// Display/consistency checks only. No API client, storage, grant or execution.
// A separate controller must revalidate this model at confirmation and preserve
// the original preview ID for uncertain-result recovery.
const OFFSET = 4070908800;
const ID = /^[A-Za-z0-9_.-]{1,128}$/;
function need(ok) { if (!ok) throw new Error("CONSENT_DATA_MISMATCH"); }
const integer = x => Number.isSafeInteger(x) && x >= 0;
const object = x => x !== null && typeof x === "object" && !Array.isArray(x);
const exact = (x,keys) => object(x) && Object.keys(x).sort().join(",") === [...keys].sort().join(",");
const freeze = x => { if(object(x)||Array.isArray(x)){for(const v of Object.values(x))freeze(v);Object.freeze(x);}return x; };
const row = (label,value) => ({label,value:String(value)});
const copy = x => JSON.parse(JSON.stringify(x));
function stable(x) {
  if (Array.isArray(x)) return "["+x.map(stable).join(",")+"]";
  if (object(x)) return "{"+Object.keys(x).sort().map(k=>JSON.stringify(k)+":"+stable(x[k])).join(",")+"}";
  return JSON.stringify(x);
}
const PREVIEW_FIELDS = ["dispatchGranted","code","previewId","orderId","shipmentVersion","snapshotId",
  "decisionId","decisionDigest","option","target","actor","generation","operationId","createdAt",
  "expiresAt","reviewDeadlineUS","state","snapshot","predictedArrival"];
const SNAPSHOT_FIELDS = ["orderId","shipmentVersion","revision","policyRevision","quantity","payload",
  "maxCost","observedAt","inventoryUntil","deliveryDeadline","offers"];
const OFFER_FIELDS = ["target","cost","availableAt","queueSeconds","travelSeconds","validUntil","capacity"];
const CODES = {
  REVIEWABLE: "Review the exact effect below. This is not yet consent or a server authorization.",
  EXPIRED: "The preview or original review window has expired. It cannot be confirmed from this view.",
  CLOCK_UNVERIFIED: "The browser clock is inconsistent with the preview. Confirm nothing until the clock and server state are checked.",
  NOT_LIVE: "This is recorded or test material. It cannot enable a live confirmation.",
  NOT_ACTIONABLE: "A HOLD, ablation, rejected or already confirmed result cannot become a new consent.",
  UNAVAILABLE: "The proposal, identity or preview does not match. No change can be confirmed from this view.",
};

export function consentView(envelope,{expectedDecisionId,expectedPreviewId,expectedActor,
  nowUnixMs,evidence="UNVERIFIED"}={}) {
  let detail=null;
  const blocked = (status="UNAVAILABLE") => freeze({
    kind:"consent",available:false,reviewable:false,canConfirm:false,status,
    title:"Consent unavailable",summary:CODES[status],tone:"error",
    evidence:detail?.evidence ?? "UNVERIFIED",evidenceLabel:detail?.evidenceLabel ?? "Source not verified",
    rows:[],sections:[],operation:null,binding:null,comparisonKey:null,expiresAtMs:null,
  });
  try {
    need(typeof expectedDecisionId==="string" && ID.test(expectedDecisionId));
    need(typeof expectedPreviewId==="string" && ID.test(expectedPreviewId));
    need(typeof expectedActor==="string" && ID.test(expectedActor));
    need(object(envelope) && object(envelope.detail) && object(envelope.preview));
    detail=decisionDetailView(envelope.detail,{expectedId:expectedDecisionId,evidence});
    need(detail.available);
    const d=envelope.detail.data,w=d.context,p=envelope.preview.data;
    if(d.outcome.status!=="VALIDATED_PROPOSAL" || w.trial_mode!=="WITH_TRIALS")return blocked("NOT_ACTIONABLE");
    need(d.outcome.code==="SEMANTICS_AND_HUMAN_REVIEW_REQUIRED");
    need(exact(p,PREVIEW_FIELDS) && exact(p.snapshot,SNAPSHOT_FIELDS));
    const s=p.snapshot;
    need(exact(s.offers,["A","B"]));
    for(const target of ["A","B"])need(exact(s.offers[target],OFFER_FIELDS));
    const preview=previewView(envelope.preview,{expectedId:expectedPreviewId,evidence});
    need(preview.available);
    if(p.state!=="PENDING")return blocked("NOT_ACTIONABLE");
    need(["PREVIEW_RECORDED","EXISTING_PREVIEW","READ_ONLY"].includes(p.code));
    need(p.actor===expectedActor && p.operationId==="preview-op-"+p.previewId);
    need(p.decisionId===d.decisionId && p.decisionDigest===d.decisionDigest &&
      p.generation===d.generation && p.reviewDeadlineUS===d.reviewDeadlineUS);
    need(p.orderId===w.order_id && p.shipmentVersion===w.shipment_version);
    need(p.option===d.proposal.action && p.target===(p.option==="RETRY_A"?"A":"B"));
    // Exact string match, not a lossy JavaScript numeric roundtrip.
    need(s.payload===d.payloadJSON && s.quantity===w.facts.payload.quantity);
    need(s.revision>=w.state_revision && s.policyRevision>=w.policy_revision);
    const offer=s.offers[p.target];
    need(offer.cost<=s.maxCost && offer.capacity>=s.quantity);
    need(p.expiresAt>p.createdAt && p.expiresAt<=p.createdAt+60 && p.expiresAt<=s.observedAt+60);
    need(s.observedAt<=p.createdAt && p.expiresAt<=offer.validUntil);
    need(p.expiresAt<=s.inventoryUntil && p.predictedArrival<=s.deliveryDeadline);
    const reviewSeconds=d.reviewDeadlineUS/1000000+OFFSET;
    need(p.expiresAt<=reviewSeconds && p.createdAt>=d.completedUS/1000000+OFFSET);
    need(p.predictedArrival>=p.createdAt);
    if(!integer(nowUnixMs))return blocked("CLOCK_UNVERIFIED");
    const nowSeconds=nowUnixMs/1000+OFFSET;
    const expiresAtMs=Math.min((p.expiresAt-OFFSET)*1000,d.reviewDeadlineUS/1000);
    need(Number.isFinite(expiresAtMs));
    if(nowSeconds<p.createdAt || nowSeconds<s.observedAt)return blocked("CLOCK_UNVERIFIED");
    if(nowUnixMs>=expiresAtMs)return blocked("EXPIRED");
    const status=evidence==="LIVE"?"REVIEWABLE":"NOT_LIVE";
    const binding=copy({
      previewId:p.previewId,decisionId:p.decisionId,decisionDigest:p.decisionDigest,
      operationId:p.operationId,actor:p.actor,generation:p.generation,
      orderId:p.orderId,shipmentVersion:p.shipmentVersion,snapshotId:p.snapshotId,
      option:p.option,target:p.target,createdAt:p.createdAt,expiresAt:p.expiresAt,
      reviewDeadlineUS:p.reviewDeadlineUS,predictedArrival:p.predictedArrival,snapshot:s,
    });
    // Equality key is only an in-memory comparison, not a cryptographic proof,
    // durable recovery reference, user credential or server dispatch token.
    const comparisonKey=stable(binding);
    const exactRows=[
      row("Action to authorize",p.option),row("Destination",p.target),row("Operation",p.operationId),
      row("Order",p.orderId),row("Shipment version",p.shipmentVersion),row("Data revision",s.revision),
      row("Policy revision",s.policyRevision),row("Quantity",s.quantity),row("Exact payload JSON",s.payload),
      row("Cost units",offer.cost),row("Maximum cost units",s.maxCost),row("Destination capacity",offer.capacity),
      row("Offer observed (UTC)",irisSecondsUTC(s.observedAt)),row("Offer available (UTC)",irisSecondsUTC(offer.availableAt)),
      row("Queue duration seconds",offer.queueSeconds),row("Travel duration seconds",offer.travelSeconds),
      row("Offer valid until (UTC)",irisSecondsUTC(offer.validUntil)),row("Inventory until (UTC)",irisSecondsUTC(s.inventoryUntil)),
      row("Predicted arrival (UTC, not guaranteed)",irisSecondsUTC(p.predictedArrival)),
      row("Delivery deadline (UTC)",irisSecondsUTC(s.deliveryDeadline)),
    ];
    return freeze({
      kind:"consent",available:true,reviewable:status==="REVIEWABLE",canConfirm:false,status,
      title:"Review the exact recovery effect",summary:CODES[status],tone:"warning",
      evidence:detail.evidence,evidenceLabel:detail.evidenceLabel,
      rows:[row("Preview",p.previewId),row("Actor",p.actor),row("Decision",p.decisionId),
        row("Decision digest",p.decisionDigest),row("Runtime generation",p.generation),
        row("Preview expires (UTC)",irisSecondsUTC(p.expiresAt)),
        row("Authority","No approval or dispatch is granted by this display")],
      sections:[
        {title:"Fresh server preview",note:"These are the exact values bound to this preview. A changed value requires a new review and consent.",rows:exactRows,table:null},
        {title:"Before confirming",note:"The server rechecks identity, permissions, state, expiry and the exact preview. A lost response requires reading this same preview and operation, never sending a replacement.",rows:[
          row("Human review","Review the full proposal, evidence, interpretation and effect below before making a decision."),
          row("Recovery reference",p.previewId+" / "+p.operationId),
          row("Rejection","Rejecting this preview does not submit the proposed recovery."),
          row("Result","Confirmation is not acceptance; acceptance is not delivery."),
        ],table:null},
        ...detail.sections,
      ],
      operation:null,binding,comparisonKey,expiresAtMs,
    });
  } catch { return blocked(); }
}
