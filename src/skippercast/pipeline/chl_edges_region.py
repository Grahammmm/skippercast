"""Write a region's chlorophyll-edge feed from its local habitat files."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, NoReturn

from skippercast.pipeline import chl_edges_feed
from skippercast.platform.contracts import atomic_json


class ChlEdgesRegionError(ValueError):
    """A regional input file does not contain valid JSON."""


def _reject_constant(token: str) -> NoReturn:
    raise ValueError(f"{token} is not a JSON value")


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"), parse_constant=_reject_constant)
    except ValueError as exc:
        raise ChlEdgesRegionError(f"{path}: {exc}") from exc


def publish_region(
    region_dir: str | Path, now: datetime, max_age_hours: float, product: str, credit: str,
) -> dict[str, Any]:
    """Build and atomically write chl-edges.json beside the region's habitat manifest."""
    folder = Path(region_dir)
    tiles = [(path.name, _read_json(path))
             for path in sorted((folder / "habitat-tiles").glob("chlorophyll-observation-*.json"))
             if path.is_file()]
    try:
        manifest = _read_json(folder / "habitat-dynamics.json")
    except FileNotFoundError:
        layers = {}
    else:
        layers = manifest.get("layers", {})
    layer = "chlorophyll-observation"
    frames_meta = layers[layer]["frames"] if layer in layers else []
    document = chl_edges_feed.publish(folder.name, tiles, frames_meta, now, max_age_hours, product, credit)
    atomic_json(folder / "chl-edges.json", document, unique_tmp=True)
    return document


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--region-dir", type=Path, required=True)
    parser.add_argument("--max-age-hours", type=float, required=True)
    parser.add_argument("--product", required=True)
    parser.add_argument("--credit", required=True)
    args = parser.parse_args(argv)
    publish_region(args.region_dir, datetime.now(timezone.utc), args.max_age_hours, args.product, args.credit)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
