"""MISFIRE-1: the optimize skill reads decision-log lines and witness exports as traces, misfires grouped per policy."""

from __future__ import annotations

import ast
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

from chock.witness_export import bundle

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "src" / "chock" / "packs" / "_skills" / "optimize" / "scripts" / "traces.py"
FIXTURES = Path(__file__).parent / "fixtures" / "optimize_traces"
LOG, WITNESS, STOPPED, MALFORMED = (FIXTURES / n for n in ("decision-log.jsonl", "witness-export.json", "stopped.jsonl", "malformed.jsonl"))  # fmt: skip
PERSON = "person@example.invalid"

_spec = importlib.util.spec_from_file_location("optimize_traces", SCRIPT)
assert _spec and _spec.loader
traces = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(traces)


def _run(capsys: pytest.CaptureFixture[str], *paths: Path) -> tuple[int, Any, str]:
    code = traces.main([str(p) for p in paths])
    out, err = capsys.readouterr()
    return code, json.loads(out) if out else None, err


def _policy(report: dict[str, Any], policy_id: str) -> dict[str, Any]:
    return next(p for p in report["policies"] if p["policy_id"] == policy_id)


def _candidates(report: dict[str, Any]) -> dict[str, list[tuple[str, str]]]:
    return {p["policy_id"]: [(c["trace"], c["overridden_by"]) for c in p["misfire_candidates"]] for p in report["policies"]}  # fmt: skip


def _records(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_a_decision_log_groups_overridden_refusals_per_policy(capsys: pytest.CaptureFixture[str]) -> None:
    code, report, err = _run(capsys, LOG)
    assert (code, err) == (0, "")
    assert report["inputs"] == [{"file": LOG.name, "kind": "decision-log", "records": 21}]
    assert _candidates(report) == {
        "ask-bad": [
            ("decision-log.jsonl:9", "decision-log.jsonl:11"),
            ("decision-log.jsonl:13", "decision-log.jsonl:14"),
        ],
        "word-check": [("decision-log.jsonl:10", "decision-log.jsonl:12")],
        "protect-agent-config": [],
        "scan-secrets": [],
    }
    assert [report["policies"][0]["policy_id"], _policy(report, "ask-bad")["refusals"]] == ["ask-bad", 3]
    pac = _policy(report, "protect-agent-config")
    assert (pac["refusals"], pac["faults"], pac["overrides"]) == (2, 1, 0)
    assert (_policy(report, "word-check")["observed"], _policy(report, "scan-secrets")["warns"]) == (1, 1)


def test_a_plain_allow_is_never_a_policys(capsys: pytest.CaptureFixture[str]) -> None:
    _, report, _ = _run(capsys, LOG)
    assert (report["allowed_calls"], report["sessions"], report["unattributed"]) == (2, 2, 0)
    per_policy = sum(p[k] for p in report["policies"] for k in ("refusals", "warns", "faults", "observed", "overrides"))
    assert per_policy == 21 - 2 - 2 - report["stops"]


def test_debugs_per_hook_allow_counts_for_no_policy(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    line = {"ts": "t", "verdict": "allow", "reason": "no-rule", "target": "src/a.py", "policy_id": "p"}
    (tmp_path / "debug.jsonl").write_text(json.dumps(line) + "\n", encoding="utf-8")
    _, report, _ = _run(capsys, tmp_path / "debug.jsonl")
    assert (report["allowed_calls"], report["policies"]) == (0, [])


def test_no_person_is_named_in_the_output(capsys: pytest.CaptureFixture[str]) -> None:
    assert PERSON in LOG.read_text(encoding="utf-8")
    assert traces.main([str(LOG)]) == 0
    assert PERSON not in capsys.readouterr().out


def test_stop_records_are_never_a_policy_misfire(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    override = next(r for r in _records(LOG) if r.get("override") and r["policy_id"] == "ask-bad")
    log = tmp_path / "after-stop.jsonl"
    log.write_text(STOPPED.read_text(encoding="utf-8") + json.dumps({**override, "ts": "2026-10-13T12:00:00Z"}) + "\n")
    code, report, _ = _run(capsys, log)
    assert (code, report["stops"], report["allowed_calls"]) == (0, 5, 2)
    assert [(p["policy_id"], p["refusals"], p["overrides"], p["misfire_candidates"]) for p in report["policies"]] == [
        ("ask-bad", 0, 1, [])
    ]


def test_a_witness_export_is_read_as_traces(capsys: pytest.CaptureFixture[str]) -> None:
    code, report, _ = _run(capsys, WITNESS)
    assert code == 0
    assert report["inputs"] == [{"file": WITNESS.name, "kind": "witness-export", "records": 6}]
    assert (report["allowed_calls"], report["sessions"], report["stops"]) == (2, 1, 0)
    pac = _policy(report, "protect-agent-config")
    assert (pac["refusals"], pac["faults"], pac["misfire_candidates"]) == (2, 1, [])
    assert [p["policy_id"] for p in report["policies"]] == ["protect-agent-config"]


def test_an_export_keeps_the_override_pairs_without_the_approver(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:  # fmt: skip
    doc = bundle("claude_code", _records(LOG), tmp_path, None)
    exported = tmp_path / "export.json"
    exported.write_text(json.dumps(doc), encoding="utf-8")
    assert PERSON not in exported.read_text(encoding="utf-8")
    _, from_log, _ = _run(capsys, LOG)
    _, from_export, _ = _run(capsys, exported)
    assert {k: len(v) for k, v in _candidates(from_export).items()} == {
        k: len(v) for k, v in _candidates(from_log).items()
    }
    assert _candidates(from_export)["word-check"] == [("export.json#9", "export.json#11")]


def test_inputs_combine(capsys: pytest.CaptureFixture[str]) -> None:
    _, report, _ = _run(capsys, LOG, WITNESS)
    assert [i["kind"] for i in report["inputs"]] == ["decision-log", "witness-export"]
    assert _policy(report, "protect-agent-config")["refusals"] == 4


def test_the_malformed_fixture_is_refused_by_line(capsys: pytest.CaptureFixture[str]) -> None:
    code, report, err = _run(capsys, LOG, MALFORMED)
    assert (code, report) == (2, None)
    assert err == f"optimize traces: {MALFORMED.name}:2: not valid JSON (want one decision record per line). Nothing was read as evidence.\n"  # fmt: skip


_EXPORT = {"format": "chock-witness-export/1", "records": []}
BAD = {
    "array.json": ("[1, 2]", "a JSON list is neither"),
    "text.jsonl": ("hello\n", "{name}:1: not valid JSON"),
    "null.json": ("null", "a JSON NoneType is neither"),
    "format.json": (json.dumps({**_EXPORT, "format": "chock-witness-export/9"}), "unsupported export format"),
    "records.json": (json.dumps({**_EXPORT, "records": {}}), "`records` must be a list"),
    "record.json": (json.dumps({**_EXPORT, "records": [3]}), "{name} record 0: a record must be a JSON object"),
    "verdict.jsonl": ('{"verdict": "maybe"}\n', "{name}:1: unknown verdict 'maybe'"),
    "policy.jsonl": (
        '{"verdict": "block"}\n{"verdict": "block", "policy_id": 7}\n',
        "{name}:2: `policy_id` must be a string",
    ),
    "shape.jsonl": ('{"policy_id": "p"}\n', "{name}:1: not a chock decision record"),
    "deep.jsonl": ("[" * 100_000 + "\n", "{name}:1: not valid JSON"),
}


@pytest.mark.parametrize("name", sorted(BAD))
def test_malformed_input_is_refused_never_raised(name: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    text, says = BAD[name]
    path = tmp_path / ("x" + Path(name).suffix)
    path.write_text(text, encoding="utf-8")
    code, report, err = _run(capsys, path)
    assert (code, report) == (2, None)
    assert says.format(name=path.name) in err


def test_unreadable_files_are_refused(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "bytes.jsonl").write_bytes(b'{"verdict": "\xff"}\n')
    for path, says in ((tmp_path / "bytes.jsonl", "not UTF-8 text"), (tmp_path / "gone.jsonl", "cannot read"), (tmp_path, "cannot read")):  # fmt: skip
        code, _, err = _run(capsys, path)
        assert code == 2
        assert says in err


def test_an_empty_log_is_no_evidence(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "empty.jsonl").write_text("\n", encoding="utf-8")
    code, report, _ = _run(capsys, tmp_path / "empty.jsonl")
    assert (code, report["policies"], report["inputs"][0]["records"]) == (0, [], 0)


def test_the_script_is_stdlib_only() -> None:
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    names = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    names |= {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    assert names <= set(sys.stdlib_module_names) | {"__future__"}, names


def test_the_skill_routes_traces_through_the_script() -> None:
    skill = SCRIPT.parents[1] / "SKILL.md"
    assert "scripts/traces.py" in skill.read_text(encoding="utf-8")


def test_an_override_pairs_only_on_its_own_surface_and_target(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:  # fmt: skip
    base = {"policy_id": "p", "verdict": "block"}
    lines = [
        {**base, "ts": "1", "surface": "pre-tool-use", "target": "a.py"},
        {**base, "ts": "2", "surface": "pre-tool-use", "target": "b.py"},
        {**base, "ts": "3", "verdict": "allow", "override": "CHOCK_ALLOW", "surface": "git-hook"},
        {**base, "ts": "4", "verdict": "allow", "override": "CHOCK_ALLOW", "surface": "pre-tool-use", "target": "a.py"},
    ]
    (tmp_path / "pairs.jsonl").write_text("".join(json.dumps(r) + "\n" for r in lines), encoding="utf-8")
    _, report, _ = _run(capsys, tmp_path / "pairs.jsonl")
    assert _candidates(report) == {"p": [("pairs.jsonl:1", "pairs.jsonl:4")]}
    assert _policy(report, "p")["overrides"] == 2
