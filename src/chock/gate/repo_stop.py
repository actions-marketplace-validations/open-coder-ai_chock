"""The repo stop at an agent's pre-tool hook: every tool call of an agent it reaches is refused. Stdlib only.

Runs before every guard and gate, so neither `CHOCK_ALLOW` nor the rollout level reaches it. Spec: `chock stop`.
A stop in any repository the call works in or touches counts: the session's project root as the client names it,
the runtime's own, every repository above the call's cwd and above each path its input names (nested ones
included, symlinks resolved), and the main worktree of each. A session whose client names no project root is
refused while any stop on the machine reaches its agent (the `~/.chock/stops` registry): fail closed.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

from .decision_log import DLOG_ROUTE_SYNC, runtime_route
from .runner.halt import halt_find, halt_main_root, halt_message, halt_registry_find, halt_repos
from .workspace_root import workspace_roots

#: The environment variables a client sets on its hooks to name the session's project root.
_REPO_STOP_PROJECT_ENV = ("CLAUDE_PROJECT_DIR", "GEMINI_PROJECT_DIR", "OPENHANDS_PROJECT_DIR")
#: The payload keys a client lists the session's workspace folders under, beside `workspace_roots`.
_REPO_STOP_PROJECT_KEYS = ("workspacePaths",)
_REPO_STOP_URI = "file://"
#: The longest path an OS opens; a longer string (a file's content) names nothing a call can reach.
_REPO_STOP_PATH_MAX = 4096
_REPO_STOP_ESCAPE_RE = re.compile(r"(?:%[0-9A-Fa-f]{2})+")


def _repo_stop_unquote(text):
    """`text` with each run of `%XX` escapes decoded as UTF-8, as a `file://` URI spells a path."""
    return _REPO_STOP_ESCAPE_RE.sub(
        lambda found: bytes.fromhex(found.group(0).replace("%", "")).decode("utf-8", "replace"), text
    )


def _repo_stop_path(text):
    """The path a string may name: a `file://` URI's path, else the string itself; None when it names none."""
    if text[: len(_REPO_STOP_URI)].lower() == _REPO_STOP_URI:
        rest = text[len(_REPO_STOP_URI) :]
        text = _repo_stop_unquote(rest[rest.find("/") :] if "/" in rest else "")
    return text if 0 < len(text) <= _REPO_STOP_PATH_MAX and "\x00" not in text else None


def _repo_stop_named(raw):
    """Every string anywhere in a payload that may name a path (`file://` URIs decoded): each client nests and
    spells its tool input its own way, so none is trusted to hold them all."""
    pending, found = [raw], []
    while pending:
        value = pending.pop()
        if isinstance(value, dict):
            pending.extend(value.values())
        elif isinstance(value, list):
            pending.extend(value)
        elif isinstance(value, str):
            found.append(_repo_stop_path(value))
    return [path for path in found if path]


def repo_stop_projects(event):
    """The session's project roots as the client names them (its hook environment, its payload); [] for none."""
    raw = getattr(event, "raw", None)
    listed = [raw.get(key) for key in _REPO_STOP_PROJECT_KEYS] if isinstance(raw, dict) else []
    named = [os.environ.get(name) for name in _REPO_STOP_PROJECT_ENV] + workspace_roots(event)
    named += [root for roots in listed if isinstance(roots, list) for root in roots]
    return [root for root in named if isinstance(root, str) and root]


def repo_stop_roots(event, projects=()):
    """Every repository whose stop applies to this call."""
    runtime = globals().get("__file__") or sys.argv[0]
    own = [Path(runtime).resolve().parent.parent.parent] if runtime_route(runtime) == DLOG_ROUTE_SYNC else []
    cwd = getattr(event, "cwd", None) or os.getcwd()
    named = [getattr(event, "path", None), *_repo_stop_named(getattr(event, "raw", None))]
    places = [cwd, *projects, *(os.path.join(cwd, path) for path in named if path)]
    return own + [repo for place in places for repo in halt_repos(place)]


def repo_stop_refusal(event):
    """`stopped: <reason>` when a stop reaches this pre-tool call's agent, else None. An unreadable stop refuses."""
    if getattr(event, "event", None) != "pre_tool":
        return None
    agent, projects = getattr(event, "agent", None), repo_stop_projects(event)
    roots = repo_stop_roots(event, projects)
    stop = halt_find(roots, agent)
    if stop is None:
        mains = [halt_main_root(root) for root in roots]
        stop = halt_registry_find(agent, [*roots, *filter(None, mains)] if projects else None)
    return None if stop is None else halt_message(stop)
