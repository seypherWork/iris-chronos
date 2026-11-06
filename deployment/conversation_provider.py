"""Separate local C1/C2 profile and durable quota. No service or model startup.

Use a dedicated empty conversation runtime, never the E1 guard runtime. Restart
uses status/open only; prepare never reuses or repairs any existing state.
"""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sqlite3

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("chronos_conversation_common", HERE / "local_provider.py")
common = importlib.util.module_from_spec(spec)
spec.loader.exec_module(common)
Profile, Allowance = common.Profile, common.Allowance
require, canonical, plain, identity = common.require, common.canonical, common.plain, common.identity
RUNTIME = Path("/opt/chronos/conversation-runtime")
CONTRACT = "chronos.case-conversation.v1"
PLAN_CONTRACT = "chronos.case-explanation-plan.v1"
PLAN_V2_CONTRACT = "chronos.case-explanation-plan.v2"
CONTRACTS = {CONTRACT:(4,"conversation-schema.json"),PLAN_CONTRACT:(5,"conversation-plan-schema.json"),
             PLAN_V2_CONTRACT:(6,"conversation-plan-v2-schema.json")}
CLI_CONTRACTS = {'c1':CONTRACT,'c2':PLAN_CONTRACT,'c2-v2':PLAN_V2_CONTRACT}
LISTEN_PORT = 11514


def location(runtime):
    runtime = Path(runtime)
    require(runtime.is_absolute() and ".." not in runtime.parts, "INVALID_RUNTIME_PATH")
    for parent in reversed((runtime, *runtime.parents)):
        plain(parent, directory=True)
    return runtime / "conversation-provider"


def schema_digest(contract=CONTRACT):
    require(type(contract) is str and contract in CONTRACTS,"INVALID_CONVERSATION_CONTRACT")
    schema = json.loads((common.TRANSPORT / CONTRACTS[contract][1]).read_bytes())
    require(schema["properties"]["schema"]["enum"] == [contract], "WRONG_SCHEMA")
    return hashlib.sha256(canonical(schema)).hexdigest()


def validate(profile, ident):
    identity(ident)
    require(profile.deployment_id == ident, "DEPLOYMENT_MISMATCH")
    require(profile.response_contract in CONTRACTS and profile.version == CONTRACTS[profile.response_contract][0]
            and profile.provider == "ollama" and profile.local_port == 11434, "LOCAL_CONVERSATION_PROFILE_REQUIRED")
    require(profile.schema_sha256 == schema_digest(profile.response_contract), "PROFILE_SCHEMA_MISMATCH")


def read_profile(area, ident):
    common.profile_module.check_conversation_state(area)
    with (area / "profile.json").open("rb") as stream:
        profile = Profile.parse(stream.read(4097))
    validate(profile, ident)
    plain(area / "allowance.sqlite")
    return profile


def status(ident, *, runtime=RUNTIME):
    identity(ident)
    area = location(runtime)
    profile = read_profile(area, ident)
    allowance = Allowance(area / "allowance.sqlite", profile)
    return {"schema_version": "chronos.conversation-provider.v1", "status": "CONFIGURED_NOT_PROBED",
            "ready": False, "model_tested": False, "profile": profile.public(),
            "profile_sha256": profile.digest, "allowance": allowance.snapshot(),
            "native_configuration": {"baseURL": "http://127.0.0.1:11514/v1/", "model": profile.model,
                "profileSha256": profile.digest, "reasoningEffort": profile.reasoning_effort}}


def plan(ident, model, limit, effort="low", *, contract=CONTRACT):
    identity(ident)
    require(type(contract) is str and contract in CONTRACTS,"INVALID_CONVERSATION_CONTRACT")
    profile = Profile.parse(canonical({"version": CONTRACTS[contract][0], "deployment_id": ident, "provider": "ollama",
        "model": model, "schema_sha256": schema_digest(contract), "request_limit": limit, "local_port": 11434,
        "reasoning_effort": effort, "response_contract": contract}))
    validate(profile, ident)
    return profile.public()


def prepare(ident, model, limit, effort="low", *, authorize_id=None, runtime=RUNTIME, contract=CONTRACT):
    identity(ident)
    require(authorize_id == ident, "EXPLICIT_INITIALIZATION_REQUIRED")
    profile = Profile.parse(canonical(plan(ident, model, limit, effort,contract=contract)))
    area = location(runtime)
    require(not area.exists(), "PROVIDER_STATE_EXISTS_NO_RESET")
    require(not any(area.parent.iterdir()), "CONVERSATION_RUNTIME_NOT_EMPTY")
    try: area.mkdir(mode=0o700, exist_ok=False)
    except FileExistsError: raise ValueError("PROVIDER_STATE_EXISTS_NO_RESET") from None
    # After this fence, preserve partial state on any failure; never auto-repair.
    with (area / "profile.json").open("xb") as stream:
        stream.write(canonical(profile.public()))
        stream.flush(); os.fsync(stream.fileno())
    Allowance.create(area / "allowance.sqlite", profile)
    return status(ident, runtime=runtime)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    inspect = commands.add_parser("status", help="Read without probing a service or model")
    inspect.add_argument("--deployment-id", required=True)
    planning = commands.add_parser("plan", help="Validate a profile without writing state")
    init = commands.add_parser("prepare", help="One explicit initialization; no reset or startup")
    init.add_argument("--authorize-id", required=True)
    for command in (planning, init):
        command.add_argument("--deployment-id", required=True)
        command.add_argument("--contract", choices=tuple(CLI_CONTRACTS),default="c1")
        command.add_argument("--model", required=True)
        command.add_argument("--request-limit", type=int, required=True)
        command.add_argument("--reasoning-effort", choices=("none", "low", "medium"), default="low")
    args = parser.parse_args(argv)
    try:
        if args.action == "status": result = status(args.deployment_id)
        elif args.action == "plan": result = plan(args.deployment_id, args.model, args.request_limit, args.reasoning_effort,contract=CLI_CONTRACTS[args.contract])
        else:
            result = prepare(args.deployment_id, args.model, args.request_limit, args.reasoning_effort,
                             authorize_id=args.authorize_id,contract=CLI_CONTRACTS[args.contract])
    except (OSError, ValueError, sqlite3.Error, KeyError, TypeError):
        print(json.dumps({"status": "PROVIDER_STATE_REJECTED_PRESERVED", "ready": False,
                          "model_tested": False, "retry_initialization": False}))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__": raise SystemExit(main())
