"""Plan a local E1 profile or initialize/inspect its allowance without starting a service.

Trusted deployment console only. No model call, native account change, credential,
quota reset or retry. An interrupted initialization is preserved, not repaired.
"""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import sys

HERE = Path(__file__).resolve().parent
TRANSPORT = HERE.parent / "src" / "chronos_transport"
spec = importlib.util.spec_from_file_location("chronos_local_provider_profile", TRANSPORT / "deployment.py")
profile_module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = profile_module
spec.loader.exec_module(profile_module)
Profile, Allowance = profile_module.Profile, profile_module.Allowance
RUNTIME = Path("/opt/chronos/runtime")
CONTRACT = "chronos.preference-extraction.v1"


class ProviderError(ValueError):
    pass


def require(value, code):
    if not value:
        raise ProviderError(code)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def plain(path, directory=False):
    info = path.lstat()
    require(not stat.S_ISLNK(info.st_mode) and not getattr(info, "st_file_attributes", 0) & 0x400,
            "LINK_OR_REPARSE_POINT")
    require(stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode), "WRONG_PATH_KIND")
    return info


def location(runtime):
    runtime = Path(runtime)
    require(runtime.is_absolute() and ".." not in runtime.parts, "INVALID_RUNTIME_PATH")
    for parent in reversed((runtime, *runtime.parents)):
        plain(parent, directory=True)
    return runtime / "local-provider"


def identity(ident):
    require(type(ident) is str and re.fullmatch(r"[a-f0-9]{32}", ident), "INVALID_DEPLOYMENT_ID")


def schema_digest():
    # This is packaged trusted source; full bundle verification is a prerequisite.
    raw = (TRANSPORT / "extraction-schema.json").read_bytes()
    schema = json.loads(raw)
    require(schema["properties"]["schema_version"]["enum"] == [CONTRACT], "WRONG_SCHEMA")
    return hashlib.sha256(canonical(schema)).hexdigest()


def validate(profile, ident):
    identity(ident)
    require(profile.deployment_id == ident, "DEPLOYMENT_MISMATCH")
    require(profile.version == 3 and profile.provider == "ollama" and profile.local_port == 11434
            and profile.response_contract == CONTRACT, "LOCAL_E1_PROFILE_REQUIRED")
    require(profile.schema_sha256 == schema_digest(), "PROFILE_SCHEMA_MISMATCH")


def read_profile(area, ident):
    plain(area, directory=True)
    allowed = {"profile.json", "allowance.sqlite", "allowance.sqlite-wal", "allowance.sqlite-shm"}
    require({p.name for p in area.iterdir()} <= allowed, "UNEXPECTED_PROVIDER_STATE")
    for child in area.iterdir():
        plain(child)
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
    snapshot = allowance.snapshot()
    return {"schema_version": "chronos.local-provider.v1", "status": "CONFIGURED_NOT_PROBED",
            "ready": False, "model_tested": False, "profile": profile.public(),
            "profile_sha256": profile.digest, "allowance": snapshot}


def plan(ident, model, limit, effort="none"):
    """Return only a validated non-secret profile; no runtime, quota or I/O effect."""
    identity(ident)
    profile = Profile.parse(canonical({"version": 3, "deployment_id": ident, "provider": "ollama",
        "model": model, "schema_sha256": schema_digest(), "request_limit": limit, "local_port": 11434,
        "reasoning_effort": effort, "response_contract": CONTRACT}))
    validate(profile, ident)
    return profile.public()


def prepare(ident, model, limit, effort="none", *, authorize_id=None, runtime=RUNTIME):
    identity(ident)
    require(authorize_id == ident, "EXPLICIT_INITIALIZATION_REQUIRED")
    profile = Profile.parse(canonical(plan(ident, model, limit, effort)))
    area = location(runtime)
    if area.exists():
        raise ProviderError("PROVIDER_STATE_EXISTS_NO_RESET")
    require(not any(area.parent.iterdir()), "GUARD_RUNTIME_NOT_EMPTY")
    # Exclusive directory creation fences concurrent or repeated initialization.
    # All later failures leave the directory/evidence intact for inspection.
    try:
        area.mkdir(mode=0o700, exist_ok=False)
    except FileExistsError:
        raise ProviderError("PROVIDER_STATE_EXISTS_NO_RESET") from None
    with (area / "profile.json").open("xb") as stream:
        stream.write(canonical(profile.public()))
        stream.flush()
        os.fsync(stream.fileno())
    Allowance.create(area / "allowance.sqlite", profile)
    return status(ident, runtime=runtime)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    inspect = commands.add_parser("status", help="Read the existing profile and durable allowance; no service probe")
    inspect.add_argument("--deployment-id", required=True)
    planning = commands.add_parser("plan", help="Print a non-secret profile for staging; no runtime or allowance")
    init = commands.add_parser("prepare", help="Explicit first initialization only; no model or service start")
    init.add_argument("--authorize-id", required=True)
    for command in (planning, init):
        command.add_argument("--deployment-id", required=True)
        command.add_argument("--model", required=True)
        command.add_argument("--request-limit", required=True, type=int)
        command.add_argument("--reasoning-effort", choices=("none", "low", "medium"), default="none")
    args = parser.parse_args(argv)
    try:
        if args.action == "status":
            result = status(args.deployment_id)
        elif args.action == "plan":
            result = plan(args.deployment_id, args.model, args.request_limit, args.reasoning_effort)
        else:
            result = prepare(args.deployment_id, args.model, args.request_limit, args.reasoning_effort,
                             authorize_id=args.authorize_id)
    except (OSError, ValueError, sqlite3.Error, KeyError, TypeError):
        # Never dump arbitrary filesystem/provider exceptions or private context.
        print(json.dumps({"status": "PROVIDER_STATE_REJECTED_PRESERVED", "ready": False,
                          "model_tested": False, "retry_initialization": False}))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
