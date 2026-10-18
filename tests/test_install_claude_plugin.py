"""`chock install`: the Claude Code build offered to agents agentseam records a witnessed refusal for (CC-3)."""

from __future__ import annotations

import inspect
import shutil
from pathlib import Path

import pytest
from agentseam.vendor_config import VENDOR_CONFIG, loads_claude_plugins
from bundle_fixtures import ADVISORY_ID, GATE_ID, GUARD_ID
from install_fixtures import make_catalog, selection, write_selection

from chock.install import claude_plugin, cli, package, place

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git required")
DATA = claude_plugin.settings()
BUILD = DATA["build_client"]
OFFERED = [cid for cid, e in DATA["clients"].items() if e["routes"]]
NOT_OFFERED = [cid for cid, e in DATA["clients"].items() if "not_offered" in e]


@pytest.fixture
def catalog(tmp_path: Path) -> tuple[Path, str]:
    return make_catalog(tmp_path)


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "home"
    path.mkdir()
    monkeypatch.setenv("HOME", str(path))
    monkeypatch.setenv("USERPROFILE", str(path))
    return path


def _out(catalog: tuple[Path, str], tmp_path: Path, client: str, capsys: pytest.CaptureFixture[str]) -> str:
    root, ref = catalog
    base = selection(root, ref, (GUARD_ID, GATE_ID, ADVISORY_ID))
    data = {
        **base,
        "schema": 2,
        "client": client,
        "bundle": {"version": "2.0.0"},
        "policies": [{"from": "catalog", **p} for p in base["policies"]],
    }
    path = write_selection(tmp_path / "chock.selection.yaml", data)
    assert cli.main(["--selection", str(path), "--allow-source", data["catalog"]["source"]]) == 0
    return capsys.readouterr().out


def test_every_route_is_backed_by_agentseams_witness_today() -> None:
    for cid, entry in DATA["clients"].items():
        assert cid in package.settings()["clients"]
        assert entry["agent"] in VENDOR_CONFIG
        assert claude_plugin.routes(cid) == entry["routes"], cid


def test_no_client_or_agent_is_named_in_the_code() -> None:
    source = inspect.getsource(claude_plugin)
    names = set(VENDOR_CONFIG) | set(package.settings()["clients"])
    assert not [n for n in names if f'"{n}"' in source or f"'{n}'" in source]


@pytest.mark.parametrize("client", OFFERED)
def test_an_agent_with_a_witness_is_offered_the_claude_build_with_its_own_steps(
    catalog, tmp_path: Path, home: Path, capsys, client: str
) -> None:
    out = _out(catalog, tmp_path, client, capsys)
    claude_dest = place.default_dest(BUILD).resolve()
    assert DATA["heading"] in out
    assert f"--client {BUILD}" in out
    for route in DATA["clients"][client]["routes"]:
        assert f"{route['where']}: {route['label']}" in out
        assert route.get("prefer_native", "") in out
    assert str(claude_dest) in out
    for warning in DATA["warnings"]:
        assert f"warning: {warning}" in out


@pytest.mark.parametrize("client", NOT_OFFERED)
def test_an_agent_without_a_witnessed_refusal_gets_no_offer_only_its_caveat(
    catalog, tmp_path: Path, home: Path, capsys, client: str
) -> None:
    out = _out(catalog, tmp_path, client, capsys)
    assert claude_plugin.routes(client) == []
    assert DATA["heading"] not in out
    assert DATA["clients"][client]["not_offered"] in out


def test_the_claude_build_lists_every_agent_it_is_witnessed_in(catalog, tmp_path: Path, home: Path, capsys) -> None:
    out = _out(catalog, tmp_path, BUILD, capsys)
    assert DATA["listing"] in out
    for cid in OFFERED:
        for route in DATA["clients"][cid]["routes"]:
            assert f"{route['where']}: {route['label']}" in out
    for cid in NOT_OFFERED:
        assert DATA["clients"][cid]["not_offered"] in out


def test_the_shared_marketplace_name_is_met_with_its_remove_step(catalog, tmp_path: Path, home: Path, capsys) -> None:
    name = package.settings()["marketplace"]
    out = "\n".join(_out(catalog, tmp_path, cid, capsys) for cid in OFFERED)
    removes = [line for line in out.splitlines() if f"plugin marketplace remove {name}" in line]
    assert removes, "a client whose own build shares the marketplace name must print the remove step"


@pytest.mark.parametrize(
    ("change", "why"),
    [
        ({"witnessed": None}, "no witness"),
        ({"deny_reply": "unknown"}, "deny unsettled"),
        ({"witnessed": "loaded; nothing was refused"}, "witness without the route's quote"),
    ],
)
def test_the_offer_follows_agentseams_data_and_fails_closed(monkeypatch, change: dict, why: str) -> None:
    def fake(agent: str) -> dict | None:
        row = dict(loads_claude_plugins(agent) or {})
        row.update(change)
        return {k: v for k, v in row.items() if v is not None}

    monkeypatch.setattr(claude_plugin, "loads_claude_plugins", fake)
    assert all(claude_plugin.routes(cid) == [] for cid in DATA["clients"]), why
