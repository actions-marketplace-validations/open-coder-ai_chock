"""GAP-1 security review of 0993dc4: five ways past a stop, each closed."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import init_repo
from decision_log_support import CLEAN_GUARD, hook_env, plugin_layout
from runtime_support import write_runtime
from test_repo_stop_git import AGENT, PERSON, _commit, _git
from test_repo_stop_git import repo as git_repo  # noqa: F401 -- the fixture, under the name the tests use

from chock import stop as chock_stop
from chock.gate.runner.halt import HALT_CLIENTS
from chock.vendors import in_agent_vendors

#: `chock stop` writes its machine registry entry under this test's own home, never the real one.
pytestmark = pytest.mark.usefixtures("private_home")


def _deny(proc: subprocess.CompletedProcess) -> bool:
    return '"permissionDecision": "deny"' in proc.stdout


def _hook(
    runtime: Path, cwd: Path, payload: object, home: Path, *flags: str, env: dict | None = None
) -> subprocess.CompletedProcess:
    text = payload if isinstance(payload, str) else json.dumps(payload)
    return subprocess.run(
        [sys.executable, str(runtime), *flags],
        input=text,
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=cwd,
        env={**hook_env(home), **(env or {})},
        timeout=60,
        check=False,
    )


def _call(tool: str, tool_input: dict, cwd: Path) -> dict:
    return {"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": tool_input, "cwd": str(cwd)}


def _stop(repo: Path, *args: str) -> None:
    assert chock_stop.stop_main(["--repo", str(repo), *args]) == 0


# --- 1. a linked worktree is stopped with its main checkout ------------------------------------------------


def test_a_stop_in_the_main_checkout_reaches_a_linked_worktree(git_repo: Path, tmp_path: Path) -> None:  # noqa: F811
    _git(git_repo, "add", "-A")  # an adopter tracks .chock/bin and .chock/compiled: a worktree has them
    assert _git(git_repo, "commit", "-qm", "install", env=PERSON).returncode == 0
    worktree = tmp_path / "wt"
    assert _git(git_repo, "worktree", "add", "-q", str(worktree)).returncode == 0
    runtime = worktree / ".chock" / "bin" / "claude_code.py"
    runtime.parent.mkdir(parents=True, exist_ok=True)
    write_runtime(runtime, "claude_code")
    _stop(git_repo, "--reason", "main checkout")

    read = _hook(runtime, worktree, _call("Read", {"file_path": "a.txt"}, worktree), tmp_path, "--stop-check")
    assert _deny(read), read.stderr
    refused = _commit(worktree, AGENT)
    assert refused.returncode != 0
    assert "stopped: main checkout" in refused.stderr
    assert _commit(worktree, PERSON).returncode == 0


def test_a_worktrees_own_stop_counts_too(git_repo: Path, tmp_path: Path) -> None:  # noqa: F811
    assert _commit(git_repo, PERSON).returncode == 0
    worktree = tmp_path / "wt"
    _git(git_repo, "worktree", "add", "-q", str(worktree))
    _stop(worktree, "--reason", "this worktree")
    assert "stopped: this worktree" in _commit(worktree, AGENT).stderr


# --- 2. the plugin route finds the repository a call touches, not only its cwd -----------------------------


@pytest.fixture
def plugin(tmp_path: Path) -> tuple[Path, Path, Path]:
    """(stopped repository A, plugin runtime outside any repository, a home)."""
    repo, runtime, _ = plugin_layout(tmp_path, CLEAN_GUARD)
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    _stop(repo, "--reason", "plugin")
    return repo, runtime, home


def test_a_write_into_a_stopped_repo_from_a_parent_folder_is_refused(plugin: tuple[Path, Path, Path]) -> None:
    repo, runtime, home = plugin
    call = _call("Write", {"file_path": str(repo / "src" / "x.py"), "content": "x"}, repo.parent)
    assert _deny(_hook(runtime, repo.parent, call, home, "--stop-check"))


def test_a_call_from_a_nested_repo_inside_a_stopped_one_is_refused(plugin: tuple[Path, Path, Path]) -> None:
    repo, runtime, home = plugin
    nested = repo / "vendor" / "lib"
    nested.mkdir(parents=True)
    init_repo(nested)
    assert _deny(_hook(runtime, nested, _call("Bash", {"command": "ls"}, nested), home, "--stop-check"))


def test_an_unrelated_repo_is_not_stopped(plugin: tuple[Path, Path, Path], tmp_path: Path) -> None:
    """A session its client roots in another repository: the machine registry reaches only a session it cannot place."""
    _, runtime, home = plugin
    other = tmp_path / "other"
    other.mkdir()
    init_repo(other)
    call = _call("Read", {"file_path": "x"}, other)
    assert not _deny(_hook(runtime, other, call, home, "--stop-check", env={"CLAUDE_PROJECT_DIR": str(other)}))


# --- 3. no opt-out variable makes an agent a person for stop or resume -------------------------------------


@pytest.mark.parametrize("main", [chock_stop.stop_main, chock_stop.resume_main], ids=["stop", "resume"])
def test_chock_agent_commit_zero_does_not_clear_an_agent_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, main
) -> None:
    init_repo(tmp_path)
    stop = tmp_path / ".chock" / "stop.json"
    stop.parent.mkdir()
    stop.write_text('{"scope": "all", "reason": "kept"}', encoding="utf-8")
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setenv("CHOCK_AGENT_COMMIT", "0")
    assert main(["--repo", str(tmp_path)]) == 1
    assert json.loads(stop.read_text(encoding="utf-8"))["reason"] == "kept"


# --- 4. a git marker's client is matched loosely, and an unknown one stays in scope ------------------------


def test_cursor_agent_is_reached_by_a_stop_on_cursor(git_repo: Path) -> None:  # noqa: F811
    _stop(git_repo, "--agent", "cursor")
    assert _commit(git_repo, {"AI_AGENT": "cursor-agent_1.2_agent"}).returncode != 0


def test_an_unmappable_ai_agent_stays_in_scope(git_repo: Path) -> None:  # noqa: F811
    _stop(git_repo, "--agent", "codex_cli")
    assert _commit(git_repo, {"AI_AGENT": "mystery_1.0_agent"}).returncode != 0
    assert _commit(git_repo, {"CLAUDECODE": "1"}).returncode == 0, "a known other client is not this stop's"


def test_the_client_list_is_every_in_agent_vendor() -> None:
    assert sorted(HALT_CLIENTS) == sorted(in_agent_vendors())


# --- 5. an unreadable payload under --stop-check is refused while stopped -----------------------------------


def test_an_unreadable_payload_is_refused_while_stopped_and_allowed_otherwise(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    init_repo(repo)
    runtime = repo / ".chock" / "bin" / "claude_code.py"
    runtime.parent.mkdir(parents=True)
    write_runtime(runtime, "claude_code")
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    unstopped = _hook(runtime, repo, "not json {", home, "--stop-check")
    assert (unstopped.returncode, _deny(unstopped)) == (0, False)
    _stop(repo)
    stopped = _hook(runtime, repo, "not json {", home, "--stop-check")
    assert _deny(stopped) or stopped.returncode == 2, (stopped.returncode, stopped.stdout, stopped.stderr)
    assert os.path.exists(repo / ".chock" / "stop.json")
