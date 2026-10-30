"""What the decision log says ran: hook records per surface, and the session_start heartbeats."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from chock.doctor.targets import ROUTE_SYNC, Target
from chock.gate.decision_log import dlog_plugin_manifest
from chock.gate.plugin_manifests import plugin_manifests
from chock.gatelog_read import LOG_DIR, LOG_NAME, PLUGIN_LOG_NAME, PLUGIN_ROTATED_NAME, ROTATED_NAME

HEARTBEAT = "session_start"


def _files(target: Target) -> list[Path]:
    if target.route == ROUTE_SYNC:
        folder = target.root / ".chock" / LOG_DIR
        return [folder / ROTATED_NAME, folder / LOG_NAME]
    folder = Path(os.path.expanduser("~")) / ".chock" / LOG_DIR / target.agent
    return [folder / PLUGIN_ROTATED_NAME, folder / PLUGIN_LOG_NAME]


def _lines(path: Path) -> list[dict[str, Any]]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    found = []
    for line in text.splitlines():
        try:
            record = json.loads(line) if line.strip() else None
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict) and isinstance(record.get("ts"), str):
            found.append(record)
    return found


def records(target: Target) -> list[dict[str, Any]]:
    """This target's own records, oldest first: its agent, and on the plugin route its plugin's name."""
    plugin = dlog_plugin_manifest(target.runtime, plugin_manifests())[0] if target.route != ROUTE_SYNC else None
    mine = [
        r
        for path in _files(target)
        for r in _lines(path)
        if r.get("agent") == target.agent and (plugin is None or r.get("plugin") in (plugin, None))
    ]
    return sorted(mine, key=lambda r: r["ts"])


def split(found: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(heartbeats, hook records)."""
    beats = [r for r in found if r.get("event") == HEARTBEAT]
    return beats, [r for r in found if r.get("event") != HEARTBEAT]


def last_by_surface(hooks: list[dict[str, Any]]) -> dict[str, str]:
    """{surface: the newest record's ts}."""
    last: dict[str, str] = {}
    for record in hooks:
        last[str(record.get("surface") or record.get("event") or "?")] = record["ts"]
    return dict(sorted(last.items()))
