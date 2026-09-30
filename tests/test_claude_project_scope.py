"""Claude project scoping must not read another repository's transcripts."""

from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from agent_session_commit import cli, core


class ClaudeProjectScopeTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.repo = self.base / "repo with spaces"
        self.repo.mkdir()
        self.projects = self.base / "claude-config" / "projects"
        self.projects.mkdir(parents=True)

        # Keep Git and Claude settings independent of the developer's machine.
        environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
        environment.update(
            GIT_CONFIG_NOSYSTEM="1",
            GIT_CONFIG_GLOBAL=str(self.base / "empty-global.gitconfig"),
            GIT_TERMINAL_PROMPT="0",
            CLAUDE_CONFIG_DIR=str(self.projects.parent),
        )
        environment_patch = patch.dict(os.environ, environment, clear=True)
        environment_patch.start()
        self.addCleanup(environment_patch.stop)
        subprocess.run(["git", "init", "--quiet", str(self.repo)], check=True, timeout=15)

    def git_config(self, key: str, value: str) -> None:
        subprocess.run(
            ["git", "-C", str(self.repo), "config", "--local", key, value],
            check=True, capture_output=True, text=True, timeout=15,
        )

    def configure_claude(self, source: Path) -> None:
        self.git_config("agent-session.agent", "claude")
        self.git_config("agent-session.source", str(source))

    def transcript(self, directory: Path, name: str = "session.jsonl") -> tuple[Path, bytes]:
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / name
        payload = (json.dumps({"cwd": str(self.repo), "message": "tiny test transcript"}) + "\n").encode()
        path.write_bytes(payload)
        return path, payload

    def guarded_scan(self, allowed: Path) -> list[tuple[Path, bytes]]:
        original_read_bytes = Path.read_bytes
        original_rglob = Path.rglob

        def read_bytes(path: Path) -> bytes:
            if self.projects in path.parents and path != allowed:
                raise AssertionError(f"Read another Claude project's transcript: {path}")
            return original_read_bytes(path)

        def rglob(path: Path, pattern: str):
            if path == self.projects:
                raise AssertionError("Traversed the global Claude projects directory")
            return original_rglob(path, pattern)

        with patch.object(Path, "read_bytes", new=read_bytes), \
                patch.object(Path, "rglob", new=rglob):
            return core._scan(self.repo)

    def project_path(self, root: Path) -> Path:
        slug = "".join(character if character.isascii() and character.isalnum() else "-"
                       for character in str(root.resolve()))
        return self.projects / slug

    def test_default_source_is_project_specific_and_sanitizes_path_separators(self) -> None:
        self.assertEqual(core.default_source("claude"), self.projects)
        self.assertEqual(core.default_source("claude", root=self.repo), self.project_path(self.repo))

        # Windows separators and drive colons can occur in a root string even
        # when this test runs on a POSIX host.
        root_with_separators = Path(f"{self.repo}:drive\\nested")
        self.assertEqual(core.default_source("claude", root=root_with_separators),
                         self.project_path(root_with_separators))

    def test_scan_global_projects_reads_only_current_project(self) -> None:
        project = core.default_source("claude", root=self.repo)
        assert project is not None
        own_file, own_payload = self.transcript(project)
        self.transcript(self.projects / "another-project", "poison.jsonl")
        self.configure_claude(self.projects)

        self.assertEqual(self.guarded_scan(own_file), [(own_file, own_payload)])

    def test_scan_missing_project_returns_empty_without_creating_it(self) -> None:
        project = core.default_source("claude", root=self.repo)
        assert project is not None
        self.assertFalse(project.exists())
        self.transcript(self.projects / "another-project", "poison.jsonl")
        self.configure_claude(self.projects)

        self.assertEqual(self.guarded_scan(project / "unused.jsonl"), [])
        self.assertFalse(project.exists())

    def test_slug_collision_does_not_archive_another_project(self) -> None:
        project = core.default_source("claude", root=self.repo)
        assert project is not None
        other_root = self.base / "repo-with-spaces"
        self.assertEqual(self.project_path(other_root), project)
        project.mkdir(parents=True)
        (project / "other.jsonl").write_text(
            json.dumps({"cwd": str(other_root), "message": f"mentions {self.repo} but belongs elsewhere"}) + "\n",
            encoding="utf-8",
        )
        self.configure_claude(self.projects)

        self.assertEqual(core._scan(self.repo), [])

    def test_native_claude_source_ignores_non_session_files_and_missing_cwd(self) -> None:
        project = core.default_source("claude", root=self.repo)
        assert project is not None
        project.mkdir(parents=True)
        (project / "MEMORY.md").write_text(str(self.repo), encoding="utf-8")
        (project / "unknown.jsonl").write_text(
            json.dumps({"message": f"mentions {self.repo} without a session cwd"}) + "\n",
            encoding="utf-8",
        )
        self.configure_claude(self.projects)

        self.assertEqual(core._scan(self.repo), [])

    def test_legacy_fingerprint_is_reused_after_source_narrows(self) -> None:
        project = core.default_source("claude", root=self.repo)
        assert project is not None
        transcript, payload = self.transcript(project)
        digest = hashlib.sha256(payload).hexdigest()
        state_path = core._state_file(self.repo)
        state_path.parent.mkdir(parents=True)
        state_path.write_text(json.dumps({
            f"{project.name}/{transcript.name}": {
                "size": len(payload), "sha256": digest, "prefix_sha256": digest,
            }
        }), encoding="utf-8")
        self.configure_claude(project)

        bundle, _ = core._write_bundle(self.repo, project, core._scan(self.repo))
        self.assertIsNone(bundle)
        with redirect_stdout(io.StringIO()) as output:
            core.status(self.repo)
        self.assertIn("(0 changed)", output.getvalue())

    def test_legacy_global_source_amends_only_this_projects_transcript(self) -> None:
        project = core.default_source("claude", root=self.repo)
        assert project is not None
        self.transcript(project)
        self.transcript(self.projects / "unrelated", "poison.jsonl")
        self.configure_claude(self.projects)
        self.git_config("user.name", "Test User")
        self.git_config("user.email", "test@example.invalid")
        (self.repo / "code.txt").write_text("code\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.repo), "add", "code.txt"], check=True)
        subprocess.run(["git", "-C", str(self.repo), "commit", "--quiet", "-m", "code"], check=True)

        self.assertEqual(core.run_hook(self.repo, "post-commit"), 0)
        history = subprocess.run(
            ["git", "-C", str(self.repo), "rev-list", "--count", "HEAD"],
            check=True, capture_output=True, text=True,
        )
        self.assertEqual(history.stdout.strip(), "1")
        bundles = list((self.repo / ".agent-sessions" / "bundles").glob("*.tar.gz"))
        self.assertEqual(len(bundles), 1)
        with tarfile.open(bundles[0], "r:gz") as archive:
            manifest = json.load(archive.extractfile("manifest.json"))
        self.assertEqual([entry["path"] for entry in manifest["files"]],
                         [f"{project.name}/session.jsonl"])

    def test_wizard_suggests_missing_project_directory_without_creating_it(self) -> None:
        project = core.default_source("claude", root=self.repo)
        assert project is not None
        prompt = Mock()
        prompt.ask.return_value = str(project)
        questionary = SimpleNamespace(path=Mock(return_value=prompt))
        for legacy_global_source in (False, True):
            with self.subTest(legacy_global_source=legacy_global_source):
                if legacy_global_source:
                    self.configure_claude(self.projects)
                with patch.dict(sys.modules, {"questionary": questionary}), \
                        patch.object(cli.sys.stdin, "isatty", return_value=True), \
                        patch.object(cli.sys.stdout, "isatty", return_value=True):
                    selected = cli._select_configuration(self.repo, "claude", None)

                self.assertEqual(questionary.path.call_args.kwargs["default"], str(project))
                self.assertIs(questionary.path.call_args.kwargs["validate"](str(project)), True)
                self.assertEqual(selected, ("claude", project))
                self.assertFalse(project.exists())

    def test_explicit_custom_source_is_preserved(self) -> None:
        custom = self.base / "custom transcripts"
        own_file, own_payload = self.transcript(custom)
        self.transcript(self.projects / "another-project", "poison.jsonl")
        self.configure_claude(custom)

        self.assertEqual(self.guarded_scan(own_file), [(own_file, own_payload)])
        questionary = SimpleNamespace(path=Mock())
        with patch.dict(sys.modules, {"questionary": questionary}):
            self.assertEqual(cli._select_configuration(self.repo, "claude", str(custom)), ("claude", custom))
        questionary.path.assert_not_called()


if __name__ == "__main__":
    unittest.main()
