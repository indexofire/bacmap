[English](installation.md) | **简体中文**

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

## 3. 开发环境（可选，贡献代码时需要）

```bash
pixi run -e dev test          # pytest（当前基线 1244 passed / 1 skipped）
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

## 5. 本地 LLM（可选）

智能体层默认使用 Strata（`http://127.0.0.1:8080/v1`，OpenAI 兼容）。
部署 Strata 与模型文件后系统自动可用；也可改用任意第三方 OpenAI 兼容 API
（见配置指南 §2），或完全不配 LLM（确定性降级）。

## 6. 沙箱运行时（mine 任务用）

挖掘任务的脚本在沙箱内执行，回退链：**Apptainer → Podman →（显式开启）直通**。

```bash
which apptainer podman            # 有其一即可
export BACMAP_ALLOW_UNSANDBOXED=1 # 仅受控开发环境可用的直通通道（不推荐生产）
```

## 7. 首次验证

```bash
pixi shell
bacmap --version                                   # 版本号
bacmap web &                                       # 任务台 http://127.0.0.1:8800
timeout 3 bacmap mcp --read-only < /dev/null       # MCP 只读冒烟（应正常退出）
```

三步全过即安装完成。下一步：[配置指南](configuration.zh-CN.md) → [使用指南](usage.zh-CN.md)。
