"""Verified trusted C1 configuration/status console; no inference or account edits.

Only a pinned installed bundle and a separately prepared C1 quota are accepted.
Transport errors remain uncertain. Status never grants mutation authorization.
"""
from __future__ import annotations
import argparse
from hashlib import sha256
import importlib.util
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import subprocess
import sys
import uuid

HERE = Path(__file__).resolve().parent
CONVERSATION_RUNTIME = Path("/opt/chronos/conversation-runtime")


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


def directory(path):
    info = path.lstat()
    require(stat.S_ISDIR(info.st_mode) and not stat.S_ISLNK(info.st_mode)
            and not getattr(info, "st_file_attributes", 0) & 0x400, "LINKED_CONVERSATION_RUNTIME")


def recorded_profile(value, ident):
    """Validate a bounded status result; this does not assert model inference."""
    fields = {"schema_version", "status", "mode", "ready", "model_tested", "fresh_inference",
              "profile", "profile_sha256", "binding_sha256", "allowance", "native_configuration"}
    require(type(value) is dict and set(value) == fields and
            value["schema_version"] == "chronos.fixture-provider.v1" and value["status"] == "CONFIGURED_NOT_PROBED"
            and value["mode"] == "RECORDED_FIXTURE" and value["ready"] is False and
            value["model_tested"] is False and value["fresh_inference"] is False, "INVALID_RECORDED_STATUS")
    profile = value["profile"]
    profile_fields = {"version", "deployment_id", "provider", "model", "schema_sha256", "request_limit",
                      "local_port", "reasoning_effort", "response_contract", "replay_corpus_sha256", "replay_fixture_sha256"}
    require(type(profile) is dict and set(profile) == profile_fields and type(profile["version"]) is int
            and profile["version"] == 6 and profile["deployment_id"] == ident and profile["provider"] == "recorded-fixture"
            and profile["model"] == "chronos-recorded-fixture-v1" and profile["local_port"] is None
            and profile["reasoning_effort"] == "none" and profile["response_contract"] == CONTRACTS["c2-v2"]
            and type(profile["request_limit"]) is int and 1 <= profile["request_limit"] <= 1000,
            "RECORDED_CONVERSATION_PROFILE_REQUIRED")
    for key in ("schema_sha256", "replay_corpus_sha256", "replay_fixture_sha256"):
        require(type(profile[key]) is str and re.fullmatch(r"[a-f0-9]{64}", profile[key]), "INVALID_RECORDED_PROFILE_HASH")
    canonical = json.dumps(profile, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("ascii")
    digest = sha256(canonical).hexdigest()
    require(value["profile_sha256"] == value["binding_sha256"] == digest, "RECORDED_PROFILE_BINDING_CHANGED")
    require(type(value["allowance"]) is dict and value["allowance"].get("profile_sha256") == digest,
            "RECORDED_ALLOWANCE_BINDING_CHANGED")
    expected = {"baseURL": "http://127.0.0.1:11514/v1/", "model": profile["model"], "profileSha256": digest,
                "reasoningEffort": "none", "contract": CONTRACTS["c2-v2"], "executionMode": "RECORDED_FIXTURE",
                "replayCorpusSha256": profile["replay_corpus_sha256"], "replayFixtureSha256": profile["replay_fixture_sha256"]}
    require(value["native_configuration"] == expected, "RECORDED_NATIVE_CONFIGURATION_CHANGED")
    return value


def provider_profile(ident, *, run=subprocess.run):
    require(type(ident) is str and re.fullmatch(r"[a-f0-9]{32}", ident), "INVALID_DEPLOYMENT_ID")
    root = CONVERSATION_RUNTIME
    for parent in reversed((root, *root.parents)):
        directory(parent)
    names = {path.name for path in root.iterdir()}
    require(names in ({"conversation-provider"}, {"fixture-conversation-provider"}),
            "EXACTLY_ONE_OWNED_CONVERSATION_PROVIDER_REQUIRED")
    directory(root / next(iter(names)))
    if names == {"conversation-provider"}:
        return sibling("conversation_provider").status(ident)
    # Use a separate interpreter: replay imports must never reuse another
    # installation's modules in a shared Embedded Python process.
    helper = HERE / "replay_provider.py"
    require(helper.resolve() == helper, "LINKED_CONVERSATION_HELPER")
    try:
        output = run(["/usr/bin/python3", "-B", str(helper), "status", "--deployment-id", ident,
                      "--contract", "c2-v2", "--runtime", str(root)], capture_output=True, timeout=10, check=False)
    except (OSError, subprocess.TimeoutExpired):
        raise ValueError("RECORDED_PROVIDER_UNAVAILABLE") from None
    require(output.returncode == 0 and type(output.stdout) in (bytes, str) and len(output.stdout) <= 16384
            and type(output.stderr) in (bytes, str) and not output.stderr.strip(), "RECORDED_PROVIDER_UNAVAILABLE")
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "DUPLICATE_RECORDED_STATUS_FIELD")
            result[key] = value
        return result
    def invalid(_):
        raise ValueError("INVALID_RECORDED_STATUS_JSON")
    value = json.loads(output.stdout, object_pairs_hook=pairs, parse_constant=invalid)
    return recorded_profile(value, ident)


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
