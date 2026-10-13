"""The decision log's level and rotation size for the toggle wrapper. Stdlib only: shipped beside it in every merged plugin.

Read as chock.gate.runner.journal reads them; a test holds the two equal.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

_GATE_LOG_ENV = "CHOCK_GATE_LOG"
_LOG_LEVEL_ENV, _LOG_SETTINGS, _LOG_LEVELS = "CHOCK_LOG_LEVEL", ".chock/chock-log.json", ("off", "info", "debug")
_LOG_BYTES_RANGE = (65_536, 1_073_741_824)
_LOG_MAX_BYTES = 1_048_576
_LOG_PARTS, _LOG_ROTATED = ("log", "gate-events.jsonl"), "gate-events.1.jsonl"


def _log_scope(path: Path) -> dict:
    """One scope's valid log settings; anything unreadable or out of range is not a setting."""
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(doc, dict):
        return {}
    found = {"level": doc["level"]} if doc.get("level") in _LOG_LEVELS else {}
    size = doc.get("max_bytes")
    if type(size) is int and _LOG_BYTES_RANGE[0] <= size <= _LOG_BYTES_RANGE[1]:
        found["max_bytes"] = size
    return found


def log_settings(root: Path | None) -> tuple[str, int]:
    """(level, max_bytes): the environment, then the repository's settings file, the user's, then info and 1 MiB."""
    scopes = [
        _log_scope(path)
        for path in [*([root / _LOG_SETTINGS] if root else []), Path(os.path.expanduser("~")) / _LOG_SETTINGS]
    ]
    named = os.environ.get(_LOG_LEVEL_ENV, "").strip().lower()
    env = _LOG_LEVELS[0] if os.environ.get(_GATE_LOG_ENV) == "0" else (named if named in _LOG_LEVELS else None)
    level = env or next((scope["level"] for scope in scopes if "level" in scope), "info")
    return level, next((scope["max_bytes"] for scope in scopes if "max_bytes" in scope), _LOG_MAX_BYTES)


def _repo(start: Path) -> Path | None:
    here = Path(start).absolute()
    return next((folder for folder in (here, *here.parents) if (folder / ".git").exists()), None)


def log_off(governing: Path, bundle: str, member: str) -> None:
    """One info line in chock's log beside the governing file, unless the level is off. Best effort: never raises."""
    try:
        level, size = log_settings(_repo(Path.cwd()))
        if level == "off":
            return
        log = governing.parent.joinpath(*_LOG_PARTS)
        log.parent.mkdir(parents=True, exist_ok=True)
        if log.exists() and log.stat().st_size > size:
            log.replace(log.parent / _LOG_ROTATED)
        record = {
            "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "route": "plugin",
            "policy_id": member,
        }
        record |= {"surface": "plugin", "event": "toggle", "kind": "guardrails-off", "bundle": bundle, "verdict": "off"}
        with log.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({**record, "level": "info"}) + "\n")
    except Exception:  # noqa: BLE001 -- a log line must never change the verdict
        return
