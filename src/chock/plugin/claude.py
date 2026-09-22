"""Emit a Claude-format plugin from a policy directory."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agentseam import packaging

from chock.compile.emitters.in_agent import (
    GATE_FILE,
    _guard_script,
    gate_hooks_map_file,
    hooks_map_file,
    tool_use_gate_spec,
)
from chock.gate import runtime_bundle
from chock.gate.runner import SCRIPT_BASE_GATE
from chock.plugin import store
from chock.plugin.build import (
    _ADVISORY_NOTE_HOOK,
    _ADVISORY_NOTE_RULE,
    LICENSE_REL,
    _author,
    _keywords,
    _one_line,
    build_skill,
    license_text,
    plugin_name,
    skill_assets,
)
from chock.plugin.store import SCRIPTS_TEMPLATE as _SCRIPTS_TEMPLATE

_MANIFEST_REL = packaging.layout("claude_code")["manifest"]

POSTURE_ENFORCED = (
    "Session-enforced via a PreToolUse hook; needs python3 and a usable bash. Without them, "
    "fail-open clients allow silently; fail-closed clients refuse matched commands. On Windows, "
    "disable the python3 Store alias or install Python. If the guard itself crashes or times "
    "out, the hook asks for confirmation rather than allowing silently."
)
POSTURE_ENFORCED_GATE = (
    "Session-enforced via PreToolUse and Stop hooks; needs python3. PreToolUse judges the file "
    "a tool call would write; Stop re-reads what the turn actually left on disk, so a file "
    "written through a shell heredoc is judged too. Without python3, fail-open clients allow "
    "silently. A gate that cannot reach a decision refuses rather than allowing one it never "
    "judged. Enforcement at every commit and in CI still needs chock installed in the repo."
)
POSTURE_ADVISORY = "Advisory skill only; enforcement needs chock installed in the repo."

_ENFORCED_NOTE = (
    "This policy is enforced in this client by a PreToolUse hook installed with the plugin, "
    "subject to the fail conditions stated in the plugin description. Repo-wide "
    "enforcement across every commit and in CI still needs `chock sync`. "
    "See https://github.com/open-coder-ai/chock"
)
_ENFORCED_GATE_NOTE = (
    "This policy is enforced in this client by the PreToolUse and Stop hooks installed with "
    "the plugin, subject to the fail conditions stated in the plugin description. Repo-wide "
    "enforcement across every commit and in CI still needs `chock sync`. "
    "See https://github.com/open-coder-ai/chock"
)

#: Where a packaged gate and everything it runs live inside the plugin: the compiled gate,
#: the runner beside it (write_gate looks there first), and a script gate's own program with
#: the files it imports, copied whole so a `sys.path` it sets on its own directory still holds.
_GATE_REL = _SCRIPTS_TEMPLATE.format(name=GATE_FILE)
_RUNNER_REL = _SCRIPTS_TEMPLATE.format(name="gate.py")
_IMPLEMENTATIONS = "implementations"


def _adapter_source(agent: str = "claude_code") -> str:
    """`agent`'s self-contained runtime, verbatim -- agentseam's bundle plus chock's own"""
    return runtime_bundle.render(agent)


def _hook_command(script: str) -> str:
    """One interpreter invocation, deliberately without a fallback chain."""
    adapter = packaging.executable_ref("claude_code", _SCRIPTS_TEMPLATE.format(name="claude_code.py"))
    guard = packaging.executable_ref("claude_code", _SCRIPTS_TEMPLATE.format(name=script))
    return f'python3 "{adapter}" --guard "{guard}"'


def _gate_command() -> str:
    """The same adapter, handed the packaged gate instead of a guard."""
    adapter = packaging.executable_ref("claude_code", _SCRIPTS_TEMPLATE.format(name="claude_code.py"))
    gate = packaging.executable_ref("claude_code", _GATE_REL)
    return f'python3 "{adapter}" --gate "{gate}"'


def _runner_source() -> str:
    """The stdlib-only gate runner, verbatim -- the one `chock sync` vendors under .chock/bin."""
    return (Path(runtime_bundle.__file__).resolve().parent / "runner.py").read_text(encoding="utf-8")


def _packaged_gate(policy_dir: Path, spec: dict[str, Any]) -> tuple[dict[str, Any], dict[Path, str]]:
    """The gate as the plugin carries it, plus the files a script gate needs beside it."""
    packaged = {key: value for key, value in spec.items() if key != "params"}
    packaged["params"] = dict(spec.get("params") or {})
    files: dict[Path, str] = {}
    if spec.get("kind") == "script":
        name = Path(str(packaged["params"].get("script", ""))).name
        packaged["params"]["script"] = f"{_IMPLEMENTATIONS}/{name}"
        packaged["script_base"] = SCRIPT_BASE_GATE
        root = Path(policy_dir) / _IMPLEMENTATIONS
        for path in sorted(root.rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts:
                rel = Path(_IMPLEMENTATIONS) / path.relative_to(root)
                files[Path(_SCRIPTS_TEMPLATE.format(name=rel.as_posix()))] = path.read_text(encoding="utf-8")
    return packaged, files


def build_claude_manifest(
    manifest: dict[str, Any], policy_dir: Path, *, enforced: bool, gate: bool = False
) -> dict[str, Any]:
    """Derive `.claude-plugin/plugin.json` from a policy manifest."""
    policy_id = manifest.get("id") or Path(policy_dir).name
    provenance = manifest.get("provenance") or {}
    posture = (POSTURE_ENFORCED_GATE if gate else POSTURE_ENFORCED) if enforced else POSTURE_ADVISORY

    data: dict[str, Any] = {
        "name": plugin_name(str(policy_id)),
        "description": f"{_one_line(manifest.get('description'))} [{posture}]",
        "keywords": _keywords(manifest),
    }
    if manifest.get("version"):
        data["version"] = str(manifest["version"])
    author = _author(provenance)
    if author:
        data["author"] = author
    if provenance.get("license"):
        data["license"] = str(provenance["license"])
    if provenance.get("source_repo"):
        data["repository"] = str(provenance["source_repo"])
    return data


def claude_plugin_files(policy_dir: Path, manifest: dict[str, Any], repo_root: Path) -> dict[Path, str]:
    """The Claude plugin's files as {relative path: content}, writing nothing."""
    policy_dir = Path(policy_dir)
    policy_id = manifest.get("id") or policy_dir.name
    name = plugin_name(str(policy_id))
    script = _guard_script(policy_dir, str(policy_id))
    gate = None if script else tool_use_gate_spec(policy_dir, Path(repo_root))
    enforced = script is not None or gate is not None

    skill = build_skill(policy_dir, manifest, Path(repo_root), hooks="hooks/hooks.json" if enforced else None)
    if script:
        skill = skill.replace(_ADVISORY_NOTE_RULE, _ENFORCED_NOTE).replace(_ADVISORY_NOTE_HOOK, _ENFORCED_NOTE)
    elif gate:
        skill = skill.replace(_ADVISORY_NOTE_RULE, _ENFORCED_GATE_NOTE).replace(
            _ADVISORY_NOTE_HOOK, _ENFORCED_GATE_NOTE
        )

    skill_rel = Path(packaging.supports("claude_code", packaging.SKILL).format(name=name))
    files: dict[Path, str] = {
        Path(_MANIFEST_REL): json.dumps(
            build_claude_manifest(manifest, policy_dir, enforced=enforced, gate=gate is not None), indent=2
        )
        + "\n",
        skill_rel: skill,
    }
    for rel, content in skill_assets(policy_dir).items():
        files[skill_rel.parent / rel] = content
    licence = license_text(manifest)
    if licence:
        files[LICENSE_REL] = licence
    hooks_rel = Path(packaging.supports("claude_code", packaging.HOOKS))
    if script:
        files[hooks_rel] = json.dumps(hooks_map_file("claude_code", _hook_command(script)), indent=2) + "\n"
        files[Path(_SCRIPTS_TEMPLATE.format(name="claude_code.py"))] = _adapter_source("claude_code")
        files[Path(_SCRIPTS_TEMPLATE.format(name=script))] = (policy_dir / _IMPLEMENTATIONS / script).read_text(
            encoding="utf-8"
        )
    elif gate:
        packaged, carried = _packaged_gate(policy_dir, gate)
        files[hooks_rel] = json.dumps(gate_hooks_map_file("claude_code", _gate_command()), indent=2) + "\n"
        files[Path(_SCRIPTS_TEMPLATE.format(name="claude_code.py"))] = _adapter_source("claude_code")
        files[Path(_RUNNER_REL)] = _runner_source()
        files[Path(_GATE_REL)] = json.dumps(packaged, indent=2) + "\n"
        files.update(carried)
    return files


def stale_claude_files(policy_dir: Path, manifest: dict[str, Any], repo_root: Path, out_dir: Path) -> list[Path]:
    """Files under this package that the current manifest would no longer produce."""
    return store.stale_store_files("claude", claude_plugin_files, policy_dir, manifest, repo_root, out_dir)


def build_claude_plugin(policy_dir: Path, manifest: dict[str, Any], repo_root: Path, out_dir: Path) -> list[Path]:
    """Write the Claude-format package for one policy into a distribution directory."""
    return store.build_store_plugin("claude", claude_plugin_files, policy_dir, manifest, repo_root, out_dir)


def claude_plugin_differences(policy_dir: Path, manifest: dict[str, Any], repo_root: Path, out_dir: Path) -> list[str]:
    """Report where the on-disk Claude plugin disagrees with what the manifest would produce."""
    return store.store_plugin_differences("claude", claude_plugin_files, policy_dir, manifest, repo_root, out_dir)
