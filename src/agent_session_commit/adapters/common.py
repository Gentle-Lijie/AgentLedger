"""Bounded reads and exact project ownership checks for agent adapters."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import unquote, urlparse


MAX_SESSION_BYTES = 50 * 1024 * 1024
HEADER_BYTES = 64 * 1024


@dataclass
class ScanResult:
    sessions: list[tuple[Path, bytes]] = field(default_factory=list)
    skipped_unverified: int = 0


def belongs_to_repo(value: object, root: Path) -> bool:
    """Accept only an absolute cwd resolving to the selected Git root."""
    if not isinstance(value, str) or not value:
        return False
    if value.casefold().startswith("file://"):
        value = unquote(urlparse(value).path)
        if os.name == "nt" and re.match(r"^/[A-Za-z]:/", value):
            value = value[1:]
    candidate = Path(os.path.expanduser(value))
    if not candidate.is_absolute():
        return False
    try:
        resolved = candidate.resolve(strict=False)
        canonical_root = root.resolve()
        return resolved == canonical_root
    except (OSError, RuntimeError, ValueError):
        return False


def read_jsonl_header(path: Path, *, byte_limit: int = HEADER_BYTES,
                      line_limit: int = 32) -> list[dict[str, object]]:
    if path.is_symlink():
        return []
    try:
        with path.open("rb") as stream:
            lines: list[bytes] = []
            remaining = byte_limit
            for _ in range(line_limit):
                line = stream.readline(remaining + 1)
                if not line or len(line) > remaining:
                    break
                lines.append(line)
                remaining -= len(line)
                if not remaining:
                    break
    except OSError:
        return []
    records: list[dict[str, object]] = []
    for line in lines:
        try:
            value = json.loads(line)
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        if isinstance(value, dict):
            records.append(value)
    return records


def read_session_bytes(path: Path, *, byte_limit: int = MAX_SESSION_BYTES) -> bytes | None:
    """Bound each body read and reject linked or growing files."""
    if path.is_symlink() or not path.is_file():
        return None
    try:
        if path.stat().st_size > byte_limit:
            return None
        with path.open("rb") as stream:
            value = stream.read(byte_limit + 1)
        return value if len(value) <= byte_limit else None
    except OSError:
        return None
