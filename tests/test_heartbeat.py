"""OBS-1: the session_start heartbeat, at each level on each route, and where it is wired."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from bundle_fixtures import make_members
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
from runtime_support import write_runtime

from chock import vendors
from chock.compile.emitters.in_agent_hooks import adapter_rel, generic_hooks_file
from chock.gate import runtime_bundle
from chock.hooks import heartbeat
from chock.hooks.in_agent_generic import install_generic
from chock.hooks.in_agent_merged import install_merged
from chock.hooks.launch import hook_command
from chock.plugin import bundle_build
from chock.plugin.clients import CLIENTS

LAYOUTS = {
    "sync": (sync_layout, lambda repo, home: sync_log(repo)),
    "plugin": (plugin_layout, lambda repo, home: plugin_log(home)),
}
DOCUMENTED = sorted(v for v in runtime_bundle.RUNTIME_AGENTS if vendors.session_start_documented(v))
UNDOCUMENTED = sorted(v for v in runtime_bundle.RUNTIME_AGENTS if not vendors.session_start_documented(v))


def _start(runtime: Path, repo: Path, env: dict[str, str], agent: str = "claude_code") -> subprocess.CompletedProcess:
    key = (vendors.entry(agent)["claims"].get("event_key") or ["hook_event_name"])[0]
    payload = {key: vendors.wire_event(agent, "session_start"), "session_id": "s", "cwd": str(repo)}
    return subprocess.run(
        [sys.executable, str(runtime)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        cwd=repo,
        env=env,
        timeout=60,
        check=False,
    )


@pytest.mark.parametrize("route", sorted(LAYOUTS))
@pytest.mark.parametrize("level", ["off", "info", "debug"])
def test_one_heartbeat_per_session_start_at_each_level_and_route(tmp_path, route, level):
    make, log_of = LAYOUTS[route]
    repo, runtime, _guard = make(tmp_path, CLEAN_GUARD)
    home = tmp_path / "home"
    settings(home, level=level)
    done = _start(runtime, repo, hook_env(home))
    assert done.returncode == 0, done.stderr
    found = records(log_of(repo, home))
    if level == "off":
        assert found == []
        return
    assert len(found) == 1  # the heartbeat only: a session start writes no decision line, even at debug
    beat = found[0]
    assert {k: beat[k] for k in ("event", "route", "agent", "level", "session_id")} == {
        "event": "session_start",
        "route": route,
        "agent": "claude_code",
        "level": "info",
        "session_id": "s",
    }
    if route == "plugin":
        assert (beat["plugin"], beat["plugin_version"]) == (POLICY, PLUGIN_VERSION)
        assert "chock_version" not in beat
    else:
        assert "plugin" not in beat
        assert "plugin_version" not in beat


def test_a_heartbeat_that_cannot_be_written_never_blocks(tmp_path):
    repo, runtime, _guard = sync_layout(tmp_path, CLEAN_GUARD)
    (repo / ".chock" / "log").write_text("a file where the log folder goes", encoding="utf-8")
    done = _start(runtime, repo, hook_env(tmp_path / "home"))
    assert done.returncode == 0, done.stderr
    assert "session_start" not in done.stdout + done.stderr


@pytest.mark.parametrize("agent", DOCUMENTED)
def test_every_documented_agent_runtime_writes_its_heartbeat(tmp_path, agent):
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    runtime = repo / ".chock" / "bin" / f"{agent}.py"
    runtime.parent.mkdir(parents=True)
    write_runtime(runtime, agent)
    done = _start(runtime, repo, hook_env(tmp_path / "home"), agent)
    assert (done.returncode, done.stdout) == (0, "")
    assert [(r["event"], r["agent"]) for r in records(sync_log(repo))] == [("session_start", agent)]


@pytest.mark.parametrize("agent", UNDOCUMENTED)
def test_no_heartbeat_is_wired_where_no_session_start_is_documented(agent):
    assert heartbeat.sync_doc(agent) is None
    assert heartbeat.heartbeat_doc(agent, "x") is None


def _stage_fragment(repo: Path, vendor: str) -> None:
    doc = generic_hooks_file(vendor, hook_command(adapter_rel(vendor), "--guard", "g.sh"))
    path = repo / ".chock" / "compiled" / POLICY / "pre-tool-use" / f"{vendor}-hooks.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(doc), encoding="utf-8")


def test_sync_wires_the_heartbeat_beside_a_generic_vendors_hooks_and_removes_it_with_them(tmp_path):
    _stage_fragment(tmp_path, "gemini_cli")
    install_generic(tmp_path, "gemini_cli")
    config = json.loads((tmp_path / vendors.config_path("gemini_cli")).read_text(encoding="utf-8"))
    start = config["hooks"][vendors.wire_event("gemini_cli", "session_start")]
    assert [h["command"] for e in start for h in e["hooks"]] == [heartbeat.sync_command("gemini_cli")]
    install_generic(tmp_path, "gemini_cli", uninstall=True)
    assert not (tmp_path / vendors.config_path("gemini_cli")).exists()


def test_sync_wires_cursors_heartbeat_only_while_cursor_has_hooks(tmp_path):
    entry = {"command": heartbeat.sync_command("cursor") + " --guard g.sh"}
    path = tmp_path / ".chock" / "compiled" / POLICY / "pre-tool-use" / "cursor-hooks.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({vendors.shell_gate_event("cursor"): [entry]}), encoding="utf-8")
    install_merged(tmp_path, "cursor")
    hooks = json.loads((tmp_path / vendors.config_path("cursor")).read_text(encoding="utf-8"))["hooks"]
    assert hooks["sessionStart"] == [{"command": heartbeat.sync_command("cursor")}]
    install_merged(tmp_path, "cursor", uninstall=True)
    hooks = json.loads((tmp_path / vendors.config_path("cursor")).read_text(encoding="utf-8")).get("hooks", {})
    assert "sessionStart" not in hooks


def _bundle_hooks(client: str, tmp_path: Path):
    members = make_members(tmp_path / "authoring", with_advisory=True)
    bundle = {"id": "obs-bundle", "version": "1.0.0", "description": "d", "members": [m.id for m in members]}
    files = bundle_build.merged_files(client, bundle, members, tmp_path)
    return json.loads(files[Path(CLIENTS[client].layout()[1])])


def _session_start_commands(doc, agent: str) -> list[str]:
    event = vendors.wire_event(agent, "session_start")
    text = json.dumps(doc)
    if isinstance(doc, list):  # kimi: a flat list of rules
        return [r["command"] for r in doc if r.get("event") == event]
    entries = (doc.get("hooks", doc)).get(event, [])
    assert "on_failure" not in json.dumps(entries)
    assert "failClosed" not in json.dumps(entries)
    assert text.count(f'"{event}"') == 1
    return [h["command"] for e in entries for h in (e.get("hooks") or [e])]


@pytest.mark.parametrize("client", sorted(CLIENTS))
def test_each_bundle_carries_one_flagless_heartbeat_where_its_client_documents_session_start(tmp_path, client):
    agent = CLIENTS[client].agent
    doc = _bundle_hooks(client, tmp_path)
    if not vendors.session_start_documented(agent):
        assert "SessionStart" not in json.dumps(doc)
        return
    commands = _session_start_commands(doc, agent)
    assert len(commands) == 1
    assert commands[0].endswith(f'/scripts/{agent}.py"')


def test_a_plugins_session_start_never_arms_the_repository(tmp_path):
    repo, runtime, _guard = plugin_layout(tmp_path, CLEAN_GUARD)
    (repo / ".chock").mkdir()
    done = _start(runtime, repo, hook_env(tmp_path / "home"))
    assert (done.returncode, done.stdout) == (0, "")  # no arming advice, no `chock sync` run: only the heartbeat
    assert not (repo / ".chock" / "bin").exists()


@pytest.mark.parametrize("route", sorted(LAYOUTS))
def test_tool_use_lines_carry_the_session_id_their_heartbeat_does(tmp_path, route):
    make, log_of = LAYOUTS[route]
    repo, runtime, guard = make(tmp_path, BLOCKING_GUARD)
    home = tmp_path / "home"
    run_hook(repo, runtime, guard, "rm -rf build", hook_env(home))
    assert [r.get("session_id") for r in records(log_of(repo, home))] == ["s"]
