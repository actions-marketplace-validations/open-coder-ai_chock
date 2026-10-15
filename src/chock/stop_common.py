"""What `chock stop` and `chock stop --everywhere` share: the actor rule, the log line, the private write."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from chock.gate.runner.actor import actor_of, stop_agent_signal
from chock.gate.runner.halt import HALT_POLICY, HALT_REASON
from chock.gate.runner.journal import log_write

LOG_PARTS = (".chock", "log", "gate-events.jsonl")
UNKNOWN = "unknown"
LIMITS = (
    "It refuses the NEXT action of an agent whose hooks Chock wires; it stops no running process "
    "and revokes no credential."
)


def printable(text: object) -> str:
    return "".join(ch for ch in str(text) if ch.isprintable())


def log_stop(repo: Path | None, event: str, fields: dict[str, object]) -> None:
    """One local line: who stopped or resumed, when, and the scope. Best effort: a log failure never undoes the act."""
    if repo is None:
        return
    record = {"route": "sync", "policy_id": HALT_POLICY, "event": event, **fields}
    record["actor"] = actor_of(stop_agent_signal(repo))
    try:
        log_write(repo.joinpath(*LOG_PARTS), record, repo)
    except OSError as exc:
        sys.stderr.write(f"chock: the stop is in place, but its log line was not written: {exc}\n")


def agent_refused(repo: Path | None, event: str, fields: dict[str, object] | None = None) -> bool:
    """Only a person changes a stop (the actor rule): an agent's `chock stop` or `chock resume` is refused, logged."""
    signal = stop_agent_signal(repo)
    if signal is None:
        return False
    sys.stderr.write(
        f"chock: refused: this shell is marked as an agent's ({signal}). Only a person stops or resumes "
        "agents; they run this from their own shell.\n"
    )
    log_stop(repo, event, {"verdict": "block", "reason": HALT_REASON, **(fields or {})})
    return True


def write_private(path: Path, text: str) -> None:
    """Write `path` whole, readable by its owner alone (0o600), in a folder only they can list (0o700)."""
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    staged = path.with_name(f".{path.name}.{os.getpid()}")
    with os.fdopen(os.open(staged, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w", encoding="utf-8") as out:
        out.write(text)
    os.replace(staged, path)
