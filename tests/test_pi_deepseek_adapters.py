"""Synthetic, private-data-free scanner tests for native session layouts."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import zstandard

from agent_session_commit.adapters.common import ScanResult, read_session_bytes
from agent_session_commit.adapters.pi_deepseek import scan_deepseek, scan_pi


class SessionScannerTests(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        self.repo = self.base / "repo"
        self.other = self.base / "repo-other"
        self.repo.mkdir()
        self.other.mkdir()
        self.compressor = zstandard.ZstdCompressor(
            write_checksum=True, write_content_size=False
        )

    def row(self, cwd: Path, **extra: object) -> bytes:
        return (json.dumps({"type": "session", "cwd": str(cwd), **extra}) + "\n").encode()

    def test_first_run_and_unknown_files(self) -> None:
        pi_home = self.base / "pi-home"
        dsh_home = self.base / "dsh-home"
        pi_home.mkdir()
        dsh_home.mkdir()
        (pi_home / "auth.json").write_text(json.dumps({"cwd": str(self.repo)}))
        (dsh_home / "credentials.json").write_text(json.dumps({"cwd": str(self.repo)}))
        self.assertEqual(scan_pi(pi_home, self.repo), ScanResult())
        self.assertEqual(scan_deepseek(dsh_home, self.repo), ScanResult())

    def test_pi_project_header_and_explicit_source(self) -> None:
        home = self.base / "pi-home"
        project = home / "sessions" / "--repo--"
        project.mkdir(parents=True)
        good = project / "2026-09-30T10-20-30-000Z_id.jsonl"
        payload = self.row(self.repo) + b'{"type":"message","text":"ok"}\n'
        good.write_bytes(payload)
        poison = project / "2026-09-30T10-20-31-000Z_other.jsonl"
        poison.write_bytes(self.row(self.other) + str(self.repo).encode() + b"\n")
        nested = project / "2026-09-30T10-20-32-000Z_nested.jsonl"
        nested.write_bytes(self.row(self.repo / "subdir"))
        (project / "auth.json").write_bytes(self.row(self.repo))
        (project / "session.jsonl").write_bytes(self.row(self.repo))
        with patch("agent_session_commit.adapters.pi_deepseek.read_session_bytes",
                   wraps=read_session_bytes) as body_read:
            found = scan_pi(home, self.repo)
            self.assertEqual(body_read.call_count, 1)
        self.assertEqual(found.sessions, [(good, payload)])
        self.assertEqual(found.skipped_unverified, 2)
        self.assertEqual(scan_pi(project, self.repo).sessions, [(good, payload)])
        self.assertEqual(scan_pi(home / "sessions", self.repo).sessions, [(good, payload)])

    def test_harness_configured_root_and_appended_frames(self) -> None:
        source = self.base / "configured-persistence"
        project = source / "--repo--"
        session = project / "session-one"
        session.mkdir(parents=True)
        old = session / "session.jsonl"
        old.write_bytes(self.row(self.repo) + b'{"old":true}\n')
        current = session / "session.v4.jsonl.zstd"
        header = self.row(self.repo, version=4)
        first = b'{"type":"message","text":"first"}\n'
        second = b'{"type":"message","text":"second"}\n'
        current.write_bytes(b"".join(self.compressor.compress(row) for row in (header, first, second)))
        (session / "session.v04.jsonl.zstd").write_bytes(self.compressor.compress(self.row(self.repo)))
        (session / "auth.json").write_bytes(self.row(self.repo))
        expected = (current.with_name(current.name + ".decompressed.jsonl"), header + first + second)
        self.assertEqual(scan_deepseek(source, self.repo).sessions, [expected])
        self.assertEqual(scan_deepseek(project, self.repo).sessions, [expected])

    def test_harness_direct_explicit_root_keeps_appended_frames(self) -> None:
        source = self.base / "explicit-session-root"
        source.mkdir()
        log = source / "session.jsonl.zstd"
        header = self.row(self.repo)
        first = b'{"type":"message","text":"first"}\n'
        second = b'{"type":"message","text":"second"}\n'
        log.write_bytes(self.compressor.compress(header) + self.compressor.compress(first))
        with log.open("ab") as stream:
            stream.write(self.compressor.compress(second))
        (source / "credentials.json").write_bytes(self.row(self.repo))
        (source / "other.jsonl.zstd").write_bytes(self.compressor.compress(self.row(self.repo)))
        self.assertEqual(scan_deepseek(source, self.repo).sessions,
                         [(source / "session.jsonl.zstd.decompressed.jsonl", header + first + second)])

    def test_harness_other_project_poison_and_limits(self) -> None:
        home = self.base / "dsh-home"
        session = home / "sessions" / "--collision--" / "id"
        session.mkdir(parents=True)
        log = session / "session.jsonl.zstd"
        log.write_bytes(self.compressor.compress(self.row(self.other)) +
                        self.compressor.compress(str(self.repo).encode() + b"\n"))
        self.assertEqual(scan_deepseek(home, self.repo).sessions, [])
        self.assertEqual(scan_deepseek(home, self.repo).skipped_unverified, 1)

        log.write_bytes(self.compressor.compress(self.row(self.repo)) +
                        self.compressor.compress(b"x" * 2048))
        with patch("agent_session_commit.adapters.pi_deepseek.MAX_SESSION_BYTES", 512):
            self.assertEqual(scan_deepseek(home, self.repo).sessions, [])
        log.write_bytes(b"not a zstandard frame")
        self.assertEqual(scan_deepseek(home, self.repo).sessions, [])

    def test_harness_raw_and_unknown_names(self) -> None:
        source = self.base / "custom-root"
        session = source / "--project--" / "id"
        session.mkdir(parents=True)
        good = session / "session.v3.jsonl"
        payload = self.row(self.repo, version=3) + b'{"event":"ok"}\n'
        good.write_bytes(payload)
        for name in ("session.v0.jsonl", "session.v03.jsonl", "Session.v4.jsonl",
                     "session.v4.jsonl.zst", "session.v4.jsonl.tmp", "credentials.json"):
            (session / name).write_bytes(self.row(self.repo))
        self.assertEqual(scan_deepseek(source, self.repo).sessions, [(good, payload)])


if __name__ == "__main__":
    unittest.main()
