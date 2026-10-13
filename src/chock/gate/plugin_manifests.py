"""Where a chock-built plugin package keeps its manifest: the runtime's decision log reads the version there."""

from __future__ import annotations

import functools
import json

from agentseam import packaging

from chock.resources import package_data_dir
from chock.vendors import in_agent_vendors


@functools.cache
def plugin_manifests() -> tuple[str, ...]:
    """Every manifest path a chock-built package may carry: agentseam's layouts, then chock's own store formats."""
    layouts = (packaging.layout(agent) for agent in sorted(in_agent_vendors()))
    found = [layout["manifest"] for layout in layouts if layout and layout.get("manifest")]
    stores = sorted(package_data_dir("chock.plugin", "data", "stores").glob("*.json"))
    layouts = (json.loads(path.read_text(encoding="utf-8")).get("layout") or {} for path in stores)
    found += [layout["manifest"] for layout in layouts if layout.get("manifest")]
    return tuple(dict.fromkeys(found))
