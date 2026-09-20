"""A vendored runtime that cannot decide refuses; it never exits with a traceback.

The client reads a hook that crashes as a non-blocking error and runs the call. The judge
can raise for reasons the handler never anticipated; the wrap turns every one into a deny
that names the failure. Exercised on the rendered bundle, not on the template, so the
splice and the vendor dialect are under the same test.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from chock.gate import runtime_bundle
from chock.vendors import in_agent_vendors


def _load(agent: str) -> dict:
    namespace: dict = {"__name__": "chock_runtime_under_test"}
    exec(compile(runtime_bundle.render(agent), f"<{agent} bundle>", "exec"), namespace)  # noqa: S102 -- the rendered runtime is the unit under test
    return namespace


def _event(**overrides) -> SimpleNamespace:
    base = {"event": "pre_tool", "command": "ls", "tool": "Bash", "raw": {}, "path": None, "content": None}
    return SimpleNamespace(**{**base, **overrides})


@pytest.mark.parametrize("agent", in_agent_vendors())
def test_a_raise_inside_the_judge_becomes_a_deny_that_names_it(agent: str) -> None:
    ns = _load(agent)

    def _blow_up(*_args, **_kwargs):
        raise RuntimeError("guard table unreadable")

    ns["evaluate"] = _blow_up
    decision = ns["handle"](_event())
    assert decision is not None and decision.outcome == ns["DENY"], decision
    assert "RuntimeError: guard table unreadable" in decision.reason
    assert "never established" in decision.reason


@pytest.mark.parametrize("agent", in_agent_vendors())
def test_the_gate_path_is_wrapped_too(agent: str) -> None:
    """The write path and stop reach the judge through evaluate_gate; a raise there is the same."""
    ns = _load(agent)

    def _blow_up(*_args, **_kwargs):
        raise ValueError("gate spec is not a mapping")

    ns["evaluate_gate"] = _blow_up
    decision = ns["handle"](_event(event="stop", command=None, tool=None))
    assert decision is not None and decision.outcome == ns["DENY"]
    assert "ValueError: gate spec is not a mapping" in decision.reason


def test_a_clean_call_is_still_untouched() -> None:
    """The mandate: the wrap must not turn a correct allow into anything else."""
    ns = _load("claude_code")
    ns["evaluate"] = lambda *_a, **_k: None
    ns["evaluate_gate"] = lambda *_a, **_k: None
    assert ns["handle"](_event()) is None
