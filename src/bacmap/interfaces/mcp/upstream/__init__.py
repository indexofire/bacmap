"""上游 MCP 适配器（每种宿主/服务一个薄适配器，禁止互相 import）。

- ``gaxis``：把本地 gaxis MCP 服务（图表复现/知识库）暴露为 ``bacmap_chart_*`` 工具。
  按 Profile 的数据级别上限在**注册期**与**调用期**双重裁剪，fail-closed。
"""
