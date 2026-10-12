"""Emit a Gemini CLI extension: `gemini-extension.json` plus `hooks/hooks.json`, for `gemini extensions install`."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from chock.plugin import gate_package, guard_gate, hook_dir
from chock.plugin.build import PluginNameError, _one_line, plugin_name
from chock.plugin.claude import POSTURE_ADVISORY

#: The reference page: "lowercase or numbers and use dashes instead of underscores or spaces".
_NAME = re.compile(r"^[a-z0-9-]+$")
MANIFEST_KEYS = ("name", "version", "description")

_CAVEAT = (
    "Gemini CLI's hooks documentation says an exit code other than 0 or 2 is a warning and the call proceeds, "
    "and Google is sunsetting Gemini CLI for consumer tiers in favor of Antigravity CLI (Gemini CLI extensions "
    "become Antigravity plugins: use the antigravity client there)."
)
POSTURE_BESTEFFORT = (
    "Best-effort in Gemini CLI by a BeforeTool hook in the extension's hooks/hooks.json (documented by the "
    f"vendor; not witnessed by chock). {_CAVEAT} {hook_dir.POSTURE_TAIL}"
)
POSTURE_GATE = gate_package.gate_posture("gemini_cli", _CAVEAT)

GUARD_NOTE = (
    "This policy ships a BeforeTool hook in this extension's hooks/hooks.json, best-effort in Gemini CLI, "
    "subject to the fail conditions stated in the extension description. Google is moving Gemini CLI users "
    "to Antigravity CLI. Repo-wide git-hook and CI coverage still needs `chock sync`. "
    "See https://github.com/open-coder-ai/chock"
)


def manifest_posture(*, enforced: bool, gate: bool = False, guard: bool = False) -> str:
    """The posture sentence a package's description ends with; `guard` with `gate` states both halves."""
    if not enforced:
        return POSTURE_ADVISORY
    return guard_gate.posture(POSTURE_BESTEFFORT, POSTURE_GATE, guard=guard or not gate, gate=gate)


def build_gemini_manifest(
    manifest: dict[str, Any], policy_dir: Path, *, enforced: bool, gate: bool = False, guard: bool = False
) -> dict[str, Any]:
    """Derive `gemini-extension.json` from a policy manifest: the reference page's example fields."""
    name = plugin_name(str(manifest.get("id") or Path(policy_dir).name))
    if not _NAME.match(name):
        msg = f"{name!r} is not a valid Gemini CLI extension name: lowercase letters, digits and '-' only"
        raise PluginNameError(msg)
    posture = manifest_posture(enforced=enforced, gate=gate, guard=guard)
    data = {
        "name": name,
        "version": str(manifest.get("version") or ""),
        "description": f"{_one_line(manifest.get('description'))} [{posture}]".strip(),
    }
    return {key: data[key] for key in MANIFEST_KEYS if data[key]}


SPEC = hook_dir.Spec("gemini", "gemini_cli", GUARD_NOTE, build_gemini_manifest)


def gemini_plugin_files(policy_dir: Path, manifest: dict[str, Any], repo_root: Path) -> dict[Path, str]:
    """The Gemini CLI extension's files as {relative path: content}, writing nothing."""
    return hook_dir.plugin_files(SPEC, policy_dir, manifest, repo_root)


def build_gemini_plugin(policy_dir: Path, manifest: dict[str, Any], repo_root: Path, out_dir: Path) -> list[Path]:
    """Write the Gemini CLI extension for one policy into a distribution directory."""
    return hook_dir.build(SPEC, policy_dir, manifest, repo_root, out_dir)


def gemini_plugin_differences(policy_dir: Path, manifest: dict[str, Any], repo_root: Path, out_dir: Path) -> list[str]:
    """Report where the on-disk Gemini CLI extension disagrees with what the manifest would produce."""
    return hook_dir.differences(SPEC, policy_dir, manifest, repo_root, out_dir)
