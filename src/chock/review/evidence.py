"""Build and verify reviewer evidence."""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from chock.cli import main as cli_main
from chock.review.policy import (
    attestation_floor,
    check_registry,
    command_set_hash,
    required_checks,
    unattestable_paths,
)

SCHEMA_URL = "https://open-coder-ai.github.io/chock/schemas/v0/reviewer-evidence-v1.json"
_GIT = shutil.which("git") or "git"

EMPTY_DIFF_SHA = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"

EVIDENCE_DIR = Path(".chock") / "evidence"


class EvidenceError(RuntimeError):
    """Evidence that cannot be produced or read."""


def _git(root: Path, *args: str) -> str:
    proc = subprocess.run(  # noqa: S603 -- reading repo facts via git is this helper's job
        [_GIT, *args], cwd=root, capture_output=True, encoding="utf-8", errors="replace", check=False
    )
    if proc.returncode != 0:
        msg = f"git {' '.join(args)} failed: {proc.stderr.strip()}"
        raise EvidenceError(msg)
    return proc.stdout


def merge_base(root: Path, base_ref: str) -> str:
    return _git(root, "merge-base", base_ref, "HEAD").strip()


def diff_sha(root: Path, base_ref: str) -> str:
    """Digest of the change, with the evidence directory excluded."""
    diff = _git(
        root,
        "diff",
        "--no-color",
        f"{merge_base(root, base_ref)}...HEAD",
        "--",
        ".",
        f":(exclude){EVIDENCE_DIR.as_posix()}/*",
    )
    return hashlib.sha256(diff.encode("utf-8")).hexdigest()


def run_check(root: Path, argv: list[str]) -> tuple[str, str]:
    """Run one registry entry. Returns (pass|fail, first line of output)."""
    resolved = [a.replace("{root}", str(root)) for a in argv]
    if resolved and resolved[0] == "python":
        proc = subprocess.run(  # noqa: S603 -- running a repo-registered review check is this function's job
            resolved, cwd=root, capture_output=True, encoding="utf-8", errors="replace", check=False
        )
        code, out = proc.returncode, (proc.stdout or proc.stderr)
    else:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(buffer):
            try:
                code = cli_main(resolved)
            except SystemExit as exc:
                code = exc.code if isinstance(exc.code, int) else 1
        out = buffer.getvalue()
    first = next((line for line in out.splitlines() if line.strip()), "")
    return ("pass" if code == 0 else "fail"), first[:2000]


def working_tree_is_dirty(root: Path) -> bool:
    return bool(_git(root, "status", "--porcelain").strip())


def build(
    root: Path, base_ref: str, produced_by: dict[str, str], checks: list[str], *, allow_empty: bool = False
) -> dict[str, Any]:
    """Run every named check and record the result. Attestations are added by a reviewer."""
    if not allow_empty and diff_sha(root, base_ref) == EMPTY_DIFF_SHA:
        hint = (
            "the working tree has uncommitted changes -- `diff_sha` is computed from committed state, so commit first"
            if working_tree_is_dirty(root)
            else f"HEAD is identical to {base_ref}"
        )
        msg = (
            f"nothing to attest: the diff against {base_ref} is empty ({hint}). "
            f"Pass --allow-empty to record evidence for an empty change anyway."
        )
        raise EvidenceError(msg)

    registry = check_registry(root, base_ref)
    unknown = [c for c in checks if c not in registry]
    if unknown:
        msg = f"unknown check(s): {', '.join(sorted(unknown))}. Known: {', '.join(sorted(registry))}"
        raise EvidenceError(msg)

    verified = []
    for name in checks:
        result, detail = run_check(root, registry[name])
        verified.append(
            {
                "check": name,
                "command": "chock " + " ".join(registry[name]).replace("{root}", "."),
                "result": result,
                "detail": detail,
            }
        )

    return {
        "$schema": SCHEMA_URL,
        "diff_sha": diff_sha(root, base_ref),
        "base_ref": base_ref,
        "head_sha": _git(root, "rev-parse", "HEAD").strip(),
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "produced_by": produced_by,
        "verified": verified,
        "attested": [],
        "unattestable": unattestable_paths(root, base_ref),
        "command_set_hash": command_set_hash(root, base_ref),
    }


def verify(root: Path, evidence: dict[str, Any], base_ref: str) -> list[str]:
    """Re-derive every verified claim. Returns failures; empty means the evidence holds."""
    failures: list[str] = []

    current = diff_sha(root, base_ref)
    if evidence.get("diff_sha") != current:
        return [
            f"evidence is stale: it describes diff {str(evidence.get('diff_sha'))[:12]}, "
            f"the branch is now {current[:12]}. Re-run `chock review emit`."
        ]

    expected_unattestable = unattestable_paths(root, base_ref)
    if sorted(evidence.get("unattestable") or []) != expected_unattestable:
        failures.append(
            f"unattestable paths disagree with repository config: evidence says "
            f"{sorted(evidence.get('unattestable') or [])}, repo says {expected_unattestable}"
        )

    registry = check_registry(root, base_ref)
    named = {entry.get("check") for entry in evidence.get("verified") or []}
    missing = sorted(set(required_checks(root, base_ref)) - named)
    if missing:
        failures.append(
            f"evidence does not cover the checks this repository requires; missing: "
            f"{', '.join(missing)}. The repository decides what a contribution is judged on, "
            f"not the evidence."
        )

    for entry in evidence.get("verified") or []:
        name = entry.get("check")
        if name not in registry:
            failures.append(f"{name}: not a known check, so nothing can re-derive it")
            continue
        expected_command = "chock " + " ".join(registry[name]).replace("{root}", ".")
        if entry.get("command") and entry["command"] != expected_command:
            failures.append(f"{name}: evidence records `{entry['command']}`, registry runs `{expected_command}`")
        actual, detail = run_check(root, registry[name])
        if actual != entry.get("result"):
            failures.append(f"{name}: evidence claims {entry.get('result')}, re-running gives {actual}. {detail}")

    return failures


def _find_evidence(root: Path, base_ref: str) -> Path | None:
    """The committed evidence file matching HEAD's `diff_sha`, or None."""
    target = diff_sha(root, base_ref)
    evidence_dir = root / EVIDENCE_DIR
    for candidate in sorted(evidence_dir.glob("*.json")) if evidence_dir.is_dir() else []:
        with contextlib.suppress(EvidenceError):
            if load(candidate).get("diff_sha") == target:
                return candidate
    return None


def _touched_unattestable_paths(root: Path, base_ref: str) -> list[str]:
    """Which of the repo's unattestable prefixes the diff actually touches."""
    diff_range = f"{merge_base(root, base_ref)}...HEAD"
    changed = [p for p in _git(root, "diff", "--no-color", "--name-only", diff_range).splitlines() if p.strip()]
    prefixes = unattestable_paths(root, base_ref)
    return sorted({prefix for prefix in prefixes for path in changed if path.startswith(prefix)})


def require(root: Path, base_ref: str) -> list[str]:
    """Present -> Valid -> Sufficient -> Passing -> Attested, in order; empty means the PR may merge."""
    evidence_path = _find_evidence(root, base_ref)
    if evidence_path is None:
        return [
            f"no evidence matches this diff against {base_ref}. Run "
            f"`chock review emit --base {base_ref} --kind agent --by <your-name>` "
            "(or --kind human if a person is producing it), then commit and push the file it writes."
        ]

    evidence = load(evidence_path)
    invalid = verify(root, evidence, base_ref)
    if invalid:
        return invalid

    required = required_checks(root, base_ref)
    if required:
        expected_hash = command_set_hash(root, base_ref)
        if evidence.get("command_set_hash") != expected_hash:
            return [
                f"evidence's command_set_hash does not match this repository's required checks "
                f"({', '.join(required)}) as currently defined -- the set, or one of its commands, "
                f"changed since the evidence was produced. Re-run "
                f"`chock review emit --base {base_ref}` and push the regenerated evidence."
            ]
    failing = sorted(str(e.get("check")) for e in evidence.get("verified") or [] if e.get("result") == "fail")
    if failing:
        label = "required check(s)" if set(failing) <= set(required) else "check(s)"
        return [
            f"{label} recorded failing: {', '.join(failing)}. Fix the underlying "
            f"issue, then re-run `chock review emit --base {base_ref}` and push the evidence."
        ]
    floor = attestation_floor(root, base_ref)
    if floor:
        touched = _touched_unattestable_paths(root, base_ref)
        attested = evidence.get("attested") or []
        if touched and len(attested) < floor:
            return [
                f"this change touches {', '.join(touched)}, which needs at least {floor} "
                f"attestation(s) but the evidence carries {len(attested)}. Add an entry to "
                f"`attested` in {evidence_path.name} recording a reviewer's judgement "
                "(see docs/reviewer-evidence.md), then commit and push it."
            ]

    return []


def load(path: Path) -> dict[str, Any]:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        msg = f"cannot read evidence at {path}: {exc}"
        raise EvidenceError(msg) from exc
