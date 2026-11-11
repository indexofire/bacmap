# gvixb 集成

**gvixb** 是一个独立的本地 3D 细菌基因组数据可视化框架。bacmap 是宿主应用：bacmap 准备结果适配器
和 JSON 端点，gvixb 负责渲染可视化。本地 checkout 通常位于 bacmap 仓库同级的 `../gvixb`。

gvixb 的正式文档维护在 gvixb 项目内：

```text
<gvixb-project>/docs/
├── index.md
├── installation.md
├── configuration.md
├── views.md
├── data-contracts.md
├── integration-bacmap.md
├── plugins.md
├── development.md
└── troubleshooting.md
```

本页只记录 bacmap 侧的职责和接入点。

## 入口

Vue 控制台的样本、运行和 GOM 页面会列出当前结果实际存在的 gvixb 视图
（`/api/v1/samples/{id}` → `gvixb`，`/api/v1/runs/{id}` 与 `/api/v1/gom/objects/{id}` →
`gvixb_views`）；旧深链 `/samples/...`、`/runs/...`、`/gom/...` 会重定向到控制台。

| bacmap 页面 | gvixb 视图 |
|---|---|
| 控制台样本页（`/console/samples/<dataset>`） | 最新结果组装图或注释圈图 |
| 控制台运行页（`/console/runs/<run_id>`） | run 范围的组装图、进化树和 MST |
| 控制台 GOM 页（`/console/gom/<object_id>`） | GOM 分析对象关联的结果视图 |
| `/gvixb/...` 结果页 | 3D 可视化本体（组装、圈图、进化树、MST） |

## bacmap 职责

- run/task 解析和 `succeeded` 状态检查；
- 从 `results/runs/<task_id>/` 做 run 范围读取；
- dataset/group 归属检查；
- 固定文件白名单和符号链接越界拒绝；
- 解析组装 FASTA、CARD/VFDB TSV、Bakta GFF3、eggNOG TSV、树汇总和 gmlst MST；
- 提供 `/api/v1/gvixb/...`；
- 从 `/static/gvixb/` 提供 gvixb 静态资源；
- Web 认证与 CSP / 安全响应头。

gvixb 不直接访问 `results/`、SQLite 数据库或 bacmap 配置。

## 静态发布包

gvixb 拥有并发布：

```text
<gvixb-project>/web/
```

bacmap vendor 到：

```text
src/bacmap/interfaces/web/static/gvixb/
```

修改 gvixb 后，在 gvixb 项目同步：

```bash
cd <gvixb-project>
python3 scripts/sync-bacmap.py --bacmap /path/to/bacmap
```

## API 端点

完整的 `/api/v1/gvixb/...` 端点见 [HTTP API](../reference/api.zh.md)。

## 测试

bacmap 宿主集成由以下测试覆盖：

```bash
pixi run -e dev pytest -q tests/unit/test_gvixb.py
```

gvixb 前端算法测试位于 gvixb 项目内。
