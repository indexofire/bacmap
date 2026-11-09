# 在个人电脑上用 Strata 跑 DeepSeek 量化模型，为 bacmap 提供 LLM 后端
# —— NCBI 沙门菌 ~100 株基因组「分析 → 数据挖掘 → 论文写作」全流程教程

> 适用环境：Linux 个人电脑（示例硬件：**RTX 5060 Ti 16GB + 64GB 内存**，需自备 ≥300GB 磁盘）+ bacmap（pixi 环境，repo 在 `~/repos/my-project/bacmap`）
> 教程基于 bacmap 冻结架构（architecture-frozen-v1）、config.example.toml（v1.10.4+）与 Strata 0.2.12 文档
> 资料核验日期：2026-11-08（Strata 0.2.12 发布于 2026-11-07，engine 0.1.58；NCBI datasets CLI 文档生成于 2026-11-05）

---

## 0. bacmap 快速评估（先说结论）

**优点**
- **架构纪律好**：冻结架构 v1，数据分级（ADR-16，D0–D4）、内存仲裁（ADR-17）、证据链（ADR-18 run manifest）都是成文红线，不是口号。
- **安全模型成熟**：plan_hash 锁版本 + 人审闸门 + mine 沙箱（无网络）+ Web 确认，agent 乱跑的空间很小。
- **LLM 后端可插拔**：v1.6 起对话外移给外部 Harness（Hermes/opencode），bacmap 内部只留「任务内 T1 解读」端点，OpenAI 兼容协议，本地/局域网/云端一视同仁，且**本地端点才能碰 D3/D4 原始数据**——隐私设计正确。
- **科研闭环完整**：Study → Cohort → AnalysisPlan → Claim 的 P2 对象 + STROBE 就绪度（G0–G3）+ 投稿包，直接对着论文写作设计。

**短板**
- 双层人审（plan confirm + task approve）对高频 agent 工作流摩擦大（可用 `[plans.auto_confirm]` 缓解，见 §9）。
- SQLite + DBOS 是开发级配置，官方自己都注明生产建议 PostgreSQL。
- mine 沙箱对输出路径约定严格（必须写进 `~/.local/share/bacmap/results`），新手最容易在这里翻车（本机已有两次失败记录）。
- 文档中英文并行，部分章节随重构漂移，以 `config.example.toml` 为准。

**总评**：单机病原基因组分析系统里设计完成度很高，尤其适合「agent 干活 + 人审关键节点」的私有部署场景，正好是你这个用例。

---

## 1. 现实检查：目标硬件（RTX 5060 Ti 16GB + 64GB 内存）能不能跑 DeepSeek 量化模型

Strata 官方支持的 DeepSeek V4.1-Flash 量化包：

| 量化包 | 下载体积 |
|---|---|
| IST-DAS 1.75 bpw | 239 GB |
| IST-DAS 2.00 bpw | 257 GB |
| IST-DAS 2.25 bpw | 274 GB |
| Unsloth ud-q8_k_xl | 508 GB |

官方「能否跑得动」口径（MODELS.md）：**12 GB 显存 + 46–64 GB 内存 + 257 GB 磁盘**，权重可在 VRAM / RAM / SSD 三层间分配（内存不够时从 SSD 流式读专家权重，能跑但明显变慢）；支持卡型 **NVIDIA RTX 30 / 40 / 50**（Linux/Windows）与 AMD Radeon AI PRO R9700。

**目标机核对（RTX 5060 Ti 16GB + 64GB RAM）**：

| 条件 | 要求 | 目标机 | 结论 |
|---|---|---|---|
| 显存 | ≥12 GB，RTX 30/40/50 | 16 GB，RTX 50 系 | ✅ |
| 内存 | 46–64 GB | 64 GB | ✅（压线，给 OS/管线留余量要靠 SSD 分层） |
| 磁盘 | ≥257 GB（装 2.00 bpw 包） | 需自备 | ⚠️ 安装前确认，另留转换临时空间 |

**结论：可以跑，选 IST-DAS 1.75 bpw（最小的 239 GB 包）**。但要明白性能定位：64GB 内存装不下 239GB 权重，大部分专家权重会驻留 SSD 流式读取，出字速度是「能用」级别，不是 RTX 4090 级。两种取舍：

| 路线 | 模型 | 体验 | 适用 |
|---|---|---|---|
| 主线：DeepSeek V4.1-Flash IST-DAS 1.75bpw | 239 GB 磁盘 | 官方最低配，速度中等 | 要 DeepSeek 本身 |
| 快线：Qwen3.8-Flash-Next IQ2_0/IQ2_XS（37.6/39.2 GB，几乎全进内存） | 40 GB 磁盘 | 快得多，质量 good/better | 重吞吐的跑批解读 |
| 折中：Qwen3.8-Flash-Next IQ3_XXS（47 GB） | 47 GB 磁盘 | 质量 great，速度中等 | 单机平衡之选 |

> 三条路线端点协议完全一致（`http://127.0.0.1:8080/v1`），bacmap 侧只改一个 model 名字，随时可换。下文主线按 DeepSeek 写。

---

## 2. 安装 Strata（目标机：RTX 5060 Ti 16GB + 64GB RAM，Linux）

```bash
# 0) 前置：NVIDIA 驱动 580+（nvidia.com/drivers 或发行版包），无需装 CUDA toolkit
nvidia-smi    # 确认 16GB 显存可见

# 0.5) 磁盘预算：DeepSeek IST-DAS 1.75bpw = 239 GB 下载 + 转换临时空间，确认目标盘有 ≥300 GB
df -h /home

# 1) 一键安装（MIT 许可，安装器不含引擎，首次启动按显卡下载 engine 0.1.58）
# 当前版本：app/Terminal 0.2.12（2026-11-07 发布）；桌面安装包为 Strata-0.2.12-linux-x86_64.AppImage
curl -fsSL https://github.com/Niko1221/Strata/releases/latest/download/install.sh -o install.sh && sh install.sh

# 2) 先出下载计划，不下载任何东西（看清模型/量化/磁盘占用再动手）
strata launch --plan --family deepseek41 --model ist-das-1.75bpw
#   计划会显示：引擎选择（CUDA RTX 50）、显存/内存/SSD 三层分配、磁盘占用、Speed 选项（Faster）

# 3) 确认无误后真正下载并启动（首次下载 239GB，耐心；--data-dir 可把模型放大盘）
strata launch --family deepseek41 --model ist-das-1.75bpw --yes --no-tui \
  --data-dir /mnt/bigdisk/strata-data
#   也可以不带参数跑 strata launch 走交互向导；装了多个模型后再启动会询问用哪个

# 4) 验证服务（OpenAI 兼容端点默认 http://127.0.0.1:8080/v1）
curl http://127.0.0.1:8080/v1/models
curl http://127.0.0.1:8080/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"<v1/models 返回的名字>","messages":[{"role":"user","content":"ping"}]}'
```

> 提速与换型提示：
> - 0.2.12 对 12–16GB 级显卡优化明显（RTX 3060 12GB 类 prompt 提速约 3 倍），5060 Ti 16GB 直接受益；DFlash2 投机解码 drafter 会被 Auto 自动启用。
> - 239GB 包在 64GB 内存机器上是 SSD 分层模式，出字速度中等。如果跑批解读嫌慢，加装一个快线模型（磁盘预算 40–47GB）：
>
> ```bash
> strata launch --plan --family qwen --model iq2_xs    # Qwen3.8-Flash-Next IQ2_XS，39.2GB，几乎全进内存
> ```
>
>   之后多模型并存，`strata launch` 会让你选；bacmap 端点只需改 model 名。

把本地模型接给你的 agent Harness（可选但推荐，bacmap 的对话层在 Harness）：

```bash
strata connect              # 列出适配器：hermes / opencode / claude-code / codex ...
strata connect hermes --check --output json   # 发真实 prompt+工具调用做连通性验证
```

> 如果模型放在另一台机器（如更快的多卡台式机）：照常 `strata launch deepseek41` 启动服务，bacmap 端点改 `location = "lan"`、base_url 指向那台机器即可，其余配置不变。

---

## 3. 配置 bacmap 的 LLM 后端

bacmap 的内置默认端点就叫 `strata`，协议对齐零改造。编辑 `$BACMAP_HOME/config.toml`（路径用 `bacmap config path` 查）：

```toml
[llm.endpoints.strata]
location = "local"                        # 本机=local，另一台机器=lan，API=cloud
base_url = "http://127.0.0.1:8080/v1"     # Strata 的 OpenAI 兼容地址
model = "<strata 里实际加载的模型 ID>"      # 用 curl /v1/models 查到的名字（如 deepseek ist-das 包）
tier = "T1"                               # T1=仅任务内解读；T2 需要工具调用能力
max_concurrency = 1                       # 本地模型务必 1，防止内存挤爆
admin_url = "http://127.0.0.1:8080"       # ADR-17 内存仲裁：bacmap 调 /load /unload
request_timeout_s = 300

[llm.routing]
interpretation = "strata"                 # 解读流量路由到本地端点

[llm.resources]                           # 模型与分析管线同机时必开
co_located = true
min_free_ram_gb_for_heavy_steps = 24.0    # 64GB 内存机器上尤其重要：DeepSeek 权重会占掉 40GB+ 内存，
                                          # 分析管线重步骤前必须确认空闲内存，否则 OOM；bacmap 会经
                                          # admin_url 调 Strata 的 /load /unload 做内存仲裁（ADR-17）

# 数据分级（ADR-16）：本地端点可放开到 D2+；cloud 端点默认 D1、封顶 D2
# [llm.data_policy]
# cloud_max_data_class = "D1"
```

验证：

```bash
bacmap doctor    # 只读体检：dirs/database/sandbox/LLM/disk/external tools 全查一遍
```

要点：**没有 `[llm.*]` 段 bacmap 也能完整跑**——确定性管线照常出结果（C3 降级），解读由外部 agent 起草后经 `bio_verify_result` 的 `interpretation_text` 传入，再由无 LLM 的 NLI 门（analysis_claims）比对管线事实。所以 LLM 在 bacmap 里是**增强项不是依赖项**，这个降级设计值得表扬。

---

## 4. 数据获取：NCBI 沙门菌 ~100 株

> 注意：现行 datasets CLI（v2 文档，2026-11 更新）**没有 `--limit` 参数**。拿"约 100 株"的正确做法是：先下载完整清单，从数据报告里挑 100 个 accession，再按清单下载。

```bash
# 1) 安装 NCBI datasets + dataformat CLI（官方文档 how-tos/genomes/download-genome）
# 2) 先下完整沙门菌完整基因组清单（dehydrated 模式，只有元数据，很小）
datasets download genome taxon "Salmonella enterica" \
  --assembly-level complete \
  --annotated --exclude-atypical --exclude-multi-isolate \
  --include none \
  --dehydrated --filename salmonella_all.zip
unzip salmonella_all.zip -d salmonella_all

# 3) 从 assembly_data_report.jsonl 里按血清型多样性人工/脚本挑 100 个 accession
#    （优先 RefSeq GCF_，记录每个的 BioSample / GCA/GCF 号作为论文 provenance）
jq -r 'select(.accession) | .accession' salmonella_all/ncbi_dataset/data/assembly_data_report.jsonl | grep '^GCF_' | head -100 > accessions.txt
#    提示：可用 --search "serotype" 等过滤，或搭配 dataformat convert 转成 TSV 后按元数据挑选

# 4) 按 100 株清单下载序列 + 注释
datasets download genome accession --inputfile accessions.txt \
  --include genome,gbff \
  --dehydrated --filename salmonella100.zip
unzip salmonella100.zip -d ~/data/salmonella100
datasets rehydrate --directory ~/data/salmonella100
# fna 为染色体 fasta，gbff 带注释与元数据（血清型/MLST/BioSample 号）
```

选株建议（写论文时审稿人会问）：
- `--assembly-level complete` + `--annotated` + `--exclude-atypical`，基因组完整、注释齐全对分型稳定性友好；
- 批量大包超过 1000 株/15GB 时官方推荐走 `--dehydrated` + `datasets rehydrate` 两步（上面已是这个模式）；
- 有 NCBI API key 的用 `--api-key` 提升下载稳定性；
- 记录每株的 **BioSample / GCA assembly 登录号**——bacmap 的证据链（ADR-18）和研究就绪度都吃 provenance，这步偷懒后面补不回来；
- 有意混入若干参考株（如 LT2、SL1344、各血清型代表株）当锚点；
- 数据分级：公共下载的 fasta 属于 **D3/D4 原始数据**，只有 `location = local/lan` 的端点能碰——这正是你用本地模型的意义。

---

## 5. 导入并跑分析（analyze）

```bash
# 方式一：MCP 路径（推荐，走 plan 人审）
#   bacmap_create_plan(tasks=[{"type":"analyze","fasta_dir":"/home/mark/data/salmonella100"}])
#   → Web 控制台确认 → bacmap_task_status 轮询

# 方式二：CLI
bacmap task submit analyze --fasta-dir ~/data/salmonella100
bacmap task list
bacmap task show <task_id 前缀>
```

analyze 的管线步骤是 `gate → ingest_and_pipeline → ...`：数据登记 → QC → 组装/分型（SNP、cgMLST）→ 结果入 `~/.local/share/bacmap/results`。

```bash
bacmap sample          # 查样本与分析状态
bacmap run list        # 查 run 记录（证据链）
bacmap overview        # 系统总览
```

> 已知坑：目录直入（`fasta_dir/fastq_dir`）受 `allow_directory_ingestion` 控制，且空 samples 会绕过 `max_samples`——批量导入前想清楚要不要开这个开关。

---

## 6. 特征库构建（curate）与数据挖掘（mine）

**curate**：构建 AMR/毒力/血清型特征库，供后续挖掘与解读引用。

```bash
bacmap_create_plan(tasks=[{"type":"curate","scope":"pathogen"}])
```

**mine**（沙箱内跑你自己的分析脚本，**无网络**）：比如「100 株的耐药基因携带 vs 血清型/MLST 关联」：

```python
# mine 脚本铁律：输出必须写进 bacmap 结果目录，否则任务失败
# （本机已有两次 a10a14c480/8a9213e09b 失败，原因就是写到了别处）
import pandas as pd, os
OUT = os.path.expanduser("~/.local/share/bacmap/results")   # 或 /data/results
df = pd.read_csv(...)   # 输入走 input_paths 绝对路径白名单
...      # 卡方/Fisher、关联矩阵、系统发育距离 vs 表型距离
df.to_csv(os.path.join(OUT, "amr_by_serotype.csv"))
```

```bash
bacmap_create_plan(tasks=[{
  "type": "mine",
  "objective": "AMR gene presence vs serotype/MLST association across 100 NCBI Salmonella genomes",
  "script": "<上述脚本绝对路径>",
  "input_paths": ["<分析结果的绝对路径>"]
}])
```

LLM 在这一步的作用：把「我想知道耐药基因和血清型有没有关系」变成可执行的 mine 计划，并解读输出（这部分解读走 `interpretation` 路由 → 你的本地 Strata 端点）。

---

## 7. 研究工作台：Study → Cohort → Plan → Claim（论文骨架）

这是 bacmap 对「到论文写作」的正式回答，对象都已 API 化（P2）：

```bash
# 1) 建研究 + 冻结队列
bacmap research plan create --study <study_id> --cohort <cohort_id> \
  --spec '{"run_id":"...","gene":"blaKPC","test_name":"..."}'
bacmap research plan freeze <plan_id>

# 2) 跑并记录实验账本
bacmap research experiment record --plan <plan_id> --status success --run-id <run_id>

# 3) 把统计结论登记为 Claim（带证据等级）
bacmap research claim create --study <study_id> --type association \
  --wording "血清型 X 与耐药基因簇 Y 携带相关" --level E2
bacmap research claim review <claim_id> --decision approve
```

Web 控制台（`http://127.0.0.1:8800`）里：
- session 页出 2×2 表、诊断、标准图/自定义图、`FigureSpec`、带 SHA-256 的可下载产物；
- Study 页出 G0–G3 就绪度（G0 = 已冻结 Cohort + 已冻结 Plan 且哈希有效）与 **STROBE 草案**（met/partial/missing）+ 投稿包入口；
- 系统发育规划（`/research/phylo`）直接产 BEAST2 XML / IQ-TREE 命令，Logistic 回归（`/research/stats`）直接出 OR/CI/p。

> 论文素材的准备口径：**每个结论都挂在 Claim 上，每个 Claim 挂在冻结的 Plan/Run 上**——投稿时审稿人要的 reproducibility 清单就是你的 G0–G3 页面。

---

## 8. 论文写作（write 任务）

```bash
bacmap_create_plan(tasks=[{
  "type": "write",
  "objective": "Draft the Salmonella 100-genome AMR association paper (IMRaD), claims G1+, figures from session manifests",
  "draft": "<可选：已有草稿/大纲路径>"
}])
```

- write 任务的草稿默认要人审（`allow_drafts` 默认关）——论文本来就是「AI 起草、人定稿」的最终人审点，保持开着。
- 解读文字（T1）由本地端点生成后，仍要过无 LLM 的 NLI 门比对管线事实：**模型幻觉在 claims 层会被确定性门拦下**，写论文时优先引用 Claim 库而不是让模型自由发挥。
- 投稿包从 Study 页导出，附 STROBE 对照与 SHA-256 产物清单。

---

## 9. 减少人工介入的推荐配置

```toml
[plans.auto_confirm]          # fail-closed：任一条件不满足就回落人审
enabled = true
task_types = ["analyze"]      # 只全自动放行只读分析；mine/write 留人审
max_samples = 120             # 覆盖你这 100 株 + 参考株
max_tasks = 10
allow_directory_ingestion = true   # 只在导入 NCBI 批量数据期间临时开
allow_scripts = false
allow_drafts = false
```

配合流程约定：
- **analyze 全自动**（结果可重跑、只读、有证据链，事后审计即可）；
- **mine 一次人审**（看脚本 + 输入输出路径），确认后 task 层建议放行——向 bacmap 提 dev 需求：plan 确认视为对其生成 task 的放行，砍掉第二次 gate；
- **write 永远人审**（对外产出）。

---

## 10. 一页检查清单

```
[ ] 磁盘 ≥300GB 就绪（239GB 包 + 转换临时空间）
[ ] strata launch 启动，curl /v1/models 有响应
[ ] strata connect hermes --check 通过（Harness 对话层可选）
[ ] config.toml: [llm.endpoints.strata] base_url/model/max_concurrency=1/admin_url
[ ] [llm.resources] co_located=true（64GB 内存 + DeepSeek 同机，必须开）
[ ] bacmap doctor 全绿
[ ] NCBI datasets 下载 100 株，登记 BioSample/GCA 号
[ ] bacmap_create_plan(analyze, fasta_dir=...) → 确认 → task_status=succeeded
[ ] bacmap sample / run list 核对 100 株全登记
[ ] curate 特征库 → mine 脚本输出写进 ~/.local/share/bacmap/results
[ ] research: study/cohort/plan 冻结 → claim 登记 → G1+ → STROBE 对照
[ ] write 草稿人审定稿 → 投稿包导出
```

## 常见坑速查

| 症状 | 原因 | 处理 |
|---|---|---|
| 首次下载/启动 DeepSeek 包失败 | 磁盘 <257GB 或转换临时空间不足 | `--data-dir` 指到大容量盘，清理转换缓存 |
| DeepSeek 出字很慢 | 64GB 内存装不下 239GB 权重，专家权重走 SSD 流式 | 官方最低配的正常表现；或加装 Qwen IQ2_XS 快线模型 |
| mine 任务 failed @ sandbox：`none of the candidate result dirs exist` | 脚本没写进 bacmap 结果目录 | 输出路径改 `~/.local/share/bacmap/results` |
| bacmap 报 LLM 端点不可用 | model ID 与服务端不一致 | `curl /v1/models` 对齐 config 里的 model 字段 |
| 分析管线 OOM | DeepSeek 权重占 40GB+ 内存 + 管线同机挤内存 | `co_located=true` + `min_free_ram_gb_for_heavy_steps=24`，靠 ADR-17 仲裁先卸载模型 |
| cloud 端点拒绝任务 | 数据超过 D1 | 原始数据只走 local/lan 端点 |
