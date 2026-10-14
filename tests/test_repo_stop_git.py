"""GAP-1 at the git hooks: an agent's commit or push is refused while stopped; a person's passes. GAP-7: who approved."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
import yaml

from chock import stop as chock_stop
from chock.compile.compiler import compile_policy
from chock.compile.surfaces import Surface
from chock.gate.runner import judge, script_verdict
from chock.hooks.installers import get_hooks_dir, install_dispatcher, install_policy_hooks
from chock.witness_export import bundle

#: `chock stop` writes its machine registry entry under this test's own home, never the real one.
pytestmark = pytest.mark.usefixtures("private_home")

POLICY_ID = "word-check"
AGENT = {"CHOCK_AGENT_COMMIT": "1"}
PERSON = {"CHOCK_AGENT_COMMIT": "0"}
#: Allows every commit: with it alone, only the dispatcher's own stop check can refuse one.
_SCRIPT = "raise SystemExit(0)\n"
_MANIFEST = {
    "id": POLICY_ID,
    "name": "Word Check",
    "version": "0.0.1",
    "description": "trigger: committing. avoid: nothing.",
    "artifact": "rule",
    "enforcement": "block",
    "rule": {"text": "never(commit): nothing\n"},
    "hook": {"script": {"on": ["commit"]}},
    "provenance": {"author": "t"},
    "lifecycle": {"status": "draft"},
}
GATE = {"kind": "content_regex", "on": ["commit", "push"], "action": "ask", "message": "no BAD", "params": {}}


def _git(repo: Path, *args: str, env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=repo, check=False, capture_output=True, text=True, env={**os.environ, **(env or {})}
    )


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.delenv("CHOCK_GATE_LOG")
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "person@example.invalid")
    _git(root, "config", "user.name", "t")
    policy = root / ".agents" / "policies" / POLICY_ID
    (policy / "implementations").mkdir(parents=True)
    (policy / "manifest.yaml").write_text(yaml.safe_dump(_MANIFEST), encoding="utf-8")
    (policy / "implementations" / f"{POLICY_ID}-pre-commit.py").write_text(_SCRIPT, encoding="utf-8")
    compile_policy(policy, targets=[Surface.GIT_HOOK.value], output_root=root / ".chock" / "compiled")
    install_policy_hooks(root, get_hooks_dir(root))
    monkeypatch.chdir(root)
    return root


def _commit(repo: Path, env: dict) -> subprocess.CompletedProcess:
    a = repo / "a.txt"
    a.write_text((a.read_text(encoding="utf-8") if a.exists() else "") + "x\n", encoding="utf-8")
    _git(repo, "add", "a.txt")
    return _git(repo, "commit", "-qm", "c", env=env)


def _log(repo: Path) -> list[dict]:
    path = repo / ".chock" / "log" / "gate-events.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


def test_an_agents_commit_is_refused_while_stopped_and_a_persons_passes(repo: Path) -> None:
    assert _commit(repo, AGENT).returncode == 0
    chock_stop.stop_main(["--repo", str(repo), "--reason", "audit"])

    refused = _commit(repo, AGENT)
    assert refused.returncode != 0
    assert "stopped: audit" in refused.stderr
    [record] = [r for r in _log(repo) if r.get("reason") == "stopped"]
    assert (record["verdict"], record["event"], record["actor"]) == ("block", "agent-commit", "agent:unknown")

    assert _commit(repo, PERSON).returncode == 0
    chock_stop.resume_main(["--repo", str(repo)])
    assert _commit(repo, AGENT).returncode == 0


def test_a_corrupt_stop_refuses_an_agents_commit(repo: Path) -> None:
    (repo / ".chock" / "stop.json").write_text("{", encoding="utf-8")
    assert "cannot be read" in _commit(repo, AGENT).stderr
    assert _commit(repo, PERSON).returncode == 0


def test_a_stop_on_another_client_lets_this_agent_commit(repo: Path) -> None:
    chock_stop.stop_main(["--repo", str(repo), "--agent", "codex_cli"])
    assert _commit(repo, {"CLAUDECODE": "1"}).returncode == 0
    assert _commit(repo, {"AI_AGENT": "codex_0.9_agent"}).returncode != 0


def test_an_agents_push_is_refused_at_the_dispatcher(repo: Path) -> None:
    hook = install_dispatcher(get_hooks_dir(repo), "pre-push").parent / "pre-push"
    chock_stop.stop_main(["--repo", str(repo)])
    done = subprocess.run(
        ["sh", str(hook), "origin", "url"], cwd=repo, input="", capture_output=True, text=True, check=False,
        env={**os.environ, **AGENT},
    )  # fmt: skip
    assert done.returncode != 0
    assert "stopped: no reason given" in done.stderr


def _gate(repo: Path) -> Path:
    gate = repo / ".chock" / "compiled" / "ask-bad" / "git-hook" / "gate.json"
    gate.parent.mkdir(parents=True)
    gate.write_text(json.dumps({**GATE, "params": {"content_pattern": "BAD"}}), encoding="utf-8")
    (repo / "b.txt").write_text("BAD\n", encoding="utf-8")
    _git(repo, "add", "b.txt")
    return gate


@pytest.mark.parametrize("env", [{"CHOCK_ALLOW": "ask-bad"}, {"CHOCK_ROLLOUT": "observe"}], ids=["allow", "observe"])
def test_neither_chock_allow_nor_the_rollout_level_loosens_a_stop(
    repo: Path, monkeypatch: pytest.MonkeyPatch, env: dict
) -> None:
    gate = _gate(repo)
    (repo / ".chock" / "config.yaml").write_text("rollout: observe\n", encoding="utf-8")
    chock_stop.stop_main(["--repo", str(repo)])
    for name, value in {**env, **AGENT}.items():
        monkeypatch.setenv(name, value)
    assert judge(gate, "pre-commit", "", repo) == (1, "block")
    assert script_verdict(POLICY_ID, "pre-commit", 4, repo) == 1


def test_an_override_names_its_approver_and_policy(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    gate = _gate(repo)
    monkeypatch.setenv("CHOCK_ALLOW", f"ask-bad,{POLICY_ID}")
    assert judge(gate, "pre-commit", "", repo) == (0, "allow")
    assert script_verdict(POLICY_ID, "pre-commit", 3, repo) == 0
    overrides = [r for r in _log(repo) if r.get("override")]
    assert [(r["policy_id"], r["approver"]) for r in overrides] == [
        ("ask-bad", "person@example.invalid"),
        (POLICY_ID, "person@example.invalid"),
    ]
    assert (repo / ".chock" / "log" / "gate-events.jsonl").stat().st_mode & 0o077 == 0 or os.name == "nt"
    exported = json.dumps(bundle("claude_code", overrides, repo, None))
    assert "person@example.invalid" not in exported


def test_resyncing_an_unedited_older_dispatcher_keeps_no_backup(tmp_path: Path) -> None:
    hooks = tmp_path / "hooks"
    hooks.mkdir()
    old = Path(chock_stop.__file__).parent / "hooks" / "data" / "dispatcher_before_stop.sh"
    install_dispatcher(hooks, "pre-push")
    marker = (hooks / "pre-push").read_text(encoding="utf-8").splitlines()[1]
    text = old.read_text(encoding="utf-8").replace("__EVENT__", "pre-push").replace("__MARKER__", marker)
    (hooks / "pre-push").write_text(text, encoding="utf-8")
    install_dispatcher(hooks, "pre-push")
    assert not list(hooks.glob("pre-push.chock-backup*"))
