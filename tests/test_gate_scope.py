"""applies_to.paths: which files a gate may judge at all.

A content pattern is written to describe one kind of file. Run against every changed file it
alarms on the README that documents it -- a control firing on a correct change, which is the
one failure a gate does not get to make.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from conftest import init_repo, stage, write_gate

from chock.gate.build import build_gate_json
from chock.gate.runner import GateContext, run

UNPINNED = "      - uses: actions/checkout@v4\n"

PARAMS = {
    "scan": "added_lines",
    "content_pattern": r"uses:\s*[A-Za-z0-9._/-]+@(?![0-9a-fA-F]{40})[A-Za-z0-9._/-]+",
}


def _gate(tmp_path: Path, paths: list[str] | None = None) -> Path:
    spec = {
        "kind": "content_regex",
        "on": ["commit"],
        "action": "block",
        "message": "pin it",
        "params": PARAMS,
    }
    if paths is not None:
        spec["paths"] = paths
    return write_gate(tmp_path, spec)


# --- the scope bounds what is judged ------------------------------------------------------------


def test_a_gate_with_no_scope_judges_every_changed_file(tmp_path: Path) -> None:
    """The behaviour before applies_to.paths was read, and still the default."""
    init_repo(tmp_path)
    stage(tmp_path, ".github/workflows/ci.yml", UNPINNED)
    assert run(_gate(tmp_path), "pre-commit", None, tmp_path) == 1


def test_a_scoped_gate_still_refuses_the_file_it_is_about(tmp_path: Path) -> None:
    init_repo(tmp_path)
    stage(tmp_path, ".github/workflows/ci.yml", UNPINNED)
    assert run(_gate(tmp_path, [".github/workflows/*"]), "pre-commit", None, tmp_path) == 1


def test_a_scoped_gate_says_nothing_about_a_file_documenting_the_pattern(tmp_path: Path) -> None:
    """The README explaining the rule must not be refused by the rule."""
    init_repo(tmp_path)
    stage(tmp_path, "docs/pinning.md", f"Never write this:\n\n```yaml\n{UNPINNED}```\n")
    assert run(_gate(tmp_path, [".github/workflows/*"]), "pre-commit", None, tmp_path) == 0
    assert run(_gate(tmp_path), "pre-commit", None, tmp_path) == 1, "unscoped, it does refuse it"


def test_a_scope_that_matches_nothing_changed_refuses_nothing(tmp_path: Path) -> None:
    init_repo(tmp_path)
    stage(tmp_path, "src/app.py", "x = 1\n")
    assert run(_gate(tmp_path, [".github/workflows/*"]), "pre-commit", None, tmp_path) == 0


# --- the context is where scope lives -----------------------------------------------------------


def test_scope_globs_cross_the_path_separator(tmp_path: Path) -> None:
    """fnmatch semantics, so one glob covers a directory's nested files too."""
    ctx = GateContext(repo_root=tmp_path, scope=[".github/workflows/*"])
    assert ctx.in_scope(".github/workflows/ci.yml")
    assert ctx.in_scope(".github/workflows/nested/ci.yml")
    assert not ctx.in_scope("docs/pinning.md")


def test_an_empty_scope_admits_everything(tmp_path: Path) -> None:
    assert GateContext(repo_root=tmp_path).in_scope("anything/at/all.txt")
    assert GateContext(repo_root=tmp_path, scope=[]).in_scope("anything/at/all.txt")


# --- the manifest is where it is declared -------------------------------------------------------


def _policy(tmp_path: Path, manifest: dict) -> Path:
    policy = tmp_path / "policy"
    policy.mkdir(parents=True, exist_ok=True)
    (policy / "manifest.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")
    return policy


def _manifest(**extra) -> dict:
    return {
        "id": "scoped",
        "name": "Scoped",
        "version": "0.0.1",
        "description": "d",
        "artifact": "hook",
        "enforcement": "block",
        "hook": {
            "gate": {"kind": "content_regex", "on": ["commit"], "action": "block", "message": "m", "params": PARAMS}
        },
        "provenance": {"author": "t"},
        "lifecycle": {"status": "draft"},
        **extra,
    }


def test_applies_to_paths_reaches_the_compiled_gate(tmp_path: Path) -> None:
    """It was a schema field nothing read, which is a claim of reach the gate did not have."""
    policy = _policy(tmp_path, _manifest(applies_to={"paths": [".github/workflows/*"]}))
    assert build_gate_json(policy, tmp_path)["paths"] == [".github/workflows/*"]


def test_a_policy_that_declares_no_paths_compiles_without_them(tmp_path: Path) -> None:
    policy = _policy(tmp_path, _manifest())
    assert "paths" not in build_gate_json(policy, tmp_path)
