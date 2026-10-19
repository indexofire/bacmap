import csv
import hashlib
import json
import re
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from bacmap.config import DEPLOYED_WORKFLOWS_DIR as _DEPLOYED_WORKFLOWS_DIR

WORKFLOW_DIR = _DEPLOYED_WORKFLOWS_DIR
SAMPLES_TSV = WORKFLOW_DIR / "config" / "samples.tsv"

_SAMPLE_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")


class DatabaseDownloadError(Exception):
    """Raised when a reference database download fails prechecks or checksum."""


def _available_ram_gb() -> float:
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) / 1024 / 1024
    except OSError:
        pass
    return float("inf")


def _md5_file(path: Path) -> str:
    h = hashlib.md5()  # noqa: S324 — 非密码学用途（遗留脚本内容指纹）
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _fetch(urls: list[str], dest: Path) -> None:
    for url in urls:
        result = subprocess.run(
            ["wget", "-c", "--tries=5", "--timeout=60", "-O", str(dest), url],
        )
        if result.returncode == 0:
            return
    raise DatabaseDownloadError(f"all mirrors failed: {urls}")


def download_database(
    name: str,
    urls: list[str],
    dest_dir: Path,
    expected_md5: str | None = None,
    expected_size_gb: float = 0.0,
    min_free_gb: float = 0.0,
    min_ram_gb: float | None = None,
    manifests_dir: Path | None = None,
) -> Path:
    dest_dir = Path(dest_dir)
    manifests = Path(manifests_dir) if manifests_dir else dest_dir.parent / "manifests"
    manifest_path = manifests / f"{name}.json"
    payload = dest_dir / "payload.bin"

    if manifest_path.exists() and payload.exists():
        digest = _md5_file(payload)
        if expected_md5 is None or digest == expected_md5:
            print(f"⏭️  {name}: already installed ({dest_dir})")
            return dest_dir

    if min_ram_gb is not None and _available_ram_gb() < min_ram_gb:
        raise DatabaseDownloadError(
            f"{name}: requires >= {min_ram_gb:.0f} GB RAM, available {_available_ram_gb():.0f} GB"
        )

    need_gb = expected_size_gb * 2 + min_free_gb
    probe = dest_dir if dest_dir.exists() else Path.cwd()
    free_gb = shutil.disk_usage(probe).free / 1e9
    if free_gb < need_gb:
        raise DatabaseDownloadError(
            f"{name}: insufficient disk space — need ~{need_gb:.0f} GB, have {free_gb:.0f} GB"
        )

    print(f"⬇️  {name}: downloading (~{expected_size_gb:.1f} GB) from {urls[0]}")
    dest_dir.mkdir(parents=True, exist_ok=True)
    _fetch(urls, payload)
    digest = _md5_file(payload)
    if expected_md5 is not None and digest != expected_md5:
        payload.unlink()
        raise DatabaseDownloadError(f"{name}: md5 mismatch (got {digest}, expected {expected_md5})")

    manifests.mkdir(parents=True, exist_ok=True)
    manifest = {
        "name": name,
        "downloaded_at": datetime.now(UTC).isoformat(),
        "source_url": urls[0],
        "mirrors": urls,
        "checksum": digest,
        "checksum_algo": "md5",
        "size_bytes": payload.stat().st_size,
        "files": [payload.name],
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"✓ {name}: installed + manifest → {manifest_path}")
    return dest_dir


def validate_sample_name(name: str) -> None:
    """Reject sample names that could break shell-concatenated Snakemake commands.

    snp.smk builds shell strings by interpolating sample names; a name with
    shell metacharacters (space, ;, $, backtick, etc.) would allow command
    injection. Allow only the safe identifier charset used by real sample IDs.
    """
    if not _SAMPLE_NAME_RE.match(name):
        raise ValueError(
            f"unsafe sample name {name!r}: must match ^[A-Za-z0-9._-]+$ "
            "(shell metacharacters are rejected to prevent command injection "
            "in Snakemake rules)"
        )


def validate_all_sample_names() -> list[str]:
    """Load samples.tsv and validate every name. Returns the list of names."""
    if not SAMPLES_TSV.exists():
        print(f"❌ samples.tsv not found: {SAMPLES_TSV}")
        sys.exit(1)
    with SAMPLES_TSV.open() as f:
        names = [r["sample"] for r in csv.DictReader(f, delimiter="\t")]
    for name in names:
        validate_sample_name(name)
    return names
