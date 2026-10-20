# Land or water for ranked places: method note (CI6-01B step 0)

Status: approved at step 0 (round 2, sol-reviewer, STEP0 APPROVED at 90aa40ba,
2026-10-20) and implemented as described under "Implementation" below. Evidence
comes from `research/scripts/assess_land_water_feasibility.py` (read-only). It ran on the
published Morro Bay shoreline, which is byte-identical from b2474f6d through
`origin/main` 573b6682a, and on terrain habitat release 4c24f963f09b…, whose
detail file matched its manifest sha256 cb4d9cbb…. Every topology test in it is
exact: coordinates are compared as integers on the published 5-decimal grid.
`--self-test` runs the same rules on injected geometry. Output is quoted below.

## Why

Ranked reef places are Morro Bay's main planning output. Nothing checks that a
ranked waypoint is on water (CI4 B6). The published shoreline is not a land
mask. `platform/shoreline.py` checks the CUSP import as lines inside the region
and publishes them as MultiLineStrings with no topology. A line alone does not
say which side is land.

## What the data is today

Counted on `dist/regions/morro-bay/shoreline.geojson`:

| Measure | Count |
| --- | --- |
| Features / lines / vertices | 63 / 3,773 / 26,520; no repeated consecutive positions, no malformed line |
| Closed lines | 3,593: 1,304 collinear (a-b-a, 1.1–15.5 m), 2,099 rings at most 25 m across, 190 larger rings |
| Open lines | 180 |
| Open-line endpoints (360) | 348 shared, all at nodes joining exactly two lines; 2 on the region bounds; 10 dangling |
| Chains after joining at shared endpoints | 13: 7 closed (5 enter parity, 2 at most 25 m across), 6 open |
| HOR_ACC (metres) per line | 4.31 (3,279 lines), 3.14 (397), 0.796 (89), 9 (8); display quantisation 1.96 m |
| zoom-12 tiles NOAA served | 29 of 238 requested; 209 answered 403/404 (`unavailable_tiles`) |

The 10 dangling endpoints form 5 mutual-nearest pairs:

| Gap | What it is | Rule (step 3) |
| --- | --- | --- |
| 6.4 m | The mainland. The north clip ends at (-121.00043, 35.46067) in tile 12/671/1615, and the south clip starts at (-121.0005, 35.46067) in 12/671/1616. Both points lie exactly on the row edge the two tiles share, and both tiles were served. 2 × HOR_ACC = 8.62 m. | seam join |
| 1.8, 4.5, 56.4, 2.2 m | Four lone 2-position lines lying along a tile edge (tiles 12/666/1611, 12/668/1612 twice, 12/670/1615). Each one's two ends pair with each other. | collinear, so edge-only |

## Candidates

(b) Basemap land polygons (`web/map/currents.ts` `landMask`): rejected; round 1
agreed. `engine.ts` `land()` returns `querySourceFeatures` over the basemap
tiles loaded for the current camera, and `landMask` rasterises them at quarter
scale. The result depends on zoom, pan and tile loading, and it does not exist
before the map draws. The overlay was reviewed as display clipping of flow
paths. It was not reviewed as an authority for withholding a place.

(a) Topology built from the approved CUSP lines: chosen.

## Method (a)

The input is the published shoreline exactly as the platform build writes it.
The CUSP import is unchanged and no new source is added. All topology tests
compare integer coordinates on the 5-decimal grid (1e-5°), so no floating-point
tolerance decides a crossing, a touch or a shared endpoint. (Round 1's float
test reported 36 crossings between distinct lines. Exactly, they are 32 proper
crossings and 4 touches, and round 1's 5 "self-crossings" are 2 proper crossings,
2 touches and one crossing inside a 6.6 m ring.)

### The premise, and what the checks add

Even-odd parity (step 7) is defined for any set of closed polylines: a point's
parity is the number of curve segments a ray from it crosses, mod 2. It is right
when the published lines trace the true mean-high-water line, within `EDGE_M`,
wherever NOAA served a tile, with no shoreline missing from a served tile. The
data cannot prove that premise; every line-based classifier rests on it. The
method does three things around it:

- It never invents shoreline the premise does not cover. There are no bridges
  (step 3).
- It refuses data whose topology suggests a large-scale error (step 6).
- It withholds everything within `EDGE_M` of a line (step 8).

One fact carries every bound below. Call it the edge-band lemma. Parity is
additive: a point's parity under several closed curves is the sum, mod 2, of
its parity under each one. A collinear closed curve has zero parity off its own
line. A closed curve at most `EDGE_M` across has zero parity outside its
bounding box, and every point of that box is within `EDGE_M` of the curve's own
vertices. So adding or removing such a curve changes no point outside the band.
Moving a curve changes a point only if a segment passes over it, so a move
smaller than a point's distance from the lines leaves that point unchanged.

### Steps

1. Lines. Each line needs at least 2 positions and finite numeric
   coordinates. Repeated consecutive positions are dropped. A line is closed
   when its first position equals its last.
2. Chains. Open lines chain at exactly equal endpoints. A node shared by three
   or more lines makes the product unavailable. Today every shared node joins
   exactly two lines.
3. Gaps: seam joins only, no bridges. Pair each dangling endpoint with its
   mutual-nearest dangling endpoint.
   - Two different chains are joined only when every seam condition holds:
     (i) both ends lie exactly on one zoom-12 tile edge; (ii) the two end
     lines' `source_tile` values are the two tiles that share that edge;
     (iii) both tiles were served; (iv) the gap is at most 2 × the larger
     HOR_ACC of the two lines (largest possible today: 18 m).
     Why this bounds the unseen coast: the import clips every line to its own
     tile, so a shoreline crossing a tile edge appears as two clips ending on
     that edge, one from each tile. With both tiles served, every other part of
     that shoreline is present in one of them under the premise. The join
     stands only for the crossing of the edge between the two ends. Every point
     of it is within half the gap (at most 9 m) of a published endpoint, so it
     lies inside the edge band, and the join segment counts as a line for
     step 8.
   - A gap that fails any condition makes the product unavailable, whatever
     its length. This is round 1's must-fix 1. A mid-tile gap has no such
     explanation: in the review's counterexample, a 50 m gap hides a headland
     whose land lies 500 m from the gap. `MAX_BRIDGE_M` and the bridge's
     unknown disc are withdrawn.
   - A chain whose two ends pair with each other is kept only when the loop it
     would close is degenerate (step 5), and then only as an edge line. Today
     that covers the four 2-position lines, including the 56.4 m one, which
     round 1 treated as a bridge. Any other such chain makes the product
     unavailable.
   - An unpaired dangling endpoint makes the product unavailable.
4. Mainland. After joining, exactly one path may run from bound to bound;
   any other number makes the product unavailable. It is closed along the
   region bounds through the corners on the land side. Each region declares
   those corners in `regions/<id>/region.json` (Morro Bay: south-east, then
   north-east). The build checks that the path's ends lie on the bounds edges
   the declaration implies. The CUSP lines carry no documented orientation,
   so the land side is declared, not inferred. The closure segments run along
   the bounds and are not shoreline; points beyond them are `outside-bounds`.
5. Degenerate curves are edge-only. A closed curve (line, chain, seam loop or
   self-paired chain) is degenerate when all its positions are collinear or
   it is at most `EDGE_M` across (bounding-box diagonal). By the lemma it
   changes no point outside the band, so it is left out of parity and kept as
   an edge line. A position count of four or more never makes a curve
   area-authoritative by itself. Today 3,403 closed lines and 2 closed chains
   are degenerate, and 196 curves enter parity: the mainland, 190 rings and 5
   chains.
6. Defects, then removal, then fail-closed. Over the parity curves, including
   the seam join and the bounds closure, the build lists every exact defect:
   - proper crossings;
   - touches (a vertex on another segment, or a repeated vertex);
   - collinear overlaps (duplicate or shared edges);
   - retraces (a segment that doubles back on the one before it).
   It checks pairs within one curve (non-adjacent segments) and between
   curves. A defect is removable when one of these witnesses holds:
   - Retrace: the doubled-back stretch is traversed twice, so it cancels mod 2.
     The vertex is removed, which changes no point off that segment.
   - Sub-loop: the defect point X splits the curve into two closed loops whose
     segments add up, mod 2, to the curve. If one loop is collinear or at most
     `EDGE_M` across, it is removed and the curve continues through X. By the
     lemma no point outside the band changes. Rounding X to the grid moves it
     under 1 m.
   Removals are applied one at a time, and the census is re-run after each,
   until nothing removable is left. What may then remain:
   - A touch without crossing: the two strands meet at a point but neither
     passes to the other side. This is decided exactly from the angular order
     of their four directions. An arbitrarily small separation removes it, so
     it is allowed and left in place.
   - Anything else makes the product unavailable: a proper crossing or a
     crossing contact with no small sub-loop, any crossing or overlap between
     two parity curves, or an overlap that runs on. This is round 1's
     must-fix 2. The method does not guess which side of a large crossing is
     wrong. A 200 m bowtie ring could be a square island with two swapped
     vertices, and even-odd would call its side triangles water up to 70 m from any
     line.
7. Land side by even-odd over the parity curves. A point is land when an odd
   number of them contain it. Every published line is a mean-high-water or
   man-made shoreline, so crossing one switches between land and water. A ring
   bounds land when it lies in water (an island or rock) and water when it lies
   in land (a pond or lagoon), whatever direction it was drawn in.
8. Edge. A point within `EDGE_M` = 25 m of any published line or seam join is
   edge, and edge is handled as unknown. This includes degenerate and removed
   loops: the band is always measured from the published lines, which is what
   steps 5 and 6 rely on. `EDGE_M` is a conservative planning tolerance, not a
   verified generalisation bound or a navigation guarantee. The worst stated
   error is 9 m (HOR_ACC) + 1.96 m (one display unit) + 0.55 m (rounding) =
   11.5 m. Doubling that allows for the tiles' undocumented generalisation
   (import limitation 2), giving 23 m, rounded up to 25 m. The build makes the
   product unavailable when a file's 2 × (max HOR_ACC + quantisation + 0.55)
   exceeds `EDGE_M`.
9. Coverage. Only the tiles NOAA served count. A point is unknown when it lies
   in a tile listed in `unavailable_tiles`, outside the region bounds, or when
   its coordinates are not finite. A shoreline running from a served tile into
   an unserved one is clipped at their shared edge and leaves a dangling end
   there. That end fails seam condition (iii), so the product is unavailable.
   A curve lying wholly inside an unserved tile has zero parity outside that
   tile, which is convex in longitude and latitude.
10. Unavailable means every point is unknown. The causes:
    - a missing shoreline file, or a product file of the wrong shape;
    - a malformed line (under 2 positions, non-numeric or non-finite
      coordinates);
    - a node of degree 3 or more;
    - a gap that fails a seam condition, an unpaired endpoint, or a
      non-degenerate self-paired chain;
    - anything other than one bound-to-bound path;
    - a defect left with no witness.
    Malformed input is never land and never water.

There are three outcomes: water, land and unknown. Unknown carries one of
these reasons: `outside-bounds`, `unserved-tile`, `edge` or `unavailable`. The
round-1 reasons `gap` and `crossing` are gone, because those cases now make the
whole product unavailable instead of opening local zones.

Default behaviour is fail-closed. Land and unknown candidates are withheld, and
the basis states the count: "N spots withheld: land/water not confirmed." N
counts the candidates that passed every other filter, not only the shown top
four.

## Defect evidence on today's data

Exact census over the 196 parity curves (12,740 segments): 33 defects. All are
within one curve; none is between two curves.

| Defects | Where | Witness |
| --- | --- | --- |
| 10 touches/overlaps | mainland at the seam, (-121.00050 to -121.00043, 35.46067): both clips run briefly along the tile edge | collinear sub-loop 6.4 m |
| 2 proper crossings | mainland, marsh line at (-120.82647, 35.34616) and (-120.82646, 35.34617) | sub-loops 17.6 and 18.4 m across |
| 4 touches/overlap | mainland at (-120.82656, 35.34618), the same spot | collinear sub-loop 10.0 m |
| 3 touches | mainland at (-120.82710, 35.34896), round 1's "mainland invalid" point | collinear sub-loop 9.3 m |
| 5 retraces | 4 on the mainland, 1 on a 142-position ring | retrace |
| 1 touch | 142-position ring at (-120.82976, 35.34088), round 1's invalid ring | collinear sub-loop 7.7 m |
| 8 touches | mainland at (-120.83588, 35.34284), (-120.83352, 35.34326) and (-120.85390, 35.31780): a vertex resting on the line without crossing. Round 1's float test counted the first one as two crossings. | touch without crossing |

Five sub-loop removals resolve everything except the 8 tangent touches, which
are allowed. No defect is left without a witness. The census over all 3,601
closed curves, degenerate ones included, finds 32 proper crossings and 94
touches between two curves. Every one of them involves a degenerate curve, and
in each pair the smaller curve is at most 10.9 m across, so none enters parity. Round 1's other
invalid shapes are handled the same way: the 5-position ring is 6.6 m across,
and the four zero-area assembled loops are the collinear self-paired lines.

An independent Shapely 2.1.2 check (a scratch script, not committed) agrees.
Before removal it finds the mainland and the 142-position ring invalid at
round 1's points. After removal the ring is valid. The noded mainland's only
nodes of degree 4 are the three tangent-touch points listed above.

Removal changes the parity of no waypoint (0 of 153 classified). The product
is available for Morro Bay today.

Self-test on injected geometry (`--self-test`, 14 of 14 pass):

| Case | Result |
| --- | --- |
| 50 m mid-tile coast gap (the review's counterexample) | not joined, so unavailable |
| 6 m mid-tile gap | not joined |
| 6.4 m gap on the shared edge, both tiles served | seam join |
| the same gap with one tile unserved, or a 20 m gap on that edge | not joined |
| 56 m 2-position line closed on itself; 10 m bowtie ring | degenerate, edge-only |
| 200 m bowtie ring | no witness, unavailable |
| 500 m ring with a 10 m self-crossing curl | curl removed, available |
| 500 m ring with a 100 m spike | retrace removed, available |
| 500 m ring with a 100 m self-crossing loop | no witness, unavailable |
| two 300 m rings crossing; an island crossing the mainland | no witness, unavailable |
| island touching the mainland at a vertex without crossing | available |

## Implementation

- `src/skippercast/platform/land_water.py` runs steps 1-10 inside
  `PYTHONPATH=src python -m skippercast.platform.build` and writes two
  generated files beside the published shoreline. A region without a
  shoreline gets neither, and stale copies are removed.
  - `dist/regions/<id>/land-water.json` is the index, 5,150 bytes for Morro
    Bay. It holds:
    - the status: available, or unavailable with its causes;
    - the constants and the census counts;
    - the shoreline's sha256 and the lines file's sha256;
    - for each of the 29 served zoom-12 tiles, a 32 × 32 grid of cells,
      run-length encoded. Each cell is `w`, `l` or `m`.

    A cell is clean (`w` or `l`) only when every published line and seam
    join stays more than `EDGE_M` + 1 m from the whole cell, and no parity
    curve after removal touches it. Every point in a clean cell is then
    outside the edge band and has the parity of the cell's centre, which the
    build computes by even-odd over the parity curves after removal. The extra
    1 m covers the difference between the build's per-tile metre scale and the
    client's per-point one. Inside each tile, cells are evenly spaced in Web
    Mercator, which is how the client looks them up.
  - `dist/regions/<id>/land-water-lines.json` is the lines file, 278,928
    bytes. It holds every published line, the seam join (the edge band) and
    the parity curves after removal, as delta-encoded integers on the
    5-decimal grid.

  Splitting the product into two files departs from the single file planned
  at step 0. The reason is the startup budget: the brief ranks places at first
  paint, and the lines file alone would exceed the budget's headroom. Only the
  index loads at first paint. The lines file loads only when a candidate falls
  in an `m` cell, and none of today's 156 waypoints does. The client checks the
  lines file's bytes against the index's sha256 and refuses a mismatch.
- `web/land-water.ts` classifies a point by these checks, in order:
  1. A point that is not strictly inside the bounds, or has no finite
     position, is `outside-bounds`.
  2. A point in a tile NOAA did not serve is `unserved-tile`.
  3. A point in a clean cell takes the cell's label.
  4. A point in an `m` cell is `pending` until the lines file loads. Then it
     is `edge` within 25 m of a line, otherwise land or water by even-odd.

  A missing, unavailable or malformed product, or a lines file that fails,
  gives `unavailable`. `pending` is the only reason not listed in step 10. It
  is transient: until the lines file loads, the list shows "Checking land and
  water for these places…" in place of picks.
- Ranking keeps water places only and counts the rest:
  - `web/ranking.ts` (terrain and atlas sources) adds the count to the basis.
  - The planner's `dist/spot-ranking.js` `bestSpots` (`place`,
    `stats.withheld`) adds it to the status line.
  - `web/planner.ts` loads the check before Best available. It refuses to
    restore a saved plan that has a spot not confirmed as water.
  - `web/map/ranked.ts` draws a pin only where the check says water.

  Where a region has no check, every place is withheld (decision 4, the
  recommended option).
- Tests:
  - `tests/unit/test_land_water.py` tests the builder on injected geometry. It
    covers:
    - the self-test rows and each seam condition;
    - a node of degree 3, a non-degenerate self-paired chain and a second
      bound-to-bound path;
    - the land corners and a vertex resting on the coast;
    - the changed-mainland regression: the parity curves carry the resolved
      mainland;
    - that the committed Morro Bay product equals a rebuild.

    It also writes the node fixtures in `tests/fixtures/land-water/`, and it
    fails when they drift.
  - `tests/test_land_water.mjs` tests the classifier, the ranking and the
    planner. It covers:
    - the acceptance item 4 cases on the fixtures;
    - agreement between the grid and the lines on more than 3,000 random
      clean-cell points of the committed product;
    - the committed-data check.
- The read-only probe's after-removal comparison now uses the resolved
  mainland, as the round-2 review's nonblocking finding asked. The result is
  unchanged: removal changes the parity of no waypoint.

## Committed-data check (acceptance item 5)

Today's waypoints come from both sources: 132 atlas targets
(`dist/data/atlas.json`) and the 24 Morro Bay terrain waypoints in release
4c24f963. Of these 156:

- 153 are water: 130 atlas and 23 terrain.
- None is land, and none is within 50 m of a line. The nearest classified
  waypoint is 634.7 m away.
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

## Round-1 must-fixes

1. Bridges. They are withdrawn entirely (step 3). Joins require all four seam
   conditions, and every other gap makes the product unavailable. The 56.4 m
   line is collinear and edge-only. The counterexample is in the self-test and
   the test plan.
2. Self-crossings, retraces, overlaps and degenerate loops. These are now
   checked by an exact census over the assembled curves, including the joins
   and the mainland closure (step 6). Each defect needs a witness bounded by
   the edge-band lemma, or the product is unavailable. Collinear and small
   loops are edge-only regardless of position count (step 5). The probe's
   equal-owner exclusion is gone. Today's actual cases are in the table
   above, cross-checked with Shapely.

## Decisions for the reviewer

1. Method (a), with (b) rejected.
2. Constants: the join limit is 2 × HOR_ACC, and only for a validated tile
   seam. There are no bridges. `EDGE_M` is 25 m, a conservative planning
   tolerance.
3. Fail closed on any gap that is not a seam and on any defect with no
   witness. The cost: a future shoreline import with one bad stretch makes
   that whole region unavailable until the data is fixed. Local unknown zones
   were the alternative, and round 1 showed they need bounds this method
   cannot prove.
4. Regions with no shoreline product, which is every region except Morro Bay
   today:
   - (Recommended, the card's default; round 1 agreed) fail closed: their
     ranked places are withheld and the basis gives the count. Today's release
     has 22 terrain waypoints in `monterey-point-sur` and 2 in
     `cambria-san-simeon`; their lists would be empty until those regions get a
     CUSP import, which is a separate data card.
   - Alternative: rank them as today with the basis "Land/water not checked in
     this region".
5. Points in unserved tiles are unknown, so the three waypoints above are
   withheld (round 1 agreed).
6. Each region declares its land corners in `region.json`.

## Limits

- No new source, and no change to the CUSP import.
- The result is a planning screen for ranked places. It is not a navigation
  boundary, a legal shoreline or a tidal line: the lines are historical mean
  high water dated 1994-02-28 to 2010-11-01.
- It is only as good as the premise above. A shoreline that NOAA's served
  tiles omit cannot be detected from them.
- CI2's Bay pins remain a QA question.
