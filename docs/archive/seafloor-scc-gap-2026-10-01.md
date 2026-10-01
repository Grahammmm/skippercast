# Cambria and northern Conception native gap batch

Privately qualify three original CSUMB 2 m grids, SCC03/SCC17/SCC21, from
observed NOAA publisher links. Exact native files, source hashes/footprints,
actual acquisition dates, nominal shallow pixels and unknown uncertainty/
interpolation are in `catalog/csumb-scc-gap-native-sources.json`. Native depth
uses its documented NAVD88/Geoid09 basis; no datum conversion or resampling.
SCC17 mixes 2010/2011 and its catalog year is unknown. Archives total
463,037,741 bytes. All prior source rows are unchanged; public source rights
remain unqualified and all new rows are physical-only.

Two previously empty reaches were processed: Cambria/San Simeon r01 and
Arguello/Conception r01. Three neighboring reaches (South Big Sur r03 and
Conception r02/r03) were updated because the new native windows intersect them.
Preserve prior summaries and private candidate geometry for diagnostics.
Selected valid coverage increased 132.340033047→195.865359483 km²,
**63.525326436 km² net**. Physical candidates increased
1722→2668, **946 net**. Resulting ranks:
2476 supported and 192 unknown. Counts are habitat candidates, not
fish-presence confirmation. Aggregate/run hashes and per-reach ranks are in
`scc-gap-private-proof-2026-10-01.json`.

SCC21 overlaps Conception r03 but does not qualify the empty southern r04.
Do not extrapolate cruise footprints or claim whole-region completion. Candidate
counts can decrease or merge after expanded scientific inputs; the net before/
after comparison does not count all changed outlines as new locations.
Supplemental original habitat and accuracy members are discovery leads only,
not ingested or independent evidence. Grid spacing is not positional accuracy.

Reproduce from retained caches with the shared pipeline:

```sh
export PYTHONPATH=src:.
python -m skippercast.seafloor run --reach cambria-san-simeon-r01 --physical-only
python -m skippercast.seafloor run --reach point-arguello-conception-r01 --physical-only
python -m skippercast.seafloor run --reach south-big-sur-san-simeon-r03 --physical-only
python -m skippercast.seafloor run --reach point-arguello-conception-r02 --physical-only
python -m skippercast.seafloor run --reach point-arguello-conception-r03 --physical-only
```

Before public fishing/export: explicit producer release qualification, adopt
checked unchanged physics, fresh whole-polygon MPA/security screening and
main regional publication with canonical-export and live map verification.
No public ledger, original raster or raw private candidate geometry is committed.
Next inspect SCC22 for the southern Conception gap and SCC04/16 for neighboring
coverage, using actual native intersections rather than assumed adjacency.
