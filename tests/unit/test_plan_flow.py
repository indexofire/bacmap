"""计划流程图 SVG 渲染测试（PLAN #3）。"""

from __future__ import annotations

from bacmap.research.plan_flow import _task_summary, render_plan_svg
from bacmap.tasks.params import AnalyzeParams, MineParams, ResearchParams


class TestRenderPlanSvg:
    def _tasks(self):
        return [
            AnalyzeParams(fasta_dir="/data/run42", species="VPA"),
            MineParams(objective="count AMR genes", script="print(1)"),
            ResearchParams(
                analysis="advstats", method="cox",
                data_path="/abs/d.csv", time="t", event="e", predictors=["x"],
            ),
        ]

    def test_svg_well_formed(self):
        svg = render_plan_svg(self._tasks(), "abc123", "awaiting_confirmation")
        assert svg.startswith("<svg")
        assert svg.rstrip().endswith("</svg>")
        assert "analyze" in svg and "mine" in svg and "research" in svg
        assert "abc123" in svg
        assert "awaiting_confirmation" in svg

    def test_svg_deterministic(self):
        tasks = self._tasks()
        assert render_plan_svg(tasks, "p1", "draft") == render_plan_svg(tasks, "p1", "draft")

    def test_empty_tasks(self):
        svg = render_plan_svg([], "p0", "empty")
        assert svg.startswith("<svg")

    def test_task_summaries(self):
        assert "fasta" in _task_summary(AnalyzeParams(fasta_dir="/data/x", species="VPA"))
        assert "mine" in _task_summary(MineParams(objective="test", script="p"))
        assert "advstats" in _task_summary(
            ResearchParams(
                analysis="advstats", method="cox",
                data_path="/d.csv", time="t", event="e", predictors=["x"],
            )
        )

    def test_arrows_present(self):
        svg = render_plan_svg(self._tasks(), "p", "")
        assert 'marker-end="url(#arrow)"' in svg
