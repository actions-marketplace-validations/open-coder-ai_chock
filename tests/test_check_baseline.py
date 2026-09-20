"""A branch may not weaken the policy set its base carries.

`protect-agent-config` refuses the agent's *shell* edit of `.chock/config.yaml`, best-effort,
and nothing refuses the same edit committed through any other path. This check reads the
config at the base ref and at the head and fails on any policy the head lets run less of.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import yaml

from chock.validation.checks_baseline import Weakening, main, weakenings

ALL = {"policies": {"disabled": [], "overrides": {}}}


def _cfg(disabled=(), overrides=None) -> dict:
    return {"policies": {"disabled": list(disabled), "overrides": dict(overrides or {})}}


# --- the comparison, on configs alone -------------------------------------------------------------


def test_disabling_a_policy_is_a_weakening() -> None:
    assert weakenings(ALL, _cfg(disabled=["scan-secrets"])) == [Weakening("scan-secrets", "enabled", "disabled")]


def test_re_enabling_a_policy_is_not() -> None:
    assert weakenings(_cfg(disabled=["scan-secrets"]), ALL) == []


def test_downgrading_to_advisory_is_a_weakening() -> None:
    found = weakenings(ALL, _cfg(overrides={"scan-secrets": {"enforcement": "advise"}}))
    assert [w.policy_id for w in found] == ["scan-secrets"]
    assert found[0].now == "limited to ambient-rule"


def test_narrowing_the_surfaces_is_a_weakening() -> None:
    wide = _cfg(overrides={"p": {"surfaces": ["git-hook", "ci-gate"]}})
    narrow = _cfg(overrides={"p": {"surfaces": ["git-hook"]}})
    assert [w.policy_id for w in weakenings(wide, narrow)] == ["p"]
    assert weakenings(narrow, wide) == [], "widening is never a finding"


def test_no_config_at_the_base_means_everything_was_enabled() -> None:
    """A repo that never had a config ran every policy; adding one that disables some is a weakening."""
    assert [w.policy_id for w in weakenings(None, _cfg(disabled=["p"]))] == ["p"]
    assert weakenings(None, ALL) == []


def test_an_unchanged_config_is_silent() -> None:
    cfg = _cfg(disabled=["x"], overrides={"y": {"surfaces": ["git-hook"]}})
    assert weakenings(cfg, cfg) == []


# --- and over real revisions ----------------------------------------------------------------------


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def _repo_with(tmp_path: Path, config: dict | None) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@e")
    _git(repo, "config", "user.name", "t")
    (repo / "README.md").write_text("x\n", encoding="utf-8")
    if config is not None:
        (repo / ".chock").mkdir()
        (repo / ".chock" / "config.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    return repo


def _write_config(repo: Path, config: dict) -> None:
    (repo / ".chock").mkdir(exist_ok=True)
    (repo / ".chock" / "config.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")


def test_a_branch_that_disables_a_policy_fails_against_main(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    repo = _repo_with(tmp_path, ALL)
    _write_config(repo, _cfg(disabled=["scan-secrets"]))
    assert main(["--repo", str(repo), "--base", "main"]) == 1
    assert "scan-secrets: enabled -> disabled" in capsys.readouterr().out


def test_a_branch_that_changes_nothing_passes(tmp_path: Path) -> None:
    repo = _repo_with(tmp_path, ALL)
    assert main(["--repo", str(repo), "--base", "main"]) == 0


def test_a_branch_that_adds_a_config_disabling_nothing_passes(tmp_path: Path) -> None:
    repo = _repo_with(tmp_path, None)
    _write_config(repo, ALL)
    assert main(["--repo", str(repo), "--base", "main"]) == 0


def test_a_branch_that_adds_a_config_disabling_something_fails(tmp_path: Path) -> None:
    repo = _repo_with(tmp_path, None)
    _write_config(repo, _cfg(disabled=["p"]))
    assert main(["--repo", str(repo), "--base", "main"]) == 1


def test_the_check_needs_a_base(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        main(["--repo", str(tmp_path)])


# --- what a strict-subset comparison missed ---------------------------------------------------------


def test_swapping_a_surface_for_another_is_a_weakening() -> None:
    """{git-hook, ci-gate} -> {git-hook, ambient-rule} has the same size and one fewer real gate."""
    before = _cfg(overrides={"p": {"surfaces": ["git-hook", "ci-gate"]}})
    after = _cfg(overrides={"p": {"surfaces": ["git-hook", "ambient-rule"]}})
    assert [w.policy_id for w in weakenings(before, after)] == ["p"]


def test_a_surfaces_value_of_the_wrong_type_does_not_crash_the_check() -> None:
    before = _cfg(overrides={"p": {"surfaces": ["git-hook"]}})
    assert weakenings(before, _cfg(overrides={"p": {"surfaces": 5}})) == [], "an unusable override enables everything"
    assert [w.policy_id for w in weakenings(before, _cfg(overrides={"p": {"surfaces": "ci-gate"}}))] == ["p"]


def test_a_base_ref_that_does_not_resolve_fails_the_check(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    """An unfetched base is not a base with no config, which would mean every policy enabled."""
    repo = _repo_with(tmp_path, ALL)
    assert main(["--repo", str(repo), "--base", "origin/nowhere"]) == 1
    assert "does not resolve" in capsys.readouterr().out


def test_a_base_config_that_is_not_yaml_fails_the_check(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    repo = _repo_with(tmp_path, None)
    (repo / ".chock").mkdir()
    (repo / ".chock" / "config.yaml").write_text("policies: [\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "broken")
    _write_config(repo, ALL)
    assert main(["--repo", str(repo), "--base", "main"]) == 1
    assert "not valid YAML" in capsys.readouterr().out
