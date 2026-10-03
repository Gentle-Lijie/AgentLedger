"""Scoped Trae and custom text exports."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from .common import HEADER_BYTES, ScanResult, belongs_to_repo, read_session_bytes


TEXT_SUFFIXES = {".jsonl", ".json", ".md", ".txt", ".yaml", ".yml"}


def _owned_header(path: Path, root: Path) -> bool:
    """Require bounded, top-level cwd metadata before opening an export body."""
    try:
        with path.open("rb") as stream:
            header = stream.read(HEADER_BYTES)
    except OSError:
        return False
    if not header:
        return False
    header = header.replace(b"\r\n", b"\n")
    suffix = path.suffix.casefold()
    try:
        if suffix in {".jsonl", ".json"}:
            first = header.split(b"\n", 1)[0] if suffix == ".jsonl" else header
            record = json.loads(first)
        elif header.startswith(b"---\n"):
            _, separator, rest = header.partition(b"---\n")
            frontmatter, closing, _ = rest.partition(b"\n---\n")
            if not separator or not closing:
                return False
            record = yaml.safe_load(frontmatter)
        elif suffix in {".yaml", ".yml"}:
            if path.stat().st_size > HEADER_BYTES:
                return False
            record = yaml.safe_load(header)
        else:
            return False
    except (OSError, json.JSONDecodeError, UnicodeDecodeError, yaml.YAMLError, ValueError):
        return False
    return isinstance(record, dict) and belongs_to_repo(record.get("cwd"), root)


def scan_exports(source: Path, root: Path) -> ScanResult:
    result = ScanResult()
    if source.is_symlink():
        result.skipped_unverified += 1
        return result
    if not source.exists():
        return result
    # Even a repository-local export folder may contain copied transcripts
    # from other projects, so every file needs an exact cwd declaration.
    candidates = [source] if source.is_file() else source.rglob("*")
    for path in candidates:
        if path.suffix.casefold() not in TEXT_SUFFIXES or not path.is_file() or path.is_symlink():
            continue
        if not _owned_header(path, root):
            result.skipped_unverified += 1
            continue
        payload = read_session_bytes(path)
        if payload is None:
            result.skipped_unverified += 1
            continue
        result.sessions.append((path, payload))
    return result
