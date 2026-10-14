"""GAP-1 wiring: sync gives every client one matcher-less stop check, so a stop refuses a Read whatever policies match.

Also: only a person changes a stop (the actor rule).
"""

from __future__ import annotations

import json
import statistics
import subprocess
import sys
import time
from pathlib import Path

import pytest
from conftest import baseline_policy, init_repo

from chock import stop as chock_stop
from chock.compile.compiler import compile_policy
from chock.compile.surfaces import Surface
from chock.hooks import in_agent_install, stop_check
from chock.hooks.in_agent_generic import STOP_CHECK_ID
from chock.vendors import config_path

READ = {"hook_event_name": "PreToolUse", "tool_name": "Read", "session_id": "e2e", "tool_use_id": "t1"}


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A repository whose one policy guards the shell alone: no policy's hook matches a Read."""
    root = tmp_path / "repo"
    root.mkdir()
    init_repo(root)
    compile_policy(
        baseline_policy("block-destructive-commands"),
        targets=[Surface.PRE_TOOL_USE.value],
        output_root=root / ".chock" / "compiled",
        agents=["claude"],
        repo_root=root,
    )
    for vendor in in_agent_install.WIRED_VENDORS:
        in_agent_install.install_hooks(root, vendor)
    return root


def _matching_read(repo: Path) -> list[str]:
    settings = json.loads((repo / config_path("claude_code")).read_text(encoding="utf-8"))
    entries = settings["hooks"]["PreToolUse"]
    return [h["command"] for e in entries if not e.get("matcher") for h in e["hooks"]]


def _hook(repo: Path, command: str) -> subprocess.CompletedProcess:
    payload = {**READ, "tool_input": {"file_path": str(repo / "notes.txt")}, "cwd": str(repo)}
    return subprocess.run(
        command, shell=True, cwd=repo, input=json.dumps(payload), capture_output=True, text=True, check=False
    )


def test_sync_wires_one_matcherless_stop_check_beside_a_shell_only_policy(repo: Path) -> None:
    assert _matching_read(repo) == [stop_check.command("claude_code")]


@pytest.mark.parametrize("vendor", ["codex_cli", "devin", "gemini_cli", "cursor", "mistral_vibe"])
def test_every_client_gets_the_stop_check(repo: Path, vendor: str) -> None:
    path = repo / config_path(vendor)
    assert stop_check.STOP_CHECK_FLAG in path.read_text(encoding="utf-8")
    assert STOP_CHECK_ID not in in_agent_install.install_hooks(repo, vendor)


def test_uninstall_removes_the_stop_check(repo: Path) -> None:
    in_agent_install.uninstall_hooks(repo, "gemini_cli")
    path = repo / config_path("gemini_cli")
    assert not path.exists() or stop_check.STOP_CHECK_FLAG not in path.read_text(encoding="utf-8")


def test_a_read_no_policy_matches_is_refused_while_stopped(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The e2e: the real hook command sync wrote, stop, refused, resume, allowed; the log lines printed."""
    monkeypatch.delenv("CHOCK_GATE_LOG")
    [command] = _matching_read(repo)
    assert chock_stop.stop_main(["--repo", str(repo), "--reason", "e2e incident"]) == 0
    refused = _hook(repo, command)
    assert '"permissionDecision": "deny"' in refused.stdout, refused.stderr
    assert chock_stop.resume_main(["--repo", str(repo)]) == 0
    allowed = _hook(repo, command)
    assert "deny" not in allowed.stdout, allowed.stdout
    lines = (repo / ".chock" / "log" / "gate-events.jsonl").read_text(encoding="utf-8").splitlines()
    with capsys.disabled():
        print(
            "\nhook:",
            command,
            "\nstopped ->",
            refused.stdout.strip(),
            "\nresumed ->",
            allowed.stdout.strip() or "(allow)",
        )
        print("\n".join(lines))
    stopped = [json.loads(line) for line in lines if '"reason": "stopped"' in line]
    assert [(r["policy_id"], r["actor"], r["target"]) for r in stopped] == [
        ("chock-stop", "agent:claude_code", "notes.txt")
    ]


@pytest.mark.parametrize("main", [chock_stop.stop_main, chock_stop.resume_main], ids=["stop", "resume"])
def test_only_a_person_changes_a_stop(repo: Path, monkeypatch: pytest.MonkeyPatch, main) -> None:
    monkeypatch.delenv("CHOCK_GATE_LOG")
    (repo / ".chock" / "stop.json").write_text('{"scope": "codex_cli", "reason": "x"}', encoding="utf-8")
    monkeypatch.setenv("CLAUDECODE", "1")
    assert main(["--repo", str(repo)]) == 1
    assert json.loads((repo / ".chock" / "stop.json").read_text(encoding="utf-8"))["scope"] == "codex_cli"
    [record] = [json.loads(line) for line in (repo / ".chock" / "log" / "gate-events.jsonl").read_text().splitlines()]
    assert (record["verdict"], record["reason"], record["actor"]) == ("block", "stopped", "agent:claude_code")


def test_stop_check_latency_unstopped(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Measured, not asserted against a budget: the added hook's wall time per tool call, median of 50."""
    [command] = _matching_read(repo)
    times = []
    for _ in range(50):
        started = time.perf_counter()
        assert "deny" not in _hook(repo, command).stdout
        times.append((time.perf_counter() - started) * 1000)
    with capsys.disabled():
        print(f"\nstop-check unstopped: median {statistics.median(times):.1f} ms over 50 on {sys.platform}")
