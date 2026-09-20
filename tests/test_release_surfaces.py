"""The surfaces a release ships beside the wheel say the version being released.

`action.yml`'s default is what an adopter gets with no `version:`; the installation page's
example is what they copy. Both are literals, so a release that bumps `pyproject.toml`
and forgets either ships an install of an older chock under the new tag.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def _released_version() -> str:
    match = re.search(r'^version\s*=\s*"([^"]+)"', (ROOT / "pyproject.toml").read_text(encoding="utf-8"), re.M)
    assert match, "pyproject.toml carries no version"
    return match.group(1)


def test_the_action_installs_the_version_being_released() -> None:
    action = yaml.safe_load((ROOT / "action.yml").read_text(encoding="utf-8"))
    default = str(action["inputs"]["version"]["default"])
    assert default == _released_version(), (
        f"action.yml installs chock=={default} by default; this release is {_released_version()}"
    )


def test_the_installation_example_pins_the_version_being_released() -> None:
    text = (ROOT / "docs" / "installation.md").read_text(encoding="utf-8")
    version = _released_version()
    assert f"uses: open-coder-ai/chock@v{version}" in text, (
        "docs/installation.md's action example names another release"
    )
    assert f"version: {version}" in text, "docs/installation.md's action example installs another release"
