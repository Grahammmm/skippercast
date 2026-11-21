# Jurisdiction review file chain

| Jurisdiction (`jurisdictions/<id>.json`) | Files | Last filename date | Last `reviewed_at` date (UTC) | Registry actually loaded (normal pipeline) | Pending file |
| --- | ---: | --- | --- | --- | --- |
| `california-central` | 9 | 2026-11-14 | 2026-11-14 | `dist/data/regulations.json` | 1 |
| `california-mendocino` | 3 | 2026-09-24 | 2026-09-25 | `dist/data/regulations-mendocino.json` | 0 |
| `california-northern` | 4 | 2026-10-20 | 2026-10-20 | `dist/data/regulations-northern.json` | 0 |
| `california-san-francisco` | 4 | 2026-09-25 | 2026-09-25 | `dist/data/regulations-san-francisco.json` | 0 |
| `california-southern` | 2 | 2026-09-24 | 2026-09-24 | `dist/regions/southern-california/regulations.json` | 0 |

Offline snapshot: local `origin/main` at `34761911d5c44a903873867426f316c7f1e5911c`, read 2026-11-21. The summary is derived from the R1 inventory and registry lookup below: 21 date-prefixed files plus one `PENDING-` file. No regulation, rights or review decision is made here.

## R1. Files and what the loader reads

**No review decision file is selected by the normal loader.** `src/skippercast/pipeline/regulation_review.py:27–34` opens the jurisdiction JSON, then reads the asset it names under `dist/`; `src/skippercast/pipeline/settings.py:22–33` and `src/skippercast/platform/build.py:42` use the same asset lookup. `schemas/jurisdiction.schema.json:7–11` requires `regulations_asset`. `src/skippercast/pipeline/regulations.py:206–259` computes snapshot status from registry content and source checks, not a review filename. The explicit review CLI is different: it reads only the caller-supplied decision path (`src/skippercast/pipeline/regulation_review.py:322–325,345–355`; `docs/regulations.md:62–68`). On apply, `review_record` is copied from `record_path` as provenance (`regulation_review.py:212–216`), not opened by that assignment. This is the hash-bound workflow described in `docs/legal/threat-model.md:115`, not a latest-filename rule.

| Jurisdiction asset binding | Registry's `review_record` basename (pointer, not a loader read) | Pointer evidence |
| --- | --- | --- |
| `jurisdictions/california-central.json:4` | `2026-11-14-california-central.json` | `dist/data/regulations.json:956` |
| `jurisdictions/california-mendocino.json:4` | `2026-09-24-california-mendocino-shelter-cove-all-mpas.json` | `dist/data/regulations-mendocino.json:50` |
| `jurisdictions/california-northern.json:4` | `2026-10-20-california-northern-trinidad-klamath.json` | `dist/data/regulations-northern.json:59` |
| `jurisdictions/california-san-francisco.json:4` | `2026-09-25-california-san-francisco-point-arena-bodega.json` | `dist/data/regulations-san-francisco.json:59` |
| `jurisdictions/california-southern.json:4` | `2026-09-24-california-southern-canonical-crab.json` | `dist/regions/southern-california/regulations.json:1459` |

Rows are grouped by `.jurisdiction_id`, sorted by filename date, then by `reviewed_at` within the day. Scope is the filename suffix only; “unqualified” means no extra suffix, not a claim about what was reviewed. `Absent` means no top-level `status` key; it is not a decision or a computed `rules_review_status`. In the last column, “none found” means no checked-in decision-file read identified, not that a caller could never supply the path to `--decision`.

| Jurisdiction | Basename under `jurisdictions/reviews/` | Filename date | Filename scope | `reviewed_at` (UTC) | `status` | Checked-in decision-file reader (R2) |
| --- | --- | --- | --- | --- | --- | --- |
| Central | `2026-09-22-california-central.json` | 2026-09-22 | unqualified | 2026-09-22T15:58:13Z | Absent | none found |
| Central | `2026-09-24-california-central-canonical-crab.json` | 2026-09-24 | canonical-crab | 2026-09-24T21:30:56Z | Absent | none found |
| Central | `2026-09-24-california-central-point-arguello-conception.json` | 2026-09-24 | point-arguello-conception | 2026-09-25T04:05:42Z | Absent | none found |
| Central | `2026-09-25-california-central-santa-cruz-monterey-bay.json` | 2026-09-25 | santa-cruz-monterey-bay | 2026-09-25T06:53:08Z | Absent | none found |
| Central | `2026-09-25-california-central-monterey-point-sur.json` | 2026-09-25 | monterey-point-sur | 2026-09-25T07:09:00Z | Absent | none found |
| Central | `2026-09-25-california-central-big-sur.json` | 2026-09-25 | big-sur | 2026-09-25T07:21:00Z | Absent | none found |
| Central | `2026-09-25-california-central-south-big-sur.json` | 2026-09-25 | south-big-sur | 2026-09-25T08:09:03Z | Absent | none found; historical pointer |
| Central | `PENDING-2026-11-13-california-central.json` | 2026-11-13 | unqualified; PENDING prefix | `null` | Absent | exact-path contract test |
| Central | `2026-11-14-california-central.json` | 2026-11-14 | unqualified | 2026-11-14T22:08:33Z | Absent | registry-pointer GIS tests |
| Mendocino | `2026-09-24-california-mendocino.json` | 2026-09-24 | unqualified | 2026-09-24T17:47:36Z | Absent | none found |
| Mendocino | `2026-09-24-california-mendocino-canonical-crab.json` | 2026-09-24 | canonical-crab | 2026-09-24T21:28:54Z | Absent | none found |
| Mendocino | `2026-09-24-california-mendocino-shelter-cove-all-mpas.json` | 2026-09-24 | shelter-cove-all-mpas | 2026-09-25T06:22:54Z | Absent | registry-pointer GIS test |
| Northern | `2026-09-24-california-northern.json` | 2026-09-24 | unqualified | 2026-09-24T18:44:47Z | Absent | none found |
| Northern | `2026-09-24-california-northern-canonical-crab.json` | 2026-09-24 | canonical-crab | 2026-09-24T21:28:54Z | Absent | none found |
| Northern | `2026-09-24-california-northern-humboldt-cape.json` | 2026-09-24 | humboldt-cape | 2026-09-25T03:25:14Z | Absent | none found |
| Northern | `2026-10-20-california-northern-trinidad-klamath.json` | 2026-10-20 | trinidad-klamath | 2026-10-20T23:14:46Z | Absent | registry-pointer contract test |
| San Francisco | `2026-09-24-california-san-francisco.json` | 2026-09-24 | unqualified | 2026-09-24T18:18:36Z | Absent | none found |
| San Francisco | `2026-09-24-california-san-francisco-canonical-crab.json` | 2026-09-24 | canonical-crab | 2026-09-24T21:28:54Z | Absent | none found |
| San Francisco | `2026-09-25-california-san-francisco-point-reyes-pigeon.json` | 2026-09-25 | point-reyes-pigeon | 2026-09-25T12:09:51Z | Absent | none found |
| San Francisco | `2026-09-25-california-san-francisco-point-arena-bodega.json` | 2026-09-25 | point-arena-bodega | 2026-09-25T13:10:13Z | Absent | registry-pointer GIS tests |
| Southern | `2026-09-22-california-southern.json` | 2026-09-22 | unqualified | 2026-09-22T15:58:13Z | Absent | none found |
| Southern | `2026-09-24-california-southern-canonical-crab.json` | 2026-09-24 | canonical-crab | 2026-09-24T21:30:56Z | Absent | none found; current registry pointer |

Reproduce from a clean checkout of the snapshot, using metadata only:

```sh
 git ls-tree -r --name-only HEAD jurisdictions
 jq -cr '[input_filename,.jurisdiction_id,.reviewed_at,(if has("status") then .status else "ABSENT" end)]' jurisdictions/reviews/*.json
 jq -cr '[input_filename,.id,.regulations_asset]' jurisdictions/*.json
 jq -cr '[input_filename,.reviewed_at,.review_record]' dist/data/regulations*.json dist/regions/southern-california/regulations.json
```

## R2. Names without a reader and the `PENDING-` prefix

All 22 basenames are outside normal loader selection. Of those, the 17 “none found” rows are also not opened by a checked-in named reader or review-selection pattern found in this snapshot. The southern canonical-crab file is pointed to but not opened; the south Big Sur record appears as a historical pointer (`dist/data/daily-evidence.json:1`, `tests/fixtures/regulations/fe61-v1.json:1631`). `tests/contract/test_schemas.py:89–90` uses a nonrecursive `jurisdictions/*.json` glob that excludes the entire review subdirectory.

Four files are opened by tests through the registry pointers above. The test's region name does not select a same-named review file:

| `review_record` resolved from | Test opens the pointed-to JSON at |
| --- | --- |
| Central registry through `settings()` | `tests/gis/test_big_sur_region.py:28–29`, `tests/gis/test_monterey_point_sur_region.py:31–33`, `tests/gis/test_santa_cruz_region.py:38–40`, `tests/gis/test_south_big_sur_region.py:32–33` |
| Mendocino registry through `regions/shelter-cove-north-mendocino/region.json:322` | `tests/gis/test_shelter_cove_region.py:35–38` |
| Northern registry by explicit registry path | `tests/contract/test_trinidad_klamath_review.py:16–23` |
| San Francisco registry through `settings()` | `tests/gis/test_point_arena_bodega_region.py:27–29`, `tests/gis/test_point_reyes_pigeon_region.py:66–68` |

**There is no production `PENDING-` prefix rule.** The CLI reads the supplied `Path` regardless of name, then validates contents; the pending file's `reviewed_at` is `null`, which fails the time-shape check if explicitly supplied (`regulation_review.py:140–150,170–173,325,354`). The contract test deliberately opens that one literal path (`tests/contract/test_rules_policy_a_and_pending_review.py:10,64–74`); that is not a prefix match or a selection rule.

Read-only search commands used to distinguish direct reads, provenance pointers and test references:

```sh
 git grep -ln 'jurisdictions/reviews' -- tests src scripts
 git grep -n -o -E 'jurisdictions/reviews/[[:alnum:].-]+\.json' -- . ':!jurisdictions/reviews'
 git grep -n -o -E 'review_record|record_path|PENDING-|jurisdictions.{0,15}reviews' -- '*.py' '*.mjs' '*.ts' '*.tsx' '*.sh' '*.yml' ':!tests/fixtures'
```

## R3. Earlier last-review dates

Date comparison only, not a judgement about review quality, currency or coverage. Central has the newest dated file and newest recorded UTC review date, both **2026-11-14** (R1 inventory). Each of these jurisdiction files has no later review file on this snapshot:

| Jurisdiction file | Latest filename date | Latest recorded UTC review date |
| --- | --- | --- |
| `jurisdictions/california-mendocino.json` | 2026-09-24 | 2026-09-25 |
| `jurisdictions/california-northern.json` | 2026-10-20 | 2026-10-20 |
| `jurisdictions/california-san-francisco.json` | 2026-09-25 | 2026-09-25 |
| `jurisdictions/california-southern.json` | 2026-09-24 | 2026-09-24 |

## R4. Follow-up

No buildable unit is needed for this inventory. The explicit CLI path and the registry loader are separate (R1); R2–R3 identify filenames and dates, not a reason to change selection or review policy.
