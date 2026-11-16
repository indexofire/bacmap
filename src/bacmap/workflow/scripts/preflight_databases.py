"""Snakemake database preflight: fail fast, never download (v1.10.38)."""

import json
import os
import sys
from pathlib import Path


def main() -> None:
    home = Path(snakemake.params.home)  # type: ignore[name-defined]
    workdir = Path(snakemake.params.workdir)  # type: ignore[name-defined]
    request_path = workdir / ".bacmap_request.json"
    samples: list[str] = []
    annotation = True
    if request_path.is_file():
        try:
            request = json.loads(request_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            request = {}
        samples = [str(item) for item in request.get("samples") or []]
        annotation = bool(request.get("annotation", True))
    if not samples:
        samples = [item for item in str(snakemake.params.samples).split() if item]  # type: ignore[name-defined]
    if os.environ.get("BACMAP_ANNOTATION_ENABLED", "1").strip().lower() in {"0", "false", "no", "off"}:
        annotation = False

    from bacmap.core.pipeline.resources import preflight_resources

    report = preflight_resources(home, samples, annotation=annotation)
    target = Path(snakemake.output[0])  # type: ignore[name-defined]
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report.as_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    if report.ok:
        return
    print("数据库预检失败：\n" + report.failure_message(), file=sys.stderr)
    raise SystemExit(1)


main()
