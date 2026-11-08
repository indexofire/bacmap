"""高级统计外部化（ADR-22：bacmap 只编排与归一，模型在固定容器内拟合）。

混合效应 logistic、IPTW、倾向评分匹配、KM/log-rank、Cox —— 这些方法**不在
bacmap 内实现**（不引入 statsmodels/lme4 依赖），而是从类型化 ``AnalysisSpec``
确定性渲染 R 脚本，在固定镜像（``docker://bacmap-stats:r45``）的沙箱里执行，
再把容器输出的 JSON 归一为研究结论字段。脚本由 bacmap 渲染而非 agent 编写：
计划确认（人工）即授权，无需挖掘门；spec/脚本/输出全部留 hash。

R 包：lme4（glmer）、survival（survfit/survdiff/coxph）、MatchIt（匹配）、
WeightIt+survey（IPTW）、jsonlite（输出）。输出统一 schema
``bacmap.advstats_result/1``::

    {"method": ..., "n": ..., "n_used": ..., "estimates": [ {"name", "log_hr"?,
    "odds_ratio"/"hazard_ratio"/"effect", "ci_low", "ci_high", "p_value"} ...],
     "diagnostics": {...}}

边界（如实）：列名/数据合法性在容器内由 R 报错并原样回传（bacmap 不猜数据）；
匹配/IPTW 的诊断（SMD、重叠）由 R 包输出，本模块只归一不判定。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ADVSTATS_RESULT_SCHEMA = "bacmap.advstats_result/1"
DEFAULT_IMAGE = "docker://bacmap-stats:r45"

Method = Literal["mixed_logistic", "iptw", "matching", "survival_km", "cox"]

_METHOD_TITLES: dict[str, str] = {
    "mixed_logistic": "Mixed-effects logistic regression (lme4 glmer)",
    "iptw": "Inverse-probability-of-treatment weighting (WeightIt + survey)",
    "matching": "Propensity-score matching (MatchIt, 1:1 nearest)",
    "survival_km": "Kaplan-Meier + log-rank (survival)",
    "cox": "Cox proportional hazards (survival coxph)",
}

_IDENTIFIER_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._")


def _valid_identifier(name: str) -> bool:
    return bool(name) and set(name) <= _IDENTIFIER_CHARS and not name[0].isdigit()


class AnalysisSpec(BaseModel):
    """一种高级统计方法的类型化规格（列名须为 R 合法标识符）。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    method: Method
    data_path: str = Field(description="CSV/TSV 绝对路径（沙箱内只读挂载）")
    outcome: str = Field(default="", description="0/1 结局列（mixed_logistic/iptw）")
    treatment: str = Field(default="", description="0/1 处理列（iptw/matching）")
    predictors: list[str] = Field(
        default_factory=list, description="固定效应/协变量列"
    )
    confounders: list[str] = Field(
        default_factory=list, description="倾向模型混杂列（iptw/matching）"
    )
    group: str = Field(default="", description="随机效应分组列（mixed_logistic）")
    time: str = Field(default="", description="生存时间列（survival_km/cox）")
    event: str = Field(default="", description="事件指示列（survival_km/cox）")
    alpha: float = Field(default=0.05, gt=0, lt=0.5)

    @field_validator("predictors", "confounders")
    @classmethod
    def _no_duplicates(cls, v: list[str]) -> list[str]:
        if len(set(v)) != len(v):
            raise ValueError("duplicate column names")
        return v

    @model_validator(mode="after")
    def _identifiers_ok(self) -> AnalysisSpec:
        for name in (
            self.outcome,
            self.treatment,
            self.group,
            self.time,
            self.event,
            *self.predictors,
            *self.confounders,
        ):
            if name and not _valid_identifier(name):
                raise ValueError(f"not a valid R column name: {name!r}")
        return self

    @model_validator(mode="after")
    def _method_requirements(self) -> AnalysisSpec:
        need: dict[str, tuple[tuple[str, str], ...]] = {
            "mixed_logistic": (("outcome", self.outcome), ("group", self.group)),
            "iptw": (
                ("treatment", self.treatment),
                ("outcome", self.outcome),
                ("confounders", ",".join(self.confounders)),
            ),
            "matching": (
                ("treatment", self.treatment),
                ("confounders", ",".join(self.confounders)),
            ),
            "survival_km": (("time", self.time), ("event", self.event)),
            "cox": (("time", self.time), ("event", self.event)),
        }
        missing = [label for label, value in need[self.method] if not value]
        if missing:
            raise ValueError(f"{self.method} requires: {', '.join(missing)}")
        if self.method == "cox" and not self.predictors:
            raise ValueError("cox requires at least one predictor")
        return self


def _data_frame_snippet(spec: AnalysisSpec) -> str:
    delimiter = r"\t" if spec.data_path.lower().endswith((".tsv", ".tab")) else ","
    return (
        f'df <- read.delim("{spec.data_path}", sep="{delimiter}", '
        "stringsAsFactors=FALSE, check.names=FALSE)\n"
        'writeLines(sprintf("rows %d", nrow(df)), stderr())\n'
    )


_HEADER = """# Rendered deterministically by bacmap (bacmap.research.advstats).
# Container: bacmap-stats (R + lme4/survival/MatchIt/WeightIt/survey/jsonlite).
# Do not edit by hand; regenerate from the plan spec.
suppressPackageStartupMessages({{
  library(jsonlite)
}})
fail <- function(msg) {{ writeLines(msg, stderr()); quit(save="no", status=1) }}
emit <- function(payload) {{
  payload$method <- "{method}"
  payload$schema <- "{schema}"
  write(toJSON(payload, auto_unbox=TRUE, digits=8), "/workspace/result.json")
}}
"""


def render_r_script(spec: AnalysisSpec) -> str:
    """从类型化规格确定性渲染 R 脚本（同一 spec 恒得同一脚本）。"""
    if not spec.data_path.startswith("/"):
        raise ValueError("data_path must be absolute (sandbox guest path)")
    parts: list[str] = [
        _HEADER.format(method=spec.method, schema=ADVSTATS_RESULT_SCHEMA),
        _data_frame_snippet(spec),
    ]
    parts.append(_METHOD_SCRIPTS[spec.method](spec))
    return "".join(parts)


def _mixed_logistic(spec: AnalysisSpec) -> str:
    # 结局在左，固定效应在右；随机截距按分组列
    rhs = " + ".join(spec.predictors) if spec.predictors else "1"
    return f"""
fit <- glmer({spec.outcome} ~ {rhs} + (1 | {spec.group}),
             data = df, family = binomial())
if (!is.null(fit@optinfo$conv$lme4$messages)) {{
  emit(list(ok=FALSE, error=paste(fit@optinfo$conv$lme4$messages, collapse="; "))))
  quit(save="no", status=1)
}}
co <- as.data.frame(summary(fit)$coefficients)
nms <- rownames(co)
estimates <- lapply(seq_len(nrow(co)), function(i) list(
  name=nms[i], log_odds=unname(co[i,1]), se=unname(co[i,2]),
  odds_ratio=exp(unname(co[i,1])),
  ci_low=exp(unname(co[i,1]) - 1.96*unname(co[i,2])),
  ci_high=exp(unname(co[i,1]) + 1.96*unname(co[i,2])),
  p_value=unname(co[i, ncol(co)]))))
vc <- as.data.frame(VarCorr(fit))
emit(list(ok=TRUE, n=nrow(df), estimates=estimates,
          diagnostics=list(random_group="{spec.group}",
                           random_variance=unname(vc$vcov[1]),
                           groups=nlevels(as.factor(df${spec.group})))))
"""


def _iptw(spec: AnalysisSpec) -> str:
    conf = " + ".join(spec.confounders)
    return f"""
if (!all(df${spec.treatment} %in% c(0,1))) fail("treatment column must be 0/1")
if (!all(df${spec.outcome} %in% c(0,1))) fail("outcome column must be 0/1")
suppressPackageStartupMessages({{ library(WeightIt); library(survey) }})
w1 <- weightit({spec.treatment} ~ {conf}, data=df, method="ps", estimand="ATE")
des <- svydesign(ids=~1, weights=w1$weights, data=df)
fit <- svyglm({spec.outcome} ~ {spec.treatment}, design=des, family=quasibinomial())
co <- summary(fit)$coefficients
tr <- rownames(co)[2]
ests <- list(list(
  name=tr, odds_ratio=exp(unname(co[2,1])),
  ci_low=exp(unname(co[2,1]) - 1.96*unname(co[2,2])),
  ci_high=exp(unname(co[2,1]) + 1.96*unname(co[2,2])),
  p_value=unname(co[2, ncol(co)])))
psd <- w1$weights * (df${spec.treatment}*2 - 1)
bal <- weightit({spec.treatment} ~ {conf}, data=df, method="ps", estimand="ATE")
emit(list(ok=TRUE, n=nrow(df), estimates=ests,
          diagnostics=list(estimand="ATE", method="ps",
                           effective_n=sum(w1$weights)^2/sum(w1$weights^2),
                           max_weight=max(w1$weights))))
"""


def _matching(spec: AnalysisSpec) -> str:
    conf = " + ".join(spec.confounders)
    return f"""
if (!all(df${spec.treatment} %in% c(0,1))) fail("treatment column must be 0/1")
suppressPackageStartupMessages({{ library(MatchIt) }})
m <- matchit({spec.treatment} ~ {conf}, data=df, method="nearest", ratio=1)
md <- match.data(m)
suppressPackageStartupMessages({{ library(survey) }})
des <- svydesign(ids=~1, weights=md$weights, data=md)
fit <- svyglm({spec.outcome} ~ {spec.treatment}, design=des, family=quasibinomial())
co <- summary(fit)$coefficients
s <- summary(m)
confs <- c({",".join(f'"{c}"' for c in spec.confounders)})
pick <- function(tab) tab[rownames(tab) %in% confs, "Std. Mean Diff."]
smd_before <- pick(s$sum.all)
smd_after <- pick(s$sum.matched)
ests <- list(list(
  name=rownames(co)[2], odds_ratio=exp(unname(co[2,1])),
  ci_low=exp(unname(co[2,1]) - 1.96*unname(co[2,2])),
  ci_high=exp(unname(co[2,1]) + 1.96*unname(co[2,2])),
  p_value=unname(co[2, ncol(co)])))
emit(list(ok=TRUE, n=nrow(df), n_used=nrow(md), estimates=ests,
          diagnostics=list(method="nearest 1:1",
                           matched_control=sum(df${spec.treatment}==1),
                           max_abs_smd_before=max(abs(smd_before)),
                           max_abs_smd_after=max(abs(smd_after)))))
"""


def _survival_km(spec: AnalysisSpec) -> str:
    group = spec.treatment or spec.group
    header = (
        "sf_survmedian <- function(sf) { m <- summary(sf)$table; "
        "as.numeric(m[rownames(m) == 'median', 'median'])[1] }\n"
        "suppressPackageStartupMessages({ library(survival) })\n"
    )
    if not group:
        return header + f"""
sf <- survfit(Surv({spec.time}, {spec.event}) ~ 1, data=df)
emit(list(ok=TRUE, n=nrow(df), estimates=list(),
          diagnostics=list(median=sf_survmedian(sf))))
"""
    return header + f"""
sf <- survfit(Surv({spec.time}, {spec.event}) ~ {group}, data=df)
sd <- survdiff(Surv({spec.time}, {spec.event}) ~ {group}, data=df)
emit(list(ok=TRUE, n=nrow(df),
          estimates=list(list(name="log_rank_{group}",
                              chi_square=unname(sd$chisq), df=length(sd$n)-1,
                              p_value=unname(pchisq(sd$chisq, length(sd$n)-1,
                                                    lower.tail=FALSE)))),
          diagnostics=list(groups=paste(names(sf$strata), collapse=" | "),
                           median=sf_survmedian(sf))))
"""


def _cox(spec: AnalysisSpec) -> str:
    rhs = " + ".join(spec.predictors)
    return f"""
suppressPackageStartupMessages({{ library(survival) }})
fit <- coxph(Surv({spec.time}, {spec.event}) ~ {rhs}, data=df)
if (is.null(fit$coefficients)) fail("no events or singular model")
ph <- cox.zph(fit)
co <- summary(fit)$coefficients
nms <- rownames(co)
ests <- lapply(seq_len(nrow(co)), function(i) list(
  name=nms[i], hazard_ratio=exp(unname(co[i,1])),
  ci_low=exp(confint(fit))[i,1], ci_high=exp(confint(fit))[i,2],
  p_value=unname(co[i, ncol(co)])))
emit(list(ok=TRUE, n=nrow(df),
          n_used=fit$nevent,
          estimates=ests,
          diagnostics=list(events=fit$nevent,
                           ph_global_p=if (is.null(ph$table)) NA
                                       else unname(ph$table[nrow(ph$table), "p"]))))
"""


_METHOD_SCRIPTS = {
    "mixed_logistic": _mixed_logistic,
    "iptw": _iptw,
    "matching": _matching,
    "survival_km": _survival_km,
    "cox": _cox,
}


def method_title(method: str) -> str:
    return _METHOD_TITLES.get(method, method)


def summarize(payload: dict[str, Any]) -> dict[str, Any]:
    """容器 result.json → 规范化研究结论（不判定、不补造字段）。"""
    method = str(payload.get("method", ""))
    out: dict[str, Any] = {
        "schema": ADVSTATS_RESULT_SCHEMA,
        "method": method,
        "title": method_title(method),
        "ok": bool(payload.get("ok")),
        "n": payload.get("n"),
        "n_used": payload.get("n_used", payload.get("n")),
        "estimates": payload.get("estimates", []) or [],
        "diagnostics": payload.get("diagnostics", {}) or {},
    }
    if not out["ok"]:
        out["error"] = str(payload.get("error", "container run failed"))
    return out
