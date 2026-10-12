"""Every hook-carrying plugin format a bundle merges into: its packager, manifest, posture, agent and layout."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from agentseam import packaging

from chock.plugin import antigravity, claude, codex, copilot, cursor, devin, gemini, goose, grok, openhands, store

FilesFn = Callable[[Path, dict[str, Any], Path], dict[Path, str]]


@dataclass(frozen=True)
class Client:
    """One format's packager and the agent its runtime is built for."""

    files: FilesFn
    manifest: Callable[..., dict[str, Any]] | None
    posture: Callable[..., str] | None
    agent: str
    package_agent: str
    #: The store whose layout chock records itself, where agentseam's packaging records none (goose, grok,
    #: antigravity, openhands).
    own_layout: str | None = None

    def layout(self) -> tuple[str | None, str, str]:
        """(manifest, hooks file, skill template) inside the plugin; a manifest-less format has no manifest."""
        if self.own_layout is not None:
            shape = store.layout(self.own_layout) or {}
            return shape["manifest"], shape["hooks"], shape["skill"]
        agent = self.package_agent
        return (
            packaging.layout(agent)["manifest"],
            packaging.supports(agent, packaging.HOOKS),
            packaging.supports(agent, packaging.SKILL),
        )


CLIENTS: dict[str, Client] = {
    "claude": Client(
        claude.claude_plugin_files,
        claude.build_claude_manifest,
        claude.manifest_posture,
        "claude_code",
        "claude_code",
    ),
    "codex": Client(
        codex.codex_plugin_files, codex.build_codex_manifest, codex.manifest_posture, "codex_cli", "codex_cli"
    ),
    "copilot": Client(
        copilot.copilot_plugin_files,
        copilot.build_copilot_manifest,
        copilot.manifest_posture,
        "vscode_copilot",
        "copilot",
    ),
    "cursor": Client(
        cursor.cursor_plugin_files, cursor.build_cursor_manifest, cursor.manifest_posture, "cursor", "cursor"
    ),
    "devin": Client(devin.devin_plugin_files, devin.build_devin_manifest, devin.manifest_posture, "devin", "devin"),
    "goose": Client(goose.goose_plugin_files, None, None, "goose", "goose", own_layout="goose"),
    "grok": Client(grok.grok_plugin_files, None, None, "grok", "grok", own_layout="grok"),
    "antigravity": Client(
        antigravity.antigravity_plugin_files,
        antigravity.build_antigravity_manifest,
        antigravity.manifest_posture,
        "antigravity",
        "antigravity",
        own_layout="antigravity",
    ),
    "gemini": Client(
        gemini.gemini_plugin_files,
        gemini.build_gemini_manifest,
        gemini.manifest_posture,
        "gemini_cli",
        "gemini_cli",
    ),
    "openhands": Client(
        openhands.openhands_plugin_files,
        openhands.build_openhands_manifest,
        openhands.manifest_posture,
        "openhands",
        "openhands",
        own_layout="openhands",
    ),
}
