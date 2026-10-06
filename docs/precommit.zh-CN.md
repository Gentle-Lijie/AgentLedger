# Agent Session Commit：pre-commit 配置指南

当前发布版本为 [`agent-session-commit 0.1.5`](https://pypi.org/project/agent-session-commit/0.1.5/)，包含 TUI 安装助手，归档后端使用 `v0.1.5` tag。0.1.1 恢复了当前包名；此前 `v0.1.0` 使用 `agentledger` 上传时被 PyPI 拒绝，未上传任何发行文件，该 tag 保持不变。下面的配置安装到**你要记录会话的项目**，不是工具源码仓库。

需要 Git、Python 3.10+、pre-commit 3.2.0+；Windows 需要 Git for Windows。pre-commit 会为归档插件创建隔离环境并安装依赖。手动配置不必另外安装 `agent-session-commit`；使用 TUI 助手则要先把 PyPI 包安装到自己的持久环境中。

本插件由 pre-commit 框架管理，但实际运行在 **post-commit** 阶段：代码提交成功后，新增会话归档会 amend 到该提交里，保留提交说明和作者，不产生额外的归档提交。

## 推荐：通过 0.1.5 TUI 完成配置和安装

从 PyPI 安装发布版本。在一个会长期保留的目录中创建并激活虚拟环境：

```sh
python -m venv .venv-agent-session-commit
# macOS / Linux：
source .venv-agent-session-commit/bin/activate
# Windows PowerShell 改用：
# .\.venv-agent-session-commit\Scripts\Activate.ps1
# Windows Git Bash 改用：
# source .venv-agent-session-commit/Scripts/activate
python -m pip install --index-url https://pypi.org/simple 'agent-session-commit[pre-commit]==0.1.5'
```

按你的系统选择一条激活命令。可选依赖 `[pre-commit]` 会安装框架控制器；`questionary` 和 `PyYAML` 是基础依赖。保持这个环境激活，再切换到目标项目；安装后也要保留环境，移动或删除后需在可用环境中重新安装 hooks。

```sh
cd /absolute/path/to/target-repository
agent-session-commit install --pre-commit
```

安装助手会：

1. 显示 agent 列表，用方向键选择、Enter 确认。
2. 显示支持路径补全的会话目录或 SQLite 文件输入框。如果选择的 agent 与已有 Git local config 相同，会预填已保存的来源；否则预填该 agent 的默认路径。Custom 和 Trae 导出目录不存在时会自动创建，其他来源须已存在。
3. 保存 `agent-session.agent`、`agent-session.source` 和仓库根目录 `agent-session.workdir`，再调用 pre-commit 框架安装 hooks。框架负责这些 hooks，助手不创建原生包装脚本。

Ctrl+C 取消时不会修改 Git 配置。每个仓库、每个克隆都需要设置自己的来源；再次运行助手即可更换 agent 或路径。

### 如何处理已有配置

- 如果没有 `.pre-commit-config.yaml`，助手会生成下方手动配置示例，归档后端固定到 `v0.1.5`，默认安装 `pre-commit` 和 `post-commit`。
- 如果已有配置，会原样保留注释和其他 hooks。文件中必须已有 `agent-session-commit` 或兼容的 `agentledger` hook ID；没有时会报错并给出合并指引，不会自动重写。手动合并下方插件条目后，再运行助手。
- 安装会保留 `default_install_hook_types` 中的所有类型，并确保安装 `post-commit`，即使 YAML 列表漏写了它。为了以后直接运行 `pre-commit install` 时也能安装该阶段，请手动把 `post-commit` 加入列表。
- 框架安装失败时，会恢复原有 Git local config 和 hook 文件，并删除本次新生成的 YAML。

如果装过原生包装脚本，先运行 `agent-session-commit uninstall`，再运行助手。助手会在预检查中提示迁移，不会自动卸载。`core.hooksPath` 必须未设置，以便使用 Git 默认 hooks 目录；相关处理见下方常见问题。缺少控制器时，错误信息会提示安装 `[pre-commit]`，请在已激活的环境中重新执行上面的 PyPI 安装命令。

如果采用仓库内的导出目录，请在目标项目的 `.gitignore` 中加入 `.agent-sessions/source/`；只提交 `bundles/` 中的归档，不要把原始导出一起暂存。

### CI 或非交互安装

同时提供 `--agent` 和 `--source`，即可跳过 TUI：

```sh
agent-session-commit install --pre-commit --agent codex --source /absolute/path/to/sessions
```

`--pre-commit`、`--agent`、`--source` 仅用于 `install`。缺少 agent 或 source 时需要交互终端；CI 应提供两项，且来源必须能被该环境读取。Git hooks 中不会弹出 TUI。

开发时也可选择可编辑源码安装，见 [CONTRIBUTING.md](../CONTRIBUTING.md#development-setup)。

普通的上游 `pre-commit install` 没有插件安装回调，不能自动弹出 agent 选择界面。请显式运行 `agent-session-commit install --pre-commit`，也可按下面步骤手动配置。

## 手动配置

以下步骤不需要 TUI 助手，共享 YAML 使用 `rev: v0.1.5`。无 `--pre-commit` 的 `agent-session-commit install` 仍是原生安装模式，会管理包装脚本，也提供 TUI。使用框架模式时应选择带 `--pre-commit` 的助手，或下面的手动步骤。

## 1. 安装 pre-commit

进入目标项目根目录；如果项目还没有 Git 仓库，先运行 `git init`。

如果已经有可用的 Python 虚拟环境，直接激活并安装工具。否则可创建 `.venv`：

### macOS / Linux

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --index-url https://pypi.org/simple "pre-commit>=3.2.0"
pre-commit --version
```

Windows Git Bash 可使用 `python -m venv .venv` 和 `source .venv/Scripts/activate`，然后执行同样的 pip 安装命令。

### Windows PowerShell

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --index-url https://pypi.org/simple "pre-commit>=3.2.0"
pre-commit --version
```

将 `.venv/` 加入项目的 `.gitignore`。安装 hooks 后保留这个环境；如果移动或删除环境，要在新的环境里重新运行 `pre-commit install`。如果 PowerShell 不允许激活脚本，可直接调用 `.\.venv\Scripts\python.exe` 和 `.\.venv\Scripts\pre-commit.exe`，无需修改全局执行策略。

如果之前执行过**不带 `--pre-commit`** 的原生 `agent-session-commit install` 或旧版 `agentledger install`，先完成下方的[旧 hooks 迁移](#旧-hooks-迁移)，再配置会话来源。

## 2. 新建配置文件

在目标仓库根目录创建 `.pre-commit-config.yaml`：

```yaml
minimum_pre_commit_version: "3.2.0"
default_install_hook_types: [pre-commit, post-commit]

repos:
  - repo: https://github.com/Gentle-Lijie/AgentLedger
    rev: v0.1.5
    hooks:
      - id: agent-session-commit
```

也可以复制[示例文件](../examples/.pre-commit-config.yaml)。如果已有配置，合并这个 `repos` 条目；`default_install_hook_types` 中增加 `post-commit`，同时保留项目已有的 hook 类型。

GitHub 仓库仍名为 `AgentLedger`；当前 PyPI 包名、命令和 hook ID 都是 `agent-session-commit`。`rev` 固定到发布版本 `v0.1.5`。

## 3. 配置使用的 agent 和会话来源

每个仓库都要设置三个 **Git local config** 项；这些配置存在 `.git/config` 中，不随源码提交。`agent-session.workdir` 固定为 Git 仓库根目录，即使从子目录安装也一样；只有会话记录的 `cwd` 与它精确相同才会归档。团队成员可以分别选择自己的工具和来源路径。

0.1.5 的 `agent-session-commit install --pre-commit` 已通过 TUI 完成这一步和 hooks 安装，无需重复下面的手动命令。选择手动配置时使用以下命令。

### Codex：macOS / Linux / Git Bash

```sh
git config --local agent-session.agent codex
git config --local agent-session.source "${CODEX_HOME:-$HOME/.codex}/sessions"
git config --local agent-session.workdir "$(git rev-parse --show-toplevel)"
```

### Codex：Windows PowerShell

```powershell
git config --local agent-session.agent codex
$agentSessionSource = Join-Path $HOME ".codex/sessions"
if ($env:CODEX_HOME) {
    $agentSessionSource = Join-Path $env:CODEX_HOME "sessions"
}
git config --local agent-session.source "$agentSessionSource"
git config --local agent-session.workdir "$(git rev-parse --show-toplevel)"
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
| Copilot VSCode | `copilot-vscode` | VSCode 的 `User/workspaceStorage/` | `COPILOT_VSCODE_HOME/workspaceStorage`；VSCode 扩展聊天会话。 |
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

使用框架模式时，不要再运行**不带 `--pre-commit`** 的原生 `agent-session-commit install`。可用 `agent-session-commit install --pre-commit` 完成框架安装，让 pre-commit 管理这些 hooks。

将配置文件提交到项目，方便团队复用：

```sh
git add .pre-commit-config.yaml
git commit -m "Configure agent session archiving"
```

如果已经产生该项目的会话记录，这次提交本身就可能包含归档。其他成员克隆仓库后，仍需设置自己的三个 Git local config 项，再运行 `pre-commit install`；也可运行 TUI 助手。

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

卸载会恢复备份的 hooks，并删除 `agent-session.agent`、`agent-session.source`、`agent-session.workdir` 三个 local config 项，不会删除已有归档。接下来运行 `agent-session-commit install --pre-commit`，重新选择来源并安装框架；也可重新执行第 3 步，再安装 pre-commit hooks。助手检测到原生包装脚本时会提示先卸载，不会自动卸载。

如果当前仓库已有其他 pre-commit 插件，保留它们的配置，合并本插件的条目即可。

## 常见问题

### 显示 Passed，但没有生成包

`Passed` 表示 hook 命令执行成功，不保证找到了当前项目的新会话。先检查：

```sh
git config --local --get agent-session.agent
git config --local --get agent-session.source
git config --local --get agent-session.workdir
```

确认来源路径存在、`agent-session.workdir` 是当前 Git 仓库根目录、agent 的会话 `cwd` 与该根目录精确相同且内容有变化。只有 pre-commit 隔离安装时，`agent-session-commit` 不一定在你的终端 PATH 中；上述 Git 命令即可检查配置。

需要看到成功 hook 的诊断输出时，可以加 `verbose`：

```yaml
hooks:
  - id: agent-session-commit
    verbose: true
```

### 安装时提示 core.hooksPath

pre-commit 要使用默认 `.git/hooks`，即使 `core.hooksPath` 的值是 `.git/hooks`，也会拒绝安装。先查看设置来自哪里：

```sh
git config --show-origin --get-all core.hooksPath
```

如果它来自 Husky、其他 hook 管理器或全局配置，先决定由哪个管理器负责，再调整配置；不要直接覆盖现有 hooks。

### 改用另一个 agent

重新运行 `agent-session-commit install --pre-commit`，或重新设置第 3 步的三个 Git local config 项即可。`.pre-commit-config.yaml` 是团队共享的插件配置，不需要每个人把自己的会话目录写进去。

### 为什么 pre-commit install 没有显示选择界面

上游命令没有插件安装回调。TUI 属于安装助手，需先按上方从 PyPI 安装，再运行 `agent-session-commit install --pre-commit`。它只在交互安装时显示，不在每次 Git commit 或 CI 中显示。

### 助手提示配置缺少本插件或缺少控制器

已有 `.pre-commit-config.yaml` 时，助手不会自动插入条目。按第 2 步合并 `agent-session-commit` hook，保留其他配置和注释，再试一次；旧 `agentledger` ID 也被接受。缺少 pre-commit 控制器时，在已激活的环境里运行 `python -m pip install --index-url https://pypi.org/simple 'agent-session-commit[pre-commit]==0.1.5'`。

### 如何停用

从 `.pre-commit-config.yaml` 中移除本插件条目即可；保留其他插件。需要卸载框架的 post-commit 脚本时，可运行 `pre-commit uninstall --hook-type post-commit`，但这会影响该阶段的其他插件，先确认项目配置。

已有会话归档仍保留在 Git 历史中。归档是未加密的普通 Git 文件，可能含提示词、代码和本地路径，不会自动脱敏；启用前确认所选会话适合提交到该仓库。

## 参考

- [pre-commit 官方文档](https://pre-commit.com/)
- [English guide](precommit.md)
- [完整示例配置](../examples/.pre-commit-config.yaml)
- [PyPI：agent-session-commit 0.1.5](https://pypi.org/project/agent-session-commit/0.1.5/)
