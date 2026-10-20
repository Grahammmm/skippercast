# Land or water for ranked places: method note (CI6-01B step 0)

Status: proposed 2026-10-20 for review. No guard code merges before this note
is reviewed. Evidence:
`research/scripts/assess_land_water_feasibility.py` (read-only), run on
`origin/main` ad1118ef7. The published Morro Bay shoreline there is
byte-identical to b2474f6d. The terrain habitat release is 4c24f963f09b…,
whose detail file matched its manifest sha256 cb4d9cbb…. Output is quoted
below.

## Why

Ranked reef places are Morro Bay's main planning output. Nothing checks that a
ranked waypoint is on water (CI4 B6). The published shoreline is not a land
mask. `platform/shoreline.py` checks the CUSP import as lines inside the region
and publishes them as MultiLineStrings with no topology. A line alone does not
say which side is land.

## What the data is today

Counted on `dist/regions/morro-bay/shoreline.geojson`, comparing vertices
exactly after the 5-decimal rounding:

| Measure | Count |
| --- | --- |
| Features / lines / vertices | 63 / 3,773 / 26,520 |
| Closed lines | 3,593 = 2,289 rings with at least 4 positions + 1,304 zero-area lines with 3 positions (a-b-a, spans 1.1–15.5 m, median 3.6 m) |
| Open lines | 180 |
| Open-line endpoints (360) | 348 shared, all at nodes joining exactly two lines; 2 on the region bounds; 10 dangling |
| Chains after joining at shared endpoints | 13: 7 closed, 6 open |
| HOR_ACC (metres) per line | 4.31 (3,279 lines), 3.14 (397), 0.796 (89), 9 (8); display quantisation 1.96 m |
| zoom-12 tiles NOAA served | 29 of 238 requested; 209 answered 403/404 (`unavailable_tiles`) |
| Proper crossings between different lines | 36: 24 open line × ring, 10 open × zero-area, 2 ring × ring; longest crossing segment 58.4 m |

The 10 dangling endpoints form 5 mutual-nearest pairs. Each pair lies on one
zoom-12 tile edge, where the import clips each line to its own tile:

| Gap | 2 × HOR_ACC | What it is |
| --- | --- | --- |
| 6.4 m | 8.62 m | The mainland. North part runs from the north bound (-121.40932, 35.85) to the row edge at 35.46067; south part runs from there to the south bound (-120.65655, 34.95). The two clips of the same coast differ by 6.4 m. |
| 1.8, 4.5, 2.2 m | 6.28, 8.62, 8.62 m | A lone 2-position line lying along a tile edge. Its own two ends pair; it encloses no area. |
| 56.4 m | 8.62 m | The same kind of line along the column edge at lon -121.28906 (35.68806–35.68857). It encloses no area. |

The data does support a topology, but only with an explicit gap rule and an
explicit rule for which side of the closure is land. A closed ring alone does
not say whether it bounds land or water.

## Candidates

(b) Basemap land polygons (`web/map/currents.ts` `landMask`): rejected.
`engine.ts` `land()` returns `querySourceFeatures` over the basemap tiles
loaded for the current camera. It flattens polygon holes into rings, and
`landMask` rasterises them at quarter scale with a nonzero fill. The result
depends on zoom, pan and tile loading. It does not exist before the map draws,
and the brief ranks without a drawn map. The overlay was reviewed as display
clipping of flow paths. It was not reviewed as an authority for withholding a
place, and it would use a basemap source in a role no review approved.

(a) Topology built from the approved CUSP lines: chosen. The rest of this note
describes it.

## Method (a)

The input is the published shoreline exactly as the platform build writes it.
The CUSP import is unchanged and no new source is added.

1. Sort the lines. A closed line with at least 4 positions is a ring. A closed
   line with fewer positions is zero-area: it counts for the edge test (step 7)
   but not for parity. Every other line is open.
2. Chain open lines at exactly equal endpoints. A node shared by three or more
   lines makes the product unavailable. Today every shared node joins exactly
   two lines.
3. Gap rule. Pair each dangling endpoint with its mutual-nearest dangling
   endpoint.
   - Join when the gap is at most 2 × the larger HOR_ACC of the two lines.
     Reason: both ends are positions on one shoreline, each with the source's
     stated accuracy, so two estimates of the same point can differ by the sum
     of the two accuracies. The tile-edge clips above are this case: 6.4 m
     against 8.62 m. The largest gap this rule can close today is 18 m
     (2 × 9 m). The joining segment counts as shoreline for the edge test.
   - Bridge when the gap is over the join tolerance but at most
     `MAX_BRIDGE_M` = 100 m. A straight segment closes the path for parity,
     and the area near it is unknown:
     - if the bridge closes its own chain (an unclosed "island"), the whole
       loop's bounding box plus `EDGE_M` is unknown, so the interior is never
       called land;
     - if it links two different chains (a coast with a gap), a disc centred
       on the gap's midpoint with radius gap + `EDGE_M` is unknown.
     The 100 m cap is a judgement for the reviewer. Today's only bridge is the
     56.4 m zero-area line, whose unknown area is its own box plus 25 m.
   - An unpaired endpoint, or a gap over 100 m, makes the whole region
     unavailable.
4. Close the mainland. After joining, exactly one path may run from bound to
   bound; more than one makes the product unavailable for now. It is closed
   along the region bounds through the corners on the land side. Each region
   declares those corners in `regions/<id>/region.json` (Morro Bay: south-east,
   then north-east). The build checks that the path's ends lie on the bounds
   edges the declaration implies. The CUSP lines carry no documented
   orientation, so the land side is declared, not inferred.
5. Land side by even-odd. A point is land when an odd number of closed
   polygons contain it: the closed mainland, the rings, and the loops closed by
   joins or bridges. Every published line is a mean-high-water or man-made
   shoreline, so crossing one switches between land and water. A ring bounds
   land when it lies in water (an island or rock) and water when it lies in land
   (a pond or lagoon), whatever direction it was drawn in. Today 2,290 closed
   polygons lie in water and 10 lie in land: six rings 4–11 m across, three
   zero-area joined loops, and one 1.0 km loop at -120.640 to -120.636, 35.131 to 35.140, which this
   rule calls an inland water body. The loop is located here, not identified.
6. Crossings. Lines should not cross, and where they do, parity is wrong only
   inside the smaller of the two lines. For each crossing, the smaller line's
   bounding box plus `EDGE_M` is unknown. Today this covers 36 crossings, each
   a small ring or zero-area line over a longer line.
7. Edge. A point within `EDGE_M` = 25 m of any line, join or bridge is edge,
   and edge is handled as unknown. The worst stated error in the file is
   9 m (HOR_ACC) + 1.96 m (one display unit) + 0.55 m (rounding) = 11.5 m.
   Doubling that allows for the tiles' undocumented generalisation (import
   limitation 2), giving 23 m, rounded up to 25 m. The build makes the product
   unavailable when a file's 2 × (max HOR_ACC + quantisation + 0.55) exceeds
   `EDGE_M`. Tiny rings and zero-area lines (most under 25 m across) are
   therefore unknown over their whole extent.
8. Coverage. Only the tiles NOAA served count. A point is unknown when it lies
   in a tile listed in `unavailable_tiles`, outside the region bounds, or when
   its coordinates are not finite. Parity in a served tile stays sound for two
   reasons. A ring that ran into an unserved tile would leave dangling
   endpoints on that tile edge, which step 3 either pairs or rejects. A ring
   entirely inside an unserved tile cannot contain a point outside that tile.
9. Malformed input makes the product unavailable, so every point is unknown.
   This covers a line with fewer than 2 positions, non-numeric or non-finite
   coordinates, a node of degree 3 or more, an unpaired endpoint, more than
   one bound-to-bound path, a gap over 100 m, or a missing shoreline file. The
   classifier also rejects a product file of the wrong shape and treats it as
   unavailable. Malformed input is never land and never water.

There are three outcomes: water, land, and unknown. Unknown carries a reason:
`outside-bounds`, `unserved-tile`, `edge`, `gap`, `crossing` or
`unavailable`.

Default behaviour is fail-closed. Land and unknown candidates are withheld,
and the basis states the count: "N spots withheld: land/water not confirmed."
N counts the candidates that passed every other filter, not only the shown
top four.

## Where it goes (after review)

- `src/skippercast/platform/land_water.py`, run by
  `PYTHONPATH=src python -m skippercast.platform.build`, writes
  `dist/regions/<id>/land-water.json`. That file is generated output: the
  closed polygons, the unknown zones (boxes and discs), the zero-area and
  edge-only lines, the served-tile list, the constants and provenance. Raw
  size is about the shoreline's (~0.6 MB for 26.5k vertices). It loads only
  when a ranked list or planner needs it, never at first paint. The PR will
  add a size note against `scripts/startup-budget.json`.
- `web/land-water.ts` classifies a point. Ranking calls it from
  `web/ranking.ts` (terrain and atlas sources), `dist/spot-ranking.js`
  `bestSpots` (the planner) and `web/map/ranked.ts` (the Chart's pins).
- Tests:
  - a pytest of the builder on injected geometry;
  - `node --test` cases for the classifier and ranking. The fixture has a
    mainland crossing the region edge to edge, an island ring and an enclosed
    water ring. The cases cover a mainland interior point, an island interior
    point, an offshore point, a point in the water ring (water), an edge point,
    a point just beyond the edge, a gap wider than the join tolerance, a
    missing file, and malformed geometry (empty line, ring under 4 positions,
    unclosed island, non-numeric coordinates).

## Committed-data check (acceptance item 5, preview)

Today's waypoints from both sources: 132 atlas targets (`dist/data/atlas.json`)
and the 24 Morro Bay terrain waypoints in release 4c24f963. Of these 156:

- 153 are water: 130 atlas and 23 terrain.
- None is land, and none is within 50 m of a line (the nearest classified
  waypoint is 634.7 m away).
- 3 are unknown because they lie in a tile NOAA did not serve, so they would
  be withheld:
  - atlas SC26-002 (-120.854196, 35.17118; tile 12/672/1620);
  - atlas SC26-116 (-121.026886, 35.456924; 12/670/1616);
  - terrain sc-hab-morro-bay-r07-8e97c7b06caffe64 (-120.86969, 35.17334;
    12/672/1620).
- With the opposite closure (south-west, north-west) all 156 are land. The
  surveyed depths at these waypoints therefore agree only with the declared
  east side.

This check does not show that the guard works; the synthetic tests do.

## Decisions for the reviewer

1. Method (a), with (b) rejected for the reasons above.
2. Constants: join tolerance 2 × HOR_ACC, `MAX_BRIDGE_M` 100 m, `EDGE_M` 25 m.
3. Regions with no shoreline product, which is every region except Morro Bay
   today:
   - (Recommended, the card's default) fail-closed: their ranked places are
     withheld and the basis gives the count. Today's release has 22 terrain
     waypoints in `monterey-point-sur` and 2 in `cambria-san-simeon`; their
     lists would be empty until those regions get a CUSP import. That import
     is a separate data card, not this one.
   - Alternative: rank them as today with the basis "Land/water not checked
     in this region". No guarantee would be shown, but a place on land could
     still be ranked there.
4. Points in unserved tiles are unknown, so the three waypoints above are
   withheld (fail-closed). An alternative would treat an unserved tile as
   water when no line touches its edges. That rests on the import's
   limitation 3 ("absence is not proof of no shoreline"), so it is not
   recommended.
5. Each region declares its land corners in `region.json`.

## Limits

- No new source, and no change to the CUSP import.
- The result is a planning screen for ranked places. It is not a navigation
  boundary, a legal shoreline or a tidal line: the lines are historical mean
  high water dated 1994-02-28 to 2010-11-01.
- CI2's Bay pins remain a QA question.
