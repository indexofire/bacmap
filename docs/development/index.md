# Development

This page is for people changing bacmap itself. The golden rules are in `AGENTS.md`; this is the
practical workflow.

## 1. Environment

```bash
pixi install          # runtime environment
pixi install -e dev   # tests/lint/mypy/contracts/docs
pixi shell
```

Never use the system Python for tests: `pixi run -e dev test` (without `-e dev`, pytest may fall
back to a Python without DBOS).

```bash
pixi run -e dev test          # pytest; current baseline 1610 passed
pixi run -e dev lint          # ruff (src + tests)
pixi run -e dev typecheck     # mypy on src/bacmap
pixi run -e dev contracts     # import-linter (5 contracts)
pixi run -e dev docs-build    # mkdocs (English + Chinese)
```

All five must be green before a change is considered done. CI runs the same order.

## 2. Dependency direction

```text
core ← store ← tools ← workflow ← tasks ← application ← interfaces
```

Hard rules:

- `core`, `store`, `tools` may not import `agent`, `tasks`, `interfaces`, `workflow`.
- DBOS only in `tasks.engine`.
- MCP SDK only in `interfaces.mcp`, `store.knowledge`, `agent.llm`.
- pydantic-ai only in `agent.llm`.

Run `pixi run -e dev contracts` after touching imports. `tests/unit/test_import_boundaries.py`
also enforces the rules.

## 3. Adding a task type

1. Add the value to `TaskType` in `tasks/spec.py`.
2. Define a params model in `tasks/params.py` (plannable) or `tasks/records.py` (record).
3. Add a `@DBOS.workflow()` and `@DBOS.step()` in `tasks/engine/dbos_engine.py`; register it in
   `TaskEngine.submit` and the approval finalizer map if it needs a signature.
4. Add gates if the outcome is a claim (`tasks/gates.py`).
5. Expose it through the intended interface (plan model, CLI, Web, MCP); never add a direct store
   write.
6. Add tests for success, failure, gate rejection, recovery/idempotency and redaction.
7. Document it in this site (guide + reference) and add a frozen-doc revision if a frozen decision
   changes.

## 4. Adding a pipeline capability

Genome-only analysis belongs in an external tool (ADR-20), not in bacmap:

1. Implement/validate it in `gside`/`gapit`/`gmlst`.
2. Add an `.smk` rule + adapter/parser under `workflow/`.
3. Extend the summary schema and ingest if the result is evidence.
4. Add fixtures/gold-standard comparisons.
5. Bump the deployed workflow hash automatically via content; no manual step.
6. Update docs and evidence.

## 5. Adding a tool

1. Add a JSON schema in `tools/schemas.py`.
2. Implement the handler with `@tool_handler` (errors become `{"error": "<type>"}`).
3. Register it in `tools/registry.py` with `effect`, `trust_layer` and `output_data_class`.
   Write tools must not be registered into MCP directly.
4. Add tests for happy path, invalid input and data-class behaviour.
5. Update [Tool registry](../reference/tools.md) and the MCP docs if visibility changes.

```python
# tools/schemas.py
MY_TOOL = {
    "name": "bio_my_tool",
    "description": "...",
    "parameters": {"type": "object", "properties": {...}, "required": [...]},
}

# tools/registry.py
("bio_my_tool", schemas.MY_TOOL, my_module.my_tool),
"bio_my_tool": (TrustLayer.L2, Effect.COMPUTE, DataClass.D3, False),
```

## 6. Database changes

- Add a numbered migration; never edit a published one.
- Baseline migrations use `CREATE TABLE IF NOT EXISTS` for legacy adoption.
- Run migrations in one `BEGIN IMMEDIATE`; backup first (the helper does this).
- Add a test that opens an old schema and migrates it.
- Update the storage/data-model docs and backup notes.

## 7. Tests and fixtures

```text
tests/unit/        fast, deterministic; mock external binaries/DBOS (the current suite)
tests/fixtures/    gold-standard data and sample summaries
dev/               local-only research notes/scripts (not committed)
```

Guidelines:

- Do not delete tests for retained functionality to make a change pass.
- For a behavior change, first add a failing test that expresses the new contract.
- Use `monkeypatch` for paths/DBOS/network; never touch the real `BACMAP_HOME`.
- Keep tests independent; DBOS tests must call `shutdown_dbos()` in teardown.
- Update the baseline in `AGENTS.md`, the frozen revision and CHANGELOG only for legitimate
  functional deletions, with the reason recorded.

## 8. Documentation

- English is the default; Chinese is `*.zh.md` (same directory, same relative links).
- The site uses `mkdocs-static-i18n`: English at `/`, Chinese at `/zh/`.
- Add a page to `mkdocs.yml` nav and translate the label in `nav_translations`.
- Use relative `.md` links; the build is checked with `mkdocs build --strict`.
- For frozen decisions, add a `v1.9.x` revision row (reason, evidence, migration cost) and a
  matching `dev/research-framework-evidence.md` section.
- Run `pixi run -e dev docs-build` before committing.

## 9. Versioning

- Program version: `pyproject.toml` / `pixi.toml` (currently 0.1.2), changed only by explicit
  release decision.
- Frozen design revision: the title and revision table in
  `docs/concepts/frozen-design.zh.md` (v1.9.3), independent of the program version.
- Test baseline: `AGENTS.md` rule 7 (currently 1610).

## 10. Commit checklist

```bash
pixi run -e dev test
pixi run -e dev lint
pixi run -e dev typecheck
pixi run -e dev contracts
pixi run -e dev docs-build
git status --short
```

Do not commit secrets (`BACMAP_*_TOKEN`, API keys), `dev/` research notes, `site/`, or generated
caches.
