"""Light startup copies of a region's map files (#617, scripts/startup-budget.json).

The v2 map reads every byte of JSON it fetches before its first view settles.
Three published files carry far more than that view uses, so the platform
build writes a derived copy of each beside the region package, outside
region.assets and the manifest (as the shoreline is), and the map reads the
copy at startup:

- regions/<id>/atlas-marks.json: the atlas without its habitat `areas` and
  `drifts` geometry, which the map draws from tiles (scripts/build_map_tiles.py)
  and the trip planner reads from the full atlas when it opens.
- regions/<id>/search-plan-index.json: each species plan's `profiles` entry (the
  target list's names and methods) without the plans' feature geometry.
- regions/<id>/shoreline-overview.geojson: skippercast.platform.shoreline's
  overview form, drawn below the zoom where the full shoreline loads.

Each copy names the file it came from and that file's SHA-256 under
`derived_from`, so a copy can always be traced to, and checked against, its
original. A region whose original is absent publishes no copy (a stale one is
removed).
"""
from pathlib import Path
import hashlib

from .contracts import atomic_json, read_json, within
from .shoreline import overview_shoreline

SCHEMA_VERSION = 1
ATLAS_MARKS = 'atlas-marks.json'
PLAN_INDEX = 'search-plan-index.json'
SHORELINE_OVERVIEW = 'shoreline-overview.geojson'
# The atlas fields the map reads for its marks, ranking and mark card (web/map/habitat.ts `Atlas`).
ATLAS_KEEP = ('schema_version', 'edition', 'title', 'coverage', 'fishing_depth_limit_ft',
              'source_validation_date', 'source_validation_note', 'sources', 'targets', 'region_id', 'note')
PLAN_KEEP = ('schema_version', 'region_id', 'method', 'reviewed_at', 'profiles', 'coverage_note')


def derived_from(path, relative):
    """The provenance block of a copy: the original's published path and SHA-256."""
    return {'path': relative, 'sha256': hashlib.sha256(Path(path).read_bytes()).hexdigest()}


def atlas_marks(atlas, source):
    """The atlas as the map's marks read it: everything but the habitat area and drift geometry."""
    return {**{k: atlas[k] for k in ATLAS_KEEP if k in atlas}, 'startup_form': 'atlas-marks', 'derived_from': source}


def plan_index(plans, source):
    """The species plans as the target list reads them: each plan's profile, no feature geometry."""
    return {**{k: plans[k] for k in PLAN_KEEP if k in plans}, 'startup_form': 'search-plan-index', 'derived_from': source}


def _publish(target, original, relative, form):
    if original is None or not original.is_file():
        target.unlink(missing_ok=True)
        return None
    atomic_json(target, form(read_json(original), derived_from(original, relative)))
    return target


def publish_startup_forms(root, region, output):
    """Write the region's startup copies to `output`; returns the paths written, relative to dist/."""
    root, output, assets = Path(root), Path(output), region['assets']
    asset = lambda key: within(root / 'dist', assets[key]) if assets.get(key) else None
    written = [
        _publish(output / ATLAS_MARKS, asset('atlas'), assets.get('atlas'), atlas_marks),
        _publish(output / PLAN_INDEX, asset('search_plans'), assets.get('search_plans'), plan_index),
        _publish(output / SHORELINE_OVERVIEW, output / 'shoreline.geojson', f"regions/{region['id']}/shoreline.geojson",
                 overview_shoreline),
    ]
    return [f"regions/{region['id']}/{p.name}" for p in written if p is not None]
