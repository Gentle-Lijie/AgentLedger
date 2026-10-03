"""Read only Pi and DeepSeek Harness session logs with verified cwd headers.

Pi layout: https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/session-format.md
Harness layout: https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/session/session-persistence-jsonl/README.md
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from .common import HEADER_BYTES, MAX_SESSION_BYTES, ScanResult, read_session_bytes


_PROJECT = re.compile(r"--[^/\\]+--\Z")
_PI_LOG = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}-\d{3}Z_[^/\\]+\.jsonl\Z")
_DSH_LOG = re.compile(r"session(?:\.v([1-9][0-9]*))?\.jsonl(\.zstd)?\Z")


def _children(directory: Path) -> list[Path]:
    if directory.is_symlink() or not directory.is_dir():
        return []
    try:
        return sorted(directory.iterdir())
    except OSError:
        return []


def _projects(source: Path) -> list[Path]:
    """Accept a configured root, its sessions parent, or one project directory."""
    if source.is_symlink():
        return []
    if _PROJECT.fullmatch(source.name) and source.is_dir():
        return [source]
    # DSH's persistence root is configurable. A CLI home can also contain a
    # `sessions` child; inspect both layouts without descending into config.
    bases = [source, source / "sessions"]
    return [p for base in bases for p in _children(base)
            if _PROJECT.fullmatch(p.name) and p.is_dir() and not p.is_symlink()]


def _owned(header: object, root: Path) -> bool:
    if not isinstance(header, dict) or header.get("type") != "session":
        return False
    cwd = header.get("cwd")
    if not isinstance(cwd, str) or not cwd:
        return False
    candidate = Path(cwd)
    try:
        return candidate.is_absolute() and candidate.resolve(strict=False) == root.resolve()
    except (OSError, RuntimeError, ValueError):
        return False


def _first_json_line(raw: bytes) -> object:
    line, separator, _ = raw.partition(b"\n")
    if not separator or len(line) > HEADER_BYTES:
        return None
    try:
        return json.loads(line)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None


def _raw_header(path: Path) -> object:
    if path.is_symlink() or not path.is_file():
        return None
    try:
        with path.open("rb") as stream:
            return _first_json_line(stream.readline(HEADER_BYTES + 2))
    except OSError:
        return None


def _compressed_header(path: Path) -> object:
    """Harness puts its header alone in the first checksummed frame."""
    try:
        import zstandard

        with path.open("rb") as raw, zstandard.ZstdDecompressor().stream_reader(
            raw, read_across_frames=False
        ) as reader:
            header = reader.read(HEADER_BYTES + 2)
            return _first_json_line(header) if len(header) <= HEADER_BYTES + 1 else None
    except ImportError:
        return None
    except (OSError, zstandard.ZstdError, ValueError):
        return None


def _compressed_body(path: Path) -> bytes | None:
    try:
        import zstandard

        if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_SESSION_BYTES:
            return None
        with path.open("rb") as raw, zstandard.ZstdDecompressor().stream_reader(
            raw, read_across_frames=True
        ) as reader:
            body = reader.read(MAX_SESSION_BYTES + 1)
            return body if len(body) <= MAX_SESSION_BYTES else None
    except ImportError:
        return None
    except (OSError, zstandard.ZstdError, ValueError):
        return None


def scan_pi(source: Path, root: Path) -> ScanResult:
    result = ScanResult()
    for project in _projects(source):
        for path in _children(project):
            if not _PI_LOG.fullmatch(path.name) or path.is_symlink() or not path.is_file():
                continue
            if not _owned(_raw_header(path), root):
                result.skipped_unverified += 1
                continue
            body = read_session_bytes(path)
            if body is None:
                result.skipped_unverified += 1
                continue
            result.sessions.append((path, body))
    return result


def _scan_harness_directory(directory: Path, root: Path, result: ScanResult) -> None:
    generations: dict[int, list[tuple[Path, bool]]] = {}
    for path in _children(directory):
        match = _DSH_LOG.fullmatch(path.name)
        if match and path.is_file() and not path.is_symlink():
            version_text = match.group(1)
            if version_text and len(version_text) > 16:
                continue
            version = int(version_text or 0)
            if version > 9007199254740991:  # JS safe-integer format version.
                continue
            generations.setdefault(version, []).append((path, bool(match.group(2))))
    if not generations:
        return
    current = generations[max(generations)]
    if len(current) != 1:  # A mixed-encoding root has no unambiguous current log.
        result.skipped_unverified += 1
        return
    path, compressed = current[0]
    header = _compressed_header(path) if compressed else _raw_header(path)
    if not _owned(header, root):
        result.skipped_unverified += 1
        return
    body = _compressed_body(path) if compressed else read_session_bytes(path)
    if body is None:
        result.skipped_unverified += 1
        return
    virtual_path = path.with_name(path.name + ".decompressed.jsonl") if compressed else path
    result.sessions.append((virtual_path, body))


def scan_deepseek(source: Path, root: Path) -> ScanResult:
    result = ScanResult()
    # An explicitly configured legacy/session root can itself contain the log.
    # Only canonical basenames are opened; home-level config is never visited.
    _scan_harness_directory(source, root, result)
    for project in _projects(source):
        for session_dir in _children(project):
            if not session_dir.is_symlink() and session_dir.is_dir():
                _scan_harness_directory(session_dir, root, result)
    return result
