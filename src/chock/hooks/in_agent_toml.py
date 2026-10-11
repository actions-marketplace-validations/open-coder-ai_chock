"""TOML in-agent install (mistral_vibe): chock's rules as one owned block in the vendor's own file."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agentseam import adapters
from agentseam.install_config import ConfigUnreadableError, block_bounds, read_text, remove_block, write_block

from chock import vendors

#: The block owner: `# >>> agentseam >>> chock` ... `# <<< agentseam <<< chock`, beside any other owner's.
OWNER = "chock"


def _read(path: Path) -> str:
    """The file's text; one that is not readable text is refused, never overwritten."""
    try:
        return str(read_text(str(path)))
    except (OSError, ConfigUnreadableError):
        msg = f"{path} is not readable text; leaving it untouched"
        raise ValueError(msg) from None


def _rules(fragment: Any) -> list[dict[str, Any]]:
    return [rule for rule in fragment if isinstance(rule, dict)] if isinstance(fragment, list) else []


def _render(vendor: str, rules: list[dict[str, Any]]) -> str:
    return str(adapters.get(vendor).render_config(rules))


def _owned_block(path: Path) -> str:
    """Our block's text in `path`, or "" where the file or the block is absent."""
    if not path.is_file():
        return ""
    text = _read(path)
    bounds = block_bounds(text, OWNER)
    return text[bounds[0] : bounds[1]] if bounds else ""


def install_toml(repo_root: Path, vendor: str, fragments: list[tuple[str, Any]]) -> list[str]:
    """Write every fragment's rules as our one block; with none, remove the block (and a file left empty)."""
    path = Path(repo_root) / vendors.config_path(vendor)
    rules = [rule for _policy_id, fragment in fragments for rule in _rules(fragment)]
    if not rules:
        if _owned_block(path):
            remove_block(str(path), OWNER)
            if not _read(path).strip():
                path.unlink()
        return []
    if path.exists():
        _read(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_block(str(path), _render(vendor, rules), OWNER)
    return [policy_id for policy_id, fragment in fragments if _rules(fragment)]


def installed_toml_ids(repo_root: Path, vendor: str, fragments: list[tuple[str, Any]]) -> set[str]:
    """Policy ids whose every rule is rendered inside our block."""
    try:
        block = _owned_block(Path(repo_root) / vendors.config_path(vendor))
    except ValueError:
        return set()
    return {
        policy_id
        for policy_id, fragment in fragments
        if _rules(fragment) and all(_render(vendor, [rule]).strip() in block for rule in _rules(fragment))
    }
