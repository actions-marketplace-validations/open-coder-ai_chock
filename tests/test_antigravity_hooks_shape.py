"""Antigravity hooks.json, plugin and repo route: the shape antigravity.google/docs/hooks documents (read 2026-10-17)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from bundle_fixtures import bundle, make_members

from chock.compile.emitters.in_agent_hooks import generic_pre_tool_config, generic_stop_config
from chock.plugin.bundle_build import merged_files

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git required")


def assert_antigravity_hooks_shape(doc: dict) -> None:
    """Tool events hold {matcher, hooks} groups; Stop lists bare handlers."""
    events = doc["agentseam"]
    assert events["PreToolUse"] and events["Stop"]
    for group in events["PreToolUse"]:
        assert group["matcher"] == "*"
        assert group["hooks"] and all(h["type"] == "command" and isinstance(h["command"], str) for h in group["hooks"])
    for handler in events["Stop"]:
        assert handler["type"] == "command" and isinstance(handler["command"], str)
        assert "hooks" not in handler and "matcher" not in handler


def test_the_antigravity_plugin_hooks_json_has_the_documented_shape(tmp_path: Path) -> None:
    members = make_members(tmp_path, with_advisory=True)
    files = merged_files("antigravity", bundle(members), members, tmp_path)
    assert_antigravity_hooks_shape(json.loads(files[Path("hooks.json")]))


def test_the_antigravity_repo_hooks_json_has_the_documented_shape() -> None:
    pre_tool = generic_pre_tool_config("antigravity", "guard", None)
    stop = generic_stop_config("antigravity", "gate --stop")
    assert_antigravity_hooks_shape({"agentseam": {**pre_tool["agentseam"], **stop["agentseam"]}})
