"""Experimental trusted console route: prepare -> propose once -> status.

Requires a natively installed matching bundle. No account/port/provider setup,
approval or recovery submission. Native compilation and end-to-end proof pending.
"""
from __future__ import annotations
import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sqlite3
import sys
import uuid

HERE = Path(__file__).resolve().parent
def sibling(name):
    path = HERE / (name + ".py")
    spec = importlib.util.spec_from_file_location("chronos_jury_" + name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

native = sibling("native_install")
SCHEMA = "chronos.jury-case.v1"
CASES = {"earliest", "economy", "ambiguous", "queue_inventory", "accepted", "uncertain"}
ACTIONS = {"inspect", "prepare", "propose", "status"}
STATUSES = {"REJECTED", "BOUND", "BUSY", "RUNTIME_NOT_READY", "DECISION_AVAILABLE",
            "REQUEST_OUTCOME_UNCERTAIN", "PREPARED", "PREPARATION_PARTIAL",
            "NOT_PREPARED", "REJECTED_STATE_PRESERVED"}
NATIVE_STATES = {"ABSENT", "PREPARING", "PREPARED", "REQUEST_ISSUED"}
DECISION_STATES = {"NOT_FOUND", "PREPARED", "IN_FLIGHT", "VALIDATING", "UNCERTAIN",
                   "UNCERTAIN_VALIDATION", "COMPLETED"}

class ScenarioError(ValueError):
    pass

def require(condition, code):
    if not condition:
        raise ScenarioError(code)

def validate(action, ident, case, origin, application, digest):
    native.validate(ident, origin, application, digest)
    require(type(action) is str and action in ACTIONS, "INVALID_JURY_ACTION")
    require(type(case) is str and case in CASES, "INVALID_JURY_CASE")

def report(ident, case, status, **values):
    order = "jury-" + ident + "-" + case
    return {"schema_version":SCHEMA, "status":status, "ready":False,
            "deployment_id":ident, "case":case, "order_id":order, "decision_id":order,
            "runtime_ready":None, "native_state":"ABSENT", "decision_state":"NOT_FOUND",
            "deterministic_code":"",
            "workflow_requests":0, "inference_may_have_run":False,
            "dispatch_authorized":False, "recovery_submissions":0, **values}

def program(action, ident, case, origin, application, digest, nonce):
    validate(action, ident, case, origin, application, digest)
    require(type(nonce) is str and re.fullmatch("[a-f0-9]{32}", nonce), "INVALID_NONCE")
    args = ",".join('"'+v+'"' for v in (action, ident, case, origin, application, digest))
    initial = json.dumps(report(ident,case,"REJECTED",inference_may_have_run=True),separators=(",",":"))
    return ('set r='+initial+' try { '
            'set sc=$System.OBJ.Load("/opt/chronos/deployment/NativeInstall.cls","ck") '
            'if $System.Status.IsOK(sc) { '
            'set sc=$System.OBJ.Load("/opt/chronos/deployment/NativeScenario.cls","ck") '
            'if $System.Status.IsOK(sc) { '
            'set r=##class(%DynamicObject).%FromJSON(##class(Chronos.Deployment.NativeScenario).Run('+args+')) } } '
            '} catch ex { set r.status="REJECTED_STATE_PRESERVED" do r.%Set("inference_may_have_run",1,"boolean") } '
            'write !,"'+native.MARKER+nonce+':",r.%ToJSON(),!\nhalt\n')

def assess(value, action, ident, case):
    expected = report(ident, case, "")
    require(type(value) is dict and set(value) == set(expected), "INVALID_JURY_RESULT_SHAPE")
    for key in ("schema_version","deployment_id","case","order_id","decision_id"):
        require(value[key] == expected[key] and type(value[key]) is str, "JURY_RESULT_BINDING_MISMATCH")
    require(type(value["status"]) is str and value["status"] in STATUSES, "INVALID_JURY_STATUS")
    require(type(value["native_state"]) is str and value["native_state"] in NATIVE_STATES, "INVALID_JURY_STATE")
    require(type(value["decision_state"]) is str and value["decision_state"] in DECISION_STATES, "INVALID_DECISION_STATE")
    for key in ("ready","dispatch_authorized"):
        require(value[key] is False, "UNSUPPORTED_AUTHORITY_CLAIM")
    require(type(value["recovery_submissions"]) is int and value["recovery_submissions"] == 0, "UNEXPECTED_RECOVERY")
    require(type(value["workflow_requests"]) is int and value["workflow_requests"] in {0,1}, "INVALID_REQUEST_COUNT")
    require(value["runtime_ready"] is None or type(value["runtime_ready"]) is bool, "INVALID_RUNTIME_READINESS")
    require(type(value["inference_may_have_run"]) is bool, "INVALID_INFERENCE_STATE")
    deterministic=value["deterministic_code"]
    require(type(deterministic) is str and deterministic in {"", "EXISTING_ACCEPTANCE", "ACCEPTANCE_UNRESOLVED"}, "INVALID_DETERMINISTIC_CODE")
    if deterministic:
        require((value["status"]=="DECISION_AVAILABLE" or (action=="inspect" and value["status"]=="BOUND")) and value["decision_state"]=="COMPLETED"
                and value["native_state"]=="REQUEST_ISSUED" and not value["inference_may_have_run"], "INVALID_DETERMINISTIC_OBSERVATION")
    if value["workflow_requests"]:
        require(action == "propose" and value["native_state"] == "REQUEST_ISSUED" and
                (value["inference_may_have_run"] or deterministic), "UNEXPECTED_WORKFLOW_REQUEST")
    if value["status"] == "DECISION_AVAILABLE":
        require(value["decision_state"] != "NOT_FOUND", "DECISION_RESULT_INCONSISTENT")
    if value["status"] == "PREPARED":
        require(value["native_state"] == "PREPARED", "PREPARATION_RESULT_INCONSISTENT")
    if value["native_state"] == "REQUEST_ISSUED":
        require(value["inference_may_have_run"] or deterministic, "MISSING_INFERENCE_UNCERTAINTY")
    return value

def execute(action, ident, case, origin, application, digest, *, authorized=False,
            run=subprocess.run):
    validate(action, ident, case, origin, application, digest)
    require(type(authorized) is bool, "INVALID_AUTHORIZATION")
    if action in {"prepare", "propose"}:
        require(authorized, "EXPLICIT_ACTION_AUTHORIZATION_REQUIRED")
    env = dict(os.environ)
    env.pop("CHRONOS_JURY_AUTHORIZED",None)
    env.pop("CHRONOS_INSTALL_APPROVED",None)
    if authorized and action in {"prepare","propose"}:
        env["CHRONOS_JURY_AUTHORIZED"] = ":".join((action,ident,case,digest))
    nonce=uuid.uuid4().hex
    text=program(action,ident,case,origin,application,digest,nonce)
    try:
        p=run(["iris","session","IRIS","-U","%SYS"],input=text,text=True,
              capture_output=True,env=env,timeout=60,check=False)
        require(p.returncode==0 and not p.stderr.strip(),"NATIVE_COMMAND_FAILED")
        return assess(native.parse_output(p.stdout,nonce),action,ident,case)
    except (subprocess.TimeoutExpired,OSError,UnicodeError,ValueError):
        # Never retry a subprocess: an unobserved call may already have committed.
        # The stable decision_id is supplied even if the native reply is unusable.
        return report(ident,case,"OUTCOME_UNCERTAIN_USE_STATUS",
                      workflow_requests=None,inference_may_have_run=True)

def owned_seed(ident, case):
    seed=sibling("first_case")
    root=Path("/durable/chronos")/ident/"owned-destinations"
    return seed.seed(root,ident,case,initialize_catalog=False)

def flow(action, ident, case, origin, application, digest, *,
         authorize_prepare_id=None, authorize_model_id=None,
         invoke=execute, seed=owned_seed):
    validate(action,ident,case,origin,application,digest)
    args=(ident,case,origin,application,digest)
    if action == "prepare":
        require(authorize_prepare_id==ident,"EXPLICIT_PREPARATION_REQUIRED")
        checked=invoke("inspect",*args)
        if checked["status"]!="BOUND":
            return checked
        # Existing native preparation/request is observed without reseeding.
        if checked["native_state"] in {"PREPARED","REQUEST_ISSUED"}:
            return invoke("status",*args)
        require(checked["runtime_ready"],"RUNTIME_NOT_READY")
        prepared=seed(ident,case)
        require(type(prepared) is dict and prepared.get("status")=="SYNTHETIC_HISTORY_ONLY" and
                prepared.get("order_id")=="jury-"+ident+"-"+case and
                prepared.get("recovery_submissions")==0 and prepared.get("model_calls")==0,
                "SEED_RESULT_UNVERIFIED")
        return invoke("prepare",*args,authorized=True)
    if action == "propose":
        require(authorize_model_id==ident,"EXPLICIT_MODEL_REQUEST_REQUIRED")
        return invoke("propose",*args,authorized=True)
    return invoke(action,*args)

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("action",choices=sorted(ACTIONS))
    p.add_argument("--deployment-id",required=True)
    p.add_argument("--case",required=True,choices=sorted(CASES))
    p.add_argument("--origin",required=True)
    p.add_argument("--application",required=True)
    p.add_argument("--manifest-sha256",required=True)
    p.add_argument("--authorize-prepare-id")
    p.add_argument("--authorize-model-id")
    args=p.parse_args(argv)
    try:
        validate(args.action,args.deployment_id,args.case,args.origin,args.application,args.manifest_sha256)
        require(sys.platform=="linux","RUN_INSIDE_OWNED_LINUX_CONTAINER")
        native.verify_source(args.manifest_sha256,args.application)
        if args.action in {"prepare","propose"}:
            health=sibling("native_health").engine()
            require(health["ready"],"ENGINE_NOT_READY")
        value=flow(args.action,args.deployment_id,args.case,args.origin,args.application,args.manifest_sha256,
                   authorize_prepare_id=args.authorize_prepare_id,authorize_model_id=args.authorize_model_id)
        print(json.dumps(value,sort_keys=True,allow_nan=False))
        return 0 if value["status"] in {"BOUND","PREPARED","DECISION_AVAILABLE","NOT_PREPARED"} else 1
    except (OSError,ValueError,sqlite3.Error):
        # Do not print exception arguments, raw provider responses or private data.
        print(json.dumps({"schema_version":SCHEMA,"status":"JURY_COMMAND_REJECTED_STATE_PRESERVED",
                          "ready":False,"dispatch_authorized":False}))
        return 1

if __name__=="__main__":
    raise SystemExit(main())
