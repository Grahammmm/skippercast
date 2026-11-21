# Chart basemap: where detail zooms fall short

| Question | Finding |
| --- | --- |
| R1. What does Chart use? | The public pointer named Protomaps **20261011**, with 15 detail boxes at zooms 11–14. |
| R2. What is missing? | **Trinidad–Klamath** is the only indexed region missing from the detail footprint: about **3,347 km²**, its whole configured box. All 16 boxes are inside the overview. |
| R3. What closes the gap? | Owner-run refresh using the 16 current detail boxes. The last measured plan was about **180 MiB**; remeasure the replacement before publishing. |
| R4. Would the check catch it? | It rejects a stale saved plan, but a fresh default check does not look at the published pointer or tiles. |

Source anchors below refer to `c5f07fc5d9516d1d9b0954e7ec47506b343963c8`
(local `origin/main`), except the explicitly pinned historical snapshot and
one dated public manifest GET. No tile data was read.

## R1. Build and detail areas

Chart calls `basemapArchive` on mount and passes the result into its style
(`web/map/chart.ts:203–211,230–231`). The client fetches
`/feeds/tiles/basemap/manifest.json` and builds the archive URL from its `key`;
there is no build date pinned in the client (`web/map/style.ts:25–37`). The
producer writes that pointer to R2 after archive read-back
(`scripts/basemap/regions.py:184–201`). There is no checked-in copy of that
manifest or extraction plan; the tracked `dist/basemap` files are glyphs.
The committed plan documents the **20261008** test build, not the current
pointer (`docs/plans/front-end/design.md:611–619,628–632`). Inspect the
tracked paths with `git ls-tree -r --name-only origin/main -- dist/basemap scripts/basemap`
and `git ls-files '*basemap*manifest*' '*basemap*plan*' '*detail.geojson'`.

Read-only GET `https://skippercast.com/feeds/tiles/basemap/manifest.json`,
**2026-11-21 15:02:25 UTC**, HTTP 200 (selected fields):

> `"key": "tiles/basemap/ca-coast-20261011.pmtiles"`, `"bytes": 189109412`,
> `"built_at": "2026-10-11T16:20:45Z"`, `"source": {"build": "20261011", …}`,
> `"overview": {"bbox": [-125.3, 32.0, -116.55, 42.5], "minzoom": 0, "maxzoom": 10}`,
> `"detail": {"minzoom": 11, "maxzoom": 14}`.

The 15 `regions[].bbox` entries in that response are exactly the 15 rows
marked **Yes** below, including their coordinates. The response's complete
list matched the active and preview `bounds` at the committed “Basemap and
shoreline build and publish” snapshot `223f4ec8c1b225d5b2a440d3ec92cc63701ef604`.
Use that snapshot for offline replay; this is a match of the reported boxes,
not a claim about which commit built the live bytes.

## R2. Every indexed region, against the union of detail boxes

**The 0.5° padding applies only to the overview.** `region_boxes` takes
`bounds` unchanged; `overview_box` pads the combined extent by 0.5° and rounds
outward to 0.01°; `detail_region` uses the original boxes
(`scripts/basemap/regions.py:32–34,59–92,118–128,246–253`). The main result
therefore uses unpadded bounds. The last column separately answers what would
be missing **if** the overview rule were applied to each region individually;
that is not a requirement of the current detail build.

Rows come from `dist/regions/index.json:1`, following each row's `config` to
`regions/<id>/region.json:8–13` (not `fishing_bounds`). Coordinates are west,
south, east, north. Areas are spherical estimates, rounded to the nearest km²;
rows can overlap, so do not sum them. This is extraction footprint, not an
inventory of actual tiles or evidence of what every screen renders.

| Region ID | Current bounds (degrees) | Fully inside detail? | Gap (km², est.) | Gap with per-region 0.5° pad (km², est.) |
| --- | --- | --- | ---: | ---: |
| big-sur-coast | `[-122.2, 35.9, -121.45, 36.3]` | Yes | 0 | 12,190 |
| bodega-point-reyes | `[-123.7, 37.95, -122.7, 38.5]` | Yes | 0 | 12,786 |
| cambria-san-simeon | `[-121.95, 35.45, -120.95, 35.66]` | Yes | 0 | 9,076 |
| crescent-city | `[-124.75, 41.55, -124.05, 42.0]` | Yes | 0 | 19,824 |
| fort-bragg-point-arena | `[-124.4, 38.958333333333336, -123.25, 39.45]` | Yes | 0 | 12,945 |
| humboldt-bay-cape-mendocino | `[-124.8, 40.166666666666664, -123.9, 40.95]` | Yes | 0 | 19,560 |
| monterey-point-sur | `[-122.35, 36.3, -121.65, 36.625]` | Yes | 0 | 10,540 |
| morro-bay | `[-121.95, 34.95, -120.55, 35.85]` | Yes | 0 | 24,598 |
| point-arena-bodega | `[-124.2, 38.4, -122.85, 39.0]` | Yes | 0 | 17,921 |
| point-arguello-conception | `[-121.25, 34.45, -120.35, 35.07]` | Yes | 0 | 13,056 |
| point-reyes-pigeon | `[-123.3, 37.18333333333333, -122.28, 37.95]` | Yes | 0 | 17,644 |
| santa-cruz-monterey-bay | `[-122.75, 36.6, -121.6, 37.18333333333333]` | Yes | 0 | 18,758 |
| shelter-cove-north-mendocino | `[-124.8, 39.45, -123.6, 40.166666666666664]` | Yes | 0 | 17,941 |
| south-big-sur-san-simeon | `[-122.0, 35.66, -121.2, 35.9]` | Yes | 0 | 9,517 |
| southern-california | `[-121.0, 32.5, -117.05, 34.45]` | Yes | 0 | 66,576 |
| trinidad-klamath | `[-124.6, 40.95, -124.0, 41.55]` | No — whole box | 3,347 | 16,674 |

Trinidad–Klamath lies between Humboldt Bay–Cape Mendocino's north edge
(40.95° N) and Crescent City's south edge (41.55° N). It touches both along
parts of its boundary, but none of its interior is in the detail footprint.
It is inside the overview box from R1, so the manifest accounts for coarse
coverage there, not planned detail (R1 response and table above).

<details>
<summary>Offline replay (Python standard library)</summary>

Save this block as a script outside the checkout. Run
`python -B /path/to/replay.py` from the audited checkout. It uses the historical
boxes that matched the GET and prints the complete old list, gap estimates and
the saved-plan check result. Optionally supply the saved response file as the
first argument to verify the exact match.

```python
import json
import math
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path.cwd()))
from scripts.basemap import check_detail, regions

main = 'c5f07fc5d9516d1d9b0954e7ec47506b343963c8'
old = '223f4ec8c1b225d5b2a440d3ec92cc63701ef604'


def git(*args):
    return subprocess.check_output(['git', *args], text=True)


def read(ref, path):
    return json.loads(git('show', f'{ref}:{path}'))


def gap(box, cuts):
    w, s, e, n = box
    xs = sorted({w, e} | {x for a, _, b, _ in cuts for x in (a, b) if w < x < e})
    ys = sorted({s, n} | {y for _, a, _, b in cuts for y in (a, b) if s < y < n})
    # Cut at every box edge and sum only cells outside all boxes.
    return sum(6371.0088**2 * math.radians(c - a) *
               (math.sin(math.radians(d)) - math.sin(math.radians(b)))
               for a, c in zip(xs, xs[1:]) for b, d in zip(ys, ys[1:])
               if not any(x <= a and y <= b and z >= c and t >= d for x, y, z, t in cuts))


assert git('rev-parse', 'HEAD').strip() == main
paths = git('ls-tree', '-r', '--name-only', old, '--', 'regions').splitlines()
boxes = [{'id': r['id'], 'bbox': r['bounds']}
         for path in paths if path.endswith('/region.json')
         if (r := read(old, path))['status'] in regions.PUBLISHED]
overview = {'bbox': regions.overview_box(boxes), 'minzoom': 0, 'maxzoom': 10}
detail = {'minzoom': 11, 'maxzoom': 14}
if len(sys.argv) > 1:
    manifest = json.loads(Path(sys.argv[1]).read_text())
    assert (boxes, overview, detail) == (manifest['regions'], manifest['overview'], manifest['detail'])
print('Old detail boxes:', boxes)
current = regions.region_boxes()
index = read(main, 'dist/regions/index.json')['regions']
assert {r['id'] for r in index} == {r['id'] for r in current}
assert regions.overview_box(current) == overview['bbox']
for row in index:
    box = read(main, row['config'])['bounds']
    cuts = [r['bbox'] for r in boxes]
    assert gap(box, [overview['bbox']]) == gap(box, [r['bbox'] for r in current]) == 0
    print(row['id'], round(gap(box, cuts)), round(gap(regions.overview_box([{'bbox': box}]), cuts)))
try:
    check_detail.check_detail({'regions': boxes, 'overview': overview, 'detail': detail},
                              regions.detail_region(boxes))
except ValueError as error:
    print(error)
```

</details>

## R3. Owner-run refresh (not run here)

Run from current main with the supported `pmtiles` CLI. The existing script
plans from active and preview configs, checks the saved plan, range-extracts
zooms 0–10 over the same overview and zooms 11–14 over the new set of 16
boxes, then merges, verifies and records the manifest
(`scripts/basemap/build_basemap.sh:14–39`). The checked-in settings already
include `trinidad-klamath` (`regions/trinidad-klamath/region.json:3–13`);
no region change is needed. The offline replay shows no indexed box outside
the new unpadded footprint.

```sh
# Owner only: build and measure; latest selects the current Protomaps listing.
bash scripts/basemap/build_basemap.sh latest var/basemap
python scripts/basemap/check_detail.py --dir var/basemap
# Owner only, after reviewing the plan and archive; needs R2 credentials.
python scripts/basemap/regions.py publish --dir var/basemap
```

The build script's optional third argument `--publish` calls the same publish
step (`scripts/basemap/build_basemap.sh:40`). Keep build and publish separate
to review the output first, as the dispatch-only workflow does
(`.github/workflows/basemap.yml:8–18,47–75`). Publishing requires credentials,
uses a content-named key, and updates the pointer only after size/hash read-back
(`scripts/basemap/regions.py:110–115,184–201,263–271`).

**Size estimate:** about 180 MiB as a planning baseline, plus the added
Trinidad–Klamath detail and any change in source data. The committed plan
measured 189,085,436 bytes (180.3 MiB) for 15 boxes: 17 MB overview and
172 MB detail (`docs/plans/front-end/design.md:611–619`). Neither those bytes
nor the 20261011 pointer measure the new 16-box archive. Use the build's
manifest size printout for the actual replacement
(`scripts/basemap/regions.py:255–261`).

## R4. What the checker catches, and the smallest missing test

`python -B scripts/basemap/check_detail.py` reports `22 of 22 regions inside a
 detail box (extract settings only; not archive coverage)` on this main. It
builds plan and geometry from the same configs, not from the live pointer.
`--dir` instead checks the saved plan and GeoJSON: it rejects missing or
changed boxes, incorrect zooms and inconsistent geometry, and requires each
config (including drafts) to fit a single detail box
(`scripts/basemap/check_detail.py:16–59,94–117`). The replay above supplies the
old manifest boxes as a plan and reconstructs its GeoJSON. The checker reports
`Detail boxes differ: missing=['trinidad-klamath'], extra=[], changed=[]`.
Recomputing today's good plan does not detect or fix that published gap.

**Smallest missing check:** compare an independently saved, archive-specific
manifest's z11–14 box union with the indexed config bounds. Run the comparison
on the candidate manifest before publication and on a saved public manifest
when auditing what Chart serves. One offline regression can use two manifest
fixtures with the same overview and zooms: in the stale fixture omit the only
box covering a preview region and require a failure naming that region; add
that box back and require success. The existing missing-box test covers a
*plan*, not the pointer (`tests/unit/test_basemap_detail.py:26–47`). A manifest
comparison catches a stale footprint, not missing tile bytes in an otherwise
good manifest; tile-level proof would also need an archive inspection
(`scripts/basemap/check_detail.py:1–5,115–117`).
