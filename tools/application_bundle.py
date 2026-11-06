"""Build/verify an explicit source-only Chronos bundle. Never installs or starts it."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import re

import stage_web as web

SCHEMA = "chronos.application-bundle.v1"
STATUS = "STAGED_LOCAL_NOT_INSTALLED"
CLASS_GROUPS = {
    "Agent": "Context Decisions GuardAdapter Ledger Model Operation Python",
    "App": "Entry Input Process Production Request Response Worker",
    "Approval": "Controller Entry Identity Input Operation Request",
    "Conversation": "Context Controller Ledger Model Python",
    "Authority": "Store", "Destination": "Simulator",
    "Recovery": "Coordinator Provider Sweep", "Review": "Python",
    "Runtime": "Bootstrap Durability Python", "Web": "API Assets Events NativePolicy Policy",
}
PACKAGES = {
    "chronos_simulation": "__init__.py clock.py model.py realtime.py registry.py store.py workflow.py",
    "chronos_agent": "__init__.py engine.py proposal.py contract.py timeview.py extraction.py AGENT_INSTRUCTIONS.txt EXTRACTION_INSTRUCTIONS.txt",
    "chronos_conversation": "__init__.py contract.py ledger.py evidence.py grounded.py grounded_v2.py",
    "chronos_grounding": "__init__.py plan.py renderer_v1.py renderer_v2.py evidence_v2.py README.md",
    "chronos_review": "__init__.py projection.py README.md",
    "chronos_transport": "guard.py deployment.py cloud_budget.py cloud_transport.py cloud_models.py cloud_server.py cloud_config.py proposal-schema.json proposal-schema-v2.json extraction-schema.json conversation-schema.json conversation-plan-schema.json conversation-plan-v2-schema.json",
    "chronos_evaluation": "__init__.py __main__.py paired.py README.md",
}
EXTRA = {"tools/application_bundle.py", "tools/stage_web.py", "tools/installation_plan.py", "tools/installation_preflight.py", "tools/installation_stage.py", "deployment/INSTALLATION.md", "deployment/JURY-ROUTE.md", "deployment/PREFLIGHT.md", "deployment/COMPOSE.md", "deployment/compose.yaml", "deployment/native_health.py", "deployment/first_case.py", "deployment/NativeInstall.cls", "deployment/native_install.py", "deployment/NativeScenario.cls", "deployment/jury_case.py", "deployment/JURY-CASE.md", "deployment/local_provider.py", "deployment/compose.local-model.yaml", "deployment/compose.local-gpu.yaml", "deployment/LOCAL-PROVIDER.md", "deployment/native_provider.py", "deployment/NativeProvider.cls", "deployment/NATIVE-PROVIDER.md", "deployment/NativeWeb.cls", "deployment/native_web.py", "deployment/WEB-ACCESS.md", "deployment/compose.web-local.yaml", "deployment/CLOUD-BUDGET.md", "deployment/CLOUD-TRANSPORT.md", "deployment/cloud_provider.py", "deployment/compose.cloud.yaml", "deployment/CLOUD-PROVIDER.md", "deployment/provider_state.py"}
EXTRA |= {"deployment/Modelfile.qwen35-9b", "deployment/MODEL-RECIPE.md"}
MANIFEST = "bundle-manifest.json"
EXTRA |= {"deployment/model_readiness.py", "README.md", "deployment/EVIDENCE.md"}
EXTRA |= {"deployment/EVIDENCE-HISTORY.md"}
EXTRA |= {"deployment/conversation_provider.py", "deployment/compose.conversation.yaml", "deployment/CONVERSATION-PROVIDER.md"}
EXTRA |= {"deployment/NativeConversation.cls", "deployment/native_conversation.py"}
EXTRA |= {"deployment/NativeResume.cls", "deployment/native_resume.py", "deployment/NATIVE-RESUME.md", "deployment/MODEL-DIAGNOSTICS.md"}


def catalogue(*, include_license=False):
    result = {f"src/Chronos/{group}/{name}.cls" for group,names in CLASS_GROUPS.items() for name in names.split()}
    result |= {f"src/{package}/{name}" for package,names in PACKAGES.items() for name in names.split()}
    result |= {f"src/chronos_web/{name}" for name in web.ASSETS}
    return result | EXTRA | ({"LICENSE"} if include_license else set())


def inventory(directory, *, ignore_caches=False):
    """Inspect without following symlinks/reparse points; ignore only bytecode caches."""
    found = set()
    web._directories(directory)
    for parent, dirs, files in os.walk(directory, followlinks=False):
        parent = Path(parent)
        web._directories(parent)
        for name in dirs[:]:
            web._plain(parent/name, directory=True)
            if ignore_caches and name == "__pycache__":
                dirs.remove(name)
        for name in files:
            web._plain(parent/name, directory=False)
            found.add((parent/name).relative_to(directory).as_posix())
    return found


def check_source_inventory(root):
    expected = catalogue()
    native = {p.removeprefix("src/Chronos/") for p in expected if p.startswith("src/Chronos/")}
    if inventory(root/"src/Chronos", ignore_caches=True) != native:
        raise web.StageError("NATIVE_CATALOGUE_CHANGED")
    for package,names in PACKAGES.items():
        if inventory(root/"src"/package, ignore_caches=True) != set(names.split()):
            raise web.StageError("PYTHON_PACKAGE_CONTENTS_CHANGED")
    if inventory(root/"src/chronos_web", ignore_caches=True) - {"README.md"} != set(web.ASSETS):
        raise web.StageError("WEB_CATALOGUE_CHANGED")


def structure(sources):
    """Syntax and fixed dependency closure only; ObjectScript is not compiled here."""
    names = {f"Chronos.{g}.{n}" for g,ns in CLASS_GROUPS.items() for n in ns.split()}
    console_classes = {"deployment/NativeInstall.cls": "Chronos.Deployment.NativeInstall",
                       "deployment/NativeScenario.cls": "Chronos.Deployment.NativeScenario",
                       "deployment/NativeProvider.cls": "Chronos.Deployment.NativeProvider",
                       "deployment/NativeConversation.cls": "Chronos.Deployment.NativeConversation",
                       "deployment/NativeResume.cls": "Chronos.Deployment.NativeResume",
                       "deployment/NativeWeb.cls": "Chronos.Deployment.NativeWeb"}
    for rel, raw in sources.items():
        text = raw.decode("utf-8")
        if rel.endswith(".py"):
            try:
                compile(text, rel, "exec", dont_inherit=True)
            except SyntaxError:
                raise web.StageError("PYTHON_SYNTAX_INVALID") from None
        elif rel.endswith(".json"):
            web_json(raw)
        elif rel.endswith(".cls"):
            # Console-only %SYS helpers stay outside application LoadDir.
            class_name = console_classes.get(rel, rel.removeprefix("src/").removesuffix(".cls").replace("/","."))
            declarations = re.findall(r"^Class\s+(Chronos\.[\w.]+)\s+Extends\s",text,re.M)
            if declarations != [class_name]:
                raise web.StageError("CLASS_DECLARATION_MISMATCH")
            refs = set(re.findall(r"##class\((Chronos\.[\w.]+)\)",text))
            refs |= set(re.findall(r'ClassName="(Chronos\.[\w.]+)"',text))
            refs |= set(re.findall(r'Parameter\s+ADAPTER\s*=\s*"(Chronos\.[\w.]+)"',text))
            allowed = names | (set(console_classes.values()) if rel in console_classes else set())
            if not refs <= allowed:
                raise web.StageError("NATIVE_DEPENDENCY_MISSING")
        elif rel.endswith(".mjs"):
            # Closed static styles used by this client. Reject unrecognized import
            # syntax rather than silently claiming a complete dependency graph.
            pattern = re.compile(r"""\bimport\s+(?:(?:\{[^{};]*\}|[A-Za-z_$][\w$]*|\*\s+as\s+[A-Za-z_$][\w$]*)\s+from\s+)?(["'])([^"'\r\n]+)\1\s*;""")
            matches = list(pattern.finditer(text))
            declarations = list(re.finditer(r"\bexport\s+(?:async\s+)?(?:function|class|const|let|var)\b",text))
            if ({m.start() for m in re.finditer(r"\bimport\b",text)} != {m.start() for m in matches}
                    or {m.start() for m in re.finditer(r"\bexport\b",text)} != {m.start() for m in declarations}):
                raise web.StageError("UNSUPPORTED_WEB_IMPORT_STYLE")
            for imported in (m.group(2) for m in matches):
                if not imported.startswith("./") or imported[2:] not in web.ASSETS:
                    raise web.StageError("WEB_DEPENDENCY_NOT_BUNDLED")


def web_json(raw):
    def pairs(items):
        output = {}
        for k,v in items:
            if k in output:
                raise web.StageError("DUPLICATE_JSON_FIELD")
            output[k] = v
        return output
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(web.StageError("NONFINITE_JSON")))
    except (UnicodeError, ValueError, RecursionError):
        raise web.StageError("INVALID_JSON") from None


def json_bytes(data):
    return (json.dumps(data,sort_keys=True,ensure_ascii=True,indent=2)+"\n").encode("ascii")


def manifest_for(source, output, api_base):
    return {"schema_version":SCHEMA, "status":STATUS, "api_base":api_base,
            "required_iris_build":"2026.3.0AI.154.0", "source_sha256":{p:web._sha(b) for p,b in sorted(source.items())},
            "output_sha256":{p:web._sha(b) for p,b in sorted(output.items())},
            "transformed_files":["src/chronos_web/index.html"],
            "contains_image":False, "contains_accounts":False, "contains_runtime_data":False,
            "installed":False, "native_compilation_verified":False}


def build(source_root, destination, api_base):
    root, target = web._path(source_root), web._path(destination)
    web._directories(root)
    web._directories(target.parent)
    if type(api_base) is not str or web.API_BASE.fullmatch(api_base) is None:
        raise web.StageError("INVALID_API_BASE")
    if os.path.lexists(target):
        raise web.StageError("DESTINATION_EXISTS")
    if any(target.is_relative_to(root/d) for d in ("src","tools","deployment")):
        raise web.StageError("DESTINATION_IN_SOURCE")
    check_source_inventory(root)
    has_license = os.path.lexists(root/"LICENSE")
    source = {rel:web._read(root/rel) for rel in sorted(catalogue(include_license=has_license))}
    structure(source)
    output = dict(source)
    output["src/chronos_web/index.html"] = web._html(source["src/chronos_web/index.html"],api_base)
    manifest = manifest_for(source,output,api_base)
    # Final source recheck before creating anything; never silently accept drift.
    check_source_inventory(root)
    if os.path.lexists(root/"LICENSE") != has_license or any(
        web._read(root/rel) != raw for rel,raw in source.items()
    ):
        raise web.StageError("SOURCE_CHANGED")
    web._directories(target.parent)
    try:
        target.mkdir(exist_ok=False)
        for rel,raw in {**output,MANIFEST:json_bytes(manifest)}.items():
            dest = target/rel
            dest.parent.mkdir(parents=True,exist_ok=True)
            web._directories(dest.parent)
            with dest.open("xb") as f:
                f.write(raw);f.flush();os.fsync(f.fileno())
            if web._read(dest) != raw:
                raise web.StageError("OUTPUT_VERIFICATION_FAILED")
    except OSError:
        raise web.StageError("WRITE_FAILED_PARTIAL_PRESERVED") from None
    verify(target, expected_manifest_sha256=web._sha(json_bytes(manifest)))
    return manifest


def verify(directory, expected_manifest_sha256=None):
    root = web._path(directory)
    all_files = inventory(root)
    expected_files = catalogue(include_license="LICENSE" in all_files)
    if all_files != expected_files | {MANIFEST}:
        raise web.StageError("BUNDLE_CONTENTS_CHANGED")
    raw = web._read(root/MANIFEST)
    if expected_manifest_sha256 is not None and (type(expected_manifest_sha256) is not str or not re.fullmatch("[a-f0-9]{64}", expected_manifest_sha256) or web._sha(raw) != expected_manifest_sha256):
        raise web.StageError("MANIFEST_DIGEST_MISMATCH")
    m = web_json(raw)
    fields = "schema_version status api_base required_iris_build source_sha256 output_sha256 transformed_files contains_image contains_accounts contains_runtime_data installed native_compilation_verified".split()
    if type(m) is not dict or set(m) != set(fields) or m["schema_version"] != SCHEMA or m["status"] != STATUS:
        raise web.StageError("INVALID_MANIFEST")
    if m["required_iris_build"] != "2026.3.0AI.154.0" or m["transformed_files"] != ["src/chronos_web/index.html"]:
        raise web.StageError("INVALID_MANIFEST")
    if any(m[k] is not False for k in ("contains_image","contains_accounts","contains_runtime_data","installed","native_compilation_verified")):
        raise web.StageError("UNSUPPORTED_INSTALLATION_CLAIM")
    if type(m["api_base"]) is not str or web.API_BASE.fullmatch(m["api_base"]) is None:
        raise web.StageError("INVALID_API_BASE")
    for key in ("source_sha256","output_sha256"):
        if type(m[key]) is not dict or set(m[key]) != expected_files or any(type(v) is not str or not re.fullmatch("[a-f0-9]{64}",v) for v in m[key].values()):
            raise web.StageError("INVALID_MANIFEST_HASHES")
    sources = {}
    for rel,h in m["output_sha256"].items():
        raw = web._read(root/rel)
        if web._sha(raw) != h:
            raise web.StageError("OUTPUT_HASH_MISMATCH")
        if rel != "src/chronos_web/index.html" and h != m["source_sha256"][rel]:
            raise web.StageError("UNEXPECTED_TRANSFORMATION")
        sources[rel] = raw
    # Recover only the one approved build-time substitution and verify its source hash.
    rel = "src/chronos_web/index.html"
    marker = f'<meta name="chronos-api-base" content="{m["api_base"]}">'.encode("ascii")
    if sources[rel].count(marker) != 1:
        raise web.StageError("API_BASE_BINDING_MISMATCH")
    original = sources[rel].replace(marker,web.PLACEHOLDER,1)
    if web._sha(original) != m["source_sha256"][rel] or web._html(original,m["api_base"]) != sources[rel]:
        raise web.StageError("INDEX_SOURCE_BINDING_MISMATCH")
    structure(sources)
    return {"status":STATUS, "verified_files":len(sources),
            "manifest_sha256":web._sha(web._read(root/MANIFEST)), "installed":False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command",required=True)
    build_p = sub.add_parser("build")
    build_p.add_argument("--source-root",type=Path,default=Path(__file__).resolve().parents[1])
    build_p.add_argument("--output",type=Path,required=True)
    build_p.add_argument("--api-base",required=True)
    verify_p = sub.add_parser("verify")
    verify_p.add_argument("directory",type=Path)
    verify_p.add_argument("--manifest-sha256")
    args = parser.parse_args(argv)
    try:
        if args.command == "build":
            m = build(args.source_root,args.output,args.api_base)
            result = {"status":STATUS,"files":len(m["output_sha256"]),
                      "manifest_sha256":web._sha(json_bytes(m)),"installed":False}
        else:
            result = verify(args.directory,args.manifest_sha256)
        print(json.dumps(result))
        return 0
    except (web.StageError,OSError) as exc:
        print(json.dumps({"status":"BUNDLE_REJECTED","code":str(exc) if isinstance(exc,web.StageError) else "FILESYSTEM_UNAVAILABLE"}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
