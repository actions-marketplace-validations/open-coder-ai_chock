"""`chock marketplace` -- emit marketplace index files over a built plugin tree."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from chock.emit import write_generated
from chock.plugin.catalog_page import CATALOG_PAGE, catalog_page_differences, render_catalog_page
from chock.plugin.marketplace_core import (
    CLAUDE_TREE,
    DESCRIPTION,
    INDEX_PATHS,
    LOCKFILE_NAME,
    NEWLINE,
    TREES,
    build_index,
    build_lock,
    collect_entries,
    index_differences,
    lock_differences,
)
from chock.plugin.marketplace_devin import (
    DEVIN_ROOT_MANIFEST_REL,
    build_devin_root_manifest,
    devin_root_manifest_differences,
)

__all__ = ["CATALOG_PAGE", "DESCRIPTION", "INDEX_PATHS", "LOCKFILE_NAME", "main"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="chock marketplace",
        description="Emit marketplace index files over a plugin tree built by `chock plugin build`",
    )
    parser.add_argument("action", choices=["build"], help="build: write the index files")
    parser.add_argument("--dist", default=".", help="Distribution root containing plugins/<id>/ directories")
    parser.add_argument("--name", default="chock", help="Marketplace name clients address plugins with")
    parser.add_argument(
        "--tree",
        choices=sorted(TREES),
        default=CLAUDE_TREE,
        help="Which format tree to index; each vendor repo indexes only its own (default: claude)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Report index files that are missing or stale, and exit non-zero. Writes nothing.",
    )
    parser.add_argument(
        "--url",
        default=None,
        help="Git URL of this marketplace's own repo. Required for --tree devin's root meta-plugin; "
        "chock does not read `git remote` for this.",
    )
    args = parser.parse_args(argv)

    if args.tree == "devin" and not args.url:
        print(
            "--tree devin requires --url: its root meta-plugin's git-subdir entries need this "
            "marketplace's own repo URL, and chock will not guess it from `git remote`.",
            file=sys.stderr,
        )
        return 2

    dist_root = Path(args.dist).resolve()
    entries = collect_entries(dist_root, args.tree)
    if not entries:
        print(f"No plugin manifests under {dist_root / args.tree}; refusing to write an empty index.", file=sys.stderr)
        return 2

    if args.check:
        differences = (
            (
                devin_root_manifest_differences(dist_root, args.name, args.url)
                if args.tree == "devin"
                else index_differences(dist_root, args.name, args.tree)
            )
            + lock_differences(dist_root)
            + catalog_page_differences(dist_root, args.tree)
        )
        if differences:
            print(f"Marketplace index is out of date ({len(differences)} difference(s)):")
            for line in differences:
                print(f"  {line}")
            print("Run `chock marketplace build` and commit the result.")
            return 1
        print(f"Marketplace index matches the plugin tree ({len(entries)} plugins).")
        return 0

    if args.tree == "devin":
        content = json.dumps(build_devin_root_manifest(dist_root, args.name, args.url), indent=2) + "\n"
        dest = dist_root / DEVIN_ROOT_MANIFEST_REL
        dest.parent.mkdir(parents=True, exist_ok=True)
        write_generated(dest, content)
        print(f"Wrote {DEVIN_ROOT_MANIFEST_REL.as_posix()}: a meta-plugin referencing {len(entries)} plugins")
    else:
        index_paths = TREES[args.tree]["index_paths"]
        content = json.dumps(build_index(dist_root, args.name, args.tree), indent=2) + "\n"
        for rel in index_paths:
            dest = dist_root / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            write_generated(dest, content)
        print(f"Indexed {len(entries)} plugins into {' and '.join(p.as_posix() for p in index_paths)}")

    lock = json.dumps(build_lock(dist_root), indent=2, sort_keys=True) + NEWLINE
    write_generated(dist_root / LOCKFILE_NAME, lock)

    write_generated(dist_root / CATALOG_PAGE, render_catalog_page(dist_root, args.tree))

    print(f"Wrote {LOCKFILE_NAME}: sha256 per published plugin directory")
    print(f"Wrote {CATALOG_PAGE}: {len(entries)} plugins with their posture")
    return 0
