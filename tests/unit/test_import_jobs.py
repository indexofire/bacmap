"""导入提案存储（v1.10.53）：上传文件只进入 pending_review，不写业务数据。"""

from __future__ import annotations

from pathlib import Path

from bacmap.store.import_jobs import ImportJobService


def test_import_job_lifecycle(tmp_path: Path):
    db = tmp_path / "data" / "bacmap.sqlite"
    upload = tmp_path / "uploads" / "wetlab.xlsx"
    upload.parent.mkdir(parents=True)
    upload.write_bytes(b"fake")
    with ImportJobService(db) as svc:
        job = svc.create(
            job_id="job-1",
            filename="wetlab.xlsx",
            file_sha256="abc",
            file_path=upload,
            created_by="alice",
            sheet_args={"lab_sheet": "lab"},
            summary={"lab_rows": 2},
            errors=[],
        )
        assert job["status"] == "pending_review"
        assert svc.count(created_by="alice") == 1
        assert svc.count(created_by="bob") == 0
        assert [j["job_id"] for j in svc.list(created_by="alice")] == ["job-1"]
        reviewed = svc.mark_reviewed(
            "job-1", status="submitted", reviewed_by="analyst", task_id="t1"
        )
        assert reviewed is not None and reviewed["status"] == "submitted"
        assert reviewed["task_id"] == "t1"
        # 状态机只允许从 pending_review 迁移一次
        assert svc.mark_reviewed(
            "job-1", status="rejected", reviewed_by="analyst"
        ) is None

def test_edit_proposal_payload_and_cleanup(tmp_path: Path):
    db = tmp_path / "data" / "bacmap.sqlite"
    with ImportJobService(db) as svc:
        job = svc.create(
            job_id="wet-1",
            filename="specimen:SP-1",
            file_sha256="",
            file_path=None,
            created_by="alice",
            sheet_args={},
            summary={"operation": "specimen_metadata"},
            errors=[],
            kind="edit",
            payload=[{"kind": "specimen_metadata", "specimen_id": "SP-1", "data": {}}],
            target_type="specimen",
            target_id="SP-1",
            base_version="absent",
        )
        assert job["kind"] == "edit"
        assert job["payload"][0]["specimen_id"] == "SP-1"
        assert job["base_version"] == "absent"
        assert svc.list(kind="edit")[0]["job_id"] == "wet-1"
        assert svc.count(kind="edit") == 1
        assert svc.expire_pending("2999-01-01T00:00:00+00:00") == 1
        assert svc.get("wet-1")["status"] == "expired"
        assert svc.terminal_before("2999-01-01T00:00:00+00:00")[0]["job_id"] == "wet-1"
        assert svc.delete("wet-1") is True
        assert svc.get("wet-1") is None
