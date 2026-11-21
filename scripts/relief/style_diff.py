#!/usr/bin/env python3
"""Compare two verified nearshore style versions and report rebuild inputs.

In JSON, a missing old or new field means a leaf was added or removed;
null is a token value. Digests are reported only when they change.
"""

import argparse
import json
from pathlib import Path

from skippercast import style

STYLE_ROOT = Path(__file__).resolve().parents[2] / "style"
REBUILD_GROUPS = {"baked", "contours", "habitat"}


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _leaves(root, version, entry, rules):
    # Use the loader's own classification, including leaves outside its public views.
    tokens = style._verified_tokens(root, version, entry)
    leaves = {}
    for path, group in style._leaf_groups(tokens, rules).items():
        value = tokens
        for part in path:
            value = value[part]
        leaves[path] = group, value
    return leaves


def _diff(root, before, after):
    entries = json.loads((root / "index.json").read_bytes())["versions"]
    rules = json.loads((root / "groups.json").read_bytes())
    old = _leaves(root, before.version, entries[before.version], rules)
    new = _leaves(root, after.version, entries[after.version], rules)
    changes = {}
    for path in sorted(old.keys() | new.keys()):
        group = (new[path] if path in new else old[path])[0]
        change = {"path": ".".join(path)}
        if path in old:
            change["old"] = old[path][1]
        if path in new:
            change["new"] = new[path][1]
        # JSON comparison distinguishes true from 1, as the loader's digests do.
        if "old" in change and "new" in change and _json(change["old"]) == _json(change["new"]):
            continue
        changes.setdefault(group, []).append(change)

    digests = {}
    for group in style.GROUPS:
        old_digest, new_digest = before.digest(group), after.digest(group)
        if old_digest != new_digest:
            digests[group] = {"old": old_digest, "new": new_digest}
    return {
        "changes": changes,
        "digests": digests,
        "groups_changed": sorted(changes),
        "paint_only": REBUILD_GROUPS.isdisjoint(changes),
    }


def _print_text(report):
    for group in report["groups_changed"]:
        print(f"[{group}]")
        for change in report["changes"][group]:
            old, new = (_json(change[key]) if key in change else "<absent>" for key in ("old", "new"))
            print(f"  {change['path']}: {old} -> {new}")
        if group in report["digests"]:
            digest = report["digests"][group]
            print(f"  digest: {digest['old']} -> {digest['new']}")
    print(f"groups_changed={_json(report['groups_changed'])} paint_only={_json(report['paint_only'])}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("version_a")
    parser.add_argument("version_b")
    parser.add_argument("--root", type=Path, default=STYLE_ROOT, help="style directory (default: checkout style/)")
    parser.add_argument("--json", action="store_true", help="emit a JSON report instead of text")
    args = parser.parse_args(argv)

    try:
        snapshots = []
        for version in (args.version_a, args.version_b):
            try:
                snapshots.append(style.load(version, args.root))
            except KeyError as exc:
                if exc.args == (version,):
                    parser.error(f"unknown style version: {version}")
                raise
        report = _diff(args.root, *snapshots)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"{parser.prog}: {exc}\n")

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        _print_text(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
