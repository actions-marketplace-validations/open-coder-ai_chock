"""`chock status --summary`: the maths over fixture logs, the timeout-proximity WARN, and the heartbeat gaps."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from chock import gatelog_summary as gs
from chock.compile.emitters.in_agent_hooks import TIMEOUT_SECONDS
from chock.gatelog_read import read_events
from chock.hook_timeout import hook_timeout
from chock.lifecycle import status_main

TS = "2026-10-13T10:00:{:02d}Z"


def _record(n: int, agent: str = "grok", **fields: object) -> dict[str, object]:
    base = {"ts": TS.format(n), "route": "plugin", "agent": agent, "event": "tool_use", "surface": "pre-tool-use"}
    return {**base, "policy_id": "p-a", "verdict": "block", "reason": "guard-blocked", "duration_ms": 10, **fields}


def _beat(n: int, agent: str = "claude_code", route: str = "plugin") -> dict[str, object]:
    return {"ts": TS.format(n), "event": "session_start", "route": route, "agent": agent, "plugin": "chock"}


def _write(path: Path, records: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    folder = tmp_path / "home"
    monkeypatch.setenv("HOME", str(folder))
    monkeypatch.setenv("USERPROFILE", str(folder))
    return folder


def test_rates_tallies_and_percentiles() -> None:
    records = [_record(i, duration_ms=100 * (i + 1), verdict="allow", reason="no-rule") for i in range(20)]
    records[0].update(verdict="block", reason="guard-blocked")
    records[1].update(verdict="block", reason="guard-errored", policy_id="p-b")
    records[2].update(verdict="ask", reason="guard-asked", agent="goose")
    records[3].update(verdict="warn", reason="gate-warn")

    report = gs.summary(records)

    assert report["records"] == 20
    assert report["rates"]["block"] == {"count": 2, "rate": 0.1}
    assert report["rates"]["ask"] == {"count": 1, "rate": 0.05}
    assert report["rates"]["warn"] == {"count": 1, "rate": 0.05}
    assert report["rates"]["fault"] == {"count": 1, "rate": 0.05}
    policies = {r["policy_id"]: r for r in report["policies"]}
    assert (policies["p-a"]["fires"], policies["p-a"]["block"]) == (19, 1)
    assert (policies["p-b"]["fires"], policies["p-b"]["fault"]) == (1, 1)
    assert [(c["agent"], c["fires"]) for c in report["clients"]] == [("grok", 19), ("goose", 1)]
    grok = next(h for h in report["hooks"] if h["agent"] == "grok")
    # nearest rank over 100..2000 without the goose call (300): 19 values
    values = sorted(100 * (i + 1) for i in range(20) if i != 2)
    assert (grok["count"], grok["p50_ms"], grok["p95_ms"]) == (19, values[9], values[18])
    assert report["faults"] == [{"policy_id": "p-b", "reason": "guard-errored", "count": 1}]


def test_percentile_is_nearest_rank() -> None:
    assert gs.percentile([5], 95) == 5
    assert gs.percentile(list(range(1, 101)), 50) == 50
    assert gs.percentile(list(range(1, 101)), 95) == 95
    assert gs.percentile([3, 1, 2, 4], 50) == 2


def test_top_faults_are_ranked_and_capped() -> None:
    records = [_record(i, policy_id=f"p{i % 7}", reason="fault") for i in range(30)]
    faults = gs.summary(records)["faults"]
    assert len(faults) == gs.TOP_FAULTS
    assert [f["count"] for f in faults] == sorted((f["count"] for f in faults), reverse=True)
    assert faults[0] == {"policy_id": "p0", "reason": "fault", "count": 5}


def test_timeout_warning_fires_within_a_quarter_of_the_client_timeout() -> None:
    seconds, basis = hook_timeout("grok")
    assert seconds == TIMEOUT_SECONDS
    assert "hook_timeouts.json" in basis
    edge = int(gs.TIMEOUT_WARN_SHARE * seconds * 1000)

    near = gs.summary([_record(0, duration_ms=edge)])
    under = gs.summary([_record(0, duration_ms=edge - 1)])

    assert near["hooks"][0]["warn"] is True
    assert under["hooks"][0]["warn"] is False
    text = gs.render_text(near)
    assert f"WARN: grok pre-tool-use: p95 {edge} ms is within 25% of the {seconds:g} s hook timeout" in text
    assert "WARN" not in gs.render_text(under).split("Heartbeats")[0]


def test_timeout_comes_from_store_data_and_is_unknown_without_a_field() -> None:
    seconds, basis = hook_timeout("kimi_code")
    assert (seconds, "store data kimi.json" in basis) == (TIMEOUT_SECONDS, True)
    assert hook_timeout("windsurf")[0] is None
    report = gs.summary([_record(0, agent="windsurf", duration_ms=10**7)])
    assert report["hooks"][0]["warn"] is False
    assert "unknown" in gs.render_text(report)


def test_heartbeat_gaps() -> None:
    events = [
        _record(0, agent="claude_code"),  # before any heartbeat
        _beat(1),
        _beat(2),  # the session at 1 had no hook record
        _record(3, agent="claude_code"),
        _beat(4),  # trailing session with no hook record
        _record(5, agent="antigravity"),  # agentseam records no session start for antigravity
        _record(6, agent="goose"),  # goose has one, and never sent it
    ]
    beats = gs.summary(events)["heartbeats"]

    assert beats["sessions"] == 3
    assert beats["hooks_without_heartbeat"] == [
        {"route": "plugin", "agent": "claude_code", "records": 1},
        {"route": "plugin", "agent": "goose", "records": 1},
    ]
    assert beats["heartbeats_without_hooks"] == [{"route": "plugin", "agent": "claude_code", "sessions": 2}]
    assert beats["no_heartbeat_available"] == ["antigravity"]


def test_the_reader_keeps_heartbeats_out_of_the_plain_log(tmp_path: Path, home: Path) -> None:
    _write(home / ".chock" / "log" / "claude_code" / "events.jsonl", [_beat(0), _record(1, agent="claude_code")])
    assert [e.get("event") for e in read_events(tmp_path)] == ["tool_use"]
    assert [e.get("event") for e in read_events(tmp_path, heartbeats=True)] == ["session_start", "tool_use"]


def test_status_summary_reads_both_routes(tmp_path: Path, home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _write(tmp_path / ".chock" / "log" / "gate-events.jsonl", [_record(0, route="sync", agent="claude_code")])
    _write(home / ".chock" / "log" / "grok" / "events.jsonl", [_record(1), _beat(2, agent="grok")])

    assert status_main(["--repo", str(tmp_path), "--summary", "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["records"] == 2
    assert report["heartbeats"]["sessions"] == 1

    assert status_main(["--repo", str(tmp_path), "--summary", "--route", "sync"]) == 0
    out = capsys.readouterr().out
    assert "Decision log summary (1 hook records)" in out
    assert "claude_code (sync): 1 hook record(s) with no session_start" in out


def test_status_summary_refuses_flags_it_does_not_read(tmp_path: Path, home: Path) -> None:
    assert status_main(["--repo", str(tmp_path), "--summary", "--policy", "x"]) == 2
