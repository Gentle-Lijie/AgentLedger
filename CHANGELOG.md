# Agent Session Commit changelog

Changes are recorded before publication. Versions come from `__version__` in `src/agent_session_commit/__init__.py`; release tags use the exact form `v<version>`.

## 0.1.2 — 2026-09-29

### Added

- TUI installation with arrow-key agent selection and a path-completion prompt. Reuse the saved source when selecting the same agent, otherwise suggest its default; create missing Custom/Trae export directories. Cancellation leaves Git configuration unchanged.
- `agent-session-commit install --pre-commit` helper to save repository-local agent/source settings and invoke the pre-commit framework installer without creating native wrappers.
- Install-only `--agent` and `--source` flags for noninteractive setup. No TUI runs in Git hooks or CI when both flags are supplied.
- Optional `[pre-commit]` extra for the framework controller; base `questionary` and `PyYAML` dependencies for the wizard and configuration validation.
- Generate a missing `.pre-commit-config.yaml` pinned to the `v0.1.2` backend, with pre/post hook types. Preserve existing YAML comments and other hooks; require the canonical or legacy hook entry and give merge instructions if it is missing.
- Install all configured default hook types and ensure `post-commit`. Preflight checks explain native-hook migration, a missing controller, and incompatible `core.hooksPath` configuration.
- Restore previous local Git settings and hook files and remove newly generated YAML if framework setup fails.

### Documentation

- Recommend installing `agent-session-commit[pre-commit]==0.1.2` from PyPI in a persistent virtual environment, then running `agent-session-commit install --pre-commit` for TUI setup. Keep manual pre-commit setup supported and source installation optional for development.
- Clarify that upstream `pre-commit install` has no plugin setup callback; use the explicit helper for the wizard. Native installation without `--pre-commit` remains supported.

## 0.1.1 — 2026-09-29

### Changed

- Restore Agent Session Commit branding, PyPI distribution and CLI `agent-session-commit`, and canonical Python module `agent_session_commit`.
- Use `src/agent_session_commit/__init__.py` as the single version source. Retain the `agentledger` CLI and module as compatibility shims.
- Use pre-commit hook ID `agent-session-commit` with entry `agent-session-commit hook post-commit`; retain the old `agentledger` hook alias.
- Update installation and pre-commit examples to version `0.1.1` and tag `v0.1.1`. The GitHub repository remains `Gentle-Lijie/AgentLedger`.

### Publication history

- The `v0.1.0` upload attempt under `agentledger` failed because PyPI rejected the project name as too similar to an existing project. No distribution files were uploaded. The public `v0.1.0` tag remains unchanged; `0.1.1` is the name restoration release.

## 0.1.0 — 2026-09-29 (failed PyPI publication)

### Added

- Python CLI to install, inspect, and uninstall repository-local session archive hooks.
- Agent choices for ZCode, Qoder, Trae, Tencent CodeBuddy, Claude Code, OpenAI Codex CLI, GitHub Copilot CLI, Hermes Agent, Pi Coding Agent, DeepSeek Harness, and custom exports.
- Incremental bundles with checksums, offsets, and full-versus-append modes.
- Read-only SQLite exports for ZCode and Hermes, and Zstandard log support for DeepSeek Harness.
- Hook backups/restoration, local fingerprints, and synthetic tests in disposable repositories.
- Contributor, security, and release documentation.
- pre-commit framework integration in the `v0.1.0` tagged build: the `agentledger` post-commit hook, example configuration, and setup/migration guide in [docs/precommit.md](docs/precommit.md). The framework installs the tool in an isolated Python environment; repository-local Git settings select the agent and session source.

### Changed

- The tagged build used AgentLedger branding: PyPI package and CLI `agentledger`, Python module `agentledger`.
- That build retained the `agent-session-commit` CLI and `agent_session_commit.cli` as compatibility shims. Internal Git configuration, state, and environment names were retained.
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
- See [docs/releasing.md](docs/releasing.md) for prerequisites.
