"""Who did what, for a decision line: session_id, actor and a tool call's `target`. Stdlib only, never raises.

`target` is a fingerprint, never content: a repo-relative path, `outside:sha256:<hex>`, `<program> sha256:<hex>`
of a whole command (no argument), or `<server>/<tool>`. Spec: docs/decision-log.md.
"""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

from .runner.journal import log_redact

DLOG_AGENT_PREFIX = "agent:"
_DLOG_HASH_PREFIX, _DLOG_OUTSIDE_PREFIX = "sha256:", "outside:"
#: Claude Code's MCP tool name, `mcp__<server>__<tool>`; Windsurf's adapter already gives `<server>/<tool>`.
_DLOG_MCP_TOOL = re.compile(r"^mcp__(?P<server>.+?)__(?P<tool>.+)$")
#: `NAME=value` words before a command's program: an env prefix, never the program.
_DLOG_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_DLOG_OPAQUE_MARKS = ("$(", "`", "'", '"')
_DLOG_PROGRAM_UNSAFE = re.compile(r"[^\w.+-]")
_DLOG_PROGRAM_CAP = 64
_DLOG_UNNAMED = "-"


def dlog_session(event, record):
    """`record` with the client's session id, where the payload carries one: what groups a session's lines."""
    session = getattr(event, "session_id", None)
    if isinstance(session, str) and session:
        record["session_id"] = session
    return record


def _dlog_client(raw):
    named = raw.get("client_type") if isinstance(raw, dict) else None
    return named if isinstance(named, str) else None


def dlog_actor(event):
    """`agent:<client>`: an agent hook is always an agent's call; the client named in the payload, else the bundle's."""
    named = _dlog_client(getattr(event, "raw", None)) or getattr(event, "agent", None)
    return DLOG_AGENT_PREFIX + str(named or "unknown")


def _dlog_sha256(text):
    return _DLOG_HASH_PREFIX + hashlib.sha256(str(text).encode("utf-8", "surrogatepass")).hexdigest()


def _dlog_program(command):
    """The program's bare name: after plain `NAME=value` words; `-` when a shell parser would be needed to tell."""
    for word in str(command).split():
        if not _DLOG_ASSIGNMENT.match(word):
            return "" if word.startswith("-") else word
        if any(mark in word for mark in _DLOG_OPAQUE_MARKS):  # `X=$(...)`, a quote: where it ends is unknowable here
            return ""
    return ""


def dlog_command_print(command):
    """`<program> sha256:<hex of the whole command>`: the program's bare name only, never an argument."""
    program = _dlog_program(command)
    name = _DLOG_PROGRAM_UNSAFE.sub("", re.split(r"[\\/]", program)[-1])[:_DLOG_PROGRAM_CAP]
    return f"{log_redact(name) or _DLOG_UNNAMED} {_dlog_sha256(command)}"


def dlog_path_print(path, cwd, repo):
    """The repository-relative path; any path outside `repo` (or with no repo) is `outside:sha256:<hex>`."""
    full = os.path.realpath(os.path.join(cwd or os.getcwd(), str(path)))
    if repo is not None:
        try:
            return log_redact(Path(full).relative_to(os.path.realpath(repo)).as_posix())
        except ValueError:
            pass
    return _DLOG_OUTSIDE_PREFIX + _dlog_sha256(full)


def dlog_target(event, repo):
    """What a tool call touched, as a fingerprint: `server/tool`, a command's print, a path's; None off a tool call."""
    if getattr(event, "event", None) != "pre_tool":
        return None
    tool = str(getattr(event, "tool", None) or "")
    mcp = _DLOG_MCP_TOOL.match(tool)
    if mcp:
        return f"{mcp['server']}/{mcp['tool']}"
    command, path = getattr(event, "command", None), getattr(event, "path", None)
    if command:
        return dlog_command_print(command)
    if path:
        return dlog_path_print(path, getattr(event, "cwd", None), repo)
    return log_redact(tool)[:_DLOG_PROGRAM_CAP] or None


def dlog_fields(event, repo):
    """Who did what, for a decision line: session_id, actor, and target on a tool call. Never raises: {} instead."""
    try:
        fields = dlog_session(event, {"actor": dlog_actor(event)})
        target = dlog_target(event, repo)
    except Exception:  # noqa: BLE001 -- a log field must never change the decision, and gate calls this inline
        return {}
    if target:
        fields["target"] = target
    return fields
