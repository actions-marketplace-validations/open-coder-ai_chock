#!/usr/bin/env python3
# ruff: noqa: TRY003 -- a refusal message sits beside the condition that refuses (AGENTS.md externalized_text)
"""Chock decision-log lines and `chock witness export` bundles as optimize traces: misfire candidates per policy.

Stdlib only, no network. Usage: `python3 traces.py FILE [FILE ...]`; JSON on stdout, exit 2 on unreadable input.
Record fields: chock docs/decision-log.md.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

WITNESS_FORMAT = "chock-witness-export/1"
KIND_LOG, KIND_WITNESS = "decision-log", "witness-export"
VERDICTS = ("allow", "block", "ask", "warn", "off")
REFUSALS = ("block", "ask")
FAULTS = ("guard-errored", "guard-missing", "fault")
#: A person's stop (`chock stop`): its refusals are the stop's, never a policy's misfire.
STOP_POLICY, STOP_REASON, STOP_EVENTS = "chock-stop", "stopped", ("repo_stop", "repo_resume")
HEARTBEAT = "session_start"
#: What lets a finding through; a line with none of them and a `target` is one plain allowed tool call.
LET_THROUGH = ("override", "would_action")
#: The record fields a candidate keeps. `approver` and `who` name a person and are never copied.
SHOWN = ("ts", "route", "client", "plugin", "event", "surface", "verdict", "reason", "actor", "session_id", "target")
#: An override pairs only with a refusal that agrees on these, where both name them.
PAIRED_BY = ("surface", "target")
_TYPED = {"policy_id": str, "verdict": str, "event": str, "ts": str, "target": str}
EXIT_BAD_INPUT = 2


class TraceError(ValueError):
    """Input that is not a decision log or a witness export."""


def _checked(record: Any, where: str) -> dict[str, Any]:
    if not isinstance(record, dict):
        raise TraceError(f"{where}: a record must be a JSON object")
    for key, kind in _TYPED.items():
        if key in record and not isinstance(record[key], kind):
            raise TraceError(f"{where}: `{key}` must be a string")
    if "verdict" not in record and "event" not in record:
        raise TraceError(f"{where}: not a chock decision record (no `verdict` or `event`)")
    if "verdict" in record and record["verdict"] not in VERDICTS:
        raise TraceError(f"{where}: unknown verdict {str(record['verdict'])[:20]!r}")
    return record


def _witness(doc: dict[str, Any], name: str) -> list[tuple[str, dict[str, Any]]]:
    if doc.get("format") != WITNESS_FORMAT:
        raise TraceError(f"{name}: unsupported export format {str(doc.get('format'))[:40]!r}; want {WITNESS_FORMAT}")
    records = doc.get("records")
    if not isinstance(records, list):
        raise TraceError(f"{name}: a witness export's `records` must be a list")
    return [(f"{name}#{i}", _checked(r, f"{name} record {i}")) for i, r in enumerate(records)]


def _lines(text: str, name: str) -> list[tuple[str, dict[str, Any]]]:
    found = []
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        where = f"{name}:{number}"
        try:
            record = json.loads(line)
        except (ValueError, RecursionError):
            raise TraceError(f"{where}: not valid JSON (want one decision record per line)") from None
        found.append((where, _checked(record, where)))
    return found


def load(path: Path) -> tuple[str, list[tuple[str, dict[str, Any]]]]:
    """(kind, [(trace id, record)]) for one file; TraceError for anything else."""
    name = path.name
    try:
        text = path.read_bytes().decode("utf-8")
    except OSError as exc:
        raise TraceError(f"{name}: cannot read ({exc.strerror or exc.__class__.__name__})") from None
    except UnicodeDecodeError:
        raise TraceError(f"{name}: not UTF-8 text") from None
    if not text.strip():
        return KIND_LOG, []
    try:
        whole = json.loads(text)
    except (ValueError, RecursionError):
        return KIND_LOG, _lines(text, name)
    if isinstance(whole, dict) and ("format" in whole or "records" in whole):
        return KIND_WITNESS, _witness(whole, name)
    if isinstance(whole, dict):
        return KIND_LOG, [(f"{name}:1", _checked(whole, f"{name}:1"))]
    raise TraceError(f"{name}: a JSON {type(whole).__name__} is neither decision-log lines nor a witness export")


def _is_stop(record: dict[str, Any]) -> bool:
    return (
        record.get("policy_id") == STOP_POLICY
        or record.get("reason") == STOP_REASON
        or record.get("event") in STOP_EVENTS
    )


def _is_plain_allow(record: dict[str, Any]) -> bool:
    untouched = not any(key in record for key in LET_THROUGH) and record.get("reason") not in FAULTS
    return record.get("verdict") == "allow" and "target" in record and untouched


def _entry(policy_id: str) -> dict[str, Any]:
    keys = ("refusals", "warns", "faults", "observed", "overrides")
    return {"policy_id": policy_id, **dict.fromkeys(keys, 0), "misfire_candidates": [], "_open": []}


def _shown(trace: str, record: dict[str, Any]) -> dict[str, Any]:
    return {"trace": trace, **{key: record[key] for key in SHOWN if key in record}}


def _pair(entry: dict[str, Any], trace: str, record: dict[str, Any]) -> None:
    """An override answers the latest open refusal of its policy (same `surface` and `target` where both name one)."""
    entry["overrides"] += 1
    for at in range(len(entry["_open"]) - 1, -1, -1):
        refused_trace, refused = entry["_open"][at]
        if all(None in (record.get(key), refused.get(key)) or record[key] == refused[key] for key in PAIRED_BY):
            del entry["_open"][at]
            entry["misfire_candidates"].append({**_shown(refused_trace, refused), "overridden_by": trace})
            return


def _tally(entry: dict[str, Any], trace: str, record: dict[str, Any]) -> None:
    verdict = record.get("verdict")
    if record.get("reason") in FAULTS:
        entry["faults"] += 1
    elif verdict in REFUSALS:
        entry["refusals"] += 1
        entry["_open"].append((trace, record))
    elif verdict == "warn":
        entry["warns"] += 1
    elif record.get("override"):
        _pair(entry, trace, record)
    elif "would_action" in record:
        entry["observed"] += 1


def group(traces: list[tuple[str, dict[str, Any]]]) -> dict[str, Any]:
    """Per-policy counts and misfire candidates: refusals a person later overrode with CHOCK_ALLOW."""
    counts = {"allowed_calls": 0, "stops": 0, "sessions": 0, "unattributed": 0}
    policies: dict[str, dict[str, Any]] = {}
    for trace, record in sorted(traces, key=lambda item: str(item[1].get("ts", ""))):
        if _is_stop(record):
            counts["stops"] += 1
        elif _is_plain_allow(record):
            counts["allowed_calls"] += not record.get("policy_id")  # debug's per-hook allows: no one's evidence
        elif record.get("event") == HEARTBEAT:
            counts["sessions"] += 1
        elif not record.get("policy_id"):
            counts["unattributed"] += 1
        else:
            _tally(policies.setdefault(record["policy_id"], _entry(record["policy_id"])), trace, record)
    for entry in policies.values():
        del entry["_open"]
    ranked = sorted(policies.values(), key=lambda e: (-len(e["misfire_candidates"]), -e["refusals"], e["policy_id"]))
    return {**counts, "policies": ranked}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Decision-log lines or witness exports as optimize traces")
    parser.add_argument("files", nargs="+", type=Path, help="decision-log .jsonl files or `chock witness export` .json")
    args = parser.parse_args(argv)
    inputs, traces = [], []
    try:
        for path in args.files:
            kind, found = load(path)
            inputs.append({"file": path.name, "kind": kind, "records": len(found)})
            traces += found
    except TraceError as exc:
        sys.stderr.write(f"optimize traces: {exc}. Nothing was read as evidence.\n")
        return EXIT_BAD_INPUT
    sys.stdout.write(json.dumps({"inputs": inputs, **group(traces)}, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
