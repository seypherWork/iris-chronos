"""Create fixed, owned synthetic incident history for the jury walkthrough.

Trusted container CLI only; not an HTTP route, model tool, consent or dispatch
API. It creates one original simulator attempt and independently reads its
final rejection, acceptance or pending state, according to the fixed scenario.
This is synthetic HISTORY, not an approved recovery or evidence of AI usefulness.
The next native steps (authority registration and PROPOSE) are deliberately not
performed by this seed helper.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import re
import sqlite3
import sys

# One short-lived CLI process, never the shared Embedded Python interpreter.
SOURCE = Path(__file__).resolve().parents[1] / "src"
sys.dont_write_bytecode = True
# Keep the ObjectScript Chronos tree out of the shared Python search path.
_import_path_before = list(sys.path)
try:
    sys.path.insert(0, str(SOURCE))
    from chronos_simulation import clock
    from chronos_simulation.model import Blocked, canonical
    from chronos_simulation.realtime import Runtime
finally:
    sys.path[:] = _import_path_before
    del _import_path_before

CASES = {
    "earliest": "For this order, choose the earliest arrival within the budget, even if it costs more.",
    "economy": "For this order, choose the lowest cost that still meets the delivery deadline.",
    "ambiguous": "For this order, I have not decided whether lower cost or earlier arrival matters more. Please ask me before choosing.",
    "queue_inventory": "For this order, choose the lowest cost that still meets the delivery deadline and all inventory constraints.",
    "accepted": "For this order, choose the lowest cost that meets the deadline.",
    "uncertain": "For this order, choose the earliest arrival within budget.",
}


def identifiers(deployment_id, case):
    if type(deployment_id) is not str or re.fullmatch("[a-f0-9]{32}",deployment_id) is None:
        raise Blocked("invalid_deployment_id")
    if type(case) is not str or case not in CASES:
        raise Blocked("unknown_jury_case")
    return "jury-" + deployment_id + "-" + case


def definition(deployment_id, case):
    order = identifiers(deployment_id,case)
    message = "customer-preference"
    world = {
        "order_id":order,"shipment_version":1,"revision":1,"budget":8,
        "deadline":25,"inventory_expires":30,"original_status":"NOT_ACCEPTED_FINAL",
        "preference":"context","payload":{"sku":"SYNTHETIC-JURY-PARCEL","quantity":1},
        "messages":[{"id":message,"text":CASES[case]}],
        "agent_provenance":{"messages":{message:{"source_id":"synthetic-customer",
            "at_minutes":0,"order_link":"VERIFIED_CURRENT","order_id":order,"shipment_version":1}},"changes":{}},
        "options":{"A":{"cost":3,"available_at":0,"queue_minutes":1,"travel_minutes":18},
                   "B":{"cost":6,"available_at":0,"queue_minutes":0,"travel_minutes":10}},
    }

    # CHR-C02: A looks cheap/on-time but its queue outlives inventory.
    # The branch engine must derive that failure; never seed it as an outcome.
    if case == "queue_inventory":
        world.update(deadline=20, inventory_expires=6)
        world["options"] = {
            "A": {"cost":3,"available_at":0,"queue_minutes":7,"travel_minutes":8},
            "B": {"cost":6,"available_at":0,"queue_minutes":0,"travel_minutes":9},
        }

    # Only the synthetic original queue differs: immediate accepted history or
    # a real pending attempt. Its receipt, never this case name, governs safety.
    if case == "accepted": world["options"]["A"]["queue_minutes"] = 0
    if case == "uncertain": world["options"]["A"]["queue_minutes"] = 30
    return world


def seed(root, deployment_id, case, *, initialize_catalog=False):
    """Internal trusted installer entry; root is never supplied by browser/agent.

    Repeating the same seed retains the existing UTC epoch, deadlines and original
    operation. Refuse extra operations (including a recovery) or incompatible history.
    Only rejection scenarios close pending history; accepted/uncertain never do.
    """
    world = definition(deployment_id,case)
    root = Path(root)
    if not root.is_absolute() or root.resolve() != root:
        raise Blocked("fixed_unlinked_root_required")
    if type(initialize_catalog) is not bool:
        raise Blocked("invalid_catalog_bootstrap")
    runtime = Runtime(root,create=initialize_catalog)
    runtime.register(world)
    order=world["order_id"]
    observation=runtime.observe(order)
    store=runtime.registry._destination(order)
    original_id=order+"-original"
    ident={"operation_id":original_id,"attempt_id":order+"-original-attempt",
           "order_id":order,"shipment_version":1,"target":"A","payload":canonical(world["payload"])}
    operations=observation["operations"]
    if len(operations)>1 or (operations and any(operations[0]["binding"].get(k)!=v for k,v in ident.items())):
        raise Blocked("jury_history_already_extended_or_changed")
    created=0
    if not operations:
        snapshot=clock.authority_snapshot(observation)
        now=clock.now_us()
        expiry=min(clock.iris_utc_to_us(snapshot["deliveryDeadline"]),
                   clock.iris_utc_to_us(snapshot["inventoryUntil"]),
                   observation["definition"]["offer_until_us"])
        if now>=expiry:
            raise Blocked("jury_case_expired_no_reset")
        binding=ident|{"reserved_at":now-observation["definition"]["utc_origin_us"],
                       "valid_until":expiry-observation["definition"]["utc_origin_us"]}
        # Initial synthetic history only, not a fabricated native authority ticket.
        store.submit_realtime(binding,expected_revision=observation["facts_revision"])
        created=1
    else:
        binding=operations[0]["binding"]
    # Query the exact binding. Rejection cases may close only the pending attempt;
    # accepted/uncertain history is never closed, rewritten or resubmitted.
    if case in {"accepted", "uncertain"}:
        receipt=store.query_realtime(ident)
        expected="ACCEPTED" if case=="accepted" else "UNKNOWN"
        if (receipt["status"]!=expected or receipt["closedForever"] is not False
                or (expected=="ACCEPTED" and not receipt["reference"])):
            raise Blocked("original_history_changed_no_reset")
    else:
        receipt=store.close_realtime(binding)
        if receipt["status"]!="NOT_ACCEPTED_FINAL" or receipt["closedForever"] is not True:
            raise Blocked("original_not_finally_rejected")
    confirmed=runtime.query({"operationId":ident["operation_id"],"attemptId":ident["attempt_id"],
        "orderId":order,"shipmentVersion":1,"target":"A","payload":ident["payload"]})
    if confirmed!=receipt:
        raise Blocked("seed_readback_mismatch")
    return {"schema_version":"chronos.jury-seed.v1","status":"SYNTHETIC_HISTORY_ONLY",
            "case":case,"order_id":order,"initial_history_submissions":created,
            "recovery_submissions":0,"model_calls":0,"native_registered":False,
            "snapshot":runtime.snapshot(order),"original_receipt":confirmed}


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--deployment-id",required=True)
    p.add_argument("--case",required=True,choices=tuple(CASES))
    p.add_argument("--initialize-catalog",action="store_true",
                   help="Create a missing catalog only in an empty owned directory")
    args=p.parse_args(argv)
    try:
        identifiers(args.deployment_id,args.case)
        # Public CLI cannot choose an arbitrary destination or reset any root.
        root=Path("/durable/chronos")/args.deployment_id/"owned-destinations"
        if sys.platform!="linux":raise Blocked("run_inside_owned_linux_container")
        report=seed(root,args.deployment_id,args.case,initialize_catalog=args.initialize_catalog)
        print(json.dumps(report,sort_keys=True));return 0
    except (ValueError,OSError,sqlite3.Error) as exc:
        # This input is fixed synthetic data; do not print exception text/paths.
        code=str(exc) if isinstance(exc,Blocked) else "SEED_IO_OR_DATA_FAILURE"
        print(json.dumps({"status":"SEED_REJECTED_PARTIAL_PRESERVED","code":code,
                          "native_registered":False,"model_calls":0}));return 1


if __name__=="__main__":raise SystemExit(main())
