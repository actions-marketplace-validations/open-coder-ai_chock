"""The repo stop at an agent's pre-tool hook: every tool call of an agent it reaches is refused. Stdlib only.

Runs before every guard and gate, so neither `CHOCK_ALLOW` nor the rollout level reaches it. Spec: `chock stop`.
A stop in any repository the call works in or touches counts: the runtime's own, every repository above the
call's cwd and above each path it names (nested ones included), and the main worktree of each.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from .decision_log import DLOG_ROUTE_SYNC, runtime_route
from .runner.halt import halt_find, halt_message, halt_repos
from .workspace_root import workspace_roots

#: The tool-input keys that name a path a call reads or writes, across the clients' own spellings.
_REPO_STOP_PATH_KEYS = ("file_path", "path", "notebook_path", "paths", "filePath", "target_file")


def _repo_stop_named(raw):
    """The paths a payload's tool input names, as given."""
    tool_input = raw.get("tool_input") if isinstance(raw, dict) else None
    if not isinstance(tool_input, dict):
        return []
    found = []
    for key in _REPO_STOP_PATH_KEYS:
        value = tool_input.get(key)
        values = value if isinstance(value, list) else [value]
        found += [item for item in values if isinstance(item, str)]
    return found


def repo_stop_roots(event):
    """Every repository whose stop applies to this call."""
    runtime = globals().get("__file__") or sys.argv[0]
    own = [Path(runtime).resolve().parent.parent.parent] if runtime_route(runtime) == DLOG_ROUTE_SYNC else []
    cwd = getattr(event, "cwd", None) or os.getcwd()
    named = [getattr(event, "path", None), *_repo_stop_named(getattr(event, "raw", None))]
    places = [cwd, *workspace_roots(event), *(os.path.join(cwd, path) for path in named if path)]
    return own + [repo for place in places for repo in halt_repos(place)]


def repo_stop_refusal(event):
    """`stopped: <reason>` when a stop reaches this pre-tool call's agent, else None. An unreadable stop refuses."""
    if getattr(event, "event", None) != "pre_tool":
        return None
    stop = halt_find(repo_stop_roots(event), getattr(event, "agent", None))
    return None if stop is None else halt_message(stop)
