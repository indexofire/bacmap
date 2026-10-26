[English](tutorial.md) | **简体中文**

# 从零到出报告：bacmap 实战教程

> 这不是命令手册。手册告诉你"有哪些参数"，这篇教程陪你走完一个真实的工作日：
> 从拿到一盒测序数据，到把报告发给同事，再到回答"这个结论凭什么可信"。
>
> 文中的输出都是示意（ID、数量、耗时因机器而异）；命令、参数与保证以当前版本为准，
> 细节仍以参考文档为唯一事实来源。

## 序：周一早上的八株菌

八点四十，你收到一封邮件：

> "上周那批副溶血弧菌（8 株）上机结果出来了，reads 在 `/data/run42/`。
> 顺便看看和去年 O3:K6 那几株是不是同一簇。周五之前给我一版报告。"

你手边有一台 Linux 工作站，装了 bacmap。接下来两个小时，我们会把这件事做完——
并且让每一步都留下证据，经得起半年后有人问"当时用的什么库、什么参数"。

---

## 第 0 章 先搞清楚 bacmap 是什么

bacmap 不是一个"聊天框"，它更像一间**有门禁的实验室**：

```
 你 / 同事 ── CLI、Web ─┐
                        ├─▶ 任务层（只认这五种任务）─▶ Snakemake 管线 / 沙箱
 外部智能体 ── MCP ─────┘         │
  （Hermes/Pi/DSH）               ├─ 四道门：结论门、发布门、挖掘门、引用门
                                  └─ 证据：运行记录 + GOM + 审批签名
```

三条规矩，记住就够用：

1. **分析只走固定管线**（L1）。物种、血清型、MLST、耐药这些结果只能来自 gside / gapit / gmlst + Snakemake，模型不参与判定。
2. **写操作只经任务**。录入、分析、建库、挖据、成稿，全部是任务；任务有状态、可恢复、有审计。
3. **对话在外部智能体里**。你在 Hermes / Pi / DSH 里说人话，它们通过 MCP 提计划；
   **确认动作永远在 bacmap 里由人完成**。

想先看它认哪些任务？`bacmap task --help`。想看系统状态？`bacmap overview`。

---

## 第 1 章 安装：把实验室搭起来

### 1.1 装环境

bacmap 用 pixi 管环境（Python + 生信工具一起管），不需要你手动配 conda。

```bash
git clone https://github.com/indexofire/bacmap.git
cd bacmap
pixi install          # 第一次会下载生信工具链，耐心等
pixi shell            # 进入环境后 bacmap / gside / gapit / gmlst 都在 PATH 上
```

验证：

```bash
bacmap --version
# bacmap 0.1.0
bacmap overview
```

`overview` 会打印数据目录、云端数据上限、沙箱后端、组件版本和 LLM 端点。
**第一次看到"沙箱后端: passthrough"不要慌**——这说明还没装隔离后端，只影响挖掘任务，标准分析不受影响。

### 1.2 数据放哪

默认数据根目录是 `~/.local/share/bacmap`（可用 `BACMAP_HOME` 改）。它会自己长成这样：

```
$BACMAP_HOME/
├── config.toml          # 可选配置（LLM、MCP）
├── tasks.sqlite         # 任务、审批、计划、事件
├── runs.sqlite          # 运行记录（证据链）
├── gom.sqlite           # GOM 对象 + 菌株索引
├── data/                # 菌株元数据、化验、知识库
├── results/<样本>/       # 每株的结果与报告
├── workflows/bacmap/    # 部署出来的 Snakemake 工作流
└── workspaces/          # 挖掘任务的工作区
```

不确定是否健康？跑一次体检：

```bash
bacmap doctor
```

```
✓ home      /home/you/.local/share/bacmap
! database  tasks.sqlite 尚未创建（首次运行后生成）
! sandbox   passthrough
! llm       无可用 LLM 端点（确定性路径仍可用）
✓ disk      可用 212.4 GB
! tools     外部工具缺失：无
```

`!` 是提醒不是失败。**bacmap 没有 LLM 也能完成全部分析**，这是设计目标之一。

### 1.3 想接模型？两分钟配好

如果你要用内置的任务内智能体（解读、开放路径），或者要接外部 Harness，加一个端点：

```toml
# ~/.local/share/bacmap/config.toml
[llm.endpoints.glm]
kind = "openai_compatible"
location = "cloud"                      # 云端：默认只能看 D0–D1
base_url = "https://open.bigmodel.cn/api/paas/v4"
model = "glm-5.3"
api_key_env = "GLM_API_KEY"
tier = "T2"

[llm.routing]
intent_classifier = "glm"
interpretation = "glm"
```

```bash
export GLM_API_KEY="你的 key"
bacmap overview     # 端点那一行会显示端点与连接状态
```

**别忘了红线**：云端端点默认只能接收 D0–D1；D3（序列）、D4（个人信息）永远不出本地网络。
需要单株结果（D2）上云时，管理员最多把 `cloud_max_data_class` 放宽到 `"D2"`——配置里写 D4 会直接报错。

---

## 第 2 章 第一次跑通：八株菌进去，八个结果出来

### 2.1 让 bacmap 自己认样本

八株 reads 放在 `/data/run42/`，命名是 `HZCPE-01_R1.fastq.gz` / `_R2`。不用写样本表，
直接把目录交给它：

```bash
bacmap task submit --type analyze --fastq-dir /data/run42
```

```
已提交任务 3f9c1a2b7d4e4c0e9b1a6d2f8c5e7a10（analyze）
用 `bacmap task show 3f9c…` 轮询
```

这条命令背后发生了什么？

1. 任务层先扫描目录，识别 `_R1/_R2` 配对，得到 8 个样本 ID（`HZCPE-01` … `HZCPE-08`）；
2. 登记进 `samples.tsv`（**这一步是任务的一部分**，不是 CLI 偷偷写文件）；
3. 启动 Snakemake：fastp 质控 → shovill 组装 → gside 物种鉴定 → MLST/SISTR/AMR/毒力/质粒 → 报告。

样本很多、想先看清单？先 `--species VPA` 跳过自动鉴定可以快一点，但**推荐让它自己认**：
认错了会在报告里写 `Unknown`，比硬塞一个物种名安全。

### 2.2 盯住它

```bash
bacmap task show 3f9c1a2b
```

```
3f9c1a2b7d4e4c0e9b1a6d2f8c5e7a10  state=running  step=pipeline
```

`step` 会一路走：`register_inputs → pipeline → run_record → ingest_and_gates`。
想看全部任务：`bacmap task ls`。想每隔几秒自己刷：`watch -n 5 bacmap task show 3f9c…`。

八株菌大约十几分钟到半小时（取决于机器）。这段时间可以做点别的——比如去配 Web。

### 2.3 结果落在哪

```bash
bacmap sample ls
```

```
┌──────────┬───────────┬──────┬──────────────┬─────┬──────┬──────────┐
│ sample_id│ verdict   │  ST  │ serovar      │ AMR │ VF   │ plasmid  │
├──────────┼───────────┼──────┼──────────────┼─────┼──────┼──────────┤
│ HZCPE-01 │ VPA       │   -  │ O3:K6        │  2  │  14  │    1     │
│ HZCPE-02 │ VPA       │   -  │ O3:K6        │  2  │  14  │    1     │
│ ...      │           │      │              │     │      │          │
└──────────┴───────────┴──────┴──────────────┴─────┴──────┴──────────┘
```

每株的完整结果：

```bash
bacmap sample show HZCPE-01
```

报告是一个自包含 HTML：

```
results/HZCPE-01/report/HZCPE-01_report.html
```

在 Web 里看更舒服（第 6 章），或者 `scp` 回自己电脑双击打开。

### 2.4 别忘了看门

任务结束时如果显示 `awaiting_approval`，说明有门没过——**不要重跑**，先看原因：

```bash
bacmap task show <task_id>
# message 里会写哪一株、哪个门、为什么
```

常见的是"解读文本与事实矛盾"（结论门）或"未签字"（挖掘门）。前者改解读、后者走审批：

```bash
bacmap task approve <task_id> --approver 张三 --decision approve --signature 我的签名口令
```

---

## 第 3 章 回答"凭什么可信"：证据链

周五的邮件里，同事可能追问："这个 O3:K6 判定，跟去年那批比过吗？用的哪个库？"

bacmap 的答案不靠记忆，靠两张表。

### 3.1 运行记录：这一次到底怎么算的

```bash
bacmap run ls
bacmap run show <run_id>
```

你会看到：流程版本（含 git commit、是否 dirty）、**合并后的完整参数**及其哈希、
工具版本（运行时实测）、数据库版本与校验值、输入文件 SHA256、随机种子、主机信息。

这些内容同时写进 `runs/<run_id>/run_manifest.json`，带 SHA256。也就是说：

> 半年后有人问"当时用的 CARD 是哪个版本"，你不需要回忆，查 `run show` 就行。

两次运行结果不一致？让 bacmap 帮你归因：

```bash
bacmap run compare <run_a> <run_b>
```

```
来源不同；变化类别：databases, tools
  [databases] card: 3.2.9 → 4.0.0
  [tools] gapit: 0.5.6 → 0.6.0
```

如果来源完全相同而结果不同，它会直接说 `NOT_REPRODUCIBLE`——这时候该查的是随机性、环境或硬件，
而不是"再跑一次看看"。

### 3.2 GOM：结果本身是不可变的

```bash
bacmap gom ls --type analysis
bacmap gom show <object_id>
```

同一样本重跑不会覆盖上一版，而是产生新版本。`bacmap gom show <id> --version 1` 永远能看到第一版。
审计要的就是这个。

### 3.3 快速找样本

```bash
bacmap search --query "CTX-M"
bacmap search --st 19
bacmap search --serotype Typhimurium
```

结果可以直接进报告，也可以交给 Web 里的样本页继续看。

---

## 第 4 章 让智能体替你干活（但确认由你）

bacmap 自己不提供聊天框。你在 Hermes、Pi 或 DeepSeek Harness 里说话，它们通过 MCP 用 bacmap 的工具。

### 4.1 接上（以 Hermes 为例）

```yaml
# ~/.hermes/config.yaml
mcp_servers:
  bacmap:
    command: /path/to/pixi/envs/default/bin/bacmap
    args: ["mcp"]          # 本地模型可加 "--profile", "local-trusted"
```

```bash
hermes mcp test bacmap
# ✓ Connected · 10 tools
```

Pi 和 DSH 的配置见[智能体 Harness 指南](harnesses.zh-CN.md)。一句话版本：
Pi 用 `mcp.json`，DSH 的新条目必须包在 `insert:` 下面。

### 4.2 它先"看"，再"提计划"

在 Hermes 里说：

> "看看本地有哪些副溶血弧菌样本，挑出 HZCPE 那批，跑一个分析计划。"

智能体会调用 `bacmap_capabilities` 和只读工具，然后给你一份**计划**：

```json
{
  "plan_id": "9a3f2c1b7d4e4f60",
  "version": 1,
  "state": "awaiting_confirmation",
  "tasks": [
    {"task_type": "analyze", "fasta_dir": "/data/run42", "species": "VPA"}
  ],
  "plan_hash": "c1d2…（64 位）"
}
```

注意 `state`：**它没有执行**。智能体也确认不了——MCP 里根本没有"确认"这个工具。

### 4.3 你来看，你来签

```bash
bacmap plan show 9a3f2c1b7d4e4f60
```

完整参数、哈希、输入目录指纹都摆在你面前。确认：

```bash
bacmap plan confirm 9a3f2c1b7d4e4f60 --version 1 --hash c1d2e3f4a5b6
```

或者交互式：

```bash
bacmap plan confirm 9a3f2c1b7d4e4f60
# 会先打印计划，问你 y/N
```

**三个保证**：

- 改了参数就是新版本，旧版本立刻失效（`superseded`）；
- 建计划后输入目录被改动，确认会报冲突，而不是"照着旧清单跑"；
- 重复确认、CLI 和 Web 同时确认，都只提交一次（任务 ID 是派生的）。

Web 里同样能做：**计划** 页面 → 看全文 → 确认/拒绝。

### 4.4 一个更"野"的例子：挖掘计划

想让智能体统计本地菌株的 ST 分布？它会提一个 `mine` 计划，里面带**脚本全文**：

```json
{
  "task_type": "mine",
  "objective": "按 ST 统计本地副溶血弧菌",
  "script": "import json, pathlib, collections\n...",
  "input_paths": ["/data/typing/st_table.csv"],
  "sandbox_image": "docker://python:3.12-slim"
}
```

`bacmap plan show` 会把脚本从头到尾打给你看——**脚本全文参与哈希**，你确认的就是要跑的那段代码。
执行时它在无网络沙箱里跑，输入只读挂载，产物落在工作区，**之后还要过挖掘门并由你签字**。

如果机器上没装沙箱后端，任务会明确告诉你"沙箱不可用"，而不是悄悄裸跑：

```bash
pixi run -e default which apptainer podman   # 至少有一个
```

---

## 第 5 章 数据是活的：元数据、化验、文献

分析结果只是一半。另一半是"这株菌从哪来、有什么临床背景、有没有文献支持"。

### 5.1 录元数据

```bash
bacmap record metadata --strain-id HZCPE-01 \
  --field isolation_date=2026-10-12 \
  --field province=Guangdong \
  --field city=Shenzhen \
  --field sample_source=food \
  --field food_category=seafood
```

它会提交一个 `record` 任务，完成后：

```bash
bacmap task show <task_id>
# message: recorded metadata for HZCPE-01
```

写错字段？任务会直接拒绝（字段白名单），不会悄悄塞进额外 JSON：

```
提交失败：invalid record: metadata.fields: unknown metadata field(s): ['sample_sorce']
```

### 5.2 录一条药敏

```bash
bacmap record lab --strain-id HZCPE-01 --category mic \
  --test-name meropenem --result 0.25 --unit mg/L \
  --interpretation S --standard CLSI-2026
```

### 5.3 文献：先入暂存，再人审

```bash
bacmap record knowledge-import --title "V. parahaemolyticus O3:K6 emergence" \
  --identifier PMID:12345678 --year 2025
# → staged knowledge entry 12 (awaiting approval)

bacmap record knowledge-approve 12
```

为什么分两步？因为**引用门只认已审核条目**。未审核的文献不能给"撰写"任务当引用来源，
这能防止模型拿一篇不存在（或没读过）的文章当证据。

Web 的 **记录** 页有同样三个表单，适合不习惯命令行的同事。

### 5.4 建一版本地流行特征库

有了元数据，就可以把本辖区菌株汇总成特征库：

```bash
bacmap task submit --type curate --scope '{"pathogen":"VPA"}'
```

任务会逐株检查：确定性校验是否通过、QC 是否合格、元数据是否完整、有没有重复。
任何一株不合格都不会让整个任务崩，而是列进 `excluded`。

通过后任务进入 `awaiting_approval`——**发布门要求人工签名**：

```bash
bacmap task approve <task_id> --approver 张三 --decision approve --signature 我的签名
# 成功后 message: published baseline v3 (signed by 张三)
```

从这一刻起，"本地首次出现""与 2025 年某暴发株同簇"这类结论，才有本地特征库版本可引用。

---

## 第 6 章 一天里的另外两个界面

### 6.1 Web：给同事看的

```bash
export BACMAP_WEB_TOKEN="$(openssl rand -hex 24)"
BACMAP_WEB_AUTH=cookie bacmap web
# bacmap web → http://127.0.0.1:8800/
```

浏览器打开 `/login`，粘贴 token。之后顶部导航就是工作流：

| 页面 | 你会用它做什么 |
|---|---|
| **任务** | 提交 analyze/curate，看六态徽章，处理审批 |
| **计划** | 审阅智能体提的计划，确认/拒绝 |
| **记录** | 录元数据、化验、文献，审核条目 |
| **运行** | 查运行记录，比较两次运行 |
| **GOM** | 看不可变对象的最新版本与载荷 |
| **样本 / 检索** | 浏览结果、看 HTML 报告（内联渲染，禁脚本） |

远程同事怎么访问？**别直接开端口**，用 SSH 隧道：

```bash
ssh -L 8800:127.0.0.1:8800 you@workstation
```

然后本机浏览器开 `http://127.0.0.1:8800`。数据不出网络，也不多一个攻击面。

### 6.2 TUI：给终端党的任务台

```bash
bacmap tui
```

它没有聊天框（对话交给 Harness），但足够处理日常：

- 左边任务/样本表，右边操作日志，底部输入命令；
- `Ctrl+G` 后按 `a` 选中任务进入签批，`Ctrl+Y` 确认（两步防误签）；
- `/approve 3f9c1a2b 张三`、`/result HZCPE-01`、`/analyze HZCPE-01`；
- 输入自然语言会提示你去用外部 Harness——不是故障，是设计。

### 6.3 命令行党的一屏速查

```bash
bacmap overview                     # 系统状态
bacmap task ls | show | submit | approve | cancel
bacmap plan ls | show | confirm | reject
bacmap record metadata | lab | knowledge-import | knowledge-approve
bacmap run ls | show | compare
bacmap gom ls | show
bacmap sample ls | show
bacmap search --query ... | --st ... | --serotype ...
bacmap doctor | backup | restore | events prune
bacmap web | tui | console | mcp
```

---

## 第 7 章 出问题的时候

**"任务一直是 running"**
先 `bacmap task show`。如果 `step` 长时间停在 `pipeline`，看日志尾部（message 会带 stderr 末尾）。
机器重载过？DBOS 会自动恢复；不需要手动重提。

**"沙箱不可用"**
装 Apptainer 或 Podman 即可（`pixi global install` 或系统包管理器）。直通模式只用于受控开发。

**"智能体看不到某些工具"**
Profile 在起作用。默认 `cloud` 只给 D0–D1 工具；本地/内网模型才用：

```bash
# config.toml
[mcp]
allow_local_trusted = true
```
```bash
bacmap mcp --profile local-trusted
```

**"云端模型报 D4/D3 拦截"**
这是红线，不是 bug。要么换本地端点，要么把该步骤交给任务层（任务层数据不出网）。

**"DSH 里没有 bacmap 工具"**
检查补丁是否包在 `insert:` 里（裸条目会被当成"修改已有 ID"而跳过），然后：

```bash
dsh <profile> --dump-config | grep mcp-bacmap
```

**"Hermes 说没有凭据"**
新版 Hermes 的隔离运行时不读环境变量：

```bash
hermes auth add zai --type api-key --api-key "$ZAI_API_KEY"
hermes auth status zai
```

**"报告打不开 / 被下载"**
Web 里默认内联渲染（带 `sandbox` CSP）；`?download=1` 才是下载。命令行直接找
`results/<样本>/report/<样本>_report.html`。

---

## 第 8 章 备份、升级、回滚

升级前先备份，这是硬规矩：

```bash
bacmap backup --out ~/backup/bacmap-$(date +%F).zip
```

备份里是配置、全部 SQLite（一致快照）和运行清单；`results/` 默认不含，需要时加 `--with-results`。

升级：

```bash
pixi install            # 拉新版本依赖
bacmap doctor           # 看库版本是否已迁移
```

迁移是自动的：单事务执行，迁移前把旧库复制成 `<db>.bak-v<N>`，失败整体回滚。
如果库版本比代码新（你回退了版本），bacmap 会拒绝打开——这是保护，不是故障。

回滚就恢复备份：

```bash
bacmap restore --from ~/backup/bacmap-2026-10-26.zip --home ~/.local/share/bacmap --force
```

恢复会拒绝路径穿越条目，并对每个库做完整性检查。事件保留期由你定：

```bash
bacmap events prune --days 180
```

---


## 第 9 章 溯源：从本地 GOM 到公共数据库

前面八章解决"跑出结果"。这一章回答更难的问题：**这株菌从哪来？和谁最像？**

bacmap 里有两条互补的溯源路径，别把它们混为一谈：

| 路径 | 数据来源 | 谁在算 | 适合回答 |
|---|---|---|---|
| **A. 本地特征库投影** | `data/reference/cgmlst/<scheme>/reference_profiles.tsv`（运维从 EnteroBase 等**公共**方案构建、版本受控） | `bio_cgmlst`（HierCC 等位基因距离 + 阈值判定） | "和参考库里哪株最近？算不算同一暴发簇？" |
| **B. 任意公共基因组比对** | 你从 NCBI 取回的近缘基因组（或本单位历史株） | 先走同一管线入库，再在挖掘任务里算距离 | "和这株 GCF_… 比呢？" |

为什么 B 不直接塞进 A 的参考库？因为 A 的判定要**可复现**：参考库由运维版本化，任何一次"本地首次出现"
的结论都能追溯到当时的库版本（`baseline_version` 与 `ref_databases`）。临时加入的基因组会悄悄改变判定，
所以 bacmap 选择"不改参考库，改动数据"。

### 9.1 路径 A：一次可解释的 cgMLST 投影

先确认这株有 cgMLST 谱（analyze 已经跑过）：

```bash
bacmap sample show HZCPE-01      # 有结果即可
```

投影本身是一个工具调用。你可以在 Hermes/Pi/DSH 里直接说：

> "用 bio_cgmlst 看一下 HZCPE-01 和本地参考库的最近邻。"

> 注意：`bio_cgmlst` 的输出是 D2（单株分型结果），默认 `cloud` Profile 看不到它。
> 用本地/内网模型时以 `bacmap mcp --profile local-trusted` 启动，或由管理员把
> `cloud_max_data_class` 放宽到 D2。下面在进程内调用不受此限（不经过 MCP）。

也可以在自己的脚本里调用**同一实现**（与 MCP 完全一致，不经 LLM）：

```python
from bacmap.tools import registry

spec = registry.get("bio_cgmlst")
print(spec.legacy_handler({"sample_id": "HZCPE-01"}))
```

返回类似：

```json
{
  "sample_id": "HZCPE-01",
  "verdict": "undetermined",
  "nearest": [
    {"sample_id": "VPA-2025-O3K6-07", "distance": 12},
    {"sample_id": "VPA-2024-014", "distance": 31}
  ],
  "threshold_used": {"outbreak_allele_dist": null, "related_allele_dist": null},
  "n_comparable_loci": 2680,
  "caveats": ["V. parahaemolyticus 无发布阈值，verdict=undetermined；如需判定须做本地校准并写入配置"]
}
```

怎么读：

- `distance` 是**等位基因距离**（Hamming），任一侧缺失的位点不参与计算——所以一定要看
  `n_comparable_loci`，太低（比如不到方案位点数的一半）说明结论不可靠；
- `verdict` 按物种阈值给：`outbreak` / `related` / `unrelated` / `undetermined`。
  **没有阈值就不硬判**——副溶血弧菌（VPA）正是这种情况：返回距离与可比位点数，判定留空；
- `caveats` 必须读。志贺菌（S. sonnei）在 HC5/HC10 上不可靠、副溶血弧菌没有发布阈值，
  这些都会写在这里，而不是假装有结论；
- 阈值来自 `workflow/config/config.yaml` 的 `cgmlst.thresholds`（按三字母物种码），
  改阈值属于方法学变更，应该走评审而不是临时改。

**把证据串起来**：投影结果本身不是真相，它引用的是 `run_id` 下的 cgMLST 谱。
查一下这次运行：

```bash
bacmap run ls
bacmap run show <run_id>          # 确认 cgmlst 方案、工具版本、输入哈希
bacmap gom show <object_id>       # cgmlst_profile 对象的完整等位基因谱
```

报告里写"与本中心 2025 年 O3:K6 株同簇"时，脚注应包含：所用 cgMLST scheme、
`run_id`、参考库版本（若引用了本地特征库，还要 `baseline_version`）。

### 9.2 路径 B：把公共近缘基因组请进来

假设审稿人问："和 NCBI 上那株 GCF_003045604.1 比呢？" 三步走。

**第一步：看清单与取回命令。** 让智能体调 `bio_list_reference_genomes`，或自己跑：

```python
from bacmap.tools import registry
print(registry.get("bio_list_reference_genomes").legacy_handler({}))
```

它会返回各 cohort 组的 accession、是否已取回、以及**可复制的取回命令**。
取回需要网络（bacmap 本身离线运行，这一步由你执行）：

```bash
cd "$BACMAP_HOME"
python workflows/bacmap/scripts/fetch_reference_genomes.py \
  --manifest workflows/bacmap/config/reference_accessions.yaml \
  --out-dir data/reference/genomes \
  --refs-dir refs --only VPA
```

任意 accession（不在清单里也行）可以用 NCBI datasets CLI：

```bash
datasets download genome accession GCF_003045604.1 \
  --include genome --filename /tmp/gcf.zip
unzip -o /tmp/gcf.zip -d /tmp/gcf
# 得到 /tmp/gcf/ncbi_dataset/data/GCF_003045604.1/*.fna

# 样本 ID 取自文件名 → 先改成干净的 accession，避免长长的文件名进报告
mkdir -p /tmp/refs && cp /tmp/gcf/ncbi_dataset/data/GCF_003045604.1/*.fna \
  /tmp/refs/GCF_003045604.1.fna
```

**第二步：让它走同一条管线。** 公共基因组不是"二等公民"——放进一个目录，按组装 FASTA 直入：

```bash
bacmap task submit --type analyze \
  --fasta-dir /tmp/refs \
  --species VPA
```

样本 ID 直接取自文件名（所以上一步改了名），它同样会得到 `run_id`、GOM 对象和报告。
**这一步很关键**：从这一刻起，"公共株"和"本地株"在证据链上是同一种东西，
比较才有意义。

**第三步：算距离。** 参考库没有因为这次分析而改变（见开头的原因），所以用挖掘任务
在 GOM 里直接比。这就是下一章的第一个代码示例。

### 9.3 一条完整的溯源叙事（可以直接写进报告）

1. `bio_cgmlst(HZCPE-01)` → 最近邻 `VPA-2025-O3K6-07`，距离 12，`undetermined`（VPA 无发布阈值），n=2680；
2. 取回并分析 `GCF_003045604.1`（公共参考株），得到 `run_id=R_pub`；
3. 挖掘任务计算 `HZCPE-01` 与所有 VPA cgMLST 谱的距离（含 `GCF_003045604.1`），
   输出 `distances.csv`，并由你签字；
4. 报告写："与本地 2025 年 O3:K6 株等位基因距离 12（未判定，VPA 无发布阈值）；
   与公共参考株 GCF_003045604.1 距离 27"，附 scheme、`run_id`、阈值来源（或"无阈值"说明）
   与挖掘产物哈希。

这条链里没有"模型说它像"，每一步都是可复算的。

---

## 第 10 章 数据挖掘：写一段能签字的代码

挖掘（`mine`）是 L2：**脚本在沙箱里跑，产物标为探索性，必须经你签字才能进报告**。
它不是"随便跑跑"，而是"可复现的探索"。

### 10.1 挖掘任务的输入约定

脚本运行时，工作区里有一份 `context.json`：

```json
{
  "backend": "podman",
  "results_dir": "/data/results",
  "gom_db": "/data/gom.sqlite",
  "datasets": {"ds-3f9c1a2b": "/input/ds-3f9c1a2b"}
}
```

规则：

- `datasets` 是**对象（id → 路径）**，不是数组——这是新手最常踩的坑；
- 容器后端下路径是 guest 路径（`/data/...`、`/input/...`），直通开发模式才是宿主路径；
- 输入只读；网络关闭；**沙箱里没有 pandas/numpy**，除非你自己提供带这些包的镜像
  （`sandbox_image` 参数）。示例一律用标准库。

### 10.2 示例 A：cgMLST 距离矩阵（GOM → CSV）

目标：把 GOM 里所有副溶血弧菌的 cgMLST 谱算成两两距离，找出与查询株最近的若干株。

```python
import csv
import itertools
import json
import sqlite3
from pathlib import Path

ctx = json.loads(Path("context.json").read_text())
if not ctx.get("gom_db"):
    raise SystemExit("GOM database is not mounted")

conn = sqlite3.connect(f"file:{ctx['gom_db']}?mode=ro", uri=True)
rows = conn.execute(
    """
    SELECT g.payload_json
    FROM genome_objects g
    JOIN (SELECT object_id, MAX(version) AS v
          FROM genome_objects WHERE object_type = 'analysis'
          GROUP BY object_id) latest
      ON g.object_id = latest.object_id AND g.version = latest.v
    WHERE g.object_type = 'analysis'
    """
).fetchall()
conn.close()

profiles = {}
for (payload_json,) in rows:
    p = json.loads(payload_json)
    if p.get("analysis_type") != "cgmlst_profile":
        continue
    if p.get("scheme") != "vparahaemolyticus_3":
        continue
    alleles = {k: v for k, v in p.get("alleles", {}).items() if isinstance(v, int)}
    if len(alleles) >= p.get("n_total", 0) * 0.5:      # 位点太少不参与
        profiles[p["sample_id"]] = alleles

def distance(a, b):
    shared = set(a) & set(b)
    if not shared:
        return None, 0
    return sum(a[k] != b[k] for k in shared), len(shared)

pairs = []
for a, b in itertools.combinations(sorted(profiles), 2):
    d, n = distance(profiles[a], profiles[b])
    if d is not None:
        pairs.append((a, b, d, n))
pairs.sort(key=lambda r: (r[2], r[0], r[1]))

with open("distances.csv", "w", newline="") as fh:
    w = csv.writer(fh)
    w.writerow(["sample_a", "sample_b", "distance", "comparable_loci"])
    w.writerows(pairs)

query = "HZCPE-01"
nearest = [p for p in pairs if query in p[:2]][:10]
with open("nearest.csv", "w", newline="") as fh:
    w = csv.writer(fh)
    w.writerow(["query", "reference", "distance", "comparable_loci"])
    for a, b, d, n in nearest:
        ref = b if a == query else a
        w.writerow([query, ref, d, n])

print(f"{len(profiles)} profiles, {len(pairs)} pairs, nearest written")
```

提交它——推荐走计划（Harness 提出、你审阅脚本全文），也支持 Python API 自动化：

```python
from pathlib import Path

from bacmap.tasks.engine.dbos_engine import DbosTaskEngine
from bacmap.tasks.spec import TaskType

script = Path("mining_cgmlst.py").read_text()
engine = DbosTaskEngine(Path.home() / ".local/share/bacmap")
tid = engine.submit(
    TaskType.MINE,
    {
        "objective": "cgMLST pairwise distances + nearest to HZCPE-01",
        "script": script,
        "input_paths": [],
        "sandbox_image": "docker://python:3.12-slim",
    },
    "cli:analyst",
)
print(tid)
```

任务结束后：

```bash
bacmap task show <task_id>       # awaiting_approval（挖掘门）
bacmap task approve <task_id> --approver 张三 --decision approve --signature 我的签名
```

产物在 `workspaces/<task_id>/`：`distances.csv`、`nearest.csv`。**未签字前它们只是探索性产物**，
不能进报告；签字动作本身写入审批表与 GOM 事件。

### 10.3 示例 B：把流调元数据 join 进来

沙箱拿不到 `data/bacmap.sqlite`（元数据是 D4），正确做法是**由你把一份导出表登记为输入**：

```bash
bacmap record metadata --strain-id HZCPE-01 --field isolation_date=2026-10-12 --field province=Guangdong
```

导出（例如从你自己的 LIMS 导出 `meta.csv`，列：sample,isolation_date,province,source）。
把示例 A 产出的 `nearest.csv` 也一起交给这个任务——**新任务的工作区是干净的**，
不能假设上一个任务的产物还在：

```python
tid = engine.submit(
    TaskType.MINE,
    {
        "objective": "join cgMLST nearest neighbours with epidemiology metadata",
        "script": Path("mining_join.py").read_text(),
        "input_paths": [
            "/data/exports/meta.csv",
            "/data/exports/nearest.csv",   # 示例 A 的产物（先复制到输入目录）
        ],
        "input_data_class": "D4",
        "sandbox_image": "docker://python:3.12-slim",
    },
    "cli:analyst",
)
```

脚本里**不要猜 dataset_id**，按表头识别两份输入：

```python
import csv, json, pathlib

ctx = json.loads(pathlib.Path("context.json").read_text())
csv_paths = list(ctx["datasets"].values())
if len(csv_paths) != 2:
    raise SystemExit(f"expected meta.csv + nearest.csv, got {csv_paths}")

def first_line(path: str) -> str:
    return pathlib.Path(path).read_text().splitlines()[0]

meta_path = next(p for p in csv_paths if "reference" not in first_line(p))
nearest_path = next(p for p in csv_paths if p != meta_path)

meta = {}
with open(meta_path, newline="") as fh:
    for row in csv.DictReader(fh):
        meta[row["sample"]] = row

out = []
with open(nearest_path, newline="") as fh:
    for row in csv.DictReader(fh):
        ref = row["reference"]
        out.append({**meta.get(ref, {}), "reference": ref, "distance": int(row["distance"])})

with open("nearest_with_epi.csv", "w", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=sorted({k for row in out for k in row}))
    w.writeheader()
    w.writerows(out)
```

注意 `input_data_class: D4`：一旦标了 D4，这份数据就受最严格约束（不进云端、只读挂载）。
如果只是去标识的聚合表，用 `D2`/`D3` 更符合最小权限。

### 10.4 示例 C：把"探索"变成"标准"

如果一段挖掘脚本反复用、结果稳定，正确路径不是让它长期停在 L2，而是**晋升**：

1. 把方法写成测试与文档（输入、阈值、输出契约）；
2. 实现为 `ToolSpec`（只读/计算）或 Snakemake 规则（进 L1）；
3. 用 12 株金标准回归，确认与原来的探索结果一致；
4. 在 GOM 事件里记录晋升（谁、何时、原脚本哈希）。

这样它才会出现在报告的标准结果区，而不是"探索性附录"。

### 10.5 挖掘的边界（请当回事）

- 沙箱没有网络；不要试图在脚本里下载参考库；
- 输入只读；产物只能写工作区；
- 挖掘产物**永不**写入权威结果表；
- 任何"跳过沙箱"的开关（`BACMAP_ALLOW_UNSANDBOXED`）只用于受控开发，生产禁用；
- 签字是对**这份产物**负责，不是对"模型说的"负责——所以确认前请打开 CSV 看一眼。


## 尾声：这套流程真正保护的是什么

回到周五那封邮件。你发出的不只是一个 HTML：

- 每一株的分析都有**运行记录**（参数、库版本、输入哈希、种子）；
- 每一条结论都能追到 **run_id**，重跑不会覆盖旧版本；
- 特征库发布有**签名**，谁在什么时候批准的可查；
- 智能体提的计划，是**你看过全文之后**才执行的；
- 数据分级在工具带、MCP Profile 和端点三层同时生效。

半年后有人问"当时那批 O3:K6 是怎么判的"，你打开 `bacmap run show`，三十秒能答完。

这，就是 bacmap 想帮你做的事。

---

**接下来读什么**

- 命令细节：[使用指南](usage.zh-CN.md)
- 客户端配置：[智能体 Harness 指南](harnesses.zh-CN.md)
- 运维与升级：[运维指南](operations.zh-CN.md)
- 安装排查：[安装指南](installation.zh-CN.md) · 配置：[配置指南](configuration.zh-CN.md)
