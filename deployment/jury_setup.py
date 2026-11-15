"""Prepare one isolated jury workspace using the existing verified installers.

This command only creates new local files. It never starts Docker, changes an
account, obtains a model, initializes an allowance or sends a model request.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import importlib.util
import json
import os
from pathlib import Path
import re
import sys
from uuid import uuid4

SOURCE = Path(__file__).resolve().parents[1]
MODEL = "chronos-qwen35:8k-full"
OLLAMA_IMAGE = "ollama/ollama@sha256:93c1376d651a9f1579ee40cc5763852f08b204466371e4bb64bca2a1d8d08e2d"
SCHEMA = "chronos.jury-workspace.v1"
RECEIPT = "jury-workspace.json"
FILES_ONLY = "FILES_PREPARED_NOT_INSTALLED"
RECORDED_MODE = "RECORDED_FIXTURE_SETUP_ONLY"
RECORDED_COMPOSE = ["compose.yaml", "compose.web-local.yaml", "compose.replay.yaml"]


class SetupError(ValueError):
    pass


def require(value, code):
    if not value:
        raise SetupError(code)


def modules(source):
    """Use the existing bundle, staging and profile validators, unchanged."""
    source = Path(source).absolute()
    expected = {name: source / "tools" / (name + ".py") for name in
                ("application_bundle", "installation_stage", "installation_plan", "stage_web")}
    for name, path in expected.items():
        prior = sys.modules.get(name)
        require(prior is None or (getattr(prior, "__file__", None) is not None and
                Path(prior.__file__).absolute() == path), "IMPORT_SOURCE_MISMATCH")
    package_root = source / "src/chronos_transport"
    for name, prior in tuple(sys.modules.items()):
        if name == "chronos_transport":
            locations = list(getattr(prior, "__path__", ()))
            require(bool(locations) and {Path(p).absolute() for p in locations} == {package_root},
                    "IMPORT_SOURCE_MISMATCH")
        elif name.startswith("chronos_transport."):
            location = getattr(prior, "__file__", None)
            require(location is not None and Path(location).absolute().is_relative_to(package_root),
                    "IMPORT_SOURCE_MISMATCH")
    before = list(sys.path)
    try:
        sys.path.insert(0, str(source / "tools"))
        import application_bundle as bundle
        import installation_stage as staging
    finally:
        sys.path[:] = before

    def load(name):
        spec = importlib.util.spec_from_file_location(
            "chronos_jury_setup_" + name, source / "deployment" / (name + ".py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    return bundle, staging, load("local_provider"), load("conversation_provider")


def local_path(value, bundle, *, exists):
    # Validate the original spelling before Path can normalize '..' away.
    bundle_path = bundle.web._path(value)
    from installation_plan import host_path
    host_path(str(value))
    bundle.web._directories(bundle_path if exists else bundle_path.parent)
    if not exists:
        require(not os.path.lexists(bundle_path), "WORKSPACE_ALREADY_EXISTS")
    return bundle_path


def separate(a, b):
    return a != b and not a.is_relative_to(b) and not b.is_relative_to(a)


def save(path, value, bundle):
    raw = bundle.json_bytes(value)
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    require(bundle.web._read(path) == raw, "WORKSPACE_WRITE_MISMATCH")


def replay_module(source):
    """Load only this checkout's fixture validator, with no quota or service work."""
    source = Path(source).absolute()
    for name, prior in tuple(sys.modules.items()):
        package = name.split(".", 1)[0]
        if package not in {"chronos_transport", "chronos_agent", "chronos_simulation"}:
            continue
        expected = source / "src" / package
        if name == package and not getattr(prior, "__file__", None):
            require({Path(p).absolute() for p in getattr(prior, "__path__", ())} == {expected},
                    "IMPORT_SOURCE_MISMATCH")
        else:
            location = getattr(prior, "__file__", None)
            require(location is not None and Path(location).absolute().is_relative_to(expected),
                    "IMPORT_SOURCE_MISMATCH")
    before = list(sys.path)
    try:
        spec = importlib.util.spec_from_file_location("chronos_jury_replay_provider", source / "deployment/replay_provider.py")
        replay = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(replay)
        return replay
    finally:
        sys.path[:] = before


def save_bytes(path, raw, bundle):
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    require(bundle.web._read(path) == raw, "WORKSPACE_WRITE_MISMATCH")


def recorded_profiles(source, ident, corpus_raw, expected_corpus_sha256, allowed):
    replay = replay_module(source)
    require(type(expected_corpus_sha256) is str and re.fullmatch(r"[a-f0-9]{64}", expected_corpus_sha256),
            "EXPECTED_CORPUS_SHA256_REQUIRED")
    require(sha256(corpus_raw).hexdigest() == expected_corpus_sha256, "RECORDED_CORPUS_BYTES_CHANGED")
    before = list(sys.path)
    try:
        sys.path.insert(0, str(Path(source) / "src"))
        from chronos_transport.fixture_replay import fixture_bank_digest, project, CASE_RULES, QUESTIONS, E1, C2
        bank = fixture_bank_digest()
        e1 = replay.plan(ident, 12, expected_corpus_sha256, bank, contract="e1")
        c2 = replay.plan(ident, 24, expected_corpus_sha256, bank, contract="c2-v2")
        # Synthetic fixture test records are deliberately unavailable through
        # this installation entry point. A reviewed evidence allowlist is needed.
        replay._corpus(corpus_raw, replay.Profile.parse(replay.canonical(e1)), allowed, False)
        replay._corpus(corpus_raw, replay.Profile.parse(replay.canonical(c2)), allowed, False)
        records = replay.guard.strict_json(corpus_raw)["records"]
        covered = []
        for item in records:
            selection = project(item["response_contract"], item["input_json"], item["system_prompt_sha256"])
            covered.append((item["response_contract"], selection.get("case", selection.get("question"))))
        expected = {(E1, row[0]) for row in CASE_RULES} | {(C2, question) for question in QUESTIONS}
        require(len(covered) == len(expected) and set(covered) == expected, "RECORDED_CORPUS_INCOMPLETE")
        return replay, e1, c2, bank
    finally:
        sys.path[:] = before


def recorded_environment(target, ident, image, port):
    return {"CHRONOS_PROJECT": "chronos-jury-" + ident[:12], "CHRONOS_IMAGE": image,
            "CHRONOS_DEPLOYMENT_ID": ident,
            "CHRONOS_APP": str(target / "stage/app"), "CHRONOS_DATA": str(target / "stage/data"),
            "CHRONOS_GUARD_STATE": str(target / "stage/guard"), "CHRONOS_WEB_PORT": str(port),
            "CHRONOS_CONVERSATION_STATE": str(target / "chat-state"),
            "CHRONOS_CONVERSATION_CONTRACT": "c2-v2", "CHRONOS_REPLAY_FIXTURES": str(target / "fixtures")}


def prepare_recorded(target, image, port, corpus, corpus_sha256, capture_allowlist, *, deployment_id=None, source=SOURCE):
    bundle, staging, _, _ = modules(source)
    require(type(image) is str and re.fullmatch(r"sha256:[0-9a-f]{64}", image), "EXACT_LOCAL_IMAGE_ID_REQUIRED")
    require(type(port) is int and 1024 <= port <= 65535 and port not in {11434, 11512, 11514}, "INVALID_WEB_PORT")
    ident = deployment_id if deployment_id is not None else uuid4().hex
    require(type(ident) is str and re.fullmatch(r"[0-9a-f]{32}", ident), "INVALID_DEPLOYMENT_ID")
    target = local_path(target, bundle, exists=False)
    source = local_path(source, bundle, exists=True)
    require(separate(target, source), "WORKSPACE_OVERLAPS_SOURCE")
    replay = replay_module(source)
    corpus = bundle.web._path(corpus)
    capture_allowlist = bundle.web._path(capture_allowlist)
    staging.planner.host_path(str(corpus))
    staging.planner.host_path(str(capture_allowlist))
    corpus_raw = replay.read_plain(corpus, replay.MAX_CORPUS)
    allowlist_raw = replay.read_plain(capture_allowlist, 65536)
    allowed = replay.evidence_allowlist(capture_allowlist)
    _, e1, c2, bank = recorded_profiles(source, ident, corpus_raw, corpus_sha256, allowed)
    bundle.check_source_inventory(source)
    source_raw = {rel: bundle.web._read(source / rel) for rel in bundle.catalogue(include_license=(source / "LICENSE").exists())}
    bundle.structure(source_raw)
    require(replay.read_plain(corpus, replay.MAX_CORPUS) == corpus_raw and
            replay.read_plain(capture_allowlist, 65536) == allowlist_raw, "REPLAY_INPUT_CHANGED")
    origin = f"http://127.0.0.1:{port}"
    target.mkdir(exist_ok=False)
    try:
        manifest = bundle.build(source, target / "bundle", "/csp/chronos/")
        manifest_hash = bundle.web._sha(bundle.json_bytes(manifest))
        e1_raw, c2_raw = bundle.json_bytes(e1), bundle.json_bytes(c2)
        staging.stage(target / "bundle", manifest_hash, target / "stage", e1_raw, origin, "http://127.0.0.1:11512/v1/")
        (target / "profiles").mkdir()
        save_bytes(target / "profiles/e1.json", e1_raw, bundle)
        save_bytes(target / "profiles/c2.json", c2_raw, bundle)
        (target / "chat-state").mkdir()
        (target / "fixtures").mkdir()
        save_bytes(target / "fixtures/corpus.json", corpus_raw, bundle)
        save_bytes(target / "fixtures/evidence-allowlist.json", allowlist_raw, bundle)
        result = {"schema": SCHEMA, "status": FILES_ONLY, "mode": RECORDED_MODE, "root": str(target),
                  "deployment_id": ident, "origin": origin, "bundle_manifest_sha256": manifest_hash,
                  "e1_profile_sha256": replay.Profile.parse(e1_raw).digest,
                  "c2_profile_sha256": replay.Profile.parse(c2_raw).digest,
                  "replay_corpus_sha256": corpus_sha256, "replay_fixture_sha256": bank,
                  "capture_allowlist_sha256": sha256(allowlist_raw).hexdigest(),
                  "environment": recorded_environment(target, ident, image, port),
                  "compose_files": list(RECORDED_COMPOSE), "profiles": ["recorded-fixture"],
                  "installed": False, "accounts_created": 0, "services_started": 0,
                  "model_calls": 0, "allowances_initialized": False}
        save(target / RECEIPT, result, bundle)
        verify(target, source=source)
        return result
    except (OSError, ValueError) as exc:
        raise SetupError("WORKSPACE_FAILED_PARTIAL_PRESERVED") from exc


def verify_recorded(target, result, source, bundle, staging):
    fields = {"schema", "status", "mode", "root", "deployment_id", "origin", "bundle_manifest_sha256",
              "e1_profile_sha256", "c2_profile_sha256", "replay_corpus_sha256", "replay_fixture_sha256",
              "capture_allowlist_sha256", "environment", "compose_files", "profiles", "installed",
              "accounts_created", "services_started", "model_calls", "allowances_initialized"}
    require(set(result) == fields and result["schema"] == SCHEMA and result["status"] == FILES_ONLY
            and result["mode"] == RECORDED_MODE and result["root"] == str(target), "INVALID_WORKSPACE_RECEIPT")
    require({p.name for p in target.iterdir()} == {"bundle", "stage", "profiles", "chat-state", "fixtures", RECEIPT},
            "WORKSPACE_CONTENTS_CHANGED")
    require(result["installed"] is False and result["allowances_initialized"] is False and
            all(type(result[k]) is int and result[k] == 0 for k in ("accounts_created", "services_started", "model_calls")),
            "INVALID_EXECUTION_CLAIM")
    replay = replay_module(source)
    bundle.web._directories(target / "fixtures")
    require({p.name for p in (target / "fixtures").iterdir()} == {"corpus.json", "evidence-allowlist.json"}, "RECORDED_FIXTURE_FILES_CHANGED")
    raw = replay.read_plain(target / "fixtures/corpus.json", replay.MAX_CORPUS)
    allow_raw = replay.read_plain(target / "fixtures/evidence-allowlist.json", 65536)
    require(sha256(allow_raw).hexdigest() == result["capture_allowlist_sha256"], "CAPTURE_ALLOWLIST_CHANGED")
    allowed = replay.evidence_allowlist(target / "fixtures/evidence-allowlist.json")
    _, expected_e1, expected_c2, bank = recorded_profiles(source, result["deployment_id"], raw, result["replay_corpus_sha256"], allowed)
    require(bank == result["replay_fixture_sha256"], "RECORDED_FIXTURE_BANK_CHANGED")
    require({p.name for p in (target / "profiles").iterdir()} == {"e1.json", "c2.json"}, "PROFILE_CONTENTS_CHANGED")
    e1 = replay.Profile.parse(bundle.web._read(target / "profiles/e1.json"))
    c2 = replay.Profile.parse(bundle.web._read(target / "profiles/c2.json"))
    require(e1.public() == expected_e1 and c2.public() == expected_c2, "RECORDED_PROFILE_CHANGED")
    require(e1.digest == result["e1_profile_sha256"] and c2.digest == result["c2_profile_sha256"], "PROFILE_DIGEST_CHANGED")
    bundle.verify(target / "bundle", result["bundle_manifest_sha256"])
    plan = staging.verify_stage(target / "stage", result["bundle_manifest_sha256"])
    require(plan["profile_sha256"] == e1.digest, "E1_PROFILE_CHANGED")
    config = bundle.web_json(bundle.web._read(target / "stage/config.json"))
    require(config["web_origin"] == result["origin"] and config["deployment_id"] == result["deployment_id"], "STAGE_BINDING_CHANGED")
    require(type(result["environment"]) is dict, "INVALID_COMPOSE_ENVIRONMENT")
    image = result["environment"].get("CHRONOS_IMAGE")
    require(type(image) is str and re.fullmatch(r"sha256:[0-9a-f]{64}", image), "COMPOSE_BINDING_CHANGED")
    port = staging.planner.origin(result["origin"])
    require(port not in {11434, 11512, 11514} and result["environment"] == recorded_environment(target, result["deployment_id"], image, port),
            "COMPOSE_BINDING_CHANGED")
    require(result["compose_files"] == RECORDED_COMPOSE and result["profiles"] == ["recorded-fixture"], "COMPOSE_LAYOUT_CHANGED")
    bundle.web._directories(target / "chat-state")
    require(not any((target / "chat-state").iterdir()), "WORKSPACE_ALREADY_USED")
    return result


def prepare(target, image, model_cache, port, *, deployment_id=None, source=SOURCE):
    bundle, staging, local, conversation = modules(source)
    require(type(image) is str and re.fullmatch(r"sha256:[0-9a-f]{64}", image),
            "EXACT_LOCAL_IMAGE_ID_REQUIRED")
    require(type(port) is int and 1024 <= port <= 65535 and
            port not in {11434, 11512, 11514}, "INVALID_WEB_PORT")
    ident = deployment_id if deployment_id is not None else uuid4().hex
    require(type(ident) is str and re.fullmatch(r"[0-9a-f]{32}", ident),
            "INVALID_DEPLOYMENT_ID")
    target = local_path(target, bundle, exists=False)
    cache = local_path(model_cache, bundle, exists=True)
    source = local_path(source, bundle, exists=True)
    require(separate(target, source), "WORKSPACE_OVERLAPS_SOURCE")
    require(separate(target, cache), "WORKSPACE_OVERLAPS_MODEL_CACHE")
    require(separate(source, cache), "MODEL_CACHE_OVERLAPS_SOURCE")
    e1 = local.plan(ident, MODEL, 12, "none")
    c2 = conversation.plan(ident, MODEL, 24, "none", contract=conversation.PLAN_V2_CONTRACT)
    origin = f"http://127.0.0.1:{port}"
    # Catch source/catalogue errors before reserving a new output directory.
    bundle.check_source_inventory(source)
    source_raw = {rel: bundle.web._read(source / rel)
                  for rel in bundle.catalogue(include_license=(source / "LICENSE").exists())}
    bundle.structure(source_raw)
    target.mkdir(exist_ok=False)
    try:
        manifest = bundle.build(source, target / "bundle", "/csp/chronos/")
        manifest_hash = bundle.web._sha(bundle.json_bytes(manifest))
        e1_raw = bundle.json_bytes(e1)
        staging.stage(target / "bundle", manifest_hash, target / "stage", e1_raw,
                      origin, "http://127.0.0.1:11512/v1/")
        profiles = target / "profiles"
        profiles.mkdir()
        save(profiles / "e1.json", e1, bundle)
        save(profiles / "c2.json", c2, bundle)
        for name in ("chat-state", "model-home"):
            (target / name).mkdir()
        env = {
            "CHRONOS_PROJECT": "chronos-jury-" + ident[:12],
            "CHRONOS_IMAGE": image,
            "CHRONOS_OLLAMA_IMAGE": OLLAMA_IMAGE,
            "CHRONOS_APP": str(target / "stage/app"),
            "CHRONOS_DATA": str(target / "stage/data"),
            "CHRONOS_GUARD_STATE": str(target / "stage/guard"),
            "CHRONOS_WEB_PORT": str(port),
            "CHRONOS_MODELS": str(cache),
            "CHRONOS_MODEL_HOME": str(target / "model-home"),
            "CHRONOS_MODEL_CPUS": "4",
            "CHRONOS_MODEL_MEMORY": "4g",
            "CHRONOS_CONVERSATION_STATE": str(target / "chat-state"),
            "CHRONOS_CONVERSATION_CONTRACT": "c2-v2",
            "CHRONOS_GPU_DEVICE_ID": "0",
        }
        result = {
            "schema": SCHEMA, "status": FILES_ONLY,
            "mode": "LIVE_LOCAL_SETUP_ONLY", "root": str(target),
            "deployment_id": ident, "origin": origin,
            "bundle_manifest_sha256": manifest_hash,
            "e1_profile_sha256": local.Profile.parse(e1_raw).digest,
            "c2_profile_sha256": conversation.Profile.parse(bundle.json_bytes(c2)).digest,
            "environment": env,
            "compose_files": ["compose.yaml", "compose.web-local.yaml",
                              "compose.local-model.yaml", "compose.conversation.yaml",
                              "compose.local-gpu.yaml"],
            "profiles": ["local-model", "conversation"],
            "installed": False, "accounts_created": 0, "services_started": 0,
            "model_calls": 0, "allowances_initialized": False,
        }
        save(target / RECEIPT, result, bundle)
        verify(target, source=source)
        return result
    except (OSError, ValueError) as exc:
        # Preserve partial output for inspection. Never delete/retry a new ID.
        raise SetupError("WORKSPACE_FAILED_PARTIAL_PRESERVED") from exc


def verify(target, *, source=SOURCE):
    bundle, staging, local, conversation = modules(source)
    target = local_path(target, bundle, exists=True)
    result = bundle.web_json(bundle.web._read(target / RECEIPT))
    if type(result) is dict and result.get("mode") == RECORDED_MODE:
        return verify_recorded(target, result, source, bundle, staging)
    require({p.name for p in target.iterdir()} ==
            {"bundle", "stage", "profiles", "chat-state", "model-home", RECEIPT},
            "WORKSPACE_CONTENTS_CHANGED")
    fields = {"schema", "status", "mode", "root", "deployment_id", "origin",
              "bundle_manifest_sha256", "e1_profile_sha256", "c2_profile_sha256",
              "environment", "compose_files", "profiles", "installed",
              "accounts_created", "services_started", "model_calls", "allowances_initialized"}
    require(type(result) is dict and set(result) == fields and result["schema"] == SCHEMA
            and result["status"] == FILES_ONLY and result["mode"] == "LIVE_LOCAL_SETUP_ONLY",
            "INVALID_WORKSPACE_RECEIPT")
    require(result["root"] == str(target), "WORKSPACE_IDENTITY_CHANGED")
    require(result["installed"] is False and result["allowances_initialized"] is False
            and all(type(result[k]) is int and result[k] == 0
                    for k in ("accounts_created", "services_started", "model_calls")),
            "INVALID_EXECUTION_CLAIM")
    bundle.verify(target / "bundle", result["bundle_manifest_sha256"])
    plan = staging.verify_stage(target / "stage", result["bundle_manifest_sha256"])
    require(plan["profile_sha256"] == result["e1_profile_sha256"], "E1_PROFILE_CHANGED")
    require({p.name for p in (target / "profiles").iterdir()} == {"e1.json", "c2.json"},
            "PROFILE_CONTENTS_CHANGED")
    e1 = local.Profile.parse(bundle.web._read(target / "profiles/e1.json"))
    c2 = conversation.Profile.parse(bundle.web._read(target / "profiles/c2.json"))
    local.validate(e1, result["deployment_id"])
    conversation.validate(c2, result["deployment_id"])
    require(e1.digest == result["e1_profile_sha256"] and c2.digest == result["c2_profile_sha256"],
            "PROFILE_DIGEST_CHANGED")
    require(e1.public() == local.plan(result["deployment_id"], MODEL, 12, "none"),
            "DECISION_PROFILE_CHANGED")
    require(c2.public() == conversation.plan(result["deployment_id"], MODEL, 24, "none",
                                           contract=conversation.PLAN_V2_CONTRACT),
            "CONVERSATION_PROFILE_CHANGED")
    config = bundle.web_json(bundle.web._read(target / "stage/config.json"))
    require(config["web_origin"] == result["origin"] and
            config["deployment_id"] == result["deployment_id"], "STAGE_BINDING_CHANGED")
    require(type(result["environment"]) is dict, "INVALID_COMPOSE_ENVIRONMENT")
    expected_env = {
        "CHRONOS_PROJECT": "chronos-jury-" + result["deployment_id"][:12],
        "CHRONOS_IMAGE": result["environment"].get("CHRONOS_IMAGE"),
        "CHRONOS_OLLAMA_IMAGE": OLLAMA_IMAGE,
        "CHRONOS_APP": str(target / "stage/app"),
        "CHRONOS_DATA": str(target / "stage/data"),
        "CHRONOS_GUARD_STATE": str(target / "stage/guard"),
        "CHRONOS_WEB_PORT": str(staging.planner.origin(result["origin"])),
        "CHRONOS_MODELS": result["environment"].get("CHRONOS_MODELS"),
        "CHRONOS_MODEL_HOME": str(target / "model-home"),
        "CHRONOS_MODEL_CPUS": "4", "CHRONOS_MODEL_MEMORY": "4g",
        "CHRONOS_CONVERSATION_STATE": str(target / "chat-state"),
        "CHRONOS_CONVERSATION_CONTRACT": "c2-v2", "CHRONOS_GPU_DEVICE_ID": "0",
    }
    require(result["environment"] == expected_env and
            re.fullmatch(r"sha256:[0-9a-f]{64}", expected_env["CHRONOS_IMAGE"] or ""),
            "COMPOSE_BINDING_CHANGED")
    cache = local_path(expected_env["CHRONOS_MODELS"], bundle, exists=True)
    require(separate(target, cache) and separate(Path(source), cache),
            "MODEL_CACHE_OVERLAPS_WORKSPACE")
    require(result["compose_files"] == ["compose.yaml", "compose.web-local.yaml",
            "compose.local-model.yaml", "compose.conversation.yaml", "compose.local-gpu.yaml"]
            and result["profiles"] == ["local-model", "conversation"], "COMPOSE_LAYOUT_CHANGED")
    for name in ("chat-state", "model-home"):
        bundle.web._directories(target / name)
        require(not any((target / name).iterdir()), "WORKSPACE_ALREADY_USED")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("prepare", help="Create new setup files only")
    create.add_argument("--workspace", required=True)
    create.add_argument("--image", required=True, help="Inspected local sha256 image ID")
    create.add_argument("--model-cache", required=True)
    create.add_argument("--port", required=True, type=int)
    recorded = commands.add_parser("prepare-recorded", help="Create finite recorded-fixture files only; no model or GPU")
    recorded.add_argument("--workspace", required=True)
    recorded.add_argument("--image", required=True)
    recorded.add_argument("--port", required=True, type=int)
    recorded.add_argument("--corpus", required=True)
    recorded.add_argument("--corpus-sha256", required=True, help="Expected hash from reviewed capture evidence")
    recorded.add_argument("--capture-allowlist", required=True)
    inspect = commands.add_parser("verify", help="Verify an unused prepared workspace")
    inspect.add_argument("--workspace", required=True)
    args = parser.parse_args(argv)
    try:
        result = (prepare(args.workspace, args.image, args.model_cache, args.port) if args.command == "prepare" else
                  prepare_recorded(args.workspace, args.image, args.port, args.corpus, args.corpus_sha256, args.capture_allowlist)
                  if args.command == "prepare-recorded" else verify(args.workspace))
        print(json.dumps({k: result[k] for k in
              ("status", "mode", "root", "deployment_id", "origin", "bundle_manifest_sha256",
               "installed", "accounts_created", "services_started", "model_calls")}, sort_keys=True))
        return 0
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print(json.dumps({"status": "JURY_SETUP_REJECTED", "code": str(exc)
              if isinstance(exc, SetupError) else type(exc).__name__, "ready": False}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
