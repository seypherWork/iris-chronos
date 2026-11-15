"""SYNTHETIC fixtures only: these tests do not prove a model or IRIS ran."""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import json
import importlib.util
import os
import sys
import tempfile
import unittest

ROOT = Path(os.environ.get("CHRONOS_REPLAY_SOURCE_ROOT", Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(ROOT / "src"))
from chronos_transport import replay as r
from chronos_agent.timeview import model_input
from chronos_agent import contract as agent_contract
from chronos_simulation import clock
from chronos_simulation.realtime import Runtime
from chronos_conversation import grounded_v2

_seed_spec = importlib.util.spec_from_file_location("replay_test_first_case", ROOT / "deployment" / "first_case.py")
_seed = importlib.util.module_from_spec(_seed_spec)
_seed_spec.loader.exec_module(_seed)

PROMPT = sha256(b"synthetic prompt only").hexdigest()
EVIDENCE = sha256(b"synthetic evidence only").hexdigest()
SOURCE = "synthetic-test-model"
ALLOWLIST = {EVIDENCE: SOURCE}


def seal(wire):
    wire = deepcopy(wire)
    wire["context_digest"] = r.digest({k: v for k, v in wire.items() if k != "context_digest"})
    return model_input(wire)


def e1(queue=60000000, text="Avoid extra cost while arriving on time."):
    # Generate the wire through the existing simulator and contract.prepare,
    # rather than assuming the native adapter's field types. Authority below is
    # synthetic test data, not an authenticated IRIS authority record.
    world = _seed.definition("1"*32, "economy")
    world.update(deadline=20, inventory_expires=6)
    world["messages"][0]["text"] = text
    world["options"] = {
        "A":dict(cost=3,available_at=0,queue_minutes=queue//60000000,travel_minutes=7),
        "B":dict(cost=6,available_at=0,queue_minutes=0,travel_minutes=5)}
    with tempfile.TemporaryDirectory(prefix="chronos-replay-test-") as directory:
        runtime = Runtime((Path(directory)/"destinations").resolve(), create=True)
        runtime.register(world)
        observation = runtime.observe(world["order_id"])
        origin = observation["definition"]["utc_origin_us"]
        original = dict(operation_id="original-test",attempt_id="attempt-1",order_id=world["order_id"],
                        shipment_version=1,target="A",payload=r.canonical(world["payload"]),
                        reserved_at=observation["clock"],valid_until=360000000)
        store = runtime.registry._destination(world["order_id"])
        store.submit_realtime(original,expected_revision=observation["facts_revision"])
        store.close_realtime(original)
        observation = runtime.observe(world["order_id"])
        receipt = observation["operations"][0]["receipt"]
        operation = {k:receipt[k] for k in ("operationId","attemptId","orderId","shipmentVersion","target","reference")}
        operation.update(payload=r.canonical(world["payload"]),state="NOT_ACCEPTED_FINAL")
        authority = dict(dispatchGranted=False,operation=operation,
                         effect=dict(quarantined=False,state="OPEN",currentOperationId=operation["operationId"],
                                     snapshotId=1,snapshot=clock.authority_snapshot(observation)))
        prepared = agent_contract.prepare(observation,authority,"context-old",now_us=max(clock.now_us(),origin+observation["clock"]),
                                          gate_state="OPEN",response_contract=r.E1)
        if prepared["status"] != "READY":
            raise AssertionError("Synthetic protocol preparation failed: "+prepared["code"])
        return prepared["input_json"]


def extraction(pref="CHEAPEST_ON_TIME"):
    return r.canonical(dict(schema_version=r.E1,interpreted_preference=pref,
                            reason_code="CONTEXT_AMBIGUOUS" if pref=="UNRESOLVED" else "PREFERENCE_MATCH",
                            source_ids=["customer-preference"],rationale="Synthetic recorded interpretation only.",clarification=None))


def c2(message="Why was this option recommended?",history=None):
    fixture=json.loads((ROOT/"tests/web/fixtures/grounded262.json").read_text(encoding="utf-8"))
    context=fixture["cases"][0]["packet"]["context"]
    scope=dict(installation_id="synthetic-install",actor="synthetic-reader",session_binding="synthetic-session",
               case_id="synthetic-case",shipment_version=1)
    conversation=context["grounding"]["source_records"]["chat-effect"]["conversation_id"]
    _,provider=grounded_v2.prepare(scope,context,conversation_id=conversation,turn_id="turn-old",user_text=message,history=history or [])
    return provider["input_json"]


def plan(raw=None):
    wire=json.loads(raw or c2())
    return r.canonical({k:wire[k] for k in ("schema","renderer_version",*r.REBIND_FIELDS)}
                       |dict(topics=["DECISION","COMPARISON"],detail="detailed",preference=None))


def record(contract,raw,answer,ident="synthetic-1"):
    return dict(record_id=ident,response_contract=contract,system_prompt_sha256=PROMPT,input_json=raw,response_text=answer,
                projection_sha256=r.projection_key(contract,raw,PROMPT),
                provenance=dict(kind="SYNTHETIC_TEST_ONLY",source_model=SOURCE,captured_at="2026-11-12T10:00:00Z",evidence_sha256=EVIDENCE,
                                input_sha256=sha256(raw.encode()).hexdigest(),response_sha256=sha256(answer.encode()).hexdigest()))


def load(records,**policy):
    raw=r.canonical(dict(schema=r.SCHEMA,mode=r.MODE,records=records)).encode()
    args=dict(expected_sha256=sha256(raw).hexdigest(),allowed_evidence=ALLOWLIST,allow_synthetic=True)
    args.update(policy)
    return r.Corpus.from_bytes(raw,**args)


class ReplayTests(unittest.TestCase):
    def setUp(self):
        self.source_e1=e1()

    def reject(self,code,callback):
        with self.assertRaises(r.ReplayError) as got:callback()
        self.assertEqual(code,got.exception.code)

    def corpus(self):return load([record(r.E1,self.source_e1,extraction())])

    def test_e1_preserves_recorded_bytes_and_honest_metadata(self):
        answer=self.corpus().lookup(r.E1,self.source_e1,PROMPT)
        self.assertEqual(extraction(),answer.response_text)
        self.assertEqual(r.MODE,answer.metadata["mode"])
        self.assertEqual("SYNTHETIC_TEST_ONLY",answer.metadata["provenance_kind"])
        self.assertFalse(answer.metadata["fresh_inference"])
        self.assertFalse(answer.metadata["dispatch_authorized"])
        self.assertEqual([],answer.metadata["rebound_fields"])

    def test_separate_a_b_hold_captures(self):
        a,b,h=e1(),e1(queue=420000000),e1(text="Cost or speed? I have not decided.")
        corpus=load([record(r.E1,a,extraction(),"a"),record(r.E1,b,extraction(),"b"),record(r.E1,h,extraction("UNRESOLVED"),"hold")])
        self.assertEqual("a",corpus.lookup(r.E1,a,PROMPT).metadata["record_id"])
        self.assertEqual("b",corpus.lookup(r.E1,b,PROMPT).metadata["record_id"])
        self.assertEqual("UNRESOLVED",json.loads(corpus.lookup(r.E1,h,PROMPT).response_text)["interpreted_preference"])

    def test_clock_receipt_and_context_changes_are_not_portable_replay(self):
        wire=json.loads(self.source_e1)["context"]
        wire.update(context_id="fresh-context",order_id="fresh-order",utc_origin_us=1800000000000000,
                    observed_at=1000000,valid_until=31000000,observation_id="c"*64,facts_id="d"*64)
        wire["evidence"][0].update(source_id="evidence:fresh",operationId="operation-fresh")
        for s in wire["source_catalog"]:
            if s["kind"]=="evidence":s["id"]="evidence:fresh"
        self.reject("REPLAY_UNSUPPORTED",lambda:self.corpus().lookup(r.E1,seal(wire),PROMPT))

    def test_changed_budget_queue_message_provenance_or_acceptance_reject(self):
        corpus=self.corpus()
        for field in ("budget","queue","message","provenance","acceptance"):
            wire=json.loads(self.source_e1)["context"]
            if field=="budget":wire["facts"]["budget"]=7
            if field=="queue":wire["facts"]["options"]["A"]["queue_duration"]+=1
            if field=="message":wire["facts"]["messages"][0]["text"]+=" "
            if field=="provenance":wire["facts"]["messages"][0]["order_link"]="VERIFIED_OTHER"
            if field=="acceptance":wire["evidence"][0]["closedForever"]=False
            self.reject("REPLAY_UNSUPPORTED",lambda:corpus.lookup(r.E1,seal(wire),PROMPT))

    def test_context_digest_and_time_conversion_are_verified(self):
        value=json.loads(e1());value["context"]["facts"]["budget"]=7
        self.reject("REPLAY_CONTEXT_CHANGED",lambda:r.project(r.E1,r.canonical(value),PROMPT))
        value=json.loads(e1());value["time_view"]["unit"]="minutes"
        self.reject("REPLAY_TIME_VIEW_CHANGED",lambda:r.project(r.E1,r.canonical(value),PROMPT))

    def test_attempt_identity_uses_the_real_string_contract(self):
        wire=json.loads(e1())["context"]
        self.assertEqual("attempt-1",wire["evidence"][0]["attemptId"])
        wire["evidence"][0]["attemptId"]=1
        self.reject("REPLAY_INPUT_INVALID",lambda:r.project(r.E1,seal(wire),PROMPT))

    def test_unknown_contract_and_wrong_prompt(self):
        self.reject("REPLAY_INPUT_CONTRACT",lambda:self.corpus().lookup([],e1(),PROMPT))
        self.reject("REPLAY_UNSUPPORTED",lambda:self.corpus().lookup(r.E1,e1(),"f"*64))

    def test_dynamic_trial_and_receipt_citations_are_refused(self):
        raw=e1()
        receipt_source=next(s["id"] for s in json.loads(raw)["context"]["source_catalog"] if s["kind"]=="evidence")
        for citation in ("trial:opt-a",receipt_source):
            answer=json.loads(extraction());answer["source_ids"].append(citation)
            self.reject("REPLAY_UNSTABLE_CITATION",lambda:load([record(r.E1,raw,r.canonical(answer))]))

    def test_c2_rebind_changes_only_four_fields_never_fact_prose(self):
        old=c2();stored=json.loads(plan(old));corpus=load([record(r.C2,old,plan(old))])
        fresh=json.loads(old)
        fresh.update(conversation_id="fresh-conversation",turn_id="fresh-turn",context_digest="c"*64,catalog_digest="d"*64)
        answer=corpus.lookup(r.C2,r.canonical(fresh),PROMPT);current=json.loads(answer.response_text)
        self.assertEqual(set(r.REBIND_FIELDS),{k for k in current if current[k]!=stored[k]})
        self.assertNotIn("answer",current)
        self.assertEqual(stored["topics"],current["topics"])
        self.assertEqual(list(r.REBIND_FIELDS),answer.metadata["rebound_fields"])

    def test_c2_does_not_fuzzy_match_or_trim_history(self):
        corpus=load([record(r.C2,c2(),plan())])
        self.reject("REPLAY_UNSUPPORTED",lambda:corpus.lookup(r.C2,c2(message="why was this option recommended?"),PROMPT))
        self.reject("REPLAY_UNSUPPORTED",lambda:corpus.lookup(r.C2,c2(history=[dict(role="user",text="Earlier question")]),PROMPT))

    def test_c2_bad_stored_binding_and_unknown_topic_reject(self):
        for key,value,code in (("context_digest","f"*64,"REPLAY_RESPONSE_BINDING"),("topics",["SEND_NOW"],"REPLAY_RESPONSE_INVALID")):
            response=json.loads(plan());response[key]=value
            self.reject(code,lambda:load([record(r.C2,c2(),r.canonical(response))]))

    def test_synthetic_not_accepted_in_production_policy(self):
        self.reject("REPLAY_SYNTHETIC_OR_UNKNOWN_PROVENANCE",lambda:load([record(r.E1,e1(),extraction())],allow_synthetic=False))

    def test_evidence_model_allowlist_is_required(self):
        self.reject("REPLAY_PROVENANCE_ALLOWLIST_REQUIRED",lambda:load([record(r.E1,e1(),extraction())],allowed_evidence={}))
        self.reject("REPLAY_PROVENANCE_NOT_ALLOWED",lambda:load([record(r.E1,e1(),extraction())],allowed_evidence={EVIDENCE:"wrong-model"}))

    def test_capture_projection_and_corpus_hashes_are_required(self):
        rec=record(r.E1,e1(),extraction());rec["provenance"]["response_sha256"]="f"*64
        self.reject("REPLAY_CAPTURE_CHANGED",lambda:load([rec]))
        rec=record(r.E1,e1(),extraction());rec["projection_sha256"]="f"*64
        self.reject("REPLAY_DUPLICATE_OR_CHANGED_KEY",lambda:load([rec]))
        self.reject("REPLAY_CORPUS_CHANGED",lambda:load([record(r.E1,e1(),extraction())],expected_sha256="f"*64))

    def test_duplicate_projection_is_rejected(self):
        self.reject("REPLAY_DUPLICATE_OR_CHANGED_KEY",lambda:load([record(r.E1,self.source_e1,extraction(),"one"),record(r.E1,self.source_e1,extraction(),"two")]))

    def test_duplicate_json_keys_and_limits(self):
        raw=b'{"schema":"a","schema":"b"}'
        self.reject("REPLAY_DUPLICATE_JSON_KEY",lambda:r.Corpus.from_bytes(raw,expected_sha256=sha256(raw).hexdigest(),allowed_evidence=ALLOWLIST))
        self.reject("REPLAY_JSON_SIZE",lambda:r.project(r.C2,"x"*(r.MAX_INPUT_BYTES+1),PROMPT))
        self.reject("REPLAY_CORPUS_SIZE",lambda:r.Corpus.from_bytes(b"x"*(r.MAX_CORPUS_BYTES+1),expected_sha256="a"*64,allowed_evidence=ALLOWLIST))

    def test_nonfinite_and_unpaired_unicode_do_not_escape_as_runtime_exceptions(self):
        for raw in ('{"bad":NaN}', '{"bad":1e999}', '{"bad":"\\ud800"}'):
            self.reject("REPLAY_INVALID_JSON",lambda:r.project(r.C2,raw,PROMPT))

    def test_record_count_is_bounded_before_processing_records(self):
        rec=record(r.E1,e1(),extraction())
        self.reject("REPLAY_CORPUS_RECORD_LIMIT",lambda:load([rec]*(r.MAX_RECORDS+1)))

    def test_missing_corpus_is_not_created_and_pinned_file_loads(self):
        raw=r.canonical(dict(schema=r.SCHEMA,mode=r.MODE,records=[record(r.E1,self.source_e1,extraction())])).encode()
        policy=dict(expected_sha256=sha256(raw).hexdigest(),allowed_evidence=ALLOWLIST,allow_synthetic=True)
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/"corpus.json"
            self.reject("REPLAY_CORPUS_UNAVAILABLE",lambda:r.Corpus.load(path,**policy))
            self.assertFalse(path.exists())
            path.write_bytes(raw)
            self.assertEqual(extraction(),r.Corpus.load(path,**policy).lookup(r.E1,self.source_e1,PROMPT).response_text)

    def test_metadata_changes_do_not_change_corpus_or_result(self):
        answer=self.corpus().lookup(r.E1,self.source_e1,PROMPT)
        metadata=answer.metadata;metadata["fresh_inference"]=True
        self.assertFalse(answer.metadata["fresh_inference"])

    def test_elapsed_time_conditional_preference_cannot_replay_earlier_interpretation(self):
        message=('For the first two minutes, avoid extra cost while meeting the deadline. '
                 'If three minutes have elapsed since this order started, prioritize the '
                 'earliest arrival and accept extra cost within the existing budget.')
        old=e1(text=message)
        corpus=load([record(r.E1,old,extraction())])
        current=json.loads(old)["context"]
        current.update(context_id="new-context-after-three-minutes",observed_at=180000000,valid_until=210000000,observation_id="d"*64)
        for trial in current["trials"]:
            row=trial["observations"]
            target="A" if row["action"]=="RETRY_A" else "B"
            offer=current["facts"]["options"][target]
            row["accepted_at"]=max(current["observed_at"],offer["available_at"])+offer["queue_duration"]
            row["arrival"]=row["accepted_at"]+offer["travel_duration"]
            row["trace"]=[]
        fresh=seal(current)
        self.assertNotEqual(r.projection_key(r.E1,old,PROMPT),r.projection_key(r.E1,fresh,PROMPT))
        self.reject("REPLAY_UNSUPPORTED",lambda:corpus.lookup(r.E1,fresh,PROMPT))

    def test_case_relative_opposite_priority_plan_cannot_rebind_to_changed_catalog(self):
        question='For the next evaluation, use the opposite priority to the one behind this recommendation.'
        old=c2(message=question)
        recorded=json.loads(plan(old))
        recorded.update(topics=["PREFERENCE_CHANGE","CURRENT_REVIEW"],preference="EARLIEST_ALLOWED")
        corpus=load([record(r.C2,old,r.canonical(recorded))])
        fresh=json.loads(old)
        fresh.update(conversation_id="new-current-case",turn_id="new-current-turn",context_digest="c"*64,catalog_digest="d"*64)
        fresh["case_explanations"]["DECISION"]={
            "concise":"The current recommendation prioritizes the earliest arrival.",
            "detailed":"The model interpreted EARLIEST_ALLOWED and selected the earliest eligible option."}
        raw=r.canonical(fresh)
        self.assertNotEqual(r.projection_key(r.C2,old,PROMPT),r.projection_key(r.C2,raw,PROMPT))
        self.reject("REPLAY_UNSUPPORTED",lambda:corpus.lookup(r.C2,raw,PROMPT))


if __name__=="__main__":unittest.main()
