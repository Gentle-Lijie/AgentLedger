from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent_session_commit.adapters.common import (
    belongs_to_repo, read_jsonl_header, read_session_bytes,
)


class AdapterCommonTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.repo = self.base / "project"
        self.repo.mkdir()

    def test_project_ownership_uses_paths_not_string_prefixes(self) -> None:
        self.assertTrue(belongs_to_repo(str(self.repo), self.repo))
        self.assertFalse(belongs_to_repo(str(self.repo / "subdir"), self.repo))
        self.assertFalse(belongs_to_repo(str(self.base / "project-other"), self.repo))
        self.assertFalse(belongs_to_repo("project", self.repo))
        self.assertFalse(belongs_to_repo({"cwd": str(self.repo)}, self.repo))

    def test_header_read_is_bounded_and_body_size_is_checked(self) -> None:
        path = self.base / "session.jsonl"
        path.write_text(
            json.dumps({"cwd": str(self.repo)}) + "\n"
            + json.dumps({"message": "x" * 100_000}) + "\n",
            encoding="utf-8",
        )
        self.assertEqual([entry["cwd"] for entry in read_jsonl_header(path)], [str(self.repo)])
        self.assertIsNone(read_session_bytes(path, byte_limit=1024))

    def test_linked_source_is_not_followed(self) -> None:
        target = self.base / "target.jsonl"
        target.write_text(json.dumps({"cwd": str(self.repo)}) + "\n", encoding="utf-8")
        link = self.base / "link.jsonl"
        try:
            link.symlink_to(target)
        except (OSError, NotImplementedError):
            self.skipTest("Symlinks unavailable")
        self.assertEqual(read_jsonl_header(link), [])
        self.assertIsNone(read_session_bytes(link))


if __name__ == "__main__":
    unittest.main()
