"""GAP-2b: a plain allowed tool call is one info line, however many policy hooks judge it; refusals stay per policy."""

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

from chock.gate.runner import journal

LAYOUTS = {
    "sync": (sync_layout, lambda repo, home: sync_log(repo)),
    "plugin": (plugin_layout, lambda repo, home: plugin_log(home)),
}
ROUTES = sorted(LAYOUTS)


@pytest.fixture
def home(tmp_path: Path) -> Path:
    folder = tmp_path / "home"
    folder.mkdir()
    return folder


def _hooks(tmp_path: Path, home: Path, route: str, guards: list[str], calls: list[str], **levels: str) -> list[dict]:
    """Each call (by tool_use_id) judged by one hook per guard, as a client runs every matching hook; the lines."""
    layout, log_of = LAYOUTS[route]
    repo, runtime, first = layout(tmp_path, guards[0])
    paths = [first]
    for at, body in enumerate(guards[1:], start=2):
        extra = first.with_name(f"guard{at}.sh")
        extra.write_text(body, encoding="utf-8", newline="\n")
        paths.append(extra)
    for call in calls:
        payload = {
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": "ls"},
            "session_id": "s",
            "tool_use_id": call,
            "cwd": str(repo),
        }
        for guard in paths:
            subprocess.run(
                [sys.executable, str(runtime), "--guard", str(guard)],
                input=json.dumps(payload),
                capture_output=True,
                text=True,
                encoding="utf-8",
                cwd=repo,
                env=hook_env(home, **levels),
                timeout=60,
                check=False,
            )
    return records(log_of(repo, home))


@pytest.mark.parametrize("route", ROUTES)
def test_a_plain_allow_is_one_line_per_tool_call_not_per_hook(tmp_path: Path, home: Path, route: str) -> None:
    found = _hooks(tmp_path, home, route, [CLEAN_GUARD] * 3, ["toolu_1", "toolu_2"])

    assert [(r["verdict"], r["level"]) for r in found] == [("allow", "info")] * 2
    assert all("call" not in r for r in found)


@pytest.mark.parametrize("route", ROUTES)
def test_every_refusal_keeps_its_own_line(tmp_path: Path, home: Path, route: str) -> None:
    found = _hooks(tmp_path, home, route, [BLOCKING_GUARD, CLEAN_GUARD, BLOCKING_GUARD, CLEAN_GUARD], ["toolu_1"])

    assert sorted(r["verdict"] for r in found) == ["allow", "block", "block"]


@pytest.mark.parametrize("route", ROUTES)
def test_debug_keeps_every_hooks_line(tmp_path: Path, home: Path, route: str) -> None:
    found = _hooks(tmp_path, home, route, [CLEAN_GUARD] * 3, ["toolu_1"], CHOCK_LOG_LEVEL="debug")

    assert len(found) == 3


def test_a_call_with_no_id_is_collapsed_within_its_second(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CHOCK_LOG_LEVEL", raising=False)
    monkeypatch.delenv("CHOCK_GATE_LOG", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    path = tmp_path / "log" / "events.jsonl"
    line = {"verdict": "allow", "target": "ls sha256:00", "session_id": "s"}

    for _ in range(3):
        journal.log_write(path, line, tmp_path)
    journal.log_write(path, {**line, "target": "cat sha256:01"}, tmp_path)

    assert [r["target"] for r in records(path)][-2:] == ["ls sha256:00", "cat sha256:01"]
    assert len(records(path)) in (2, 3)  # 3 only when the second turned between the writes


def test_an_unencodable_record_is_still_one_line(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"

    journal.log_append(path, {"target": "caf\udce9.txt"})

    assert records(path) == [{"ts": records(path)[0]["ts"], "target": "caf\\udce9.txt"}]
