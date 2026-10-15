"""GAP-2b: the `target` fingerprint and `actor` client never carry a name, a path or a byte that is not safe to log."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from history_support import SECRET
from test_decision_principal import ROUTES, SESSION, _call, _sha

from chock.gate import decision_target


@pytest.fixture
def home(tmp_path: Path) -> Path:
    folder = tmp_path / "home"
    folder.mkdir()
    return folder


@pytest.mark.parametrize(
    ("command", "program"),
    [
        ("./secret-abc123 --flag", "-"),
        ('"/home/me/my tool" run', "-"),
        (">out.txt echo hi", "-"),
        ("/usr/local/bin/deploy --to prod", "-"),
        ("/usr/bin/git status", "git"),
        ("python3 -m pytest", "python3"),
        ("mytool2 run", "-"),
        ("mytool run", "mytool"),
    ],
)
def test_the_program_is_an_allowlisted_name_or_a_plain_word_without_digits(command: str, program: str) -> None:
    assert decision_target.dlog_command_print(command) == f"{program} {_sha(command)}"


@pytest.mark.skipif(os.name == "nt", reason="a Windows path read on a POSIX host")
@pytest.mark.parametrize(
    "path", [r"C:\Users\me\secret-notes.txt", "C:secret-notes.txt", r"\\server\share\secret-notes.txt"]
)
def test_a_windows_path_on_posix_is_outside_and_hashed(tmp_path: Path, path: str) -> None:
    printed = decision_target.dlog_path_print(path, str(tmp_path), str(tmp_path))

    assert printed == "outside:" + _sha(path)


@pytest.mark.parametrize("route", ROUTES)
def test_an_unencodable_path_still_writes_its_line(tmp_path: Path, home: Path, route: str) -> None:
    file_path = str(tmp_path / "repo" / "caf\udce9.txt")
    [record] = _call(tmp_path, home, route, "Write", {"file_path": file_path, "content": "x"}, session_id=SESSION)

    assert record["target"] == "caf\\udce9.txt"


def test_an_mcp_target_is_redacted_and_capped() -> None:
    class Call:
        event, tool, command, path = "pre_tool", f"mcp__{SECRET}__{'t' * 300}", None, None

    printed = decision_target.dlog_target(Call(), None)

    assert SECRET not in printed
    assert printed.startswith("[redacted]/t")
    assert len(printed) == 128


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize(
    ("client", "expected"),
    [("Claude Code\x1b[31m/../x", "claudecode31mx"), ("c" * 40, "c" * 32), ("!!!", "claude_code")],
)
def test_client_type_is_sanitised_before_it_names_the_actor(
    tmp_path: Path, home: Path, route: str, client: str, expected: str
) -> None:
    [record] = _call(tmp_path, home, route, "Bash", {"command": "ls"}, session_id=SESSION, client_type=client)

    assert record["actor"] == f"agent:{expected}"
    assert record.get("client", expected) == expected
