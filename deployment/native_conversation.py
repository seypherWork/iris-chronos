"""Verified trusted C1 configuration/status console; no inference or account edits.

Only a pinned installed bundle and a separately prepared C1 quota are accepted.
Transport errors remain uncertain. Status never grants mutation authorization.
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
    path = HERE / (name + ".py")
    if path.resolve() != path: raise ValueError("LINKED_CONVERSATION_HELPER")
    spec = importlib.util.spec_from_file_location("chronos_c1_install_" + name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


native = sibling("native_install")
SCHEMA = "chronos.native-conversation.v1"
ACTIONS = {"configure", "status"}
CONTRACTS = {"c1":"chronos.case-conversation.v1", "c2":"chronos.case-explanation-plan.v1", "c2-v2":"chronos.case-explanation-plan.v2"}
STATUSES = {"REJECTED", "REJECTED_STATE_PRESERVED", "BUSY", "MODEL_NOT_CONFIGURED",
            "CONFIGURATION_UNCERTAIN", "CONFIGURED"}


def require(condition, code):
    if not condition: raise ValueError(code)


def validate(action, ident, origin, application, digest, profile):
    native.validate(ident, origin, application, digest)
    require(type(action) is str and action in ACTIONS, "INVALID_CONVERSATION_ACTION")
    require(type(profile) is str and re.fullmatch(r"[a-f0-9]{64}", profile), "INVALID_C1_PROFILE_DIGEST")


def report(ident, digest, profile, status, **values):
    return {"schema_version": SCHEMA, "status": status, "ready": False, "deployment_id": ident,
            "bundle_sha256": digest, "profile_sha256": profile, "model_configured": None,
            "native_state": "UNKNOWN", "production_state": None, "e1_config_unchanged": None,
            "model_tested": False, **values}


def program(action, ident, origin, application, digest, profile, nonce, contract="c1"):
    validate(action, ident, origin, application, digest, profile)
    require(type(nonce) is str and re.fullmatch(r"[a-f0-9]{32}", nonce), "INVALID_NONCE")
    require(type(contract) is str and contract in CONTRACTS, "INVALID_CONVERSATION_CONTRACT")
    args = ",".join('"' + v + '"' for v in (action, ident, origin, application, digest, profile, CONTRACTS[contract]))
    initial = json.dumps(report(ident, digest, profile, "REJECTED"), separators=(",", ":"))
    return ('set r=' + initial + ' try { '
            'set sc=$System.OBJ.Load("/opt/chronos/deployment/NativeInstall.cls","ck") '
            'if $System.Status.IsOK(sc) { '
            'set sc=$System.OBJ.Load("/opt/chronos/deployment/NativeConversation.cls","ck") '
            'if $System.Status.IsOK(sc) { '
            'set r=##class(%DynamicObject).%FromJSON(##class(Chronos.Deployment.NativeConversation).Run(' + args + ')) } } '
            '} catch ex { set r.status="REJECTED_STATE_PRESERVED" } '
            'write !,"' + native.MARKER + nonce + ':",r.%ToJSON(),!\nhalt\n')


def assess(value, ident, digest, profile):
    expected = report(ident, digest, profile, "")
    require(type(value) is dict and set(value) == set(expected), "INVALID_C1_RESULT_SHAPE")
    for key in ("schema_version", "deployment_id", "bundle_sha256", "profile_sha256"):
        require(type(value[key]) is str and value[key] == expected[key], "C1_RESULT_BINDING_CHANGED")
    require(type(value["status"]) is str and value["status"] in STATUSES, "INVALID_C1_STATUS")
    require(type(value["native_state"]) is str and value["native_state"] in
            {"UNKNOWN", "ABSENT", "CONFIGURE_REQUESTED", "CONFIGURED"}, "INVALID_C1_NATIVE_STATE")
    require(value["ready"] is False and value["model_tested"] is False, "UNSUPPORTED_READINESS_CLAIM")
    for key in ("model_configured", "e1_config_unchanged"):
        require(value[key] is None or type(value[key]) is bool, "INVALID_C1_OBSERVATION")
    state = value["production_state"]
    require(state is None or type(state) is int and state in {1, 2, 3, 4}, "INVALID_PRODUCTION_STATE")
    if value["status"] in {"CONFIGURED", "MODEL_NOT_CONFIGURED", "CONFIGURATION_UNCERTAIN"}:
        require(state is not None and value["e1_config_unchanged"] is True, "C1_PRESERVATION_UNVERIFIED")
    if value["status"] == "CONFIGURED":
        require(value["model_configured"] is True and value["native_state"] in
                {"CONFIGURE_REQUESTED", "CONFIGURED"}, "C1_READBACK_MISSING")
    elif value["status"] == "MODEL_NOT_CONFIGURED":
        require(value["model_configured"] is False and value["native_state"] == "ABSENT", "C1_ABSENCE_UNVERIFIED")
    elif value["status"] == "CONFIGURATION_UNCERTAIN":
        require(value["model_configured"] is False and value["native_state"] in
                {"CONFIGURE_REQUESTED", "CONFIGURED"}, "C1_UNCERTAINTY_UNVERIFIED")
    return value


def execute(action, ident, origin, application, digest, profile, *, authorized=False,
            run=subprocess.run, verify=native.verify_source, contract="c1"):
    validate(action, ident, origin, application, digest, profile)
    require(type(contract) is str and contract in CONTRACTS, "INVALID_CONVERSATION_CONTRACT")
    require(type(authorized) is bool, "INVALID_AUTHORIZATION")
    if action == "configure": require(authorized, "EXPLICIT_CONVERSATION_ACTION_REQUIRED")
    # Verification occurs even when called as a function, before compiling any
    # helper. A source failure is a known refusal, not an uncertain native call.
    verify(digest, application)
    env = {key: value for key, value in os.environ.items()
           if not (key.startswith("CHRONOS_") and (key.endswith("_AUTHORIZED") or key.endswith("_APPROVED")))}
    if action == "configure":
        env["CHRONOS_CONVERSATION_AUTHORIZED"] = ":".join((action, ident, digest, profile)) + (":"+CONTRACTS[contract] if contract!="c1" else "")
    nonce = uuid.uuid4().hex
    try:
        p = run(["iris", "session", "IRIS", "-U", "%SYS"],
                input=program(action, ident, origin, application, digest, profile, nonce, contract),
                text=True, capture_output=True, env=env, timeout=90, check=False)
        require(p.returncode == 0 and not p.stderr.strip(), "NATIVE_COMMAND_FAILED")
        return assess(native.parse_output(p.stdout, nonce), ident, digest, profile)
    except (subprocess.TimeoutExpired, OSError, UnicodeError, ValueError):
        return report(ident, digest, profile, "OUTCOME_UNCERTAIN_USE_STATUS")


def provider_profile(ident):
    return sibling("conversation_provider").status(ident)


def flow(action, ident, origin, application, digest, profile, *, authorize_id=None,
         read=provider_profile, invoke=execute, contract="c1"):
    validate(action, ident, origin, application, digest, profile)
    if action == "configure": require(authorize_id == ident, "EXPLICIT_CONVERSATION_ACTION_REQUIRED")
    require(type(contract) is str and contract in CONTRACTS, "INVALID_CONVERSATION_CONTRACT")
    before = read(ident)
    # Older C1 callers retain their default; C2 is never inferred from a profile.
    require(before["profile"].get("response_contract", CONTRACTS["c1"]) == CONTRACTS[contract], "CONVERSATION_CONTRACT_CHANGED")
    require(before["profile_sha256"] == profile and before["profile"]["deployment_id"] == ident,
            "C1_PROFILE_CHANGED")
    # Freeze the fingerprint before invoking; changing counts are not profile drift.
    pin = json.dumps(before["profile"], sort_keys=True, separators=(",", ":"), allow_nan=False)
    options={"contract":contract} if contract!="c1" else {}
    result = invoke(action, ident, origin, application, digest, profile, authorized=action == "configure", **options)
    try:
        after = read(ident)
        require(after["profile_sha256"] == profile and
                json.dumps(after["profile"], sort_keys=True, separators=(",", ":"), allow_nan=False) == pin,
                "C1_PROFILE_CHANGED")
    except (OSError, ValueError, sqlite3.Error, KeyError, TypeError):
        return report(ident, digest, profile, "C1_PROFILE_CHANGED_USE_STATUS")
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
    parser.add_argument("--contract",choices=sorted(CONTRACTS),default="c1")
    args = parser.parse_args(argv)
    try:
        inputs = (args.deployment_id, args.origin, args.application, args.manifest_sha256, args.profile_sha256)
        validate(args.action, *inputs)
        if args.action == "configure": require(args.authorize_id == args.deployment_id, "EXPLICIT_CONVERSATION_ACTION_REQUIRED")
        require(sys.platform == "linux", "RUN_INSIDE_OWNED_LINUX_CONTAINER")
        result = flow(args.action, *inputs, authorize_id=args.authorize_id, contract=args.contract)
        print(json.dumps(result, sort_keys=True, allow_nan=False))
        return 0 if result["status"] in {"MODEL_NOT_CONFIGURED", "CONFIGURED"} else 1
    except (OSError, ValueError, sqlite3.Error, KeyError, TypeError):
        print(json.dumps({"schema_version": SCHEMA, "status": "C1_COMMAND_REJECTED_STATE_PRESERVED",
                          "ready": False, "model_tested": False}))
        return 1


if __name__ == "__main__": raise SystemExit(main())
