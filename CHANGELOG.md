# AgentLedger changelog

Changes are recorded before publication. Versions come from `__version__` in `src/agentledger/__init__.py`; release tags use the exact form `v<version>`.

## 0.1.0 — Unreleased

### Added

- Python CLI to install, inspect, and uninstall repository-local session archive hooks.
- Agent choices for ZCode, Qoder, Trae, Tencent CodeBuddy, Claude Code, OpenAI Codex CLI, GitHub Copilot CLI, Hermes Agent, Pi Coding Agent, DeepSeek Harness, and custom exports.
- Incremental bundles with checksums, offsets, and full-versus-append modes.
- Read-only SQLite exports for ZCode and Hermes, and Zstandard log support for DeepSeek Harness.
- Hook backups/restoration, local fingerprints, and synthetic tests in disposable repositories.
- Contributor, security, and release documentation.

### Changed

- Canonical branding is AgentLedger: PyPI package and CLI `agentledger`, Python module `agentledger`.
- Legacy `agent-session-commit` CLI and `agent_session_commit.cli` remain compatibility shims. Internal Git configuration, state, and environment names are retained.
- Bundles are added through `git commit --amend --no-edit`, replacing separate archive commits from earlier development.
- Internal amend operations suppress hooks; existing post-commit hooks run once against final HEAD.
- A temporary index excludes unrelated staged changes while retaining commit message, author, and parents.

### Fixed

- Read all appended Zstandard frames in DeepSeek Harness logs, skip malformed compressed files, and bound decompressed content size.
- Validate original ZIP entry names so Windows path normalization cannot hide unsafe release archive paths.

### Known limitations

- Trae IDE and CodeBuddy IDE require exported transcripts.
- SQLite schemas and repository-path matching are best-effort; complete conversation export is not guaranteed.
- Referenced binary attachments are not automatically collected. Archives are not redacted or encrypted.
- Amend changes the SHA; local fingerprint state is not synchronized between clones.

### Release preparation

- The CI contract tests installed wheels on macOS, Linux, and Windows with Python 3.10 and 3.14.
- Tag publication builds and validates wheel/sdist artifacts, passes the same matrix, publishes to PyPI, then creates a GitHub Release with distribution assets.
- See [docs/releasing.md](docs/releasing.md) for prerequisites. This unreleased entry does not assert that remote CI or publication has completed.
