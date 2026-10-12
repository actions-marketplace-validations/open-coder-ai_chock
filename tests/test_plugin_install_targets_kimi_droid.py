"""kimi and droid plugins: Kimi's hooks inside its manifest, Droid's local marketplace, each runtime's grammar."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path, PureWindowsPath

import client_payloads
import pytest
import yaml
from bundle_fixtures import ADVISORY_ID, GATE_ID, GUARD_ID, bundle, hook_commands, make_members, project, run_command
from install_fixtures import make_catalog
from packaging_helpers import tree_bytes
from test_plugin_install_targets import _install, _tree

from chock.install import package, place
from chock.install.selection import DEFAULT_BUNDLE
from chock.plugin import cli as plugin_cli
from chock.plugin import factory_droid, hook_dir, kimi_code
from chock.plugin.build import PluginNameError
from chock.plugin.bundle_build import CLIENTS, merged_files

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git required")

GOLDEN = Path(__file__).parent / "fixtures" / "plugin_targets"
TARGETS = ("kimi", "droid")
#: (manifest, hooks file) as written to disk: Kimi's hooks are the manifest's `hooks` array.
LAYOUT = {
    "kimi": ("kimi.plugin.json", "kimi.plugin.json"),
    "droid": (".factory-plugin/plugin.json", "hooks/hooks.json"),
}
ROOT_VAR = {"kimi": "${KIMI_PLUGIN_ROOT}", "droid": "${DROID_PLUGIN_ROOT}"}


def written(fmt: str, root: Path) -> dict[Path, str]:
    """A demo bundle's files exactly as `chock install` writes them (hooks folded, roots resolved)."""
    members = make_members(root, with_advisory=True)
    files = merged_files(fmt, bundle(members), members, root)
    return hook_dir.fold(hook_dir.resolve_root(files, root / "pkg"), fmt)


def hooks_of(fmt: str, files: dict[Path, str]) -> object:
    doc = json.loads(files[Path(LAYOUT[fmt][1])])
    return doc["hooks"] if fmt == "kimi" else doc


def snapshot(fmt: str, root: Path) -> dict:
    files = written(fmt, root)
    return {
        "files": sorted(p.as_posix() for p in files),
        "manifest": json.loads(files[Path(LAYOUT[fmt][0])]),
        "hooks": hooks_of(fmt, files),
    }


@pytest.mark.parametrize("fmt", TARGETS)
def test_a_build_matches_its_golden_layout_manifest_and_hooks(tmp_path: Path, fmt: str) -> None:
    golden = json.loads((GOLDEN / f"{fmt}.json").read_text(encoding="utf-8"))
    assert snapshot(fmt, tmp_path) == golden


def test_kimi_ships_its_hooks_in_the_manifest_and_names_its_skills(tmp_path: Path) -> None:
    found = snapshot("kimi", tmp_path)
    assert "hooks/hooks.json" not in found["files"] and "kimi.plugin.json" in found["files"]
    manifest = found["manifest"]
    assert manifest["skills"] == "./skills/" and set(manifest) <= set(kimi_code.MANIFEST_KEYS)
    assert {rule["event"] for rule in manifest["hooks"]} == {"PreToolUse", "Stop"}
    # Every rule holds only the four documented [[hooks]] fields, with chock's 45 s over Kimi's 30 s default.
    assert all(set(rule) <= {"event", "matcher", "command", "timeout"} for rule in manifest["hooks"])
    assert all(rule["timeout"] == 45 for rule in manifest["hooks"])
    for member in (GATE_ID, GUARD_ID, ADVISORY_ID):
        assert f"skills/{member}/SKILL.md" in found["files"]
    with pytest.raises(PluginNameError, match="Kimi Code"):
        kimi_code.build_kimi_manifest({"id": "a.b"}, tmp_path, enforced=False)


def test_droid_ships_a_top_level_event_map_under_its_root_variable(tmp_path: Path) -> None:
    found = snapshot("droid", tmp_path)
    assert set(found["hooks"]) == {"PreToolUse", "Stop"}
    assert set(found["manifest"]) <= set(factory_droid.MANIFEST_KEYS)
    assert "agentseam records that Droid degrades an ask" in factory_droid.manifest_posture(enforced=True, guard=True)


@pytest.mark.parametrize("fmt", TARGETS)
def test_hooks_name_the_folder_by_the_documented_variable_never_a_path(tmp_path: Path, fmt: str) -> None:
    """Both vendors copy the plugin before running it, so an absolute path would name the wrong folder."""
    commands = hook_commands(snapshot(fmt, tmp_path)["hooks"])
    assert commands and all(f'"{ROOT_VAR[fmt]}/scripts/' in c for c in commands)
    assert not any(hook_dir.ROOT_TOKEN in c or tmp_path.as_posix() in c for c in commands)
    members = make_members(tmp_path / "w")
    files = merged_files(fmt, bundle(members), members, tmp_path)
    windows = PureWindowsPath(r"C:\Users\Jo Smith\.chock\marketplace\x\chock-guardrails")
    assert hook_dir.resolve_root(files, windows) == files


@pytest.mark.parametrize("fmt", TARGETS)
def test_the_runtime_answers_its_agents_payload_in_its_own_grammar(tmp_path: Path, fmt: str) -> None:
    members = make_members(tmp_path)
    guard = next(m for m in members if m.id == GUARD_ID)
    out = tmp_path / "pkg"
    files = hook_dir.fold(CLIENTS[fmt].files(guard.policy_dir, guard.manifest, tmp_path), fmt)
    for rel, content in files.items():
        (out / rel).parent.mkdir(parents=True, exist_ok=True)
        (out / rel).write_text(content, encoding="utf-8")
    commands = hook_commands(hooks_of(fmt, files))
    repo = project(tmp_path)
    # Kimi runs a plugin's hooks in the plugin root; Droid in the session's project.
    cwd = out if fmt == "kimi" else repo

    def answers(command: str) -> list:
        payload = client_payloads.pre_tool(fmt, repo, "Bash", {"command": command})
        return [run_command(c, out, cwd, payload) for c in commands]

    denied = answers("rm -rf /")
    assert any(p.returncode == 0 and '"deny"' in p.stdout for p in denied), denied
    assert not any("deny" in p.stdout for p in answers("ls"))


def test_a_spaced_kimi_root_reaches_the_launcher_as_exact_single_arguments(tmp_path: Path) -> None:
    """Executed: the shell expands ${KIMI_PLUGIN_ROOT} inside the quotes, so a spaced folder arrives whole."""
    root = tmp_path / "First Last" / ".kimi-code" / "plugins" / "managed" / "demo"
    (root / "scripts").mkdir(parents=True)
    (root / "scripts" / "argv.py").write_text("import json, sys\nprint(json.dumps(sys.argv[1:]))\n", encoding="utf-8")
    launcher = f'exec "{sys.executable}" "$(dirname "$0")/argv.py" "$@"\n'
    (root / "scripts" / "launch.sh").write_text(launcher, encoding="utf-8")
    command = hook_dir.hook_command(kimi_code.SPEC, "--guard", "g.py")
    env = {**os.environ, "KIMI_PLUGIN_ROOT": root.as_posix()}
    done = subprocess.run(["sh", "-c", command], cwd=root, env=env, capture_output=True, text=True, check=False)
    scripts = root.as_posix() + "/scripts"
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout) == [f"{scripts}/kimi_code.py", "--guard", f"{scripts}/g.py"]


@pytest.mark.parametrize("fmt", TARGETS)
def test_chock_plugin_build_writes_a_target_and_check_finds_it_current(tmp_path: Path, fmt: str) -> None:
    make_members(tmp_path)
    args = ["build", "--repo", str(tmp_path), "--format", fmt, "--out-dir", str(tmp_path / "dist")]
    assert plugin_cli.main(args) == 0
    built = tmp_path / "dist" / fmt / GUARD_ID
    assert (built / LAYOUT[fmt][1]).is_file() and not (fmt == "kimi" and (built / "hooks").exists())
    assert plugin_cli.main([*args, "--check"]) == 0


# --- chock install --client kimi-code|factory-droid ----------------------------------------------


@pytest.fixture
def catalog(tmp_path: Path) -> tuple[Path, str]:
    return make_catalog(tmp_path)


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "home"
    path.mkdir()
    monkeypatch.setenv("HOME", str(path))
    monkeypatch.setenv("USERPROFILE", str(path))
    return path


def test_kimi_install_stages_the_folder_prints_the_tui_steps_and_touches_nothing_else(
    catalog, tmp_path: Path, home: Path, capsys
) -> None:
    root, ref = catalog
    before = _tree(home)
    assert _install(tmp_path, root, ref, "kimi-code", "--apply") == 0
    out = capsys.readouterr().out
    folder = place.plugin_dir("kimi-code", place.default_dest("kimi-code"), DEFAULT_BUNDLE)
    manifest = json.loads((folder / "kimi.plugin.json").read_text(encoding="utf-8"))
    assert manifest["hooks"] and not (folder / "hooks").exists() and (folder / package.MARKER).is_file()
    rel = folder.relative_to(home).as_posix()
    added = _tree(home) - before
    assert all(p == rel or p.startswith(f"{rel}/") or rel.startswith(f"{p}/") for p in added), added
    assert f"/plugins install {folder}" in out and "/reload" in out


def test_droid_install_writes_a_local_marketplace_and_prints_both_commands(
    catalog, tmp_path: Path, home: Path, capsys, monkeypatch
) -> None:
    root, ref = catalog
    monkeypatch.setenv("PATH", os.pathsep.join(p for p in os.environ["PATH"].split(os.pathsep) if p))
    assert shutil.which("droid") is None, "droid is on PATH; this test needs it absent"
    before = _tree(home)
    assert _install(tmp_path, root, ref, "factory-droid", "--apply") == 1
    out = capsys.readouterr()
    dest = place.default_dest("factory-droid")
    folder = place.plugin_dir("factory-droid", dest, DEFAULT_BUNDLE)
    assert dest.name == package.settings()["marketplace"], "the folder name and marketplace name agree"
    index = json.loads((dest / ".factory-plugin" / "marketplace.json").read_text(encoding="utf-8"))
    assert index["name"] == "chock-local"
    assert index["plugins"] == [
        {
            "name": DEFAULT_BUNDLE,
            "source": f"./droid/{DEFAULT_BUNDLE}",
            "description": index["plugins"][0]["description"],
        }
    ]
    assert (folder / ".factory-plugin" / "plugin.json").is_file() and (folder / "hooks" / "hooks.json").is_file()
    added = _tree(home) - before
    rel = dest.relative_to(home).as_posix()
    assert all(p == rel or p.startswith(f"{rel}/") or rel.startswith(f"{p}/") for p in added), added
    assert f"droid plugin marketplace add {dest}" in out.out
    assert f"droid plugin install {DEFAULT_BUNDLE}@chock-local --scope project" in out.out
    assert "--apply needs the `droid` command on PATH" in out.err


def test_droid_apply_runs_both_commands_where_the_cli_is_present(
    catalog, tmp_path: Path, home: Path, monkeypatch
) -> None:
    root, ref = catalog
    bin_dir, log = tmp_path / "bin", tmp_path / "droid.log"
    bin_dir.mkdir()
    (bin_dir / "droid").write_text(f'#!/bin/sh\necho "$@" >> "{log}"\n', encoding="utf-8")
    (bin_dir / "droid").chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    assert _install(tmp_path, root, ref, "factory-droid", "--apply") == 0
    dest = place.default_dest("factory-droid")
    assert log.read_text(encoding="utf-8").splitlines() == [
        f"plugin marketplace add {dest}",
        f"plugin install {DEFAULT_BUNDLE}@chock-local --scope project",
    ]


@pytest.mark.parametrize("client", ["kimi-code", "factory-droid"])
def test_a_second_install_changes_nothing(catalog, tmp_path: Path, home: Path, client: str) -> None:
    root, ref = catalog
    assert _install(tmp_path, root, ref, client) == 0
    dest = place.default_dest(client)
    first = tree_bytes(dest)
    assert _install(tmp_path, root, ref, client) == 0
    assert tree_bytes(dest) == first


@pytest.mark.parametrize(
    ("client", "evidence"), [("kimi-code", "agentseam/issues/135"), ("factory-droid", "agentseam/issues/184")]
)
def test_labels_come_from_the_tier_table_and_warnings_link_the_evidence_issue(
    catalog, tmp_path: Path, home: Path, capsys, client: str, evidence: str
) -> None:
    root, ref = catalog
    assert _install(tmp_path, root, ref, client) == 0
    out = capsys.readouterr().out
    lines = {line.split()[0]: line for line in out.splitlines() if line.startswith("  demo-")}
    prefix = "best-effort, fail mode open (agentseam vendor-docs): "
    assert f"{prefix}refuses a matched shell command" in lines[GUARD_ID]
    assert "advisory only" in lines[ADVISORY_ID] and prefix not in lines[ADVISORY_ID]
    assert "warning: Untested: chock has not witnessed an install in this client" in out
    assert evidence in out


def test_an_ask_gate_is_labelled_not_enforced_in_kimi_and_droid(tmp_path: Path) -> None:
    members = make_members(tmp_path / "m")
    gate = next(m for m in members if m.id == GATE_ID)
    gate.manifest["hook"]["gate"]["action"] = "ask"
    (gate.policy_dir / "manifest.yaml").write_text(yaml.safe_dump(gate.manifest), encoding="utf-8")
    kimi = {label.policy_id: label.says for label in package.labels(members, tmp_path / "m", "kimi-code")}
    assert kimi[GATE_ID].endswith("; the ask is not enforced here: Kimi Code cannot prompt for confirmation")
    droid = {label.policy_id: label.says for label in package.labels(members, tmp_path / "m", "factory-droid")}
    assert droid[GATE_ID].endswith(
        "; the ask is not enforced here: Droid's ask does not force a prompt, so this is a block"
    )
