"""Synthetic fixtures only; never inspect local vendor profiles."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent_session_commit import core
from agent_session_commit.adapters.common import ScanResult, read_session_bytes
from agent_session_commit.adapters.qoder_codebuddy import scan_codebuddy, scan_qoder


class VendorScannerTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.root = self.base / "my repo"
        self.other = self.base / "my repo-other"
        self.root.mkdir()
        self.other.mkdir()

    def write(self, path: Path, *records: dict[str, object]) -> tuple[Path, bytes]:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = b"".join((json.dumps(record) + "\n").encode() for record in records)
        path.write_bytes(payload)
        return path, payload

    def test_qoder_cli_and_ide_locations_preserve_physical_paths(self) -> None:
        projects = self.base / ".qoder" / "projects"
        project = projects / "opaque-project-id"
        cli = self.write(project / "session-cli.jsonl",
                         {"type": "user", "cwd": str(self.root), "message": {"content": "hello"}})
        ide = self.write(project / "transcript" / "session-ide.jsonl",
                         {"type": "session_meta", "sessionId": "session-ide",
                          "data": {"meta_type": "session_info", "content": {"mode": "agent"}}},
                         {"type": "user", "cwd": str(self.root), "message": {"content": "hello"}})
        result = scan_qoder(projects, self.root)
        self.assertIsInstance(result, ScanResult)
        self.assertEqual(result.sessions, [cli, ide])
        self.assertEqual(result.skipped_unverified, 0)
        self.assertEqual(scan_qoder(project, self.root).sessions, [cli, ide])

    def test_codebuddy_project_transcript_and_explicit_source(self) -> None:
        projects = self.base / ".codebuddy" / "projects"
        session = self.write(projects / "opaque-id" / "session.jsonl",
                             {"type": "user", "cwd": str(self.root),
                              "message": {"content": "hello"}})
        self.assertEqual(scan_codebuddy(projects, self.root).sessions, [session])
        self.assertEqual(scan_codebuddy(session[0], self.root).sessions, [session])
        custom = self.write(self.base / "chosen source" / "session.jsonl",
                            {"type": "user", "cwd": str(self.root)})
        self.assertEqual(scan_codebuddy(custom[0].parent, self.root).sessions, [custom])

    def test_unrelated_body_mentions_are_not_attribution_or_full_read(self) -> None:
        for scanner, location in ((scan_qoder, ".qoder"), (scan_codebuddy, ".codebuddy")):
            with self.subTest(scanner=scanner.__name__):
                projects = self.base / location / "projects"
                own = self.write(projects / "one" / "own.jsonl",
                                 {"type": "user", "cwd": str(self.root)})
                poison = self.write(projects / "two" / "poison.jsonl",
                                    {"type": "user", "cwd": str(self.other),
                                     "message": {"content": f"mentions {self.root}"}})[0]
                unknown = self.write(projects / "two" / "unknown.jsonl",
                                     {"type": "user", "message": {"content": str(self.root)}})[0]
                with patch("agent_session_commit.adapters.qoder_codebuddy.read_session_bytes",
                           wraps=read_session_bytes) as read:
                    result = scanner(projects, self.root)
                self.assertEqual(result.sessions, [own])
                self.assertEqual(result.skipped_unverified, 2)
                self.assertEqual([call.args[0] for call in read.call_args_list], [own[0]])
                self.assertNotIn(poison, [call.args[0] for call in read.call_args_list])
                self.assertNotIn(unknown, [call.args[0] for call in read.call_args_list])

    def test_unknown_and_non_session_files_are_rejected(self) -> None:
        projects = self.base / ".codebuddy" / "projects"
        project = projects / "opaque-id"
        self.write(project / "unknown.jsonl", {"cwd": str(self.root), "type": "new-format"})
        self.write(project / "history.jsonl", {"type": "user", "cwd": str(self.root)})
        self.write(project / "settings.json", {"type": "user", "cwd": str(self.root)})
        self.write(project / "session-id" / "subagents" / "agent-x.jsonl",
                   {"type": "user", "cwd": str(self.root)})
        self.write(projects / "global.jsonl", {"type": "user", "cwd": str(self.root)})
        result = scan_codebuddy(projects, self.root)
        self.assertEqual(result.sessions, [])
        self.assertEqual(result.skipped_unverified, 1)

    def test_bounded_header_and_conflicting_metadata_fail_closed(self) -> None:
        projects = self.base / ".qoder" / "projects"
        project = projects / "opaque-id"
        large = project / "large.jsonl"
        large.parent.mkdir(parents=True)
        large.write_bytes(b'{"type":"user","message":"' + b"x" * 70_000
                          + b'"}\n' + json.dumps({"type": "user", "cwd": str(self.root)}).encode() + b"\n")
        self.write(project / "conflict.jsonl",
                   {"type": "session_meta", "cwd": str(self.other),
                    "sessionId": "conflict", "data": {"meta_type": "session_info"}},
                   {"type": "user", "cwd": str(self.root)})
        self.write(project / "late-cwd.jsonl",
                   {"type": "user", "message": {"content": str(self.root)}},
                   {"type": "user", "cwd": str(self.root)})
        with patch("agent_session_commit.adapters.qoder_codebuddy.read_session_bytes") as read:
            result = scan_qoder(projects, self.root)
        self.assertEqual(result.sessions, [])
        self.assertEqual(result.skipped_unverified, 3)
        read.assert_not_called()

    def test_symlinked_sources_and_transcripts_are_ignored(self) -> None:
        project = self.base / "selected project"
        real = self.write(project / "real.jsonl", {"type": "user", "cwd": str(self.root)})
        (project / "linked.jsonl").symlink_to(real[0])
        self.assertEqual(scan_codebuddy(project, self.root).sessions, [real])
        alias = self.base / "linked project"
        alias.symlink_to(project, target_is_directory=True)
        self.assertEqual(scan_codebuddy(alias, self.root).sessions, [])


class WorkBuddyTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.root = self.base / "my repo"
        self.root.mkdir()

    def test_default_source_env_override_wins(self) -> None:
        override = self.base / "portable"
        with patch.dict(os.environ, {"WORKBUDDY_CONFIG_DIR": str(override)}):
            self.assertEqual(core.default_source("workbuddy"), override / "projects")

    def test_default_source_prefers_existing_international_dir(self) -> None:
        with patch.dict(os.environ):
            os.environ.pop("WORKBUDDY_CONFIG_DIR", None)
            with patch.object(core.Path, "home", return_value=self.base):
                international = self.base / ".workbuddy-ai" / "projects"
                international.mkdir(parents=True)
                self.assertEqual(core.default_source("workbuddy"), international)

    def test_default_source_falls_back_to_documented_dir(self) -> None:
        with patch.dict(os.environ):
            os.environ.pop("WORKBUDDY_CONFIG_DIR", None)
            with patch.object(core.Path, "home", return_value=self.base):
                documented = self.base / ".workbuddy" / "projects"
                self.assertEqual(core.default_source("workbuddy"), documented)
                documented.mkdir(parents=True)
                self.assertEqual(core.default_source("workbuddy"), documented)

    def test_workbuddy_projects_layout_reuses_codebuddy_verification(self) -> None:
        projects = self.base / ".workbuddy" / "projects"
        owned = projects / "opaque-id"
        owned.mkdir(parents=True)
        session = owned / "session.jsonl"
        session.write_text(json.dumps({"type": "user", "cwd": str(self.root)}) + "\n",
                           encoding="utf-8")
        unverified = owned / "unverified.jsonl"
        unverified.write_text(json.dumps({"type": "user", "message": {"content": str(self.root)}}) + "\n",
                              encoding="utf-8")
        result = scan_codebuddy(projects, self.root)
        self.assertEqual(result.sessions, [(session, session.read_bytes())])
        self.assertEqual(result.skipped_unverified, 1)


if __name__ == "__main__":
    unittest.main()
