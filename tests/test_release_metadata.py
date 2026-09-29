"""Publication gates tested with synthetic wheel and sdist archives (stdlib only)."""

from __future__ import annotations

import importlib.util
import io
import subprocess
import sys
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_release.py"
SPEC = importlib.util.spec_from_file_location("release_guard", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
guard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(guard)

MIT = b'''MIT License

Copyright (c) 2026 Agent Session Commit contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
'''

INFO = "agent_session_commit-0.1.0.dist-info"
ROOT = "agent_session_commit-0.1.0"


def metadata(version: str = "0.1.0", name: str = "agent-session-commit") -> bytes:
    return (f"Metadata-Version: 2.4\nName: {name}\nVersion: {version}\n"
            "License-Expression: MIT\nLicense-File: LICENSE\n\nRelease fixture\n").encode()


class ReleaseMetadataTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name)
        source = self.repo / "src" / "agent_session_commit" / "__init__.py"
        source.parent.mkdir(parents=True)
        # Executing this module would fail. Checking release versions must not import it.
        source.write_text('__version__ = "0.1.0"\nraise RuntimeError("do not import")\n', encoding="utf-8")
        self.source = source
        self.dist = self.repo / "dist"
        self.dist.mkdir()
        self.wheel_files = {
            "agent_session_commit/__init__.py": b'__version__ = "0.1.0"\n',
            "agent_session_commit/cli.py": b"def main(): pass\n",
            "agentledger/__init__.py": b"from agent_session_commit import __version__\n",
            "agentledger/cli.py": b"from agent_session_commit.cli import main\n",
            f"{INFO}/METADATA": metadata(),
            f"{INFO}/entry_points.txt": b"[console_scripts]\nagent-session-commit = agent_session_commit.cli:main\nagentledger = agentledger.cli:main\n",
            f"{INFO}/licenses/LICENSE": MIT,
        }
        self.sdist_files = {
            f"{ROOT}/LICENSE": MIT,
            f"{ROOT}/README.md": b"# AgentLedger\n",
            f"{ROOT}/PKG-INFO": metadata(),
            f"{ROOT}/src/agent_session_commit/__init__.py": b'__version__ = "0.1.0"\n',
            f"{ROOT}/src/agent_session_commit/cli.py": b"def main(): pass\n",
            f"{ROOT}/src/agentledger/__init__.py": b"from agent_session_commit import __version__\n",
            f"{ROOT}/src/agentledger/cli.py": b"from agent_session_commit.cli import main\n",
        }

    def build_fixtures(self) -> None:
        with zipfile.ZipFile(self.dist / "agent_session_commit-0.1.0-py3-none-any.whl", "w") as archive:
            for name, data in self.wheel_files.items():
                # Keep deliberately unsafe archive names unchanged on Windows.
                entry = zipfile.ZipInfo()
                entry.filename = name
                archive.writestr(entry, data)
        with tarfile.open(self.dist / "agent_session_commit-0.1.0.tar.gz", "w:gz") as archive:
            for name, data in self.sdist_files.items():
                entry = tarfile.TarInfo(name)
                entry.size = len(data)
                archive.addfile(entry, io.BytesIO(data))

    def check(self, **kwargs: object) -> str:
        return guard.check_release(repository_root=self.repo, **kwargs)

    def test_version_check_does_not_import_package_or_require_dist(self) -> None:
        self.assertEqual(self.check(tag="v0.1.0"), "0.1.0")
        self.assertEqual(self.check(), "0.1.0")

    def test_tag_must_match_exactly(self) -> None:
        for tag in ("0.1.0", "v0.1", "v0.1.1", "v0.1.0-extra", "refs/tags/v0.1.0", "v0.1.0\n", "", "V0.1.0"):
            with self.subTest(tag=tag), self.assertRaisesRegex(guard.ReleaseError, "must equal v0.1.0"):
                self.check(tag=tag)

    def test_version_source_must_be_one_literal(self) -> None:
        for content in ('__version__ = str("0.1.0")', '__version__ = 1',
                        '__version__ = "0.1.0"\n__version__ = "0.2.0"',
                        '# no version', '__version__ = ""'):
            with self.subTest(content=content):
                self.source.write_text(content, encoding="utf-8")
                with self.assertRaises(guard.ReleaseError):
                    self.check()

    def test_valid_artifacts_and_normalized_distribution_name(self) -> None:
        self.wheel_files[f"{INFO}/METADATA"] = metadata(name="Agent_Session.Commit")
        self.sdist_files[f"{ROOT}/PKG-INFO"] = metadata(name="AGENT-SESSION-COMMIT")
        self.build_fixtures()
        self.assertEqual(self.check(tag="v0.1.0", dist_dir=Path("dist")), "0.1.0")

    def test_legacy_aliases_are_allowed_but_not_required(self) -> None:
        self.build_fixtures()
        self.assertEqual(self.check(dist_dir=self.dist), "0.1.0")
        for name in ("agentledger/__init__.py", "agentledger/cli.py"):
            del self.wheel_files[name]
            del self.sdist_files[f"{ROOT}/src/{name}"]
        self.wheel_files[f"{INFO}/entry_points.txt"] = (
            b"[console_scripts]\nagent-session-commit = agent_session_commit.cli:main\n"
        )
        self.build_fixtures()
        self.assertEqual(self.check(dist_dir=self.dist), "0.1.0")

    def test_each_artifact_must_match_source_version_and_name(self) -> None:
        for artifact, key in ((self.wheel_files, f"{INFO}/METADATA"),
                              (self.sdist_files, f"{ROOT}/PKG-INFO")):
            for invalid in (metadata(version="0.1.1"), metadata(name="another-package"),
                            metadata(name="agentledger"),
                            metadata().replace(b"Version: 0.1.0", b"Version: 0.1.0\nVersion: 0.1.1")):
                with self.subTest(artifact=key, metadata=invalid):
                    artifact[key] = invalid
                    self.build_fixtures()
                    with self.assertRaises(guard.ReleaseError):
                        self.check(dist_dir=self.dist)
                    artifact[key] = metadata()

    def test_exactly_one_wheel_and_one_sdist_required(self) -> None:
        with self.assertRaisesRegex(guard.ReleaseError, "exactly one"):
            self.check(dist_dir=self.dist)
        self.build_fixtures()
        extra = self.dist / "extra.whl"
        extra.write_bytes(b"not a wheel")
        with self.assertRaisesRegex(guard.ReleaseError, "exactly one"):
            self.check(dist_dir=self.dist)
        extra.unlink()
        (self.dist / "extra.tar.gz").write_bytes(b"not a tar")
        with self.assertRaisesRegex(guard.ReleaseError, "exactly one"):
            self.check(dist_dir=self.dist)

    def test_required_package_docs_license_and_entry_point(self) -> None:
        required_wheel = ("agent_session_commit/__init__.py", "agent_session_commit/cli.py",
                          f"{INFO}/METADATA", f"{INFO}/licenses/LICENSE", f"{INFO}/entry_points.txt")
        required_source = tuple(key for key in self.sdist_files if "/agentledger/" not in key)
        for artifact, required in ((self.wheel_files, required_wheel), (self.sdist_files, required_source)):
            for key in required:
                with self.subTest(missing=key):
                    data = artifact.pop(key)
                    self.build_fixtures()
                    with self.assertRaises(guard.ReleaseError):
                        self.check(dist_dir=self.dist)
                    artifact[key] = data

    def test_entry_point_and_pep639_license_contract(self) -> None:
        modifications = (
            (f"{INFO}/entry_points.txt", b"[console_scripts]\nagent-session-commit = wrong.cli:main\n"),
            (f"{INFO}/entry_points.txt", b"[console_scripts]\nagentledger = agentledger.cli:main\n"),
            (f"{INFO}/entry_points.txt", b"[console_scripts]\nagent-session-commit = agentledger.cli:main\n"),
            (f"{INFO}/METADATA", metadata().replace(b"License-Expression: MIT", b"License-Expression: Apache-2.0")),
            (f"{INFO}/METADATA", metadata().replace(b"License-File: LICENSE\n", b"")),
            (f"{INFO}/METADATA", metadata().replace(b"Metadata-Version: 2.4", b"Metadata-Version: 2.1")),
            (f"{INFO}/licenses/LICENSE", b"Proprietary license"),
        )
        for key, invalid in modifications:
            with self.subTest(file=key, invalid=invalid):
                original = self.wheel_files[key]
                self.wheel_files[key] = invalid
                self.build_fixtures()
                with self.assertRaises(guard.ReleaseError):
                    self.check(dist_dir=self.dist)
                self.wheel_files[key] = original

    def test_private_and_session_artifacts_rejected_in_both_archives(self) -> None:
        forbidden = (".agent-sessions/bundles/session.tar.gz", ".git/config", ".venv/pyvenv.cfg",
                     ".env", ".env.production", "auth.json", "credentials.json", "pypi-token.txt",
                     ".pypirc", ".netrc", ".ssh/id_ed25519", "private.pem", "api_key.txt")
        for artifact, prefix in ((self.wheel_files, ""), (self.sdist_files, f"{ROOT}/")):
            for path in forbidden:
                key = prefix + path
                with self.subTest(archive=prefix or "wheel", file=path):
                    artifact[key] = b"sensitive fixture"
                    self.build_fixtures()
                    with self.assertRaises(guard.ReleaseError):
                        self.check(dist_dir=self.dist)
                    del artifact[key]

    def test_unsafe_paths_rejected_without_extraction(self) -> None:
        for artifact in (self.wheel_files, self.sdist_files):
            for path in ("../escaped.txt", "/absolute.txt", "C:/Windows/token.txt", "bad\\file.txt", "bad\x00file.txt"):
                with self.subTest(path=path):
                    artifact[path] = b"fixture"
                    self.build_fixtures()
                    with self.assertRaises(guard.ReleaseError):
                        self.check(dist_dir=self.dist)
                    del artifact[path]
        self.assertFalse((self.repo / "escaped.txt").exists())

    def test_archive_links_cannot_hide_forbidden_data(self) -> None:
        self.build_fixtures()
        wheel = self.dist / "agent_session_commit-0.1.0-py3-none-any.whl"
        with zipfile.ZipFile(wheel, "a") as archive:
            link = zipfile.ZipInfo("agent_session_commit/history")
            link.create_system = 3
            link.external_attr = 0o120777 << 16
            archive.writestr(link, b"../../.agent-sessions")
        with self.assertRaisesRegex(guard.ReleaseError, "symbolic link"):
            self.check(dist_dir=self.dist)
        self.build_fixtures()
        # Write a valid source fixture with an additional disguised history link.
        with tarfile.open(self.dist / "agent_session_commit-0.1.0.tar.gz", "w:gz") as archive:
            for name, data in self.sdist_files.items():
                entry = tarfile.TarInfo(name)
                entry.size = len(data)
                archive.addfile(entry, io.BytesIO(data))
            link = tarfile.TarInfo(f"{ROOT}/history")
            link.type = tarfile.SYMTYPE
            link.linkname = "../../.agent-sessions"
            archive.addfile(link)
        with self.assertRaisesRegex(guard.ReleaseError, "unsupported archive entry"):
            self.check(dist_dir=self.dist)

    def test_command_from_another_cwd_and_failure_exit_status(self) -> None:
        version = guard.read_version()
        result = subprocess.run([sys.executable, str(SCRIPT), "--tag", f"v{version}"],
                                cwd=self.repo, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(version, result.stdout)
        # Artifacts use the source version even if a future release bumps it.
        self.wheel_files[f"{INFO}/METADATA"] = metadata(version=version)
        self.sdist_files[f"{ROOT}/PKG-INFO"] = metadata(version=version)
        self.build_fixtures()
        result = subprocess.run([sys.executable, str(SCRIPT), "--tag", f"v{version}", "--dist-dir", str(self.dist)],
                                cwd=self.repo, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        for extra in (("--tag", "vmalformed"), ("--dist-dir", str(self.repo / "missing"))):
            result = subprocess.run([sys.executable, str(SCRIPT), *extra], cwd=self.repo,
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 1)
            self.assertIn("Release check failed:", result.stderr)
            self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
