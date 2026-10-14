"""GAP-2b: a plain allowed tool call is one info line naming no policy, written by its first hook; refusals stay per policy."""

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
    records,
    sync_layout,
    sync_log,
)

from chock import gatelog, gatelog_summary
from chock.gate.runner import journal
from chock.gatelog_read import allowed_calls, read_events

LAYOUTS = {
    "sync": (sync_layout, lambda repo, home: sync_log(repo)),
    "plugin": (plugin_layout, lambda repo, home: plugin_log(home)),
}
ROUTES = sorted(LAYOUTS)
SESSION = "s"
POLICY_FIELDS = ("policy_id", "policies", "plugin", "plugin_version")


@pytest.fixture
def home(tmp_path: Path) -> Path:
    folder = tmp_path / "home"
    folder.mkdir()
    return folder


def _hooks(tmp_path: Path, home: Path, route: str, guards: list[str], calls: list[str], **levels: str) -> Path:
    """Each call (by tool_use_id) judged by one hook per guard, as a client runs every matching hook; the repo.

    On the sync route each further guard is another policy's (`.agents/policies/p-<n>/implementations/`).
    """
    layout, _ = LAYOUTS[route]
    repo, runtime, first = layout(tmp_path, guards[0])
    paths = [first]
    for at, body in enumerate(guards[1:], start=2):
        folder = first.parent.parent.with_name(f"p-{at}") / "implementations" if route == "sync" else first.parent
        folder.mkdir(parents=True, exist_ok=True)
        paths.append(folder / f"guard{at}.sh")
        paths[-1].write_text(body, encoding="utf-8", newline="\n")
    payload = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": "ls"}}
    for call in calls:
        for guard in paths:
            subprocess.run(
                [sys.executable, str(runtime), "--guard", str(guard)],
                input=json.dumps({**payload, "session_id": SESSION, "tool_use_id": call, "cwd": str(repo)}),
                capture_output=True,
                text=True,
                encoding="utf-8",
                cwd=repo,
                env=hook_env(home, **levels),
                timeout=60,
                check=False,
            )
    return repo


@pytest.mark.parametrize("route", ROUTES)
def test_a_plain_allow_is_one_line_per_tool_call_naming_no_policy(tmp_path: Path, home: Path, route: str) -> None:
    repo = _hooks(tmp_path, home, route, [CLEAN_GUARD] * 3, ["toolu_1", "toolu_2"])

    found = records(LAYOUTS[route][1](repo, home))
    assert [(r["verdict"], r["level"]) for r in found] == [("allow", "info")] * 2
    assert all(not set(POLICY_FIELDS) & set(r) and "call" not in r for r in found)


def test_one_call_two_policies_is_one_line_counted_as_one_allowed_call(tmp_path: Path, home: Path) -> None:
    repo = _hooks(tmp_path, home, "sync", [CLEAN_GUARD, CLEAN_GUARD], ["toolu_1"])

    [line] = records(sync_log(repo))
    assert not set(POLICY_FIELDS) & set(line)
    events = read_events(repo, heartbeats=True)
    assert allowed_calls(events) == 1
    assert gatelog.summarize(events) == []  # no policy is credited with the allow
    report = gatelog_summary.summary(events)
    assert (report["allowed_calls"], report["policies"]) == (1, [])


@pytest.mark.parametrize("route", ROUTES)
def test_every_refusal_keeps_its_own_line(tmp_path: Path, home: Path, route: str) -> None:
    guards = [BLOCKING_GUARD, CLEAN_GUARD, BLOCKING_GUARD, CLEAN_GUARD]
    repo = _hooks(tmp_path, home, route, guards, ["toolu_1"])

    found = records(LAYOUTS[route][1](repo, home))
    assert sorted(r["verdict"] for r in found) == ["allow", "block", "block"]
    if route == "sync":  # each refusal names the policy that refused
        assert sorted(r["policy_id"] for r in found if r["verdict"] == "block") == ["p-3", "p-log"]


@pytest.mark.parametrize("route", ROUTES)
def test_debug_keeps_every_hooks_line(tmp_path: Path, home: Path, route: str) -> None:
    repo = _hooks(tmp_path, home, route, [CLEAN_GUARD] * 3, ["toolu_1"], CHOCK_LOG_LEVEL="debug")

    found = records(LAYOUTS[route][1](repo, home))
    assert len(found) == 3
    assert allowed_calls(found) == 1  # the call's own line; the other hooks' traces name their policy


def test_with_no_call_id_different_calls_in_one_second_are_both_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The key is (session, second, target): identical calls in one second are one line, different ones never."""
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

    assert sorted((r["session_id"], r["target"]) for r in records(path)) == [
        ("other", "ls sha256:00"),
        (SESSION, "cat sha256:01"),
        (SESSION, "ls sha256:00"),
    ]


def test_an_unencodable_record_is_still_one_line(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"

    journal.log_append(path, {"target": "caf\udce9.txt"})

    assert records(path) == [{"ts": records(path)[0]["ts"], "target": "caf\\udce9.txt"}]
