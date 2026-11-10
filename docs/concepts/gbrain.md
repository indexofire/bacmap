# GBrain: long-term knowledge base and knowledge graph (PLAN #8)

> Status: design proposal (2026-11-09), awaiting user confirmation before implementation.

## Positioning

GBrain is bacmap's **knowledge layer** — not conversational memory, but
structured knowledge that has passed human review. Two cores:

1. **Long-term knowledge base** (existing foundation): literature / guideline /
   experience entries, stored after citation-gate review
2. **Knowledge graph** (existing foundation): the strain–gene–phenotype–literature
   relation network

```
┌──────────────────────────────────────────────────────────┐
│                    GBrain knowledge layer                 │
│                                                           │
│  ┌─────────────────┐       ┌─────────────────────────┐  │
│  │  knowledge base  │       │  knowledge graph        │  │
│  │  (knowledge.     │       │  (GOM + evidence_edges) │  │
│  │   sqlite)        │       │                          │  │
│  │                  │       │                          │  │
│  │  · literature    │ ←──→  │  · strain→gene→phenotype │  │
│  │  · guidelines    │       │  · strain→run→results    │  │
│  │  · experience    │       │  · study→claim→evidence  │  │
│  │  · citations     │       │  · analysis→literature   │  │
│  └─────────────────┘       └─────────────────────────┘  │
│                                                           │
│  Unified query interface: bacmap knowledge search + MCP  │
└──────────────────────────────────────────────────────────┘
```

## Existing foundation (0.1.3)

| Component | Status | GBrain direction |
|---|---|---|
| `knowledge.sqlite` | Literature entries + citation gate | Add: guidelines, experience rules, auto-summaries |
| `evidence_edges` | Research-object relations (cohort/plan/claim/experiment) | Add: gene–phenotype–literature edges |
| `GOM genome_objects` | Strain analysis results (incl. summary) | Add: cross-sample knowledge extraction (e.g. "common AMR genes for this species") |
| `bio_search_samples` | Search samples by feature | Add: semantic knowledge search ("which strains are blaKPC-positive and studied?") |
| MCP `skill://` resources | Role manuals | Add: GBrain fact sources (knowledge agents can query) |

## New capabilities (design)

### 1. Extended knowledge entries

The existing knowledge.sqlite stores only literature. Extend to multiple types:

```yaml
# Knowledge entry types
- literature:     # literature (existing)
    title, authors, year, doi, abstract, full_text_hash
- guideline:      # operating guideline (new)
    topic, content, source, reviewed_by
- experience:     # experience rule (new, distilled from mine results)
    rule, evidence_ids, confidence, created_by
- summary:        # auto-summary (new, agent-generated + human review)
    topic, content, source_ids, generated_by, reviewed_by
```

### 2. Semantic query interface

```bash
# CLI
bacmap knowledge search "blaKPC resistance mechanism"
bacmap knowledge related --gene blaKPC          # strains/phenotypes/literature linked to the gene
bacmap knowledge graph --study <id> --depth 2   # visualise the knowledge graph

# MCP (agent-callable)
bacmap_knowledge_search(query)                   # semantic search
bacmap_knowledge_graph(entity, depth)            # graph traversal
```

### 3. Agent knowledge injection

Agents automatically query GBrain for context while interpreting:

```python
# inside agent/interpret.py
knowledge = gbrain.query(f"{species} {gene} resistance mechanism")
# → reviewed knowledge entries + related local data
```

### 4. Automatic knowledge accumulation

```
mine sandbox output → agent distils experience rules → human review → knowledge.sqlite
analysis reports → agent generates summary → human review → knowledge.sqlite
```

## Difference from external memory systems

| | GBrain | External memory (e.g. Mem0/Zep) |
|---|---|---|
| Data | Structured, human-reviewed | Unstructured, auto-extracted |
| Storage | Local SQLite (data stays offline) | Usually cloud |
| Query | SQL + semantic search | Vector search |
| Trust | Citation gate + review signature | Automatic (no review) |
| Role | bacmap's knowledge infrastructure | Agent session memory |

GBrain does **not** replace external memory — it is bacmap's **domain knowledge
base**, independent of any harness or agent. Agent session memory is managed by
the harness itself.

## Implementation priority

1. `knowledge.sqlite` entry types (guideline/experience/summary) — migration + models
2. `bacmap knowledge search/related/graph` CLI
3. MCP `bacmap_knowledge_search` tool (D2, read-only)
4. Agent knowledge injection (`agent/interpret.py` queries GBrain)
5. Knowledge-graph visualisation (web frontend, Vue3 + D3.js force graph)
