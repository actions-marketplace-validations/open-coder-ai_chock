"""goose, grok and antigravity payloads, for suites parametrized over every plugin client.

Shapes follow agentseam's vendor fields (and each vendor's hooks page): goose names the event under
`event` and the folder under `working_dir`; grok sends both event keys; antigravity names no event,
nests the call under `toolCall` and lists `workspacePaths`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from chock.plugin import gate_package, hook_dir
from chock.plugin.bundle_build import CLIENTS


def pre_tool(client: str, repo: Path, tool: str, tool_input: dict[str, Any]) -> dict[str, Any] | None:
    """`tool` ("Bash" or "Write") called in `client`'s own shape; None for a client not covered here."""
    write = tool == "Write"
    if client == "goose":
        args = {"path": tool_input["file_path"], "content": tool_input["content"]} if write else tool_input
        body = {"event": "PreToolUse", "session_id": "s", "tool_call_id": "call-1", "working_dir": str(repo)}
        return {**body, "tool_name": "write" if write else "shell", "tool_input": args}
    if client == "grok":
        body = {"hook_event_name": "PreToolUse", "hookEventName": "pre_tool_use", "sessionId": "s", "cwd": str(repo)}
        return {**body, "toolName": tool, "toolInput": tool_input}
    if client == "antigravity":
        args = (
            {"TargetFile": tool_input["file_path"], "CodeContent": tool_input["content"]}
            if write
            else {"CommandLine": tool_input["command"], "Cwd": str(repo)}
        )
        call = {"name": "write_to_file" if write else "run_command", "args": args}
        return {"toolCall": call, "stepIdx": 1, "conversationId": "c", "workspacePaths": [str(repo)]}
    return None


def stop(client: str, repo: Path) -> dict[str, Any] | None:
    """A clean turn end in `client`'s own shape; None for a client not covered here."""
    if client == "goose":
        return {"event": "Stop", "session_id": "s", "last_assistant_message": "done"}
    if client == "grok":
        return {"hook_event_name": "Stop", "hookEventName": "stop", "sessionId": "s", "cwd": str(repo)}
    if client == "antigravity":
        body = {"executionNum": 1, "terminationReason": "model_stop", "error": "", "fullyIdle": True}
        return {**body, "conversationId": "c", "workspacePaths": [str(repo)]}
    return None


def has_stop(client: str) -> bool:
    """Whether `client`'s package runs anything at the turn's end (grok's records no blocking Stop)."""
    return gate_package.gate_reach(CLIENTS[client].agent)[1]


def rootless(client: str) -> bool:
    """Whether `client`'s hooks name the plugin folder by absolute path, the vendor documenting no root variable."""
    own = CLIENTS[client].own_layout
    return own is not None and hook_dir.layout(own)["plugin_root"] is None


#: Each runtime's own pre-tool deny, as its client reads it.
PRE_TOOL_DENIES = {
    "goose": lambda p: p.returncode == 0 and _decision(p) == "block",
    "antigravity": lambda p: p.returncode == 0 and _decision(p) == "deny",
}


def _decision(proc: Any) -> Any:
    try:
        body = json.loads(proc.stdout or "null")
    except ValueError:
        return None
    return body.get("decision") if isinstance(body, dict) else None


def bash_json(client: str, repo: Path, command: str) -> str | None:
    native = pre_tool(client, repo, "Bash", {"command": command})
    return None if native is None else json.dumps(native)


def write_resolved(folder: Path, files: dict[Path, str]) -> Path:
    """Write a package the way chock does, its root resolved to `folder` where the client names it by path."""
    for rel, content in hook_dir.resolve_root(files, folder).items():
        (folder / rel).parent.mkdir(parents=True, exist_ok=True)
        (folder / rel).write_text(content, encoding="utf-8")
    return folder


def skip_rootless(client: str) -> None:
    if rootless(client):
        pytest.skip(f"{client} names its folder by path: test_plugin_install_targets moves the folder instead")
