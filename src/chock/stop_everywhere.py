"""`chock stop --everywhere` and `chock resume --everywhere`: a person's stop on every agent on this machine.

The file is `~/.chock/stops/_everywhere.json`, beside the per-repo registry entries; every hook reads it fail-closed
(chock.gate.runner.halt). It sends nothing over the network.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from chock.gate.runner.actor import git_email
from chock.gate.runner.halt import HALT_ALL, halt_everywhere_entry, halt_everywhere_read, halt_repos
from chock.gate.runner.journal import log_now, log_trace_text
from chock.stop_common import LIMITS, UNKNOWN, agent_refused, log_stop, printable, write_private

#: The word a person types to resume: the repository name's equivalent for a stop that names no repository.
CONFIRM_WORD = "everywhere"
_MARK = {"everywhere": True}
_PER_REPO = (
    "Per-repository stops (`chock stop`) are not lifted: `chock status` in a repository shows one in force, "
    "and `chock resume` there lifts it.\n"
)


def _log_repo(repo: Path) -> Path | None:
    """The repository the command runs in, whose log takes its line; None outside every repository."""
    found = halt_repos(repo)
    return found[0] if found else None


def everywhere_line() -> str | None:
    """The line `chock status` and `chock doctor` lead with while the machine-wide stop is in force."""
    stop = halt_everywhere_read()
    if stop is None:
        return None
    if stop.get("unreadable"):
        return (
            f"STOPPED EVERYWHERE: {halt_everywhere_entry()} cannot be read, so every agent on this machine is "
            "refused. `chock resume --everywhere` removes it."
        )
    who, when = printable(stop.get("who") or UNKNOWN), printable(stop.get("when") or UNKNOWN)
    reason = printable(stop.get("reason") or "no reason given")
    return (
        f"STOPPED EVERYWHERE: every agent on this machine, by {who} at {when}: {reason}. Their tool calls, commits "
        "and pushes are refused in every repository; `chock resume --everywhere` lifts it."
    )


def stop_everywhere(repo: Path, agent: str | None, reason: str) -> int:
    """Write the machine-wide stop: every agent's tool calls, commits and pushes are refused until resume."""
    if agent:
        sys.stderr.write("chock stop: --everywhere stops every agent; it takes no --agent.\n")
        return 2
    log_repo = _log_repo(repo)
    if agent_refused(log_repo, "repo_stop", _MARK):
        return 1
    doc = {"scope": HALT_ALL, "reason": reason, "who": git_email(log_repo) or UNKNOWN, "when": log_now(), **_MARK}
    entry = halt_everywhere_entry()
    try:
        write_private(entry, json.dumps(doc, indent=2) + "\n")
    except OSError as exc:
        sys.stderr.write(f"chock stop: {entry} was not written: {exc}; nothing is stopped.\n")
        return 1
    log_stop(log_repo, "repo_stop", {**doc, "reason": log_trace_text(reason)})
    sys.stdout.write(f"{everywhere_line()}\n{LIMITS}\n")
    return 0


def _person_confirms() -> bool:
    """Only a person at their own terminal resumes: stdin and stdout are TTYs and they type `everywhere`."""
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        sys.stderr.write(
            "chock resume: refused: it needs a person at a terminal (stdin and stdout are not a TTY). "
            "Run `chock resume --everywhere` yourself, in your own terminal.\n"
        )
        return False
    sys.stdout.write(f"Type {CONFIRM_WORD!r} to resume every agent on this machine: ")
    sys.stdout.flush()
    if sys.stdin.readline().strip() == CONFIRM_WORD:
        return True
    sys.stderr.write("chock resume: the word typed does not match; the machine-wide stop is still in force.\n")
    return False


def resume_everywhere(repo: Path) -> int:
    """Remove the machine-wide stop. Per-repository stops stay in force."""
    log_repo = _log_repo(repo)
    if agent_refused(log_repo, "repo_resume", _MARK) or not _person_confirms():
        return 1
    entry = halt_everywhere_entry()
    if not os.path.lexists(entry):
        sys.stdout.write("No machine-wide stop; nothing to resume.\n" + _PER_REPO)
        return 0
    try:
        entry.unlink()
    except OSError as exc:
        sys.stderr.write(
            f"chock resume --everywhere: {entry} was not removed ({exc}); the machine-wide stop is still in force.\n"
        )
        return 1
    log_stop(
        log_repo, "repo_resume", {"scope": HALT_ALL, "who": git_email(log_repo) or UNKNOWN, "when": log_now(), **_MARK}
    )
    sys.stdout.write("Resumed everywhere: the machine-wide stop is lifted.\n" + _PER_REPO)
    return 0
