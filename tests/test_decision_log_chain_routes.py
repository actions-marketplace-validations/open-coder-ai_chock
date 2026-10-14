"""GAP-4: every route chains its lines; concurrent writers never fork; a chaining failure changes no verdict."""

from __future__ import annotations

import json
import os
import runpy
import subprocess
import sys
import time
from pathlib import Path

import pytest
from decision_log_support import BLOCKING_GUARD, hook_env, records, run_hook, sync_layout, sync_log

from chock.cli import main as cli_main
from chock.gate import assemble, runtime_bundle
from chock.gate.runner import chain, journal
from chock.gatelog_chain import chains, verify
from chock.guardrails import chock_bundle_log, plugin


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    folder = tmp_path / "home"
    folder.mkdir()
    monkeypatch.setenv("HOME", str(folder))
    monkeypatch.setenv("USERPROFILE", str(folder))
    return folder


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    folder = tmp_path / "repo"
    (folder / ".git").mkdir(parents=True)
    return folder


def _fill(path: Path, count: int) -> None:
    for i in range(count):
        journal.log_append(path, {"policy_id": "p", "verdict": "block", "i": i})


def test_the_git_hook_runner_and_an_agent_runtime_both_chain(tmp_path: Path, home: Path) -> None:
    gate = runpy.run_path(str(_source(tmp_path / "gate.py", assemble.runner_source())), run_name="gate")
    hook = runpy.run_path(str(_source(tmp_path / "rt.py", runtime_bundle.render("claude_code"))), run_name="rt")
    log = tmp_path / "events.jsonl"
    for append in (gate["log_append"], hook["log_append"], gate["log_append"]):
        append(log, {"policy_id": "p", "verdict": "block"})

    walked = verify("events", [log])
    assert (walked.breaks, walked.records, walked.start) == (None, 3, "genesis")


def _source(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


WRITER = """
import sys
from chock.gate.runner.journal import log_append
for i in range(int(sys.argv[2])):
    log_append(sys.argv[1], {"policy_id": "p", "writer": sys.argv[3], "i": i}, int(sys.argv[4]))
"""
WRITERS, PER_WRITER = 8, 200


@pytest.mark.parametrize(
    "max_bytes", [journal.LOG_DEFAULT_MAX_BYTES, journal.LOG_MIN_MAX_BYTES], ids=["one", "rotating"]
)
def test_eight_concurrent_writers_never_fork_the_chain(tmp_path: Path, max_bytes: int) -> None:
    log = tmp_path / "events.jsonl"
    started = time.monotonic()
    args = (str(log), str(PER_WRITER))
    writers = [subprocess.Popen([sys.executable, "-c", WRITER, *args, str(n), str(max_bytes)]) for n in range(WRITERS)]
    assert [w.wait(timeout=300) for w in writers] == [0] * WRITERS
    elapsed = time.monotonic() - started

    walked = verify("events", [f for f in (chain.log_rotated(log), log) if f.exists()])
    kept = [json.loads(line) for f in walked.files for line in f.read_bytes().splitlines()]
    seqs = [r["seq"] for r in kept]
    sys.stdout.write(f"\n{WRITERS}x{PER_WRITER} writers, max_bytes={max_bytes}: {elapsed:.2f}s, {len(kept)} kept\n")
    assert walked.breaks is None
    assert not [r for r in kept if "unchained" in r]
    assert seqs == list(range(seqs[0], WRITERS * PER_WRITER)), "one line per seq: no fork, no gap"
    if max_bytes == journal.LOG_DEFAULT_MAX_BYTES:
        assert len(kept) == WRITERS * PER_WRITER


def test_a_chain_that_cannot_be_read_still_writes_the_line(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    log = tmp_path / "events.jsonl"
    _fill(log, 1)

    def unreadable(path: object) -> None:
        raise PermissionError(path)

    monkeypatch.setattr(journal, "log_tail", unreadable)
    journal.log_append(log, {"policy_id": "p", "verdict": "block"})

    last = json.loads(log.read_bytes().splitlines()[-1])
    assert (last["verdict"], last["unchained"]) == ("block", "unreadable")
    assert "prev" not in last


def _hold_lock(log: Path) -> int:
    import fcntl

    log.parent.mkdir(parents=True, exist_ok=True)
    holder = os.open(str(log) + ".lock", os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(holder, fcntl.LOCK_EX)
    return holder


def _make_lock_a_folder(log: Path) -> int:
    lock = Path(str(log) + ".lock")
    lock.unlink(missing_ok=True)
    lock.mkdir(parents=True)
    return -1


@pytest.mark.skipif(os.name == "nt", reason="fcntl lock and POSIX folders")
@pytest.mark.parametrize("break_it", [_hold_lock, _make_lock_a_folder], ids=["lock-held", "lock-unopenable"])
def test_a_chaining_failure_never_changes_the_verdict(tmp_path: Path, home: Path, break_it) -> None:
    repo, runtime, guard = sync_layout(tmp_path, BLOCKING_GUARD)
    healthy = run_hook(repo, runtime, guard, "rm -rf build", hook_env(home))
    assert '"deny"' in healthy.stdout
    sync_log(repo).unlink()

    holder = break_it(sync_log(repo))
    try:
        broken = run_hook(repo, runtime, guard, "rm -rf build", hook_env(home))
    finally:
        if holder >= 0:
            os.close(holder)

    assert (broken.returncode, broken.stdout) == (healthy.returncode, healthy.stdout)
    assert "Traceback" not in broken.stderr
    if break_it is _hold_lock:
        assert [r.get("unchained") for r in records(sync_log(repo))] == ["lock"]


def test_the_export_carries_the_head_and_overrides_without_the_approver(tmp_path: Path, repo: Path, home: Path) -> None:
    agent_log = home / ".chock" / "log" / "goose" / "events.jsonl"
    journal.log_append(agent_log, {"route": "plugin", "agent": "goose", "policy_id": "p", "verdict": "block"})
    override = {"route": "sync", "policy_id": "ask-bad", "verdict": "allow", "actor": "person"}
    journal.log_append(
        sync_log(repo),
        {**override, "override": "CHOCK_ALLOW", "approver": "person@example.invalid"},
    )
    journal.log_append(
        sync_log(repo),
        {"route": "sync", "agent": "grok", "policy_id": "p", "verdict": "block"},
    )
    out = tmp_path / "bundle.json"

    assert cli_main(["witness", "export", "--client", "goose", "--out", str(out), "--repo", str(repo)]) == 0

    text = out.read_text(encoding="utf-8")
    assert "person@example.invalid" not in text
    doc = json.loads(text)
    found = sorted((r["policy_id"], r.get("agent"), r.get("override")) for r in doc["records"])
    assert found == [("ask-bad", None, "CHOCK_ALLOW"), ("p", "goose", None)]
    heads = {h["log"]: h for h in doc["chain"]}
    assert set(heads) == {".chock/log/gate-events.jsonl", "~/.chock/log/goose/events.jsonl"}
    for label, files in chains(repo, home=home, agents=["goose"]):
        assert {k: heads[label][k] for k in ("seq", "sha256")} == verify(label, files).head
        assert heads[label]["intact"] is True


def test_a_merged_plugins_vendored_journal_chains_without_chock(tmp_path: Path, home: Path) -> None:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "chock_journal.py").write_text(plugin.wrapper_journal(), encoding="utf-8")
    (scripts / "chock_chain.py").write_text(Path(chain.__file__).read_text(encoding="utf-8"), encoding="utf-8")
    (scripts / "chock_bundle_log.py").write_text(Path(chock_bundle_log.__file__).read_text(encoding="utf-8"))
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    code = f"import sys; sys.path.insert(0, {str(scripts)!r}); import chock_bundle_log as b, pathlib\n"
    code += f"for _ in range(2): b.log_off(pathlib.Path({str(repo / 'guardrails.json')!r}), 'bundle', 'member')"
    subprocess.run([sys.executable, "-S", "-c", code], check=True, cwd=repo, timeout=60, env=hook_env(home))

    walked = verify("toggle", [repo / "log" / "gate-events.jsonl"])
    assert (walked.breaks, walked.records, walked.start) == (None, 2, "genesis")
