"""A gate pattern that does not compile is found at validate, not by the first commit it guards."""

from __future__ import annotations

from chock.validation.checks_gate_shape import _validate_gate
from chock.validation.report import Report


def _gate(**params: str) -> dict:
    return {"kind": "content_regex", "on": ["commit"], "action": "block", "message": "m", "params": params}


def test_an_unbalanced_pattern_is_an_error() -> None:
    report = Report()
    _validate_gate(_gate(content_pattern="(", forbidden_path_regex="[", allowlist_pragma="ok"), "test", report)
    messages = [f.message for f in report.errors]
    assert len(messages) == 2
    assert messages[0].startswith("content_pattern is not a valid regular expression")
    assert messages[1].startswith("forbidden_path_regex is not a valid regular expression")


def test_a_valid_pattern_is_silent() -> None:
    report = Report()
    _validate_gate(_gate(content_pattern=r"AKIA[A-Z0-9]{16}", allowlist_pragma="pragma: allow"), "test", report)
    assert report.errors == []
