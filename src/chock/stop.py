"""`chock stop` and `chock resume`: a person's local stop on every agent tool call, commit and push in a repo.

The file is `.chock/stop.json` (never committed), mirrored in `~/.chock/stops/` for hooks that cannot tell which
repository their session is in; the hooks read both fail-closed (chock.gate.runner.halt).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import TextIO

from chock.gate.runner.actor import git_email
from chock.gate.runner.halt import (
    HALT_ALL,
    HALT_PARTS,
    halt_find,
    halt_norm,
    halt_read,
    halt_registry_entry,
    halt_repos,
)
from chock.gate.runner.journal import log_now, log_trace_text
from chock.stop_common import LIMITS, UNKNOWN, agent_refused, log_stop, printable, write_private
from chock.stop_everywhere import everywhere_line, resume_everywhere, stop_everywhere


def _person_confirms(repo: Path) -> bool:
    """Only a person at their own terminal resumes: stdin and stdout are TTYs and they type the repository's name."""
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        sys.stderr.write(
            "chock resume: refused: it needs a person at a terminal (stdin and stdout are not a TTY). "
            "Run `chock resume` yourself, in your own terminal.\n"
        )
        return False
    sys.stdout.write(f"Type the repository name ({repo.name}) to resume agents in {repo}: ")
    sys.stdout.flush()
    typed = sys.stdin.readline().strip()
    if typed and not {"/", os.sep} & set(typed) and halt_norm(repo.parent / typed) == halt_norm(repo):
        return True
    sys.stderr.write("chock resume: the name typed does not match; the stop is still in force.\n")
    return False


def stop_line(repo: Path) -> str | None:
    """The one line `chock status` leads with while a stop is in force here, above, or in the main worktree."""
    stop = halt_find(halt_repos(repo) or [repo], None)
    if stop is None:
        return None
    if stop.get("unreadable"):
        return "STOPPED: .chock/stop.json cannot be read, so every agent is refused. `chock resume` removes it."
    scope = "every agent" if stop["scope"] == HALT_ALL else f"agent {stop['scope']}"
    who, when = printable(stop.get("who") or UNKNOWN), printable(stop.get("when") or UNKNOWN)
    reason = printable(stop.get("reason") or "no reason given")
    return (
        f"STOPPED: {scope}, by {who} at {when}: {reason}. Its tool calls, commits and pushes are refused; "
        "`chock resume` lifts it."
    )


def print_stop(repo: Path, stream: TextIO) -> None:
    """`chock status` leads with a stop in force, before anything else it shows."""
    for stopped in (everywhere_line(), stop_line(repo)):
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
    parser.add_argument("--everywhere", action="store_true", help="Stop every agent on this machine, in every repo")
    args = parser.parse_args(argv)
    repo = Path(args.repo).resolve()
    if args.everywhere:
        return stop_everywhere(repo, args.agent, args.reason)
    if agent_refused(repo, "repo_stop"):
        return 1
    doc = {"scope": args.agent or HALT_ALL, "reason": args.reason, "who": git_email(repo) or UNKNOWN}
    doc["when"] = log_now()
    path = repo.joinpath(*HALT_PARTS)
    path.parent.mkdir(parents=True, exist_ok=True)
    staged = path.with_name(f".{path.name}.{os.getpid()}")
    staged.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    os.replace(staged, path)
    log_stop(repo, "repo_stop", {**doc, "reason": log_trace_text(args.reason)})
    sys.stdout.write(f"{stop_line(repo)}\n{LIMITS}\n")
    entry = halt_registry_entry(repo)
    try:
        write_private(entry, json.dumps({**doc, "repo": os.path.realpath(repo)}, indent=2) + "\n")
    except OSError as exc:
        sys.stderr.write(
            f"chock stop: the stop is in force here, but {entry} was not written: {exc}. A hook that cannot tell "
            "which repository its session is in does not see it.\n"
        )
        return 1
    return 0


def resume_main(argv: list[str] | None) -> int:
    """Remove `.chock/stop.json`: agents' tool calls, commits and pushes are judged by the policies again."""
    parser = argparse.ArgumentParser(prog="chock resume", description=resume_main.__doc__)
    _repo_arg(parser)
    parser.add_argument("--everywhere", action="store_true", help="Lift the machine-wide stop only")
    args = parser.parse_args(argv)
    repo = Path(args.repo).resolve()
    if args.everywhere:
        return resume_everywhere(repo)
    if agent_refused(repo, "repo_resume") or not _person_confirms(repo):
        return 1
    path, entry = repo.joinpath(*HALT_PARTS), halt_registry_entry(repo)
    stop = halt_read(repo)
    if stop is None and os.path.lexists(entry):
        return _unregister(entry, "No stop file here; its machine registry entry is removed.\n")
    if stop is None:
        elsewhere = halt_find(halt_repos(repo) or [repo], None)
        where = (
            "; the one in force is in a repository above this one or in the main worktree: resume it there"
            if elsewhere
            else ""
        )
        sys.stdout.write(f"No stop file here; nothing to resume{where}.\n")
        return 0
    try:
        path.unlink()
    except OSError as exc:
        sys.stderr.write(f"chock resume: cannot remove {path}: {exc}; the stop is still in force.\n")
        return 1
    log_stop(repo, "repo_resume", {"scope": stop["scope"], "who": git_email(repo) or UNKNOWN, "when": log_now()})
    return _unregister(
        entry, "Resumed: agents' tool calls, commits and pushes are judged by this repository's policies again.\n"
    )


def _unregister(entry: Path, done: str) -> int:
    """Remove the machine registry entry; while it stays, a hook that cannot place its session still refuses."""
    try:
        entry.unlink(missing_ok=True)
    except OSError as exc:
        sys.stderr.write(f"chock resume: cannot remove {entry}: {exc}; hooks that read it still refuse.\n")
        return 1
    sys.stdout.write(done)
    return 0
