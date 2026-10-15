"""GAP-5: `chock incident` reads an ordered, redacted timeline from the local decision log, as evidence."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from chock import incident
from chock.gate.runner import chain, journal

EMAIL = "me@example.com"
SINCE, UNTIL = "2026-10-14T10:00:00Z", "2026-10-14T11:00:00Z"
#: OSC title + BEL, clear screen, a right-to-left override, and a C1 CSI: each must reach no terminal raw.
ESCAPES = "".join(map(chr, (0x1B, 0x5D, 0x30, 0x3B, 0x6F, 0x07, 0x1B, 0x5B, 0x32, 0x4A, 0x202E, 0x9B)))
UNSAFE = [c for c in ESCAPES if not c.isprintable()]


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    folder = tmp_path / "home"
    folder.mkdir()
    monkeypatch.setenv("HOME", str(folder))
    monkeypatch.setenv("USERPROFILE", str(folder))
    return folder


@pytest.fixture
def repo(tmp_path: Path, home: Path) -> Path:
    folder = tmp_path / "repo"
    (folder / ".git").mkdir(parents=True)
    return folder


def _log(repo: Path) -> Path:
    return repo / ".chock" / "log" / "gate-events.jsonl"


def _put(repo: Path, ts: str, **fields: object) -> None:
    journal.log_append(_log(repo), {"ts": ts, "route": "sync", **fields})


def _block(repo: Path, ts: str, **fields: object) -> None:
    record = {"policy_id": "scan-secrets", "verdict": "block", "actor": "agent:claude_code", "session_id": "s1"}
    _put(repo, ts, **{**record, **fields})


def _run(repo: Path, capsys: pytest.CaptureFixture[str], *extra: str) -> str:
    capsys.readouterr()
    assert incident.main(["--repo", str(repo), "--since", SINCE, "--until", UNTIL, *extra]) == 0
    return capsys.readouterr().out


def _doc(repo: Path, capsys: pytest.CaptureFixture[str], *extra: str) -> dict:
    return json.loads(_run(repo, capsys, "--format", "json", *extra))


def _shown(entry: dict) -> object:
    return entry.get("problem") or entry.get("break") or entry.get("target")


def test_order_runs_across_the_rotated_file_by_time_then_log_position(repo: Path, capsys) -> None:
    _block(repo, "2026-10-14T10:00:02Z", target="a")
    _block(repo, "2026-10-14T10:00:03Z", target="b")
    os.replace(_log(repo), chain.log_rotated(_log(repo)))  # what rotation does; the chain runs on across it
    _block(repo, "2026-10-14T10:00:01Z", target="c")  # an earlier clock in the newer file
    _block(repo, "2026-10-14T10:00:03Z", target="d")  # the same second as b: log position decides
    doc = _doc(repo, capsys)
    assert [(e["target"], e["at"]) for e in doc["timeline"]] == [
        ("c", ".chock/log/gate-events.jsonl:1"),
        ("a", ".chock/log/gate-events.1.jsonl:1"),
        ("b", ".chock/log/gate-events.1.jsonl:2"),
        ("d", ".chock/log/gate-events.jsonl:2"),
    ]
    assert doc["chains"][0]["summary"] == ".chock/log/gate-events.jsonl: chain intact from seq 0 to 3"


def test_the_window_includes_its_start_and_leaves_out_its_end(repo: Path, capsys) -> None:
    for target, ts in {"before": "09:59:59", "start": "10:00:00", "last": "10:59:59", "end": "11:00:00"}.items():
        _block(repo, f"2026-10-14T{ts}Z", target=target)
    doc = _doc(repo, capsys)
    assert [e["target"] for e in doc["timeline"]] == ["start", "last"]
    assert doc["chains"][0]["summary"].endswith("chain intact from seq 1 to 2")


def test_a_zoned_date_or_relative_time_is_read_as_utc() -> None:
    assert incident.parse_time("2026-10-14T12:00:00+02:00") == SINCE
    assert incident.parse_time("2026-10-14") == "2026-10-14T00:00:00Z"
    assert incident.parse_time("24h") < incident.parse_time("90m")


@pytest.mark.parametrize(
    "args",
    [["--since", "yesterday"], ["--since", "0001-01-01T00:00:00+01:00"], ["--since", UNTIL, "--until", SINCE]],
)
def test_a_bad_time_or_an_empty_range_is_a_usage_error(repo: Path, args: list[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        incident.main(["--repo", str(repo), *args])
    assert exc.value.code == 2


def test_a_chain_break_is_shown_inline_where_it_is(repo: Path, capsys) -> None:
    for second in range(1, 5):
        _block(repo, f"2026-10-14T10:00:0{second}Z", target=f"t{second}")
    lines = _log(repo).read_bytes().splitlines()
    lines[1] = lines[1].replace(b'"block"', b'"allow"')  # line 2 edited: line 3's link to it breaks
    _log(repo).write_bytes(b"\n".join(lines) + b"\n")
    doc = _doc(repo, capsys)
    assert [(e["kind"], _shown(e)) for e in doc["timeline"]] == [
        ("decision", "t1"),  # the edited line 2 now reads as a debug allow: left out, and its edit shows below
        ("chain_break", "prev"),
        ("decision", "t3"),
        ("decision", "t4"),
    ]
    assert doc["timeline"][1]["at"] == ".chock/log/gate-events.jsonl:3"
    assert doc["chains"][0]["summary"].endswith("break at .chock/log/gate-events.jsonl:3 (prev)")
    assert "chain_break  break=prev" in _run(repo, capsys)


def test_a_break_outside_the_window_is_counted_not_listed(repo: Path, capsys) -> None:
    for ts in ("09:00:00", "09:00:01", "09:00:02", "10:30:00"):
        _block(repo, f"2026-10-14T{ts}Z")
    lines = _log(repo).read_bytes().splitlines()
    _log(repo).write_bytes(b"\n".join([lines[0], *lines[2:]]) + b"\n")  # line 2 deleted
    doc = _doc(repo, capsys)
    assert [e["kind"] for e in doc["timeline"]] == ["decision"]
    assert doc["chains"][0]["summary"].endswith("1 break(s) outside the window (chock status --verify-log)")


def _people(repo: Path) -> None:
    _put(
        repo, "2026-10-14T10:00:01Z", policy_id="scan-secrets", verdict="allow", override="CHOCK_ALLOW", approver=EMAIL
    )
    _put(repo, "2026-10-14T10:00:02Z", policy_id="chock-stop", event="repo_stop", scope="all", who=EMAIL, reason="r")
    _put(repo, "2026-10-14T10:00:03Z", policy_id="chock-stop", event="repo_resume", scope="all", who=EMAIL)


def test_overrides_stop_and_resume_show_the_person_locally(repo: Path, capsys) -> None:
    _people(repo)
    doc = _doc(repo, capsys)
    assert [(e["kind"], e.get("approver") or e.get("who")) for e in doc["timeline"]] == [
        ("override", EMAIL),
        ("repo_stop", EMAIL),
        ("repo_resume", EMAIL),
    ]
    assert EMAIL in _run(repo, capsys)


@pytest.mark.parametrize("form", incident.FORMATS)
def test_share_strips_approver_and_who(repo: Path, capsys, form: str) -> None:
    _people(repo)
    out = _run(repo, capsys, "--share", "--format", form)
    assert EMAIL not in out
    assert "repo_stop" in out
    assert "CHOCK_ALLOW" in out


@pytest.mark.parametrize("form", incident.FORMATS)
def test_a_terminal_escape_in_a_target_is_rendered_inert(repo: Path, capsys, form: str) -> None:
    _block(repo, "2026-10-14T10:00:01Z", target=f"src/{ESCAPES}x.py", session_id=f"s{ESCAPES}")
    out = _run(repo, capsys, "--format", form)
    assert UNSAFE
    assert not [c for c in UNSAFE if c in out]
    assert ("u001b" if form == "json" else "x1b") in out


def test_an_empty_window_says_so(repo: Path, capsys) -> None:
    _block(repo, "2026-10-14T09:00:00Z")
    out = _run(repo, capsys)
    assert "Timeline (0 entries)\n  nothing in this window" in out
    assert "no chained record in the window" in out
    assert _doc(repo, capsys)["timeline"] == []


def test_no_log_at_all_says_so(repo: Path, capsys) -> None:
    assert "Logs read: no decision log found" in _run(repo, capsys)


def test_a_malformed_line_is_reported_in_place_not_crashed_on(repo: Path, capsys) -> None:
    _block(repo, "2026-10-14T10:00:01Z", target="before")
    with _log(repo).open("ab") as fh:
        fh.write(b'{"ts": "2026-10-14T10:00:0\n\xff\xfe not json\n[1, 2]\n{"verdict": "block"}\n')
    _block(repo, "2026-10-14T10:00:02Z", target="after")
    doc = _doc(repo, capsys)
    assert [(e["kind"], _shown(e), e["at"].rsplit(":", 1)[1]) for e in doc["timeline"]] == [
        ("decision", "before", "1"),
        ("unreadable", "not a JSON record", "2"),
        ("unreadable", "not a JSON record", "3"),
        ("chain_break", "unchained", "4"),
        ("unreadable", "not a JSON object", "4"),
        ("chain_break", "unchained", "5"),
        ("unreadable", "no readable ts", "5"),
        ("decision", "after", "6"),
    ]
    assert "unreadable  problem=not a JSON record" in _run(repo, capsys)


def test_plain_allows_are_counted_per_session_never_listed(repo: Path, capsys) -> None:
    _put(repo, "2026-10-14T10:00:00Z", event="session_start", session_id="s1", actor="agent:claude_code")
    for second in range(1, 4):
        _put(repo, f"2026-10-14T10:00:0{second}Z", verdict="allow", target="src/a.py", session_id="s1")
    _put(repo, "2026-10-14T10:00:05Z", verdict="allow", target="src/a.py", session_id="s1", policy_id="p")  # debug
    _block(repo, "2026-10-14T10:00:06Z")
    doc = _doc(repo, capsys)
    assert [e["kind"] for e in doc["timeline"]] == ["session_start", "decision"]
    session = doc["sessions"]["s1"]
    assert (session["allowed"], session["verdicts"], session["actors"]) == (3, {"block": 1}, ["agent:claude_code"])
    assert (session["first"], session["last"]) == ("2026-10-14T10:00:00Z", "2026-10-14T10:00:06Z")
    assert doc["debug_lines_left_out"] == 1


def test_the_output_is_evidence_not_a_report(repo: Path, capsys) -> None:
    _block(repo, "2026-10-14T10:00:01Z")
    out = _run(repo, capsys)
    assert "It is evidence for a person's report, not a report" in out
    assert "it makes no claim about any regulation or standard" in out


def test_an_unreadable_log_file_is_reported_not_crashed_on(repo: Path, capsys) -> None:
    _log(repo).mkdir(parents=True)  # exists, but cannot be read as a file
    doc = _doc(repo, capsys)
    assert [(e["kind"], e["problem"], e["ts"]) for e in doc["timeline"]] == [("unreadable", "unreadable file", "")]
    assert "unknown time  unreadable  problem=unreadable file" in _run(repo, capsys)
