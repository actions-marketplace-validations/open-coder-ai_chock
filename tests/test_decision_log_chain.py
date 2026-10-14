"""GAP-4: every decision-log line names the sha256 of the line before it; `chock status --verify-log` finds the break."""

from __future__ import annotations

import itertools
import json
from pathlib import Path

import pytest

from chock.gate.runner import chain, journal
from chock.lifecycle import status_main

GENESIS = chain.LOG_CHAIN_GENESIS


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    folder = tmp_path / "home"
    folder.mkdir()
    monkeypatch.setenv("HOME", str(folder))
    monkeypatch.setenv("USERPROFILE", str(folder))
    return folder


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    folder = tmp_path / "repo"
    (folder / ".git").mkdir(parents=True)
    return folder


def _log(repo: Path) -> Path:
    return repo / ".chock" / "log" / "gate-events.jsonl"


def _fill(path: Path, count: int, max_bytes: int = journal.LOG_DEFAULT_MAX_BYTES) -> None:
    for i in range(count):
        journal.log_append(path, {"policy_id": "p", "verdict": "block", "i": i}, max_bytes)


def _verify(repo: Path, capsys: pytest.CaptureFixture[str], *extra: str) -> tuple[int, dict]:
    capsys.readouterr()
    code = status_main(["--repo", str(repo), "--verify-log", "--route", "sync", "--json", *extra])
    return code, json.loads(capsys.readouterr().out)


def test_an_intact_chain_starts_at_genesis_and_counts_up(repo: Path, home: Path, capsys) -> None:
    _fill(_log(repo), 5)
    lines = _log(repo).read_bytes().splitlines()

    assert [json.loads(line)["seq"] for line in lines] == [0, 1, 2, 3, 4]
    assert json.loads(lines[0])["prev"] == GENESIS
    assert all(json.loads(b)["prev"] == chain.log_line_hash(a) for a, b in itertools.pairwise(lines))
    code, doc = _verify(repo, capsys)
    assert code == 0
    [walk] = doc["chains"]
    assert (walk["intact"], walk["records"], walk["starts_at"]) == (True, 5, "genesis")
    assert walk["head"] == {"seq": 4, "sha256": chain.log_line_hash(lines[-1])}


def _edit(lines: list[bytes]) -> list[bytes]:
    return [*lines[:2], lines[2].replace(b'"block"', b'"allow"'), *lines[3:]]


def _insert(lines: list[bytes]) -> list[bytes]:
    forged = json.loads(lines[2])
    forged.update(i=99, seq=3, prev=chain.log_line_hash(lines[2]))  # a well-formed link to the line before it
    return [*lines[:3], json.dumps(forged).encode(), *lines[3:]]


#: (tamper, the line the first break is reported at, its kind)
TAMPERS = {
    "edit": (_edit, 4, "prev"),
    "delete": (lambda lines: [*lines[:2], *lines[3:]], 3, "prev"),
    "insert": (_insert, 5, "prev"),
    "reorder": (lambda lines: [*lines[:2], lines[3], lines[2], *lines[4:]], 3, "prev"),
}


@pytest.mark.parametrize("kind", sorted(TAMPERS))
def test_each_kind_of_tampering_is_the_first_break(repo: Path, home: Path, capsys, kind: str) -> None:
    _fill(_log(repo), 6)
    tamper, line, found = TAMPERS[kind]
    _log(repo).write_bytes(b"\n".join(tamper(_log(repo).read_bytes().splitlines())) + b"\n")

    code, doc = _verify(repo, capsys)

    assert code == 1
    first = doc["chains"][0]["first_break"]
    assert (first["file"], first["line"], first["kind"]) == (".chock/log/gate-events.jsonl", line, found)
    assert first["expected"] != first["found"]


def test_the_text_report_names_file_line_expected_and_found(repo: Path, home: Path, capsys) -> None:
    _fill(_log(repo), 4)
    lines = _log(repo).read_bytes().splitlines()
    _log(repo).write_bytes(b"\n".join(_edit(lines)) + b"\n")
    capsys.readouterr()

    assert status_main(["--repo", str(repo), "--verify-log", "--route", "sync"]) == 1

    out = capsys.readouterr().out
    expected = chain.log_line_hash(_edit(lines)[2])
    assert f"BROKEN at .chock/log/gate-events.jsonl:4 (prev): expected {expected}, found " in out


def test_a_sequence_gap_with_a_good_hash_is_a_break(repo: Path, home: Path, capsys) -> None:
    _fill(_log(repo), 3)
    lines = _log(repo).read_bytes().splitlines()
    forged = {**json.loads(lines[2]), "seq": 7}
    _log(repo).write_bytes(b"\n".join([*lines[:2], json.dumps(forged).encode()]) + b"\n")

    code, doc = _verify(repo, capsys)

    assert code == 1
    assert doc["chains"][0]["first_break"] | {"file": None} == {
        "file": None,
        "line": 3,
        "kind": "seq",
        "expected": 2,
        "found": 7,
    }


def test_the_chain_carries_across_rotation(repo: Path, home: Path, capsys) -> None:
    _fill(_log(repo), 12, max_bytes=1000)
    rotated = chain.log_rotated(_log(repo))

    assert rotated.exists()
    first = json.loads(_log(repo).read_bytes().splitlines()[0])
    assert first["prev"] == chain.log_line_hash(chain.log_last_line(rotated))
    assert first["seq"] == chain.log_line_seq(chain.log_last_line(rotated)) + 1
    code, doc = _verify(repo, capsys)
    assert code == 0
    assert doc["chains"][0]["head"]["seq"] == 11


def test_history_rotated_away_is_where_the_chain_starts_not_a_break(repo: Path, home: Path, capsys) -> None:
    _fill(_log(repo), 30, max_bytes=1000)  # several rotations: only the last two files remain
    oldest = chain.log_rotated(_log(repo)).read_bytes().splitlines()[0]

    code, doc = _verify(repo, capsys)

    assert code == 0
    walk = doc["chains"][0]
    assert walk["starts_at"] == f"{json.loads(oldest)['prev']} (seq {json.loads(oldest)['seq']})"
    assert walk["starts_at"] != "genesis"
    assert walk["head"]["seq"] == 29


def test_records_written_before_chaining_are_counted_not_broken(repo: Path, home: Path, capsys) -> None:
    _log(repo).parent.mkdir(parents=True)
    _log(repo).write_text('{"policy_id": "old", "verdict": "block"}\n' * 2, encoding="utf-8")
    _fill(_log(repo), 2)

    code, doc = _verify(repo, capsys)

    assert code == 0
    walk = doc["chains"][0]
    assert (walk["unchained_before_start"], walk["records"]) == (2, 2)
    assert json.loads(_log(repo).read_bytes().splitlines()[2])["seq"] == 0


def test_an_unchained_line_after_the_chain_began_is_a_break(repo: Path, home: Path, capsys) -> None:
    _fill(_log(repo), 2)
    with _log(repo).open("a", encoding="utf-8") as fh:
        fh.write('{"policy_id": "old-runtime", "verdict": "allow"}\n')

    code, doc = _verify(repo, capsys)

    assert code == 1
    assert doc["chains"][0]["first_break"]["kind"] == "unchained"


def test_a_kept_head_is_confirmed_until_its_record_changes(repo: Path, home: Path, capsys) -> None:
    _fill(_log(repo), 4)
    lines = _log(repo).read_bytes().splitlines()
    kept = f"1:{chain.log_line_hash(lines[1])}"
    _fill(_log(repo), 2)

    assert _verify(repo, capsys, "--head", kept)[1]["kept_head"]["confirmed_in"] == ".chock/log/gate-events.jsonl"
    rewritten = [json.loads(line) for line in _log(repo).read_bytes().splitlines()]
    rewritten[1]["verdict"] = "allow"  # a local admin rewrites the record and every later hash
    _log(repo).unlink()
    for record in rewritten:
        journal.log_append(_log(repo), {k: v for k, v in record.items() if k != "ts"})

    code, doc = _verify(repo, capsys, "--head", kept)
    assert doc["chains"][0]["intact"] is True, "a whole rewrite passes the walk: only the kept head shows it"
    assert (code, doc["kept_head"]["confirmed_in"]) == (1, None)
