"""Explicit cloud plan/prepare/status/private-console launcher. No auto enable.

No key arguments, files or environment lookup. Plan and status never contact the
provider. Serve needs a reviewed plan digest, a verified bundle, a Linux private
console and the owned container network namespace documented in CLOUD-PROVIDER.
"""
from __future__ import annotations
import argparse
import getpass
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import sys
import time
import warnings

ROOT = Path(__file__).resolve().parents[1]
# Keep the ObjectScript Chronos tree out of the shared Python search path.
_import_path_before = list(sys.path)
try:
    sys.path.insert(0, str(ROOT / "src"))
    from chronos_transport.cloud_budget import CloudAllowance, CloudBudgetPolicy, canonical, digest
    from chronos_transport.cloud_models import reviewed_model, validate_selection
    from chronos_transport.cloud_config import SCHEMA, schema_digest, validate
    from chronos_transport.cloud_transport import ApiKey, OpenAITransport
    from chronos_transport.cloud_server import make_server
    from chronos_transport.deployment import Profile
    from chronos_transport import guard
finally:
    sys.path[:] = _import_path_before
    del _import_path_before
RUNTIME = Path("/opt/chronos/runtime")


def require(value, code):
    if not value: raise ValueError(code)


def plain(path, directory=False):
    info = Path(path).lstat()
    require(not stat.S_ISLNK(info.st_mode) and not getattr(info, "st_file_attributes", 0) & 0x400,
            "LINK_OR_REPARSE_POINT")
    require(stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode), "WRONG_PATH_KIND")
    return info


def directory(path):
    path = Path(path)
    require(path.is_absolute() and ".." not in path.parts, "ABSOLUTE_PLAIN_PATH_REQUIRED")
    for parent in reversed((path, *path.parents)): plain(parent, True)
    return path




def plan(ident, model, requests, budget, seconds, *, input_rate=None, output_rate=None):
    require(type(ident) is str and re.fullmatch(r"[a-f0-9]{32}", ident), "INVALID_DEPLOYMENT_ID")
    require(type(seconds) is int and 60 <= seconds <= 86400, "INVALID_VALIDITY_SECONDS")
    card = reviewed_model(model)
    profile = Profile(ident, "openai-chat-json", model, schema_digest(), requests,
                      None, 3, "none", guard.EXTRACTION_CONTRACT)
    # Validate dataclass values via its strict public parser too.
    profile = Profile.parse(canonical(profile.public()))
    now = time.time_ns() // 1000
    policy = CloudBudgetPolicy(profile.digest, budget, card["model_context_tokens"],
        card["input_rate_floor_micro_usd_per_million"] if input_rate is None else input_rate,
        card["output_rate_floor_micro_usd_per_million"] if output_rate is None else output_rate,
        now, now + seconds * 1_000_000)
    validate_selection(profile, policy)
    return {"schema_version": SCHEMA, "profile": profile.public(), "policy": policy.public(), "model_review": card}




def read_plan(path):
    path = Path(path)
    directory(path.parent)
    require(plain(path).st_size <= 8192, "PLAN_TOO_LARGE")
    with path.open("rb") as f: raw = f.read(8193)
    require(len(raw) <= 8192, "PLAN_TOO_LARGE")
    try:
        value = guard.strict_json(raw)
    except guard.Rejected:
        raise ValueError("INVALID_PLAN_JSON") from None
    validate(value)
    return value


def current(policy):
    now = time.time_ns() // 1000
    require(policy.created_at_us <= now < policy.expires_at_us, "AUTHORIZATION_NOT_CURRENT")


def authorize(value, authorization):
    require(type(authorization) is str and authorization == digest(value), "EXACT_PLAN_AUTHORIZATION_REQUIRED")


def summary(value, ledger=None):
    profile, policy = validate(value)
    return {"status": "CLOUD_CONFIG_NOT_PROBED", "ready": False, "model_tested": False,
        "native_verified": False, "billing_verified": False, "plan_sha256": digest(value),
        "profile_sha256": profile.digest, "policy_sha256": policy.digest,
        "reserve_micro_usd_per_request": policy.reserve_micro_usd,
        "max_admitted_requests": min(profile.request_limit, policy.budget_micro_usd // policy.reserve_micro_usd),
        "plan": value, "allowance": ledger.snapshot() if ledger else None}


def state(ident, *, runtime=RUNTIME):
    root = directory(runtime); area = root / "cloud-provider"; plain(area, True)
    require({p.name for p in root.iterdir()} == {"cloud-provider"}, "DEDICATED_GUARD_ROOT_REQUIRED")
    names = {p.name for p in area.iterdir()}
    require({"plan.json", "allowance.sqlite"} <= names <= {
        "plan.json", "allowance.sqlite", "allowance.sqlite-wal", "allowance.sqlite-shm"}, "UNEXPECTED_PROVIDER_STATE")
    for name in names: plain(area / name)
    value = read_plan(area / "plan.json"); profile, policy = validate(value)
    require(profile.deployment_id == ident, "DEPLOYMENT_MISMATCH")
    return value, CloudAllowance(area / "allowance.sqlite", profile, policy)


def prepare(value, *, authorized_plan_sha256, runtime=RUNTIME):
    profile, policy = validate(value)
    authorize(value, authorized_plan_sha256); current(policy)
    root = directory(runtime)
    require(not any(root.iterdir()), "PROVIDER_STATE_EXISTS_NO_RESET")
    area = root / "cloud-provider"; area.mkdir(mode=0o700)
    # No cleanup/recovery on failure: preserve partial initialization for review.
    fd = os.open(area / "plan.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(canonical(value).encode("ascii")); f.flush(); os.fsync(f.fileno())
    ledger = CloudAllowance.create(area / "allowance.sqlite", profile, policy,
                                  authorized_policy_sha256=policy.digest)
    return summary(value, ledger)


def private_key():
    # Refuse getpass's plaintext fallback, redirected stdin and automated keys.
    require(sys.stdin.isatty() and sys.stderr.isatty(), "PRIVATE_INTERACTIVE_CONSOLE_REQUIRED")
    with warnings.catch_warnings():
        warnings.simplefilter("error", getpass.GetPassWarning)
        secret = getpass.getpass("OpenAI key (hidden; memory only): ", stream=sys.stderr)
    try: return ApiKey(secret)
    finally: secret = None  # Drops this reference, not a secure-memory erasure claim.


def verify_console(bundle_sha256):
    require(sys.platform == "linux" and os.geteuid() == 51773 and ROOT == Path("/opt/chronos"),
            "OWNED_LINUX_DEPLOYMENT_REQUIRED")
    require(type(bundle_sha256) is str and re.fullmatch(r"[a-f0-9]{64}", bundle_sha256), "BUNDLE_DIGEST_REQUIRED")
    bundle = Path("/opt/chronos/bundle"); raw = (bundle / "bundle-manifest.json").read_bytes()
    require(hashlib.sha256(raw).hexdigest() == bundle_sha256, "BUNDLE_DIGEST_MISMATCH")
    manifest = guard.strict_json(raw)
    spec = importlib.util.spec_from_file_location("chronos_cloud_verify", ROOT / "deployment/native_install.py")
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    mod.verify_source(bundle_sha256, manifest["api_base"])
    # UID/path verification is not proof of network isolation. Compose and its
    # operator own that boundary. Do not expose this process outside private IRIS.
    require(sys.stdin.isatty() and sys.stderr.isatty(), "PRIVATE_INTERACTIVE_CONSOLE_REQUIRED")
    area = directory(RUNTIME) / "cloud-provider"
    for p in [RUNTIME, area, *area.iterdir()]:
        info = plain(p, p in (RUNTIME, area))
        require(info.st_uid == 51773 and not info.st_mode & 0o022, "PRIVATE_STATE_OWNERSHIP_REQUIRED")


def serve(ident, authorization, bundle_sha256):
    verify_console(bundle_sha256)
    value, ledger = state(ident); authorize(value, authorization); current(ledger.policy)
    available = ledger.snapshot()
    require(not available["halted"] and available["remaining_requests"] > 0
            and available["remaining_budget_micro_usd"] >= ledger.policy.reserve_micro_usd,
            "NO_AUTHORIZED_ALLOWANCE")
    key = private_key(); server = None
    try:
        current(ledger.policy)  # A console wait may outlive consent.
        client = OpenAITransport(ledger, key, authorized_policy_sha256=ledger.policy.digest)
        server = make_server(client); server.timeout = 0.5
        print(json.dumps({"status": "CLOUD_LISTENER_STARTED_NOT_NATIVE_VERIFIED", "ready": False}), flush=True)
        while time.time_ns() // 1000 < ledger.policy.expires_at_us:
            available = ledger.snapshot()
            if (available["halted"] or available["remaining_requests"] == 0
                    or available["remaining_budget_micro_usd"] < ledger.policy.reserve_micro_usd): break
            server.handle_request()
    finally:
        try:
            if server is not None: server.server_close()  # Join admitted workers before dropping the key.
        finally:
            key.close()
    return summary(value, ledger)


class PrivateParser(argparse.ArgumentParser):
    def error(self, message):
        # Unknown --api-key VALUE must never be copied into argparse diagnostics.
        raise ValueError("INVALID_CLOUD_COMMAND")


def main(argv=None):
    try:
        parser = PrivateParser(description=__doc__)
        sub = parser.add_subparsers(dest="action", required=True, parser_class=PrivateParser)
        p = sub.add_parser("plan")
        p.add_argument("--deployment-id", required=True); p.add_argument("--model", required=True)
        p.add_argument("--request-limit", type=int, required=True)
        p.add_argument("--budget-micro-usd", type=int, required=True)
        p.add_argument("--valid-for-seconds", type=int, required=True)
        p.add_argument("--input-rate-micro", type=int); p.add_argument("--output-rate-micro", type=int)
        p = sub.add_parser("inspect-plan"); p.add_argument("--plan", type=Path, required=True)
        p = sub.add_parser("prepare"); p.add_argument("--plan", type=Path, required=True)
        p.add_argument("--authorize-plan-sha256", required=True)
        p = sub.add_parser("status"); p.add_argument("--deployment-id", required=True)
        p = sub.add_parser("serve"); p.add_argument("--deployment-id", required=True)
        p.add_argument("--authorize-plan-sha256", required=True); p.add_argument("--bundle-sha256", required=True)
        args = parser.parse_args(argv)
        if args.action == "plan":
            # Output only the actual plan: save/review it, then compute its digest.
            result = plan(args.deployment_id, args.model, args.request_limit, args.budget_micro_usd,
                          args.valid_for_seconds, input_rate=args.input_rate_micro, output_rate=args.output_rate_micro)
        elif args.action == "inspect-plan":
            result = summary(read_plan(args.plan.absolute()))
        elif args.action == "prepare":
            result = prepare(read_plan(args.plan.absolute()), authorized_plan_sha256=args.authorize_plan_sha256)
        elif args.action == "status":
            value, ledger = state(args.deployment_id); result = summary(value, ledger)
        else:
            result = serve(args.deployment_id, args.authorize_plan_sha256, args.bundle_sha256)
    except (Exception, KeyboardInterrupt):
        print(json.dumps({"status": "CLOUD_ACTION_REJECTED_STATE_PRESERVED", "ready": False,
                          "model_tested": False, "automatic_retry": False}))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__": raise SystemExit(main())
