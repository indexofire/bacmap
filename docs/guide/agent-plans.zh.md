# 智能体与计划

自 v1.5 起（ADR-21），对话交互位于外部智能体 Harness 中。Harness 只经 MCP 访问 bacmap；
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

## 1. 启动 MCP 服务器

```bash
# stdio: the harness launches the process
bacmap mcp

# read-only: no task/plan write tools at all
bacmap mcp --read-only

# local-trusted (D4): must be enabled in config.toml first
bacmap mcp --profile local-trusted

# Streamable HTTP: bearer auth is mandatory
export BACMAP_MCP_TOKEN="$(openssl rand -hex 24)"
bacmap mcp --transport http --host 127.0.0.1 --port 8765
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

## 3. 客户端配置

把 `/path/to/bacmap` 换成你的可执行文件
（`/path/to/bacmap/.pixi/envs/default/bin/bacmap`）。

### Hermes

```yaml
# ~/.hermes/config.yaml
mcp_servers:
  bacmap:
    command: /path/to/bacmap
    args: ["mcp"]                 # add "--profile", "local-trusted" for local models
```

```bash
hermes mcp test bacmap
```

### Pi（内置 MCP 需 ≥0.99）

```json
// ~/.pi/agent/mcp.json
{"mcpServers": {"bacmap": {
  "command": "/path/to/bacmap", "args": ["mcp"]}}}
```

```bash
pi mcp list
```

### DeepSeek Harness（DSH）

新增条目必须包在 `insert:` 下；裸条目会被当作补丁并跳过。

```yaml
# $DSH_HOME/cordis.patch.yml
- insert:
  - id: mcp-bacmap
    name: '@deepseek-ai/dsh-mcp-client'
    config:
      serverName: bacmap
      transport: stdio
      command: /path/to/bacmap
      args: ['mcp']
      failOnStartupError: true
```

### Codex

```toml
# ~/.codex/config.toml
[mcp_servers.bacmap]
command = "/path/to/bacmap"
args = ["mcp"]
```

### OpenCode

```json
// opencode.json
{"mcp": {"bacmap": {
  "type": "local",
  "command": ["/path/to/bacmap", "mcp"],
  "enabled": true}}}
```

### Streamable HTTP

让客户端指向 `http://127.0.0.1:8765/mcp` 并发送：

```http
Authorization: Bearer <BACMAP_MCP_TOKEN>
```

Hermes 使用 `url` + `headers`；Pi 支持
`pi mcp add bacmap --url … --bearer-token-env-var BACMAP_MCP_TOKEN`；DSH 使用
`transport: streamable-http`。

## 4. 工具暴露了什么

确切可见性取决于 Profile。先询问服务器：

```json
// call bacmap_capabilities
{
  "server": "bacmap",
  "bacmap_version": "0.1.2",
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

### 5.2 确认（仅限人）

三种渠道：

1. **Web 链接**（默认）：`confirm_url` → 计划页面 → **Confirm and submit**。
2. **本机对话框**（stdio）：让智能体调用 `bacmap_confirm_plan_locally`；zenity/kdialog
   对话框会显示计划 ID/版本/哈希；点击即确认（`actor=local-dialog`）。
3. **预授权**（管理员，可选）：仅限 analyze 计划，且只针对已登记样本、样本数不超过
   `max_samples`；`actor=policy:auto-confirm`。

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
2. 以该账户运行 `bacmap mcp --transport http`（以及 `bacmap web`），只绑定回环地址；
3. 只把 MCP 的 URL/令牌交给 Harness，绝不给 Web 令牌。

bacmap 无法控制被复制进 Harness 工作区的文件，也无法控制模型提供方如何处理它收到的内容。

## 8. 故障排查

| 现象 | 检查项 |
|---|---|
| Harness 看不到任何工具 | `bacmap_capabilities`；确认进程正在运行，且 Profile 符合预期 |
| D3/D4 相关工具报“tool not found” | 受 cloud Profile 上限限制；改用 `local-trusted` 并配合本地模型 |
| `bacmap_get_plan` 返回 `forbidden` | 该计划属于另一个 MCP 客户端；请使用同一个客户端，或新建计划 |
| `confirm_url` 无法访问 | 检查 `BACMAP_WEB_URL` / 启动 `bacmap web`；或改用 CLI 确认 |
| 确认冲突 | 输入在创建计划之后发生了变化；请让智能体修订计划并重新确认 |
| 任务一直停在 `awaiting_approval` | 必须由人签署该门；智能体无法代签 |
| `sandbox unavailable` | 安装 Apptainer/Podman；直通模式仅限开发 |
| 任务失败信息被脱敏 | 受 cloud Profile 限制；改用 `local-trusted`，或在本地查看 `bacmap task show` |

## 9. 已验证的客户端（2026-10）

| Harness | 版本 | 发现 | 计划往返 |
|---|---|---|---|
| Hermes | 0.21.3（以及 0.17.0+52045） | `hermes mcp test bacmap` | 创建 → 人工确认 → 读回 `submitted` + task ID |
| Pi | 1.4.0（内置 MCP ≥0.99） | `pi mcp list` | 同上 |
| DSH | 0.2.1-rc.2 | 插件会拉起 MCP 服务器 | 同上 |

上游变通：

- **Hermes 使用全新的 `HERMES_HOME`**：`python-olm` 在 CMake ≥4 下构建失败；首次启动时设置
  `CMAKE_POLICY_VERSION_MINIMUM=3.5`。该隔离运行时在你用
  `hermes auth add zai --type api-key --api-key <key>` 添加之前，不会读取
  `ZAI_API_KEY`/`GLM_API_KEY`。
- **DSH**：新增条目必须包在 `insert:` 下；裸条目会被当作补丁并跳过。
- **Pi**：如果看不到 MCP 工具，请检查 `pi --version`（≥0.99）。

自动化测试套件用真实的 MCP 客户端覆盖了 stdio 计划往返；上表记录的是使用智谱编码套餐端点的、
由模型驱动的人工检查。
