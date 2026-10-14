"""`chock status --summary`: fires, rates, hook latency against the client's timeout, guard faults and heartbeats."""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter, defaultdict
from itertools import pairwise
from pathlib import Path
from typing import Any

from agentseam import contract
from agentseam import matrix as _matrix

from chock.gatelog import JSON_HELP, REPO_HELP, SINCE_HELP, positive_days
from chock.gatelog_read import (
    HEARTBEAT_EVENT,
    ROUTES,
    allowed_call,
    allowed_calls,
    read_events,
    record_level,
    record_route,
)
from chock.gatelog_report import _printable
from chock.hook_timeout import hook_timeout

VERDICTS = ("block", "ask", "warn")
#: Reason codes of a hook that could not judge the call: a guard that errored or is missing, or a runtime fault.
FAULT_REASONS = frozenset({"fault", "guard-errored", "guard-missing"})
#: WARN once a hook's p95 reaches this share of its client's timeout: a client timeout fails open.
TIMEOUT_WARN_SHARE = 0.75
TOP_FAULTS = 5
_MS = 1000
UNKNOWN = "unknown"
NO_HEARTBEAT = "no_heartbeat_available"


def is_fault(record: dict[str, Any]) -> bool:
    return str(record.get("reason") or "") in FAULT_REASONS


def percentile(values: list[int], pct: int) -> int:
    """Nearest-rank percentile of a non-empty list."""
    ordered = sorted(values)
    return ordered[max(math.ceil(pct / 100 * len(ordered)) - 1, 0)]


def _tally(records: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    """Fires and verdict/fault counts per `key` value, most fires first."""
    rows: dict[str, Counter] = defaultdict(Counter)
    for record in records:
        row = rows[str(record.get(key) or UNKNOWN)]
        row["fires"] += 1
        row["fault"] += is_fault(record)
        if record.get("verdict") in VERDICTS:
            row[str(record["verdict"])] += 1
    return sorted(
        ({key: name, "fires": c["fires"], **{v: c[v] for v in (*VERDICTS, "fault")}} for name, c in rows.items()),
        key=lambda r: (-r["fires"], r[key]),
    )


def _durations(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """p50/p95 per hook (client x surface), with the client's timeout and a WARN when p95 nears it."""
    found: dict[tuple[str, str], list[int]] = defaultdict(list)
    for record in records:
        ms = record.get("duration_ms")
        if isinstance(ms, int) and not isinstance(ms, bool):
            found[(str(record.get("agent") or UNKNOWN), str(record.get("surface") or UNKNOWN))].append(ms)
    rows = []
    for (agent, surface), values in sorted(found.items()):
        seconds, basis = hook_timeout(agent)
        p95 = percentile(values, 95)
        rows.append(
            {
                "agent": agent,
                "surface": surface,
                "count": len(values),
                "p50_ms": percentile(values, 50),
                "p95_ms": p95,
                "timeout_s": seconds,
                "timeout_basis": basis,
                "warn": seconds is not None and p95 >= TIMEOUT_WARN_SHARE * seconds * _MS,
            }
        )
    return rows


def _faults(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts = Counter((str(r.get("policy_id")), str(r.get("reason"))) for r in records if is_fault(r))
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:TOP_FAULTS]
    return [{"policy_id": policy, "reason": reason, "count": n} for (policy, reason), n in ranked]


def heartbeat_available(agent: str) -> bool:
    """Whether agentseam records a session-start event for `agent`, so a heartbeat can exist at all."""
    row = _matrix.MATRIX.get(agent)
    return bool(row) and contract.SESSION_START in row["events"]


def heartbeats(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Per (route, client): hook records before any `session_start`, and `session_start` records followed by none.

    The log carries no session id, so a session is read as one heartbeat up to the next on the same route and client.
    """
    streams: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for record in events:
        streams[(record_route(record), str(record.get("agent") or UNKNOWN))].append(record)
    unseen, silent, unavailable, started = [], [], set(), 0
    for (route, agent), records in sorted(streams.items()):
        if not heartbeat_available(agent):
            unavailable.add(agent)
            continue
        beats = [i for i, r in enumerate(records) if r.get("event") == HEARTBEAT_EVENT]
        started += len(beats)
        before = beats[0] if beats else len(records)
        if before:
            unseen.append({"route": route, "agent": agent, "records": before})
        bounds = [*beats, len(records)]
        empty = sum(1 for start, end in pairwise(bounds) if end - start == 1)
        if empty:
            silent.append({"route": route, "agent": agent, "sessions": empty})
    return {
        "sessions": started,
        "hooks_without_heartbeat": unseen,
        "heartbeats_without_hooks": silent,
        NO_HEARTBEAT: sorted(unavailable),
    }


def summary(events: list[dict[str, Any]]) -> dict[str, Any]:
    """The whole summary over `events` (heartbeats included), as one JSON-ready dict."""
    hooks = [e for e in events if e.get("event") != HEARTBEAT_EVENT]
    total = len(hooks)
    counts = {v: sum(r.get("verdict") == v for r in hooks) for v in VERDICTS}
    counts["fault"] = sum(map(is_fault, hooks))
    return {
        "records": total,
        "debug_records": sum(record_level(r) != "info" for r in hooks),
        "rates": {k: {"count": n, "rate": round(n / total, 4) if total else 0.0} for k, n in counts.items()},
        "allowed_calls": allowed_calls(hooks),
        "policies": _tally([r for r in hooks if not allowed_call(r)], "policy_id"),
        "clients": _tally(hooks, "agent"),
        "hooks": _durations(hooks),
        "faults": _faults(hooks),
        "heartbeats": heartbeats(events),
    }


def _pct(entry: dict[str, Any]) -> str:
    return f"{entry['count']} ({entry['rate']:.1%})"


def _table(rows: list[dict[str, Any]], key: str) -> list[str]:
    width = max(len(key), *(len(str(r[key])) for r in rows))
    cols = ("fires", *VERDICTS, "fault")
    return [
        key.ljust(width) + "".join(f"  {c:>6}" for c in cols),
        *(str(r[key]).ljust(width) + "".join(f"  {r[c]:>6}" for c in cols) for r in rows),
    ]


def _hook_lines(rows: list[dict[str, Any]]) -> list[str]:
    lines = [f"{'hook (client / surface)':<36}  {'calls':>6}  {'p50 ms':>7}  {'p95 ms':>7}  timeout"]
    for r in rows:
        timeout = f"{r['timeout_s']:g} s" if r["timeout_s"] is not None else "unknown"
        lines.append(
            f"{r['agent'] + ' / ' + r['surface']:<36}  {r['count']:>6}  {r['p50_ms']:>7}  {r['p95_ms']:>7}  {timeout}"
        )
    for r in (r for r in rows if r["warn"]):
        lines.append(
            f"WARN: {r['agent']} {r['surface']}: p95 {r['p95_ms']} ms is within {1 - TIMEOUT_WARN_SHARE:.0%} of the {r['timeout_s']:g} s hook "
            f"timeout ({r['timeout_basis']}); a client timeout fails open, so a slower call goes through unchecked."
        )
    return lines


def _heartbeat_lines(beats: dict[str, Any]) -> list[str]:
    lines = [f"Heartbeats: {beats['sessions']} session_start record(s)"]
    lines += [
        f"WARN: {h['agent']} ({h['route']}): {h['records']} hook record(s) with no session_start before them"
        for h in beats["hooks_without_heartbeat"]
    ]
    lines += [
        f"WARN: {h['agent']} ({h['route']}): {h['sessions']} session_start record(s) with no hook record after them"
        for h in beats["heartbeats_without_hooks"]
    ]
    if beats[NO_HEARTBEAT]:
        lines.append(f"No heartbeat available (no session-start event): {', '.join(beats[NO_HEARTBEAT])}")
    return lines


def render_text(report: dict[str, Any], since: int | None = None) -> str:
    window = f", last {since} days" if since is not None else ""
    head = [f"Decision log summary ({report['records']} hook records{window})"]
    if not report["records"] and not report["heartbeats"]["sessions"]:
        return head[0] + "\nNo records yet."
    rates = report["rates"]
    lines = [*head, "Rates: " + ", ".join(f"{k} {_pct(rates[k])}" for k in (*VERDICTS, "fault"))]
    lines.append(f"Allowed tool calls: {report['allowed_calls']} (each counted once, never toward a policy)")
    if report["records"]:
        lines += ["", *_table(report["policies"], "policy_id"), "", *_table(report["clients"], "agent")]
        lines += ["", *_hook_lines(report["hooks"])]
    if not report["debug_records"] and report["records"]:
        lines.append("Only info records: allows are logged at debug, so the latencies cover calls a policy fired on.")
    if report["faults"]:
        lines += ["", f"Top guard faults (exit 2, top {TOP_FAULTS}):"]
        lines += [f"  {f['count']:>5}  {f['policy_id']}  {f['reason']}" for f in report["faults"]]
    return "\n".join([*lines, "", *_heartbeat_lines(report["heartbeats"])])


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="chock status --summary", description="Summarize the decision log")
    parser.add_argument("--repo", default=".", help=REPO_HELP)
    parser.add_argument("--since", type=positive_days, metavar="DAYS", help=SINCE_HELP)
    parser.add_argument("--route", choices=ROUTES, help="Only the sync route (this repo) or the plugin route")
    parser.add_argument("--json", action="store_true", help=JSON_HELP)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    events = read_events(Path(args.repo).resolve(), args.since, route=args.route, heartbeats=True)
    report = summary(events)
    sys.stdout.write(
        (json.dumps(report, indent=2) if args.json else _printable(render_text(report, args.since))) + "\n"
    )
    return 0
