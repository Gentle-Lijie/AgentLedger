# Agent Session Commit：pre-commit 配置指南

适用于已发布的 [`agent-session-commit 0.1.1`](https://pypi.org/project/agent-session-commit/0.1.1/)。下面的配置安装到**你要记录会话的项目**，不是工具源码仓库。

需要 Git、Python 3.10+、pre-commit 3.2.0+；Windows 需要 Git for Windows。pre-commit 会自动为本插件创建隔离环境并安装依赖，不必另外安装 `agent-session-commit`。

本插件由 pre-commit 框架管理，但实际运行在 **post-commit** 阶段：代码提交成功后，新增会话归档会 amend 到该提交里，保留提交说明和作者，不产生额外的归档提交。

## 1. 安装 pre-commit

进入目标项目根目录；如果项目还没有 Git 仓库，先运行 `git init`。

如果已经有可用的 Python 虚拟环境，直接激活并安装工具。否则可创建 `.venv`：

### macOS / Linux / Git Bash

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --index-url https://pypi.org/simple "pre-commit>=3.2.0"
pre-commit --version
```

### Windows PowerShell

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --index-url https://pypi.org/simple "pre-commit>=3.2.0"
pre-commit --version
```

将 `.venv/` 加入项目的 `.gitignore`。安装 hooks 后保留这个环境；如果移动或删除环境，要在新的环境里重新运行 `pre-commit install`。如果 PowerShell 不允许激活脚本，可直接调用 `.\.venv\Scripts\python.exe` 和 `.\.venv\Scripts\pre-commit.exe`，无需修改全局执行策略。

如果之前执行过 `agent-session-commit install` 或旧版 `agentledger install`，先完成下方的[旧 hooks 迁移](#旧-hooks-迁移)，再配置会话来源。

## 2. 新建配置文件

在目标仓库根目录创建 `.pre-commit-config.yaml`：

```yaml
minimum_pre_commit_version: "3.2.0"
default_install_hook_types: [pre-commit, post-commit]

repos:
  - repo: https://github.com/Gentle-Lijie/AgentLedger
    rev: v0.1.1
    hooks:
      - id: agent-session-commit
```

也可以复制[示例文件](../examples/.pre-commit-config.yaml)。如果已有配置，合并这个 `repos` 条目；`default_install_hook_types` 中增加 `post-commit`，同时保留项目已有的 hook 类型。

GitHub 仓库仍名为 `AgentLedger`；当前 PyPI 包名、命令和 hook ID 都是 `agent-session-commit`。`rev` 固定到已发布的 `v0.1.1`。

## 3. 配置使用的 agent 和会话来源

每个仓库都要设置两个 **Git local config** 项；这些配置存在 `.git/config` 中，不随源码提交。团队成员可以分别选择自己的工具和路径。

### Codex：macOS / Linux / Git Bash

```sh
git config --local agent-session.agent codex
git config --local agent-session.source "${CODEX_HOME:-$HOME/.codex}/sessions"
```

### Codex：Windows PowerShell

```powershell
git config --local agent-session.agent codex
$agentSessionSource = Join-Path $HOME ".codex/sessions"
if ($env:CODEX_HOME) {
    $agentSessionSource = Join-Path $env:CODEX_HOME "sessions"
}
git config --local agent-session.source "$agentSessionSource"
```

### Claude Code 示例

```sh
git config --local agent-session.agent claude
git config --local agent-session.source "${CLAUDE_CONFIG_DIR:-$HOME/.claude}/projects"
```

### 其他 agent

把 `agent-session.agent` 改为下面的配置值，并把 `agent-session.source` 设置为实际存在的目录或受支持的 SQLite 文件。

| 工具 | 配置值 | 默认来源 | 自定义目录说明 |
| --- | --- | --- | --- |
| ZCode | `zcode` | `~/.zcode/cli/db/db.sqlite` | 检查 `ZCODE_STORAGE_DIR` 或 `ZCODE_DATA_BASE_DIR` 下的实际数据库。 |
| Qoder | `qoder` | `~/.qoder/projects/` | `QODER_CONFIG_DIR/projects`；IDE 可指定实际 transcript 目录。 |
| Trae IDE | `trae` | 项目的 `.agent-sessions/source/` | 先导出会话为文本文件；不直接读取加密历史库。 |
| CodeBuddy | `codebuddy` | `~/.codebuddy/projects/` | CLI 可用 `CODEBUDDY_CONFIG_DIR/projects`；IDE 需导出会话。 |
| Claude Code | `claude` | `~/.claude/projects/` | `CLAUDE_CONFIG_DIR/projects`。 |
| Codex CLI | `codex` | `~/.codex/sessions/` | `CODEX_HOME/sessions`。 |
| Copilot CLI | `copilot` | `~/.copilot/session-state/` | `COPILOT_HOME/session-state`；不是 IDE Chat 的存储目录。 |
| Hermes | `hermes` | `~/.hermes/state.db` | `HERMES_HOME/state.db`。 |
| Pi | `pi` | `~/.pi/agent/sessions/` | `PI_CODING_AGENT_DIR/sessions`。 |
| DeepSeek Harness | `deepseek-harness` | `~/.dsh/` | `DSH_HOME` 或实际配置的会话 persistence root。 |
| 自定义导出 | `custom` | 自行指定 | 包含受支持文本会话文件的目录。 |

例如 Qoder 的默认目录：

```sh
git config --local agent-session.agent qoder
git config --local agent-session.source "$HOME/.qoder/projects"
```

路径必须能被运行 Git 的这台机器读取。直接写 Git 配置时，需要自己把环境变量展开成实际路径；之后修改环境变量，不会自动更新已保存的 Git 配置。SSH、WSL 或远程 IDE 的记录可能保存在另一台机器上。

Trae/CodeBuddy IDE 的导出目录需要先创建，再导出文本。项目匹配是启发式的，导出内容应包含当前仓库的绝对路径；SQLite 适配是尽力读取，不保证所有版本和所有关联消息都能完整导出。详见 [README 中的来源与限制](../README.md#agent-sources-and-limitations)。

## 4. 安装 Git hooks

完成 YAML 和本地 Git 配置后运行：

```sh
pre-commit validate-config
pre-commit install --install-hooks
```

正常情况下，会安装 `.git/hooks/pre-commit` 和 `.git/hooks/post-commit`，并首次下载、安装插件环境。之后会复用缓存。

使用框架模式时，不要再运行 `agent-session-commit install`；让 pre-commit 管理这些 hooks。

将配置文件提交到项目，方便团队复用：

```sh
git add .pre-commit-config.yaml
git commit -m "Configure agent session archiving"
```

如果已经产生该项目的会话记录，这次提交本身就可能包含归档。其他成员克隆仓库后，仍需设置自己的两个 Git local config 项，再运行 `pre-commit install`。

## 5. 验证是否生效

先在该项目里使用选定的 AI agent，产生一段**新的**会话记录，然后正常提交代码；也可以创建一个空的验证提交：

```sh
git commit --allow-empty -m "Verify agent session archive"
git log --oneline -3
git ls-tree -r --name-only HEAD -- .agent-sessions/bundles
git show --stat HEAD
git rev-parse HEAD
```

预期结果：

- Git 历史里只有这次用户提交，没有额外的 agent `chore` 提交。
- 如果发现新的会话内容，该提交包含 `.agent-sessions/bundles/*.tar.gz`。
- 继续对话、再次提交，会新增一个增量包；会话没有变化时，不生成包，也不 amend。
- amend 会改变 SHA，最终提交以 `git rev-parse HEAD` 为准。

`pre-commit run --all-files` 默认运行 **pre-commit** 阶段，不会执行本插件的 **post-commit** 归档。验证本插件应使用真实的 Git 提交。

## 旧 hooks 迁移

如果之前用了工具自带的原生安装器，先使用原环境里的命令卸载包装脚本：

```sh
agent-session-commit uninstall
# 旧版也可使用：agentledger uninstall
```

卸载会恢复备份的 hooks，并删除 `agent-session.agent`、`agent-session.source` 两个 local config 项，不会删除已有归档。因此接下来要重新执行第 3 步，再安装 pre-commit hooks。

如果当前仓库已有其他 pre-commit 插件，保留它们的配置，合并本插件的条目即可。

## 常见问题

### 显示 Passed，但没有生成包

`Passed` 表示 hook 命令执行成功，不保证找到了当前项目的新会话。先检查：

```sh
git config --local --get agent-session.agent
git config --local --get agent-session.source
```

确认路径存在、agent 在该仓库中产生过记录、内容有变化，并且记录可以匹配当前仓库路径。只有 pre-commit 隔离安装时，`agent-session-commit` 不一定在你的终端 PATH 中；上述 Git 命令即可检查配置。

需要看到成功 hook 的诊断输出时，可以加 `verbose`：

```yaml
hooks:
  - id: agent-session-commit
    verbose: true
```

### 安装时提示 core.hooksPath

pre-commit 要使用默认 `.git/hooks`，即使 `core.hooksPath` 的值是 `.git/hooks`，也会拒绝安装。先查看设置来自哪里：

```sh
git config --show-origin --get core.hooksPath
```

如果它来自 Husky、其他 hook 管理器或全局配置，先决定由哪个管理器负责，再调整配置；不要直接覆盖现有 hooks。

### 改用另一个 agent

重新设置第 3 步的两个 Git local config 项即可。`.pre-commit-config.yaml` 是团队共享的插件配置，不需要每个人把自己的会话目录写进去。

### 如何停用

从 `.pre-commit-config.yaml` 中移除本插件条目即可；保留其他插件。需要卸载框架的 post-commit 脚本时，可运行 `pre-commit uninstall --hook-type post-commit`，但这会影响该阶段的其他插件，先确认项目配置。

已有会话归档仍保留在 Git 历史中。归档是未加密的普通 Git 文件，可能含提示词、代码和本地路径，不会自动脱敏；启用前确认所选会话适合提交到该仓库。

## 参考

- [pre-commit 官方文档](https://pre-commit.com/)
- [English guide](precommit.md)
- [完整示例配置](../examples/.pre-commit-config.yaml)
- [PyPI：agent-session-commit 0.1.1](https://pypi.org/project/agent-session-commit/0.1.1/)
