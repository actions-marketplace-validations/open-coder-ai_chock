"""The two `content_regex` evaluators judge the same text the same way at tool-use.

chock#145 found `gate/runner.py` honouring the per-line waiver at every event while the
mcp-gateway evaluator never read it -- and the published message said the gateway was right.
Nothing had asked the two the same question. This asks it: one fixture, both evaluators,
one verdict per case at each agent event.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import init_repo, write_gate

from chock.gate.runner import AGENT_EVENTS, run
from chock.gateway import gates as gateway_gates

PATTERN = r"(?i)AKIA[0-9A-Z]{16}"
PRAGMA = r"#\s*pragma:\s*allowlist\s+secret"
KEY = "AKIAIOSFODNN7EXAMPLE"  # pragma: allowlist secret -- AWS's own published example key

CASES = {
    "clean": ("KEY = os.environ['KEY']\n", False),
    "secret": (f'KEY = "{KEY}"\n', True),
    "secret with the waiver on its line": (f'KEY = "{KEY}"  # pragma: allowlist secret\n', True),
    "secret on the second line": (f'x = 1\nKEY = "{KEY}"\n', True),
    "waiver on a clean line": ("x = 1  # pragma: allowlist secret\n", False),
}

PARAMS = {"scan": "added_lines", "allowlist_pragma": PRAGMA, "content_pattern": PATTERN}


def _gateway_blocks(text: str) -> bool:
    spec = {"kind": "content_regex", "params": PARAMS, "message": "secret", "policy_id": "p"}
    return gateway_gates.evaluate([spec], "write_file", {"content": text}) is not None


def _runner_blocks(tmp_path: Path, event: str, text: str) -> bool:
    spec = {
        "kind": "content_regex",
        "on": ["commit", "tool_use"],
        "action": "block",
        "message": "secret",
        "params": PARAMS,
    }
    return run(write_gate(tmp_path, spec), event, None, tmp_path, writes={"app.py": text}) == 1


@pytest.mark.parametrize("event", AGENT_EVENTS)
@pytest.mark.parametrize("name", sorted(CASES))
def test_both_evaluators_reach_the_same_verdict(tmp_path: Path, event: str, name: str) -> None:
    text, expected = CASES[name]
    init_repo(tmp_path)
    assert _gateway_blocks(text) is expected, f"gateway on {name!r}"
    assert _runner_blocks(tmp_path, event, text) is expected, f"runner at {event} on {name!r}"


def test_the_waiver_is_the_one_case_the_two_could_disagree_on() -> None:
    """Pinned so the fixture cannot be trimmed to the cases that were never in doubt."""
    assert any("waiver" in name for name in CASES)
