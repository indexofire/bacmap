"""数字审计门（P2）：报告中的数字必须能回溯到槽位或模板常量。"""

from __future__ import annotations

from bacmap.research.numeric_audit import audit_numbers, mask_non_data, numeric_tokens


def test_numeric_tokens_extracts_plain_numbers() -> None:
    assert numeric_tokens("OR=3.10，95% CI 1.20–8.00，p<0.001") == ["3.10", "95", "1.20", "8.00", "0.001"]


def test_timestamps_and_hashes_are_masked() -> None:
    text = (
        "生成时间 2026-11-15T16:01:53+00:00；产物 sha256:"
        "9f2c1d4b6a8e0f3c5b7d9a1e2f4c6b8d；表 1"
    )
    assert numeric_tokens(text) == ["1"]


def test_headings_are_masked() -> None:
    text = "## 1 材料与方法\n### 1.1 数据来源\n结果 OR=2.50"
    assert numeric_tokens(text) == ["2.50"]
    assert "1.1" not in mask_non_data(text)


def test_audit_passes_when_numbers_come_from_slots() -> None:
    slots = {"n": 5, "or": "3.10", "ci_low": "1.20", "ci_high": "8.00", "p": "0.004"}
    text = "共 5 株；OR=3.10（95% CI 1.20–8.00，p=0.004）。"
    assert audit_numbers(text, slots) == []


def test_audit_flags_fabricated_numbers() -> None:
    slots = {"n": 5, "or": "3.10"}
    text = "共 5 株；OR=3.10，另补充 9.99 的校正结果。"
    assert audit_numbers(text, slots) == ["9.99"]


def test_audit_tolerates_missing_values() -> None:
    slots = {"or": "无法估计", "p": "<0.001"}
    # "<0.001" 是槽位值，0.001 因此可回溯；"无法估计" 不是数字。
    assert audit_numbers("OR 无法估计，p<0.001", slots) == []


def test_audit_allows_numeric_strings_from_slots() -> None:
    slots = {"or": "35.00", "ci": "2435.69"}
    assert audit_numbers("OR=35.00，上限 2435.69", slots) == []


def test_audit_allows_extra_constants() -> None:
    assert audit_numbers("阈值 7.50", {}, extra_allowed=(7.5,)) == []
