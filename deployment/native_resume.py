"""Explicit clean-stop resume and phased crash recovery; no automatic retry.

Native readiness is not model readiness. This command does not submit a case,
change access or replay the initial installation start. Crash recovery uses
explicit action-bound authorization and preserves uncertain lifecycle receipts.
"""
from __future__ import annotations
import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import uuid

HERE = Path(__file__).resolve().parent


def sibling(name):
    spec = importlib.util.spec_from_file_location("chronos_resume_" + name, HERE / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


native = sibling("native_install")
SCHEMA = "chronos.native-resume.v2"
RECOVERY_ACTIONS = {"recover", "resolve-recovery", "continue-recovery"}
MUTATIONS = {"resume"} | RECOVERY_ACTIONS
ACTIONS = {"inspect", "status"} | MUTATIONS
RECOVERY_PHASES = {"NONE", "RECOVER_REQUESTED", "RECOVERED_OBSERVED", "START_REQUESTED", "VERIFIED"}
STATUSES = {"REJECTED", "REJECTED_STATE_PRESERVED", "BUSY", "NOT_RESUMABLE",
            "STOPPED_RESUME_AVAILABLE", "CRASH_RECOVERY_AVAILABLE", "CURRENTLY_RUNNING", "GENERATION_ALREADY_REQUESTED",
            "REQUEST_NOT_FOUND", "RESUME_VERIFIED", "REQUESTED_OUTCOME_UNCERTAIN"}
AUTH_KEYS = ("CHRONOS_RESUME_AUTHORIZED", "CHRONOS_RECOVERY_AUTHORIZED", "CHRONOS_PROVIDER_AUTHORIZED",
             "CHRONOS_JURY_AUTHORIZED", "CHRONOS_INSTALL_APPROVED")
DIAGNOSTICS = {"NOT_ATTEMPTED", "LEGACY_RECEIPT", "START_CALL_UNCERTAIN", "DURABILITY_UNCONFIRMED",
               "READBACK_PENDING", "READBACK_TIMEOUT", "READBACK_REJECTED", "VERIFIED",
               "RECOVERY_CALL_UNCERTAIN", "RECOVERY_STATE_OBSERVED"}


def require(condition, code):
    if not condition:
        raise ValueError(code)


def matches(value, pattern):
    return type(value) is str and re.fullmatch(pattern, value) is not None


def validate(action, ident, origin, application, digest, profile, request_id="", expected_generation=""):
    native.validate(ident, origin, application, digest)
    require(type(action) is str and action in ACTIONS, "INVALID_RESUME_ACTION")
    require(matches(profile, r"[a-f0-9]{64}"), "INVALID_PROFILE_DIGEST")
    require(type(request_id) is str and type(expected_generation) is str, "INVALID_REQUEST_BINDING")
    if action == "inspect":
        require(request_id == expected_generation == "", "INSPECT_HAS_NO_REQUEST")
    else:
        require(matches(request_id, r"[a-f0-9]{32}"), "INVALID_RESUME_REQUEST_ID")
        if action in MUTATIONS:
            require(matches(expected_generation, r"[a-zA-Z0-9_.-]{1,128}"), "INVALID_EXPECTED_GENERATION")
        else:
            require(expected_generation == "", "STATUS_HAS_NO_EXPECTED_GENERATION")


def report(ident, profile, status, request_id="", expected_generation="", **values):
    return {"schema_version": SCHEMA, "deployment_id": ident, "profile_sha256": profile,
            "binding_sha256": None, "status": status, "request_id": request_id,
            "expected_generation": expected_generation, "request_state": "UNKNOWN",
            "previous_generation": "", "recorded_generation": "", "current_generation": "",
            "generation_request_id": "", "production_state": None, "runtime_state": "UNKNOWN",
            "runtime_ready": None, "web_enabled": None, "start_requested_this_call": False,
            "model_tested": False, "ready": False, "diagnostic_code": "NOT_ATTEMPTED",
            "request_kind": "none", "recovery_phase": "NONE", "recover_requested_this_call": False, **values}


def program(action, ident, origin, application, digest, profile, nonce, *, binding_sha256,
            request_id="", expected_generation=""):
    validate(action, ident, origin, application, digest, profile, request_id, expected_generation)
    require(matches(nonce, r"[a-f0-9]{32}"), "INVALID_NONCE")
    require(matches(binding_sha256, r"[a-f0-9]{64}"), "INVALID_PROVIDER_BINDING")
    args = ",".join('"' + v + '"' for v in (action, ident, origin, application, digest, profile,
                                          binding_sha256, request_id, expected_generation))
    initial = json.dumps(report(ident, profile, "REJECTED", request_id, expected_generation), separators=(",", ":"))
    # Protect loading and use of the console classes against another instance of
    # this CLI. The native provider lock still protects the lifecycle operation.
    # Other console tools do not share this lock; their failures stay uncertain.
    # The terminal accepts the structured TRY block as one input line.
    return ('set r=' + initial + ',locked=0 '
            'try { '
            'lock +^ChronosInstall("resumeConsoleLock"):0 '
            'if \'$test { set r.status="BUSY" } else { '
            'set locked=1 '
            'set sc=$System.OBJ.Load("/opt/chronos/deployment/NativeInstall.cls","ck") '
            'if $System.Status.IsOK(sc) { '
            'set sc=$System.OBJ.Load("/opt/chronos/deployment/NativeProvider.cls","ck") '
            'if $System.Status.IsOK(sc) { '
            'set sc=$System.OBJ.Load("/opt/chronos/deployment/NativeResume.cls","ck") '
            'if $System.Status.IsOK(sc) { '
            'set r=##class(%DynamicObject).%FromJSON(##class(Chronos.Deployment.NativeResume).Run(' + args + ')) } } } } '
            '} catch ex { set r.status="OUTCOME_UNCERTAIN_USE_STATUS" do r.%Set("request_state","UNKNOWN"),r.%Set("start_requested_this_call","","null"),r.%Set("recover_requested_this_call","","null") }\n'
            'if locked { zn "%SYS" lock -^ChronosInstall("resumeConsoleLock") }\n'
            'write !,"' + native.MARKER + nonce + ':",r.%ToJSON(),!\nhalt\n')


def assess(value, ident, profile, request_id="", expected_generation="", *, action=None):
    expected = report(ident, profile, "", request_id, expected_generation)
    require(type(value) is dict and set(value) == set(expected), "INVALID_RESUME_RESULT_SHAPE")
    for key in ("schema_version", "deployment_id", "profile_sha256", "request_id", "expected_generation"):
        require(type(value[key]) is str and value[key] == expected[key], "RESUME_RESULT_BINDING_MISMATCH")
    require(type(value["status"]) is str and value["status"] in STATUSES, "INVALID_RESUME_STATUS")
    require(type(value["diagnostic_code"]) is str and value["diagnostic_code"] in DIAGNOSTICS, "INVALID_RESUME_DIAGNOSTIC")
    require(value["ready"] is False and value["model_tested"] is False, "UNSUPPORTED_READINESS_CLAIM")
    require(type(value["start_requested_this_call"]) is bool, "INVALID_START_OBSERVATION")
    require(type(value["recover_requested_this_call"]) is bool, "INVALID_RECOVERY_OBSERVATION")
    require(type(value["request_kind"]) is str and value["request_kind"] in {"none", "resume", "recover"}, "INVALID_REQUEST_KIND")
    require(type(value["recovery_phase"]) is str and value["recovery_phase"] in RECOVERY_PHASES, "INVALID_RECOVERY_PHASE")
    require(type(value["request_state"]) is str and value["request_state"] in {"UNKNOWN", "ABSENT", "REQUESTED", "VERIFIED"}, "INVALID_REQUEST_STATE")
    kind, phase = value["request_kind"], value["recovery_phase"]
    if kind != "recover":
        require(phase == "NONE" and not value["recover_requested_this_call"], "UNBOUND_RECOVERY_PHASE")
    else:
        require(phase != "NONE" and value["request_state"] in {"REQUESTED", "VERIFIED"}, "RECOVERY_RECEIPT_MISSING")
    if value["request_state"] in {"REQUESTED", "VERIFIED"}:
        require(kind != "none", "REQUEST_KIND_MISSING")
    if value["start_requested_this_call"]:
        require(kind != "none" and value["request_state"] in {"REQUESTED", "VERIFIED"}, "START_RECEIPT_MISSING")
        if kind == "recover":
            require(phase in {"START_REQUESTED", "VERIFIED"}, "START_PHASE_MISSING")
    if kind == "recover" and value["request_state"] == "VERIFIED":
        require(phase == "VERIFIED", "RECOVERY_VERIFICATION_PHASE_MISSING")
    if action is not None:
        require(type(action) is str and action in ACTIONS, "INVALID_RESUME_ACTION")
        if action == "resume":
            require(kind != "recover", "CROSS_KIND_RECEIPT")
        if action in RECOVERY_ACTIONS:
            require(kind != "resume", "CROSS_KIND_RECEIPT")
        if action in {"inspect", "status", "resolve-recovery"}:
            require(not value["start_requested_this_call"] and not value["recover_requested_this_call"], "UNEXPECTED_LIFECYCLE_CALL")
        if action == "continue-recovery":
            require(not value["recover_requested_this_call"], "RECOVERY_REPLAY_FORBIDDEN")
    for key in ("runtime_ready", "web_enabled"):
        require(value[key] is None or type(value[key]) is bool, "INVALID_OBSERVATION")
    binding = value["binding_sha256"]
    require(binding is None or matches(binding, r"[a-f0-9]{64}"), "INVALID_PROVIDER_BINDING")
    for key in ("previous_generation", "recorded_generation", "current_generation"):
        require(value[key] == "" or matches(value[key], r"[a-zA-Z0-9_.-]{1,128}"), "INVALID_GENERATION")
    require(value["generation_request_id"] == "" or matches(value["generation_request_id"], r"[a-f0-9]{32}"), "INVALID_GENERATION_REQUEST")
    diagnostic = value["diagnostic_code"]
    if diagnostic == "VERIFIED":
        require(value["status"] == "RESUME_VERIFIED" and value["request_state"] == "VERIFIED", "DIAGNOSTIC_CANNOT_CLAIM_SUCCESS")
    if value["request_state"] == "VERIFIED":
        require(diagnostic in {"VERIFIED", "LEGACY_RECEIPT"}, "VERIFIED_DIAGNOSTIC_MISSING")
    if value["request_state"] == "REQUESTED":
        require(diagnostic in DIAGNOSTICS - {"VERIFIED", "NOT_ATTEMPTED"}, "PENDING_DIAGNOSTIC_MISSING")
    require(type(value["runtime_state"]) is str and value["runtime_state"] in {"UNKNOWN", "STOPPED", "RECOVERED", "RECOVERING", "FAILED"}, "INVALID_RUNTIME_STATE")
    state = value["production_state"]
    require(state is None or type(state) is int and state in {1, 2, 3, 4}, "INVALID_PRODUCTION_STATE")
    if value["status"] not in {"REJECTED", "REJECTED_STATE_PRESERVED", "BUSY"}:
        require(binding is not None, "PROVIDER_BINDING_NOT_OBSERVED")
    if value["request_state"] in {"REQUESTED", "VERIFIED"}:
        require(request_id != "" and value["previous_generation"] != "", "REQUEST_BINDING_NOT_OBSERVED")
        if expected_generation:
            require(value["previous_generation"] == expected_generation, "PREVIOUS_GENERATION_MISMATCH")
    if value["status"] == "RESUME_VERIFIED":
        require(value["request_state"] == "VERIFIED" and value["recorded_generation"] != ""
                and value["recorded_generation"] != value["previous_generation"], "RESUME_RECEIPT_MISSING")
        # Historical verification does not promise that this generation is still running.
        if value["start_requested_this_call"]:
            require(state == 1 and value["runtime_ready"] is True and value["runtime_state"] == "RECOVERED"
                    and value["current_generation"] == value["recorded_generation"], "RESUME_READBACK_MISSING")
    if value["status"] == "REQUESTED_OUTCOME_UNCERTAIN":
        require(value["request_state"] == "REQUESTED", "UNCERTAIN_REQUEST_NOT_OBSERVED")
    if value["status"] == "STOPPED_RESUME_AVAILABLE":
        require(state == 2 and value["runtime_ready"] is False and value["runtime_state"] == "STOPPED"
                and value["current_generation"] != "" and value["generation_request_id"] == "", "CLEAN_STOP_NOT_OBSERVED")
    if value["status"] == "CRASH_RECOVERY_AVAILABLE":
        require(state == 4 and value["runtime_ready"] is False and value["current_generation"] != ""
                and value["generation_request_id"] == "" and value["request_kind"] == "none", "CRASH_STATE_NOT_OBSERVED")
    if value["status"] == "CURRENTLY_RUNNING":
        require(state == 1 and value["runtime_ready"] is True and value["runtime_state"] == "RECOVERED"
                and value["current_generation"] != "", "NATIVE_READBACK_MISSING")
    if value["status"] == "GENERATION_ALREADY_REQUESTED":
        require(value["generation_request_id"] != "", "GENERATION_FENCE_NOT_OBSERVED")
    return value


def execute(action, ident, origin, application, digest, profile, *, binding_sha256,
            request_id="", expected_generation="", authorized=False, run=subprocess.run):
    validate(action, ident, origin, application, digest, profile, request_id, expected_generation)
    require(type(authorized) is bool, "INVALID_AUTHORIZATION")
    require(matches(binding_sha256, r"[a-f0-9]{64}"), "INVALID_PROVIDER_BINDING")
    if action in MUTATIONS:
        require(authorized, "EXPLICIT_RESUME_ACTION_REQUIRED")
    env = dict(os.environ)
    for key in AUTH_KEYS:
        env.pop(key, None)
    if action == "resume":
        env["CHRONOS_RESUME_AUTHORIZED"] = ":".join((ident, digest, profile, binding_sha256, request_id, expected_generation))
    elif action in RECOVERY_ACTIONS:
        env["CHRONOS_RECOVERY_AUTHORIZED"] = ":".join((action, ident, digest, profile, binding_sha256, request_id, expected_generation))
    nonce = uuid.uuid4().hex
    try:
        p = run(["iris", "session", "IRIS", "-U", "%SYS"],
                input=program(action, ident, origin, application, digest, profile, nonce,
                              binding_sha256=binding_sha256, request_id=request_id, expected_generation=expected_generation),
                text=True, capture_output=True, env=env, timeout=90, check=False)
        require(p.returncode == 0 and not p.stderr.strip(), "NATIVE_COMMAND_FAILED")
        return assess(native.parse_output(p.stdout, nonce), ident, profile, request_id, expected_generation, action=action)
    except (subprocess.TimeoutExpired, OSError, UnicodeError, ValueError):
        return report(ident, profile, "OUTCOME_UNCERTAIN_USE_STATUS", request_id, expected_generation,
                      request_state="UNKNOWN", start_requested_this_call=None, recover_requested_this_call=None)


def provider_profile(ident):
    return sibling("provider_state").status(ident)


def flow(action, ident, origin, application, digest, profile, *, request_id="", expected_generation="",
         authorize_id=None, read=provider_profile, invoke=execute):
    validate(action, ident, origin, application, digest, profile, request_id, expected_generation)
    if action in MUTATIONS:
        require(authorize_id == ident, "EXPLICIT_RESUME_ACTION_REQUIRED")
    before = read(ident)
    require(before["profile_sha256"] == profile and before["profile"]["deployment_id"] == ident,
            "PROVIDER_PROFILE_CHANGED")
    require(matches(before.get("binding_sha256"), r"[a-f0-9]{64}"), "PROVIDER_BINDING_REQUIRED")
    result = invoke(action, ident, origin, application, digest, profile, request_id=request_id,
                    expected_generation=expected_generation, binding_sha256=before["binding_sha256"], authorized=action in MUTATIONS)
    try:
        after = read(ident)
        require(after["profile_sha256"] == profile and after["profile"] == before["profile"]
                and after["binding_sha256"] == before["binding_sha256"], "PROVIDER_PROFILE_CHANGED")
    except (OSError, ValueError, sqlite3.Error, KeyError, TypeError):
        return report(ident, profile, "PROVIDER_PROFILE_CHANGED_USE_STATUS", request_id, expected_generation,
                      request_state="UNKNOWN", start_requested_this_call=None, recover_requested_this_call=None)
    if result.get("binding_sha256") is not None and result["binding_sha256"] != before["binding_sha256"]:
        return report(ident, profile, "PROVIDER_BINDING_CHANGED_USE_STATUS", request_id, expected_generation,
                      request_state="UNKNOWN", start_requested_this_call=None, recover_requested_this_call=None)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=sorted(ACTIONS))
    for arg in ("deployment-id", "origin", "application", "manifest-sha256", "profile-sha256"):
        parser.add_argument("--" + arg, required=True)
    parser.add_argument("--request-id", default="")
    parser.add_argument("--expected-generation", default="")
    parser.add_argument("--authorize-id")
    args = parser.parse_args(argv)
    try:
        inputs = (args.deployment_id, args.origin, args.application, args.manifest_sha256, args.profile_sha256)
        validate(args.action, *inputs, args.request_id, args.expected_generation)
        if args.action in MUTATIONS:
            require(args.authorize_id == args.deployment_id, "EXPLICIT_RESUME_ACTION_REQUIRED")
        require(sys.platform == "linux", "RUN_INSIDE_OWNED_LINUX_CONTAINER")
        native.verify_source(args.manifest_sha256, args.application)
        if args.action in MUTATIONS:
            require(sibling("native_health").engine()["ready"], "ENGINE_NOT_READY")
        result = flow(args.action, *inputs, request_id=args.request_id, expected_generation=args.expected_generation,
                      authorize_id=args.authorize_id)
        print(json.dumps(result, sort_keys=True, allow_nan=False))
        return 0 if result["status"] in {"RESUME_VERIFIED", "STOPPED_RESUME_AVAILABLE", "CRASH_RECOVERY_AVAILABLE", "CURRENTLY_RUNNING"} else 1
    except (OSError, ValueError, sqlite3.Error, KeyError, TypeError):
        print(json.dumps({"schema_version": SCHEMA, "status": "RESUME_COMMAND_REJECTED_STATE_PRESERVED",
                          "ready": False, "model_tested": False}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
