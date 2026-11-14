# Check a region before promotion

From an up-to-date checkout with locked JavaScript dependencies installed and
Node 22.18 or newer, run:

```sh
node scripts/check_region_promotion.mjs morro-bay san-diego
```

Leave off the region names to check **every local `regions/*/region.json`**,
including drafts. Multiple names are checked in one command, once each, sorted
by ID. `--base https://skippercast.com` is the default; another origin can be
used for a preview/test site. `--json` emits the same per-region checks plus the
observation time and site origin as JSON.

- **Exit 0:** every requested region passes the technical checks below.
- **Exit 1:** at least one region fails. Its failed checks explain why. A draft
  or unpublished region fails before its unavailable feeds are fetched.
- **Exit 2:** invalid invocation or a local tool failure; not readiness.

**PASS is a technical preflight, not permission to promote.** The command never
changes a region status, approves rules, clears a held package, opens an issue,
publishes data, or starts a beta. Preserve the roadmap's current promotion hold,
G's substantive legal/product decisions, independent review, and the final beta
GO gate. This does not implement or replace the scheduled rules-card alarm.

## What is checked

| Check | PASS requires |
| --- | --- |
| Package | A local preview/active package, exactly one live index entry, matching ID/status/config path, a live species list and jurisdiction/timezone, and region-specific feed bindings. A stale checkout/status mismatch fails; update the checkout, do not edit status to make a check green. |
| Feeds | Public regional conditions, daily and intelligence JSON with the right schema/region, nonempty sources, and aware clocks no more than 3 h / 36 h / 3 h old (catalog limits; no feed-declared override). A clock more than 10 minutes ahead fails. Conditions need observations; daily needs observations, predictions, advisories and forecasts; intelligence needs forecasts. Critical kinds use the catalog's whole-kind degradation limits (12 h live / 48 h daily). One healthy source can bridge another source's outage. Missing required kinds fail. |
| Tides | A configured seven-digit station matching the daily tide source; source status `ok`, retrieval within 36 h, coverage spanning now, a future numeric high/low, and the app's `MLLW` / `ft` / `UTC` contract. Reference tides do not establish safe entrance currents. |
| Rules | The app's own `loadRegs` and `regulationState`, including startup/fallback/daily precedence. The registry must match the jurisdiction, reviewed region footprint and timezone. **Every** species must have a season state; `reef` expands to **both** lingcod and rockfish. Only the app's specific location-needed prompt is allowed as an unknown. Missing review, changed sources, stale checks and expired rules fail, even when another species is known. |
| Habitat | The app's current seafloor manifest gate: ready/unexpired for this region. Under approved SC-D1=B, a 404 (no publication) or an explicit matching held manifest passes **as a named GAP**, not as habitat coverage or clearance. Updating, expired, malformed, wrong-region, unreadable or otherwise unavailable manifests fail. No archive is downloaded or independently verified. |
| Smoke | Healthy site with a clean commit revision, HTTP map HTML containing a module script, and a current correctly identified regional brief API response. **This is an HTTP/data smoke check, not a rendered-phone/browser test.** |

Checks run independently after package validation, so a rules failure still
prints the tides, habitat and smoke results. Network/HTTP/JSON failures are
failures, not skipped successes. Fetches are anonymous same-origin GETs with
15-second timeouts, no redirects or retries, at most 16 MiB per response, and one
fetch of each path per invocation. Output contains status codes/identifiers and
check reasons, not feed bodies. No source records, surveys or archives are
acquired. The tool writes no files.

## Future rules dates and human evidence

By default this answers readiness **now**, not an intended future launch date.
To require validity through an explicitly chosen date as well:

```sh
node scripts/check_region_promotion.mjs --rules-through 2027-01-31 morro-bay
```

The horizon is caller-supplied; the tool does not approve a GO date or adopt the
SCB-03 audit's proposed numerical launch policy. Before promotion, independently
check the rules card in each region at the deployed head, the actual phone
journey and honest gap wording, and cite required human approvals in the beta
gate record. An HTTP shell or a hidden habitat layer does not prove that UI.

## Proof and rollback

```sh
node --test tests/test_region_promotion.mjs tests/test_rules_status_probe.mjs
```

The positive Morro Bay and preview cases are **synthetic fixture sites only**,
using a frozen test registry with synthetic fresh checks. They are not legal
reviews or evidence that live Morro Bay can be promoted. Negative cases cover
drafts, partial rules availability, both reef members, clock limits, broken
feeds/tides/manifests, wrong identities, failed smoke checks and CLI exit codes.
All tests are offline.

At implementation validation on 2026-11-13, live Morro Bay correctly returned
FAIL because every species had `rules.reason.sourceChanged`; feeds, tides,
habitat and HTTP smoke passed. Draft `san-diego` returned FAIL `region-draft`.
Those are snapshots, not a promise about later live state. Do not weaken rules
checks or substitute the synthetic PASS to meet the proposal's old "Morro Bay
passes" wording.

Rollback is to stop using the tool, or revert its PR. There is no running job,
service change, configuration migration, or live state to roll back.
