"""Synthetic database tests; never inspect an installed agent's private store."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from agent_session_commit.adapters import sqlite_agents


class SQLiteAgentAdaptersTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        base = Path(temporary.name)
        self.root = base / "repo"
        self.root.mkdir()
        self.other = base / "other"
        self.other.mkdir()
        self.db_path = base / "state.db"

    def records(self, result):
        self.assertEqual(len(result.sessions), 1)
        path, payload = result.sessions[0]
        self.assertEqual(path, self.db_path.with_name("state.db.project-sessions.jsonl"))
        return [json.loads(line) for line in payload.splitlines()]

    def make_hermes(self) -> None:
        with closing(sqlite3.connect(self.db_path)) as db, db:
            db.executescript("""
                CREATE TABLE sessions (
                    id TEXT PRIMARY KEY, cwd TEXT, git_repo_root TEXT,
                    title TEXT, model_config TEXT, system_prompt TEXT
                );
                CREATE TABLE messages (
                    id INTEGER PRIMARY KEY, session_id TEXT, role TEXT,
                    content TEXT, tool_calls TEXT
                );
                CREATE TABLE secrets (id TEXT, content TEXT);
            """)
            db.executemany(
                "INSERT INTO sessions VALUES (?, ?, ?, ?, ?, ?)", [
                    ("own", str(self.root), str(self.root), "own title", "SECRET_CONFIG", "SECRET_PROMPT"),
                    ("other", str(self.other), str(self.other), "other title", None, None),
                    ("conflict", str(self.root), str(self.other), "conflict", None, None),
                    ("prefix", str(self.root) + "-extra", None, "prefix", None, None),
                ],
            )
            db.executemany("INSERT INTO messages VALUES (?, ?, ?, ?, ?)", [
                (1, "own", "user", "own message", "SECRET_TOOL_CALLS"),
                (2, "other", "user", f"mentions {self.root} but belongs elsewhere", None),
                (3, "conflict", "user", "conflicting root", None),
                (4, "prefix", "user", "path prefix", None),
                (5, "orphan", "user", f"orphan mentions {self.root}", None),
            ])
            db.execute("INSERT INTO secrets VALUES ('token', ?)", (str(self.root),))

    def make_zcode(self) -> None:
        with closing(sqlite3.connect(self.db_path)) as db, db:
            db.executescript("""
                CREATE TABLE session (
                    id TEXT PRIMARY KEY, directory TEXT, title TEXT, api_key TEXT
                );
                CREATE TABLE message (
                    id TEXT PRIMARY KEY, session_id TEXT, data TEXT
                );
                CREATE TABLE part (
                    id TEXT PRIMARY KEY, message_id TEXT, session_id TEXT, data TEXT
                );
                CREATE TABLE secrets (path TEXT, value TEXT);
            """)
            db.executemany("INSERT INTO session VALUES (?, ?, ?, ?)", [
                ("own", str(self.root), "own title", "SECRET_API_KEY"),
                ("other", str(self.other), "other title", "OTHER_KEY"),
                ("prefix", str(self.root) + "-extra", "prefix title", None),
                ("nested", str(self.root / "subdir"), "nested title", None),
            ])
            db.executemany("INSERT INTO message VALUES (?, ?, ?)", [
                ("m1", "own", json.dumps({"role": "user", "apiKey": "SECRET_MESSAGE_META"})),
                ("m2", "other", json.dumps({"role": "user"})),
            ])
            db.executemany("INSERT INTO part VALUES (?, ?, ?, ?)", [
                ("p1", "m1", "own", json.dumps({"type": "text", "text": "own text"})),
                ("p2", "m2", "other", json.dumps({"type": "text", "text": f"mentions {self.root}"})),
                ("p3", "m1", "other", json.dumps({"type": "text", "text": "wrong session part"})),
                ("p4", "m1", "own", json.dumps({"type": "tool", "text": "SECRET_TOOL"})),
            ])
            db.execute("INSERT INTO secrets VALUES (?, ?)", (str(self.root), "SECRET_TABLE"))

    def test_hermes_exports_only_owned_session_and_related_messages(self) -> None:
        self.make_hermes()
        result = sqlite_agents.scan_hermes(self.db_path, self.root)
        records = self.records(result)
        self.assertEqual([item["table"] for item in records], ["sessions", "messages"])
        self.assertEqual(records[0]["record"]["id"], "own")
        self.assertEqual(records[1]["record"]["content"], "own message")
        payload = result.sessions[0][1]
        for excluded in (b"SECRET_CONFIG", b"SECRET_PROMPT", b"SECRET_TOOL_CALLS",
                         b"mentions", b"conflicting", b"SECRET_TABLE"):
            self.assertNotIn(excluded, payload)

    def test_zcode_joins_both_part_keys_and_exports_text_only(self) -> None:
        self.make_zcode()
        result = sqlite_agents.scan_zcode(self.db_path, self.root)
        records = self.records(result)
        self.assertEqual([item["table"] for item in records], ["session", "message"])
        self.assertEqual(records[0]["record"]["id"], "own")
        self.assertEqual(records[1]["record"]["text"], "own text")
        payload = result.sessions[0][1]
        for excluded in (b"SECRET_API_KEY", b"SECRET_MESSAGE_META", b"SECRET_TOOL",
                         b"wrong session part", b"mentions", b"SECRET_TABLE"):
            self.assertNotIn(excluded, payload)

    def test_unknown_schema_fails_closed(self) -> None:
        with closing(sqlite3.connect(self.db_path)) as db, db:
            db.execute("CREATE TABLE arbitrary (prompt TEXT)")
            db.execute("INSERT INTO arbitrary VALUES (?)", (f"mentions {self.root}",))
        for scanner in (sqlite_agents.scan_zcode, sqlite_agents.scan_hermes):
            with self.subTest(scanner=scanner.__name__):
                result = scanner(self.db_path, self.root)
                self.assertEqual(result.sessions, [])
                self.assertGreater(result.skipped_unverified, 0)

    def test_read_only_source_and_missing_source(self) -> None:
        self.make_hermes()
        before = hashlib.sha256(self.db_path.read_bytes()).digest()
        self.db_path.chmod(0o444)
        connect = sqlite3.connect
        opened = []

        def checked_connect(database, **kwargs):
            opened.append((database, kwargs))
            return connect(database, **kwargs)

        with patch.object(sqlite_agents.sqlite3, "connect", side_effect=checked_connect):
            result = sqlite_agents.scan_hermes(self.db_path, self.root)
        self.records(result)
        self.assertEqual(len(opened), 1)
        self.assertTrue(opened[0][0].endswith("?mode=ro"))
        self.assertIs(opened[0][1]["uri"], True)
        self.assertEqual(hashlib.sha256(self.db_path.read_bytes()).digest(), before)
        self.assertEqual(sorted(path.name for path in self.db_path.parent.iterdir()),
                         ["other", "repo", "state.db"])
        missing = self.db_path.parent / "missing.db"
        self.assertEqual(sqlite_agents.scan_hermes(missing, self.root).sessions, [])
        self.assertFalse(missing.exists())

    def test_over_limit_session_is_skipped_without_partial_export(self) -> None:
        self.make_hermes()
        with patch.object(sqlite_agents, "MAX_MESSAGES_PER_SESSION", 0):
            result = sqlite_agents.scan_hermes(self.db_path, self.root)
        self.assertEqual(result.sessions, [])
        self.assertGreater(result.skipped_unverified, 0)


if __name__ == "__main__":
    unittest.main()
