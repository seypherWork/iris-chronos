"""Read-only IRIS engine / Chronos native readiness; never calls a model.

Run inside the owned container as its existing OS user. This does not create
namespaces, configure a production, reset state or certify end-to-end readiness.
"""
from __future__ import annotations
import argparse
import json
import re
import subprocess

SCHEMA = "chronos.health.v1"
MARKER = "CHRONOS_HEALTH:"
BUILD = "2026.3.0AI.154.0"
PRODUCTION = "Chronos.App.Production"


def result(scope, code, ready=False):
    return {"schema_version": SCHEMA, "scope": scope, "code": code,
            "ready": ready, "provider_checked": False, "model_calls": 0}


def engine(*, run=subprocess.run):
    scope = "IRIS_ENGINE_ONLY"
    try:
        p = run(["iris", "qlist", "IRIS"], capture_output=True, text=True,
                timeout=4, check=False)
    except subprocess.TimeoutExpired:
        return result(scope, "ENGINE_TIMEOUT")
    except (OSError, UnicodeError):
        return result(scope, "ENGINE_UNAVAILABLE")
    if p.returncode != 0 or p.stderr.strip():
        return result(scope, "ENGINE_COMMAND_FAILED")
    rows = p.stdout.strip().splitlines()
    if len(rows) != 1:
        return result(scope, "ENGINE_RESPONSE_INVALID")
    fields = rows[0].split("^")
    if len(fields) < 9 or fields[0] != "IRIS":
        return result(scope, "ENGINE_RESPONSE_INVALID")
    if fields[2] != BUILD + "com":
        return result(scope, "REQUIRED_AI_HUB_154_NOT_RUNNING")
    if fields[3].split(",", 1)[0] != "running":
        return result(scope, "ENGINE_NOT_RUNNING")
    if fields[8] not in {"ok", "warn"}:
        return result(scope, "ENGINE_ALERT_OR_UNKNOWN_HEALTH")
    return result(scope, "ENGINE_READY", True)


def native_program(namespace):
    # No raw CLI input can become ObjectScript syntax. Even quoted strings,
    # expressions and system namespaces are excluded.
    if type(namespace) is not str or re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", namespace) is None:
        raise ValueError("INVALID_NAMESPACE")
    initial = json.dumps(result("NATIVE_PRODUCTION_ONLY", "NAMESPACE_MISSING"),
                         separators=(",", ":"))
    # One command prevents terminal errors on one line from falling through to
    # a later unconditional success marker. Never print exception details.
    command = (
        'set r=' + initial + ' '
        'try { '
        'if ##class(%SYS.Namespace).Exists("' + namespace + '") { '
        'zn "' + namespace + '" '
        'set r.code="BOOTSTRAP_MISSING" '
        'if ##class(%Dictionary.CompiledClass).%ExistsId("Chronos.Runtime.Bootstrap") { '
        'set r.code="NATIVE_NOT_READY" '
        'set sc=##class(Chronos.Runtime.Bootstrap).Ready(.s) '
        'if $SYSTEM.Status.IsOK(sc),$IsObject(s),s.ready { '
        'if s.production="' + PRODUCTION + '" { '
        'set r.code="NATIVE_READY" do r.%Set("ready",1,"boolean") '
        '} else { set r.code="WRONG_PRODUCTION" } '
        '} '
        '} '
        '} '
        '} catch ex { set r.code="NATIVE_CHECK_FAILED" do r.%Set("ready",0,"boolean") } '
        'write !,"' + MARKER + '",r.%ToJSON(),!'
    )
    return command + '\nhalt\n'


def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("DUPLICATE_FIELD")
        value[key] = item
    return value


def read_native(namespace, *, run=subprocess.run):
    scope = "NATIVE_PRODUCTION_ONLY"
    try:
        command = native_program(namespace)
    except ValueError:
        return result(scope, "INVALID_NAMESPACE")
    try:
        p = run(["iris", "session", "IRIS", "-U", "%SYS"], input=command,
                capture_output=True, text=True, timeout=15, check=False)
    except subprocess.TimeoutExpired:
        return result(scope, "NATIVE_TIMEOUT")
    except (OSError, UnicodeError):
        return result(scope, "NATIVE_UNAVAILABLE")
    if p.returncode != 0 or p.stderr.strip():
        return result(scope, "NATIVE_COMMAND_FAILED")
    # Console error recovery must not turn an incomplete check into success.
    if "<" in p.stdout or "ERROR #" in p.stdout or "\x1b" in p.stdout:
        return result(scope, "NATIVE_RESPONSE_INVALID")
    markers = [line[len(MARKER):] for line in p.stdout.splitlines() if line.startswith(MARKER)]
    if len(markers) != 1 or p.stdout.count(MARKER) != 1:
        return result(scope, "NATIVE_RESPONSE_INVALID")
    try:
        observed = json.loads(markers[0], object_pairs_hook=_unique_object)
    except (ValueError, RecursionError):
        return result(scope, "NATIVE_RESPONSE_INVALID")
    allowed = {"NAMESPACE_MISSING", "BOOTSTRAP_MISSING", "NATIVE_NOT_READY",
               "WRONG_PRODUCTION", "NATIVE_CHECK_FAILED", "NATIVE_READY"}
    if (type(observed) is not dict or set(observed) != set(result(scope, ""))
            or type(observed.get("code")) is not str or observed.get("code") not in allowed
            or observed != result(scope, observed["code"], observed["code"] == "NATIVE_READY")
            or type(observed.get("ready")) is not bool
            or type(observed.get("provider_checked")) is not bool
            or type(observed.get("model_calls")) is not int):
        return result(scope, "NATIVE_RESPONSE_INVALID")
    return observed


def check(mode, namespace=None, *, run=subprocess.run):
    if mode not in {"engine", "native"}:
        return result("UNDETERMINED", "INVALID_MODE")
    if mode == "native":
        try:
            native_program(namespace)
        except ValueError:
            return result("NATIVE_PRODUCTION_ONLY", "INVALID_NAMESPACE")
    state = engine(run=run)
    if not state["ready"] or mode == "engine":
        return state
    return read_native(namespace, run=run)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("mode", choices=("engine", "native"))
    p.add_argument("--namespace")
    args = p.parse_args(argv)
    state = check(args.mode, args.namespace)
    print(json.dumps(state, sort_keys=True))
    return 0 if state["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
