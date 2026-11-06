"""Reproducible local web staging. Never deploys, overwrites or removes files."""
from __future__ import annotations

import argparse
import hashlib
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import stat

ASSETS = (
    "boot.mjs", "client.mjs", "consent-controller.mjs", "consent-panel.mjs",
    "consent.mjs", "controller.mjs", "conversation-controller.mjs", "conversation-panel.mjs", "conversation-v2.mjs", "detail.mjs", "index.html",
    "preparation-references.mjs", "presentation.mjs", "references.mjs",
    "render.mjs", "screen.css", "screen.mjs", "session-references.mjs",
)
API_BASE = re.compile(r"/(?:[A-Za-z0-9_-]+/)*[A-Za-z0-9_-]+/?", re.ASCII)
PLACEHOLDER = b'<meta name="chronos-api-base" content="">'
STATUS = "STAGED_LOCAL_NOT_DEPLOYED"
PROJECT = Path(__file__).absolute().parents[1]


class StageError(ValueError):
    """Controlled staging rejection; no automatic cleanup or retry."""


def _path(value: str | os.PathLike[str]) -> Path:
    path = Path(value)
    # Do not normalize traversal away before checking its components.
    if ".." in path.parts:
        raise StageError("PATH_TRAVERSAL")
    return path.absolute()


def _plain(path: Path, *, directory: bool) -> os.stat_result:
    try:
        info = path.lstat()
    except OSError as exc:
        raise StageError("PATH_UNAVAILABLE") from exc
    if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
        raise StageError("LINK_OR_REPARSE_POINT")
    if not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)):
        raise StageError("WRONG_PATH_KIND")
    return info


def _directories(path: Path) -> None:
    for component in reversed((path, *path.parents)):
        _plain(component, directory=True)


def _identity(info: os.stat_result) -> tuple[int, int, int, int]:
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns


def _read(path: Path) -> bytes:
    _directories(path.parent)
    before = _plain(path, directory=False)
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        with os.fdopen(os.open(path, flags), "rb") as stream:
            if _identity(os.fstat(stream.fileno())) != _identity(before):
                raise StageError("SOURCE_CHANGED")
            raw = stream.read()
            after = os.fstat(stream.fileno())
    except OSError as exc:
        raise StageError("SOURCE_READ_FAILED") from exc
    if _identity(before) != _identity(after) or _identity(before) != _identity(_plain(path, directory=False)):
        raise StageError("SOURCE_CHANGED")
    if not raw or b"\0" in raw:
        raise StageError("INVALID_SOURCE_TEXT")
    try:
        raw.decode("utf-8", errors="strict")
    except UnicodeError as exc:
        raise StageError("INVALID_SOURCE_UTF8") from exc
    return raw


class _Meta(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.matches: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "meta" and any(k == "name" and (v or "").lower() == "chronos-api-base" for k, v in attrs):
            self.matches.append(self.get_starttag_text())

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)


def _html(raw: bytes, api_base: str) -> bytes:
    parser = _Meta()
    try:
        parser.feed(raw.decode("utf-8"))
        parser.close()
    except Exception as exc:
        raise StageError("INVALID_INDEX_HTML") from exc
    if parser.matches != [PLACEHOLDER.decode("ascii")] or raw.count(PLACEHOLDER) != 1:
        raise StageError("API_PLACEHOLDER_NOT_UNIQUE_EMPTY")
    return raw.replace(PLACEHOLDER, f'<meta name="chronos-api-base" content="{api_base}">'.encode("ascii"), 1)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def stage(source_dir: str | os.PathLike[str], destination: str | os.PathLike[str], api_base: str) -> dict:
    """Create one new directory with 15 exact assets and manifest.json.

    All input bytes are validated before creating the destination. If writing
    fails, a partial new directory is preserved; it is never overwritten/removed.
    This is local packaging, not an adversarial filesystem transaction.
    """
    if type(api_base) is not str or API_BASE.fullmatch(api_base) is None:
        raise StageError("INVALID_API_BASE")
    source, target = _path(source_dir), _path(destination)
    _directories(source)
    _directories(target.parent)
    if os.path.lexists(target):
        raise StageError("DESTINATION_EXISTS")
    # Refuse a newly introduced runtime asset which this explicit package omits.
    for candidate in source.iterdir():
        if candidate.suffix.lower() in {".mjs", ".css", ".html"} and candidate.name not in ASSETS:
            raise StageError("UNLISTED_WEB_ASSET")
    originals = {name: _read(source / name) for name in ASSETS}
    output = dict(originals)
    output["index.html"] = _html(originals["index.html"], api_base)
    # Recheck the complete source snapshot before the first output mutation.
    if any(_read(source / name) != originals[name] for name in ASSETS):
        raise StageError("SOURCE_CHANGED")
    manifest = {
        "version": 1, "status": STATUS, "api_base": api_base,
        "source_sha256": {name: _sha(originals[name]) for name in ASSETS},
        "output_sha256": {name: _sha(output[name]) for name in ASSETS},
    }
    manifest_bytes = (json.dumps(manifest, ensure_ascii=True, sort_keys=True, indent=2) + "\n").encode("ascii")
    _directories(target.parent)
    try:
        target.mkdir(exist_ok=False)
    except FileExistsError as exc:
        raise StageError("DESTINATION_EXISTS") from exc
    except OSError as exc:
        raise StageError("DESTINATION_CREATE_FAILED") from exc
    try:
        for name, raw in output.items():
            _directories(target)
            with (target / name).open("xb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            if _read(target / name) != raw:
                raise StageError("OUTPUT_VERIFICATION_FAILED")
        _directories(target)
        with (target / "manifest.json").open("xb") as stream:
            stream.write(manifest_bytes)
            stream.flush()
            os.fsync(stream.fileno())
        if _read(target / "manifest.json") != manifest_bytes:
            raise StageError("MANIFEST_VERIFICATION_FAILED")
        if set(p.name for p in target.iterdir()) != set(ASSETS) | {"manifest.json"}:
            raise StageError("OUTPUT_CONTENT_CHANGED")
    except OSError as exc:
        raise StageError("STAGE_WRITE_FAILED_PARTIAL_PRESERVED") from exc
    return manifest


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--api-base", required=True)
    args = parser.parse_args(argv)
    try:
        result = stage(PROJECT / "src" / "chronos_web", args.output, args.api_base)
    except (StageError, OSError) as exc:
        code = str(exc) if isinstance(exc, StageError) else "FILESYSTEM_UNAVAILABLE"
        print(json.dumps({"status": "STAGING_FAILED", "code": code}))
        return 1
    print(json.dumps({"status": result["status"], "assets": len(ASSETS)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
