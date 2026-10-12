"""LOG-1: decision logging with levels on both routes, person-only settings, redaction and the reader."""

from __future__ import annotations

import json
import os
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

from chock import gatelog
from chock.gate import assemble
from chock.gate.runner import journal
from chock.guardrails import toggle
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

    assert written[0]["plugin_version"] == PLUGIN_VERSION
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


def test_the_toggle_wrapper_reads_the_settings_as_the_runtime_does(tmp_path: Path, monkeypatch) -> None:
    repo, home = tmp_path / "repo", tmp_path / "home"
    (repo / ".git").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("CHOCK_GATE_LOG", raising=False)
    cases = [
        ({}, {}, None),
        ({"level": "debug"}, {"max_bytes": 70_000}, None),
        ({"level": "x"}, {"level": "off"}, None),
    ]
    cases += [({"max_bytes": 1}, {"level": "info"}, "debug"), ({}, {}, "off"), ({}, {"level": "debug"}, "bogus")]
    for user, repo_values, env in cases:
        settings(home, **user)
        settings(repo, **repo_values)
        if env is None:
            monkeypatch.delenv("CHOCK_LOG_LEVEL", raising=False)
        else:
            monkeypatch.setenv("CHOCK_LOG_LEVEL", env)
        assert toggle.log_settings(repo) == journal.log_settings(repo), (user, repo_values, env)
    assert (toggle._LOG_LEVEL_ENV, toggle._LOG_SETTINGS) == (
        journal.LOG_LEVEL_ENV,
        "/".join(journal.LOG_SETTINGS_PARTS),
    )
    assert toggle._LOG_BYTES_RANGE == (journal.LOG_MIN_MAX_BYTES, journal.LOG_MAX_MAX_BYTES)


def test_the_vendored_redaction_is_the_scan_secrets_pattern() -> None:
    manifest = Path(__file__).resolve().parent.parent / ".agents" / "policies" / "scan-secrets" / "manifest.yaml"
    pattern = yaml.safe_load(manifest.read_text(encoding="utf-8"))["hook"]["gate"]["params"]["content_pattern"]
    assert journal._LOG_SECRET_RE.pattern == pattern


# -- person-only: the settings in either scope refuse an agent's write -----------------------------------------

AGENT_WRITES = [
    'echo \'{"level": "off"}\' > .chock/chock-log.json',
    'echo \'{"level": "debug"}\' > ~/.chock/chock-log.json',
    "printf x >> $HOME/.chock/chock-log.json",
    "rm .chock/chock-log.json",
    "sed -i s/info/off/ .chock/chock-log.json",
    "cp evil.json .CHOCK/Chock-Log.JSON",
    "python3 -c \"open('.chock/chock-log.json','w').write('{}')\"",
    'echo x > ".chock\\chock-log.json"',
]


@pytest.mark.parametrize("command", AGENT_WRITES)
def test_an_agents_shell_write_to_the_settings_is_refused(tmp_path: Path, command: str) -> None:
    env = {**os.environ, "CHOCK_RAW_COMMAND": command}
    proc = subprocess.run(
        [sys.executable, str(IMPL / "chock-guardrails-protect.py"), *command.split()],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 1, (proc.stdout, proc.stderr)
    assert "may not change .chock/chock-log.json or ~/.chock/chock-log.json" in proc.stdout


@pytest.mark.parametrize("command", ["cat .chock/chock-log.json", "jq . ~/.chock/chock-log.json"])
def test_reading_the_settings_passes(tmp_path: Path, command: str) -> None:
    env = {**os.environ, "CHOCK_RAW_COMMAND": command}
    proc = subprocess.run(
        [sys.executable, str(IMPL / "chock-guardrails-protect.py"), *command.split()],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout


@pytest.mark.parametrize(
    "path",
    [
        ".chock/chock-log.json",
        "{home}/.chock/chock-log.json",
        r"C:\Users\someone\.chock\chock-log.json",
        ".CHOCK/CHOCK-LOG.JSON",
    ],
    ids=["repo", "user", "windows", "case"],
)
def test_an_agents_edit_or_write_to_the_settings_is_refused_in_both_scopes(tmp_path: Path, path: str) -> None:
    material = json.dumps(
        {"event": "pre-tool-use", "repo_root": str(tmp_path), "writes": {path.format(home=tmp_path): "{}"}}
    )
    proc = subprocess.run(
        [sys.executable, str(IMPL / "chock-guardrails-protect-gate.py")],
        cwd=tmp_path,
        input=material,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 1
    assert "log settings" in proc.stderr


# -- the reader: both routes, and the new filters ---------------------------------------------------------------


def _seed(repo: Path, home: Path) -> None:
    sync = [{"policy_id": "a", "verdict": "block"}, {"policy_id": "a", "verdict": "allow"}]
    plugin = [{"policy_id": "b", "verdict": "ask", "route": "plugin", "level": "info"}]
    for path, lines in ((sync_log(repo), sync), (plugin_log(home), plugin)):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "".join(json.dumps({"ts": "2026-10-12T00:00:00Z", **r}) + "\n" for r in lines), encoding="utf-8"
        )


@pytest.mark.parametrize(
    ("flags", "expected"),
    [
        ([], {"a", "b"}),
        (["--route", "sync"], {"a"}),
        (["--route", "plugin"], {"b"}),
        (["--verdict", "ask"], {"b"}),
        (["--level", "info", "--route", "sync"], {"a"}),
        (["--policy", "b"], {"b"}),
    ],
)
def test_the_reader_reads_both_routes_and_filters(
    tmp_path: Path, monkeypatch, capsys: pytest.CaptureFixture[str], flags: list[str], expected: set[str]
) -> None:
    repo, home = tmp_path / "repo", tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    _seed(repo, home)

    assert gatelog.main(["--repo", str(repo), "--json", *flags]) == 0

    summary = json.loads(capsys.readouterr().out)["summary"]
    assert {row["policy_id"] for row in summary} == expected


def test_level_info_drops_the_allows(tmp_path: Path, monkeypatch, capsys) -> None:
    repo, home = tmp_path / "repo", tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    _seed(repo, home)

    gatelog.main(["--repo", str(repo), "--json", "--level", "info"])

    assert json.loads(capsys.readouterr().out)["events"] == 2


def test_the_reader_says_what_is_wrong_with_the_settings(tmp_path: Path, monkeypatch, capsys) -> None:
    repo, home = tmp_path / "repo", tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    settings(repo, max_bytes=10)

    gatelog.main(["--repo", str(repo), "--json"])

    assert "max_bytes must be a whole number from 65536 (64 KiB)" in capsys.readouterr().err


def test_follow_prints_records_as_they_arrive(tmp_path: Path, monkeypatch) -> None:
    repo, home = tmp_path / "repo", tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    _seed(repo, home)
    monkeypatch.setattr(gatelog, "FOLLOW_INTERVAL", 0)
    printed: list[str] = []

    class Out:
        def write(self, text: str) -> None:
            printed.append(text)

        def flush(self) -> None:
            return None

    calls: list[int] = []

    def paths() -> list[Path]:
        calls.append(1)
        if len(calls) == 2:  # the first call marks where following starts; then a new block lands
            with sync_log(repo).open("a", encoding="utf-8") as fh:
                fh.write(json.dumps({"policy_id": "c", "verdict": "block"}) + "\n")
        return [sync_log(repo)]

    gatelog.follow(paths, lambda record: True, Out(), polls=2)

    assert [json.loads(line)["policy_id"] for line in "".join(printed).splitlines()] == ["c"]


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
