"""goose's guard note and Antigravity's posture render their witness clause from the ledger, never a hand-written one."""

from __future__ import annotations

from chock import evidence
from chock.plugin import antigravity, goose, posture


def test_the_goose_note_cites_its_ledger_row_and_the_sh_requirement() -> None:
    clause = posture.witness_clause("goose")
    assert clause.startswith("witnessed blocking on ")
    assert f"({clause})" in goose.GUARD_NOTE
    assert "not witnessed" not in goose.GUARD_NOTE
    assert "`sh -c`" in goose.GUARD_NOTE and "without sh every tool call is denied" in goose.GUARD_NOTE


def test_the_antigravity_posture_says_what_the_ledger_says() -> None:
    assert f"({posture.witness_clause('antigravity')})" in antigravity.POSTURE_BESTEFFORT
    forged = (evidence.Witness("antigravity", evidence.PLUGIN_HOOK, "a real install", "2026-10-18", "live probe"),)
    assert posture.witness_clause("antigravity", ledger=forged) == "witnessed blocking on a real install, 2026-10-18"
