"""The repo stop (`chock stop`): `.chock/stop.json` read fail-closed. Stdlib only; gate.py and every runtime carry it."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

# >>> gate.py 21
#: A person's stop for one repository: local state, never committed (`chock init` ignores it).
HALT_PARTS = (".chock", "stop.json")
HALT_ALL = "all"
#: The decision log's reason for every call a stop refused.
HALT_REASON = "stopped"
#: The policy id the log files a refusal under when no policy's hook made it, and the stop and resume lines.
HALT_POLICY = "chock-stop"
#: A client id as `--agent` takes it and a scope is written: anything else reads as every agent.
HALT_CLIENT_RE = re.compile(r"^[a-z0-9_]{1,32}$")
#: The runtime flag of the repo stop's own pre-tool hook, which `chock sync` wires for every client.
HALT_HOOK_FLAG = "--stop-check"
#: Every in-agent client id (`chock.vendors.in_agent_vendors()`, pinned by a test): a git marker naming
#: none of them cannot be told apart from a stopped client, so any stop reaches it.
HALT_CLIENTS = (
    "antigravity",
    "claude_code",
    "codex_cli",
    "cursor",
    "devin",
    "factory_droid",
    "gemini_cli",
    "goose",
    "grok",
    "mistral_vibe",
    "openhands",
    "tabnine",
    "vscode_copilot",
    "windsurf",
)
_HALT_GITDIR = "gitdir:"
_HALT_REASON_CAP = 200
_HALT_UNREADABLE = ".chock/stop.json exists but cannot be read, so every agent is refused"
_HALT_NO_REASON = "no reason given"


def halt_read(repo_root):
    """The stop in force for `repo_root` as {scope, reason, ...}, or None. A file that exists but cannot be
    read or parsed, or names no valid scope, stops every agent: fail closed."""
    if repo_root is None:
        return None
    path = Path(repo_root).joinpath(*HALT_PARTS)
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, NotADirectoryError):
        return {"scope": HALT_ALL, "reason": _HALT_UNREADABLE, "unreadable": True} if os.path.lexists(path) else None
    except (OSError, UnicodeError, ValueError):
        return {"scope": HALT_ALL, "reason": _HALT_UNREADABLE, "unreadable": True}
    scope = doc.get("scope") if isinstance(doc, dict) else None
    if not isinstance(scope, str) or not (scope == HALT_ALL or HALT_CLIENT_RE.match(scope)):
        return {"scope": HALT_ALL, "reason": _HALT_UNREADABLE, "unreadable": True}
    reason = doc.get("reason")
    return {**doc, "scope": scope, "reason": reason if isinstance(reason, str) else ""}


def halt_main_root(repo_root):
    """The main worktree of the linked worktree at `repo_root` (its `.git` is a file naming a gitdir whose
    `commondir` leads to the main `.git`), else None. Read from disk: the runtime cannot wait on git."""
    dot = Path(repo_root) / ".git"
    try:
        text = dot.read_text(encoding="utf-8").strip() if dot.is_file() else ""
        if not text.startswith(_HALT_GITDIR):
            return None
        gitdir = Path(repo_root) / text[len(_HALT_GITDIR) :].strip()  # an absolute gitdir replaces the root
        common = gitdir.joinpath("commondir").read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        return None  # a submodule's gitdir has no commondir: it is no linked worktree
    common_dir = Path(os.path.realpath(gitdir / common))
    return common_dir.parent if common_dir.name == ".git" else None


def halt_repos(path):
    """Every repository holding `path`, nearest first: each folder up from it with a `.git`, nested ones included."""
    try:
        here = Path(os.path.abspath(str(path)))
    except (OSError, ValueError):
        return []
    return [folder for folder in (here, *here.parents) if os.path.lexists(folder / ".git")]


def halt_find(roots, client):
    """The first stop in force over `roots`, or in the main worktree of any of them, that reaches `client`."""
    seen = []
    for root in roots:
        for folder in (root, halt_main_root(root)):
            if folder is None or folder in seen:
                continue
            seen.append(folder)
            stop = halt_read(folder)
            if stop is not None and halt_covers(stop, client):
                return stop
    return None


def _halt_client(name):
    return str(name or "").strip().lower().replace("-", "_")


def _halt_names(client, named):
    """Whether `client` (from a marker or a bundle) names the client id `named`, or a shorter form of it."""
    return client.startswith(named) or named.startswith(client + "_")


def halt_covers(stop, client):
    """Whether `stop` reaches `client`: every agent, or the one named (`cursor_agent` is `cursor`'s; `codex` may
    be `codex_cli`). An agent naming no client, or one no in-agent client id matches, is reached: fail closed."""
    scope, client = _halt_client(stop.get("scope")), _halt_client(client)
    if scope == HALT_ALL or not client:
        return True
    return _halt_names(client, scope) or not any(_halt_names(client, known) for known in HALT_CLIENTS)


def halt_message(stop):
    """`stopped: <reason>`, the reason printable and capped, and the one way to lift it."""
    reason = "".join(ch for ch in str(stop.get("reason") or "") if ch.isprintable()).strip()
    reason = (reason or _HALT_NO_REASON)[:_HALT_REASON_CAP]
    return (
        f"{HALT_REASON}: {reason}. A person stopped agents in this repository (`chock stop`); "
        "every tool call is refused until they run `chock resume`."
    )
