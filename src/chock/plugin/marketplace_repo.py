"""Repo-level files a plugin repo publishes beside its index: `llms.txt` and the issue-routing config."""

from __future__ import annotations

from pathlib import Path

from chock.emit import write_generated
from chock.plugin.catalog_page import _CATALOG_WORDS, _DEFAULT_CATALOG_WORDS, CATALOG_DOCS, _hooks_rel, _summary
from chock.plugin.marketplace_core import DESCRIPTION, NEWLINE, collect_entries
from chock.plugin.marketplace_devin import DEVIN_DESCRIPTION

LLMS_TXT = Path("llms.txt")
ISSUE_CONFIG = Path(".github/ISSUE_TEMPLATE/config.yml")

_DATA = Path(__file__).resolve().parent / "data"
_LLMS_TEMPLATE = _DATA / "repo-llms.txt.tmpl"
_ISSUE_CONFIG_DATA = _DATA / "repo-issue-config.yml"


def render_llms_txt(dist_root: Path, tree: str) -> str:
    """llms.txt over the built tree: one line per plugin with its posture in this client."""
    dist_root = Path(dist_root)
    words = _CATALOG_WORDS.get(tree, _DEFAULT_CATALOG_WORDS)
    hooks_rel = _hooks_rel(tree)
    lines = []
    enforcing = 0
    for entry in collect_entries(dist_root, tree):
        has_hook = (dist_root / entry["source"] / hooks_rel).exists()
        enforcing += has_hook
        posture = words["row"] if has_hook else "advisory"
        name = entry["name"]
        lines.append(f"- [{name}]({CATALOG_DOCS}/{name}/README.md): {posture}; {_summary(entry['description'])}")
    summary = words["summary"].format(enforcing=enforcing, advisory=len(lines) - enforcing)
    return (
        _LLMS_TEMPLATE.read_text(encoding="utf-8")
        .replace("__DESCRIPTION__", DEVIN_DESCRIPTION if tree == "devin" else DESCRIPTION)
        .replace("__TOTAL__", str(len(lines)))
        .replace("__SUMMARY__", summary)
        .replace("__PLUGINS__", NEWLINE.join(lines))
    )


def render_repo_files(dist_root: Path, tree: str) -> dict[Path, str]:
    """{relative path: content} for every repo-level file this build owns."""
    return {
        LLMS_TXT: render_llms_txt(dist_root, tree),
        ISSUE_CONFIG: _ISSUE_CONFIG_DATA.read_text(encoding="utf-8"),
    }


def write_repo_files(dist_root: Path, tree: str) -> list[Path]:
    """Write the repo-level files; returns the relative paths written."""
    files = render_repo_files(dist_root, tree)
    for rel, content in files.items():
        dest = Path(dist_root) / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        write_generated(dest, content)
    return list(files)


def repo_files_differences(dist_root: Path, tree: str) -> list[str]:
    """Report repo-level files that are missing, stale, or hand-edited."""
    differences: list[str] = []
    for rel, content in render_repo_files(dist_root, tree).items():
        dest = Path(dist_root) / rel
        if not dest.exists():
            differences.append(f"missing: {rel.as_posix()}")
        elif dest.read_text(encoding="utf-8") != content:
            differences.append(f"differs: {rel.as_posix()}")
    return differences
