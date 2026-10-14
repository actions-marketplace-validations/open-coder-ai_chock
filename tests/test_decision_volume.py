"""GAP-2b: a plain allowed tool call is one info line listing every policy that let it through; refusals stay per policy."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from decision_log_support import (
    BLOCKING_GUARD,
    CLEAN_GUARD,
    hook_env,
    plugin_layout,
    plugin_log,
    raw_records,
    records,
    sync_layout,
    sync_log,
)

from chock import gatelog
from chock.gate.runner import journal
from chock.gatelog_read import read_events

LAYOUTS = {
    "sync": (sync_layout, lambda repo, home: sync_log(repo)),
    "plugin": (plugin_layout, lambda repo, home: plugin_log(home)),
}
ROUTES = sorted(LAYOUTS)
SESSION = "s"


@pytest.fixture
def home(tmp_path: Path) -> Path:
    folder = tmp_path / "home"
    folder.mkdir()
    return folder


def _run(repo: Path, runtime: Path, guard: Path, payload: dict, env: dict[str, str]) -> None:
    subprocess.run(
        [sys.executable, str(runtime), "--guard", str(guard)],
        input=json.dumps({"session_id": SESSION, "cwd": str(repo), **payload}),
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=repo,
        env=env,
        timeout=60,
        check=False,
    )


class Session:
    """One layout's runtime, a guard per policy hook, and a clean guard for the turn's end."""

    def __init__(self, tmp_path: Path, home: Path, route: str, guards: list[str], **levels: str) -> None:
        layout, log_of = LAYOUTS[route]
        self.repo, self.runtime, first = layout(tmp_path, guards[0])
        self.log, self.env, self.guards = log_of(self.repo, home), hook_env(home, **levels), [first]
        for at, body in enumerate(guards[1:], start=2):
            # sync: another policy's guard (`.agents/policies/<id>/implementations/`); plugin: the same package's
            folder = first.parent.parent.with_name(f"p-{at}") / "implementations" if route == "sync" else first.parent
            folder.mkdir(parents=True, exist_ok=True)
            self.guards.append(folder / f"guard{at}.sh")
            self.guards[-1].write_text(body, encoding="utf-8", newline="\n")
        self.stop_guard = first.with_name("stop.sh")
        self.stop_guard.write_text(CLEAN_GUARD, encoding="utf-8", newline="\n")

    def call(self, call: str, command: str = "ls") -> None:
        payload = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": command}}
        for guard in self.guards:
            _run(self.repo, self.runtime, guard, {**payload, "tool_use_id": call}, self.env)

    def stop(self) -> None:
        _run(self.repo, self.runtime, self.stop_guard, {"hook_event_name": "Stop", "stop_hook_active": False}, self.env)


@pytest.mark.parametrize("route", ROUTES)
def test_a_plain_allow_is_held_then_one_line_per_tool_call(tmp_path: Path, home: Path, route: str) -> None:
    session = Session(tmp_path, home, route, [CLEAN_GUARD] * 3)
    session.call("toolu_1")
    session.call("toolu_2")

    assert raw_records(session.log) == []  # held until the call settles
    session.stop()
    written = raw_records(session.log)
    assert [(r["verdict"], r["level"]) for r in written] == [("allow", "info")] * 2
    assert all("call" not in r and "policy_id" not in r for r in written)


def test_one_call_two_policies_is_one_line_counted_once_for_each(tmp_path: Path, home: Path) -> None:
    session = Session(tmp_path, home, "sync", [CLEAN_GUARD, CLEAN_GUARD])
    session.call("toolu_1")
    session.stop()

    [line] = raw_records(session.log)
    assert line[journal.LOG_POLICIES] == ["p-2", "p-log"]
    counts = {e["policy_id"]: e["allow"] for e in gatelog.summarize(read_events(session.repo))}
    assert counts == {"p-2": 1, "p-log": 1}


@pytest.mark.parametrize("route", ROUTES)
def test_every_refusal_keeps_its_own_line(tmp_path: Path, home: Path, route: str) -> None:
    session = Session(tmp_path, home, route, [BLOCKING_GUARD, CLEAN_GUARD, BLOCKING_GUARD, CLEAN_GUARD])
    session.call("toolu_1")
    session.stop()

    assert sorted(r["verdict"] for r in raw_records(session.log)) == ["allow", "block", "block"]


@pytest.mark.parametrize("route", ROUTES)
def test_debug_keeps_every_hooks_line(tmp_path: Path, home: Path, route: str) -> None:
    session = Session(tmp_path, home, route, [CLEAN_GUARD] * 3, CHOCK_LOG_LEVEL="debug")
    session.call("toolu_1")

    assert len([r for r in raw_records(session.log) if r["event"] == "tool_use"]) == 3


def test_with_no_call_id_different_calls_in_one_second_are_both_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The key is (session, second, target): identical calls in one second collapse, different ones never do."""
    monkeypatch.delenv("CHOCK_LOG_LEVEL", raising=False)
    monkeypatch.delenv("CHOCK_GATE_LOG", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(journal, "log_now", lambda: "2026-10-14T00:00:00Z")
    path = tmp_path / "log" / "events.jsonl"
    line = {"verdict": "allow", "target": "ls sha256:00", "session_id": SESSION, "policy_id": "p-a"}

    for policy in ("p-a", "p-b"):
        journal.log_write(path, {**line, "policy_id": policy}, tmp_path)
    journal.log_write(path, {**line, "target": "cat sha256:01"}, tmp_path)
    journal.log_write(path, {**line, "session_id": "other"}, tmp_path)

    written = records(path)
    assert sorted((r["session_id"], r["target"], r[journal.LOG_POLICIES]) for r in written) == [
        ("other", "ls sha256:00", ["p-a"]),
        (SESSION, "cat sha256:01", ["p-a"]),
        (SESSION, "ls sha256:00", ["p-a", "p-b"]),
    ]


def test_an_unencodable_record_is_still_one_line(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"

    journal.log_append(path, {"target": "caf\udce9.txt"})

    assert records(path) == [{"ts": records(path)[0]["ts"], "target": "caf\\udce9.txt"}]
