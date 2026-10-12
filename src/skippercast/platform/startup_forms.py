"""Light startup copies of a region's map files (#617, scripts/startup-budget.json).

The v2 map reads every byte of JSON it fetches before its first view settles.
Three published files carry far more than that view uses, so the platform
build writes a derived copy of each beside the region package, outside
region.assets and the manifest (as the shoreline is), and the map reads the
copy at startup:

- regions/<id>/atlas-marks.json: the atlas without its habitat `areas` and
  `drifts` geometry, which the map draws from tiles (scripts/build_map_tiles.py)
  and the trip planner reads from the full atlas when it opens.
- regions/<id>/search-plan-index.json: the plans without their feature
  geometry (the target list reads `profiles`: names and methods).
- regions/<id>/shoreline-overview.geojson: skippercast.platform.shoreline's
  overview form, drawn below the zoom where the full shoreline loads.
- regions/<id>/poster.svg: that overview as one SVG path in Web Mercator
  pixels at POSTER_ZOOM (512-pixel tiles, as MapLibre's), with the region's
  north-west corner at the origin. The map draws it over the empty Chart,
  aligned to the opening camera, until MapLibre's first complete frame
  (web/map/poster.ts), so the coast shows before the map engine has loaded.

Each copy names the file it came from and that file's SHA-256 under
`derived_from`, so a copy can always be traced to, and checked against, its
original. A region whose original is absent publishes no copy (a stale one is
removed).
"""
from pathlib import Path
import hashlib
import math
from xml.sax.saxutils import escape

from .contracts import atomic_json, read_json, within
from .shoreline import overview_shoreline

SCHEMA_VERSION = 1
ATLAS_MARKS = 'atlas-marks.json'
PLAN_INDEX = 'search-plan-index.json'
SHORELINE_OVERVIEW = 'shoreline-overview.geojson'
POSTER = 'poster.svg'
POSTER_ZOOM = 12
# The geometry each copy leaves out; every other field is kept, so a new field reaches the map unchanged.
ATLAS_DROP = ('areas', 'drifts')
PLAN_DROP = ('features',)


def derived_from(path, relative):
    """The provenance block of a copy: the original's published path and SHA-256."""
    return {'path': relative, 'sha256': hashlib.sha256(Path(path).read_bytes()).hexdigest()}


def atlas_marks(atlas, source):
    """The atlas as the map's marks read it: everything but the habitat area and drift geometry."""
    return {**{k: v for k, v in atlas.items() if k not in ATLAS_DROP}, 'startup_form': 'atlas-marks', 'derived_from': source}


def plan_index(plans, source):
    """The species plans as the target list reads them: each plan's profile, no feature geometry."""
    return {**{k: v for k, v in plans.items() if k not in PLAN_DROP}, 'startup_form': 'search-plan-index', 'derived_from': source}


def mercator(longitude, latitude, zoom=POSTER_ZOOM):
    """Web Mercator world pixels at `zoom` for 512-pixel tiles (MapLibre's)."""
    size = 512 * 2 ** zoom
    sin = math.sin(math.radians(latitude))
    return (longitude + 180) / 360 * size, (0.5 - math.log((1 + sin) / (1 - sin)) / (4 * math.pi)) * size


def poster_svg(overview, source):
    """The overview shoreline as one integer-pixel SVG path (see the module notes); deterministic text."""
    west, south, east, north = overview['provenance']['bounds']
    x0, y0 = mercator(west, north)
    x1, y1 = mercator(east, south)
    parts = []
    for feature in overview['features']:
        for line in feature['geometry']['coordinates']:
            points = []
            for lon, lat in line:
                x, y = mercator(lon, lat)
                p = (round(x - x0), round(y - y0))
                if not points or p != points[-1]:
                    points.append(p)
            if len(points) < 2:
                continue
            (sx, sy), steps = points[0], []
            for (ax, ay), (bx, by) in zip(points, points[1:]):
                steps.append(f'{bx - ax} {by - ay}')
            parts.append(f'M{sx} {sy}l' + ' '.join(steps))
    credit = overview['provenance'].get('attribution', 'NOAA NGS CUSP shoreline')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {round(x1 - x0)} {round(y1 - y0)}" '
            f'data-zoom="{POSTER_ZOOM}" data-west="{west}" data-north="{north}" data-sha256="{source["sha256"]}">'
            f'<title>{escape(credit)}</title><path d="{"".join(parts)}"/></svg>\n')


def _publish_text(target, original, relative, form):
    if original is None or not original.is_file():
        target.unlink(missing_ok=True)
        return None
    target.write_text(form(read_json(original), derived_from(original, relative)), encoding='utf-8')
    return target


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
    # After the overview: the poster is drawn from it, and names its checksum.
    written.append(_publish_text(output / POSTER, output / SHORELINE_OVERVIEW,
                                 f"regions/{region['id']}/{SHORELINE_OVERVIEW}", poster_svg))
    return [f"regions/{region['id']}/{p.name}" for p in written if p is not None]
