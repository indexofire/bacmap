# 故障排查

先看任务消息与 `bacmap doctor`；大多数故障都归于少数几类。

## 1. 首要命令

```bash
bacmap doctor
bacmap task list
bacmap task show <task_id>
bacmap task show <task_id> --json | jq .state,.current_step,.message
```

对于失败的流水线，MCP 客户端可以用日志路径或 stderr 文本调用 `bio_diagnose`；
`bacmap_task_status` 返回的脱敏 `failure` 块使用同一个分类器。

日志：

```text
$BACMAP_HOME/workflow_state/log/*.snakemake.log
$BACMAP_HOME/workspaces/<task_id>/      # mine 的 stdout/stderr 与 context.json
```

## 2. 提交与校验

| 症状 | 原因 / 修复 |
|---|---|
| `非法样本 ID` / invalid sample id | ID 超出 `A-Za-z0-9._-`，或使用了全角逗号；请用 ASCII `,` 或换行 |
| `analyze requires samples or fasta_dir/fastq_dir` | 只提供一种输入形式 |
| `directory must be an absolute path` | 计划要求输入路径为绝对路径 |
| `dataset_id collision` | 同一 ID 内容不同；重命名为 `<isolate>__<platform>__<date>` |
| `scope 必须是 JSON 对象` | 传入 `{"pathogen":"Salmonella"}`，而不是数组 |
| `task_type 'mine' is not submittable via MCP` | 使用 `bacmap_create_plan`；开放路径只支持计划 |

## 3. 确认与计划

| 症状 | 原因 / 修复 |
|---|---|
| `plan hash mismatch` | 你确认的是另一个版本；运行 `bacmap plan show` 并使用当前哈希 |
| `input ... changed since the plan was created` | 计划创建后输入发生了变化；修订计划并重新确认 |
| `plan ... is submitted; cannot revise` | 已提交；请创建新计划 |
| `bacmap_get_plan` 上的 `forbidden` | 计划属于另一个 MCP 客户端；请使用同一客户端 |
| `confirm_url` 不可达 | 启动 `bacmap web`，或设置 `BACMAP_WEB_URL`；CLI 确认仍然可用 |
| 本地对话框无反应 | 仅限带 GUI（zenity/kdialog）的 stdio 会话；否则请用 Web 链接 |
| 自动确认从未触发 | 策略已禁用、任务非 analyze、目录摄取，或 `max_samples` 格式错误（故障安全） |

## 4. 流水线故障

`bio_diagnose` 会对 Snakemake stderr 进行分类。经过脱敏的云端响应也会给出类别名。

| 类别 | 含义 | 修复 |
|---|---|---|
| `missing_input` | FASTQ/FASTA 路径错误或文件不存在 | 检查 `samples.tsv` 与 `gs/`；路径相对于 `BACMAP_HOME` |
| `missing_tool` | 外部工具不在 PATH 上 | 在 pixi 环境中运行；`pixi install` |
| `missing_db` | BLAST/参考库索引缺失 | 重建数据库或恢复 `refs/` |
| `lock` | 中断的运行留下的 `.snakemake` 锁 | `snakemake --unlock -d "$BACMAP_HOME/workflows/bacmap"` |
| `oom` | 内存不足 | 降低 cores/threads；避免同时运行本地 LLM |
| `disk_full` | 空间不足 | 释放空间；有意清理旧的运行目录 |
| `sandbox_unavailable` | 没有 Apptainer/Podman | 安装一个；passthrough 仅限开发 |
| `timeout` | 流水线长时间运行/阻塞 | 检查进程、增加超时、解锁 |
| `permission` | 文件权限/属主 | 对受影响的目录树执行 `chmod -R u+rwX` |

`snakemake_v8` 诊断属于历史遗留；当前锁定版本为 Snakemake 9（见 `pixi.lock`）。

## 5. 沙箱与 mine

| 症状 | 修复 |
|---|---|
| `no apptainer/podman on PATH` | 安装 Podman（`pixi global install podman`）或 Apptainer |
| `image pull failed` | 在联网机器上预先拉取沙箱镜像，或使用本地 SIF |
| `input path not found` | `input_paths` 必须在创建计划时存在；登记文件/目录，而不是通配符 |
| 校验时 `dataset ... missing` | 原始文件已移动；重新登记正确路径 |
| 脚本没有网络 | 设计如此；请事先下载数据并登记 |
| 产物未出现在报告中 | 挖掘门要求人工签名 |

## 6. Web、API 与鉴权

| 症状 | 修复 |
|---|---|
| 浏览器中出现 401（bearer 模式） | 浏览器无法设置 `Authorization`；请用 SSH 隧道或 `BACMAP_WEB_AUTH=cookie` |
| 403 CSRF | 在 cookie 模式下发送与 `bacmap_csrf` cookie 相同的 `X-CSRF-Token` |
| 审批时 409 | 任务已处于终态，或不在 `awaiting_approval`；请刷新 |
| 报告 404 | 先运行分析/报告；检查样本 ID |
| 登录时 CORS/Origin 错误 | 请求的 Origin 必须与 Host 一致；请使用相同主机名 |
| `/api/v1` token 泄露给 Harness | 轮换 `BACMAP_WEB_TOKEN`；Harness 必须使用 MCP |

## 7. MCP 客户端

| 症状 | 修复 |
|---|---|
| 未发现任何工具 | 检查 `bacmap mcp` 能否启动；`bacmap_capabilities`；profile 参数 |
| HTTP 401 | `Authorization: Bearer $BACMAP_MCP_TOKEN`；token 必须与服务端环境一致 |
| `local-trusted` 拒绝启动 | 设置 `[mcp] allow_local_trusted = true`（布尔值） |
| D3/D4 工具缺失 | 你处于 `cloud`；请使用本地模型 + `local-trusted` |
| 任务消息为空 | cloud profile 脱敏；使用 `failure` 块或本地 profile |
| Hermes 全新 home 失败 | 设置 `CMAKE_POLICY_VERSION_MINIMUM=3.5`，然后 `hermes auth add zai` |
| DSH 条目被忽略 | 用 `insert:` 包裹新条目 |

## 8. 数据与证据

| 症状 | 修复 |
|---|---|
| 升级后结果缺失 | 运行 `bacmap results migrate`；检查符号链接目标 |
| 同一样本的两次运行结果不同 | `bacmap run compare <a> <b>`；检查 `NOT_REPRODUCIBLE` |
| 基线排除了某个菌株 | 查看 `excluded` 原因：物种/QC/元数据/重复/代表株 |
| 引用门拒绝 | 批准知识条目（`knowledge-approve`）或修正引用 |
| 知识审批被覆盖？ | 设计上不可能；审批是一次性的 |
| 恢复后任务卡在 `running` | 确认备份中包含 `dbos.sqlite`；否则重新提交 |

## 9. 获取帮助

- `bacmap doctor --json` 获取机器可读的快照。
- `bacmap overview` 查看版本、路径、策略、沙箱与端点。
- `bacmap run show` / `gom show` 查看证据。
- 外部智能体可以调用 `bacmap_capabilities`、`bacmap_task_status`（脱敏）与
  `bio_diagnose`；它们不能替你签名或确认。
