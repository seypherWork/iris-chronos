"""Explicit recorded interpretation, never fresh inference or dispatch authority.

Pure corpus/projection library only: no HTTP server, model, allowance, native
configuration or approval integration is installed here. Native callers must
still validate freshness, identity, feasibility and all effect permissions.
Corpus provenance hashes bind supplied records; they cannot prove that a model
actually ran. A trusted launcher must supply the independently reviewed evidence
allowlist and exact corpus digest. Synthetic test captures are refused by default.

E1 currently requires the complete captured input, including time and trial
evidence. Fresh-install/rebased demo contexts are deliberately unsupported until
an explicit, separately validated fixture contract exists. C2 may rebind only
four routing/digest fields while its entire factual explanation catalog stays
identical. A subject-selection plan can depend on that catalog too.
"""
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta
from hashlib import sha256
from pathlib import Path
import json
import os
import re
import stat

from . import guard
from chronos_agent import extraction
from chronos_agent.timeview import model_input
from chronos_grounding.renderer_v2 import checked_history

MODE = "RECORDED_REPLAY"
MODEL = "chronos-recorded-replay-v1"
SCHEMA = "chronos.replay-corpus.v1"
E1 = guard.EXTRACTION_CONTRACT
C2 = guard.PLAN_V2_CONTRACT
CONTRACTS = frozenset((E1, C2))
MAX_CORPUS_BYTES = 2 * 1024 * 1024
MAX_RECORDS = 32
MAX_INPUT_BYTES = 65536
MAX_RESPONSE_BYTES = 8192
REBIND_FIELDS = ("conversation_id", "turn_id", "context_digest", "catalog_digest")
_HEX = re.compile(r"[a-f0-9]{64}")
_ID = re.compile(r"[A-Za-z0-9_.:-]{1,128}")
_WIRE_FIELDS = set("schema_version context_id order_id shipment_version state_revision policy_revision observation_id facts_id clock_kind ticks_per_minute utc_origin_us observed_at valid_until trial_horizon facts evidence source_catalog trial_mode trial_status trials context_digest".split())
_FACT_FIELDS = set("payload budget deadline inventory_expires offer_until preference_mode structured_preference messages known_changes options".split())


class ReplayError(ValueError):
    """Fixed diagnostic only; never include case, prompt or response text."""
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _need(condition, code):
    if not condition:
        raise ReplayError(code)


def canonical(value):
    try:
        text = json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False, allow_nan=False)
        text.encode("utf-8")
        return text
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise ReplayError("REPLAY_INVALID_JSON") from None


def digest(value):
    return sha256(canonical(value).encode("utf-8")).hexdigest()


def _hash(value):
    return type(value) is str and _HEX.fullmatch(value) is not None


def _text(value, limit):
    try:
        return type(value) is str and 0 < len(value.encode("utf-8")) <= limit
    except UnicodeError:
        return False


def _exact(value, fields, code="REPLAY_INPUT_INVALID"):
    _need(type(value) is dict and set(value) == set(fields), code)


def _json(raw, limit):
    _need(_text(raw, limit), "REPLAY_JSON_SIZE")
    def pairs(items):
        result = {}
        for key, value in items:
            _need(key not in result, "REPLAY_DUPLICATE_JSON_KEY")
            result[key] = value
        return result
    def constant(_):
        raise ReplayError("REPLAY_INVALID_JSON")
    try:
        value = json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)
        # Detect overflowing float literals and excessive nesting too.
        canonical(value)
        return value
    except ReplayError:
        raise
    except (ValueError, UnicodeError, RecursionError, OverflowError):
        raise ReplayError("REPLAY_INVALID_JSON") from None


def _integer(value, minimum=0):
    return type(value) is int and minimum <= value <= 2**53 - 1


def _e1_wire(input_json):
    envelope = _json(input_json, MAX_INPUT_BYTES)
    _exact(envelope, {"schema_version", "context", "time_view"})
    _need(envelope["schema_version"] == "chronos.experimental-time-view.v1", "REPLAY_INPUT_CONTRACT")
    wire = envelope["context"]
    _exact(wire, _WIRE_FIELDS)
    _need(wire["schema_version"] == "chronos.agent-input.v2"
          and wire["clock_kind"] == "relative_microseconds"
          and type(wire["ticks_per_minute"]) is int
          and wire["ticks_per_minute"] == 60000000, "REPLAY_INPUT_CONTRACT")
    for key in ("context_id", "order_id"):
        _need(type(wire[key]) is str and _ID.fullmatch(wire[key]), "REPLAY_INPUT_INVALID")
    for key in ("shipment_version", "state_revision", "policy_revision", "utc_origin_us",
                "observed_at", "valid_until", "trial_horizon"):
        _need(_integer(wire[key]), "REPLAY_INPUT_INVALID")
    _need(wire["shipment_version"] >= 1 and wire["observed_at"] < wire["valid_until"], "REPLAY_INPUT_INVALID")
    for key in ("observation_id", "facts_id", "context_digest"):
        _need(_hash(wire[key]), "REPLAY_INPUT_INVALID")
    _need(digest({k: v for k, v in wire.items() if k != "context_digest"}) == wire["context_digest"], "REPLAY_CONTEXT_CHANGED")
    facts = wire["facts"]
    _exact(facts, _FACT_FIELDS)
    _need(type(facts["payload"]) is dict and bool(facts["payload"]), "REPLAY_INPUT_INVALID")
    for key in ("budget", "deadline", "inventory_expires", "offer_until"):
        _need(_integer(facts[key]), "REPLAY_INPUT_INVALID")
    _need(facts["preference_mode"] in ("STRUCTURED", "CONTEXT_REQUIRED"), "REPLAY_INPUT_INVALID")
    if facts["preference_mode"] == "STRUCTURED":
        _need(facts["structured_preference"] in ("CHEAPEST_ON_TIME", "EARLIEST_ALLOWED"), "REPLAY_INPUT_INVALID")
    else:
        _need(facts["structured_preference"] is None, "REPLAY_INPUT_INVALID")
    _exact(facts["options"], {"A", "B"})
    for option in facts["options"].values():
        _exact(option, {"cost", "available_at", "queue_duration", "travel_duration"})
        _need(all(_integer(v) for v in option.values()), "REPLAY_INPUT_INVALID")
    _need(type(facts["messages"]) is list and len(facts["messages"]) <= 8, "REPLAY_INPUT_INVALID")
    message_ids = set()
    for message in facts["messages"]:
        _exact(message, {"message_id", "source_id", "at", "order_link", "text"})
        for key in ("message_id", "source_id"):
            _need(type(message[key]) is str and _ID.fullmatch(message[key]), "REPLAY_INPUT_INVALID")
        _need(message["message_id"] not in message_ids, "REPLAY_INPUT_INVALID")
        message_ids.add(message["message_id"])
        _need(_integer(message["at"]) and message["order_link"] in ("VERIFIED_CURRENT", "VERIFIED_OTHER", "UNRESOLVED")
              and _text(message["text"], 8000), "REPLAY_INPUT_INVALID")
    _need(type(facts["known_changes"]) is list and len(facts["known_changes"]) <= 64, "REPLAY_INPUT_INVALID")
    for change in facts["known_changes"]:
        _exact(change, {"event_id", "at", "kind", "target", "value", "observed_at"})
        _need(type(change["event_id"]) is str and _ID.fullmatch(change["event_id"])
              and change["kind"] == "DELAY_QUEUE" and change["target"] in ("A", "B", "*")
              and all(_integer(change[k]) for k in ("at", "value", "observed_at")), "REPLAY_INPUT_INVALID")
    catalog = wire["source_catalog"]
    _need(type(catalog) is list and 1 <= len(catalog) <= 100, "REPLAY_INPUT_INVALID")
    ids = set()
    for source in catalog:
        _exact(source, {"id", "kind"})
        _need(type(source["id"]) is str and _ID.fullmatch(source["id"])
              and source["id"] not in ids and source["kind"] in ("fact", "message", "known_change", "evidence", "trial"), "REPLAY_INPUT_INVALID")
        ids.add(source["id"])
    _need(message_ids <= {s["id"] for s in catalog if s["kind"] == "message"}, "REPLAY_INPUT_INVALID")
    evidence = wire["evidence"]
    _need(type(evidence) is list and 1 <= len(evidence) <= 64, "REPLAY_INPUT_INVALID")
    evidence_ids = set()
    for item in evidence:
        _exact(item, {"source_id", "operationId", "attemptId", "target", "status", "closedForever"})
        _need(type(item["source_id"]) is str and item["source_id"] in ids
              and item["source_id"] not in evidence_ids, "REPLAY_INPUT_INVALID")
        evidence_ids.add(item["source_id"])
        _need(type(item["operationId"]) is str and _ID.fullmatch(item["operationId"])
              and type(item["attemptId"]) is str and _ID.fullmatch(item["attemptId"])
              and item["target"] in ("A", "B")
              and item["status"] in ("ACCEPTED", "NOT_ACCEPTED_FINAL", "UNKNOWN", "NOT_FOUND")
              and type(item["closedForever"]) is bool, "REPLAY_INPUT_INVALID")
    _need(type(wire["trials"]) is list and len(wire["trials"]) <= 2, "REPLAY_INPUT_INVALID")
    _need((wire["trial_mode"] == "WITH_TRIALS" and wire["trial_status"] == "COMPLETE" and len(wire["trials"]) == 2)
          or (wire["trial_mode"] == "WITHOUT_TRIALS_ABLATION" and wire["trial_status"] == "NOT_REQUESTED" and not wire["trials"]), "REPLAY_INPUT_INVALID")
    try:
        _need(_json(model_input(wire), MAX_INPUT_BYTES) == envelope, "REPLAY_TIME_VIEW_CHANGED")
    except ReplayError:
        raise
    except (ValueError, KeyError, TypeError, AttributeError, RecursionError):
        raise ReplayError("REPLAY_TIME_VIEW_CHANGED") from None
    return wire


def _c2_wire(input_json):
    wire = _json(input_json, MAX_INPUT_BYTES)
    _exact(wire, {"schema", "renderer_version", *REBIND_FIELDS, "message", "history", "available_topics", "case_explanations"})
    _need(wire["schema"] == C2 and wire["renderer_version"] == guard.PLAN_V2_RENDERER, "REPLAY_INPUT_CONTRACT")
    _need(_text(wire["message"], 2048), "REPLAY_INPUT_INVALID")
    _need(wire["available_topics"] == sorted(guard.PLAN_V2_TOPICS), "REPLAY_INPUT_INVALID")
    try:
        guard.check_plan_shape({k: wire[k] for k in ("schema", "renderer_version", *REBIND_FIELDS)}
                               | {"topics": ["CLARIFY"], "detail": "concise", "preference": None}, C2)
        _need(checked_history(wire["history"]) == wire["history"], "REPLAY_INPUT_INVALID")
    except ReplayError:
        raise
    except (ValueError, guard.Rejected, KeyError, TypeError, AttributeError, RecursionError):
        raise ReplayError("REPLAY_INPUT_INVALID") from None
    _exact(wire["case_explanations"], guard.PLAN_V2_TOPICS - {"PREFERENCE_CHANGE"})
    for section in wire["case_explanations"].values():
        _exact(section, {"concise", "detailed"})
        _need(all(_text(v, 32768) for v in section.values()), "REPLAY_INPUT_INVALID")
    return wire


def project(response_contract, input_json, system_prompt_sha256):
    """Versioned exact semantic key; never chooses a preference or chat subject."""
    _need(type(response_contract) is str and response_contract in CONTRACTS
          and _hash(system_prompt_sha256), "REPLAY_INPUT_CONTRACT")
    base = {"response_contract": response_contract, "system_prompt_sha256": system_prompt_sha256}
    if response_contract == E1:
        _e1_wire(input_json)
        # A customer's intent can depend on elapsed/absolute time, the trials
        # or referenced evidence. Native feasibility revalidation cannot detect
        # a wrong replayed interpretation, so no input field is discarded here.
        return base | {"projection": "chronos.replay.e1.v2",
                       "captured_input": _json(input_json, MAX_INPUT_BYTES)}
    wire = _c2_wire(input_json)
    # Even a subject-selection plan can infer a preference from the catalog
    # (for example, "use the opposite priority"). Bind all of that evidence.
    return base | {"projection": "chronos.replay.c2.v2", "schema": wire["schema"],
                   "renderer_version": wire["renderer_version"], "message": wire["message"],
                   "history": deepcopy(wire["history"]), "available_topics": deepcopy(wire["available_topics"]),
                   "case_explanations": deepcopy(wire["case_explanations"])}


def projection_key(response_contract, input_json, system_prompt_sha256):
    return digest(project(response_contract, input_json, system_prompt_sha256))


def _response(contract, input_json, response_text):
    _need(_text(response_text, 2048 if contract == E1 else MAX_RESPONSE_BYTES), "REPLAY_RESPONSE_INVALID")
    response = _json(response_text, MAX_RESPONSE_BYTES)
    try:
        if contract == E1:
            wire = _e1_wire(input_json)
            extraction.extraction(response_text, wire)
            stable = {s["id"] for s in wire["source_catalog"] if s["kind"] in ("fact", "message", "known_change")}
            _need(set(response["source_ids"]) <= stable, "REPLAY_UNSTABLE_CITATION")
        else:
            wire = _c2_wire(input_json)
            guard.check_plan_shape(response, C2)
            _need(all(response[k] == wire[k] for k in ("schema", "renderer_version", *REBIND_FIELDS)), "REPLAY_RESPONSE_BINDING")
    except ReplayError:
        raise
    except (ValueError, guard.Rejected, KeyError, TypeError, AttributeError, RecursionError):
        raise ReplayError("REPLAY_RESPONSE_INVALID") from None
    return response


@dataclass(frozen=True)
class ReplayResult:
    response_text: str
    metadata_json: str

    @property
    def metadata(self):
        return json.loads(self.metadata_json)


@dataclass(frozen=True)
class _Record:
    record_id: str
    contract: str
    key: str
    input_json: str
    response_text: str
    provenance_json: str


@dataclass(frozen=True)
class Corpus:
    sha256: str
    records: tuple

    @classmethod
    def from_bytes(cls, raw, *, expected_sha256, allowed_evidence, allow_synthetic=False):
        _need(type(raw) is bytes and 0 < len(raw) <= MAX_CORPUS_BYTES, "REPLAY_CORPUS_SIZE")
        _need(_hash(expected_sha256) and sha256(raw).hexdigest() == expected_sha256, "REPLAY_CORPUS_CHANGED")
        _need(type(allowed_evidence) is dict and bool(allowed_evidence)
              and all(_hash(k) and _text(v, 128) for k, v in allowed_evidence.items()), "REPLAY_PROVENANCE_ALLOWLIST_REQUIRED")
        _need(type(allow_synthetic) is bool, "REPLAY_INVALID_POLICY")
        try:
            body = _json(raw.decode("utf-8"), MAX_CORPUS_BYTES)
        except UnicodeError:
            raise ReplayError("REPLAY_INVALID_JSON") from None
        _exact(body, {"schema", "mode", "records"}, "REPLAY_CORPUS_SHAPE")
        _need(body["schema"] == SCHEMA and body["mode"] == MODE, "REPLAY_CORPUS_CONTRACT")
        _need(type(body["records"]) is list and 1 <= len(body["records"]) <= MAX_RECORDS, "REPLAY_CORPUS_RECORD_LIMIT")
        records, ids, keys = [], set(), set()
        for item in body["records"]:
            _exact(item, {"record_id", "response_contract", "system_prompt_sha256", "input_json", "response_text", "projection_sha256", "provenance"}, "REPLAY_RECORD_SHAPE")
            ident = item["record_id"]
            _need(type(ident) is str and _ID.fullmatch(ident) and ident not in ids, "REPLAY_RECORD_ID")
            contract = item["response_contract"]
            key = projection_key(contract, item["input_json"], item["system_prompt_sha256"])
            _need(item["projection_sha256"] == key and key not in keys, "REPLAY_DUPLICATE_OR_CHANGED_KEY")
            _response(contract, item["input_json"], item["response_text"])
            provenance = item["provenance"]
            _exact(provenance, {"kind", "source_model", "captured_at", "evidence_sha256", "input_sha256", "response_sha256"}, "REPLAY_PROVENANCE_SHAPE")
            kind = provenance["kind"]
            _need(kind == "REAL_MODEL_CAPTURE" or (allow_synthetic and kind == "SYNTHETIC_TEST_ONLY"), "REPLAY_SYNTHETIC_OR_UNKNOWN_PROVENANCE")
            source = provenance["source_model"]
            _need(type(source) is str and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", source)
                  and source != MODEL, "REPLAY_SOURCE_MODEL")
            evidence = provenance["evidence_sha256"]
            _need(_hash(evidence) and allowed_evidence.get(evidence) == source, "REPLAY_PROVENANCE_NOT_ALLOWED")
            _need(provenance["input_sha256"] == sha256(item["input_json"].encode("utf-8")).hexdigest()
                  and provenance["response_sha256"] == sha256(item["response_text"].encode("utf-8")).hexdigest(), "REPLAY_CAPTURE_CHANGED")
            try:
                date = provenance["captured_at"]
                _need(type(date) is str and len(date) <= 40, "REPLAY_CAPTURE_DATE")
                stamp = datetime.fromisoformat(date.replace("Z", "+00:00"))
                _need(stamp.tzinfo is not None and stamp.utcoffset() == timedelta(0), "REPLAY_CAPTURE_DATE")
            except (ValueError, OverflowError):
                raise ReplayError("REPLAY_CAPTURE_DATE") from None
            ids.add(ident); keys.add(key)
            records.append(_Record(ident, contract, key, item["input_json"], item["response_text"], canonical(provenance)))
        return cls(expected_sha256, tuple(records))

    @classmethod
    def load(cls, path, **policy):
        """Read one pinned regular file; reject links and observed replacement.

        Hash pinning remains mandatory. Like the other deployment readers this
        is not a defense against a hostile operating-system administrator.
        """
        try:
            path = Path(path).absolute()
            for part in (*reversed(path.parents), path):
                current = part.lstat()
                _need(not stat.S_ISLNK(current.st_mode)
                      and not getattr(current, "st_file_attributes", 0) & 0x400, "REPLAY_CORPUS_PATH")
            info = path.lstat()
            _need(stat.S_ISREG(info.st_mode), "REPLAY_CORPUS_PATH")
            _need(info.st_size <= MAX_CORPUS_BYTES, "REPLAY_CORPUS_SIZE")
            with path.open("rb") as stream:
                opened = os.fstat(stream.fileno())
                _need((opened.st_dev, opened.st_ino) == (info.st_dev, info.st_ino), "REPLAY_CORPUS_PATH_CHANGED")
                raw = stream.read(MAX_CORPUS_BYTES + 1)
                after = os.fstat(stream.fileno())
            current = path.lstat()
            _need((after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
                  == (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)
                  == (current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns), "REPLAY_CORPUS_PATH_CHANGED")
        except ReplayError:
            raise
        except (OSError, ValueError, TypeError):
            raise ReplayError("REPLAY_CORPUS_UNAVAILABLE") from None
        return cls.from_bytes(raw, **policy)

    def lookup(self, response_contract, input_json, system_prompt_sha256):
        projection = project(response_contract, input_json, system_prompt_sha256)
        key = digest(projection)
        matches = [r for r in self.records if r.contract == response_contract and r.key == key]
        _need(len(matches) == 1, "REPLAY_UNSUPPORTED")
        record = matches[0]
        response_text = record.response_text
        rebound = []
        if response_contract == C2:
            response = _json(response_text, MAX_RESPONSE_BYTES)
            current = _c2_wire(input_json)
            for field in REBIND_FIELDS:
                response[field] = current[field]
            response_text = canonical(response)
            rebound = list(REBIND_FIELDS)
        # Repeat validation against this current input. In particular, citations,
        # structured policy and C2 bindings cannot inherit an old authorization.
        _response(response_contract, input_json, response_text)
        provenance = json.loads(record.provenance_json)
        metadata = {"mode": MODE, "fresh_inference": False, "corpus_sha256": self.sha256,
                    "record_id": record.record_id, "projection": projection["projection"],
                    "projection_sha256": key, "source_model": provenance["source_model"],
                    "provenance_kind": provenance["kind"], "captured_at": provenance["captured_at"],
                    "evidence_sha256": provenance["evidence_sha256"],
                    "recorded_response_sha256": provenance["response_sha256"],
                    "rebound_fields": rebound, "dispatch_authorized": False,
                    "evidence_binding": "ALLOWLIST_MATCH_NOT_RUNTIME_PROOF"}
        return ReplayResult(response_text, canonical(metadata))
