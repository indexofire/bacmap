"""Web 控制台对话层（AG-UI 协议模型、配置、编排）。

本包**不得**导入 pydantic_ai/openai/dbos/mcp（ADR-02）——内置 LLM 后端
实现位于 ``bacmap.agent.llm.chat``，经 ``ChatBackend`` 协议注入。
"""
