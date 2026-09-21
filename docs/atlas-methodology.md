# How the habitat atlas was derived

The public release preserves reviewed USGS-derived locations and measurements from a larger September 2026 research effort. It packages the data and an exporter; it does not yet ship a portable end-to-end multibeam-processing pipeline.

## Evidence hierarchy

1. **Mapped habitat:** bathymetry and seafloor character support an interpretation of rocky or rugose terrain worth investigating.
2. **Terrain priority:** a fixed formula orders search effort using measured local relief, rough cover, detrended complexity, and nearby usable habitat area.
3. **Fishing activity:** the reviewed public AIS sample produced no verified local charter identity matches. There are no AIS-confirmed charter hotspots in this release.
4. **Catch success:** no catches have been verified at these exact coordinates. The score is not trained or calibrated against catch records.

Individual boulder dimensions, live fish concentrations, present kelp, snag risk, and current drift cannot be established from the regional interpretation. High confidence in a source's existence is not high confidence that a fish will bite there.

## Terrain score

For measured relief `R` in meters, mapped rough-cover fraction `F`, detrended terrain RMS `C` in meters, and usable rough habitat `A` in hectares:

```text
score = round(35 × min(R / 15, 1)
            + 30 × F
            + 20 × min(C / 3, 1)
            + 15 × min(A / 10, 1))
```

Relief and rough-cover metrics use the original 210-m local neighborhood definition. Complexity and area use a 250-m-radius neighborhood; a fitted plane is removed before computing RMS so a smooth slope is not mistaken for complex terrain. The original workflow measured these on a 10-m analysis grid; the included record names preserve that provenance.

Grades are A ≥75, B ≥55, and C below 55. The formula deliberately caps each contribution so a large footprint alone cannot dominate. [scoring.py](../src/skippercast/atlas/scoring.py) reproduces this arithmetic from included metrics. Tied ranks are recomputed within the 132 public targets. These weights are a research heuristic, not a validated ecological model.

## Outlines and drift alignments

The original analysis selected nearby mapped rough-rock/bedrock cells, removed isolated grid noise, bridged small interruptions, and limited footprints to nearby target search windows and conservative depth/closure screens. Polygon simplification retained meaningful holes. These are **partial habitat footprints**, not comprehensive reef boundaries or individual boulder outlines.

Optional alignments follow a strong principal axis of raised rough habitat near a target. The original workflow required a pronounced axis, a 150–400 m line, at least 70% mapped rough habitat in a 25-m corridor on each side, and complete native-depth coverage. Actual drift direction and speed must be measured on the water; the line does not predict current.

## Depths, positions, and closures

The public subset uses MLLW-referenced USGS grids. Native depth checks covered each selected point and its 100-m investigation neighborhood. Final polygons and line corridors were checked in full, not only at vertices. A conservative ≤195-foot ceiling for those geometries provided room below the requested 200-foot source-depth limit. This is not a tide correction or a guarantee that current sounder depth stays under 200 feet.

The original screen excluded relevant protected areas and the Diablo Canyon security area, with a ≥500-m planning margin for exported outlines and alignments. **That margin is a research choice, not a legal boundary rule.** Source checks are dated September 20, 2026. Recheck official current boundaries and rules before fishing; the public validator does not query them.

## What can be reproduced here

| Operation | Included now? |
| --- | --- |
| Inspect every published target, measurement, linked geometry, and source | Yes: `atlas.json` |
| Recompute terrain scores and tied ranks | Yes: validator and scoring module |
| Rebuild GPX, GeoJSON, offline notes, and checksums | Yes: exporter |
| Check internal links, counts, ring closure, and recorded thresholds | Yes: offline tests/validation |
| Redownload every source and regenerate original habitat metrics | No: complete native GIS pipeline is future work |
| Independently rerun native-grid depth and present closure checks | No: recorded evidence is included, source grids are not |
| Verify current catch success, actual depth, safe navigation, or legality | No |

Public data excludes direct Cambria survey derivatives and historical charter-ground annotations with unresolved reuse terms. Do not reconstruct or reintroduce those layers merely because they appeared in an earlier private research artifact. See [data-sources.md](data-sources.md).
