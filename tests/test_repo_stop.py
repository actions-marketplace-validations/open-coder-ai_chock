"""GAP-1: `chock stop` refuses every tool call of an agent in scope at its pre-tool hook, fail-closed; `chock resume` lifts it."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from decision_log_support import CLEAN_GUARD, hook_env, plugin_layout, plugin_log, records, sync_layout, sync_log
from stop_person_support import person_resume

from chock import stop as chock_stop
from chock.lifecycle import status_main
from chock.scaffold.gitrules import ensure_git_rules

#: `chock stop` writes its machine registry entry under this test's own home, never the real one.
pytestmark = pytest.mark.usefixtures("private_home")

LAYOUTS = {
    "sync": (sync_layout, lambda repo, home: sync_log(repo)),
    "plugin": (plugin_layout, lambda repo, home: plugin_log(home)),
}
ROUTES = sorted(LAYOUTS)
REASON = "incident 42"
READ = ("Read", {"file_path": "notes.txt"})


@pytest.fixture
def home(tmp_path: Path) -> Path:
    folder = tmp_path / "home"
    folder.mkdir(exist_ok=True)
    return folder


def _stop(repo: Path, *args: str) -> None:
    assert chock_stop.stop_main(["--repo", str(repo), "--reason", REASON, *args]) == 0


def _call(repo: Path, runtime: Path, guard: Path, home: Path, tool: tuple[str, dict], **env: str):
    payload = {"hook_event_name": "PreToolUse", "tool_name": tool[0], "tool_input": tool[1], "cwd": str(repo)}
    payload.update(session_id="sess-1", tool_use_id="call-1")
    return subprocess.run(
        [sys.executable, str(runtime), "--guard", str(guard)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=repo,
        env={**hook_env(home), **env},
        timeout=60,
        check=False,
    )


def _layout(tmp_path: Path, home: Path, route: str):
    layout, log_of = LAYOUTS[route]
    repo, runtime, guard = layout(tmp_path, CLEAN_GUARD)
    return repo, runtime, guard, (lambda: records(log_of(repo, home)))


def _denied(proc: subprocess.CompletedProcess) -> bool:
    return '"permissionDecision": "deny"' in proc.stdout


@pytest.mark.parametrize("route", ROUTES)
def test_a_read_is_refused_while_stopped_and_allowed_after_resume(tmp_path: Path, home: Path, route: str) -> None:
    repo, runtime, guard, logged = _layout(tmp_path, home, route)
    assert not _denied(_call(repo, runtime, guard, home, READ))

    _stop(repo)
    refused = _call(repo, runtime, guard, home, READ)
    assert _denied(refused), refused.stderr
    assert f"stopped: {REASON}" in refused.stdout

    assert person_resume(repo) == 0
    assert not (repo / ".chock" / "stop.json").exists()
    assert not _denied(_call(repo, runtime, guard, home, READ))
    stopped = [r for r in logged() if r.get("reason") == "stopped"]
    assert len(stopped) == 1


@pytest.mark.parametrize("route", ROUTES)
def test_the_refusal_record_says_stopped_and_who_did_what(tmp_path: Path, home: Path, route: str) -> None:
    repo, runtime, guard, logged = _layout(tmp_path, home, route)
    _stop(repo)
    _call(repo, runtime, guard, home, ("Bash", {"command": "ls -la"}))

    [record] = [r for r in logged() if r.get("reason") == "stopped"]
    assert (record["verdict"], record["event"], record["level"]) == ("block", "tool_use", "info")
    assert (record["actor"], record["session_id"]) == ("agent:claude_code", "sess-1")
    assert record["target"].startswith("ls sha256:")


@pytest.mark.parametrize("body", ["{not json", '{"scope": 7}', '{"scope": "codex-cli!"}', "[]", "\udcff"])
def test_a_stop_file_that_cannot_be_read_refuses_every_agent(tmp_path: Path, home: Path, body: str) -> None:
    repo, runtime, guard, _ = _layout(tmp_path, home, "sync")
    stop = repo / ".chock" / "stop.json"
    stop.write_bytes(body.encode("utf-8", "surrogateescape"))

    refused = _call(repo, runtime, guard, home, READ)
    assert _denied(refused)
    assert "cannot be read" in refused.stdout


def test_a_stop_path_that_is_a_folder_refuses(tmp_path: Path, home: Path) -> None:
    repo, runtime, guard, _ = _layout(tmp_path, home, "sync")
    (repo / ".chock" / "stop.json").mkdir()
    assert _denied(_call(repo, runtime, guard, home, READ))


def test_a_named_client_stops_only_that_client(tmp_path: Path, home: Path) -> None:
    repo, runtime, guard, _ = _layout(tmp_path, home, "sync")
    _stop(repo, "--agent", "codex_cli")
    assert not _denied(_call(repo, runtime, guard, home, READ))

    _stop(repo, "--agent", "claude_code")
    assert _denied(_call(repo, runtime, guard, home, READ))


def test_chock_allow_does_not_loosen_a_stop(tmp_path: Path, home: Path) -> None:
    repo, runtime, guard, _ = _layout(tmp_path, home, "sync")
    _stop(repo)
    assert _denied(_call(repo, runtime, guard, home, READ, CHOCK_ALLOW="p-log", CHOCK_AGENT_COMMIT="0"))


def test_the_observe_level_does_not_loosen_a_stop(tmp_path: Path, home: Path) -> None:
    repo, runtime, guard, _ = _layout(tmp_path, home, "sync")
    (repo / ".chock" / "config.yaml").write_text("rollout: observe\n", encoding="utf-8")
    _stop(repo)
    assert _denied(_call(repo, runtime, guard, home, READ, CHOCK_ROLLOUT="observe"))


def test_stop_writes_scope_reason_who_and_when_and_both_ends_are_logged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, *_ = sync_layout(tmp_path, CLEAN_GUARD)
    monkeypatch.delenv("CHOCK_GATE_LOG")
    _stop(repo, "--agent", "codex_cli")
    doc = json.loads((repo / ".chock" / "stop.json").read_text(encoding="utf-8"))
    assert (doc["scope"], doc["reason"], doc["who"]) == ("codex_cli", REASON, "t@example.com")
    assert doc["when"].endswith("Z")

    assert person_resume(repo) == 0
    stop, resume = records(sync_log(repo))
    assert (stop["event"], stop["scope"], stop["who"], stop["actor"]) == (
        "repo_stop",
        "codex_cli",
        doc["who"],
        "person",
    )
    assert (resume["event"], resume["who"]) == ("repo_resume", "t@example.com")
    assert resume["when"] and stop["policy_id"] == resume["policy_id"] == "chock-stop"


def test_an_unknown_agent_is_refused_by_the_cli(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        chock_stop.stop_main(["--repo", str(tmp_path), "--agent", "nobody"])
    assert not (tmp_path / ".chock" / "stop.json").exists()


def test_status_leads_with_the_stop(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo, *_ = sync_layout(tmp_path, CLEAN_GUARD)
    _stop(repo, "--agent", "codex_cli")
    capsys.readouterr()
    status_main(["--repo", str(repo)])
    first = capsys.readouterr().out.splitlines()[0]
    assert first.startswith("STOPPED: agent codex_cli, by t@example.com at ")
    assert REASON in first


def test_status_names_an_unreadable_stop(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo, *_ = sync_layout(tmp_path, CLEAN_GUARD)
    (repo / ".chock" / "stop.json").write_text("{", encoding="utf-8")
    status_main(["--repo", str(repo)])
    assert capsys.readouterr().out.splitlines()[0].startswith("STOPPED: .chock/stop.json cannot be read")


def test_init_ignores_the_stop_file(tmp_path: Path) -> None:
    ensure_git_rules(tmp_path)
    assert ".chock/stop.json" in (tmp_path / ".gitignore").read_text(encoding="utf-8").splitlines()
