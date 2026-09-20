"""`sync` wires in-agent hooks for the agents the repo names, not for every vendor chock knows."""

from __future__ import annotations

import shutil
from pathlib import Path

from conftest import baseline_policy, init_repo

from chock.hooks.in_agent_install import WIRED_VENDORS
from chock.scaffold.recompile import recompile, wired_vendors
from chock.vendors import CHOCK_AGENT


def _repo(tmp_path: Path) -> Path:
    repo = init_repo(tmp_path)
    shutil.copytree(
        baseline_policy("block-destructive-commands"), repo / ".agents" / "policies" / "block-destructive-commands"
    )
    return repo


def test_every_wired_vendor_is_chosen_when_every_agent_is() -> None:
    assert wired_vendors(sorted(CHOCK_AGENT)) == WIRED_VENDORS


def test_one_agent_chooses_one_vendor() -> None:
    assert wired_vendors(["claude"]) == ("claude_code",)
    assert wired_vendors(["cursor", "claude"]) == tuple(v for v in WIRED_VENDORS if v in {"claude_code", "cursor"})


def test_a_claude_only_repo_gets_no_other_vendors_config(tmp_path: Path) -> None:
    """`chock init --agents claude` followed by `sync` used to write ten vendors' hook files."""
    repo = _repo(tmp_path)
    recompile(repo, ["claude"], skip_hooks=False)

    assert (repo / ".claude" / "settings.json").exists()
    assert (repo / ".chock" / "bin" / "claude_code.py").exists()
    for stray in (".cursor", ".codex", ".windsurf", ".devin", ".gemini", ".github/hooks", ".agents/hooks.json"):
        assert not (repo / stray).exists(), stray
    runtimes = sorted(p.name for p in (repo / ".chock" / "bin").iterdir() if p.name != "gate.py")
    assert runtimes == ["claude_code.py"], "no other vendor's runtime is vendored either"


def test_a_cursor_only_repo_gets_no_claude_settings(tmp_path: Path) -> None:
    """The SessionStart arm hook lives in .claude/settings.json; it is only wired for a repo that names claude."""
    repo = _repo(tmp_path)
    recompile(repo, ["cursor"], skip_hooks=False)

    assert (repo / ".cursor" / "hooks.json").exists()
    assert not (repo / ".claude" / "settings.json").exists()
