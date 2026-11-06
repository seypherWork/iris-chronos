"""Trusted console status/open/close for the installed Chronos web route.

Never changes accounts/passwords, provider allowance, ports or business state.
A request ID fences one activation attempt; uncertainty is read, never retried.
"""
from __future__ import annotations
import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import uuid

HERE = Path(__file__).resolve().parent


def sibling(name):
    spec = importlib.util.spec_from_file_location("chronos_web_" + name, HERE / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


native = sibling("native_install")
SCHEMA = "chronos.native-web.v1"
ACTIONS = {"status", "enable", "disable"}
STATUSES = {"REJECTED", "REJECTED_STATE_PRESERVED", "BUSY", "ENABLE_PREREQUISITES_NOT_MET",
            "WEB_ENABLED_LOGIN_UNVERIFIED", "WEB_DISABLED", "REQUEST_UNCERTAIN_USE_STATUS",
            "STATE_CHANGED_SINCE_REQUEST"}
STATES = {"UNKNOWN", "ABSENT", "REQUESTED", "VERIFIED"}


def require(value, code):
    if not value:
        raise ValueError(code)


def validate(action, ident, origin, application, digest, profile, request_id):
    native.validate(ident, origin, application, digest)
    require(type(action) is str and action in ACTIONS, "INVALID_WEB_ACTION")
    for value, size in ((profile, 64), (request_id, 32)):
        require(type(value) is str and re.fullmatch(r"[a-f0-9]{" + str(size) + r"}", value),
                "INVALID_WEB_BINDING")


def report(ident, profile, request_id, status, **values):
    return {"schema_version": SCHEMA, "status": status, "ready": False,
            "deployment_id": ident, "profile_sha256": profile, "request_id": request_id,
            "web_enabled": None, "policy_verified": None, "identity_prepared": None,
            "native_ready": None, "mutation_requested": None, "request_state": "UNKNOWN",
            "login_tested": False, **values}


def program(action, ident, origin, application, digest, profile, request_id, nonce):
    validate(action, ident, origin, application, digest, profile, request_id)
    require(type(nonce) is str and re.fullmatch(r"[a-f0-9]{32}", nonce), "INVALID_NONCE")
    args = ",".join('"' + v + '"' for v in (action, ident, origin, application, digest, profile, request_id))
    initial = json.dumps(report(ident, profile, request_id, "REJECTED"), separators=(",", ":"))
    return ('set r=' + initial + ' try { '
            'set sc=$System.OBJ.Load("/opt/chronos/deployment/NativeInstall.cls","ck") '
            'if $System.Status.IsOK(sc) { '
            'set sc=$System.OBJ.Load("/opt/chronos/deployment/NativeProvider.cls","ck") '
            'if $System.Status.IsOK(sc) { '
            'set sc=$System.OBJ.Load("/opt/chronos/deployment/NativeWeb.cls","ck") '
            'if $System.Status.IsOK(sc) { '
            'set r=##class(%DynamicObject).%FromJSON(##class(Chronos.Deployment.NativeWeb).Run(' + args + ')) } } } '
            '} catch ex { set r.status="REJECTED_STATE_PRESERVED" } '
            'write !,"' + native.MARKER + nonce + ':",r.%ToJSON(),!\nhalt\n')


def assess(value, ident, profile, request_id, action="status"):
    expected = report(ident, profile, request_id, "")
    require(type(value) is dict and set(value) == set(expected), "INVALID_WEB_RESULT_SHAPE")
    for key in ("schema_version", "deployment_id", "profile_sha256", "request_id"):
        require(type(value[key]) is str and value[key] == expected[key], "WEB_RESULT_BINDING_MISMATCH")
    require(type(value["status"]) is str and value["status"] in STATUSES, "INVALID_WEB_STATUS")
    require(type(value["request_state"]) is str and value["request_state"] in STATES, "INVALID_REQUEST_STATE")
    require(value["ready"] is False and value["login_tested"] is False, "UNSUPPORTED_READINESS_CLAIM")
    for key in ("web_enabled", "policy_verified", "identity_prepared", "native_ready"):
        require(value[key] is None or type(value[key]) is bool, "INVALID_OBSERVATION")
    require(value["mutation_requested"] is None or type(value["mutation_requested"]) is bool,
            "INVALID_MUTATION_OBSERVATION")
    if value["request_state"] == "UNKNOWN":
        require(value["mutation_requested"] is None, "UNKNOWN_MUTATION_MUST_BE_NULL")
    if value["request_state"] in {"REQUESTED", "VERIFIED"}:
        require(value["mutation_requested"] is True, "MUTATION_FENCE_NOT_REPORTED")
    if value["request_state"] == "ABSENT":
        require(value["mutation_requested"] is False, "INVALID_ABSENCE_CLAIM")
    if value["status"] == "WEB_ENABLED_LOGIN_UNVERIFIED":
        require(value["web_enabled"] is True and value["policy_verified"] is True,
                "WEB_OPEN_READBACK_MISSING")
    if value["status"] == "WEB_DISABLED":
        require(value["web_enabled"] is False, "WEB_CLOSE_READBACK_MISSING")
    if value["status"] == "REQUEST_UNCERTAIN_USE_STATUS":
        require(value["request_state"] == "REQUESTED", "REQUEST_FENCE_MISSING")
    if value["status"] == "STATE_CHANGED_SINCE_REQUEST":
        require(value["request_state"] == "VERIFIED", "PRIOR_VERIFIED_REQUEST_MISSING")
    if action != "status" and value["status"] in {"WEB_ENABLED_LOGIN_UNVERIFIED", "WEB_DISABLED"}:
        expected_status = "WEB_ENABLED_LOGIN_UNVERIFIED" if action == "enable" else "WEB_DISABLED"
        require(value["status"] == expected_status and value["request_state"] == "VERIFIED"
                and value["mutation_requested"] is True, "ACTION_READBACK_MISMATCH")
        if action == "enable":
            require(value["identity_prepared"] is True and value["native_ready"] is True,
                    "ACTIVATION_PREREQUISITES_NOT_VERIFIED")
    return value


def execute(action, ident, origin, application, digest, profile, request_id, *,
            authorized=False, run=subprocess.run):
    validate(action, ident, origin, application, digest, profile, request_id)
    require(type(authorized) is bool, "INVALID_AUTHORIZATION")
    if action != "status":
        require(authorized, "EXPLICIT_WEB_ACTION_REQUIRED")
    env = dict(os.environ)
    # A command can only carry its own exact action grant.
    for key in ("CHRONOS_WEB_AUTHORIZED", "CHRONOS_PROVIDER_AUTHORIZED",
                "CHRONOS_JURY_AUTHORIZED", "CHRONOS_INSTALL_APPROVED"):
        env.pop(key, None)
    if action != "status":
        env["CHRONOS_WEB_AUTHORIZED"] = ":".join((action, ident, digest, profile, request_id))
    nonce = uuid.uuid4().hex
    try:
        p = run(["iris", "session", "IRIS", "-U", "%SYS"],
                input=program(action, ident, origin, application, digest, profile, request_id, nonce),
                text=True, capture_output=True, env=env, timeout=90, check=False)
        require(p.returncode == 0 and not p.stderr.strip(), "NATIVE_COMMAND_FAILED")
        return assess(native.parse_output(p.stdout, nonce), ident, profile, request_id, action)
    except (subprocess.TimeoutExpired, OSError, UnicodeError, ValueError):
        # Process interruption is not rollback; keep its ID and never call again.
        return report(ident, profile, request_id, "OUTCOME_UNCERTAIN_USE_STATUS", mutation_requested=None)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("action", choices=sorted(ACTIONS))
    for name in ("deployment-id", "origin", "application", "manifest-sha256", "profile-sha256"):
        p.add_argument("--" + name, required=True)
    p.add_argument("--request-id", help="Reuse the printed ID only to inspect the original operation.")
    p.add_argument("--authorize-id")
    args = p.parse_args(argv)
    request_id = args.request_id if args.request_id is not None else uuid.uuid4().hex
    try:
        inputs = (args.deployment_id, args.origin, args.application, args.manifest_sha256,
                  args.profile_sha256, request_id)
        validate(args.action, *inputs)
        if args.action != "status":
            require(args.authorize_id == args.deployment_id, "EXPLICIT_WEB_ACTION_REQUIRED")
        require(sys.platform == "linux", "RUN_INSIDE_OWNED_LINUX_CONTAINER")
        native.verify_source(args.manifest_sha256, args.application)
        # Closing/status must remain possible when the model/engine health is bad.
        if args.action == "enable":
            require(sibling("native_health").engine()["ready"], "ENGINE_NOT_READY")
        if args.action != "status":
            # Flush the non-secret recovery ID BEFORE the one native invocation.
            print(json.dumps({"schema_version": SCHEMA, "status": "REQUEST_ID_PREPARED",
                              "request_id": request_id, "action": args.action,
                              "mutation_sent": False}), flush=True)
        result = execute(args.action, *inputs, authorized=args.action != "status")
        print(json.dumps(result, sort_keys=True, allow_nan=False))
        return 0 if result["status"] in {"WEB_ENABLED_LOGIN_UNVERIFIED", "WEB_DISABLED"} else 1
    except (OSError, ValueError, KeyError, TypeError):
        # No exception text, user properties, credentials or raw native output.
        print(json.dumps({"schema_version": SCHEMA, "status": "WEB_COMMAND_REJECTED_STATE_PRESERVED",
                          "ready": False, "login_tested": False, "request_id": request_id
                          if type(request_id) is str and re.fullmatch(r"[a-f0-9]{32}", request_id) else None}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
