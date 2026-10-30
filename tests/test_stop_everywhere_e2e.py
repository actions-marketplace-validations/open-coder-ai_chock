"""STOP-EVERYWHERE end to end: stop in repo A, and a Read in repo B is refused by B's synced hooks and a plugin's."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

from conftest import baseline_policy, init_repo, run_hook_command
from stop_person_support import person_resume_everywhere
from test_plugin_stop_check import _installed, _read
from test_shared_runtime_e2e import _hooks

from chock import stop as chock_stop
from chock.gate.runner.halt import halt_everywhere_entry
from chock.scaffold.recompile import recompile

REASON = "e2e machine incident"


def _repo(path: Path) -> Path:
    path.mkdir(parents=True)
    return init_repo(path)


def _synced(path: Path) -> Path:
    repo = _repo(path)
    for policy in ("block-destructive-commands", "block-no-verify"):
        shutil.copytree(baseline_policy(policy), repo / ".agents" / "policies" / policy)
    recompile(repo, ["claude"], skip_hooks=False)
    return repo


def _sync_read(repo: Path, home: Path) -> list:
    env = {**os.environ, "HOME": str(home), "USERPROFILE": str(home), "CLAUDE_PROJECT_DIR": str(repo)}
    payload = {"hook_event_name": "PreToolUse", "tool_name": "Read", "cwd": str(repo), "session_id": "e2e"}
    payload.update(tool_input={"file_path": str(repo / "README.md")}, tool_use_id="call-1")
    return [run_hook_command(c, repo, json.dumps(payload), env=env) for c in _hooks(repo, "Read")]


def _denied(proc) -> bool:
    return proc.returncode == 2 or '"permissionDecision": "deny"' in proc.stdout


def test_stop_everywhere_in_a_refuses_a_read_in_b_on_the_sync_and_plugin_routes(
    tmp_path: Path, private_home: Path
) -> None:
    stopped = _repo(tmp_path / "a")
    other = _synced(tmp_path / "b")
    pkg_repo, plugin, stop_check = _installed(tmp_path / "pkg", "claude", "package")
    assert not any(_denied(p) for p in _sync_read(other, private_home))
    assert "deny" not in _read(pkg_repo, plugin, private_home, stop_check).stdout

    assert chock_stop.stop_main(["--repo", str(stopped), "--everywhere", "--reason", REASON]) == 0
    synced = _sync_read(other, private_home)
    assert synced and all(_denied(p) for p in synced), [(p.returncode, p.stdout) for p in synced]
    assert all(f"stopped: {REASON}" in p.stdout for p in synced)
    plugged = _read(pkg_repo, plugin, private_home, stop_check)
    assert "deny" in plugged.stdout, (plugged.stdout, plugged.stderr)
    assert "chock resume --everywhere" in plugged.stdout

    assert chock_stop.resume_main(["--repo", str(stopped), "--everywhere"]) == 1  # no TTY: refused
    assert halt_everywhere_entry().is_file()
    assert all(_denied(p) for p in _sync_read(other, private_home))

    assert person_resume_everywhere(repo=stopped) == 0
    assert not any(_denied(p) for p in _sync_read(other, private_home))
    assert "deny" not in _read(pkg_repo, plugin, private_home, stop_check).stdout
