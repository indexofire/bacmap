"""NLI Reflector — project.md §8.2 Layer 3。

把 LLM 解读文本分解为 atomic claims，与 Source of Truth（管线产物事实，
project.md §8.3 第一层）逐条比对（entailed / contradicted / unverifiable）。
contradiction rate 超过阈值 → NEEDS_HUMAN_REVIEW（CRAG 模式）。

比对为确定性规则（species 规范名 / ST 整数 / 血清型 casefold / 基因集合
成员 + 共享 gene_identity 归一），不依赖 LLM——Layer 3 结论本身必须可复现。

语义约定（评审 P0 修复）：
- 否定式表述（不是/未检出/not…）产生 negated claim，比对规则为
  ENTAILED iff (claim 与 facts 匹配) != negated。
- contradiction_rate 的分母/分子只计 decomposed（文本提取）claims；
  佐证回填（facts 基因在文本中的提及）单列 corroborated_count，
  不稀释阈值判定（防「单条矛盾被 15 条佐证淹没」的漏报）。
"""

from __future__ import annotations

import logging
import re
import sqlite3
from pathlib import Path
from typing import Any, assert_never

from bacmap.core.utils import parse_mlst

from ..analysis.gene_identity import normalize_amr
from ..analysis.species_canon import (
    ECOLI,
    SALMONELLA,
    SHIGELLA,
    VPARA,
    canonical_from_verdict,
)
from .nli_types import (
    DEFAULT_CONTRADICTION_THRESHOLD,
    AtomicClaim,
    ClaimType,
    ClaimVerdict,
    ReflectionResult,
    StrainFacts,
    Verdict,
)

logger = logging.getLogger(__name__)


_SPECIES_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"Salmonella|沙门氏?菌"), SALMONELLA),
    (re.compile(r"V\.?\s*parahaemolyticus|副溶血性弧菌"), VPARA),
    (re.compile(r"Shigella|志贺氏?菌"), SHIGELLA),
    (re.compile(r"E\.?\s*coli|大肠埃希菌|大肠杆菌"), ECOLI),
)

_ST_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bST[-\s]*(?:型\s*)?(?:为|:|：)?\s*(\d+)"),
    re.compile(r"序列型\s*(?:为|是|:|：)?\s*(\d+)"),
)

_SEROTYPE_PATTERNS: tuple[re.Pattern[str], ...] = (
    # 值捕获支持「词(. 词)*」多词形态（"S. Typhimurium" 整体捕获），归一见
    # _normalize_serotype；抗原式（"1,4,[5],12:i:1,2"，数字开头）按设计不
    # 捕获——formula↔name 映射需查表，未映射文本不构成可比较 claim（防假矛盾）
    re.compile(
        r"血清型\s*(?:为|是|:|：)?\s*"
        r"([A-Za-z][A-Za-z0-9\[\]'\-]*(?:\.\s*[A-Za-z][A-Za-z0-9\[\]'\-]*)*)"
    ),
    re.compile(
        r"\bserovar\s+"
        r"([A-Za-z][A-Za-z0-9\[\]'\-]*(?:\.\s*[A-Za-z][A-Za-z0-9\[\]'\-]*)*)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bserotype\s+"
        r"([A-Za-z][A-Za-z0-9\[\]'\-]*(?:\.\s*[A-Za-z][A-Za-z0-9\[\]'\-]*)*)",
        re.IGNORECASE,
    ),
)


def _normalize_serotype(value: str) -> str:
    """血清型值归一：casefold + 剥离 "S."/"s"/"salmonella" 属名前缀与尾点。

    "S. Typhimurium" → "typhimurium"，与 facts 的 sistr serovar 名可比较。
    """
    v = value.casefold().strip().rstrip(".")
    for prefix in ("salmonella ", "s. ", "s "):
        if v.startswith(prefix):
            v = v[len(prefix) :]
    return v.strip()


# 基因符号 token（覆盖 blaCTX-M-15 / AAC(6')-Iaa / tet(A) 等形态）。
_GENE_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_'()\-]{1,30}")

# 否定标记（中/英）。marker 与匹配起点之间只允许空白/标点——「非常罕见的
# 沙门菌」中「非」因间隙含字词而不构成否定（评审 A1 间隙约束）。
_NEGATION_ZH_RE = re.compile(
    r"(不是|并非|未检出|未检测到|未携带|不携带|不含|不带|排除|缺乏|未|无|非)"
)
_NEGATION_EN_RE = re.compile(r"\b(not|no|nor|without|absent|negative|lacks?)\b", re.IGNORECASE)
_GAP_RE = re.compile(r"^[\s'\"“”‘’、，。,:：;；()（）\[\]-]*$")


def _is_negated(text: str, start: int) -> bool:
    """匹配起点前 12 字符窗口内是否存在紧邻的否定标记。"""
    window = text[max(0, start - 12) : start]
    for pattern in (_NEGATION_ZH_RE, _NEGATION_EN_RE):
        for m in pattern.finditer(window):
            if _GAP_RE.match(window[m.end() :]):
                return True
    return False


# 常见 AMR 基因家族（fullmatch，casefold 比较）。
_AMR_FAMILY_RE = re.compile(
    r"(?:bla[A-Z]{2}[A-Za-z0-9]*(?:-[A-Za-z0-9]+)+"
    r"|mcr-\d+"
    r"|tet\([A-Z]\)"
    r"|tet[A-Z]\d*"
    r"|sul[123]"
    r"|qnr[A-Z]?[a-z]?\d*"
    r"|erm\([A-Z]\)"
    r"|aac\([0-9']+\)-[A-Za-z0-9-]+"
    r"|ant\([0-9']+\)-[A-Za-z0-9-]+"
    r"|van[ABCD]"
    r"|dfrA\d+"
    r"|cat[AB]\d*"
    r"|floR"
    r"|lnu\([A-Z]\))",
    re.IGNORECASE,
)


def _canonical_species(verdict: str, ipah: str) -> str:
    """verdict → 规范物种名（共享 species_canon，not_X 按 ipaH 分流）。"""
    return canonical_from_verdict(verdict, ipah)


def _gene_names(rows: object) -> tuple[str, ...]:
    if not isinstance(rows, list):
        return ()
    return tuple(str(r.get("GENE", "")) for r in rows if isinstance(r, dict) and r.get("GENE"))


def extract_facts(summary: dict[str, Any], sample_id: str) -> StrainFacts:
    """从 summary.json（steps 结构）提取 Source of Truth 事实。"""
    steps = summary.get("steps", {})

    sp = steps.get("species", {})
    verdict = ""
    if isinstance(sp, dict):
        verdict = str(sp.get("verdict") or sp.get("species") or "")
    dec = steps.get("dec", {})
    ipah = str(dec.get("ipaH", "")) if isinstance(dec, dict) else ""

    mlst_raw = steps.get("mlst", "")
    st = ""
    if isinstance(mlst_raw, str) and mlst_raw:
        st = str(parse_mlst(mlst_raw).get("st", ""))
        if st in ("N/A", "-"):
            st = ""

    sero = steps.get("serotype", {})
    serotype = str(sero.get("sistr", "")) if isinstance(sero, dict) else ""

    amr = steps.get("amr", {})
    pl = steps.get("plasmid", {})

    return StrainFacts(
        sample_id=sample_id,
        species=_canonical_species(verdict, ipah),
        mlst_st=st,
        serotype=serotype,
        amr_genes=_gene_names(amr.get("abricate_card") if isinstance(amr, dict) else None),
        virulence_genes=_gene_names(amr.get("abricate_vfdb") if isinstance(amr, dict) else None),
        plasmids=_gene_names(pl.get("plasmidfinder") if isinstance(pl, dict) else None),
    )


def decompose_claims(text: str) -> list[AtomicClaim]:
    """把解读文本分解为 atomic claims（确定性正则，无 LLM）。

    AMR 家族基因无需事实库即可提取（用于矛盾检测）；virulence/plasmid
    claims 由 reflect() 依据事实表补全（仅产生 entailed 佐证）。
    否定式提及（不是/未检出/not…）产出 negated=True 的 claim。
    """
    claims: list[AtomicClaim] = []
    seen: set[tuple[ClaimType, str, bool]] = set()

    def _add(claim_type: ClaimType, value: str, raw: str, negated: bool) -> None:
        key = (claim_type, value.casefold(), negated)
        if key not in seen:
            seen.add(key)
            claims.append(AtomicClaim(claim_type, value, raw, negated))

    for pattern, canonical in _SPECIES_PATTERNS:
        for m in pattern.finditer(text):
            _add(ClaimType.SPECIES, canonical, m.group(0), _is_negated(text, m.start()))

    for pattern in _ST_PATTERNS:
        for m in pattern.finditer(text):
            _add(ClaimType.MLST_ST, m.group(1), m.group(0), _is_negated(text, m.start()))

    for pattern in _SEROTYPE_PATTERNS:
        for m in pattern.finditer(text):
            _add(
                ClaimType.SEROTYPE,
                m.group(1),
                m.group(0),
                _is_negated(text, m.start()),
            )

    for m in _GENE_TOKEN_RE.finditer(text):
        token = m.group(0)
        if _AMR_FAMILY_RE.fullmatch(token):
            _add(ClaimType.AMR_GENE, token, token, _is_negated(text, m.start()))

    return claims


def _casefold_set(values: tuple[str, ...]) -> frozenset[str]:
    return frozenset(v.casefold() for v in values)


def _amr_norm_set(values: tuple[str, ...]) -> frozenset[str]:
    return frozenset(normalize_amr(v) for v in values)


def _compare(claim: AtomicClaim, facts: StrainFacts) -> Verdict:
    """ENTAILED iff (claim 与 facts 匹配) != claim.negated。"""
    match claim.claim_type:
        case ClaimType.SPECIES:
            if facts.species == "unknown":
                return Verdict.UNVERIFIABLE
            matches = claim.value == facts.species
        case ClaimType.MLST_ST:
            if not facts.mlst_st:
                return Verdict.UNVERIFIABLE
            matches = claim.value == facts.mlst_st
        case ClaimType.SEROTYPE:
            if not facts.serotype:
                return Verdict.UNVERIFIABLE
            matches = _normalize_serotype(claim.value) == _normalize_serotype(facts.serotype)
        case ClaimType.AMR_GENE:
            matches = normalize_amr(claim.value) in _amr_norm_set(facts.amr_genes)
        case ClaimType.VIRULENCE_GENE:
            matches = claim.value.casefold() in _casefold_set(facts.virulence_genes)
        case ClaimType.PLASMID:
            matches = claim.value.casefold() in _casefold_set(facts.plasmids)
        case unreachable:
            assert_never(unreachable)
    return Verdict.ENTAILED if matches != claim.negated else Verdict.CONTRADICTED


def _evidence(claim: AtomicClaim, facts: StrainFacts) -> str:
    match claim.claim_type:
        case ClaimType.SPECIES:
            return f"facts.species={facts.species!r}"
        case ClaimType.MLST_ST:
            return f"facts.mlst_st={facts.mlst_st!r}"
        case ClaimType.SEROTYPE:
            return f"facts.serotype={facts.serotype!r}"
        case ClaimType.AMR_GENE:
            return f"facts.amr_genes={list(facts.amr_genes)}"
        case ClaimType.VIRULENCE_GENE:
            return f"facts.virulence_genes={list(facts.virulence_genes)}"
        case ClaimType.PLASMID:
            return f"facts.plasmids={list(facts.plasmids)}"
        case unreachable:
            assert_never(unreachable)


def reflect(
    text: str,
    facts: StrainFacts,
    threshold: float = DEFAULT_CONTRADICTION_THRESHOLD,
) -> ReflectionResult:
    """Layer 3 主入口：分解 claims → 逐条比对 → 汇总 contradiction rate。

    contradiction_rate 只对 decomposed（文本提取）claims 计算；佐证回填
    （facts 基因在文本中的提及，含否定式——文本否认管线检出的基因构成
    矛盾 verdict）单列 corroborated_count，不进分母（评审 A3：防稀释）。
    """
    decomposed = decompose_claims(text)
    decomposed_verdicts = tuple(
        ClaimVerdict(c, _compare(c, facts), _evidence(c, facts)) for c in decomposed
    )

    seen = {(c.claim_type, c.value.casefold(), c.negated) for c in decomposed}
    backfilled: list[AtomicClaim] = []
    for claim_type, genes in (
        (ClaimType.AMR_GENE, facts.amr_genes),
        (ClaimType.VIRULENCE_GENE, facts.virulence_genes),
        (ClaimType.PLASMID, facts.plasmids),
    ):
        for gene in genes:
            occurrences = list(re.finditer(re.escape(gene), text, re.IGNORECASE))
            if not occurrences:
                continue
            negated = all(_is_negated(text, m.start()) for m in occurrences)
            key = (claim_type, gene.casefold(), negated)
            if key not in seen:
                seen.add(key)
                backfilled.append(AtomicClaim(claim_type, gene, gene, negated))
    backfilled_verdicts = tuple(
        ClaimVerdict(c, _compare(c, facts), _evidence(c, facts)) for c in backfilled
    )
    corroborated = sum(1 for v in backfilled_verdicts if v.verdict is Verdict.ENTAILED)

    verifiable = [v for v in decomposed_verdicts if v.verdict is not Verdict.UNVERIFIABLE]
    contradicted = [v for v in verifiable if v.verdict is Verdict.CONTRADICTED]
    rate = len(contradicted) / len(verifiable) if verifiable else 0.0

    return ReflectionResult(
        verdicts=decomposed_verdicts + backfilled_verdicts,
        verifiable_count=len(verifiable),
        contradicted_count=len(contradicted),
        contradiction_rate=rate,
        needs_human_review=bool(verifiable) and rate > threshold,
        threshold=threshold,
        corroborated_count=corroborated,
    )


def record_reflection_event(db_path: Path, sample_id: str, reflection: ReflectionResult) -> bool:
    """把 reflection 结果落 GOM 审计事件（needs_human_review 时调用）。

    payload 含完整矛盾明细（contradicted claims），供 bio_review_flags 工具
    与报告「AI 解读自检」章节读回（P1-3/P1-4 人审闭环出口）。
    GOM 不可用（DB 缺失/无对应样本对象/写失败）→ False，静默降级——
    审计失败不得阻断 Layer 2 校验的返回。
    """
    if not db_path.exists():
        return False
    from bacmap.store.genome_object_service import (
        GenomeObjectService,
        GOMValidationError,
        ObjectType,
    )

    try:
        with GenomeObjectService(db_path) as gos:
            # P3-2+：优先挂到该样本的 sample_analysis ANALYSIS 对象（单样本结果版本），
            # 取其 created_at 最新一条保证确定性；无标记时回退任一 ANALYSIS 对象。
            target = None
            for obj in gos.list_by_type(ObjectType.ANALYSIS):
                if obj.strain_id != sample_id:
                    continue
                if obj.payload.get("analysis_type") != "sample_analysis":
                    continue
                if target is None or obj.created_at > target.created_at:
                    target = obj
            if target is None:
                for obj in gos.list_by_type(ObjectType.ANALYSIS):
                    if obj.strain_id == sample_id and (
                        target is None or obj.created_at > target.created_at
                    ):
                        target = obj
            if target is None:
                return False
            gos.log_event(
                target.object_id,
                "nli_reflected",
                {
                    "sample_id": sample_id,
                    "contradiction_rate": reflection.contradiction_rate,
                    "contradicted_count": reflection.contradicted_count,
                    "needs_human_review": reflection.needs_human_review,
                    "verifiable_count": reflection.verifiable_count,
                    "corroborated_count": reflection.corroborated_count,
                    "threshold": reflection.threshold,
                    "contradicted_claims": [
                        {
                            "claim_type": str(cv.claim.claim_type),
                            "value": cv.claim.value,
                            "negated": cv.claim.negated,
                            "evidence": cv.evidence,
                        }
                        for cv in reflection.verdicts
                        if cv.verdict is Verdict.CONTRADICTED
                    ],
                },
            )
            return True
    except (GOMValidationError, sqlite3.Error, OSError):
        logger.exception("record_reflection_event failed for %s", sample_id)
        return False


def latest_review_flag(db_path: Path, sample_id: str) -> dict[str, Any] | None:
    """读回某样本最近一次 nli_reflected 审计事件（工具/报告共用读回面）。

    无 DB / 无匹配样本 / 无事件 / 读失败 → None（调用方按"无自检记录"降级）。
    """
    if not db_path.exists():
        return None
    from bacmap.store.genome_object_service import (
        GenomeObjectService,
        GOMValidationError,
        ObjectType,
    )

    try:
        with GenomeObjectService(db_path) as gos:
            latest = None
            for obj in gos.list_by_type(ObjectType.ANALYSIS):
                if obj.strain_id != sample_id:
                    continue
                for ev in gos.list_events(obj.object_id):
                    if ev.event_type == "nli_reflected" and (
                        latest is None or ev.timestamp > latest.timestamp
                    ):
                        latest = ev
            if latest is None:
                return None
            return {"timestamp": latest.timestamp.isoformat(), **latest.event_payload}
    except (GOMValidationError, sqlite3.Error, OSError):
        logger.exception("latest_review_flag failed for %s", sample_id)
        return None
