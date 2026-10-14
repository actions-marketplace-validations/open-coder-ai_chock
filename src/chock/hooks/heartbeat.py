"""The session-start heartbeat's hook entry: wired only where the client documents a session-start event."""

from __future__ import annotations

import re
from typing import Any

from chock import vendors
from chock.compile.emitters.in_agent_hooks import adapter_rel, copilot_entry, hook_entry, with_timeout
from chock.hooks.launch import PLUGIN_LAUNCHER, hook_command
from chock.plugin.store import SCRIPTS_TEMPLATE

#: Entry keys that turn a failed hook into a refusal: a heartbeat never refuses, so it never carries one.
_FAIL_CLOSED_KEYS = ("on_failure", "failClosed")
#: The sync route's own installer already runs this vendor's runtime at session start (the arm hook).
ARMED_ELSEWHERE = frozenset({"claude_code"})


def heartbeat_doc(vendor: str, command: str) -> Any:
    """`vendor`'s hook-config document running `command` (the runtime, no flags) at session start, or None."""
    if not vendors.session_start_documented(vendor):
        return None
    return _fail_open(with_timeout(vendor, vendors.session_start_hook_config(vendor, command)))


def _fail_open(node: Any) -> Any:
    """`node` with every fail-closed key dropped from its hook entries."""
    if isinstance(node, dict):
        return {k: _fail_open(v) for k, v in node.items() if k not in _FAIL_CLOSED_KEYS}
    return [_fail_open(v) for v in node] if isinstance(node, list) else node


def sync_command(vendor: str) -> str:
    """The repo-relative command that runs `vendor`'s vendored runtime with no flags: a heartbeat only."""
    return hook_command(adapter_rel(vendor))


def sync_doc(vendor: str) -> Any:
    """The sync route's heartbeat document for `vendor`, or None where it is not wired this way."""
    return None if vendor in ARMED_ELSEWHERE else heartbeat_doc(vendor, sync_command(vendor))


def copilot_entries(vendor: str) -> dict[str, list[dict[str, Any]]]:
    """chock's own Copilot hooks file's heartbeat entries, keyed by the session-start event, in its witnessed shape."""
    if not vendors.session_start_documented(vendor):
        return {}
    return {vendors.wire_event(vendor, "session_start"): [copilot_entry(sync_command(vendor))]}


def _commands(node: Any) -> list[str]:
    if isinstance(node, dict):
        own = [node["command"]] if isinstance(node.get("command"), str) else []
        return own + [c for k, v in node.items() if k != "command" for c in _commands(v)]
    return [c for v in node for c in _commands(v)] if isinstance(node, list) else []


def plugin_doc(agent: str, hooks: Any) -> Any:
    """A plugin's heartbeat document: the launcher and runtime its own hooks already run, with no flags; or None."""
    runtime = re.compile(
        rf'^(.*?{re.escape(PLUGIN_LAUNCHER)}" "[^"\s]*{re.escape(SCRIPTS_TEMPLATE.format(name=agent + ".py"))}")'
    )
    found = next((m.group(1) for m in map(runtime.match, _commands(hooks)) if m), None)
    if not found:
        return None
    doc = heartbeat_doc(agent, found)
    if doc is None or _wrapped(doc) == _wrapped(hooks):
        return doc
    # The package speaks the hooks-map dialect rather than the vendor's own (Copilot's Claude-format plugin).
    event_map = {vendors.wire_event(agent, "session_start"): [hook_entry(found)]}
    return event_map if vendors.hook_entry_bare(agent) else {"hooks": event_map}


def _wrapped(node: Any) -> bool:
    """Whether the first hook entry under `node` wraps its commands in a `hooks` list (the hooks-map shape)."""
    if isinstance(node, dict):
        if isinstance(node.get("hooks"), list):
            return True
        return any(_wrapped(v) for k, v in node.items() if k != "command" and isinstance(v, (dict, list)))
    return any(_wrapped(v) for v in node) if isinstance(node, list) else False
