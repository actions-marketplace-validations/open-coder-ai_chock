"""The gateway's decision-log lines: the sync route's journal and fields (docs/decision-log.md). Never raises."""

from __future__ import annotations

import re
import time
import uuid
from pathlib import Path
from typing import Any

from chock import __version__
from chock.gate.decision_target import DLOG_AGENT_PREFIX
from chock.gate.runner.journal import LOG_ALLOW, LOG_CALL, log_redact, log_write
from chock.gatelog_read import LOG_DIR, LOG_NAME
from chock.gateway.gates import FAULT

#: Written to the repo's sync-route file; `agent` and `surface` tell a gateway line from a hook's.
GATEWAY_ROUTE = "sync"
GATEWAY_AGENT = "mcp-gateway"
#: A refusal no policy made (a malformed call, a batch refused for a sibling) is filed under the gateway.
GATEWAY_POLICY = GATEWAY_AGENT
_EVENT = "tool_use"
_UNNAMED = "-"
#: Same cap and character set as a hook's MCP target and `client` (decision_target.py).
_TARGET_CAP = 128
_CLIENT_UNSAFE = re.compile(r"[^a-z0-9_-]")
_CLIENT_CAP = 32
#: action -> (verdict, reason). An ask is refused: a proxy on a pipe has no person to ask.
_SPOKEN = {
    "warn": ("warn", "gate-warn"),
    "ask": ("block", "gate-ask"),
    FAULT: ("block", FAULT),
}
_BLOCK = ("block", "gate-block")
BATCH_REASON = "batch"


def client_name(raw: Any) -> str | None:
    """An MCP `clientInfo.name` as `[a-z0-9_-]{1,32}`, or None when nothing of it is left."""
    if not isinstance(raw, str):
        return None
    return _CLIENT_UNSAFE.sub("", raw.lower())[:_CLIENT_CAP] or None


def target(server: str | None, tool: Any) -> str:
    """`<server>/<tool>`, redacted, cut to 128 characters. Never an argument."""
    return log_redact(f"{server or _UNNAMED}/{tool if isinstance(tool, str) and tool else _UNNAMED}")[:_TARGET_CAP]


def records(findings: list[tuple[str, str, str]], context: dict[str, Any]) -> list[dict[str, Any]]:
    """One line per finding; a forwarded call adds its one plain allow line (no policy, as GAP-2b's hooks do).

    `context`: target, client, started (monotonic), forwarded, and `batch` when a sibling refused the call.
    """
    base = {
        "route": GATEWAY_ROUTE,
        "agent": GATEWAY_AGENT,
        "event": _EVENT,
        "surface": GATEWAY_AGENT,
        "duration_ms": round((time.monotonic() - context["started"]) * 1000),
        "can_ask": False,
        "chock_version": __version__,
        "actor": DLOG_AGENT_PREFIX + (context.get("client") or "unknown"),
        "target": context["target"],
    }
    if context.get("client"):
        base["client"] = context["client"]
    lines = []
    for policy, action, _message in findings:
        verdict, reason = _SPOKEN.get(action, _BLOCK)
        lines.append({**base, "policy_id": policy, "verdict": verdict, "reason": reason})
    if context.get("forwarded"):
        lines.append({**base, "verdict": LOG_ALLOW, "reason": "no-rule", LOG_CALL: uuid.uuid4().hex})
    elif context.get("batch") and not any(_SPOKEN.get(a, _BLOCK)[0] == "block" for _, a, _ in findings):
        lines.append({**base, "policy_id": GATEWAY_POLICY, "verdict": "block", "reason": BATCH_REASON})
    return lines


def lines_for(judged: list[tuple[list[tuple[str, str, str]], str]], context: dict[str, Any]) -> list[dict[str, Any]]:
    """Every (findings, target) call's lines; [] when they cannot be built, so the verdict never waits on them."""
    try:
        return [line for findings, aim in judged for line in records(findings, {**context, "target": aim})]
    except Exception:  # noqa: BLE001 -- a log line must never change the verdict or raise
        return []


def write(repo_root: Path, lines: list[dict[str, Any]]) -> None:
    """Append each line to `<repo>/.chock/log/gate-events.jsonl` (0o600) at the level in force. Never raises."""
    path = Path(repo_root) / ".chock" / LOG_DIR / LOG_NAME
    for line in lines:
        try:
            log_write(path, line, repo_root)
        except Exception:  # noqa: BLE001,S112 -- a log line must never change the verdict or raise
            continue
