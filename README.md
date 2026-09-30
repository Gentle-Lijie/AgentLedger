# Agent Session Commit

Incrementally archive AI coding-agent sessions in the same Git commit as your code. Agent Session Commit targets macOS, Linux, and Windows with Python 3.10 or newer.

After a successful commit, the hook adds a session bundle using `git commit --amend --no-edit`. There are no extra agent chore commits. Unchanged sessions produce no bundle and no amend.

Author: Lijie Zhou · GitHub: [Gentle-Lijie/AgentLedger](https://github.com/Gentle-Lijie/AgentLedger) · Current stable PyPI release: 0.1.2. Checkout source reports 0.1.3, which is unreleased and not approved for publication.

Version 0.1.1 restores the `agent-session-commit` distribution and command. The `v0.1.0` upload attempt under `agentledger` failed because PyPI rejected the project name; no distribution files were uploaded. That tag remains unchanged.

## Install

Install release 0.1.2 from PyPI in a persistent virtual environment. Create it in a directory you will keep:

~~~sh
python -m venv .venv-agent-session-commit
# macOS / Linux:
source .venv-agent-session-commit/bin/activate
# Windows PowerShell instead:
# .\.venv-agent-session-commit\Scripts\Activate.ps1
# Windows Git Bash instead:
# source .venv-agent-session-commit/Scripts/activate
python -m pip install --index-url https://pypi.org/simple 'agent-session-commit[pre-commit]==0.1.2'
~~~

Keep that environment active when switching to the target repository. The `[pre-commit]` extra installs the pre-commit controller; `questionary` and `PyYAML` are base dependencies. Keep the installed Python environment available: installed hooks depend on it. Moving or deleting it requires reinstalling hooks with a working environment. For an editable source install, see [development setup](CONTRIBUTING.md#development-setup).

On Windows, install Git for Windows and Python. Run the CLI in PowerShell or Git Bash; Git executes its shell hooks using Git for Windows.

## Enable a repository

Recommended: inside the repository you want to archive, run the pre-commit TUI installer:

~~~sh
agent-session-commit install --pre-commit
agent-session-commit status
~~~

Choose one agent and its local session directory or supported SQLite file. The selection is repository-local Git configuration; run `install` separately in each repository. Rerun it to change the source or refresh hooks after an upgrade.

The helper offers arrow-key agent selection and a path-completion prompt, then installs framework-managed hooks. See the details below.

Native hooks are also supported. To use native hook wrappers, run `agent-session-commit install` without `--pre-commit`; it provides the same TUI. Choose one hook manager per repository.

Existing executable pre-commit and post-commit hooks are backed up and called by the wrappers. An existing pre-commit hook can still reject a commit. The original post-commit hook runs once after archiving and sees the final HEAD. Custom `core.hooksPath` setups and third-party hook managers may need manual integration; check which hooks Git actually executes.

To disable native archiving and restore backed-up hooks:

~~~sh
agent-session-commit uninstall
~~~

Previously committed archives and local archive state remain in place. For framework-managed hooks, remove this plugin's entry from `.pre-commit-config.yaml` to disable archiving.

### Use the pre-commit framework

中文步骤：[pre-commit 配置指南](https://github.com/Gentle-Lijie/AgentLedger/blob/main/docs/precommit.zh-CN.md)。

Agent Session Commit supports the [pre-commit framework](https://pre-commit.com/). The extra above installs `pre-commit` version 3.2.0 or newer; the framework installs the archive backend in an isolated Python environment.

Recommended for release 0.1.2: after installing the PyPI package with `[pre-commit]` above, keep its environment active and run this in your target repository:

~~~sh
cd /absolute/path/to/target-repository
agent-session-commit install --pre-commit
agent-session-commit status
~~~

Use the arrow keys to select an agent, then confirm its session directory or SQLite file in the path-completion prompt. If the selected agent matches your existing local Git configuration, the prompt uses the saved source; otherwise it suggests that agent's default path. Custom and Trae export directories are created when missing. Ctrl+C cancels without changing Git configuration.

In unreleased source 0.1.3, choosing Claude Code suggests this repository's Claude project directory, including when an older installation saved the global projects root. A missing Claude project directory is accepted but left for Claude to create after its first session.

The helper saves `agent-session.agent` and `agent-session.source`, then calls the framework installer. pre-commit owns the hooks; the helper creates no native wrappers. If `.pre-commit-config.yaml` is missing, it generates the configuration below with the `v0.1.2` archive backend and both pre/post hook types. An existing configuration, including comments and other hooks, is preserved and must already contain `agent-session-commit` or legacy `agentledger`. If neither is present, setup stops with instructions to merge the entry yourself. All configured default hook types are installed, with `post-commit` ensured even if omitted from the YAML.

If native wrappers are installed, run `agent-session-commit uninstall` first; the helper instructs you to migrate and does not auto-uninstall. `core.hooksPath` must be unset so Git uses its default hook directory. A missing controller error directs you to install `[pre-commit]`; rerun the PyPI install command above in your active environment. Failed framework installation restores previous local Git settings and hook files and removes any newly generated YAML.

For repository-local exports, add `.agent-sessions/source/` to the target repository's `.gitignore`; keep raw exports separate from the tracked bundles.

For scripts or CI, provide both install-only flags to skip the TUI:

~~~sh
agent-session-commit install --pre-commit --agent codex --source /absolute/path/to/sessions
~~~

The TUI runs only during interactive installation, never in Git hooks or CI with both flags supplied. Ordinary upstream `pre-commit install` has no plugin setup callback and cannot automatically display this wizard.

Manual setup is also supported: configure the agent yourself and use the following YAML and commands. These steps do not require the TUI helper.

Copy the [example configuration](https://github.com/Gentle-Lijie/AgentLedger/blob/main/examples/.pre-commit-config.yaml) to your target repository's `.pre-commit-config.yaml`, or merge its settings into an existing configuration:

~~~yaml
minimum_pre_commit_version: '3.2.0'
default_install_hook_types: [pre-commit, post-commit]
repos:
  - repo: https://github.com/Gentle-Lijie/AgentLedger
    rev: v0.1.2
    hooks:
      - id: agent-session-commit
~~~

Inside that repository, activate a persistent virtual environment, configure your source, and install the framework's hooks:

~~~sh
python -m pip install 'pre-commit>=3.2.0'
git config --local agent-session.agent codex
git config --local agent-session.source "$HOME/.codex/sessions"
pre-commit install
~~~

If you previously ran native `agent-session-commit install` **without `--pre-commit`**, run `agent-session-commit uninstall` **before** setting these Git values and installing pre-commit. Older installations can use `agentledger uninstall` for the same migration. Uninstall removes those values, so configure them again afterward. Let pre-commit own the hooks when using this integration; do not run the native installer alongside it.

The `post-commit` stage is intentional: it archives changed sessions and amends the commit that just succeeded. Unchanged sessions cause no amend. The canonical hook ID is `agent-session-commit`, with entry `agent-session-commit hook post-commit`; the old `agentledger` hook ID remains an alias. This configuration uses the `v0.1.2` release tag. See the [integration guide](https://github.com/Gentle-Lijie/AgentLedger/blob/main/docs/precommit.md) for other agents, `CODEX_HOME`, Windows commands, migration, and a portable synthetic example.

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
| Claude Code | Repository's directory under `~/.claude/projects/` | Unreleased source 0.1.3 scopes the default and older global-root configurations to this project; explicit custom sources are retained. Honors `CLAUDE_CONFIG_DIR`; stable 0.1.2 defaults to the shared projects root. |
| OpenAI Codex CLI | `~/.codex/sessions/` | Rollout JSONL scan; honors `CODEX_HOME`. |
| GitHub Copilot CLI | `~/.copilot/session-state/` | Events and text artifacts; honors `COPILOT_HOME`. IDE chat storage and the CLI index database are not directly captured. |
| Hermes Agent | `~/.hermes/state.db` | Read-only SQLite export; honors `HERMES_HOME`. Known session/message relations are used when available; other schemas are best-effort. |
| Pi Coding Agent | `~/.pi/agent/sessions/` | JSONL scan; honors `PI_CODING_AGENT_DIR`. |
| DeepSeek Harness | `~/.dsh/` | JSONL and Zstandard logs; honors `DSH_HOME`. Select the actual persistence root if configured elsewhere. |
| Custom | Repository's `.agent-sessions/source/` | Supported text exports from other tools. |

Text formats include `.jsonl`, `.json`, `.md`, `.txt`, `.yaml`, and `.yml`. DeepSeek Harness also supports `.zst` and `.zstd` through the `zstandard` dependency. In unreleased source 0.1.3, Claude's default and older global-root configurations scan this repository's project directory, skip it if it does not exist yet, and include only native JSONL transcripts with an exact `cwd` match in their header. Other files in that directory are skipped; explicit custom Claude sources remain supported. Other agents may still scan shared roots and match repository paths in content or encoded file paths. Their matching is heuristic, not a workspace isolation guarantee: once a text file matches, its full content is eligible for capture, including other projects in that file. Exports without a matching repository path can be skipped.

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
