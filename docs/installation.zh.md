# 安装指南

bacmap 面向单工作站部署（Linux / 64 GB 内存推荐 / 数据不出网）。本文覆盖从零安装到首次验证。

## 1. 系统要求

| 项 | 要求 | 说明 |
|---|---|---|
| 操作系统 | Linux x86_64 | 生信工具链均为 Linux 原生 |
| 内存 | 16 GB 起；**64 GB** 推荐 | 64 GB 才能同机跑本地 LLM（Strata ~45 GB）+ 管线 |
| 网络 | 安装时需要；**运行时零外联** | ADR-16：分析数据永不离开本机 |
| 磁盘 | 50 GB+ | 参考数据库（CARD/VFDB/MLST 方案等）占大头 |

> 内存不足 64 GB 时可以不部署本地 LLM——系统按 C3 原则降级为确定性路径，
> 全流程（分析/入库/报告）依然完整可用，仅意图分类与解读撰写需要外部智能体或人工。

## 2. 基础安装

```bash
git clone <repo> bacmap && cd bacmap
pixi install          # 创建运行时环境（Python 3.12 + 生信工具链 + 三个外部工具）
pixi shell            # 进入环境
bacmap --version      # 验证：应输出版本号
```

环境内容（全部由 `pixi.toml` 声明，无需手动装）：

- **conda 工具链**：bwa / minimap2 / samtools / bcftools / blast / bedtools / snakemake 9 等
- **Python 外部工具**（ADR-20 分工）：
  - `gside` —— 物种鉴定（PyPI 发布版）
  - `gapit` —— 基因筛查/血清型（PyPI 发布版）
  - `gmlst` —— MLST/cgMLST/MST（PyPI 发布版）

`pixi install` 还会创建独立的 **`recomb` 环境**（含 **Gubbins**，可选重组检测）。之所以独立，
是因为 Gubbins 锁定 `iqtree 2.0.3.*`，与管线的 `iqtree 3.1.2.*` 冲突；仅当某病原设置
`plan.recombination: true` 时才用，且以 `pixi run -e recomb …` 调用。

## 3. 开发环境（可选，贡献代码时需要）

```bash
pixi run -e dev test          # pytest（当前基线 1369 passed）
pixi run -e dev lint          # ruff
pixi run -e dev contracts     # import-linter 依赖方向契约
```

> pytest / ruff 只装在 dev 环境——**任务必须带 `-e dev`**，否则会落到系统 Python 报
> `No module named 'dbos'` 类错误（真实踩坑记录）。

## 4. 参考数据库

### gmlst 分型方案（一次性 vendor）

cgMLST 方案按需从 EnteroBase 下载（每个方案数百 MB～数 GB）：

```bash
# 用打包的 vendor 脚本（可指定多个方案）
.pixi/envs/default/bin/python src/bacmap/workflow/scripts/vendor_cgmlst_schemes.py \
    --schemes senterica_2,ecoli_2

# 或直接用 gmlst（注意：下载中断会留损坏缓存，重跑即可续传）
gmlst scheme download senterica_2
gmlst scheme list              # ✓ = 已缓存可用
```

> ⚠️ 方案缓存在 `.pixi/envs/default/share/gmlst/`——**重建 pixi 环境会丢失**，
> 届时重跑 vendor 脚本。EnteroBase 匿名访问有限速，失败时耐心重试或申请 API token。

### 大型鉴定库（可选）

CheckM2 / GTDB-Tk 等大型数据库通过环境变量指向（见配置指南），不随包分发。

## 5. LLM 端点：本地模型或外部 API（可选）

智能体层默认使用 Strata（`http://127.0.0.1:8080/v1`，OpenAI 兼容）。也可改用任意
第三方 OpenAI 兼容 API（GLM、DeepSeek、Kimi、vLLM 等），或完全不配 LLM（确定性降级，
任务表单/CLI/MCP 全部可用，仅依赖 LLM 的解读与任务内智能体降级）。

### 5.1 外部 API 接入（以 GLM 为例，完整步骤）

**① 写配置** `$BACMAP_HOME/config.toml`（默认 `~/.local/share/bacmap/config.toml`）：

```toml
[llm.endpoints.glm]
location = "cloud"                     # 外部 API 都是 cloud，受数据分级约束（§3/ADR-16）
base_url = "https://open.bigmodel.cn/api/paas/v4/"   # GLM 通用端点
model = "glm-4.6"                      # 改成你实际开通的模型
api_key_env = "GLM_API_KEY"            # 只存变量名；密钥本身绝不写入文件
tier = "T2"
supports_tools_with_schema = true      # 对话助手需要 function calling

[llm.routing]
intent_classifier = "glm"              # 会话助手
interpretation = "glm"                 # 分析解读

[llm.data_policy]
cloud_max_data_class = "D2"            # 对话助手完整能力所需（上限即 D2，D3/D4 不可配置）

[llm.resources]
co_located = false                     # 模型不在本机时关闭内存仲裁
```

**② 注入密钥**（环境变量，按 `api_key_env` 指定的名字）：

```bash
echo 'export GLM_API_KEY="你的密钥"' >> ~/.bashrc
source ~/.bashrc
```

> systemd 服务运行时改用服务单元的 `Environment=GLM_API_KEY=...`。
> `export` 只对当前 shell 生效——换个终端要重新 `source`，否则 bacmap 进程拿到
> 的是占位值，表现为 401。

**③ 端点与密钥必须匹配**（GLM 常见踩坑）：

| 密钥类型 | base_url | 说明 |
|---|---|---|
| 普通 API 密钥（控制台「API Keys」页） | `https://open.bigmodel.cn/api/paas/v4/` | 按量计费/资源包 |
| GLM Coding Plan 订阅密钥 | `https://open.bigmodel.cn/api/coding/paas/v4/` | 订阅额度，仅 coding 端点有效 |

密钥有效但端点不匹配时同样报错（见 §5.2 排查表）。

**④ 验证**：

```bash
bacmap overview                  # 端点状态；确定性功能与端点无关
bacmap tui                       # 顶部标题显示「LLM · glm [cloud] … 已连接」
```

### 5.2 LLM 接入排查表

| 现象 | 原因 | 处理 |
|---|---|---|
| `payload D4 exceeds cloud limit …`（DataClassViolationError） | 数据分级拦截：该用途载荷级别超过云端上限 | 云端 MCP 实例与任务内智能体都会自动裁剪工具带；若仍出现请确认 bacmap 为当前版本 |
| HTTP 401「令牌已过期或验证不正确」 | 密钥未传进进程（export 在别的 shell），或密钥与端点类型不匹配 | 同 shell `echo $GLM_API_KEY` 自查；按 §5.1③ 对照端点 |
| HTTP 429 code 1113「余额不足或无可用资源包」 | 账户无该模型额度 | 控制台充值/换用免费模型（如 `glm-4-flash`），或换用有订阅的密钥 |
| 模型不存在（code 1211） | 模型名不在你的订阅范围 | 改 `model` 为实际开通的模型名 |
| `LLM 不可用 / degraded（agent run failed …）` | 以上任意原因重试耗尽后的统一降级提示 | 用 `bacmap overview` 看端点状态；任务级失败的原因写在任务消息里 |

## 6. 沙箱运行时（mine 任务与外部数据读取的前提）

挖掘任务（mine）的脚本在沙箱内执行，回退链：**Apptainer → Podman →（显式开启）直通**。
**注意：docker 不在支持链内**（守护进程是 root 权限面，且被刻意列入 shell 禁用清单）。

```bash
sudo apt-get install podman         # 推荐：无守护进程、无 root、单工作站最合适
# 或 sudo apt-get install apptainer
# Arch / Omarchy：sudo pacman -S podman
which apptainer podman              # 有其一即可，装完零配置
export BACMAP_ALLOW_UNSANDBOXED=1   # 仅受控开发环境的直通通道（无隔离，不推荐生产）
```

没有沙箱后端时，凡带脚本的 mine 任务（包括对话助手读取外部数据的链路）都会失败并
提示「沙箱不可用」——这是执行环境问题，不是权限配置问题。数据接入方式见
[使用指南](usage.zh.md) §2「给助手一份数据路径」。

## 7. 首次验证

```bash
pixi shell
bacmap --version                                   # 版本号
bacmap web &                                       # 任务台 http://127.0.0.1:8800
timeout 3 bacmap mcp --read-only < /dev/null       # MCP 只读冒烟（应正常退出）
```

三步全过即安装完成。下一步：[配置指南](configuration.zh.md) → [使用指南](usage.zh.md)。
