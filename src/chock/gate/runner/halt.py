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


def halt_covers(stop, client):
    """Whether `stop` reaches `client`: every agent, or the one named. An agent naming no client is reached."""
    scope = stop.get("scope")
    if scope == HALT_ALL or not client or client == "unknown":
        return True
    return client == scope or scope.startswith(str(client) + "_")


def halt_message(stop):
    """`stopped: <reason>`, the reason printable and capped, and the one way to lift it."""
    reason = "".join(ch for ch in str(stop.get("reason") or "") if ch.isprintable()).strip()
    reason = (reason or _HALT_NO_REASON)[:_HALT_REASON_CAP]
    return (
        f"{HALT_REASON}: {reason}. A person stopped agents in this repository (`chock stop`); "
        "every tool call is refused until they run `chock resume`."
    )
