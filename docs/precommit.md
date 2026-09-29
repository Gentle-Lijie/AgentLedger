# Use Agent Session Commit with the pre-commit framework

[简体中文配置指南](precommit.zh-CN.md)

Agent Session Commit includes a hook for the [pre-commit framework](https://pre-commit.com/). You need Git, Python 3.10 or newer, and pre-commit 3.2.0 or newer; Windows requires Git for Windows. The framework installs the archive backend in an isolated Python environment. A separate installation is needed only if you want to run the development installer helper in your shell.

Version `0.1.1` is [published on PyPI](https://pypi.org/project/agent-session-commit/0.1.1/) and the `v0.1.1` tag is available. The earlier `v0.1.0` PyPI upload under `agentledger` failed a project-name conflict check without uploading distribution files; that tag remains unchanged.

The source version on `main` is **0.1.2 (unreleased)**. Its new TUI helper can configure the repository and call the framework installer in one command. It is not available in the published 0.1.1 package. The shared YAML below continues to use stable `v0.1.1` as the archive backend.

## Development 0.1.2: configure with the TUI helper

This is the recommended setup **when trying development version 0.1.2**. Clone the source and install it in a persistent virtual environment:

~~~sh
git clone https://github.com/Gentle-Lijie/AgentLedger.git
cd AgentLedger
python -m venv .venv
# macOS / Linux:
source .venv/bin/activate
# Windows PowerShell instead:
# .\.venv\Scripts\Activate.ps1
# Windows Git Bash instead:
# source .venv/Scripts/activate
python -m pip install --index-url https://pypi.org/simple -e '.[pre-commit]'
~~~

Use the activation command appropriate to your shell. The optional `[pre-commit]` extra installs the framework controller; `questionary` and `PyYAML` are base dependencies. Keep the environment active as you switch to the target repository, and retain it after installation. If you move or delete it, reinstall the hooks from a working environment.

~~~sh
cd /absolute/path/to/target-repository
agent-session-commit install --pre-commit
~~~

Use the arrow keys and Enter to select an agent. The next prompt supports path completion for a session directory or supported SQLite file. It prefills the saved Git-local source if the agent matches the previous selection, otherwise the agent's default path. Custom and Trae export directories are created if missing; other sources must already exist. Ctrl+C cancels without changing Git configuration.

The helper saves `agent-session.agent` and `agent-session.source` in local Git configuration, then invokes the framework installer. It does not create native hook wrappers. Each clone needs its own setup; rerun the helper to change your agent or source.

Configuration handling:

- With no `.pre-commit-config.yaml`, it generates the YAML shown in the stable section below, pinned to available `v0.1.1`, with `default_install_hook_types: [pre-commit, post-commit]`.
- An existing YAML file, including comments and other hooks, is preserved. It must already include hook ID `agent-session-commit` or legacy `agentledger`. If the entry is missing, setup stops with actionable merge instructions; it does not rewrite your configuration automatically. Merge the entry shown below, then rerun the helper.
- Installation includes all hook types from `default_install_hook_types` and ensures `post-commit`, even when absent from that list. Commit the YAML so collaborators can reuse it; for future plain `pre-commit install` runs, include `post-commit` in that list yourself.
- If framework installation fails, previous local Git settings and hook files are restored and newly generated YAML is removed.

Before setup, migrate any native wrappers with `agent-session-commit uninstall` as described below. The helper detects them and explains the migration; it does not auto-uninstall. `core.hooksPath` must be unset so Git uses its default hooks directory. If the controller is missing, install the `[pre-commit]` extra using the source-install command above, then retry.

For CI or other noninteractive setup, supply both flags:

~~~sh
agent-session-commit install --pre-commit --agent codex --source /absolute/path/to/sessions
~~~

`--pre-commit`, `--agent`, and `--source` are valid only with `install`. Supplying both agent and source skips the TUI; an interactive terminal is required when either is omitted. The source must be accessible in that environment. Git hooks never show the TUI.

As an alternative to a checkout, install from `main` into an active persistent environment with a quoted PEP 508 reference:

~~~sh
python -m pip install --index-url https://pypi.org/simple 'agent-session-commit[pre-commit] @ git+https://github.com/Gentle-Lijie/AgentLedger.git@main'
~~~

Prefer the checkout instructions for development. Neither method installs a published 0.1.2 release from PyPI.

Ordinary upstream `pre-commit install` has no plugin setup callback, so it cannot automatically show this wizard. Use the explicit helper above, or the stable manual steps below. `agent-session-commit install` **without `--pre-commit`** remains the native installer (with a TUI in source version 0.1.2) and owns native wrappers.

## Stable 0.1.1: configure a repository manually

These steps remain valid with published 0.1.1. Only the pre-commit controller needs to be installed in your shell; the framework installs the archive backend separately.

Run these commands inside the repository whose sessions you want to archive. If it already uses Agent Session Commit's native hooks, complete the migration section first.

~~~sh
python -m pip install 'pre-commit>=3.2.0'
git config --local agent-session.agent codex
git config --local agent-session.source "$HOME/.codex/sessions"
~~~

If Codex uses a custom `CODEX_HOME`, use its sessions directory instead:

~~~sh
git config --local agent-session.source "${CODEX_HOME:-$HOME/.codex}/sessions"
~~~

You can also specify an absolute source path explicitly:

~~~sh
git config --local agent-session.source "/absolute/path/to/session-directory"
~~~

These commands use macOS/Linux or Git Bash syntax. For Windows PowerShell:

~~~powershell
python -m pip install 'pre-commit>=3.2.0'
git config --local agent-session.agent codex
git config --local agent-session.source "$HOME/.codex/sessions"
# If CODEX_HOME is configured, use this instead:
# git config --local agent-session.source "$env:CODEX_HOME/sessions"
~~~

The selected source must exist and be accessible on the machine running Git. Git configuration stores the path you provide; setting an environment variable later does not change it. Each clone needs its own local configuration.

Copy [examples/.pre-commit-config.yaml](../examples/.pre-commit-config.yaml) into the target repository as `.pre-commit-config.yaml`. Its contents are:

~~~yaml
minimum_pre_commit_version: '3.2.0'
default_install_hook_types: [pre-commit, post-commit]
repos:
  - repo: https://github.com/Gentle-Lijie/AgentLedger
    rev: v0.1.1
    hooks:
      - id: agent-session-commit
~~~

For an existing configuration, merge the repository entry and include both hook types in `default_install_hook_types`. Preserve any other hook types your project uses. Then install:

~~~sh
pre-commit install
~~~

The framework installs into Git's default `.git/hooks` directory and refuses installation when `core.hooksPath` is set, even if that setting points to `.git/hooks`. If the installer reports this, inspect `git config --show-origin --get-all core.hooksPath` and choose which hook manager should own the repository before changing that configuration.

Commit `.pre-commit-config.yaml` to share the integration with collaborators. They run the Git configuration commands and `pre-commit install` in their own clones, or use the development helper above. Do not run native `agent-session-commit install` **without `--pre-commit`** alongside framework-managed hooks.

## Why post-commit?

The canonical hook ID is `agent-session-commit`. Its entry point is `agent-session-commit hook post-commit`, with `language: python`, `stages: [post-commit]`, `always_run: true`, `pass_filenames: false`, `require_serial: true`, and minimum pre-commit version `3.2.0`. These defaults are supplied by Agent Session Commit's root hook manifest; users do not need to repeat them. The old `agentledger` hook ID remains an alias, and the `agentledger` CLI/module remain compatibility shims. New configurations should use the canonical ID.

The stage name describes when it runs: after Git creates your code commit, Agent Session Commit gathers changed session data and adds the bundle with `git commit --amend --no-edit`. No additional chore commit is created. Unchanged sessions produce no bundle and no amend. The hook runs even when no filenames are passed, including an empty commit.

The amend preserves the commit message, author, and parents, and excludes unrelated staged changes. Internal amend operations suppress hooks to prevent recursion. Other hooks in the original post-commit run execute according to the framework's order; integrations needing the final HEAD should follow Agent Session Commit.

Amending changes the SHA; use `git rev-parse HEAD` for the final value. Archive failures leave the code commit in place. `pre-commit run --all-files` runs the default pre-commit stage and does not exercise this post-commit hook. Validate it with a real commit as described below.

## Migrate from native Agent Session Commit hooks

If you previously ran native `agent-session-commit install` **without `--pre-commit`**, use its existing installation to uninstall the native wrappers first:

~~~sh
agent-session-commit uninstall
~~~

Older installations can use `agentledger uninstall`, the retained compatibility command. Uninstall restores backed-up hooks and removes `agent-session.agent` and `agent-session.source`. Previously committed archives and local fingerprint state remain. With development 0.1.2, run `agent-session-commit install --pre-commit` afterward to select and save your agent/source again. The helper preflight instructs you to uninstall native wrappers first and does not remove them automatically.

With stable 0.1.1, configure the agent and source again, copy or merge the example configuration, then install the framework hooks:

~~~sh
git config --local agent-session.agent codex
git config --local agent-session.source "$HOME/.codex/sessions"
pre-commit install
~~~

Use your actual source path, including any `CODEX_HOME` override. Uninstalling native hooks before installing framework hooks avoids two owners of the same Git hooks. Agent Session Commit's command need not be available in your shell afterward: pre-commit uses its isolated installation.

## Other agents

Set `agent-session.agent` to the key below and `agent-session.source` to an existing source. Paths use your home directory unless described as repository-local.

| Agent key | Source | Custom location |
| --- | --- | --- |
| `zcode` | `~/.zcode/cli/db/db.sqlite` | Actual SQLite file under `ZCODE_STORAGE_DIR`, or `ZCODE_DATA_BASE_DIR/.zcode/cli/db/db.sqlite`. |
| `qoder` | `~/.qoder/projects/` | `QODER_CONFIG_DIR/projects`, or the IDE transcript directory. |
| `trae` | Repository's `.agent-sessions/source/` | Directory containing exported conversations. |
| `codebuddy` | `~/.codebuddy/projects/` | `CODEBUDDY_CONFIG_DIR/projects`; IDE users select exported transcripts. |
| `claude` | `~/.claude/projects/` | `CLAUDE_CONFIG_DIR/projects`. |
| `codex` | `~/.codex/sessions/` | `CODEX_HOME/sessions`. |
| `copilot` | `~/.copilot/session-state/` | `COPILOT_HOME/session-state`; CLI sessions only. |
| `hermes` | `~/.hermes/state.db` | `HERMES_HOME/state.db`. |
| `pi` | `~/.pi/agent/sessions/` | `PI_CODING_AGENT_DIR/sessions`. |
| `deepseek-harness` | `~/.dsh/` | `DSH_HOME` or the actual configured persistence root. |
| `custom` | Repository's `.agent-sessions/source/` | Directory containing supported text exports. |

For example, Claude Code with its default path:

~~~sh
git config --local agent-session.agent claude
git config --local agent-session.source "$HOME/.claude/projects"
~~~

With direct Git configuration, expand environment overrides yourself into the actual source path; the hook reads `agent-session.source` rather than discovering a new default each time. See [agent sources and limitations](../README.md#agent-sources-and-limitations) for formats and project matching. Exported text should contain the target repository's absolute path so it can be matched.

## Portable synthetic check

In a disposable repository, install the example configuration and framework hooks as above. These commands work in macOS/Linux shells and Windows PowerShell with Python available as `python`. They create a synthetic transcript under Git's private directory, keeping the raw fixture out of commits:

~~~sh
git config --local agent-session.agent custom
python -c "import json, subprocess; from pathlib import Path; source = Path(subprocess.check_output(['git', 'rev-parse', '--git-path', 'agent-session-commit-demo-sessions'], text=True).strip()).resolve(); source.mkdir(parents=True, exist_ok=True); (source / 'demo.jsonl').write_text(json.dumps({'cwd': str(Path.cwd().resolve()), 'message': 'synthetic test'}) + '\n', encoding='utf-8'); subprocess.run(['git', 'config', '--local', 'agent-session.source', str(source)], check=True)"
git commit --allow-empty -m "Test session archive"
git log --oneline
git ls-tree -r --name-only HEAD -- .agent-sessions/bundles
~~~

Expect one new commit containing a bundle, with no extra archive commit. Append a record and commit again:

~~~sh
python -c "import json, subprocess; from pathlib import Path; source = Path(subprocess.check_output(['git', 'config', '--local', 'agent-session.source'], text=True).strip()); transcript = source / 'demo.jsonl'; transcript.write_bytes(transcript.read_bytes() + (json.dumps({'cwd': str(Path.cwd().resolve()), 'message': 'second record'}) + '\n').encode('utf-8'))"
git commit --allow-empty -m "Test incremental archive"
git ls-tree -r --name-only HEAD -- .agent-sessions/bundles
git commit --allow-empty -m "Test unchanged sessions"
~~~

The second commit should add one incremental bundle. The third should add none. Without an Agent Session Commit shell installation, inspect configuration with `git config --local --get agent-session.agent` and `git config --local --get agent-session.source`.

To disable only Agent Session Commit in a shared pre-commit setup, remove its hook entry from `.pre-commit-config.yaml`. Keep the framework installed for your other hooks. Archives remain ordinary Git files; the [README](../README.md#what-gets-committed) describes their contents and reconstruction.
