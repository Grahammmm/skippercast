# Adjacent original BSS grids — September 30, 2026

Existing Block01 and Block08 catalog records now carry checked original archive
bytes, native 2 m grids, normalized identities and explicit private-only source
qualification. Block13 retains its original 5 m grid; its 12,063 source pixels
nominally under 300 ft do not establish coverage in the requested reference band.
The older 200 ft exclusion note is insufficient to reject a 300 ft source.

## Actual requested-band results

| Reach | Selected valid km² | Tier-1 cell km² | Physical candidates | Supported ranks | Unknown metrics |
| --- | ---: | ---: | ---: | ---: | ---: |
| Big Sur r06 | 6.246063391 | 6.999375 | 95 | 81 | 14 |
| Southern Big Sur / San Simeon r03 | 4.844458905 | 5.298750 | 60 | 51 | 9 |
| Big Sur r02 | 0 | 0 | 0 | 0 | 0 |
| Big Sur r03 | 0 | 0 | 0 | 0 | 0 |

The additions total **11.090522296 km²** selected valid footprint and
**155 physical candidates**, including **132 supported lingcod ranks** (13 rank3,
119 rank2) and 23 unknown. Block13 valid shallow source pixels lie outside the
requested-band intersections in the two tested reaches; their envelope overlaps
are scheduling estimates, not measured expansion. No zero-area run is counted
as completed mapped coastline. No source was resampled to invent detail.

The prior private batch remains 42.966359419 km² / 465 candidates; combined
private additions are 54.056881715 km² / 620 candidates before any refreshed
overlap in previously processed reaches. These totals exclude all earlier public
Monterey additions. Every new candidate remains publication-prohibited pending
producer-specific release terms/attribution and current whole-polygon screening.
Public ledger and map are unchanged by this source batch.

## Validation and next work

Native source inspection and checksum-qualified ingestion reused cached original
archives. Four actual private run receipts and candidate outputs are retained
privately. Focused manifest, cache-key, ArcInfo and planning tests: 34 passed /
2,996 subtests. BSS01 also intersects an already private-processed reach; refresh
that overlap separately and report its measured delta without double counting.
Producer policy: https://csumb.edu/undersea/sfml-data-library/ . Original members
and distributor links are recorded in the existing catalog; no duplicate survey
or independent-lineage claim is added.

## Overlap refresh, counted once

Adding Block01 to Southern Big Sur / San Simeon r02 increased its selected valid
footprint from 39.604673429 to 53.116323968 km²: **+13.511650539 km²**. Tier-1
planning cells increased by 13.799375 km². The reconstructed candidate count
changed from 427 to 592; this is a net +165 outlines, not 165 confirmed new fish
sites. Supported lingcod ranks changed from 390 to 543; unknown metrics from
37 to 49. Neighboring source overlaps are not counted a second time.

Across all five nonzero private reaches from both batches, current measured
coverage is **67.568532254 km²**, with **785 physical candidates**,
**697 supported lingcod ranks** and **88 unknown**. None is publicly released.
The three-source qualification PR retains its historical pre-refresh result;
this section records the subsequent delta instead of rewriting that history.
