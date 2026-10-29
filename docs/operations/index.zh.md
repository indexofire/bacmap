# 运维

单工作站上的日常事务：体检、备份/恢复、迁移、升级与保留。不需要守护进程或服务管理器。

本节：[排障](troubleshooting.zh.md) · [安全与数据分级](../concepts/security.zh.md) · [开发](../development/index.zh.md)。

## 1. 体检

```bash
bacmap doctor
bacmap doctor --json
```

| 检查项 | 验证内容 | 失败时怎么办 |
|---|---|---|
| `home` | `BACMAP_HOME` 存在且可写 | 修正属主，或传入 `--home` |
| `database` | `tasks.sqlite` 的 schema 版本与代码一致 | 偏旧：启动任意命令即迁移（会自动备份）；偏新：你降级了——使用更新的构建 |
| `sandbox` | Apptainer/Podman 可用性 | 跑 `mine` 前先装一个；`passthrough` 表示没有隔离 |
| `llm` | 配置的端点是否可达 | 确定性功能仍可正常工作（C3） |
| `disk` | 可用空间 ≥1 GB | 释放空间或迁移 `BACMAP_HOME` |
| `tools` | `PATH` 上的 `gside`、`gapit`、`gmlst`、`snakemake` | 在 pixi 环境中运行 |

仅当某项检查为 `fail` 时，退出码才为 `1`。

## 2. 备份

```bash
bacmap backup --out /backup/bacmap-2026-10-30.zip
bacmap backup --out /backup/full.zip --with-results
```

默认包含：

- `config.toml`、`refs/manifest.json`；
- 每一个 SQLite 数据库：`tasks`、`dbos`、`runs`、`gom`、`baseline`、`data/bacmap`、
  `data/knowledge`——通过 SQLite 的 backup API 获得一致快照；
- `runs/*/run_manifest.json`（落盘的证据链）。

`dbos.sqlite` 包含工作流/步骤检查点；把它纳入归档，恢复后在途任务才能继续。除非指定
`--with-results`，否则不包含结果（`results/`）与 `workspaces/`。

备份的价值取决于恢复测试。请定期恢复到临时目录：

```bash
bacmap restore --from /backup/bacmap-2026-10-30.zip --home /tmp/bacmap-restore
bacmap doctor --home /tmp/bacmap-restore
```

## 3. 恢复

```bash
bacmap restore --from /backup/bacmap-2026-10-30.zip --home /srv/bacmap
bacmap restore --from ... --home /srv/bacmap --force   # 目标非空
```

- 目标非空时拒绝恢复，除非指定 `--force`；归档中不存在的既有文件不会被删除。
- 拒绝 `..` 与绝对路径条目（zip-slip）。
- 对每个恢复的数据库执行 `PRAGMA integrity_check`；失败即中止。
- 恢复后运行 `bacmap doctor`；若归档较旧，迁移会自动执行。

## 4. 事件保留

`tasks.sqlite.events` 记录计划/任务的状态转换、步骤与审批。它是审计辅助手段，不是
真相来源。

```bash
bacmap events prune --days 180
bacmap events prune --days 0      # 全部删除（很少合适）
```

门评估、运行记录、审批与发布存放在各自的表中，**不受**影响。

## 5. 结果布局迁移

结果写入 `results/runs/<task_id>/<dataset>/`；扁平路径是指向最新运行的链接。

```bash
bacmap results migrate --dry-run   # 列出遗留的扁平目录（数据集 + snp/cgmlst）
bacmap results migrate             # 移入 runs/legacy-<name>/ 并建立链接
```

规则：

- 绝不删除数据：已存在的 `runs/legacy-*` 目标会获得递增后缀。
- 新分析在建立链接前也会迁移遗留目录，因此升级不会把一次成功的运行变成失败的任务。
- 不要手工创建真实的 `results/<dataset>` 目录；它们会在下一次运行时被迁移。

## 6. Schema 迁移

- 每个数据库都有编号迁移清单与 `PRAGMA user_version`。
- 启动时在一个事务中自动执行迁移，迁移前先复制为 `<db>.bak-v<N>`。
- 比运行中代码更新的数据库会被拒绝（不做静默降级）。
- 清单只追加；绝不修改已发布的迁移。
- 通过 `store/migrations.py` 或 `store/schema.py` 中的文件级清单新增表/列。

## 7. 升级清单

1. `bacmap doctor` —— 记录当前状态。
2. `bacmap backup --out …` —— 包含 `dbos.sqlite`。
3. 让运行中的任务结束或将其取消；`bacmap task list` 显示非终态任务。
4. 更新环境：`pixi install`（开发时还需 `pixi install -e dev`）。
5. 重启 `bacmap web` / `bacmap mcp`；通过内容哈希检查会自动重新部署。
6. `bacmap doctor`；核对数据库版本。
7. 冒烟测试：`bacmap overview`、`bacmap run list`、一个小型 `analyze` 或 `record`。

回滚：恢复第 2 步的备份。被更新构建迁移过的数据库无法被旧构建打开；不要原地降级。

## 8. 运行时隔离

MCP Profile 保护的是流经 MCP 的数据，而不是 Harness 自己的 shell。对于外部 Harness：

- 以专用操作系统账户运行 bacmap，`BACMAP_HOME` 权限为 `0700`；
- 以该账户运行 `bacmap web` 与 `bacmap mcp --transport http`，绑定回环地址；
- 只把 MCP URL/token 交给 Harness，绝不给 Web token。

威胁模型见[安全](../concepts/security.zh.md)。
