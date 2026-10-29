# 智能体 Harness（Hermes · Pi · DeepSeek Harness）

v1.5 起（冻结 ADR-21），与 bacmap 的对话交互在外部智能体 Harness 的原生界面中进行。Harness 只经
MCP 访问 bacmap；bacmap 保留确定性管线、门与**可信确认面**：智能体提出的计划，只有在人通过
`bacmap plan confirm` 或 Web `/plans` 页面确认该确切版本后才会执行。

Harness 不是必需的。没有 Harness 时，CLI 与 Web 控制台照常提供全部确定性功能。

## 1. Harness 经 MCP 能做什么

| 工具 | 用途 |
|---|---|
| `bio_*` 读/算工具 | 查询结果、运行单步工具，按实例 Profile 裁剪 |
| `bacmap_create_plan` / `bacmap_revise_plan` / `bacmap_get_plan` | 提出类型化的 analyze/curate 任务；查看计划状态，确认后取得 `task_ids` |
| `bacmap_task_status` / `bacmap_task_result` / `bacmap_task_cancel` | 跟踪任务；结果为摘要（运行 ID、门结论）；取消仅限本客户端提交的任务 |
| `bacmap_record_data` | 经 `record` 任务录入元数据/化验/知识库（仅 local-trusted） |
| `bacmap_confirm_plan_locally` | stdio 下弹本机确认对话框；人的点击即确认 |
| 计划归属 | `bacmap_get_plan` / `bacmap_revise_plan` 仅对本客户端创建的计划有效 |
| `bacmap_capabilities` | 服务版本、Profile 与数据级别上限、可计划任务类型、推荐写入路径、长任务机制 |
| `bacmap_submit_task` | 直接提交的兼容入口 |
| prompts `bacmap_role_<角色>` 与资源 `skill://bacmap/<角色>/SKILL.md` | 领域说明书；每个资源的元数据带 `sha256` 摘要 |

Harness 不能确认计划，也不能签署审批。MCP elicitation 与 Harness 自身的工具审批由客户端或模型
应答，bacmap 不把它们当作确认。

## 2. Profile

每个 bacmap MCP 实例启动时绑定一个 Profile（见[使用指南](usage.zh.md)）：

- `cloud`（默认）：输出级别不超过 `[llm.data_policy].cloud_max_data_class` 的工具。任务消息不回传，
  任务结果只给门结论计数——它们可能点名单株。
- `local-trusted`：全部读/算工具，至 D4。管理员在 `config.toml` 中设置
  `[mcp] allow_local_trusted = true` 开启。仅在 Harness 使用本地或内网模型时使用。

## 3. 客户端配置

把 `/path/to/bacmap` 换成 pixi 环境中的 `bacmap` 可执行文件（`.pixi/envs/default/bin/bacmap`）。

### Hermes（已验证 v0.21.3）

```yaml
# ~/.hermes/config.yaml
mcp_servers:
  bacmap:
    command: /path/to/bacmap
    args: ["mcp"]                    # 本地模型时追加 "--profile", "local-trusted"
```

不开对话即可检查连接：`hermes mcp test bacmap`。

### Pi（已验证 v1.1.0；内置 MCP 需 Pi ≥ 0.99）

```json
// ~/.pi/agent/mcp.json
{ "mcpServers": { "bacmap": { "command": "/path/to/bacmap", "args": ["mcp"] } } }
```

用 `pi mcp list` 检查。Pi 默认启用自带的 `bash`、`read`、`write`、`edit` 工具，见 §4。

### DeepSeek Harness（已验证 v0.2.1-rc.2）

DSH 由补丁层组合插件。新增条目必须包在 `insert:` 下；裸条目会被当作对已有 ID 的补丁，
并以 `patch: entry ... not found` 跳过。

```yaml
# $DSH_HOME/cordis.patch.yml（全部 profile）或 $DSH_HOME/profiles/<profile>/cordis.patch.yml
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

`dsh <profile> --dump-config` 可确认条目已组合进去。工具名形如 `mcp__bacmap__<tool>`。

### Streamable HTTP（任意 Harness）

```bash
export BACMAP_MCP_TOKEN="$(openssl rand -hex 24)"
bacmap mcp --transport http --host 127.0.0.1 --port 8765            # cloud Profile
```

让 Harness 指向 `http://127.0.0.1:8765/mcp` 并带 `Authorization: Bearer <token>`
（Hermes：`url` + `headers`；Pi：`pi mcp add bacmap --url … --bearer-token-env-var BACMAP_MCP_TOKEN`；
DSH：`transport: streamable-http`、`url`、`headers`）。需要同时提供 `local-trusted` 时，以另一端口、
另一 token 再起一个实例。

## 4. 数据边界：按操作系统账户隔离 bacmap

MCP Profile 只保护经过 MCP 的数据。所有受支持的 Harness 都带 Shell 与文件工具，使用云端模型的
Harness 会把这些工具读到的内容发出去。因此推荐按账户把两者隔开：

1. bacmap 以独立系统账户运行（如 `bacmap`），`BACMAP_HOME=/srv/bacmap`，`chmod 700 /srv/bacmap`。
2. 以该账户启动 `bacmap mcp --transport http`（以及 `bacmap web`），例如用 systemd 服务，绑定 `127.0.0.1`。
3. Harness 以你的普通用户运行，只给它 MCP 地址与 token，不给 Web 令牌。

这样 Harness 的 Shell 无法直接读取序列与元数据。用户自己复制进 Harness 工作目录的数据、模型提供方
如何处理收到的内容，bacmap 无法控制；该部署降低而不是消除这些风险。

**本地模型与资源仲裁（ADR-17）。** Harness 若与 bacmap 共用同一个本机 Strata，其请求不经 bacmap 的
串行队列；内存密集的管线步骤卸载模型期间，Harness 会话会卡住或失败。Harness 最好使用独立推理主机，
或使用云端端点并配合 `cloud` Profile。

## 5. 验证记录

实测模型 `glm-5.3`（Zhipu 编码套餐端点 `https://open.bigmodel.cn/api/coding/paas/v4`）。
三个 Harness 各跑同一段对话两轮：第一轮调用 `bacmap_create_plan` 并报告 `plan_id`、`version`、`state`；
人在 CLI 确认该确切版本；第二轮调用 `bacmap_get_plan` 与 `bacmap_task_status`，报告 `submitted` 与 task ID。

| Harness | 版本 | MCP 发现 | 完整计划往返 | 说明 |
|---|---|---|---|---|
| Hermes | 0.17.0+52045（2026-10-25） | ✓ 按下述两个变通后全链路通过 | ✓ 创建 → 确认 → 读回 `submitted` + task ID | `provider: zai` + `GLM_BASE_URL` 指向编码套餐端点 |
| Hermes | 0.21.3（2026-10-25，早前记录） | ✓ `hermes mcp test`，`cloud` 下工具可发现 | ✓ 同上 | 该版本尚未改为按 data root 隔离运行时 |
| Pi | 1.4.0（2026-10-25） | ✓ `pi mcp list` | ✓ 同上 | `models.json` 自定义 provider，`api: openai-completions`；1.4 升级后复验 |
| DSH | 0.2.1-rc.2（2026-10-25） | ✓ 插件启动时拉起 bacmap MCP 服务 | ✓ 同上 | 需补丁**已有**的 `llm-pi-ai` 条目；再加一个 `dsh-llm-pi-ai` 条目会报 `provider "amazon-bedrock" is already declared` |

**Hermes 0.17.0+52045 的两个变通（均为上游行为，与 bacmap 无关）：**

1. **全新** `HERMES_HOME` 会自行引导运行时，`python-olm 3.2.16` 因 CMake ≥ 4 拒绝
   `cmake_minimum_required` < 3.5 而构建失败。首次启动时设 `CMAKE_POLICY_VERSION_MINIMUM=3.5`
   （或安装不带 `matrix` extra 的构建）。
2. 该隔离运行时**不读环境变量中的** `ZAI_API_KEY`/`GLM_API_KEY`，需先写入它自己的凭据库：
   `hermes auth add zai --type api-key --api-key <key>`（随后 `hermes auth status zai` 应显示 logged in）。

复现脚本为 `dev/harness-e2e.sh`（仅本地，需环境中的模型 key，不把 key 写盘）。计划往返在测试套件与发布
冒烟中另有真实 MCP stdio 客户端覆盖（不需要模型）。
