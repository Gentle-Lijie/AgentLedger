"""Regression checks for Harness's appended, checksummed Zstandard frames."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import zstandard

from agent_session_commit.core import _scan, configure


class HarnessSessionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name).resolve() / "repo"
        self.source = Path(self.temp.name).resolve() / "harness-sessions"
        self.repo.mkdir()
        self.source.mkdir()
        subprocess.run(["git", "init", "--quiet", str(self.repo)], check=True)
        configure(self.repo, "deepseek-harness", self.source)
        self.log = self.source / "session.jsonl.zstd"
        self.compressor = zstandard.ZstdCompressor(write_checksum=True, write_content_size=False)

    def test_appended_frames_are_all_captured(self) -> None:
        header = (json.dumps({"cwd": str(self.repo), "type": "session"}) + "\n").encode()
        message = b'{"type":"message","text":"first reply"}\n'
        self.log.write_bytes(self.compressor.compress(header) + self.compressor.compress(message))
        files = _scan(self.repo)
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0][1], header + message)

        appended = b'{"type":"message","text":"next reply"}\n'
        with self.log.open("ab") as stream:
            stream.write(self.compressor.compress(appended))
        self.assertEqual(_scan(self.repo)[0][1], header + message + appended)

    def test_invalid_compressed_record_is_skipped(self) -> None:
        self.log.write_bytes(b"not a Zstandard frame")
        self.assertEqual(_scan(self.repo), [])

    def test_decompressed_limit_is_enforced(self) -> None:
        payload = (json.dumps({"cwd": str(self.repo), "message": "a" * 4000}) + "\n").encode()
        self.log.write_bytes(self.compressor.compress(payload))
        self.assertLess(self.log.stat().st_size, 512)
        with patch("agent_session_commit.adapters.pi_deepseek.MAX_SESSION_BYTES", 512):
            self.assertEqual(_scan(self.repo), [])


if __name__ == "__main__":
    unittest.main()
