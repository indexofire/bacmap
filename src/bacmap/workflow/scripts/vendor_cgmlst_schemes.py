#!/usr/bin/env python3
"""Vendor EnteroBase cgMLST schemes locally via `gmlst scheme download`.

Build-time helper. NOT part of the Snakemake DAG — invoked manually by an
operator (or future CI step) to populate `data/reference/cgmlst/<scheme>/`
with a pinned copy of each scheme and a `.meta.json` recording provenance
(download timestamp, locus count, provider, content sha256).

Usage:
    python workflows/bacmap/scripts/vendor_cgmlst_schemes.py
    python workflows/bacmap/scripts/vendor_cgmlst_schemes.py --schemes senterica_2,ecoli_2
    python workflows/bacmap/scripts/vendor_cgmlst_schemes.py --output-dir /tmp/cgmlst

Network-dependent: shells out to `gmlst scheme download` (EnteroBase upstream).
The gmlst binary must be on PATH or resolvable via the pixi env at
`.pixi/envs/default/bin/gmlst`.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUTPUT_DIR = ROOT / "data" / "reference" / "cgmlst"
DEFAULT_GMLST_BIN = "gmlst"
PROVIDER = "EnteroBase"

ALL_SCHEMES = ("senterica_2", "ecoli_2", "vparahaemolyticus_3")


def _resolve_gmlst_bin(explicit: str | None) -> str:
    if explicit:
        return explicit
    if Path(DEFAULT_GMLST_BIN).exists():
        return DEFAULT_GMLST_BIN
    found = shutil.which("gmlst")
    if not found:
        raise FileNotFoundError(
            "gmlst binary not found: pass --gmlst-bin, install via `pixi install`, "
            f"or ensure gmlst is on PATH (default tried: {DEFAULT_GMLST_BIN})"
        )
    return found


def _gmlst_version(gmlst_bin: str) -> str:
    try:
        out = subprocess.run(
            [gmlst_bin, "--version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        combined = (out.stdout + out.stderr).strip()
        return combined.splitlines()[0] if combined else "unknown"
    except (subprocess.SubprocessError, OSError) as exc:
        print(f"  ! could not determine gmlst version: {exc}", file=sys.stderr)
        return "unknown"


def _count_loci(scheme_dir: Path) -> int:
    """Count locus files in a downloaded scheme directory.

    gmlst scheme download lays down one FASTA per locus (typically *.tfa).
    Any file ending in .tfa/.fasta/.fa is counted; falls back to all files
    if no recognized extension is present.
    """
    if not scheme_dir.exists() or not scheme_dir.is_dir():
        return 0
    candidates = [
        p for p in scheme_dir.iterdir()
        if p.is_file() and p.suffix.lower() in {".tfa", ".fasta", ".fa", ".fna"}
    ]
    if candidates:
        return len(candidates)
    return sum(1 for p in scheme_dir.iterdir() if p.is_file())


def _content_sha256(scheme_dir: Path) -> str:
    """SHA-256 over the concatenation of all sorted locus file contents."""
    h = hashlib.sha256()
    if not scheme_dir.exists():
        return h.hexdigest()
    for locus in sorted(p for p in scheme_dir.iterdir() if p.is_file()):
        h.update(locus.name.encode("utf-8"))
        h.update(b"\0")
        with locus.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                h.update(chunk)
    return h.hexdigest()


def _download_scheme(gmlst_bin: str, scheme: str, scheme_dir: Path) -> None:
    """Invoke `gmlst scheme download -s <scheme>` into scheme_dir.

    gmlst creates the destination directory; we ensure the parent exists.
    If scheme_dir already exists, it is removed first to give a clean
    re-download (idempotent vendoring).
    """
    scheme_dir.parent.mkdir(parents=True, exist_ok=True)
    if scheme_dir.exists():
        shutil.rmtree(scheme_dir)
    cmd = [gmlst_bin, "scheme", "download", "-s", scheme]
    print(f"  $ {' '.join(cmd)} -> {scheme_dir}")
    result = subprocess.run(cmd, cwd=str(scheme_dir.parent), capture_output=True, text=True)
    if result.returncode != 0:
        msg = (
            f"gmlst scheme download failed for {scheme} (exit {result.returncode})\n"
            f"stdout: {result.stdout.strip()}\n"
            f"stderr: {result.stderr.strip()}"
        )
        raise RuntimeError(msg)
    if not scheme_dir.exists():
        # gmlst may name the output dir after the scheme; verify it landed.
        candidates = [p for p in scheme_dir.parent.iterdir() if p.is_dir()]
        raise RuntimeError(
            f"gmlst scheme download reported success for {scheme} but "
            f"expected dir {scheme_dir} is missing. Inspected siblings: "
            f"{[p.name for p in candidates]}"
        )


def vendor_scheme(
    scheme: str,
    output_dir: Path,
    gmlst_bin: str,
) -> dict:
    """Download one scheme + write its `.meta.json`. Returns the meta dict."""
    print(f"\n=== Vendoring scheme: {scheme} ===")
    scheme_dir = output_dir / scheme
    _download_scheme(gmlst_bin, scheme, scheme_dir)
    locus_count = _count_loci(scheme_dir)
    sha = _content_sha256(scheme_dir)
    meta = {
        "downloaded_at": _dt.datetime.now(_dt.UTC).isoformat(timespec="seconds"),
        "locus_count": locus_count,
        "scheme": scheme,
        "provider": PROVIDER,
        "content_sha256": sha,
        "gmlst_version": _gmlst_version(gmlst_bin),
    }
    meta_path = scheme_dir / ".meta.json"
    meta_path.write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n")
    print(f"  ✓ {scheme}: {locus_count} loci, sha256={sha[:12]}...")
    print(f"  ✓ wrote {meta_path}")
    return meta


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Vendor EnteroBase cgMLST schemes via `gmlst scheme download`. "
            "Build-time helper; not part of the Snakemake DAG."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Default schemes (all 4 are vendored if --schemes is omitted): "
            + ", ".join(ALL_SCHEMES)
        ),
    )
    parser.add_argument(
        "--schemes",
        type=str,
        default=",".join(ALL_SCHEMES),
        help="Comma-separated list of scheme names to vendor (default: all 4)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Root directory to vendor into (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--gmlst-bin",
        type=str,
        default=None,
        help=f"Path to gmlst binary (default: {DEFAULT_GMLST_BIN}, or PATH lookup)",
    )
    args = parser.parse_args(argv)

    schemes = [s.strip() for s in args.schemes.split(",") if s.strip()]
    if not schemes:
        parser.error("--schemes must list at least one scheme")

    try:
        gmlst_bin = _resolve_gmlst_bin(args.gmlst_bin)
    except FileNotFoundError as exc:
        print(f"❌ {exc}", file=sys.stderr)
        return 2

    print(f"gmlst binary: {gmlst_bin}")
    print(f"output dir:   {args.output_dir}")
    print(f"schemes:      {', '.join(schemes)}")
    args.output_dir.mkdir(parents=True, exist_ok=True)

    failures: list[tuple[str, str]] = []
    for scheme in schemes:
        try:
            vendor_scheme(scheme, args.output_dir, gmlst_bin)
        except (RuntimeError, OSError) as exc:
            failures.append((scheme, str(exc)))
            print(f"  ✗ failed to vendor {scheme}: {exc}", file=sys.stderr)

    print(f"\nDone. {len(schemes) - len(failures)}/{len(schemes)} schemes vendored.")
    if failures:
        for scheme, err in failures:
            print(f"  ✗ {scheme}: {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
