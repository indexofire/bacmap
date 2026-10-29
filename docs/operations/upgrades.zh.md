# 升级与迁移

## 1. 升级清单

1. `bacmap doctor` —— 记录当前状态。
2. `bacmap backup --out …` —— 包含 `dbos.sqlite`。
3. 让运行中任务完成或取消；`bacmap task list` 可看非终态任务。
4. 更新环境：`pixi install`（开发环境另加 `pixi install -e dev`）。
5. 重启 `bacmap web` / `bacmap mcp`；工作流按内容哈希自动重部署。
6. 再次 `bacmap doctor`，确认数据库版本。
7. 冒烟：`bacmap overview`、`bacmap run list`、一次小型 `analyze` 或 `record`。

回滚：用第 2 步的备份恢复。被新版本迁移过的数据库不能由旧版本打开，不要原地降级。

## 2. 结果布局迁移

结果写入 `results/runs/<task_id>/<dataset>/`；扁平路径是指向最新运行的链接。

```bash
bacmap results migrate --dry-run   # 列出旧扁平目录（数据集 + snp/cgmlst）
bacmap results migrate             # 搬入 runs/legacy-<name>/ 并建立链接
```

规则：

- 永不删除数据；已存在的 `runs/legacy-*` 目标会递增后缀。
- 新分析也会在建立链接前自动迁移遗留目录，升级不会把成功分析变成失败任务。
- 不要手工创建真实的 `results/<dataset>` 目录；下一次运行会迁移它。

## 3. Schema 迁移

- 每个数据库有编号迁移列表与 `PRAGMA user_version`。
- 启动时在单个事务中自动执行，执行前复制为 `<db>.bak-v<N>`。
- 库版本高于代码时拒绝打开（不做静默降级）。
- 迁移列表只追加；不要修改已发布的迁移。
- 新表/列通过 `store/migrations.py` 或 `store/schema.py` 的文件级清单添加。

## 4. 运行隔离

MCP Profile 只保护经过 MCP 的数据，不能阻止 Harness 自己的 shell。外部 Harness 场景：

- 用专用系统账户运行 bacmap，`BACMAP_HOME` 权限 `0700`；
- 以该账户运行 `bacmap web` 与 `bacmap mcp --transport http`，只绑回环；
- 只把 MCP URL/token 给 Harness，绝不给 Web token。

威胁模型见[安全与数据分级](../concepts/security.zh.md)。
