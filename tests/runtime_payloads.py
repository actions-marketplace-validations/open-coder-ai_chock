"""One shell pre-tool payload per vendored runtime, and the deny word each one's wire carries."""

from __future__ import annotations

PAYLOADS = {
    "claude_code": lambda c: {
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": c},
        "session_id": "s",
        "transcript_path": "/t",
        "permission_mode": "default",
    },
    "vscode_copilot": lambda c: {
        "hook_event_name": "PreToolUse",
        "timestamp": "2026-08-31T00:00:00Z",
        "tool_name": "Bash",
        "tool_input": {"command": c},
        "tool_use_id": "1",
    },
    "cursor": lambda c: {
        "hook_event_name": "beforeShellExecution",
        "conversation_id": "a",
        "generation_id": "b",
        "cursor_version": "3.17.8",
        "workspace_roots": ["/x"],
        "command": c,
        "cwd": "/x",
        "sandbox": False,
    },
    "codex_cli": lambda c: {
        "hook_event_name": "PreToolUse",
        "turn_id": "t1",
        "tool_name": "Bash",
        "tool_input": {"command": c},
    },
    "antigravity": lambda c: {
        "toolCall": {"name": "run_command", "args": {"CommandLine": c, "Cwd": "/x"}},
        "conversationId": "c1",
        "stepIdx": 1,
        "workspacePaths": ["/x"],
    },
    "devin": lambda c: {
        "hook_event_name": "PreToolUse",
        "prompt_id": "p1",
        "tool_name": "Bash",
        "tool_input": {"command": c},
        "session_id": "s",
    },
    "gemini_cli": lambda c: {
        "hook_event_name": "BeforeTool",
        "tool_name": "run_shell_command",
        "tool_input": {"command": c},
        "session_id": "s",
    },
    "grok": lambda c: {
        "hookEventName": "PreToolUse",
        "toolName": "Bash",
        "toolInput": {"command": c},
        "sessionId": "s",
    },
    "tabnine": lambda c: {
        "hook_event_name": "BeforeTool",
        "timestamp": "2026-08-31T00:00:00Z",
        "tool_name": "shell",
        "tool_input": {"command": c},
    },
    "windsurf": lambda c: {
        "trajectory_id": "t1",
        "tool_info": {"command_line": c},
        "cwd": "/x",
    },
    # The next four: agentseam's golden pre_tool payloads (tests/fixtures/golden at bebbfa6), shell tool.
    "factory_droid": lambda c: {
        "hook_event_name": "PreToolUse",
        "permission_mode": "auto-medium",
        "session_id": "s",
        "transcript_path": "/x/.factory/projects/x/session.jsonl",
        "cwd": "/x",
        "tool_name": "Execute",
        "tool_input": {"command": c},
    },
    "goose": lambda c: {
        "event": "PreToolUse",
        "matcher_context": "shell",
        "session_id": "s",
        "tool_call_id": "call-1",
        "tool_name": "shell",
        "tool_input": {"command": c},
        "working_dir": "/x",
    },
    "openhands": lambda c: {
        "event_type": "PreToolUse",
        "session_id": "s",
        "tool_name": "terminal",
        "tool_input": {"command": c},
        "working_dir": "/x",
    },
    "mistral_vibe": lambda c: {
        "hook_event_name": "pre_tool",
        "parent_session_id": None,
        "session_id": "s",
        "tool_call_id": "call-1",
        "tool_name": "bash",
        "tool_input": {"command": c},
        "transcript_path": "/x/.vibe/session.jsonl",
        "cwd": "/x",
    },
}

#: The deny each vendor's wire actually carries, witnessed by the deny-guard fixture below:
#: `block` is the devin-family spelling, `exit-2` windsurf's wordless exit-code grammar (G5).
DENY_ON_THE_WIRE = {
    "claude_code": "deny",
    "codex_cli": "deny",
    "cursor": "deny",
    "vscode_copilot": "deny",
    "antigravity": "deny",
    "devin": "block",
    "gemini_cli": "deny",
    "grok": "deny",
    "tabnine": "deny",
    "windsurf": "exit-2",
    "factory_droid": "deny",
    "goose": "block",
    "openhands": "deny",
    "mistral_vibe": "deny",
}
