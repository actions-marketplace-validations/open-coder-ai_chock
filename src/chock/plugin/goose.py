"""Emit a goose plugin: a manifest-less folder with `hooks/hooks.json`, loaded from `.agents/plugins/<name>/`."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from chock.plugin import hook_dir

#: The vendor's hooks guide documents `on_failure: block` (agentseam writes it on every entry) as
#: denying a PreToolUse call whose hook fails; it also says Stop stays fail-open whatever it says.
GUARD_NOTE = (
    "This policy ships a PreToolUse hook in this plugin's hooks/hooks.json with `on_failure: block`, "
    "which goose's hooks documentation says denies the tool call when the hook fails to run or "
    "answer (documented, not witnessed by chock); goose's Stop hooks stay fail-open. The hook needs "
    "git and a Python 3.11+ on PATH. Repo-wide git-hook and CI coverage still needs `chock sync`. "
    "See https://github.com/open-coder-ai/chock"
)

SPEC = hook_dir.Spec("goose", "goose", GUARD_NOTE)


def goose_plugin_files(policy_dir: Path, manifest: dict[str, Any], repo_root: Path) -> dict[Path, str]:
    """The goose plugin's files as {relative path: content}, writing nothing."""
    return hook_dir.plugin_files(SPEC, policy_dir, manifest, repo_root)


def build_goose_plugin(policy_dir: Path, manifest: dict[str, Any], repo_root: Path, out_dir: Path) -> list[Path]:
    """Write the goose package for one policy into a distribution directory."""
    return hook_dir.build(SPEC, policy_dir, manifest, repo_root, out_dir)


def goose_plugin_differences(policy_dir: Path, manifest: dict[str, Any], repo_root: Path, out_dir: Path) -> list[str]:
    """Report where the on-disk goose plugin disagrees with what the manifest would produce."""
    return hook_dir.differences(SPEC, policy_dir, manifest, repo_root, out_dir)
