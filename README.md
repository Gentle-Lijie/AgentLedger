# Agent Session Commit

Incrementally archive AI coding-agent sessions in the same Git commit as your code. Agent Session Commit targets macOS, Linux, and Windows with Python 3.10 or newer.

After a successful commit, the hook adds a session bundle using `git commit --amend --no-edit`. There are no extra agent chore commits. Unchanged sessions produce no bundle and no amend.

Author: Lijie Zhou · GitHub: [Gentle-Lijie/AgentLedger](https://github.com/Gentle-Lijie/AgentLedger) · Release version: 0.1.1.

Version 0.1.1 restores the `agent-session-commit` distribution and command. The `v0.1.0` upload attempt under `agentledger` failed because PyPI rejected the project name; no distribution files were uploaded. That tag remains unchanged.

## Install from source

Before the first PyPI release, install from a checkout:

~~~sh
git clone https://github.com/Gentle-Lijie/AgentLedger.git
cd AgentLedger
python -m venv .venv
# macOS / Linux:
source .venv/bin/activate
# Windows PowerShell instead:
# .\.venv\Scripts\Activate.ps1
python -m pip install .
~~~

Use `python -m pip install -e .` for development. Keep the installed Python environment available: generated hooks record its executable path. Moving or deleting that environment requires reinstalling the hooks with a working Python installation.

**After the first release is available on PyPI**, you can also install with:

~~~sh
python -m pip install agent-session-commit==0.1.1
~~~

On Windows, install Git for Windows and Python. Run the CLI in PowerShell or Git Bash; Git executes its shell hooks using Git for Windows.

## Enable a repository

Inside the repository you want to archive:

~~~sh
agent-session-commit install
agent-session-commit status
~~~

Choose one agent and its local session directory or supported SQLite file. The selection is repository-local Git configuration; run `install` separately in each repository. Rerun it to change the source or refresh hooks after an upgrade.

Existing executable pre-commit and post-commit hooks are backed up and called by the wrappers. An existing pre-commit hook can still reject a commit. The original post-commit hook runs once after archiving and sees the final HEAD. Custom `core.hooksPath` setups and third-party hook managers may need manual integration; check which hooks Git actually executes.

To disable archiving and restore backed-up hooks:

~~~sh
agent-session-commit uninstall
~~~

Previously committed archives and local archive state remain in place.

### Use the pre-commit framework

Agent Session Commit 0.1.1 also supports the [pre-commit framework](https://pre-commit.com/). Install `pre-commit` version 3.2.0 or newer; it installs Agent Session Commit automatically in an isolated Python environment.

Copy the [example configuration](https://github.com/Gentle-Lijie/AgentLedger/blob/main/examples/.pre-commit-config.yaml) to your target repository's `.pre-commit-config.yaml`, or merge its settings into an existing configuration:

~~~yaml
minimum_pre_commit_version: '3.2.0'
default_install_hook_types: [pre-commit, post-commit]
repos:
  - repo: https://github.com/Gentle-Lijie/AgentLedger
    rev: v0.1.1
    hooks:
      - id: agent-session-commit
~~~

Inside that repository, configure your source and install the framework's hooks:

~~~sh
python -m pip install 'pre-commit>=3.2.0'
git config --local agent-session.agent codex
git config --local agent-session.source "$HOME/.codex/sessions"
pre-commit install
~~~

If you previously ran `agent-session-commit install`, run `agent-session-commit uninstall` **before** setting these Git values and installing pre-commit. Older installations can use `agentledger uninstall` for the same migration. Uninstall removes those values, so configure them again afterward. Let pre-commit own the hooks when using this integration.

The `post-commit` stage is intentional: it archives changed sessions and amends the commit that just succeeded. Unchanged sessions cause no amend. The canonical hook ID is `agent-session-commit`, with entry `agent-session-commit hook post-commit`; the old `agentledger` hook ID remains an alias. This configuration requires the `v0.1.1` tag to be available. See the [integration guide](https://github.com/Gentle-Lijie/AgentLedger/blob/main/docs/precommit.md) for other agents, `CODEX_HOME`, Windows commands, migration, and a portable synthetic example.

### Compatibility with earlier installations

The canonical PyPI distribution and command are `agent-session-commit`; the canonical Python module is `agent_session_commit`. The old `agentledger` command and module remain compatibility shims. The single version source is `src/agent_session_commit/__init__.py`.

Internal names remain unchanged for existing installations: Git configuration uses `agent-session.agent` and `agent-session.source`, private state lives under Git's `agent-session-commit/` directory, and the recursion guard is `AGENT_SESSION_COMMIT_RECURSION`. Bundles still live under `.agent-sessions/`. These names do not require migration when refreshing hooks.

## What gets committed

Bundles live in `.agent-sessions/bundles/*.tar.gz`. Each contains session payloads and a `manifest.json` with offsets, modes, sizes, and checksums. New files are captured in full. Append-only files contribute their new bytes; rewrites or truncations produce replacement snapshots. Reconstruct a transcript by applying its bundles in order: replace on `full`, append at the recorded offset on `append`.

The hook uses a temporary index based on the just-created commit. Other staged and unstaged changes are preserved. The commit retains its message, author including author date, and parents. Internal amend hooks are suppressed to avoid recursion and duplicate integrations. Signed commits require the configured signing key to be available for re-signing.

Amending changes the SHA. Git's original summary can show the earlier SHA; use `git rev-parse HEAD` for the final one. Archive failures leave the original commit intact and session changes eligible for a later attempt. Fingerprints are local, not tracked or synchronized between clones; losing them can cause full content to be archived again.

Archives are ordinary, unencrypted Git content. They can contain prompts, code, tool output, credentials, and local paths; the manifest includes the absolute repository path. There is no automatic secret redaction. Review the selected source before enabling this in a public repository. See [security guidance](https://github.com/Gentle-Lijie/AgentLedger/blob/main/SECURITY.md).

## Agent sources and limitations

`~` below means the current user's home directory on every supported OS. Paths must be accessible from the machine running Git; remote IDE, WSL, or SSH sessions may live elsewhere.

| Agent | Default source | Notes |
| --- | --- | --- |
| ZCode | `~/.zcode/cli/db/db.sqlite` | Read-only SQLite export; schema and project matching are best-effort. `ZCODE_STORAGE_DIR` and `ZCODE_DATA_BASE_DIR` are discovery overrides. |
| Qoder | `~/.qoder/projects/` | Text/JSONL scan; honors `QODER_CONFIG_DIR`. For IDE transcripts, select their actual directory. |
| Trae IDE | Repository's `.agent-sessions/source/` | Export conversations to supported text files first. Encrypted IDE history is not read directly. |
| Tencent CodeBuddy | `~/.codebuddy/projects/` | CLI transcripts; honors `CODEBUDDY_CONFIG_DIR`. CodeBuddy IDE requires exported transcripts and selecting their directory. |
| Claude Code | `~/.claude/projects/` | Text/JSONL scan; honors `CLAUDE_CONFIG_DIR`. |
| OpenAI Codex CLI | `~/.codex/sessions/` | Rollout JSONL scan; honors `CODEX_HOME`. |
| GitHub Copilot CLI | `~/.copilot/session-state/` | Events and text artifacts; honors `COPILOT_HOME`. IDE chat storage and the CLI index database are not directly captured. |
| Hermes Agent | `~/.hermes/state.db` | Read-only SQLite export; honors `HERMES_HOME`. Known session/message relations are used when available; other schemas are best-effort. |
| Pi Coding Agent | `~/.pi/agent/sessions/` | JSONL scan; honors `PI_CODING_AGENT_DIR`. |
| DeepSeek Harness | `~/.dsh/` | JSONL and Zstandard logs; honors `DSH_HOME`. Select the actual persistence root if configured elsewhere. |
| Custom | Repository's `.agent-sessions/source/` | Supported text exports from other tools. |

Text formats include `.jsonl`, `.json`, `.md`, `.txt`, `.yaml`, and `.yml`. DeepSeek Harness also supports `.zst` and `.zstd` through the `zstandard` dependency. Discovery matches repository paths in content or encoded file paths. This is a heuristic, not a workspace isolation guarantee: once a text file matches, its full content is eligible for capture, including other projects in that file. Exports without a matching repository path can be skipped.

SQLite adapters export project-matched rows rather than raw database files. Unknown schemas, encrypted databases, and messages without a discoverable project relationship can result in incomplete or missing exports. Referenced binary attachments are not automatically collected. Text inputs larger than 50 MiB and databases larger than 1 GiB are skipped; decompression is also bounded. Agent storage changes can require adapter updates. Selection of an agent does not guarantee complete history capture for every product edition.

## Try it in a disposable repository

With the installed environment active:

~~~sh
mkdir agent-session-commit-demo
cd agent-session-commit-demo
git init
git config user.name "Test User"
git config user.email "test@example.invalid"
agent-session-commit install
~~~

Choose **Custom session/export directory** and accept `.agent-sessions/source/`. Create a synthetic transcript containing this repository's absolute path:

~~~sh
python -c "import json; from pathlib import Path; Path('.agent-sessions/source/demo.jsonl').write_text(json.dumps({'cwd': str(Path.cwd()), 'message': 'synthetic test'}) + '\n', encoding='utf-8')"
agent-session-commit status
git commit --allow-empty -m "Test session archive"
git log --oneline
git ls-tree -r --name-only HEAD -- .agent-sessions/bundles
~~~

Expect one commit containing one bundle. Add a line with the same `cwd` to the transcript and commit again to check incremental capture. A commit without session changes should add no bundle. Do not stage the raw source directory; the hook archives it automatically.

## Development and releases

See [CONTRIBUTING.md](https://github.com/Gentle-Lijie/AgentLedger/blob/main/CONTRIBUTING.md) for setup and tests, [CHANGELOG.md](https://github.com/Gentle-Lijie/AgentLedger/blob/main/CHANGELOG.md) for release notes, and [docs/releasing.md](https://github.com/Gentle-Lijie/AgentLedger/blob/main/docs/releasing.md) for publishing prerequisites and the tag-triggered CI contract. Branch pushes and pull requests run tests; publication is reserved for version tags.
