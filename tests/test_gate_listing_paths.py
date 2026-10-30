"""The gate lists changed paths with `git ... -z`: a name git would C-quote is judged under its own name, never missed."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import init_repo, write_gate

from chock.gate.assemble import runner_source
from chock.gate.runner import GateContext, run
from chock.gate.runner.context import ListingError, _nul_paths

TOKEN = "FORBIDDEN_TOKEN"
#: Names `git diff --name-only` C-quotes: ESC and newline always, non-ASCII under the default core.quotePath,
#: a leading space survives quoting but not a `.strip()` of the listing.
NAMES = {"esc": "a\x1bb.txt", "non_ascii": "é.txt", "newline": "a\nb.txt", "leading_space": " sp.txt"}
SCANS = ("added_lines", "staged_blob")


def _gate(repo: Path, scan: str = "added_lines", kind: str = "content_regex", **params: str) -> Path:
    params = {"scan": scan, "content_pattern": TOKEN, **params} if kind == "content_regex" else params
    return write_gate(
        repo.parent, {"kind": kind, "on": ["commit"], "action": "block", "message": "m", "params": params}
    )


def _repo(tmp_path: Path) -> Path:
    (tmp_path / "repo").mkdir()
    return init_repo(tmp_path / "repo")


def _git(repo: Path, *args: str | bytes) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def _stage(repo: Path, name: str | bytes, content: str) -> None:
    raw = name if isinstance(name, bytes) else os.fsencode(name)
    with open(os.fsencode(repo) + b"/" + raw, "w", encoding="utf-8") as handle:
        handle.write(content)
    _git(repo, "add", "--", raw)


@pytest.mark.skipif(sys.platform == "win32", reason="ESC, newline and raw bytes are not legal Windows file names")
@pytest.mark.parametrize("scan", SCANS)
@pytest.mark.parametrize("label", NAMES)
def test_a_quoted_name_is_still_blocked(tmp_path: Path, label: str, scan: str) -> None:
    repo = _repo(tmp_path)
    _stage(repo, NAMES[label], f"{TOKEN}\n")
    assert run(_gate(repo, scan), "pre-commit", None, repo) == 1


@pytest.mark.skipif(sys.platform == "win32", reason="ESC is not a legal Windows file name")
def test_a_quoted_name_with_clean_content_is_allowed(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _stage(repo, NAMES["esc"], "fine\n")
    assert run(_gate(repo), "pre-commit", None, repo) == 0


def test_non_ascii_is_blocked_whatever_the_repo_sets_quotepath_to(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _git(repo, "config", "core.quotePath", "true")
    _stage(repo, NAMES["non_ascii"], f"{TOKEN}\n")
    assert run(_gate(repo), "pre-commit", None, repo) == 1


@pytest.mark.skipif(sys.platform == "win32", reason="ESC and newline are not legal Windows file names")
@pytest.mark.parametrize("label", ["esc", "newline"])
def test_a_quoted_name_is_blocked_in_range_mode(tmp_path: Path, label: str) -> None:
    repo = _repo(tmp_path)
    _stage(repo, "seed.txt", "seed\n")
    _git(repo, "commit", "-q", "-m", "base")
    _git(repo, "branch", "trunk")
    _stage(repo, NAMES[label], f"{TOKEN}\n")
    _git(repo, "commit", "-q", "-m", "change")
    assert run(_gate(repo), "ci", None, repo, base="trunk") == 1


@pytest.mark.skipif(sys.platform == "win32", reason="ESC is not a legal Windows file name")
def test_a_deleted_test_under_a_quoted_name_is_seen(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    name = "test_\x1b.py"
    _stage(repo, name, "assert True\n")
    _git(repo, "commit", "-q", "-m", "base")
    _git(repo, "rm", "-q", "--", name)
    gate = _gate(repo, kind="test_integrity", test_path_regex=r"^test_.*\.py$", assertion_pattern=r"assert ")
    assert run(gate, "pre-commit", None, repo) == 1


@pytest.mark.skipif(sys.platform != "linux", reason="needs a file system that stores non-UTF-8 name bytes")
def test_a_name_that_is_not_utf8_refuses(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    repo = _repo(tmp_path)
    _stage(repo, b"\xff.txt", "fine\n")
    assert run(_gate(repo), "pre-commit", None, repo) == 2
    assert "refusing" in capsys.readouterr().err


def test_a_listing_git_cannot_produce_refuses(tmp_path: Path) -> None:
    """Outside a repository `git diff` fails: that is a refusal, never an empty change."""
    (tmp_path / "plain").mkdir()
    with pytest.raises(ListingError):
        GateContext(repo_root=tmp_path / "plain").staged_paths()


@pytest.mark.parametrize("out", [b"a.txt", b"a.txt\0\0b.txt\0", b"\xff\0"])
def test_an_unparseable_listing_raises(out: bytes) -> None:
    with pytest.raises(ListingError):
        _nul_paths(out)


def test_a_listing_is_split_on_nul_only() -> None:
    assert _nul_paths(b"") == []
    assert _nul_paths(b' a\nb\0"c"\0') == [" a\nb", '"c"']


@pytest.mark.skipif(sys.platform == "win32", reason="ESC is not a legal Windows file name")
def test_the_vendored_gate_blocks_a_quoted_name(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _stage(repo, NAMES["esc"], f"{TOKEN}\n")
    runtime = tmp_path / "gate.py"
    runtime.write_text(runner_source(), encoding="utf-8")
    argv = [sys.executable, str(runtime), "run", "--gate", str(_gate(repo)), "--event", "pre-commit"]
    proc = subprocess.run(argv, cwd=repo, capture_output=True, text=True, check=False)
    assert proc.returncode == 1, proc.stderr
