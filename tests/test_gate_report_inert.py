"""The gate runtime's printed refusal, workflow commands and step summary are inert: no escape sequence,
control, bidi or invisible character a finding carries reaches a terminal or a CI log raw."""

from __future__ import annotations

import os
import subprocess
import sys
import unicodedata
from pathlib import Path

import pytest
from conftest import init_repo, stage
from test_github_annotations import _ci, _commands, _finding, _repo

from chock.gate.runner.context import GateResult
from chock.gate.runner.report import (
    _annotation,
    _reason,
    _report_refusal,
    _step_summary,
    _workflow_command,
    inert,
)

POLICY = "demo-policy"
#: CSI, OSC 8 hyperlink, OSC 52 clipboard write, BEL, bidi override and isolate, ZWSP, BOM, tag, U+2028,
#: C1 CSI, a forged newline and a lone surrogate.
PAYLOAD = (
    "ok\x1b[2J\x1b]8;;https://evil.example\x1b\\link\x1b]8;;\x1b\\\x1b]52;c;ZXZpbA==\x07\x07"
    "\u202e\u2066\u200b\ufeff\U000e0041\u2028\x9b31m\nFORGED allow\ud800"
)
#: What no printed line may hold: every unsafe character class in the payload.
RAW = ("\x1b", "\x07", "\x9b", "\u202e", "\u2066", "\u200b", "\ufeff", "\U000e0041", "\u2028", "\ud800")


def _unsafe(text: str) -> list[str]:
    return [ch for ch in text if ch in RAW or (ch not in "\n" and unicodedata.category(ch) in {"Cc", "Cs", "Cf"})]


def _no_forged_line(text: str) -> None:
    assert not [line for line in text.splitlines() if line.lstrip("> ").startswith(("FORGED", "::error::x"))]


def test_inert_escapes_the_payload_visibly() -> None:
    shown = inert(PAYLOAD)
    assert _unsafe(shown) == []
    assert "\\x1b[2J" in shown
    assert "\\x07" in shown
    assert "\\u202e" in shown
    assert "\\nFORGED" in shown
    assert shown.endswith("\\ud800")


def test_inert_keeps_zwnj_zwj_and_other_scripts() -> None:
    text = "\u0645\u06cc\u200c\u062e\u0648\u0627\u0647\u0645 \U0001f468\u200d\U0001f4bb 設定"
    assert inert(text) == text


def test_the_commit_refusal_is_inert(capsys: pytest.CaptureFixture) -> None:
    message = "blocked " + PAYLOAD.replace("\n", " ")
    result = GateResult(allowed=False, message=message, matches=[f"src/{PAYLOAD}.py: content pattern"])
    _report_refusal(result, {}, "commit", None, POLICY)
    err = capsys.readouterr().err
    assert _unsafe(err) == []
    _no_forged_line(err)


def test_a_findings_refusal_is_inert(capsys: pytest.CaptureFixture) -> None:
    result = GateResult(
        allowed=False, matches=[f"src/a.py:1: {PAYLOAD}"], detail={"new_findings": 1, "baseline_findings": 0}
    )
    _report_refusal(result, {"message": "m"}, "commit", None, POLICY)
    err = capsys.readouterr().err
    assert _unsafe(err) == []
    _no_forged_line(err)


def test_a_multi_line_policy_message_keeps_its_lines() -> None:
    result = GateResult(allowed=False, message="first\x1b[1m\r\nsecond\u202e")
    assert _reason(result, {}, "commit", POLICY) == "first\\x1b[1m\nsecond\\u202e"


def test_an_error_workflow_command_is_inert() -> None:
    item = _finding(1, path=f"src/{PAYLOAD}.py", rule=f"r{PAYLOAD}", message=PAYLOAD)
    line = _workflow_command("error", item, POLICY, Path.cwd())
    assert _unsafe(line) == []
    assert "\n" not in line
    assert "\\x1b[2J" in line
    assert "%0AFORGED allow\\ud800" in line


def test_a_warning_annotation_is_inert() -> None:
    line = _annotation(f"p{PAYLOAD}", f"reason {PAYLOAD}")
    assert _unsafe(line) == []
    assert "\n" not in line
    assert line.startswith("::warning title=chock p")


def test_the_step_summary_is_inert() -> None:
    item = _finding(1, path=PAYLOAD, rule=PAYLOAD, message=PAYLOAD)
    result = GateResult(allowed=False, detail={"new_findings": 1, "baseline_findings": 0})
    text = _step_summary(result, PAYLOAD, "block", [item])
    assert _unsafe(text.replace("\n", "")) == []
    _no_forged_line(text)


def test_ci_output_is_inert_end_to_end(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    repo, gate = _repo(tmp_path, [_finding(1, message=PAYLOAD)])
    summary = tmp_path / "summary.md"
    assert _ci(gate, repo, monkeypatch, actions="true", summary=summary) == (1, "block")
    captured = capsys.readouterr()
    for text in (captured.out, captured.err, summary.read_text(encoding="utf-8")):
        assert _unsafe(text) == []
        _no_forged_line(text)
    assert len(_commands(captured.out)) == 1


def test_the_vendored_runtime_prints_an_inert_refusal(tmp_path: Path, gate_py: Path) -> None:
    repo = init_repo(tmp_path)
    name = "a\u202egnp.\u2066\u200b\ufeffb.md"
    stage(repo, name, "BAD\n")
    spec = tmp_path / "gate.json"
    spec.write_text(
        '{"kind": "content_regex", "on": ["commit"], "action": "block", "message": "blocked",'
        ' "params": {"scan": "added_lines", "content_pattern": "BAD"}}',
        encoding="utf-8",
    )
    proc = subprocess.run(
        [sys.executable, str(gate_py), "run", "--gate", str(spec), "--event", "pre-commit"],
        cwd=repo,
        capture_output=True,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        check=False,
    )
    err = proc.stderr.decode("utf-8")
    assert proc.returncode == 1
    assert "a\\u202egnp.\\u2066\\u200b\\ufeffb.md: content pattern" in err
    assert _unsafe(err) == []
    _no_forged_line(err)


def test_the_vendored_rule_matches_chock_display() -> None:
    display = pytest.importorskip("chock.display")
    for text in (PAYLOAD, "plain", "\u200c\u200d", "\t\r\n", "\U000e007f\u061c\u00ad"):
        assert inert(text).encode("utf-8", "surrogatepass") == display.inert(text).encode("utf-8", "surrogatepass")
