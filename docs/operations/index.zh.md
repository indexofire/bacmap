# 运维

单工作站上的日常事务：体检、备份/恢复、迁移、升级与保留。不需要守护进程或服务管理器。

<div class="grid cards" markdown>

-   **体检与保留**

    ---

    `bacmap doctor`、任务/日志检查与事件保留。

    [体检](health.zh.md)

-   **备份与恢复**

    ---

    一致的 SQLite 快照、运行清单、DBOS 检查点与恢复安全。

    [备份与恢复](backup.zh.md)

-   **升级与迁移**

    ---

    升级清单、结果布局迁移、schema 迁移与回滚。

    [升级](upgrades.zh.md)

-   **排障**

    ---

    提交/计划错误、管线失败、沙箱、鉴权与证据问题。

    [排障](troubleshooting.zh.md)

</div>

## 日常检查

```bash
bacmap doctor
bacmap task list
bacmap run list
```

运行隔离背后的安全模型见[安全](../concepts/security.zh.md)。
