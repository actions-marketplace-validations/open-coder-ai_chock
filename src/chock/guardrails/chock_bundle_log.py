"""The toggle wrapper's log line. Stdlib only: shipped beside the wrapper, with the gate's journal, in every merged plugin."""

from __future__ import annotations

from pathlib import Path

try:  # beside the wrapper in a merged plugin; inside the chock package everywhere else
    from chock_journal import LOG_INFO, LOG_OFF, log_append, log_settings
except ImportError:
    from chock.gate.runner.journal import LOG_INFO, LOG_OFF, log_append, log_settings

_LOG_PARTS = ("log", "gate-events.jsonl")


def _repo(start: Path) -> Path | None:
    here = Path(start).absolute()
    return next((folder for folder in (here, *here.parents) if (folder / ".git").exists()), None)


def log_off(governing: Path, bundle: str, member: str) -> None:
    """One info line in chock's log beside the governing file, unless the level is off. Best effort: never raises."""
    try:
        level, size = log_settings(_repo(Path.cwd()))
        if level == LOG_OFF:
            return
        record = {"route": "plugin", "level": LOG_INFO, "policy_id": member, "surface": "plugin", "event": "toggle"}
        record |= {"kind": "guardrails-off", "bundle": bundle, "verdict": "off"}
        log_append(governing.parent.joinpath(*_LOG_PARTS), record, size)
    except Exception:  # noqa: BLE001 -- a log line must never change the verdict
        return
