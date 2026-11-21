# Region coverage matrix

| Packaged regions | Visitor status | Need cells | Ready | Partial | Research | Missing | Not applicable |
|---|---|---:|---:|---:|---:|---:|---:|
| 16 | 1 active, 15 preview | 416 | 25 | 149 | 194 | 48 | 0 |

Snapshot: locally available `origin/main` at `c26ef040374f33159ffa978820785006733981d4`. The table and matrix come from R4, not a live check. The cheapest improvements found are five cases where committed evidence can support **partial** coverage without new source rights. None makes a capability ready by itself.

## R1. Committed coverage matrix

Each row's cells come from `dist/regions/<region>/coverage.json:1`, keyed by `needs[].id`. The need list comes from `catalog/data-needs.json` via `src/skippercast/platform/contracts.py:152–155`. `src/skippercast/platform/build.py:140,169–170` builds the report and writes it beside the generated region config.

| Cell | Meaning in the generator (`src/skippercast/platform/contracts.py:412–426,430–443`) |
|---|---|
| R | `ready`: an approved binding exists and the regional evidence explicitly says `ready`. |
| P | `partial`: an approved binding exists and the regional evidence says coverage is incomplete. Read the need's `reason` for the limit. |
| Q | `research`: with no approved binding, a candidate binding produces `research`; with an approved binding, regional evidence can still explicitly say `research`. |
| M | `missing`: no approved or candidate binding, or an approved binding with no recorded state or an explicit `missing`. A restricted binding alone is not coverage. |
| N | `not-applicable`: allowed as an explicit regional state with an approved binding; none is committed here. |

Capability gates accept only `ready` and `not-applicable`; they do not measure freshness or legal permission (`src/skippercast/platform/contracts.py:435–443`).

## R2. Visitor status

The **Visitor status** column in all three panels is the literal `status` from `dist/regions/index.json:1`. R4 checks every entry against `dist/regions/<region>/region.json:1`. The builder omits drafts and copies the configured status instead of calculating it from coverage (`src/skippercast/platform/build.py:90–96,169–176`). This is the status packaged for visitors, not a claim about the currently deployed revision (`docs/regions.md:27`). The second-active-region plan treats reviewed needs, capabilities and a reviewed port/harbor as a proposed bar, not a rule already enforced by the status flag (`docs/plans/second-active-region.md:40–72`).

Columns: 1 `bathymetry`, 2 `substrate`, 3 `groundtruth`, 4 `kelp`, 5 `protected-areas`, 6 `regulations`, 7 `dynamic-closures`

| Region | Visitor status | 1 | 2 | 3 | 4 | 5 | 6 | 7 |
|---|---|---|---|---|---|---|---|---|
| `big-sur-coast` | preview | Q | Q | Q | Q | P | P | P |
| `bodega-point-reyes` | preview | P | Q | Q | Q | P | P | Q |
| `cambria-san-simeon` | preview | P | P | Q | Q | R | R | R |
| `crescent-city` | preview | P | Q | Q | Q | P | P | Q |
| `fort-bragg-point-arena` | preview | P | Q | Q | Q | P | P | Q |
| `humboldt-bay-cape-mendocino` | preview | P | Q | Q | Q | P | P | Q |
| `monterey-point-sur` | preview | Q | Q | Q | Q | P | P | P |
| `morro-bay` | active | P | R | Q | Q | R | R | R |
| `point-arena-bodega` | preview | P | Q | Q | Q | P | P | Q |
| `point-arguello-conception` | preview | P | Q | Q | Q | P | P | Q |
| `point-reyes-pigeon` | preview | Q | Q | Q | Q | P | P | P |
| `santa-cruz-monterey-bay` | preview | Q | Q | Q | Q | P | P | P |
| `shelter-cove-north-mendocino` | preview | P | Q | Q | Q | P | P | P |
| `south-big-sur-san-simeon` | preview | Q | Q | Q | Q | P | P | P |
| `southern-california` | preview | P | P | Q | P | R | R | P |
| `trinidad-klamath` | preview | Q | Q | Q | Q | P | P | Q |

Columns: 8 `wind-forecast`, 9 `wave-forecast`, 10 `wave-observations`, 11 `weather-observations`, 12 `tides`, 13 `surface-currents`, 14 `subsurface-ocean`, 15 `sea-temperature`, 16 `chlorophyll`

| Region | Visitor status | 8 | 9 | 10 | 11 | 12 | 13 | 14 | 15 | 16 |
|---|---|---|---|---|---|---|---|---|---|---|
| `big-sur-coast` | preview | P | P | P | P | P | P | Q | P | P |
| `bodega-point-reyes` | preview | P | P | P | P | P | Q | Q | P | P |
| `cambria-san-simeon` | preview | R | R | P | P | R | P | Q | P | P |
| `crescent-city` | preview | P | P | P | P | P | Q | Q | P | P |
| `fort-bragg-point-arena` | preview | P | P | P | P | P | Q | Q | P | P |
| `humboldt-bay-cape-mendocino` | preview | P | P | P | P | P | Q | Q | Q | Q |
| `monterey-point-sur` | preview | P | P | P | P | P | P | Q | P | P |
| `morro-bay` | active | R | R | R | P | R | P | Q | P | P |
| `point-arena-bodega` | preview | Q | Q | Q | Q | Q | Q | Q | Q | Q |
| `point-arguello-conception` | preview | P | P | P | P | P | Q | Q | Q | Q |
| `point-reyes-pigeon` | preview | P | P | P | P | P | P | Q | P | P |
| `santa-cruz-monterey-bay` | preview | P | P | P | P | P | P | Q | P | P |
| `shelter-cove-north-mendocino` | preview | P | P | P | P | P | Q | Q | P | P |
| `south-big-sur-san-simeon` | preview | P | P | P | P | P | Q | Q | P | P |
| `southern-california` | preview | R | R | P | P | R | P | Q | P | P |
| `trinidad-klamath` | preview | Q | Q | Q | Q | Q | Q | Q | Q | Q |

Columns: 17 `species-occurrence`, 18 `catch-effort`, 19 `historical-charter-grounds`, 20 `charter-identity`, 21 `ais-history`, 22 `harbor-access`, 23 `wind-ensemble`, 24 `wave-ensemble`, 25 `forecast-verification`, 26 `seasonal-climate`

| Region | Visitor status | 17 | 18 | 19 | 20 | 21 | 22 | 23 | 24 | 25 | 26 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `big-sur-coast` | preview | Q | Q | M | M | Q | P | Q | Q | Q | M |
| `bodega-point-reyes` | preview | Q | Q | M | M | Q | Q | Q | Q | Q | M |
| `cambria-san-simeon` | preview | Q | P | M | M | P | P | R | R | P | M |
| `crescent-city` | preview | Q | Q | M | M | Q | Q | Q | Q | Q | M |
| `fort-bragg-point-arena` | preview | Q | Q | M | M | Q | Q | Q | Q | Q | M |
| `humboldt-bay-cape-mendocino` | preview | Q | Q | M | M | Q | Q | Q | Q | Q | M |
| `monterey-point-sur` | preview | Q | Q | M | M | Q | P | Q | Q | Q | M |
| `morro-bay` | active | Q | P | M | M | P | P | R | R | P | M |
| `point-arena-bodega` | preview | Q | Q | M | M | Q | Q | Q | Q | Q | M |
| `point-arguello-conception` | preview | Q | Q | M | M | Q | Q | Q | Q | Q | M |
| `point-reyes-pigeon` | preview | Q | Q | M | M | Q | Q | Q | Q | Q | M |
| `santa-cruz-monterey-bay` | preview | Q | Q | M | M | Q | Q | Q | Q | Q | M |
| `shelter-cove-north-mendocino` | preview | Q | Q | M | M | Q | Q | Q | Q | Q | M |
| `south-big-sur-san-simeon` | preview | Q | Q | M | M | Q | Q | Q | Q | Q | M |
| `southern-california` | preview | Q | Q | M | M | Q | P | R | R | P | M |
| `trinidad-klamath` | preview | Q | Q | M | M | Q | Q | Q | Q | Q | M |

## R3. Cheapest coverage gaps to close

Ranked by estimated hands-on engineering time, including a focused test and regeneration, not PR wait or a live run. These close the **unrecorded partial coverage** gaps, not the remaining gaps to `ready`. Use the dated evidence below and existing approved bindings; keep the state unchanged if the evidence does not support the stated scope. No source approval, station failover change, or owner decision is proposed for these five. The rights register lists the existing tide, buoy and model sources at `docs/legal/data-rights-register.md:186–190,202`; the September model receipt is historical and does not certify the current delivery path.

For each row, edit only the named need in the region source file and rebuild the generated package with `src/skippercast/platform/build.py:139–176` (including the region/coverage JSON and any derived readiness output; never hand-edit those files). Add the named focused check in the existing test file; the tests below are **proposed**, not run for this report. Each check should compare `requirement_report()` and the committed rebuilt cell, including its limiting reason.

| Rank | Need and proposed closure | Evidence on main | Files and focused test | Estimate |
|---:|---|---|---|---|
| 1 | Trinidad–Klamath `tides`: record the dated Trinidad Harbor high/low prediction check as `partial`, water levels only. | `regions/trinidad-klamath/region.json:109–112,177–179,277–280` records NOAA 9419059, subordinate to 9419750. `dist/regions/trinidad-klamath/coverage.json:1` still says `research`. | `regions/trinidad-klamath/region.json`, generated `dist/regions/trinidad-klamath/{region,coverage}.json`; extend `tests/contract/test_trinidad_klamath_draft.py:60–67` to assert 9419059 and subordinate water-level-only scope, with `tide-chart` still not ready. | 25–40 min |
| 2 | Point Arena–Bodega `tides`: record the documented Arena Cove and Bodega Harbor predictions as `partial` reference coverage, not a current or entrance forecast. | `docs/archive/point-arena-bodega-rollout.md:3–5`; regional references and distinct context stations in `regions/point-arena-bodega/region.json:102–105,355–387`; committed `research` in `dist/regions/point-arena-bodega/coverage.json:1`. | `regions/point-arena-bodega/region.json`, generated `dist/regions/point-arena-bodega/{region,coverage}.json`; add `test_arena_tide_reference_coverage` to `tests/contract/test_platform.py` (pattern at lines 151–155): keep both station IDs distinct and make `tide-chart` stay not ready. | 30–45 min |
| 3 | Point Arena–Bodega `wave-observations`: record the existing offshore references as `partial`; no nearshore measurement or new backup. | `docs/archive/point-arena-bodega-rollout.md:5`; `regions/point-arena-bodega/region.json:108–113`; committed `research` in `dist/regions/point-arena-bodega/coverage.json:1`. | Same Point Arena–Bodega source/generated files; add `test_arena_wave_reference_coverage` to `tests/contract/test_platform.py` (lines 151–155): 46013/46014 stay offshore references and the coverage reason explicitly denies cove/entrance measurement. | 35–50 min |
| 4 | Point Arena–Bodega `wind-forecast`: record the dated GFS/IFS collection for the three configured samples as `partial`; no continuous availability or accuracy claim. | `docs/archive/point-arena-bodega-rollout.md:5`; `regions/point-arena-bodega/region.json:74–96,155–159`; committed `research` in `dist/regions/point-arena-bodega/coverage.json:1`. | Same Point Arena–Bodega source/generated files; add `test_arena_wind_sample_coverage` to `tests/contract/test_platform.py` (lines 151–167): three regional points, both model IDs, `conditions-outlook` still not ready. | 45–65 min |
| 5 | Point Arena–Bodega `wave-forecast`: record the same collection's GFS Wave/WAM evidence as `partial` for the configured samples; do not claim nearshore or verified skill. | `docs/archive/point-arena-bodega-rollout.md:5`; `regions/point-arena-bodega/region.json:74–96,160–163`; committed `research` in `dist/regions/point-arena-bodega/coverage.json:1`. | Same Point Arena–Bodega source/generated files; add `test_arena_wave_sample_coverage` to `tests/contract/test_platform.py` (lines 151–167): both distinct wave models are bound, the receipt is dated, and `conditions-outlook` still not ready. | 45–70 min |

### Decisions and evidence still needed (not included in the estimates)

| Gap | Decision or prerequisite, not decided here |
|---|---|
| Cambria–San Simeon native bathymetry and substrate | `csumb-cambria` reuse/redistribution permission remains unresolved. For the separate CSUMB co-produced USGS substrate/habitat products used by Morro Bay and other coastal packages, commercial permission is a separate decision; do not infer rights from coverage. `docs/legal/data-rights-register.md:82–96,216,234–235`; `docs/regions.md:31`. |
| Big Sur and South Big Sur–San Simeon habitat, and candidate kelp coverage | PMEP compilation terms (`pmep-hapc`) and `kelpwatch` product-specific terms/technical qualification still need their own dispositions. The Kelpwatch display decision is not a regional data qualification. `docs/legal/data-rights-register.md:61,92–96,207,235`. |
| Charter grounds, identity, and AIS | DS1091 permission for historical charter grounds; fleet source terms and aggregate-only use for identity; MarineCadastre conditions review and Global Fishing Watch noncommercial terms for AIS. `docs/legal/data-rights-register.md:77–81,141–161,213–217`. All 16 regions have missing charter grounds and identity (R4); no registry collection or publication is proposed. |
| Regulations, closures and harbor access | Dated legal/access review is not an engineering checkbox; Southern California's Navy range schedule and live clearance are separate. Owner decides the scope of any future closure claim and any `active` threshold/promotion. No local clearance is supplied. `docs/regions.md:8–13,49`; `docs/regulations.md:7`; `docs/plans/second-active-region.md:63–72,171–173`. Morro Bay shore review dates likewise require human renewal (`scripts/collect_shore_habitat.py:12–14,59–62`). |
| Measured bottom and forecast skill | No ready label from a discovery lead, historical outline, or first fetch. Exact-footprint native depth/datum, classification and exclusion checks are needed for a fishing target (`docs/regions.md:8–12`; `docs/archive/point-arena-bodega-rollout.md:9–11`). Morro Bay forecast verification needs prospective matches across time (`dist/regions/morro-bay/coverage.json:1`). `seasonal-climate` is missing across the matrix; a suitable source and reviewed coverage are not established here (R4). |

## R4. Offline reproduction

From the repository root, save this script outside the checkout as `rebuild_matrix.py`, then run `python ../rebuild_matrix.py` if saved beside the checkout. It reads pinned Git blobs, not the current working tree; it builds no data and uses no network. The printed totals and all three panels above come from this script.

```python
import json
import subprocess
from collections import Counter

BASE = 'c26ef040374f33159ffa978820785006733981d4'


def read(path):
    data = subprocess.check_output(['git', 'show', f'{BASE}:{path}'], text=True)
    assert len(data.splitlines()) == 1, path  # generated line citations
    return json.loads(data)


index = read('dist/regions/index.json')['regions']
columns, rows = None, []
counts = Counter()
key = {'ready': 'R', 'partial': 'P', 'research': 'Q', 'missing': 'M', 'not-applicable': 'N'}
for entry in index:
    name = entry['id']
    path = f'dist/regions/{name}'
    config = read(f'{path}/region.json')
    coverage = read(f'{path}/coverage.json')
    assert config['id'] == coverage['region_id'] == name
    assert config['status'] == entry['status']
    cells = {n['id']: n['status'] for n in coverage['needs']}
    if columns is None:
        columns = list(cells)
    assert list(cells) == columns and len(cells) == len(coverage['needs'])
    counts.update(cells.values())
    rows.append((name, entry['status'], [key[cells[k]] for k in columns]))
assert len({r[0] for r in rows}) == len(rows) == 16 and len(columns) == 26
print('Visitor status:', dict(Counter(r[1] for r in rows)))
print('Need totals:', dict(counts))
for start, stop in ((0, 7), (7, 16), (16, 26)):
    header = ['Region', 'Visitor status'] + [str(i + 1) for i in range(start, stop)]
    print('\nColumns:', ', '.join(f'{i + 1} `{columns[i]}`' for i in range(start, stop)))
    print('| ' + ' | '.join(header) + ' |')
    print('|' + '---|' * len(header))
    for name, status, values in rows:
        print('| ' + ' | '.join([f'`{name}`', status, *values[start:stop]]) + ' |')
```
