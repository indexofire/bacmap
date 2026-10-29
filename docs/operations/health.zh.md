# 体检与保留

## 1. `bacmap doctor`

```bash
bacmap doctor
bacmap doctor --json
```

| 检查项 | 验证内容 | 失败时 |
|---|---|---|
| `home` | `BACMAP_HOME` 存在且可写 | 修复权限或用 `--home` 指定 |
| `database` | `tasks.sqlite` schema 版本与代码一致 | 旧库：启动任意命令即迁移（自动备份）；新库：说明你降级了，请用更新的构建 |
| `sandbox` | Apptainer/Podman 可用性 | 运行 `mine` 前安装；`passthrough` 表示无隔离 |
| `llm` | 配置的端点可达性 | 确定性功能仍可用（C3） |
| `disk` | 可用空间 ≥1 GB | 清理空间或迁移 `BACMAP_HOME` |
| `tools` | `gside`、`gapit`、`gmlst`、`snakemake` 在 `PATH` | 在 pixi 环境中运行 |

只有 `fail` 项会让退出码为 `1`。

## 2. 日志与任务状态

```bash
bacmap task list
bacmap task show <task_id>
ls "$BACMAP_HOME/workflow_state/log/"
```

- 读取状态/列表时 DBOS 会把 running 任务与工作流实际终态对账；长期 `running` 通常意味着进程
  已退出且未重启。
- 管线日志在 `workflow_state/log/`；`mine` 任务的 stdout/stderr 留在其工作区。

## 3. 事件保留

`tasks.sqlite.events` 记录计划/任务转换、步骤与审批，是审计辅助，不是事实来源。

```bash
bacmap events prune --days 180
bacmap events prune --days 0      # 全部清理（很少合适）
```

门评估、运行记录、审批与发布在各自表中，**不会**被此命令删除。保留期按机构审计政策决定。

失败分类与修复见[排障](troubleshooting.zh.md)。
