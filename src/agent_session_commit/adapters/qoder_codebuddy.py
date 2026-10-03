"""Conservative discovery of Qoder and CodeBuddy JSONL session transcripts.

Vendor references:
https://docs.qoder.com/cli/sessions
https://docs.qoder.com/extensions/hooks#transcript-file-format
https://www.codebuddy.cn/docs/cli/codebuddy-dir
https://www.codebuddy.cn/docs/cli/daemon

Project directory names are opaque vendor identifiers. Never derive one from a
repository path: collisions and changes to the vendor encoding are possible.
"""

from __future__ import annotations

import json
from pathlib import Path

from .common import HEADER_BYTES, ScanResult, belongs_to_repo, read_session_bytes


_RECORD_TYPES = {"session_meta", "user", "assistant", "progress"}
_HEADER_LIMIT = min(HEADER_BYTES, 64 * 1024)


def _session_paths(source: Path, *, qoder: bool) -> list[Path]:
    """Visit only documented session locations or an explicitly selected source.

    No recursive walk: Qoder IDE has a transcript/ child; CodeBuddy's child
    directories also contain tool results, subagents, and other runtime data.
    """
    if source.is_symlink():
        return []
    if source.is_file():
        return [source] if source.suffix == ".jsonl" else []
    if not source.is_dir():
        return []
    try:
        children = list(source.iterdir())
    except OSError:
        return []

    directories = [source]
    if source.name == "projects":
        directories = [path for path in children if path.is_dir() and not path.is_symlink()]
    elif qoder:
        transcript = source / "transcript"
        if transcript.is_dir() and not transcript.is_symlink():
            directories.append(transcript)

    paths: list[Path] = []
    for directory in directories:
        try:
            entries = directory.iterdir()
            paths.extend(path for path in entries
                         if path.suffix == ".jsonl" and path.name != "history.jsonl"
                         and path.is_file() and not path.is_symlink())
            if qoder and source.name == "projects" and directory != source:
                transcript = directory / "transcript"
                if transcript.is_dir() and not transcript.is_symlink():
                    paths.extend(path for path in transcript.iterdir()
                                 if path.suffix == ".jsonl" and path.is_file()
                                 and not path.is_symlink())
        except OSError:
            continue
    return sorted(set(paths))


def _verified_header(path: Path, root: Path, *, qoder: bool) -> bool:
    """Require session-shaped metadata and an owned top-level cwd in 64 KiB.

    Message text, tool arguments, and directory names are never attribution.
    A malformed or oversized initial record makes the format unverified.
    """
    try:
        with path.open("rb") as stream:
            header = stream.read(_HEADER_LIMIT)
    except OSError:
        return False
    lines = header.splitlines(keepends=True)
    if not lines or not lines[0].endswith((b"\n", b"\r")):
        return False
    try:
        first = json.loads(lines[0])
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False
    if not isinstance(first, dict) or first.get("type") not in _RECORD_TYPES:
        return False
    if qoder and first.get("type") == "session_meta":
        data = first.get("data")
        if (not isinstance(data, dict) or data.get("meta_type") != "session_info"
                or not isinstance(first.get("sessionId"), str)
                or not first["sessionId"]):
            return False
    elif first.get("cwd") is None:
        return False

    # The Qoder IDE example omits cwd on its first session_meta line, while
    # its documented record schema places cwd at top level of later lines.
    # CodeBuddy does not document an equivalent first-line schema, so require
    # its first record itself to carry cwd rather than infer it from content.
    records = lines[:256] if qoder else lines[:1]
    owned = False
    for line in records:
        if not line.endswith((b"\n", b"\r")):
            break
        try:
            record = json.loads(line)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return False
        if not isinstance(record, dict) or record.get("type") not in _RECORD_TYPES:
            return False
        cwd = record.get("cwd")
        if cwd is not None:
            if not belongs_to_repo(cwd, root):
                return False
            owned = True
    return owned


def _scan(source: Path, root: Path, *, qoder: bool) -> ScanResult:
    result = ScanResult()
    for path in _session_paths(source, qoder=qoder):
        if not _verified_header(path, root, qoder=qoder):
            result.skipped_unverified += 1
            continue
        body = read_session_bytes(path)
        if body is None:
            result.skipped_unverified += 1
            continue
        result.sessions.append((path, body))
    return result


def scan_qoder(source: Path, root: Path) -> ScanResult:
    return _scan(source, root, qoder=True)


def scan_codebuddy(source: Path, root: Path) -> ScanResult:
    return _scan(source, root, qoder=False)
