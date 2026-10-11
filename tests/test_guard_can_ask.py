"""CHOCK_CAN_ASK: the dispatcher tells a guard whether its client prompts on an ask; nobody else does."""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from chock.eval import execute
from chock.gate import guard_runner, runtime_bundle

DUMP = 'printf "%s" "${CHOCK_CAN_ASK-unset}" > "$OUT"; exit 0'
ASK = 'echo "confirm first"; exit 3'
BLOCK = 'echo "no"; exit 1'
CLEAN = "exit 0"

#: The plan's table (org-plan plan/one-oh-gaps.md C1b): each vendor's value at its shell pre-tool event.
PLANNED = {"claude_code": "1", "vscode_copilot": "1", "cursor": "1", "codex_cli": "0", "devin": "0"}

_HOOK = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": "ls"}}
_CURSOR = {"command": "ls", "cwd": ".", "conversation_id": "c", "workspace_roots": ["."]}
#: One shell pre_tool payload per bundle that has one, with the wire event it names.
PAYLOADS = {
    "claude_code": ("PreToolUse", _HOOK),
    "codex_cli": ("PreToolUse", _HOOK),
    "cursor": ("beforeShellExecution", {**_CURSOR, "hook_event_name": "beforeShellExecution"}),
    "devin": ("PreToolUse", _HOOK),
    "gemini_cli": ("BeforeTool", {**_HOOK, "hook_event_name": "BeforeTool"}),
    "tabnine": ("BeforeTool", {**_HOOK, "hook_event_name": "BeforeTool"}),
    "vscode_copilot": ("PreToolUse", _HOOK),
    "windsurf": ("pre_run_command", {"agent_action_name": "pre_run_command", "tool_info": {"command_line": "ls"}}),
}
#: Cursor events beyond the shell one: the value follows the event that fired, not the agent.
CURSOR_EVENTS = [
    ("preToolUse", {**_HOOK, "hook_event_name": "preToolUse", "conversation_id": "c", "workspace_roots": ["."]}, "0"),
    ("unnamed shell shape", _CURSOR, "1"),
]


def make_guard(tmp_path: Path, body: str) -> Path:
    guard = tmp_path / "g.sh"
    guard.write_text(f"#!/usr/bin/env bash\n{body}\n", encoding="utf-8", newline="\n")
    guard.chmod(guard.stat().st_mode | stat.S_IEXEC)
    return guard


def seen(tmp_path: Path) -> str:
    return (tmp_path / "seen.txt").read_text(encoding="utf-8")


@pytest.fixture
def dumping_guard(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("OUT", str(tmp_path / "seen.txt"))
    # An inherited value must never reach the guard: only the dispatcher may say.
    monkeypatch.setenv(guard_runner.CAN_ASK_ENV, "inherited")
    return make_guard(tmp_path, DUMP)


def run_bundle(agent: str, payload: dict, guard: Path, tmp_path: Path) -> subprocess.CompletedProcess[bytes]:
    runtime = tmp_path / f"{agent}.py"
    runtime.write_text(runtime_bundle.render(agent), encoding="utf-8")
    return subprocess.run(
        [sys.executable, str(runtime), "--guard", str(guard)],
        input=json.dumps(payload).encode(),
        capture_output=True,
        cwd=tmp_path,
        env=os.environ.copy(),
        check=False,
    )


@pytest.mark.parametrize("agent", sorted(PLANNED))
def test_each_planned_vendor_resolves_to_the_planned_value(agent: str) -> None:
    event = PAYLOADS[agent][0]
    assert str(int(runtime_bundle.pre_tool_can_ask(agent)[event])) == PLANNED[agent]


@pytest.mark.parametrize("agent", sorted(PAYLOADS))
def test_the_dispatcher_hands_each_vendors_guard_its_value(agent, tmp_path, dumping_guard) -> None:
    event, payload = PAYLOADS[agent]

    run_bundle(agent, payload, dumping_guard, tmp_path)

    expected = str(int(runtime_bundle.pre_tool_can_ask(agent)[event]))
    assert seen(tmp_path) == PLANNED.get(agent, expected) == expected


@pytest.mark.parametrize(("event", "payload", "expected"), CURSOR_EVENTS, ids=[e[0] for e in CURSOR_EVENTS])
def test_cursor_follows_the_event_that_fired(event, payload, expected, tmp_path, dumping_guard) -> None:
    run_bundle("cursor", payload, dumping_guard, tmp_path)

    assert seen(tmp_path) == expected


@pytest.mark.parametrize("agent", sorted(PAYLOADS))
def test_an_unknown_event_name_cannot_ask(agent) -> None:
    namespace: dict = {}
    exec(runtime_bundle.render(agent), namespace)  # noqa: S102 -- loading the rendered bundle is the test
    unknown = {"hook_event_name": "NotAnEvent", "hookEventName": "NotAnEvent", "agent_action_name": "NotAnEvent"}

    assert namespace["_chock_can_ask"](unknown) is False


@pytest.mark.parametrize("can_ask", [True, False])
def test_evaluate_sets_one_or_zero(can_ask, tmp_path, dumping_guard) -> None:
    guard_runner.evaluate(["--guard", str(dumping_guard)], "ls", "Bash", can_ask=can_ask)

    assert seen(tmp_path) == ("1" if can_ask else "0")


def test_unset_outside_the_dispatcher(tmp_path, dumping_guard) -> None:
    guard_runner.evaluate(["--guard", str(dumping_guard)], "ls", "Bash")
    assert seen(tmp_path) == "unset"

    guard_runner.run_guard(dumping_guard, "ls")
    assert seen(tmp_path) == "unset"


def test_unset_in_eval_replay(tmp_path, dumping_guard) -> None:
    execute._run_guard(tmp_path, dumping_guard, "ls")

    assert seen(tmp_path) == "unset"


@pytest.mark.parametrize("body", [ASK, BLOCK, CLEAN])
def test_no_guard_verdict_changes_with_the_value(body, tmp_path) -> None:
    guard = make_guard(tmp_path, body)
    argv = ["--guard", str(guard)]

    legacy = guard_runner.evaluate(argv, "ls", "Bash")

    assert guard_runner.evaluate(argv, "ls", "Bash", can_ask=True) == legacy
    assert guard_runner.evaluate(argv, "ls", "Bash", can_ask=False) == legacy
