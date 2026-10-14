"""gemini and openhands plugins: their manifests, plugin roots, and why the Claude package is not reused."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path, PureWindowsPath

import pytest
from bundle_fixtures import bundle, hook_commands, make_members, project, run_command
from runtime_payloads import PAYLOADS
from test_plugin_install_targets import LAYOUT, snapshot

from chock.install import package
from chock.plugin import antigravity, gemini, hook_dir, openhands
from chock.plugin.build import PluginNameError
from chock.plugin.bundle_build import merged_files

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git required")


@pytest.mark.parametrize(
    ("fmt", "keys"),
    [
        ("antigravity", set(antigravity.MANIFEST_KEYS)),
        ("gemini", set(gemini.MANIFEST_KEYS)),
        ("openhands", set(openhands.MANIFEST_KEYS)),
    ],
)
def test_an_installed_manifest_holds_only_the_documented_fields(tmp_path: Path, fmt: str, keys: set) -> None:
    """The per-member manifest `chock install` writes adds no key (Antigravity's schema refuses unknown ones)."""
    members = make_members(tmp_path, with_advisory=True)
    files = merged_files(fmt, bundle(members), members, tmp_path, aggregate=False)
    assert set(json.loads(files[Path(LAYOUT[fmt][0])])) <= keys


def test_gemini_hooks_name_the_folder_by_its_documented_variable(tmp_path: Path) -> None:
    hooks = snapshot("gemini", tmp_path)["hooks"]["hooks"]
    assert set(hooks) == {"BeforeTool", "AfterAgent", "SessionStart"}
    assert all('"${extensionPath}/scripts/' in c for c in hook_commands(hooks))


def test_gemini_names_its_extension_as_the_reference_page_asks(tmp_path: Path) -> None:
    manifest = snapshot("gemini", tmp_path)["manifest"]
    assert manifest["name"] == "demo-bundle" and set(manifest) <= set(gemini.MANIFEST_KEYS)
    with pytest.raises(PluginNameError, match="Gemini CLI"):
        gemini.build_gemini_manifest({"id": "a.b"}, tmp_path, enforced=False)
    assert "Antigravity CLI" in gemini.manifest_posture(enforced=True, guard=True)


def test_a_hydrated_gemini_command_reaches_the_launcher_as_exact_single_arguments(tmp_path: Path) -> None:
    """Executed: Gemini replaces ${extensionPath} by text (variables.ts); a spaced folder still arrives whole."""
    root = tmp_path / "First Last" / ".gemini" / "extensions" / "demo"
    stub = "import json, sys\nprint(json.dumps(sys.argv[1:]))\n"
    (root / "scripts").mkdir(parents=True)
    (root / "scripts" / "argv.py").write_text(stub, encoding="utf-8")
    launcher = f'exec "{sys.executable}" "$(dirname "$0")/argv.py" "$@"\n'
    (root / "scripts" / "launch.sh").write_text(launcher, encoding="utf-8")
    command = hook_dir.hook_command(gemini.SPEC, "--guard", "g.py").replace("${extensionPath}", root.as_posix())
    done = subprocess.run(["sh", "-c", command], cwd=project(tmp_path), capture_output=True, text=True, check=False)
    scripts = root.as_posix() + "/scripts"
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout) == [f"{scripts}/gemini_cli.py", "--guard", f"{scripts}/g.py"]


def test_openhands_hooks_name_the_folder_by_absolute_path(tmp_path: Path) -> None:
    found = snapshot("openhands", tmp_path)
    assert set(found["hooks"]["hooks"]) == {"PreToolUse", "Stop", "SessionStart"}
    assert all(hook_dir.ROOT_TOKEN in c for c in hook_commands(found["hooks"]))
    assert found["manifest"]["name"] == "demo-bundle"


def test_the_claude_package_does_not_serve_openhands(tmp_path: Path) -> None:
    """Measured: OpenHands reads `.claude-plugin/`, but chock's Claude package neither matches nor answers its calls."""
    members = make_members(tmp_path)
    out = tmp_path / "claude"
    for rel, content in merged_files("claude", bundle(members), members, tmp_path).items():
        (out / rel).parent.mkdir(parents=True, exist_ok=True)
        (out / rel).write_text(content, encoding="utf-8")
    doc = json.loads((out / "hooks" / "hooks.json").read_text(encoding="utf-8"))
    matchers = {rule.get("matcher") for rules in doc["hooks"].values() for rule in rules} - {None}
    assert matchers and not any(re.fullmatch(m, "terminal") or re.fullmatch(m, "file_editor") for m in matchers)
    repo = project(tmp_path)
    payload = json.loads(json.dumps(PAYLOADS["openhands"]("rm -rf /")).replace('"/x"', json.dumps(repo.as_posix())))
    answers = [run_command(c, out, repo, payload) for c in hook_commands(doc)]
    assert not any(p.returncode == 2 or '"deny"' in p.stdout for p in answers), answers


def test_an_openhands_package_resolves_a_spaced_windows_folder_and_refuses_a_dollar(tmp_path: Path) -> None:
    members = make_members(tmp_path)
    files = merged_files("openhands", bundle(members), members, tmp_path)
    folder = PureWindowsPath(r"C:\Users\Jo Smith\.chock\marketplace\openhands\chock-guardrails")
    hooks = json.loads(hook_dir.resolve_root(files, folder)[Path("hooks/hooks.json")])
    assert all(
        '"C:/Users/Jo Smith/.chock/marketplace/openhands/chock-guardrails/scripts/' in c for c in hook_commands(hooks)
    )
    with pytest.raises(ValueError, match="choose another --dest"):
        hook_dir.resolve_root(files, Path("/home/a$b/p"))


def test_the_surfaces_page_names_every_install_client_in_its_plugin_timeout_row() -> None:
    page = (Path(__file__).resolve().parents[1] / "docs" / "enforcement-surfaces.md").read_text(encoding="utf-8")
    row = next(line for line in page.splitlines() if line.startswith("| Plugin package (`hooks.json`) |"))
    named = {name.strip() for name in row.split("|")[2].split(",")}
    names = {data["name"] for data in package.settings()["clients"].values()}
    assert names - {"GitHub Copilot"} | {"Copilot"} == named
    assert "Claude Code plugin does not protect OpenHands" in page and "--client openhands" in page
