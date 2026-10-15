"""The repo stop (`chock stop`) at the gateway: the runtime's own check, once per root the gateway works in."""

from __future__ import annotations

import os
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname

from chock.gate.repo_stop import repo_stop_refusal
from chock.gate.runner.halt import HALT_POLICY, HALT_REASON
from chock.vendors import in_agent_vendors

STOP_POLICY = HALT_POLICY
STOP_ACTION = HALT_REASON
#: initialize params that name the folders the client works in (MCP `roots`, the LSP-style `workspaceFolders`).
_ROOT_KEYS = ("roots", "workspaceFolders")
_FILE_SCHEME = "file"
_SEPARATORS = re.compile(r"[^a-z0-9]+")


def stop_client(name: Any) -> str | None:
    """The chock client an MCP `clientInfo.name` is, as a stop scope reads it; None (every stop reaches it) otherwise.

    `claude-code` is `claude_code`; `codex-mcp-client` is `codex`, reached by a stop on `codex_cli`.
    """
    if not isinstance(name, str):
        return None
    words = _SEPARATORS.sub("_", name.lower()).strip("_")
    for vendor in in_agent_vendors():
        if words == vendor or words.startswith(vendor + "_"):
            return vendor
    first = words.split("_", 1)[0]
    return first if first and any(v.startswith(first + "_") for v in in_agent_vendors()) else None


def _root_path(entry: Any) -> str | None:
    """A root as a local path: a `file:` URI, a `{uri}` object, or a plain path; None for anything else."""
    text = entry.get("uri") if isinstance(entry, dict) else entry
    if not isinstance(text, str) or not text:
        return None
    parsed = urlparse(text)
    if parsed.scheme == _FILE_SCHEME:
        return url2pathname(unquote(parsed.path)) or None
    return text if not parsed.scheme or len(parsed.scheme) == 1 else None


def initialize_roots(params: Any) -> list[str]:
    """The folders an `initialize` names, in order; [] when it names none."""
    if not isinstance(params, dict):
        return []
    found = []
    for key in _ROOT_KEYS:
        entries = params.get(key)
        if isinstance(entries, list):
            found.extend(p for p in map(_root_path, entries) if p)
    return found


def stop_refusal(repo_root: Path | None, roots: list[str], client: str | None) -> str | None:
    """`stopped: <reason>` when a stop on any root the gateway works in reaches `client`, else None. Raises on fault."""
    candidates = dict.fromkeys(str(r) for r in (repo_root, os.getcwd(), *roots) if r is not None)
    for root in candidates:
        event = SimpleNamespace(event="pre_tool", agent=client, cwd=root, raw={}, path=None)
        refused = repo_stop_refusal(event)
        if refused is not None:
            return refused
    return None
