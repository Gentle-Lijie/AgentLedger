#!/usr/bin/env python3
"""Check release tags and built distributions without importing the package.

Relative distribution paths are resolved against this repository, not the cwd.
No archives are extracted. Only the Python standard library is required.
"""

from __future__ import annotations

import argparse
import ast
import configparser
import re
import sys
import tarfile
import zipfile
from email.parser import BytesParser
from pathlib import Path, PurePosixPath
from typing import Mapping


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_NAME = "agent-session-commit"
PACKAGE_PATH = "agent_session_commit"


class ReleaseError(ValueError):
    """A release does not meet the publication contract."""


def read_version(repository_root: Path = REPOSITORY_ROOT) -> str:
    source = repository_root / "src" / PACKAGE_PATH / "__init__.py"
    try:
        tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    except (OSError, SyntaxError, UnicodeError) as exc:
        raise ReleaseError(f"Cannot read version source {source}: {exc}") from exc
    values = []
    for statement in tree.body:
        if isinstance(statement, ast.Assign):
            targets = statement.targets
            value = statement.value
        elif isinstance(statement, ast.AnnAssign):
            targets = [statement.target]
            value = statement.value
        else:
            continue
        if any(isinstance(target, ast.Name) and target.id == "__version__" for target in targets):
            values.append(value)
    if len(values) != 1 or not isinstance(values[0], ast.Constant) or not isinstance(values[0].value, str):
        raise ReleaseError("__version__ must be assigned exactly once as a string literal")
    version = values[0].value
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:(?:a|b|rc)[0-9]+)?(?:\.post[0-9]+)?(?:\.dev[0-9]+)?", version):
        raise ReleaseError(f"Unsupported release version: {version!r}")
    return version


def normalized_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def check_member_path(name: str) -> str:
    """Validate all entries, including directories and otherwise unused files."""
    path = PurePosixPath(name)
    if not path.parts or "\x00" in name or "\\" in name or path.is_absolute() or ".." in path.parts or re.match(r"^[A-Za-z]:", name):
        raise ReleaseError(f"Unsafe archive path: {name!r}")
    for part in path.parts:
        lower = part.lower()
        if lower in {".agent-sessions", ".git", ".venv", "venv", ".env", ".aws", ".ssh", ".azure", ".gnupg"}:
            raise ReleaseError(f"Forbidden release artifact: {name}")
        if lower.startswith(".env.") or lower in {".pypirc", ".netrc", "auth.json", "id_rsa", "id_ed25519", "id_dsa", "id_ecdsa"}:
            raise ReleaseError(f"Credential/environment artifact: {name}")
        if re.search(r"(?:^|[-_.])(?:tokens?|credentials?|secrets?|api[-_]?keys?)(?:$|[-_.])", lower):
            raise ReleaseError(f"Token/credential artifact: {name}")
        if lower.endswith((".pem", ".key", ".p12", ".pfx")):
            raise ReleaseError(f"Private key artifact: {name}")
    return str(path)


def check_metadata(data: bytes, version: str, label: str, *, wheel: bool = False) -> None:
    metadata = BytesParser().parsebytes(data)
    for field in ("Name", "Version"):
        if len(metadata.get_all(field, [])) != 1:
            raise ReleaseError(f"{label}: expected exactly one {field} field")
    if normalized_name(metadata["Name"]) != PACKAGE_NAME:
        raise ReleaseError(f"{label}: unexpected Name {metadata['Name']!r}")
    if metadata["Version"] != version:
        raise ReleaseError(f"{label}: Version {metadata['Version']!r} does not match {version!r}")
    if wheel:
        if metadata.get_all("License-Expression", []) != ["MIT"]:
            raise ReleaseError(f"{label}: License-Expression must be MIT")
        if "LICENSE" not in metadata.get_all("License-File", []):
            raise ReleaseError(f"{label}: missing License-File: LICENSE metadata")
        if not re.fullmatch(r"2\.(?:[4-9]|[1-9][0-9]+)", metadata.get("Metadata-Version", "")):
            raise ReleaseError(f"{label}: license-files requires Metadata-Version >= 2.4")


def require_files(files: Mapping[str, bytes], required: tuple[str, ...], label: str) -> None:
    for name in required:
        if name not in files or not files[name]:
            raise ReleaseError(f"{label}: missing or empty {name}")


def check_mit_license(data: bytes, label: str) -> None:
    text = " ".join(data.decode("utf-8").lower().split())
    for clause in (
        "permission is hereby granted, free of charge",
        "the above copyright notice and this permission notice",
        'the software is provided "as is"',
    ):
        if clause not in text:
            raise ReleaseError(f"{label}: LICENSE does not contain the MIT license terms")


def check_wheel(path: Path, version: str) -> None:
    files: dict[str, bytes] = {}
    seen = set()
    with zipfile.ZipFile(path) as archive:
        for member in archive.infolist():
            # ZipInfo normalizes OS separators on Windows and truncates NULs.
            # Validate the original archive spelling before that normalization.
            name = check_member_path(member.orig_filename)
            if name in seen:
                raise ReleaseError(f"{path.name}: duplicate archive entry {name}")
            seen.add(name)
            mode = (member.external_attr >> 16) & 0o170000
            if mode == 0o120000:
                raise ReleaseError(f"{path.name}: symbolic link {name}")
            if not member.is_dir():
                files[name] = archive.read(member)
    dist_infos = {PurePosixPath(name).parts[0] for name in files if PurePosixPath(name).parts[0].endswith(".dist-info")}
    if len(dist_infos) != 1:
        raise ReleaseError(f"{path.name}: expected one .dist-info directory")
    info = dist_infos.pop()
    require_files(files, (
        f"{PACKAGE_PATH}/__init__.py", f"{PACKAGE_PATH}/cli.py",
        f"{info}/METADATA", f"{info}/entry_points.txt", f"{info}/licenses/LICENSE",
    ), path.name)
    check_metadata(files[f"{info}/METADATA"], version, path.name, wheel=True)
    check_mit_license(files[f"{info}/licenses/LICENSE"], path.name)
    parser = configparser.ConfigParser(interpolation=None, strict=True)
    parser.optionxform = str
    parser.read_string(files[f"{info}/entry_points.txt"].decode("utf-8"))
    if parser.get("console_scripts", "agent-session-commit", fallback="").strip() != "agent_session_commit.cli:main":
        raise ReleaseError(f"{path.name}: missing or incorrect agent-session-commit console script")


def check_sdist(path: Path, version: str) -> None:
    files: dict[str, bytes] = {}
    roots = set()
    seen = set()
    with tarfile.open(path, "r:gz") as archive:
        for member in archive:
            name = check_member_path(member.name)
            if name in seen:
                raise ReleaseError(f"{path.name}: duplicate archive entry {name}")
            seen.add(name)
            roots.add(PurePosixPath(name).parts[0])
            if not (member.isfile() or member.isdir()):
                raise ReleaseError(f"{path.name}: unsupported archive entry {name}")
            if member.isfile():
                stream = archive.extractfile(member)
                if stream is None:
                    raise ReleaseError(f"{path.name}: unreadable archive entry {name}")
                with stream:
                    files[name] = stream.read()
    if len(roots) != 1:
        raise ReleaseError(f"{path.name}: expected one source distribution root")
    root = roots.pop()
    require_files(files, (
        f"{root}/LICENSE", f"{root}/README.md", f"{root}/PKG-INFO",
        f"{root}/src/{PACKAGE_PATH}/__init__.py", f"{root}/src/{PACKAGE_PATH}/cli.py",
    ), path.name)
    check_metadata(files[f"{root}/PKG-INFO"], version, path.name)
    check_mit_license(files[f"{root}/LICENSE"], path.name)


def check_release(tag: str | None = None, dist_dir: Path | None = None,
                  repository_root: Path = REPOSITORY_ROOT) -> str:
    version = read_version(repository_root)
    if tag is not None and tag != f"v{version}":
        raise ReleaseError(f"Release tag {tag!r} must equal v{version}")
    if dist_dir is not None:
        if not dist_dir.is_absolute():
            dist_dir = repository_root / dist_dir
        if not dist_dir.is_dir():
            raise ReleaseError(f"Distribution directory does not exist: {dist_dir}")
        wheels = sorted(dist_dir.glob("*.whl"))
        sdists = sorted(dist_dir.glob("*.tar.gz"))
        if len(wheels) != 1 or len(sdists) != 1:
            raise ReleaseError(f"Expected exactly one .whl and one .tar.gz in {dist_dir}; found {len(wheels)} and {len(sdists)}")
        check_wheel(wheels[0], version)
        check_sdist(sdists[0], version)
    return version


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", help="Exact Git release tag, such as v0.1.0")
    parser.add_argument("--dist-dir", type=Path, help="Check built artifacts (relative paths use the repository root)")
    args = parser.parse_args(argv)
    try:
        version = check_release(args.tag, args.dist_dir)
    except (ReleaseError, OSError, ValueError, UnicodeError, tarfile.TarError,
            zipfile.BadZipFile, configparser.Error, RuntimeError, EOFError) as exc:
        print(f"Release check failed: {exc}", file=sys.stderr)
        return 1
    print(f"Release check passed: {PACKAGE_NAME} {version}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
