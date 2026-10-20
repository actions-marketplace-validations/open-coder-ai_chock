"""A gate pattern a backtracking engine can run in exponential time is refused before it reaches a gate."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from conftest import init_repo

from chock.gate.build import CatastrophicPatternError, build_gate_json
from chock.gate.pattern_safety import catastrophic
from chock.toggles import recompile_main
from chock.validation.checks_gate_shape import _validate_gate
from chock.validation.report import Report

REFUSED = {
    "nested plus": r"^(a+)+$",
    "optional separator": r"(\w+\s?)+$",
    "separator inside the class": r"(?:\.[\w.-]+)+",
    "nested star": r"(a*)*b",
    "bounded inner": r"(a{2,3})+$",
    "nested through a group": r"((a+)b?)+",
    "two inner repeats": r"(x+x+)+y",
    "overlapping branch in a loop": r"(?:a+|b)+$",
    "bounded outer": r"(a+){1,50}$",
    "classic email": r"([a-z]+\d*)*@",
}
ACCEPTED = {
    "separated repeats": r"(\d+\.){3}\d+",
    "fixed count": r"(?i)AKIA[0-9A-Z]{16}",
    "literal separator": r"(a+b)+",
    "literal lead": r"(ab+)+",
    "adjacent repeats": r"a+a+",
    "base64": r"(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==)?",
    "distinct separator": r"(\w+@)+",
    "optional inner": r"^(a?)+$",
    "lookahead-bounded whitespace": r"(?:\s+(?=[^\s#])|x)*",
    "end anchor in the loop": r"(?:[&!]\S*(?:\s+|$))*",
    "literal word after the repeat": r"(?:(?:[\w./-]*/)?sudo\s+)*",
    "alternation": r"(?:foo|bar)+",
}
#: Shapes the check does not see; the runtime deadline (chock.gate.budget) is their backstop.
MISSED = {"overlapping alternation": r"(a|aa)+", "separator the inner absorbs": r"(.*a)+"}


@pytest.mark.parametrize("name", sorted(REFUSED))
def test_a_nested_repeat_that_can_run_into_the_next_iteration_is_refused(name: str) -> None:
    assert catastrophic(REFUSED[name]), name


@pytest.mark.parametrize("name", sorted(ACCEPTED))
def test_a_pattern_whose_repeats_cannot_overlap_is_accepted(name: str) -> None:
    assert catastrophic(ACCEPTED[name]) is None, name


@pytest.mark.parametrize("name", sorted(MISSED))
def test_the_shapes_the_check_leaves_to_the_deadline_are_pinned(name: str) -> None:
    assert catastrophic(MISSED[name]) is None, name


def test_a_pattern_that_does_not_compile_is_not_this_checks_finding() -> None:
    assert catastrophic("(") is None


def test_every_installed_gate_pattern_is_accepted() -> None:
    """The check never fires on the patterns chock itself installs."""
    root = Path(__file__).resolve().parents[1]
    seen = 0
    for manifest in sorted((root / ".agents" / "policies").glob("*/manifest.yaml")):
        params = ((yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}).get("hook") or {}).get("gate") or {}
        for name, value in (params.get("params") or {}).items():
            if isinstance(value, str) and name.endswith(("_pattern", "_regex", "_pragma")):
                seen += 1
                assert catastrophic(value) is None, f"{manifest.parent.name}: {name}"
    assert seen


def _gate(**params: str) -> dict:
    return {"kind": "content_regex", "on": ["commit"], "action": "block", "message": "m", "params": params}


def test_validate_names_the_param_the_pattern_and_the_shape() -> None:
    report = Report()
    _validate_gate(_gate(content_pattern=r"^(a+)+$", allowlist_pragma="ok"), "test", report)
    messages = [f.message for f in report.errors]
    assert len(messages) == 1
    assert messages[0].startswith("content_pattern can take exponential time on a crafted line (a repeat nested")
    assert "'^(a+)+$'" in messages[0] and "both accept 'a'" in messages[0]


def test_validate_shows_a_long_pattern_cut_short() -> None:
    report = Report()
    _validate_gate(_gate(content_pattern="x" * 200 + r"(a+)+"), "test", report)
    assert "..." in report.errors[0].message and "x" * 200 not in report.errors[0].message


def _policy(root: Path, pattern: str) -> Path:
    policy = root / ".agents" / "policies" / "redos-gate"
    policy.mkdir(parents=True)
    manifest = {
        "id": "redos-gate",
        "name": "redos",
        "version": "0.0.1",
        "description": "d",
        "artifact": "hook",
        "enforcement": "block",
        "hook": {"gate": {"kind": "content_regex", "on": ["commit"], "params": {"content_pattern": pattern}}},
        "provenance": {"author": "t"},
        "lifecycle": {"status": "draft"},
    }
    (policy / "manifest.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")
    return policy


def test_the_compile_step_refuses_naming_policy_param_and_pattern(tmp_path: Path) -> None:
    policy = _policy(tmp_path, r"^(a+)+$")
    with pytest.raises(
        CatastrophicPatternError, match=r"redos-gate: hook\.gate\.params\.content_pattern .*'\^\(a\+\)\+\$'"
    ):
        build_gate_json(policy, tmp_path)
    assert build_gate_json(_policy(tmp_path / "ok", r"^a+$"), tmp_path / "ok") is not None


def test_sync_refuses_the_pattern_and_compiles_nothing(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = init_repo(tmp_path)
    _policy(repo, r"^(a+)+$")
    (repo / ".chock").mkdir()
    (repo / ".chock" / "config.yaml").write_text("agents: [claude]\n", encoding="utf-8")
    rc = recompile_main(["--repo", str(repo), "--skip-hooks"])
    err = capsys.readouterr().err
    assert rc == 1 and "redos-gate: hook.gate.params.content_pattern" in err and "nothing was compiled" in err
    assert not (repo / ".chock" / "compiled" / "redos-gate" / "git-hook" / "gate.json").exists()
