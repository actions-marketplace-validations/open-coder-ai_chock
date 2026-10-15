"""RT-SPLIT end to end on the sync route: `sync`, then Claude Code's own hook commands as it runs them."""

from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path

import pytest
from conftest import baseline_policy, init_repo, run_hook_command
from stop_person_support import person_resume

from chock import stop as chock_stop
from chock.gate import runtime_bundle
from chock.scaffold.recompile import recompile

POLICIES = ("block-destructive-commands", "block-no-verify")


@pytest.fixture
def synced(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, dict[str, str]]:
    """A repository `sync` wired for Claude Code, and a private HOME: `chock stop` mirrors into `~/.chock/stops`,
    which refuses every plugin hook on the machine, so a shared HOME would stop other tests' hooks too."""
    (tmp_path / "repo").mkdir()
    repo = init_repo(tmp_path / "repo")
    for policy in POLICIES:
        shutil.copytree(baseline_policy(policy), repo / ".agents" / "policies" / policy)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    recompile(repo, ["claude"], skip_hooks=False)
    return repo, {**os.environ, "HOME": str(home), "USERPROFILE": str(home), "CLAUDE_PROJECT_DIR": str(repo)}


def _hooks(repo: Path, tool: str) -> list[str]:
    """The PreToolUse commands Claude Code runs for `tool`, read from the settings `sync` wrote."""
    groups = json.loads((repo / ".claude" / "settings.json").read_text(encoding="utf-8"))["hooks"]["PreToolUse"]
    return [h["command"] for g in groups if re.fullmatch(g.get("matcher") or ".*", tool) for h in g["hooks"]]


def _run(repo: Path, env: dict[str, str], tool: str, tool_input: dict) -> list:
    payload = {"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": tool_input, "cwd": str(repo)}
    payload.update(session_id="e2e", tool_use_id="call-1")
    return [run_hook_command(c, repo, json.dumps(payload), env=env) for c in _hooks(repo, tool)]


def _denied(proc) -> bool:
    return proc.returncode == 2 or '"permissionDecision": "deny"' in proc.stdout


def test_sync_writes_the_shared_runtime_beside_its_entry(synced) -> None:
    repo, _env = synced
    bin_dir = repo / ".chock" / "bin"
    assert (bin_dir / runtime_bundle.SHARED_FILE).read_text(encoding="utf-8") == runtime_bundle.render_shared()
    assert (bin_dir / "claude_code.py").read_text(encoding="utf-8") == runtime_bundle.render("claude_code")


def test_a_read_passes_a_policy_blocks_a_stop_refuses_and_a_missing_shared_runtime_refuses(synced) -> None:
    repo, env = synced
    read = ("Read", {"file_path": str(repo / "README.md")})
    allowed = _run(repo, env, *read)
    assert allowed and not any(_denied(p) or p.returncode for p in allowed), [(p.returncode, p.stderr) for p in allowed]

    blocked = _run(repo, env, "Bash", {"command": "git commit --no-verify -m x"})
    assert any(_denied(p) and "block-no-verify" in p.stdout for p in blocked), [p.stdout for p in blocked]

    assert chock_stop.stop_main(["--repo", str(repo), "--reason", "rt-split e2e"]) == 0
    stopped = _run(repo, env, *read)
    assert any(_denied(p) and "rt-split e2e" in p.stdout for p in stopped), [p.stdout for p in stopped]
    assert person_resume(repo) == 0
    assert not any(_denied(p) for p in _run(repo, env, *read))

    (repo / ".chock" / "bin" / runtime_bundle.SHARED_FILE).unlink()
    gone = _run(repo, env, *read)
    assert gone and all(_denied(p) for p in gone), [(p.returncode, p.stdout) for p in gone]
    assert all(runtime_bundle.SHARED_FILE in p.stderr for p in gone)
