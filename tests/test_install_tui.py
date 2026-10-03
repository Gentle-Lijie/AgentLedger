from __future__ import annotations

import io
import os
import sqlite3
import subprocess
import tempfile
import unittest
from contextlib import closing, redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from agent_session_commit import cli
from agent_session_commit.core import AGENTS, HOOK_BEGIN


class InstallTuiTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.repo = self.base / "repo with spaces"
        self.repo.mkdir()
        environment = {
            key: value for key, value in os.environ.items()
            if not key.startswith("GIT_")
        }
        environment.update(
            GIT_CONFIG_NOSYSTEM="1",
            GIT_CONFIG_GLOBAL=str(self.base / "unused-global-config"),
            GIT_TERMINAL_PROMPT="0",
        )
        self.environment = patch.dict(os.environ, environment, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        subprocess.run(["git", "init", "--quiet", str(self.repo)], check=True)
        original_cwd = Path.cwd()
        os.chdir(self.repo)
        self.addCleanup(os.chdir, original_cwd)
        select_patch = patch("questionary.select")
        path_patch = patch("questionary.path")
        self.select = select_patch.start()
        self.addCleanup(select_patch.stop)
        self.path = path_patch.start()
        self.addCleanup(path_patch.stop)

    def git(self, *args: str) -> str:
        return subprocess.run(
            ["git", "-C", str(self.repo), *args],
            check=True, capture_output=True, text=True, timeout=15,
        ).stdout.strip()

    def run_cli(self, *args: str, stdin_tty: bool = True,
                stdout_tty: bool = True) -> tuple[int, str]:
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()) as errors:
            with patch.object(cli.sys.stdin, "isatty", return_value=stdin_tty), \
                    patch.object(cli.sys.stdout, "isatty", return_value=stdout_tty):
                result = cli.main(list(args))
        return result, errors.getvalue()

    def snapshot(self) -> dict[str, tuple[bytes, int]]:
        # Detect config edits, backup files, hook changes and source creation.
        return {
            path.relative_to(self.repo).as_posix(): (path.read_bytes(), path.stat().st_mode)
            for path in self.repo.rglob("*") if path.is_file()
        }

    def test_cancel_agent_leaves_repository_unchanged_in_both_modes(self) -> None:
        self.select.return_value.ask.return_value = None
        for flags in ([], ["--pre-commit"]):
            with self.subTest(flags=flags), patch(
                "agent_session_commit.precommit_setup.PreCommitSetup"
            ) as setup:
                before = self.snapshot()
                code, error = self.run_cli("install", *flags)
                self.assertEqual(code, 130)
                self.assertIn("cancelled", error)
                self.path.assert_not_called()
                setup.return_value.install.assert_not_called()
                self.assertEqual(self.snapshot(), before)

    def test_cancel_path_preserves_existing_config_hooks_and_missing_exports(self) -> None:
        self.git("config", "--local", "agent-session.agent", "custom")
        missing = self.repo / "exports" / "pending"
        self.git("config", "--local", "agent-session.source", str(missing))
        (self.repo / ".git" / "hooks" / "post-commit").write_bytes(b"#!/bin/sh\nexit 0\n")
        self.select.return_value.ask.return_value = "custom"
        self.path.return_value.ask.return_value = None
        for flags in ([], ["--pre-commit"]):
            with self.subTest(flags=flags), patch(
                "agent_session_commit.precommit_setup.PreCommitSetup"
            ) as setup:
                before = self.snapshot()
                self.assertEqual(self.run_cli("install", *flags)[0], 130)
                setup.return_value.install.assert_not_called()
                self.assertEqual(self.snapshot(), before)
                self.assertFalse(missing.parent.exists())

    def test_existing_agent_and_source_are_prompt_defaults(self) -> None:
        source = self.repo / "previous sessions"
        source.mkdir()
        self.git("config", "--local", "agent-session.agent", "codex")
        self.git("config", "--local", "agent-session.source", str(source))
        self.select.return_value.ask.return_value = "codex"
        self.path.return_value.ask.return_value = str(source)
        with patch.object(cli.sys.stdin, "isatty", return_value=True), \
                patch.object(cli.sys.stdout, "isatty", return_value=True):
            self.assertEqual(cli._select_configuration(self.repo, None, None), ("codex", source))
        self.assertEqual(self.select.call_args.kwargs["default"], "codex")
        self.assertEqual(self.path.call_args.kwargs["default"], str(source))
        choices = self.select.call_args.kwargs["choices"]
        self.assertEqual({choice.value for choice in choices}, set(AGENTS))
        self.assertIs(self.path.call_args.kwargs["validate"](str(source)), True)

    def test_switching_agent_does_not_reuse_previous_source(self) -> None:
        previous = self.repo / "previous"
        previous.mkdir()
        source = self.repo / "new sessions"
        source.mkdir()
        self.git("config", "--local", "agent-session.agent", "codex")
        self.git("config", "--local", "agent-session.source", str(previous))
        self.select.return_value.ask.return_value = "pi"
        self.path.return_value.ask.return_value = str(source)
        with patch.object(cli, "default_source", return_value=source), \
                patch.object(cli.sys.stdin, "isatty", return_value=True), \
                patch.object(cli.sys.stdout, "isatty", return_value=True):
            self.assertEqual(cli._select_configuration(self.repo, None, None), ("pi", source))
        self.assertEqual(self.path.call_args.kwargs["default"], str(source))

    def test_relative_source_is_resolved_against_git_root_from_subdirectory(self) -> None:
        source = self.repo / "session exports"
        source.mkdir()
        nested = self.repo / "src" / "nested"
        nested.mkdir(parents=True)
        os.chdir(nested)
        self.select.return_value.ask.return_value = "custom"
        self.path.return_value.ask.return_value = "session exports"
        self.assertEqual(self.run_cli("install")[0], 0)
        self.assertEqual(self.git("config", "--local", "agent-session.source"), str(source))
        self.assertEqual(self.git("config", "--local", "agent-session.workdir"), str(self.repo))
        self.assertFalse((nested / "session exports").exists())

    def test_missing_agent_source_and_regular_text_file_are_rejected_without_changes(self) -> None:
        invalid = self.repo / "not-a-database.txt"
        invalid.write_text("not a SQLite source", encoding="utf-8")
        database_path = self.repo / "unsupported.sqlite"
        with closing(sqlite3.connect(database_path)) as database:
            database.execute("CREATE TABLE sessions (id TEXT)")
        for agent, value in (
            ("codex", "missing sessions"), ("custom", str(invalid)),
            ("codex", str(database_path)),
        ):
            with self.subTest(agent=agent):
                before = self.snapshot()
                self.path.return_value.ask.return_value = value
                code, error = self.run_cli("install", "--agent", agent)
                self.assertEqual(code, 1)
                self.assertTrue(error)
                validator = self.path.call_args.kwargs["validate"]
                self.assertIsInstance(validator(value), str)
                self.assertEqual(self.snapshot(), before)

    def test_custom_and_trae_exports_are_created_only_after_path_answer(self) -> None:
        for agent in ("custom", "trae"):
            with self.subTest(agent=agent):
                source = self.repo / agent / "exports"
                self.select.return_value.ask.return_value = agent

                def answer() -> str:
                    self.assertFalse(source.parent.exists())
                    self.assertIs(self.path.call_args.kwargs["validate"](str(source)), True)
                    return str(source)

                self.path.return_value.ask.side_effect = answer
                self.assertEqual(self.run_cli("install")[0], 0)
                self.assertTrue(source.is_dir())
                self.assertEqual(self.git("config", "--local", "agent-session.agent"), agent)
                self.assertEqual(self.git("config", "--local", "agent-session.source"), str(source))

    def test_nontty_explicit_flags_install_native_hooks_without_prompts(self) -> None:
        source = self.repo / "sessions"
        source.mkdir()
        code, error = self.run_cli(
            "install", "--agent", "custom", "--source", str(source),
            stdin_tty=False, stdout_tty=False,
        )
        self.assertEqual((code, error), (0, ""))
        self.select.assert_not_called()
        self.path.assert_not_called()
        self.assertEqual(self.git("config", "--local", "agent-session.source"), str(source))
        for name in ("pre-commit", "post-commit"):
            contents = (self.repo / ".git" / "hooks" / name).read_text(encoding="utf-8")
            self.assertIn(HOOK_BEGIN, contents)
            self.assertIn(f"hook {name}", contents)

    def test_nontty_missing_flags_fail_without_prompts_or_mutations(self) -> None:
        for flags in ([], ["--agent", "custom"], ["--source", "missing exports"]):
            for stdin_tty, stdout_tty in ((False, True), (True, False), (False, False)):
                with self.subTest(flags=flags, tty=(stdin_tty, stdout_tty)):
                    before = self.snapshot()
                    code, error = self.run_cli(
                        "install", *flags, stdin_tty=stdin_tty, stdout_tty=stdout_tty,
                    )
                    self.assertEqual(code, 1)
                    self.assertIn("--agent and --source", error)
                    self.select.assert_not_called()
                    self.path.assert_not_called()
                    self.assertEqual(self.snapshot(), before)

    def test_sqlite_source_is_accepted_as_file_without_attempting_mkdir(self) -> None:
        source = self.repo / "sessions.sqlite"
        with closing(sqlite3.connect(source)) as database:
            database.execute("CREATE TABLE sessions (id TEXT)")
        before = source.read_bytes()
        self.path.return_value.ask.return_value = str(source)
        for agent in ("zcode", "hermes"):
            with self.subTest(agent=agent):
                self.assertEqual(self.run_cli("install", "--agent", agent)[0], 0)
                self.assertIs(self.path.call_args.kwargs["validate"](str(source)), True)
                self.assertEqual(source.read_bytes(), before)
                self.assertEqual(self.git("config", "--local", "agent-session.source"), str(source))

    def test_framework_preflight_precedes_prompts_and_routes_install_without_native_hooks(self) -> None:
        source = self.repo / "exports"
        events: list[str] = []
        with patch("agent_session_commit.precommit_setup.PreCommitSetup") as setup, \
                patch.object(cli, "configure") as native:
            plan = setup.return_value

            def preflight(root: Path):
                self.assertEqual(root, self.repo)
                events.append("preflight")
                return plan

            setup.side_effect = preflight
            self.select.return_value.ask.side_effect = lambda: events.append("agent") or "custom"
            self.path.return_value.ask.side_effect = lambda: events.append("source") or str(source)
            plan.install.side_effect = lambda *args: events.append("install")
            self.assertEqual(self.run_cli("install", "--pre-commit")[0], 0)
            self.assertEqual(events, ["preflight", "agent", "source", "install"])
            plan.install.assert_called_once_with("custom", source)
            native.assert_not_called()
        for name in ("pre-commit", "post-commit"):
            self.assertFalse((self.repo / ".git" / "hooks" / name).exists())

    def test_framework_preflight_error_returns_before_tui_and_source_creation(self) -> None:
        before = self.snapshot()
        self.select.return_value.ask.return_value = "custom"
        self.path.return_value.ask.return_value = str(self.repo / "missing exports")
        with patch(
            "agent_session_commit.precommit_setup.PreCommitSetup",
            side_effect=RuntimeError("Existing framework configuration is invalid"),
        ), patch.object(cli, "configure") as native:
            code, error = self.run_cli("install", "--pre-commit")
            self.assertEqual(code, 1)
            self.assertIn("framework configuration is invalid", error)
            self.select.assert_not_called()
            self.path.assert_not_called()
            native.assert_not_called()
        self.assertEqual(self.snapshot(), before)


if __name__ == "__main__":
    unittest.main()
