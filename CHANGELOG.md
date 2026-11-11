# 更新日志

本文件格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [Unreleased]

### gvixb 3D 可视化集成

- **结果启动的 3D 视图**：从控制台样本/运行/GOM 页面打开线性组装图、Bakta/eggNOG
  注释圈图、SNP/cgMLST 进化树与 gmlst 原始 MST（`/gvixb/...` 结果页 + three.js 本地
  静态资源，零外联）。
- **只读适配器** `interfaces/gvixb.py`：按 run 物理目录读真实产物，任务未成功不暴露
  入口；固定文件白名单 + 符号链接越界拒绝；样本"最新结果"入口是独立标注的 latest
  scope，不复用历史运行接口。
- **当前产物布局适配**：菌株名产物（`{sample}.fasta`、`{sample}.gff3`、
  `{sample}.emapper.annotations`）优先，旧命名回退；v1.10.20 冷产物压缩（注释目录
  `.gz`）透明解压；AMR/VFDB 坐标来自 gspec screen JSON（旧 abricate TSV 回退）。
- **API**：`/api/v1/gvixb/runs/{run_id}/manifest` 等 7 个只读端点；样本/运行/GOM
  详情端点附 `gvixb` / `gvixb_views` 入口字段供控制台渲染。

### 流式两阶段分析（prelim 先行，注释垫底）

- **管线顺序澄清**：DAG 由 bacmap 固定（rules/*.smk 声明式依赖），LLM 不参与排程。
- **两阶段执行**：引擎先跑 prelim 目标（物种/MLST/血清型/AMR/质粒——分钟级，
  实测 ~4 分钟出首屏）→ 产出 `<sample>_summary.prelim.json` + 建立扁平别名 →
  web 即可查看初步报告（按需生成 `_report.prelim.html`，标注"注释进行中"）；
  再跑最终目标（QUAST/Bakta/eggNOG 自然垫底）→ 完整 summary/报告自动升级。
- **collect_summary** 适配无注释输入（prelim 标记 + annotation.status=pending）；
  **sample_detail** 最终缺失回退 prelim（digest.prelim 供前端提示）；
  报告路由 prelim 回退 + 幂等缓存；前端"完整报告"页签接受 prelim 并带徽标。
- 重试逻辑抽取 `_run_targets_with_retry`（两阶段共用，含陈旧锁自愈）。
- 实测：14:01 提交 → 14:05 首屏可见 → 14:24 完整报告（succeeded，26MB 压缩）。

### 中断任务自动恢复 + 用户暂停/恢复

- **根因**：DBOS 恢复线程按 `application_version` 过滤 PENDING 工作流——
  断电重启叠加代码升级后版本哈希漂移，旧版本中断工作流成为**永久孤儿**
  （任务行 running、无进程执行，实测）。修复：`_runtime` 启动后经
  `recovery.py` ①收养旧版本本地 PENDING 工作流（改版本号 + 主动触发恢复，
  步骤输入为 JSON 标量跨版本安全）②对账卡死任务行（running × 工作流终态/
  缺失 → failed，提示 resume）。**实战验证**：重启 web 后孤儿任务
  3777ad63 的 snakemake 自动在同一 run 目录续跑（已完成规则跳过）。
- **用户暂停/恢复**：`bacmap task pause/resume <id>` + Web API
  `POST /tasks/{id}/pause|resume`。pause 在步骤边界收场（不强杀当前
  snakemake 规则）；resume 清旧工作流后以同一 task_id 重建，
  `--rerun-incomplete` 在同一 run 目录从已完成规则继续。新增 PAUSED 任务态。
- **陈旧 snakemake 锁自愈**：SIGKILL 残留的 `.snakemake/locks` 永不自愈
  （实测恢复链路卡死于此）——锁冲突重试前探测本机无 snakemake 进程即
  清除锁并立即重试；并发 analyze 合法持锁仍走退避。
- **实战闭环**：断电中断任务 3777ad63（跨版本孤儿 × 陈旧锁双重卡死）经
  cancel → resume 重建 → 锁自愈 → 16 核续跑 → 全流程 succeeded；产物含
  菌株命名组装文件（MLST FILE=26OTH0027、ST 1025）、gspec/typing 全
  JSON、自动压缩 31MB。
- 测试基线 2038 → 2044。

### 分型产物 JSON 化 + 组装文件以菌株命名 + 防唤醒守卫

- **gspec typing screen 产物 JSON 化**：gene 库（ecoh/shi_sero/vpa_* 等）的
  screen 中间产物从 TSV 改为 `gspec/<db>_screen.json`（gspec.report/1，含
  工具版本/参数 provenance）；`gspec typing` 所需表格由 JSON 派生到临时
  文件、用完即删——结果目录不再残留机器难读的 TSV。原则：程序读 JSON，
  人读表格（报告 HTML 已是表格形态）。
- **组装文件以菌株命名**：`assembly/contigs.fasta` → `assembly/<sample>.fasta`，
  下游所有结果的 FILE 字段（MLST/amrfinder/QUAST/gspec）不再统一显示
  "contigs"。读取层双路径兼容旧 run。
- **取消防唤醒守卫**：DBOS 重启恢复会唤醒已取消的任务（实测发生过）——
  工作流入口与管线结束后查询 tasks.sqlite，cancelled/failed 即刻以
  CANCELLED 终态收场；顺带修复守卫插入时损坏的 `@DBOS.workflow()` 装饰器
  （曾致 analyze 工作流注册失败）。
- **CONCRETE 输入框走查修复**：静息态黑框 → 暖灰细线（悬停加深，黑框+
  硬阴影保留为焦点签名态）；聚焦三重黑环（全局 outline 与控件焦点态叠加）
  消除；检索页 meta-grid 黑色网格线移除（`:has(.meta-item)` 限定数据格场景）。
- 崩溃恢复实证：SIGKILL 全进程树后重启，任务自动从断点续跑（步骤级 +
  规则级双断点）；旧中断批次同样被唤醒（已按需取消）。

### 沙门菌 MLST 方案错配修复（数据完整性 P0）

- **错误**：`pathogens.yaml` 沙门菌 `mlst_scheme: salmonella_2`——该方案实为
  cgMLST（2750 位点，pubmlst），套在 7 基因 MLST 步骤上导致 **ST 全部 N/A**
  （旧 run 1719d5c3 的 20 株沙门样本全部污染）。正确方案为 `senterica_1`
  （Achtman 7 基因，enterobase）。
- **修复**：改为 `senterica_1` 并下载安装；真实样本验证 26SAL0518 →
  **ST 8334**（aroC 173/dnaN 788/hemD 125/hisD 206/purE 40/sucA 174/thrA 165）。
- **防再犯守卫**（`test_pathogen_scheme_types.py`）：从 gmlst 方案目录读取类型，
  断言所有物种 `mlst_scheme` 类型=mlst 且 7 位点、`cgmlst_scheme` 类型=cgmlst；
  回归锁死沙门=senterica_1。全物种核验通过（志贺/大肠 ecoli_1、弧菌
  vparahaemolyticus_1、李斯特 lmonocytogenes_1 均正确）。
- **同类全面核查**：amrfinder_organism（Salmonella/Escherichia 均合法）、
  serotype_engine（sistr/ecoh）、gspec_screens（vpa_*/shi_sero/eco_*/lmo_sero
  均已安装）、snp_group 参考组均无错配。
- 旧 run 数据不可变保留；重跑沙门批次即可获得正确 MLST。

### run 冷产物自动压缩

- **动机**：单株 analyze 结果 ~89MB，其中 ~85MB 是 Bakta 导出（embl 14M + gbff 13M +
  gff3/ffn/fna/faa）、合并 annotation.json（12M）与 eggNOG 中间表（6.8M）——运行期
  消费后 Web/报告/GOM 路径不再读取。
- **方案**：`analyze` 收尾新增 `_step_compact`：冷产物 gzip（实测 89MB → 26MB，压掉
  ~70%）；热路径（summary.json、gspec/*.json、报告 HTML、MLST、QUAST 表、contigs）
  保持明文。幂等。CLI：`bacmap run compact/expand <run_id>`（存量 run 补压/恢复）。

### figures4papers 作图技能（部署期安装）

- `scripts/install_figure_skill.py`：把 figures4papers 的 scientific-figure-making
  技能（CC BY-NC 4.0，pin commit）装到 `$BACMAP_HOME/skills/figure-maker/`。
  MCP 以 `skill://bacmap/figure-maker/**` 发布（SKILL.md + api/patterns/tutorials
  参考），writer/miner 说明书指引模型按其出版级样式作图。**仓库不内嵌上游内容**
  （许可不兼容，部署期下载；限非商业场景）。

### 研究工具页纳入控制台（消除孤立页）

- 旧 Jinja 研究工具（高级工作台 / 系统发育 BEAST 规格 / Logistic / Study 打包与
  操作台）经新增 `LegacyEmbedView` 以沙箱 iframe 嵌入控制台外壳；ResearchView 的
  三个跳出链接改为站内路由。`/research` 前缀响应放宽为 `frame-ancestors 'self'`
  （外站仍不可嵌，与样本报告策略一致）。

### 输入登记符号链接误判修复

- **假碰撞根因**：`shigapass_run/26OTH0027.fasta -> ../26OTH0027.fna` 这类外部工具
  留下的符号链接被递归扫描当成独立输入；复合校验和含文件名，同一物理文件的两个
  名字必然"不同"→ 误报 `dataset id collision`（且 `new_path` 显示 resolve 后
  路径，与 existing path 相同，极具迷惑性）。**修复**：① `scan_fasta_dir` 按
  `resolve()` 去重，每个物理文件只登记一次；② `_guard_collision` 兜底——新文件
  resolve 后与登记路径同一物理文件即幂等放行。真实数据目录复验：24 株全部
  幂等复用、零冲突。同一基因组多次分析的既有语义（`--samples` 复用）不受影响。

### 仪表盘一行三栏布局（CONCRETE 优化）

- **AMRFinderPlus 数据库升级 2026-08-07.1 → 2026-10-29.1**（NCBI 最新）：
  下载到 `$BACMAP_HOME/data/db/amrfinderplus/2026-10-29.1`（实体目录，不再依赖
  mamba 环境的符号链接；pixi 环境内存放会在环境重建时丢失）；工作流规则按
  sorted-latest 自动选用新版本，Bakta db6 的 `amrfinderplus-db/latest` 已重新
  指向。软件端 4.2.7 已是 bioconda 最新。
- **eggnog-mapper 2.1.13 升级受阻记录**：bioconda 的 2.1.13–2.1.15 构建均要求
  python <3.12，与 bacmap 的 3.12 冲突，无法经 conda 解出；2.1.12 为当前可解
  最高版本（约束收紧为 `>=2.1.12,<2.1.13` 并注明原因，防误升破坏环境）。
  2.1.13 对 bacmap 无功能差异（DB 同为 5.0.2、diamond 接口不变）。
- "最近 7 天任务 / 任务状态分布 / 最近任务"三个面板合并为一行（5:4:7 三栏、
  等高对齐；≤1180px 降为两栏 + 最近任务独占一行，≤760px 单栏堆叠）。
- "最近任务"改为分页（每页 5 条，上一页/下一页 + 页码指示），任务 ID 下附
  创建时间，表格改紧凑行高。
- 数据库概览扩展为 9 张可点击导航卡（新增"计划"、研究子计数、化验覆盖菌株数），
  悬停显示箭头直达对应页面（菌株/样本/GOM/研究/计划/知识库/运行/记录）。

### gspec screen 改为 JSON 主输出 + vpara 残留清理

- **merge_annotation SyntaxError 修复**：`merge_annotation.py` 顶部的
  `from __future__ import annotations` 与 Snakemake `script:` 指令的 preamble
  注入冲突（preamble 拼在文件最前 → `__future__` 不再是首条语句 → 编译期
  SyntaxError，无 traceback、极难定位）。该雷自 v1.10.14 注释落地即潜伏，
  首次启用注释时引爆。已移除该行并新增回归测试锁定所有 `script:` 指令
  脚本禁止 `from __future__ import`（`test_workflow_script_future.py`）。
- **注释全链路实测（16 核）**：Bakta full ~8 分钟 + eggNOG mid-sensitive
  ~3.5 分钟 + gspec screens 秒级 + merge/summary 2.6 秒 ≈ **12.5 分钟/基因组**，
  注释率 97.65%（4502 CDS），COG 全 20 类、GO 5412、KEGG KO 3367、Pfam 2874。
- **JSON 主输出**：card / vfdb / plasmidfinder 三条 screen 规则改为
  `gspec screen -f json -o gspec/<kind>.json`（规则更名 `gspec_screen_*`），
  保留 schema / 工具版本 / 参数等 provenance；数值字段（%IDENTITY 等）恢复类型。
  新增共享解析层 `core.utils.parse_gspec_report` / `load_screen_hits`：JSON 优先、
  旧运行目录的 `amr/abricate_*.tsv` 布局自动回退（报告对历史 run 仍可重渲染）。
  collect_summary / generate_report / sample_steps 同步。
- **vpara_virulence 残留清理**（回应 run 记录“参考数据库=vpara_virulence”的错象）：
  志贺菌分析流程本身正确（gspec shi_sero）；错在部署期登记表
  `refs/manifest.json` 只有一条 v1.4.41 删规则时漏清的 `gspec:vpara_virulence`
  条目，被 ADR-18 证据链机械记入每个 run。已删除 `config.yaml databases`
  的 vpara_virulence 条目与 `refs/gspec/vpara_virulence/` 目录，并按
  `pathogens.yaml` 实际引用重建登记表（card/vfdb/plasmidfinder/shi_sero/
  eco_dec/ecoh/lmo_sero/vpa_ok/vpa_vf/vpa_pai + ncbi-amrfinderplus，
  含 sha256 与版本日期）。此后 run 记录的 ref_databases 如实反映在用库。
- **eggNOG 快速档实测**：mid-sensitive + 关闭迭代 + 8 线程下 diamond 阶段
  ~4.5 分钟/基因组（此前 sensitive+迭代 >53 分钟未完成）；Bakta full ~8 分钟。

### 注释数据库就位 + eggNOG 速度档位

- **`bacmap start web -D/--daemon`**：守护进程方式后台启动 Web 控制台（双 fork
  脱离会话）。PID 写入 `$BACMAP_HOME/web.pid`，stdout/stderr 追加到
  `$BACMAP_HOME/web.log`；已在运行（PID 存活）时拒绝二次启动，陈旧 PID 自动放行。
  停止：`kill $(cat $BACMAP_HOME/web.pid)`。默认仍为前台运行。
- **cores 修复**：`task_engine` 不再给每个任务写死 `cores=8`；缺省时引擎读部署
  `config.yaml` 的 `threads` 作为 snakemake `--cores`（16 核工作站不再被截断到 8）。
  显式传 `cores` 仍优先生效。
- **annotation 配置读取修复**：`annotation.smk` 此前在 config 顶层找 `annotation`，
  实际它嵌在 `tools:` 下——注释配置从未生效，一直靠默认值运行；现改为
  `config.tools.annotation`（与 `tools.quast` 同级同源）。
- **eggNOG 速度档位**：`annotation.smk` 的 eggnog 规则新增 `sensmode` / `iterate` /
  `usemem` 配置项（工作流 `config.yaml` 的 `tools.annotation.eggnog` 段）。默认
  `mid-sensitive` + 关闭迭代（实测 sensitive+迭代在 8 线程上仅 diamond 阶段就
  >50 分钟/基因组，不可用）；极限灵敏度可改回 `sensmode: "sensitive"` +
  `iterate: true`。`usemem: true` 让 diamond 库常驻内存。
- **线程默认 8 → 16**：匹配 16 核工作站；小机器可在 config.yaml 调回。
- **eggNOG 上游域名修复记录**：eggnog-mapper ≤2.1.13 的
  `download_eggnog_data.py` 使用已失效的 `eggnogdb.embl.de`（NXDOMAIN）；需改为
  `eggnog5.embl.de`（或用 Cloudflare 镜像 `downloads.eggnogdb.org`，速度快 ~25x）。
- **AMRFinderPlus DB 版本兼容**：amrfinder 4.2.7 要求 DB ≥ 2025-09-22.2，Bakta
  db6 自带的 2024-12-18.1 过旧会导致 Bakta AMR 专家系统失败（exit 1）；将
  `<bakta-db>/amrfinderplus-db/latest` 指向新版 DB（如 2026-08-07.1）即可修复。

### DSH 控制台嵌入修复 + 报告可视化与 AI 解读

- **DSH 挂载修复**：`tools/dsh-bacmap-console` 现在把控制台固定在 `/bacmap/console/`，
  运行时注入 `__BACMAP_MOUNT__` / `__BACMAP_ROUTER_BASE__`，并让前端 API、登录跳转、
  报告 iframe/下载与研究产物链接统一经 `appUrl()` 加挂载前缀。此前根路径 `/` 会被
  SPA 路由解析成 `/console/bacmap/console/`，导致报告 404；现在控制台与内嵌完整报告
  都能在 DSH iframe 中显示。报告页不再注入代理 shim，消除 sandbox script 报错。
- **报告可视化**：样本报告新增 KPI 摘要条、AMR 类别分布与高置信耐药基因条形图、
  VFDB 毒力基因条形图、质粒复制子表、Bakta 特征/eggNOG COG 功能分类图，以及可折叠的
  完整基因明细表。全部用 HTML/CSS 实现，适配报告的沙箱 CSP（无脚本）。
- **AI 解读章节**：`bio_verify_result` 传入 `interpretation_text` 时，NLI Reflector
  无论是否触发人审都会持久化解读文本；报告新增“AI 解读与 NLI 自检”，展示解读正文、
  矛盾率、可验证/佐证 claims 与矛盾明细。无 LLM 时只显示确定性结果，不伪造解读。
- 回归：新增 NLI 报告章节测试 1 项；测试基线 2006 → 2007。
- **文档站修复**：5 个文档文件名带隐藏换行符（`glossary.zh.md\n` 等）导致 mkdocs
  nav 找不到页面，已改名修复；补齐 glossary / accounts / gbrain / gene-investigation
  四页英文版（此前只有中文版）；tutorial 存根页删除手写语言链接（改用 i18n 插件
  顶部语言切换）。`docs-build` 现在零告警。

### gside 模式升级 + CONCRETE 灰色主题

- **gside 模式参数同步**：`gside_species.py` 接受 gside 0.2.4 的 canonical
  `marker/ani/mash/sourmash/gtdbtk/all`，兼容旧别名
  `simple/panel/skani_gtdb/mash_refseq/standard`；在 gside 0.2.3 CLI 上自动映射为
  `marker/panel/mash_refseq/sourmash/gtdbtk/all`。`species_mode` 默认改为 `marker`，
  升级阶梯加入 gtdbtk；CLI/服务层同步接受新名称。
- **CONCRETE 灰色主题**：前端新增第三套 Swiss/brutalist 灰色模板（网格纸、硬边框、
  Helvetica 大标题、等宽数据、分屏海报式仪表盘首页、三态主题菜单）；暗色与浅色保留。
  图表、主题菜单与样本 HTML 报告同步（报告支持 `?theme=gray`）。
- 宋门菌血清型暂继续使用 SISTR；gspec `sen_sero_sistr` 的 serotype/2 支持发布后再迁移。
- **报告可见性/校验修复**：样本报告统一读取 `steps.serotype.value`（gspec shi_sero/ecoh），
  Deterministic Verifier 接受非沙门菌的 `N/A` serogroup；注释关闭时不再渲染空的
  Bakta/eggNOG 章节。`BACMAP_ANNOTATION_ENABLED=0` 的禁用占位规则改为 Snakemake `run:`
  块，避免脚本注入失败；真实样本 `26OTH0027` 重新分析后报告返回 200。

### 志贺菌血清型迁移到 gspec `shi_sero`

- **SHI registry 改路由**：`core/pathogens.yaml` 从 `serotype_engine: shigatyper` 改为
  `gspec_screens: [shi_sero]`；`report_inputs` 不再请求读段级 `shigella_serotype.json`，
  assembly 直入样本也不会再把 ShigaTyper 放进 DAG。
- **gspec 直接判组装子**：`shi_sero` 是 marker-set 血清型库，`gspec_typing` 对
  `assembly/contigs.fasta` 执行 screen + typing；`collect_summary` 将
  `schemes.serotype` 归一为 `steps.serotype.value` / `steps.dec.primary_serotype`
  （方法 `gspec shi_sero`），GOM 菌株索引、前端和报告统一读取。
- **旧 gspec 数据目录修复**：`shi_sero` 在 gspec 0.10.2 之前安装的副本缺少
  `serotype.json`，会报 `TYPING_NO_SCHEME`。已备份旧库并用
  `gspec db setup -d shi_sero` 重建；升级后需确认该文件存在。
- **删除 ShigaTyper 旧路径**：移除 `shigella_serotype` 规则、
  `run_shigatyper.py`、pixi `shigatyper` 依赖及其 7 个专属测试；志贺菌血清型只保留
  gspec `shi_sero`。
- **真实数据验证**：`26OTH0027`（assembly 直入）由 `shi_sero` 判定为
  `S. flexneri 3a`；失败任务中的 `PosixPath / float` 不再出现。
- 回归：新增 gspec shi_sero 适配 3 项、collect_summary 1 项、strain_index 1 项、
  sample_summary 1 项、FASTA DAG 1 项；删除 8 个 ShigaTyper 专属测试，净基线
  2002 → 2001（2009 → 2001）。

### 细菌基因组注释（QUAST → Bakta → eggNOG-mapper）

- **`workflow/rules/annotation.smk` 替换占位实现**：组装后先跑 QUAST
  （`assembly/qc` 报告），再跑 Bakta 基因注释（JSON/GFF3/FAA/TSV）与
  eggNOG-mapper 功能分类（COG/GO/KEGG/CAZy/Pfam），合并为
  `annotation/annotation.json`。
- 新增 `core/annotation_parse.py`：Bakta stats/CDS 与 eggNOG `#query` 表解析、
  COG/GO/KEGG 计数、Bakta 特征与 eggNOG query 关联；`collect_summary.py`
  的 annotation 段增加 `status`/`bakta`/`eggnog`，并容忍无 identity 的注释特征。
- 依赖新增 `bakta >=1.12`、`eggnog-mapper >=2.1.12`（conda）与
  `quast >=5.2`（PyPI）；AMRFinderPlus 升级到 `>=4.2.7`，既作为 Bakta 1.12
  内部 AMR 专家系统依赖，也保留直接 `amrfinder` 规则用于 AMR 基因 + 点突变检出。
  gspec `ncbi` 提供同一 Reference Gene Catalog 的存在性筛查（不含点突变）；
  `abricate` 依赖移除（CARD/VFDB/PlasmidFinder 早已由 gspec screen 承担）。
  数据库不随 `pixi install` 下载，新增
  `scripts/setup_annotation_dbs.py`，默认写入 `$BACMAP_HOME/refs/`，可用
  `BACMAP_BAKTA_DB` / `BACMAP_EGGNOG_DATA_DIR` 覆盖。
- `BACMAP_ANNOTATION_ENABLED=0` 时写 `disabled` 占位，不伪造注释结果；
  ADR-20 不再等待 gspec 注释子命令（冻结文档 v1.10.14）。
- 测试基线 2006 → 2015（+9：Bakta/eggNOG 解析合并 4、collect_summary 1、
  DAG 启用/关闭 2、报告注释章节 2）。

### Web 控制台重设计（Vue 3 + Vite SPA）

- 新增 `frontend/`：Vue 3 + Vite + TypeScript 控制台，构建产物提交在
  `src/bacmap/interfaces/web/static/console/`，由 FastAPI 托管；运行期零 Node（ADR-01）。
- `/` 重定向到 `/console/`；原 Jinja 任务台保留 `/legacy`。控制台包含仪表盘
  （KPI、7 天趋势、状态环图、待审批）、任务列表/提交抽屉/详情/审批/事件时间线、
  计划确认/拒绝、样本列表/详情（基因/注释/HTML 报告）、运行记录与来源比较、
  数据记录表单、GOM 对象/版本/载荷、研究会话（统计/图/产物/证据链）与
  Study/Cohort/Plan/Claim 只读总览、系统概览、样本检索。
- 新增 `/api/v1` 端点：`POST /tasks`、`POST /tasks/{id}/approve`、
  `POST /records/{kind}`、`GET /overview`、`GET /search`、`GET /samples/{id}`；
  `GET /tasks/{id}` 返回完整元数据。任务提交者由服务端固定为 `web`，不接受客户端伪造。
- 新增 pixi `web` 环境（仅 Node，独立求解避免主环境 libzlib 冲突）与
  `web-install`/`web-build`/`web-dev` 任务；CI 增加 web job 重建产物并校验一致性。
- 视觉延续 `DESIGN.md` 暗色 Linear 风格；ECharts 按需加载，无 3D、无 CDN/webfont。
- 测试基线 2000 → 2006（+6：SPA 根重定向/静态资源、任务提交、审批校验、
  概览/检索、记录提交）。

### Web 控制台续作（样本 / GOM / 研究）

- 新增样本列表与详情页：`GET /api/v1/samples/{id}` 返回 digest、完整 steps 与
  报告就绪标记；详情页展示物种/MLST/血清型、CARD/VFDB/质粒基因、Bakta/eggNOG
  注释摘要与 QUAST 报告，并链接 HTML 报告。
- 新增 GOM 对象列表/详情：类型筛选、版本、菌株、载荷键与 JSON 载荷。
- 新增研究总览与会话详情：会话、Study/Cohort/Plan/Claim 只读表格；会话详情展示
  统计表、OR/CI/p、标准图、报告/论文 Markdown、产物列表与 ledger；支持新建会话。
- 侧栏导航增加研究、样本、GOM；高级研究工具（系统发育、logistic、对象写操作）
  仍保留旧版 `/research`。
- 测试基线 2015 → 2016（+1：样本详情 API）。

### Web 收官：全宽布局、数据库仪表盘、报告主题、旧 UI 移除

- 内容区改为 **full width**（不再居中限宽），顶部搜索框与内容右边缘对齐；仪表盘改为
  全宽纵向堆叠，不再使用双列 grid。
- 仪表盘新增数据库概览：菌株总数、GOM 对象、AMR 基因命中、样本报告、研究会话、
  知识库条目、运行记录、化验结果，以及物种/血清型/MLST/AMR Top 分布。
- 单样本 HTML 报告改为与 Web 面板一致的暗色主题（token、卡片、状态徽章、等宽读数），
  移除 emoji 标题；打印时切换为浅色。
- 新增 **浅色主题模板**（TailAdmin 风格：浅灰画布、白卡片、细边框、柔和阴影），
  顶栏太阳/月亮按钮切换，`localStorage` 持久化；图表与 HTML 报告随主题同步
  （报告支持 `?theme=light`）。
- 报告内嵌到样本详情的“完整报告”页签（沙箱 iframe），不再单独打开页面；直接访问
  `/samples/{id}/report` 会 307 回 `/console/samples/{id}?tab=report`，`?download=1`
  仍为附件。旧模板报告（无 `bacmap-report` 版本标记）首次访问时自动重渲染为暗色主题。
- 仪表盘对 `/api/v1/stats` 失败降级：任务区独立加载，数据库统计显示不可用提示而非全 0。
- 移除旧 Jinja 任务台：删除旧任务/计划/记录/运行/GOM/样本/搜索/概览模板与 HTML 路由，
  旧路径 307 到 `/console/...`；仅保留登录、样本 HTML 报告和高级研究页（Jinja）。
- 依赖升级：`gside ==0.2.3`、`gspec ==0.10.2`、`gseek ==0.10.5`、`gmlst ==0.6.1`，
  新增 `gmeta ==0.1.0`（mNGS 可选依赖）。
- 新增 `GET /api/v1/stats`；测试基线 2016 → 1995（-21：删除旧 HTML 页面/表单测试，
  API 覆盖保留），报告内嵌/主题/检索/DAG 回归净基线 2002 → 2001（删除 8 个 ShigaTyper 旧测试，新增 7 个 shi_sero/gspec 测试），v1.10.18 +5（共 2006）。

## [0.1.5] - 2026-11-09

### 长读/混合组装规则（PLAN #4）

- **新增 `workflow/rules/assembly_long.smk`**：三条组装规则，按 samples.tsv
  输入形态自动路由：
  - `assembly_flye`：纯长读组装——ONT R10.4.1 SUP → `--nano-hq`（Q20+ 默认），
    旧 R9.4 可配 `ont_mode: raw`；PacBio HiFi → `--pacbio-hifi`；
    基因组大小由 flye 2.9+ 自动估计（`genome_size` 可选配置）
  - `assembly_unicycler`：混合组装（短读骨架 + 长读补洞/桥接）
  - `assembly_trycycler`：多组装器一致性合并（高级路径）
- **samples.tsv 新增 `longread` 列**：长读 FASTQ 路径（自动检测或手动填写），
  位于 R2 与 assembly 之间；旧版表自动升级、行数据对齐
- **`_scan_unpaired_longreads`**：目录扫描时自动检测未配对且中位读长 ≥1kb
  的文件为长读（排除已配对的短读），探测平台填入 `platform` 列
- **Snakefile 路由**：`_contigs_src()` 按输入形态分派到
  shovill/flye/unicycler/直接 FASTA，下游规则无差别消费 `contigs.fasta`
- config 新增 `flye`（minlen/ont_mode/genome_size）、`unicycler`（mode）、
  `trycycler`（min_identity，百分比）参数
- **依赖**：pixi conda 新增 `flye >=2.9.5`、`unicycler >=0.5.1`；trycycler 的
  conda 包目前要求 Python <3.11（bacmap 为 3.12），未随默认环境安装，规则保留为
  需另行提供可执行文件的高级路径
- 测试基线：1989 → 2000（+11：长读检测/纯长读登记/混合自动检测/平台探测/
  向后兼容/PacBio 识别/短读不误判，以及 4 个 DAG 路由测试：flye 省略
  --genome-size、PacBio 标志、混合→unicycler、platform=trycycler 路由）

## [0.1.4] - 2026-11-09

### CLI 基础设施（PLAN #12/#13/#17/#18/#19）

- **`bacmap stats`**：全库统计汇总——任务/计划/运行/GOM/化验/知识库/研究会话/
  文件大小，`--json` 支持（PLAN #18）
- **`bacmap detect <dir>`**：FASTQ 平台探测（读长启发式：Illumina/ONT/PacBio/unclear），
  纯标准库 gzip 支持，多文件多数投票（PLAN #4）
- **`bacmap species list|resolve`**：物种注册表查询——3 字母码、显示名、gside
  标签、MLST 方案、SNP 组；按码/名称/标签过滤（PLAN #13）
- **`bacmap reference list`**：参考基因组清单与就绪状态（PLAN #19）
- **`bacmap completion bash|zsh`**：shell 补全脚本输出（PLAN #12）
- **`bacmap ops`** 命令组：doctor/backup/restore/results/events 收纳为二级命令，
  旧顶层命令保留兼容（PLAN #17）
- **plan 前缀解析**：`plan show/confirm/reject` 支持短前缀（同 task 命令）
- **sample 分页**：`sample ls --limit/--offset`（PLAN #15）

### i18n 双语言变量（PLAN #1）

- `[ui] language`（全局默认）+ `[ui] cli_language`（CLI 专用覆盖）
- 环境变量优先级：`BACMAP_CLI_LANG` > `BACMAP_LANG` > `cli_language` > `language`
- 新增 `system_language()` 函数（供 Web/TUI 使用，不读 CLI 覆盖）

### 安装与硬件需求（PLAN #2/#10）

- **`scripts/setup.sh`**：一键安装脚本（curl 可执行）——检查 pixi → 克隆 → install → doctor
- **`docs/getting-started/llm-install.md`**：LLM 可执行安装指令（贴给任意智能体即装）
- 安装文档双语增加硬件需求表：最低 8核16G / 工作站 16核64G / 服务器 64核256G
  （GTDB-Tk full-tree）+ 本地 LLM 配置（5060Ti 16G+64G / 2×DGX Spark）
- 一键安装命令写入安装文档

### 计划流程图 SVG（PLAN #3）

- `plan show --diagram out.svg`：任务流→SVG 流程图（确定性渲染、离线无依赖）
- 任务框（类型+摘要）→ 箭头 → 结尾状态节点

### 架构设计文档（PLAN #5/#8/#11/#14）

- **`docs/concepts/flexible-workflow.zh.md`**：两层弹性模型——固定层（registry 驱动
  的确定性监测流程）+ 弹性层（AI 生成临时 smk → 人审 → 沙箱执行 → 一次性归档）
- **`docs/concepts/gbrain.zh.md`**：GBrain 双核心——长期知识库 + 知识图谱
- **`docs/concepts/accounts.zh.md`**：三模式用户管理——单用户/多用户（角色+审核）/多系统（联邦）
- **`docs/guide/gene-investigation.zh.md`**：基因调查编排——六步端到端方案

### 术语表与嵌入指南（PLAN #16/#20）

- **`docs/concepts/glossary.zh.md`**：isolate/sample/task/plan/参考基因组等核心概念定义
- **agent-plans §10**：bacmap 控制台嵌入各 harness——DSH（已实现）/ Hermes（Desktop
  plugin）/ Pi（glimpseui WebView）+ 远程部署（SSH 隧道/token/VPN）

### 仓库整理

- `scripts/README.md` 更新（安装+数据准备分区）
- 参考基因组管理链、物种命名流转链写入术语表

### 下版本预告（0.2.0）

- Vue 3 + Vite SPA 前端重设计（TresJS/Three.js + ECharts + D3.js）
- flye/unicycler/trycycler smk 组装规则（长读/混合组装路径）

- 测试基线：1959 → 1989（+30：fastq_probe/species/completion/stats/plan_flow/i18n_config）

### 仓库整理（configs/、tools/、scripts/、开发文档出库）

- 配置模板集中到 `configs/`（`config.example.toml` 移入；`pyproject.toml`
  force-include 与 `bacmap config path/init` 的源码树解析路径同步，打包路径不变）。
- 新增 `tools/dsh-bacmap-console`：DSH Web 侧栏内嵌 bacmap 控制台的本地 bundle
  （`/bacmap` 前缀反向代理剥除 X-Frame-Options/CSP frame-ancestors、URL 重写、
  经 DSH 连接鉴权放行；bacmap 未运行时给出提示页）。
- 新增 `scripts/`：数据准备辅助脚本（`renamefq.py`——FASTQ 配对重命名、
  `extract_genes.sh`——GFF 基因区间提取、`json2tsv.py`——NCBI JSON 扁平化，
  含 README）；非运行时组成部分，入库前手动执行。
- 新增 `docs/tutorial/`：长教程区（mkdocs nav 新增 Tutorials 节）。首篇
  「本地 Strata + DeepSeek 后端」教程（中文全文 335 行：个人电脑量化模型部署 →
  NCBI 沙门菌 ~100 株下载 → analyze/mine/write 全流程）；配英文摘要页
  （双语制，全文以中文为权威）。
- `PLAN-agent-research.md` 移入 `dev/`（该方案 P0–P5 全部完成，转为本地归档，
  不再随仓库分发；`dev/` 按规则不入库）。

### P4 完成：高级统计外部化（ADR-22）+ 研究任务类型（ADR-23）

### Research 证据链（自 feat/agent-research-bridge 并入）

### 投稿包导出分析结果（自 feat/agent-research-bridge 并入）

- 投稿包新增 `supplementary/analyses.json` 与 `analyses.tsv`，包含 Study 下所有
  `research_analyses` 结果与 hash；manifest 增加 `analyses` 摘要列表。
- 投稿包详情页显示 Supplementary analyses 表。

### 分析结果对象化（自 feat/agent-research-bridge 并入）

- 新增 migration 10 `research_analyses`：保存 analysis_id、类型、输入路径 + SHA-256、
  params、result、`result_sha256`、作者/时间，并自动写 `ANALYSIS_OF` 证据边。
- Web stats 表单可填 Study 自动保存；phylo 页面新增“保存到 Study”；
  `/research/studies/{id}/analyses` 与 `/research/analyses/{id}` 查看历史/详情。
- CLI：`research analysis list|show|save`；stats 命令支持 `--study`。
- MCP 只读：`bacmap_research_analyses`、`bacmap_research_analysis`。
- 测试基线：1868 → 1873（1 skipped：gapit live smoke）。

### Research 证据链

- 研究对象自动写入 `evidence_edges`：cohort/plan/session/claim/experiment/checklist/package/
  request 与 study 的关系；session 的 cohort/plan 来源；experiment 与 plan 的关系。
- Edge 幂等；Study/Session 页面显示证据链表；MCP `bacmap_research_evidence` 与 CLI
  `research evidence` 可读取。

- **新增第六任务类型 `research`**（ADR-23，冻结）：类型化 `ResearchParams`
  （`analysis=session|advstats`），**仅经计划执行**（`bacmap_create_plan` → 人工
  确认 → 引擎）；`PlannableTask`/MCP `plannable_task_types`/`[plans.auto_confirm]
  task_types` 同步纳入；advstats 数据表进入计划输入指纹（确认时数据已变则冲突）。
  - `session`：从既有 run 创建确定性 AMR 关联草案（P1 薄链路，引擎内执行）；
  - `advstats`（ADR-22，冻结）：类型化 `AnalysisSpec`（方法/列名，未知字段拒绝）
    → bacmap **确定性渲染 R 脚本**（`mixed_logistic`=lme4 glmer、`iptw`=WeightIt+
    survey、`matching`=MatchIt、`survival_km`=survfit+survdiff、`cox`=coxph+cox.zph）
    → `bacmap-stats:r45` 镜像沙箱拟合（数据零拷贝只读挂载、无网络）→ 归一
    `bacmap.advstats_result/1`。脚本非 agent 编写：**计划确认即授权，无挖掘门**；
    spec/脚本/输出 SHA-256 入 research ledger。
- **新增 `research/advstats.py`**（渲染器/归一器）与 `docker/stats/r45` 构建资产
  （R 4.5 + lme4/survival/MatchIt/WeightIt/survey/jsonlite）；主环境零统计模型依赖。
- **CLI `bacmap research advstats render`**：渲染确定性 R 脚本供提交前人工审阅。
- 新增 ADR-22/ADR-23 与 v1.10.11 修订记录（中英）；AGENTS.md（六类任务）、
  research-workbench §12 / cli / mcp 双语同步。
- 真实镜像冒烟：`bacmap-stats:r45` 容器内 Cox 拟合 120 例模拟队列
  （n=120、events=71、tx HR=1.386 p=0.179、PH 全局 p=0.173），spec/script
  SHA-256 与镜像名入 ledger。
- 合并 `feat/agent-research-bridge` 增量 6 提交（见上）；跳过其内置
  IPTW/KM/matching 实现（与 ADR-22 冲突，容器外部化为唯一路径）。
- 测试基线：1908 → 1959（advstats/research 计划 + bridge 增量用例）。

### P4 第一片：样本量/把握度与外部验证（确定性）

- **`bacmap research stats power`**：两比例比较的事先样本量/把握度（正态近似，
  纯标准库 `statistics.NormalDist`，无连续性校正并如实注明）。三种输入：
  `--p1/--p2` 显式比例、`--baseline/--odds`（OR 推导暴露组比例）、`--session`
  （以既有会话观察比例为设计假设，结果标注 `design_input_from_session` 且明示
  **不是事后功效**）；给 `--n1/--n2` 则返回达到的把握度。极端比例（<0.05/>0.95）
  或每组 n<30 输出 `caution` 提示精确法。输出 `bacmap.power_two_proportions/1`。
- **`bacmap research stats validate`**：外部验证——推导队列 vs 验证队列两个 2×2
  关联的 Woolf 齐性检验（Q 统计量、χ² df=1、固定合并 OR、各队列 OR/CI 带 0.5
  校正）。文档明确"一致 ≠ 复现成功（验证队列可能把握度不足）"。
  输出 `bacmap.external_validation/1`。
- **MCP `bacmap_research_power`**（D2 只读计算）：与 CLI 同一编排（`power.compute`）
  ——数值/session 参数，无路径，数据不出站。
- STROBE 草案 item 10 note 指向 `stats power`；docs（research-workbench/cli/mcp
  双语）与 PLAN P4 同步。
- 测试基线：1886 → 1908（power 自洽/单调/换算 + session/validate 端到端 + CLI）。

### P1 收官（skills 目录约定）与 P2 B 档图片真实镜像实测

- **`bacmap agent install --with-skills` 按各 harness 实测约定直写 skills**：
  Hermes `~/.hermes/skills/<role>/SKILL.md`（项目级 `./.hermes/skills` 需先
  `hermes skills trust`）、Pi `~/.pi/agent/skills/<role>/`、OpenCode/generic 走
  跨 agent 约定 `~/.agents/skills/<role>/`；DSH/Codex 无经验证的文件系统 skills
  机制，保持 `.bacmap/skills/` 便携副本（DSH 经 MCP resources / `--inline-roles`）。
- 真机验证：用户级安装后 `hermes skills list` 枚举到全部 6 个 bacmap 角色
  （analyst/curator/epidemiologist/literature/miner/writer，source=local，enabled）。
- `HarnessSpec` 新增按 scope 的 `skills` 目录声明；doctor 沿 manifest 校验实际路径。
- **B 档图片 mine 真实镜像实测通过**（PLAN P2）：本地
  `podman --cgroup-manager=cgroupfs build -t bacmap-figures:py312`（镜像
  `e25aa46bf9e6`，matplotlib 3.10.0）→ mine 计划（driver 从 `context.json` 自动
  发现挂载的 figure_spec）→ 沙箱渲染 `figure_custom.pdf`（12,963 字节）→ 挖掘门
  人工签字 → `bacmap research figure attach` 登记完整 provenance（spec/data/code/
  output 四哈希 + `bacmap.figure_artifact/1` manifest）。`docker/figures/README.md`
  补充 rootless Podman 无 systemd 会话时的 cgroupfs 构建方法。
- **`attach` 产物质量门（PDF/PNG/SVG 校验，P2 收官）**：新增
  `research/figure_checks.py`（纯标准库）——PDF 检查文件头/页数/字体嵌入（无
  `/FontFile*` 且非 Type3 内联字形即拒；matplotlib 默认 Type3 与 fonttype 42 通过）；
  PNG 检查签名/chunk CRC/IHDR 色彩类型与 pHYs 密度（低于契约 dpi 或缺 pHYs 即拒，
  ppm 整数比较对齐 matplotlib 11811=300dpi 生态约定）；SVG 检查良构并拒绝
  DTD/ENTITY（规避 XML 实体攻击面）。被拒产物给出可操作的重导出提示；真实沙箱
  PDF/SVG 产物实证通过。
- 文档 `docs/guide/agent-plans`、`docs/guide/research-workbench` 双语同步；
  **PLAN P1/P2 全部完成**。
- 测试基线：1867 → 1886（质量门用例；四门 + docs-build 全绿）。
- 测试基线：1863 → 1867（harness skills 目录约定用例）。

### 工作流面向全病原注册表泛化与按物种校验（v1.10.10）

- **删除 `vpara.smk` 与打包私有库链路**（`build_gspec_db.py`、
  `refs/vpara_virulence.fasta`、部署期建库）：VPA 毒力标记（tdh/trh/tlh）改用官方
  gspec catalog 的 `vpa_vf` 库，O/K 血清型用 `vpa_ok`；registry VPA 默认库改为
  `[vpa_vf, vpa_ok, vpa_pai]`。种以下判定全部经 registry + 官方 gspec 库路由，
  **无逐菌专用 smk 规则与占位文件**，pipeline 面向 pathogens.yaml 全部登记病原菌。
- **删除 ECO ecoh 占位规则**：O/H 能力状态/表型统一出自 `gspec/typing.json`
  （`ecoh_serotype_summary` 归一）；VPA 血清型 unavailable 语义由 collect_summary
  按物种生成；`routing.report_inputs` 移除逐菌专用文件输入。
- **Deterministic Verifier 按物种路由**（修复非沙门菌假阴性）：MLST 期望位点取自
  gmlst TSV 的 SCHEME 列（已登记方案用其位点表；未登记方案按实际位点全量校验，
  绝不套用别种位点表——此前对 VPA 套用沙门菌位点致全 missing）；serotype 尊重
  `sistr_status=not_applicable`。
- **HTML 报告修复**：基本信息"物种判定"读 gside `species` 键（旧 `verdict` 键兼容，
  此前 VPA 显示 N/A 而 Verifier 实为通过）；Contigs 数列索引（此前显示 "DNA"）；
  MLST alleles 展示剔除 file/scheme 元列。
- **`run_gspec_typing` 对 no_scheme gene 库保留 screen 基因命中**（gspec ≥0.10 的
  screen JSON 无 genes 键，从 hits/TSV 归一）——毒力存在性判定只依赖 screen。
- 真实单株验证：VPA 组装 → ST1762、tlh⁺/tdh⁻/trh⁻（vpa_vf）、O3:KUT（vpa_ok，
  O high/K low）、报告与 Verifier 四项全过。
- 冻结设计新增 v1.10.10 修订记录；AGENTS.md 已知占位表同步。
- 测试基线：1860 → 1863。

### Hermes / DSH 真实数据端到端验证与沙箱挂载修复

- **Hermes 0.23.0 全链路实测通过**（无头 `-z`，智谱端点）：MCP 连接（29 工具）、
  `.hermes.md` 指导注入、只读 research 工具（figure_recipes 可见 forest/strobe_flow
  experimental）、analyze 计划 → 人工确认 → 8 株真实副溶血弧菌组装 `succeeded`
  （MLST ST423/1762/1784/2157/2128/2799、CARD/毒力基因谱）、结果汇总引用
  plan/task/run 标识。agent 在 cloud Profile 下自纠 D3→D2，从未自行确认计划。
- **mine 开放路径实测通过**：rootless Podman 沙箱执行 → `mine_report.json` 产出 →
  挖掘门 `awaiting_approval` → 人工签字（`task approve`）→ `succeeded`。
- **修复沙箱挂载覆盖 bug**：`mine.input_paths` 指向 `home/results`（或 `gom.sqlite`）
  时，数据集挂载与规范挂载在 `build_access` 内同 key 互相覆盖，导致容器内
  `/data/results` 缺失。现同源数据集复用规范 guest 路径并在 `context.json` 中指向
  真实可读路径；新增回归测试（tests/unit/test_datasets.py）。
- **DSH 0.2.2-rc.1 浏览器对话层实测通过**：`cordis.patch.yml` 插件合成（`--dump-config`）
  + 实例经 `pixi run` 拉起 bacmap MCP；用户 Web 会话中模型成功调用
  `bacmap_capabilities`，会话记录证实全部 29 个工具（含 research 系列）注入模型
  上下文（模型"列举不全"是回复行为，非链路问题）。文档（agent-plans 双语）改推
  `pixi run` 包装启动 MCP；§9 验证表更新并记录"仓库移动后 pixi 环境入口 shebang
  失效"的重建方法。
- 测试基线：1858 → 1860。

### 图片 recipe 第二批：builtin SVG 可执行 + 确定性渲染 + B 档模板

- **`forest` 与 `strobe_flow` recipe 从 planned 升为 experimental（builtin SVG）**：
  森林图（效应量 + 95% CI，log 轴 + OR=1 无效应虚线）与 STROBE 流程图（run 名册 →
  排除“无基因型/可用表型” → 分析 n，计数全部由 `runs.sqlite` 与 session 统计派生）。
  builtin renderer 只消费 `FigureSpec`，不回读数据库，同一 spec 恒得同一图。
- **`bacmap research figure render <session> --recipe <id>`**：用 builtin recipe 确定性
  渲染 session 图片，写出 `research/<session>/figure_<recipe>.svg`，登记 `figure`
  产物并写 `figure.rendered` ledger（recipe/renderer/output+spec hash）；拒绝 planned
  与非 builtin recipe（容器/pixi/host 仍走沙箱 + `figure attach`）。幂等可重复渲染。
- **`bacmap research figure template [--output FILE]`**：输出 B 档自定义图脚本模板
  （自包含：仅标准库 + matplotlib、不导入 bacmap、校验 `spec.style.formats` 允许的
  输出格式、打印 provenance 摘要），配合 `mine` 沙箱与 `figure attach` 使用。
- **research.sqlite 迁移 v6**：`research_artifacts` 主键从 (session_id, kind) 扩为
  (session_id, kind, path)，一个 session 可同时保留多张标准图（association_bar 与
  forest 等）；迁移前自动备份旧库。
- 投稿包按源文件名复制产物，修复同 kind 同后缀产物互相覆盖的问题。
- `heatmap`/`pca`/`volcano`/`tree_rectangular` 仍为 planned：容器 recipe 待 CI 发布
  固定镜像后启用，不假装已运行。
- 文档：`docs/guide/research-workbench`（recipe 表、figure render/template 章节）、
  `docs/reference/cli` 双语同步；`PLAN-agent-research.md` P2 勾选更新。
- 测试基线：1838 → 1858。

### Checklist 编辑与签字

- Study 页新增 STROBE checklist 编辑器：逐项 status/evidence/note、保存草稿、签字确认、
  重置；签字要求没有 `missing` 项（migration 8 `checklist_reviews`）。
- 投稿包合并编辑后的 checklist，并在 manifest 记录 `checklist_review` 状态。
- 测试基线：1852 → 1857（1 skipped：gapit live smoke）。

### Markdown 渲染与投稿包历史

- Session 页安全渲染报告/论文草案 Markdown（转义原始 HTML、限制链接协议）。
- 投稿包版本化：migration 7 `submission_packages`；Study 页/`/packages` 历史、
  详情页与 ZIP 下载；记录 package_id、label、created_at、文件数、blockers、
  manifest SHA-256。
- 测试基线：1843 → 1852（1 skipped：gapit live smoke）。

### Figure 迭代（Web）

- Session 页新增 **Figure 迭代** gallery：上传 SVG/PNG/PDF 草稿（≤10 MiB）、保存反馈、
  最终 attach 或拒绝；草稿记录 SHA-256、作者与状态（migration 6）。
- 只有 final 草稿进入投稿包；最终 attach 复用 `figure_custom` + provenance manifest。
- CLI：`research figure drafts|feedback|finalize|reject`；MCP 只读
  `bacmap_research_figure_drafts`（D2）。
- 测试基线：1838 → 1843 passed（1 skipped：gapit live smoke；当前环境已切 gspec）。

### Web Phylo / Logistic 页面

- 新增 `/research/phylo`：alignment profile → PhyloPlan → 校验 → BEAST2 XML 下载 /
  IQ-TREE 命令；支持 dates、partition 候选与可选 `beast -validate`。
- 新增 `/research/stats`：CSV/TSV 路径 + outcome/predictors → 多变量 logistic
  OR/CI/p 表格、诊断与 JSON。
- 研究首页新增两个工具入口；结果页面保留输入与隐藏 profile/plan JSON，可连续操作。
- 测试基线：1834 → 1838。

### Cohort builder（Web）

- Study 页新增 Cohort builder：从 `runs.sqlite` 选择 run/样本，复选框生成 members；
- 创建前预览重复 isolate/dataset、缺失 run、成员/去重计数；预检不通过时阻止创建；
- 支持 cohort 名称与 rules JSON；创建后回到 Study 页；
- 保留原有 members JSON 表单作为高级兜底。
- 测试基线：1831 → 1834。

### 研究请求（Agent → 人）与 Web 收件箱

- 新增 `bacmap.research_request` 草案：MCP `bacmap_research_request` 只写
  `research.sqlite`，不创建 Study/Cohort/Plan、不执行分析；`bacmap_research_requests`
  只读列出。
- Web 研究首页新增“研究请求收件箱”：人工可编辑 members/plan spec 后“确认并创建”，
  自动创建 Study → 冻结 Cohort → 冻结 Plan → 可选 session；也可拒绝并记录原因。
- CLI：`bacmap research request create|list|show|approve|reject`。
- 冻结设计新增 v1.10.9：MCP 只提议草案，执行/写对象仍由人工在 Web 确认。
- 测试基线：1824 → 1831。

### Research Web 工作台完善

- 研究首页：run 下拉选择、Study 关联、Cohort/Plan 可选绑定、研究说明；创建 session 时
  直接写入完整来源链。
- Session 页：标准图/自定义图 gallery、FigureSpec 表、自定义图 provenance（renderer/
  spec/data/code/output hash）、全部产物下载、研究说明、Study/Cohort/Plan 链接。
- Study 页：关联 session 缩略图、STROBE 草案（met/partial/missing）、投稿包查看与 ZIP
  下载。
- 新增投稿包页面与 `/package.zip`；通用 artifact 下载路由。
- 测试基线：1818 → 1824。

### 研究功能实测修正

- `bacmap research create` 支持 `--study/--cohort/--plan`，session 可绑定完整来源链；
  `figure attach` 支持 `--recipe`，agent 自定义图默认登记为 `custom`（此前会沿用
  `association_bar`，provenance 不准确）。
- 真实 Pi + Podman 研究链路通过：Study/Cohort/Plan/Claim/Experiment → G0–G3 →
  FigureSpec/recipe/draft/attach → logistic → PhyloProfile/Plan/BEAST2 XML → 投稿包。
- 测试基线：1816 → 1818。

### Podman 沙箱兼容性

- Rootless Podman 在无可用 systemd 会话时，`mine` 沙箱自动以
  `--cgroup-manager=cgroupfs` 重试一次；同时将 `USER`/`LOGNAME` 对齐到真实账户，
  修复 `$USER` 异常导致的 subuid/subgid 解析失败。真实 Pi + Podman 冒烟通过
  （mine 脚本产出 `podman_ok.txt`，挖掘门签字后任务 `succeeded`）。
- 测试基线：1812 → 1816。

### Agent 桥接与发表级图片契约（`feat/agent-research-bridge`）

#### 新增
- **`bacmap agent list|export|install|doctor`**：为用户自选的 agent harness 生成薄适配
  文件（Hermes/Pi/DSH/Codex/OpenCode/generic）。事实来源仍是 bacmap 的 MCP instructions、
  `bacmap_role_<role>` prompts 与 `skill://bacmap/<role>/SKILL.md` resources；安装文件带
  `.bacmap-agent.json` 清单与 hash，`doctor` 检测缺失、篡改与版本漂移。
- **Pi 实测修正**：`bacmap agent install --inline-skills/--inline-role` 把角色正文内联到
  指导文件；静态安装文件不再硬编码 `Profile=cloud/D1`（以运行中 server instructions 为准）。
  Pi 1.5.0 `--print` 模式不会自动注入 skills/MCP resources，内联是已验证的可用路径。
- **外部角色说明书**：`build_system_prompt(role, audience="external")` 不再把
  `role.yaml` 的内部权限字段说成强制，明确外部 agent 的实际权限由 MCP Profile 决定；
  MCP prompts 改用 external 版本。
- **发表级图片契约**：新增 `bacmap.figure_spec/1`（数据、统计量、来源 ID、样式/期刊约束）
  与 `bacmap.figure_artifact/1`（spec/data/code/output SHA-256）。会话自动保存
  `figure_spec.json`；`bacmap research figure spec|attach` 与只读 MCP 工具
  `bacmap_research_figure_spec` 暴露契约；自定义图脚本走既有 `mine` 沙箱 + 人工签字。
- **研究统计与投稿包**：`bacmap research stats logistic`（确定性 IRLS：系数、OR、95% CI、
  p 值、事件/收敛/分离诊断）与 `bacmap research package`（STROBE 草案、发表门 blocker、
  artifact 复制与 SHA-256、数据/代码可用性声明）；只读 MCP 工具
  `bacmap_research_logistic`（D3）与 `bacmap_research_reporting_checklist`（D2）。
  混合效应/IPTW/匹配/生存分析仍为后续，不允许 agent 伪造。
- **系统发育参数规划**：`bacmap research phylo profile|plan|validate|xml|iqtree`；
  `PhyloProfile` 统计 taxa/位点/缺失/可变/信息位点与日期，`PhyloPlan` 类型化模型/时钟/
  先验/链长/seed，`validate` 强制边界，`xml` 从版本化模板渲染 BEAST2 XML 并记录
  plan/XML/alignment hash；支持 HKY/GTR、+G、strict clock、constant coalescent。
  只读 MCP 工具 `bacmap_research_phylo_profile`/`bacmap_research_phylo_plan`（D3，仅
  local-trusted）。AI 负责规划，XML 由 bacmap 渲染，人确认后工作流执行。
- **图片 recipe 运行时**：recipe 声明 `builtin`/`container`/`pixi`/`host`；
  `bacmap research figure runtimes` 检查 Apptainer/Podman、pixi 或 host R/Python 是否可用。
  R/ggtree 与 matplotlib 走 `bacmap-figures:r4`/`py312` 容器，主环境不引入 R 依赖。
- **图片草稿迭代**：`bacmap research figure draft` 把中间图复制到 `research/<session>/drafts/`
  并写入 ledger（hash + note）；最终图仍用 `figure attach` 登记完整 provenance。
- **图片运行时资产**：新增 `docker/figures/py312` 与 `r4` Dockerfile（matplotlib/seaborn、
  R/ggtree/ggplot2）及构建说明；发布镜像仍属 CI/部署步骤。
- **style brief**：`FigureStyle` 增加 `journal`/`panel_layout`/`palette_colors`/`reference_note`；
  示例图只提取风格描述，不复制、下载或再分发原图；草稿迭代后只登记最终图。
- **版本化图片 recipe 注册表**：`bacmap research figure recipes` 与只读 MCP 工具
  `bacmap_research_figure_recipes`；`association_bar` 为 stable，`forest`/`heatmap`/`pca`/
  `volcano`/`tree_rectangular`/`strobe_flow` 为 planned，`custom` 为沙箱兜底。建树与渲染
  分离：树推断走 IQ-TREE/Gubbins 工作流，`tree_rectangular` 只负责渲染 Newick。
- 文档：`docs/guide/agent-plans`、`docs/reference/cli`、`docs/guide/research-workbench`、
  `docs/reference/mcp` 双语更新；新增分支方案 `PLAN-agent-research.md`。

#### 变更
- MCP server instructions 统一由 `agent/instructions.py` 生成，并指向角色 prompts/resources。
- `ArtifactKind` 增加 `figure_spec`、`figure_custom`、`figure_manifest`。
- 测试基线：1761 → 1857（新增 agent harness/CLI、figure spec/attach 与 recipe 用例）。

### 物种→工具参考数据用户覆盖层（`tool_selection.yaml`）

#### 新增
- **`tool_selection.yaml` 用户覆盖层**：`core/pathogens.yaml` 继续作为包内默认值，
  用户/项目选择写入 `$BACMAP_HOME/config/tool_selection.yaml`（schema `bacmap.tool_selection/1`），
  按工具分节：`gspec`（`mode`/`databases`）与 `gmlst`（`mode`/`modes`/`schemes`），
  支持 `replace`/`extend`、物种级与单样本覆盖（优先级 sample > species > registry）。
  旧 `db_selection.yaml`（`bacmap.db_selection/1`）自动翻译为 gspec-only 并告警。
- **`bacmap selection options|select|show|validate`**：统一查看/编辑 gspec 库与 gmlst
  模式/scheme；`bacmap db ...` 保留为 gspec-only 别名。校验未知库名/scheme、
  mode/scheme 类型不匹配、未下载 scheme、cgmlst/wgmlst 冲突、license、cluster-on-reads。
- **只读 MCP 工具 `bio_tool_selection_options`**（L1/READ/D0）：AI 获取同一份选项文档；
  写路径仍是本地 CLI 或任务，AI 不直接落盘。
- **gmlst 覆盖层接线**：`typing_mlst`/`typing_cgmlst` 从 `effective_gmlst` 取 mode/scheme，
  未选时写 `N/A`（不再用 `salmonella_2`/`ecoli_2` 兜底）；新增 `typing_tgmlst` 规则；
  cgMLST cohort 组要求组内 scheme 一致，混合 scheme 的组跳过。
- **cluster 库分流**：`run_gspec_typing.py` 按 catalog `kind` 选择 `gspec screen --format json`
  （cluster，typing 已在 screen 内完成）或 `screen` + `gspec typing`（gene），绝不对 cluster TSV
  跑 `gspec typing`。
- **VPA O/K 表型**：`vpa_ok` 的 `o_group`/`k_group`/`serotype` 并入 `steps.vpa_serotype`
  （占位规则保留兼容；gspec 结果优先，带 `source: gspec:vpa_ok`）。

#### 变更
- `gspec_typing` 规则新增 `species_id.json` 输入：DAG 解析期合并用户覆盖层，运行时由 gside
  verdict 选物种码；`Unknown`/低置信度不路由物种特异库（通用 AMR/VF 仍运行）。
- `pathogens.yaml` 默认值不变（VPA 仍为 `vpara_virulence`）；`vpa_ok`/`vpa_pai` 通过覆盖层按需启用。
- 运行记录新增 `tool_selection_effective` 与 `tool_selection_sha256`（旧 `db_selection_*` 兼容读取）。
- 文档双语同步：`docs/reference/configuration`（新增 §13）、`docs/reference/cli`、
  `docs/reference/tools`、`docs/reference/mcp`、README；架构冻结文档新增 v1.10.8 修订记录
  （ADR-03 扩展）。
- 测试基线：1703 → 1761（新增 tool_selection 模型/校验/CLI/MCP 工具与工作流路由用例）。

### CLI：长驻界面统一为 `bacmap start <iface>` + 显示语言设置
- **破坏性变更**：顶层接口命令 `bacmap mcp|web|tui|console` 移除，统一为
  `bacmap start mcp|web|tui|console`（不留别名）。一次性命令（overview/task/
  plan/record/run/gom/isolate/sample/search/doctor/backup/restore/results/events/
  config/research）保持顶层不变。`python -m bacmap.interfaces.mcp` 模块入口不变。
- Hermes/Pi/DSH 等外部客户端配置需同步：`args` 由 `["mcp"]` 改为
  `["start", "mcp"]`（shell 形式 `bacmap mcp` → `bacmap start mcp`）。
- **新增显示语言**：`config.toml` 新增 `[ui] language`（`en` | `zh`，默认 `en`），
  环境变量 `BACMAP_LANG` 显式设置时优先（与 `BACMAP_DEBUG` 同构）；CLI 帮助、
  提示与错误文案按语言输出，JSON 输出不受影响。非法取值确定性回落 `en`。
- 全部 CLI 模块文案双语化（`interfaces/i18n.py::T(en, zh)`）；`bacmap --help`
  尾注区分"长驻界面"与"一次性命令"两组。
- 文档同步：README 双语、getting-started/guide/concepts/operations/reference
  中英文页面（含 `docs/reference/cli.md` 重构与 `configuration.md` 新增 §12）；
  `config.example.toml` 新增 `[ui]` 段。
- 测试基线：1703 → 1708（`start` 入口/旧命令拒绝/语言切换与回落/配置解析新增
  用例；原中文文案断言改为显式 `BACMAP_LANG=zh` 下断言）。

### 外部工具依赖升级（gside / gspec / gmlst / gseek）
- PyPI 依赖升级：`gside 0.1.4 → 0.2.2`、`gspec 0.5.6 → 0.6.8`、
  `gmlst 0.5.5 → 0.6.1`；新增 `gseek ==0.10.4`（gside 0.2+ 依赖，gspec/gmlst
  可选引擎共用）。
- 适配 gspec 0.6 数据库重命名：`ecoli_dec → eco_dec`、`lm_doumith → lmo_sero`。
- 补齐 Listeria MLST 声明 `lmonocytogenes_1`，并修复未声明物种静默回退
  `salmonella_2` 的问题；无 scheme 时如实输出 `scheme=none / ST=N/A`。
- CLI 签名复核与真实单株 analyze 冒烟通过：gside 0.2.2 鉴定
  *E. coli*（high）、gmlst 0.6.1 得 ecoli_1 ST795、gspec 0.6.8 eco_dec 得
  EPEC_atypical（high），ecoh 如实 `no_scheme`，分析门 pass。
- 注意：gspec 0.6.7 起 `ecoh`/`ncbi`/`resfinder` 不再随 wheel 捆绑，需要时在安装期
  `gspec db fetch -d ...`。

### 配置模板与分层配置路径
- 新增根目录模板 `config.example.toml`，并纳入发行包。
- 新增 `bacmap config init|path`：默认写 `$BACMAP_HOME/config.toml`，`--user` 写
  XDG 用户配置目录，`--project` 写当前目录（源码检出已 gitignore）。
- 配置解析顺序：`BACMAP_CONFIG` > `$BACMAP_HOME/config.toml` >
  `~/.config/bacmap/config.toml`；项目内配置必须显式指定，不由源码位置自动推导。
- LLM、MCP Profile、auto-confirm、debug 与 backup 统一改走 `config_path()`；
  备份包含实际生效的外部配置文件。
- 测试基线：1693 → 1703。

### Debug 模式配置文件开关
- 新增 `[debug] enabled = true`：无需每个命令前缀 `BACMAP_DEBUG=1`。
- 优先级：显式 `BACMAP_DEBUG` > 配置文件；`BACMAP_DEBUG=0` 可临时关闭配置开启的 debug。
- 配置缺失/解析错误/非 `true` 一律视为关闭；doctor 对配置开启同样输出 `debug=warn`。
- 测试基线：1689 → 1693。

### 计划自动确认策略放宽
- `[plans.auto_confirm]` 新增 `task_types`、`max_tasks`、`allow_directory_ingestion`、
  `allow_scripts`、`allow_drafts`；默认行为保持不变（仅已登记样本的 analyze）。
- 管理员可显式放开目录摄入、mine 脚本与 write 草稿，支持智能体自动迭代；
  计划修订同样应用预授权。
- 策略非法或任务不满足条件时 fail-closed 回到人工确认；模型/Harness 仍不能自证确认。
- 任务门不消失：curate 发布、mine 签字、write 导出与复核仍可能要求人工处理。
- 测试基线：1684 → 1689。

### 智能体接入文档与 MCP 操作规程
- MCP server instructions 现在明确写入操作边界：分析/写入先 `bacmap_create_plan`、
  人工确认、不得用 Harness shell 运行生信工具或读取原始序列、结论引用样本/task/run
  标识；无需用户每轮粘贴长提示词。
- 文档新增持久指令/Hook 方案：Hermes `.hermes.md`/`AGENTS.md`、Pi
  `APPEND_SYSTEM.md`、DSH `$DSH_HOME/AGENTS.md`。
- 补全 Hermes / Pi / DSH 的安装、stdio/HTTP 配置、模型凭据与验证命令；说明独立
  conda 环境与 Harness 环境解耦，`conda run --no-capture-output` 的 stdio 接法。
- 测试：新增 MCP instructions 边界断言；测试基线 1683 → 1684。

### 代码质量审计循环（第 1–3 轮，无严重问题）
- 第 1 轮（debug/research 面）：`benjamini_hochberg` 拒绝 `[0,1]` 外的 p 值；
  `associate_counts` 拒绝负格子并在 n>2000 时明示正态近似；`event_period`
  拒绝 00/13 月；Web Study 页的 Cohort/Plan 下拉只列已冻结对象。
- 第 2 轮（API/文档面）：`OutbreakAnalyzeRequest.events` 增加上限 10000；
  README/installation/development 的测试基线陈旧值统一刷新。
- 第 3 轮（运维面）：`bacmap doctor` 在 `BACMAP_DEBUG=1` 时输出 `debug=warn`
  （此前只显示沙箱 direct，不提示治理限制已放宽）。
- 连续 3 轮未发现严重问题，按停止条件结束；全量验证见证据 §10.79。
- 测试基线：1678 → 1683。

### 开发调试模式（BACMAP_DEBUG）
- 新增 `BACMAP_DEBUG=1`：开发机放宽 Web 鉴权/CSRF、计划确认、任务审批、四道门、
  MCP Profile 数据级别、Research Claim/发表门与沙箱回退；所有入口打印警告。
- 硬边界不变：D3/D4 仍不得发往 cloud LLM 端点（ADR-16）；默认不设置时全部 fail-closed。
- 新增 13 项测试：显式放宽面 + 默认拒绝 + 数据红线边界。
- 测试基线：1665 → 1678。

### P2 收尾 + 暴发事件挖掘 + 真实队列敏感性 + P3 第一片
- Web `/research` 与 Study 页补齐 Study/Cohort/Plan/Experiment/Claim 创建、冻结、审核和
  G0–G3 发表门展示，不再只能走 API/CLI。
- 新增 `research/outbreak.py`：按已记录地点+日期精度聚类，区分聚集/散在与未知日期，
  对 clustered/source/lineage 做 BH 校正分类关联；不推断传播方向。OSF n78q3 真实数据
  得到 71 个上下文聚类、145 聚集/31 散在事件；来源效应明确标注为采样混杂。
- BV-BRC L1 基准加入真实队列敏感性：Mantel–Haenszel 分层、留一范围与 E-value。
  KPC crude 113.7→MH 33.9、NDM 28.0→7.87、OXA-48 4.03→2.48、CTX-M 0.70→0.71。
- 新增 `research/discovery.py`（P3 第一片）：仅 screening 数据、预算/最小 n/FDR 排序、
  停止原因、拒绝确认性输入、不创建 Claim；CLI/API 增加 `outbreak`/`sensitivity`/`explore`。
- 测试基线：1649 → 1665。

### 冻结文档 v1.10.1：P2 真实数据基准与统计评审
- P2 真实数据基准：BV-BRC *K. pneumoniae*/meropenem L1 关联基准（方向先验、BH q、
  Intermediate 计数）、OSF n78q3 L2 队列表型覆盖摘要、数据集 manifest SHA-256/行数校验。
- 新增 Benjamini–Hochberg FDR 与 Mantel–Haenszel/Greenland–Robins 分层统计。
- P2 Experiment 账本与发表门：`success`/`failed`/`negative`/`deviated` 追加式记录，
  绑定冻结计划哈希；`publication-readiness` 实现 G0–G3（冻结来源、Claim 门、D0–D2、
  可复现执行）。过门仍需人工评审。
- P2 CLI 对象生命周期：`bacmap research study|cohort|plan|claim|experiment|publication`
  支持创建/预检/冻结/执行/审核/发表检查；JSON/文件参数通用。
- 测试基线：1632 → 1649。

### 冻结文档 v1.10.0：Research Workbench P1
- 新增 `research/` 模块与 `research.sqlite`：从既有 run 生成确定性 AMR 关联
  （2×2、OR/95% CI、Fisher 检验、诊断）、SVG 图、报告与论文草案。
- 新增治理 Profile（open-test/research/publication）、CLI `bacmap research`、
  Web `/research`、`/api/v1/research`、只读 MCP 研究工具。
- P2 核心对象：Study/Cohort/AnalysisPlan/Claim/evidence_edges，含冻结哈希、
  Claim 最低等级/措辞门、冻结计划执行 P1 AMR 配方、对象列表/账本 API、
  L0 AMR 基准、Cohort 预检、session→Claim、Web study 页面。
- 不改变 GOM/Snakemake/DBOS/五类任务；P2–P5 见
  `dev/next-phase-research-workbench-plan.md`。
- 测试基线：1610 → 1632。

### 文档站重构：按软件文档结构重写（中英双语）
- 信息架构改为 Home / Getting Started / Guide / Concepts / Operations / Reference /
  Development；新增概念、参考、开发章节与各节 landing page。
- 内容按当前代码校准：五类任务、`bacmap_record_data`、计划归属、run 级结果隔离、
  DBOS 检查点备份、`samples.tsv` 相对路径与 ID 规则等。
- 大量补充可复制示例（CLI/JSON/TOML/MCP/API）与概念解释；README 同步重写。
- 中文页面统一为 `.zh.md`，顶部语言切换由 `mkdocs-static-i18n` 提供。

### 冻结文档 v1.9.3：并发 run 隔离 + DBOS 检查点备份
- analyze 的 summary/门/报告/cgMLST/队列入库只读 `results/runs/<task_id>/`；
  报告脚本内部支持 `--results-dir`。
- `bacmap backup` 纳入 `dbos.sqlite`，恢复后运行中任务可继续。
- 测试基线：1606 → 1610。

### 冻结文档 v1.9.2：20 轮巡检修复
- 结果迁移自动覆盖旧扁平样本与 snp/cgmlst 实体目录，升级后首次运行不再失败；
  另修复 sample id/证据链路径、预授权范围、计划归属、引用门回退、审核不可覆盖、
  数据集级别去重、Web 409/scope/重定向与工作流错误可读性。
- 测试基线：1571 → 1606。

### 冻结文档 v1.9.1：巡检修复（R1–R7）
- 结果迁移绝不删除既有运行目录；旧行缺 checksum 时重算比对；
  auto_confirm 配置非法时安全回退。
- 连续 3 轮无新问题结束（范围见 dev/code-review-log.md）。
- 测试基线：1568 → 1571。

### 冻结文档 v1.9.0：计划确认三通道
- 计划返回 `confirm_url`；新增本地弹窗确认（stdio，`local-dialog`）；
  `[plans.auto_confirm]` 低风险预授权（默认关，仅 analyze）。
- 教程 §3.4 与配置文档同步。
- 测试基线：1562 → 1568。

### 冻结文档 v1.8.5：自然语言排障
- `bacmap_task_status` 在云端 Profile 返回脱敏 `failure`（类别/建议/修复命令）；
  `failure_diagnostics` 增补 `sandbox_unavailable`。
- 教程新增“出问题时，先跟它说”一节（中英）。
- 测试基线：1559 → 1562。

### 冻结文档 v1.8.4：自然语言数据管理 + 教程智能体优先
- 新增 MCP `bacmap_record_data`（local-trusted）：智能体可经任务层录入元数据/化验/知识库。
- 教程重写为智能体优先（中英），CLI 退到兜底小节。
- 测试基线：1556 → 1559。

### 冻结文档 v1.8.3：curate 代表运行（I3）
- 同一 isolate 多个 dataset 只纳入一次：默认最新分析，可显式指定；
  `representative_runs` / `superseded` 记录选择与依据。
- `scope.strains` 可用 isolate 或 dataset；元数据按 isolate 查找。
- 测试基线：1552 → 1556。

### 冻结文档 v1.8.2：I3 第一片（isolate 注册表）
- 新增 `isolates` 表与 `bacmap isolate ls|show`；登记自动同步 isolate，
  `EVO-001-P037` 自动解析 lineage/passage。
- 测试基线：1545 → 1552。

## [0.1.2] - 2026-10-26

### 冻结文档 v1.8.1：run 级结果目录（P2 方案 A）
- 物理结果改为 `results/runs/<task_id>/...`，历史运行永不覆盖；
  `results/<sample>`、`results/snp`、`results/cgmlst` 为最新运行符号链接。
- 新增 `bacmap results migrate [--dry-run]`：旧扁平目录迁入 `runs/legacy-*` 后立即替换为链接。
- 视图/工具/GOM 入库路径不变（跟随链接）。
- 测试基线：1537 → 1545。

## [0.1.1] - 2026-10-26

### 冻结文档 v1.8.0：身份模型 I1（登记冲突修复）
- **修复**：同名不同内容的样本不再被静默复用——按内容 SHA256 判定，哈希不同立即报错；同内容仍幂等。
- **新增**：`samples.tsv` v3（`isolate`/`platform`/`checksum`，v2 自动升级）；
  命名约定 `<isolate>__<platform>[__<date>]`，支持一株多测。
- **裁定记录**：传代=每代一个 isolate + lineage；P2 落地后旧目录立即删除；P1 存储优化暂缓。
- **测试基线**：1529 → 1537。

### 冻结文档 v1.7.1：证据可见性
- 新增 `bacmap run ls|show|compare`、`bacmap gom ls|show`；`/api/v1/runs`、`/runs/{id}`、
  `/runs/{id}/compare`、`/gom/objects`；Web **运行** 与 **GOM** 页面（含来源比较）。

### 冻结文档 v1.7.2：开放路径入计划 + 运维命令 + 文档站
- **计划**：`mine`/`write` 成为可计划类型（脚本/成稿全文进入哈希并在确认页展示；
  `mine` 输入路径建计划时记录指纹）；MCP 与能力协商同步。
- **运维**：`bacmap doctor` / `backup` / `restore` / `events prune`；SQLite 一致快照备份、
  zip-slip 防护与恢复后完整性检查。
- **文档**：新增双语 `docs/operations*.md`，更新 mkdocs 导航、README 索引与 usage 章节；
  实战教程补充"第 9 章 溯源（GOM + 公共近缘基因组）"与"第 10 章 数据挖掘（可签字代码示例）"。
- **测试基线**：1510 → 1529。

### 冻结文档 v1.7.0：数据记录入口（新增 `record` 任务）
- **新增**：CLI `bacmap record metadata|lab|knowledge-import|knowledge-approve` 与 Web `/records`
  （元数据/化验/知识库三个表单 + 审核）。所有写入经任务层（ADR-07），留任务与事件审计。
- **任务类型**：新增第五类 `record`（ADR-06 修订）；不进计划、不经 MCP（D4 写）。
  `knowledge_import` 只入暂存，`knowledge_approve` 后引用门才认可。
- **修复**：`StrainMetadataService`/`LabResultService` 先连接后建目录导致的
  `unable to open database file`（父目录不存在时）。
- **测试基线**：1489 → 1510。

### 冻结文档 v1.6.1：v1.7 四项
- **清理**：删除仅内置助手使用的死代码——`agent/intent.py`、`agent/sandbox/tool.py`、
  `agent/llm/tools.py`、gateway 的 `run_agent*`/流式与工具智能体（550→203 行）、CLI `_stream_respond`。
- **新增**：MCP `bacmap_capabilities`（版本、Profile/数据级别、可计划任务、推荐写入路径、
  `tasks_extension: unsupported_by_sdk`）。
- **MCP Tasks**：Python SDK 2.3.0 仍未实现官方扩展，继续用显式任务句柄（语义待迁移）。
- **Harness**：Hermes 0.17.0+52045 全链路通过；需 `CMAKE_POLICY_VERSION_MINIMUM=3.5` 与
  `hermes auth add zai`（隔离运行时不读环境变量）。
- **ACP**：按记录暂不实现（与 ADR-21 冲突、无具体消费者）；SDK 0.12.1 可用但不加依赖。
- **测试基线**：1500 → 1489（净删除死代码测试 + 新增能力/移除断言）。

### 冻结文档 v1.6.0：移除内置会话助手（ADR-21 落地）
- **破坏性变更**：CLI `ask`/`chat`、Web `/assistant`、TUI 对话与计划确认全部移除。
  对话请用外部 Harness（Hermes / Pi / DSH）经 MCP；计划在 `bacmap plan` 或 Web `/plans` 确认。
- **TUI 重写为任务台**：任务/样本侧栏、操作日志、命令输入、leader 和弦、签批两步确认、
  失败回显、`/result` `/search` `/analyze` `/curate` 保留；输入框只接受斜杠命令。
  顺带修复 Input 吞掉 leader 可打印键的真实缺陷（新增回归测试）。
- **删除**：`agent/session.py`、`interfaces/assistant.py`、assistant 角色与说明书；
  MCP prompts 由 7 个角色变为 6 个。任务内智能体（解读、sandbox 工具）保留。
- **迁移**：`data/bacmap.sqlite`（元数据 + 检验）、`data/knowledge.sqlite`（知识库 + FTS）
  纳入按文件迁移；菌株基因型索引确认与 GOM 同库，作为 `gom.sqlite` 迁移 2。
- **文档**：usage / installation / README 双语同步；`docs/harnesses*.md` 更新实测版本
  （Pi 1.4.0、Hermes 0.17.0+52045、DSH 0.2.1-rc.2）。
- **测试基线**：1546 → 1500（功能删除导致的合法调整，见冻结文档 v1.6.0 记录）。

### 冻结文档 v1.5.2：事件、API、MCP 任务控制

> 本节及以下 v1.5.x 标题均为**架构文档修订版本**，不是程序版本；程序版本仍为 0.1.0（早期开发）。

- **新增 · 领域事件日志**：`tasks.sqlite` 迁移 3 新增 `events` 表；计划与任务关键转换写事件；
  任务 `current_step` 现随管线步骤更新（此前提交后不变）。
- **新增 · `/api/v1`**：capabilities、tasks（含 cancel）、plans（含 confirm/reject）、events（轮询 + SSE，
  `Last-Event-ID` 续传）、samples（游标分页）。cookie 模式状态变更须 `X-CSRF-Token`。
- **新增 · MCP**：`bacmap_task_cancel`（仅本客户端任务）、`bacmap_task_result`（运行 ID + 门结论，
  cloud 下只给计数）、`skill://bacmap/<role>/SKILL.md` 资源（带 sha256）。
- **变更 · cloud Profile**：`bacmap_task_status` 不再回传任务消息（`message_withheld: true`）。
- **变更 · 废弃提示**：CLI `ask`/`chat`（stderr）、TUI 帮助、Web `/assistant` 显示 ADR-21 迁移提示；
  内置助手移除推迟到 v1.6（三个 Harness 完成真实对话联调后）。
- **工程**：`runs.sqlite`、`baseline.sqlite`、`gom.sqlite`（按文件清单）纳入编号迁移；`bacmap.__version__` 取安装元数据（与 `pyproject.toml` 同源，程序版本保持 0.1.0）。
- **文档**：新增 `docs/harnesses.md`（Hermes / Pi / DSH 接入、按系统账户隔离、实测记录，双语）。

### 冻结文档 v1.5.1：版本化计划闭环
- **新增 · 计划工具（MCP）**：`bacmap_create_plan` / `bacmap_revise_plan` / `bacmap_get_plan`——
  外部 Harness 只能建/改/查计划，MCP 不提供确认工具。
- **新增 · 可信确认面**：CLI `bacmap plan ls|show|confirm|reject`；Web `/plans`（列表、完整参数、
  确认/拒绝，cookie 模式带 CSRF）。确认绑定 `(plan_id, version, plan_hash)`，修订使旧版本失效，
  输入目录变化即冲突，重复/并发确认只提交一次（确定性 task_id）。
- **新增 · 类型化任务参数**（`tasks/params.py`）与应用服务层 `bacmap.application`；
  `tasks.sqlite` 迁移 2 新增 `plans` 表；`TaskEngine.submit` 新增可选 `task_id`（显式 ID 幂等）。
- **工程**：import-linter 增至 5 条契约（应用层不得导入接口层/智能体层）。

### 冻结文档 v1.5.0：M0 安全基线，新增 ADR-21“交互智能体外置”
- **破坏性变更 · MCP 数据级别 Profile**：每个 MCP 实例绑定 Profile。默认 `cloud` 只暴露输出级别
  ≤ `[llm.data_policy].cloud_max_data_class`（默认 D1）的工具；`local-trusted`（至 D4）须在
  `config.toml` 设 `[mcp] allow_local_trusted = true` 并以 `bacmap mcp --profile local-trusted` 启动，
  未开启即拒绝启动。此前 D3/D4 工具对任意 MCP 客户端可见可调（ADR-16 缺口）。
- **破坏性变更 · 提交者身份服务端认定**：`bacmap_submit_task` 删除 `submitted_by` 参数，
  提交者记为 `mcp-stdio:<profile>:<OS 账户>` / `mcp-http:<profile>`。
- **修复 · CLI 任务层外写**：`task submit --fasta-dir/--fastq-dir` 不再自行写 `samples.tsv`，
  目录参数交给任务引擎登记（ADR-07）；目录不存在时 CLI 立即报错。
- **工程 · ADR-02 契约化**：import-linter 增至 4 条契约（LLM 库 / DBOS / MCP SDK 边界），修复
  `agent/session.py`、`agent/sandbox/tool.py` 直接导入 pydantic-ai 的违例（经 `agent/llm/tools.py`）；
  新增 AST 边界测试覆盖 `mcp.client` 与命名空间包 `workflow`。
- **工程 · schema 迁移机制**（ADR-13）：新增 `store/migrations.py`（`PRAGMA user_version`、单事务、
  迁移前备份、拒绝降级），`tasks.sqlite` 纳管为版本 1。
- **方向 · ADR-21**：对话交互外置给 Hermes / Pi / DSH；内置会话助手（TUI 对话、Web `/assistant`、
  `ask`/`chat`）进入废弃期；确认与审批留在 bacmap CLI/Web。

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
- **文档全面双语化（英文为默认语言）**：README 与全部 docs 提供 EN + `.zh.md`
  双版本，顶部语言切换链接，跨链同语言互指；新增工具参考 `docs/tools.md`（24 工具
  全参数，源自运行时注册表）；冻结架构文档补全量英译 `architecture-frozen-v1.md`（英文）
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
- **vpara_virulence 换装 gspec（ADR-20，冻结文档 v1.4.9）**：删除内联 blastn 筛查，
  改用 gspec 自定义库 `vpara_virulence`（tdh/trh/tlh）；部署期
  `workflow/scripts/build_gspec_db.py` 自动建库于 `$BACMAP_HOME/refs/gspec/` 并登记
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
- v1.4.5：血清型扫描与判定整体迁入 gspec，bacmap `core/typing` 删除。
- v1.4.7：物种鉴定五模块外移 gside，4 个物种类工具删除；血清型三模块彻底放弃。
- v1.4.7：genome_annotator 外移（annotation 规则 `pending_external_tool` 占位）。
- v1.4.8：插件通道取消，仅保留 MCP。

### 验证
- V1 12 株金标准 ✅（3 项 MLST 方案演化 DIFF 已归因）
- V8 三次重跑 SHA256 一致 ✅；V10 gside 10/12（2 项 marker 法原理边界已归因）✅
- V11 六道门 ✅；V3 意图分类 95/100 ✅；V4 Hermes MCP 22 工具 ✅
- 测试基线 945 passed / 1 skipped；ruff、import-linter 契约全绿。
