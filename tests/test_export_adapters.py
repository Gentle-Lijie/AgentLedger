from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent_session_commit.adapters.common import read_session_bytes
from agent_session_commit.adapters.exports import scan_exports


class ExportAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.repo = self.base / "repo"
        self.repo.mkdir()

    def test_external_source_requires_cwd_not_a_mention(self) -> None:
        source = self.base / "shared exports"
        source.mkdir()
        own = source / "own.jsonl"
        own.write_text(json.dumps({"cwd": str(self.repo), "message": "own"}) + "\n", encoding="utf-8")
        other = source / "other.jsonl"
        other.write_text(json.dumps({"cwd": str(self.base / "another"),
                                     "message": f"mentions {self.repo}"}) + "\n", encoding="utf-8")
        note = source / "note.md"
        note.write_text(f"mentions {self.repo}", encoding="utf-8")
        with patch("agent_session_commit.adapters.exports.read_session_bytes",
                   wraps=read_session_bytes) as body_reader:
            found = scan_exports(source, self.repo)
        self.assertEqual([path for path, _ in found.sessions], [own])
        self.assertEqual([call.args[0] for call in body_reader.call_args_list], [own])
        self.assertEqual(found.skipped_unverified, 2)

    def test_repository_local_exports_require_work_directory_metadata(self) -> None:
        source = self.repo / ".agent-sessions" / "source"
        source.mkdir(parents=True)
        note = source / "chat.md"
        note.write_text("exported conversation without metadata", encoding="utf-8")
        owned = source / "owned.md"
        owned.write_text(f"---\ncwd: '{self.repo}'\n---\nExported conversation\n", encoding="utf-8")
        nested = source / "nested.jsonl"
        nested.write_text(json.dumps({"cwd": str(self.repo / "subdir")}) + "\n", encoding="utf-8")
        found = scan_exports(source, self.repo)
        self.assertEqual(found.sessions, [(owned, owned.read_bytes())])
        self.assertEqual(found.skipped_unverified, 2)

    def test_linked_export_source_is_not_trusted(self) -> None:
        real = self.base / "outside"
        real.mkdir()
        (real / "private.md").write_text("private", encoding="utf-8")
        link = self.repo / ".agent-sessions" / "source"
        link.parent.mkdir()
        try:
            link.symlink_to(real, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("Symlinks unavailable")
        self.assertEqual(scan_exports(link, self.repo).sessions, [])


if __name__ == "__main__":
    unittest.main()
