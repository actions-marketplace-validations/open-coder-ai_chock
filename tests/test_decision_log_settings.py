"""LOG-1: the decision log's settings are a person's, and the reader covers both routes."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from decision_log_support import plugin_log, settings, sync_log

from chock import gatelog, gatelog_read
from chock.guardrails.plugin import protect_dir

IMPL = protect_dir() / "implementations"


# -- person-only: the settings in either scope refuse an agent's write -----------------------------------------

AGENT_WRITES = [
    'echo \'{"level": "off"}\' > .chock/chock-log.json',
    'echo \'{"level": "debug"}\' > ~/.chock/chock-log.json',
    "printf x >> $HOME/.chock/chock-log.json",
    "rm .chock/chock-log.json",
    "sed -i s/info/off/ .chock/chock-log.json",
    "cp evil.json .CHOCK/Chock-Log.JSON",
    "python3 -c \"open('.chock/chock-log.json','w').write('{}')\"",
    'echo x > ".chock\\chock-log.json"',
]


@pytest.mark.parametrize("command", AGENT_WRITES)
def test_an_agents_shell_write_to_the_settings_is_refused(tmp_path: Path, command: str) -> None:
    env = {**os.environ, "CHOCK_RAW_COMMAND": command}
    proc = subprocess.run(
        [sys.executable, str(IMPL / "chock-guardrails-protect.py"), *command.split()],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 1, (proc.stdout, proc.stderr)
    assert "may not change .chock/chock-log.json or ~/.chock/chock-log.json" in proc.stdout


@pytest.mark.parametrize("command", ["cat .chock/chock-log.json", "jq . ~/.chock/chock-log.json"])
def test_reading_the_settings_passes(tmp_path: Path, command: str) -> None:
    env = {**os.environ, "CHOCK_RAW_COMMAND": command}
    proc = subprocess.run(
        [sys.executable, str(IMPL / "chock-guardrails-protect.py"), *command.split()],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout


@pytest.mark.parametrize(
    "path",
    [
        ".chock/chock-log.json",
        "{home}/.chock/chock-log.json",
        r"C:\Users\someone\.chock\chock-log.json",
        ".CHOCK/CHOCK-LOG.JSON",
    ],
    ids=["repo", "user", "windows", "case"],
)
def test_an_agents_edit_or_write_to_the_settings_is_refused_in_both_scopes(tmp_path: Path, path: str) -> None:
    material = json.dumps(
        {"event": "pre-tool-use", "repo_root": str(tmp_path), "writes": {path.format(home=tmp_path): "{}"}}
    )
    proc = subprocess.run(
        [sys.executable, str(IMPL / "chock-guardrails-protect-gate.py")],
        cwd=tmp_path,
        input=material,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 1
    assert "log settings" in proc.stderr


# -- the reader: both routes, and the new filters ---------------------------------------------------------------


def _seed(repo: Path, home: Path) -> None:
    sync = [{"policy_id": "a", "verdict": "block"}, {"policy_id": "a", "verdict": "allow"}]
    plugin = [{"policy_id": "b", "verdict": "ask", "route": "plugin", "level": "info"}]
    for path, lines in ((sync_log(repo), sync), (plugin_log(home), plugin)):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "".join(json.dumps({"ts": "2026-10-12T00:00:00Z", **r}) + "\n" for r in lines), encoding="utf-8"
        )


@pytest.mark.parametrize(
    ("flags", "expected"),
    [
        ([], {"a", "b"}),
        (["--route", "sync"], {"a"}),
        (["--route", "plugin"], {"b"}),
        (["--verdict", "ask"], {"b"}),
        (["--level", "info", "--route", "sync"], {"a"}),
        (["--policy", "b"], {"b"}),
    ],
)
def test_the_reader_reads_both_routes_and_filters(
    tmp_path: Path, monkeypatch, capsys: pytest.CaptureFixture[str], flags: list[str], expected: set[str]
) -> None:
    repo, home = tmp_path / "repo", tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    _seed(repo, home)

    assert gatelog.main(["--repo", str(repo), "--json", *flags]) == 0

    summary = json.loads(capsys.readouterr().out)["summary"]
    assert {row["policy_id"] for row in summary} == expected


def test_level_info_drops_the_allows(tmp_path: Path, monkeypatch, capsys) -> None:
    repo, home = tmp_path / "repo", tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    _seed(repo, home)

    gatelog.main(["--repo", str(repo), "--json", "--level", "info"])

    assert json.loads(capsys.readouterr().out)["events"] == 2


def test_the_reader_says_what_is_wrong_with_the_settings(tmp_path: Path, monkeypatch, capsys) -> None:
    repo, home = tmp_path / "repo", tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    settings(repo, max_bytes=10)

    gatelog.main(["--repo", str(repo), "--json"])

    assert "max_bytes must be a whole number from 65536 (64 KiB)" in capsys.readouterr().err


def test_follow_prints_records_as_they_arrive(tmp_path: Path, monkeypatch) -> None:
    repo, home = tmp_path / "repo", tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    _seed(repo, home)
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
        if len(calls) == 2:  # the first call marks where following starts; then a new block lands
            with sync_log(repo).open("a", encoding="utf-8") as fh:
                fh.write(json.dumps({"policy_id": "c", "verdict": "block"}) + "\n")
        return [sync_log(repo)]

    gatelog.follow(paths, lambda record: True, Out(), polls=2)

    assert [json.loads(line)["policy_id"] for line in "".join(printed).splitlines()] == ["c"]
