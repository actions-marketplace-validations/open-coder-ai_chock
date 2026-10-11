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

#: The plan's table (org-plan plan/one-oh-gaps.md C1b), read from each vendor's native pre_tool gate.
PLANNED = {"claude_code": "1", "vscode_copilot": "1", "cursor": "0", "codex_cli": "0", "devin": "0"}

_HOOK = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": "ls"}}
#: One pre_tool shell payload per bundle that has a shell pre_tool event.
PAYLOADS = {
    "claude_code": _HOOK,
    "codex_cli": _HOOK,
    "cursor": {
        "hook_event_name": "preToolUse",
        "tool_name": "Shell",
        "tool_input": {"command": "ls"},
        "conversation_id": "c",
        "workspace_roots": ["."],
    },
    "devin": _HOOK,
    "gemini_cli": {**_HOOK, "hook_event_name": "BeforeTool"},
    "tabnine": {**_HOOK, "hook_event_name": "BeforeTool"},
    "vscode_copilot": _HOOK,
    "windsurf": {"agent_action_name": "pre_run_command", "tool_info": {"command_line": "ls"}},
}


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


@pytest.mark.parametrize("agent", sorted(PLANNED))
def test_each_planned_vendor_resolves_to_the_planned_value(agent: str) -> None:
    assert str(int(runtime_bundle.pre_tool_can_ask(agent))) == PLANNED[agent]


@pytest.mark.parametrize("agent", sorted(PAYLOADS))
def test_the_dispatcher_hands_each_vendors_guard_its_value(agent, tmp_path, dumping_guard) -> None:
    runtime = tmp_path / f"{agent}.py"
    runtime.write_text(runtime_bundle.render(agent), encoding="utf-8")

    subprocess.run(
        [sys.executable, str(runtime), "--guard", str(dumping_guard)],
        input=json.dumps(PAYLOADS[agent]).encode(),
        capture_output=True,
        cwd=tmp_path,
        env=os.environ.copy(),
        check=False,
    )

    expected = str(int(runtime_bundle.pre_tool_can_ask(agent)))
    assert seen(tmp_path) == PLANNED.get(agent, expected) == expected


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
