"""Score supplied captures against a source-bound plan; never execute a plan."""
from argparse import ArgumentParser
from hashlib import sha256
from pathlib import Path, PurePosixPath
import json
import sys
from .paired import assess, EvaluationError, validate


def pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise EvaluationError("DUPLICATE_JSON_FIELD")
        result[key] = value
    return result


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=pairs)


def verify_sources(root, bindings):
    root = Path(root).resolve(strict=True)
    if not root.is_dir():
        raise EvaluationError("SOURCE_ROOT_NOT_DIRECTORY")
    for rel, expected in bindings.items():
        if not isinstance(rel, str) or not rel or "\\" in rel or ":" in rel:
            raise EvaluationError("INVALID_SOURCE_PATH")
        path = PurePosixPath(rel)
        if path.is_absolute() or any(p in {".", "..", ""} for p in rel.split("/")):
            raise EvaluationError("INVALID_SOURCE_PATH")
        actual = (root / rel).resolve(strict=True)
        if not actual.is_relative_to(root):
            raise EvaluationError("SOURCE_OUTSIDE_ROOT")
        if not actual.is_file() or sha256(actual.read_bytes()).hexdigest() != expected:
            raise EvaluationError("SOURCE_HASH_MISMATCH")


def main():
    parser = ArgumentParser(description="Offline Chronos E1 scoring. This never calls IRIS or a model.")
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--plan", required=True)
    parser.add_argument("--labels", required=True)
    parser.add_argument("--captures", required=True)
    parser.add_argument("--output", required=True, help="New JSON file; existing output is never overwritten.")
    args = parser.parse_args()
    try:
        plan, labels = read_json(args.plan), read_json(args.labels)
        validate(plan, labels)
        verify_sources(args.source_root, plan["source_sha256"])
        result = assess(plan, labels, read_json(args.captures))
        with Path(args.output).open("x", encoding="utf-8") as f:
            json.dump(result, f, sort_keys=True, ensure_ascii=True, indent=2)
        print(json.dumps({"output":str(Path(args.output).resolve()), "scheduled_rows":result["scheduled_rows"],
                          "received_rows":result["received_rows"], "complete":result["complete"],
                          "native_origin_verified":False, "ai_advantage":result["ai_advantage"]}))
        return 0
    except (ValueError, TypeError, KeyError, OSError) as exc:
        # Do not echo capture text, arbitrary paths, or provider error messages.
        code = str(exc) if isinstance(exc, EvaluationError) else type(exc).__name__
        print(json.dumps({"status":"REJECTED","code":code}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
