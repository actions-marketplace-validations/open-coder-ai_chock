"""The smallest payload a vendor parses back to one canonical event: what an unreadable payload is answered as."""

from __future__ import annotations

import json
from typing import Any

from agentseam import adapters

from chock.resources import package_data_dir
from chock.vendors import entry

#: Where a vendor's payload names its event, after the vendor's own recorded `event_key`.
EVENT_KEYS = ("hook_event_name", "hookEventName", "agent_action_name")

#: A payload naming its event by shape, not by a key (antigravity): the vendor's own required field, per event.
_SHAPE_EVENTS = json.loads(package_data_dir("chock", "data").joinpath("shape_events.json").read_text(encoding="utf-8"))


def wire_raw(agent: str, canonical: str) -> dict[str, Any]:
    """The smallest payload `agent` parses back to `canonical`; {} where none does.

    An event-less vendor is tried with its recorded shape, kept only when agentseam parses it to `canonical`:
    without it an unreadable Stop would be answered in the pre-tool grammar, which such a Stop reads as allow.
    """
    adapter = adapters.get(agent)
    wire = adapter.REVERSE_EVENT_MAP.get(canonical)
    keys = (*entry(agent)["claims"].get("event_key", ()), *EVENT_KEYS)
    found = next(({key: wire} for key in keys if wire and adapter.parse({key: wire}).event == canonical), None)
    shaped = (_SHAPE_EVENTS.get(agent) or {}).get(canonical)
    if found is None and shaped and adapter.parse(dict(shaped)).event == canonical:
        return dict(shaped)
    return found or {}
