# 智能体与计划

用户使用自然语言与大语言模型交互直接使用外部智能体 Harness。Harness 经 MCP 访问 bacmap；
确定性管线、门以及**可信确认界面**都留在 bacmap 内。没有内置对话。

```text
Hermes / Pi / DSH / Codex / any MCP client
        │  MCP: tools, prompts, resources
        ▼
bacmap MCP server ── profile (cloud | local-trusted)
        │
        ├─ read/compute tools (profile-filtered)
        ├─ plan tools: create / revise / get
        ├─ task tools: submit / status / result / cancel
        └─ record tool (local-trusted only)
                 │
                 ▼
        task engine + gates + audit
                 ▲
                 │ human confirmation (Web / CLI / local dialog)
              you
```

## 0. 最小操作序列（照抄即可）

1. 让客户端启动 `bacmap start mcp`（配置见 §3）；
2. 在对话里给出目标与**绝对路径**：
   > 用标准管线分析 `/data/run42` 下的八套副溶血性弧菌 reads。
3. 智能体调用 `bacmap_create_plan`，返回 `plan_id`、`version`、`plan_hash` 和 `confirm_url`；
4. **你**确认这个确切版本：点击 `confirm_url`、让智能体调用本机对话框，或执行：
   ```bash
   bacmap plan confirm <plan_id> --version <version> --hash <前12位>
   ```
5. 继续追问：
   > 运行到哪一步了？完成后汇总血清型和耐药，并列出需要复核的样本。

智能体不能替你确认；这是设计边界，不是故障。完整示例见[教程](../getting-started/tutorial.zh.md)。

## 0.1 不必每次粘贴规则：持久指令 / Hook

bacmap MCP 服务器在初始化时会返回一段 **server instructions**，已经写明：

- 分析/写入先 `bacmap_create_plan`；
- 计划由人确认，智能体不能确认；
- 不要用 Harness 自己的 shell/文件工具运行 `snakemake`/`gside`/`gspec`/`gmlst`；
- 不要读取原始序列，只传绝对路径或样本 ID；
- 结果用 `bacmap_get_plan` / `bacmap_task_status` / `bacmap_task_result` 跟踪；
- 结论引用样本、task、run 标识。

支持 MCP instructions 的客户端会自动把它纳入上下文。若你的客户端没有这样做，或你想更强制一点，用该客户端的**持久指令/自动注入机制**，而不是每轮粘贴。

### Hermes

Hermes 会自动注入项目上下文文件。在启动 Hermes 的工作目录放：

```text
.hermes.md        # Hermes 专用，可随项目继承
AGENTS.md         # 跨客户端通用（当前目录）
```

写入：

```markdown
# bacmap 操作规则

- bacmap 相关分析只调用 mcp__bacmap__* 工具。
- 写入/分析先 bacmap_create_plan；把 plan_id/version/plan_hash/confirm_url 给用户，等待人工确认。
- 禁止用 shell 运行 snakemake/gside/gspec/gmlst；禁止读取 FASTQ/FASTA 原文。
- 用户提供绝对路径或样本 ID；由 bacmap 本地执行。
- 跟踪用 bacmap_get_plan/bacmap_task_status；结论引用 task_id/run_id。
```

验证是否注入：新会话直接问“你操作 bacmap 的规则是什么”。用
`hermes --ignore-rules` 可以临时关闭上下文注入做对照。

### Pi

Pi 支持全局与项目级持久系统指令：

```text
~/.pi/agent/APPEND_SYSTEM.md     # 全局追加
<project>/.pi/APPEND_SYSTEM.md   # 项目级（需项目信任）
<project>/AGENTS.md              # 常规上下文
```

推荐把上面同一段“bacmap 操作规则”放进 `~/.pi/agent/APPEND_SYSTEM.md`。修改后在会话内执行
`/reload`，或重开 Pi。

### DSH

DSH 的 agent-instructions 插件会读取：

```text
$DSH_HOME/AGENTS.md              # 全局指令；DSH_HOME 未设置时为 ~/.dsh
<workspace>/AGENTS.md            # 工作区指令
```

把同一段规则写入其中一个文件，然后开新会话。会话日志的第一条
`source.kind=agent-instructions` 消息应包含这段文本；也可用
`dsh <profile> --dump-config` 确认 `@deepseek-ai/dsh-agent-instructions` 已启用。

### 什么时候用真正的 Hook？

只有当你想**机械强制**（例如拦截 shell 调用、改写提示词、记录审计事件）时才用 Hook/插件。
对“不要绕过 bacmap”这种操作规程，持久指令 + bacmap 服务端计划门已经足够：即使模型被提示
注入误导，它也没有确认计划或签门的权限。

## 0.2 可安装的指导文件（`bacmap agent`）

角色说明与操作规程由 bacmap 自己提供：MCP server instructions、`bacmap_role_<role>`
prompts 与 `skill://bacmap/<role>/SKILL.md` resources。若客户端不会自动注入，生成
harness 适配文件即可，不要手工复制文本：

```bash
bacmap agent list                              # 支持的 harness
bacmap agent export --harness pi               # 打印指导文件
bacmap agent export --harness hermes --format mcp-config
bacmap agent install --harness pi --scope project
bacmap agent install --harness generic --with-skills
bacmap agent install --harness pi --inline-skills
bacmap agent doctor
```

- `install` 幂等；除非 `--force`，否则拒绝覆盖用户文件；
- `.bacmap-agent.json` 记录生成的文件及其 hash；
- `doctor` 报告缺失/被修改的文件以及 bacmap 版本漂移；
- `--with-skills` 按 2026-11 实测的各 harness 目录约定直写：Hermes
  `~/.hermes/skills/<role>/`（项目级 `./.hermes/skills` 需先 `hermes skills trust`）、
  Pi `~/.pi/agent/skills/<role>/`、OpenCode/generic 走跨 agent 约定
  `~/.agents/skills/<role>/`；DSH/Codex 无经验证的 skills 目录，保持
  `.bacmap/skills/<role>/SKILL.md` 便携副本（DSH 用 MCP resources 或
  `--inline-roles`）；
- `--inline-skills`（或重复 `--inline-role ROLE`）把角色正文追加到指导文件。适用于不会把
  skills/resources 注入模型上下文的 harness（Pi 的 `--print` 模式是已实测例子）；
- MCP 配置片段由 `--format mcp-config` 打印，不会自动写入。

这些文件是**指导，不是权限**。实际权限由 MCP Profile 决定；计划门、写边界与数据分级
始终在服务端（ADR-12/16/21）。

## 1. 启动 MCP 服务器

```bash
# stdio: the harness launches the process
bacmap start mcp

# read-only: no task/plan write tools at all
bacmap start mcp --read-only

# local-trusted (D4): must be enabled in config.toml first
bacmap start mcp --profile local-trusted

# Streamable HTTP: bearer auth is mandatory
export BACMAP_MCP_TOKEN="$(openssl rand -hex 24)"
bacmap start mcp --transport http --host 127.0.0.1 --port 8765
```

`--profile` 在启动时固定；客户端无法自行提升权限。两个 Profile 请使用不同的端口/令牌。

## 2. Profile 与数据分级

| Profile | 工具输出上限 | 开启方式 |
|---|---|---|
| `cloud`（默认） | `[llm.data_policy].cloud_max_data_class`，默认 D1，最多 D2 | 无需配置 |
| `local-trusted` | 最高 D4（序列、元数据、化验结果） | `[mcp] allow_local_trusted = true` **且** `--profile local-trusted` |

```toml
# $BACMAP_HOME/config.toml
[mcp]
allow_local_trusted = true
```

仅当 Harness 对接本地/内网模型时才使用 `local-trusted`。在 `cloud` 下，任务消息会被隐去（它们
可能含有样本 ID/路径），但 `bacmap_task_status` 会返回一个脱敏的 `failure` 块，包含失败类型、
建议修复方式与恢复命令。

## 3. 客户端安装与配置

### 3.0 先安装 Harness（三者任选）

三者都与 bacmap 环境解耦，可以装在系统、npm、pipx 或各自的独立 conda 环境中；它们不需要
看见 `snakemake`、`gside`、`gspec`、`gmlst`。

**Hermes**

```bash
curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash
hermes --version
```

**Pi**（内置 MCP 需 ≥0.99；Node ≥22.19）

```bash
curl -fsSL https://pi.dev/install.sh | sh
# 或：npm install -g --ignore-scripts @earendil-works/pi-coding-agent
pi --version
```

**DeepSeek Harness / DSH**

```bash
npx @deepseek-ai/dsh web
# 默认 Web UI: http://127.0.0.1:3080
```

### 3.1 bacmap 可执行文件的位置

当前官方发布形态是 pixi：

```text
/path/to/bacmap/.pixi/envs/default/bin/bacmap
```

未来提供独立 conda 包后，可安装成：

```bash
conda create -n bacmap -c conda-forge -c bioconda bacmap
```

stdio 客户端不要依赖自己的 PATH。推荐两种接法：

**直接指向可执行文件（pixi / conda env 的 bin）**

```text
command: /opt/conda/envs/bacmap/bin/bacmap
args: ["start", "mcp"]
```

**用 conda run 启动（确保 PATH 来自该环境）**

```text
command: conda
args: ["run", "--no-capture-output", "-n", "bacmap", "bacmap", "start", "mcp"]
```

`--no-capture-output` 很重要：MCP stdio 必须原样透传，不能被 conda 缓冲/包裹。

HTTP 模式则先在 bacmap 环境内启动服务，客户端只需要 URL 和 token，完全不需要生信工具：

```bash
conda run --no-capture-output -n bacmap bacmap start mcp \
  --transport http --host 127.0.0.1 --port 8765
```

### Hermes

配置 MCP 服务器。推荐经 `pixi run`（或 `conda run`）启动：任务执行会调用
`snakemake`，裸的控制台入口脚本不会把环境 bin 放进 harness 的 PATH。

```yaml
# ~/.hermes/config.yaml
mcp_servers:
  bacmap:
    command: pixi
    args: ["run", "--manifest-path", "/path/to/bacmap/pixi.toml", "-e", "default",
           "bacmap", "start", "mcp"]
    # 本地/内网模型且已开启 [mcp] allow_local_trusted = true 时：
    # args: [..., "bacmap", "start", "mcp", "--profile", "local-trusted"]
```

模型凭据属于 Hermes，不属于 bacmap。按 Hermes 自己的方式配置（通常是 `/login`、`/model`
或 `hermes auth add ...`），然后验证：

```bash
hermes mcp test bacmap
hermes
```

连接成功后工具名形如 `mcp__bacmap__bacmap_create_plan`。

### Pi（内置 MCP 需 ≥0.99）

推荐用 CLI 写入配置：

```bash
pi mcp add bacmap -- /path/to/bacmap start mcp
# 本地可信 Profile：
pi mcp add bacmap -- /path/to/bacmap start mcp --profile local-trusted

pi mcp list
pi
```

等价 JSON：

```json
// ~/.pi/agent/mcp.json
{"mcpServers": {"bacmap": {
  "command": "/path/to/bacmap",
  "args": ["start", "mcp"],
  "description": "Local pathogen genomics workstation"
}}}
```

模型用 Pi 的 `/login` 与 `/model` 配置。MCP 状态在会话内用 `/mcp` 查看。

### DeepSeek Harness（DSH）

DSH 通过插件连接 MCP。补丁文件**按 profile 分层**：`$DSH_HOME/profiles/<profile>/cordis.patch.yml`
（如 `~/.dsh/profiles/tui/`、`~/.dsh/profiles/web/`、`~/.dsh/profiles/dsh-tui/` 各一份），
在用哪个 profile 就改哪份；常用几个就都加上。新增条目必须包在 `insert:` 下；裸条目会被当作补丁并跳过。

```yaml
# $DSH_HOME/profiles/<profile>/cordis.patch.yml
# 每个 profile 一份；DSH_HOME 未设置时为 ~/.dsh
- insert:
  - id: mcp-bacmap
    name: '@deepseek-ai/dsh-mcp-client'
    config:
      serverName: bacmap
      transport: stdio
      command: pixi
      args: ['run', '--manifest-path', '/path/to/bacmap/pixi.toml', '-e', 'default',
             'bacmap', 'start', 'mcp']
      # 本地可信 Profile：
      # args: [..., 'bacmap', 'start', 'mcp', '--profile', 'local-trusted']
      failOnStartupError: true
```

检查组合结果：

```bash
dsh <profile> --dump-config
```

启动：

```bash
npx @deepseek-ai/dsh web
```

工具名形如 `mcp__bacmap__bacmap_create_plan`。模型在 DSH 的
**Settings → Models** 中配置。

### Codex

```toml
# ~/.codex/config.toml
[mcp_servers.bacmap]
command = "/path/to/bacmap"
args = ["start", "mcp"]
```

### OpenCode

```json
// opencode.json
{"mcp": {"bacmap": {
  "type": "local",
  "command": ["/path/to/bacmap", "start", "mcp"],
  "enabled": true}}}
```

### Streamable HTTP（推荐多客户端/隔离部署）

先在 bacmap 环境内启动服务：

```bash
export BACMAP_MCP_TOKEN="$(openssl rand -hex 24)"
bacmap start mcp --transport http --host 127.0.0.1 --port 8765
```

Hermes：

```yaml
mcp_servers:
  bacmap:
    url: http://127.0.0.1:8765/mcp
    headers:
      Authorization: "Bearer ${BACMAP_MCP_TOKEN}"
```

Pi：

```bash
pi mcp add bacmap \
  --url http://127.0.0.1:8765/mcp \
  --bearer-token-env-var BACMAP_MCP_TOKEN
pi mcp list
```

DSH：

```yaml
- insert:
  - id: mcp-bacmap
    name: '@deepseek-ai/dsh-mcp-client'
    config:
      serverName: bacmap
      transport: streamable-http
      url: http://127.0.0.1:8765/mcp
      headers:
        Authorization: "Bearer ${BACMAP_MCP_TOKEN}"
      failOnStartupError: true
```

HTTP 模式下 Harness 完全不需要 bacmap 的 conda/pixi 环境；它只访问本机 URL。若要同时提供
`cloud` 与 `local-trusted`，分别启动两个端口并使用不同 token。

## 4. 工具暴露了什么

确切可见性取决于 Profile。先询问服务器：

```json
// call bacmap_capabilities
{
  "server": "bacmap",
  "bacmap_version": "0.1.5",
  "api": "mcp",
  "profile": "cloud",
  "max_data_class": "D1",
  "plannable_task_types": ["analyze", "curate", "mine", "write"],
  "recommended_write_path": "bacmap_create_plan -> user confirms in bacmap CLI/Web -> bacmap_get_plan -> bacmap_task_status",
  "long_running": "explicit task handles (bacmap_task_status polling)",
  "tasks_extension": "unsupported_by_sdk"
}
```

| 分组 | 工具 |
|---|---|
| 能力协商 | `bacmap_capabilities` |
| 读/算 | Profile 上限内的 `bio_*` 工具（例如 `bio_get_result`、`bio_search_samples`、`bio_compare_runs`、序列/计算类工具） |
| 计划 | `bacmap_create_plan`、`bacmap_revise_plan`、`bacmap_get_plan` |
| 计划确认（仅 stdio） | `bacmap_confirm_plan_locally` |
| 任务 | `bacmap_submit_task`、`bacmap_task_status`、`bacmap_task_result`、`bacmap_task_cancel` |
| 记录（仅 local-trusted） | `bacmap_record_data` |
| 说明 | prompts `bacmap_role_<role>`、资源 `skill://bacmap/<role>/SKILL.md`（带 `sha256` 元数据） |

`bacmap_submit_task` 是 `analyze`/`curate` 的兼容入口；推荐的写入路径是计划。
`bacmap_task_cancel` 只对本客户端直接提交、或通过其自身计划提交的任务有效。

## 5. 计划 → 确认 → 运行循环

### 5.1 创建

```json
// bacmap_create_plan arguments
{
  "tasks": [
    {"task_type": "analyze", "fasta_dir": "/data/run42", "species": "VPA"}
  ],
  "rationale": "batch 42 assembled genomes"
}
```

响应（有删节）：

```json
{
  "plan_id": "9a3f2c1b7d4e4f60",
  "version": 1,
  "state": "awaiting_confirmation",
  "plan_hash": "c1d2e3f4a5b6...",
  "inputs": {"/data/run42": "files-v1:sha256:..."},
  "confirm_url": "http://127.0.0.1:8800/plans/9a3f2c1b7d4e4f60?version=1",
  "next_step": "Ask the user to review and confirm ... You cannot confirm it."
}
```

可计划的任务形态：

```json
{"task_type": "analyze", "samples": ["SAM-001"]}
{"task_type": "analyze", "fasta_dir": "/abs/dir"}
{"task_type": "analyze", "fastq_dir": "/abs/dir", "species": "SAL"}
{"task_type": "curate", "scope": {"pathogen": "Salmonella"}}
{"task_type": "mine", "objective": "...", "script": "print('hi')", "input_paths": ["/abs/data"]}
{"task_type": "write", "objective": "...", "draft": "text [PMID:12345678]", "known_citations": []}
```

一个计划最多包含 10 个任务。输入路径在创建时生成指纹，并在确认时重新校验；发生变化即为冲突。

### 5.2 确认（人或服务端预授权）

三种渠道：

1. **Web 链接**（默认）：`confirm_url` → 计划页面 → **Confirm and submit**。
2. **本机对话框**（stdio）：让智能体调用 `bacmap_confirm_plan_locally`；zenity/kdialog
   对话框会显示计划 ID/版本/哈希；点击即确认（`actor=local-dialog`）。
3. **预授权**（管理员，可选）：默认仅限已登记样本的 analyze 计划；也可通过
   `task_types` / `allow_directory_ingestion` / `allow_scripts` / `allow_drafts`
   显式放宽到自动迭代（`actor=policy:auto-confirm`）。

CLI 备用方式：

```bash
bacmap plan list
bacmap plan show 9a3f2c1b7d4e4f60
bacmap plan confirm 9a3f2c1b7d4e4f60 --version 1 --hash c1d2e3f4a5b6
bacmap plan reject 9a3f2c1b7d4e4f60 --version 1 --reason "wrong sample"
```

不变式：

- 确认绑定 `(plan_id, version, plan_hash)`；修订会使旧版本失效；
- 一次性：重复确认只会提交同一组确定性任务 ID 一次；
- 模型无法确认；MCP elicitation 与客户端工具审批不被接受；
- 计划按创建它的 MCP 客户端隔离：其他客户端调用 `bacmap_get_plan` / `bacmap_revise_plan`
  会得到 `forbidden`。

### 5.3 轮询

```json
// bacmap_get_plan
{"plan_id": "9a3f2c1b7d4e4f60", "version": 1}
// → state=submitted, task_ids=["..."]
```

```json
// bacmap_task_status
{"task_id": "..."}
// → {"state": "running", "current_step": "pipeline", ...}
```

确认之后，任务以 `submitted_by="<confirmer> via plan <id>@v1"` 提交。

## 6. 开放路径审阅

`mine` 与 `write` 计划在确认时会展示**完整的**脚本/草稿；它们是计划哈希的一部分。确认前请先阅读。
`mine` 在沙箱内离线运行；产物仍需通过挖掘门和人的签字。

## 7. 数据边界与部署

MCP Profile 只保护流经 MCP 的数据。Harness 自带 Shell/文件工具，因此对于使用云端模型的 Harness：

1. 用专用的操作系统账户运行 bacmap，`BACMAP_HOME` 权限设为 `0700`；
2. 以该账户运行 `bacmap start mcp --transport http`（以及 `bacmap start web`），只绑定回环地址；
3. 只把 MCP 的 URL/令牌交给 Harness，绝不给 Web 令牌。

bacmap 无法控制被复制进 Harness 工作区的文件，也无法控制模型提供方如何处理它收到的内容。

## 8. 故障排查

| 现象 | 检查项 |
|---|---|
| Harness 看不到任何工具 | `bacmap_capabilities`；确认进程正在运行，且 Profile 符合预期 |
| D3/D4 相关工具报“tool not found” | 受 cloud Profile 上限限制；改用 `local-trusted` 并配合本地模型 |
| `bacmap_get_plan` 返回 `forbidden` | 该计划属于另一个 MCP 客户端；请使用同一个客户端，或新建计划 |
| `confirm_url` 无法访问 | 检查 `BACMAP_WEB_URL` / 启动 `bacmap start web`；或改用 CLI 确认 |
| 确认冲突 | 输入在创建计划之后发生了变化；请让智能体修订计划并重新确认 |
| 任务一直停在 `awaiting_approval` | 必须由人签署该门；智能体无法代签 |
| `sandbox unavailable` | 安装 Apptainer/Podman；直通模式仅限开发 |
| 任务失败信息被脱敏 | 受 cloud Profile 限制；改用 `local-trusted`，或在本地查看 `bacmap task show` |

## 9. 已验证的客户端（2026-11）

| Harness | 版本 | 发现 | 计划往返 |
|---|---|---|---|
| Hermes | 0.23.0 | `hermes mcp test bacmap` | 创建 → 人工确认 → 读回 `submitted` + task ID |
| Pi | 1.4.0（内置 MCP ≥0.99） | `pi mcp list` | 同上 |
| DSH | 0.2.2-rc.1 | 插件会拉起 MCP 服务器 | MCP 插件层已验证；浏览器对话层待人工实测 |

2026-11 真实数据实测（8 株副溶血弧菌组装，Hermes 无头 `-z` + CLI 确认）：analyze 计划
确认后执行至 `succeeded`；只读工具汇总各株 MLST/AMR；`mine` 计划在 rootless Podman
沙箱执行、产出 `mine_report.json` 并停在挖掘门，人工签字（`task approve`）后
`succeeded`。期间 agent 在 cloud Profile 下自纠 `input_data_class` D3→D2，且从未
尝试自行确认计划。

上游变通：

- **Hermes 使用全新的 `HERMES_HOME`**：`python-olm` 在 CMake ≥4 下构建失败；首次启动时设置
  `CMAKE_POLICY_VERSION_MINIMUM=3.5`。该隔离运行时在你用
  `hermes auth add zai --type api-key --api-key <key>` 添加之前，不会读取
  `ZAI_API_KEY`/`GLM_API_KEY`。
- **仓库移动后的 pixi 环境**：仓库改名/移动后，conda 入口脚本（`snakemake`、`bedtools`
  等）的 shebang 仍指向旧绝对路径（`bad interpreter`）。`pixi clean --environment
  default && pixi install` 重建即可。MCP 经 `pixi run` 启动（见 §3）也能保证任务执行时
  环境 bin 在 PATH。
- **DSH**：新增条目必须包在 `insert:` 下；裸条目会被当作补丁并跳过。Web UI 首次启动打印
  带 `?token=…` 的 URL；浏览器之外的 curl 会撞上 browser-trust 限制，属预期行为。
- **Pi**：如果看不到 MCP 工具，请检查 `pi --version`（≥0.99）。

自动化测试套件用真实的 MCP 客户端覆盖了 stdio 计划往返；上表记录的是使用智谱编码套餐端点的、
由模型驱动的人工检查。

## 10. 把 bacmap 控制台嵌入 Harness（PLAN #20）

bacmap Web 与 Harness 分窗口使用没问题，但有些用户希望只开一个窗口。各 Harness 的机制不同：

### DSH：侧边栏 bundle（已实现）

`tools/dsh-bacmap-console` 是 DSH bundle，把 bacmap Web 控制台嵌入 DSH 侧边栏。它在
`/bacmap/console/` 下反向代理 `http://127.0.0.1:8800`（移除 `X-Frame-Options` 并把 CSP
`frame-ancestors` 放宽到 `'self'`），同时设置 SPA router base、为运行时报告/API URL 加挂载
前缀。控制台与内嵌的完整报告都能在 DSH iframe 内显示；需要时也可直接打开 `/bacmap/console/`。

```bash
# bundle 已在 bacmap 仓库内；链接到 DSH profile：
ln -s /path/to/bacmap/tools/dsh-bacmap-console ~/.dsh/profiles/web/node_modules/@local/
```

### Hermes：Desktop 插件面板

Hermes Desktop 支持用插件包内的 `desktop/plugin.js` 注册自定义侧边栏面板。bacmap 面板需要：

1. 在 `plugin.yaml` 注册 `bacmap_console` 面板；
2. 在 `desktop/plugin.js` 创建指向 `http://127.0.0.1:8800` 的 `<iframe>`（可能需要调整 CORS，
   或使用 Hermes 内置代理）；
3. 面板会与 Hermes 内置面板并列显示。

这需要 Hermes Desktop（CLI/TUI 版本不支持）。

### Pi：glimpseui WebView 窗口

Pi 扩展可用 [`glimpse`](https://github.com/hazat/glimpse) 原生 WebView 打开 bacmap Web 浮窗，
并支持双向 JSON 通信；安装：`pi install npm:glimpseui`。示例 TypeScript 代码见英文版。

### 远程部署（bacmap 在服务器、智能体在本机）

1. **SSH 隧道**（最简单）：`ssh -L 8800:localhost:8800 server`，Web 与 MCP 都经 localhost 访问；
2. **带令牌的直连 HTTP**：在局域网暴露 `bacmap start web`（设置 `BACMAP_WEB_TOKEN`），
   Harness 的 MCP 配置指向 `http://server:8765/mcp` 并携带令牌；
3. **VPN/WireGuard**：整网可达，无需额外配置。

DSH 反向代理同样适用于远程 bacmap——把代理目标从 `localhost:8800` 改成服务器地址即可。
