# 开发

本页面向修改 bacmap 本身的人。黄金规则见 `AGENTS.md`；这里讲实际工作流。

## 1. 环境

```bash
pixi install          # 运行时环境
pixi install -e dev   # tests/lint/mypy/contracts/docs
pixi shell
```

绝不要用系统 Python 跑测试：`pixi run -e dev test`（不带 `-e dev` 时，pytest 可能
回退到没有 DBOS 的 Python）。

```bash
pixi run -e dev test          # pytest；当前基线 1610 passed
pixi run -e dev lint          # ruff（src + tests）
pixi run -e dev typecheck     # 对 src/bacmap 跑 mypy
pixi run -e dev contracts     # import-linter（5 条契约）
pixi run -e dev docs-build    # mkdocs（英文 + 中文）
```

五项全部通过，改动才算完成。CI 按相同顺序执行。

## 2. 依赖方向

```text
core ← store ← tools ← workflow ← tasks ← application ← interfaces
```

硬性规则：

- `core`、`store`、`tools` 不得导入 `agent`、`tasks`、`interfaces`、`workflow`。
- DBOS 只在 `tasks.engine`。
- MCP SDK 只在 `interfaces.mcp`、`store.knowledge`、`agent.llm`。
- pydantic-ai 只在 `agent.llm`。

改动 imports 后运行 `pixi run -e dev contracts`。`tests/unit/test_import_boundaries.py`
也会强制这些规则。

## 3. 新增任务类型

1. 在 `tasks/spec.py` 的 `TaskType` 中添加该值。
2. 在 `tasks/params.py`（可计划）或 `tasks/records.py`（记录）中定义参数模型。
3. 在 `tasks/engine/dbos_engine.py` 中添加 `@DBOS.workflow()` 与 `@DBOS.step()`；在
   `TaskEngine.submit` 与审批终结器映射中注册（若需要签名）。
4. 若产出是主张，添加门（`tasks/gates.py`）。
5. 通过预定接口暴露它（计划模型、CLI、Web、MCP）；绝不添加直接写 store 的路径。
6. 为成功、失败、门拒绝、恢复/幂等与脱敏添加测试。
7. 在本文档站中记录（指南 + 参考）；若冻结决策发生变化，添加冻结文档修订记录。

## 4. 新增流水线能力

仅依赖基因组的分析属于外部工具（ADR-20），不属于 bacmap：

1. 在 `gside`/`gapit`/`gmlst` 中实现/验证。
2. 在 `workflow/` 下添加 `.smk` 规则与适配器/解析器。
3. 若结果是证据，扩展摘要 schema 并入库。
4. 添加测试夹具/金标准比较。
5. 通过内容自动更新已部署工作流的哈希；无需手工步骤。
6. 更新文档与证据。

## 5. 新增工具

1. 在 `tools/schemas.py` 中添加 JSON schema。
2. 用 `@tool_handler` 实现处理器（错误会变成 `{"error": "<type>"}`）。
3. 在 `tools/registry.py` 中注册，并标明 `effect`、`trust_layer` 与 `output_data_class`。
   写工具不得直接注册进 MCP。
4. 为正常路径、无效输入与数据分级行为添加测试。
5. 更新[工具注册表](../reference/tools.zh.md)；若可见性变化，也更新 MCP 文档。

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

## 6. 数据库变更

- 添加编号迁移；绝不修改已发布的迁移。
- 基线迁移对遗留采纳使用 `CREATE TABLE IF NOT EXISTS`。
- 在一个 `BEGIN IMMEDIATE` 中运行迁移；先备份（辅助函数会处理）。
- 添加一个打开旧 schema 并执行迁移的测试。
- 更新存储/数据模型文档与备份说明。

## 7. 测试与夹具

```text
tests/unit/        快速、确定性；mock 外部二进制/DBOS（当前测试套件）
tests/fixtures/    金标准数据与样本摘要
dev/               仅本地的调研笔记/脚本（不入库）
```

准则：

- 不要为了让改动通过而删除保留功能的测试。
- 对于行为变更，先添加一个表达新契约的失败测试。
- 路径/DBOS/网络使用 `monkeypatch`；绝不触碰真实的 `BACMAP_HOME`。
- 保持测试相互独立；DBOS 测试必须在 teardown 中调用 `shutdown_dbos()`。
- 仅对合法的功能删除更新 `AGENTS.md`、冻结修订与 CHANGELOG 中的基线，并记录原因。

## 8. 文档

- 英文为默认；中文为 `*.zh.md`（同目录，相同相对链接）。
- 站点使用 `mkdocs-static-i18n`：英文位于 `/`，中文位于 `/zh/`。
- 在 `mkdocs.yml` 的 nav 中添加页面，并在 `nav_translations` 中翻译标签。
- 使用相对的 `.md` 链接；构建以 `mkdocs build --strict` 检查。
- 对于冻结决策，添加一行 `v1.9.x` 修订记录（原因、证据、迁移成本），并在
  `dev/research-framework-evidence.md` 中添加对应小节。
- 提交前运行 `pixi run -e dev docs-build`。

## 9. 版本管理

- 程序版本：`pyproject.toml` / `pixi.toml`（当前 0.1.2），仅在明确发布决定后更改。
- 冻结设计修订：`docs/concepts/frozen-design.zh.md` 中的标题与修订表（v1.9.3），
  独立于程序版本。
- 测试基线：`AGENTS.md` 规则 7（当前 1610）。

## 10. 提交清单

```bash
pixi run -e dev test
pixi run -e dev lint
pixi run -e dev typecheck
pixi run -e dev contracts
pixi run -e dev docs-build
git status --short
```

不要提交密钥（`BACMAP_*_TOKEN`、API 密钥）、`dev/` 调研笔记、`site/` 或生成的
缓存。
