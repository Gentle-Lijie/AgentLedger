from __future__ import annotations

import json
import os
import subprocess
import tarfile
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from agent_session_commit.core import AGENTS, configure


class HookIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        base = Path(self.temp.name)
        self.repo = base / "repo"
        self.source = base / "sessions"
        self.repo.mkdir()
        self.source.mkdir()
        subprocess.run(["git", "init", "--quiet", str(self.repo)], check=True)
        self._git("config", "user.name", "Test User")
        self._git("config", "user.email", "test@example.invalid")
        self._git("config", "commit.gpgsign", "false")
        self._git("config", "core.autocrlf", "false")
        self._git("config", "core.hooksPath", ".git/hooks")
        self.transcript = self.source / "session.jsonl"
        self.first_line = json.dumps({"cwd": str(self.repo), "message": "first"}) + "\n"
        self.transcript.write_bytes(self.first_line.encode("utf-8"))
        (self.repo / "tracked.txt").write_bytes(b"initial\n")
        self._git("add", "tracked.txt")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _git(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        if env.get("AGENT_SESSION_TEST_INSTALLED") == "1":
            env.pop("PYTHONPATH", None)
        else:
            env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
        env.pop("AGENT_SESSION_COMMIT_RECURSION", None)
        return subprocess.run(
            ["git", "-C", str(self.repo), *args],
            env=env,
            text=True,
            capture_output=True,
            check=check,
            timeout=30,
        )

    def _install_hooks(self, *, original_hooks: bool = False) -> None:
        hooks_dir = self.repo / ".git" / "hooks"
        if original_hooks:
            for name, body in {
                "pre-commit": "printf 'pre-commit\\n' >> .git/original-pre-calls\n",
                "post-commit": (
                    "git rev-parse HEAD >> .git/original-post-heads\n"
                    "git ls-tree -r --name-only HEAD > .git/original-post-tree\n"
                ),
            }.items():
                path = hooks_dir / name
                path.write_text("#!/bin/sh\n" + body, encoding="utf-8", newline="\n")
                path.chmod(path.stat().st_mode | 0o111)
        configure(self.repo, "custom", self.source)
        # Count wrapper entry, even if a recursion guard skips the agent itself.
        # The internal amend should disable all hooks, so neither wrapper runs twice.
        for name in ("pre-commit", "post-commit"):
            path = hooks_dir / name
            contents = path.read_text(encoding="utf-8")
            contents = contents.replace(
                "#!/bin/sh\n",
                f"#!/bin/sh\nprintf '{name}\\n' >> .git/agent-hook-invocations\n",
                1,
            )
            path.write_text(contents, encoding="utf-8", newline="\n")

    def _bundles(self) -> set[Path]:
        return set((self.repo / ".agent-sessions" / "bundles").glob("*.tar.gz"))

    def _append_transcript(self, message: str) -> bytes:
        line = (json.dumps({"cwd": str(self.repo), "message": message}) + "\n").encode("utf-8")
        with self.transcript.open("ab") as stream:
            stream.write(line)
        return line

    def _assert_hook_count(self, user_commits: int) -> None:
        calls = (self.repo / ".git" / "agent-hook-invocations").read_text(encoding="utf-8")
        self.assertEqual(calls.splitlines(), ["pre-commit", "post-commit"] * user_commits)

    def _assert_amend_preserved_commit(self) -> None:
        # The reflog retains the user's commit before post-commit amends it.
        original = self._git("rev-parse", "HEAD@{1}").stdout.strip()
        final = self._git("rev-parse", "HEAD").stdout.strip()
        self.assertNotEqual(final, original)
        self.assertEqual(self._git("reflog", "-1", "--format=%gs").stdout.split(":", 1)[0],
                         "commit (amend)")
        before = self._git("cat-file", "commit", original).stdout
        after = self._git("cat-file", "commit", final).stdout
        before_headers, before_message = before.split("\n\n", 1)
        after_headers, after_message = after.split("\n\n", 1)
        self.assertEqual(after_message, before_message)
        for field in ("author ", "parent "):
            self.assertEqual(
                [line for line in after_headers.splitlines() if line.startswith(field)],
                [line for line in before_headers.splitlines() if line.startswith(field)],
            )
        self.assertEqual(self._git("show", "-s", "--format=%cn <%ce>", "HEAD").stdout.strip(),
                         "Test User <test@example.invalid>")

    def _assert_bundles_committed(self) -> None:
        paths = {path.relative_to(self.repo).as_posix() for path in self._bundles()}
        self.assertEqual(
            set(self._git("ls-tree", "-r", "--name-only", "HEAD", "--", ".agent-sessions").stdout.splitlines()),
            paths,
        )

    def _manifest_and_payload(self, bundle: Path) -> tuple[dict[str, object], bytes]:
        with tarfile.open(bundle, "r:gz") as archive:
            manifest = json.load(archive.extractfile("manifest.json"))
            file_record = manifest["files"][0]
            payload = archive.extractfile(f"sessions/{file_record['path']}").read()
        return file_record, payload

    def test_post_commit_amends_initial_file_then_only_appended_bytes(self) -> None:
        self._install_hooks()
        self._git("commit", "--quiet", "--author=Session Author <author@example.invalid>",
                  "--date=2024-01-02T03:04:05+00:00", "-m", "initial", "-m", "Keep this body.\nAnd this line.")
        self._assert_amend_preserved_commit()
        self.assertEqual(self._git("rev-list", "--count", "HEAD").stdout.strip(), "1")
        self.assertEqual(self._git("show", "-s", "--format=%an <%ae>").stdout.strip(),
                         "Session Author <author@example.invalid>")
        author_date = self._git("show", "-s", "--format=%aI").stdout.strip()
        self.assertEqual(datetime.fromisoformat(author_date.replace("Z", "+00:00")),
                         datetime.fromisoformat("2024-01-02T03:04:05+00:00"))
        self.assertEqual(self._git("show", "-s", "--format=%P").stdout.strip(), "")
        bundles = self._bundles()
        self.assertEqual(len(bundles), 1)
        first_record, first_payload = self._manifest_and_payload(next(iter(bundles)))
        self.assertEqual(first_record["mode"], "full")
        self.assertEqual(first_payload, self.first_line.encode("utf-8"))
        self._assert_bundles_committed()
        self._assert_hook_count(1)
        first_head = self._git("rev-parse", "HEAD").stdout.strip()

        # An unchanged transcript must not amend or add a bundle to this commit.
        self._git("commit", "--quiet", "--allow-empty", "-m", "second")
        second_head = self._git("rev-parse", "HEAD").stdout.strip()
        self.assertEqual(self._git("reflog", "-1", "--format=%gs").stdout.strip(), "commit: second")
        self.assertEqual(self._git("show", "-s", "--format=%P").stdout.strip(), first_head)
        self.assertEqual(self._bundles(), bundles)
        self.assertEqual(self._git("rev-list", "--count", "HEAD").stdout.strip(), "2")
        self.assertEqual(self._git("diff", "--cached", "--name-only").stdout, "")
        self._assert_hook_count(2)

        appended_line = self._append_transcript("third")
        self._git("commit", "--quiet", "--allow-empty", "-m", "third")
        self._assert_amend_preserved_commit()
        self.assertEqual(self._git("rev-list", "--count", "HEAD").stdout.strip(), "3")
        self.assertEqual(self._git("log", "--format=%s").stdout.splitlines(), ["third", "second", "initial"])
        self.assertEqual(self._git("show", "-s", "--format=%P").stdout.strip(), second_head)
        new_bundles = self._bundles() - bundles
        self.assertEqual(len(new_bundles), 1)
        second_record, second_payload = self._manifest_and_payload(next(iter(new_bundles)))
        self.assertEqual(second_record["mode"], "append")
        self.assertEqual(second_record["offset"], len(self.first_line.encode("utf-8")))
        self.assertEqual(second_payload, appended_line)
        self._assert_bundles_committed()
        self.assertEqual(self._git("status", "--porcelain").stdout, "")
        self._assert_hook_count(3)

    def test_commit_archives_only_sessions_started_at_git_root(self) -> None:
        self.transcript.write_text(
            json.dumps({"cwd": str(self.repo / "src"), "message": "nested"}) + "\n",
            encoding="utf-8",
        )
        sibling = self.source / "sibling.jsonl"
        sibling.write_text(
            json.dumps({"cwd": str(self.repo) + "-other", "message": "other"}) + "\n",
            encoding="utf-8",
        )
        self._install_hooks()
        self.assertEqual(
            self._git("config", "--local", "--get", "agent-session.workdir").stdout.strip(),
            str(self.repo.resolve()),
        )
        self._git("commit", "--quiet", "-m", "without matching sessions")
        self.assertEqual(self._bundles(), set())

        owned = self.source / "owned.jsonl"
        owned.write_text(self.first_line, encoding="utf-8")
        self._git("commit", "--quiet", "--allow-empty", "-m", "with matching session")
        bundle, = self._bundles()
        with tarfile.open(bundle, "r:gz") as archive:
            manifest = json.load(archive.extractfile("manifest.json"))
        self.assertEqual([item["path"] for item in manifest["files"]], [owned.name])

    def test_pathspec_commit_preserves_other_staged_and_unstaged_changes(self) -> None:
        self._install_hooks()
        for name in ("partial.txt", "unstaged.txt"):
            (self.repo / name).write_bytes(b"baseline\n")
        self._git("add", "partial.txt", "unstaged.txt")
        self._git("commit", "--quiet", "-m", "baseline")
        parent = self._git("rev-parse", "HEAD").stdout.strip()

        (self.repo / "partial.txt").write_bytes(b"staged version\n")
        (self.repo / "new-staged.txt").write_bytes(b"keep staged\n")
        self._git("add", "partial.txt", "new-staged.txt")
        (self.repo / "partial.txt").write_bytes(b"unstaged version\n")
        (self.repo / "unstaged.txt").write_bytes(b"unstaged only\n")
        (self.repo / "tracked.txt").write_bytes(b"selected staged version\n")
        self._git("add", "tracked.txt")
        (self.repo / "tracked.txt").write_bytes(b"selected working version\n")

        unrelated = ("partial.txt", "new-staged.txt", "unstaged.txt")
        index_before = self._git("ls-files", "--stage", "--", *unrelated).stdout
        staged_before = self._git("diff", "--cached", "--", *unrelated).stdout
        unstaged_before = self._git("diff", "--", *unrelated).stdout
        worktree_before = {name: (self.repo / name).read_bytes() for name in unrelated}
        appended_line = self._append_transcript("pathspec commit")
        bundles_before = self._bundles()

        self._git("commit", "--quiet", "--only", "-m", "selected file", "--", "tracked.txt")

        self._assert_amend_preserved_commit()
        self.assertEqual(self._git("rev-list", "--count", "HEAD").stdout.strip(), "2")
        self.assertEqual(self._git("show", "-s", "--format=%P").stdout.strip(), parent)
        self.assertEqual(self._git("show", "HEAD:tracked.txt").stdout, "selected working version\n")
        self.assertEqual(self._git("show", "HEAD:partial.txt").stdout, "baseline\n")
        self.assertEqual(self._git("show", "HEAD:unstaged.txt").stdout, "baseline\n")
        self.assertNotEqual(self._git("cat-file", "-e", "HEAD:new-staged.txt", check=False).returncode, 0)
        self.assertEqual(self._git("ls-files", "--stage", "--", *unrelated).stdout, index_before)
        self.assertEqual(self._git("diff", "--cached", "--", *unrelated).stdout, staged_before)
        self.assertEqual(self._git("diff", "--", *unrelated).stdout, unstaged_before)
        self.assertEqual({name: (self.repo / name).read_bytes() for name in unrelated}, worktree_before)
        self.assertEqual(set(self._git("diff", "--cached", "--name-only").stdout.splitlines()),
                         {"partial.txt", "new-staged.txt"})
        self.assertEqual(set(self._git("diff", "--name-only").stdout.splitlines()),
                         {"partial.txt", "unstaged.txt"})
        new_bundles = self._bundles() - bundles_before
        self.assertEqual(len(new_bundles), 1)
        record, payload = self._manifest_and_payload(next(iter(new_bundles)))
        self.assertEqual(record["mode"], "append")
        self.assertEqual(payload, appended_line)
        self._assert_bundles_committed()
        self._assert_hook_count(2)

    def test_original_post_hook_runs_once_after_archiving_and_sees_final_head(self) -> None:
        self._install_hooks(original_hooks=True)
        expected_heads: list[str] = []
        for number in range(1, 4):
            with self.subTest(user_commit=number):
                if number == 2:
                    self._append_transcript("second commit")
                self._git("commit", "--quiet", "--allow-empty", "-m", f"user commit {number}")
                expected_heads.append(self._git("rev-parse", "HEAD").stdout.strip())
                actual_heads = (self.repo / ".git" / "original-post-heads").read_text(encoding="utf-8")
                self.assertEqual(actual_heads.splitlines(), expected_heads)
                pre_calls = (self.repo / ".git" / "original-pre-calls").read_text(encoding="utf-8")
                self.assertEqual(pre_calls.splitlines(), ["pre-commit"] * number)
                observed_tree = (self.repo / ".git" / "original-post-tree").read_text(encoding="utf-8")
                self.assertEqual(observed_tree, self._git("ls-tree", "-r", "--name-only", "HEAD").stdout)
                expected_bundles = 1 if number == 1 else 2
                self.assertEqual(len(self._bundles()), expected_bundles)
                for bundle in self._bundles():
                    self.assertIn(bundle.relative_to(self.repo).as_posix(), observed_tree.splitlines())
                self.assertEqual(self._git("rev-list", "--count", "HEAD").stdout.strip(), str(number))
                self._assert_hook_count(number)
                self.assertEqual(self._git("status", "--porcelain").stdout, "")

    def test_all_requested_agents_are_selectable(self) -> None:
        self.assertTrue({"zcode", "qoder", "trae", "codebuddy", "workbuddy", "claude",
                         "codex", "copilot", "copilot-vscode", "hermes", "pi",
                         "deepseek-harness"}.issubset(AGENTS))


if __name__ == "__main__":
    unittest.main()
