**English** | [简体中文](installation.zh-CN.md)

# Installation guide

bacmap targets single-workstation deployment (Linux / 64 GB RAM recommended / data never leaves the local network). This guide covers a from-zero installation through first verification.

## 1. System requirements

| Item | Requirement | Notes |
|---|---|---|
| OS | Linux x86_64 | The bioinformatics toolchain is Linux-native throughout |
| Memory | 16 GB minimum; **64 GB** recommended | 64 GB is what it takes to run a local LLM (Strata ~45 GB) and the pipeline on the same machine |
| Network | Needed during installation; **zero outbound connections at runtime** | ADR-16: analysis data never leaves the machine |
| Disk | 50 GB+ | Reference databases (CARD/VFDB/MLST schemes, etc.) take up the bulk |

> With less than 64 GB of memory you can skip the local LLM. Per the C3 principle the
> system degrades to deterministic paths, and the full workflow (analysis / ingestion /
> reporting) remains fully usable; only intent classification and interpretation drafting
> need an external agent or a human.

## 2. Base installation

```bash
git clone <repo> bacmap && cd bacmap
pixi install          # 创建运行时环境（Python 3.12 + 生信工具链 + 三个外部工具）
pixi shell            # 进入环境
bacmap --version      # 验证：应输出版本号
```

What the environment contains (all declared in `pixi.toml`, nothing to install by hand):

- **conda toolchain**: bwa / minimap2 / samtools / bcftools / blast / bedtools / snakemake 9 and more
- **Python external tools** (ADR-20 division of labor):
  - `gside`: species identification (installed editable from a local repository, so source changes take effect immediately)
  - `gapit`: gene screening / serotyping (PyPI release)
  - `gmlst`: MLST/cgMLST/MST (PyPI release)

## 3. Development environment (optional, needed to contribute code)

```bash
pixi run -e dev test          # pytest（当前基线 948 passed / 1 skipped）
pixi run -e dev lint          # ruff
pixi run -e dev contracts     # import-linter 依赖方向契约
```

> pytest and ruff are installed only in the dev environment, so **tasks must include `-e dev`**.
> Otherwise they fall back to the system Python and fail with errors like
> `No module named 'dbos'` (a real, previously hit pitfall).

## 4. Reference databases

### gmlst typing schemes (one-time vendoring)

cgMLST schemes are downloaded from EnteroBase on demand (several hundred MB to several GB per scheme):

```bash
# 用打包的 vendor 脚本（可指定多个方案）
.pixi/envs/default/bin/python src/bacmap/workflow/scripts/vendor_cgmlst_schemes.py \
    --schemes senterica_2,ecoli_2

# 或直接用 gmlst（注意：下载中断会留损坏缓存，重跑即可续传）
gmlst scheme download senterica_2
gmlst scheme list              # ✓ = 已缓存可用
```

> ⚠️ Schemes are cached in `.pixi/envs/default/share/gmlst/` and are **lost when the pixi
> environment is rebuilt**; rerun the vendor script when that happens. EnteroBase rate-limits
> anonymous access, so retry patiently on failure or apply for an API token.

### Large identification databases (optional)

Large databases such as CheckM2 / GTDB-Tk are located through environment variables (see the configuration guide) and are not distributed with the package.

## 5. Local LLM (optional)

The agent layer uses Strata by default (`http://127.0.0.1:8080/v1`, OpenAI-compatible).
Once Strata and its model files are deployed, the system picks it up automatically. You can
also switch to any third-party OpenAI-compatible API (see configuration guide §2), or
configure no LLM at all (deterministic degradation).

## 6. Sandbox runtime (for mine tasks)

Scripts from mining tasks execute inside a sandbox. Fallback chain:
**Apptainer → Podman → passthrough (explicitly enabled)**.

```bash
which apptainer podman            # 有其一即可
export BACMAP_ALLOW_UNSANDBOXED=1 # 仅受控开发环境可用的直通通道（不推荐生产）
```

## 7. First verification

```bash
pixi shell
bacmap --version                                   # 版本号
bacmap web &                                       # 任务台 http://127.0.0.1:8800
timeout 3 bacmap mcp --read-only < /dev/null       # MCP 只读冒烟（应正常退出）
```

If all three steps pass, installation is complete. Next steps: [Configuration guide](configuration.md) → [Usage guide](usage.md).
