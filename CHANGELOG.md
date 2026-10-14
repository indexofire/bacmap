# 更新日志

本文件格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [未发布]

### 新增
- **MCP Streamable HTTP 传输（ADR-12）**：`bacmap mcp --transport http`（仅绑 127.0.0.1 或 unix socket，强制 Bearer token，DNS-rebinding 防护）；stdio 仍为默认。
- **Web 可选鉴权（ADR-14）**：`BACMAP_WEB_TOKEN` 配置后全站 Bearer 校验，用于局域网访问。
- **`bio_compare_runs` 运行比较工具（ADR-18）**：比较同一样本两次运行的来源与结果，归因差异，来源相同而结果不同判为 `NOT_REPRODUCIBLE`（注册表 23→24；MCP 暴露 22→23）。
- 统一控制台命令 `bacmap`（`mcp` / `web` / `version` 子命令，`[project.scripts]` 注册）。
- 项目四件套：README.md、CHANGELOG.md、AGENTS.md、LICENSE（MIT）。
- 文档分层：项目说明 `docs/`（架构冻结文档，随仓库发布）；开发调研 `dev/`
  （证据与辩论记录，仅本地阅读，已 gitignore 不提交）。
- 三份用户文档：`docs/installation.md` / `configuration.md` / `usage.md`
  （含 SSH 隧道远程访问方案）。
- **文档全面双语化（英文为默认语言）**：README 与全部 docs 提供 EN + `.zh-CN.md`
  双版本，顶部语言切换链接，跨链同语言互指；新增工具参考 `docs/tools.md`（24 工具
  全参数，源自运行时注册表）；冻结架构文档补全量英译 `architecture-frozen-v1.en.md`
  （中文版为权威，英文版为参考翻译）。
- Web 任务台现代化重设计：DESIGN.md 设计系统（257 行契约）+ 858 行本地 CSS，
  Linear 式暗色操作台、六态语义徽章、轮询守卫修复、零外联（ADR-16）。
- 只读系统概览页 `/overview`：端点/路由/数据策略/版本/路径/沙箱/任务分布。
- analyze 任务末尾自动生成模板化 HTML 报告（§2 注①：确定性路径，报告失败降级为 error 信封不拖垮任务）。
- Web 结果查询界面：`/samples` 样本列表、`/samples/{id}` 单株详情（检出基因 + 报告入口）、`/samples/{id}/report` 报告文件服务、`/search` 关键词与结构化检索。
- gmlst senterica_2 方案 vendor 完成（20GB 编译库）+ 单株 typing 冒烟（3002-locus 谱）。
- V3 全子项收口：意图分类 99/100（prompt 复合句改进，两轮独立复测同分）、
  工具调用参数 45/46、挖掘样例 3/3、许可证确认、IQ3_XXS 单档+仲裁裁决。

### 变更
- gmlst 0.1.1 → **0.5.5**（PyPI；`typing cgmlst -s --format tsv` / `visual matrix|mst` 接口兼容）。
- 架构文档升至 **v1.4.8**：用户裁定取消 Hermes 插件通道，接入方式仅保留 MCP
  （`bacmap.adapters` 包、`hermes_agent.plugins` entry-point、Hermes 侧插件全部移除）。

### 修复
- ADR-03 路径合规：`bio_list_samples` / `bio_diagnose` / `bio_cgmlst` 及运行记录
  的 `env_lock_sha256` 不再由源码位置推导，统一经 `BACMAP_HOME`（`DEPLOYED_WORKFLOWS_DIR`
  /`DATA_DIR`/`env_lock_path()`）解析；删除失效的 `_PROJECT_ROOT`、`_scripts_dir`、`core/db.py`。
- ADR-17 资源仲裁接线：analyze 的内存密集步骤前经 `StrataArbiter.heavy_step()`（`[llm.resources]` 配置）；
  此前仲裁器仅存于测试、生产路径未生效。
- ADR-16 红线加固：`cloud_max_data_class` 配置层钳制到 D2，D3/D4 直接拒绝。
- ADR-08/§4.5 配置解析：补全 `LlmEndpoint` 的能力/管理字段（`supports_tools_with_schema`
  /`constrained_decoding`/`request_timeout_s`/`admin_url`），修复按文档编写的 config.toml 被 `extra=forbid` 拒绝。
- 安全：MCP `bacmap_submit_task` 与 Web 提交对样本 ID 做白名单校验（路径遍历防护）；MCP HTTP 报告路由同理。
- ADR-18 运行记录封存：`finalize_run` 落盘 `run_manifest.json`（表与文件同源、写入 `finished_at` 并重算哈希），此前 `write_manifest` 生产从不调用。
- ADR-20/18 `ref_databases`：部署期登记 `$BACMAP_HOME/refs/manifest.json`，其数据库（名称/版本/校验值）写入每次运行记录。
- MCP stdio 入口按 mcp 2.x API 重写（原 1.x `create_initialization_options` 从未可用）。
- 清理失效资源：`schemas.py` 中已删工具（validate_taxonomy/annotate/vpa_serotype/species_compare/db_setup/db_status）的 6 段死 schema；工具描述与 docs/tools 中残留的 `skill_view('hermes_bacmap:...')`（插件通道 v1.4.8 已删）改为 MCP 角色 prompt 指引。
- DBOS 系统库 URL 按 dbos 3.2 `system_database_url` 字段配置，
  绝对路径锚定 `$BACMAP_HOME/dbos.sqlite`（旧配置被静默忽略导致库落 CWD）。
- pixi.toml 自声明 editable 安装（`bacmap = { path = ".", editable = true }`），
  任意 CWD 均可 `import bacmap`。

## [0.1.0] - 2026-10-10

首个里程碑：hermes-bacmap 插件 → standalone 系统迁移**全部 10 步完成**。

### 新增
- Snakemake 9.27 工作流迁移（QC/组装/分型/AMR/毒力/报告，pixi 环境运行）。
- 工具注册表（29 → 23 工具，随外部化裁定逐步收缩）与 pydantic 参数模型。
- DBOS 任务引擎（analyze/curate/mine/write，断点恢复 + 审批流）。
- 六道门（分析结论、发布、MCP 直写、任务写、挖掘签字、引用门）全部实测拦截。
- MCP 服务器（20 个只读工具 + bacmap_submit_task/bacmap_task_status）与 Web 任务页。
- 智能体层：意图分类（Strata 实测 95/100）、沙箱执行器、LLM 网关（数据分级门控）。
- 本地流行特征库（baseline_releases）与 cohort MST（gmlst visual）。

### 变更（架构裁定，冻结文档 v1.4 → v1.4.8）
- v1.4.5：血清型扫描与判定整体迁入 gapit，bacmap `core/typing` 删除。
- v1.4.7：物种鉴定五模块外移 gside，4 个物种类工具删除；血清型三模块彻底放弃。
- v1.4.7：genome_annotator 外移（annotation 规则 `pending_external_tool` 占位）。
- v1.4.8：插件通道取消，仅保留 MCP。

### 验证
- V1 12 株金标准 ✅（3 项 MLST 方案演化 DIFF 已归因）
- V8 三次重跑 SHA256 一致 ✅；V10 gside 10/12（2 项 marker 法原理边界已归因）✅
- V11 六道门 ✅；V3 意图分类 95/100 ✅；V4 Hermes MCP 22 工具 ✅
- 测试基线 945 passed / 1 skipped；ruff、import-linter 契约全绿。
