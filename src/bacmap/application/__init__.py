"""应用服务层（v1.5）：CLI / Web / MCP 共享的业务用例。

依赖方向（ADR-02，import-linter 强制）：可依赖 core/store/tools/tasks；不得导入接口层；
计划与任务服务不得导入 ``bacmap.agent``（保 C3：无 LLM 时计划闭环可用）。
"""
