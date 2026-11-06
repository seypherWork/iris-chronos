"""Historical decision-detail projection. No I/O, model call or authorization.

Only a trusted native adapter may load the private ledger record and invoke this
module. Never accept a browser/model-supplied ledger record. The installed native
bridge uses manifest-bound helpers. This view cannot authorize a preview or effect.
"""
from copy import deepcopy
import re
# The native manifest-bound loader injects the exact namespace-owned helpers.
# Standalone tests use ordinary imports. No dependency alias comes from data.
if "_chronos_review_dependencies" in globals():
    parse, sensitive, OPTIONS, HOLD_REASONS, canonical, fingerprint, response_contract_of, validate_explanation = _chronos_review_dependencies
else:
    from chronos_agent.proposal import parse, sensitive, OPTIONS, HOLD_REASONS
    from chronos_agent.contract import response_contract_of, validate_explanation
    from chronos_simulation.model import canonical, fingerprint

MAX_INT = 2**53 - 1
class InvalidDisplay(ValueError):
    pass

def need(condition):
    if not condition:
        raise InvalidDisplay()

def text(limit, pattern=None, empty=False):
    def validate(value):
        need(type(value) is str and len(value) <= limit and (empty or bool(value)))
        if pattern:
            need(re.fullmatch(pattern, value) is not None)
        return value
    return validate

def number(value):
    need(type(value) is int and 0 <= value <= MAX_INT)
    return value

def positive(value):
    number(value)
    need(value > 0)
    return value

def boolean(value):
    need(type(value) is bool)
    return value

def enum(*values):
    def validate(value):
        need(type(value) is str and value in values)
        return value
    return validate

def nullable(validator):
    return lambda value: None if value is None else validator(value)

def fields(schema):
    def validate(value):
        need(type(value) is dict and set(value) == set(schema))
        return {key: validator(value[key]) for key, validator in schema.items()}
    return validate

def items(validator, maximum):
    def validate(value):
        need(type(value) is list and len(value) <= maximum)
        return [validator(item) for item in value]
    return validate

identifier = text(128, r"[A-Za-z0-9_.:-]+")
digest = text(64, r"[0-9a-f]{64}")
code = text(128, r"[A-Z0-9_]*", empty=True)
action = enum("RETRY_A", "FAILOVER_B")
offer = fields(dict(cost=number, available_at=number, queue_duration=number, travel_duration=number))
message = fields(dict(message_id=identifier, source_id=identifier, at=number,
    order_link=enum("VERIFIED_CURRENT", "VERIFIED_OTHER", "UNRESOLVED"), text=text(2000)))
change = fields(dict(event_id=identifier, at=number, kind=enum("DELAY_QUEUE"),
    target=enum("A", "B", "*"), value=number, observed_at=number))
def payload(value):
    # Business payload is intentionally extensible in the simulator. Do not
    # silently narrow it to item/quantity or discard additional effect fields.
    need(type(value) is dict)
    positive(value.get("quantity"))
    forbidden = re.compile(r"(?:password|passwd|api[_ -]?key|client[_ -]?secret|access[_ -]?token|authorization|private[_ -]?key)", re.I)
    def visit(item, depth=0):
        need(depth <= 12)
        if type(item) is dict:
            need(len(item) <= 128)
            for key, child in item.items():
                text(128)(key)
                need(forbidden.fullmatch(key) is None)
                visit(child, depth + 1)
        elif type(item) is list:
            need(len(item) <= 128)
            for child in item:
                visit(child, depth + 1)
        elif type(item) is str:
            text(65536, empty=True)(item)
        elif type(item) is int:
            need(-MAX_INT <= item <= MAX_INT)
        elif item is None or type(item) is bool:
            pass
        elif type(item) is float:
            import math
            need(math.isfinite(item))
        else:
            raise InvalidDisplay()
    visit(value)
    return deepcopy(value)

facts = fields(dict(payload=payload,
    budget=number, deadline=number, inventory_expires=number, offer_until=number,
    preference_mode=enum("STRUCTURED", "CONTEXT_REQUIRED"),
    structured_preference=nullable(enum("CHEAPEST_ON_TIME", "EARLIEST_ALLOWED")),
    messages=items(message, 8), known_changes=items(change, 64),
    options=fields(dict(A=offer, B=offer))))
evidence = fields(dict(source_id=identifier, operationId=identifier, attemptId=identifier,
    target=enum("A", "B"), status=enum("ACCEPTED", "UNKNOWN", "NOT_ACCEPTED_FINAL"),
    closedForever=boolean))

def trace_event(value):
    need(type(value) is list and len(value) == 2)
    return [number(value[0]), text(256)(value[1])]

trial = fields(dict(trial_id=identifier, option_id=enum("opt-a", "opt-b"),
    observations=fields(dict(action=action,
        state=enum("QUEUED", "BLOCKED", "NOT_ACCEPTED_FINAL", "ACCEPTED", "DELIVERED_SIMULATED"),
        reason=code, accepted_at=nullable(number), arrival=nullable(number),
        cost=number, trace=items(trace_event, 30)))))
catalog_item = fields(dict(id=identifier, kind=enum("fact", "message", "known_change", "evidence", "trial")))
wire_schema = fields(dict(
    schema_version=enum("chronos.agent-input.v2"), context_id=identifier, context_digest=digest,
    order_id=identifier, shipment_version=positive, state_revision=positive, policy_revision=positive,
    observation_id=identifier, facts_id=digest, clock_kind=enum("relative_microseconds"),
    ticks_per_minute=positive, utc_origin_us=number, observed_at=number, valid_until=number,
    trial_horizon=positive, facts=facts, evidence=items(evidence, 64),
    source_catalog=items(catalog_item, 128), trial_mode=enum("WITH_TRIALS", "WITHOUT_TRIALS_ABLATION"),
    trial_status=enum("COMPLETE", "NOT_REQUESTED"), trials=items(trial, 2)))
proposal_schema = fields(dict(
    schema_version=enum("chronos.agent-proposal.v2"), context_id=identifier,
    context_digest=digest, order_id=identifier, shipment_version=positive,
    state_revision=positive, action=enum("RETRY_A", "FAILOVER_B", "HOLD"),
    option_id=nullable(enum("opt-a", "opt-b")),
    interpreted_preference=enum("CHEAPEST_ON_TIME", "EARLIEST_ALLOWED", "UNRESOLVED", "NOT_USED"),
    source_ids=items(identifier, 16), reason_code=code, rationale=text(600),
    clarification=nullable(text(240))))

def historical_proposal(raw, wire):
    # Stored FINISH validation used freshly observed alternatives, which need
    # not equal PREPARE's ranking. A historical display must not rerun ranking
    # or feasibility using either old or invented alternatives.
    proposal = proposal_schema(raw)
    need(len(canonical(proposal).encode("utf-8")) <= 4096 and not sensitive(proposal))
    for key in ("context_id", "context_digest", "order_id", "shipment_version", "state_revision"):
        need(proposal[key] == wire[key])
    sources = proposal["source_ids"]
    need(1 <= len(sources) <= 16 and len(set(sources)) == len(sources))
    need(set(sources) <= {item["id"] for item in wire["source_catalog"]})
    need(bool(proposal["rationale"].strip()))
    option, preference, reason = proposal["action"], proposal["interpreted_preference"], proposal["reason_code"]
    question = proposal["clarification"]
    if question is not None:
        need(bool(question.strip()) and option == "HOLD" and reason in {"CONTEXT_AMBIGUOUS", "CONTEXT_INCOMPLETE"})
    if option == "HOLD":
        need(proposal["option_id"] is None and reason in HOLD_REASONS)
        need(preference in HOLD_REASONS[reason] and reason != "ACCEPTANCE_UNRESOLVED")
    else:
        need(proposal["option_id"] == OPTIONS[option] and reason == "PREFERENCE_MATCH")
        need(preference in {"CHEAPEST_ON_TIME", "EARLIEST_ALLOWED"})
        facts = wire["facts"]
        if facts["preference_mode"] == "STRUCTURED":
            need(preference == facts["structured_preference"])
        else:
            current_sources = {item["message_id"] for item in facts["messages"] if item["order_link"] == "VERIFIED_CURRENT"}
            need(bool(current_sources.intersection(sources)))
    return proposal



def validate_wire(raw):
    wire = wire_schema(raw)
    need(len(canonical(wire).encode("utf-8")) <= 65536 and not sensitive(wire))
    need(wire["context_digest"] == fingerprint({k: v for k, v in wire.items() if k != "context_digest"}))
    need(wire["ticks_per_minute"] == 60_000_000 and wire["trial_horizon"] == 1_800_000_000)
    need(wire["observed_at"] < wire["valid_until"])
    expected = {key: "fact" for key in ("fact:order", "fact:policy", "option:A", "option:B")}
    def add(key, kind):
        need(key not in expected)
        expected[key] = kind
    for m in wire["facts"]["messages"]:
        need(m["at"] <= wire["observed_at"])
        add(m["message_id"], "message")
    for c in wire["facts"]["known_changes"]:
        need(c["observed_at"] <= wire["observed_at"] <= c["at"])
        add(c["event_id"], "known_change")
    for e in wire["evidence"]:
        add(e["source_id"], "evidence")
    if wire["trial_mode"] == "WITH_TRIALS":
        need(wire["trial_status"] == "COMPLETE" and len(wire["trials"]) == 2)
        seen = set()
        for t in wire["trials"]:
            expected_option = {"RETRY_A": "opt-a", "FAILOVER_B": "opt-b"}[t["observations"]["action"]]
            need(t["option_id"] == expected_option and t["trial_id"] == "trial:" + expected_option)
            need(expected_option not in seen)
            seen.add(expected_option)
            add(t["trial_id"], "trial")
    else:
        need(wire["trial_status"] == "NOT_REQUESTED" and not wire["trials"])
    catalog = wire["source_catalog"]
    need(len(catalog) == len(expected) and {v["id"]: v["kind"] for v in catalog} == expected)
    pref = wire["facts"]
    need((pref["preference_mode"] == "CONTEXT_REQUIRED") == (pref["structured_preference"] is None))
    return wire

def historical_attribution(record, decision):
    # Verify the original frozen binding only. Never rerank/reassemble historical
    # alternatives or treat the current installation as provenance of old data.
    contract = response_contract_of(record)
    call = decision.get("call", {})
    need(type(call) is dict)
    if contract == "chronos.preference-extraction.v1":
        need(call.get("responseContract") == contract)
        need(call.get("interpretationOrigin") == "MODEL")
        need(call.get("selectionOrigin") == "DETERMINISTIC_CODE")
        digest(call.get("profileSha256"))
        return {"responseContract": contract, "interpretationOrigin": "MODEL",
                "selectionOrigin": "DETERMINISTIC_CODE"}
    need(not {"responseContract", "interpretationOrigin", "selectionOrigin"}.intersection(call))
    return {"responseContract": contract, "interpretationOrigin": "NOT_RECORDED",
            "selectionOrigin": "NOT_RECORDED"}


def historical_trace(decision, namespace):
    # Only original metadata bound before Chat. This is not proof of completion
    # or message retention, and never uses the HTTP read request's session ID.
    call = decision.get("call", {})
    keys = {"aiHubSessionId", "interopSessionId"}
    if not keys.intersection(call):
        return None
    native_id = text(18, r"[0-9]{1,18}")
    ai, interop = native_id(call.get("aiHubSessionId")), native_id(call.get("interopSessionId"))
    need(call.get("sessionSnapshot") == "BEFORE_CHAT")
    bound = number(call.get("boundUS"))
    need(decision["createdUS"] <= bound <= decision["completedUS"])
    if namespace is not None:
        text(64, r"[A-Za-z%][A-Za-z0-9_%-]{0,63}")(namespace)
    return {"aiHubSessionId": ai, "interopSessionId": interop,
            "namespace": namespace, "sessionSnapshot": "BEFORE_CHAT"}


def project(decision_json, expected_id, *, namespace=None):
    """Return safe historical material or a constant unavailable result.

    Does not revalidate current world/authority, authenticate, reserve or dispatch.
    No token, instruction, runtime path, claim, transport or validation ID is copied.
    The native caller must enforce fresh READ permission before and after projection.
    """
    unavailable = {"code": "DECISION_DETAIL_UNAVAILABLE", "dispatchGranted": False,
                   "canConfirm": False, "currentAuthorityVerified": False}
    try:
        identifier(expected_id)
        need(type(decision_json) is str and len(decision_json.encode("utf-8")) <= 524288)
        d = parse(decision_json)
        need(type(d) is dict and d["state"] == "COMPLETED" and d["requestId"] == expected_id)
        identifier(d["generation"])
        r, record = d["result"], d["prepared"]["record"]
        need(type(r) is dict and set(r) <= {"status", "code", "dispatch_authorized", "proposal", "runtime_generation", "explanation"})
        need(r["status"] in {"VALIDATED_PROPOSAL", "VALIDATED_HOLD"} and r["dispatch_authorized"] is False)
        code(r["code"])
        need(r.get("runtime_generation", d["generation"]) == d["generation"])
        wire = validate_wire(record["wire"])
        need((wire["context_id"], wire["order_id"], wire["shipment_version"], wire["trial_mode"]) ==
             (expected_id, d["orderId"], d["shipmentVersion"], d["mode"]))
        need(type(d["shipmentVersion"]) is int)
        need(record["facts_digest"] == fingerprint(wire["facts"]))
        start, deadline, completed, review_end = (number(record["started_us"]), number(record["deadline_us"]),
            number(d["completedUS"]), number(record["review_deadline_us"]))
        created = number(d["createdUS"]); need(number(d["deadlineUS"]) == deadline)
        need(start <= created <= completed < deadline <= review_end)
        attribution = historical_attribution(record, d)
        proposal = historical_proposal(r["proposal"], wire)
        if "explanation" in r:
            receipt=validate_explanation(r["explanation"],record,proposal)
            need(created<=receipt["finished_at_us"]<=completed)
        need((r["status"] == "VALIDATED_HOLD") == (proposal["action"] == "HOLD"))
        decision_digest = fingerprint({"requestId": expected_id, "generation": d["generation"],
            "completedUS": completed, "context_digest": wire["context_digest"],
            "result": r, "reviewDeadlineUS": review_end})
        result = {"code": "DECISION_DETAIL_RECORDED", "schema": "chronos.review-detail.v2",
            "attribution": attribution,
            "dispatchGranted": False, "canConfirm": False, "currentAuthorityVerified": False,
            "historical": True, "decisionId": expected_id, "decisionDigest": decision_digest,
            "generation": d["generation"], "completedUS": completed, "reviewDeadlineUS": review_end,
            "outcome": {"status": r["status"], "code": r["code"]},
            "proposal": deepcopy(proposal), "context": wire,
            "payloadJSON": canonical(wire["facts"]["payload"])}
        native_trace = historical_trace(d, namespace)
        if native_trace is not None:
            result["schema"] = "chronos.review-detail.v3"
            result["nativeTrace"] = native_trace
        need(not sensitive(result) and len(canonical(result).encode("utf-8")) <= 262144)
        return result
    except (ValueError, TypeError, KeyError, OverflowError, RecursionError):
        return unavailable
