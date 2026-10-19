"""门框架（冻结设计 §4.2 / ADR-07）。

门是任务步骤之间的代码检查点，由 bacmap.tasks 强制执行，任何接口层
无法绕过。本模块实现分析结论门（analysis_claims）——解读文本在展示、
导出、入库前必须通过确定性校验（deterministic verifier）与 NLI 反射
（nli_reflector），两者均为确定性代码（v1.4.1 更正：无 LLM 审核角色）。

四道门均已落地：analysis_claims（第 6 步）、baseline_release（第 7 步）、
mining/citation（第 10 步，citation 后端为 store.knowledge 持久知识库）。
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol

from pydantic import BaseModel

from bacmap.core.analysis.species_canon import UNKNOWN as SPECIES_UNKNOWN
from bacmap.core.analysis.species_canon import canonical_from_verdict
from bacmap.core.verify import nli_reflector


class GateVerdict(StrEnum):
    PASS = "pass"  # noqa: S105 — 门判定字面量，非凭据
    NEEDS_HUMAN_REVIEW = "needs_human_review"
    REJECT = "reject"


class GateResult(BaseModel):
    gate: str  # "analysis_claims" | "baseline_release" | "mining" | "citation"
    verdict: GateVerdict
    details: dict[str, Any] = {}
    evaluated_at: datetime


class GateSubject(BaseModel):
    gate: str
    payload: dict[str, Any]


class Gate(Protocol):
    name: str

    def evaluate(self, subject: GateSubject) -> GateResult: ...


def evaluate_analysis_claims(
    interpretation_text: str, summary: dict[str, Any], sample_id: str
) -> GateResult:
    """分析结论门：解读文本 vs 管线事实（Source of Truth）。

    判定映射：
    - 摘要自身不一致（deterministic verifier 失败）→ REJECT（数据级问题）
    - NLI 反射 needs_human_review（矛盾率超阈）→ NEEDS_HUMAN_REVIEW
    - 其余 → PASS（details 携带计数供审计）
    """
    now = datetime.now(UTC)

    species = ""
    sp = ((summary.get("steps", {}) or {}).get("species", {})) or {}
    if isinstance(sp, dict):
        species = str(sp.get("verdict") or sp.get("species") or "")
    if species:
        dec = ((summary.get("steps", {}) or {}).get("dec", {})) or {}
        ipah = str(dec.get("ipaH", "")) if isinstance(dec, dict) else ""
        if canonical_from_verdict(species, ipah) == SPECIES_UNKNOWN:
            return GateResult(
                gate="analysis_claims",
                verdict=GateVerdict.REJECT,
                details={"reason": "species_not_supported", "species": species},
                evaluated_at=now,
            )

    facts = nli_reflector.extract_facts(summary, sample_id)
    r = nli_reflector.reflect(interpretation_text, facts)
    details = {
        "verifiable_count": r.verifiable_count,
        "contradicted_count": r.contradicted_count,
        "contradiction_rate": r.contradiction_rate,
        "corroborated_count": r.corroborated_count,
        "threshold": r.threshold,
        "sample_id": sample_id,
    }
    if r.needs_human_review:
        return GateResult(
            gate="analysis_claims",
            verdict=GateVerdict.NEEDS_HUMAN_REVIEW,
            details=details,
            evaluated_at=now,
        )
    return GateResult(
        gate="analysis_claims", verdict=GateVerdict.PASS, details=details, evaluated_at=now
    )


_D4_KEYS = frozenset({
    "patient_id", "patient_name", "patient_age", "patient_gender", "patient_phone",
    "symptoms", "onset_date", "diagnosis", "outcome", "hospital", "facility",
    "receiver", "submitting_lab",
})


def _record_list(value: Any) -> list[dict[str, Any]]:
    """把候选/产物字段收敛为 dict 列表；非列表或含非 dict 项一律丢弃（门按缺失处理，
    fail-closed：畸形候选 → REJECT，而非在门里抛异常）。"""
    if not isinstance(value, list):
        return []
    return [r for r in value if isinstance(r, dict)]


def evaluate_baseline_release(candidate: dict[str, Any]) -> GateResult:
    """特征库发布门（ADR-07/19）：纳入菌株逐项检查 + D4 泄漏防御。

    检查：非空候选、无重复菌株、物种可规范化、分离日期/地区/来源齐备、
    特征字段无 D4 泄漏（白名单构造之外的二次防线）。
    """
    now = datetime.now(UTC)
    strains = _record_list(candidate.get("strains"))
    excluded = candidate.get("excluded", [])
    problems: list[str] = []
    seen: set[str] = set()
    for rec in strains:
        sid = str(rec.get("strain_id", ""))
        if sid in seen:
            problems.append(f"duplicate:{sid}")
        seen.add(sid)
        f = rec.get("features", {}) if isinstance(rec.get("features"), dict) else {}
        species = str(f.get("species", ""))
        if not species or species == SPECIES_UNKNOWN:
            problems.append(f"species:{sid}")
        if not f.get("isolation_date"):
            problems.append(f"isolation_date:{sid}")
        if not f.get("sample_source"):
            problems.append(f"sample_source:{sid}")
        if not (f.get("province") or f.get("city")):
            problems.append(f"region:{sid}")
        leaked = _D4_KEYS & set(f.keys())
        if leaked:
            problems.append(f"d4_leak:{sid}:{sorted(leaked)}")
    if not strains:
        problems.append("empty_candidate")
    details = {
        "n_strains": len(strains),
        "n_excluded": len(excluded) if isinstance(excluded, list) else 0,
        "problems": problems[:50],
    }
    verdict = GateVerdict.PASS if not problems else GateVerdict.REJECT
    return GateResult(gate="baseline_release", verdict=verdict, details=details, evaluated_at=now)


def _baseline_release_adapter(subject: GateSubject) -> GateResult:
    return evaluate_baseline_release(subject.payload.get("candidate", {}))


def evaluate_mining(payload: dict[str, Any]) -> GateResult:
    """挖掘结论门（ADR-07/V11⑤）：未签字产物不得进入报告。

    payload: {artifacts: [{name, reproducible}], signed_by: str|None}
    检查：产物非空、逐条可复现（有脚本/命令来源）、用户已签字。
    """
    now = datetime.now(UTC)
    raw_artifacts = payload.get("artifacts", [])
    artifacts = _record_list(raw_artifacts)
    problems: list[str] = []
    if not isinstance(raw_artifacts, list):
        problems.append("malformed_artifacts")
    if not artifacts:
        problems.append("empty_artifacts")
    for art in artifacts:
        if not art.get("name"):
            problems.append("artifact_missing_name")
        elif not art.get("reproducible", False):
            problems.append(f"not_reproducible:{art.get('name')}")
    if not payload.get("signed_by"):
        problems.append("unsigned")
    details = {"n_artifacts": len(artifacts), "problems": problems[:50]}
    verdict = GateVerdict.PASS if not problems else GateVerdict.REJECT
    return GateResult(gate="mining", verdict=verdict, details=details, evaluated_at=now)


_CITE_RE = re.compile(r"PMID:\s?(\d{6,9})|\[(\d{4,8})\]", re.IGNORECASE)
_DOI_RE = re.compile(r"(?<![0-9A-Za-z.])(10\.\d{4,9}/[-._;()/:A-Za-z0-9]+)")
_KNOWN_PMID_RE = re.compile(r"(?i)^pmid[:\s]*(\d+)$")


def _normalize_known(citation: str) -> str:
    """知识库侧标识符归一，与成稿侧提取结果可比：
    - ``PMID:12345678`` / ``pmid 12345678`` → ``12345678``（纯数字）
    - 方括号包裹 ``[12345678]`` → ``12345678``
    - DOI（``10.…``）→ 小写
    """
    k = str(citation).strip()
    m = _KNOWN_PMID_RE.match(k)
    if m:
        return m.group(1)
    if k.startswith("[") and k.endswith("]"):
        k = k[1:-1].strip()
    if k[:3].lower() == "10.":
        return k.lower()
    return k


def evaluate_citation(payload: dict[str, Any]) -> GateResult:
    """引用门（ADR-07/V11⑥）：成稿中每条引用必须能在本地知识库找到。

    payload: {draft: str, known_citations: list[str]}
    提取 PMID（``PMID:`` 前缀或 ``[数字]``）与 DOI（大小写不敏感）形引用，
    逐条核对 known_citations（标识符两侧均归一，PMID 前缀/方括号不影响比对）。

    已知边界：3 位及以下的编号式引用（如 ``[1]``）不视为可核引用，不参与判定
    （避免把列表编号误判为未知引用）。
    """
    now = datetime.now(UTC)
    draft = str(payload.get("draft", ""))
    known_raw = payload.get("known_citations", [])
    known = {
        _normalize_known(c)
        for c in (known_raw if isinstance(known_raw, list) else [])
    }
    found: set[str] = set()
    for m in _CITE_RE.finditer(draft):
        pmid = m.group(1) or m.group(2)
        if pmid:
            found.add(pmid)
    for m in _DOI_RE.finditer(draft):
        doi = m.group(1).rstrip(".,;:)]}。，；：）】》〉」』").lower()
        if len(doi) > 8:
            found.add(doi)
    unknown = sorted(found - known)
    details = {"citations_found": sorted(found), "unknown": unknown}
    verdict = GateVerdict.PASS if not unknown else GateVerdict.REJECT
    return GateResult(gate="citation", verdict=verdict, details=details, evaluated_at=now)


def _mining_adapter(subject: GateSubject) -> GateResult:
    return evaluate_mining(subject.payload)


def _citation_adapter(subject: GateSubject) -> GateResult:
    return evaluate_citation(subject.payload)


def _analysis_claims_adapter(subject: GateSubject) -> GateResult:
    p = subject.payload
    return evaluate_analysis_claims(
        p.get("interpretation_text", ""),
        p.get("summary", {}),
        p.get("sample_id", ""),
    )


GATES: dict[str, Any] = {
    "analysis_claims": _analysis_claims_adapter,
    "baseline_release": _baseline_release_adapter,
    "mining": _mining_adapter,
    "citation": _citation_adapter,
}


def evaluate(subject: GateSubject) -> GateResult:
    fn = GATES.get(subject.gate)
    if fn is None:
        raise KeyError(f"unknown gate: {subject.gate}")
    return fn(subject)
