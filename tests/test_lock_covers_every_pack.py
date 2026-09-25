"""`chock check --only verify` attests every pack `sync` compiles, and says so when it cannot read the lock."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from conftest import baseline_policy

from chock.lock import LOCKFILE_NAME, build_lock, verify_lock, write_lock
from chock.scaffold.recompile import recompile

POLICY_ID = "protect-main-branch"


def _install(repo: Path, rel: str) -> Path:
    dest = repo / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(baseline_policy(POLICY_ID), dest)
    return dest


def test_a_pack_missing_from_the_lock_is_drift(tmp_path: Path) -> None:
    """An empty lock over an installed pack used to verify clean: nothing was compared, so nothing failed."""
    _install(tmp_path, f".agents/policies/{POLICY_ID}")
    write_lock({"lockfile_version": "1", "engine": ">=0.1,<0.2", "packs": []}, tmp_path)

    ok, failures = verify_lock(tmp_path)

    assert not ok
    assert failures == [
        f"{POLICY_ID}: installed at .agents/policies/{POLICY_ID} but not in {LOCKFILE_NAME} (run `chock sync`)"
    ]


def test_no_lockfile_over_installed_packs_is_drift_too(tmp_path: Path) -> None:
    _install(tmp_path, f".agents/policies/{POLICY_ID}")
    ok, failures = verify_lock(tmp_path)
    assert not ok and len(failures) == 1


def test_a_lock_that_is_not_json_is_a_failure_not_a_traceback(tmp_path: Path) -> None:
    (tmp_path / LOCKFILE_NAME).write_text("{not json", encoding="utf-8")
    ok, failures = verify_lock(tmp_path)
    assert not ok
    assert failures[0].startswith(f"{LOCKFILE_NAME} is not valid JSON")


def test_a_lock_of_the_wrong_shape_is_a_failure(tmp_path: Path) -> None:
    (tmp_path / LOCKFILE_NAME).write_text(json.dumps(["packs"]), encoding="utf-8")
    ok, failures = verify_lock(tmp_path)
    assert not ok and "not a lockfile" in failures[0]


def test_a_nested_pack_is_locked_at_its_path_and_verified_there(tmp_path: Path) -> None:
    """`sync` compiles every manifest under .agents/policies, however deep; the lock covered only the top level."""
    nested = _install(tmp_path, f".agents/policies/team/{POLICY_ID}")
    recompile(tmp_path, ["claude"], skip_hooks=True)

    lock = build_lock(tmp_path)
    (entry,) = lock["packs"]
    assert entry["id"] == POLICY_ID
    assert entry["path"] == f".agents/policies/team/{POLICY_ID}"
    assert "artifacts_sha256" in entry, "the compiled tree of a nested pack is attested like any other"

    write_lock(lock, tmp_path)
    assert verify_lock(tmp_path) == (True, [])

    (nested / "manifest.yaml").write_text("id: protect-main-branch\n", encoding="utf-8")
    ok, failures = verify_lock(tmp_path)
    assert not ok and failures[0].startswith(f"{POLICY_ID}: hash mismatch")


def test_a_top_level_pack_records_no_path(tmp_path: Path) -> None:
    """The lock format is unchanged for the layout every adopter has."""
    _install(tmp_path, f".agents/policies/{POLICY_ID}")
    (entry,) = build_lock(tmp_path)["packs"]
    assert "path" not in entry
