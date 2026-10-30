"""The hook timeout in force for a client chock wires: hook_timeouts.json, then the plugin store data."""

from __future__ import annotations

from chock.compile.emitters.in_agent_hooks import TIMEOUT_SECONDS, VENDOR_TIMEOUTS
from chock.plugin import store
from chock.plugin.clients import CLIENTS

HOOK_TIMEOUTS_FILE = "src/chock/data/hook_timeouts.json"


def hook_timeout(agent: str) -> tuple[float | None, str]:
    """(seconds, where that number comes from) for `agent`'s chock hook entries; None when no timeout is known.

    Every chock-written entry carries `TIMEOUT_SECONDS`, except where the vendor's hook schema has no
    timeout field: there the client's own default applies, which may be undocumented.
    """
    facts = VENDOR_TIMEOUTS.get(agent)
    if facts is not None and facts["field"] is None:
        default = facts["default_seconds"]
        basis = f"{agent}'s hook schema has no timeout field ({HOOK_TIMEOUTS_FILE})"
        return (float(default) if default is not None else None), basis + ("" if default else "; default undocumented")
    if facts is not None:
        return float(TIMEOUT_SECONDS), f"chock writes `{facts['field']}` on {agent}'s hooks ({HOOK_TIMEOUTS_FILE})"
    own = next((c.own_layout for c in CLIENTS.values() if c.agent == agent and c.own_layout), None)
    field = store.hook_timeout_field(own) if own else None
    if field:
        return float(TIMEOUT_SECONDS), f"chock writes `{field}` on {agent}'s plugin hooks (store data {own}.json)"
    return float(TIMEOUT_SECONDS), f"chock writes its {TIMEOUT_SECONDS} s timeout on every {agent} hook entry"
