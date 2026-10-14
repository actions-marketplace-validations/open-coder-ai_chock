"""The repo stop's own pre-tool hook (`chock stop`): one entry per client, no matcher, whatever policies are installed.

The runtime refuses every tool call while a stop reaches the agent, reads included, so it must run on every tool
call; a policy's hook runs only for the tools its matcher names. Unstopped, it allows and writes nothing of its own.
"""

from __future__ import annotations

from typing import Any

from chock import vendors
from chock.compile.emitters.in_agent_hooks import (
    copilot_entry,
    cursor_entry,
    generic_pre_tool_config,
    hook_entry,
)
from chock.gate.runner.halt import HALT_HOOK_FLAG
from chock.hooks.launch import hook_command
from chock.hooks.runtime_vendor import runtime_rel

STOP_CHECK_FLAG = HALT_HOOK_FLAG


def command(vendor: str) -> str:
    """The repo-relative command running `vendor`'s runtime as the stop check alone."""
    return hook_command(runtime_rel(vendor).as_posix(), STOP_CHECK_FLAG)


def claude_entry() -> dict[str, Any]:
    """Claude Code's PreToolUse entry: no matcher, so every tool."""
    return hook_entry(command("claude_code"))


def cursor_entries() -> dict[str, list[dict[str, Any]]]:
    """Cursor's entry under its generic pre-tool event, fail-closed like every gate there."""
    return {vendors.pre_tool_event("cursor"): [cursor_entry(command("cursor"), fail_closed=True)]}


def generic_doc(vendor: str) -> Any:
    """`vendor`'s pre-tool hook-config document running the stop check, agentseam's rendering, no matcher."""
    return generic_pre_tool_config(vendor, command(vendor), None)


def copilot_entries(vendor: str) -> dict[str, list[dict[str, Any]]]:
    """chock's own Copilot hooks file's stop-check entry, under its pre-tool event."""
    return {vendors.pre_tool_event(vendor): [copilot_entry(command(vendor))]}
