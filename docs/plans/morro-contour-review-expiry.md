# Morro Bay depth contours: review expiry

| Question | Answer | Evidence |
| --- | --- | --- |
| Last valid UTC date | **September 26, 2027**, inclusive, for both served files | R1 GETs; `web/map/depth-contours.ts:217`; `dist/trip-export.js:73` |
| First refusal | **September 27 at 00:00 UTC = September 26 at 5:00 p.m. PDT** for fresh checks. An already open Chart can keep drawing; the planner can still hand over a recently prepared GPX. | R2 |
| Time left | About **309 days and 7 hours** at the November 21, 2026 public readback | R2 calculation |
| Owner's next step | Schedule the source re-review and release work **by Friday, August 27, 2027** (recommended); the region build stamps both files after the review is recorded. | R3–R4 |

File and line references are to `origin/main` at `e2cfc500163c0551cda4458f738e68cec04af6b3`. The six cited input/consumer files had no diff from the card baseline (`git diff d52008bfba3a55529a4965c23243cf487838ffad origin/main -- src/skippercast/platform/depth_contours.py catalog/depth-contours/morro-bay.geojson web/map/depth-contours.ts web/app/Legend.tsx web/planner.ts dist/trip-export.js`).

## R1. What the public files and catalog actually carry

Read-only GETs on November 21, 2026; the hashes are over the response bodies. The excerpts quote the HTTP status and date, the two review fields, and each listed source's ID and survey date (other fields omitted).

> GET `https://skippercast.com/regions/morro-bay/depth-contours.geojson`
>
> `HTTP/2 200` · `date: Sat, 21 Nov 2026 16:43:47 GMT` · 804,575 bytes
>
> SHA-256 `594a213c27c84385145765faa4b8df99feef154615af362a3d3f99a27ea47876`
>
> `"review_expires":"2027-09-26","review_days":365`;
> `"usgs-point-buchon"`, `"usgs-morro-bay"`, `"usgs-point-estero"`: each `"survey_date":"2008"`.

> GET `https://skippercast.com/regions/morro-bay/depth-contours-overview.geojson`
>
> `HTTP/2 200` · `date: Sat, 21 Nov 2026 16:43:47 GMT` · 53,441 bytes
>
> SHA-256 `187561c00c777a769212de2da231756f82c442c6fa8514e62541364207e7ac0b`
>
> `"review_expires":"2027-09-26","review_days":365`;
> `"usgs-point-buchon"`, `"usgs-morro-bay"`, `"usgs-point-estero"`: each `"survey_date":"2008"`.

The three `reviewed_at` dates are **not carried** in either response or in the contour catalog copy. All three are **2026-09-26** in `catalog/sources.json:6–16,51–61,95–105`. Survey year `2008` is acquisition metadata, not review age. The oldest **included** source review plus 365 days gives `2027-09-26` (`src/skippercast/platform/depth_contours.py:137–138,560–568`; `date -ud '2026-09-26 + 365 days' +%F`). All three forms list `noaa-bag` under `sources_omitted` as `approved`; its catalog review of `2026-10-30` does not enter the calculation (`catalog/sources.json:174–185`; `depth_contours.py:563–568,620–628`, same path as above).

The committed input `catalog/depth-contours/morro-bay.geojson:1` (SHA-256 `3fb67bbb42f6b0b453e15dff83577106ad89d4458341432ce5e2c049df788874`) has the same sources and 40 features, but no `review_expires` or `review_days`. After removing those two fields and sorting JSON keys, the public full file matches the input. The overview keeps the same review and source metadata but has 39 features, four coordinate decimals instead of five, simplified geometry and an `overview` record (`src/skippercast/platform/depth_contours.py:518–557,617–630`). Both HTTP hashes match the corresponding tracked `dist/regions/morro-bay/depth-contours*.geojson` at the pinned main. To reproduce the comparison, save each GET body with `curl -fsS -D headers -o body URL` (substitute the exact URL), use `sha256sum body` and `jq '.provenance' body`, and compare `jq -cS 'del(.provenance.review_expires,.provenance.review_days)' body` for the full file with `jq -cS . catalog/depth-contours/morro-bay.geojson`.

## R2. What visitors see at the cutoff

Both comparisons use the UTC calendar date and test `today > review_expires`, not `>=`. So the first expired instant is **2027-09-27 00:00:00 UTC**, or **2027-09-26 17:00:00 PDT (UTC−07:00)** in `America/Los_Angeles` (`regions/morro-bay/region.json:6`; `web/map/depth-contours.ts:169–173,217,410–418`; `web/planner.ts:352–358`; `dist/trip-export.js:62–73`). From the GET time to that instant is **309 days, 7 hours, 16 minutes, 13 seconds**. Reproduce by subtracting `date -ud '2026-11-21T16:43:47Z' +%s` (1795279427) from `date -ud '2027-09-27T00:00:00Z' +%s` (1822003200); convert with `TZ=America/Los_Angeles date -d '2027-09-27T00:00:00Z'`. The margin is from the confirmed public serving time, not an inferred launch timestamp.

- **Chart:** On a check at or after the cutoff, neither form draws. The legend says “Depth contours withheld: their source review is past its one-year age limit.” (`web/map/depth-contours.ts:116–121,217,444–456`; `web/app/Legend.tsx:389–406`). The open Chart checks on file load, not on a midnight timer; a same-file camera move does not recheck a successfully loaded file. Reloading the Chart checks again (`web/map/depth-contours.ts:410–442`).
- **Trip planner, with Depth contour tracks on:** A fresh full-file check says “Depth contours withheld: their source review is past its one-year age limit. Turn off depth contour tracks to export.” The planner blocks the download rather than silently dropping the requested tracks (`web/planner.ts:150–161,266–285`; `web/app/Planner.tsx:346–365`). When it generates a GPX from previously loaded contours after midnight, it rechecks the review and can say “Depth contours cannot be exported: source review expired or undated. Turn off depth contour tracks or reload the region.” (`web/planner.ts:528–551`; `dist/trip-export.js:62–73,136,161`). However, if the summary still passes and the plan key is unchanged, Download or Share can reuse a GPX prepared before midnight while that file is less than 60 seconds old; there is no separate expiry check at that handoff (`web/planner.ts:695–739`). Turning the tracks off removes this blocker, not other trip checks (`web/planner.ts:267–277`).

## R3. Who refreshes it, and how

1. **The map/data owner gets a fresh source review accepted and recorded** before republishing. The source reviewer must decide whether the three included grid inputs are still acceptable for this display use. All three currently tie for oldest, so updating only one or two leaves the expiry unchanged. A new survey or new geometry is not required just to renew the review of the same inputs. Rebuilding unchanged inputs and review dates cannot buy any time (`catalog/sources.json:6–16,51–61,95–105`; `src/skippercast/platform/depth_contours.py:319–349,560–568`). No acceptance, rights decision or hold change was made here.
2. **Regenerate the release files:** With the repo package importable, the owner runs `python -m skippercast.platform.build`. This is the step that reads `catalog/depth-contours/morro-bay.geojson` and the source catalog, validates approved bound bathymetry, rejects a held collection or explicit display denial, stamps both forms, enforces both byte budgets and lists the files in generated `region.json`. The regional build also requires valid regional bindings, reviewed regulatory inputs and existing regional assets (`src/skippercast/platform/build.py:39–48,82–100,122–139,169–173,190–193`; `src/skippercast/platform/depth_contours.py:319–349,589–636`; `regions/morro-bay/region.json:286–292`). If geometry actually needs retracing, that is a separate owner step: `python scripts/build_depth_contours.py --region morro-bay` with the three `--grid SOURCE_ID=PATH` arguments, the survey stack and approved original or hash-bound normalized GeoTIFF inputs. It writes the catalog input, not the served pair; held output cannot be published (`scripts/build_depth_contours.py:1–28,713–730,973–975`).
3. **Republish through the normal main release:** Commit the reviewed inputs and regenerated `dist/regions/morro-bay/depth-contours.geojson` and `depth-contours-overview.geojson`; CI rebuilds and checks that generated files match (`.github/workflows/ci.yml:374–386`). The Cloudflare release selects checked main, runs `pnpm build`, and copies the checked-in `dist` assets into `dist/client` at those same relative paths before deploying and smoke-testing. After authorized deployment, read back both public URLs and check their date and hashes against the intended release pair (`.github/workflows/deploy-cloudflare.yml:50–57,162–172,224–227,247–266,398–412`; `package.json:10`; `scripts/build-worker.mjs:13–20`; `scripts/client-build.mjs:104–113,195–205`; `wrangler.jsonc:13`).

## R4. Schedule and one small follow-up

**Schedule the owner review and release work by Friday, August 27, 2027.** This is a recommendation, not a deadline in code: it is one day before the 30-day lead date (`date -ud '2027-09-27 - 30 days' +%F` → `2027-08-28`). The buffer is for the human decision, checked build and public readback in R3, not an estimate of how long those steps take.

No change is needed to renew the stamp. Prioritize one separate planner fix (**estimate: 90 minutes**): check the contour review day immediately before handing a prepared GPX to Download or Share; discard an expired prepared file and show the existing refusal without saving or sharing it. Limit the change to `web/planner.ts` and `tests/test_planner_retry.mjs`. With a fake clock and synthetic contour file, prepare at `23:59:59Z` and try delivery at `00:00:00Z` without changing the plan key; assert refusal and no save/share. Keep a same-day delivery control and verify tracks-off export is unaffected. Run `node --test tests/test_planner_retry.mjs` offline with locked dependencies installed. Preserve the existing cutoff and exporter guard. This report does not make that change or touch data, caches or publication.
