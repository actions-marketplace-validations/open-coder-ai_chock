"""GAP-1 third review of 40e6534: a stop lifted from another repository, a scan past the hook timeout, case."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from decision_log_support import CLEAN_GUARD, sync_layout
from stop_person_support import person_resume
from test_repo_stop_gap1c import _call, _deny, _hook, _repo, _stop
from test_repo_stop_git import AGENT, PERSON, _commit, _git

from chock.gate import repo_stop
from chock.gate.runner.halt import halt_registry_entry
from chock.hooks.installers import get_hooks_dir, install_policy_hooks

#: `chock stop` writes its machine registry entry under this test's own home, never the real one.
pytestmark = pytest.mark.usefixtures("private_home")

RESUME = "env -u CLAUDECODE -u AI_AGENT chock resume --repo {repo}"
#: The confirmed timing attack: 500 distinct path strings of 4096 characters, 2048 folders deep.
DEEP_COUNT, DEEP_LEN = 500, 4096
CAP_SECONDS = 2.0


@pytest.fixture
def stopped_and_other(tmp_path: Path, private_home: Path) -> tuple[Path, Path, Path]:
    """(stopped A, unstopped B with its own synced runtime, B's runtime): the session is rooted in B."""
    stopped = _repo(tmp_path / "a")
    other, runtime, _ = sync_layout(tmp_path, CLEAN_GUARD)
    _stop(stopped, "--reason", "gap1d")
    return stopped, other, runtime


def _in_b(runtime: Path, other: Path, home: Path, tool_input: dict, tool: str = "Bash"):
    return _hook(runtime, other, _call(tool, tool_input, other), home, CLAUDE_PROJECT_DIR=str(other))


# --- 1. the stop can no longer be lifted from a session rooted in another repository ----------------------


@pytest.mark.parametrize(
    "command",
    [
        RESUME,
        "chock resume --repo {repo}",
        "chock resume --repo={repo}",
        "rm {repo}/.chock/stop.json",
        "rm -f '{repo}/.chock/stop.json'",
        "mv {repo}/.chock/stop.json /tmp/x",
        "truncate -s0 {repo}/.chock/stop.json",
        "echo ok;rm {repo}/.chock/stop.json",
        ": >{repo}/.chock/stop.json",
        "cd ../a && rm .chock/stop.json",
    ],
)
def test_a_command_naming_a_stopped_repo_is_refused_from_an_unstopped_session(
    stopped_and_other: tuple[Path, Path, Path], private_home: Path, command: str
) -> None:
    stopped, other, runtime = stopped_and_other
    refused = _in_b(runtime, other, private_home, {"command": command.format(repo=stopped)})
    assert _deny(refused), refused.stdout + refused.stderr
    assert (stopped / ".chock" / "stop.json").exists()
    assert halt_registry_entry(stopped).exists()


def test_a_command_naming_no_stopped_repo_is_allowed(
    stopped_and_other: tuple[Path, Path, Path], private_home: Path
) -> None:
    _, other, runtime = stopped_and_other
    assert not _deny(_in_b(runtime, other, private_home, {"command": "git status && ls -la src"}))


def _resume_cli(repo: Path, **io: object) -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, "-m", "chock", "resume", "--repo", str(repo)],
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        **io,
    )


def test_resume_without_a_terminal_is_refused_and_the_stop_stays(stopped_and_other: tuple[Path, Path, Path]) -> None:
    stopped = stopped_and_other[0]
    proc = _resume_cli(stopped, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    out, err = proc.communicate(stopped.name + "\n", timeout=60)
    assert proc.returncode == 1, out + err
    assert "own terminal" in err
    assert (stopped / ".chock" / "stop.json").exists()
    assert halt_registry_entry(stopped).exists()


def _resume_at_a_terminal(repo: Path, typed: str) -> tuple[int, str]:
    pty = pytest.importorskip("pty")
    main, child = pty.openpty()
    proc = _resume_cli(repo, stdin=child, stdout=child, stderr=child)
    os.close(child)
    seen, deadline = b"", time.monotonic() + 60
    while b"to resume" not in seen and time.monotonic() < deadline:
        seen += os.read(main, 4096)
    os.write(main, typed.encode("utf-8") + b"\n")
    code = proc.wait(timeout=60)
    try:
        while chunk := os.read(main, 4096):
            seen += chunk
    except OSError:
        pass  # the terminal closes when the child exits
    os.close(main)
    return code, seen.decode("utf-8", "replace")


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX pseudo-terminal")
def test_a_person_at_a_terminal_who_types_the_name_resumes(stopped_and_other: tuple[Path, Path, Path]) -> None:
    stopped = stopped_and_other[0]
    code, seen = _resume_at_a_terminal(stopped, stopped.name)
    assert code == 0, seen
    assert "Resumed" in seen
    assert not (stopped / ".chock" / "stop.json").exists()
    assert not halt_registry_entry(stopped).exists()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX pseudo-terminal")
def test_a_wrong_name_at_a_terminal_leaves_the_stop(stopped_and_other: tuple[Path, Path, Path]) -> None:
    stopped = stopped_and_other[0]
    code, seen = _resume_at_a_terminal(stopped, "not-" + stopped.name)
    assert code == 1, seen
    assert "does not match" in seen
    assert (stopped / ".chock" / "stop.json").exists()


def test_stop_needs_no_terminal(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "s")
    proc = subprocess.run(
        [sys.executable, "-m", "chock", "stop", "--repo", str(repo)],
        stdin=subprocess.PIPE,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert (repo / ".chock" / "stop.json").exists()


# --- 2. the payload scan: none with no stop anywhere, capped (refusing past the cap) with one ---------------


def _deep_payload(cwd: Path) -> dict:
    folders = "d/" * (DEEP_LEN // 2)
    paths = [(f"{i:04d}/" + folders)[:DEEP_LEN] for i in range(DEEP_COUNT)]
    return _call("Read", {"file_path": "x", "paths": paths}, cwd)


def test_a_deep_payload_is_refused_within_the_cap_while_a_stop_is_registered(
    stopped_and_other: tuple[Path, Path, Path], private_home: Path
) -> None:
    _, other, runtime = stopped_and_other
    started = time.monotonic()
    refused = _hook(runtime, other, _deep_payload(other), private_home, CLAUDE_PROJECT_DIR=str(other))
    elapsed = time.monotonic() - started
    assert _deny(refused), refused.stdout + refused.stderr
    assert "more paths than the stop check reads" in refused.stdout
    assert elapsed < CAP_SECONDS, elapsed


def test_no_stop_anywhere_skips_the_payload_scan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, private_home: Path
) -> None:
    repo = _repo(tmp_path / "free")
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))

    def scanned(_event: object) -> list:
        raise AssertionError("the payload was scanned with no stop anywhere")

    monkeypatch.setattr(repo_stop, "repo_stop_paths", scanned)
    event = SimpleNamespace(event="pre_tool", agent="claude_code", cwd=str(repo), path=None)
    event.raw, event.command = _deep_payload(repo), "rm -rf " + str(tmp_path)
    assert repo_stop.repo_stop_refusal(event) is None


def test_a_deep_payload_with_no_stop_anywhere_is_allowed(tmp_path: Path, private_home: Path) -> None:
    repo, runtime, _ = sync_layout(tmp_path, CLEAN_GUARD)
    proc = _hook(runtime, repo, _deep_payload(repo), private_home, CLAUDE_PROJECT_DIR=str(repo))
    assert not _deny(proc), proc.stdout + proc.stderr


# --- 3. case-insensitive filesystems: a resume typed in another case clears the registry entry ------------


def test_a_resume_in_another_case_clears_the_entry_on_a_caseless_platform(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("chock.gate.runner.halt.sys", SimpleNamespace(platform="darwin"))
    repo = _repo(tmp_path / "Repo")
    _stop(repo)
    entry = halt_registry_entry(repo)
    assert entry.exists()
    assert halt_registry_entry(tmp_path / "REPO") == entry
    assert person_resume(tmp_path / "REPO") == 0
    assert not entry.exists()


# --- the dispatcher's runner: a repository chock installed with no policy still tells a person from an agent --


def test_a_persons_commit_passes_in_a_repo_with_no_policy_while_stopped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("CHOCK_GATE_LOG", raising=False)
    root = tmp_path / "bare-policy"
    root.mkdir()
    for args in (("init", "-q"), ("config", "user.email", "person@example.invalid"), ("config", "user.name", "t")):
        _git(root, *args)
    install_policy_hooks(root, get_hooks_dir(root))
    assert (root / ".chock" / "bin" / "gate.py").is_file()
    _stop(root, "--reason", "no policy")
    assert _commit(root, PERSON).returncode == 0
    refused = _commit(root, AGENT)
    assert refused.returncode != 0
    assert "stopped: no policy" in refused.stderr


@pytest.mark.parametrize(
    "command",
    [
        r"rm C:\repo\.chock\stop.json",
        r"rm -f 'C:\repo\.chock\stop.json'",
        r'rm "C:\repo\.chock\stop.json"',
        r"rm C:\repo/.chock/stop.json",
    ],
)
def test_a_windows_path_word_names_its_repo_on_every_platform(command: str) -> None:
    paths = repo_stop.repo_stop_paths(SimpleNamespace(command=command, path=None, raw=None))
    assert "C:/repo/.chock/stop.json" in paths or "C:\\repo\\.chock\\stop.json" in paths
