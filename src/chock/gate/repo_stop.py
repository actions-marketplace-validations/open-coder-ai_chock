"""The repo stop at an agent's pre-tool hook: every tool call of an agent it reaches is refused. Stdlib only.

Runs before every guard and gate, so neither `CHOCK_ALLOW` nor the rollout level reaches it. Spec: `chock stop`.
A stop in any repository the call works in or touches counts: the session's project root as the client names it,
the runtime's own, every repository above the call's cwd and above each path its input names (nested ones
included, symlinks resolved), and the main worktree of each. A session whose client names no project root is
refused while any stop on the machine reaches its agent (the `~/.chock/stops` registry): fail closed. The
machine-wide stop there (`chock stop --everywhere`) refuses every call, whatever its repository or session.
While no stop is near the call and none is registered, the payload is not scanned (the fast path); otherwise the
scan is capped and a call past the cap is refused.
"""

from __future__ import annotations

import os
import re
import shlex
import sys
import time
from pathlib import Path

from .decision_log import DLOG_ROUTE_SYNC, runtime_route
from .runner.halt import (
    HALT_REASON,
    halt_find,
    halt_main_root,
    halt_message,
    halt_registry_find,
    halt_repos,
)
from .workspace_root import workspace_roots

#: The environment variables a client sets on its hooks to name the session's project root.
_REPO_STOP_PROJECT_ENV = ("CLAUDE_PROJECT_DIR", "GEMINI_PROJECT_DIR", "OPENHANDS_PROJECT_DIR")
#: The payload keys a client lists the session's workspace folders under, beside `workspace_roots`.
_REPO_STOP_PROJECT_KEYS = ("workspacePaths",)
_REPO_STOP_URI = "file://"
#: The longest path an OS opens; a longer string (a file's content) names nothing a call can reach.
_REPO_STOP_PATH_MAX = 4096
_REPO_STOP_ESCAPE_RE = re.compile(r"(?:%[0-9A-Fa-f]{2})+")
#: The most a payload scan reads while a stop is registered: distinct strings, their characters, seconds.
_REPO_STOP_CAP_STRINGS = 256
_REPO_STOP_CAP_CHARS = 64 * 1024
_REPO_STOP_CAP_SECONDS = 2.0
_REPO_STOP_OVER_CAP = (
    f"{HALT_REASON}: a person stopped agents in a repository on this machine (`chock stop`), and this call names "
    "more paths than the stop check reads, so it cannot tell the call stays out of it. Split the call; "
    "`chock resume` lifts the stop."
)


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


def _repo_stop_words(command):
    """Each word of a shell command, and the value of each `--flag=value` word: best effort, never raises."""
    lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    try:
        words = list(lexer)
    except ValueError:
        words = command.split()
    return words + [word.split("=", 1)[1] for word in words if "=" in word]


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


def _repo_stop_cwd(event):
    return getattr(event, "cwd", None) or os.getcwd()


def repo_stop_near(event, projects=()):
    """The repositories the call works in, read without its payload: the runtime's own, the cwd's, the project's."""
    runtime = globals().get("__file__") or sys.argv[0]
    own = [Path(runtime).resolve().parent.parent.parent] if runtime_route(runtime) == DLOG_ROUTE_SYNC else []
    return own + [repo for place in [_repo_stop_cwd(event), *projects] for repo in halt_repos(place)]


def repo_stop_paths(event):
    """Every distinct string the call's input may name a path with, the shell command's words included."""
    command = getattr(event, "command", None)
    words = _repo_stop_words(command) if isinstance(command, str) else []
    named = [getattr(event, "path", None), *_repo_stop_named(getattr(event, "raw", None))]
    named += [_repo_stop_path(word) for word in words]
    return list(dict.fromkeys(path for path in named if isinstance(path, str) and path))


def repo_stop_named_roots(event):
    """The repositories above every path the call names, or None past the cap (too many, too long, too slow)."""
    paths = repo_stop_paths(event)
    if len(paths) > _REPO_STOP_CAP_STRINGS or sum(map(len, paths)) > _REPO_STOP_CAP_CHARS:
        return None
    cwd, deadline, roots = _repo_stop_cwd(event), time.monotonic() + _REPO_STOP_CAP_SECONDS, []
    for path in paths:
        if time.monotonic() > deadline:
            return None
        roots += halt_repos(os.path.join(cwd, path))
    return roots


def repo_stop_refusal(event):
    """`stopped: <reason>` when a stop reaches this pre-tool call's agent, else None. An unreadable stop refuses."""
    if getattr(event, "event", None) != "pre_tool":
        return None
    agent, projects = getattr(event, "agent", None), repo_stop_projects(event)
    near = repo_stop_near(event, projects)
    stop = halt_find(near, agent)
    if stop is not None:
        return halt_message(stop)
    registered = halt_registry_find(agent)
    if registered is None or registered.get("everywhere") or not projects:
        return None if registered is None else halt_message(registered)
    named = repo_stop_named_roots(event)
    if named is None:
        return _REPO_STOP_OVER_CAP
    roots = near + named
    mains = [halt_main_root(root) for root in roots]
    stop = halt_find(named, agent) or halt_registry_find(agent, [*roots, *filter(None, mains)])
    return None if stop is None else halt_message(stop)
