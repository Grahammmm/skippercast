# Require a positive habitat opportunity before an expansion session

The objective is more useful habitat on the visitor map. New survey coverage,
new habitat within existing coverage, and better evidence for an existing patch
are different outcomes. Only the first two add mapped habitat. A research or
maintenance success must not be substituted for them.

## Check these causes separately

- All processed reaches are selected for refresh by the existing daily planner.
  This maintains restrictions and source freshness; it is not an expansion queue.
- The terrain extractor uses relative roughness/positive relief, not every
  publisher-interpreted habitat class. An interpreted rock/boulder habitat can exist outside its
  current rough-patch outlines.
- Missing surrounding depth prevents a numerical grade. Use the existing
  measured-rough search contract where applicable; do not lower its grade rule.
- A quality hold, no valid shallow pixels, an MPA conflict and a missing original
  source are different blockers. Do not call all of them unavailable mapping data.
- A processed reach is not finished. Assess additional interpretation and source
  support inside it, as well as native gaps beyond it.

## Session acceptance and priority

Start from a concrete source/reach and measure a small before/after result before
large processing. Prefer a ready positive result over another infrastructure PR.
Use this order:

1. Release an already supported private candidate batch through the applicable
   evidence, rights and whole-polygon restriction contract.
2. Test existing reviewed classifications for habitat missed by the terrain
   extractor. Class semantics, valid paired nominal depth, original lineage and
   current source rights must remain explicit.
3. Test useful new original measurements against a real gap.
4. Fix a pipeline blocker only when it demonstrably prevents one of those batches.

The reusable bounded private probe is:

    PYTHONPATH=src:. python -m research.scripts.probe_classified_habitat \
      --root CHECKED_RUN_ROOT --reach REACH_ID --source QUALIFIED_DEPTH_ID \
      --output var/seafloor/BATCH --max-pixels 25000000

It tests only reviewed rugose rock/boulder class3, paired with valid nominal
25–300ft depth, excluding current physical outlines. Mixed rock/sediment class2
does not become rock. Tile fragments are dissolved before the minimum area test.
The output remains private, unranked and nonexportable. Preliminary spatial
eligibility is not production admission. Any release needs an independently
reviewed classified-habitat contract, producer evidence and current whole-polygon
screening; never pass these polygons through the rough-terrain contract by
inventing support fractions or grades.

An unknown effective precision or missing depth-dependent resolution profile is
not by itself a blocker to a limited Tier-1 producer interpretation when the
class-3 semantics and original source are authenticated and paired nominal-depth
cells are valid. The interpretation may proceed through source-specific review,
current whole-polygon screens and publication when those gates pass. Keep it
unranked and nonexportable as a fishing location; preserve unknown datum,
accuracy, interpolation and acquisition lineage. A delivered 2 m grid is grid
spacing, not 2 m accuracy. Leave fit, grades, measurement credit and precision
unknown. Do not invent a fine-to-depth limit, coarse-resolution cutoff, rank or
measurement, and do not borrow another source pair's depth thresholds. Known-
invalid native geometry remains held even when a projected or repaired display
shape appears valid.

## Production path

The reviewed production path uses source-specific opt-ins in
`catalog/classified-habitat-policy.json` and the separate classified-habitat
contract. After private qualification and independent review, invoke:

    PYTHONPATH=src:. python -m skippercast.seafloor.classified_habitat \
      --root ROOT --reach REACH

This CLI retains its default 25-million-pixel bound and does not accept the
research probe's `--max-pixels` argument. The probe output is qualification
evidence only. Follow the existing automatic workflow on current main, then
check source rights, a fresh whole-polygon screen, and live archive/map
readback. Use native EPSG:3310 geometry as the authoritative fidelity and area
basis according to `docs/engineering/classified-geometry.md`; do not publish raw
or private geometry.

For a reviewed batch with unresolved neighboring native overlap, an opt-in
`neighbor_reaches` list can suppress whole patches using the verified shared
planning grid. Prove that the planning footprint contains every relevant
neighbor cell and leaves a useful disjoint subset before enabling it. This is
a conservative exclusion, not surveyed coverage or an accuracy estimate.
The maintained stage and publisher must independently reconstruct the same
native holds; never edit held outputs or commit private feature IDs to select
the passing subset. Paired reference footprints also retain each contributor's
verified dependencies, credits and use restrictions; they supply no habitat
metrics to the original depth/classification pair.

Within 20 active minutes, require either a positive bounded habitat delta or a
specific reproducible processing failure that prevents it. If the probe adds
nothing, change source/reach/method. Do not follow it with an all-reach refresh
as the mapping deliverable. If no positive batch is ready, say so before starting
a lengthy run and preserve the exact dependency.

Report deduplicated additional habitat area from the authoritative native union
and feature count from unique verified native feature IDs. Also report unranked
versus ranked candidates, restriction/quality exclusions, verified public
additions, and new measured coverage separately. Union components can merge
edge-touching polygons; tile fragments never count as features. IDs alone do not
prove new physical-area expansion. Splitting polygons or rerating existing
geometry does not add habitat. Keep routine daily maintenance running separately.

If private native area and live feature-area attributes differ, preserve both
area bases and verify the actual runner inputs before assigning a cause. If the
runner's native union cannot be reconstructed, report attribute-based area as
approximate and the cause as unknown. Do not sum clipped tile fragments.
