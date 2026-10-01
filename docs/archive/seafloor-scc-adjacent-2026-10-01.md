# Adjacent native SCC original survey batch

Three original CSUMB 2 m bathymetry grids (SCC02, SCC18, SCC20) were opened from
the exact nested GRID members in their NOAA-distributed archives. Source URLs,
hashes, native footprints, acquisition dates and shallow valid-pixel counts are
in `catalog/csumb-scc-adjacent-native-sources.json`. All previous catalog rows
are unchanged. New rows are physical-only, with public rights unqualified.

The three archives total 492,078,539 bytes. SCC02 and SCC18 have 2010 acquisition
dates; SCC20 mixes 2010/2011 and its catalog year is unknown. Native NAVD88/Geoid09
metadata is retained. Unknown per-cell uncertainty and interpolation remain
unknown; 2 m grid spacing is not sounding accuracy. The selected bathymetry is
not a hillshade, slope product or interpolated display GeoTIFF.

The ordinary private runner processed Conception r02/r03 and southern Big Sur
r03. Conception r03 was previously unprocessed; its initial SCC19-only run was
expanded with SCC20 in this same batch and is counted once from a zero baseline.
Selected valid footprint increased from 59.800166603 to 132.340033047 km²:
**72.539866444 km² net**. Physical candidates increased from 744 to 1,722:
**978 net**. Of 1,722 resulting candidates, 1,616 have supported lingcod and reef
rockfish ranks and 106 retain unknown ranks. These are habitat suitability
results, not confirmed fish locations. See the committed aggregate proof.

Conception r02 gained coverage while its candidate count fell from 577 to 542
after expanded native inputs. Candidate counts are not monotonic coverage
metrics. Do not label every changed polygon as an additional fishing location.
No previous public map/export is modified; all current new results remain held.

SCC02's actual native footprint mainly expands the southern Big Sur reach.
The planner does not qualify Cambria r01 from this file. The three surveyed
footprints cannot be used to claim the remaining Cambria or northern/southern
Conception gaps are covered. Inspect SCC03, SCC17 and SCC21 originals next and
schedule their actual native intersections, rather than infer coverage from
neighboring cruise numbers.

Each archive also includes habitat-classification and accuracy-assessment
members, recorded as supplemental leads. They are not yet ingested or independent
evidence; assess their method, positional support and same-survey lineage first.

Reproduce with the existing caches and shared runner:

```sh
export PYTHONPATH=src:.
python -m skippercast.seafloor run --reach point-arguello-conception-r02 --physical-only
python -m skippercast.seafloor run --reach point-arguello-conception-r03 --physical-only
python -m skippercast.seafloor run --reach south-big-sur-san-simeon-r03 --physical-only
```

Before release, explicitly qualify producer terms using the reviewed contract,
adopt unchanged private physics, then apply fresh whole-polygon MPA/security
screens. Unknown ranks and restricted candidates stay unavailable for export.
Review, current-head CI, main publication and map/export verification remain
separate steps. Public-source metadata alone does not make these candidates live.
