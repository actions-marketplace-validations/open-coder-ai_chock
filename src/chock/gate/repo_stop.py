"""The repo stop at an agent's pre-tool hook: every tool call of an agent it reaches is refused. Stdlib only.

Runs before every guard and gate, so neither `CHOCK_ALLOW` nor the rollout level reaches it. Spec: `chock stop`.
"""

from __future__ import annotations

import sys
from pathlib import Path

from .decision_log import DLOG_ROUTE_SYNC, _dlog_repo_root, runtime_route
from .runner.halt import halt_covers, halt_message, halt_read
from .workspace_root import workspace_root


def repo_stop_root(event):
    """The repository whose stop applies: the runtime's own on the sync route, else the one the call works in."""
    runtime = globals().get("__file__") or sys.argv[0]
    if runtime_route(runtime) == DLOG_ROUTE_SYNC:
        return Path(runtime).resolve().parent.parent.parent
    return _dlog_repo_root(getattr(event, "cwd", None) or workspace_root(event) or ".")


def repo_stop_refusal(event):
    """`stopped: <reason>` when a stop reaches this pre-tool call's agent, else None. An unreadable stop refuses."""
    if getattr(event, "event", None) != "pre_tool":
        return None
    stop = halt_read(repo_stop_root(event))
    if stop is None or not halt_covers(stop, getattr(event, "agent", None)):
        return None
    return halt_message(stop)
