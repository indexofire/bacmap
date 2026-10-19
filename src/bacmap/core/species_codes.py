"""物种三字母码 —— 全系统统一的稳定键（gside 标签/显示名 → CODE）。

定位（ADR-19/20）：gside 负责**鉴定**并给出物种标签；本模块只做**翻译 + 防呆**，
不参与鉴定。三字母码是全系统唯一键：`pathogens.yaml` 键、baseline 分组键、
`samples.tsv.species`、`snp_group`/`cgmlst_scheme` 等查表一律以码为准。

规则：``属首字母 + 种名前 2 字母``（大写）。
例外/覆盖（见 ``_OVERRIDES``）：SAL(Salmonella)、SHI(Shigella)、ECO(DEC/E. coli)、
EFM(E. faecium，避免与 EFA 撞)、CDP(C. diphtheriae，避免与 CDI 撞)。
有意合并：VCH = Vibrio_cholerae / _O1 / _O139（种下血清型暂不拆分，交 gapit）。
未识别/占位/否定（``not_*``）→ ``UNK`` 哨兵。
"""

from __future__ import annotations

import re

UNK = "UNK"

# 占位/未鉴定写法（统一收敛到 UNK，避免各消费者各写一份字符串判断）
_PLACEHOLDER_TOKENS = frozenset(
    {
        "",
        "unknown",
        "n/a",
        "na",
        "none",
        "unidentified",
        "unclassified",
        "pending_gside",
        "pending_gapit",
    }
)

# 属级覆盖：不区分种（Salmonella 以血清型分型、Shigella 按属归口）。
_GENUS_OVERRIDES: dict[str, str] = {"salmonella": "SAL", "shigella": "SHI"}

# 覆盖：(归一化 token 元组) → 码。token 由 label 按 [._\s/]+ 切分、小写得到。
_OVERRIDES: dict[tuple[str, ...], str] = {
    ("dec",): "ECO",
    ("enterococcus", "faecium"): "EFM",
    ("corynebacterium", "diphtheriae"): "CDP",
}

# 有意合并的码：同码多个标签是**设计如此**（区别于需要消除的意外冲突）。
INTENTIONAL_MERGES: dict[str, frozenset[str]] = {
    "VCH": frozenset({"Vibrio_cholerae", "Vibrio_cholerae_O1", "Vibrio_cholerae_O139"}),
}

_SPLIT_RE = re.compile(r"[._\s/]+")


def _tokens(label: str) -> tuple[str, ...]:
    return tuple(t for t in _SPLIT_RE.split(label.strip().lower()) if t)


def _first_alpha(text: str) -> str:
    for ch in text:
        if ch.isalpha():
            return ch.upper()
    return ""


def _letters(text: str, n: int) -> str:
    out = "".join(ch for ch in text if ch.isalpha())[:n]
    return out.upper()


def species_code(label: str) -> str:
    """gside 标签 / 显示名 → 三字母码；占位、空、``not_*`` → ``UNK``。"""
    text = (label or "").strip()
    low = text.lower()
    if low in _PLACEHOLDER_TOKENS or low.startswith("not_"):
        return UNK
    tokens = _tokens(text)
    if not tokens:
        return UNK
    genus_override = _GENUS_OVERRIDES.get(tokens[0])
    if genus_override:
        return genus_override
    override = _OVERRIDES.get(tokens)
    if override:
        return override
    genus = tokens[0]
    # 只有属名（未细分到种）：取属名前 3 字母
    code = _letters(genus, 3) if len(tokens) == 1 else _first_alpha(genus) + _letters(tokens[1], 2)
    return code if len(code) == 3 else UNK


def code_map(labels: list[str]) -> dict[str, list[str]]:
    """标签 → {code: [labels]}；意外冲突（同码不同物种且非有意合并）即抛错。"""
    grouped: dict[str, list[str]] = {}
    for label in labels:
        code = species_code(label)
        grouped.setdefault(code, []).append(label)
    for code, members in grouped.items():
        if len(members) > 1 and set(members) != set(INTENTIONAL_MERGES.get(code, frozenset())):
            raise ValueError(
                f"species code collision: {code} ← {sorted(members)}"
                "（请加显式覆盖或确认有意合并）"
            )
    return grouped


# gside 0.1.1 `D1_marker/marker_rules.yaml` 的物种标签快照（40 条）——
# 码表/冲突检查的权威输入；重建 pathogens.yaml 时以此为覆盖面基准。
GSIDE_MARKER_LABELS: tuple[str, ...] = (
    "Salmonella",
    "V_parahaemolyticus",
    "Listeria_monocytogenes",
    "Vibrio_cholerae",
    "Vibrio_cholerae_O1",
    "Vibrio_cholerae_O139",
    "Vibrio_vulnificus",
    "Staphylococcus_aureus",
    "Klebsiella_pneumoniae",
    "Acinetobacter_baumannii",
    "Pseudomonas_aeruginosa",
    "Enterococcus_faecalis",
    "Enterococcus_faecium",
    "Streptococcus_pneumoniae",
    "Streptococcus_pyogenes",
    "Streptococcus_agalactiae",
    "Neisseria_meningitidis",
    "Neisseria_gonorrhoeae",
    "Clostridioides_difficile",
    "Cronobacter_sakazakii",
    "Legionella_pneumophila",
    "Mycoplasma_pneumoniae",
    "Helicobacter_pylori",
    "Bordetella_pertussis",
    "Corynebacterium_diphtheriae",
    "Haemophilus_influenzae",
    "Streptococcus_suis",
    "Burkholderia_pseudomallei",
    "Leptospira_interrogans",
    "Treponema_pallidum",
    "Bacillus_anthracis",
    "Yersinia_pestis",
    "Yersinia_enterocolitica",
    "Aeromonas_hydrophila",
    "Clostridium_botulinum",
    "Clostridium_perfringens",
    "DEC",
    "Shigella_EIEC",
    "Campylobacter_jejuni",
    "Campylobacter_coli",
)
