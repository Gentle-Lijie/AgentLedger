"""Synthetic privacy and format checks; never inspect local agent history."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent_session_commit import core
from agent_session_commit.adapters import codex_copilot
from agent_session_commit.adapters.common import MAX_SESSION_BYTES


SESSION_ID = "12345678-1234-1234-1234-123456789abc"


class ScannerTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.repo = self.base / "my repo"
        self.repo.mkdir()
        self.other = self.base / "other repo"
        self.other.mkdir()
        self.codex = self.base / "codex" / "sessions"
        self.copilot = self.base / "copilot" / "session-state"
        self.codex.mkdir(parents=True)
        self.copilot.mkdir(parents=True)

    def rollout(self, cwd: object, *, name: str | None = None, first: dict | None = None) -> tuple[Path, bytes]:
        day = self.codex / "2026" / "09" / "30"
        day.mkdir(parents=True, exist_ok=True)
        path = day / (name or f"rollout-2026-09-30T12-34-56-{SESSION_ID}.jsonl")
        record = first if first is not None else {"type": "session_meta", "payload": {"cwd": cwd}}
        body = (json.dumps(record) + "\n" + json.dumps({"type": "event_msg", "payload": {
            "text": f"mentions {self.other} and {self.repo}"}}) + "\n").encode()
        path.write_bytes(body)
        return path, body

    def copilot_session(self, cwd: object, *, metadata: str | None = None,
                        first: dict | None = None, session_id: str = SESSION_ID) -> tuple[Path, bytes]:
        directory = self.copilot / session_id
        directory.mkdir(parents=True, exist_ok=True)
        event = first if first is not None else {"type": "session.start", "data": {
            "context": {"cwd": cwd}}}
        body = (json.dumps(event) + "\n" + json.dumps({"type": "user.message", "data": {
            "content": f"mentions {self.other} and {self.repo}"}}) + "\n").encode()
        path = directory / "events.jsonl"
        path.write_bytes(body)
        if metadata is not None:
            (directory / "workspace.yaml").write_text(metadata, encoding="utf-8")
        return path, body

    def test_codex_rejects_rollout_in_nested_cwd(self) -> None:
        nested = self.repo / "src"
        nested.mkdir()
        path, body = self.rollout(str(nested))
        result = codex_copilot.scan_codex(self.codex, self.repo)
        self.assertEqual(result.sessions, [])
        self.assertEqual(result.skipped_unverified, 1)

    def test_codex_accepts_exact_git_root(self) -> None:
        path, body = self.rollout(str(self.repo))
        self.assertEqual(codex_copilot.scan_codex(self.codex, self.repo).sessions, [(path, body)])

    def test_codex_caches_other_project_headers_but_discovers_changed_sessions(self) -> None:
        owned, body = self.rollout(str(self.repo))
        other, _ = self.rollout(
            str(self.other), name=f"rollout-2026-09-30T12-34-57-{SESSION_ID}.jsonl"
        )
        cache = self.base / "private-git-state" / "codex-candidates.json"
        first = codex_copilot.scan_codex(self.codex, self.repo, cache_path=cache)
        self.assertEqual(first.sessions, [(owned, body)])
        self.assertTrue(cache.is_file())
        with patch.object(codex_copilot, "read_jsonl_header",
                          wraps=codex_copilot.read_jsonl_header) as read:
            second = codex_copilot.scan_codex(self.codex, self.repo, cache_path=cache)
        self.assertEqual(second.sessions, [(owned, body)])
        self.assertEqual([call.args[0] for call in read.call_args_list], [owned])

        for_other = codex_copilot.scan_codex(self.codex, self.other, cache_path=cache)
        self.assertEqual([path for path, _ in for_other.sessions], [other])

        other.write_text(json.dumps({"type": "session_meta", "payload": {"cwd": str(self.repo)}})
                         + "\n", encoding="utf-8")
        third = codex_copilot.scan_codex(self.codex, self.repo, cache_path=cache)
        self.assertEqual([path for path, _ in third.sessions], [owned, other])

    def test_codex_accepts_documented_revert_rollout_suffix(self) -> None:
        rollout_id = "12345678-1234-1234-1234-123456789abd"
        path, body = self.rollout(str(self.repo),
                                  name=f"rollout-2026-09-30T12-34-56-{SESSION_ID}_{rollout_id}.jsonl",
                                  first={"type": "session_meta", "payload": {
                                      "cwd": str(self.repo), "id": SESSION_ID}})
        self.assertEqual(codex_copilot.scan_codex(self.codex, self.repo).sessions, [(path, body)])

    def test_codex_rejects_other_project_and_unknown_first_metadata_before_body_read(self) -> None:
        other, _ = self.rollout(str(self.other))
        unknown, _ = self.rollout(str(self.repo), name=f"rollout-2026-09-30T12-34-57-{SESSION_ID}.jsonl",
                                  first={"type": "event_msg", "payload": {"cwd": str(self.repo)}})
        with patch.object(codex_copilot, "read_session_bytes", side_effect=AssertionError("body read")):
            result = codex_copilot.scan_codex(self.codex, self.repo)
        self.assertEqual(result.sessions, [])
        self.assertEqual(result.skipped_unverified, 2)
        self.assertTrue(other.exists() and unknown.exists())

    def test_codex_ignores_artifacts_and_rejects_large_and_linked_rollouts(self) -> None:
        path, _ = self.rollout(str(self.repo))
        (path.parent / "notes.md").write_text(str(self.repo), encoding="utf-8")
        (path.parent / "random.jsonl").write_text(str(self.repo), encoding="utf-8")
        linked = path.with_name(f"rollout-2026-09-30T12-34-57-{SESSION_ID}.jsonl")
        try:
            linked.symlink_to(path)
        except (OSError, NotImplementedError):
            pass
        with patch.object(codex_copilot, "read_session_bytes", return_value=None) as read:
            result = codex_copilot.scan_codex(self.codex, self.repo)
        self.assertEqual(result.sessions, [])
        self.assertEqual(result.skipped_unverified, 1 + int(linked.is_symlink()))
        read.assert_called_once_with(path)

    def test_codex_oversized_file_and_conflicting_id_are_skipped_without_body_read(self) -> None:
        huge, _ = self.rollout(str(self.repo))
        with huge.open("ab") as stream:
            stream.truncate(MAX_SESSION_BYTES + 1)
        wrong_id = "12345678-1234-1234-1234-123456789abd"
        self.rollout(str(self.repo), name=f"rollout-2026-09-30T12-34-57-{SESSION_ID}.jsonl",
                     first={"type": "session_meta", "payload": {"cwd": str(self.repo), "id": wrong_id}})
        original = codex_copilot.read_session_bytes
        calls: list[Path] = []

        def guarded_read(path: Path) -> bytes | None:
            calls.append(path)
            return original(path)

        with patch.object(codex_copilot, "read_session_bytes", side_effect=guarded_read):
            result = codex_copilot.scan_codex(self.codex, self.repo)
        self.assertEqual(result.sessions, [])
        self.assertEqual(result.skipped_unverified, 2)
        self.assertEqual(calls, [huge])

    def test_copilot_accepts_matching_event_and_workspace_metadata(self) -> None:
        path, body = self.copilot_session(str(self.repo), metadata=f"id: {SESSION_ID}\ncwd: '{self.repo}'\n")
        result = codex_copilot.scan_copilot(self.copilot, self.repo)
        self.assertEqual(result.sessions, [(path, body)])
        self.assertEqual(result.skipped_unverified, 0)

    def test_copilot_accepts_session_start_when_workspace_yaml_absent(self) -> None:
        path, body = self.copilot_session(str(self.repo))
        self.assertEqual(codex_copilot.scan_copilot(self.copilot, self.repo).sessions, [(path, body)])

    def test_copilot_rejects_nested_cwd(self) -> None:
        self.copilot_session(str(self.repo / "src"))
        self.assertEqual(codex_copilot.scan_copilot(self.copilot, self.repo).sessions, [])

    def test_copilot_rejects_other_project_and_missing_start_metadata_before_body_read(self) -> None:
        self.copilot_session(str(self.other), metadata=f"cwd: '{self.other}'\n")
        second_id = "12345678-1234-1234-1234-123456789abd"
        self.copilot_session(str(self.repo), session_id=second_id,
                             first={"type": "user.message", "data": {"text": str(self.repo)}})
        with patch.object(codex_copilot, "read_session_bytes", side_effect=AssertionError("body read")):
            result = codex_copilot.scan_copilot(self.copilot, self.repo)
        self.assertEqual(result.sessions, [])
        self.assertEqual(result.skipped_unverified, 2)

    def test_copilot_rejects_conflicting_or_oversized_workspace_metadata(self) -> None:
        path, _ = self.copilot_session(str(self.repo), metadata=f"cwd: '{self.other}'\n")
        with patch.object(codex_copilot, "read_session_bytes", side_effect=AssertionError("body read")):
            result = codex_copilot.scan_copilot(self.copilot, self.repo)
        self.assertEqual(result.skipped_unverified, 1)
        (path.parent / "workspace.yaml").write_text(f"id: {SESSION_ID}\nsummary: no cwd\n", encoding="utf-8")
        with patch.object(codex_copilot, "read_session_bytes", side_effect=AssertionError("body read")):
            result = codex_copilot.scan_copilot(self.copilot, self.repo)
        self.assertEqual(result.skipped_unverified, 1)
        (path.parent / "workspace.yaml").write_bytes(b"x" * (64 * 1024 + 1))
        with patch.object(codex_copilot, "read_session_bytes", side_effect=AssertionError("body read")):
            result = codex_copilot.scan_copilot(self.copilot, self.repo)
        self.assertEqual(result.skipped_unverified, 1)

    def test_copilot_ignores_non_session_artifacts_and_rejects_linked_events(self) -> None:
        path, _ = self.copilot_session(str(self.repo))
        (path.parent / "notes.md").write_text(str(self.repo), encoding="utf-8")
        (self.copilot / "random.jsonl").write_text(str(self.repo), encoding="utf-8")
        path.unlink()
        external = self.base / "poison.jsonl"
        external.write_text(str(self.repo), encoding="utf-8")
        try:
            path.symlink_to(external)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks unavailable")
        with patch.object(codex_copilot, "read_session_bytes", side_effect=AssertionError("body read")):
            result = codex_copilot.scan_copilot(self.copilot, self.repo)
        self.assertEqual(result.sessions, [])
        self.assertEqual(result.skipped_unverified, 1)

    def test_copilot_rejects_missing_cwd_and_unrelated_metadata_file(self) -> None:
        self.copilot_session(None, first={"type": "session.start", "data": {"context": {}}},
                             metadata=f"cwd: '{self.repo}'\n")
        with patch.object(codex_copilot, "read_session_bytes", side_effect=AssertionError("body read")):
            result = codex_copilot.scan_copilot(self.copilot, self.repo)
        self.assertEqual(result.skipped_unverified, 1)

    def test_copilot_oversized_log_and_conflicting_event_id_are_skipped(self) -> None:
        huge, _ = self.copilot_session(str(self.repo))
        with huge.open("ab") as stream:
            stream.truncate(MAX_SESSION_BYTES + 1)
        second_id = "12345678-1234-1234-1234-123456789abd"
        self.copilot_session(str(self.repo), session_id=second_id,
                             first={"type": "session.start", "data": {
                                 "sessionId": SESSION_ID, "context": {"cwd": str(self.repo)}}})
        original = codex_copilot.read_session_bytes
        calls: list[Path] = []

        def guarded_read(path: Path) -> bytes | None:
            calls.append(path)
            return original(path)

        with patch.object(codex_copilot, "read_session_bytes", side_effect=guarded_read):
            result = codex_copilot.scan_copilot(self.copilot, self.repo)
        self.assertEqual(result.sessions, [])
        self.assertEqual(result.skipped_unverified, 2)
        self.assertEqual(calls, [huge])


class CopilotVscodeScannerTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.repo = self.base / "my repo"
        self.repo.mkdir()
        self.other = self.base / "other repo"
        self.other.mkdir()
        self.vscode = self.base / "vscode" / "User" / "workspaceStorage"

    def entry(self, folder: object, *, name: str = "a", session_id: str = SESSION_ID,
              ext: str = ".jsonl", first: dict | None = None,
              body: bytes | None = None) -> tuple[Path, bytes]:
        storage = self.vscode / name
        chat = storage / "chatSessions"
        chat.mkdir(parents=True, exist_ok=True)
        workspace = folder if isinstance(folder, str) else json.dumps(folder)
        (storage / "workspace.json").write_text(workspace, encoding="utf-8")
        path = chat / f"{session_id}{ext}"
        if body is None:
            if ext == ".jsonl":
                record = first if first is not None else {"kind": 0, "v": {
                    "sessionId": session_id, "requests": []}}
                body = (json.dumps(record) + "\n" + json.dumps({"kind": 2, "v": {
                    "text": f"mentions {self.other} and {self.repo}"}}) + "\n").encode()
            else:
                document = first if first is not None else {"sessionId": session_id, "requests": []}
                body = json.dumps(document).encode()
        path.write_bytes(body)
        return path, body

    def test_accepts_json_and_jsonl_from_user_root_parent(self) -> None:
        json_path, json_body = self.entry({"folder": self.repo.as_uri()}, name="a", ext=".json")
        jsonl_path, jsonl_body = self.entry({"folder": self.repo.as_uri()}, name="b", ext=".jsonl")
        result = codex_copilot.scan_copilot_vscode(self.vscode.parent, self.repo)
        self.assertEqual(result.sessions, [(json_path, json_body), (jsonl_path, jsonl_body)])
        self.assertEqual(result.skipped_unverified, 0)

    def test_accepts_multi_root_code_workspace_reference(self) -> None:
        workspace_file = self.base / "team.code-workspace"
        workspace_file.write_text(json.dumps({"folders": [
            {"uri": self.other.as_uri()},
            {"path": str(self.repo)},
        ]}), encoding="utf-8")
        path, body = self.entry({"workspace": workspace_file.as_uri()})
        result = codex_copilot.scan_copilot_vscode(self.vscode, self.repo)
        self.assertEqual(result.sessions, [(path, body)])

    def test_rejects_other_project_and_unattributable_storage_before_body_read(self) -> None:
        self.entry({"folder": self.other.as_uri()})
        self.entry({"folder": "vscode-remote://ssh-remote%2Bvm/home/zlj"}, name="b")
        storage = self.vscode / "c"
        (storage / "chatSessions").mkdir(parents=True)
        (storage / "workspace.json").write_text("not json", encoding="utf-8")
        (storage / "chatSessions" / f"{SESSION_ID}.jsonl").write_bytes(b"{}")
        with patch.object(codex_copilot, "read_session_bytes", side_effect=AssertionError("body read")):
            result = codex_copilot.scan_copilot_vscode(self.vscode, self.repo)
        self.assertEqual(result.sessions, [])
        self.assertEqual(result.skipped_unverified, 0)

    def test_rejects_nested_workspace_folder(self) -> None:
        self.entry({"folder": (self.repo / "src").as_uri()})
        self.assertEqual(codex_copilot.scan_copilot_vscode(self.vscode, self.repo).sessions, [])

    def test_jsonl_session_id_must_agree_with_filename(self) -> None:
        second_id = "12345678-1234-1234-1234-123456789abd"
        self.entry({"folder": self.repo.as_uri()},
                   first={"kind": 0, "v": {"sessionId": second_id, "requests": []}})
        with patch.object(codex_copilot, "read_session_bytes", side_effect=AssertionError("body read")):
            result = codex_copilot.scan_copilot_vscode(self.vscode, self.repo)
        self.assertEqual(result.sessions, [])
        self.assertEqual(result.skipped_unverified, 1)
        self.entry({"folder": self.repo.as_uri()}, name="b",
                   first={"kind": 0, "v": {"requests": []}})
        self.assertEqual(len(codex_copilot.scan_copilot_vscode(self.vscode, self.repo).sessions), 1)

    def test_ignores_artifacts_and_rejects_linked_sessions(self) -> None:
        path, _ = self.entry({"folder": self.repo.as_uri()})
        chat = path.parent
        (chat / "notes.md").write_text(str(self.repo), encoding="utf-8")
        (chat / f"{SESSION_ID}.txt").write_text(str(self.repo), encoding="utf-8")
        (chat / "random.jsonl").write_text(str(self.repo), encoding="utf-8")
        path.unlink()
        external = self.base / "poison.json"
        external.write_text(str(self.repo), encoding="utf-8")
        try:
            path.symlink_to(external)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks unavailable")
        with patch.object(codex_copilot, "read_session_bytes", side_effect=AssertionError("body read")):
            result = codex_copilot.scan_copilot_vscode(self.vscode, self.repo)
        self.assertEqual(result.sessions, [])
        self.assertEqual(result.skipped_unverified, 1)

    def test_oversized_session_is_skipped(self) -> None:
        huge, _ = self.entry({"folder": self.repo.as_uri()})
        with huge.open("ab") as stream:
            stream.truncate(MAX_SESSION_BYTES + 1)
        self.assertEqual(codex_copilot.scan_copilot_vscode(self.vscode, self.repo).sessions, [])
        self.assertEqual(codex_copilot.scan_copilot_vscode(self.vscode, self.repo).skipped_unverified, 1)

    def test_unusable_code_workspace_reference_is_ignored(self) -> None:
        self.entry({"workspace": (self.base / "missing.code-workspace").as_uri()})
        broken = self.base / "broken.code-workspace"
        broken.write_text("{not json", encoding="utf-8")
        self.entry({"workspace": broken.as_uri()}, name="b")
        valid = self.base / "valid.code-workspace"
        valid.write_text(json.dumps({"folders": [{"path": str(self.repo)}]}), encoding="utf-8")
        accepted, _ = self.entry({"workspace": valid.as_uri()}, name="c")
        try:
            linked = self.base / "linked.code-workspace"
            linked.write_text(json.dumps({"folders": [{"path": str(self.repo)}]}), encoding="utf-8")
            broken.unlink()
            broken.symlink_to(linked)
        except (OSError, NotImplementedError):
            pass
        result = codex_copilot.scan_copilot_vscode(self.vscode, self.repo)
        # A linked or malformed reference never establishes ownership, so only
        # the regular-file workspace entry contributes its session.
        self.assertEqual([path for path, _ in result.sessions], [accepted])
        self.assertEqual(result.skipped_unverified, 0)


class CopilotVscodeDefaultSourceTests(unittest.TestCase):
    def test_env_override_wins(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            override = Path(temporary) / "portable" / "User"
            with patch.dict(os.environ, {"COPILOT_VSCODE_HOME": str(override)}):
                self.assertEqual(core.default_source("copilot-vscode"), override / "workspaceStorage")

    def test_platform_defaults(self) -> None:
        # pathlib cannot construct a WindowsPath on POSIX hosts, so the win32
        # branch is exercised only where it runs natively; CI covers Windows.
        cases = [("posix", "darwin"), ("posix", "linux")]
        if os.name == "nt":
            cases.insert(0, ("nt", "win32"))
        for name, platform in cases:
            with self.subTest(platform=platform):
                home = classmethod(lambda cls: Path("/home/tester"))
                environment = {"APPDATA": "/roam"} if platform == "win32" else {}
                with patch.object(core.os, "name", name), \
                        patch.object(core.sys, "platform", platform), \
                        patch.object(core.Path, "home", home), \
                        patch.dict(os.environ, environment, clear=False):
                    os.environ.pop("COPILOT_VSCODE_HOME", None)
                    if platform == "win32":
                        expected = Path("/roam") / "Code" / "User"
                    elif platform == "darwin":
                        expected = Path("/home/tester") / "Library" / "Application Support" / "Code" / "User"
                    else:
                        expected = Path("/home/tester") / ".config" / "Code" / "User"
                    self.assertEqual(core.default_source("copilot-vscode"),
                                     expected / "workspaceStorage")


if __name__ == "__main__":
    unittest.main()
