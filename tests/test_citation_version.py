"""CITATION.cff restates the package version; pin it to pyproject.toml and the installed package."""

import re
import tomllib
from pathlib import Path

import chock

ROOT = Path(__file__).resolve().parents[1]


def _citation_version() -> str:
    match = re.search(r"^version:\s*['\"]?([^'\"\s]+)", (ROOT / "CITATION.cff").read_text(encoding="utf-8"), re.M)
    assert match, "CITATION.cff has no top-level version: line"
    return match.group(1)


def test_citation_version_tracks_the_package():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    assert _citation_version() == project, "bump CITATION.cff version with pyproject.toml"
    assert chock.__version__ == project, "installed chock is stale; reinstall from this tree"
