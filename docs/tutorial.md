**English** | [简体中文](tutorial.zh-CN.md)

# From zero to a report: a hands-on bacmap tutorial

> This is not a command reference. The reference tells you which flags exist; this tutorial walks
> through a real working day — from a folder of sequencing reads to a report you can send to a
> colleague, and to an answer when someone asks "why should I trust this?"
>
> Outputs below are illustrative (IDs, counts and timings vary). Commands, flags and guarantees are
> accurate for the current release; the reference pages remain the source of truth.

## Prologue: eight isolates on a Monday morning

08:40. An email arrives:

> "The eight *Vibrio parahaemolyticus* isolates from last week finished sequencing; reads are in
> `/data/run42/`. Also check whether they cluster with last year's O3:K6 strains. A report by
> Friday, please."

You have a Linux workstation with bacmap on it. Over the next couple of hours we will do the whole
job — and leave evidence behind at every step, so that six months from now nobody has to guess which
database version was used.

---

## Chapter 0: what bacmap actually is

bacmap is not a chat box. It is closer to a **lab with a door policy**:

```
 you / colleagues ── CLI, Web ─┐
                               ├─▶ task layer (five task types) ─▶ Snakemake / sandbox
 external agents ── MCP ───────┘        │
   (Hermes/Pi/DSH)                     ├─ four gates: claims, release, mining, citation
                                       └─ evidence: run records + GOM + signed approvals
```

Three rules are enough to operate it:

1. **Analysis runs through a fixed pipeline (L1).** Species, serotype, MLST and resistance come from
   gside / gapit / gmlst plus Snakemake; no model decides biology.
2. **Writes go through tasks.** Data entry, analysis, curation, mining and drafting are all tasks —
   with state, recovery and an audit trail.
3. **Conversation lives in the harness.** You speak naturally in Hermes, Pi or DSH; they propose
   **plans** over MCP, and **a human confirms in bacmap**.

Curious what it accepts? `bacmap task --help`. Curious about the system? `bacmap overview`.

---

## Chapter 1: installation — building the lab

### 1.1 The environment

bacmap uses pixi (Python and bioinformatics tools in one environment):

```bash
git clone https://github.com/indexofire/bacmap.git
cd bacmap
pixi install          # first run downloads the toolchain
pixi shell            # afterwards bacmap / gside / gapit / gmlst are on PATH
```

Check it:

```bash
bacmap --version
# bacmap 0.1.0
bacmap overview
```

`overview` prints the data home, the cloud data-class ceiling, the sandbox backend, component versions
and LLM endpoints. **Seeing `sandbox: passthrough` on day one is normal** — it only affects mining
tasks; the standard pipeline does not need a container.

### 1.2 Where data lives

The default home is `~/.local/share/bacmap` (override with `BACMAP_HOME`). It grows into:

```
$BACMAP_HOME/
├── config.toml          # optional (LLM, MCP)
├── tasks.sqlite         # tasks, approvals, plans, events
├── runs.sqlite          # run records (the evidence chain)
├── gom.sqlite           # GOM objects + strain index
├── data/                # metadata, lab results, knowledge base
├── results/<sample>/    # per-sample results and reports
├── workflows/bacmap/    # the deployed Snakemake workflow
└── workspaces/          # mining workspaces
```

A quick health check:

```bash
bacmap doctor
```

```
✓ home      /home/you/.local/share/bacmap
! database  tasks.sqlite 尚未创建（首次运行后生成）
! sandbox   passthrough
! llm       no usable LLM endpoint (deterministic paths still work)
✓ disk      212.4 GB free
```

`!` is a heads-up, not a failure. **bacmap completes every deterministic function without an LLM.**

### 1.3 Adding a model (two minutes, optional)

For in-task agents (interpretation) or external harnesses, add an endpoint:

```toml
# ~/.local/share/bacmap/config.toml
[llm.endpoints.glm]
kind = "openai_compatible"
location = "cloud"                      # cloud: D0–D1 by default
base_url = "https://open.bigmodel.cn/api/paas/v4"
model = "glm-5.3"
api_key_env = "GLM_API_KEY"
tier = "T2"

[llm.routing]
intent_classifier = "glm"
interpretation = "glm"
```

```bash
export GLM_API_KEY="your key"
bacmap overview
```

**Mind the red line:** a cloud endpoint may receive D0–D1 by default; D3 (sequences) and D4 (personal
data) never leave the local network. An administrator may relax single-strain results (D2) to cloud
(`cloud_max_data_class = "D2"` at most — D4 in the config is rejected outright).

---

## Chapter 2: the first run — eight isolates in, eight results out

### 2.1 Let bacmap name the samples

Reads live in `/data/run42/` as `HZCPE-01_R1.fastq.gz` / `_R2`. No spreadsheet needed:

```bash
bacmap task submit --type analyze --fastq-dir /data/run42
```

```
已提交任务 3f9c1a2b7d4e4c0e9b1a6d2f8c5e7a10（analyze）
```

What just happened?

1. The task scans the folder, pairs `_R1/_R2`, and derives eight sample IDs (`HZCPE-01` … `HZCPE-08`);
2. It registers them into `samples.tsv` **as part of the task** (not as a side effect of the CLI);
3. It starts Snakemake: fastp → shovill → gside species ID → MLST/SISTR/AMR/virulence/plasmid → report.

If you already know the species, `--species VPA` skips auto-identification for speed. Letting it
identify is safer: a wrong species shows up as `Unknown` in the report rather than being forced.

### 2.2 Watch it

```bash
bacmap task show 3f9c1a2b
```

```
3f9c1a2b7d4e4c0e9b1a6d2f8c5e7a10  state=running  step=pipeline
```

`step` walks through `register_inputs → pipeline → run_record → ingest_and_gates`. `bacmap task ls`
shows everything; `watch -n 5 bacmap task show …` if you like watching paint dry.

### 2.3 Where results land

```bash
bacmap sample ls
bacmap sample show HZCPE-01
```

The report is a self-contained HTML file:

```
results/HZCPE-01/report/HZCPE-01_report.html
```

Open it in the Web console (chapter 6) or copy it to your laptop.

### 2.4 Mind the gates

If a task ends as `awaiting_approval`, **do not re-run it** — read the message first:

```bash
bacmap task show <task_id>
```

A contradictory interpretation fails the claims gate; unsigned mining artefacts fail the mining gate.
The latter is resolved with a signature:

```bash
bacmap task approve <task_id> --approver "Zhang San" --decision approve --signature "my passphrase"
```

---

## Chapter 3: "why should I trust this?" — the evidence chain

A colleague will ask: "Does this O3:K6 call really compare with last year's batch? Which database did
you use?" bacmap answers from records, not memory.

### 3.1 Run records: exactly how this result was produced

```bash
bacmap run ls
bacmap run show <run_id>
```

You get the workflow version (git commit, dirty flag), the **full resolved parameters and their hash**,
measured tool versions, database versions with checksums, input SHA256s, random seeds and host info.
The same content is written to `runs/<run_id>/run_manifest.json` with a SHA256 — so the on-disk and
in-database halves agree.

Two runs disagree? Let bacmap attribute it:

```bash
bacmap run compare <run_a> <run_b>
```

```
来源不同；变化类别：databases, tools
  [databases] card: 3.2.9 → 4.0.0
  [tools] gapit: 0.5.6 → 0.6.0
```

If provenance is identical but results differ, it says `NOT_REPRODUCIBLE` — time to look at randomness,
environment or hardware, not "run it again".

### 3.2 GOM: results are immutable

```bash
bacmap gom ls --type analysis
bacmap gom show <object_id>
```

Re-running a sample creates a **new version** instead of overwriting. `--version 1` still shows the
first one. That is what an audit needs.

### 3.3 Finding things

```bash
bacmap search --query "CTX-M"
bacmap search --st 19
bacmap search --serotype Typhimurium
```

---

## Chapter 4: let an agent do the typing (you still sign)

bacmap ships no chat UI. You talk in Hermes, Pi or DeepSeek Harness; they use bacmap over MCP.

### 4.1 Connect (Hermes shown)

```yaml
# ~/.hermes/config.yaml
mcp_servers:
  bacmap:
    command: /path/to/pixi/envs/default/bin/bacmap
    args: ["mcp"]          # add "--profile", "local-trusted" for local models
```

```bash
hermes mcp test bacmap
# ✓ Connected · 10 tools
```

Pi and DSH configuration is in the [agent harness guide](harnesses.md). In one sentence: Pi uses
`mcp.json`; DSH entries must be wrapped in `insert:`.

### 4.2 It looks first, then proposes

Say:

> "Look at the local V. parahaemolyticus samples, pick the HZCPE batch, and propose an analysis plan."

The agent calls `bacmap_capabilities` plus read tools and returns a **plan**:

```json
{
  "plan_id": "9a3f2c1b7d4e4f60",
  "version": 1,
  "state": "awaiting_confirmation",
  "tasks": [{"task_type": "analyze", "fasta_dir": "/data/run42", "species": "VPA"}],
  "plan_hash": "c1d2… (64 chars)"
}
```

Note `state`: **nothing ran**. The agent cannot confirm either — there is no confirmation tool in MCP.

### 4.3 You look, you sign

```bash
bacmap plan show 9a3f2c1b7d4e4f60
```

Full parameters, hash and input fingerprints are on screen. Then:

```bash
bacmap plan confirm 9a3f2c1b7d4e4f60 --version 1 --hash c1d2e3f4a5b6
```

Or interactively (`bacmap plan confirm <id>` shows the plan and asks y/N).

**Three guarantees:**

- editing parameters creates a new version; the old one is `superseded` immediately;
- if an input directory changed since the plan was created, confirmation fails with a conflict;
- repeated confirmation, or CLI and Web at the same time, submits the tasks exactly once.

The Web console does the same under **Plans** → full text → confirm or reject.

### 4.4 A wilder example: a mining plan

Ask the agent to summarise local ST distribution. It proposes a `mine` plan containing the **whole
script**:

```json
{
  "task_type": "mine",
  "objective": "ST distribution of local V. parahaemolyticus",
  "script": "import json, pathlib, collections\n...",
  "input_paths": ["/data/typing/st_table.csv"],
  "sandbox_image": "docker://python:3.12-slim"
}
```

`bacmap plan show` prints the script from top to bottom — **the full text is part of the hash**, so
what you read is what runs. Execution happens in a network-less sandbox with read-only mounts; the
artefacts then pass the mining gate and your signature.

No sandbox backend? The task says so instead of silently running bare:

```bash
which apptainer podman    # at least one
```

---

## Chapter 5: data is alive — metadata, lab results, literature

Results are half the story. The other half is where an isolate came from, what the clinic saw, and
which papers back it up.

### 5.1 Metadata

```bash
bacmap record metadata --strain-id HZCPE-01 \
  --field isolation_date=2026-10-12 \
  --field province=Guangdong \
  --field sample_source=food \
  --field food_category=seafood
```

That submits a `record` task; when it finishes, `bacmap task show <task_id>` reports
`recorded metadata for HZCPE-01`. Typos are rejected, not silently stored:

```
提交失败：invalid record: metadata.fields: unknown metadata field(s): ['sample_sorce']
```

### 5.2 A lab result

```bash
bacmap record lab --strain-id HZCPE-01 --category mic \
  --test-name meropenem --result 0.25 --unit mg/L \
  --interpretation S --standard CLSI-2026
```

### 5.3 Literature: stage, then approve

```bash
bacmap record knowledge-import --title "V. parahaemolyticus O3:K6 emergence" \
  --identifier PMID:12345678 --year 2025
# → staged knowledge entry 12 (awaiting approval)

bacmap record knowledge-approve 12
```

Why two steps? Because **the citation gate only honours approved entries**. An unapproved paper cannot
become evidence for a writing task — which keeps a model from citing something it never read.

The Web **Records** page offers the same three forms for colleagues who prefer clicking.

### 5.4 Build a local baseline release

With metadata in place, summarise the jurisdiction's strains:

```bash
bacmap task submit --type curate --scope '{"pathogen":"VPA"}'
```

Each strain is checked for a passing deterministic verification, acceptable QC, complete metadata and
duplicates. A failing strain is listed as excluded rather than crashing the task.

On success the task waits in `awaiting_approval` — **the release gate requires a human signature**:

```bash
bacmap task approve <task_id> --approver "Zhang San" --decision approve --signature "my passphrase"
# message: published baseline v3 (signed by Zhang San)
```

From that point, claims such as "first local appearance" or "same cluster as a 2025 outbreak strain"
can cite a baseline version.

---

## Chapter 6: the other two interfaces

### 6.1 Web: for colleagues

```bash
export BACMAP_WEB_TOKEN="$(openssl rand -hex 24)"
BACMAP_WEB_AUTH=cookie bacmap web
# bacmap web → http://127.0.0.1:8800/
```

Open `/login` and paste the token. The navigation is the workflow:

| Page | What you do there |
|---|---|
| **Tasks** | Submit analyze/curate, watch state badges, handle approvals |
| **Plans** | Review agent-proposed plans; confirm or reject |
| **Records** | Enter metadata, lab results, literature; approve entries |
| **Runs** | Inspect run records; compare two runs |
| **GOM** | Browse immutable objects and payloads |
| **Samples / Search** | Browse results, view HTML reports (inline, script-free) |

Remote access? **Do not open the port** — use an SSH tunnel:

```bash
ssh -L 8800:127.0.0.1:8800 you@workstation
```

### 6.2 TUI: a terminal task console

```bash
bacmap tui
```

No chat box (conversation lives in the harness), but enough for daily work: task/sample sidebar,
operation log, command input. `Ctrl+G` then `a` selects a task for signing, `Ctrl+Y` confirms (two
steps against mis-clicks); `/approve 3f9c1a2b "Zhang San"`, `/result HZCPE-01`, `/analyze HZCPE-01`.
Typing natural language points you at the harness — by design, not a bug.

### 6.3 Command-line cheat sheet

```bash
bacmap overview
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

## Chapter 7: when things go wrong

**"The task stays running."** `bacmap task show` first. If `step` sits at `pipeline`, the message
carries the tail of stderr. Did the machine reboot? DBOS resumes automatically; do not resubmit.

**"Sandbox unavailable."** Install Apptainer or Podman. Passthrough is for controlled development only.

**"The agent cannot see some tools."** That is the profile. The default `cloud` profile exposes D0–D1
tools only; for local/LAN models:

```toml
[mcp]
allow_local_trusted = true
```
```bash
bacmap mcp --profile local-trusted
```

**"Cloud reports a D3/D4 block."** That is the red line working. Use a local endpoint, or let the task
layer do the work (task data never leaves the network).

**"DSH shows no bacmap tools."** Check the patch is wrapped in `insert:` (a bare entry is treated as
editing an existing ID and skipped), then `dsh <profile> --dump-config | grep mcp-bacmap`.

**"Hermes says there are no credentials."** New builds use an isolated runtime that ignores environment
variables:

```bash
hermes auth add zai --type api-key --api-key "$ZAI_API_KEY"
hermes auth status zai
```

**"The report downloads instead of opening."** In the Web console it renders inline under a `sandbox`
CSP; `?download=1` downloads. On disk it is `results/<sample>/report/<sample>_report.html`.

---

## Chapter 8: backup, upgrade, rollback

Back up before upgrading — non-negotiable:

```bash
bacmap backup --out ~/backup/bacmap-$(date +%F).zip
```

The archive contains config, all SQLite databases (consistent snapshots) and run manifests.
`results/` is excluded unless you add `--with-results`.

Upgrade:

```bash
pixi install
bacmap doctor          # check the database version moved
```

Migrations are automatic: one transaction, a `<db>.bak-v<N>` copy first, full rollback on failure.
A database newer than the code is refused (that is protection when you downgrade).

Rollback means restoring the backup:

```bash
bacmap restore --from ~/backup/bacmap-2026-10-26.zip --home ~/.local/share/bacmap --force
```

Restore rejects path-traversal entries and runs an integrity check on every database. Event retention
is your policy:

```bash
bacmap events prune --days 180
```

---


## Chapter 9: traceback — from your local GOM to public genomes

Chapters 1–8 get results out. This chapter answers the harder question: **where did this isolate come
from, and what is it closest to?**

bacmap has two complementary traceback paths; do not confuse them:

| Path | Data source | Who computes | Answers |
|---|---|---|---|
| **A. Curated reference projection** | `data/reference/cgmlst/<scheme>/reference_profiles.tsv` (built by operations from public schemes such as EnteroBase, versioned) | `bio_cgmlst` (HierCC allele distance + per-species thresholds) | "Which reference is closest? Outbreak cluster or not?" |
| **B. Arbitrary public genomes** | Genomes you fetch from NCBI (or historical isolates) | Run them through the same pipeline, then mine distances across GOM | "What about GCF_… specifically?" |

Why doesn't B simply extend A's reference library? Because A's verdicts must be **reproducible**: the
library is versioned by operations, so every "first local appearance" claim can cite the library
version that produced it (`baseline_version`, `ref_databases`). Dropping a genome into the library
would silently change verdicts, so bacmap keeps the library stable and adds data instead.

### 9.1 Path A: one explainable cgMLST projection

First make sure the sample has a cgMLST profile (the analyze run produces it):

```bash
bacmap sample show HZCPE-01
```

The projection is a tool call. In Hermes/Pi/DSH just ask:

> "Use bio_cgmlst to find the nearest local references for HZCPE-01."

> Note: `bio_cgmlst` output is D2 (single-strain typing), so the default `cloud` profile hides it.
> With a local/LAN model, start `bacmap mcp --profile local-trusted`, or have an administrator raise
> `cloud_max_data_class` to D2. In-process calls below are not affected (they bypass MCP).

Or call the **same implementation** from a script (identical to MCP, no LLM involved):

```python
from bacmap.tools import registry

spec = registry.get("bio_cgmlst")
print(spec.legacy_handler({"sample_id": "HZCPE-01"}))
```

A result looks like:

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
  "caveats": ["V. parahaemolyticus has no published threshold; verdict=undetermined; local calibration required"]
}
```

How to read it:

- `distance` is **allele distance** (Hamming) with missing-on-either loci excluded — always check
  `n_comparable_loci`; if it is far below half the scheme, the verdict is weak;
- `verdict` is `outbreak` / `related` / `unrelated` / `undetermined` under the species thresholds.
  **No threshold means no verdict** — *V. parahaemolyticus* is exactly this case: you get distances and
  comparable loci, the verdict stays undetermined;
- `caveats` are not decoration. *S. sonnei* HC5/HC10 is unreliable, *V. parahaemolyticus* has no
  published boundary — bacmap says so instead of inventing a conclusion;
- thresholds live in `workflow/config/config.yaml` under `cgmlst.thresholds` (keyed by three-letter
  species code). Changing them is a methodological change: review it, do not tweak it ad hoc.

**Tie the evidence together.** The projection is not truth by itself; it points at the cgMLST profile
under a `run_id`:

```bash
bacmap run ls
bacmap run show <run_id>          # scheme, tool versions, input hashes
bacmap gom show <object_id>       # full allele profile
```

When a report says "same cluster as our 2025 O3:K6 strain", the footnote should carry the cgMLST
scheme, the `run_id`, the reference-library version, and — when a local baseline comparison is used —
the `baseline_version`.

### 9.2 Path B: invite public close relatives in

A reviewer asks: "What about NCBI's GCF_003045604.1?" Three steps.

**Step 1: see the manifest and the fetch command.** Ask the agent for
`bio_list_reference_genomes`, or run it yourself:

```python
from bacmap.tools import registry
print(registry.get("bio_list_reference_genomes").legacy_handler({}))
```

It returns cohort accessions, whether each is already present, and a copy-paste fetch command.
Fetching needs network (bacmap itself runs offline; you do this step):

```bash
cd "$BACMAP_HOME"
python workflows/bacmap/scripts/fetch_reference_genomes.py \
  --manifest workflows/bacmap/config/reference_accessions.yaml \
  --out-dir data/reference/genomes \
  --refs-dir refs --only VPA
```

Any accession (even outside the manifest) can come from the NCBI datasets CLI:

```bash
datasets download genome accession GCF_003045604.1 \
  --include genome --filename /tmp/gcf.zip
unzip -o /tmp/gcf.zip -d /tmp/gcf
# /tmp/gcf/ncbi_dataset/data/GCF_003045604.1/*.fna

# sample IDs come from the file name — rename first so long assembly names stay out of reports
mkdir -p /tmp/refs && cp /tmp/gcf/ncbi_dataset/data/GCF_003045604.1/*.fna \
  /tmp/refs/GCF_003045604.1.fna
```

**Step 2: run it through the same pipeline.** A public genome is not a second-class citizen — point
bacmap at the directory of assembled FASTAs:

```bash
bacmap task submit --type analyze \
  --fasta-dir /tmp/refs \
  --species VPA
```

The sample ID is the file name (which is why we renamed it), and it gets its own `run_id`, GOM objects
and report. **This is the key move**: from here on, the public strain and your local strains are the
same kind of thing, so comparing them means something.

**Step 3: compute distances.** The curated library did not change (see the note above), so use a
mining task to compare profiles inside GOM — that is the first code example in the next chapter.

### 9.3 A complete traceback narrative (report-ready)

1. `bio_cgmlst(HZCPE-01)` → nearest `VPA-2025-O3K6-07`, distance 12, `undetermined` (VPA has no
   published threshold), n=2680;
2. fetch and analyze `GCF_003045604.1`, yielding `run_id=R_pub`;
3. a mining task computes distances between `HZCPE-01` and every VPA cgMLST profile (including the
   public strain), writes `distances.csv`, and you sign it;
4. the report states: "allele distance 12 to our 2025 O3:K6 strain (undetermined — VPA has no
   published threshold); distance 27 to public reference GCF_003045604.1", with scheme, `run_id`,
   threshold source (or an explicit "no threshold") and the mining artefact hash.

Nothing in that chain is "the model thought it looked similar". Every step can be recomputed.

---

## Chapter 10: data mining — write code you can sign

Mining (`mine`) is L2: **the script runs in a sandbox, its output is exploratory, and it enters a
report only after your signature**. It is not "run whatever"; it is reproducible exploration.

### 10.1 The contract your script gets

At run time the workspace contains `context.json`:

```json
{
  "backend": "podman",
  "results_dir": "/data/results",
  "gom_db": "/data/gom.sqlite",
  "datasets": {"ds-3f9c1a2b": "/input/ds-3f9c1a2b"}
}
```

Rules:

- `datasets` is an **object (id → path)**, not an array — the most common first-timer mistake;
- with a container backend these are guest paths (`/data/...`, `/input/...`); passthrough (development)
  exposes host paths;
- inputs are read-only, the network is off, and **the sandbox has no pandas/numpy** unless you supply
  an image that contains them (`sandbox_image`). All examples below use the standard library.

### 10.2 Example A: a cgMLST distance matrix (GOM → CSV)

Goal: compute pairwise distances between all *V. parahaemolyticus* cgMLST profiles in GOM and find the
nearest neighbours of one query sample.

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
    if len(alleles) >= p.get("n_total", 0) * 0.5:      # too many missing loci -> skip
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

Submit it — preferably as a plan (the harness proposes it, you review the full script), or through the
Python API for automation:

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

When it finishes:

```bash
bacmap task show <task_id>       # awaiting_approval (mining gate)
bacmap task approve <task_id> --approver "Zhang San" --decision approve --signature "my passphrase"
```

Artefacts land in `workspaces/<task_id>/` (`distances.csv`, `nearest.csv`). **Until signed they are
exploratory only** and cannot enter a report; the signature itself is recorded in the approvals table
and GOM events.

### 10.3 Example B: join epidemiology metadata

The sandbox cannot read `data/bacmap.sqlite` (metadata is D4). The correct pattern is to **register an
export as an input**:

```bash
bacmap record metadata --strain-id HZCPE-01 --field isolation_date=2026-10-12 --field province=Guangdong
```

Export `meta.csv` from your LIMS (columns: sample, isolation_date, province, source). Also hand the
`nearest.csv` from example A to this task — **a new task starts with a clean workspace**, so never
assume the previous task's artefacts are still there:

```python
tid = engine.submit(
    TaskType.MINE,
    {
        "objective": "join cgMLST nearest neighbours with epidemiology metadata",
        "script": Path("mining_join.py").read_text(),
        "input_paths": [
            "/data/exports/meta.csv",
            "/data/exports/nearest.csv",   # example A's output, copied into the input directory
        ],
        "input_data_class": "D4",
        "sandbox_image": "docker://python:3.12-slim",
    },
    "cli:analyst",
)
```

Inside the script, **do not guess a dataset_id** — identify the two inputs by header:

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

Note `input_data_class: "D4"`: once labelled D4, the data is under the strictest handling (never sent to
a cloud endpoint, read-only mount). If your export is de-identified aggregates, `D2`/`D3` expresses the
least privilege.

### 10.4 Example C: promote exploration into the standard path

A mining script that keeps being useful should not stay in L2 forever. Promotion means:

1. write tests and documentation (inputs, thresholds, output contract);
2. implement it as a `ToolSpec` (read/compute) or a Snakemake rule (L1);
3. regress it against the 12-strain gold standard and confirm it matches the exploration;
4. record the promotion in GOM events (who, when, original script hash).

Only then does it belong in the standard section of a report rather than an exploratory appendix.

### 10.5 Mining boundaries (take them seriously)

- no network inside the sandbox; do not try to download references from a script;
- inputs are read-only, artefacts only in the workspace;
- mining output **never** enters authoritative result tables;
- any "skip the sandbox" switch (`BACMAP_ALLOW_UNSANDBOXED`) is for controlled development only;
- your signature is about **this artefact**, not about what a model said — open the CSV before signing.


## Epilogue: what this workflow actually protects

Back to Friday's email. What you send is more than an HTML file:

- every isolate has a **run record** (parameters, database versions, input hashes, seeds);
- every claim traces to a **run_id**, and re-runs never overwrite old versions;
- a baseline release carries a **signature** — who approved it, and when, is on record;
- agent-proposed plans execute only after **you have read the full text**;
- data classification is enforced in the tool belt, MCP profiles and endpoints at once.

Six months from now, when someone asks "how was that O3:K6 batch called?", open `bacmap run show` and
answer in thirty seconds.

That is what bacmap is for.

---

**Read next**

- Command details: [usage guide](usage.md)
- Client setup: [agent harness guide](harnesses.md)
- Operations and upgrades: [operations guide](operations.md)
- Install troubleshooting: [installation guide](installation.md) · [configuration guide](configuration.md)
