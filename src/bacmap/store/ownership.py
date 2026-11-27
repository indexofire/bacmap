"""湿实验数据归属（v1.10.56，P4）。

审核通过或受控写入时，把**无主**的 specimen/isolate 归属到提交人；已有 owner
永不覆盖。library/lab 没有独立 owner 列，按 specimen > isolate 的身份链归属。
"""

from __future__ import annotations

from pathlib import Path


def _claim_specimen(home: Path, specimen_id: str, owner: str) -> bool:
    from bacmap.store.specimens import SpecimenService

    with SpecimenService(home / "data" / "bacmap.sqlite") as store:
        row = store.get(specimen_id)
        if row is None or str(row.get("owner_user_id") or ""):
            return False
        # 样本下已有他人的菌株时不得把样本归给自己：owner 优先级是 specimen > isolate。
        children = store.isolates(specimen_id)
        if any(
            str(child.get("owner_user_id") or "")
            and str(child.get("owner_user_id")) != owner
            for child in children
        ):
            return False
        return store.set_owner(specimen_id, owner)


def _claim_isolate(home: Path, isolate_id: str, owner: str) -> bool:
    from bacmap.store.isolates import IsolateService

    with IsolateService(home / "data" / "bacmap.sqlite") as store:
        row = store.get(isolate_id)
        if row is None or str(row.get("owner_user_id") or ""):
            return False
        return store.set_owner(isolate_id, owner)


def claim_owner(
    home: Path | str, target_type: str, target_id: str, owner_user_id: str
) -> bool:
    """把无主目标归属到 owner；返回是否实际写入。"""
    owner = (owner_user_id or "").strip()
    if not owner or not target_id:
        return False
    root = Path(home)
    if target_type == "specimen":
        return _claim_specimen(root, target_id, owner)
    if target_type == "isolate":
        return _claim_isolate(root, target_id, owner)
    if target_type == "library":
        from bacmap.store.catalog import library_links

        links = library_links(root, target_id)
        claimed = False
        if links["isolate_id"]:
            claimed = _claim_isolate(root, links["isolate_id"], owner) or claimed
        if links["specimen_id"]:
            claimed = _claim_specimen(root, links["specimen_id"], owner) or claimed
        return claimed
    if target_type == "lab":
        from bacmap.store.lab_results import LabResultService

        with LabResultService(root / "data" / "bacmap.sqlite") as store:
            row = store.get_by_id(target_id)
        if row is None:
            return False
        if row.subject_type == "specimen":
            return _claim_specimen(root, row.subject_id or row.strain_id, owner)
        return _claim_isolate(root, row.subject_id or row.strain_id, owner)
    return False
