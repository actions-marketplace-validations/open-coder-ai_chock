"""GAP-1b: every `chock install` bundle carries one matcher-less stop check, so a stop refuses a Read on the plugin route."""

from __future__ import annotations

import json
import re
import statistics
import sys
import time
from pathlib import Path
from typing import Any

import pytest
from bundle_fixtures import ALL_ROOTS, BUNDLE_ID, bundle, hook_commands, make_members, project, write
from conftest import run_hook_command
from decision_log_support import hook_env

from chock import stop as chock_stop
from chock import vendors
from chock.hooks import stop_check
from chock.hooks.stop_check import STOP_CHECK_FLAG
from chock.plugin.bundle_build import CLIENTS, merged_files
from chock.plugin.store import SCRIPTS_TEMPLATE

#: The clients whose pre-tool payload is Claude-shaped, so one Read payload drives each.
E2E = ("claude", "devin")


def _hooks(client: str, root: Path) -> Any:
    members = make_members(root)
    files = merged_files(client, bundle(members), members, root)
    return json.loads(files[Path(CLIENTS[client].layout()[1])])


def _pre_tool_groups(client: str, doc: Any) -> list[dict]:
    """Every entry under the client's pre-tool event, whatever its dialect (a flat rule list for kimi)."""
    event = vendors.pre_tool_event(CLIENTS[client].agent)
    if isinstance(doc, list):
        return [rule for rule in doc if rule.get("event") == event]
    events = doc.get("hooks", doc.get("agentseam", doc))
    return list(events.get(event, []))


@pytest.mark.parametrize("client", sorted(CLIENTS))
def test_every_bundle_carries_one_matcherless_stop_check(tmp_path: Path, client: str) -> None:
    doc = _hooks(client, tmp_path)
    stops = [c for c in hook_commands(doc) if STOP_CHECK_FLAG in c]
    assert len(stops) == 1, stops
    [group] = [g for g in _pre_tool_groups(client, doc) if any(STOP_CHECK_FLAG in c for c in hook_commands(g))]
    assert "matcher" not in group
    runtime = SCRIPTS_TEMPLATE.format(name=f"{CLIENTS[client].agent}.py")
    assert stops[0].endswith(f'{runtime}" {STOP_CHECK_FLAG}'), stops[0]


def test_a_plugin_with_no_runtime_hook_refuses_to_build() -> None:
    with pytest.raises(ValueError, match="cannot carry the stop check"):
        stop_check.plugin_doc("claude_code", {"hooks": {}}, generic=False)


def _reads(client: str, doc: Any) -> list[str]:
    """The pre-tool commands a Read reaches: entries with no matcher, or one matching `Read`."""
    return [
        c
        for g in _pre_tool_groups(client, doc)
        if not g.get("matcher") or re.fullmatch(g["matcher"], "Read")
        for c in hook_commands(g)
    ]


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A private HOME for this process and the hook: the real ~/.chock is never written."""
    folder = tmp_path / "home"
    folder.mkdir()
    monkeypatch.setenv("HOME", str(folder))
    monkeypatch.setenv("USERPROFILE", str(folder))
    return folder


def _installed(tmp_path: Path, client: str) -> tuple[Path, Path, str]:
    """(project repo, plugin folder, the stop-check command a Read reaches) for a bundle written to disk."""
    plugin = tmp_path / "plugin"
    members = make_members(tmp_path)
    write(plugin, merged_files(client, bundle(members), members, tmp_path))
    doc = json.loads((plugin / CLIENTS[client].layout()[1]).read_text(encoding="utf-8"))
    [command] = [c for c in _reads(client, doc) if STOP_CHECK_FLAG in c]
    return project(tmp_path), plugin, command


def test_in_claude_only_the_stop_check_reaches_a_read(tmp_path: Path) -> None:
    """The bundle's own policies match the shell and writes alone, so without the stop check a Read ran no hook."""
    [command] = _reads("claude", _hooks("claude", tmp_path))
    assert command.endswith(STOP_CHECK_FLAG)


def _read(repo: Path, plugin: Path, home: Path, command: str):
    payload = {
        "hook_event_name": "PreToolUse",
        "tool_name": "Read",
        "tool_input": {"file_path": str(repo / "notes.txt")},
        "session_id": "s",
        "cwd": str(repo),
    }
    env = {**hook_env(home), **dict.fromkeys(ALL_ROOTS, plugin.as_posix())}
    return run_hook_command(command, repo, json.dumps(payload), env=env)


@pytest.mark.parametrize("client", E2E)
def test_a_read_no_policy_matches_is_refused_on_the_plugin_route_while_stopped(
    tmp_path: Path, home: Path, client: str
) -> None:
    """The e2e: the bundle's real hook command; allowed, stop, refused, resume, allowed."""
    repo, plugin, command = _installed(tmp_path, client)
    assert STOP_CHECK_FLAG in command
    deny = "deny" if client == "claude" else "block"
    assert deny not in _read(repo, plugin, home, command).stdout
    assert chock_stop.stop_main(["--repo", str(repo), "--reason", "e2e incident"]) == 0
    refused = _read(repo, plugin, home, command)
    assert deny in refused.stdout, (refused.stdout, refused.stderr)
    assert "stopped: e2e incident" in refused.stdout
    assert chock_stop.resume_main(["--repo", str(repo)]) == 0
    allowed = _read(repo, plugin, home, command)
    assert allowed.returncode == 0, allowed.stderr
    assert deny not in allowed.stdout, allowed.stdout


def test_plugin_stop_check_latency_unstopped(tmp_path: Path, home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Measured, not asserted against a budget: the bundle's stop check per tool call, median of 50."""
    repo, plugin, command = _installed(tmp_path, "claude")
    times = []
    for _ in range(50):
        started = time.perf_counter()
        assert "deny" not in _read(repo, plugin, home, command).stdout
        times.append((time.perf_counter() - started) * 1000)
    with capsys.disabled():
        print(
            f"\nplugin stop-check unstopped ({BUNDLE_ID}): median {statistics.median(times):.1f} ms over 50 on {sys.platform}"
        )
