"""`chock install` refuses the retired gemini-cli client and points to antigravity."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from install_fixtures import make_catalog, selection, write_selection

from chock.install import cli
from chock.plugin import cli as plugin_cli
from chock.plugin.bundle_build import CLIENTS

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git required")


@pytest.mark.parametrize("extra", [(), ("--client", "gemini-cli")])
def test_gemini_cli_is_retired_and_install_points_to_antigravity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys, extra: tuple
) -> None:
    """A selection naming gemini-cli, or the flag, exits non-zero with one line naming the antigravity client."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    root, ref = make_catalog(tmp_path)
    base = selection(root, ref)
    picks = [{"from": "catalog", **p} for p in base["policies"]]
    client = "goose" if extra else "gemini-cli"
    data = {**base, "schema": 2, "client": client, "bundle": {"version": "2.0.0"}, "policies": picks}
    path = write_selection(tmp_path / "chock.selection.yaml", data)
    assert cli.main(["--selection", str(path), "--allow-source", str(root), *extra]) == 1
    err = capsys.readouterr().err.splitlines()
    assert len(err) == 1 and "--client antigravity" in err[0], err
    assert not any(home.iterdir())
    assert "gemini-cli" not in cli.CLIENTS and "gemini" not in CLIENTS and "gemini" not in plugin_cli.FORMATS
