"""Conservative, project-scoped readers for Codex and Copilot CLI sessions."""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Iterator

import yaml

from .common import ScanResult, belongs_to_repo, read_jsonl_header, read_session_bytes


_UUID = r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}"
_ROLLOUT = re.compile(
    rf"rollout-(\d{{4}})-(\d{{2}})-(\d{{2}})T\d{{2}}-\d{{2}}-\d{{2}}-({_UUID})(?:_{_UUID})?\.jsonl\Z"
)
_SESSION_ID = re.compile(rf"{_UUID}\Z")
_YEAR = re.compile(r"\d{4}\Z")
_MONTH_DAY = re.compile(r"\d{2}\Z")
_METADATA_BYTES = 64 * 1024


def _negative_cache(path: Path | None, source: Path, root: Path) -> dict[str, list[int]]:
    if path is None or path.is_symlink():
        return {}
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        return {}
    if (not isinstance(document, dict) or document.get("source") != str(source.resolve())
            or document.get("workdir") != str(root.resolve())):
        return {}
    entries = document.get("other_project")
    if not isinstance(entries, dict):
        return {}
    return {name: value for name, value in entries.items()
            if isinstance(name, str) and isinstance(value, list)
            and len(value) == 5 and all(isinstance(item, int) for item in value)}


def _write_negative_cache(path: Path | None, source: Path, root: Path,
                          entries: dict[str, list[int]]) -> None:
    if path is None:
        return
    temporary: Path | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent,
                                         prefix="codex-candidates-", delete=False) as stream:
            temporary = Path(stream.name)
            json.dump({"source": str(source.resolve()), "workdir": str(root.resolve()),
                       "other_project": entries}, stream)
        os.replace(temporary, path)
    except OSError:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _signature(path: Path) -> list[int] | None:
    try:
        info = path.stat()
        return [info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns]
    except OSError:
        return None


def _children(directory: Path) -> Iterator[Path]:
    """Never descend through a linked directory, including a linked source."""
    if directory.is_symlink() or not directory.is_dir():
        return
    try:
        yield from sorted(directory.iterdir())
    except OSError:
        return


def _codex_paths(source: Path) -> Iterator[tuple[Path, str]]:
    for year in _children(source):
        if not _YEAR.fullmatch(year.name):
            continue
        for month in _children(year):
            if not _MONTH_DAY.fullmatch(month.name):
                continue
            for day in _children(month):
                if not _MONTH_DAY.fullmatch(day.name):
                    continue
                for path in _children(day):
                    match = _ROLLOUT.fullmatch(path.name)
                    if match and match.group(1, 2, 3) == (year.name, month.name, day.name):
                        yield path, match.group(4)


def scan_codex(source: Path, root: Path, *, cache_path: Path | None = None) -> ScanResult:
    """Read dated rollouts only when the first record's session cwd is in root."""
    result = ScanResult()
    previous_other = _negative_cache(cache_path, source, root)
    current_other: dict[str, list[int]] = {}
    for path, filename_id in _codex_paths(source):
        if path.is_symlink() or not path.is_file():
            result.skipped_unverified += 1
            continue
        relative = path.relative_to(source).as_posix()
        signature = _signature(path)
        if signature is not None and previous_other.get(relative) == signature:
            current_other[relative] = signature
            result.skipped_unverified += 1
            continue
        header = read_jsonl_header(path, line_limit=1)
        first = header[0] if header else None
        payload = first.get("payload") if first and first.get("type") == "session_meta" else None
        session_id = payload.get("id") if isinstance(payload, dict) else None
        if (not isinstance(payload, dict) or not belongs_to_repo(payload.get("cwd"), root)
                or (session_id is not None and (
                    not isinstance(session_id, str) or session_id.casefold() != filename_id.casefold()
                ))):
            result.skipped_unverified += 1
            if signature is not None:
                current_other[relative] = signature
            continue
        body = read_session_bytes(path)
        if body is None:
            result.skipped_unverified += 1
        else:
            result.sessions.append((path, body))
    if current_other != previous_other:
        _write_negative_cache(cache_path, source, root, current_other)
    return result


def _workspace_cwd(path: Path, session_id: str) -> tuple[bool, object]:
    """Return whether optional workspace metadata is usable and its cwd."""
    if not path.exists() and not path.is_symlink():
        return True, None
    if path.is_symlink() or not path.is_file():
        return False, None
    try:
        if path.stat().st_size > _METADATA_BYTES:
            return False, None
        with path.open("rb") as stream:
            raw = stream.read(_METADATA_BYTES + 1)
        if len(raw) > _METADATA_BYTES:
            return False, None
        metadata = yaml.safe_load(raw)
    except (OSError, yaml.YAMLError, UnicodeDecodeError, ValueError):
        return False, None
    if not isinstance(metadata, dict):
        return False, None
    recorded_id = metadata.get("id")
    if recorded_id is not None and (
        not isinstance(recorded_id, str) or recorded_id.casefold() != session_id.casefold()
    ):
        return False, None
    cwd = metadata.get("cwd")
    if not isinstance(cwd, str) or not cwd:
        return False, None
    return True, cwd


def scan_copilot(source: Path, root: Path) -> ScanResult:
    """Read only ID-directory event logs whose session start owns this repo."""
    result = ScanResult()
    for directory in _children(source):
        if not _SESSION_ID.fullmatch(directory.name):
            continue
        if directory.is_symlink() or not directory.is_dir():
            result.skipped_unverified += 1
            continue
        events = directory / "events.jsonl"
        if events.is_symlink() or not events.is_file():
            result.skipped_unverified += 1
            continue
        header = read_jsonl_header(events, line_limit=1)
        first = header[0] if header else None
        data = first.get("data") if first and first.get("type") == "session.start" else None
        context = data.get("context") if isinstance(data, dict) else None
        cwd = context.get("cwd") if isinstance(context, dict) else None
        event_id = data.get("sessionId") if isinstance(data, dict) else None
        valid_workspace, workspace_cwd = _workspace_cwd(directory / "workspace.yaml", directory.name)
        if (not belongs_to_repo(cwd, root) or not valid_workspace
                or (event_id is not None and (
                    not isinstance(event_id, str) or event_id.casefold() != directory.name.casefold()
                ))
                or (workspace_cwd is not None and not belongs_to_repo(workspace_cwd, root))):
            result.skipped_unverified += 1
            continue
        body = read_session_bytes(events)
        if body is None:
            result.skipped_unverified += 1
        else:
            result.sessions.append((events, body))
    return result
