"""GAP-1 second review of 551efc4: six more ways past a stop, each closed."""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import init_repo
from decision_log_support import CLEAN_GUARD, hook_env, plugin_layout, sync_layout
from stop_person_support import person_resume
from test_repo_stop_git import AGENT, PERSON, _commit, _git
from test_repo_stop_git import repo as git_repo  # noqa: F401 -- the fixture, under the name the tests use

from chock import stop as chock_stop
from chock.gate.runner.halt import halt_registry_dir, halt_registry_entry
from chock.hooks.installers import get_hooks_dir, install_policy_hooks

#: `chock stop` writes its machine registry entry under this test's own home, never the real one.
pytestmark = pytest.mark.usefixtures("private_home")

RESUME_A = "env -u CLAUDECODE -u AI_AGENT chock resume --repo {repo}"


def _deny(proc: subprocess.CompletedProcess) -> bool:
    return '"permissionDecision": "deny"' in proc.stdout


def _hook(runtime: Path, cwd: Path, payload: object, home: Path, **env: str) -> subprocess.CompletedProcess:
    text = payload if isinstance(payload, str) else json.dumps(payload)
    return subprocess.run(
        [sys.executable, str(runtime), "--stop-check"],
        input=text,
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=cwd,
        env={**hook_env(home), **env},
        timeout=60,
        check=False,
    )


def _call(tool: str, tool_input: dict, cwd: Path) -> dict:
    return {"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": tool_input, "cwd": str(cwd)}


def _stop(repo: Path, *args: str) -> None:
    assert chock_stop.stop_main(["--repo", str(repo), *args]) == 0


def _repo(path: Path) -> Path:
    path.mkdir(parents=True)
    return init_repo(path)


# --- 1. the sync route: a session rooted in A sees A's stop whichever repository's runtime runs ------------


@pytest.fixture
def two_repos(tmp_path: Path, private_home: Path) -> tuple[Path, Path, Path, Path]:
    """(stopped A, unstopped B with its own synced runtime, B's runtime, a folder outside both)."""
    stopped = _repo(tmp_path / "a")
    other, runtime, _ = sync_layout(tmp_path, CLEAN_GUARD)
    outside = tmp_path / "out"
    outside.mkdir()
    _stop(stopped, "--reason", "sync")
    return stopped, other, runtime, outside


def test_a_session_rooted_in_a_stopped_repo_is_refused_from_another_repos_runtime(
    two_repos: tuple[Path, Path, Path, Path], private_home: Path
) -> None:
    """The client ran A's relative hook command from B's top level, so git started B's runtime."""
    stopped, other, runtime, outside = two_repos
    call = _call("Bash", {"command": RESUME_A.format(repo=stopped)}, outside)
    assert _deny(_hook(runtime, other, call, private_home, CLAUDE_PROJECT_DIR=str(stopped)))


def test_a_session_rooted_in_an_unstopped_repo_is_allowed(
    two_repos: tuple[Path, Path, Path, Path], private_home: Path
) -> None:
    _, other, runtime, outside = two_repos
    call = _call("Bash", {"command": "ls"}, outside)
    assert not _deny(_hook(runtime, other, call, private_home, CLAUDE_PROJECT_DIR=str(other)))


def test_a_session_no_client_places_is_refused_while_any_stop_is_in_force(
    two_repos: tuple[Path, Path, Path, Path], private_home: Path
) -> None:
    stopped, other, runtime, outside = two_repos
    call = _call("Bash", {"command": RESUME_A.format(repo=stopped)}, outside)
    assert _deny(_hook(runtime, other, call, private_home))
    assert person_resume(stopped) == 0
    assert not _deny(_hook(runtime, other, call, private_home))


# --- 2. the plugin route: the machine registry ---------------------------------------------------------------


@pytest.fixture
def plugin(tmp_path: Path, private_home: Path) -> tuple[Path, Path, Path]:
    """(stopped repository A, plugin runtime outside any repository, a folder outside every repository)."""
    repo, runtime, _ = plugin_layout(tmp_path, CLEAN_GUARD)
    outside = tmp_path / "out"
    outside.mkdir()
    _stop(repo, "--reason", "plugin")
    return repo, runtime, outside


def test_stop_writes_a_private_registry_entry_and_resume_removes_it(plugin: tuple[Path, Path, Path]) -> None:
    repo, _, _ = plugin
    entry = halt_registry_entry(repo)
    assert entry.parent == halt_registry_dir()
    assert json.loads(entry.read_text(encoding="utf-8"))["repo"] == os.path.realpath(repo)
    if os.name == "posix":
        assert stat.S_IMODE(entry.stat().st_mode) == 0o600
    assert person_resume(repo) == 0
    assert not entry.exists()


@pytest.mark.parametrize(
    "payload",
    [_call("mcp__db__query", {}, Path("/")), "not json {"],
    ids=["mcp-call-with-no-path", "non-json-payload"],
)
def test_a_plugin_call_naming_no_stopped_path_is_refused_from_outside(
    plugin: tuple[Path, Path, Path], private_home: Path, payload: object
) -> None:
    _, runtime, outside = plugin
    if isinstance(payload, dict):
        payload = {**payload, "cwd": str(outside)}
    refused = _hook(runtime, outside, payload, private_home)
    assert _deny(refused) or refused.returncode == 2, (refused.returncode, refused.stdout, refused.stderr)


def test_a_stop_file_removed_by_hand_still_refuses_until_resume(
    plugin: tuple[Path, Path, Path], private_home: Path
) -> None:
    repo, runtime, outside = plugin
    (repo / ".chock" / "stop.json").unlink()
    call = _call("mcp__db__query", {}, outside)
    assert _deny(_hook(runtime, outside, call, private_home))
    assert person_resume(repo) == 0
    assert not _deny(_hook(runtime, outside, call, private_home))


@pytest.mark.parametrize("damage", ["entry", "folder"])
def test_an_unreadable_registry_refuses(tmp_path: Path, private_home: Path, damage: str) -> None:
    _, runtime, _ = plugin_layout(tmp_path, CLEAN_GUARD)
    outside = tmp_path / "out"
    outside.mkdir()
    folder = halt_registry_dir()
    folder.parent.mkdir(parents=True, exist_ok=True)
    if damage == "entry":
        folder.mkdir()
        (folder / f"{'0' * 64}.json").write_text("{", encoding="utf-8")
    else:
        folder.write_text("not a folder", encoding="utf-8")
    assert _deny(_hook(runtime, outside, _call("mcp__db__query", {}, outside), private_home))


# --- 3. git: the stop roots as the dispatcher finds them, and only the main checkout's gate.py ---------------


def test_a_commit_through_a_copied_work_tree_into_a_stopped_repo_is_refused(
    git_repo: Path,  # noqa: F811
    tmp_path: Path,
) -> None:
    assert _commit(git_repo, PERSON).returncode == 0
    copy = tmp_path / "copy"
    shutil.copytree(git_repo, copy, ignore=shutil.ignore_patterns(".git"))
    _stop(git_repo, "--reason", "copied")
    env = {**AGENT, "GIT_DIR": str(git_repo / ".git"), "GIT_WORK_TREE": str(copy)}
    (copy / "a.txt").write_text("changed\n", encoding="utf-8")
    assert _git(copy, "add", "a.txt", env=env).returncode == 0
    refused = _git(copy, "commit", "-qm", "c", env=env)
    assert refused.returncode != 0
    assert "stopped: copied" in refused.stderr


def test_chock_agent_commit_zero_does_not_clear_an_agents_commit(git_repo: Path) -> None:  # noqa: F811
    _stop(git_repo, "--reason", "forged")
    refused = _commit(git_repo, {"CLAUDECODE": "1", "CHOCK_AGENT_COMMIT": "0"})
    assert refused.returncode != 0
    assert "stopped: forged" in refused.stderr
    assert _commit(git_repo, PERSON).returncode == 0


# --- 4. paths: symlinks resolved, and every string in the tool input --------------------------------------


@pytest.fixture
def placed(plugin: tuple[Path, Path, Path], tmp_path: Path) -> tuple[Path, Path, Path, dict[str, str]]:
    """(stopped A, runtime, outside, env): the session rooted in an unstopped repository, so only paths count."""
    repo, runtime, outside = plugin
    (repo / "src").mkdir()
    (repo / "notes.txt").write_text("x\n", encoding="utf-8")
    elsewhere = _repo(tmp_path / "elsewhere")
    return repo, runtime, outside, {"CLAUDE_PROJECT_DIR": str(elsewhere)}


@pytest.mark.skipif(os.name != "posix", reason="symlinks need privileges on Windows")
@pytest.mark.parametrize("target", ["src", "notes.txt"], ids=["into-a-subfolder", "a-symlinked-file"])
def test_a_symlink_into_a_stopped_repo_is_refused(
    placed: tuple[Path, Path, Path, dict[str, str]], private_home: Path, target: str
) -> None:
    repo, runtime, outside, env = placed
    link = outside / "link"
    link.symlink_to(repo / target)
    path = link / "x.py" if target == "src" else link
    assert _deny(_hook(runtime, outside, _call("Write", {"file_path": str(path)}, outside), private_home, **env))


def _inputs(repo: Path) -> list[tuple[str, dict]]:
    src, notes = str(repo / "src"), str(repo / "notes.txt")
    uri = "file://" + (repo / "with space.txt").as_posix().replace(" ", "%20")
    return [
        ("cwd", {"command": "ls", "cwd": src}),
        ("directory", {"directory": src}),
        ("edits", {"edits": [{"file_path": notes, "old_string": "x", "new_string": "y"}]}),
        ("file_paths", {"file_paths": ["/nowhere", notes]}),
        ("dir_path", {"dir_path": src}),
        ("absolute_path", {"absolute_path": notes}),
        ("uri", {"uri": uri}),
    ]


@pytest.mark.parametrize("index", range(7), ids=[name for name, _ in _inputs(Path("/r"))])
def test_every_path_in_the_tool_input_is_checked(
    placed: tuple[Path, Path, Path, dict[str, str]], private_home: Path, index: int
) -> None:
    repo, runtime, outside, env = placed
    _, tool_input = _inputs(repo)[index]
    assert _deny(_hook(runtime, outside, _call("mcp__fs__op", tool_input, outside), private_home, **env))


def test_paths_outside_every_stopped_repo_are_allowed(
    placed: tuple[Path, Path, Path, dict[str, str]], private_home: Path
) -> None:
    _, runtime, outside, env = placed
    tool_input = {"edits": [{"file_path": str(outside / "x")}], "uri": "file:///nowhere/y"}
    assert not _deny(_hook(runtime, outside, _call("mcp__fs__op", tool_input, outside), private_home, **env))


# --- 5. a bare repository's worktrees ---------------------------------------------------------------------


@pytest.fixture
def bare_worktree(tmp_path: Path, private_home: Path) -> tuple[Path, Path]:
    """(bare repository, a linked worktree of it with chock's git hooks installed)."""
    seed = _repo(tmp_path / "seed")
    (seed / "a.txt").write_text("x\n", encoding="utf-8")
    _git(seed, "add", "a.txt")
    assert _git(seed, "commit", "-qm", "seed", env=PERSON).returncode == 0
    bare = tmp_path / "bare.git"
    assert _git(tmp_path, "clone", "-q", "--bare", str(seed), str(bare)).returncode == 0
    worktree = tmp_path / "wt"
    assert _git(bare, "worktree", "add", "-q", str(worktree)).returncode == 0
    for key, value in (("user.email", "t@example.com"), ("user.name", "t")):
        _git(worktree, "config", key, value)
    install_policy_hooks(worktree, get_hooks_dir(worktree))
    return bare, worktree


def test_a_stop_on_a_bare_repo_reaches_its_worktrees_tool_calls(
    bare_worktree: tuple[Path, Path], tmp_path: Path, private_home: Path
) -> None:
    bare, worktree = bare_worktree
    (tmp_path / "p").mkdir()
    _, runtime, _ = plugin_layout(tmp_path / "p", CLEAN_GUARD)
    _stop(bare, "--reason", "bare")
    call = _call("Read", {"file_path": "a.txt"}, worktree)
    assert _deny(_hook(runtime, worktree, call, private_home, CLAUDE_PROJECT_DIR=str(worktree)))


def test_a_stop_on_a_bare_repo_reaches_its_worktrees_commits(bare_worktree: tuple[Path, Path]) -> None:
    bare, worktree = bare_worktree
    _stop(bare, "--reason", "bare")
    assert _commit(worktree, AGENT).returncode != 0
