"""Devin's marketplace shape: a root meta-plugin, not an index file.

Kept apart from marketplace.py so neither file crosses the 300-line review budget; this
module depends on marketplace_core, never the reverse, so importing it stays acyclic.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from chock.plugin.marketplace_core import collect_entries

#: Where a Devin marketplace's own meta-plugin manifest lives, at the dist root -- distinct
#: from a per-plugin `devin/<id>/.devin-plugin/plugin.json` built by `plugin build --format devin`.
DEVIN_ROOT_MANIFEST_REL = Path(".devin-plugin/plugin.json")

#: Kept apart from marketplace_core.DESCRIPTION: Devin's text must never claim "enforces"
#: (the vendor's plugin hooks are fail-open by design).
DEVIN_DESCRIPTION = (
    "Chock policies packaged as installable plugins. Generated from the chock-catalog; "
    "each plugin states whether it is best-effort in this client or advisory."
)


def build_devin_root_manifest(dist_root: Path, name: str, url: str) -> dict[str, Any]:
    """Devin's root meta-plugin: `optionalPlugins` git-subdir entries in place of an index file."""
    entries = collect_entries(dist_root, "devin")
    plugins = [{"source": "git-subdir", "url": url, "path": e["source"].removeprefix("./")} for e in entries]
    return {"name": name, "description": DEVIN_DESCRIPTION, "optionalPlugins": plugins}


def devin_root_manifest_differences(dist_root: Path, name: str, url: str) -> list[str]:
    """Report a Devin root manifest that is missing, stale, or hand-edited."""
    content = json.dumps(build_devin_root_manifest(dist_root, name, url), indent=2) + "\n"
    dest = Path(dist_root) / DEVIN_ROOT_MANIFEST_REL
    if not dest.exists():
        return [f"missing: {DEVIN_ROOT_MANIFEST_REL.as_posix()}"]
    return [] if dest.read_text(encoding="utf-8") == content else [f"differs: {DEVIN_ROOT_MANIFEST_REL.as_posix()}"]
