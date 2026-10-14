"""Gate runner: the best-effort gate event log."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from .actor import actor_of
from .constants import (
    _CONFIG_PATH,
    _EVENT_NAME,
    _LOG_FIELD_CAP,
    _LOG_FIELDS,
    _LOG_MATCH_CAP,
    _MIN_COMPILED_PATH_DEPTH,
    ACTION_BLOCK,
    ACTOR_AGENT_PREFIX,
)
from .context import GateResult
from .journal import log_write


# >>> gate.py 10
def _write_log(chock_root: Path, record: dict) -> None:
    """Append one sync-route record to `<chock_root>/log/gate-events.jsonl` at the level in force."""
    log_write(chock_root / "log" / "gate-events.jsonl", {"route": "sync", **record}, chock_root.parent)


def _log_outcome(
    gate_path: Path,
    event: str,
    spec: dict,
    result: GateResult,
    verdict: str,
    extra: Mapping[str, object] | None = None,
) -> None:
    """Append one outcome record. Best effort: never raises, never changes the verdict."""
    try:
        parents = gate_path.resolve().parents
        if len(parents) < _MIN_COMPILED_PATH_DEPTH or parents[2].name != "compiled":
            return
        record = {
            "policy_id": parents[1].name,
            "surface": parents[0].name,
            "event": event,
            "kind": spec.get("kind"),
            "verdict": verdict,
            "match_count": len(result.matches),
            "matches": result.matches[:_LOG_MATCH_CAP],
            **result.detail,
        }
        if result.rules:
            record["rules"] = result.rules
        record.update(extra or {})
        _write_log(parents[3], record)
    except Exception:  # noqa: BLE001 -- best effort logging: never raises, never changes the verdict
        return


# >>> gate.py 18
def _actor(signal: str | None, fields: Mapping[str, object] | None = None, *, hook: bool = False) -> dict[str, object]:
    """Who acted: the agent marker, when there is one, and `actor`; plus what an agent hook's runtime gave.

    `fields` is the runtime's `log` stdin key (session_id, actor, target), kept only as short strings. An
    agent `hook` with no marker and no runtime actor is still an agent's call: `agent:unknown`, never a person.
    """
    record: dict[str, object] = {"agent": signal} if signal else {}
    record["actor"] = actor_of(signal) if signal or not hook else ACTOR_AGENT_PREFIX + "unknown"
    for key in _LOG_FIELDS:
        value = (fields or {}).get(key)
        if isinstance(value, str) and 0 < len(value) <= _LOG_FIELD_CAP:
            record[key] = value
    return record


def _held_record(held: str, level: str) -> dict[str, object]:
    """What the log keeps of an action the rollout level lowered: the evidence for switching to enforce."""
    return {"rollout": level, "would_action": held, "would_block": held == ACTION_BLOCK}


def _log_script_hook(
    policy_id: str, event: str, verdict: str, repo_root: Path, extra: Mapping[str, object] | None = None
) -> None:
    """Record a script-backed hook's warn or ask; best effort like every gate log write."""
    try:
        record = {"policy_id": policy_id, "surface": "git-hook", "event": _EVENT_NAME.get(event, event)}
        record.update({"kind": "script-hook", "verdict": verdict, "match_count": 0, "matches": []})
        record.update(extra or {})
        _write_log(repo_root / _CONFIG_PATH[0], record)
    except Exception:  # noqa: BLE001 -- best effort logging: never raises, never changes the verdict
        return
