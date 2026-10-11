[English](usage.md) | **简体中文**

# 使用指南

bacmap 有三个人口：**CLI**（运维）、**Web 任务台**（人）、**MCP**（AI 智能体）。

## 1. CLI

```bash
bacmap --version
bacmap web [--host 127.0.0.1] [--port 8800]   # Web 任务台（默认仅绑本机）
bacmap mcp [--read-only] [--home H]           # stdio MCP 服务器（智能体接入用）
```

## 2. Web 任务台（人的主界面）

`bacmap web` 后浏览器打开 `http://127.0.0.1:8800`：

1. **提交任务**——左侧表单选任务类型、填样本列表（analyze）或范围 JSON（curate）
2. **监控**——右侧任务表实时状态（六态徽章：排队中/运行中/待审批/已完成/已失败/已取消），点进详情页每 2 秒自动刷新
3. **审批**——任务到 `待审批` 时详情页出现琥珀色审批卡：填审批人、决定（approve/reject）、签名口令，提交后过挖掘门/发布门放行

> 审批是六道门的一环：未签字的挖掘产物进不了报告、不达金标准的特征库发不了版——
> 这是设计（智能体不能自己签字），不是故障。

### 远程访问：SSH 隧道（推荐方式）

bacmap web 默认只绑 `127.0.0.1`（ADR-16）。需要从其他电脑访问时，**不要**直接
`--host 0.0.0.0` 裸暴露（界面无认证，局域网内任何人可提交/审批任务）——用 SSH 隧道，
加密与认证全部由 SSH 承担，bacmap 侧零改动：

```bash
# 在你自己的电脑上执行（user 为工作站账号，10.0.0.5 换成工作站实际 IP）：
ssh -L 8800:127.0.0.1:8800 user@10.0.0.5
# 保持连接，然后本地浏览器打开 http://127.0.0.1:8800
```

- 多个用户各自建各自的隧道，互不影响
- 传输全程加密——符合基因组数据（D3/D4）不出本地网络且不落明文的要求
- 无需 root、无需在工作站开防火墙端口、无需给 bacmap 加认证层
- 数据文件仍由操作员在工作机上按[配置指南 §5](configuration.zh-CN.md)注册；
  远程上传功能属于规划项（待智能体生信分析功能完成后再考虑）

## 3. MCP 智能体接入

任意支持 MCP stdio 的客户端都能接（Hermes / Codex / OpenCode / OpenClaw / Claude…）。
客户端配置样例：

```json
// OpenCode（opencode.json）
{ "mcp": { "bacmap": { "type": "local",
  "command": ["/path/to/.pixi/envs/default/bin/bacmap", "mcp"], "enabled": true } } }
```

```toml
# Codex（~/.codex/config.toml）
[mcp_servers.bacmap]
command = "/path/to/.pixi/envs/default/bin/bacmap"
args = ["mcp"]
```

接入后智能体可调 **22 个工具**：

| 类别 | 工具 | 说明 |
|---|---|---|
| 单步计算（20） | `bio_fastq_qc` `bio_align` `bio_blast` `bio_samtools` `bio_variant` `bio_gene_scan` `bio_seq_stats` … | 同步返回结果，可吃任意本地路径 |
| 任务提交 | `bacmap_submit_task` | **写操作唯一入口**；analyze/curate 任务异步执行 |
| 任务查询 | `bacmap_task_status` | 轮询状态与门消息 |

智能体还可经 MCP prompts 获取领域说明书：每个已交付角色（analyst / curator / miner / literature / writer / epidemiologist）以 `bacmap_role_<名称>` prompt 暴露其说明书（全局原则 + 权限边界 + SKILL 指导）。

安全模型（对任何客户端一致）：

- MCP 通道**无直写**——写库只能经任务提交走六道门；
- 不信任的客户端先接 `bacmap mcp --read-only`（只暴露查询工具）；
- 连通性排查：`hermes mcp test bacmap`。

在智能体里的典型对话：

> "对 SAM-TYP-001 跑全套分析" → 智能体调 `bacmap_submit_task`(analyze) → 拿 task_id
> → 轮询 `bacmap_task_status` → "已完成，报告在 results/SAM-TYP-001/report/"

## 4. 四类任务与门

| 任务 | 内容 | 关键门 |
|---|---|---|
| `analyze` | 全流程管线：QC→组装→分型→AMR/毒力→报告 | 分析结论门（矛盾解读标记人工复核） |
| `curate` | 本地流行特征库构建（去标识、汇总） | **发布门**：不达金标准阈值拒绝发布 |
| `mine` | 沙箱内跑自定义分析脚本 | **签字门**：未签字产物不得进入报告 |
| `write` | LLM 撰写报告/简报 | **引用门**：引用知识库中不存在的条目拒绝导出 |

断点恢复：任务引擎基于 DBOS，运行中 kill 进程重启后从断点继续（V2 已验证）。

## 5. 端到端示例（新样本上机 → 报告）

```bash
# ① 布局数据并注册
cp /mnt/seq_run/SAM-NEW-100_R{1,2}.fastq.gz ~/.local/share/bacmap/gs/SAM-NEW-100/
echo -e "SAM-NEW-100\tSalmonella\tgs/SAM-NEW-100/SAM-NEW-100_R1.fastq.gz\tgs/SAM-NEW-100/SAM-NEW-100_R2.fastq.gz" \
  >> ~/.local/share/bacmap/workflows/config/samples.tsv

# ② 提交（Web 表单选 analyze 填 SAM-NEW-100，或智能体对话）
# ③ 监控直至完成；待审批任务在详情页签字
# ④ 取报告
ls ~/.local/share/bacmap/results/SAM-NEW-100/report/
```

## 6. 已知能力边界（外部工具依赖）

| 字段/能力 | 状态 | 等待 |
|---|---|---|
| 物种鉴定（marker/panel/mash 档） | ✅ gside 已接入 | — |
| 血清型 | ⏳ `pending_gapit` 占位 | gapit 血清型子命令（开发中） |
| 基因组注释 | ⏳ `pending_external_tool` 占位 | gapit 注释子命令 |
| 物种鉴定 GTDB-Tk 标准档 / 分类 | ⏳ `pending_gside` 占位 | gside GTDB-Tk 档 |

管线在这些字段上照常运行并输出占位值，外部能力就绪后替换规则即可，无需改架构。
