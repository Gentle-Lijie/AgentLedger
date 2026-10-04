from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import tarfile
import tempfile
import shutil
from datetime import datetime, timezone
from pathlib import Path

AGENTS = {
    "zcode": "ZCode",
    "qoder": "Qoder",
    "trae": "Trae",
    "codebuddy": "Tencent CodeBuddy",
    "claude": "Claude Code",
    "codex": "OpenAI Codex CLI",
    "copilot": "GitHub Copilot CLI",
    "copilot-vscode": "GitHub Copilot VSCode",
    "hermes": "Hermes Agent",
    "pi": "Pi Coding Agent",
    "deepseek-harness": "DeepSeek Harness",
    "custom": "Custom agent",
}
HOOK_BEGIN = "# >>> agent-session-commit >>>"
HOOK_END = "# <<< agent-session-commit <<<"


def claude_project_source(root: Path, projects_root: Path | None = None) -> Path:
    """Claude Code's project directory for this checkout, even before it exists."""
    projects = projects_root or default_source("claude")
    assert projects is not None
    # Claude encodes the absolute cwd using one dash per non-ASCII-alphanumeric
    # character (including separators, drive colon, dots and spaces).
    slug = re.sub(r"[^A-Za-z0-9]", "-", str(root.resolve()))
    return projects / slug


def default_source(agent: str, root: Path | None = None) -> Path | None:
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
        projects = base / "projects"
        return claude_project_source(root, projects) if root is not None else projects
    if agent == "codex":
        base = Path(os.environ.get("CODEX_HOME", home / ".codex")).expanduser()
        return base / "sessions"
    if agent == "copilot":
        base = Path(os.environ.get("COPILOT_HOME", home / ".copilot")).expanduser()
        return base / "session-state"
    if agent == "copilot-vscode":
        override = os.environ.get("COPILOT_VSCODE_HOME")
        if override:
            base = Path(override).expanduser()
        elif os.name == "nt":
            base = Path(os.environ.get("APPDATA", home / "AppData" / "Roaming")) / "Code" / "User"
        elif sys.platform == "darwin":
            base = home / "Library" / "Application Support" / "Code" / "User"
        else:
            base = home / ".config" / "Code" / "User"
        return base / "workspaceStorage"
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
    result = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, encoding="utf-8",
    )
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


def save_configuration(root: Path, agent: str, source: Path) -> None:
    # Git executes hooks from the repository root, regardless of the shell
    # directory from which the user invoked git commit.
    workdir = root.resolve()
    _git(root, "config", "--local", "agent-session.agent", agent)
    _git(root, "config", "--local", "agent-session.source", str(source))
    _git(root, "config", "--local", "agent-session.workdir", str(workdir))


def configure(root: Path, agent: str, source: Path) -> None:
    save_configuration(root, agent, source)
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
            f"  {shlex.quote(_shell_path(Path(sys.executable)))} -m agent_session_commit.cli hook {hook_name}\n"
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
    _git(root, "config", "--local", "--unset", "agent-session.workdir", check=False)


def _state_file(root: Path) -> Path:
    return _git_path(root, "agent-session-commit/state.json")


def _load_state(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _legacy_claude_prefix(root: Path, source: Path) -> str:
    # Legacy Claude installs used the projects root, so their state keys
    # include the project slug. Reusing those fingerprints avoids re-archiving
    # an unchanged transcript when the installer switches to a scoped source.
    if (_config(root, "agent-session.agent") == "claude"
        and source.parent.name == "projects"
        and source.name == claude_project_source(root).name):
        return source.name + "/"
    return ""


def _write_bundle(root: Path, source: Path, sessions: list[tuple[Path, bytes]]) -> tuple[Path | None, dict[str, object]]:
    state_path = _state_file(root)
    previous = _load_state(state_path)
    source_base = source.parent if source.is_file() else source
    legacy_claude_prefix = _legacy_claude_prefix(root, source)
    changed: list[tuple[Path, bytes, str, int, int, str, str]] = []
    updated = dict(previous)
    for path, payload in sessions:
        rel = path.relative_to(source_base).as_posix()
        digest = hashlib.sha256(payload).hexdigest()
        prior = previous.get(rel)
        if prior is None and legacy_claude_prefix:
            prior = previous.get(legacy_claude_prefix + rel)
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


def _effective_source(root: Path, agent: str | None, source: Path) -> Path:
    """Narrow legacy Claude installs that saved the entire projects root."""
    if agent == "claude":
        default_projects = default_source("claude")
        if (default_projects is not None and source == default_projects.resolve()) or (
            source.name == "projects" and source.parent.name == ".claude"
        ):
            return claude_project_source(root, source)
    return source


def _scan(root: Path, *, report_skips: bool = False) -> list[tuple[Path, bytes]]:
    configured = _config(root, "agent-session.source")
    if not configured:
        raise RuntimeError("Not installed. Run `agent-session-commit install` first.")
    agent = _config(root, "agent-session.agent")
    configured_workdir = _config(root, "agent-session.workdir")
    if configured_workdir:
        workdir = Path(configured_workdir).expanduser()
        if not workdir.is_absolute() or workdir.resolve() != root.resolve():
            raise RuntimeError(
                "Configured work directory does not match this Git repository. "
                "Run `agent-session-commit install` again in this checkout."
            )
    # Legacy installations have no explicit key; the containing Git root is
    # still the only admissible work directory.
    workdir = root.resolve()
    source = _effective_source(root, agent, Path(configured).expanduser().resolve())
    if not source.exists():
        if agent == "claude" and source.parent.name == "projects" and source.name == claude_project_source(root).name:
            # Claude creates this directory only after its first session.
            return []
        raise RuntimeError(f"Configured session source is unavailable: {source}")
    if not source.is_dir() and source.suffix.casefold() not in {".db", ".sqlite", ".sqlite3"}:
        raise RuntimeError(f"Configured session source is not a directory or SQLite file: {source}")
    if agent == "claude":
        from .adapters.claude import scan_claude
        result = scan_claude(source, workdir, project_slug=claude_project_source(workdir).name)
    elif agent in {"custom", "trae"}:
        from .adapters.exports import scan_exports
        result = scan_exports(source, workdir)
    elif agent == "codex":
        from .adapters.codex_copilot import scan_codex
        result = scan_codex(source, workdir,
                            cache_path=_git_path(root, "agent-session-commit/codex-candidates.json"))
    elif agent == "copilot":
        from .adapters.codex_copilot import scan_copilot
        result = scan_copilot(source, workdir)
    elif agent == "copilot-vscode":
        from .adapters.codex_copilot import scan_copilot_vscode
        result = scan_copilot_vscode(source, workdir)
    elif agent == "zcode":
        from .adapters.sqlite_agents import scan_zcode
        result = scan_zcode(source, workdir)
    elif agent == "hermes":
        from .adapters.sqlite_agents import scan_hermes
        result = scan_hermes(source, workdir)
    elif agent == "pi":
        from .adapters.pi_deepseek import scan_pi
        result = scan_pi(source, workdir)
    elif agent == "deepseek-harness":
        from .adapters.pi_deepseek import scan_deepseek
        result = scan_deepseek(source, workdir)
    elif agent == "qoder":
        from .adapters.qoder_codebuddy import scan_qoder
        result = scan_qoder(source, workdir)
    elif agent == "codebuddy":
        from .adapters.qoder_codebuddy import scan_codebuddy
        result = scan_codebuddy(source, workdir)
    else:
        raise RuntimeError(f"Unknown configured agent: {agent!r}")
    if report_skips and result.skipped_unverified:
        print(f"agent-session-commit: ignored {result.skipped_unverified} other-project or unverifiable session candidate(s).",
              file=sys.stderr)
    return result.sessions


def status(root: Path) -> None:
    agent = _config(root, "agent-session.agent")
    source = _config(root, "agent-session.source")
    if not agent or not source:
        print("Agent Session Commit is not installed in this repository.")
        return
    sessions = _scan(root, report_skips=True)
    source_path = Path(source).resolve()
    effective_source = _effective_source(root, agent, source_path)
    source_base = source_path.parent if source_path.is_file() else source_path
    legacy_claude_prefix = _legacy_claude_prefix(root, source_path)
    state = _load_state(_state_file(root))
    def digest_matches(entry: object, digest: str) -> bool:
        if isinstance(entry, dict):
            return entry.get("sha256") == digest
        return entry == digest

    pending = 0
    for path, payload in sessions:
        rel = path.relative_to(source_base).as_posix()
        prior = state.get(rel)
        if prior is None and legacy_claude_prefix:
            prior = state.get(legacy_claude_prefix + rel)
        if not digest_matches(prior, hashlib.sha256(payload).hexdigest()):
            pending += 1
    print(f"Agent: {AGENTS.get(agent, agent)}")
    print(f"Work directory: {root.resolve()}")
    print(f"Source: {effective_source}")
    print(f"Project session files found: {len(sessions)} ({pending} changed)")


def run_hook(root: Path, hook_name: str) -> int:
    if hook_name == "pre-commit":
        return 0
    try:
        sessions = _scan(root)
    except RuntimeError as exc:
        print(f"agent-session-commit: {exc}", file=sys.stderr)
        return 0
    configured = _config(root, "agent-session.source")
    source = Path(configured).expanduser().resolve() if configured else root
    state_path = _state_file(root)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = state_path.with_suffix(".lock")
    try:
        lock_fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        print("agent-session-commit: another archive operation is active; skipping.", file=sys.stderr)
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
                print(f"agent-session-commit: archive amended, but index refresh failed: {exc}", file=sys.stderr)
            state_path.write_text(json.dumps(updated, indent=2, sort_keys=True), encoding="utf-8")
            final_commit = _git(root, "rev-parse", "--short", "HEAD").stdout.strip()
            print(f"agent-session-commit: session archive added to commit {final_commit}", file=sys.stderr)
        else:
            raise RuntimeError(result.stderr.strip() or "Git could not amend the commit.")
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        if bundle is not None and not _git(root, "cat-file", "-e", f"HEAD:{bundle.relative_to(root)}", check=False).returncode == 0:
            bundle.unlink(missing_ok=True)
        print(f"agent-session-commit: archive amend skipped: {exc}", file=sys.stderr)
    finally:
        if index_path is not None:
            index_path.unlink(missing_ok=True)
        lock_path.unlink(missing_ok=True)
    return 0
