"""`chock stop` and `chock resume`: a person's local stop on every agent tool call, commit and push in a repo.

The file is `.chock/stop.json` (never committed); the hooks read it fail-closed (chock.gate.runner.halt).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import TextIO

from chock.gate.runner.actor import actor_of, agent_signal, git_email
from chock.gate.runner.halt import HALT_ALL, HALT_PARTS, HALT_POLICY, HALT_REASON, halt_read
from chock.gate.runner.journal import log_now, log_trace_text, log_write

_LOG = (".chock", "log", "gate-events.jsonl")
_UNKNOWN = "unknown"
_LIMITS = (
    "It refuses the NEXT action of an agent whose hooks Chock wires; it stops no running process "
    "and revokes no credential."
)


def _printable(text: object) -> str:
    return "".join(ch for ch in str(text) if ch.isprintable())


def _log(repo: Path, event: str, fields: dict[str, object]) -> None:
    """One local line: who stopped or resumed, when, and the scope. Best effort: a log failure never undoes the act."""
    record = {"route": "sync", "policy_id": HALT_POLICY, "event": event, **fields}
    record["actor"] = actor_of(agent_signal(repo))
    try:
        log_write(repo.joinpath(*_LOG), record, repo)
    except OSError as exc:
        sys.stderr.write(f"chock: the stop is in place, but its log line was not written: {exc}\n")


def _agent_refused(repo: Path, event: str) -> bool:
    """Only a person changes a stop (the actor rule): an agent's `chock stop` or `chock resume` is refused, logged."""
    signal = agent_signal(repo)
    if signal is None:
        return False
    sys.stderr.write(
        f"chock: refused: this shell is marked as an agent's ({signal}). Only a person stops or resumes "
        "agents; they run this from their own shell.\n"
    )
    _log(repo, event, {"verdict": "block", "reason": HALT_REASON})
    return True


def stop_line(repo: Path) -> str | None:
    """The one line `chock status` leads with while a stop is in force, else None."""
    stop = halt_read(repo)
    if stop is None:
        return None
    if stop.get("unreadable"):
        return "STOPPED: .chock/stop.json cannot be read, so every agent is refused. `chock resume` removes it."
    scope = "every agent" if stop["scope"] == HALT_ALL else f"agent {stop['scope']}"
    who, when = _printable(stop.get("who") or _UNKNOWN), _printable(stop.get("when") or _UNKNOWN)
    reason = _printable(stop.get("reason") or "no reason given")
    return (
        f"STOPPED: {scope}, by {who} at {when}: {reason}. Its tool calls, commits and pushes are refused; "
        "`chock resume` lifts it."
    )


def print_stop(repo: Path, stream: TextIO) -> None:
    """`chock status` leads with a stop in force, before anything else it shows."""
    stopped = stop_line(repo)
    if stopped:
        stream.write(stopped + "\n")


def _repo_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--repo", default=".", help="Repo root (default: cwd)")


def stop_main(argv: list[str] | None) -> int:
    """Write `.chock/stop.json`: every tool call, commit and push by an agent in scope is refused until resume."""
    from chock.vendors import in_agent_vendors  # noqa: PLC0415 -- vendor data loads only for `chock stop`

    parser = argparse.ArgumentParser(prog="chock stop", description=stop_main.__doc__)
    _repo_arg(parser)
    parser.add_argument("--agent", choices=in_agent_vendors(), help="Stop this one client only (default: every agent)")
    parser.add_argument("--reason", default="", help="Why: the agent is told `stopped: <reason>`")
    args = parser.parse_args(argv)
    repo = Path(args.repo).resolve()
    if _agent_refused(repo, "repo_stop"):
        return 1
    doc = {"scope": args.agent or HALT_ALL, "reason": args.reason, "who": git_email(repo) or _UNKNOWN}
    doc["when"] = log_now()
    path = repo.joinpath(*HALT_PARTS)
    path.parent.mkdir(parents=True, exist_ok=True)
    staged = path.with_name(f".{path.name}.{os.getpid()}")
    staged.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    os.replace(staged, path)
    _log(repo, "repo_stop", {**doc, "reason": log_trace_text(args.reason)})
    sys.stdout.write(f"{stop_line(repo)}\n{_LIMITS}\n")
    return 0


def resume_main(argv: list[str] | None) -> int:
    """Remove `.chock/stop.json`: agents' tool calls, commits and pushes are judged by the policies again."""
    parser = argparse.ArgumentParser(prog="chock resume", description=resume_main.__doc__)
    _repo_arg(parser)
    repo = Path(parser.parse_args(argv).repo).resolve()
    if _agent_refused(repo, "repo_resume"):
        return 1
    path = repo.joinpath(*HALT_PARTS)
    stop = halt_read(repo)
    if stop is None:
        sys.stdout.write("No stop is in force here; nothing to resume.\n")
        return 0
    try:
        path.unlink()
    except OSError as exc:
        sys.stderr.write(f"chock resume: cannot remove {path}: {exc}; the stop is still in force.\n")
        return 1
    _log(repo, "repo_resume", {"scope": stop["scope"], "who": git_email(repo) or _UNKNOWN, "when": log_now()})
    sys.stdout.write(
        "Resumed: agents' tool calls, commits and pushes are judged by this repository's policies again.\n"
    )
    return 0
