# 更新日志

本文件格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [未发布]

### 安全（2026-10 代码质量评估整改）
- **沙箱 shell 白名单结构性绕过修复**（`agent/sandbox/tool.py`）：①命令分段正则补上**换行符**——此前
  `ls\nrm -rf …` 因首段白名单整段放行；②禁用清单新增**隐藏执行语法**（命令替换 `$(...)`、反引号、
  进程替换 `<(...)`、`find -exec/-execdir`、`system(...)`）——引号拼接（`cu""rl`）不再绕过表面积黑名单；
  ③`_SHELL_DESCRIPTION` 如实降级承诺：白名单是**意图分类**而非安全边界（python 等图灵完备命令天然可任意
  计算），真正边界是容器后端 `--network none` + 只读挂载，直通模式仅限受控开发环境。
- **Web 非回环绑定 fail-fast**（对齐 MCP HTTP）：未设 `BACMAP_WEB_TOKEN` 且 `--host` 非回环地址时
  拒绝启动（此前静默无鉴权暴露任务提交/审批签名给整个网段）。回环免鉴权单机形态不变。
- **助手计划确认强制点**：`PlannedTask.requires_confirmation` 此前无任何代码消费。现
  `execute_plan` 增加 `confirmed` 参数——含需确认任务的计划未经确认**拒绝提交**
  （`PlanNotConfirmedError`）；Web 确认按钮 / CLI `Confirm.ask`、`--yes` / TUI `Ctrl+Y` 为确认事实来源。
- **Web 助手确认界面展示完整任务参数**（`script`/`input_paths`/`sandbox_image` 此前对用户不可见，
  人工确认形同虚设）；并修复会话表并发竞态（LRU 淘汰加锁、计划原子取出防双击重复提交、
  执行中也刷新活跃时间）。
- 登录 token 比较改 UTF-8 bytes 常量时间比较（非 ASCII 输入不再触发未捕获 500）。

### 修复（正确性/资源）
- **GOM `create()` 并发契约**：不可变检查移入 `BEGIN IMMEDIATE` 事务内 + `IntegrityError` 兜底转换
  为 `GOMImmutableError`——并发写者不再以裸 `sqlite3.IntegrityError` 冒泡，`dbos_engine` 的幂等重跑
  契约在并发下仍成立。
- **连接泄漏两处**：`search_samples` 的 `StrainGenotypeIndex`（手动双 `close` 无 finally，异常路径泄漏）
  改 `with` 管理（`StrainGenotypeIndex` 新增上下文管理器）；`_ensure_task_object` 同样改 `with`。
- mine 产物清单推导、GOM"最新版本"SQL 子查询（×4）、`EventType` Literal/frozenset 双写——三处
  复制粘贴消除（单一事实来源）；`register_file_artifact` 的 sha256 格式校验前置（不再先白读大文件）。

### 变更（工程/工具链）
- **ruff 收紧**：select 扩至 `B`/`C90`/`SIM`/`RUF`/`S`（max-complexity=15），修复全部 178 项违规
  （含 F821 未定义名、W605 无效转义、恒真断言等真问题）；已知复杂度热点（`create_app`/`samtools_op`/
  `seq_ops`/`_extract_genotype`）带 noqa 标注列入重构清单。
- **mypy 收紧**：`bacmap.core.*`/`bacmap.store.*` 启用 `disallow_untyped_defs`（领域层函数签名完整标注）。
- **覆盖率基线**：新增 `[tool.coverage]` 配置（忽略 Snakemake 脚本/遗留迁移脚本）与
  `pixi run -e dev coverage` 任务，门槛见 `pyproject.toml`（只升不降）。
- `DbosTaskEngine.approve()` 类型专属副作用拆为模块级终态化函数 + 分发表
  （新增任务类型注册即可，不再改长 if 链）；reject 的任务消息如实为 `rejected by …`（原为误导性的
  `approved by …`）。
- `search_samples` 拆分为编排层 + `_search_structured`/`_search_fulltext`（原 138 行 6 层嵌套）；
  未捕获异常统一由 `@tool_handler` 转错误信封（错误前缀从 `Search failed:` 统一为
  `search_samples failed:`，不再双层兜底）。
- **巧合代码消除**：`snp_tree`/`_load_cgmlst_profile_payload` 的 `max(objs, key=version)` 跨
  object_id 比较无意义（碰巧与 `list_by_type` 的 created_at DESC 排序一致）——改为显式取排序首个。
- **`dbos_engine`**：`init_dbos` 的 check-then-set 加锁（Web 线程池 + CLI 并发不双 launch）；
  `_fastqs` 改 `csv.DictReader`（表头校验 + 转义处理，替代魔法列索引）；`status()` 的
  工作流状态映射提取为纯函数 `_map_workflow_outcome`（可单测，新增 5 个 case）。
- **Web**：`/logout` 补 CSRF 校验（跨站不得强制登出）；`task_detail`/`task_fragment` 双胞胎路由
  合并渲染；`BACMAP_WEB_AUTH` 非法值从静默回退改为 warning 日志。
- **GOM**：`close()` 后再调用给出可定位的 `sqlite3.ProgrammingError`（原为裸 `AttributeError`）；
  三个逐字相同的 ID 生成函数合一（`_new_uuid`，公共名保留）。
- **LLM 路由**：`LlmConfig.resolve` 对漏配路由的 purpose 回退首个 enabled 端点时打 warning
  （cloud 端点 + 默认 D0 的意外外发面，ADR-16）。
- **双层错误兜底移除**：`query_metadata`/`add_metadata`/`query_lab_results`/`add_lab_result` 的
  内层 try/except 与 `@tool_handler` 重复且错误前缀不一致，统一交装饰器兜底；
  `search_samples`/`review_flags` 共用 `_parse_limit`；工具错误消息统一英文。

### 安全（遗留修复，第四轮 A1-A3）
- **`bio_generate_report` effect 修正为 `WRITE`**（冻结规则 5 的实锤违例）：报告生成会向
  `results/` 落盘 HTML/PDF（三处 `write_text`），此前误标 `COMPUTE` 而暴露在 MCP 只读面。
  改标后从 MCP 摘除；内部调用（`_step_report`）与 CLI/TUI/Web 不受影响。docs/tools 双语同步。
- **GOM 保留前缀防护**：`GenomeObject` 模型边界拒绝 `__gom_*` 前缀的 payload 键——此前
  用户 payload 携带同名键会在写入时被静默覆盖、读出时被静默剥离（无检测的数据损坏）。
- **工具错误信封收敛**：`tool_handler` 兜底只返回异常**类型名**（原文常含宿主绝对路径，
  经 MCP 进入客户端与 LLM 上下文）；完整堆栈保留在服务日志。

### 变更（重构收尾，第三轮）
- **`dbos_engine.py` 拆分**（1044 → 715 行）：DBOS 生命周期 → `_runtime.py`（40 行）；
  审批副作用 + 工作流状态映射 → `_outcomes.py`（103 行）；`DbosTaskEngine` 类 →
  `task_engine.py`（261 行，submit 内延迟导入 workflow——保持测试对 dbos_engine 模块的
  monkeypatch 契约且无顶层循环导入）。dbos_engine 只留 step/workflow 编排核（step 与可注入
  辅助、workflow 与 step 必须同模块：DBOS 恢复语义 + 测试 patch 点），其余旧名全部
  re-export——`from bacmap.tasks.engine.dbos_engine import X` 的既有路径不变。
- **`create_app` 拆分**（290 行单闭包工厂 → 组装器 + 4 个路由工厂）：`_build_auth_routes`/
  `_build_sample_routes`/`_build_task_routes`/`_build_assistant_routes`，各 <15 复杂度；
  提交表单解析（`_submit_task_payload`）与审批构造（`_approval_from_form`）独立可测。
- **复杂度热点清零**（C901 noqa 全部移除）：`samtools_op`（24）拆出 `_samtools_build_cmd` +
  必要参数前置校验；`seq_ops`（25）拆为 8 个 `_seq_*` 操作函数 + `_SEQ_OPERATIONS` 分发表
  （新增操作只注册即可）；`_extract_genotype`（20）拆为血清型/MLST/AMR/质粒四个独立提取器。
  **全仓无超线函数**（mccabe 上限 15）。

### 新增
- **深度挖掘执行**：内置助手可调用 `sandbox_run`（ADR-11 L2）执行 Python 脚本并产出图表
  （PNG/CSV）；可反复调用迭代，成熟脚本再作为 `mine` 任务经挖掘门/人工签字进入报告。
  沙箱后端 Apptainer/Podman；无后端且 `BACMAP_ALLOW_UNSANDBOXED=1` 时受控直通，否则显式报错。
- **TUI 视觉语言**：注册 `bacmap-dark`/`bacmap-light` 语义主题，CSS 全用语义槽；Header 显示
  LLM 端点；会话日志配色与主题一致。
- **异步会话**：网关 `run_agent_async`/`structured_async`；只读工具异步 + 线程卸载；
  TUI `Esc` 真正取消在途 LLM 请求。
- **LLM 驱动的会话助手（三端统一）**：`agent/session.py`（多轮、只读工具、结构化 `AnalysisPlan`，
  ADR-10 规划型 + ADR-11 开放路径）。简单需求规划为 `analyze`/`curate`（Snakemake 路径）；
  深度挖掘规划为 `mine`（LLM 写脚本、沙箱执行，可多步）或 `write`。写操作**分级确认**后经同一任务引擎提交；
  无 LLM 时降级到显式子命令/表单（C3）。新增 `assistant` 角色三文件。
  - CLI：`bacmap ask "<需求>"`（一次性）、`bacmap chat`（多轮）。
  - TUI：对话页即助手（规划 → `Ctrl+Y`/按钮确认 → 提交）。
  - Web：`/assistant` 页（多轮会话保存在服务端 + 确认提交按钮）。
- 网关新增 `run_agent`（带工具智能体，ADR-08 Tool Output 模式），与 `structured` 共用端点/数据分级/角色校验。
- **CLI 扩展**：`bacmap tui|console|overview|task {ls,show,submit,approve,cancel}|sample {ls,show}|search`，
  查询类子命令支持 `--json`。写操作与 Web/MCP 走同一套门与审批。
- **全屏 TUI（Textual，会话优先重构）** `bacmap tui`：状态头（LLM 端点）+ 可折叠侧栏
  （任务/样本）+ 会话区 + 计划提示 + 输入框 + 按键提示栏。参考 opencode TUI 的 leader 和弦
  （`Ctrl+X` 后 `n/l/s/m/t/h/q`）与命令面板（`Ctrl+P`）、hermes agent 的 REPL 语义（`Esc` 中断、
  斜杠命令）。直接键：`Ctrl+B` 侧栏、`Ctrl+R` 刷新、`Ctrl+L` 清屏、`Ctrl+Y` 确认计划；
  斜杠命令 `/help /new /clear /tasks /samples /search /model /analyze /curate /quit`。
- **交互式菜单** `bacmap console`（rich）：面向偏好引导式操作的用户。
- **共享视图层** `interfaces/views.py`：Web / CLI / TUI 三端复用同一只读视图逻辑。
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
- **清理 gside 已覆盖的专项占位规则（冻结文档 v1.4.10）**：删除
  `species_ani`/`species_sourmash`（alternate 物种鉴定档，gside `all` 已含多法仲裁）、
  `taxonomy.smk`、`vpara_targets`；Snakefile 移除 `_ALT_*`/`_STANDARD_ACTIVE` 档位门控
  （`.smk` 11→10）。物种/分类学鉴定收敛为单一 `species_identify`（gside）。
- **vpara_virulence 换装 gapit（ADR-20，冻结文档 v1.4.9）**：删除内联 blastn 筛查，
  改用 gapit 自定义库 `vpara_virulence`（tdh/trh/tlh）；部署期
  `workflow/scripts/build_gapit_db.py` 自动建库于 `$BACMAP_HOME/refs/gapit/` 并登记
  `refs/manifest.json`；规则输出归一化为既有 `virulence.json` 契约，新增
  tool/database/hits 溯源字段；打包参考序列 `workflow/refs/vpara_virulence.fasta`。
- gmlst 0.1.1 → **0.5.5**（PyPI；`typing cgmlst -s --format tsv` / `visual matrix|mst` 接口兼容）。
- 架构文档升至 **v1.4.8**：用户裁定取消 Hermes 插件通道，接入方式仅保留 MCP
  （`bacmap.adapters` 包、`hermes_agent.plugins` entry-point、Hermes 侧插件全部移除）。

### 修复
- 运行记录封存加固：`run_manifest.json` 的 `manifest_sha256` 改为**可复算的规范 JSON 哈希**（键排序、无空白），并原子写入；新增 `verify_run_manifest`。
- 引用门：知识库侧标识符归一（`PMID:` 前缀/方括号/DOI 大小写），消除 `PMID:123` ↔ `[123]` 的误拒。
- GOM：FTS5 `rowid` 显式对齐 `genome_objects.rowid`（原依赖两表自增巧合）。
- 任务提交：先落任务行再启动工作流（`SetWorkflowID` 确定性映射），启动失败回滚为 FAILED，杜绝孤儿工作流；`current_step` 按任务类型写入（此前恒为 analyze）；引擎层补样本 ID 校验。
- 工具注册表：导入期自检元数据缺失/陈旧、schema 名字不一致、重复注册（快速失败）。
- MCP/Web：提交接口收敛到 analyze/curate（mine/write 需 script/draft，经内建智能体或 Web 开放路径），拒绝空任务。
- 本地流行特征库：候选扫描不再硬编码 `SAM-*`，覆盖任意样本 ID（与 bio_list_samples/Web 一致）。
- LLM 网关：补齐 ADR-09 档位强制（端点档位低于角色 min_model_tier 即拒绝）；智能体缓存键纳入 instructions。
- Snakemake 部署：`project_root` 重写标记缺失时快速失败（原先静默留错路径）。
- ADR-18 运行记录：`seeds`/`nondeterministic_steps` 支持 config.yaml 声明。
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
