"""Synthetic privacy and format checks; never inspect local agent history."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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


if __name__ == "__main__":
    unittest.main()
