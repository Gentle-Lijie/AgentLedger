"""Bounded, read-only exports from known ZCode and Hermes session schemas.

ZCode's session/directory and message/part layout is documented by observed
ZCode 3.x schema: https://github.com/wilbeibi/catchup/tree/main/internal/zcode
Hermes defines sessions/messages in its own schema:
https://github.com/NousResearch/hermes-agent/blob/main/hermes_state_common.py
Unknown layouts are deliberately not searched for path strings.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path

from .common import ScanResult, belongs_to_repo


MAX_DATABASE_BYTES = 1024 * 1024 * 1024
MAX_SCANNED_SESSIONS = 10_000
MAX_EXPORTED_SESSIONS = 128
MAX_MESSAGES_PER_SESSION = 1_000
MAX_PARTS_PER_SESSION = 2_000
MAX_SESSION_BYTES = 5 * 1024 * 1024
MAX_OUTPUT_BYTES = 50 * 1024 * 1024


def _columns(db: sqlite3.Connection, table: str) -> set[str]:
    # Table names are constants chosen by the adapter, never database data.
    return {row[1] for row in db.execute(f'PRAGMA table_info("{table}")')}


def _schema_is_supported(db: sqlite3.Connection, agent: str) -> bool:
    names = {row[0] for row in db.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' LIMIT 256"
    )}
    if agent == "zcode":
        required = {
            "session": {"id", "directory"},
            "message": {"id", "session_id", "data"},
            "part": {"id", "message_id", "session_id", "data"},
        }
    else:
        required = {
            "sessions": {"id"},
            "messages": {"id", "session_id", "role", "content"},
        }
    if not required.keys() <= names:
        return False
    if agent == "hermes" and not {"cwd", "git_repo_root"} & _columns(db, "sessions"):
        return False
    return all(columns <= _columns(db, table) for table, columns in required.items())


def _source_ok(source: Path) -> bool:
    try:
        return (not source.is_symlink() and source.is_file()
                and 0 < source.stat().st_size <= MAX_DATABASE_BYTES)
    except OSError:
        return False


def _record_bytes(value: dict[str, object]) -> bytes:
    return (json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")


def _virtual_path(source: Path) -> Path:
    # Keep the legacy SQLite export path to preserve existing fingerprints.
    return source.with_name(source.name + ".project-sessions.jsonl")


def _owned_hermes(cwd: object, git_repo_root: object, root: Path) -> bool:
    # A recorded Git root is authoritative. A conflicting cwd cannot reassign
    # another repository's session to this one.
    if isinstance(git_repo_root, str) and git_repo_root:
        if not belongs_to_repo(git_repo_root, root):
            return False
        return not cwd or belongs_to_repo(cwd, root)
    return belongs_to_repo(cwd, root)


def _export_hermes(db: sqlite3.Connection, source: Path, root: Path) -> ScanResult:
    result = ScanResult()
    columns = _columns(db, "sessions")
    cwd = '"cwd"' if "cwd" in columns else "NULL"
    git_root = '"git_repo_root"' if "git_repo_root" in columns else "NULL"
    title = '"title"' if "title" in columns else "NULL"
    sessions = db.execute(
        f'SELECT "id", {cwd}, {git_root}, {title} FROM "sessions" '
        f'ORDER BY "id" LIMIT {MAX_SCANNED_SESSIONS + 1}'
    ).fetchall()
    if len(sessions) > MAX_SCANNED_SESSIONS:
        result.skipped_unverified += 1
    output = bytearray()
    exported_count = 0
    for session_id, session_cwd, session_root, session_title in sessions[:MAX_SCANNED_SESSIONS]:
        if not _owned_hermes(session_cwd, session_root, root):
            continue
        if exported_count >= MAX_EXPORTED_SESSIONS:
            result.skipped_unverified += 1
            break
        if not isinstance(session_id, (str, int)):
            result.skipped_unverified += 1
            continue
        payload = bytearray(_record_bytes({
            "table": "sessions", "record": {"id": session_id,
                "cwd": session_cwd, "git_repo_root": session_root,
                "title": session_title if isinstance(session_title, str) else None},
        }))
        rows = db.execute(
            'SELECT "id", "role", "content" FROM "messages" '
            'WHERE "session_id" = ? ORDER BY "id" LIMIT ?',
            (session_id, MAX_MESSAGES_PER_SESSION + 1),
        ).fetchall()
        if len(rows) > MAX_MESSAGES_PER_SESSION:
            result.skipped_unverified += 1
            continue
        valid = True
        for message_id, role, content in rows:
            if not isinstance(role, str) or not isinstance(content, (str, type(None))):
                valid = False
                break
            payload.extend(_record_bytes({"table": "messages", "record": {
                "id": message_id, "session_id": session_id,
                "role": role, "content": content,
            }}))
            if len(payload) > MAX_SESSION_BYTES:
                valid = False
                break
        if not valid or len(output) + len(payload) > MAX_OUTPUT_BYTES:
            result.skipped_unverified += 1
            continue
        output.extend(payload)
        exported_count += 1
    if output:
        result.sessions.append((_virtual_path(source), bytes(output)))
    return result


def _zcode_text(data: object) -> str | None:
    if not isinstance(data, str):
        return None
    try:
        part = json.loads(data)
    except (ValueError, UnicodeError):
        return None
    if not isinstance(part, dict) or part.get("type") != "text":
        return None
    return part.get("text") if isinstance(part.get("text"), str) else None


def _zcode_role(data: object) -> str | None:
    if not isinstance(data, str):
        return None
    try:
        message = json.loads(data)
    except (ValueError, UnicodeError):
        return None
    role = message.get("role") if isinstance(message, dict) else None
    return role if role in {"user", "assistant", "system"} else None


def _export_zcode(db: sqlite3.Connection, source: Path, root: Path) -> ScanResult:
    result = ScanResult()
    columns = _columns(db, "session")
    message_columns = _columns(db, "message")
    part_columns = _columns(db, "part")
    title = '"title"' if "title" in columns else "NULL"
    message_order = '"sequence", "id"' if "sequence" in message_columns else '"id"'
    part_order = '"time_created", "id"' if "time_created" in part_columns else '"id"'
    sessions = db.execute(
        f'SELECT "id", "directory", {title} FROM "session" '
        f'ORDER BY "id" LIMIT {MAX_SCANNED_SESSIONS + 1}'
    ).fetchall()
    if len(sessions) > MAX_SCANNED_SESSIONS:
        result.skipped_unverified += 1
    output = bytearray()
    exported_count = 0
    for session_id, directory, session_title in sessions[:MAX_SCANNED_SESSIONS]:
        if not belongs_to_repo(directory, root):
            continue
        if exported_count >= MAX_EXPORTED_SESSIONS:
            result.skipped_unverified += 1
            break
        if not isinstance(session_id, (str, int)):
            result.skipped_unverified += 1
            continue
        payload = bytearray(_record_bytes({"table": "session", "record": {
            "id": session_id, "directory": directory,
            "title": session_title if isinstance(session_title, str) else None,
        }}))
        messages = db.execute(
            'SELECT "id", "data" FROM "message" WHERE "session_id" = ? '
            f'ORDER BY {message_order} LIMIT ?',
            (session_id, MAX_MESSAGES_PER_SESSION + 1),
        ).fetchall()
        if len(messages) > MAX_MESSAGES_PER_SESSION:
            result.skipped_unverified += 1
            continue
        valid = True
        part_count = 0
        for message_id, message_data in messages:
            role = _zcode_role(message_data)
            if role is None:
                valid = False
                break
            parts = db.execute(
                'SELECT "id", "data" FROM "part" WHERE "session_id" = ? '
                f'AND "message_id" = ? ORDER BY {part_order} LIMIT ?',
                (session_id, message_id, MAX_PARTS_PER_SESSION - part_count + 1),
            ).fetchall()
            part_count += len(parts)
            if part_count > MAX_PARTS_PER_SESSION:
                valid = False
                break
            texts = [text for _, data in parts if (text := _zcode_text(data)) is not None]
            payload.extend(_record_bytes({"table": "message", "record": {
                "id": message_id, "session_id": session_id,
                "role": role, "text": "\n".join(texts),
            }}))
            if len(payload) > MAX_SESSION_BYTES:
                valid = False
                break
        if not valid or len(output) + len(payload) > MAX_OUTPUT_BYTES:
            result.skipped_unverified += 1
            continue
        output.extend(payload)
        exported_count += 1
    if output:
        result.sessions.append((_virtual_path(source), bytes(output)))
    return result


def _scan(source: Path, root: Path, agent: str) -> ScanResult:
    skipped = ScanResult(skipped_unverified=1)
    if not _source_ok(source):
        return skipped
    try:
        # mode=ro prevents creation of a missing DB and all writes to the DB.
        # query_only also guards against an accidental future write statement.
        with closing(sqlite3.connect(source.resolve().as_uri() + "?mode=ro",
                                     uri=True, timeout=2)) as db:
            db.execute("PRAGMA query_only=ON")
            if hasattr(db, "setlimit"):
                db.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, MAX_SESSION_BYTES)
            db.set_progress_handler(lambda: 1, 2_000_000)
            if not _schema_is_supported(db, agent):
                return skipped
            return (_export_zcode(db, source, root) if agent == "zcode"
                    else _export_hermes(db, source, root))
    except (sqlite3.Error, OSError, ValueError, RuntimeError):
        return skipped


def scan_zcode(source: Path, root: Path) -> ScanResult:
    """Export verified ZCode sessions and their related text parts."""
    return _scan(source, root, "zcode")


def scan_hermes(source: Path, root: Path) -> ScanResult:
    """Export verified Hermes sessions and their related messages."""
    return _scan(source, root, "hermes")
