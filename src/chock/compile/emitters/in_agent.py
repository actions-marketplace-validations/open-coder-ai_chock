"""The one in-agent emitter: hook fragments for every wired vendor, wire facts from vendor config."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

from chock import vendors
from chock.compile.emitters import DATA_DIR, GUARD_SUFFIXES, policy_rel_path
from chock.emit import write_generated_json

_BASH_TEMPLATE = DATA_DIR.joinpath("agent_hook_bash.sh").read_text(encoding="utf-8").rstrip("\n")
_POWERSHELL_TEMPLATE = DATA_DIR.joinpath("agent_hook_powershell.ps1").read_text(encoding="utf-8").rstrip("\n")

GUARD_SCRIPTS = {
    "block-destructive-commands": "block-destructive.sh",
    "block-no-verify": "block-no-verify.sh",
}


def _guard_script(policy_dir: Path, policy_id: str) -> str | None:
    """The policy's guard script name, by convention first, legacy map second."""
    impl = policy_dir / "implementations"
    for suffix in GUARD_SUFFIXES:
        if (impl / f"{policy_id}{suffix}").exists():
            return f"{policy_id}{suffix}"
    legacy = GUARD_SCRIPTS.get(policy_id)
    if legacy and (impl / legacy).exists():
        return legacy
    return None


TIMEOUT_SECONDS = 30

#: claude_code's own recorded shell vocabulary, used for its claude-plugin hooks file.
MATCHER = vendors.shell_matcher("claude_code")
assert MATCHER is not None  # noqa: S101 -- import-time upstream-data invariant, not request handling

#: Wire token Claude Code substitutes for the repo root, read from agentseam's vendor
#: config (`repo_root_token`) instead of chock's own hardcoded copy.
PROJECT_DIR_TOKEN = vendors.repo_root_token("claude_code")
assert PROJECT_DIR_TOKEN is not None  # noqa: S101 -- import-time upstream-data invariant, not request handling

# Witnessed overrides: chock's agent-hooks file speaks `preToolUse` with bash/powershell/
# timeoutSec entry keys (live deny, data/witnesses.json: vscode_copilot x agent-hooks);
# agentseam 0.2.0 records `PreToolUse` with {type, command, windows} instead. The facts
# stay here until upstream ingests the witnessed shape; tests/test_vendor_wire_facts.py
# pins the disagreement so its resolution surfaces loudly.
AGENT_HOOKS_EVENT = "preToolUse"
AGENT_HOOKS_ENVELOPE = {"version": 1}
SHELL_MATCHER = "bash|powershell|pwsh|sh|shell"

#: The content fragment claude_code's installer merges, named apart from the shell one so a
#: policy could one day carry both without either overwriting the other.
WRITE_FRAGMENT = "pretooluse-write.json"


def _adapter_rel(vendor: str) -> str:
    """Where the vendored runtime lives in a consumer repo: chock's convention + agent id."""
    return f".chock/bin/{vendor}.py"


def _compiled_rel(policy_id: str) -> str:
    """Where this policy's pre-tool-use artifacts land, from chock's own compiled layout."""
    return f".chock/compiled/{policy_id}/pre-tool-use"


#: Vendors wired through hand-shaped fragments that predate the derivation (claude/cursor
#: entry shapes, the witnessed agent-hooks override). Everyone else the membership
#: predicate admits renders through agentseam's own hook_config -- no per-vendor emitter.
BESPOKE_VENDORS = ("claude_code", "cursor", "vscode_copilot")

GENERIC_VENDORS = tuple(v for v in vendors.in_agent_vendors() if v not in BESPOKE_VENDORS)


def generic_hooks_file(vendor: str, command: str) -> dict[str, Any]:
    """`vendor`'s full hook-config document for one guard command, agentseam's rendering.

    Paths inside `command` are repo-relative: no repo-root token is recorded upstream for
    these vendors (the `${CLAUDE_PROJECT_DIR}` gap), so the entry resolves only where the
    vendor runs hooks from the repo root -- the same condition under which the relative
    adapter path resolves at all.
    """
    return vendors.pre_tool_hook_config(vendor, command, matcher=vendors.shell_matcher(vendor))


def hook_entry(command: str, *, matcher: str | None = None) -> dict[str, Any]:
    """One hooks-map entry (agentseam's `hooks_map` wrapper shape) plus chock's timeout."""
    entry: dict[str, Any] = {}
    if matcher is not None:
        entry["matcher"] = matcher
    entry["hooks"] = [{"type": "command", "command": command, "timeout": TIMEOUT_SECONDS}]
    return entry


def hooks_map_file(vendor: str, command: str) -> dict[str, Any]:
    """A claude-plugin-format hooks file under `vendor`'s own pre-tool event spelling."""
    matcher = vendors.shell_matcher(vendor)
    return {"hooks": {vendors.pre_tool_event(vendor): [hook_entry(command, matcher=matcher)]}}


def cursor_entry(command: str) -> dict[str, Any]:
    """One cursor hook entry: the flat `cursor` wrapper shape plus chock's timeout."""
    return {"command": command, "timeout": TIMEOUT_SECONDS}


def cursor_hooks_file(command: str) -> dict[str, Any]:
    """A cursor-format hooks file: envelope and shell-gate event from the vendor entry."""
    return {
        **vendors.config_envelope("cursor"),
        "hooks": {vendors.shell_gate_event("cursor"): [cursor_entry(command)]},
    }


GATE_FILE = "gate.json"

#: A gate reaches this surface only when the policy asked for this event by name.
TOOL_USE = "tool_use"


def _tool_use_gate(policy_dir: Path, output_dir: Path) -> dict[str, Any] | None:
    """The compiled gate this policy wants run at tool use, or None when it wants none.

    Three ways to want none, each the policy's own statement rather than a judgement made
    here: no declarative gate at all, tool_use not among its declared events, or a kind
    asking a question a write cannot answer. The runner refuses that last case anyway, so
    emitting a hook certain to refuse would be installing noise.
    """
    # Deferred: chock.compile.surfaces imports this module, and the gate builder reaches
    # chock.config which imports surfaces back. Module-level here closes that cycle.
    from chock.compile.emitters.advisory import repo_root_from_output  # noqa: PLC0415
    from chock.gate.build import build_gate_json  # noqa: PLC0415
    from chock.gate.runner import WRITE_PATH_KINDS  # noqa: PLC0415

    spec = build_gate_json(policy_dir, repo_root_from_output(output_dir))
    if spec is None or TOOL_USE not in spec.get("on", []):
        return None
    return spec if spec.get("kind") in WRITE_PATH_KINDS else None


def _guard_fragments(policy_dir: Path, script: str, output_dir: Path) -> list[Path]:
    """The shell-command fragments, one per wired vendor. Behaviour unchanged."""
    rel = policy_rel_path(policy_dir)
    guard = f"{PROJECT_DIR_TOKEN}/{rel}/implementations/{script}"
    written: list[Path] = []
    for vendor, name, build in (
        ("claude_code", "pretooluse.json", lambda cmd: hook_entry(cmd, matcher=MATCHER)),
        ("cursor", "cursor-hooks.json", lambda cmd: {vendors.shell_gate_event("cursor"): [cursor_entry(cmd)]}),
    ):
        adapter = f"{PROJECT_DIR_TOKEN}/{_adapter_rel(vendor)}"
        command = f'@CHOCK_PYTHON@ "{adapter}" --guard "{guard}"'
        dest = output_dir / name
        write_generated_json(dest, build(command))
        written.append(dest)
    for vendor in GENERIC_VENDORS:
        command = f'@CHOCK_PYTHON@ "{_adapter_rel(vendor)}" --guard "{rel}/implementations/{script}"'
        dest = output_dir / f"{vendor}-hooks.json"
        write_generated_json(dest, generic_hooks_file(vendor, command))
        written.append(dest)
    return written


def _gate_fragments(policy_id: str, spec: dict[str, Any], output_dir: Path) -> list[Path]:
    """The content fragments, for the vendors whose write vocabulary is actually recorded.

    Most vendors record no `tools.write`, and a pre-tool hook needs a matcher. Inventing one
    would gate a tool name nobody verified the vendor uses, so those vendors get no fragment
    and the coverage they are credited with stays exactly what it was.
    """
    gate = output_dir / GATE_FILE
    write_generated_json(gate, spec)
    written: list[Path] = [gate]

    reference = f"{PROJECT_DIR_TOKEN}/{_compiled_rel(policy_id)}/{GATE_FILE}"
    for vendor in sorted(vendors.in_agent_vendors()):
        matcher = vendors.write_matcher(vendor)
        if matcher is None:
            continue
        adapter = f"{PROJECT_DIR_TOKEN}/{_adapter_rel(vendor)}"
        command = f'@CHOCK_PYTHON@ "{adapter}" --gate "{reference}"'
        name = WRITE_FRAGMENT if vendor == "claude_code" else f"{vendor}-write-hooks.json"
        dest = output_dir / name
        write_generated_json(dest, hook_entry(command, matcher=matcher))
        written.append(dest)
    return written


def emit_pre_tool_use(policy_dir: Path, output_dir: Path, manifest: dict[str, Any]) -> list[Path]:
    """Write the pre-tool-use fragments: a shell guard's, a content gate's, or neither."""
    policy_id = manifest.get("id", policy_dir.name)
    script = _guard_script(policy_dir, policy_id)
    spec = None if script else _tool_use_gate(policy_dir, output_dir)
    if not script and spec is None:
        return []

    output_dir.mkdir(parents=True, exist_ok=True)
    if script:
        return _guard_fragments(policy_dir, script, output_dir)
    return _gate_fragments(str(policy_id), spec or {}, output_dir)


def _bash_command(adapter: str, guard: str) -> str:
    return _BASH_TEMPLATE.replace("__ADAPTER__", adapter).replace("__GUARD__", guard)


def _powershell_command(adapter: str, guard: str) -> str:
    return _POWERSHELL_TEMPLATE.replace("__ADAPTER__", adapter).replace("__GUARD__", guard)


def build_entry(policy_dir: Path, manifest: dict[str, Any]) -> dict[str, Any] | None:
    """The single agent-hooks entry for one policy, or None when it has no guard script."""
    policy_id = manifest.get("id", policy_dir.name)
    script = _guard_script(policy_dir, policy_id)
    if not script:
        return None
    rel = policy_rel_path(policy_dir)
    adapter = _adapter_rel("vscode_copilot")
    guard = f"{rel}/implementations/{script}"
    bash = _bash_command(adapter, guard)
    powershell = _powershell_command(adapter, guard)
    return {
        "type": "command",
        "matcher": SHELL_MATCHER,
        "timeout": TIMEOUT_SECONDS,
        "timeoutSec": TIMEOUT_SECONDS,
        "bash": bash,
        "command": bash,
        "powershell": powershell,
        "windows": powershell,
    }


def emit_agent_hooks(policy_dir: Path, output_dir: Path, manifest: dict[str, Any]) -> list[Path]:
    """Write the per-policy entry; the installer aggregates them into .github/hooks/chock.json."""
    entry = build_entry(policy_dir, manifest)
    if entry is None:
        return []
    output_dir.mkdir(parents=True, exist_ok=True)
    dest = output_dir / "agent-hooks.json"
    write_generated_json(dest, entry)
    return [dest]


pre_tool_use = SimpleNamespace(emit=emit_pre_tool_use)
agent_hooks = SimpleNamespace(emit=emit_agent_hooks)
