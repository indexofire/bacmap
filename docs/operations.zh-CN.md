[English](operations.md) | **简体中文**

# 运维指南

上线后的日常事务：体检、备份、恢复、事件保留、schema 迁移与升级。全部在单工作站上完成，
不需要常驻服务或守护进程。

## 1. 体检：`bacmap doctor`

```bash
bacmap doctor                 # 人读
bacmap doctor --json          # 机器读（CI / 监控）
```

| 检查项 | 含义 | 不绿时怎么办 |
|---|---|---|
| `home` | `BACMAP_HOME` 存在且可写 | 修正属主（`chown`），或用 `--home` 指向正确目录 |
| `database` | `tasks.sqlite` schema 版本与代码一致 | 偏旧：任意命令启动即自动迁移（迁移前自动备份）。比代码新：你降级了——换回新版本 |
| `sandbox` | 沙箱后端（`apptainer`/`podman`）；`passthrough` 表示**没有隔离** | 跑 `mine` 前先装 Apptainer 或 Podman（安装指南 §6） |
| `llm` | 配置的 LLM 端点可达性 | 确定性功能照常可用（C3）；按配置指南 §2 修正端点 |
| `disk` | 可用空间 ≥ 1 GB | 清理空间或迁移 `BACMAP_HOME` |
| `tools` | `PATH` 上的 `gside`/`gapit`/`gmlst`/`snakemake` | 在 `pixi shell` 中运行，或重装环境 |

任一项为 `fail` 时退出码为 `1`（`warn` 不影响退出码）。

## 2. 备份：`bacmap backup`

```bash
bacmap backup --out /backup/bacmap-2026-10-26.zip
bacmap backup --out /backup/full.zip --with-results   # 连 results/ 一起（体积大）
```

包含内容与方式：

- `config.toml`、`refs/manifest.json`；
- 所有 SQLite 库（`tasks`、`runs`、`gom`、`baseline`、`data/bacmap`、`data/knowledge`）——
  用 SQLite **backup API** 取一致快照，任务运行中也能安全备份；
- `runs/*/run_manifest.json`（证据链的落盘部分，ADR-18）。

`results/`（报告与逐样本产物）与 `workspaces/` 默认**不**包含；需要完整归档时加 `--with-results`。

## 3. 恢复：`bacmap restore`

```bash
bacmap restore --from /backup/bacmap-2026-10-26.zip --home /srv/bacmap
bacmap restore --from ... --home /srv/bacmap --force   # 目标已有数据
```

- 目标非空时默认拒绝，除非 `--force`（且绝不删除归档之外的文件）；
- 拒绝含 `..` 或绝对路径的条目（zip-slip 防护）；
- 对每个恢复的库执行 `PRAGMA integrity_check`，失败即中止并给出明确信息；
- 恢复后跑一次 `bacmap doctor`；归档比代码旧时迁移会自动执行。

## 4. 事件保留：`bacmap events prune`

领域事件（`tasks.sqlite.events`）记录计划与任务的转换、步骤与审批。它是协作审计轨迹，
**不是**真相来源（任务/计划表才是）。

```bash
bacmap events prune --days 180     # 保留半年，删除更早
bacmap events prune --days 0       # 全部删除（通常不建议）
```

保留期按本单位审计政策决定。门评估、运行记录与审批在各自的表里，**不受**该命令影响。

## 5. 结果目录迁移（v1.8.1）

结果写入 `results/runs/<task_id>/<sample>/`；扁平路径是指向最新运行的链接。

```bash
bacmap results migrate --dry-run     # 列出旧扁平目录（样本 + snp/cgmlst）
bacmap results migrate               # 搬入 runs/legacy-<name>/ 并建立链接
```

升级后执行一次。不会删除数据：全部搬入运行目录，旧路径变成链接。若之后又出现真实的
`results/<sample>` 目录，重链会拒绝而不是覆盖。

## 6. schema 迁移

- 每个库都有编号迁移清单与 `PRAGMA user_version`；见 `bacmap/store/migrations.py` 与各按文件清单
  （`tasks`、`runs`、`baseline`、`gom`、`data`、`knowledge`）。
- 启动时自动迁移：单事务执行，迁移前把文件复制为 `<db>.bak-v<N>`。
- 库版本高于代码时拒绝打开，而不是静默降级。
- 迁移只追加；已发布的迁移不得修改。

## 6. 升级清单

1. `bacmap doctor`（记录当前状态）。
2. `bacmap backup --out …`（见 §2）。
3. 停止运行中的任务或等其结束；`bacmap task ls` 查看非终态任务。
4. 更新环境（`pixi install`）并重启 `bacmap web` / `bacmap mcp`。
5. 再跑 `bacmap doctor`；确认 `database` 显示新版本。
6. 冒烟：`bacmap overview`、`bacmap run ls`、一个小 `analyze` 或 `bacmap record`。

回滚：用第 2 步的备份 `bacmap restore --force`。注意被新版本迁移过的库无法被旧版本打开
（版本检查会拒绝）——应恢复备份，而不是原地降级。

## 7. 运行隔离（推荐）

MCP Profile 只保护经过 MCP 的数据，挡不住 Harness 自己的 Shell。使用外部 Harness 时：

- bacmap 以独立系统账户运行，`BACMAP_HOME` 权限 `0700`；
- `bacmap web` 与 `bacmap mcp --transport http` 以该账户运行，绑定 `127.0.0.1`；
- Harness 只拿到 MCP 地址与 token，绝不给 Web 令牌。

原因与残余风险见[智能体 Harness 指南](harnesses.zh-CN.md) §4。
