"""Tree-generic marketplace logic: index files, the lockfile, and the catalog page.

Split out of marketplace.py to keep both files under the 300-line review budget. Never
imports marketplace_devin, so devin's own import of this module stays acyclic.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agentseam import packaging

from chock.lock import compute_pack_hash
from chock.vendors import CHOCK_AGENT

OWNER = {"name": "open-coder-ai", "url": "https://github.com/open-coder-ai"}

TREES: dict[str, dict[str, Any]] = {
    "claude": {
        "index_paths": (Path(".claude-plugin/marketplace.json"), Path(".github/plugin/marketplace.json")),
        "style": "claude",
    },
    "codex": {
        "index_paths": (Path(".claude-plugin/marketplace.json"),),
        "style": "claude",
    },
    "cursor": {
        "index_paths": (Path(".cursor-plugin/marketplace.json"),),
        "style": "cursor",
    },
    # Devin has no index-file format: the vendor's own template (CognitionAI/team-marketplace-
    # template) is a repo whose root .devin-plugin/plugin.json IS the marketplace, a meta-plugin
    # whose optionalPlugins point git-subdir entries at each plugin's own folder. index_paths
    # stays empty; marketplace.main() routes "devin" to marketplace_devin instead.
    "devin": {"index_paths": (), "style": "devin"},
}

CLAUDE_TREE = "claude"
INDEX_PATHS = TREES["claude"]["index_paths"]


def _manifest_rel(tree: str) -> str:
    """This tree's plugin manifest path, from agentseam's packaging layout."""
    return packaging.layout(CHOCK_AGENT[tree])["manifest"]


def collect_entries(dist_root: Path, tree: str = CLAUDE_TREE) -> list[dict[str, Any]]:
    """Index entries from the built plugin manifests, sorted by directory name."""
    manifest_rel = _manifest_rel(tree)
    entries: list[dict[str, Any]] = []
    for manifest_path in sorted(Path(dist_root).glob(f"{tree}/*/{manifest_rel}")):
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        package_dir = manifest_path.parent.parent if manifest_rel.count("/") else manifest_path.parent
        entry: dict[str, Any] = {
            "name": data["name"],
            "source": f"./{tree}/{package_dir.name}",
            "description": data.get("description", ""),
        }
        if data.get("version"):
            entry["version"] = data["version"]
        entries.append(entry)
    return entries


DESCRIPTION = (
    "Chock policies packaged as installable plugins. Generated from the chock-catalog; "
    "each plugin states whether it enforces in this client or is advisory."
)


def build_index(dist_root: Path, name: str, tree: str = CLAUDE_TREE) -> dict[str, Any]:
    entries = collect_entries(dist_root, tree)
    if TREES[tree]["style"] == "cursor":
        return {
            "name": name,
            "owner": {"name": OWNER["name"]},
            "metadata": {"description": DESCRIPTION},
            "plugins": [{k: e[k] for k in ("name", "source", "description")} for e in entries],
        }
    return {
        "name": name,
        "owner": OWNER,
        "description": DESCRIPTION,
        "plugins": entries,
    }


LOCKFILE_NAME = "chock-market.lock"

NEWLINE = chr(10)


def build_lock(dist_root: Path) -> dict[str, Any]:
    """Hash every plugin directory in every format tree, sorted for a stable diff."""
    dist_root = Path(dist_root)
    plugins: dict[str, str] = {}
    for manifest in sorted(dist_root.glob("*/*/")):
        if not manifest.is_dir() or manifest.parts[-2].startswith("."):
            continue
        rel = manifest.relative_to(dist_root).as_posix()
        plugins[rel] = compute_pack_hash(manifest)
    return {"lockfile_version": 1, "plugins": plugins}


def lock_differences(dist_root: Path) -> list[str]:
    """Report where the on-disk lockfile disagrees with the tree it describes."""
    content = json.dumps(build_lock(dist_root), indent=2, sort_keys=True) + NEWLINE
    dest = Path(dist_root) / LOCKFILE_NAME
    if not dest.exists():
        return [f"missing: {LOCKFILE_NAME}"]
    return [] if dest.read_text(encoding="utf-8") == content else [f"differs: {LOCKFILE_NAME}"]


CATALOG_PAGE = "PLUGINS.md"

CATALOG_DOCS = "https://github.com/open-coder-ai/chock-catalog/blob/main/docs"

#: Summaries longer than this are truncated (at _SUMMARY_TRUNCATE_AT) with an ellipsis.
_SUMMARY_MAX_LEN = 99
_SUMMARY_TRUNCATE_AT = 96


def _summary(description: str) -> str:
    """First sentence of the description, with the bracketed posture note stripped."""
    text = description.split("[", maxsplit=1)[0].strip()
    first = text.split(". ")[0].strip().rstrip(".")
    return (first[:_SUMMARY_TRUNCATE_AT].rstrip() + "...") if len(first) > _SUMMARY_MAX_LEN else first


def _hooks_rel(tree: str) -> str:
    """This tree's hooks-file path, relative to a package directory (root or nested)."""
    return packaging.supports(CHOCK_AGENT[tree], packaging.HOOKS)


#: Per-tree catalog-page vocabulary. Devin gets its own row/summary/explain text so the page
#: never claims "enforce"/"block" for a fail-open, best-effort client; others keep the original.
_CATALOG_WORDS: dict[str, dict[str, str]] = {
    "devin": {
        "row": "best-effort",
        "summary": "{enforcing} are best-effort in this client, {advisory} are advisory",
        "explain": (
            "A best-effort package ships a `PreToolUse` hook, a guard script and a stdlib-only "
            "adapter. Devin's own docs call plugin hooks fail-open by design -- a hook that "
            "fails to load or run lets the session continue without it -- so this is not a "
            "guarantee. An advisory package ships skill text; nothing stops a violation."
        ),
    },
}
_DEFAULT_CATALOG_WORDS = {
    "row": "enforces",
    "summary": "{enforcing} enforce in this client, {advisory} are advisory",
    "explain": (
        "An enforcing package ships a `PreToolUse` hook, a guard script and a stdlib-only "
        "adapter, and can deny a shell command before the client runs it. It fails open when "
        "`python3` or a usable `bash` is unavailable, and asks -- on Codex CLI, denies -- when "
        "the guard crashes. An advisory package ships skill text; nothing stops a violation."
    ),
}


def render_catalog_page(dist_root: Path, tree: str = CLAUDE_TREE) -> str:
    """The generated catalog: how many packages enforce, how many advise, and which."""
    dist_root = Path(dist_root)
    words = _CATALOG_WORDS.get(tree, _DEFAULT_CATALOG_WORDS)
    rows = []
    enforcing = 0
    manifest_rel = _manifest_rel(tree)
    hooks_rel = _hooks_rel(tree)
    for manifest_path in sorted(dist_root.glob(f"{tree}/*/{manifest_rel}")):
        pkg = manifest_path.parent.parent
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        has_hook = (pkg / hooks_rel).exists()
        enforcing += 1 if has_hook else 0
        posture = words["row"] if has_hook else "advisory"
        name = data["name"]
        rows.append(
            f"| [`{name}`]({CATALOG_DOCS}/{name}/README.md) "
            f"| {data.get('version', '-')} | {posture} | {_summary(data.get('description', ''))} |"
        )

    total = len(rows)
    summary = words["summary"].format(enforcing=enforcing, advisory=total - enforcing)
    lines = [
        "# Published plugins",
        "",
        "<!-- generated by `chock marketplace build`; edits are overwritten -->",
        "",
        f"**{total} policies are published here: {summary}.**",
        "",
        *words["explain"].splitlines(),
        "",
        "| plugin | version | in this client | what it does |",
        "| :--- | :--- | :--- | :--- |",
        *rows,
        "",
        f"Each name links to its full policy page in the [catalog]({CATALOG_DOCS}): what it",
        "solves, how it works, and its honest reach.",
        "",
    ]
    return NEWLINE.join(lines)


def catalog_page_differences(dist_root: Path, tree: str = CLAUDE_TREE) -> list[str]:
    """Report a catalog page that disagrees with the tree it describes."""
    dest = Path(dist_root) / CATALOG_PAGE
    content = render_catalog_page(dist_root, tree)
    if not dest.exists():
        return [f"missing: {CATALOG_PAGE}"]
    return [] if dest.read_text(encoding="utf-8") == content else [f"differs: {CATALOG_PAGE}"]


def index_differences(dist_root: Path, name: str, tree: str = CLAUDE_TREE) -> list[str]:
    """Report where the on-disk index files disagree with the plugin tree."""
    content = json.dumps(build_index(dist_root, name, tree), indent=2) + "\n"
    differences: list[str] = []
    for rel in TREES[tree]["index_paths"]:
        dest = Path(dist_root) / rel
        if not dest.exists():
            differences.append(f"missing: {rel.as_posix()}")
        elif dest.read_text(encoding="utf-8") != content:
            differences.append(f"differs: {rel.as_posix()}")
    return differences
