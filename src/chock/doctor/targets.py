"""Where chock's hooks are installed: the sync route's vendored runtimes in a repo, and `chock install` plugins."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from chock import vendors
from chock.hooks import launch
from chock.hooks.in_agent_install import WIRED_VENDORS, agent_hooks_rel
from chock.hooks.runtime_vendor import runtime_rel
from chock.install import package, place
from chock.plugin import store
from chock.plugin.clients import CLIENTS
from chock.plugin.store import SCRIPTS_TEMPLATE

ROUTE_SYNC, ROUTE_PLUGIN = "sync", "plugin"


@dataclass(frozen=True)
class Target:
    """One installed hook set: who it is for, which route, and the files a check reads."""

    client: str
    agent: str
    route: str
    root: Path
    runtime: Path
    launcher: Path
    hooks: Path
    marker: dict[str, Any] | None = None

    def wired(self) -> bool:
        """Whether the hooks file the client reads names this runtime."""
        try:
            text = self.hooks.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return False
        name = self.runtime.name if self.route == ROUTE_PLUGIN else runtime_rel(self.agent).as_posix()
        return name in text


def _sync_hooks(agent: str) -> Path:
    return agent_hooks_rel(agent) if agent in vendors.AGENT_HOOKS_VENDORS else Path(vendors.config_path(agent))


def sync_targets(repo: Path) -> list[Target]:
    """Every wirable agent whose vendored runtime or config entry is in `repo`."""
    found = []
    for agent in WIRED_VENDORS:
        target = Target(
            agent,
            agent,
            ROUTE_SYNC,
            repo,
            repo / runtime_rel(agent),
            repo / launch.LAUNCHER_REL,
            repo / _sync_hooks(agent),
        )
        if target.runtime.exists() or target.wired():
            found.append(target)
    return found


def _hooks_file(fmt: str) -> str:
    """The file a format's client reads hooks from: its hooks document, or (kimi) the manifest that carries it."""
    client = CLIENTS[fmt]
    shape = store.layout(client.own_layout) if client.own_layout else None
    manifest, hooks, _skill = client.layout()
    return str(manifest) if shape and shape.get("hooks_key") else hooks


def _bundles(client_id: str, data: dict[str, Any]) -> list[Path]:
    dest = place.default_dest(client_id)
    base = dest / data["format"] if data["layout"] == place.MARKETPLACE else dest
    return sorted(path for path in base.glob("*") if (path / package.MARKER).is_file()) if base.is_dir() else []


def plugin_targets() -> list[Target]:
    """Every plugin `chock install` built into a client's default folder."""
    found = []
    for client_id, data in package.settings()["clients"].items():
        agent = CLIENTS[data["format"]].agent
        for folder in _bundles(client_id, data):
            marker = package.read_marker(folder)
            if marker is None or marker.get("client") != client_id:
                continue
            runtime = folder / SCRIPTS_TEMPLATE.format(name=f"{agent}.py")
            launcher = folder / SCRIPTS_TEMPLATE.format(name=launch.PLUGIN_LAUNCHER)
            found.append(
                Target(
                    client_id,
                    agent,
                    ROUTE_PLUGIN,
                    folder,
                    runtime,
                    launcher,
                    folder / _hooks_file(data["format"]),
                    marker,
                )
            )
    return found


def marker_engine(target: Target) -> dict[str, Any]:
    """The engine block a plugin's install marker recorded at build time; empty when there is none."""
    block = (target.marker or {}).get(package.MARKER_KEY)
    engine = block.get("engine") if isinstance(block, dict) else None
    return engine if isinstance(engine, dict) else {}
