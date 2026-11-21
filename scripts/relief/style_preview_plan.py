#!/usr/bin/env python3
"""List the regional preview windows to capture before rolling out a relief style."""

import argparse
import json
import os
from pathlib import Path
from typing import Any

from skippercast import style
from skippercast.paths import repo_root
from skippercast.relief import render_config
from skippercast.relief.package import decode_document


def _region_plan(region, version) -> dict[str, Any]:
    row = dict(region=region, current=None, status="preview", windows=[])
    try:
        row["current"], _ = render_config.resolve_style(region)
        if row["current"] == version and (render_config._config(region) or {}).get("style") == version:
            row["status"] = "unchanged"
        else:
            row["windows"] = render_config.previews(region)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        row.update(status="invalid", error=str(exc))
    return row


def _plan(root, version, selected) -> dict[str, Any]:
    directory = root / "style"
    # The same admission and token verification used by the render resolver
    # and style_diff; the legacy builder has no token file to load.
    render_config._select({"style": version}, directory)
    if version != render_config.LEGACY:
        style.load(version, directory)

    index = decode_document((root / "dist/regions/index.json").read_bytes())
    regions = [row["id"] for row in index["regions"]]
    for region in selected:
        if region not in regions:
            raise ValueError(f"unknown region: {region}")
    rows = [_region_plan(region, version) for region in dict.fromkeys(selected or regions)]
    summary = dict(regions=len(rows), windows=sum(len(row["windows"]) for row in rows),
                   unchanged=sum(row["status"] == "unchanged" for row in rows),
                   invalid=sum(row["status"] == "invalid" for row in rows))
    return dict(version=version, regions=rows, summary=summary)


def _print_text(plan):
    for row in plan["regions"]:
        current = row["current"] or "unknown"
        suffix = ""
        if row["status"] == "invalid":
            suffix = f" invalid: {row['error']}"
        elif row["status"] == "unchanged":
            suffix = f" unchanged (already on {plan['version']})"
        print(f"{row['region']}: current={current}{suffix}")
        for window in row["windows"]:
            center = json.dumps(window["center"])
            print(f"  {window['id']} center={center} size_m={window['size_m']} zoom={window['zoom']}")
    print(" ".join(f"{key}={count}" for key, count in plan["summary"].items()))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("version", metavar="VERSION")
    parser.add_argument("regions", nargs="*", metavar="REGION", help="defaults to every indexed region")
    parser.add_argument("--root", type=Path, help="repository root (defaults to the configured checkout)")
    parser.add_argument("--json", action="store_true", help="emit a JSON report instead of text")
    args = parser.parse_args(argv)

    previous = os.environ.get("SKIPPERCAST_ROOT")
    if args.root is not None:
        # render_config reads regional inputs via the shared repo_root().
        os.environ["SKIPPERCAST_ROOT"] = str(args.root.expanduser().resolve())
    try:
        report = _plan(repo_root(), args.version, args.regions)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(1, f"{parser.prog}: {exc}\n")
    finally:
        if args.root is not None:
            if previous is None:
                os.environ.pop("SKIPPERCAST_ROOT", None)
            else:
                os.environ["SKIPPERCAST_ROOT"] = previous
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        _print_text(report)
    return int(report["summary"]["invalid"] > 0)


if __name__ == "__main__":
    raise SystemExit(main())
