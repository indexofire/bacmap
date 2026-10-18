**English** | [简体中文（权威）](architecture-frozen-v1.md)

*Reference translation. The Chinese version is authoritative; in case of divergence, the Chinese text governs.*

# BacMAP Standalone Framework Design (Frozen v1.4.10)

- **Date**: 2026-10-09 (v1.1 through v1.4.7 revised the same day; see Section 10)
- **Status**: Frozen. Becomes "Confirmed" once all verification items in Section 8 pass
- **Basis**: Round 1 debate (`dev/debate-standalone-architecture.md`, local-only, not committed), Round 2 debate (`dev/debate-round2-harness-vs-delivery.md`), research evidence (`dev/research-framework-evidence.md`) (cited below as "evidence §x")
- **Change rule**: for any decision marked "frozen" in this document, a change requires adding a new ADR revision record (Section 10) stating the reason, evidence, and migration cost; parts marked "replaceable" may have their implementation swapped freely as long as the interface stays unchanged

---

## 0. Project Positioning (Core Definition)

**bacmap is a standalone, locally runnable pathogen genome analysis system implemented in Python, with a built-in AI agent layer, exposing its capabilities to external AI assistants through MCP.**

| Question | Answer |
|---|---|
| Is bacmap an AI agent implemented in Python? | Yes, but the agent is only one layer. The core is a deterministic analysis kernel (pipelines, GOM, verification, gates); the agent layer (pydantic-ai plus a local model or LLM API, routed by data classification) handles understanding user intent, interpreting results, and carrying out open-ended tasks. Remove the agent layer and the deterministic features still work as usual (C3) |
| Is a platform like Hermes required? | **No.** bacmap ships with its own web UI, CLI, and built-in agent, connects directly to a local model service (Strata by default) or an LLM API (ADR-08), and completes all functions on its own. Hermes is just one optional external client (ADR-15) |
| Are the multiple expert roles a "multi-agent" system? | No, it is not a set of agents conversing autonomously. It is **code-orchestrated multi-role**: the same model, with temporary agent instances created per task step from different role configurations (instructions + tool allowlist + permissions); each instance ends when its step is done, and roles exchange results only through the GOM and the task workspace (ADR-10) |
| What implements the agent layer? | pydantic-ai handles the "call model, run tools, validate output" loop inside a single agent; multi-role orchestration, the task state machine, gates, and the request queue are implemented by bacmap's own code (ADR-08, ADR-10) |
| How are bioinformatics analyses done? | Standard analyses always go through Snakemake workflows (L1, the single authoritative source); Python/R scripts written by the LLM are used only for exploratory mining inside the sandbox (L2). Their results cannot become authoritative facts, but they may be promoted to L1 after human rewriting and verification (ADR-11) |
| What is the local epidemiological baseline library? | Not a reference database for analysis, but a **collection of epidemiological characteristics of local strains**: stored in the GOM, it aggregates typing, resistance, cgMLST profiles, and time/place/source of local strains, used for matching characteristics of new isolates and mining local epidemiological patterns (ADR-19) |
| Does it integrate AI agent tools through MCP? | **The direction is the reverse: bacmap is the MCP server and does not assemble itself out of MCP.** The built-in agent calls the tool registry in-process; MCP is the outbound channel that lets any MCP client (Hermes, Claude, Codex, Cursor, the Strata chat page, etc.) use bacmap's tools. bacmap can also act as an MCP client to attach a small set of optional external capabilities (such as the GBrain knowledge base), but it does not depend on them |
| Can other AI assistants integrate with bacmap? | Yes. Any MCP-capable assistant can call bacmap's tools and receive domain instructions through MCP prompts/resources (the SKILL.md content). All writes go through "task submission", so the gates apply equally to every client (ADR-07, ADR-12) |

```
          外部 AI 助手（可选）                       bacmap（独立运行）
  ┌───────────────────────────────┐    MCP    ┌──────────────────────────────────┐
  │ Hermes · Claude · Codex ·     │ ───────▶ │ MCP Server ─┐                      │
  │ Cursor · Strata 聊天页 · ...  │          │ Web / CLI ──┼─▶ 任务层（门） ─▶ 内核 │
  └───────────────────────────────┘          │ 内置智能体 ─┘        ▲              │
                                               │      │ OpenAI 兼容 API │              │
                                               └──────┼─────────────────┼──────────────┘
                                                      ▼                 │
                                      Strata（本地默认）/ LLM API   Snakemake 9
```

---

## 1. Scope and Hard Constraints

**Functional scope**: pathogen genome analysis, GOM data management and mining, local epidemiological baseline library construction (corrected in v1.2: epidemiological characteristics of strains, stored in the GOM, not a reference library for analysis), and report and manuscript writing.

**Hard constraints (non-negotiable)**:

| # | Constraint | Source |
|---|---|---|
| C1 | Runs on a single Linux workstation/server, usable offline | project.md §2.1 |
| C2 | Sequence data (D3) and personally or epidemiologically identifiable information (D4) **never** leave the local network; single-strain typing results (D2) are not sent to public endpoints by default, and an administrator may allow them up to D2 per ADR-16; LLM APIs may only receive what the data classification permits | Round 1 ruling, refined in v1.2/v1.4.3; **user approved (2026-10-09; later adjustments go through the revision process)** |
| C3 | **All deterministic functions must work without an LLM** (analysis, baseline library release, reports) | Added in this document; jointly guaranteed by ADR-02 dependency direction, the ADR-06 deterministic path, and the ADR-09 T0 tier |
| C4 | Every conclusion carries an evidence chain `(strain_id, run_id)`: `run_id` points to the complete analysis run record of one analysis run, including analysis time, pipeline version, all parameters, measured versions of reference databases and tools, and input file checksums (expanded in v1.2 from a triple evidence chain, ADR-18); results cannot be overwritten | project.md §4.5–4.6 |
| C5 | Text produced by the LLM must pass a gate before display, export, or storage | Round 2 ruling, ADR-07 |
| C6 | Support Xinchuang environments (Kylin/UOS, including ARM) | Round 2 debate |

---

## 2. Overall Architecture

```
┌────────────────────────── 接口层（可并存） ──────────────────────────┐
│  Web UI (FastAPI+Jinja2+htmx)   CLI   MCP Server   Hermes 插件适配器  │
└───────────────┬──────────────────────────────┬────────────────────────┘
                │ 提交任务 / 查询                │ 只读工具 / 提交任务
┌───────────────▼──────────────────────────────▼────────────────────────┐
│  bacmap.tasks   任务层：封闭任务类型 · 状态机 · 门 · 审批              │
│                 （TaskEngine 接口，默认实现 DBOS）                      │
├───────────────────────────────┬────────────────────────────────────────┤
│  bacmap.agent  智能体层        │  bacmap.workflow  工作流层              │
│  LLM 接入 · 角色 · 意图分类    │  Snakemake 9 CLI（WorkflowRunner 接口） │
│  开放路径运行时 · 沙箱         │                                        │
├───────────────────────────────┴────────────────────────────────────────┤
│  bacmap.tools   工具层：ToolSpec 注册表（唯一事实来源）                  │
├─────────────────────────────────────────────────────────────────────────┤
│  bacmap.core    领域层：engine · analysis · typing · pathogens · verify │
│  bacmap.store   存储层：GOM · 索引 · 知识库（KnowledgeStore 接口）       │
└─────────────────────────────────────────────────────────────────────────┘
        依赖方向只能自上而下；core / store / tools 不得导入 agent
```

Two paths (ruled in Round 2, confirmed this round):

| Path | Task types | Driver | Role of the LLM |
|---|---|---|---|
| Deterministic path | analysis, baseline library release, reports | task state machine (code) | optional: writing interpretations; must pass a gate |
| Open path | data mining, manuscript writing | built-in agent runtime (pydantic-ai) | writes scripts, retrieves, drafts; executes inside the sandbox; outputs pass a gate |

> Note: "report" comes in two kinds (clarified in v1.4.3): (1) the **templated analysis report** at the end of an `analyze` task (deterministic path, generated in a `generate_report` style, containing no free text or only interpretations that have already passed a gate); (2) **custom writing** in a `write` task (briefs, manuscripts; open path, produced with a human signature after the mining-conclusion gate and the citation gate). The "report and manuscript writing" capability spans both paths.

---

## 3. Architecture Decision Records (ADR)

Each ADR is marked **Frozen** (changes must go through the revision process) or **Replaceable** (interface frozen, implementation swappable).

### ADR-01 Language and Runtime: Frozen
- **Decision**: Python 3.12 (`>=3.12,<3.14`); pixi is the only environment manager, handling both Python dependencies and bioinformatics CLI tools; no Node/Bun introduced at runtime.
- **Rationale**: all existing assets are Python (evidence §2.1); LLM integration, the MCP SDK, and the durable execution library all have first-class Python support; a single environment makes offline packaging easy (C1, C6).
- **Rejected**: a TypeScript shell (excluded in Round 2); a Rust kernel (to be revisited per the Round 1 trigger conditions).
- **Reversal cost**: extremely high.

### ADR-02 Package Structure and Dependency Direction: Frozen
- **Decision**: single repository, single distribution package `bacmap`, subdivided into subpackages per Section 6; dependency direction enforced in CI with `import-linter`.
- **Rules**:
  - `core`, `store`, and `tools` must not import `agent`, `tasks`, or the interface layers
  - Only `bacmap.agent.llm` may import LLM libraries (pydantic-ai/openai)
  - Only `bacmap.tasks.engine` may import DBOS
  - Only `bacmap.workflow` may call Snakemake
  - MCP **client** code is allowed only in `bacmap.store.knowledge` (optional external knowledge backend such as GBrain) and `bacmap.agent.llm` (if external tool capability is needed); `bacmap.interfaces.mcp` implements only the MCP server (ADR-12)
- **Rationale**: the three third-party dependencies (LLM library, durable execution library, Snakemake) are each confined to one module, so replacing one later touches a single place; this guarantees C3 (remove the agent layer and the system still runs).

### ADR-03 Configuration and Paths: Frozen
- **Decision**: no path is derived from the source location. The data root is `BACMAP_HOME` (default `~/.local/share/bacmap`), the config file is `$BACMAP_HOME/config.toml`, loaded and validated by a pydantic model; bioinformatics tools are resolved from the PATH of the current pixi environment.
- **Rationale**: the existing `config.py` hardcodes `PIXI_BIN` and `PROJECT_ROOT` to the development repository directory, and plugins load through symlinks (evidence §2.2). This is the root cause of the standalone build failing to install.

### ADR-04 Tool Contract: Frozen
- **Decision**: each tool is described by a `ToolSpec` (Section 4.1): inputs are pydantic models, the JSON Schema is generated from the model, replacing the hand-written 973-line `schemas.py`; every tool returns a uniform `ToolResult` envelope.
- **Tool metadata** (frozen fields): `name`, `trust_layer` (L1/L2/L3), `effect` (`read` / `compute` / `write`), `long_running`, `version`, `output_data_class` (added in v1.2: the data level D0–D4 of the tool's output, which decides whether that output may be sent to an LLM API; see ADR-16).
- **Migration**: the existing 29 `handler(args: dict) -> str` handlers are first wrapped with an adapter, then rewritten one by one into typed inputs.
- **Rationale**: the tool registry is the single source of truth shared by the MCP server, the Hermes plugin, and the built-in agent (Round 2 ruling); the `effect` field is the basis for gate and permission control.

### ADR-05 Workflow Engine: Frozen (engine) / Replaceable (invocation style)
- **Decision**: adopt Snakemake 9 (confirmed in v1.1), pinned in pixi as `snakemake = "9.27.*"`; upgrading a minor version requires re-running V1. It is invoked only as a CLI subprocess, wrapped behind the `WorkflowRunner` interface; `.snakemake/` checkpoint resume is preserved.
- **Rationale**: 7.x lost maintenance in 2023-08; the existing code uses only the CLI and none of the directives removed in 8.x (evidence §2.3, §4.1), so the upgrade cost is low; the CLI is the most stable contract across 7→8→9.
- **Rejected**: staying pinned at 7.32 (it freezes the Python version); switching to in-process calls via `snakemake.api` (insufficient justification).

### ADR-06 Task State Machine: Frozen (interface and tables) / Replaceable (execution library)
- **Decision**:
  - Closed task types: `analyze`, `curate`, `mine`, `write` (Section 4.3; v1.2 renamed `build_db` to `curate`, now meaning local epidemiological baseline library construction, see ADR-19); adding a type requires revising this ADR
  - The default implementation of the `TaskEngine` interface is **DBOS Transact** (embedded, SQLite system database, MIT)
  - The four tables `tasks`, `approvals`, `analysis_runs` (ADR-18), and `baseline_releases` (ADR-19), plus the GOM `events`, are owned by bacmap and are the only externally visible state; the DBOS system database is an internal implementation detail using a separate SQLite file
- **Rationale**: crash recovery, waiting for human approval, and long tasks (about 8 hours for 96 strains) are required; DBOS is the only option satisfying "no service process + SQLite + human wait + automatic recovery" all at once (evidence §4.2). Both debate rounds underestimated the cost of writing these by hand.
- **Fallback**: if verification item V2 does not pass, switch to a hand-written `transitions` + SQLite implementation with the interface and tables unchanged.

### ADR-07 Gates: Frozen
- **Decision**: gates are code checkpoints between task steps, enforced by `bacmap.tasks`; no interface layer can bypass them.
- **Four gates**:

| Gate | Trigger point | What is checked | On failure |
|---|---|---|---|
| Analysis-conclusion gate | before interpretation text is displayed, exported, or stored | deterministic verifier + NLI reflector (both deterministic code, evidence §1 item 12) | flagged `NEEDS_HUMAN_REVIEW` and enters approval |
| Baseline library release gate (changed in v1.2) | before releasing a new local epidemiological baseline library version | for every strain included: the deterministic verifier has passed, QC is acceptable, required metadata (isolation date, region, source) is complete, no duplicate strains; personal information is separated from characteristic data; human signature | release refused, the previous version remains unchanged |
| Mining-conclusion gate | before mining outputs enter a report | reproducible in the sandbox + user signature | outputs stay in the workspace and do not enter the report |
| Citation gate | before a manuscript/report is finalized | every citation can be found in the local knowledge base | missing citations flagged, export refused |

- **Rule**: all `effect=write` operations go only through task submission; external MCP clients and Hermes cannot write to the GOM or released databases directly.
- **Rationale**: the current verification is "optional" (Round 2 F5), and small local models easily fail to call it.

### ADR-08 LLM Integration: Frozen (interface) / Replaceable (library)
- **Decision**: pydantic-ai (major version pinned) is the only LLM/agent library, importable only from `bacmap.agent.llm`. Two endpoint classes are supported, equal in standing and selected by configuration (clarified in v1.2):
  - **Local model service**: Strata by default (ADR-09); OpenAI-compatible services such as vLLM and Ollama also work
  - **LLM API**: OpenAI-compatible APIs (such as Z.AI GLM, DeepSeek, Tongyi, via `OpenAIChatModel` + `base_url`), and the Anthropic Messages API (via pydantic-ai's Anthropic model)
  - Each endpoint declares `location` in the configuration: `local` (this machine), `lan` (intranet, such as an institution's self-hosted inference server, treated as local), `cloud` (public API); `cloud` endpoints are subject to the ADR-16 data classification
  - Roles can be routed to different endpoints individually (for example intent classification on local Strata, literature-review drafting on an API model)
- **Calling rules** (revised in v1.1 to match Strata's actual capabilities, evidence §8):
  - Intent classification and interpretation generation must use structured output (JSON Schema); **on a parse failure, retry up to 2 times, and if it still fails, proceed as if there is no LLM**. Strata's structured output is "prompt + post-hoc validation", without grammar-constrained decoding
  - Structured output and tool calls are **never mixed in the same request** (Strata rejects `response_format` + `tools`): calls without tools use `response_format`; tool-carrying agents emit output as "the final result is also a tool call" (pydantic-ai's Tool Output mode)
  - Tool calls and classification requests always disable thinking: `reasoning_effort: "none"` (equivalent to `enable_thinking=false`); complex reasoning on the open path may enable `low`/`medium` per task and set `reasoning_budget_tokens`
  - A Strata deployment must have the `jsonschema` package installed, otherwise `json_schema` only checks "is it a JSON object"
  - The rules above defer to per-endpoint capability declarations: the configuration marks each endpoint with `supports_tools_with_schema`, `constrained_decoding`, `max_concurrency`; API endpoints with native structured output can use it directly, and the code writes no vendor-specific branches
- **Rationale**: one library covers structured output, tool calls, the MCP client, and tool-level human approval (evidence §5.1, §6.1); the conflict between thinking mode and tool calls is the known top pitfall (evidence §5.2).
- **Rejected**: LiteLLM (the enterprise catalog is a paid license and it releases too often); hand-writing openai SDK calls directly (validation retry and the tool loop would have to be implemented by hand).

### ADR-09 Model Tiers: Frozen
- **Decision**:

From v1.2 on, "capability tier" and "deployment location" are two independent dimensions: the tier decides what the model may do, the location decides what data it may see (ADR-16).

| Capability tier | Example | Allowed uses |
|---|---|---|
| T0 | no LLM | all deterministic functions (C3) |
| T1 | small local model (optional, not the default) | only single-step intent classification and schema-constrained interpretation generation; **no multi-step tool calls** |
| T2 | **Strata + Qwen3.8-Flash-Next** (local default); LLM API models of comparable capability | intent classification, interpretation, multi-step tool calls, open-path agent |

| Deployment location | Example | Data it may receive |
|---|---|---|
| `local` / `lan` | Strata, institutional intranet inference servers | all of D0–D4 (still subject to the role allowlist) |
| `cloud` | GLM, DeepSeek, Claude and other public APIs | D0–D1 by default; an administrator may relax to D2; D3 and D4 are never sent |

- **v1.1 change**: Qwen3-14B is dropped as the local default model; the local default becomes Qwen3.8-Flash-Next running under Strata (an MoE of roughly 125B parameters), so T1 is no longer a required tier and a single local model covers both T1 and T2 uses.
- **v1.2 change**: the original T3 tier is abolished; cloud APIs are grouped into T2 by capability and constrained by data classification by location; a local machine without a GPU can run configured with API endpoints only (subject to data classification; roles that would touch data above D2 refuse to start).
- **Local hardware baseline**: NVIDIA/AMD GPU with ≥12 GB VRAM + **64 GB system memory** (Strata keeps expert weights in memory and the rest in VRAM; "64G" means memory per Strata's requirements) + an SSD of about 80 GB.
- **Quantization tier choice**:
  - model has the machine to itself: IQ3_XXS (3-bit, roughly 47 GB loaded, context ≤128K)
  - model and analysis pipeline share one 64 GB machine: **IQ2_XS** (about 39 GB), or keep IQ3_XXS and enable the resource arbitration of ADR-17
- Each role declares `min_model_tier`; if the runtime finds the configured model is below the requirement, it refuses to start the role and tells the user to use the deterministic path instead.
- **Tiers are monotonic**: T2 covers all T1 uses (when the configuration has only Strata, a role with "minimum tier T1" runs on the T2 model).
- **Rationale**: Qwen3-14B scored only 34.8% on BFCL V4 multi-turn tool calling (evidence §5.3); Strata provides an OpenAI-compatible interface with tool calling on an ordinary PC with 12 GB VRAM + 64 GB memory, and both tool calling and structured output were verified locally (evidence §8). Qwen3.8-Flash-Next has no published function-calling benchmark yet; its fitness is judged by the measured V3 results.

### ADR-10 Multi-Agent Collaboration: Frozen
- **Decision**:
  - **The supervisor is code**: intent → (structured classification by the local model) → closed task type → **the decomposition is shown to the user for confirmation** → the state machine executes the steps defined in code (v1.1: in testing, the model decomposed "run samples + compare + write a brief" into one extra unrequested `build_db` task; that task type was renamed `curate` as of v1.2, and the original observed wording is kept here, evidence §8)
  - **Sub-agents run serially**: the local model service has a single slot and processes one request at a time (ADR-17); sub-agents run serially through the queue, not concurrently
  - **This is not a "multi-agent system" of agents conversing autonomously**, but code-orchestrated multi-role: temporary agent instances are created per task step from different role configurations (the model is routed per §4.5; by default all roles use the same local Strata instance, serially; once API endpoints are configured, roles may use heterogeneous models), and roles do not talk to each other autonomously (clarified in v1.2, corrected in v1.4.3 for the outdated "same model" wording)
  - **Each role is defined by three files, each governing one thing** (clarified in v1.2):

| File | Content | Loaded when | Can constrain permissions |
|---|---|---|---|
| `agent/principles.md` (global principles, analogous to Hermes's SOUL.md) | system identity and general principles: public-health compliance, no invented conclusions, citations must have sources, say so when uncertain | loaded every time | no |
| `agent/skills/<角色>/SKILL.md` (instructions, agentskills.io spec) | **how** this role works: methods, interpretation criteria, output format | loaded at role startup | no |
| `agent/roles/<角色>.role.yaml` (role manifest, bacmap's own format) | **what** this role may do: tool allowlist, capability tier, allowed endpoint locations, data level ceiling, file scope, network access or not | read and enforced by code | **yes, only this file can** |

  - What distinguishes roles is the tool allowlist and data level ceiling in the role manifest, enforced by code; SKILL.md and the global principles are only guidance to the model
  - **Sub-agents are short-lived**: pick up a task, read the GOM, write the task workspace, finish; sub-agents do not communicate directly with each other
  - **No LLM reviewer role**: review is done by the gates
- **Role table**:

| Role | Task types | Minimum tier | Write access |
|---|---|---|---|
| Bioinformatics analyst | analyze | T1 (interpretation only) | none (results are written by the pipeline) |
| Baseline library curator (v1.2 replaces "database builder") | curate | T0 suffices; T2 optional (metadata cleaning suggestions, characteristic summaries) | baseline library staging area |
| Mining analyst | mine | T2 | task workspace (inside the sandbox) |
| Literature searcher | write, mine | T2 | knowledge base import staging area |
| Writer | write | T2 | task workspace |
| Epidemiologist | analyze (cohort), mine | T2 | task workspace |

- **Rationale**: tool permissions cannot live in SKILL.md, because agentskills.io's `allowed-tools` is still an experimental field (evidence §7.4); scientific multi-agent systems have all converged on the "plan/execute + independent verification + explicit provenance" pattern (Round 1 appendix A).

### ADR-11 Open Path Execution and Sandbox: Frozen (isolation requirements) / Replaceable (technology)
- **Decision**: the open path is driven by a pydantic-ai agent; scripts the agent writes can run only inside the sandbox:
  - default is **Apptainer**: `--containall --cleanenv --network none`; the task workspace is mounted read-write, GOM exported data is mounted read-only
  - SIF images are pre-built, versioned, and distributed offline
  - when the host has no Apptainer, fall back to rootless Podman (`--network none`)
- **Relationship between L1 and L2** (clarified in v1.2):
  - Snakemake workflows (L1) are the single authoritative source for species, serotype, MLST, resistance, virulence, provenance, and similar results; the LLM must not modify workflow rules
  - Scripts written by the LLM (L2) produce only exploratory results; after passing the mining-conclusion gate and being signed, they are cited in reports labeled "exploratory results" and are never written into authoritative result tables
  - **Promotion path**: an L2 script that gets reused is rewritten by a human into a Snakemake rule or a formal `ToolSpec` tool; once tests are added and verification passes, it enters L1, and the original script plus the promotion record are written into the GOM `events`
- **Rationale**: Apptainer is the bioinformatics/HPC standard and reproduces offline in a single file; the Biomni lesson is "isolation is mandatory, and environments must be pre-packaged" (evidence §6.2); Kylin V10 needs unprivileged userns enabled.
- **Positioning of Hermes**: not used as the built-in executor (the plugin API carries no stability guarantee; it would require native tool calling and ≥64K context, evidence §3.1, §6.1); it connects as an external client via MCP or the plugin (ADR-15).

### ADR-12 MCP Boundary: Frozen
- **Decision**:
  - **MCP is for the outside only**: the built-in agent uses the tool registry in-process (pydantic-ai tools generated from `ToolSpec`) and does not go through MCP (clarified in v1.1)
  - use the official `mcp>=2.3,<3` `MCPServer`, implementing the 2026-07-28 spec
  - transports: stdio (local clients such as Hermes) + Streamable HTTP (bound only to 127.0.0.1 or a unix socket, bearer token auth)
  - besides tools, role instructions (SKILL.md) are exposed as MCP prompts/resources so external assistants can also get domain guidance
  - long tasks return a job handle, with separate `job_status` and `job_cancel` tools; progress is pushed via `progressToken`; adopted once SDK support such as the Tasks extension arrives
  - MCP exposes only tools with `effect=read/compute`, plus task-submission tools; no direct-write tools are exposed
- **Security**: the startup command in client configs is hardcoded; all parameters are strictly validated against JSON Schema; logs go to stderr (Logging is deprecated).
- **Rationale**: evidence §7.1–7.3; Hermes ships an `mcp==2.0.0` client of the same generation as the server (evidence §3.5).

### ADR-13 Data Layer: Frozen (GOM) / Replaceable (knowledge base implementation)
- **Decision**:
  - SQLite (WAL) is kept and the GOM table structure carries over (evidence §2.4); schema versions are managed with `PRAGMA user_version` + numbered SQL migration scripts
  - four new tables: `tasks`, `approvals`, `analysis_runs` (run records, ADR-18), `baseline_releases` (local epidemiological baseline library versions, ADR-19) (v1.2: the original `db_releases` is dropped)
  - two kinds of "database version" are strictly distinguished (v1.2): versions of **reference databases** (CARD, VFDB, PlasmidFinder, MLST/cgMLST schemes, etc., inputs to analysis) are recorded in the run record; versions of the **local epidemiological baseline library** (a summary of analysis results) are recorded in `baseline_releases`, and whenever a conclusion cites local characteristic matching, the baseline library version used is recorded alongside
  - the knowledge base is accessed through the `KnowledgeStore` interface; the v1 implementation is SQLite FTS5 (sqlite-vec optional); GBrain can serve as an optional MCP backend, not a dependency
  - structured analysis facts do not enter the vector store (project.md §8.3)
- **Rationale**: the GOM has been validated across seven versions. GBrain connects as an independent process over MCP; the Bun runtime exists only on machines that choose to deploy GBrain and **does not enter the bacmap runtime**, so it does not conflict with ADR-01 (no Node/Bun at runtime); the cost is that machines enabling that backend need one extra Bun service to maintain, which is why it remains optional.

### ADR-14 Web UI: Replaceable
- **Decision**: FastAPI + Jinja2 + htmx + SSE; upgraded from a read-only dashboard to the primary interaction entry (task submission, chat, approval, signing); binds to localhost only by default, LAN access requires enabling authentication.
- **Rationale**: front-line users do not use terminals (Round 2); no front-end engineering is introduced (ADR-01).

### ADR-15 Role of Hermes: Replaceable (rewritten in v1.1)
- **Positioning**: Hermes is **one of bacmap's optional external clients**, equal in standing to Claude, Codex, Cursor, the Strata chat page, and so on. bacmap does not depend on Hermes to run, and no core functionality lives in Hermes.
- **It is not a case of "other assistants cannot integrate with bacmap"**: any MCP client can use all of bacmap's tools and instructions (ADR-12); the gates execute in bacmap's task layer, independent of the client (ADR-07).
- **What Hermes adds over an ordinary MCP client** (this is the reason to keep it, not a reason to depend on it):

| Capability | Use | Evidence |
|---|---|---|
| Message gateway (Telegram, Slack, Signal, etc.) | lab staff query results and receive task-completion notifications in a phone IM | evidence §3 |
| cron scheduled tasks | check newly sequenced data on a schedule, generate weekly reports | evidence §3 |
| Plugin hooks (`pre_tool_call` can block, `transform_llm_output`) | add one more gate on interpretation text inside Hermes conversations | evidence §3.4 |
| Existing plugin assets and usage habits | smooth transition for hermes-bacmap users | — |

- **Integration method**: MCP only (Hermes configures `mcp_servers` pointing at bacmap, stdio). The v1.4.8 user ruling removed the second plugin channel: `bacmap.adapters.hermes` and the `hermes_agent.plugins` entry-point were deleted (V4 measured ✓ Connected / 22 tools).
- **Gate mechanism** (single channel from v1.4.8): the MCP channel is enforced by the bacmap server (only read/compute tools + task submission are exposed, ADR-12). The Hermes hook defenses of the former plugin channel (`pre_tool_call`/`transform_llm_output`) were abolished together with the channel.
- **What it does not do**: Hermes is not used as the built-in executor (the plugin API carries no stability guarantee, evidence §3.1); users are not required to install Hermes.
- **Rationale**: the existing entry-point declarations do not take effect and plugins load through symlinks (evidence §2.2); MCP puts Hermes and other assistants on the same path, so only one copy of the code is maintained.

### ADR-16 Security Red Lines and Data Classification: Frozen
- **Data classification** (added in v1.2):

| Level | Content | May it be sent to a `cloud` endpoint |
|---|---|---|
| D0 | public knowledge: literature, public database entries, method descriptions, users' general questions | yes |
| D1 | de-identified aggregate statistics: e.g. the share of each local ST, the detection rate of a resistance gene in a given year | yes |
| D2 | single-strain typing results: a strain's species, serotype, ST, resistance genes (no personal information or precise location) | not by default, an administrator may enable |
| D3 | sequence and alignment data: reads, assemblies, allele profiles, SNP matrices | **never** |
| D4 | personally and epidemiologically identifiable information: patient names, phone numbers, case details, precise addresses | **never** |

- Enforcement: every tool declares `output_data_class` (ADR-04); before sending a request, `bacmap.agent.llm` checks the highest level of everything in the current context, and refuses to send and records an event if it exceeds the level the endpoint allows; the role manifest declares `max_data_class`, and a role routed to a `cloud` endpoint that needs higher-level data refuses to start
- The existing `strain_metadata` contains patient names, phone numbers, and similar fields (evidence §2.4); those fields are all D4, never enter requests sent to `cloud` endpoints, and never enter the characteristic tables of the local epidemiological baseline library
- Sequence and epidemiological data never leave the local network
- Agent-generated code runs only inside the sandbox, with no network access
- All external interfaces bind to localhost by default
- Database release and report export require a human signature; signature records are written into `approvals` and the GOM `events`


### ADR-17 Local Model Resource Arbitration: Frozen (added in v1.1)
- **Background**: Strata is a single-slot service and does not process requests concurrently; the model stays resident in memory at roughly 39–47 GB, which competes with memory-intensive steps such as SPAdes/shovill assembly on a 64 GB machine (measured locally: the Strata process held 44.6 GB resident and about 6 GB of system memory remained available, evidence §8).
- **Decision**:
  - `bacmap.agent.llm` maintains a single request queue; all LLM calls go out serially; each request carries a timeout, and on timeout it degrades to no-LLM behavior
  - the task layer checks available memory before starting a memory-intensive workflow step; if it is insufficient it calls Strata `POST /unload` to release the model, and after the step finishes `POST /load` reloads it (loading takes 1–3 minutes); LLM requests queue or degrade in the meantime
  - config option `llm.resources.co_located` (see the 4.5 example): whether the model and the pipeline share one machine. Arbitration is enabled by default when co-located, and disabled when the model runs on a separate host
- **Rationale**: without arbitration, assembly can fail for lack of memory, violating the "re-running the same sample gives identical results" requirement; treating the model as a preemptible resource guarantees C3 (deterministic functions take priority over the LLM).

### ADR-18 Run Records and Reproducibility: Frozen (added in v1.2)
- **Background**: repeated analyses of the same sample can produce different results because of differing parameters, database versions, tool versions, or randomness in the tools themselves. The current state is: `pipeline_version` is a hand-written label (such as `salmonella-workflow-v0.1`), tool and database versions are constants in `ingest_results.py` rather than values measured at runtime, workflow parameters are not recorded at all, `created_at` is the ingestion time rather than the analysis time, and iqtree does not pin a random seed (evidence §9).
- **Decision**:
  - the evidence chain expands from a triple to `(strain_id, run_id)`; each workflow execution generates one immutable **analysis run record** (the `analysis_runs` table + `run_manifest.json` inside the run directory, with identical content, the latter carrying a SHA256)
  - Run record fields (Section 4.6): analysis start and end times, ingestion time; pipeline version (the Git commit of the workflow directory, or a diff summary plus a `dirty` flag when uncommitted changes exist); **the complete parsed parameters** (the full merged text of config.yaml and all overrides, with its hash); reference database inventory (name, version, file checksums); tool versions (measured at runtime by calling each tool's `--version`, plus the hash of `pixi.lock`); input file SHA256s; random seeds; host and CPU/thread counts; triggerer and task ID
  - Tools involving randomness always pin a seed and write the seed into the parameters (e.g. iqtree `-seed`); steps that cannot be pinned are flagged `nondeterministic_steps` in the run record
  - LLM-generated interpretations are recorded separately: endpoint, model identifier, location, the Git versions of the role manifest and instructions (that is, `prompt_version`), sampling parameters
  - Old results are never overwritten: every run produces a new result version, and GOM objects point to `run_id`
  - a "run comparison" tool is provided: for two runs of the same sample it compares results field by field and attributes differences to differing parameters, databases, tool versions, or inputs; if the run record shows all of these identical while results differ, it is flagged as irreproducible and an alert is raised
- **Rationale**: the analysis time only says "when" and cannot explain "why different"; parameters and versions are the sources of differences. The evidence chain must be able to answer "what was this conclusion computed with, and how".
- **Verification**: V8.

### ADR-19 Local Epidemiological Baseline Library: Frozen (added in v1.2)
- **Definition**: the local epidemiological baseline library is not a reference database for analysis, but a **versioned collection of epidemiological characteristics of strains in the jurisdiction**, stored in the GOM, used for:
  - characteristic matching of new isolates against the local background: whether this ST/serotype/resistance profile is common locally, whether it appears for the first time, cgMLST nearest neighbors and cluster membership
  - mining of local epidemiological patterns: time trends, regional distribution, source (food category, clinical/environmental) associations, resistance changes
- **Composition**:
  - included strain list: each strain points to its analysis result version and `run_id`
  - characteristic tables: typing (species, serotype, ST, cgMLST type/cluster), resistance and virulence genes, plasmids; time (isolation date), region (down to district/county), source category; **no D4 personal information**
  - cgMLST local reference profiles: the existing `build_cgmlst_reference.py` and `cgmlst_projection.py` (nearest-neighbor projection and outbreak/related/unrelated determination) already belong to this library, and after moving in they are managed by baseline library version
  - aggregate statistics snapshots: distributions by pathogen, year, region, and source
- **Versioning and release**: a `curate` task produces a candidate version → baseline library release gate (ADR-07) → human signature → written into `baseline_releases`; released versions are immutable, and newly added strains produce new versions
- **Usage rule**: whenever a conclusion uses local characteristic matching (such as "first local occurrence" or "same cluster as a 2025 outbreak strain"), the evidence records the `baseline_version` used
- **Rationale**: the existing `strain_metadata` (region, isolation date, source, outbreak number), `strain_genotype_index`, `strain_amr_genes`, and the cgMLST local reference library already provide the data foundation for a baseline library (evidence §2.4, §9); what is missing is versioning, the release gate, and de-identification.

### ADR-20 Standard External Toolchain: Frozen (added in v1.3)
- **Decision**: typing and screening analyses use the following three standard external tools, all agent-first CLIs by the same author (uniform JSON output, self-reported version, documented exit codes):

| Responsibility | Tool | Form | Place in the workflow |
|---|---|---|---|
| Species identification | **gside** | Python CLI (git install, not yet on PyPI), MIT, **in development; the roadmap includes a GTDB-Tk identification tier** (confirmed in v1.4) | `species` rule: `gside species --mode marker\|panel\|mash_refseq\|sourmash\|all` |
| MLST / cgMLST / wgMLST typing + minimum spanning tree | **gmlst** | PyPI `gmlst>=0.1.4` (already in the environment) | `typing` rule: `gmlst typing mlst/cgmlst`; cohort MST via `gmlst visual`, replacing the hand-written MST script |
| Gene and gene cluster identification (AMR/virulence/plasmid/serotype targets/custom libraries) | **gapit** | PyPI `gapit>=0.5`, MIT | `screen` rule: `gapit screen` (contigs via BLAST, reads via minimap2), replacing abricate and the hand-written gene scan |

- **Division-of-responsibility principle** (added in v1.4.5, user ruling): **analyses that depend only on the genome (gene screening, species identification, typing, and their determinations) are always externalized to tools (gapit / gside / gmlst)**; **determinations that must be combined with data beyond the analysis results stay in bacmap**: the cgMLST nearest-neighbor projection onto the local baseline library and outbreak/relatedness determination (ADR-19), consensus merging of multi-method species results (species_consensus), and associating results with epidemiological metadata. bacmap consumes analysis results, then combines them with other data.
- **genome_annotator attribution pending** (flagged in v1.4.5): by the principle above, in-process pyrodigal annotation should also be externalized, but none of gapit/gside/gmlst currently has annotation capability. Until gapit provides an annotation subcommand, genome_annotator stays in bacmap for now and is invoked only as an L1 workflow step; once gapit gains that capability, it moves out through this ADR's revision process.
- **Tool output contract**: all three outputs include the tool name and version (gside JSON top-level `tool`/`version`; gapit versioned schemas such as `gapit.report/1`; gmlst follows the same family convention, subject to what V10 measures). At ingestion they are parsed into `AnalysisRun.tool_versions` and the result payload; ADR-18's "runtime measured versions" take the version embedded in the output JSON as authoritative, falling back to probing the CLI `--version` when it is missing.
- **Replacement relations** (relative to the existing hermes-bacmap implementation):

| Existing module | Destination |
|---|---|
| `analysis/species_identifier.py`, `taxonomic_validator.py`, `sourmash_identifier.py`, `ani_identifier.py`, `species_consensus.py`, the five-tier `bio_db_setup` | **Replaced by gside, effective immediately per the v1.4.7 user ruling**: without waiting for step 5, the modules above and the `bio_validate_taxonomy`/`bio_species_compare`/`bio_db_setup`/`bio_db_status` tools were deleted from bacmap (registry 29→24); the workflow species/taxonomy/vpara_targets rules emit `pending_gside` placeholders, to be replaced in step 5 once `gside species` is wired in. Direct blastn orchestration-style rules (abricate/amrfinder/vpara_virulence/kraken2_prefilter) are kept until step 5 swaps them uniformly |
| `analysis/gene_scanner.py` and its calls in AMR/virulence/plasmid screening | **Replaced by gapit** (dual channel for contigs and reads, abricate-compatible TSV + JSON) |
| ecoh / shigella / vpa serotype modules (both scanning **and determination**) | **Moved into gapit wholesale** (ruled in v1.4.5, finally confirmed in v1.4.7: no transitional restoration is kept; they were briefly restored in v1.4.6 as migration scaffolding, which the user explicitly overturned). The bacmap `core/typing` and `bacmap/typing` shims were both deleted; the workflow ecoh/shigella/vpa serotype rules emit `pending_gapit` placeholders (rule names and output contracts kept), to be replaced in step 5 once gapit's serotype subcommand is wired in |
| cgmlst cohort hand-written MST script | **Replaced by `gmlst visual`** |
| the `engine/` SequenceMatcher abstraction and blast/kma backends | shrinks once screening is handed to gapit; ReadMapper (bwa/bowtie2 SNP alignment) is kept |
| GTDB-Tk standard tier (101GB+140GB RAM) | **not integrated by bacmap directly; provided by gside's GTDB-Tk tier** (in development); until that tier is ready, the standard path is marker/panel/mash/sourmash (`all` arbitration), consistent with the single-workstation constraint. Once gside releases the GTDB-Tk tier, it joins the `all` arbitration automatically, and the bacmap adapter probes for mode availability; no architecture change needed |

- **Database version management**: the three tools' bundled databases (gside panel/mash sketch, gapit's card/vfdb/plasmidfinder and so on, gmlst's scheme) are registered at deployment into `AnalysisRun.ref_databases` (name, version, directory checksum); the tools' self-managed download directories are organized under ADR-03's `BACMAP_HOME` (e.g. `$BACMAP_HOME/refs/{gside,gapit,gmlst}/`) instead of being scattered across the repos' `data/`.
- **Dependency management**: pixi's pypi-dependencies add `gapit`, `gmlst`, `gside` (gside pinned via git+commit until it reaches PyPI); the external binaries blast/minimap2/skani/mash/sourmash/kma/mummer are already in the current pixi manifest.
- **Quality bar for standard tools** (added in v1.4; external tools entering the L1 standard path must meet it):
  1. **Frozen output contract**: a versioned schema (such as `gapit.report/1`) promises backward compatibility; breaking changes must bump the major version and be announced in advance, and the bacmap side triggers a V10 re-run
  2. **Gold-standard regression**: 100% agreement on bacmap's 12-strain gold standard (including close-relation negative controls), or a written attribution; the tool's own repo ships a regression harness kept green in CI
  3. **Determinism**: same input, same output, byte-identical; any randomness must be declared explicitly and support a pinned seed
  4. **Explicit failure**: errors are reported with a non-zero exit code or a typed error envelope, never silently swallowed, never downgraded output
  5. **Release discipline**: semantic versioning + CHANGELOG; changes to thresholds, hit rules, or database content must leave a trace traceable to a version
  6. **Self-describing versions and databases**: the output JSON embeds the tool version and the database versions used (ADR-18 depends on this)
- **Higher bar for gapit** (v1.4, spelled out at the user's request): gapit takes over all L1 gene screening and is the riskiest replacement in the standard chain (replacing gene_scanner + abricate, validated across seven versions), so it carries additional requirements:
  - the parity harness (abricate frozen baseline) stays a **run-on-every-release** release gate and is not relaxed by v0.5.0's "parity is no longer a release gate"; any release bacmap uses must ship with a green parity record
  - hit rules (identity/coverage thresholds, overlap handling, multi-hit resolution) are documented item by item in SPEC.md; any rule change must first be validated for impact on the bacmap gold standard
  - a benchmark report must exist for the detection differences between the reads channel (minimap2) and the contigs channel (BLAST) on the same assembly, for use in V10 attribution
  - every update of the bundled databases gets an independent version number, and old versions remain retrievable (supporting ADR-18's `ref_databases` checksum registration)
- **Relation to MCP** (clarified in v1.4): bacmap always calls the bioinformatics tools as CLI/in-process and does not detour through the tools' own MCP services; this is a performance and call-chain-simplicity consideration. The MCP capability of tools such as gapit is an independent usage channel aimed at **other agent clients** (the Strata chat page, Claude, Codex, etc.) and coexists with bacmap's CLI integration. Both channels land on the same tools and databases, and result consistency is guaranteed by the tools themselves. bacmap's own MCP server keeps exposing the `bio_*` semantic tools (which internally call these CLIs).
- **Trust layer**: all three are L1 deterministic tools; `gside species` always exits with code 0 and writes per-method errors into the JSON; the adapter must check each method entry's error field rather than only the exit code.
- **Verification**: V10.

---

## 4. Interface Contracts (Frozen)

The following are signatures and field definitions. Implementations may add optional fields but may not delete or change existing fields.

### 4.1 Tools

```python
class TrustLayer(StrEnum):
    L1 = "L1"   # 固定管线：只调用，不改写
    L2 = "L2"   # 受控探索：沙箱 + 人审
    L3 = "L3"   # 自由对话：受门约束

class Effect(StrEnum):
    READ = "read"        # 只读查询
    COMPUTE = "compute"  # 计算但不写持久状态
    WRITE = "write"      # 写 GOM / 数据库，只能经由任务

class ToolSpec(BaseModel):
    name: str                     # 全局唯一，如 "bio_gene_scan"
    version: str
    description: str
    input_model: type[BaseModel]  # JSON Schema 由此生成
    trust_layer: TrustLayer
    effect: Effect
    long_running: bool = False    # True 时经 MCP 返回作业句柄
    output_data_class: DataClass  # D0–D4（v1.2，ADR-16）
    handler: Callable[[BaseModel, ToolContext], ToolResult]

class DataClass(IntEnum):
    D0 = 0  # 公开知识
    D1 = 1  # 去标识聚合统计
    D2 = 2  # 单株分型结果
    D3 = 3  # 序列与比对数据
    D4 = 4  # 个人与流调可识别信息

class ToolResult(BaseModel):
    ok: bool
    data: dict[str, Any] = {}
    error: str | None = None
    evidence: list[EvidenceRef] = []   # 指向 GOM object_id@version / file sha256
```

### 4.2 Gates

```python
class GateVerdict(StrEnum):
    PASS = "pass"
    NEEDS_HUMAN_REVIEW = "needs_human_review"
    REJECT = "reject"

class GateResult(BaseModel):
    gate: str                     # "analysis_claims" | "baseline_release" | "mining" | "citation"
    verdict: GateVerdict
    details: dict[str, Any]
    evaluated_at: datetime

class Gate(Protocol):
    name: str
    def evaluate(self, subject: GateSubject) -> GateResult: ...
```

Every gate evaluation writes a GOM `events` record (`event_type = "gate.<name>"`).

### 4.3 Tasks

```python
class TaskType(StrEnum):
    ANALYZE = "analyze"
    CURATE = "curate"     # 本地流行特征库构建（v1.2，原 build_db）
    MINE = "mine"
    WRITE = "write"

class TaskState(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"

class TaskEngine(Protocol):
    def submit(self, task_type: TaskType, params: BaseModel, submitted_by: str) -> TaskId: ...
    def status(self, task_id: TaskId) -> TaskStatus: ...
    def cancel(self, task_id: TaskId) -> None: ...
    def approve(self, task_id: TaskId, approval: Approval) -> None: ...
```

Minimum `tasks` table fields: `task_id, task_type, state, params_json, submitted_by, created_at, updated_at, workspace_path, result_object_ids`.

### 4.4 Role Manifest

```yaml
# roles/miner.role.yaml
name: miner                       # 与 skills/miner/SKILL.md 对应
task_types: [mine]
min_model_tier: T2
allowed_locations: [local, lan]   # 可路由的端点位置（v1.2）
max_data_class: D3                # 本角色上下文可出现的最高数据级别（v1.2）
trust_layer: L2
tools:                            # 白名单，按 ToolSpec.name
  - bio_search_samples
  - bio_query_metadata
  - bio_cgmlst
  - sandbox_run                   # 沙箱执行
fs_scope:
  read: ["${GOM_EXPORT}"]
  write: ["${TASK_WORKSPACE}"]
network: false
```

The corresponding `SKILL.md` contains only instructions; its frontmatter follows agentskills.io: `name` and `description` are required, the version goes in `metadata.version`.

### 4.5 Model Configuration

```toml
[llm.endpoints.strata]
kind = "openai_compatible"
location = "local"
base_url = "http://127.0.0.1:8080/v1"
model = "qwen3.8-flash-next-iq3_xxs"   # 共用机器时换 iq2_xs
tier = "T2"
max_concurrency = 1                     # Strata 单槽位（ADR-17）
supports_tools_with_schema = false      # 不能在同一请求中混用 tools 与 response_format
constrained_decoding = false
request_timeout_s = 300
admin_url = "http://127.0.0.1:8080"     # /load、/unload

[llm.endpoints.glm_api]
kind = "openai_compatible"
location = "cloud"
base_url = "https://open.bigmodel.cn/api/paas/v4"
model = "glm-5.x"
api_key_env = "GLM_API_KEY"             # 密钥只从环境变量读取
tier = "T2"
max_concurrency = 4
enabled = false

[llm.routing]                           # 角色/用途 → 端点
intent_classifier = "strata"
interpretation = "strata"
open_path = "strata"
writer = "strata"                       # 可改为 glm_api：仅能接收 D0–D1（或管理员允许的 D2）

[llm.data_policy]
cloud_max_data_class = "D1"             # 管理员最多可放宽到 D2；D3/D4 不可配置

[llm.resources]
co_located = true                       # 模型与管线同机时启用仲裁（ADR-17）
min_free_ram_gb_for_heavy_steps = 24
```

### 4.6 Analysis Run Record (v1.2, ADR-18)

```python
class RefDatabase(BaseModel):
    name: str                 # "card", "vfdb", "cgmlst:senterica_2", ...
    version: str
    checksum: str             # 数据库文件/目录的 SHA256

class AnalysisRun(BaseModel):
    run_id: str
    task_id: str
    strain_ids: list[str]
    workflow: str                         # "bacmap"、"snp"、"cgmlst" 等
    workflow_commit: str                  # 工作流目录 Git commit
    workflow_dirty: bool
    started_at: datetime                  # 分析开始
    finished_at: datetime | None          # 分析结束
    ingested_at: datetime | None          # 入库
    resolved_config: dict[str, Any]       # 合并全部覆盖项后的完整参数
    config_sha256: str
    ref_databases: list[RefDatabase]
    tool_versions: dict[str, str]         # 运行时实测（tool --version）
    env_lock_sha256: str                  # pixi.lock 哈希
    input_files: dict[str, str]           # 路径 → SHA256
    seeds: dict[str, int]                 # 步骤 → 随机种子
    nondeterministic_steps: list[str]
    host: dict[str, Any]                  # 主机名、CPU、线程数
    baseline_version: str | None          # 用到本地流行特征库比对时填写
    manifest_sha256: str                  # run_manifest.json 的哈希
```

LLM interpretations are additionally recorded in `LlmProvenance`: `endpoint`, `location`, `model`, `prompt_version` (the Git versions of the role manifest and instructions), `sampling`, `data_class_max`.

### 4.7 Helper Types (minimal definitions, added in v1.4.3; referenced in §4.1–4.3 but previously undefined)

```python
TaskId = NewType("TaskId", str)

class EvidenceRef(BaseModel):
    kind: Literal["gom_object", "file"]
    object_id: str | None        # kind=gom_object：GOM 对象 ID
    version: int | None          # kind=gom_object：对象版本
    path: str | None             # kind=file：文件路径
    sha256: str | None           # kind=file：内容哈希

class ToolContext(BaseModel):
    task_id: TaskId
    role: str                    # 调用方角色（role.yaml 的 name）
    run_id: str | None           # L1 工具执行时所属的运行记录
    workspace: Path              # 任务工作区

class GateSubject(BaseModel):
    gate: str                    # 与 GateResult.gate 同域
    payload: dict[str, Any]      # 各门自定义，如 interpretation_text /
                                 # candidate_release / mining_artifact / draft

class TaskStatus(BaseModel):     # TaskEngine.status 的返回类型
    task_id: TaskId
    state: TaskState
    current_step: str | None
    message: str | None

class Approval(BaseModel):
    approver: str                # 签名人（本地账号）
    decision: Literal["approve", "reject"]
    signature: str               # 签名凭据形式，实现期细化（至少含时间戳与对象哈希）
    comment: str | None
    at: datetime
```

---

## 5. Key Flows

**Deterministic analysis (analyze)**: submit → validate samples → draft the run record (parameters, seeds, measured database and tool versions, input checksums) → `WorkflowRunner` runs Snakemake → fill in the end time and seal the run record → ingest into the GOM (results point to `run_id`) → deterministic verifier → (optional) compare against the current local epidemiological baseline library (recording `baseline_version`) → (optional) LLM generates an interpretation → analysis-conclusion gate → report generation → done. On a mid-run crash, DBOS recovers from the last completed step, and Snakemake resumes via `.snakemake/`.

**Local epidemiological baseline library construction (curate)**: submit (specifying the inclusion scope, such as a pathogen or a time range) → select candidate strains from the GOM → check inclusion criteria strain by strain (deterministic verification passed, QC acceptable, metadata complete, deduplicated) → strip D4 personal information, generate the characteristic tables, cgMLST local reference profiles, and aggregate statistics → (optional, T2) the LLM offers metadata cleaning suggestions and characteristic summaries → baseline library release gate → `AWAITING_APPROVAL` → human signature → a new version is written into `baseline_releases`.

**Open mining (mine) / writing (write)**: submit → start the pydantic-ai agent per the role manifest (permissions limited by the allowlist) → scripts run inside the Apptainer sandbox → outputs are written to the task workspace → mining-conclusion gate / citation gate → user signature → eligible to enter a report.

---

## 6. Package Structure

```
bacmap/
├── pixi.toml                    # 唯一环境定义（Python + 生信工具）
├── pyproject.toml               # 包名 bacmap；import-linter 规则
├── src/bacmap/
│   ├── config.py                # BACMAP_HOME + config.toml（ADR-03）
│   ├── core/                    # 领域层：engine / analysis / pathogen_registry（typing 已外移 gapit，v1.4.5）
│   │   └── verify/              # deterministic_verifier、nli_reflector
│   ├── store/                   # GOM、strain_index、metadata、lab_results、migrations/、knowledge/
│   │   ├── runs/                # 运行记录 analysis_runs（ADR-18）
│   │   └── baseline/            # 本地流行特征库 baseline_releases（ADR-19）
│   ├── tools/                   # ToolSpec 注册表；工具集合随版本演进（迁移起点为现有 29 个，ADR-20 替换后有增减）（ADR-04）
│   ├── workflow/                # WorkflowRunner + Snakemake 9 工作流文件
│   ├── tasks/                   # TaskEngine、任务类型、门、审批（ADR-06/07）
│   │   └── engine/              # 唯一导入 DBOS 的位置
│   ├── agent/                   # 智能体层
│   │   ├── llm/                 # 唯一导入 pydantic-ai 的位置（ADR-08）
│   │   ├── principles.md        # 全局原则（相当于 Hermes 的 SOUL.md）
│   │   ├── roles/               # *.role.yaml
│   │   ├── skills/              # agentskills.io 规范的 SKILL.md
│   │   ├── intent.py            # 意图 → 任务类型
│   │   └── sandbox/             # Apptainer / Podman 后端（ADR-11）
│   ├── interfaces/
│   │   ├── web/                 # FastAPI + Jinja2 + htmx
│   │   ├── cli/
│   │   └── mcp/                 # MCPServer（ADR-12）
├── sandbox/                     # SIF 镜像定义文件
└── tests/
```

---

## 7. Frozen Boundaries at a Glance

| Frozen (changes require the revision process) | Replaceable (implementation swappable while the interface stays unchanged) |
|---|---|
| Python 3.12 + pixi | Web front-end technology details |
| Package structure and dependency direction | Durable execution library (DBOS → hand-written) |
| `ToolSpec` / `ToolResult` / `Gate` / `TaskEngine` interfaces | LLM library (pydantic-ai → others) |
| Closed task type set | Sandbox technology (Apptainer → Podman etc.) |
| The four gates and "writes go only through tasks" | Knowledge base implementation (FTS5 → sqlite-vec / GBrain) |
| Model tier and deployment location rules | Specific models, inference services, and API vendors (currently Strata by default) |
| GOM table structure and the evidence chain `(strain_id, run_id)` | Hermes adapter and other external clients |
| Run record fields (`AnalysisRun`) | How the run comparison tool presents results |
| Composition, versioning, and release rules of the local epidemiological baseline library | The specific characteristic statistics metrics |
| Division of labor among the three role files (permissions decided only by the role manifest) | The specific content of instructions and global principles |
| MCP spec version and exposure scope (outbound only) | |
| Local model resource arbitration and the serial queue | |
| Data classification D0–D4 and security red lines | |
| Responsibility split of the standard toolchain gside / gmlst / gapit (ADR-20) | The tools' own versions (follow upstream releases) |

---

## 8. Pre-Work Verification Items (1–3 days each)

These are assumptions the frozen design depends on that have not yet been measured on this machine. If any item fails, revise the corresponding ADR per its "on failure" column; **bypassing is not allowed**.

| # | What is verified | Pass criteria | On failure |
|---|---|---|---|
| V1 | Snakemake 9.x runs the existing workflows in the pixi environment (scope revised in v1.4.7) | 12-strain gold standard re-run end to end; comparison scope = QC/assembly/MLST/SISTR/AMR/pathotype/vpa_virulence/annotation/report; species (→gside) and serotype (→gapit) fields matching on both sides are excluded and counted as SKIP; all other fields match 7.32 field by field | locate the incompatible rules and fix them; no rollback to 7.x |
| V2 | DBOS (SQLite system database) runs an `analyze` task | kill the process mid-run; after restart it continues from the checkpoint; still recoverable after waiting over 24 hours for approval | switch to `transitions` + SQLite (the ADR-06 fallback) |
| V3 | Measured capability of Strata + Qwen3.8-Flash-Next (both IQ3_XXS and IQ2_XS tested) | intent decomposition accuracy ≥95% (a self-built 100-item Chinese test set, including cross-task utterances); single-step tool-call parameter accuracy ≥95% for all registry tools (29 at migration start); complete 3 sample mining tasks; confirm the model and quantization licenses are usable for this project | if IQ2_XS falls short, co-located deployment uses IQ3_XXS + arbitration only; if overall results fall short, adjust the roles' `min_model_tier` |
| V4 | `mcp` 2.x MCPServer connects to Hermes and at least one other client (such as Claude/Codex/the Strata chat page) | both clients call tools and read instructions over MCP, and long-task handles are pollable; writes go only through task submission | revise ADR-12's transport |
| V5 | Apptainer runs on the target Xinchuang systems | Kylin V10 (one x86 and one ARM machine) runs Python/R scripts normally with `--containall --network none` | switch to rootless Podman |
| V6 | pydantic-ai works against Strata | structured output (prompt + validation) failure rate after retries <1%; multi-step tool calling completes in Tool Output mode; `jsonschema` installed in the Strata environment | evaluate switching LLM libraries or hand-writing a thin layer (ADR-08 interface unchanged) |
| V7 | Model and pipeline on the same machine (added in v1.1) | on a 64 GB machine with Strata loaded, run shovill assembly: with arbitration enabled the assembly succeeds and results match those with the model unloaded; record the unload/load round-trip time | co-located deployment switches to IQ2_XS, or the model gets a dedicated host |
| V8 | Reproducibility (added in v1.2) | the same sample with an identical run configuration (parameters, databases, tools, and seeds all the same) run 3 times in a row gives field-by-field identical results; after changing a single parameter, the run comparison tool attributes the difference to that parameter | locate the randomness source and pin a seed; steps that cannot be pinned are registered as `nondeterministic_steps` |
| V9 | LLM API and data classification (added in v1.2) | with a `cloud` endpoint configured: D0–D1 requests go through normally; requests containing D2 or above are intercepted and an event is recorded; roles routed to that endpoint whose `max_data_class` is exceeded refuse to start | fix the classification check; disable the `cloud` endpoint until it passes |
| V10 | Standard toolchain integration (added in v1.3, expanded in v1.4) | gside (marker and panel modes), gmlst (typing + visual MST), and gapit (screen contigs and reads) are usable in the pixi environment; all three's JSON/TSV outputs parse fully into the store (embedded version numbers included), and `ref_databases` registers each one's database versions and checksums; re-verify against hermes-bacmap's 12-strain gold standard: gside determinations and gapit gene detections match the original species_identifier/gene_scanner results or have a clear attribution; gapit quality bar check: the release in use ships a green parity record, repeated runs on the same input are byte-identical, and the reads-versus-contigs channel difference has a benchmark report | attribute the difference: differing thresholds or rule versions mean aligning the parameters; a tool defect means rolling back to the corresponding original implementation and recording it in ADR-20 |
| V11 | Gate enforcement (added in v1.4.1; changed to phased in v1.4.2, aligned with migration steps) | **Step 6 (gate framework lands)**: (1) a constructed contradictory interpretation text (fixed sample, need not come from an LLM) is intercepted and flagged `NEEDS_HUMAN_REVIEW` by the analysis-conclusion gate at all three points: display, export, and storage; (2) CLI and internal API direct writes to the GOM/released databases are refused. **Step 7**: (3) a baseline library candidate version below the gold-standard threshold is refused by the release gate and the previous version is unchanged. **Step 8**: (4) MCP write-type direct writes are refused. **Step 10**: (5) unsigned mining outputs cannot enter a report; (6) a manuscript containing citations absent from the knowledge base is refused export by the citation gate. **After step 9**: regression of (1) with genuinely LLM-generated interpretations | any sub-item not intercepted is an architecture-level defect and frozen C5 fails; it must be fixed before moving to the next step |

---

## 9. Migration Order from hermes-bacmap

1. **Skeleton**: create the Section 6 package structure, `config.py`, and import-linter rules
2. **Domain and storage**: port `engine`, `analysis`, `typing`, and `services` over, fixing path derivation; get the existing unit tests running
3. **Tool registry**: `ToolSpec` + adapter-wrapping the existing 29 handlers; generate the Hermes plugin from the registry and fix the entry-point
4. **Workflows and run records**: complete V1, upgrade to Snakemake 9, wire in `WorkflowRunner`; implement the run record (measured tool versions, parameter snapshots, pinned seeds for iqtree and the like), complete V8
5. **Standard toolchain**: integrate gside / gmlst / gapit (ADR-20), complete V10; replace the species identification, gene screening, and cohort MST rules; serotype determination switches to gapit wholesale (this depends on the gapit repo finishing the porting and verification of the three serotype modules; `core/typing` is already deleted and the adapter is implemented in this step)
6. **Tasks and gates**: complete V2 and V11 sub-items (1)(2); implement the `analyze` task, the gate framework, and the analysis-conclusion gate (this reaches C3: the full pipeline works without an LLM)
7. **Local epidemiological baseline library**: move in the cgMLST local reference library and strain metadata; implement the `curate` task, de-identification, and the baseline library release gate (V11 sub-item (3))
8. **Interfaces**: MCP server (V4, V11 sub-item (4)), web task pages
9. **Agent**: complete V3, V6, V7, and V9; wire in Strata and LLM APIs, the request queue, resource arbitration, and data classification; implement intent classification and interpretation; regress V11 sub-item (1) with real LLM interpretations
10. **Open path**: complete V5; implement `mine`, `write`, and their gates (V11 sub-items (5)(6))

(Revised in v1.4.8: the plugin channel was removed. Throughout the migration, `bacmap mcp --read-only` served as the continuously available external channel.)

---

## 10. Revision Records

| Version | Date | Change | Basis |
|---|---|---|---|
| v1 | 2026-10-09 | Initial frozen version | Two debate rounds + research evidence |
| v1.1 | 2026-10-09 | Added Section 0 project positioning; ADR-05 pinned Snakemake 9.27.*; ADR-08 calling rules revised to match Strata's actual capabilities; ADR-09 local default model changed to Strata + Qwen3.8-Flash-Next, dropping Qwen3-14B; ADR-10 decomposition results now require user confirmation, sub-agents run serially; ADR-12 clarified that MCP is for the outside only; ADR-15 rewrote Hermes's positioning; added ADR-17 resource arbitration; V3/V4/V6 revised and V7 added | User decisions + Strata source code and local measurement (evidence §8) |
| v1.2 | 2026-10-09 | Section 0 expanded with multi-role, agent implementation, bioinformatics analysis paths, and the baseline library definition; C2 and C4 revised; ADR-04 added `output_data_class`; ADR-06 task type `build_db` renamed `curate`; ADR-07 database-release gate changed to baseline library release gate; ADR-08 clarified support for both local model services and LLM APIs as endpoint classes; ADR-09 separated capability tier from deployment location and abolished T3; ADR-10 clarified it is not autonomous multi-agent conversation and defined the three-file role split; ADR-11 clarified the L1/L2 relationship and the promotion path; ADR-13 distinguished reference database versions from local baseline library versions; ADR-16 added data classification D0–D4; added ADR-18 run records and ADR-19 local epidemiological baseline library; added interface 4.6; added V8 and V9 | User additions + audit of hermes-bacmap's run record state (evidence §9) |
| v1.3 | 2026-10-09 | Added ADR-20 standard external toolchain (gside species identification / gmlst typing and MST / gapit gene and gene cluster identification) and the replacement table; identification tiers changed to gside's data-layered modes, GTDB-Tk exits the standard path; tool databases brought under `ref_databases` registration and `BACMAP_HOME` planning; added V10; inserted the "standard toolchain" step into the migration order | User statement + verification of the three tools' source code and repos (evidence §10) |
| v1.4 | 2026-10-09 | ADR-20: gside marked as in development with a roadmap including a GTDB-Tk tier (GTDB-Tk now provided by gside, not integrated by bacmap directly); added the standard tool quality bar and higher requirements for gapit (parity run on every release, rules documented, dual-channel difference benchmark, database versions retrievable); clarified that the tools' own MCP capability and bacmap's CLI integration coexist; V10 expanded with quality checks | Item-by-item user rulings on five v1.3 decisions |
| v1.4.1 | 2026-10-09 | Full-text review corrections: fixed ADR-13's self-contradictory GBrain rationale (changed to "independent process over MCP, not entering the bacmap runtime"); the 4.2 gate enum `db_release` renamed `baseline_release` (leftover from the v1.2 rename); ADR-17 config name unified as `llm.resources.co_located`; ADR-10's v1.1 note annotated `build_db` as the old name of `curate`; §6 and V3's "29 tools" changed to "all registry tools (29 at migration start)"; ADR-02 added the rule on where MCP client modules may live; ADR-09 declared tier monotonicity; ADR-15 clarified the two channels have different gate mechanisms; ADR-07's baseline library release gate check changed to the deterministic verifier; C3's basis changed to ADR-02/06/09; added V11 gate-enforcement verification tied to migration step 6 | Full-text re-review |
| v1.4.2 | 2026-10-09 | Second full-text re-review corrections: fixed the contradiction between ADR-06's "two tables" and ADR-13's "four tables" (unified as four); §5's curate flow "analysis-conclusion gate already passed" changed to deterministic verification in step (missed in v1.4.1); **V11 sequencing contradiction**: the original text required testing LLM interpretation and MCP interception at step 6, but the agent only exists from step 9 and MCP from step 8; changed to phased sub-items (1)–(6) aligned with the migration steps; ADR-20's gmlst version-embedding claim downgraded to "subject to what V10 measures"; V1 and V10 gold-standard strain counts unified at 12; V8's "same run record" changed to "same run configuration"; ADR ordering fixed (ADR-16 had been misordered after ADR-20; moved back between ADR-15 and ADR-17) | Second full-text re-review |
| v1.4.3 | 2026-10-09 | Third full-text re-review: **fixed the policy-level contradiction between C2 and ADR-16**: C2 originally read "strain-level details (D2) never leave the local network" as an absolute constraint, conflicting with ADR-16's "an administrator may allow D2"; C2 changed to "D3/D4 never; D2 not sent by default but may be allowed" (**this policy choice awaited user approval**, see ADR-16); §0 positioning table and ADR-10's outdated "same model/local model" wording updated (once API endpoints are supported, roles may be heterogeneous); §2 added the "two kinds of report" note (the analyze templated report = deterministic path, write custom writing = open path); added §4.7 minimal helper type definitions (TaskId, EvidenceRef, ToolContext, GateSubject, TaskStatus, Approval; previously referenced by §4.1–4.3 but undefined, with TaskStatus/TaskState naming inconsistent) | Third full-text re-review |
| v1.4.4 | 2026-10-09 | The D2 data policy was approved by the user: D3/D4 never leave the local network; D2 is not sent to public endpoints by default and an administrator may allow up to D2 (C2 and ADR-16 now consistent and in force); later adjustments follow this document's change rule through ADR revision | User approval |
| v1.4.5 | 2026-10-09 | ADR-20 revised (user ruling): **the serotype determination layer also belongs to gapit**, overturning v1.3's "determination logic stays" clause; added the division-of-responsibility principle, that analyses depending only on the genome are always externalized while determinations needing data beyond analysis results stay in bacmap (cgMLST local projection and consensus merging kept); genome_annotator attribution flagged as pending (stays for now, until gapit gains annotation capability); bacmap `core/typing` deleted (8 modules + 4 test files); test baseline 839 passed / 2 skipped, with ruff and the import-linter contracts all green | User ruling + implementation verification |
| v1.4.7 | 2026-10-09 | **Two user rulings effective immediately**: (1) the three serotype modules are abandoned outright (overturning v1.4.6's migration-scaffolding-style temporary restoration), with gapit taking over and the rules changed to `pending_gapit` placeholders; (2) **species identification analysis capability moves to gside entirely**: the five modules species_identifier/taxonomic_validator/sourmash_identifier/ani_identifier/species_consensus and the four species tools (validate_taxonomy/species_compare/db_setup/db_status) were deleted immediately (registry at 24 tools), and the species/taxonomy/vpara_targets rules changed to `pending_gside` placeholders; test baseline 1004 passed / 1 skipped, ruff and contracts all green; V1's comparison scope revised accordingly (species/serotype fields SKIP); deploy() fixed (redeployment keeps .snakemake resume state) | Two user rulings + implementation verification |
| v1.4.8 | 2026-10-10 | **User ruling: the plugin channel is removed, MCP only**: the `bacmap.adapters` package, the `hermes_agent.plugins` entry-point, and the adapters entry in the importlinter forbidden layers were deleted; on the Hermes side, the `~/.hermes/plugins/hermes_bacmap` directory and the plugins.enabled entry were removed (the plugin had been failing to load since 09-18 due to a syntax error); ADR-15's integration method revised to MCP as the sole channel, and the plugin hook defense clause abolished. Preceding fact: V4 had already measured the MCP path (✓ Connected 2038ms / all 22 tools discovered, including the sole write entry point bacmap_submit_task) | User ruling + implementation verification |
| v1.4.9 | 2026-10-15 | **ADR-20 implementation: `vpara_virulence` moved to gapit** — the inline blastn screen was removed and replaced by a gapit custom database `vpara_virulence` (tdh/trh/tlh); the database is built at deploy time by `workflow/scripts/build_gapit_db.py` under `$BACMAP_HOME/refs/gapit/` and registered in `refs/manifest.json` (traceable via ADR-18 `ref_databases`); the rule output is normalized to the existing `virulence.json` contract with added tool/database/hits provenance. After this, the only remaining direct-blastn orchestration rules in ADR-20's replacement table are amrfinderplus (an NCBI-specific tool) and kraken2_prefilter (reads-level prefilter), neither of which falls under gapit's three databases. Test baseline 1101 passed / 1 skipped | Implementation verification (real gapit DB build + end-to-end Snakemake rule smoke) |
| v1.4.10 | 2026-10-15 | **Remove specialized placeholder rules now covered by gside**: deleted `species_ani`/`species_sourmash` (alternate species-ID modes — gside's `all` mode already arbitrates across methods and picks up the GTDB-Tk tier), `taxonomy.smk` (`taxonomy_validation`, a gside GTDB-Tk capability), and `vpara_targets` (V. parahaemolyticus species target, a gside species concern); the Snakefile drops the `_ALT_*`/`_STANDARD_ACTIVE` mode gating (`.smk` 11→10). Species and taxonomy identification converge on the single `species_identify` rule (`gside species`, tier selected by `species_mode`). Test baseline 1101 passed / 1 skipped | User ruling + implementation verification |
| v1.4.11 | 2026-10-17 | **GOM analysis-ingest layer implemented (ingest-contract fix)**: previously the production analyze only wrote SAMPLE objects to the GOM (payload `{summary,run_id}`), while six consumers (`snp_tree`/`cgmlst_traceback`/`search_samples`/`review_flags`/`nli_reflector`/`strain_index.rebuild_from_gom`) filtered for ANALYSIS and read `BACMAP_DB_PATH` (`data/bacmap.sqlite`), a different file from the written `gom.sqlite` — so "human-review loop, cohort tree, cgMLST trace-back, strain search" **silently no-oped** in production (both files were never created on this machine, which is why it went unnoticed). This revision unifies three things: (1) **DB path** — GOM objects/events always land in `BACMAP_GOM_DB` (`$BACMAP_HOME/gom.sqlite`), and the GOM read tools (including `nli_reflector` and the report self-check) use it too; `BACMAP_DB_PATH` carries only strain-metadata/lab-result/genotype-index tables; (2) **object type** — analyze now writes ANALYSIS objects: per-sample `sample_analysis` (flat genotype view `species_verdict/serotype/mlst/amr/dec/plasmid` + full `summary` + `run_id`), per-sample `cgmlst_profile`, and cohorts `cohort:<group>-snp` / `cohort:<group>-cgmlst`, and populates `strain_genotype_index`; (3) **evidence chain** — `AnalysisRun.workflow_commit`/`workflow_dirty` are now captured from the workflow directory's Git (previously constant empty, ADR-18), and the ANALYSIS validation is relaxed to `pipeline_version` + (`database_versions` **or** `tool_versions`), consistent with C4's "measured versions of reference databases and tools". Test baseline 1199 passed / 1 skipped, ruff/mypy/contracts all green | User ruling (full scope) + implementation verification (end-to-end analyze→ingest→tool read-back) |
| v1.4.12 | 2026-10-17 | **External-data access capability (A+B+D, ADR-11 completion)**: previously the assistant could not use a user-provided data path — no tool accepted a path, `fs_scope` was declared but not enforced, and the sandbox mounted only the task workspace (and the `context.json`-advertised results/GOM paths were not actually mounted). This revision completes it: (1) **dataset registration (A)** — `store/datasets.py` adds a `datasets` table in the GOM DB, registering a user path **zero-copy** (per-file SHA256 + manifest-hash dedup, source descriptor dev/inode/mtime, data class); the `mine` task gains an `input_paths` parameter that registers before the sandbox and **read-only bind-mounts** the data at `/input/<dataset_id>` (ADR-11 "data mounted read-only"; no copy, no replica); (2) **read tool (B)** — new `bio_inspect_dataset` (read/L1, registry at 25 entries: 8 read / 14 compute / 3 write) to list/inspect registered datasets and their mount points; (3) **sandbox access surface and boundary (D)** — `SandboxSpec` gains an `allowed_readonly_roots` allow-list; a read-only mount outside it is rejected (fs_scope enforced in code); `context.json` matches the real backend (container uses `/data/*`, `/input/<id>` guest paths; passthrough uses host paths), fixing the unmounted results/GOM defect. Hashing uses SHA256 (consistent with file_artifacts/ADR-18); on-demand materialization (a copy) is an opt-in, off by default. Test baseline 1216 passed / 1 skipped, ruff/mypy/contracts all green | User ruling (A+B+D) + implementation verification |
| v1.4.13 | 2026-10-17 | **Restricted general shell (option C, narrowed form) + ten rounds of Web/TUI inspection**: (1) **`sandbox_shell`** (a session-internal tool, not in the registry/MCP) runs a single shell command inside the same sandbox — read/analysis allow-listed commands (ls/cat/grep/zcat/samtools/seqkit/python, …) pass through, anything else is refused and steered to a signed `mine` task, and a deny-list (podman/docker/nsenter/mount/curl, …) hard-rejects; it runs **only on a real container backend** (passthrough is refused by default; `BACMAP_SANDBOX_ALLOW_SHELL_PASSTHROUGH=1` is dev-only) and every invocation is audited to `$BACMAP_HOME/audits/sandbox_shell.jsonl`. (2) **Web inspection**: a security-headers middleware (strict CSP + nosniff + frame-deny + referrer-policy + COOP, also covering auth 401s); the inline polling script moved to `/static/js/task_poll.js` and inline styles to utility classes to satisfy the strict CSP; the HTML report is now an **attachment download** (removing the same-origin inline-render XSS surface); the assistant sessions have an **LRU cap of 32** against unbounded growth; the assistant input is bounded (empty → 400, over-long → 413). (3) **TUI inspection**: fixed **repeated Ctrl+Y resubmitting the same plan** (confirmation now clears the pending plan), `_start_chat` misused as a thread worker, calling `refresh_tasks` directly from a thread worker (now `call_from_thread`), leftover leader keys falling back into the input box, and a new session not cancelling in-flight requests; the prompt is length-bounded. Test baseline 1235 passed / 1 skipped; ruff/mypy/contracts/docs-build all green | User ruling (implement C + ten-round Web/TUI inspection) + implementation verification |
| v1.4.14 | 2026-10-18 | **Module-by-module audit (config/utils/analysis/engine/agent/tasks/cli/mcp) and tightened behavior**: (1) **config** — `DATA_DIR` now resolves as env > `config.toml[paths].data_dir` (expanded and resolved) > `$BACMAP_HOME/data` (previously the toml silently overrode the env and was not normalized); the `CHECKM2_DB` environment-variable name matches the docs (the code read `CHECKM2DB`; the old name is kept as an alias). (2) **tasks/gates** — the four gates are now **fail-closed (REJECT)** on malformed input instead of raising inside the gate (preserving C5's force); `DbosTaskEngine.cancel()` only cancels non-terminal tasks (it used to rewrite a succeeded/failed task to CANCELLED); **`analyze` submission requires samples** (it used to become a silently FAILED task), with Web/MCP/CLI returning a clear error. (3) **CLI** — untrusted sample values are escaped via `rich.markup.escape` (no more Rich-markup restyling); `bacmap --help` explicitly separates "interfaces/modes (mcp/web/tui/console)" from "commands (overview/task/sample/search/ask/chat)", keeping commands at the **top level** rather than adding a `cli` subcommand (`bacmap` itself is the CLI; zero BC break). (4) **engine** — `get_backend` normalizes case (`BLASTP` used to degrade to `blastn`). (5) **agent** — `RoleDef` enum fields are validated (a bad manifest fails at load) plus an all-roles tool-inventory consistency test. (6) **mcp** — `submit_task` returns an error envelope on engine validation errors. Test baseline 1260 passed / 1 skipped; ruff/mypy/contracts/docs-build all green | Module-by-module code-quality audit (user-directed) + implementation verification |
| v1.4.15 | 2026-10-18 | **Web browser authentication: token → cookie + CSRF (ADR-14 completion)**: the default `BACMAP_WEB_AUTH=bearer` stays **backward compatible** (header only, for API clients); a new `cookie` mode logs in at `/login` with the deployment token (constant-time compare + Origin check) and issues a stateless `sid.exp.HMAC-SHA256` session cookie (`HttpOnly; SameSite=Strict; Path=/`; a fresh sid on login **prevents session fixation**; `BACMAP_WEB_COOKIE_SECURE=1` adds `Secure`), plus a non-HttpOnly `bacmap_csrf` cookie; **state-changing POSTs carry three CSRF defenses**: SameSite=Strict + Origin/Referer same-origin check + a `csrf` form field matching the cookie (**double-submit**); unauthenticated HTML requests 303 to `/login`, XHR gets 401; `/logout` clears cookies; `next` is restricted to local paths (no open redirect). The signing secret is `BACMAP_WEB_SECRET` (derived from the token by default). Test baseline 1275 passed / 1 skipped; ruff/mypy/contracts/docs-build all green | User ruling (implement web token→cookie+CSRF after design) + implementation verification |
| v1.4.16 | 2026-10-18 | **Pathogen registry rebuilt (code-primary) + 3-letter species codes**: `pathogens.yaml` — previously only 4 enteric pathogens with name keys and marker genes — is rebuilt to cover **all 40 species labels in gside's `D1_marker`**, keyed by **3-letter species code** (new `core/species_codes.py`: rule "genus initial + 2 species letters", overrides SAL/SHI/ECO/EFM/CDP; VCH intentionally merges cholerae/O1/O139; `UNK` sentinel; collision detection). **Marker genes are removed** (identification belongs to gside, ADR-20); new fields `gside_labels`/`gapit_screens`/`serotype_engine`/`plan{snp,cgmlst,recombination}`. **SNP/cgMLST grouping becomes generic**: group members are **derived** from the declared `snp_group`, no longer listed by hand. Consumers (`snp.smk`/`cgmlst.smk`/`typing_amr.smk`) resolve keys via `resolve_species()` with **dual-accept** (code / gside label / display name); `samples.tsv.species` accepts either form. Reference genomes will be provisioned from NCBI in Stage C (accession manifest / agent skill); below-species determination (DEC pathotype etc.) goes through **gapit** databases (`ecoli_dec`/`ecoh`/`lm_doumith`/`kpsc`/`ab_k`, …); recombination detection uses **Gubbins** (external tool, Stage C). Test baseline 1287 passed; ruff/mypy/contracts/docs-build all green | User ruling (registry rebuild + code-primary + dual-accept) + implementation verification |
