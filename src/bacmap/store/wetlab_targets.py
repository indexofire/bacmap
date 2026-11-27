"""湿实验提案的目标版本/归属读取（v1.10.56，P4）。

只返回哈希/归属，不把 D4 原始值写入提案表；版本用于审核时检测目标是否在
提案提交后被别人修改。``target_type`` 取值：specimen / isolate / library / lab。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

ABSENT = "absent"


def _hash(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode(
            "utf-8"
        )
    ).hexdigest()


def target_exists(home: Path | str, target_type: str, target_id: str) -> bool:
    root = Path(home)
    db = root / "data" / "bacmap.sqlite"
    if target_type == "specimen":
        from bacmap.store.specimens import SpecimenService

        with SpecimenService(db) as store:
            return store.get(target_id) is not None
    if target_type == "isolate":
        from bacmap.store.isolates import IsolateService

        with IsolateService(db) as store:
            return store.get(target_id) is not None
    if target_type == "library":
        from bacmap.store.catalog import library_exists

        return library_exists(root, target_id)
    if target_type == "lab":
        from bacmap.store.lab_results import LabResultService

        with LabResultService(db) as store:
            return store.get_by_id(target_id) is not None
    return False


def target_owner(home: Path | str, target_type: str, target_id: str) -> str:
    root = Path(home)
    db = root / "data" / "bacmap.sqlite"
    if target_type == "specimen":
        from bacmap.store.specimens import SpecimenService

        with SpecimenService(db) as store:
            specimen_row = store.get(target_id)
        return str((specimen_row or {}).get("owner_user_id") or "")
    if target_type == "isolate":
        from bacmap.store.catalog import owner_for_isolate

        return owner_for_isolate(root, target_id)
    if target_type == "library":
        from bacmap.store.catalog import library_identity

        return str(library_identity(root, target_id).get("owner_user_id") or "")
    if target_type == "lab":
        from bacmap.store.lab_results import LabResultService

        with LabResultService(db) as store:
            lab_row = store.get_by_id(target_id)
        if lab_row is None:
            return ""
        if lab_row.subject_type == "specimen":
            from bacmap.store.specimens import SpecimenService

            with SpecimenService(db) as store:
                subject = store.get(lab_row.subject_id or lab_row.strain_id)
            return str((subject or {}).get("owner_user_id") or "")
        from bacmap.store.catalog import owner_for_isolate

        return owner_for_isolate(root, lab_row.subject_id or lab_row.strain_id)
    return ""


def target_version(home: Path | str, target_type: str, target_id: str) -> str:
    root = Path(home)
    db = root / "data" / "bacmap.sqlite"
    if target_type == "specimen":
        from bacmap.store.specimen_metadata import SpecimenMetadataService

        with SpecimenMetadataService(db) as store:
            data = store.get(target_id)
        return ABSENT if data is None else _hash(data)
    if target_type == "isolate":
        from bacmap.store.strain_metadata import StrainMetadataService

        with StrainMetadataService(db) as store:
            meta = store.get(target_id)
        return (
            ABSENT
            if meta is None
            else _hash(
                {
                    "data": meta.to_dict(),
                    "extra": meta.extra,
                    "updated_at": meta.updated_at,
                }
            )
        )
    if target_type == "library":
        from bacmap.store.catalog import library_links
        from bacmap.store.library_metadata import LibraryMetadataService

        with LibraryMetadataService(db) as store:
            library_row = store.get(target_id)
        return _hash({"row": library_row, "links": library_links(root, target_id)})
    if target_type == "lab":
        from bacmap.store.lab_results import LabResultService

        with LabResultService(db) as store:
            lab_row = store.get_by_id(target_id)
        return ABSENT if lab_row is None else _hash(lab_row.to_dict())
    return ABSENT
