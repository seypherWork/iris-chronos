"""Verified console bootstrap for a NEW isolated Community AI Hub154 deployment.

Inspect is read-only apart from compiling the reviewed installer class into %SYS.
Apply requires an explicit matching deployment authorization. It creates disabled
accounts/apps only. No model call, port publication, password output or reset.
"""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import uuid

BUNDLE = Path("/opt/chronos/bundle")
ALIASES = {name: Path("/opt/chronos") / name for name in ("src", "deployment", "tools")}
MARKER = "CHRONOS_NATIVE_INSTALL:"


class InstallError(ValueError):
    pass


def require(value, code):
    if not value:
        raise InstallError(code)


def validate(deployment_id, origin, application, digest):
    require(type(deployment_id) is str and re.fullmatch(r"[a-f0-9]{32}", deployment_id), "INVALID_DEPLOYMENT_ID")
    require(type(digest) is str and re.fullmatch(r"[a-f0-9]{64}", digest), "INVALID_MANIFEST_DIGEST")
    require(type(application) is str and len(application) <= 100 and
            re.fullmatch(r"/csp/chronos(?:-[a-z0-9-]+)?/", application), "INVALID_APPLICATION")
    require(type(origin) is str and len(origin) <= 256, "INVALID_ORIGIN")
    match = re.fullmatch(r"(https?)://([a-z0-9.-]+|\[::1\])(?::([1-9][0-9]{0,4}))?", origin)
    require(match is not None, "INVALID_ORIGIN")
    scheme, host, port = match.groups()
    require(port is None or (int(port) <= 65535 and int(port) != (443 if scheme == "https" else 80)), "INVALID_PORT")
    require(scheme == "https" or host in {"127.0.0.1", "localhost", "[::1]"}, "TLS_REQUIRED")


def verify_source(digest, application, *, bundle=BUNDLE, aliases=ALIASES):
    """Use the pinned source verifier, then compare every mounted source alias."""
    # The tool was supplied from trusted source. This detects bundle/alias drift,
    # not a malicious local administrator replacing this verifier and its caller.
    tools = bundle / "tools"
    import_path_before = list(sys.path)
    sys.path.insert(0, str(tools))
    try:
        import application_bundle
        require(Path(application_bundle.__file__).absolute() == (tools / "application_bundle.py").absolute(), "VERIFIER_MODULE_ORIGIN_CHANGED")
        require(Path(application_bundle.web.__file__).absolute() == (tools / "stage_web.py").absolute(), "VERIFIER_MODULE_ORIGIN_CHANGED")
        application_bundle.verify(bundle, digest)
        raw = application_bundle.web._read(bundle / "bundle-manifest.json")
        require(hashlib.sha256(raw).hexdigest() == digest, "MANIFEST_CHANGED_AFTER_VERIFY")
        manifest = application_bundle.web_json(raw)
        require(manifest["api_base"] == application, "BUNDLE_APPLICATION_MISMATCH")
        require(set(aliases) == {"src", "deployment", "tools"}, "ALIAS_SET_CHANGED")
        for top, alias in aliases.items():
            expected_files = {relative.split("/", 1)[1] for relative in manifest["output_sha256"]
                              if relative.startswith(top + "/")}
            require(application_bundle.inventory(alias) == expected_files, "MOUNT_ALIAS_CONTENTS_CHANGED")
        for relative, expected in manifest["output_sha256"].items():
            top, separator, rest = relative.partition("/")
            if separator:
                require(top in aliases, "UNEXPECTED_SOURCE_ROOT")
                actual = application_bundle.web._read(aliases[top] / rest)
            else:
                # Verify the allowed root documents against the full bundle.
                require(relative in {"README.md", "LICENSE"}, "UNEXPECTED_SOURCE_ROOT")
                actual = application_bundle.web._read(bundle / relative)
            require(hashlib.sha256(actual).hexdigest() == expected, "MOUNT_ALIAS_DRIFT")
        require((aliases["deployment"] / "NativeInstall.cls").is_file(), "NATIVE_INSTALLER_MISSING")
        return manifest
    except (OSError, ValueError, KeyError, TypeError) as exc:
        if isinstance(exc, InstallError):
            raise
        raise InstallError("BUNDLE_VERIFICATION_FAILED") from exc
    finally:
        sys.path[:] = import_path_before


def program(action, deployment_id, origin, application, digest, nonce):
    validate(deployment_id, origin, application, digest)
    require(action in {"inspect", "apply"}, "INVALID_ACTION")
    require(type(nonce) is str and re.fullmatch(r"[a-f0-9]{32}", nonce), "INVALID_MARKER")
    # Validated inputs contain no quotes, backslashes or ObjectScript syntax.
    args = ','.join('"' + value + '"' for value in (deployment_id, origin, application))
    call = 'Inspect(' + args + ')' if action == "inspect" else 'Install(' + args + ',"' + digest + '")'
    return ('set r={"status":"NATIVE_COMMAND_FAILED","ready":false} '
            'try { set sc=$System.OBJ.Load("/opt/chronos/deployment/NativeInstall.cls","ck") '
            'if $System.Status.IsOK(sc) { set r=##class(%DynamicObject).%FromJSON('
            '##class(Chronos.Deployment.NativeInstall).' + call + ') } '
            '} catch ex { set r={"status":"NATIVE_COMMAND_FAILED","ready":false} } '
            'write !,"' + MARKER + nonce + ':",r.%ToJSON(),!\nhalt\n')


def parse_output(raw, nonce):
    require(type(raw) is str and len(raw) <= 131072, "NATIVE_OUTPUT_UNAVAILABLE")
    prefix = MARKER + nonce + ":"
    lines = [line[len(prefix):] for line in raw.splitlines() if line.startswith(prefix)]
    require(len(lines) == 1, "NATIVE_RESULT_MISSING_OR_DUPLICATE")
    def unique(pairs):
        out = {}
        for k, v in pairs:
            require(k not in out, "DUPLICATE_NATIVE_FIELD")
            out[k] = v
        return out
    try:
        result = json.loads(lines[0], object_pairs_hook=unique,
                            parse_constant=lambda _: (_ for _ in ()).throw(InstallError("INVALID_NATIVE_NUMBER")))
    except ValueError as exc:
        raise InstallError("INVALID_NATIVE_RESULT") from exc
    require(type(result) is dict and type(result.get("status")) is str and
            result.get("ready") is False, "INVALID_NATIVE_RESULT")
    # A printed terminal/compiler error can never be a successful installation.
    require(not re.search(r"<[^<>\r\n]{1,160}>|ERROR\s+#\d+", raw), "NATIVE_ERROR_OUTPUT")
    return result


def assess_result(result, action, deployment_id, origin, application):
    success = "NAMES_CLEAR_NOT_AUTHORIZATION" if action == "inspect" else "NATIVE_INSTALLED_DISABLED"
    if result["status"] != success:
        return result
    spec = result.get("spec")
    require(type(spec) is dict and type(spec.get("layoutVersion")) is int and spec["layoutVersion"] == 4 and
            spec.get("id") == deployment_id and
            spec.get("origin") == origin and spec.get("application") == application and
            spec.get("namespace") == "CHRONOS_" + deployment_id[:12].upper() and
            spec.get("root") == "/durable/chronos/" + deployment_id,
            "NATIVE_BINDING_MISMATCH")
    primary = "%DB_Chronos_" + deployment_id[:12]
    temporary = primary + "_TEMP"
    databases = spec.get("databases")
    require(spec.get("resource") == primary and spec.get("tempResource") == temporary and
            type(databases) is list and len(databases) == 3 and
            type(databases[0]) is dict and databases[0].get("resource") == primary and
            databases[1] == {"name": spec["namespace"] + "_TEMP", "directory": spec["root"] + "/temp/",
                             "resource": temporary, "journal": 2},
            "NATIVE_TEMP_STORAGE_BINDING_MISMATCH")
    if action == "inspect":
        rows = result.get("rows")
        require(result.get("applied") is False and result.get("conflicts") == 0 and
                result.get("intentExists") == 0 and type(rows) is list and len(rows) == 25,
                "INCOMPLETE_PREFLIGHT")
        seen = set()
        for row in rows:
            require(type(row) is dict and set(row) == {"kind", "name", "status"}, "INVALID_PREFLIGHT_ROW")
            require(all(type(row[k]) is str for k in row), "INVALID_PREFLIGHT_ROW")
            key = row["kind"], row["name"]
            require(key not in seen and row["status"] in {"ABSENT", "PRESENT"}, "INVALID_PREFLIGHT_ROW")
            if key == ("resource", temporary):
                require(row["status"] == "ABSENT", "TEMP_RESOURCE_PREFLIGHT_CONFLICT")
            seen.add(key)
        require(("resource", temporary) in seen, "TEMP_RESOURCE_PREFLIGHT_MISSING")
    else:
        require(result.get("accountsEnabled") is False and type(result.get("modelCalls")) is int and
                result["modelCalls"] == 0, "INVALID_INSTALL_RECEIPT")
    return result


def execute(action, deployment_id, origin, application, digest, *, authorize_id=None,
            run=subprocess.run):
    validate(deployment_id, origin, application, digest)
    require(action != "apply" or authorize_id == deployment_id, "EXPLICIT_INSTALL_AUTHORIZATION_REQUIRED")
    env = dict(os.environ)
    # Never inherit authorization from an unrelated shell or previous invocation.
    env.pop("CHRONOS_INSTALL_APPROVED", None)
    if action == "apply":
        env["CHRONOS_INSTALL_APPROVED"] = deployment_id + ":" + digest
    nonce = uuid.uuid4().hex
    script = program(action, deployment_id, origin, application, digest, nonce)
    try:
        p = run(["iris", "session", "IRIS", "-U", "%SYS"], input=script,
                text=True, capture_output=True, env=env, timeout=180, check=False)
    except subprocess.TimeoutExpired:
        return {"status":"INSTALL_OUTCOME_UNCERTAIN_DO_NOT_RETRY", "ready":False}
    except (OSError, UnicodeError):
        return {"status":"NATIVE_COMMAND_UNAVAILABLE", "ready":False}
    require(p.returncode == 0 and not p.stderr.strip(), "NATIVE_COMMAND_FAILED")
    return assess_result(parse_output(p.stdout, nonce), action, deployment_id, origin, application)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("action", choices=("inspect", "apply"))
    p.add_argument("--deployment-id", required=True)
    p.add_argument("--origin", required=True)
    p.add_argument("--application", required=True)
    p.add_argument("--manifest-sha256", required=True)
    p.add_argument("--authorize-id", help="Apply only: repeat the approved deployment ID")
    args = p.parse_args(argv)
    try:
        validate(args.deployment_id, args.origin, args.application, args.manifest_sha256)
        require(os.name == "posix", "RUN_INSIDE_OWNED_LINUX_CONTAINER")
        require(args.action != "apply" or args.authorize_id == args.deployment_id,
                "EXPLICIT_INSTALL_AUTHORIZATION_REQUIRED")
        verify_source(args.manifest_sha256, args.application)
        from native_health import engine
        health = engine()
        require(health.get("ready") is True, health.get("code", "ENGINE_UNAVAILABLE"))
        result = execute(args.action, args.deployment_id, args.origin, args.application,
                         args.manifest_sha256, authorize_id=args.authorize_id)
    except (InstallError, OSError) as exc:
        result = {"status": str(exc) if isinstance(exc, InstallError) else "INSTALLER_UNAVAILABLE", "ready":False}
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] in {"NAMES_CLEAR_NOT_AUTHORIZATION", "NATIVE_INSTALLED_DISABLED"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
