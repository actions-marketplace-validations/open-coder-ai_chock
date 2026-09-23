"""The packaged gate in every hook-carrying store, reaching exactly what agentseam records.

Claude Code records a write-tool vocabulary and a blocking turn-end hook, so its package gates
both. Codex, Devin and Copilot record no write tools but block at the turn's end, so their
packages carry the gate at `Stop` alone and say so. Cursor records neither, so a gate has no
surface there and its package stays advisory rather than installing a hook that could only
refuse. None of that is typed here: the test asks agentseam the same question the emitter does.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from conftest import init_repo
from test_plugin_gate import POLICY_ID, SCRIPT, _manifest
from test_plugin_gate import policy as shared_policy

from chock.gate import runtime_bundle
from chock.plugin import codex, copilot, cursor, devin
from chock.plugin.gate_package import gate_reach, gate_reaches

#: The shared fixture under a name no test parameter shadows.
gate_policy = shared_policy

STORES = {
    "codex": ("codex_cli", codex.build_codex_plugin, codex.HOOKS_REL, codex.codex_plugin_differences),
    "devin": ("devin", devin.build_devin_plugin, devin.HOOKS_REL, devin.devin_plugin_differences),
    "copilot": ("vscode_copilot", copilot.build_copilot_plugin, copilot.HOOKS_REL, copilot.copilot_plugin_differences),
    "cursor": ("cursor", cursor.build_cursor_plugin, cursor.HOOKS_REL, cursor.cursor_plugin_differences),
}


def _hooks_doc(out: Path, vendor: str, hooks_rel: str) -> dict:
    doc = json.loads((out / hooks_rel).read_text(encoding="utf-8"))
    return doc if vendor == "devin" else doc["hooks"]


@pytest.mark.parametrize("store", sorted(STORES))
def test_the_gate_reaches_what_the_vendor_records(gate_policy, tmp_path: Path, store: str) -> None:
    vendor, build, hooks_rel, _ = STORES[store]
    manifest = _manifest()
    out = tmp_path / "dist" / store / POLICY_ID
    build(gate_policy(manifest), manifest, tmp_path, out)
    matcher, stop = gate_reach(vendor)

    if not gate_reaches(vendor):
        assert not (out / hooks_rel).exists()
        assert not (out / "scripts").exists()
        return

    hooks = _hooks_doc(out, vendor, hooks_rel)
    events = set(hooks)
    assert ("PreToolUse" in events or "preToolUse" in events) == (matcher is not None)
    assert ("Stop" in events or "stop" in events) == stop
    for entries in hooks.values():
        assert "--gate" in entries[0]["hooks"][0]["command"]
    gate = json.loads((out / "scripts" / "gate.json").read_text(encoding="utf-8"))
    assert gate["script_base"] == "gate" and gate["params"]["script"] == f"implementations/{SCRIPT}"
    assert (out / "scripts" / "gate.py").exists()
    assert (out / "scripts" / "implementations" / "helper.py").exists()


def test_which_vendors_the_gate_reaches_is_agentseam_s_answer() -> None:
    """Pinned so a change upstream surfaces here rather than silently widening or narrowing a package."""
    assert gate_reach("claude_code") == ("Write|Edit|MultiEdit|NotebookEdit", True)
    assert gate_reach("codex_cli") == (None, True)
    assert gate_reach("devin") == (None, True)
    assert gate_reach("vscode_copilot") == (None, True)
    assert gate_reach("cursor") == (None, False)


@pytest.mark.parametrize("store", ["codex", "devin", "copilot"])
def test_a_stop_only_package_says_the_write_is_not_judged(gate_policy, tmp_path: Path, store: str) -> None:
    vendor, build, _, _ = STORES[store]
    manifest = _manifest()
    out = tmp_path / "dist" / store / POLICY_ID
    build(gate_policy(manifest), manifest, tmp_path, out)
    manifest_path = next(p for p in out.rglob("plugin.json"))
    description = json.loads(manifest_path.read_text(encoding="utf-8"))["description"]
    assert "Stop hook" in description and "write itself is not judged" in description
    skill = (out / "skills" / POLICY_ID / "SKILL.md").read_text(encoding="utf-8")
    assert "Stop hook installed with the plugin" in skill
    assert "advisory: the client reading it" not in skill


def test_cursor_stays_advisory_for_a_gate(gate_policy, tmp_path: Path) -> None:
    manifest = _manifest()
    out = tmp_path / "dist" / "cursor" / POLICY_ID
    cursor.build_cursor_plugin(gate_policy(manifest), manifest, tmp_path, out)
    description = json.loads((out / ".cursor-plugin" / "plugin.json").read_text(encoding="utf-8"))["description"]
    assert cursor.POSTURE_ADVISORY in description


@pytest.mark.parametrize("store", sorted(STORES))
def test_output_is_byte_stable_in_every_store(gate_policy, tmp_path: Path, store: str) -> None:
    _, build, _, differences = STORES[store]
    manifest = _manifest()
    pack = gate_policy(manifest)
    out = tmp_path / "dist" / store / POLICY_ID
    build(pack, manifest, tmp_path, out)
    assert differences(pack, manifest, tmp_path, out) == []


def test_codex_s_packaged_gate_reads_the_turn_from_where_the_agent_works(gate_policy, tmp_path: Path) -> None:
    """The stop-only path end to end on a non-Claude bundle: the worktree is the event's cwd."""
    manifest = _manifest()
    out = tmp_path / "dist" / "codex" / POLICY_ID
    codex.build_codex_plugin(gate_policy(manifest), manifest, tmp_path, out)
    repo = tmp_path / "project"
    repo.mkdir()
    init_repo(repo)
    (repo / "Leak.java").write_text("FORBIDDEN\n", encoding="utf-8")
    ns: dict = {"__name__": "chock_runtime_under_test"}
    exec(compile(runtime_bundle.render("codex_cli"), "<codex_cli bundle>", "exec"), ns)  # noqa: S102 -- the rendered runtime is the unit under test
    event = SimpleNamespace(event="stop", tool=None, command=None, path=None, content=None, cwd=str(repo), raw={})
    refused = ns["evaluate_gate"](["--gate", str(out / "scripts" / "gate.json")], event)
    assert refused is not None and "Leak.java" in refused[1]


@pytest.mark.parametrize("store", sorted(STORES))
def test_skill_assets_ride_in_every_store(gate_policy, tmp_path: Path, store: str) -> None:
    _, build, _, differences = STORES[store]
    manifest = _manifest()
    pack = gate_policy(
        manifest, skill_files={"body.md": "## Guided setup\n\nOpen `setup.html`.", "setup.html": "<p>page</p>"}
    )
    out = tmp_path / "dist" / store / POLICY_ID
    build(pack, manifest, tmp_path, out)
    assert (out / "skills" / POLICY_ID / "setup.html").read_text(encoding="utf-8") == "<p>page</p>"
    assert "## Guided setup" in (out / "skills" / POLICY_ID / "SKILL.md").read_text(encoding="utf-8")
    (pack / "skill" / "setup.html").unlink()
    assert any("setup.html" in d for d in differences(pack, manifest, tmp_path, out))
    build(pack, manifest, tmp_path, out)
    assert not (out / "skills" / POLICY_ID / "setup.html").exists()
