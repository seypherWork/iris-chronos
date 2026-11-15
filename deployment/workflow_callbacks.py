"""Compare exported production callbacks; never proof of their execution."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET


CLASS = "Chronos.App.Production"
CALLBACKS = ("OnStart", "OnStop")
MAX_BYTES = 2_000_000


class Rejected(ValueError):
    """Fixed, non-sensitive comparison error."""


def tree_key(node: ET.Element):
    # Ignore formatting between child elements, but preserve every leaf's text,
    # including Implementation whitespace, formal signatures and method flags.
    children = list(node)
    text = node.text or ""
    if children and not text.strip():
        text = ""
    return (node.tag, tuple(sorted(node.attrib.items())), text,
            tuple((tree_key(child), (child.tail or "").strip()) for child in children))


def members(cls: ET.Element):
    result = {"@ClassAttributes": tuple(sorted(cls.attrib.items()))}
    for node in cls:
        label = node.tag + (":" + node.get("name") if node.get("name") else "")
        result.setdefault(label, []).append(tree_key(node))
    return result


def read_class(raw: bytes):
    if type(raw) is not bytes or not raw or len(raw) > MAX_BYTES or b"\x00" in raw:
        raise Rejected("INVALID_XML_INPUT")
    try:
        text = raw.decode("utf-8", "strict")
        if "<!DOCTYPE" in text.upper() or "<!ENTITY" in text.upper():
            raise Rejected("INVALID_XML_INPUT")
        root = ET.fromstring(text)
    except (ET.ParseError, ValueError, UnicodeError):
        raise Rejected("INVALID_XML_INPUT") from None
    if root.tag != "Export" or len(root) != 1 or root[0].tag != "Class":
        raise Rejected("EXPECTED_SINGLE_CLASS_EXPORT")
    cls = root[0]
    if cls.get("name") != CLASS:
        raise Rejected("UNEXPECTED_CLASS")
    methods = {}
    for name in CALLBACKS:
        found = [n for n in cls if n.tag == "Method" and n.get("name") == name]
        if len(found) != 1:
            raise Rejected("CALLBACK_MISSING_OR_DUPLICATED")
        method = found[0]
        implementation = method.findall("Implementation")
        if len(implementation) != 1 or not (implementation[0].text or "").strip():
            raise Rejected("CALLBACK_IMPLEMENTATION_MISSING")
        methods[name] = tree_key(method)
    xdata = [n for n in cls if n.tag == "XData" and n.get("name") == "ProductionDefinition"]
    if len(xdata) != 1 or len(xdata[0].findall("Data")) != 1:
        raise Rejected("PRODUCTION_DEFINITION_MISSING_OR_DUPLICATED")
    definition = tree_key(xdata[0])
    cls.remove(xdata[0])
    stamps = [node for node in cls if node.tag == "TimeChanged"]
    stamp = None
    if stamps:
        if len(stamps) != 1 or stamps[0].attrib or list(stamps[0]):
            raise Rejected("INVALID_TIMECHANGED_METADATA")
        stamp = stamps[0].text or ""
        match = re.fullmatch(r"([0-9]{1,10}),([0-9]{1,5})(?:\.([0-9]{1,18}))?", stamp)
        if match is None or int(match[2]) >= 86400:
            raise Rejected("INVALID_TIMECHANGED_METADATA")
    return methods, definition, tree_key(cls), members(cls), stamp


def compare(before: bytes, after: bytes):
    result = {
        "schema": "chronos.production-callback-comparison.v1",
        "attribution": "STATIC_XML_ONLY_NOT_RUNTIME",
        "class": CLASS,
        "before_sha256": hashlib.sha256(before).hexdigest(),
        "after_sha256": hashlib.sha256(after).hexdigest(),
        "passed": False,
    }
    try:
        old, old_definition, old_class, old_members, old_stamp = read_class(before)
        new, new_definition, new_class, new_members, new_stamp = read_class(after)
        result["callbacks_identical"] = {name: old[name] == new[name] for name in CALLBACKS}
        result["production_definition_changed"] = old_definition != new_definition
        result["other_class_content_identical"] = old_class == new_class
        result["other_class_deltas"] = [label for label in sorted(old_members.keys() | new_members.keys())
                                        if old_members.get(label) != new_members.get(label)]
        allowed = result["other_class_deltas"] == [] or (
            result["other_class_deltas"] == ["TimeChanged"] and old_stamp is not None and new_stamp is not None)
        result["review_required"] = not allowed
        if not all(result["callbacks_identical"].values()):
            raise Rejected("CALLBACK_CHANGED")
        if not allowed:
            raise Rejected("UNEXPECTED_CLASS_DELTA")
        result.update(passed=True, code=("ONLY_PRODUCTION_DEFINITION_MAY_DIFFER" if old_class == new_class
                                        else "ONLY_PRODUCTION_DEFINITION_AND_TIMECHANGED_MAY_DIFFER"))
    except Rejected as exc:
        result["code"] = str(exc)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("before", type=Path)
    parser.add_argument("after", type=Path)
    args = parser.parse_args()
    try:
        result = compare(args.before.read_bytes(), args.after.read_bytes())
    except OSError:
        result = {"passed": False, "code": "XML_FILE_UNAVAILABLE",
                  "attribution": "STATIC_XML_ONLY_NOT_RUNTIME"}
    print(json.dumps(result, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
