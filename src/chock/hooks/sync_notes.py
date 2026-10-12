"""What `chock sync` says about each wired agent: agentseam's pre-tool row, and whether chock has seen it run."""

from __future__ import annotations

from agentseam import tier_table

from chock import evidence

#: Surfaces sync installs; plugin-hook witnesses `chock install` only, git-hook-env a marker only.
_HOOK_SURFACES = ("pre-tool-use", "agent-hooks")

UNTESTED = (
    "Untested: chock has not witnessed its hooks run in this client; the wiring follows agentseam's record. "
    "What you see there is wanted as evidence: open-coder-ai/agentseam issues labelled 'evidence wanted'."
)


def tier_line(vendor: str) -> str | None:
    """agentseam's pre-tool row for `vendor`, its basis carried through; None where it has no row."""
    row = next((r for r in tier_table.rows() if r["agent"] == vendor), None)
    if row is None:
        return None
    return (
        f"pre-tool: {row['tier']}, {row['grade']}, fail mode {row['fail_mode']}"
        f" (agentseam basis {row['basis']}, recorded {row['recorded']})"
    )


def witnessed(vendor: str, *, ledger: tuple[evidence.Witness, ...] | None = None) -> bool:
    """Whether the ledger holds a live run of chock's repo hooks deciding in `vendor`'s client."""
    return any(evidence.witness(vendor, surface, ledger=ledger) for surface in _HOOK_SURFACES)


def notes(vendor: str) -> list[str]:
    """The lines sync prints under a vendor it registered hooks for."""
    lines = [line for line in (tier_line(vendor),) if line]
    if not witnessed(vendor):
        lines.append(UNTESTED)
    return [f"  {vendor}: {line}" for line in lines]
