"""Read-only tool catalogs + agent selection-options tool.

``gapit db list --json`` and ``gmlst scheme list/show -f json`` are the live
sources of database/scheme facts.  The species defaults stay in
``core/pathogens.yaml``; this module never invents a mapping.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from bacmap.core.tool_selection import (
    SelectionError,
    is_legacy_path,
    load_selection,
    resolve_selection_path,
)
from bacmap.core.tool_selection_validate import (
    DbCatalogEntry,
    GmlstScheme,
    build_options,
    parse_catalog,
    parse_gmlst_schemes,
)
from bacmap.tools._common import tool_handler


def fetch_gapit_catalog(
    *, datadir: str | None = None, gapit: str | None = None, timeout: int = 60
) -> dict[str, DbCatalogEntry]:
    """Fetch ``gapit db list --json``; an unavailable gapit returns ``{}``."""
    executable = gapit or shutil.which("gapit")
    if not executable:
        return {}
    cmd = [executable, "db", "list", "--json"]
    if datadir:
        cmd += ["--datadir", datadir]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return {}
    if proc.returncode != 0 or not proc.stdout.strip():
        return {}
    try:
        payload = json.loads(proc.stdout)
    except ValueError:
        return {}
    if not isinstance(payload, dict):
        return {}
    try:
        return parse_catalog(payload)
    except SelectionError:
        return {}


# Backward-compatible name for call sites written before the v1.4.40 rename.
fetch_catalog = fetch_gapit_catalog


def fetch_gmlst_schemes(
    *,
    gmlst: str | None = None,
    downloaded_only: bool = False,
    name_pattern: str = "",
    timeout: int = 120,
) -> dict[str, GmlstScheme]:
    """Fetch ``gmlst scheme list -f json``; unavailable gmlst returns ``{}``."""
    executable = gmlst or shutil.which("gmlst")
    if not executable:
        return {}
    cmd = [executable, "scheme", "list", "-f", "json"]
    if downloaded_only:
        cmd.append("-a")
    if name_pattern:
        cmd += ["-n", name_pattern]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return {}
    if proc.returncode != 0 or not proc.stdout.strip():
        return {}
    try:
        payload = json.loads(proc.stdout)
    except ValueError:
        return {}
    if not isinstance(payload, dict):
        return {}
    try:
        return parse_gmlst_schemes(payload)
    except SelectionError:
        return {}


def fetch_gmlst_scheme(
    name: str, *, gmlst: str | None = None, timeout: int = 60
) -> GmlstScheme | None:
    """Fetch one scheme via ``gmlst scheme show NAME -f json``."""
    executable = gmlst or shutil.which("gmlst")
    if not executable:
        return None
    try:
        proc = subprocess.run(
            [executable, "scheme", "show", name, "-f", "json"],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    try:
        payload = json.loads(proc.stdout)
    except ValueError:
        return None
    if not isinstance(payload, dict):
        return None
    try:
        return parse_gmlst_schemes(payload).get(name)
    except SelectionError:
        return None


def options_payload(
    *,
    tool: str = "all",
    species: str = "",
    datadir: str = "",
    selection_path: str = "",
    home: str = "",
    include_remote_schemes: bool = True,
) -> dict[str, Any]:
    """Build the ``bacmap.tool_selection_options/1`` document."""
    home_path = Path(home).expanduser() if home else None
    selection = load_selection(selection_path or None, home=home_path)
    resolved = resolve_selection_path(selection_path or None, home=home_path)

    selected_tool = tool.strip().lower()
    if selected_tool not in {"gapit", "gmlst", "all"}:
        raise SelectionError(f"unknown tool: {tool!r} (gapit|gmlst|all)")
    gapit_catalog = (
        fetch_gapit_catalog(datadir=datadir or None)
        if selected_tool in {"gapit", "all"}
        else None
    )
    gmlst_catalog = (
        fetch_gmlst_schemes(downloaded_only=not include_remote_schemes)
        if selected_tool in {"gmlst", "all"}
        else None
    )
    document = build_options(
        selection,
        catalog=gapit_catalog,
        gmlst_catalog=gmlst_catalog,
        species=species or None,
        selection_path=str(resolved or ""),
        legacy_selection=is_legacy_path(resolved),
    )
    return document.model_dump(by_alias=True, mode="json")


@tool_handler
def tool_selection_options(args: dict[str, Any], **kwargs: Any) -> str:
    """Agent tool: list species defaults + live gapit/gmlst catalogs.

    Read-only (L1/D0).  Use the returned ``default``/``selected`` flags to
    propose a ``tool_selection.yaml``; write it through the CLI or a task,
    never by inventing database/scheme names.
    """
    payload = options_payload(
        tool=str(args.get("tool") or "all"),
        species=str(args.get("species") or ""),
        datadir=str(args.get("datadir") or ""),
        selection_path=str(args.get("selection_path") or ""),
        home=str(args.get("home") or ""),
        include_remote_schemes=bool(args.get("include_remote_schemes", True)),
    )
    return json.dumps(payload, ensure_ascii=False, indent=2)


# Backward-compatible handler name (not registered as a second MCP tool).
gapit_db_options = tool_selection_options
