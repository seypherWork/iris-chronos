"""Trusted first-install provider configuration/start/status, no inference request.

Full bundle and actual immutable installed provider must match. Native code compiled
in %SYS only. Never retry an uncertain process, change accounts, reset allowances,
force a production restart or claim model readiness from native production state.
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
    spec = importlib.util.spec_from_file_location("chronos_provider_" + name, HERE / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


native = sibling("native_install")
SCHEMA = "chronos.native-provider.v2"
ACTIONS = {"configure", "start", "status"}
STATES = {"UNKNOWN", "ABSENT", "CONFIGURE_REQUESTED", "CONFIGURED", "START_REQUESTED"}
STATUSES = {"REJECTED", "REJECTED_STATE_PRESERVED", "BUSY", "MODEL_NOT_CONFIGURED",
            "CONFIGURATION_UNCERTAIN", "CONFIGURED", "START_REQUEST_UNCERTAIN", "RUNNING_NATIVE_ONLY"}


def require(condition, code):
    if not condition:
        raise ValueError(code)


def validate(action, ident, origin, application, digest, profile):
    native.validate(ident, origin, application, digest)
    require(type(action) is str and action in ACTIONS, "INVALID_PROVIDER_ACTION")
    require(type(profile) is str and re.fullmatch(r"[a-f0-9]{64}", profile), "INVALID_PROFILE_DIGEST")


def report(ident, profile, status, **values):
    return {"schema_version": SCHEMA, "status": status, "ready": False,
            "deployment_id": ident, "profile_sha256": profile, "model_configured": None,
            "native_state": "UNKNOWN", "production_state": None, "runtime_ready": None,
            "start_requested": None, "model_tested": False, "binding_sha256": None, **values}


def program(action, ident, origin, application, digest, profile, nonce, *, expected_binding=None):
    validate(action, ident, origin, application, digest, profile)
    require(type(nonce) is str and re.fullmatch(r"[a-f0-9]{32}", nonce), "INVALID_NONCE")
    require(expected_binding is None or type(expected_binding) is str and re.fullmatch(r"[a-f0-9]{64}",expected_binding), "INVALID_EXPECTED_PROVIDER_BINDING")
    if action != "status": require(expected_binding is not None,"EXPLICIT_PROVIDER_BINDING_REQUIRED")
    args = ",".join('"' + v + '"' for v in (action, ident, origin, application, digest, profile, expected_binding or ""))
    initial = json.dumps(report(ident, profile, "REJECTED"), separators=(",", ":"))
    return ('set r=' + initial + ' try { '
            'set sc=$System.OBJ.Load("/opt/chronos/deployment/NativeInstall.cls","ck") '
            'if $System.Status.IsOK(sc) { '
            'set sc=$System.OBJ.Load("/opt/chronos/deployment/NativeProvider.cls","ck") '
            'if $System.Status.IsOK(sc) { '
            'set r=##class(%DynamicObject).%FromJSON(##class(Chronos.Deployment.NativeProvider).Run(' + args + ')) } } '
            '} catch ex { set r.status="REJECTED_STATE_PRESERVED" } '
            'write !,"' + native.MARKER + nonce + ':",r.%ToJSON(),!\nhalt\n')


def assess(value, ident, profile):
    expected = report(ident, profile, "")
    require(type(value) is dict and set(value) == set(expected), "INVALID_PROVIDER_RESULT_SHAPE")
    for key in ("schema_version", "deployment_id", "profile_sha256"):
        require(type(value[key]) is str and value[key] == expected[key], "PROVIDER_RESULT_BINDING_MISMATCH")
    require(type(value["status"]) is str and value["status"] in STATUSES, "INVALID_PROVIDER_STATUS")
    require(type(value["native_state"]) is str and value["native_state"] in STATES, "INVALID_NATIVE_STATE")
    require(value["ready"] is False and value["model_tested"] is False, "UNSUPPORTED_READINESS_CLAIM")
    for key in ("model_configured", "runtime_ready", "start_requested"):
        require(value[key] is None or type(value[key]) is bool, "INVALID_OBSERVATION")
    binding = value["binding_sha256"]
    require(binding is None or type(binding) is str and re.fullmatch(r"[a-f0-9]{64}", binding), "INVALID_PROVIDER_BINDING")
    if value["status"] in {"CONFIGURED", "RUNNING_NATIVE_ONLY", "START_REQUEST_UNCERTAIN"}:
        require(binding is not None, "PROVIDER_BINDING_NOT_OBSERVED")
    state = value["production_state"]
    require(state is None or type(state) is int and state in {1, 2, 3, 4}, "INVALID_PRODUCTION_STATE")
    if value["native_state"] == "START_REQUESTED":
        require(value["start_requested"] is True, "START_FENCE_NOT_REPORTED")
    if value["status"] in {"CONFIGURED", "RUNNING_NATIVE_ONLY", "START_REQUEST_UNCERTAIN"}:
        require(value["model_configured"] is True and value["native_state"] in
                {"CONFIGURE_REQUESTED", "CONFIGURED", "START_REQUESTED"}, "MODEL_READBACK_MISSING")
    if value["status"] == "START_REQUEST_UNCERTAIN":
        require(value["native_state"] == "START_REQUESTED" and value["start_requested"] is True, "START_FENCE_NOT_REPORTED")
    if value["status"] == "RUNNING_NATIVE_ONLY":
        require(state == 1 and value["runtime_ready"] is True and value["start_requested"] is True
                and value["native_state"] == "START_REQUESTED", "NATIVE_READBACK_MISSING")
    if value["status"] == "MODEL_NOT_CONFIGURED":
        require(value["native_state"] == "ABSENT" and value["model_configured"] is False,
                "ABSENCE_NOT_VERIFIED")
    return value


def execute(action, ident, origin, application, digest, profile, *, binding_sha256=None, authorized=False, run=subprocess.run):
    validate(action, ident, origin, application, digest, profile)
    require(type(authorized) is bool, "INVALID_AUTHORIZATION")
    if action != "status":
        require(authorized, "EXPLICIT_PROVIDER_ACTION_REQUIRED")
        require(type(binding_sha256) is str and re.fullmatch(r"[a-f0-9]{64}",binding_sha256), "EXPLICIT_PROVIDER_BINDING_REQUIRED")
    env = dict(os.environ)
    for key in ("CHRONOS_PROVIDER_AUTHORIZED", "CHRONOS_JURY_AUTHORIZED", "CHRONOS_INSTALL_APPROVED"):
        env.pop(key, None)
    if authorized and action != "status":
        env["CHRONOS_PROVIDER_AUTHORIZED"] = ":".join((action, ident, digest, profile, binding_sha256))
    nonce = uuid.uuid4().hex
    try:
        p = run(["iris", "session", "IRIS", "-U", "%SYS"],
                input=program(action, ident, origin, application, digest, profile, nonce, expected_binding=binding_sha256),
                text=True, capture_output=True, env=env, timeout=90, check=False)
        require(p.returncode == 0 and not p.stderr.strip(), "NATIVE_COMMAND_FAILED")
        return assess(native.parse_output(p.stdout, nonce), ident, profile)
    except (subprocess.TimeoutExpired, OSError, UnicodeError, ValueError):
        # A disconnected/failed client does not prove that native execution stopped.
        return report(ident, profile, "OUTCOME_UNCERTAIN_USE_STATUS")


def provider_profile(ident):
    return sibling("provider_state").status(ident)


def flow(action, ident, origin, application, digest, profile, *, authorize_id=None,
         read=provider_profile, invoke=execute):
    validate(action, ident, origin, application, digest, profile)
    if action != "status":
        require(authorize_id == ident, "EXPLICIT_PROVIDER_ACTION_REQUIRED")
    before = read(ident)
    require(before["profile_sha256"] == profile and before["profile"]["deployment_id"] == ident,
            "PROVIDER_PROFILE_CHANGED")
    require(type(before.get("binding_sha256")) is str and re.fullmatch(r"[a-f0-9]{64}",before["binding_sha256"]),
            "PROVIDER_BINDING_REQUIRED")
    result = invoke(action, ident, origin, application, digest, profile,
                    binding_sha256=before["binding_sha256"], authorized=action != "status")
    # Even a successful native response is not a complete binding if the actual
    # installed provider changed while the command ran. Never undo or retry it.
    try:
        after = read(ident)
        require(after["profile_sha256"] == profile and after["profile"] == before["profile"]
                and after["binding_sha256"] == before["binding_sha256"],
                "PROVIDER_PROFILE_CHANGED")
    except (OSError, ValueError, sqlite3.Error, KeyError, TypeError):
        return report(ident, profile, "PROVIDER_PROFILE_CHANGED_USE_STATUS")
    if result.get("binding_sha256") is not None and result["binding_sha256"] != before["binding_sha256"]:
        return report(ident, profile, "PROVIDER_BINDING_CHANGED_USE_STATUS")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=sorted(ACTIONS))
    parser.add_argument("--deployment-id", required=True)
    parser.add_argument("--origin", required=True)
    parser.add_argument("--application", required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--profile-sha256", required=True)
    parser.add_argument("--authorize-id")
    args = parser.parse_args(argv)
    try:
        inputs = (args.deployment_id, args.origin, args.application, args.manifest_sha256, args.profile_sha256)
        validate(args.action, *inputs)
        if args.action != "status":
            require(args.authorize_id == args.deployment_id, "EXPLICIT_PROVIDER_ACTION_REQUIRED")
        require(sys.platform == "linux", "RUN_INSIDE_OWNED_LINUX_CONTAINER")
        native.verify_source(args.manifest_sha256, args.application)
        if args.action != "status":
            require(sibling("native_health").engine()["ready"], "ENGINE_NOT_READY")
        result = flow(args.action, *inputs, authorize_id=args.authorize_id)
        print(json.dumps(result, sort_keys=True, allow_nan=False))
        return 0 if result["status"] in {"MODEL_NOT_CONFIGURED", "CONFIGURED", "RUNNING_NATIVE_ONLY"} else 1
    except (OSError, ValueError, sqlite3.Error, KeyError, TypeError):
        print(json.dumps({"schema_version": SCHEMA, "status": "PROVIDER_COMMAND_REJECTED_STATE_PRESERVED",
                          "ready": False, "model_tested": False}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
