"""中文监测报告渲染（研究编排层 ``text.report`` 算子，P1 最小版）。

设计约束（见 ``dev/PLAN-research-orchestration.md`` §8）：

- 正文中的每个数值都来自槽位（``slots``），模板不做自由发挥；
- 返回值同时给出 ``slots`` 与 ``claims``（含证据 artifact id），供后续
  数字审计门与证据绑定使用；
- 阴性结果（无关联）与零单元格必须如实呈现，不得省略。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from bacmap.research.models import StatResult


def _fmt(value: float | None, digits: int = 2) -> str:
    if value is None:
        return "无法估计"
    return f"{value:.{digits}f}"


def _fmt_p(value: float | None) -> str:
    if value is None:
        return "无法估计"
    if value < 0.001:
        return "<0.001"
    return f"{value:.3f}"


def _verdict(stat: StatResult) -> str:
    if stat.odds_ratio is None or stat.p_value is None:
        return "数据不足以估计关联（存在零单元格或有效样本不足）"
    if stat.p_value < 0.05:
        if stat.odds_ratio > 1:
            return "阳性与耐药表型呈统计学显著正关联"
        return "阳性与耐药表型呈统计学显著负关联"
    return "未发现统计学显著关联"


def build_slots(
    *, run_id: str, gene: str, drug: str, stat: StatResult, generated_at: str
) -> dict[str, Any]:
    table = dict(stat.table)
    a = int(table.get("gene_pos_resistant", 0))
    b = int(table.get("gene_pos_susceptible", 0))
    c = int(table.get("gene_neg_resistant", 0))
    d = int(table.get("gene_neg_susceptible", 0))
    return {
        "run_id": run_id,
        "gene": gene,
        "drug": drug,
        "generated_at": generated_at,
        "n": stat.n,
        "a": a,
        "b": b,
        "c": c,
        "d": d,
        "gene_pos": a + b,
        "gene_neg": c + d,
        "resistant": a + c,
        "susceptible": b + d,
        "or": _fmt(stat.odds_ratio),
        "ci_low": _fmt(stat.ci_low),
        "ci_high": _fmt(stat.ci_high),
        "p": _fmt_p(stat.p_value),
        "verdict": _verdict(stat),
        "diagnostics": list(stat.diagnostics),
    }


def render_surveillance_report(
    *,
    run_id: str,
    gene: str,
    drug: str,
    stat: StatResult,
    table_artifact: str,
    figure_artifact: str = "",
    generated_at: str | None = None,
) -> dict[str, Any]:
    """渲染中文监测报告；返回 markdown + 槽位 + claims（证据绑定）。"""
    stamp = generated_at or datetime.now(UTC).isoformat(timespec="seconds")
    s = build_slots(run_id=run_id, gene=gene, drug=drug, stat=stat, generated_at=stamp)

    diagnostics = s["diagnostics"]
    diagnostics_md = (
        "\n".join(f"- {item}" for item in diagnostics) if diagnostics else "- 无"
    )
    figure_md = (
        f"\n![森林图]({figure_artifact})\n" if figure_artifact else "\n（未附森林图）\n"
    )

    markdown = f"""# {s["gene"]} 与 {s["drug"]} 耐药关联分析报告

| 项目 | 内容 |
|---|---|
| 数据来源 | run `{s["run_id"]}` |
| 数据级别 | D2（菌株分型结果） |
| 生成时间 | {s["generated_at"]} |
| 分析方法 | 2×2 列联表 + Woolf 95% 置信区间 |

## 摘要

在纳入分析的 **{s["n"]} 株**菌株中，{s["gene"]} 阳性 {s["gene_pos"]} 株、
阴性 {s["gene_neg"]} 株；{s["drug"]} 耐药 {s["resistant"]} 株、敏感 {s["susceptible"]} 株。

携带 {s["gene"]} 的菌株对 {s["drug"]} 耐药的比值比为 **{s["or"]}**
（95% CI {s["ci_low"]}–{s["ci_high"]}，p={s["p"]}）。{s["verdict"]}。

## 1 材料与方法

### 1.1 数据来源

本报告使用 bacmap 运行记录 `{s["run_id"]}` 的菌株集合；基因存在性来自本地
AMR 基因筛查结果，表型来自本地药敏记录。仅纳入基因与表型均可用的菌株。

### 1.2 统计方法

构建「基因存在 × 表型耐药」2×2 列联表（a={s["a"]}，b={s["b"]}，c={s["c"]}，d={s["d"]}），
估计比值比及其 95% 置信区间；零单元格按 Haldane–Anscombe 0.5 校正。
显著性水平取 α=0.05，未做多重比较校正（单假设）。

## 2 结果

表 1　基因存在性与耐药表型交叉表

| | {s["drug"]} 耐药 | {s["drug"]} 敏感 | 合计 |
|---|---:|---:|---:|
| {s["gene"]} 阳性 | {s["a"]} | {s["b"]} | {s["gene_pos"]} |
| {s["gene"]} 阴性 | {s["c"]} | {s["d"]} | {s["gene_neg"]} |
| 合计 | {s["resistant"]} | {s["susceptible"]} | {s["n"]} |
{figure_md}
## 3 讨论

{s["verdict"]}。关联强度以 OR={s["or"]} 表示；置信区间跨越 1 时提示关联不确定，
应结合样本量、克隆结构（同一克隆株重复计数会高估关联）与耐药机制解释。

## 4 局限

- 本分析为横断面关联，不能推断因果关系。
- 菌株间亲缘关系未校正；同一暴发克隆可能造成非独立观测。
- 基因存在性不等于基因表达；表型判读依赖本地药敏方法与折点。

## 附录 A　诊断信息

{diagnostics_md}

## 附录 B　证据与复现

- 统计结果产物：`{table_artifact}`
- 图产物：`{figure_artifact or "无"}`
- 由 bacmap 研究编排层自动生成；数字均由产物槽位解析，未经语言模型改写。

"""

    claims = [
        {
            "claim_type": "observation",
            "wording": f"纳入 {s['n']} 株菌株完成基因-表型关联分析",
            "evidence": [table_artifact],
        },
        {
            "claim_type": "association",
            "wording": (
                f"{s['gene']} 与 {s['drug']} 耐药的 OR={s['or']}"
                f"（95% CI {s['ci_low']}–{s['ci_high']}，p={s['p']}）"
            ),
            "evidence": [table_artifact],
        },
        {
            "claim_type": "association",
            "wording": str(s["verdict"]),
            "evidence": [table_artifact],
        },
    ]
    return {"markdown": markdown, "slots": s, "claims": claims}


# ---------------------------------------------------------------------------
# 英文 IMRAD 稿（P5）：与中文报告共用槽位与审计门
# ---------------------------------------------------------------------------


def _verdict_en(stat: StatResult) -> str:
    if stat.odds_ratio is None or stat.p_value is None:
        return "the data were insufficient to estimate an association"
    if stat.p_value < 0.05:
        if stat.odds_ratio > 1:
            return "carriage was significantly associated with resistance"
        return "carriage was significantly associated with susceptibility"
    return "no statistically significant association was observed"


def render_imrad_manuscript(
    *,
    run_id: str,
    gene: str,
    drug: str,
    stat: StatResult,
    table_artifact: str,
    figure_artifact: str = "",
    title: str = "",
    generated_at: str | None = None,
) -> dict[str, Any]:
    """IMRAD 稿（英文）；数字全部来自槽位，不含文献引用。"""
    stamp = generated_at or datetime.now(UTC).isoformat(timespec="seconds")
    s = build_slots(run_id=run_id, gene=gene, drug=drug, stat=stat, generated_at=stamp)
    verdict_en = _verdict_en(stat)
    p_is_sig = stat.p_value is not None and stat.p_value < 0.05
    manuscript_title = title or (
        f"Association between {gene} carriage and {drug} resistance "
        f"in a routine surveillance batch"
    )
    diagnostics = s["diagnostics"]
    diagnostics_md = (
        "\n".join(f"- {item}" for item in diagnostics) if diagnostics else "- None"
    )
    figure_md = (
        f"\n![Figure 1]({figure_artifact})\n\n**Figure 1.** Forest plot of the association.\n"
        if figure_artifact
        else ""
    )

    markdown = f"""# {manuscript_title}

**Running title:** {gene} and {drug} resistance

## Abstract

**Background.** Antimicrobial resistance surveillance increasingly relies on genomic
predictors, but the strength of individual gene–phenotype associations must be quantified
in local populations before they inform practice.

**Methods.** We analysed {s["n"]} isolates from surveillance run `{s["run_id"]}`. Carriage of
{s["gene"]} was cross-tabulated against {s["drug"]} susceptibility. We estimated the odds
ratio (OR) with a Woolf 95% confidence interval (CI) and tested the association at α=0.05.

**Results.** {s["gene"]} was detected in {s["gene_pos"]} isolates; {s["resistant"]} isolates
were resistant to {s["drug"]}. The OR was {s["or"]} (95% CI {s["ci_low"]}–{s["ci_high"]},
p={s["p"]}). {verdict_en.capitalize()}.

**Conclusions.** These data quantify the local gene–phenotype relationship and provide a
baseline for genomic resistance prediction in this surveillance system.

## Introduction

Genomic surveillance of bacterial pathogens generates gene presence calls alongside
phenotypic susceptibility testing. Translating the former into the latter requires
population-specific estimates of association, because resistance mechanisms vary by
lineage, plasmid background and setting. Here we estimate the association between
{s["gene"]} carriage and {s["drug"]} resistance in a single routine surveillance batch.

## Methods

### Data source

Isolates were drawn from bacmap analysis run `{s["run_id"]}`. Gene presence was taken from
the local AMR gene screen and phenotype from local susceptibility records. Only isolates
with both a gene call and an interpretable phenotype were analysed.

### Statistical analysis

A 2×2 table was constructed (a={s["a"]}, b={s["b"]}, c={s["c"]}, d={s["d"]}). The odds ratio
and its Woolf 95% CI were estimated; zero cells were handled with the Haldane–Anscombe 0.5
correction. The significance level was α=0.05. No adjustment for multiple comparisons was
applied (single hypothesis).

## Results

Of {s["n"]} isolates, {s["gene_pos"]} carried {s["gene"]} and {s["resistant"]} were resistant
to {s["drug"]}. The cross-tabulation is shown in Table 1.

**Table 1.** {s["gene"]} carriage by {s["drug"]} susceptibility.

| | Resistant | Susceptible | Total |
|---|---:|---:|---:|
| {s["gene"]} positive | {s["a"]} | {s["b"]} | {s["gene_pos"]} |
| {s["gene"]} negative | {s["c"]} | {s["d"]} | {s["gene_neg"]} |
| Total | {s["resistant"]} | {s["susceptible"]} | {s["n"]} |
{figure_md}
The estimated OR was {s["or"]} (95% CI {s["ci_low"]}–{s["ci_high"]}, p={s["p"]}).
{verdict_en.capitalize()}.

## Discussion

In this batch, {s["gene"]} carriage {"was" if p_is_sig else "was not"}
statistically associated with {s["drug"]} resistance at α=0.05. The point estimate should be
interpreted alongside its confidence interval, which reflects the limited sample size and
the zero-cell correction where applicable.

## Limitations

- The design is cross-sectional; no causal inference is possible.
- Isolates are not corrected for clonal relatedness; repeated outbreak clones can inflate
  apparent associations.
- Gene presence is not gene expression, and phenotype depends on local testing methods and
  breakpoints.

## Data availability

All inputs are local. Statistical results are stored as artifact `{table_artifact}`;
the analysis is reproducible from the run identifier and the parameters above.

## Diagnostics

{diagnostics_md}

"""

    claims = [
        {
            "claim_type": "observation",
            "wording": f"{s['n']} isolates had both a gene call and a phenotype",
            "evidence": [table_artifact],
        },
        {
            "claim_type": "association",
            "wording": (
                f"OR={s['or']} (95% CI {s['ci_low']}-{s['ci_high']}, p={s['p']})"
            ),
            "evidence": [table_artifact],
        },
        {
            "claim_type": "association",
            "wording": verdict_en,
            "evidence": [table_artifact],
        },
    ]
    return {"markdown": markdown, "slots": s, "claims": claims}
