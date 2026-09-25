"""A `.chock/config.yaml` of the wrong shape neither crashes the resolver nor quietly widens or narrows a policy."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from chock.config import policy_status
from chock.validation.checks_policy_toggles import check_policy_toggles
from chock.validation.report import Report

ALL_SURFACES = policy_status({}, "p")["targets"]


@pytest.mark.parametrize(
    "config",
    [
        {"policies": None},
        {"policies": "disabled"},
        {"policies": {"disabled": None, "overrides": None}},
        {"policies": {"overrides": {"p": None}}},
        {"policies": {"overrides": {"p": "advise"}}},
        {"policies": {"overrides": {"p": {"surfaces": 5}}}},
        {"policies": {"overrides": {"p": {"surfaces": [5, None]}}}},
    ],
)
def test_a_malformed_block_leaves_the_policy_enabled_everywhere(config: dict) -> None:
    status = policy_status(config, "p")
    assert status["state"] in {"enabled", "overridden"}
    assert status["targets"] == ALL_SURFACES


def test_a_bare_string_in_disabled_is_one_id_not_its_letters() -> None:
    assert policy_status({"policies": {"disabled": "scan-secrets"}}, "scan-secrets")["state"] == "disabled"
    assert policy_status({"policies": {"disabled": "scan-secrets"}}, "s")["state"] == "enabled"


def test_a_bare_string_surface_is_one_surface() -> None:
    status = policy_status({"policies": {"overrides": {"p": {"surfaces": "git-hook"}}}}, "p")
    assert status["targets"] == ["git-hook"]


def test_pol1_the_config_cannot_disable_a_mandatory_policy() -> None:
    """`chock disable` and validate both refuse it; `sync` must not honour the entry either."""
    status = policy_status({"policies": {"disabled": ["m"]}}, "m", {"mandatory": True})
    assert status["state"] == "enabled"
    assert status["targets"] == ALL_SURFACES


# --- and validate names the mistake ----------------------------------------------------------------


def _repo(tmp_path: Path, config: dict) -> Path:
    (tmp_path / ".chock").mkdir()
    (tmp_path / ".chock" / "config.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")
    (tmp_path / ".agents" / "policies" / "p").mkdir(parents=True)
    (tmp_path / ".agents" / "policies" / "p" / "manifest.yaml").write_text(
        "id: p\nname: P\nartifact: rule\nenforcement: advise\neffects: [read_only]\ndescription: p\n", encoding="utf-8"
    )
    return tmp_path


def _errors(tmp_path: Path, config: dict) -> list[str]:
    report = Report()
    check_policy_toggles(_repo(tmp_path, config), report)
    return [f.message for f in report.errors]


def test_validate_rejects_a_policies_block_that_is_not_a_mapping(tmp_path: Path) -> None:
    assert _errors(tmp_path, {"policies": "nope"}) == ["policies: must be a mapping"]


def test_validate_rejects_disabled_that_is_not_a_list(tmp_path: Path) -> None:
    assert _errors(tmp_path, {"policies": {"disabled": "p"}}) == ["policies.disabled: must be a list"]


def test_validate_rejects_an_override_that_is_not_a_mapping(tmp_path: Path) -> None:
    assert _errors(tmp_path, {"policies": {"overrides": {"p": "advise"}}}) == [
        "policies.overrides.p: must be a mapping"
    ]


def test_validate_rejects_an_unknown_surface_name(tmp_path: Path) -> None:
    (message,) = _errors(tmp_path, {"policies": {"overrides": {"p": {"surfaces": ["git-hook", "githook"]}}}})
    assert message.startswith("policies.overrides.p.surfaces: unknown surface(s): githook; known: ")


def test_validate_rejects_surfaces_that_are_not_a_list(tmp_path: Path) -> None:
    (message,) = _errors(tmp_path, {"policies": {"overrides": {"p": {"surfaces": 5}}}})
    assert message.startswith("policies.overrides.p.surfaces: must be a list of surface names")


def test_validate_is_silent_on_a_well_formed_override(tmp_path: Path) -> None:
    assert _errors(tmp_path, {"policies": {"disabled": [], "overrides": {"p": {"surfaces": ["git-hook"]}}}}) == []


def test_a_non_mapping_override_on_a_security_block_guard_does_not_crash(tmp_path: Path) -> None:
    """The block-guard-downgraded-to-advisory check must not run `.get` on a shape it already rejected."""
    (tmp_path / ".chock").mkdir()
    (tmp_path / ".chock" / "config.yaml").write_text(
        yaml.safe_dump({"policies": {"overrides": {"scan-secrets": "advise"}}}), encoding="utf-8"
    )
    (tmp_path / ".agents" / "policies" / "scan-secrets").mkdir(parents=True)
    (tmp_path / ".agents" / "policies" / "scan-secrets" / "manifest.yaml").write_text(
        "id: scan-secrets\nname: Scan\nartifact: rule\nenforcement: block\neffects: [read_only]\ndescription: d\n",
        encoding="utf-8",
    )
    report = Report()
    check_policy_toggles(tmp_path, report)
    assert [f.message for f in report.errors] == ["policies.overrides.scan-secrets: must be a mapping"]
