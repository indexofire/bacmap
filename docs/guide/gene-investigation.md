# Gene-investigation orchestration (PLAN #14)

> Status: design proposal (2026-11-09), awaiting user confirmation before implementation.

## Scenario

The user names a gene / phenotype / area of interest (e.g. "blaKPC" or
"carbapenem resistance") and the system completes an end-to-end investigation
automatically:

```
User: "investigate the local distribution and resistance association of blaKPC"
  ↓
┌────────────────────────────────────────────────────────┐
│ Orchestration engine (bacmap research chain)            │
│                                                         │
│  ① Local search     bio_search_samples --gene blaKPC   │
│  ② Association      research create --gene blaKPC      │
│                    --test-name meropenem                │
│  ③ Deep mining      mine (custom statistics/figures)    │
│  ④ Literature       agent (external harness) search     │
│                    + synthesis                          │
│  ⑤ Report           research session → figure → report  │
│  ⑥ Knowledge        result summary → GBrain (after      │
│                    human review)                        │
└────────────────────────────────────────────────────────┘
  ↓
Returns: structured report (local data + literature review + figures + knowledge graph)
```

## Orchestration design

### Entry point: `bacmap research investigate`

```bash
# One command starts the full investigation
bacmap research investigate --gene blaKPC --test-name meropenem \
  [--run-id <restrict to one run>] [--auto] [--json]

# Or via MCP (agent-invoked)
bacmap_research_investigate(gene="blaKPC", test_name="meropenem", auto=False)
```

### Step breakdown

| Step | Engine | Human confirmation | Output |
|---|---|---|---|
| ① Local search | Deterministic (`bio_search_samples`) | No | List of gene-positive strains |
| ② Association analysis | Deterministic (`research create`, P1 chain) | No (read-only) | 2×2 table, OR/CI/p, figure spec |
| ③ Deep mining | `mine` plan (agent script) | **Yes** (script review + mining-gate signature) | Custom statistics/figures |
| ④ Literature review | External agent (harness searches itself) | Agent's own judgement | Literature digest (citing the local knowledge base) |
| ⑤ Report generation | Deterministic (session artefacts) | No | report.md + figure.svg + manuscript.md |
| ⑥ Knowledge accumulation | Agent writes summary → human review | **Yes** (knowledge gate) | GBrain knowledge entry |

### Key design decisions

1. **①②⑤ are deterministic** — no plan confirmation needed; executed directly (read-only + P1 thin chain)
2. **③ needs plan confirmation** — mine is an open path; scripts must be human-reviewed
3. **④ happens in the external harness** — bacmap does not search the network (ADR-16 red line)
4. **⑥ needs human review** — knowledge ingestion must pass the knowledge gate

### Automation level

```toml
# config.toml
[research.investigate]
# auto = true: ①②⑤ run automatically; ③⑥ still need human confirmation
# auto = false: every step needs confirmation
auto = false
```

## Realisation

### Phase 1: deterministic chain (①②⑤)

A new `research investigate` command — chains existing functionality:

```python
# research/investigate.py
def investigate(home, gene, test_name, run_id=None, auto=False):
    # ① search
    samples = bio_search_samples(gene=gene)
    # ② association analysis
    session = research_create(run_id=run_id, gene=gene, test_name=test_name)
    # ⑤ report
    report = session.artifacts.report
    figure = session.artifacts.figure
    return {"samples": samples, "session": session, "report": report, "figure": figure}
```

### Phase 2: mine integration (③)

The agent proposes a mine plan via MCP (the deep-mining part of the
investigation); a human confirms before execution.

### Phase 3: literature-review integration (④)

The agent searches literature in the harness (external tools); results flow back
into the bacmap knowledge base as a `record knowledge-import` task (citation-gate
review).

### Phase 4: knowledge accumulation (⑥)

After the investigation, the agent generates a summary →
`bacmap record knowledge-import` → human review.

## Example output

```json
{
  "investigation_id": "inv-a1b2c3d4",
  "gene": "blaKPC",
  "test_name": "meropenem",
  "steps": {
    "search": {"n_positives": 12, "n_total": 156, "samples": []},
    "association": {"session_id": "rs-xxx", "odds_ratio": 25.3, "p_value": 0.001},
    "mining": {"task_id": "mine-xxx", "status": "awaiting_approval"},
    "literature": {"status": "delegated_to_harness"},
    "report": {"path": "research/rs-xxx/report.md"},
    "knowledge": {"status": "pending_review"}
  }
}
```

## Implementation priority

1. `research investigate` command (deterministic chain ①②⑤)
2. MCP `bacmap_research_investigate` tool
3. Automatic mine-plan proposal (agent proposes mining directions from investigation results)
4. Literature-review write-back (`record knowledge-import`)
