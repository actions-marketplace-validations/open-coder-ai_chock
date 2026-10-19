"""What `chock stop` and `chock stop --everywhere` share: the actor rule, the log line, the private write."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from chock.gate.runner.actor import actor_of, agent_signal
from chock.gate.runner.halt import HALT_POLICY, HALT_REASON
from chock.gate.runner.journal import log_write

LOG_PARTS = (".chock", "log", "gate-events.jsonl")
UNKNOWN = "unknown"
#: The log's policy id for a refused person-only command (`chock sync`, `enable`, `disable`, ...).
PERSON_ONLY_POLICY = "chock-cli"
_STOP_RULE = "Only a person stops or resumes agents; they run this from their own shell."
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
    record["actor"] = actor_of(agent_signal(repo))
    try:
        log_write(repo.joinpath(*LOG_PARTS), record, repo)
    except OSError as exc:
        sys.stderr.write(f"chock: the stop is in place, but its log line was not written: {exc}\n")


def agent_refused(
    repo: Path | None, event: str, fields: dict[str, object] | None = None, *, rule: str = _STOP_RULE
) -> bool:
    """The actor rule: an agent's `chock stop`, `resume` or person-only command is refused, with `rule` said, and
    logged."""
    signal = agent_signal(repo)
    if signal is None:
        return False
    sys.stderr.write(f"chock: refused: this shell is marked as an agent's ({signal}). {rule}\n")
    log_stop(repo, event, {"verdict": "block", "reason": HALT_REASON, **(fields or {})})
    return True


def person_only_refused(repo: Path, command: str) -> bool:
    """`chock <command>` changes what chock enforces here (its config, lock or compiled tree): an agent's call is
    refused and logged, so a wrapper script that edits `.chock/config.yaml` cannot make `chock sync` apply it."""
    fields = {"policy_id": PERSON_ONLY_POLICY, "reason": "agent", "command": command}
    rule = f"Only a person changes what chock enforces here; a person runs `chock {command}` from their own shell."
    return agent_refused(repo, command, fields, rule=rule)


def write_private(path: Path, text: str) -> None:
    """Write `path` whole, readable by its owner alone (0o600), in a folder only they can list (0o700)."""
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    staged = path.with_name(f".{path.name}.{os.getpid()}")
    with os.fdopen(os.open(staged, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w", encoding="utf-8") as out:
        out.write(text)
    os.replace(staged, path)
