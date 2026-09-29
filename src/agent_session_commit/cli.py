from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from .core import AGENTS, _config, configure, default_source, run_hook, status, uninstall


class InstallationCancelled(Exception):
    """The terminal wizard was cancelled before installation."""


def _git_root() -> Path:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, encoding="utf-8"
    )
    if result.returncode:
        raise RuntimeError("Run this command from inside a Git repository.")
    return Path(result.stdout.strip()).resolve()


def _resolve_source(root: Path, value: str) -> Path:
    source = Path(os.path.expandvars(os.path.expanduser(value.strip())))
    return (source if source.is_absolute() else root / source).resolve()


def _source_error(root: Path, agent: str, value: str) -> bool | str:
    if not value.strip():
        return "A session/export directory is required."
    try:
        source = _resolve_source(root, value)
        if source.exists():
            if source.is_dir():
                return True
            if source.is_file() and source.suffix.casefold() in {".db", ".sqlite", ".sqlite3"}:
                return True if agent in {"zcode", "hermes"} else "SQLite sources are supported for ZCode and Hermes; choose a transcript directory for this agent."
            return "Choose a session directory or a SQLite database file."
        if agent in {"custom", "trae"} or source == (root / ".agent-sessions" / "source").resolve():
            return True
        return f"Session source does not exist: {source}. Enter its actual path."
    except (OSError, ValueError, RuntimeError) as exc:
        return f"Cannot use this source: {exc}"


def _select_configuration(root: Path, agent: str | None, source_value: str | None) -> tuple[str, Path]:
    needs_prompt = agent is None or source_value is None
    if needs_prompt and not (sys.stdin.isatty() and sys.stdout.isatty()):
        raise RuntimeError("Interactive installation requires a terminal. Supply both --agent and --source for non-interactive use.")
    previous_agent = _config(root, "agent-session.agent")
    if agent is None:
        import questionary

        choices = [questionary.Choice(f"{label} ({key})", value=key) for key, label in AGENTS.items()]
        agent = questionary.select(
            "Choose the AI coding agent to archive:",
            choices=choices,
            default=previous_agent if previous_agent in AGENTS else next(iter(AGENTS)),
            pointer=">",
        ).ask()
        if agent is None:
            raise InstallationCancelled
    if source_value is None:
        import questionary

        candidate = default_source(agent)
        previous_source = _config(root, "agent-session.source") if agent == previous_agent else None
        suggested = previous_source or str(candidate or (root / ".agent-sessions" / "source"))
        source_value = questionary.path(
            "Session directory or SQLite database:",
            default=suggested,
            only_directories=False,
            get_paths=lambda: [str(root)],
            validate=lambda value: _source_error(root, agent, value),
        ).ask()
        if source_value is None:
            raise InstallationCancelled
    error = _source_error(root, agent, source_value)
    if error is not True:
        raise RuntimeError(str(error))
    source = _resolve_source(root, source_value)
    if not source.exists():
        source.mkdir(parents=True, exist_ok=True)
    return agent, source


def _install(root: Path, *, framework: bool, agent: str | None, source_value: str | None) -> None:
    # The framework preflight is read-only and happens before the wizard.
    plan = None
    if framework:
        from .precommit_setup import PreCommitSetup

        plan = PreCommitSetup(root)
    agent, source = _select_configuration(root, agent, source_value)
    if plan is not None:
        print("Installing pre-commit hooks and their environments; the first run may take a few minutes...")
        plan.install(agent, source)
        print(f"Installed pre-commit integration for {AGENTS[agent]} in {root}")
    else:
        configure(root, agent, source)
        print(f"Installed native hooks for {AGENTS[agent]} in {root}")
    print(f"Session source: {source}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agent-session-commit")
    parser.add_argument("command", choices=("install", "status", "uninstall", "hook"))
    parser.add_argument("hook_name", nargs="?", choices=("pre-commit", "post-commit"))
    parser.add_argument("--pre-commit", action="store_true", help="Use the pre-commit framework instead of native hook wrappers (install only)")
    parser.add_argument("--agent", choices=list(AGENTS), help="Skip the agent selection prompt (install only)")
    parser.add_argument("--source", help="Skip the session source prompt (install only)")
    args = parser.parse_args(argv)
    if args.command != "install" and (args.pre_commit or args.agent is not None or args.source is not None):
        parser.error("--pre-commit, --agent and --source are only valid with install")
    if args.command != "hook" and args.hook_name is not None:
        parser.error("A hook name is only valid with the hook command")
    try:
        root = _git_root()
        if args.command == "install":
            _install(root, framework=args.pre_commit, agent=args.agent, source_value=args.source)
        elif args.command == "status":
            status(root)
        elif args.command == "uninstall":
            uninstall(root)
            print("Removed Agent Session Commit configuration and hook sections.")
        elif args.command == "hook":
            if not args.hook_name:
                raise RuntimeError("The hook command requires a hook name.")
            return run_hook(root, args.hook_name)
    except (InstallationCancelled, KeyboardInterrupt, EOFError):
        action = "installation" if args.command == "install" else "operation"
        print(f"agent-session-commit: {action} cancelled.", file=sys.stderr)
        return 130
    except (RuntimeError, OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"agent-session-commit: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
