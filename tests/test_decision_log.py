"""LOG-1: decision logging with levels on both routes, person-only settings, redaction and the reader."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from decision_log_support import (
    BLOCKING_GUARD,
    CLEAN_GUARD,
    PLUGIN_VERSION,
    POLICY,
    hook_env,
    plugin_layout,
    plugin_log,
    records,
    run_hook,
    settings,
    sync_layout,
    sync_log,
)
from history_support import SECRET

from chock.gate import assemble
from chock.gate.runner import journal
from chock.guardrails import chock_bundle_log
from chock.guardrails.plugin import protect_dir

LAYOUTS = {
    "sync": (sync_layout, lambda repo, home: sync_log(repo)),
    "plugin": (plugin_layout, lambda repo, home: plugin_log(home)),
}
#: (level, guard) -> the (verdict, record level) lines one hook call writes.
EXPECTED = {
    ("off", BLOCKING_GUARD): [],
    ("off", CLEAN_GUARD): [],
    ("info", BLOCKING_GUARD): [("block", "info")],
    ("info", CLEAN_GUARD): [],
    ("debug", BLOCKING_GUARD): [("block", "info")],
    ("debug", CLEAN_GUARD): [("allow", "debug")],
}
IMPL = protect_dir() / "implementations"


@pytest.fixture
def home(tmp_path: Path) -> Path:
    folder = tmp_path / "home"
    folder.mkdir()
    return folder


def _call(tmp_path: Path, home: Path, route: str, guard_body: str, command: str = "rm -rf build", **levels: str):
    layout, log = LAYOUTS[route]
    repo, runtime, guard = layout(tmp_path, guard_body)
    proc = run_hook(repo, runtime, guard, command, hook_env(home, **levels))
    return proc, records(log(repo, home))


@pytest.mark.parametrize("route", sorted(LAYOUTS))
@pytest.mark.parametrize(("level", "guard_body"), sorted(EXPECTED), ids=lambda v: v if v in journal.LOG_LEVELS else "")
def test_each_level_on_each_route_writes_exactly_its_records(
    tmp_path: Path, home: Path, route: str, level: str, guard_body: str
) -> None:
    _, written = _call(tmp_path, home, route, guard_body, CHOCK_LOG_LEVEL=level)

    assert [(r["verdict"], r["level"]) for r in written] == EXPECTED[(level, guard_body)]
    for record in written:
        assert record["route"] == route
        assert record["policy_id"] == POLICY
        assert {"ts", "agent", "event", "surface", "reason", "duration_ms", "can_ask", "chock_version"} <= set(record)
        assert ("trace" in record) == (level == "debug")
        assert ("plugin_version" in record) == (route == "plugin")


def test_the_plugin_route_names_its_package_version_and_writes_nothing_into_the_repo(
    tmp_path: Path, home: Path
) -> None:
    _, written = _call(tmp_path, home, "plugin", BLOCKING_GUARD)

    assert (written[0]["plugin"], written[0]["plugin_version"]) == (POLICY, PLUGIN_VERSION)
    assert not (tmp_path / "repo" / ".chock").exists()


def test_the_default_level_is_info(tmp_path: Path, home: Path) -> None:
    _, written = _call(tmp_path, home, "sync", BLOCKING_GUARD)

    assert [r["level"] for r in written] == ["info"]
    assert "trace" not in written[0]


def test_a_level_in_the_command_string_does_not_reach_the_hook(tmp_path: Path, home: Path) -> None:
    """Hook env comes from the client, never from the tool input an agent writes."""
    proc, written = _call(tmp_path, home, "sync", BLOCKING_GUARD, command="CHOCK_LOG_LEVEL=off rm -rf build")

    assert '"deny"' in proc.stdout
    assert [r["verdict"] for r in written] == ["block"]


@pytest.mark.parametrize("route", sorted(LAYOUTS))
def test_secrets_are_redacted_and_the_trace_is_capped_in_debug(tmp_path: Path, home: Path, route: str) -> None:
    command = f"deploy --key {SECRET} " + "x" * 400
    _, written = _call(tmp_path, home, route, BLOCKING_GUARD, command=command, CHOCK_LOG_LEVEL="debug")

    trace = written[0]["trace"]
    assert SECRET not in json.dumps(written)
    assert trace["command"].startswith("deploy --key [redacted] ")
    assert len(trace["command"]) == journal.LOG_TRACE_CAP + len("...")
    assert (trace["tool"], trace["wire_event"], trace["exit_code"]) == ("Bash", "PreToolUse", 1)
    assert set(trace["stages_ms"]) == {"guard"}


def test_a_log_that_cannot_be_written_leaves_the_plugin_verdict_alone(tmp_path: Path, home: Path) -> None:
    (home / ".chock").write_text("a file where the log folder goes", encoding="utf-8")

    proc, _ = _call(tmp_path, home, "plugin", BLOCKING_GUARD, CHOCK_LOG_LEVEL="debug")

    assert proc.returncode == 0
    assert '"permissionDecision": "deny"' in proc.stdout
    assert "Traceback" not in proc.stderr


def test_rotation_follows_a_custom_max_bytes(tmp_path: Path, home: Path) -> None:
    layout, _ = LAYOUTS["sync"]
    repo, runtime, guard = layout(tmp_path, BLOCKING_GUARD)
    settings(repo, max_bytes=journal.LOG_MIN_MAX_BYTES)
    sync_log(repo).parent.mkdir(parents=True)
    sync_log(repo).write_text("x" * (journal.LOG_MIN_MAX_BYTES + 1), encoding="utf-8")

    run_hook(repo, runtime, guard, "rm -rf build", hook_env(home))

    assert sync_log(repo).with_name("gate-events.1.jsonl").stat().st_size == journal.LOG_MIN_MAX_BYTES + 1
    assert len(records(sync_log(repo))) == 1


@pytest.mark.parametrize(
    ("size", "kept"),
    [
        (journal.LOG_MIN_MAX_BYTES - 1, False),
        (journal.LOG_MIN_MAX_BYTES, True),
        (journal.LOG_MAX_MAX_BYTES, True),
        (journal.LOG_MAX_MAX_BYTES + 1, False),
        (True, False),
        ("1048576", False),
    ],
)
def test_max_bytes_bounds_are_enforced_with_a_clear_error(tmp_path: Path, size: object, kept: bool) -> None:
    found, problems = journal.log_settings_read(settings(tmp_path, max_bytes=size))

    assert ("max_bytes" in found) is kept
    assert bool(problems) is not kept
    if problems:
        assert "65536 (64 KiB) to 1073741824 (1 GiB)" in problems[0]


def test_precedence_is_env_then_repo_then_user_then_info(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo, home = tmp_path / "repo", tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.delenv("CHOCK_GATE_LOG", raising=False)
    assert journal.log_settings(repo) == ("info", journal.LOG_DEFAULT_MAX_BYTES)

    settings(home, level="debug", max_bytes=200_000)
    assert journal.log_settings(repo) == ("debug", 200_000)

    settings(repo, level="off")
    assert journal.log_settings(repo) == ("off", 200_000)

    monkeypatch.setenv("CHOCK_LOG_LEVEL", "info")
    assert journal.log_settings(repo) == ("info", 200_000)

    monkeypatch.setenv("CHOCK_GATE_LOG", "0")
    assert journal.log_settings(repo)[0] == "off", "the deprecated switch still turns logging off"


@pytest.mark.parametrize(("level", "lines"), [("off", 0), ("info", 1), ("debug", 1)])
def test_the_toggle_wrapper_writes_its_off_line_at_the_level_in_force(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, level: str, lines: int
) -> None:
    repo, home = tmp_path / "repo", tmp_path / "home"
    (repo / ".git").mkdir(parents=True)
    monkeypatch.chdir(repo)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("CHOCK_GATE_LOG", raising=False)
    monkeypatch.setenv("CHOCK_LOG_LEVEL", level)

    chock_bundle_log.log_off(repo / ".chock" / "guardrails.json", "bundle-x", "member-y")

    written = records(repo / ".chock" / "log" / "gate-events.jsonl")
    assert [(r["policy_id"], r["verdict"], r["level"]) for r in written] == [("member-y", "off", "info")] * lines


def test_the_vendored_redaction_is_the_scan_secrets_pattern() -> None:
    manifest = Path(__file__).resolve().parent.parent / ".agents" / "policies" / "scan-secrets" / "manifest.yaml"
    pattern = yaml.safe_load(manifest.read_text(encoding="utf-8"))["hook"]["gate"]["params"]["content_pattern"]
    assert journal._LOG_SECRET_RE.pattern == pattern


def test_an_unreadable_payload_is_one_info_line(tmp_path: Path, home: Path) -> None:
    repo, runtime, guard = sync_layout(tmp_path, CLEAN_GUARD)

    proc = subprocess.run(
        [sys.executable, str(runtime), "--guard", str(guard)],
        input="not json",
        capture_output=True,
        text=True,
        cwd=repo,
        env=hook_env(home),
        timeout=60,
        check=False,
    )

    assert "could not read this hook's payload" in proc.stdout + proc.stderr
    assert [(r["verdict"], r["reason"]) for r in records(sync_log(repo))] == [("block", "unreadable-block")]


GATE_SPEC = {
    "kind": "content_regex",
    "on": ["tool_use"],
    "action": "block",
    "message": "secret",
    "params": {"scan": "added_lines", "content_pattern": r"(?i)(AKIA[0-9A-Z]{16})"},
}


@pytest.mark.parametrize("level", ["info", "debug"])
def test_a_sync_gate_decision_is_one_line_not_two(tmp_path: Path, home: Path, level: str) -> None:
    """gate.py writes a compiled gate's line on the sync route; the runtime around it adds none."""
    repo, runtime, _ = sync_layout(tmp_path, CLEAN_GUARD)
    (runtime.parent / "gate.py").write_text(assemble.runner_source(), encoding="utf-8")
    gate = repo / ".chock" / "compiled" / "p-gate" / "pre-tool-use" / "gate.json"
    gate.parent.mkdir(parents=True)
    gate.write_text(json.dumps(GATE_SPEC), encoding="utf-8")
    write = {"file_path": str(repo / "app.py"), "content": f'KEY = "{SECRET}"\n'}
    payload = {"hook_event_name": "PreToolUse", "tool_name": "Write", "tool_input": write, "session_id": "s"}

    proc = subprocess.run(
        [sys.executable, str(runtime), "--gate", str(gate)],
        input=json.dumps({**payload, "cwd": str(repo)}),
        capture_output=True,
        text=True,
        cwd=repo,
        env=hook_env(home, CHOCK_LOG_LEVEL=level),
        timeout=60,
        check=False,
    )

    assert '"deny"' in proc.stdout, proc.stderr
    written = records(sync_log(repo))
    assert [(r["policy_id"], r["verdict"], r["route"]) for r in written] == [("p-gate", "block", "sync")]
    assert SECRET not in sync_log(repo).read_text(encoding="utf-8")
