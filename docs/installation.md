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
  - `gside`: species identification (PyPI release)
  - `gapit`: gene screening / serotyping (PyPI release)
  - `gmlst`: MLST/cgMLST/MST (PyPI release)

`pixi install` also provisions a separate **`recomb` environment** with **Gubbins** (optional
recombination detection). It is isolated from the default env because Gubbins pins
`iqtree 2.0.3.*`, which conflicts with the pipeline's `iqtree 3.1.2.*`; it is only used when
a pathogen sets `plan.recombination: true`. Run it via `pixi run -e recomb …`.

## 3. Development environment (optional, needed to contribute code)

```bash
pixi run -e dev test          # pytest（当前基线 1369 passed）
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

## 5. LLM endpoint: local model or external API (optional)

The agent layer uses Strata by default (`http://127.0.0.1:8080/v1`, OpenAI-compatible).
You can also switch to any third-party OpenAI-compatible API (GLM, DeepSeek, Kimi, vLLM, …),
or configure no LLM at all (deterministic degradation — the task form / CLI / MCP keep
working; only the conversational assistant is unavailable).

### 5.1 External API setup (GLM example, step by step)

**① Write the config** at `$BACMAP_HOME/config.toml` (default `~/.local/share/bacmap/config.toml`):

```toml
[llm.endpoints.glm]
location = "cloud"                     # external APIs are all cloud — data-class constrained (ADR-16)
base_url = "https://open.bigmodel.cn/api/paas/v4/"   # GLM standard endpoint
model = "glm-4.6"                      # change to a model you actually subscribe to
api_key_env = "GLM_API_KEY"            # only the variable NAME is stored; never the key itself
tier = "T2"
supports_tools_with_schema = true      # the chat assistant needs function calling

[llm.routing]
intent_classifier = "glm"              # conversational assistant
interpretation = "glm"                 # analysis interpretation

[llm.data_policy]
cloud_max_data_class = "D2"            # needed for the full cloud assistant belt (max D2; D3/D4 impossible)

[llm.resources]
co_located = false                     # disable memory arbitration when the model is off-machine
```

**② Inject the key** (environment variable, named per `api_key_env`):

```bash
echo 'export GLM_API_KEY="your-key"' >> ~/.bashrc
source ~/.bashrc
```

> Under a systemd service use `Environment=GLM_API_KEY=...` in the unit instead.
> `export` only affects the current shell — re-`source` in other terminals, otherwise the
> bacmap process sees a placeholder and you get 401s.

**③ Endpoint must match the key type** (a common GLM pitfall):

| Key type | base_url | Notes |
|---|---|---|
| Standard API key (console "API Keys" page) | `https://open.bigmodel.cn/api/paas/v4/` | pay-as-you-go / resource packs |
| GLM Coding Plan subscription key | `https://open.bigmodel.cn/api/coding/paas/v4/` | subscription quota, valid only on the coding endpoint |

A valid key pointed at the wrong endpoint still fails (see §5.2).

**④ Verify**:

```bash
bacmap ask "hi, what can you do"    # a normal reply means connected (CLI streams)
bacmap tui                          # header shows "LLM · glm [cloud] … 已连接/connected"
```

### 5.2 LLM troubleshooting table

| Symptom | Cause | Fix |
|---|---|---|
| `payload D4 exceeds cloud limit …` (DataClassViolationError) | Data-class block: payload level above the cloud cap | The cloud assistant trims its tool belt automatically (v1.4.30) and should not hit this; if it does, check the bacmap version |
| HTTP 401 "token expired or incorrect" | Key not visible to the process (exported in another shell), or key/endpoint mismatch | `echo $GLM_API_KEY` in the same shell; match the endpoint per §5.1③ |
| HTTP 429 code 1113 "insufficient balance / no resource pack" | Account has no quota for that model | Recharge, switch to a free model (e.g. `glm-4-flash`), or use a subscribed key |
| Model not found (code 1211) | Model name outside your subscription | Set `model` to one you actually have |
| `内置助手暂不可用 (agent run failed …)` | Unified degrade notice after retries of any of the above | Run `bacmap ask "hi" 2>&1` — the WARNING lines print the real per-attempt failure |

## 6. Sandbox runtime (prerequisite for mine tasks and external-data access)

Scripts from mining tasks (mine) execute inside a sandbox. Fallback chain:
**Apptainer → Podman → passthrough (explicitly enabled)**.
**Docker is deliberately NOT supported** (root daemon surface; also on the shell deny-list).

```bash
sudo apt-get install podman         # recommended: daemonless, rootless, best for a single workstation
# or: sudo apt-get install apptainer
# Arch / Omarchy: sudo pacman -S podman
which apptainer podman              # either one suffices; zero configuration afterwards
export BACMAP_ALLOW_UNSANDBOXED=1   # passthrough for controlled dev environments only (no isolation)
```

Without a sandbox backend, every script-bearing mine task (including the assistant's
external-data path) fails with "沙箱不可用 / sandbox unavailable" — an environment issue,
not a permission setting. See the usage guide §2, "Giving the assistant a data path".

## 7. First verification

```bash
pixi shell
bacmap --version                                   # 版本号
bacmap web &                                       # 任务台 http://127.0.0.1:8800
timeout 3 bacmap mcp --read-only < /dev/null       # MCP 只读冒烟（应正常退出）
```

If all three steps pass, installation is complete. Next steps: [Configuration guide](configuration.md) → [Usage guide](usage.md).
