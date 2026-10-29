*Reference translation. The Chinese version is authoritative; in case of divergence, the Chinese text governs.*

# BacMAP Standalone Framework Design (Frozen v1.9.3)

- **Date**: 2026-10-09 (v1.1 through v1.4.7 revised the same day; see Section 10)
- **Status**: Frozen. Becomes "Confirmed" once all verification items in Section 8 pass
- **Basis**: Round 1 debate (`dev/debate-standalone-architecture.md`, local-only, not committed), Round 2 debate (`dev/debate-round2-harness-vs-delivery.md`), research evidence (`dev/research-framework-evidence.md`) (cited below as "evidence §x")
- **Change rule**: for any decision marked "frozen" in this document, a change requires adding a new ADR revision record (Section 10) stating the reason, evidence, and migration cost; parts marked "replaceable" may have their implementation swapped freely as long as the interface stays unchanged. v1.5 is a major version; revision records from here on are numbered v1.5.x

---

## 0. Project Positioning (Core Definition)

**bacmap is a standalone, locally runnable pathogen genome analysis system implemented in Python, with a built-in AI agent layer, exposing its capabilities to external AI assistants through MCP.**

| Question | Answer |
|---|---|
| Is bacmap an AI agent implemented in Python? | Yes, but the agent is only one layer. The core is a deterministic analysis kernel (pipelines, GOM, verification, gates); the agent layer (pydantic-ai plus a local model or LLM API, routed by data classification) handles understanding user intent, interpreting results, and carrying out open-ended tasks. Remove the agent layer and the deterministic features still work as usual (C3) |
| Is a platform like Hermes required? | **No.** bacmap ships with its own web UI, CLI and **in-task** agents (interpretation / open path), connects directly to a local model service (Strata by default) or an LLM API (ADR-08), and completes all functions on its own. (v1.5: everyday conversational interaction is recommended through the native UI of an external harness — Hermes / Pi / DSH — see ADR-21; deterministic functions and the trusted confirmation surface are still provided by bacmap's own CLI/Web.) Hermes is just one optional external client (ADR-15) |
| Are the multiple expert roles a "multi-agent" system? | No, it is not a set of agents conversing autonomously. It is **code-orchestrated multi-role**: the same model, with temporary agent instances created per task step from different role configurations (instructions + tool allowlist + permissions); each instance ends when its step is done, and roles exchange results only through the GOM and the task workspace (ADR-10) |
| What implements the agent layer? | pydantic-ai handles the "call model, run tools, validate output" loop inside a single agent; multi-role orchestration, the task state machine, gates, and the request queue are implemented by bacmap's own code (ADR-08, ADR-10). From v1.5, pydantic-ai only powers **in-task** agents (interpretation, open path); user-facing conversation is handled by external harnesses (ADR-21) |
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
  - (v1.5) these rules are enforced by import-linter contracts (LLM libraries, DBOS, MCP SDK — including lazy in-function imports); what import-linter cannot express (the external subpackage `mcp.client`, the namespace package `bacmap.workflow`) is covered by `tests/unit/test_import_boundaries.py`. The upcoming `bacmap.application` layer must not import the interface layer, and its plan and task services must not import `bacmap.agent` (preserving C3)
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
  - Closed task types: `analyze`, `curate`, `mine`, `write`, `record` (added in v1.7) (Section 4.3; v1.2 renamed `build_db` to `curate`, now meaning local epidemiological baseline library construction, see ADR-19); adding a type requires revising this ADR
  - The default implementation of the `TaskEngine` interface is **DBOS Transact** (embedded, SQLite system database, MIT)
  - The four tables `tasks`, `approvals`, `analysis_runs` (ADR-18), and `baseline_releases` (ADR-19), plus the GOM `events`, are owned by bacmap and are the only externally visible state; the DBOS system database is an internal implementation detail using a separate SQLite file
  - (v1.5.1) new `plans` table (versioned analysis plans, `tasks.sqlite` migration 2); parameters of plannable tasks (analyze/curate) are defined by typed models in `tasks/params.py`; `TaskEngine.submit` gains an optional keyword argument `task_id`, and submission with an explicit ID is idempotent
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
  - **Profiles (v1.5)**: each MCP server instance is bound to one profile — `cloud` (default) exposes only tools with `output_data_class ≤ cloud_max_data_class` (D1 by default, at most D2); `local-trusted` exposes up to D4 and must be explicitly enabled by the administrator with `[mcp] allow_local_trusted = true` in `config.toml`, otherwise the server refuses to start. The profile is fixed by launch arguments and clients cannot escalate themselves; since tool lists no longer vary per connection under the 2026-07-28 spec, different profiles are served by different instances (stdio launch arguments / separate HTTP port and token); the data class is re-checked at call time
  - **Plan tools (v1.5.1)**: `bacmap_create_plan` / `bacmap_revise_plan` / `bacmap_get_plan` — clients can only create, revise and read plans; confirmation happens only in the bacmap CLI/Web (ADR-21); `bacmap_submit_task` remains as a compatibility entry
  - **Submitter identity (v1.5)**: determined server-side from transport and profile (`mcp-stdio:<profile>:<OS account>` / `mcp-http:<profile>`); `bacmap_submit_task` no longer accepts a client-supplied `submitted_by`
  - **2026-07-28 spec alignment (v1.5)**: Tasks is now the official extension `io.modelcontextprotocol/tasks`, but Python SDK v2 does not implement it yet — long tasks keep using explicit handle tools, with semantics aligned to the extension for later migration; MRTR/elicitation is answered by the client (the harness) and **must not** serve as evidence of plan confirmation or approval
- **Security**: the startup command in client configs is hardcoded; all parameters are strictly validated against JSON Schema; logs go to stderr (Logging is deprecated).
- **Rationale**: evidence §7.1–7.3; Hermes ships an `mcp==2.0.0` client of the same generation as the server (evidence §3.5). v1.5: Hermes, Pi (built-in MCP since 0.99) and DSH (`dsh-mcp-client`) can all act as clients, and Hermes already supports the stateless 2026-07-28 protocol (evidence §10.56).

### ADR-13 Data Layer: Frozen (GOM) / Replaceable (knowledge base implementation)
- **Decision**:
  - SQLite (WAL) is kept and the GOM table structure carries over (evidence §2.4); schema versions are managed with `PRAGMA user_version` + numbered SQL migration scripts
  - four new tables: `tasks`, `approvals`, `analysis_runs` (run records, ADR-18), `baseline_releases` (local epidemiological baseline library versions, ADR-19) (v1.2: the original `db_releases` is dropped)
  - two kinds of "database version" are strictly distinguished (v1.2): versions of **reference databases** (CARD, VFDB, PlasmidFinder, MLST/cgMLST schemes, etc., inputs to analysis) are recorded in the run record; versions of the **local epidemiological baseline library** (a summary of analysis results) are recorded in `baseline_releases`, and whenever a conclusion cites local characteristic matching, the baseline library version used is recorded alongside
  - the knowledge base is accessed through the `KnowledgeStore` interface; the v1 implementation is SQLite FTS5 (sqlite-vec optional); GBrain can serve as an optional MCP backend, not a dependency
  - structured analysis facts do not enter the vector store (project.md §8.3)
  - (v1.5) the migration mechanism is implemented: `bacmap.store.migrations` (numbered consecutively from 1, a single `BEGIN IMMEDIATE` transaction, automatic backup to `<db>.bak-v<N>` before migrating, full rollback on failure, refusal to open a database newer than the code); `tasks.sqlite` is adopted first (baseline migration 1 = `tasks` + `approvals`), other databases follow in later migrations; from v1.5.2 `runs.sqlite`, `baseline.sqlite` and `gom.sqlite` (per-file list) are adopted, `data/*.sqlite` is pending
- **Rationale**: the GOM has been validated across seven versions. GBrain connects as an independent process over MCP; the Bun runtime exists only on machines that choose to deploy GBrain and **does not enter the bacmap runtime**, so it does not conflict with ADR-01 (no Node/Bun at runtime); the cost is that machines enabling that backend need one extra Bun service to maintain, which is why it remains optional.

### ADR-14 Web UI: Replaceable
- **Decision**: FastAPI + Jinja2 + htmx + SSE; upgraded from a read-only dashboard to the primary interaction entry (task submission, chat, approval, signing); binds to localhost only by default, LAN access requires enabling authentication.
- **Rationale**: front-line users do not use terminals (Round 2); no front-end engineering is introduced (ADR-01).
- **v1.5.2 addendum**: a versioned JSON API `/api/v1` (tasks, plan confirm/reject, event polling and SSE resume, sample cursor pagination) shares the pages' authentication; it is a trusted surface and its token must not be given to external harnesses (ADR-21).

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
- **v1.5 revision**: Hermes stands alongside Pi and DSH as a first-class supported external harness handling user-facing conversation (ADR-21); it still connects only via MCP and remains "optional" — with no harness installed, bacmap's deterministic functions and trusted confirmation surface are fully available.
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
- (v1.5) the model location behind an MCP client cannot be verified, so MCP clients are **always treated as `cloud`** unless the administrator explicitly enables the `local-trusted` profile (ADR-12)
- (v1.5) MCP only protects data that flows through MCP; external harnesses bring their own shell/file tools, so deployments isolate `BACMAP_HOME` by operating-system account (ADR-21)


### ADR-17 Local Model Resource Arbitration: Frozen (added in v1.1)
- **Background**: Strata is a single-slot service and does not process requests concurrently; the model stays resident in memory at roughly 39–47 GB, which competes with memory-intensive steps such as SPAdes/shovill assembly on a 64 GB machine (measured locally: the Strata process held 44.6 GB resident and about 6 GB of system memory remained available, evidence §8).
- **Decision**:
  - `bacmap.agent.llm` maintains a single request queue; all LLM calls go out serially; each request carries a timeout, and on timeout it degrades to no-LLM behavior
  - the task layer checks available memory before starting a memory-intensive workflow step; if it is insufficient it calls Strata `POST /unload` to release the model, and after the step finishes `POST /load` reloads it (loading takes 1–3 minutes); LLM requests queue or degrade in the meantime
  - config option `llm.resources.co_located` (see the 4.5 example): whether the model and the pipeline share one machine. Arbitration is enabled by default when co-located, and disabled when the model runs on a separate host
  - (v1.5) if an external harness talks to the local Strata directly, its requests bypass bacmap's serial queue: in co-located deployments the harness session is unavailable while arbitration has the model unloaded; harnesses should preferably use a separate inference host or a cloud endpoint (which maps to the `cloud` profile, ADR-21)
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

### ADR-21 Externalized Conversational Agents: Frozen (added in v1.5)
- **Background**: general-purpose agents such as Hermes, Pi and DeepSeek Harness (DSH) already offer mature conversational interfaces (persistent sessions, context compaction, model switching, skills, IM gateways or web UIs), and all of them can use external tools over MCP (Hermes `mcp_servers`; Pi built-in MCP since 0.99; DSH's official `@deepseek-ai/dsh-mcp-client`). bacmap's home-grown conversational UX (TUI streaming, thinking blocks, session history; v1.4.13/31/32) duplicates them at high maintenance cost (evidence §10.56).
- **Decision**:
  - **Conversation is externalized**: users' natural-language interaction happens in the native UI of an external harness, which uses bacmap via MCP (ADR-12); bacmap's built-in conversational assistant (`AgentSession`, the TUI chat panel, Web `/assistant`, CLI `ask`/`chat`) enters a deprecation period; the removal condition (adjusted in v1.5.2) is that the three harnesses have completed real conversational verification and the plan loop is stable; v1.5.3 verified all three (Hermes/Pi/DSH each completed create plan → human confirmation → read back the task), so the condition is met and removal happens in v1.6 as planned; during deprecation it only shows a migration notice and receives no new features
  - **In-task agents stay**: analyze interpretation, curate suggestions and the mine/write open-path agents keep running on pydantic-ai inside the task layer (ADR-08/10/11 unchanged) — external harnesses cannot enter the sandbox, are not bound by gates and cannot record `LlmProvenance`
  - **The trusted confirmation surface stays in bacmap**: plan confirmation, baseline release signatures and mining-artifact sign-off happen only in bacmap's own interfaces (Web approval pages / CLI); tool approvals inside a harness and MCP elicitation are answered by the client or the model and do not constitute confirmation
  - **Structured interfaces stay**: the CLI (with `--json`) and the Web task/sample/report/approval pages remain, serving non-terminal users (ADR-14) and the no-LLM scenario (C3)
  - **The data red line is backstopped by OS isolation**: harnesses bring their own shell/file tools, and MCP profiles only protect data that flows through MCP. Recommended deployment: bacmap runs under a dedicated system account with `BACMAP_HOME` readable only by that account; the harness runs as a normal user and reaches bacmap only via Streamable HTTP (loopback or unix socket) plus a profile token (ADR-16)
  - **Support matrix**: Hermes, Pi (≥0.99) and DSH (pinned while in rc) are the first-class harnesses of v1.5, each requiring real end-to-end verification before release (discovery, read-only, submission, status, errors and exit); a harness's Node/Python runtime is installed by the user and does not enter the bacmap runtime (consistent with ADR-13's treatment of GBrain/Bun, no conflict with ADR-01)
  - **Embedded runtime** (driving an external harness inside bacmap Web) is not a required v1.5 deliverable; if implemented, ACP (Agent Client Protocol, natively supported by Hermes/DSH) comes first, with Pi RPC as the fallback
- **Rejected**: keeping a full conversational TUI inside bacmap (duplicates harness capabilities); handing confirmation/approval to the harness (untrusted); handing in-task agents to the harness (cannot be gated); writing core business plugins per harness (violates ToolSpec as the single source of truth).
- **Reversal cost**: medium — the built-in assistant remains usable until removal; if needed later, pydantic-ai can be re-attached to the same MCP/application-service contracts.

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
    RECORD = "record"   # v1.7: metadata / lab / knowledge records (writes still via tasks only)

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
| MCP profile data-class filtering and server-determined submitter identity (ADR-12, v1.5) | How each profile is deployed (stdio arguments / HTTP port and token) |
| Externalized conversational agents with the trusted confirmation surface kept in bacmap (ADR-21, v1.5) | The specific versions and list of supported harnesses |

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
| v1.4.17 | 2026-10-18 | **Stage C: identification escalation + reference provisioning + recombination (plus orchestration fixes)**: (1) **Escalation ladder** — `gside_species.py` gains `--escalation`: an unresolved verdict escalates `marker→panel→mash_refseq→sourmash→all` until identifiable, recording every tier in `attempts`; unprovisioned tiers fall through (no crash) and an all-fail run keeps `Unknown` with diagnostics (`species_escalation`/`species_mode_max`, off by default). (2) **Reference genomes (NCBI)** — new `workflow/config/reference_accessions.yaml` (`group→out+accessions`; multi-replicon concatenated) and `scripts/fetch_reference_genomes.py` (efetch → `data/reference/genomes/` → registered into `refs/manifest.json` for ADR-18 provenance; offline failures are non-fatal, `--strict` exits non-zero). (3) **Recombination (Gubbins)** — new `scripts/run_recombination.py` (orchestration + format adaptation only) and `rules/recombination.smk`; `plan.recombination` is the sole switch, and a **missing tool writes `status=skipped` (no silent skip)**; Gubbins lives in a separate `recomb` pixi environment (its `iqtree 2.0.3.*` conflicts with the pipeline's `3.1.2.*`, so it solves with `no-default-feature`). (4) **Orchestration fixes** — `run_analysis.py` drops its hardcoded group table (now derived from the registry + `resolve_species` dual-accept, fixing code/name mismatch); `--snp` targeted a wrong single-file path and now targets **per group** (plus recombination targets), and the ≥2-sample count was fixed (it deduplicated codes). A real Gubbins smoke passed (3.4.3, producing GFF + tree). Test baseline 1313 passed; ruff/mypy(88)/contracts/docs-build all green | User ruling (continue Stage C) + implementation verification |
| v1.4.18 | 2026-10-18 | **DEC pathotype determination moved to gapit (`ecoli_dec`)**: gside stops at species (`ECO`), so below-species determination is delegated to gapit's `ecoli_dec` database (`gapit.typing/2`, two schemes — GB 4789.6-2016 and risk-monitoring; fallback `non-DEC`; control gene `uidA`). (1) Removed bacmap's own `call_pathotype.py` (ADR-20: no determination logic in bacmap) and its rule; (2) new adapter `run_dec_typing.py` (`gapit screen --db ecoli_dec` → `gapit typing -f json`; a **missing gapit writes `status=skipped`**, screen/typing failures write `status=failed`+stage — never guesses); (3) pure adaptation module `core/analysis/dec_pathotype.py::summarize` (prefers `gb4789_6`; emits `pathotype`/`pathotype_scheme`/`pathotype_confidence`/`pathotype_genes`/`pathotype_runner_up`/`pathotype_schemes`); (4) `dec/pathotype.tsv` → `dec/pathotype.json` (`report.smk` input updated), `collect_summary` normalizes into `steps.dec`, and `pipeline.get_result` accepts both new (clean string) and legacy (multi-line TSV) shapes. Real smoke passed: a positive contig (escV+stx1a+uidA) → `EHEC` (gb4789_6, high, runner-up STEC). Test baseline 1317 passed; ruff/mypy(89)/contracts/docs-build all green | User ruling (continue remaining Stage C) + implementation verification |
| v1.4.19 | 2026-10-18 | **Agent skill: reference-genome manifest and provisioning status**: new read-only tool `bio_list_reference_genomes` (L1/READ/D0; registry 25→26, 9 read) returning the accession manifest (deployed copy preferred, packaged template as fallback), each cohort group's NCBI accessions, expected output path, whether it has been fetched, whether it is registered in `refs/manifest.json` (with checksum), and the **networked fetch command**; the agent can therefore check status before giving a command or plan (the assistant has no network access and never tries to download). `assistant`/`analyst` SKILL docs gain reference-genome and SNP-cohort guidance (including how to cite DEC pathotype fields). Test baseline 1321 passed; ruff/mypy(89)/contracts/docs-build all green | User ruling (build the agent skill) + implementation verification |
| v1.4.20 | 2026-10-18 | **cgMLST threshold/scheme keys migrated to codes + reference library keyed by scheme**: (1) `config.yaml`'s `cgmlst.thresholds` keys change from species names (`salmonella`/`ecoli`/`shigella`/`vparahaemolyticus`) to **3-letter codes** (`SAL`/`ECO`/`SHI`/`VPA`); (2) the **dead `cgmlst.schemes` block is deleted** (nobody read it; the scheme mapping already lives in the code-keyed `pathogens.yaml`); (3) `cgmlst_projection._normalize_species_key` now uses `species_code`, so the **`_SPECIES_KEY_ALIASES` alias table is deleted** (`Escherichia coli` → `ECO`, etc.); (4) new `core/analysis/cgmlst_reference.py` provides the **single scheme-keyed reference-library locator**, and the two duplicated species→dir alias tables plus `_species_dir_name`/`_CGMLST_SPECIES_DIRS` are **removed**; the path is uniformly `data/reference/cgmlst/<scheme>/reference_profiles.tsv` (matching `vendor_cgmlst_schemes.py`); (5) `generate_cgmlst_summary._load_thresholds`'s group→key map now points at codes. Test baseline 1321 passed; ruff/mypy(90)/contracts/docs-build all green | User ruling (migration) + implementation verification |
| v1.4.21 | 2026-10-18 | **Generic registry-driven gapit typing + factual serotype placeholders**: (1) new `run_gapit_typing.py` (runs `screen`+`typing` for every database a species declares in `gapit_screens`; status is **factual** — `ran` / `no_scheme` (DB not built with `--typing`) / `skipped` / `failed`; `ecoli_dec` excluded, handled by the dedicated DEC step) plus `rules/gapit_typing.smk` (database list derived from the registry via `gapit_screens_for()`); (2) new pure adapter `core/analysis/gapit_typing.py::summarize`, results land in `steps.gapit_typing` and a serogroup-designating scheme is merged into `steps.serotype.serogroup` (+`serogroup_scheme`); (3) the three `pending_gapit` placeholders become **factual**: `ecoh_serotype` → `unavailable` (gapit `ecoh` has no typing scheme; measured `TYPING_NO_SCHEME`), `shigella_serotype` → points at the already-integrated **SISTR**, `vpa_serotype` → `unavailable` (no upstream DB). Real smoke: `lm_doumith` → L. monocytogenes Doumith serogroup **IIa**. Test baseline 1330 passed; ruff/mypy(91)/contracts/docs-build all green | User ruling (continue) + implementation verification (with a real gapit typing smoke) |
| v1.4.22 | 2026-10-18 | **Reference genomes expanded (21 cohorts, all NCBI-verified) + gapit missing-DB status + TUI pty smoke**: (1) new `verify_reference_accessions.py` (NCBJ esummary check of accession↔organism, preventing misplaced accessions); `reference_accessions.yaml` grows to **21 groups** (the original 3 + 18 common pathogens: VCH/VVU/LMO/SAU/KPN/ABA/PAE/EFA/SPN/SPY/NME/NGO/CDI/LPN/HPY/CJE/BPS/YPE) with **all 25 accessions verified**; `pathogens.yaml` gains the matching `snp_group`+`plan.snp` (grouping still derived by the registry). (2) `run_gapit_typing.py` gains an **`unavailable`** status: gapit's `DATABASE_NOT_FOUND` (a declared-but-unfetched DB) is distinguished from a real failure and recorded faithfully. (3) **TUI "computer use" smoke**: new `interfaces/tui/pty_smoke.py` (drives the real `bacmap tui` in a pseudo-terminal: render → type a slash command → Leader chord to quit) plus `test_tui_pty_smoke.py`; it **caught and fixed a real UX defect** — focus landed on the tasks table so input was swallowed, now `on_mount` focuses the input box. Test baseline 1333 passed; ruff/mypy(92)/contracts/docs-build all green | User ruling (add accessions/gapit declarations + computer-use test the TUI) + implementation verification |
| v1.4.23 | 2026-10-18 | **TUI computer-use session (tmux-driven, with the real assembly `GCF_003045604.1.fna`) found and fixed 4 real defects**: (1) `list_tasks`/`count_states` now **lazily reconcile** running tasks against their workflow's terminal state — previously only an explicit `status(id)` transitioned state, so TUI/Web/CLI lists showed `running` forever (observed: two finished tasks stuck in running). (2) `_run_snakemake` now goes through `deploy()`: on a fresh BACMAP_HOME `<home>/workflows/bacmap` does not exist and the old code used it as cwd while skipping the content-hash check → `FileNotFoundError` and stale templates after upgrade (verified: a fresh home now deploys a Snakefile and rewrites project_root to BACMAP_HOME). (3) **Failure reasons reach the task `message`**: `_step_run` captures step exceptions and returns the stderr tail, mine returns the sandbox stderr, and a workflow ending in ERROR (no result) records `workflow <STATUS>` — no more bare DBOS stack traces. (4) The assistant skill documents the exact `context.json` schema (`datasets` is an id→path **mapping**, not an array; the LLM iterated it as an array → `AttributeError` broke the mine task). Also: TUI gains the Leader chord `i` → focus the input box (no direct way back from a focused table; exposed by the real session). Test baseline 1339 passed; ruff/mypy(92)/contracts all green | User ruling (tmux computer-use + given data) real-session exposure + fix |
| v1.4.24 | 2026-10-18 | **Below-species steps routed per species + Shigella serotyping via ShigaTyper**: (1) new pure routing module `core/analysis/routing.py` (`serotype_engine`/`uses_gapit_db`/`report_inputs`); `rules/report.smk` now declares **conditional dependencies** with `unpack(_report_inputs)` — inapplicable steps never enter the DAG and never run external tools (measured: ECO's DAG no longer contains `typing_sistr`/`shigella_serotype`/`vpara_*`; the results directory no longer collects unrelated artifacts). (2) `pathogens.yaml` gains `serotype_engine`: SHI=`shigatyper`, ECO=`ecoh` (SAL already had `sistr`); `WorkflowTables` exposes `serotype_engines`. (3) **ShigaTyper integrated** (bioconda 2.0.5 via `pixi add`): `scripts/run_shigatyper.py` (read-level; factual `ran`/`not_shigella`/`unavailable`/`failed`; planned migration to gapit) and `dec_shigella.smk::shigella_serotype` now actually runs it, **replacing the wrong “Shigella serovar comes from SISTR” placeholder** (SISTR predicts Salmonella only). (4) `collect_summary.py` records `not_applicable` for absent inputs (`steps.serotype.sistr_status`/`steps.dec.status`/`shigella_status`/`pathotype_status`); `vpa_*` no longer appears for species where it does not apply; the GOM strain index no longer records `-:-:-` as a SISTR result for E. coli (now `N/A`). Test baseline 1362 passed; ruff/mypy(93)/contracts/docs-build all green | User ruling (SISTR is Salmonella-only; Shigella uses ShigaTyper; fix via option A) |
| v1.4.25 | 2026-10-19 | **Web login reachability + inline report viewing**: (1) **fixed the `/login` redirect loop** — the old handler 303'd `/login` → `/` outside cookie mode while the middleware 303'd unauthenticated HTML → `/login`, so browsers looped forever (measured: `curl -L` stalled at 303). `/login` now **always renders**: cookie = login form, bearer = explanation (how to enable cookie mode or use Bearer), auth-disabled = “no login needed”; unauthenticated HTML in bearer mode returns **401 with an actionable page** (containing a `/login` link), while API/XHR keeps a plain 401. (2) `bacmap web` prints the URL and auth hint at startup. (3) **HTML reports now render inline by default** (clicking “view” used to download): `/samples/{id}/report` returns `content-disposition: inline` with a response-level `Content-Security-Policy: sandbox; default-src 'none'; style-src 'unsafe-inline'; img-src data:` (no scripts, no external requests, opaque origin); `?download=1` still serves an attachment; the detail page offers both links. (4) the pty smoke now **waits for markers** (ready / output / “Leader 已激活” / exit) instead of fixed sleeps, removing load-related flakiness. Test baseline 1369 passed; ruff/mypy(93)/contracts/docs-build all green | User feedback (“no login path”, “view report becomes download”) + live reproduction and fix |
| v1.4.26 | 2026-10-19 | **Repo-wide code-quality assessment remediation (security tightening + correctness + tooling)**: (1) **`sandbox_shell` allowlist structural-bypass fixes** (quality follow-up to v1.4.13): the segment-split regex now treats **newlines** as command boundaries (`ls\nrm -rf` no longer passes wholesale on the first segment); the deny list adds **hidden-execution syntax** (`$(...)`, backticks, `<(...)`, `-exec(dir)`, `system(`) — measured before: quote-splitting (`cu""rl`), `find -exec nc`, and `awk system()` all slipped through as `allow`; the tool description now states honestly that the allowlist is **intent classification**, not a security boundary (the real boundary is the container backend's network-none + read-only mounts). (2) **Web non-loopback fail-fast** (aligned with MCP HTTP): binding a non-loopback host without a token refuses to start, closing the silent "missing token exposes submit/approve to the LAN" degradation. (3) **Write-side confirmation enforcement**: `execute_plan` gains a `confirmed` assertion parameter and `PlannedTask.requires_confirmation` stops being a dead field; the web confirmation page now renders **full task parameters** (script/input_paths/sandbox_image were previously invisible). (4) GOM `create()` moves the immutability check inside `BEGIN IMMEDIATE` and converts `IntegrityError` → `GOMImmutableError` (preserving the engine's idempotent-retry contract under concurrency); connection leaks in `search_samples`/`_ensure_task_object` fixed with `with`. (5) Tooling: ruff extended with B/C90/SIM/RUF/S (178 findings cleared, including real defects F821/W605/always-true asserts), mypy `disallow_untyped_defs` for core/store, coverage config + task, three copy-paste duplications eliminated (mine artifacts / GOM latest-version SQL / EventType), `approve()` converted to a dispatch table. Test baseline 1373 passed; ruff/mypy/contracts all green | Repo-wide quality assessment (bypasses reproduced live during the security review) + user-directed remediation by priority |
| v1.4.27 | 2026-10-19 | **Quality-assessment low-risk leftover cleanup (round two)**: (1) **tool-layer double error-wrapping removed**: the inner try/except in `query_metadata`/`add_metadata`/`query_lab_results`/`add_lab_result` duplicated the `tool_handler` decorator with inconsistent prefixes — unified under the decorator; a `_parse_limit` helper deduplicates two parsers; tool error messages unified to English. (2) **Coincidental code eliminated**: `max(objs, key=version)` in `snp_tree`/cgMLST loading compares version numbers across object_ids where they are meaningless (version is a per-object sequence); `list_by_type`'s created_at DESC ordering is the real basis — now takes the first explicitly, with a comment. (3) **Engine robustness**: `init_dbos` check-then-set gains a threading lock (no double launch under the web thread pool); `_fastqs` switches to `csv.DictReader` (header-validated, replacing the parts[0]/[2]/[3] magic column indexes); `status()`'s workflow-status mapping extracted into the pure function `_map_workflow_outcome` (+5 unit tests). (4) **Web hygiene**: `/logout` gains CSRF verification (cross-site forced logout, a harassment vector); the twin task routes merged into one renderer; invalid `BACMAP_WEB_AUTH` values now warn instead of silently falling back. (5) **GOM**: calls after `close()` raise an locatable `sqlite3.ProgrammingError` (previously a bare AttributeError); the three identical ID-generator functions unified. (6) **ADR-16 surface**: `LlmConfig.resolve` warns when falling back to the first enabled endpoint for a purpose missing from routing (an accidental-egress path with cloud endpoints and the D0 default — now logged). Test baseline 1381 passed; ruff/mypy/contracts all green | Quality-assessment leftover list + user instruction to "fix the low-risk spots too" |
| v1.4.28 | 2026-10-19 | **Structural refactoring wrap-up (round three, hotspots zeroed)**: (1) **`dbos_engine.py` split** (1044 → 715 lines — the assessment's god-module item): `_runtime.py` (DBOS singleton lifecycle), `_outcomes.py` (approval side-effect dispatch table + workflow-status→task-outcome mapping), `task_engine.py` (`DbosTaskEngine`: tasks.sqlite CRUD / lazy reconciliation / approval persistence). **The split boundary is dictated by two hard constraints**: DBOS recovery semantics require step identity to be module-level stable, and test monkeypatching goes through module attributes (`_run_snakemake`/`_step_*` etc.) — so the step/workflow orchestration core stays together in dbos_engine, and `task_engine.submit` resolves workflows via **call-time module attribute access** (no top-level circular import). All former names are re-exported; existing import paths and test patch points are unchanged. (2) **`create_app` split** (290-line closure factory → assembler + four route factories for auth/sample/task/assistant, each <15 complexity); form parsing (`_submit_task_payload`) and approval construction (`_approval_from_form`) extracted into testable functions. (3) **Complexity hotspots zeroed** (all four noqas flagged in v1.4.26 removed): `samtools_op`(24) → builder + up-front parameter validation; `seq_ops`(25) → eight `_seq_*` handlers + an `_SEQ_OPERATIONS` dispatch table; `_extract_genotype`(20) → four extractors for serotype/MLST/AMR/plasmid. **No function in the repo exceeds mccabe 15.** (4) The mine gate order stays as frozen (gate evaluates artifacts, signature re-checks on approval; the execution side has network isolation + read-only mounts and no egress channel; v1.4.26's confirmation hardening already covers the human-informed side). Test baseline 1381 passed; ruff/mypy(96)/contracts/docs-build all green | User instruction to "refactor the remaining parts" (the assessment's leftover refactoring list) |
| v1.4.29 | 2026-10-20 | **Leftover fixes (round four, A1-A3 from the assessment review)**: (1) **`bio_generate_report` effect corrected COMPUTE→WRITE** (a hard violation of frozen rule 5): report generation writes HTML/PDF under `results/` (three write_text sites) yet was mislabeled COMPUTE and exposed through the MCP read-only surface; relabeled, it is removed from MCP (the test locking the write-tool list updated 3→4), internal call paths unaffected, docs/tools synced in both languages. (2) **GOM reserved-prefix guard**: `GenomeObject.__post_init__` rejects payload keys with the `__gom_*` prefix — the service layer injects pipeline/database versions under that prefix (overwritten on write, stripped on read), so user payloads carrying such keys were silently corrupted; the model boundary now raises `GOMValidationError` (+regression test). (3) **`tool_handler` error envelope tightened**: the catch-all now returns only `f"{func} failed: {type(e).__name__}"` — exception texts often embed host-absolute paths that reached clients and LLM tool context via MCP (the L2 leak surface); full stack traces remain in the service log (logger.exception kept). Known unfixed (on record): no enforcement point for the effect/DataPolicy self-declaration mechanisms (needs mechanism design), `_reconcile_running` N+1, full-scan sample pages, login rate limiting, session revocation channel, sandbox_image allowlist, aware/naive timestamp duality. Test baseline 1382 passed; ruff/mypy/contracts/docs-build all green | User instruction to fix A1-A3 (the recommended items from the assessment review) |
| v1.4.30 | 2026-10-20 | **Cloud conversational assistant (trim-based support, ADR-16 red line untouched)**: the session assistant (Web `/assistant`, TUI chat, CLI ask/chat) was previously marked D4 wholesale (its tool belt includes D4 metadata/lab-result queries) and could only route to local/lan endpoints — while §4.5 v1.2 explicitly supports running API-endpoint-only on GPU-less machines, a deployment shape in which the assistant was unusable, conflicting with the user ruling (external APIs must be able to serve the assistant; a local model is a security option, not a gate). Changes: (1) **location-adaptive tool belt** — on a cloud endpoint `build_session` trims the read-tool belt by registry `output_data_class` against `cloud_max_data_class` (D4 `bio_query_metadata` and D3 `bio_inspect_dataset` stay out of the session), and sandbox tools (`sandbox_run`/`sandbox_shell`, unbounded output that can read raw data) are excluded entirely; (2) **the session data class is derived from the actual belt** (new `session_belt()`: the belt's maximum class, replacing the hardcoded `_ASSISTANT_DATA_CLASS = D4`) — ≤D2 on cloud, automatically degrading to the D0 belt when policy is tightened to D1; (3) `assistant.role.yaml` `allowed_locations` gains `cloud` (this only permits the **location**; the data red line stays code-enforced by the gateway per ADR-16 — D3/D4 payloads are still blocked, and the `DataPolicy` config-level D2 cap rejection is unchanged); (4) local/lan behavior is unchanged (full belt + sandbox + D4). The ADR-16 boundary is untouched: D3/D4 never leave the local network. Test baseline 1382 → 1390 passed (+8: belt trimming / class derivation / both build paths / gateway acceptance); ruff/mypy/contracts/docs-build all green | User ruling (the assistant must work with external APIs; security vs. usability balanced by data-class trimming) |
| v1.4.31 | 2026-10-20 | **Assistant streaming output & thinking indicator (presentation layer, contract unchanged)**: the session assistant (Web/TUI/CLI) previously rendered nothing until the whole "tool calls → thinking → structured plan" run completed — a long silent wait. Changes: (1) **gateway event stream** — `LlmGateway.run_agent_events_async` iterates pydantic-ai `agent.iter()` node by node and calls back `(kind, payload)` events: `thinking_delta` (native reasoning streams such as GLM's), `text_delta`, `reply_delta` (when the provider streams output-tool arguments, a tolerant `"reply"`-prefix extractor emits incremental text and safely waits on truncated escapes), `tool_call`/`tool_result`, `retry`; retry and semaphore semantics match `run_agent_async`, events are display-only and the final result is still fully validated by pydantic-ai. (2) **session layer** — `AgentSession.respond_stream(text, on_event)`, with `respond_async` delegating to it (the TUI cancel path keeps a single entry point). (3) **TUI** — an OpenCode-style braille-spinner activity line (`⠋ 调用 bio_list_samples…`) plus a bottom stream panel (dim italic thinking tail + reply buffer with a `▌` cursor, merged into conversation history on completion); `Esc` stops the spinner and hides the panel. (4) **CLI** — `ask`/`chat` stream (reply deltas to stdout, tool activity dim on stderr; `--json` stays a single payload); Web `/assistant` remains non-streaming for now (SSE is a future option). ADR-08 Tool-Output mode and the ADR-10 planner contract are untouched. Test baseline 1390 → 1399 passed (+9: six reply-prefix-extraction cases, three respond_stream wiring cases; TUI fake sessions renamed respond_async→respond_stream with the API), ruff/mypy/contracts/docs-build all green | User ruling (asked for streaming output and an OpenCode-style thinking indicator) + verified against the real GLM endpoint (424 thinking deltas, 2 tool-event pairs, reply intact) |
| v1.4.32 | 2026-10-20 | **TUI thinking stream inline in the main view (presentation layer; v1.4.31 event contract untouched)**: the v1.4.31 thinking tail lived in a bottom panel above the input box (last 240 chars scrolling backwards) while the conversation view rendered only the final reply — not the OpenCode-style interaction the user asked for. Changes: (1) the conversation view was rebuilt from an append-only RichLog into a componentized message stream (VerticalScroll + one Static per message; `_chat_append`'s signature and the untrusted-text escaping discipline are unchanged); (2) from the first `thinking_delta` a thinking message widget is lazily mounted and streams inline in dim italic (live window capped at 4000 chars, 60ms throttling merges high-frequency deltas); when the turn ends the full text **stays visible** (user ruling: thinking must not vanish automatically), and a new `Ctrl+T` binding collapses/expands the most recent thinking block (Esc-interrupt and error paths finalize it too, with the reason noted); (3) the reply widget streams in place with a `▌` cursor and is finalized with the authoritative `reply.message` — no duplicate append; (4) the bottom `#stream` panel is removed; the spinner/tool-activity line stays in the hint row; (5) installing podman on the host exposed a "no backend" environment assumption in three passthrough tests — they now monkeypatch `_which` to pin the direct-execution semantics (a hermeticity fix, not a weakening of assertions). Test baseline 1405 → 1408 passed (+3: inline stream & finalize / Ctrl+T collapse-expand / interrupt finalize), ruff/mypy/contracts/docs-build all green | User ruling (thinking must render in the main view and stay after completion; interaction aligned with opencode) |
| v1.4.33 | 2026-10-20 | **Pre-assembled FASTA (assembly) direct entry into the closed analyze path**: the closed pipeline previously accepted reads only (samples.tsv R1/R2 → fastp → shovill); finished assemblies could only be explored via the mine sandbox, never reaching the gated, run-record-protected closed path — at odds with "external data should also run through standard analysis". Changes: (1) samples.tsv gains an optional `assembly` column (path relative to BACMAP_HOME; either reads or assembly per sample — reads win when both are listed, and a sample with neither fails fast at DAG build); (2) `assembly_shovill` now emits the intermediate `assembly/shovill/contigs.fa`, and a new `contigs_finalize` rule funnels both sources into the same `assembly/contigs.fasta` — all downstream rules (species/typing/AMR/annotation/report) unchanged; (3) `report_inputs` gains a `has_qc` gate (no `qc_json` in the DAG for assembly-entry samples) and `collect_summary.py` tolerates the missing qc section; (4) kraken2 prefilter targets expand over reads samples only; (5) the engine's `_fastqs` includes the assembly FASTA in the input_files evidence chain (C4). Test baseline 1408 → 1414 passed (+6: two routing qc-gating cases, FASTA/reads dual-entry DAG dry-runs, missing-input fail-fast, one evidence-chain case), ruff/mypy/contracts/docs-build all green | User ruling (FASTA data needs an smk closed path rather than mine) |
| v1.4.39 | 2026-10-21 | **Engine-side fully-automatic directory registration (v1.4.38/39)**: analyze previously accepted only pre-registered samples (samples.tsv), and directory registration was a CLI-only synchronous action — the assistant could not plan it, and a deleted samples.tsv crashed Snakemake inside pandas (hit in real use). Changes: (1) analyze gains `fasta_dir`/`fastq_dir` params; the first workflow step `_step_register_inputs` registers automatically (a write performed via the task engine): FASTA files are identified per-genome by `gside species --mode marker` and assigned species codes (parsing prefers the top-level `verdict`, falling back to `methods.<mode>.species` — fixing an all-batch Unknown caused by reading only the top level), reads pairs `*_R1/_R2` (incl. `_001`/`_1` variants) are matched with species defaulting to `UNK`; unidentified files are skipped and listed in the task message; (2) registration logic consolidated into `workflow/samples_registry` (CLI and engine share it), the CLI gains `--fastq-dir` and `--species` becomes optional for FASTA; (3) deploy self-heal extended: a stamp hit with a missing samples.tsv now also triggers redeploy (template restored); (4) submit validation relaxed to samples or a directory param; (5) concurrent analyze runs no longer fail on the Snakemake directory lock — the engine retries with backoff (45s×4); (6) fastp clean reads are no longer `temp()` (retry interleaving let Snakemake delete them, killing shovill with "Can't read R1"). SKILL updated: the assistant plans `{"fasta_dir"|"fastq_dir"}` directly, removing the stale "assemblies cannot enter the pipeline" teaching. Verified end-to-end on real data: 8 V. parahaemolyticus genomes from ~/temps fully automatically (identify VPA → register → analyze → gates pass), plus one reads sample through the standard pipeline. Test baseline 1429 → 1438 passed (+9: pairing/UNK/single-end skip/three gside JSON shapes/auto-registration/lock retry), ruff/mypy/contracts/docs-build all green | User ruling (hand a directory, get the full auto pipeline: identify → register → standard analysis, no manual species or registration) |
| v1.5.0 | 2026-10-25 | **Major version: externalized conversational agents + MCP data-class profiles (M0 security baseline)**. User rulings: (1) the ADR numbering moves to v1.5; (2) the tighter default MCP profile is accepted (breaking change); (3) runtime protocol ACP first with Pi RPC as fallback, the embedded Web runtime becomes optional; (4) DSH stays a first-class harness; (5) ADR-02 violations are fixed in code. **New ADR-21**: conversation is handled by the native UIs of Hermes/Pi/DSH over MCP and the built-in assistant enters deprecation; in-task pydantic-ai agents, the trusted confirmation surface and the CLI/Web structured interfaces remain; the data red line is backstopped by OS-account isolation. **Delivered now (M0)**: (1) **MCP data-class filtering** — MCP previously filtered only by effect, so D3/D4 tools (`bio_query_metadata`, `bio_inspect_dataset`, eight sequence tools, …) were visible and callable by any client (an existing ADR-16 gap); each instance is now bound to a profile, the default `cloud` exposes only tools ≤ `cloud_max_data_class` (D1 by default), `local-trusted` (≤D4) requires `[mcp] allow_local_trusted = true` and the server refuses to start otherwise; checks at both discovery and call time; `bacmap mcp` / `python -m bacmap.interfaces.mcp` gain `--profile`. (2) **Server-determined submitter identity** — `bacmap_submit_task` drops the client-supplied `submitted_by` in favour of `mcp-stdio:<profile>:<OS account>` / `mcp-http:<profile>`. (3) **CLI write-bypass fix** — `task submit --fasta-dir/--fastq-dir` no longer writes `samples.tsv` outside the task layer; the directory parameter is handed to the engine's first step `_step_register_inputs` (ADR-07: writes only through tasks) and the CLI performs only a read-only existence check. (4) **ADR-02 enforced by contracts** — import-linter grows from 1 to 4 contracts (LLM libraries only in `agent.llm`, DBOS only in `tasks.engine`, MCP SDK only in `interfaces.mcp`/`store.knowledge`/`agent.llm`), and the existing violations are fixed (`agent/session.py` and `agent/sandbox/tool.py` imported pydantic-ai directly → now via the new `agent/llm/tools.py::tool_from_schema`); `mcp.client` and the namespace package `workflow` are covered by an AST boundary test. (5) **ADR-13 migration mechanism implemented** — `store/migrations.py`, with `tasks.sqlite` adopted as version 1. **Migration cost**: existing deployments connecting Hermes or other clients over stdio will by default no longer see D2+ tools; local-model deployments must enable `local-trusted` in config.toml and launch `bacmap mcp --profile local-trusted`. Test baseline 1438 → 1461 passed (+23: profile filtering / refusal to start / identity / CLI delegation / migration framework / import boundaries), ruff/mypy/contracts (4)/docs-build all green | User rulings (review §5 five questions + v1.5 conversational externalization) + code audit (no MCP data-class filtering, client-supplied `submitted_by`, CLI writes outside the task layer, ADR-02 not contract-enforced and already violated, no migration mechanism) + external research (evidence §10.56) |
| v1.5.1 | 2026-10-25 | **Versioned plan loop (the execution side of ADR-21)**: external harnesses can only **create / revise / read** plans over MCP (`bacmap_create_plan` / `bacmap_revise_plan` / `bacmap_get_plan`); confirmation happens only on bacmap's trusted surfaces (CLI `bacmap plan ls/show/confirm/reject`; Web `/plans`), and MCP offers no confirmation or approval tool. (1) **Typed task parameters** (`tasks/params.py`, ADR-06 addendum): `AnalyzeParams` (exactly one of samples / fasta_dir / fastq_dir, sample-ID allowlist, absolute directories, unknown fields rejected) and `CurateParams` (scope = pathogen / strains); mine/write stay out of plans (consistent with the existing MCP/form rules). (2) **plans table** (`tasks.sqlite` migration 2) plus a new application-service layer `bacmap.application` (`PlanService`, unified errors `validation_error/not_found/conflict`); import-linter grows to 5 contracts (the application layer must not import the interface or agent layers). (3) **Canonical hash**: `plan_hash` = SHA-256 of key-sorted, compact, ASCII-escaped canonical JSON (typed parameters + input-directory fingerprints); confirmation requires `(plan_id, version, hash prefix ≥12)`, and a revision creates a new version that `supersedes` the old one — confirming v1 can never run v2. (4) **Input fingerprints**: directory inputs are fingerprinted at plan creation (relative path + size + mtime_ns) and re-checked at confirmation; any change or disappearance is a conflict. (5) **Idempotent submission with deterministic task IDs**: `TaskEngine.submit` gains an optional keyword argument `task_id` (an existing explicit ID returns idempotently without restarting the workflow); plan task IDs derive from `plan_id/version/index`, so repeated confirmation, concurrent confirmation from two surfaces, or re-confirmation after a crash all yield the same set of tasks. (6) `bacmap_submit_task` remains as a compatibility entry, and its description steers new clients to plans. Real smoke test: stdio MCP client (cloud profile) creates a plan → CLI confirms → `bacmap_get_plan` returns the task_id → `bacmap_task_status` reports it. Test baseline 1461 → 1502 passed (+41: parameters / hashing / supersession / concurrent confirmation / input fingerprints / engine idempotency / CLI / Web / MCP), ruff/mypy/contracts (5)/docs-build all green | ADR-21 and review §3.4 (plan hash, input snapshot, deterministic IDs) + implementation verification |
| v1.5.2 | 2026-10-25 | **Domain events, versioned JSON API, MCP task control and harness checks; plan adjustment**. (1) **Event log** (`tasks/events.py`, `tasks.sqlite` migration 3): append-only `events` table whose monotonic `seq` is the resume cursor; key plan transitions (created/revised/confirmed/submitted/rejected/failed) and task transitions (submitted/step/state/approval) are recorded; events are not the source of truth, and clients recover by querying after a disconnect; task-message events are marked D2. (2) **Step progress**: `current_step` was never updated after submission; it is now written inside existing DBOS step bodies (register_inputs/pipeline/run_record/ingest_and_gates/sandbox/draft/curate_build/gate) without adding steps, so the replay sequence of in-flight workflows is unchanged. (3) **`/api/v1`** (ADR-14 addendum): capabilities, tasks (with cancel), plans (with confirm/reject), events (cursor polling + SSE resuming from `Last-Event-ID`), samples (cursor pagination that parses only the requested page); shares authentication with the pages, state-changing requests in cookie mode need `X-CSRF-Token`; errors are `validation_error/not_found/conflict` → 400/404/409; the API is a trusted surface and its token must not be given to a harness. (4) **MCP** (ADR-12 addendum): new `bacmap_task_cancel` (only tasks the principal submitted directly or through a plan it created) and `bacmap_task_result` (run ID + gate verdicts; counts only for profiles below D2); under `cloud`, `bacmap_task_status` withholds the task message (it can contain sample IDs or host paths); role instructions are published as `skill://bacmap/<role>/SKILL.md` resources with a sha256 digest (SDK 2.3 has no Skills extension yet, so standard resources are used). (5) **Migrations**: `runs.sqlite` and `baseline.sqlite` adopt numbered migrations (version 1); `gom.sqlite`, shared by the GOM and the dataset registry, now uses one **per-file** list `GOM_MIGRATIONS` used by both modules (legacy files are adopted losslessly with an automatic backup); `data/*.sqlite` (strain index / metadata / lab results / knowledge base, whose file ownership depends on the caller) is **deferred**. (6) **Harness checks**: Hermes 0.21.3 (`hermes mcp test`) and Pi 1.1.0 (`pi mcp list`) both connect and discover 9 tools (Pi also lists 7 skill resources); DSH 0.2.1-rc.2 composes the configuration and launches the bacmap MCP server at plugin start, while the model call was not run for lack of credentials; DSH requires new entries to be wrapped in `insert:`, documented in the new bilingual `docs/harnesses*.md`. (7) **Plan adjustment (ADR-21)**: the removal condition for the built-in assistant changes from "the three front ends have migrated" to "the three harnesses have completed real conversational verification (needs model credentials, not automated) and the plan loop is stable", expected in v1.6; during deprecation the three front ends show a migration notice (CLI `ask/chat` print it on stderr, keeping `--json` clean) and receive no new features; the planned work to route the assistant's execution path through PlanService is dropped (no further investment in a path slated for removal). (8) `bacmap.__version__` now comes from installed metadata, with `pyproject.toml` as the single source. **Version numbering (user ruling)**: v1.5.x is the revision number of this architecture document, not the program version; the program stays at 0.1.0 (early development), and the earlier practice of bumping the program version along with document revisions (1.4.x/1.5.x) stops. Test baseline 1502 → 1546 passed (+44), ruff/mypy/contracts (5)/docs-build all green | Review §3.4/§3.6/§3.9 + harness checks + implementation verification |
| v1.5.3 | 2026-10-25 | **ADR-21 verification condition met (real conversations across three harnesses)**: with `glm-5.3` on the Zhipu coding-plan endpoint, Hermes 0.21.3, Pi 1.1.0 and DSH 0.2.1-rc.2 each completed two conversational turns — (1) call `bacmap_create_plan` and report `plan_id/version/state`; (2) after a person confirmed that exact version with `plan confirm` in the CLI, call `bacmap_get_plan` and `bacmap_task_status` and read back `submitted` plus the task ID. All three passed (DSH must patch the **existing** `llm-pi-ai` entry; adding a second `dsh-llm-pi-ai` fails because `amazon-bedrock` is already declared). Conclusion: the ADR-21 condition "the three harnesses have completed real conversational verification" is satisfied and the built-in assistant is **eligible for removal**; per the existing plan it is still removed in v1.6 (no code is deleted here, to avoid shipping that with the API/event work). Reproduction script `dev/harness-e2e.sh` (local, not committed, key only via environment). Verification record in `docs/harnesses*.md` §5. No code change; test baseline stays at 1546 passed | User ruling (use the Zhipu coding-plan credential) + measurement |
| v1.6.0 | 2026-10-25 | **ADR-21 executed: the built-in conversational assistant is removed (TUI becomes a task console)**. v1.5.3 verified the three harnesses end to end, so this version removes the built-in assistant as planned: (1) delete `bacmap.agent.session` (AgentSession/AnalysisPlan/PlannedTask/build_read_tools), `bacmap.interfaces.assistant` (build_session/execute_plan/format_plan), `agent/skills/assistant/SKILL.md` and `agent/roles/assistant.role.yaml` (MCP prompts drop from 7 roles to 6); (2) the CLI drops `ask`/`chat` (`bacmap <cmd>` is now `{mcp,web,tui,console,overview,task,plan,sample,search}`); (3) the Web console drops `/assistant` and its template, and the navigation becomes Tasks / Plans / System / Samples; (4) **the TUI is rewritten as a task console**: status header, tasks/samples sidebar, leader chords, two-step approval signing, task-failure echo, `/result`, `/search`, `/analyze`, `/curate` all stay; the conversation stream, thinking stream, plan confirmation, `Ctrl+F`/`Ctrl+T`, `/new` and the session semantics of `/model` are gone; the input box accepts only slash commands and answers natural language with a pointer to an external harness. This also fixed a real defect: **the Input widget swallowed printable leader chords** (`a`/`t` did nothing while the input was focused); the new `_CommandInput` hands keys back to the App while the leader is active, with a regression test. (5) **In-task agents stay** (interpretation and sandbox_run/sandbox_shell are still pydantic-ai, ADR-08/11 unchanged). (6) **ADR-13 per-file migrations completed**: `data/bacmap.sqlite` (strain metadata + lab results) and `data/knowledge.sqlite` (knowledge base + FTS triggers) adopt lists; the **strain genotype index actually lives in the GOM database** (`dbos_engine`/`tools.services` open it on `gom.sqlite`), so it becomes `GOM_MIGRATIONS` version 2 rather than part of the data list; the DDL single source stays in each store module and `store/schema.py` only aggregates per file (lazy imports avoid cycles). (7) Evidence and docs: `docs/usage*.md` rewrite §2/§3/§4 (conversation → external harness, plan confirmation, TUI task console), `docs/installation*.md` verify with `bacmap overview`, the README command table drops `ask`/`chat`, `docs/harnesses*.md` records the verified versions; `dev/harness-e2e.sh` stays as a local reproduction script (not committed). **Test baseline adjustment**: after 1546, this version removes the built-in-assistant tests (`test_agent_session.py`, `test_assistant_deprecation.py`, TUI chat/thinking/plan, CLI ask/chat, Web assistant — about 90 items) and adds task-console / removal-assertion / per-file migration tests; the baseline is adjusted from 1546 to **1500** (a **legitimate adjustment caused by deleting a feature, not deleting tests to make things pass**, and AGENTS.md rule 7 explains it) | User ruling (continue v1.6) + v1.5.3 harness verification + implementation verification |
| v1.6.1 | 2026-10-25 | **The four v1.7 items: dead-code cleanup, a capabilities tool, Hermes re-verification, and the ACP decision**. (1) **Removed code that only the old assistant used**: the LLM gateway drops `run_agent*`, `structured_async`, the tool-agent factory and the streaming JSON-prefix parser (550 → 203 lines); `agent/intent.py` (intent classification, already judged removable by ADR-21), `agent/sandbox/tool.py` (the pydantic-ai shells for `sandbox_run`/`sandbox_shell`, unreachable in production — the sandbox executor and `access.py` stay, mine tasks still use them), `agent/llm/tools.py` and the CLI `_stream_respond` are deleted; their tests go too, replaced by regression assertions that the modules/methods are gone. (2) **New MCP tool `bacmap_capabilities`** (read/D0, also available in read-only mode): server version, profile and data-class ceiling, plannable task types, recommended write path, long-task mechanism, and **`tasks_extension: unsupported_by_sdk`**. (3) **MCP Tasks extension status**: the Python SDK is still 2.3.0 and does not implement `io.modelcontextprotocol/tasks` (its docstring merely cites `tasks/get` as an example); bacmap keeps explicit task handles, semantically aligned with the extension, and migrates when the SDK supports it — recorded in capabilities and the evidence file. (4) **Hermes 0.17.0+52045 re-verified**: two upstream workarounds are required — `CMAKE_POLICY_VERSION_MINIMUM=3.5` on first launch (python-olm 3.2.16's cmake floor), and `hermes auth add zai` because the isolated runtime no longer reads the API key from the environment; documented in `docs/harnesses*.md`. (5) **ACP embedded runtime decision (optional, not implemented)**: ACP is an editor-drives-agent conversation protocol; implementing it would reintroduce a conversation surface and a tool layer, contradicting ADR-21 and the cleanup just done, and there is no concrete consumer yet (editors can reach bacmap over MCP). The ACP Python SDK 0.12.1 is available and is not added as a dependency; revisit on a concrete editor/remote need, building a thin adapter over `agent.llm` plus the application services without rebuilding TUI/Web chat. Test baseline 1500 → 1489 (net deletion of dead-code tests plus new capabilities/removal assertions, same rationale as v1.6.0) | User ruling (continue the four v1.7 items) + implementation verification + Hermes measurement |
| v1.7.0 | 2026-10-26 | **P0 data entry: a fifth task type `record` (ADR-06 revision)**. Background: metadata, lab results and the literature knowledge base previously had only registry write tools or store methods — no CLI/Web/MCP entry — while `curate` requires complete metadata and the `write` citation gate requires approved entries, so both main lines were blocked at data entry (even more visible after v1.6 removed the assistant). Following ADR-07 ("writes only through the task layer"), a new closed type `RECORD` (`tasks/records.py`) covers: (1) `metadata` (field allowlist = known store columns, extra keys rejected); (2) `lab_result`; (3) `knowledge_import` (staged only, `approved_by` empty); (4) `knowledge_approve` (the citation gate only honours approved entries). Parameters are validated with a discriminated union **at the submission entry**; `submit` rejects invalid payloads; a single-step workflow writes the corresponding store and converts exceptions into `FAILED` with a readable message (no more bare `workflow ERROR`). Entry points: CLI `bacmap record metadata|lab|knowledge-import|knowledge-approve` and Web `/records` (three forms plus approval, CSRF-protected in cookie mode). Record tasks are **not plannable** (`PlanService` still only accepts analyze/curate) and **not exposed over MCP** (D4 writes, ADR-16). Also fixed a constructor-order defect in `StrainMetadataService`/`LabResultService` (connected before creating the parent directory, causing `unable to open database file`). Test baseline 1489 → 1510 (+21: models/workflow/CLI/Web), all four gates green | User ruling (proceed in the P0 data-entry order) + implementation verification |
| v1.7.1 | 2026-10-26 | **Evidence visibility (P0 item 2)**: run records and GOM objects were previously readable only from internal tools. New read-only surfaces: (1) CLI `bacmap run ls|show|compare` and `bacmap gom ls|show`; (2) `/api/v1/runs`, `/runs/{id}`, `/runs/{id}/compare?other=`, `/gom/objects`, `/gom/objects/{id}?version=`; (3) Web pages **Runs** (list, detail, provenance-compare form) and **GOM** (latest-version list plus payload view). Run comparison reuses ADR-18's `compare_runs` (field-by-field attribution across parameters/databases/tools/inputs/workflow) instead of inventing a new verdict. The GOM list shows payload key names only; the full payload lives on the detail page. Test baseline 1510 to 1517 | User ruling (follow the P0 order) + implementation verification |
| v1.7.2 | 2026-10-26 | **Open-path tasks in plans, operations commands, and a publishable docs site**. (1) **Four plannable types**: `PlannableTask` gains `mine` (objective, script up to 20k, absolute input_paths, sandbox_image, input_data_class D2-D4) and `write` (objective, draft up to 40k, known_citations); the full `script`/`draft` text enters the plan hash and is shown at confirmation, so what you read is what runs; `mine` input files/directories are fingerprinted at plan creation (files by size+mtime, directories recursively) and re-checked at confirmation with a conflict on change. MCP `bacmap_create_plan` accepts all four (description updated) and `bacmap_capabilities.plannable_task_types` follows. Security semantics are unchanged: execution stays inside the network-less sandbox and artefacts still pass the mining gate plus signature; record tasks remain unplannable and absent from MCP. (2) **Operations commands**: `bacmap doctor` (home writability, database version, sandbox backend, LLM, disk, external tools; exit code 1 on failure), `bacmap backup --out [--with-results]` (config plus consistent SQLite snapshots via the backup API plus run manifests, as a zip), `bacmap restore --from [--force]` (refuses non-empty targets, zip-slip protection, per-database integrity_check) and `bacmap events prune --days N` (event retention), backed by `EventLog.prune`. (3) **Docs site completed**: new bilingual `docs/operations*.md` (health checks, backup/restore, migrations, upgrade checklist, runtime isolation), updated mkdocs navigation and README doc index, and usage additions for runs/GOM, open-path plans and operations. Test baseline 1517 to 1529 | User ruling (continue P1 and raise docs to publishable quality) + implementation verification |
| v1.8.0 | 2026-10-26 | **Identity model (ADR-22 direction) and registration-collision fix (I1)**. Background: one strain may be sequenced many times (different platforms, batches, passages) and each dataset and result must stay independently evidenced; today `sample` collapses strain, dataset and result directory into one key, so a same-named but different file is silently reused (the old file is analysed), a re-run overwrites reports, and multi-platform/passage data cannot be expressed. User rulings: (1) passages are modelled as **one isolate per passage plus `lineage_id` and `passage`**; (2) once P2 (run-scoped results) lands, legacy flat directories are **deleted immediately**; (3) storage optimisation (redundant intermediates / cold archive) is deferred and recorded (measured: 8 strains = 149 MB, ~19 MB each, of which ~10 MB of `spades.fasta` + `contigs.gfa` is pure redundancy). **This release lands the first slice of I1**: `samples.tsv` v3 (`sample` now means dataset id; new `isolate`/`platform`/`checksum`; v2 upgrades automatically); the `<isolate>__<platform>[__<date>]` naming convention is parsed on registration; registering an existing dataset id is idempotent **only when the content hash matches**, otherwise it fails immediately with both paths and a rename suggestion (SHA256 of the FASTA file, or of R1+R2 together), eliminating silent analysis of the old file. Remaining: I2 run-scoped result directories (the engine already supports `--config workdir`, so no .smk changes are needed), I3 isolate-level cohort/baseline representative-run policy, and the `isolates` table plus lineage/passage commands. Test baseline 1529 → 1537 | User rulings (defer P1, P2 option A, re-plan P3) + implementation verification |
| v1.8.1 | 2026-10-26 | **P2 option A landed: run-scoped result directories**. Physical layout is now `results/runs/<task_id>/<sample>/...` (everything one execution produced, never overwritten; cohort output `snp/` and `cgmlst/` belongs to that run). `results/<sample>`, `results/snp` and `results/cgmlst` are relative symlinks to the **latest run** — views, report scripts, tools and tests keep their paths and still see the "latest result", while every historical run stays intact. The engine change is small: `_run_snakemake` passes `--config workdir=results/runs/<task_id>` (the Snakefile computes `WORKDIR = PROJECT_ROOT / config["workdir"]`), targets point into the run directory, and the links are repointed atomically on success. New `bacmap results migrate [--dry-run]` moves legacy flat `results/<sample>/` into `runs/legacy-<sample>/` and **replaces it with a link immediately** (user ruling: no compatibility copy). Readers (views, tools, GOM ingest) still use the flat path and follow the link, so none of the 29 fixture-heavy tests or report scripts had to change. Risk handling: if `<sample>` is still a real directory, relinking refuses and asks for a migration first. Test baseline 1537 → 1545 | User ruling (P2 option A, delete old dirs immediately) + implementation verification |
| v1.8.2 | 2026-10-26 | **First slice of I3: isolate registry and passage lineage**. New `isolates` table (`data/bacmap.sqlite` migration 2: `isolate_id`/`lineage_id`/`passage`) and `IsolateService`; registration into `samples.tsv` now ensures isolate rows (idempotent, explicit lineage/passage preserved). Names such as `EVO-001-P037` parse to `lineage=EVO-001, passage=37`; plain strains carry no lineage. New CLI `bacmap isolate ls|show [--json]`. **Remaining I3**: curate selecting one representative run per isolate (so multiple datasets of one strain are not double-counted in the baseline), cohorts aggregated by isolate/lineage, and explicit `isolate create/update` for lineage maintenance. Test baseline 1545 → 1552 | User ruling (continue I3) + implementation verification |
| v1.8.3 | 2026-10-26 | **Second slice of I3: curate picks one representative run per isolate**. `build_candidate` now groups by `isolate` (from `samples.tsv` v3, falling back to the dataset id) and includes each isolate once: by default the **latest analysis** (summary mtime with a stable tie-break), or an explicit choice via `{"representative_dataset": {"<isolate>": "<dataset>"}}`. The decision is recorded in `representative_runs` (dataset, summary, reason) and the unused datasets in `superseded` (with the reason); a missing explicit choice becomes `excluded` with `representative_dataset_missing`. `scope.strains` accepts dataset or isolate ids; metadata lookup uses the isolate (falling back to the dataset), and the default metadata DB is corrected to `data/bacmap.sqlite`. Test baseline 1552 → 1556 | User ruling (continue representative-run work) + implementation verification |
| v1.8.4 | 2026-10-26 | **Built for non-CLI users: natural-language data management and a repositioned tutorial**. (1) New MCP `bacmap_record_data` (`local-trusted`/D4 profiles only): agents can submit metadata, lab results and knowledge import/approval through the task layer (reusing `record` tasks and validation); cloud profiles hide it. This makes "just tell the agent about the isolate" a real path. (2) The tutorial is rewritten **agent-first** (about 180 lines per language): natural-language dialogue carries installation, the first analysis, follow-ups, data management, mining, reports and boundaries; the CLI appears only in a short fallback section with links to the reference docs — answering the product goal of sparing ordinary users from bioinformatics commands. Test baseline 1556 → 1559 | User feedback (tutorial should show the agent/LLM, less CLI) + implementation verification |
| v1.8.5 | 2026-10-26 | **Natural-language troubleshooting**. (1) MCP `bacmap_task_status` no longer returns only an empty message below D2: it adds a **redacted `failure` block** (kind / suggested fix / recovery commands, without sample IDs or raw paths), so cloud agents can help diagnose; `failure_diagnostics` gains a `sandbox_unavailable` pattern (missing Apptainer/Podman). (2) The tutorial (both languages) gains a "When something breaks, ask it first" section covering failed tasks, missing sandbox, wrong paths, dataset collisions, confirmation conflicts, data-class blocks, stuck tasks and log access, with the explicit boundary that the agent diagnoses and proposes but never executes privileged actions or signs. Test baseline 1559 → 1562 | User feedback (problems during use should also be handled by the LLM) + implementation verification |
| v1.9.0 | 2026-10-26 | **Three convenient confirmation channels (A then B then C, per user ruling)** for the "plan in Hermes, but confirm in a terminal" friction. A: plans carry `confirm_url` (`BACMAP_WEB_URL`, default `http://127.0.0.1:8800`) opening the Web plan page; B: new MCP `bacmap_confirm_plan_locally` (stdio only) opens a local system dialog (zenity/kdialog) where **the human click** is the confirmation fact, audited as `actor=local-dialog`, falling back to `confirm_url` when no GUI exists; C: `[plans.auto_confirm]` (off by default) auto-confirms only low-risk analyze plans with no script and ≤ `max_samples`, audited as `actor=policy:auto-confirm`; mine/write/curate are never auto-confirmed. Shared invariants: bound to `(plan_id, version, plan_hash)`, single-use, invalidated by revisions, and the model can never self-attest confirmation. Tutorial §3.4 becomes "confirm without leaving the chat"; configuration documents the policy. Test baseline 1562 → 1568 | User ruling (implement A/B/C in order) + implementation verification |
| v1.9.1 | 2026-10-27 | **Code-review round (R1–R7) fixes**: (1) `results migrate` no longer `rmtree`s an existing run directory (which would delete prior results); it picks an incrementing directory and never deletes; (2) legacy samples.tsv rows without `checksum` now have their recorded files re-hashed, so a same-id/different-content file is caught; (3) a malformed `[plans.auto_confirm] max_samples` safely falls back to "human confirmation required" instead of raising; (4) full ruff/mypy/contracts plus MCP/plan/record/evidence-view/CLI review found no new issues. Three consecutive clean rounds ended the pass per the user's stop rule (scope in `dev/code-review-log.md`; not a claim of 100 full rounds). Test baseline 1568 → 1571 | User request (100 rounds, stop after 3 clean) + implementation verification |
| v1.9.2 | 2026-10-27 | **20-round code review (R1–R20) fixes**. (1) **Result layout**: `link_run_results` now auto-migrates legacy real directories (samples plus old `results/snp`/`cgmlst`) before repointing the latest aliases, so `_link` no longer refuses a real directory and turns a **successful analysis into a failed task**; `results migrate` covers cohort directories too, superseding the v1.8.1 "relinking refuses, migrate first" risk clause. (2) **Identity/inputs**: the sample-id whitelist rejects `.`/`..`, directory registration skips illegal dataset ids with a reason, and relative `R1`/`R2` paths in `_fastqs` resolve against `BACMAP_HOME` (matching Snakefile `PROJECT_ROOT`), restoring `input_files` in the evidence chain. (3) **Confirmation/plans**: channel C only auto-confirms analyze plans with **non-empty registered samples** (directory ingestion can no longer bypass `max_samples` with zero samples); MCP `bacmap_get_plan`/`bacmap_revise_plan` are limited to the client that created the plan. (4) **Writes/audit**: `write` with `known_citations=[]` falls back to the approved knowledge base as documented (the old default made every draft fail the citation gate); knowledge approval is single-shot so a later reviewer cannot overwrite the original approver; dataset content dedup only escalates the data class (D4 is never downgraded by an earlier D3 registration). (5) **Interface robustness**: approving an already-terminal task returns 409 instead of 500; `scope` must be a JSON object (Web/CLI); `safe_next` rejects the `/\` open-redirect bypass and control characters; analyze input-registration and mine sandbox-preparation failures become readable FAILED messages instead of `workflow ERROR`; views and curate only accept same-named summaries (stale differently-named files no longer create duplicate/wrong samples); run records now write `ingested_at`; an explicit representative isolate that does not exist is recorded in `excluded`. (6) `dev/code-review-log.md` records the 20 rounds and remaining gaps. Test baseline 1571 → 1606 | User request (20 rounds, fix after tests, sync docs) + implementation verification |
| v1.9.3 | 2026-10-27 | **Run-scoped read isolation for concurrent analyses + DBOS checkpoint backup**. (1) After a successful pipeline, `analyze_workflow` resolves this run's physical directory `results/runs/<task_id>/`; summary loading, the analysis-claims gate, report generation, per-sample cgMLST profiles and cohort ingestion all read only that directory. `_load_summary`/`_run_results_base` fall back to the legacy flat layout only when the run directory does not exist (test fixtures and tasks resumed from before the upgrade); if the run directory exists but lacks an artefact it means "no result in this run", never the possibly re-pointed latest-run alias. The report script gains an internal `--results-dir` (not exposed on the MCP tool surface) and writes into the run directory. (2) `bacmap backup` now includes `dbos.sqlite` (workflow/step checkpoints): previously the task tables were backed up without the DBOS system database, so in-flight tasks could not resume after restoring to another machine; operations docs updated. Closes the v1.9.2 residual item "concurrent analyses of the same dataset may read each other's results". Test baseline 1606 → 1610 | User request (continue modifying) + implementation verification |
