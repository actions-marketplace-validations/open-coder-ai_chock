"""GAP-2: every decision line says who acted (`session_id`, `actor`) and what was touched (`target`), as a fingerprint."""

from __future__ import annotations

import hashlib
import json
import os
import stat
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
from history_support import SECRET

from chock.gate import assemble, decision_target
from chock.gate.runner import actor, log

LAYOUTS = {
    "sync": (sync_layout, lambda repo, home: sync_log(repo)),
    "plugin": (plugin_layout, lambda repo, home: plugin_log(home)),
}
ROUTES = sorted(LAYOUTS)
SESSION = "sess-123"
HOME_FILE = "notes/private.txt"
CLEAN_SPEC = {
    "kind": "content_regex",
    "on": ["tool_use"],
    "action": "block",
    "message": "secret",
    "params": {"scan": "added_lines", "content_pattern": r"(?i)(AKIA[0-9A-Z]{16})"},
}
MARKERS = ("CHOCK_AGENT_COMMIT", "CLAUDECODE", "AI_AGENT")


@pytest.fixture
def home(tmp_path: Path) -> Path:
    folder = tmp_path / "home"
    folder.mkdir()
    return folder


def _sha(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _call(tmp_path: Path, home: Path, route: str, tool: str, tool_input: dict, **extra: object) -> list[dict]:
    """One PreToolUse call through the rendered runtime on `route` (guard clean); the lines it logged."""
    layout, log_of = LAYOUTS[route]
    tmp_path.mkdir(exist_ok=True)
    repo, runtime, guard = layout(tmp_path, extra.pop("guard", CLEAN_GUARD))
    payload = {"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": tool_input, "cwd": str(repo)}
    payload.update(extra)
    subprocess.run(
        [sys.executable, str(runtime), "--guard", str(guard)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=repo,
        env=hook_env(home),
        timeout=60,
        check=False,
    )
    return records(log_of(repo, home))


@pytest.mark.parametrize("route", ROUTES)
def test_session_id_is_on_the_line_when_the_client_gives_one(tmp_path: Path, home: Path, route: str) -> None:
    [given] = _call(tmp_path / "a", home, route, "Bash", {"command": "ls"}, session_id=SESSION)
    [absent] = _call(tmp_path / "b", home / "b", route, "Bash", {"command": "ls"})

    assert given["session_id"] == SESSION
    assert "session_id" not in absent


@pytest.mark.parametrize("route", ROUTES)
def test_actor_names_the_agent_client(tmp_path: Path, home: Path, route: str) -> None:
    [record] = _call(tmp_path, home, route, "Bash", {"command": "ls"}, session_id=SESSION)

    assert record["actor"] == "agent:claude_code"


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("guard", [CLEAN_GUARD, BLOCKING_GUARD], ids=["allow", "block"])
def test_a_shell_target_is_the_program_and_a_hash_never_an_argument(
    tmp_path: Path, home: Path, route: str, guard: str
) -> None:
    command = f"FOO=bar /usr/local/bin/deploy --token {SECRET} --to prod.example.invalid"
    [record] = _call(tmp_path, home, route, "Bash", {"command": command}, session_id=SESSION, guard=guard)

    assert record["target"] == f"- {_sha(command)}"
    written = json.dumps(record)
    for argument in (SECRET, "--token", "prod.example.invalid", "/usr/local/bin", "FOO=bar"):
        assert argument not in written


@pytest.mark.parametrize("route", ROUTES)
def test_a_file_in_the_repo_is_its_repo_relative_path(tmp_path: Path, home: Path, route: str) -> None:
    file_path = str(tmp_path / "repo" / "src" / "app.py")
    [record] = _call(tmp_path, home, route, "Write", {"file_path": file_path, "content": SECRET}, session_id=SESSION)

    assert record["target"] == "src/app.py"
    assert SECRET not in json.dumps(record)


@pytest.mark.parametrize("route", ROUTES)
def test_a_file_outside_the_repo_is_hashed_never_written_in_clear(tmp_path: Path, home: Path, route: str) -> None:
    outside = home / HOME_FILE
    [record] = _call(tmp_path, home, route, "Read", {"file_path": str(outside)}, session_id=SESSION)

    assert record["target"] == "outside:" + _sha(os.path.realpath(outside))
    written = json.dumps(record)
    assert str(home) not in written
    assert "private.txt" not in written


@pytest.mark.parametrize("route", ROUTES)
def test_an_mcp_call_is_server_slash_tool(tmp_path: Path, home: Path, route: str) -> None:
    [record] = _call(tmp_path, home, route, "mcp__github__create_issue", {"title": SECRET}, session_id=SESSION)

    assert record["target"] == "github/create_issue"
    assert SECRET not in json.dumps(record)


@pytest.mark.skipif(os.name == "nt", reason="POSIX file modes")
@pytest.mark.parametrize("route", ROUTES)
def test_the_log_file_stays_owner_only(tmp_path: Path, home: Path, route: str) -> None:
    _call(tmp_path, home, route, "Bash", {"command": "ls"})
    path = LAYOUTS[route][1](tmp_path / "repo", home)

    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def _sync_gate(tmp_path: Path, home: Path, tool: str, tool_input: dict) -> tuple[Path, subprocess.CompletedProcess]:
    """A `--gate` PreToolUse call on the sync route, gate.py beside the runtime as `chock sync` lays it out."""
    repo, runtime, _ = sync_layout(tmp_path, CLEAN_GUARD)
    (runtime.parent / "gate.py").write_text(assemble.runner_source(), encoding="utf-8")
    gate = repo / ".chock" / "compiled" / "p-gate" / "pre-tool-use" / "gate.json"
    gate.parent.mkdir(parents=True)
    gate.write_text(json.dumps(CLEAN_SPEC), encoding="utf-8")
    payload = {"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": tool_input, "session_id": SESSION}
    proc = subprocess.run(
        [sys.executable, str(runtime), "--gate", str(gate)],
        input=json.dumps({**payload, "cwd": str(repo)}),
        capture_output=True,
        text=True,
        cwd=repo,
        env=hook_env(home),
        timeout=60,
        check=False,
    )
    return repo, proc


@pytest.mark.parametrize(("content", "verdict"), [("x = 1\n", "allow"), (f'KEY = "{SECRET}"\n', "block")])
def test_gate_py_writes_the_fields_on_its_own_line(tmp_path: Path, home: Path, content: str, verdict: str) -> None:
    """The sync route's compiled gate writes the call's one line: with the runtime's session_id, actor, target."""
    repo, proc = _sync_gate(
        tmp_path, home, "Write", {"file_path": str(tmp_path / "repo" / "app.py"), "content": content}
    )

    [record] = records(sync_log(repo))
    policy = None if verdict == "allow" else "p-gate"  # an allowed tool call's one line names no policy
    assert (record.get("policy_id"), record["verdict"], record["level"]) == (policy, verdict, "info"), proc.stderr
    assert (record["session_id"], record["actor"], record["target"]) == (SESSION, "agent:claude_code", "app.py")
    assert SECRET not in sync_log(repo).read_text(encoding="utf-8")


def test_a_gate_with_nothing_to_judge_leaves_the_line_to_the_runtime(tmp_path: Path, home: Path) -> None:
    """A shell call writes no file, so gate.py never runs: the runtime still logs the allowed action, once."""
    repo, _ = _sync_gate(tmp_path, home, "Bash", {"command": f"echo {SECRET}"})

    [record] = records(sync_log(repo))
    assert (record["verdict"], record["actor"], record["target"]) == (
        "allow",
        "agent:claude_code",
        f"echo {_sha('echo ' + SECRET)}",
    )
    assert SECRET not in json.dumps(record)


@pytest.mark.parametrize(
    ("env", "expected"),
    [
        ({}, "person"),
        ({"CLAUDECODE": "1"}, "agent:claude_code"),
        ({"AI_AGENT": "claude-code_2.1.0_agent"}, "agent:claude_code"),
        ({"AI_AGENT": "Some Agent!"}, "agent:someagent"),
        ({"CHOCK_AGENT_COMMIT": "1"}, "agent:unknown"),
        ({"CHOCK_AGENT_COMMIT": "0", "CLAUDECODE": "1"}, "agent:claude_code"),
        ({"CHOCK_AGENT_COMMIT": "0"}, "person"),
    ],
)
def test_a_git_hook_line_names_the_actor_by_the_actor_rule(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, env: dict[str, str], expected: str
) -> None:
    for name in MARKERS:
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("CHOCK_GATE_LOG", raising=False)
    monkeypatch.setenv("CHOCK_LOG_LEVEL", "info")
    signal = actor.agent_signal(tmp_path)

    log._log_script_hook("p-x", "commit", "warn", tmp_path, log._actor(signal))

    [record] = records(tmp_path / ".chock" / "log" / "gate-events.jsonl")
    assert record["actor"] == expected
    assert "target" not in record
    assert "session_id" not in record


def test_gate_py_keeps_only_short_string_fields_from_the_runtime() -> None:
    given = {"session_id": "s", "actor": 7, "target": "x" * 600, "matches": ["leak"]}

    assert log._actor(None, given, hook=True) == {"actor": "agent:unknown", "session_id": "s"}


@pytest.mark.parametrize(
    ("command", "program"),
    [
        ("git push origin main", "git"),
        ("FOO=1 BAR=2 /opt/tools/bin/make -j4", "make"),
        ("PATH=$HOME/bin:$PATH chock sync", "chock"),
        (f"P=$(python -c 'print({SECRET!r})') echo $P", "-"),
        (f'TOKEN="{SECRET}" curl x', "-"),
        ("--version", "-"),
        ("", "-"),
        (r"C:\Tools\deploy.exe --token x", "-"),
    ],
)
def test_the_program_is_a_bare_name_or_dash_never_an_argument(command: str, program: str) -> None:
    assert decision_target.dlog_command_print(command) == f"{program} {_sha(command)}"
