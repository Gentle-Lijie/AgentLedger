from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from .core import AGENTS, configure, run_hook, status, uninstall
from .core import default_source


def _git_root() -> Path:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True
    )
    if result.returncode:
        raise RuntimeError("Run this command from inside a Git repository.")
    return Path(result.stdout.strip()).resolve()


def _prompt_install(root: Path) -> None:
    print("Choose the AI coding agent whose sessions should be archived:")
    agent_keys = [key for key in AGENTS if key != "custom"]
    for index, key in enumerate(agent_keys, 1):
        label = AGENTS[key]
        print(f"  {index}. {label} ({key})")
    print(f"  {len(agent_keys) + 1}. Custom session/export directory")
    choice = input("Selection [1]: ").strip() or "1"
    try:
        number = int(choice)
        agent = agent_keys[number - 1] if 1 <= number <= len(agent_keys) else "custom"
        if number == len(agent_keys) + 1:
            agent = "custom"
        elif number < 1 or number > len(agent_keys) + 1:
            raise ValueError
    except ValueError as exc:
        raise RuntimeError("Enter one of the listed numbers.") from exc

    candidate = default_source(agent)
    suggested = str(candidate) if candidate else str(root / ".agent-sessions" / "source")
    entered = input(f"Session/export directory{f' [{suggested}]' if suggested else ''}: ").strip()
    if not entered and suggested:
        entered = suggested
    if not entered:
        raise RuntimeError("A session/export directory is required.")
    source = Path(os.path.expandvars(os.path.expanduser(entered))).resolve()
    if not source.exists():
        if agent in {"custom", "trae"} or source == (root / ".agent-sessions" / "source").resolve():
            source.mkdir(parents=True, exist_ok=True)
        else:
            raise RuntimeError(f"Default session source does not exist: {source}. Enter its actual path.")
    if not source.is_dir() and source.suffix.casefold() not in {".db", ".sqlite", ".sqlite3"}:
        raise RuntimeError("Choose a session directory or a SQLite database file.")
    configure(root, agent, source)
    print(f"Installed for {AGENTS.get(agent, 'Custom agent')} in {root}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agent-session-commit")
    parser.add_argument("command", choices=("install", "status", "uninstall", "hook"))
    parser.add_argument("hook_name", nargs="?", choices=("pre-commit", "post-commit"))
    args = parser.parse_args(argv)
    try:
        root = _git_root()
        if args.command == "install":
            _prompt_install(root)
        elif args.command == "status":
            status(root)
        elif args.command == "uninstall":
            uninstall(root)
            print("Removed Agent Session Commit configuration and hook sections.")
        elif args.command == "hook":
            if not args.hook_name:
                raise RuntimeError("The hook command requires a hook name.")
            return run_hook(root, args.hook_name)
    except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
        print(f"agent-session-commit: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
