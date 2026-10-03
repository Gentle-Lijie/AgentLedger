"""Project-owned Claude Code transcripts, with a safe explicit-export fallback."""

from __future__ import annotations

from pathlib import Path

from .common import ScanResult, read_jsonl_header, read_session_bytes
from .exports import scan_exports


def _owned_header(path: Path, root: Path) -> bool:
    canonical_root = root.resolve()
    for record in read_jsonl_header(path, byte_limit=1024 * 1024, line_limit=256):
        cwd = record.get("cwd")
        if not isinstance(cwd, str):
            continue
        candidate = Path(cwd)
        try:
            if candidate.is_absolute() and candidate.resolve(strict=False) == canonical_root:
                return True
        except (OSError, RuntimeError, ValueError):
            continue
    return False


def scan_claude(source: Path, root: Path, *, project_slug: str) -> ScanResult:
    if source.parent.name != "projects" or source.name != project_slug:
        return scan_exports(source, root)
    result = ScanResult()
    if source.is_symlink() or not source.is_dir():
        return result
    for path in source.rglob("*"):
        if path.suffix.casefold() != ".jsonl" or not path.is_file() or path.is_symlink():
            continue
        if not _owned_header(path, root):
            result.skipped_unverified += 1
            continue
        body = read_session_bytes(path)
        if body is None:
            result.skipped_unverified += 1
        else:
            result.sessions.append((path, body))
    return result
