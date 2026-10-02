# Reviewed native terrain support

Some original CSUMB depth grids contain documented vessel-heave artifacts.
Their original rough/smooth interpretations include manual terrain exclusions,
but those classes are not a depth-validity mask or independent rock/sand data.
`terrain_support.py` provides an optional positive-support gate for these
products. It preserves measured coverage and original depth neighborhoods while
restricting habitat analysis to explicitly reviewed rough cells.

## Qualify a binding

Use original archive bytes already retained by the native adapter. A source-row
`terrain_support` binding must identify the exact depth source ID, original
archive hash and depth member, normalized depth hash, separate categorical
member, embedded metadata hash, original legend, review date and inventoried
evidence. The initial profile is `csumb-native-rough-v1`:

- Rough: `-1`, `-31`, `-101`, `-201`.
- Smooth: `0`, `-30`, `-100`, `-200`. Zero is a valid smooth class.
- Original NoData is unsupported habitat. An unreviewed class code fails the
  run; it is not silently interpreted as either rock or sediment.

Read the original metadata and review each proposed product. Do not copy this
legend to a different producer or infer a class grid from rendered imagery.
The reader checks original hashes, embedded metadata, one-band grids, exact
native CRS/transform/dimensions and spacing against the original depth grid.
It uses the existing bounded archive adapter and nearest projection onto the
same analysis grid used for depth. It does not create an independent survey or
grant publication rights.

## Run the existing pipeline

1. Keep unresolved sources `physical-only`; preserve existing quality holds.
2. Record the proposed binding and original-source review in a focused source
   PR. Native depth, datum, uncertainty and rights metadata remain explicit.
3. Run the normal physical-only reach command in an isolated proof root or
   worktree. Preserve the prior result and compare its measured cells, source
   selection, thresholds, geometry and rankings with the new result.
4. Review surviving native patches against original depth and available
   observations. Rough support alone does not establish artifact-free terrain,
   substrate, fish presence or improved sounding accuracy.
5. Only a separate source review can resolve a quality hold or change source
   publication status. Apply the current whole-polygon spatial screen before
   map/export publication and verify the deployed regional bundle.

The implementation intersects positive support with the habitat analysis mask
before both shared percentile calibration and extraction. Raw depth validity,
measured coverage and derivative neighborhoods remain intact. Morphological
closing is clipped back to supported, valid, in-depth-band cells. Existing
rule constants and scoring formulas are unchanged. Recomputed numerical
cutoffs can change, including candidates from **unbound sources in the same
calibration group**. Groups without an active binding retain their previous
numerical behavior.

Binding content and implementation hashes enter physical-cache identity.
Each candidate retains source-bound support evidence with same-survey and
non-independent labels. The candidate collection records support digests for
all calibration contributors, including sources with no own candidates.
Publication rejects stale direct or indirect support evidence. A source that
was never selected does not impose a false dependency on another survey.
Original archives remain the recovery objects; extracted class grids are
verified, reproducible scratch.

## Validation and the initial native proof

`tests/gis/test_seafloor_terrain_support.py` covers original alignment/hash
failures, explicit zero/NoData handling, empty support, synthetic acquisition
stripes, depth edges, holes and morphology, tile equivalence, shared calibration,
unchanged unbound groups, persistent quality holds and stale publication.
Manifest contract tests enforce the exact source binding and legend.

The October 2 private SCC26–28 proof used two retained Arguello reaches. Their
selected measured support remained 38.991811670 and 82.655034790 km², with
identical depth cells. Physical candidates changed from 1,119/1,203 to 776/840;
direct SCC26–28 candidates changed from 630 to 39. Other contributors changed
with the recalibrated shared thresholds. These are private method-validation
results, not geographic acquisition, source promotion or public fishing spots.
Native review and public spatial screening remain separate stages.
