"""A tracked text file is never checked out CRLF; a tracked binary is never treated as text."""

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
LF_ENTRY = "i/lf"
BINARY_ENTRY = "i/-text"
BINARY_TEXT_ATTRS = {"unset", "unspecified"}


def _git(*args: str, stdin: str | None = None) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=ROOT,
        input=stdin,
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def _tracked_by_index_state() -> dict[str, list[str]]:
    by_state: dict[str, list[str]] = {}
    for line in _git("ls-files", "--eol", "-z").split("\0"):
        if not line:
            continue
        info, path = line.split("\t", 1)
        by_state.setdefault(info.split()[0], []).append(path)
    return by_state


def _attr(attr: str, paths: list[str]) -> dict[str, str]:
    out = _git("check-attr", "-z", "--stdin", attr, stdin="\0".join(paths) + "\0")
    fields = out.split("\0")
    return {fields[i]: fields[i + 2] for i in range(0, len(fields) - 2, 3)}


@pytest.fixture(scope="module")
def tracked() -> dict[str, list[str]]:
    if not (ROOT / ".git").exists():
        pytest.skip("not a git checkout")
    return _tracked_by_index_state()


def test_every_tracked_lf_text_file_is_pinned_to_lf(tracked):
    paths = tracked.get(LF_ENTRY, [])
    assert paths
    wrong = {p: v for p, v in _attr("eol", paths).items() if v != "lf"}
    assert not wrong, f"tracked text files without eol=lf: {sorted(wrong)}"


def test_every_tracked_binary_file_is_not_text(tracked):
    paths = tracked.get(BINARY_ENTRY, [])
    assert paths
    wrong = {p: v for p, v in _attr("text", paths).items() if v not in BINARY_TEXT_ATTRS}
    assert not wrong, f"tracked binaries git may treat as text: {sorted(wrong)}"


def test_no_tracked_file_is_crlf_in_the_index(tracked):
    bad = [p for state in ("i/crlf", "i/mixed") for p in tracked.get(state, [])]
    assert not bad, f"CRLF in the index: {sorted(bad)}"
