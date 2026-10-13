"""Repo-level files `chock marketplace build` owns: llms.txt and the issue-routing config."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from test_marketplace import DEVIN_URL
from test_marketplace import dist as shared_dist

from chock.plugin.marketplace import main as marketplace_main
from chock.plugin.marketplace_repo import ISSUE_CONFIG, LLMS_TXT

CATALOG = "https://github.com/open-coder-ai/chock-catalog"
FRAMEWORK = "https://github.com/open-coder-ai/chock"

built = shared_dist


def test_llms_txt_is_derived_from_the_built_tree(built: Path) -> None:
    marketplace_main(["build", "--dist", str(built)])
    body = (built / LLMS_TXT).read_text(encoding="utf-8")

    assert body.startswith("# Chock plugins\n\n> "), "llms.txt opens with an H1 and a summary blockquote"
    assert "2 plugins are published here: 1 enforce in this client, 1 are advisory." in body
    assert "- [block-destructive-commands](" in body
    assert "block-destructive-commands/README.md): enforces; Block rm -rf and friends" in body
    assert "code-safety/README.md): advisory; Advisory rule with no gate" in body
    assert "(PLUGINS.md)" in body
    assert f"({CATALOG})" in body and f"({FRAMEWORK})" in body
    assert "__" not in body, "every template token is filled"


def test_devin_llms_txt_never_claims_enforcement(built: Path) -> None:
    marketplace_main(["build", "--dist", str(built), "--tree", "devin", "--url", DEVIN_URL])
    body = (built / LLMS_TXT).read_text(encoding="utf-8")

    assert "best-effort" in body
    assert "enforce" not in body


def test_issue_config_routes_away_from_the_generated_repo(built: Path) -> None:
    marketplace_main(["build", "--dist", str(built)])
    config = yaml.safe_load((built / ISSUE_CONFIG).read_text(encoding="utf-8"))

    assert config["blank_issues_enabled"] is False, "an issue filed here cannot be fixed here"
    urls = [link["url"] for link in config["contact_links"]]
    assert f"{CATALOG}/issues/new/choose" in urls
    assert f"{FRAMEWORK}/issues/new/choose" in urls
    assert f"{FRAMEWORK}/security/advisories/new" in urls
    assert all(link["name"] and link["about"] for link in config["contact_links"])


@pytest.mark.parametrize("rel", [LLMS_TXT, ISSUE_CONFIG])
def test_check_catches_missing_and_hand_edited_repo_files(built: Path, rel: Path, capsys) -> None:
    marketplace_main(["build", "--dist", str(built)])
    assert marketplace_main(["build", "--dist", str(built), "--check"]) == 0

    target = built / rel
    target.write_text(target.read_text(encoding="utf-8") + "hand edit\n", encoding="utf-8")
    assert marketplace_main(["build", "--dist", str(built), "--check"]) == 1
    assert f"differs: {rel.as_posix()}" in capsys.readouterr().out

    target.unlink()
    assert marketplace_main(["build", "--dist", str(built), "--check"]) == 1
    assert f"missing: {rel.as_posix()}" in capsys.readouterr().out
