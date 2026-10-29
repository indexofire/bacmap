# 备份与恢复

## 1. 备份

```bash
bacmap backup --out /backup/bacmap-2026-10-30.zip
bacmap backup --out /backup/full.zip --with-results
```

默认包含：

- `config.toml`、`refs/manifest.json`；
- 全部 SQLite 数据库：`tasks`、`dbos`、`runs`、`gom`、`baseline`、`data/bacmap`、
  `data/knowledge` —— 用 SQLite backup API 取得一致快照；
- `runs/*/run_manifest.json`（磁盘侧证据链）。

`dbos.sqlite` 保存工作流/步骤检查点；纳入后恢复时运行中任务可继续。结果（`results/`）与
`workspaces/` 默认不包含，需要时加 `--with-results`。

备份只有经过恢复验证才可靠。建议定期恢复到临时目录：

```bash
bacmap restore --from /backup/bacmap-2026-10-30.zip --home /tmp/bacmap-restore
bacmap doctor --home /tmp/bacmap-restore
```

## 2. 恢复

```bash
bacmap restore --from /backup/bacmap-2026-10-30.zip --home /srv/bacmap
bacmap restore --from ... --home /srv/bacmap --force   # 目标非空
```

- 目标非空时默认拒绝，`--force` 允许覆盖；归档之外的文件不会被删除。
- 拒绝 `..` 与绝对路径条目（zip-slip）。
- 对每个恢复的数据库执行 `PRAGMA integrity_check`，失败即中止。
- 恢复后运行 `bacmap doctor`；归档较旧时会自动迁移。

## 3. bacmap 之外的备份

- `refs/` 下的参考数据库及外部 CheckM2/GTDB-Tk 路径（默认不复制）。
- `BACMAP_HOME` 的权限/属主与 systemd unit。
- 若要在别处重建运行时，保留 `pixi.lock`。

升级顺序与回滚见[升级与迁移](upgrades.zh.md)。
