from __future__ import annotations

import hashlib
import json
import os
import shlex
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import shutil
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, unquote, urlparse

AGENTS = {
    "zcode": "ZCode",
    "qoder": "Qoder",
    "trae": "Trae",
    "codebuddy": "Tencent CodeBuddy",
    "claude": "Claude Code",
    "codex": "OpenAI Codex CLI",
    "copilot": "GitHub Copilot CLI",
    "hermes": "Hermes Agent",
    "pi": "Pi Coding Agent",
    "deepseek-harness": "DeepSeek Harness",
    "custom": "Custom agent",
}
HOOK_BEGIN = "# >>> agent-session-commit >>>"
HOOK_END = "# <<< agent-session-commit <<<"
TEXT_SUFFIXES = {".jsonl", ".json", ".md", ".txt", ".yaml", ".yml"}
COMPRESSED_SUFFIXES = {".zst", ".zstd"}
MAX_FILE_SIZE = 50 * 1024 * 1024
MAX_DATABASE_SIZE = 1024 * 1024 * 1024


def default_source(agent: str) -> Path | None:
    home = Path.home()
    if agent == "zcode":
        storage_override = os.environ.get("ZCODE_STORAGE_DIR")
        data_override = os.environ.get("ZCODE_DATA_BASE_DIR")
        if storage_override:
            base = Path(storage_override).expanduser()
        elif data_override:
            base = Path(data_override).expanduser() / ".zcode"
        else:
            base = home / ".zcode"
        candidates = [base / "cli" / "db" / "db.sqlite", base / "cli" / "db.sqlite"]
        return next((path for path in candidates if path.is_file()), candidates[0])
    if agent == "qoder":
        base = Path(os.environ.get("QODER_CONFIG_DIR", home / ".qoder")).expanduser()
        return base / "projects"
    if agent == "codebuddy":
        base = Path(os.environ.get("CODEBUDDY_CONFIG_DIR", home / ".codebuddy")).expanduser()
        return base / "projects"
    if agent == "claude":
        base = Path(os.environ.get("CLAUDE_CONFIG_DIR", home / ".claude")).expanduser()
        return base / "projects"
    if agent == "codex":
        base = Path(os.environ.get("CODEX_HOME", home / ".codex")).expanduser()
        return base / "sessions"
    if agent == "copilot":
        base = Path(os.environ.get("COPILOT_HOME", home / ".copilot")).expanduser()
        return base / "session-state"
    if agent == "hermes":
        base = Path(os.environ.get("HERMES_HOME", home / ".hermes")).expanduser()
        return base / "state.db"
    if agent == "pi":
        base = Path(os.environ.get("PI_CODING_AGENT_DIR", home / ".pi" / "agent")).expanduser()
        return base / "sessions"
    if agent == "deepseek-harness":
        return Path(os.environ.get("DSH_HOME", home / ".dsh")).expanduser()
    return None


def _git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)
    if check and result.returncode:
        raise RuntimeError(result.stderr.strip() or f"git {' '.join(args)} failed")
    return result


def _git_path(root: Path, name: str) -> Path:
    path = Path(_git(root, "rev-parse", "--git-path", name).stdout.strip())
    return (path if path.is_absolute() else root / path).resolve()


def _config(root: Path, key: str) -> str | None:
    result = _git(root, "config", "--local", "--get", key, check=False)
    return result.stdout.strip() if result.returncode == 0 else None


def _shell_path(path: Path) -> str:
    value = str(path)
    if os.name == "nt":
        value = value.replace("\\", "/")
        if len(value) >= 3 and value[1:3] == ":/":
            value = f"/{value[0].lower()}{value[2:]}"
    return value


def configure(root: Path, agent: str, source: Path) -> None:
    _git(root, "config", "--local", "agent-session.agent", agent)
    _git(root, "config", "--local", "agent-session.source", str(source))
    for hook_name in ("pre-commit", "post-commit"):
        hook_path = _git_path(root, f"hooks/{hook_name}")
        hook_path.parent.mkdir(parents=True, exist_ok=True)
        backup = _git_path(root, f"agent-session-commit/original-hooks/{hook_name}")
        if hook_path.exists() and HOOK_BEGIN not in hook_path.read_text(encoding="utf-8", errors="replace"):
            backup.parent.mkdir(parents=True, exist_ok=True)
            if backup.exists():
                raise RuntimeError(f"An original-hook backup already exists: {backup}")
            shutil.copy2(hook_path, backup)
        backup_shell = shlex.quote(_shell_path(backup))
        original_call = f"if [ -x {backup_shell} ]; then\n  {backup_shell} \"$@\"\n  ORIGINAL_STATUS=$?\n  if [ \"$ORIGINAL_STATUS\" -ne 0 ] && [ \"{hook_name}\" = \"pre-commit\" ]; then exit \"$ORIGINAL_STATUS\"; fi\nfi\n" if backup.exists() else ""
        invocation = (
            f"  {shlex.quote(_shell_path(Path(sys.executable)))} -m agentledger.cli hook {hook_name}\n"
        )
        managed_call = (
            f"{HOOK_BEGIN}\n"
            f'if [ "${{AGENT_SESSION_COMMIT_RECURSION:-0}}" != "1" ]; then\n'
            f"{invocation}"
            "fi\n"
            f"{HOOK_END}\n"
        )
        # Other post-commit integrations should observe the final amended HEAD.
        body = managed_call + original_call if hook_name == "post-commit" else original_call + managed_call
        wrapper = "#!/bin/sh\n" + body
        hook_path.write_text(wrapper, encoding="utf-8", newline="\n")
        hook_path.chmod(hook_path.stat().st_mode | 0o111)


def _remove_hook_section(contents: str) -> str:
    start = contents.find(HOOK_BEGIN)
    if start < 0:
        return contents
    end = contents.find(HOOK_END, start)
    if end < 0:
        raise RuntimeError("Found an incomplete managed hook section; refusing to edit it.")
    end += len(HOOK_END)
    return contents[:start] + contents[end:]


def uninstall(root: Path) -> None:
    for hook_name in ("pre-commit", "post-commit"):
        hook_path = _git_path(root, f"hooks/{hook_name}")
        backup = _git_path(root, f"agent-session-commit/original-hooks/{hook_name}")
        if backup.exists():
            hook_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(backup, hook_path)
            backup.unlink()
        elif hook_path.exists() and HOOK_BEGIN in hook_path.read_text(encoding="utf-8", errors="replace"):
            hook_path.unlink()
    _git(root, "config", "--local", "--unset", "agent-session.agent", check=False)
    _git(root, "config", "--local", "--unset", "agent-session.source", check=False)


def _session_candidates(source: Path, root: Path) -> list[tuple[Path, bytes]]:
    root_forms = {
        str(root).replace("\\", "/").casefold(),
        str(root).replace("/", "\\").casefold(),
        quote(str(root).replace("\\", "/"), safe="").casefold(),
        json.dumps(str(root), ensure_ascii=False)[1:-1].casefold(),
        root.as_uri().casefold(),
        str(root).replace("/", "-").replace("\\", "-").casefold(),
    }
    found: list[tuple[Path, bytes]] = []
    def matching(payload: bytes) -> bool:
        if b"\x00" in payload:
            return False
        raw_text = payload.decode("utf-8", errors="ignore")
        text = raw_text.casefold()
        if any(form and form in text for form in root_forms):
            return True

        def contains_root(value: object) -> bool:
            if isinstance(value, dict):
                return any(contains_root(item) for item in value.values())
            if isinstance(value, list):
                return any(contains_root(item) for item in value)
            if not isinstance(value, str):
                return False
            candidate_text = value.strip()
            if candidate_text.casefold().startswith("file://"):
                candidate_text = unquote(urlparse(candidate_text).path)
            candidate = Path(candidate_text).expanduser()
            try:
                return candidate.is_absolute() and candidate.resolve(strict=False) == root
            except (OSError, RuntimeError):
                return False

        for line in raw_text.splitlines():
            try:
                if contains_root(json.loads(line)):
                    return True
            except json.JSONDecodeError:
                continue
        return False

    def sqlite_project_export(path: Path) -> bytes | None:
        uri = path.resolve().as_uri() + "?mode=ro"
        records: list[str] = []
        try:
            with sqlite3.connect(uri, uri=True, timeout=2) as db:
                tables = db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
                table_names = {name for (name,) in tables}
                if _config(root, "agent-session.agent") == "hermes" and {"sessions", "messages"}.issubset(table_names):
                    session_columns = [row[1] for row in db.execute('PRAGMA table_info("sessions")')]
                    message_columns = [row[1] for row in db.execute('PRAGMA table_info("messages")')]
                    if "id" in session_columns and "session_id" in message_columns:
                        session_projection = ", ".join('"' + col.replace('"', '""') + '"' for col in session_columns)
                        message_projection = ", ".join('"' + col.replace('"', '""') + '"' for col in message_columns)
                        for values in db.execute(f'SELECT {session_projection} FROM "sessions"'):
                            session = dict(zip(session_columns, values))
                            serialized = json.dumps(session, ensure_ascii=False, default=str)
                            if not any(form and form in serialized.casefold() for form in root_forms):
                                continue
                            records.append(json.dumps({"table": "sessions", "record": session}, ensure_ascii=False, default=str))
                            for message_values in db.execute(
                                f'SELECT {message_projection} FROM "messages" WHERE "session_id" = ?',
                                (session["id"],),
                            ):
                                message = dict(zip(message_columns, message_values))
                                records.append(json.dumps({"table": "messages", "record": message}, ensure_ascii=False, default=str))
                        if records:
                            return ("\n".join(records) + "\n").encode("utf-8")
                for (table,) in tables:
                    if table.startswith("sqlite_"):
                        continue
                    quoted_table = '"' + table.replace('"', '""') + '"'
                    columns = [row[1] for row in db.execute(f"PRAGMA table_info({quoted_table})")]
                    if not columns:
                        continue
                    quoted_columns = ", ".join('"' + name.replace('"', '""') + '"' for name in columns)
                    try:
                        rows = db.execute(f"SELECT {quoted_columns} FROM {quoted_table}")
                        for row in rows:
                            serializable = [value.decode("utf-8", "ignore") if isinstance(value, bytes) else value for value in row]
                            record = {"table": table, "columns": columns, "values": serializable}
                            raw = json.dumps(record, ensure_ascii=False, default=str)
                            if matching(raw.encode("utf-8")):
                                records.append(raw)
                    except sqlite3.DatabaseError:
                        continue
        except (sqlite3.DatabaseError, OSError):
            return None
        if not records:
            return None
        return ("\n".join(records) + "\n").encode("utf-8")

    try:
        paths = [source] if source.is_file() else source.rglob("*")
        for path in paths:
            if not path.is_file():
                continue
            try:
                suffix = path.suffix.casefold()
                limit = MAX_DATABASE_SIZE if suffix in {".db", ".sqlite", ".sqlite3"} else MAX_FILE_SIZE
                if path.stat().st_size > limit:
                    continue
            except OSError:
                continue
            if suffix in {".db", ".sqlite", ".sqlite3"} and _config(root, "agent-session.agent") in {"zcode", "hermes"}:
                payload = sqlite_project_export(path)
                if payload:
                    virtual_path = path.with_name(path.name + ".project-sessions.jsonl")
                    found.append((virtual_path, payload))
            elif suffix in TEXT_SUFFIXES:
                payload = path.read_bytes()
                encoded_root = str(root).replace("/", "-").replace("\\", "-").casefold()
                path_text = str(path).replace("\\", "/").casefold()
                if matching(payload) or (encoded_root and encoded_root in path_text):
                    found.append((path, payload))
            elif suffix in COMPRESSED_SUFFIXES and _config(root, "agent-session.agent") == "deepseek-harness":
                try:
                    import zstandard
                except ImportError:
                    continue
                try:
                    # Harness appends separate checksummed frames, so decode
                    # across all frames while bounding decompressed input.
                    with path.open("rb") as raw, zstandard.ZstdDecompressor().stream_reader(
                        raw, read_across_frames=True
                    ) as reader:
                        payload = reader.read(MAX_FILE_SIZE + 1)
                except (OSError, zstandard.ZstdError):
                    continue
                if len(payload) > MAX_FILE_SIZE:
                    continue
                if matching(payload):
                    virtual_path = path.with_name(path.name + ".decompressed.jsonl")
                    found.append((virtual_path, payload))
    except OSError:
        return []
    return found


def _state_file(root: Path) -> Path:
    return _git_path(root, "agent-session-commit/state.json")


def _load_state(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _write_bundle(root: Path, source: Path, sessions: list[tuple[Path, bytes]]) -> tuple[Path | None, dict[str, object]]:
    state_path = _state_file(root)
    previous = _load_state(state_path)
    source_base = source.parent if source.is_file() else source
    changed: list[tuple[Path, bytes, str, int, int, str, str]] = []
    updated = dict(previous)
    for path, payload in sessions:
        rel = path.relative_to(source_base).as_posix()
        digest = hashlib.sha256(payload).hexdigest()
        prior = previous.get(rel)
        if isinstance(prior, str):  # migrate the first release's digest-only state
            if prior == digest:
                continue
            old_size = 0
            old_prefix = ""
        elif isinstance(prior, dict):
            if prior.get("sha256") == digest:
                continue
            try:
                old_size = int(prior.get("size", 0))
            except (TypeError, ValueError):
                old_size = 0
            old_prefix = str(prior.get("prefix_sha256", ""))
        else:
            old_size = 0
            old_prefix = ""
        append_only = (
            0 < old_size <= len(payload)
            and bool(old_prefix)
            and hashlib.sha256(payload[:old_size]).hexdigest() == old_prefix
        )
        offset = old_size if append_only else 0
        chunk = payload[offset:]
        if not chunk:
            continue
        mode = "append" if append_only else "full"
        changed.append((path, chunk, rel, offset, len(payload), digest, mode))
        updated[rel] = {
            "size": len(payload),
            "sha256": digest,
            "prefix_sha256": hashlib.sha256(payload).hexdigest(),
        }
    if not changed:
        return None, updated

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    bundle_dir = root / ".agent-sessions" / "bundles"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    bundle = bundle_dir / f"{timestamp}-{os.getpid()}-{__import__('time').time_ns()}.tar.gz"
    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "agent": _config(root, "agent-session.agent") or "custom",
        "repository": str(root),
        "files": [
            {
                "path": rel,
                "mode": mode,
                "offset": offset,
                "result_size": size,
                "result_sha256": digest,
                "chunk_sha256": hashlib.sha256(data).hexdigest(),
            }
            for _, data, rel, offset, size, digest, mode in changed
        ],
    }
    with tarfile.open(bundle, "w:gz") as archive:
        for _, payload, rel, offset, _, _, mode in changed:
            info = tarfile.TarInfo(f"sessions/{rel}")
            if mode == "append":
                info.pax_headers = {"AGENT_SESSION_COMMIT.offset": str(offset), "AGENT_SESSION_COMMIT.mode": mode}
            info.size = len(payload)
            info.mtime = int(datetime.now().timestamp())
            import io

            archive.addfile(info, io.BytesIO(payload))
        raw_manifest = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")
        info = tarfile.TarInfo("manifest.json")
        info.size = len(raw_manifest)
        archive.addfile(info, __import__("io").BytesIO(raw_manifest))
    return bundle, updated


def _scan(root: Path) -> list[tuple[Path, bytes]]:
    configured = _config(root, "agent-session.source")
    if not configured:
        raise RuntimeError("Not installed. Run `agentledger install` first.")
    source = Path(configured).expanduser().resolve()
    if not source.exists():
        raise RuntimeError(f"Configured session source is unavailable: {source}")
    if not source.is_dir() and source.suffix.casefold() not in {".db", ".sqlite", ".sqlite3"}:
        raise RuntimeError(f"Configured session source is not a directory or SQLite file: {source}")
    return _session_candidates(source, root)


def status(root: Path) -> None:
    agent = _config(root, "agent-session.agent")
    source = _config(root, "agent-session.source")
    if not agent or not source:
        print("AgentLedger is not installed in this repository.")
        return
    sessions = _scan(root)
    source_path = Path(source).resolve()
    source_base = source_path.parent if source_path.is_file() else source_path
    state = _load_state(_state_file(root))
    def digest_matches(entry: object, digest: str) -> bool:
        if isinstance(entry, dict):
            return entry.get("sha256") == digest
        return entry == digest

    pending = sum(
        1 for path, payload in sessions
        if not digest_matches(state.get(path.relative_to(source_base).as_posix()), hashlib.sha256(payload).hexdigest())
    )
    print(f"Agent: {AGENTS.get(agent, agent)}")
    print(f"Source: {source}")
    print(f"Project session files found: {len(sessions)} ({pending} changed)")


def run_hook(root: Path, hook_name: str) -> int:
    if hook_name == "pre-commit":
        return 0
    try:
        sessions = _scan(root)
    except RuntimeError as exc:
        print(f"agentledger: {exc}", file=sys.stderr)
        return 0
    configured = _config(root, "agent-session.source")
    source = Path(configured).expanduser().resolve() if configured else root
    state_path = _state_file(root)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = state_path.with_suffix(".lock")
    try:
        lock_fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        print("agentledger: another archive operation is active; skipping.", file=sys.stderr)
        return 0
    os.close(lock_fd)
    bundle: Path | None = None
    index_path: Path | None = None
    try:
        original_commit = _git(root, "rev-parse", "HEAD").stdout.strip()
        bundle, updated = _write_bundle(root, source, sessions)
        if bundle is None:
            return 0
        index_fd, index_name = tempfile.mkstemp(prefix="index-", dir=state_path.parent)
        os.close(index_fd)
        index_path = Path(index_name)
        env = os.environ.copy()
        env["GIT_INDEX_FILE"] = str(index_path)
        subprocess.run(["git", "-C", str(root), "read-tree", original_commit], env=env, check=True, capture_output=True, text=True)
        subprocess.run(["git", "-C", str(root), "add", "--", str(bundle.relative_to(root))], env=env, check=True, capture_output=True, text=True)
        diff = subprocess.run(["git", "-C", str(root), "diff", "--cached", "--quiet"], env=env)
        if diff.returncode == 0:
            bundle.unlink(missing_ok=True)
            return 0
        if diff.returncode != 1:
            raise RuntimeError("Unable to inspect the archive amend index.")
        if _git(root, "rev-parse", "HEAD").stdout.strip() != original_commit:
            raise RuntimeError("HEAD changed during archiving; leaving that commit untouched.")
        env["AGENT_SESSION_COMMIT_RECURSION"] = "1"
        original_object = subprocess.run(
            ["git", "-C", str(root), "cat-file", "commit", original_commit],
            capture_output=True,
            check=True,
        ).stdout
        headers = original_object.split(b"\n\n", 1)[0]
        signed = any(line.startswith((b"gpgsig ", b"gpgsig-sha256 ")) for line in headers.splitlines())
        # Checks already ran on the user's commit. Avoid invoking hooks again,
        # including integrations that push or notify on post-commit/post-rewrite.
        with tempfile.TemporaryDirectory(prefix="amend-hooks-", dir=state_path.parent) as empty_hooks:
            result = subprocess.run(
                ["git", "-C", str(root), "-c", f"core.hooksPath={empty_hooks}",
                 "commit", "--amend", "--no-edit", "--cleanup=verbatim",
                 "--allow-empty-message", "--no-verify", "--no-post-rewrite", "--quiet",
                 "--gpg-sign" if signed else "--no-gpg-sign"],
                env=env,
                capture_output=True,
                text=True,
            )
        if result.returncode == 0:
            # HEAD now includes the bundle; refresh just that path in the user's
            # index so it is not shown as a staged deletion after the amend.
            user_index_env = os.environ.copy()
            try:
                subprocess.run(
                    ["git", "-C", str(root), "add", "--", str(bundle.relative_to(root))],
                    env=user_index_env,
                    check=True,
                    capture_output=True,
                    text=True,
                )
            except subprocess.SubprocessError as exc:
                print(f"agentledger: archive amended, but index refresh failed: {exc}", file=sys.stderr)
            state_path.write_text(json.dumps(updated, indent=2, sort_keys=True), encoding="utf-8")
            final_commit = _git(root, "rev-parse", "--short", "HEAD").stdout.strip()
            print(f"agentledger: session archive added to commit {final_commit}", file=sys.stderr)
        else:
            raise RuntimeError(result.stderr.strip() or "Git could not amend the commit.")
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        if bundle is not None and not _git(root, "cat-file", "-e", f"HEAD:{bundle.relative_to(root)}", check=False).returncode == 0:
            bundle.unlink(missing_ok=True)
        print(f"agentledger: archive amend skipped: {exc}", file=sys.stderr)
    finally:
        if index_path is not None:
            index_path.unlink(missing_ok=True)
        lock_path.unlink(missing_ok=True)
    return 0
