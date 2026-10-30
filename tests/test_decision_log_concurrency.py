"""LOG-1: many plugins' hooks append to one client file at once; lines never interleave and rotation never blocks."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import types
from pathlib import Path

import pytest
from decision_log_support import (
    BLOCKING_GUARD,
    POLICY,
    hook_env,
    plugin_layout,
    plugin_log,
    records,
    run_hook,
)

from chock.gate.runner import journal

WRITER = """
import sys
from chock.gate.runner.journal import log_append
for i in range(int(sys.argv[2])):
    log_append(sys.argv[1], {"policy_id": "p", "writer": sys.argv[3], "i": i, "pad": "x" * 60}, 200_000)
"""
PER_WRITER = 500


def test_two_writers_appending_500_records_each_leave_1000_intact_lines(tmp_path: Path) -> None:
    log = tmp_path / "events.jsonl"
    writers = [subprocess.Popen([sys.executable, "-c", WRITER, str(log), str(PER_WRITER), name]) for name in ("a", "b")]
    assert [w.wait(timeout=120) for w in writers] == [0, 0]

    lines = [
        line
        for path in (log.with_name("events.1.jsonl"), log)
        if path.exists()
        for line in path.read_text(encoding="utf-8").splitlines()
    ]
    parsed = [json.loads(line) for line in lines]  # a torn or interleaved line fails here
    assert len(parsed) == 2 * PER_WRITER
    for name in ("a", "b"):
        assert sorted(r["i"] for r in parsed if r["writer"] == name) == list(range(PER_WRITER))


class _Msvcrt(types.ModuleType):
    """A stand-in for Windows' msvcrt: `held` says whether another process holds the lock."""

    LK_NBLCK, LK_UNLCK = 2, 0

    def __init__(self, *, held: bool) -> None:
        super().__init__("msvcrt")
        self.held, self.calls = held, []

    def locking(self, fd: int, mode: int, nbytes: int) -> None:
        self.calls.append(mode)
        if mode == self.LK_NBLCK and self.held:
            raise OSError("locked by another process")


@pytest.mark.parametrize("held", [False, True], ids=["free", "busy"])
def test_the_windows_lock_rotates_when_free_and_skips_rotation_when_busy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, held: bool
) -> None:
    fake = _Msvcrt(held=held)
    monkeypatch.setitem(sys.modules, "msvcrt", fake)
    monkeypatch.setattr(journal, "log_windows", lambda: True)
    log = tmp_path / "events.jsonl"
    log.write_text("x" * journal.LOG_MIN_MAX_BYTES + "\n", encoding="utf-8")

    journal.log_append(log, {"policy_id": "p", "verdict": "block"}, journal.LOG_MIN_MAX_BYTES)

    rotated = log.with_name("events.1.jsonl")
    assert rotated.exists() is not held
    last = json.loads(log.read_text(encoding="utf-8").splitlines()[-1])
    assert last["verdict"] == "block", "the line is never lost"
    assert last.get("unchained") == ("lock" if held else None)
    assert fake.calls[-1] == (fake.LK_NBLCK if held else fake.LK_UNLCK)
    assert set(fake.calls) == ({fake.LK_NBLCK} if held else {fake.LK_NBLCK, fake.LK_UNLCK})


@pytest.mark.skipif(os.name == "nt", reason="fcntl is the lock everywhere but Windows")
def test_a_busy_posix_lock_skips_rotation_and_keeps_the_line(tmp_path: Path) -> None:
    import fcntl

    log = tmp_path / "events.jsonl"
    log.write_text("x" * journal.LOG_MIN_MAX_BYTES + "\n", encoding="utf-8")
    holder = os.open(str(log) + ".lock", os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(holder, fcntl.LOCK_EX)
    try:
        code = (
            f"from chock.gate.runner.journal import log_append; log_append({str(log)!r}, {{'policy_id': 'p'}}, 65536)"
        )
        subprocess.run([sys.executable, "-c", code], check=True, timeout=60)
    finally:
        os.close(holder)

    assert not log.with_name("events.1.jsonl").exists()
    assert json.loads(log.read_text(encoding="utf-8").splitlines()[-1])["policy_id"] == "p"


def test_two_plugins_in_one_client_share_its_file_and_each_line_names_its_plugin(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    first = tmp_path / "one"
    second = tmp_path / "two"
    first.mkdir()
    second.mkdir()
    for base, name in ((first, POLICY), (second, "other-pack")):
        repo, runtime, guard = plugin_layout(base, BLOCKING_GUARD)
        manifest = runtime.parent.parent / ".claude-plugin" / "plugin.json"
        manifest.write_text(json.dumps({"name": name, "version": "9.9.9"}), encoding="utf-8")
        run_hook(repo, runtime, guard, "rm -rf build", hook_env(home))

    assert sorted(r["plugin"] for r in records(plugin_log(home))) == sorted([POLICY, "other-pack"])


@pytest.mark.skipif(os.name == "nt", reason="POSIX modes")
def test_a_new_log_file_is_readable_by_its_owner_only(tmp_path: Path) -> None:
    log = tmp_path / "events.jsonl"

    journal.log_append(log, {"policy_id": "p"})

    assert log.stat().st_mode & 0o077 == 0
