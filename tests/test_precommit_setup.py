from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from agent_session_commit.core import HOOK_BEGIN, configure
from agent_session_commit.precommit_setup import (
    CONFIG_KEYS, DEFAULT_CONFIG, PRE_COMMIT_MARKER, PRE_COMMIT_SCRIPT_IDS, PreCommitSetup, _detect_controller,
)


class ControllerDetectionTests(unittest.TestCase):
    def test_prefers_module_in_current_interpreter(self) -> None:
        with patch("agent_session_commit.precommit_setup.importlib.util.find_spec", return_value=object()), \
                patch("agent_session_commit.precommit_setup.shutil.which") as which:
            self.assertEqual(_detect_controller(), (sys.executable, "-m", "pre_commit"))
            which.assert_not_called()

    def test_falls_back_to_path_executable_on_windows_and_linux(self) -> None:
        for executable in (r"C:\Program Files\Python\Scripts\pre-commit.exe", "/usr/bin/pre-commit"):
            with self.subTest(executable=executable), \
                    patch("agent_session_commit.precommit_setup.importlib.util.find_spec", return_value=None), \
                    patch("agent_session_commit.precommit_setup.shutil.which", return_value=executable):
                self.assertEqual(_detect_controller(), (executable,))

    def test_missing_controller_has_install_instruction(self) -> None:
        with patch("agent_session_commit.precommit_setup.importlib.util.find_spec", return_value=None), \
                patch("agent_session_commit.precommit_setup.shutil.which", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "pip install"):
                _detect_controller()


class PreCommitSetupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.repo = self.base / "repo with spaces"
        self.repo.mkdir()
        self.source = self.base / "sessions"
        self.source.mkdir()
        self.global_config = self.base / "global.gitconfig"
        self.global_config.write_bytes(b"[test]\n\tunchanged = global value\n")
        # Every Git subprocess uses real repositories but isolated config,
        # including when the developer has a global core.hooksPath.
        env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
        env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=str(self.global_config),
                   GIT_TERMINAL_PROMPT="0")
        self.environment = patch.dict(os.environ, env, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        subprocess.run(["git", "init", "--quiet", str(self.repo)], check=True)
        self.git("config", "core.autocrlf", "false")
        self.hooks = self.repo / ".git" / "hooks"
        self.config = self.repo / ".pre-commit-config.yaml"
        self.controller = (sys.executable, "-m", "mock_pre_commit")
        self.detect = patch("agent_session_commit.precommit_setup._detect_controller", return_value=self.controller)
        self.detect.start()
        self.addCleanup(self.detect.stop)
        self.real_run = subprocess.run
        self.controller_calls: list[list[str]] = []
        self.fail_command: str | None = None
        self.mutate_before_failure = False
        self.runner = patch("agent_session_commit.precommit_setup.subprocess.run", side_effect=self.run_controller_process)
        self.runner.start()
        self.addCleanup(self.runner.stop)

    def git(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        return subprocess.run(["git", "-C", str(self.repo), *args], check=check,
                              capture_output=True, text=True, encoding="utf-8")

    def run_controller_process(self, args: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
        if tuple(args[:len(self.controller)]) != self.controller:
            return self.real_run(args, **kwargs)
        self.assertEqual(kwargs["cwd"], self.repo.resolve())
        command = args[len(self.controller):]
        self.controller_calls.append(command)
        if command[0] == "install" and (self.fail_command != "install" or self.mutate_before_failure):
            self.assertIn("--install-hooks", command)
            names = [command[index + 1] for index, arg in enumerate(command) if arg == "--hook-type"]
            for name in names:
                active = self.hooks / name
                legacy = self.hooks / (name + ".legacy")
                self.hooks.mkdir(exist_ok=True)
                if active.exists() and not any(identifier in active.read_bytes() for identifier in PRE_COMMIT_SCRIPT_IDS):
                    shutil.move(str(active), str(legacy))
                active.write_bytes(PRE_COMMIT_MARKER + b"\n# ID: " + PRE_COMMIT_SCRIPT_IDS[0] + b"\n")
                active.chmod(active.stat().st_mode | 0o111)
            if self.mutate_before_failure:
                # Force rollback of existing legacy snapshots as well as hooks
                # already installed before a package environment build failed.
                for name in names:
                    legacy = self.hooks / (name + ".legacy")
                    if legacy.exists():
                        legacy.write_bytes(b"partial installer legacy mutation\n")
        code = 1 if command[0] == self.fail_command else 0
        return subprocess.CompletedProcess(args, code, stdout="", stderr="mock environment build failed" if code else "")

    def write_config(self, *, hook_id: str = "agent-session-commit", defaults: str = "[pre-push, commit-msg]") -> bytes:
        contents = (
            "# Keep this team comment and CRLF formatting.\r\n"
            f"default_install_hook_types: {defaults} # keep this too\r\n"
            "repos:\r\n"
            "  - repo: local\r\n"
            "    hooks:\r\n"
            "      - id: team-check\r\n"
            "        name: Existing team check\r\n"
            "        entry: python -V\r\n"
            "        language: system\r\n"
            f"      - id: {hook_id}\r\n"
            "        name: Agent archive\r\n"
            "        entry: agent-session-commit hook post-commit\r\n"
            "        language: system\r\n"
        ).encode()
        self.config.write_bytes(contents)
        return contents

    def hook(self, name: str, content: bytes) -> Path:
        path = self.hooks / name
        path.write_bytes(content)
        path.chmod(path.stat().st_mode | 0o111)
        return path

    def tree(self) -> dict[str, tuple[bytes, int]]:
        return {str(path.relative_to(self.repo)): (path.read_bytes(), stat.S_IMODE(path.stat().st_mode))
                for path in self.repo.rglob("*") if path.is_file()}

    def assert_no_native_backups(self) -> None:
        self.assertFalse((self.repo / ".git" / "agent-session-commit" / "original-hooks").exists())

    def test_init_is_read_only_and_install_generates_stable_defaults(self) -> None:
        before = self.tree()
        setup = PreCommitSetup(self.repo)
        self.assertEqual(self.tree(), before)
        self.assertEqual(self.controller_calls, [])
        setup.install("custom", self.source)
        self.assertEqual(self.config.read_bytes(), DEFAULT_CONFIG.encode())
        data = yaml.safe_load(self.config.read_bytes())
        self.assertEqual(data["minimum_pre_commit_version"], "3.2.0")
        self.assertEqual(data["repos"][0]["rev"], "v0.1.1")
        self.assertEqual(data["repos"][0]["hooks"][0]["id"], "agent-session-commit")
        self.assertEqual(self.controller_calls[-1], ["install", "--install-hooks", "--hook-type", "pre-commit",
                                                     "--hook-type", "post-commit"])
        self.assertEqual(self.git("config", "--local", "--get", CONFIG_KEYS[0]).stdout.strip(), "custom")
        self.assertEqual(self.git("config", "--local", "--get", CONFIG_KEYS[1]).stdout.strip(), str(self.source))
        self.assertEqual(self.global_config.read_bytes(), b"[test]\n\tunchanged = global value\n")
        self.assertEqual(self.git("ls-files").stdout, "")
        self.assertNotEqual(self.git("rev-parse", "--verify", "HEAD", check=False).returncode, 0)
        self.assert_no_native_backups()

    def test_preserves_yaml_comments_other_hooks_and_default_types(self) -> None:
        content = self.write_config() + b"        stages: [post-commit]\r\n        always_run: true\r\n"
        self.config.write_bytes(content)
        original = b"#!/bin/sh\necho team pre-push\n"
        self.hook("pre-push", original)
        unrelated = self.hook("post-checkout", b"#!/bin/sh\necho unrelated hook\n")
        before = unrelated.read_bytes()
        setup = PreCommitSetup(self.repo)
        self.assertEqual(self.config.read_bytes(), content)
        setup.install("codex", self.source)
        self.assertEqual(self.config.read_bytes(), content)
        self.assertEqual(self.controller_calls[-1], ["install", "--install-hooks", "--hook-type", "pre-push",
                                                     "--hook-type", "commit-msg", "--hook-type", "post-commit"])
        self.assertEqual((self.hooks / "pre-push.legacy").read_bytes(), original)
        self.assertEqual(unrelated.read_bytes(), before)
        self.assertFalse((self.hooks / "pre-commit").exists())
        self.assert_no_native_backups()

    def test_legacy_id_accepted_without_rewriting_config(self) -> None:
        before = self.write_config(hook_id="agentledger", defaults="[post-commit, pre-commit, post-commit]")
        PreCommitSetup(self.repo).install("claude", self.source)
        self.assertEqual(self.config.read_bytes(), before)
        self.assertEqual(self.controller_calls[-1][-4:], ["--hook-type", "post-commit", "--hook-type", "pre-commit"])

    def test_missing_default_types_uses_framework_default_plus_post_commit(self) -> None:
        self.config.write_bytes(DEFAULT_CONFIG.encode().replace(b"default_install_hook_types: [pre-commit, post-commit]\n", b""))
        PreCommitSetup(self.repo).install("custom", self.source)
        self.assertEqual(self.controller_calls[-1][-4:], ["--hook-type", "pre-commit", "--hook-type", "post-commit"])

    def test_missing_hook_instructs_merge_before_any_edits(self) -> None:
        self.write_config(hook_id="other-hook")
        before = self.tree()
        with self.assertRaisesRegex(RuntimeError, "Merge the hook"):
            PreCommitSetup(self.repo)
        self.assertEqual(self.tree(), before)
        self.assertEqual([call[0] for call in self.controller_calls], ["validate-config"])

    def test_agent_stages_override_rejected_read_only_even_after_controller_validation(self) -> None:
        self.hook("post-commit", b"#!/bin/sh\necho preserve user hook\n")
        self.git("config", "--local", CONFIG_KEYS[0], "pi")
        self.git("config", "--local", CONFIG_KEYS[1], str(self.source))
        for hook_id in ("agent-session-commit", "agentledger"):
            for stages in ("[pre-commit]", "[pre-commit, post-commit]"):
                with self.subTest(hook_id=hook_id, stages=stages):
                    contents = self.write_config(hook_id=hook_id) + f"        stages: {stages}\r\n".encode()
                    self.config.write_bytes(contents)
                    self.controller_calls.clear()
                    before = self.tree()
                    with self.assertRaisesRegex(RuntimeError, "stages: \\[post-commit\\]"):
                        PreCommitSetup(self.repo)
                    self.assertEqual(self.tree(), before)
                    self.assertEqual(self.config.read_bytes(), contents)
                    self.assertEqual([call[0] for call in self.controller_calls], ["validate-config"])
                    self.assert_no_native_backups()

    def test_agent_always_run_false_rejected_read_only_even_after_controller_validation(self) -> None:
        self.hook("post-commit", b"#!/bin/sh\necho preserve user hook\n")
        self.git("config", "--local", CONFIG_KEYS[0], "pi")
        self.git("config", "--local", CONFIG_KEYS[1], str(self.source))
        for hook_id in ("agent-session-commit", "agentledger"):
            with self.subTest(hook_id=hook_id):
                contents = self.write_config(hook_id=hook_id) + b"        always_run: false\r\n"
                self.config.write_bytes(contents)
                self.controller_calls.clear()
                before = self.tree()
                with self.assertRaisesRegex(RuntimeError, "always_run: true"):
                    PreCommitSetup(self.repo)
                self.assertEqual(self.tree(), before)
                self.assertEqual(self.config.read_bytes(), contents)
                self.assertEqual([call[0] for call in self.controller_calls], ["validate-config"])
                self.assert_no_native_backups()

    def test_local_global_included_and_environment_hooks_path_block_preflight(self) -> None:
        for scope in ("local", "global", "include", "environment"):
            with self.subTest(scope=scope):
                if scope == "local":
                    self.git("config", "--local", "core.hooksPath", "")
                elif scope == "global":
                    self.git("config", "--global", "core.hooksPath", "custom-hooks")
                elif scope == "include":
                    included = self.base / "included.gitconfig"
                    included.write_bytes(b"[core]\n\thooksPath = included-hooks\n")
                    self.git("config", "--global", "include.path", str(included))
                else:
                    os.environ.update(GIT_CONFIG_COUNT="1", GIT_CONFIG_KEY_0="core.hooksPath",
                                      GIT_CONFIG_VALUE_0="environment-hooks")
                before = self.tree()
                global_before = self.global_config.read_bytes()
                with self.assertRaisesRegex(RuntimeError, "defining scope"):
                    PreCommitSetup(self.repo)
                self.assertEqual(self.tree(), before)
                self.assertEqual(self.global_config.read_bytes(), global_before)
                self.assertFalse(self.config.exists())
                self.git("config", "--local", "--unset-all", "core.hooksPath", check=False)
                self.git("config", "--global", "--unset-all", "core.hooksPath", check=False)
                self.git("config", "--global", "--unset-all", "include.path", check=False)
                for key in ("GIT_CONFIG_COUNT", "GIT_CONFIG_KEY_0", "GIT_CONFIG_VALUE_0"):
                    os.environ.pop(key, None)
        self.assertEqual(self.controller_calls, [])

    def test_native_hooks_require_explicit_migration_without_uninstall(self) -> None:
        configure(self.repo, "custom", self.source)
        before = self.tree()
        with self.assertRaisesRegex(RuntimeError, "agent-session-commit uninstall"):
            PreCommitSetup(self.repo)
        self.assertEqual(self.tree(), before)

    def test_legacy_native_marker_also_requires_migration(self) -> None:
        self.hook("post-commit", b"#!/bin/sh\n# >>> agentledger >>>\n")
        before = self.tree()
        with self.assertRaisesRegex(RuntimeError, "uninstall"):
            PreCommitSetup(self.repo)
        self.assertEqual(self.tree(), before)

    def test_unknown_or_traversing_hook_names_are_rejected_read_only(self) -> None:
        for defaults in ("[../config]", "[--overwrite]", "[pre-fetch]", "[42]", "pre-commit"):
            with self.subTest(defaults=defaults):
                self.write_config(defaults=defaults)
                before = self.tree()
                with self.assertRaisesRegex(RuntimeError, "unsafe"):
                    PreCommitSetup(self.repo)
                self.assertEqual(self.tree(), before)

    def test_unsafe_yaml_tags_and_shapes_are_rejected(self) -> None:
        for document in (b"!!python/object/apply:os.getcwd []", b"[]", b"repos: null", b"repos: [null]"):
            with self.subTest(document=document):
                self.config.write_bytes(document)
                before = self.tree()
                with self.assertRaises(RuntimeError):
                    PreCommitSetup(self.repo)
                self.assertEqual(self.tree(), before)

    def test_hook_and_legacy_conflict_is_not_overwritten(self) -> None:
        self.hook("pre-commit", b"#!/bin/sh\necho current\n")
        self.hook("pre-commit.legacy", b"#!/bin/sh\necho previous\n")
        before = self.tree()
        with self.assertRaisesRegex(RuntimeError, "Merge/migrate"):
            PreCommitSetup(self.repo)
        self.assertEqual(self.tree(), before)

    def test_comment_alone_does_not_allow_clobbering_legacy_hook(self) -> None:
        self.hook("pre-commit", PRE_COMMIT_MARKER + b"\n# user-added comment, no framework ID\n")
        self.hook("pre-commit.legacy", b"#!/bin/sh\necho previous\n")
        before = self.tree()
        with self.assertRaisesRegex(RuntimeError, "Merge/migrate"):
            PreCommitSetup(self.repo)
        self.assertEqual(self.tree(), before)

    def test_repeat_install_preserves_existing_legacy_hooks(self) -> None:
        original = b"#!/bin/sh\necho team\n"
        self.hook("pre-commit", original)
        PreCommitSetup(self.repo).install("custom", self.source)
        before = (self.hooks / "pre-commit.legacy").read_bytes()
        PreCommitSetup(self.repo).install("pi", self.source)
        self.assertEqual((self.hooks / "pre-commit.legacy").read_bytes(), before)
        self.assertEqual(before, original)
        self.assert_no_native_backups()

    def test_failed_install_restores_hooks_legacy_modes_git_values_and_new_yaml(self) -> None:
        self.git("config", "--local", CONFIG_KEYS[0], "pi")
        self.git("config", "--local", CONFIG_KEYS[1], "old source\nwith newline")
        self.hook("pre-commit", b"#!/bin/sh\necho previous user hook\n")
        self.hook("post-commit", PRE_COMMIT_MARKER + b"\n# ID: " + PRE_COMMIT_SCRIPT_IDS[0] + b"\n")
        self.hook("post-commit.legacy", b"#!/bin/sh\necho legacy user hook\n")
        unrelated = self.hook("pre-push", b"#!/bin/sh\necho leave alone\n")
        before = self.tree()
        setup = PreCommitSetup(self.repo)
        self.fail_command = "install"
        self.mutate_before_failure = True
        with self.assertRaisesRegex(RuntimeError, "rolled back"):
            setup.install("codex", self.source)
        self.assertEqual(self.tree(), before)
        self.assertEqual(unrelated.read_bytes(), b"#!/bin/sh\necho leave alone\n")
        self.assert_no_native_backups()

    def test_failed_install_preserves_existing_yaml_and_absent_local_values(self) -> None:
        config_before = self.write_config()
        self.git("config", "--global", CONFIG_KEYS[0], "claude")
        self.git("config", "--global", CONFIG_KEYS[1], "global source")
        global_before = self.global_config.read_bytes()
        before = self.tree()
        setup = PreCommitSetup(self.repo)
        self.fail_command = "install"
        self.mutate_before_failure = True
        with self.assertRaisesRegex(RuntimeError, "environment build failed"):
            setup.install("codex", self.source)
        self.assertEqual(self.tree(), before)
        self.assertEqual(self.config.read_bytes(), config_before)
        self.assertEqual(self.global_config.read_bytes(), global_before)
        for key in CONFIG_KEYS:
            self.assertEqual(self.git("config", "--local", "--get-all", key, check=False).returncode, 1)
        self.assert_no_native_backups()

    def test_validation_failure_removes_generated_yaml_preserving_existing_hooks(self) -> None:
        self.hook("post-commit", b"#!/bin/sh\necho team\n")
        self.git("config", "--local", CONFIG_KEYS[0], "hermes")
        before = self.tree()
        setup = PreCommitSetup(self.repo)
        self.fail_command = "validate-config"
        with self.assertRaisesRegex(RuntimeError, "validate-config failed"):
            setup.install("pi", self.source)
        self.assertEqual(self.tree(), before)
        self.assertFalse(self.config.exists())
        self.assert_no_native_backups()

    def test_existing_yaml_controller_validation_failure_is_read_only(self) -> None:
        self.write_config()
        before = self.tree()
        self.fail_command = "validate-config"
        with self.assertRaisesRegex(RuntimeError, "validate-config failed"):
            PreCommitSetup(self.repo)
        self.assertEqual(self.tree(), before)

    def test_wizard_time_changes_are_rechecked(self) -> None:
        setup = PreCommitSetup(self.repo)
        self.hook("post-commit", HOOK_BEGIN.encode())
        before = self.tree()
        with self.assertRaisesRegex(RuntimeError, "uninstall"):
            setup.install("pi", self.source)
        self.assertEqual(self.tree(), before)

    def test_multi_value_local_config_is_restored_when_save_fails(self) -> None:
        self.git("config", "--local", "--add", CONFIG_KEYS[0], "pi")
        self.git("config", "--local", "--add", CONFIG_KEYS[0], "hermes")
        before = self.git("config", "--local", "--null", "--get-all", CONFIG_KEYS[0]).stdout
        with self.assertRaisesRegex(RuntimeError, "rolled back"):
            PreCommitSetup(self.repo).install("custom", self.source)
        self.assertEqual(self.git("config", "--local", "--null", "--get-all", CONFIG_KEYS[0]).stdout, before)
        self.assertFalse(self.config.exists())
        self.assert_no_native_backups()

    def test_unknown_agent_is_rejected_without_creating_source_or_yaml(self) -> None:
        missing_source = self.base / "not created by engine"
        before = self.tree()
        with self.assertRaisesRegex(RuntimeError, "Unknown agent"):
            PreCommitSetup(self.repo).install("unknown", missing_source)
        self.assertEqual(self.tree(), before)
        self.assertFalse(missing_source.exists())

    def test_unicode_root_source_and_config_roundtrip_under_non_utf8_locale(self) -> None:
        new_repo = self.base / "中文 项目"
        self.repo.rename(new_repo)
        self.repo = new_repo
        self.hooks = self.repo / ".git" / "hooks"
        self.config = self.repo / ".pre-commit-config.yaml"
        self.source = self.base / "会话 来源"
        self.source.mkdir()
        self.git("config", "--local", CONFIG_KEYS[0], "pi")
        self.git("config", "--local", CONFIG_KEYS[1], str(self.base / "原有 会话"))
        config_before = b"# " + "中文注释保持原样\r\n".encode("utf-8") + self.write_config(defaults="[pre-rebase]")
        self.config.write_bytes(config_before)
        # Emulate a Windows legacy code page for subprocesses without an
        # explicit encoding, while the real Git process still emits UTF-8.
        with patch("subprocess._text_encoding", return_value="cp1252"):
            setup = PreCommitSetup(self.repo)
            self.assertEqual(setup.root, self.repo.resolve())
            setup.install("custom", self.source)
            self.assertEqual(self.git("config", "--local", "--get", CONFIG_KEYS[1]).stdout.rstrip("\n"),
                             str(self.source))
            self.assertEqual(self.controller_calls[-1][-4:],
                             ["--hook-type", "pre-rebase", "--hook-type", "post-commit"])
            before_failure = self.tree()
            self.fail_command = "install"
            self.mutate_before_failure = True
            with self.assertRaisesRegex(RuntimeError, "rolled back"):
                setup.install("codex", self.base / "另一 会话")
            self.assertEqual(self.tree(), before_failure)
            self.assertEqual(self.git("config", "--local", "--get", CONFIG_KEYS[1]).stdout.rstrip("\n"),
                             str(self.source))
        self.assertEqual(self.config.read_bytes(), config_before)
        self.assert_no_native_backups()

    def test_symlinked_hooks_directory_rejected_before_snapshots_or_edits(self) -> None:
        setup = PreCommitSetup(self.repo)
        self.hook("pre-commit", b"#!/bin/sh\necho shared external hook\n")
        git_config_before = (self.repo / ".git" / "config").read_bytes()
        external = self.base / "shared external hooks"
        self.hooks.rename(external)
        try:
            self.hooks.symlink_to(external, target_is_directory=True)
        except (OSError, NotImplementedError):
            external.rename(self.hooks)
            self.skipTest("Directory symlink creation unavailable on this system")
        try:
            before = {path.name: path.read_bytes() for path in external.iterdir()}
            with patch("agent_session_commit.precommit_setup._FileSnapshot.capture") as capture:
                with self.assertRaisesRegex(RuntimeError, "Unsafe hooks directory"):
                    PreCommitSetup(self.repo)
                # Also protect the install phase if the link appears during
                # the wizard after the original read-only preflight.
                with self.assertRaisesRegex(RuntimeError, "Unsafe hooks directory"):
                    setup.install("custom", self.source)
                capture.assert_not_called()
            self.assertEqual({path.name: path.read_bytes() for path in external.iterdir()}, before)
            self.assertEqual((self.repo / ".git" / "config").read_bytes(), git_config_before)
            self.assertFalse(self.config.exists())
            self.assertEqual(self.controller_calls, [])
            self.assert_no_native_backups()
        finally:
            self.hooks.unlink()
            external.rename(self.hooks)

    def test_symlinked_yaml_or_hook_is_rejected_without_touching_target(self) -> None:
        target = self.base / "external file"
        target.write_bytes(DEFAULT_CONFIG.encode())
        for path in (self.config, self.hooks / "pre-commit", self.hooks / "post-commit.legacy"):
            with self.subTest(path=path):
                try:
                    path.symlink_to(target)
                except (OSError, NotImplementedError):
                    self.skipTest("Symlink creation unavailable on this system")
                try:
                    with self.assertRaisesRegex(RuntimeError, "Unsafe setup path"):
                        PreCommitSetup(self.repo)
                    self.assertEqual(target.read_bytes(), DEFAULT_CONFIG.encode())
                finally:
                    path.unlink()


if __name__ == "__main__":
    unittest.main()
