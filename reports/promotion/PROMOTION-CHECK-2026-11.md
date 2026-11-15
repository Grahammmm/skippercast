# Region promotion preflight, re-run after the signed Central Coast rules (SC1114-02)

Technical preflight only. A PASS here is not permission to promote any region. Human/legal approval and the beta GO gate still apply, and nothing in this report lifts the Morro Bay hold.

## Setup

- Clean shallow clone of `origin/main`, branch `rb/sc1114-02`. **main SHA: `f8a679d1451141ccad443d65d5138a0cbb6e3074`**. `origin/main` was unchanged when re-fetched after the runs.
- Node v22.23.2. Dependencies from `pnpm install --frozen-lockfile` (lockfile untouched). No build was needed.
- Tool: `node scripts/check_region_promotion.mjs`, default origin `https://skippercast.com`. Each region was run on its own, four argv forms each (text and `--json`, now and `--rules-through 2027-01-31`). 24 runs in all. No fake clock, alternate origin or credentials.
- Runs took place 2026-11-15 20:23:10Z to 20:23:43Z. The manifest, with argv, start/end times and exit codes for every run, is `raw/SC1114-02-runs.json`.
- All GETs were anonymous and read-only. No stderr was produced (no `.stderr.txt` files).

## Deployed SHA

The smoke check of all 24 runs read **live head `f8a679d1451141ccad443d65d5138a0cbb6e3074`**, the same as the local main SHA. There was no deployment drift. A separate `/api/health` GET at 2026-11-15T20:23:52Z, not the smoke check, returned the same revision (`"revision_dirty": false`, build `391fd2209a`, version 0.8.0): `raw/SC1114-02-api-health.json`.

## Result: all six regions PASS, in both horizons and both modes

Exit code is 0 for every run. There is no failed check code in any run.

| Region | Now: text exit / JSON exit | Now result | Through 2027-01-31: text / JSON exit | Through 2027-01-31 result | Failed checks |
|---|---|---|---|---|---|
| cambria-san-simeon | 0 / 0 | PASS | 0 / 0 | PASS | none |
| south-big-sur-san-simeon | 0 / 0 | PASS | 0 / 0 | PASS | none |
| big-sur-coast | 0 / 0 | PASS | 0 / 0 | PASS | none |
| monterey-point-sur | 0 / 0 | PASS | 0 / 0 | PASS | none |
| point-arguello-conception | 0 / 0 | PASS | 0 / 0 | PASS | none |
| morro-bay (control) | 0 / 0 | PASS | 0 / 0 | PASS | none |

Every region passed all six checks (`package`, `feeds`, `tides`, `rules`, `habitat`, `smoke`). The `rules` detail reads "valid through 2027-03-31" (past the 2027-01-31 horizon) and lists seven species. Each species, for example in `big-sur-coast`, is open, closed or restricted as listed, not "reason" failures:

`lingcod:open, rockfish:open, halibut:open, salmon:closed, dungeness:restricted, albacore:open, bluefin:open`

- `package` detail is `preview` for every region. They are still previews.
- The JSON `checked_at` stamps run 20:23:13Z (cambria) to 20:23:42Z (morro-bay, through-2027-01-31). The text and JSON runs for the same region/horizon are 1 to 2 seconds apart and agree on every verdict. No drift was observed. Raw outputs: `raw/SC1114-02-<region>-<now|through-2027-01-31>.<txt|json>`.
- There was no exit 1 or 2 and no early package failure, so none of the failure-path rows apply.

## What changed since R4-SC-10 (2026-11-13)

- Then: all six regions failed `rules` with `rules.reason.sourceChanged` for seven species. The other five checks passed. That run used the PR head `09224070`, not merged main, and live `114079ae`.
- Now: all six pass `rules`. Seven species resolve open, closed or restricted, valid through 2027-03-31.
- The causes, from main history: the checker is merged (SCB-17, PR 2207). G's signed Central Coast rules review was applied (`71444dff3a`). The 2027 decision (30 sources approved, `access-vandenberg-maritime` held) was recorded and regenerated into the regional copies (`7f63bc57d8`, `5c8047a5a2`, `e1bbac91d8`). The public rules have `reviewed_at` 2026-11-14T22:08:33Z.
- Unchanged: the other five checks pass as before, and the regions remain `preview`. Deployed SHA moved from `114079ae` to `f8a679d1`, which is the current main.

## Does the held Vandenberg source still fail point-arguello-conception?

**No. The promotion check passes for point-arguello-conception despite the hold. The hold is still in place, and it is not a gate in this tool.**

- `jurisdictions/reviews/2026-11-14-california-central.json:116-119` still holds `access-vandenberg-maritime` (`decision: hold`, `content_sha256: null`, "unfetched row stays on hold, as G signed 2026-11-14 07:10").
- The public regulations for the region (`/api/daily?region=point-arguello-conception&part=regulations`, `raw/SC1114-02-pa-api-daily-regulations.json`) still show:
  - `sources.access-vandenberg-maritime.approved_content_sha256 = null`.
  - `checks.access-vandenberg-maritime = {status: "unavailable", source_status: "failed", content_sha256: null}`, checked 2026-11-15T18:52:32Z.
  - `review_required = ["access-vandenberg-maritime"]`.
  - `rules_review_status = "reviewed"`.
- The source is bound only to the area notice `vandenberg-conception` ("Vandenberg and Point Conception access", `source_ids: [mpa-vandenberg, mpa-point-conception, access-vandenberg-maritime]`). It is not in the `source_ids` of any of the seven species (checked: lingcod, rockfish, halibut, salmon, albacore, bluefin, dungeness). The tool gates reviewed footprint, all species and the horizon, and not each area notice, so the held notice does not fail `rules`.
- The R4-SC-10 prediction of an extra held-source failure after signing was therefore not borne out.
- This is not clearance of Vandenberg access, habitat quality or legal permission. The access notice still carries `review_required`, and the maritime source is still unavailable. Whether the held area notice should block promotion is a human decision, not something this tool tests.
- The region startup file (`/regions/point-arguello-conception/regulations-startup.json`, `raw/SC1114-02-pa-regulations-startup.json`) carries no Vandenberg source. The daily endpoint takes precedence at equal or newer review time.

## Raw files and limits

- `raw/SC1114-02-*` holds 24 stdout captures, `SC1114-02-runs.json`, the three supplementary GETs (`SC1114-02-pa-regulations-startup.json`, `SC1114-02-pa-api-daily-regulations.json`, `SC1114-02-api-health.json`) and their manifest `SC1114-02-supplementary-gets.json` (URL, UTC time, status, bytes).
- This is a point-in-time observation of the live site. It is not a browser test and not a phone test. No region status, registry, review record or `docs/roadmap.md` was edited.
