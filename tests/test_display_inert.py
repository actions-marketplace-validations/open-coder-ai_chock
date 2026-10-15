"""GAP-3: a logged string a person reads is inert: no escape, control or bidi character acts, and a forged line stays one."""

from __future__ import annotations

import json
import unicodedata
from pathlib import Path

import pytest

from chock import gatelog, gatelog_read, gatelog_summary
from chock import witness_export as we
from chock.display import inert, inert_all
from chock.doctor import checks
from chock.doctor import cli as doctor_cli
from chock.doctor.targets import Target
from chock.gate.sarif import safe_text
from chock.history.cli import _plain

#: Cursor moves, clear screen and line, colour, OSC 8 link, OSC 52 clipboard, BEL, BS, CR, a bare ESC,
#: C1 CSI and NEL, bidi overrides and isolates, then a newline that would fake a second record.
PAYLOAD = (
    "ok\x1b[2J\x1b[1;1H\x1b[2K\x1b[31mred\x1b[0m"
    "\x1b]8;;https://evil.example\x1b\\link\x1b]8;;\x1b\\"
    "\x1b]52;c;ZXZpbA==\x07\x07\x08\r\x1b \x9b31m\x85\x90"
    "\u202etxt\u202d\u202a\u2066\u2067\u2068\u2069\u200e\u200f\u061c\u2028\u2029\ufeff\u200b"
    "\nFORGED 2026-10-13T00:00:00Z allow"
)
MARKS = ("\\x1b[2J", "\\x1b]8;;https://evil.example", "\\x1b]52;c;", "\\x07", "\\x08", "\\r", "\\x9b", "\\u202e", "\\n")
#: Other languages, and the joiners Persian and emoji need, pass unchanged.
WORLD = "日本語 агент \u0639\u0631\u0628\u06cc\u200c\u0647\u0627 👩\u200d💻 ñ"
AGENT = "claude_code"


def _unsafe(char: str) -> bool:
    return unicodedata.category(char) in {"Cc", "Cs", "Zl", "Zp", "Cf"} and char not in "\u200c\u200d"


def assert_inert(out: str) -> None:
    """Only the renderer's own line breaks remain, no line is forged, and what was removed is marked."""
    lines = out.split("\n")
    assert not [c for line in lines for c in line if _unsafe(c)]
    assert not [line for line in lines if line.lstrip("-|> ").startswith("FORGED")]
    unescaped = out.replace("\\[", "[").replace("\\]", "]")  # markdown escapes brackets
    assert all(mark in unescaped for mark in MARKS)


def _record(**fields: object) -> dict[str, object]:
    base = {
        "ts": "2026-10-13T10:00:00Z",
        "route": "sync",
        "agent": PAYLOAD,
        "event": PAYLOAD,
        "surface": PAYLOAD,
        "policy_id": PAYLOAD,
        "verdict": "block",
        "reason": "fault",
        "trace": {"target": PAYLOAD, "command": PAYLOAD},
        "rules": {PAYLOAD: 1},
        "matches": [f"{PAYLOAD.replace(' ', '_')}.py:3: {PAYLOAD}"],
        "plugin": PAYLOAD,
        "client": PAYLOAD,
        "duration_ms": 5,
    }
    return {**base, **fields}


def _write(path: Path, *records: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    folder = tmp_path / "home"
    folder.mkdir()
    monkeypatch.setenv("HOME", str(folder))
    monkeypatch.setenv("USERPROFILE", str(folder))
    return folder


@pytest.fixture
def repo(tmp_path: Path, home: Path) -> Path:
    root = tmp_path / "repo"
    _write(
        root / ".chock" / "log" / "gate-events.jsonl",
        _record(),
        _record(agent=WORLD, policy_id=WORLD, event=WORLD, surface=WORLD, rules={WORLD: 1}),
    )
    return root


def test_inert_marks_every_unsafe_character_and_keeps_other_languages() -> None:
    shown = inert(PAYLOAD)
    assert_inert(shown)
    assert "\n" not in shown
    assert inert(WORLD) == WORLD
    assert inert("\ud800") == "\\ud800"
    assert inert("\U000e0001") == "\\U000e0001"
    assert inert_all({"k\x1b": ["v\n", 3, ("\x07",)]}) == {"k\\x1b": ["v\\n", 3, ("\\x07",)]}


@pytest.mark.parametrize(
    "argv",
    [
        [],
        ["--by", "agent"],
        ["--by", "rule"],
        ["--by", "policy"],
        ["--by", "event"],
        ["--format", "md"],
        ["--format", "md", "--by", "agent"],
    ],
)
def test_status_log_text_and_markdown_are_inert(repo: Path, capsys: pytest.CaptureFixture[str], argv: list) -> None:
    assert gatelog.main(["--repo", str(repo), *argv]) == 0
    out = capsys.readouterr().out
    assert_inert(out)
    assert WORLD in out


def test_status_log_follow_is_inert(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    log = repo / ".chock" / "log" / "gate-events.jsonl"
    monkeypatch.setattr(gatelog_read, "FOLLOW_INTERVAL", 0)
    printed: list[str] = []

    class Out:
        def write(self, text: str) -> None:
            printed.append(text)

        def flush(self) -> None:
            return None

    calls: list[int] = []

    def paths() -> list[Path]:
        calls.append(1)
        if len(calls) == 2:  # the first call marks where following starts
            with log.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(_record()) + "\n")
        return [log]

    gatelog.follow(paths, lambda record: True, Out(), polls=2)

    out = "".join(printed)
    assert len(out.strip().split("\n")) == 1
    assert not [c for c in out.strip() if _unsafe(c)]
    assert json.loads(out)["agent"] == PAYLOAD  # the record itself is untouched


def test_status_summary_is_inert(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert gatelog_summary.main(["--repo", str(repo)]) == 0
    out = capsys.readouterr().out
    assert_inert(out)
    assert WORLD in out


def test_doctor_is_inert(home: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    found = [
        checks.Check(checks.PASS, "last fired", f"{PAYLOAD} 2026-10-13T00:00:01Z"),
        checks.Check(checks.INFO, "x", WORLD, PAYLOAD),
    ]
    monkeypatch.setattr(checks, "run", lambda *args: found)
    runtime = home / "r.py"
    fake = Target("claude-code", AGENT, "sync", home / PAYLOAD, runtime, runtime, runtime)
    monkeypatch.setattr(doctor_cli, "sync_targets", lambda repo: [fake])
    monkeypatch.setattr(doctor_cli, "plugin_targets", list)

    assert doctor_cli.main(["--repo", str(home)]) == 0

    out = capsys.readouterr().out
    assert_inert(out)
    assert WORLD in out


def test_the_log_on_disk_is_unchanged_by_a_render(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    log = repo / ".chock" / "log" / "gate-events.jsonl"
    before = log.read_bytes()
    gatelog.main(["--repo", str(repo), "--by", "agent"])
    gatelog_summary.main(["--repo", str(repo)])
    capsys.readouterr()
    assert log.read_bytes() == before
    assert json.loads(before.splitlines()[0])["agent"] == PAYLOAD


def test_witness_export_prints_inert_lines_and_keeps_the_file_json(
    tmp_path: Path, home: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(home / ".chock" / "log" / "goose" / "events.jsonl", _record(agent="goose", route="plugin"))
    monkeypatch.setattr(we, "catalog_refs", lambda *args: [])
    out = tmp_path / "bundle.json"

    assert we.main(["export", "--client", "goose", "--out", str(out), "--repo", str(tmp_path)]) == 0

    printed = capsys.readouterr().out
    assert_inert(printed)
    text = out.read_text(encoding="utf-8")
    assert not [c for c in text.rstrip("\n").replace("\n", "") if _unsafe(c)]
    assert json.loads(text)["records"][0]["surface"] == PAYLOAD


def test_sarif_text_is_one_inert_line() -> None:
    shown = safe_text(PAYLOAD, 10_000)
    assert shown.isprintable()
    assert all(mark in shown for mark in MARKS if mark not in ("\\r", "\\n"))  # line breaks become spaces
    assert " FORGED" in shown
    assert safe_text(WORLD) == WORLD


def test_history_paths_are_inert() -> None:
    shown = _plain(PAYLOAD)
    assert_inert(shown)
    assert _plain(WORLD) == WORLD
