> **Historical archive (copied 2026-10-11, SkipperCast FE-62).** This is `docs/SKIPPERCAST-UPDATES.md` from the retired Fish (SLO Fish Report) repository at commit `68d7b44` (2026-10-06). It records how Fish worked and what was checked at the time, is not maintained, and may describe services, data and claims that no longer exist. SkipperCast's own documentation is the live truth: start at the [archive index](../../README.md) and [front-end design § 15](../../../../plans/front-end/design.md#15-retiring-fish). Links to Fish code, configuration or data that were not archived are shown as plain text, and identifiers that could not be published were redacted.

# Parallel SkipperCast data upgrades

Fish consumes SkipperCast through reviewed data contracts, rather than copying its application code on every update. Compatible data can improve independently of Fish's website deployment. A new variable, county, producer permission, species meaning or schema needs its own adapter review.

## What updates and how

| Data | Update path | Existing restrictions |
| --- | --- | --- |
| NOAA WCOFS / HF radar | Existing hourly Fish Worker reads the SkipperCast `conditions` branch | Native fields, units, coordinates, masks and independent issue/sample/receipt clocks; only the three reviewed NOAA products |
| Local charter counts | Same report collector reads the SkipperCast `data` branch | Reviewed linked factual categories, original trip dates and original publisher-check clocks; selected categories are not complete trip totals |
| Government habitat / terrain | Completed reviewed government build → Fish sync publisher → private R2 immutable set → one conditional control switch | All regional run/output/catalog hashes, actual implementation identity, whole geometry, physical/calibration/substrate rights, screens and consumer semantics |
| Habitat species profiles | Travels with the same habitat release | The reviewed semantic hash in `config/skippercast.json`; changed planning depths, proxy species, citations, meanings, limitations or rule version require a Fish adapter and explanatory-copy review |
| Other SkipperCast additions | Review and add an explicit adapter/binding | AIS inference, new model families, measured visibility and restricted sources are not automatically promoted |

The existing hourly Worker needs provisioned Fish D1 storage and witnessed cloud runs to operate unattended. The deleted chat automation stays deleted. No second polling schedule or GitHub Cron is introduced.

## One command for the local preview

To refresh compatible current/catch feeds through the existing collectors and rebuild the local snapshot assets:

```sh
npm run sync:skippercast
```

It preserves prior useful data and original source clocks when a provider fails. It does not backfill annual buoy history, renew manual regulations/access review, download restricted mixed archives, or invent new observation dates. Each dataset outcome is retained in ignored `artifacts/skippercast-sync/` receipts.

To publish completed, reviewed government habitat from the owned engine:

```sh
npm run sync:skippercast -- \
  --engine artifacts/government-engine \
  --expected-producer 0978207dd12cc4f0591302f7458f8db75fdfc782 \
  --habitat-only
```

That SHA is the current reviewed implementation, not a forever-current upstream version. For a new producer revision, first obtain normal SkipperCast review/CI, update only the owned isolated engine, finish processing every reach in every region in the reviewed bound set under `government-only`/`for-profit`, and renew spatial screens through their real reviewed process. Pass its exact reviewed SHA to the command. This importer does not execute or fetch arbitrary upstream code. Every retained run's implementation, reference, scoring, habitat rules and screen hashes must match that checkout; changing `HEAD` alone cannot rebrand old outputs as newly computed.

The publisher verifies all stored bytes. Unchanged complete data is skipped; missing/corrupt unchanged data is re-staged from the revalidated science. Older regional builds are rejected. A held selected control requires resolution by the operator and is not silently reopened. A filesystem lock protects one local command; conditional R2 pointer writes prevent concurrent publishers from overwriting each other.

## Producer release hook and cloud activation

The government build's successful release step should call the same command **after** producer tests/review and full regional publication. Use an isolated, pinned Fish checkout, the owned completed engine and its reviewed commit. This is the integration hook; Fish does not mutate SkipperCast's mixed publication namespace or other worktrees.

Once the dedicated private cloud `fish-habitat` bucket exists and authorized Wrangler account access is configured, the hook uses:

```sh
npm run sync:skippercast -- \
  --engine /path/to/owned-completed-government-engine \
  --expected-producer <reviewed-40-character-commit> \
  --habitat-only --stage-remote
```

`wrangler.habitat-remote.jsonc` marks only that R2 binding remote, using the installed supported Wrangler `getPlatformProxy` API. Local promotion is the default; an explicit remote flag is required. Keep the bucket private. The publisher uses SHA metadata, full read-back and the same atomic conditional selection as local staging. No cloud upload, authenticated remote acceptance, or automatic producer hook execution is claimed by the local verification. Configure this hook in the producer's existing release job when cloud operation is activated; no separate Fish schedule is necessary.

The Fish Worker needs one code deployment containing the live consumer adapter. After that, compatible habitat upgrades require only the private data promotion, **not another website build/deploy**. Report/ocean updates use the existing deployed collector rather than the local file command.

## Release and browser contract

Each live control adds `consumerContract:fish-habitat-v1`, `scientificReleaseId`, the reviewed `speciesProfileSha256`, and `consumerAssets` descriptors for `consumer.json`, `details.geojson`, and `species.json`. Every descriptor binds exact immutable path, bytes and SHA-256. All three live under the release's private prefix alongside every reviewed regional PMTiles archive, original canonical exports and review receipts. They are staged and read back before `current.json` is conditionally switched. Previous immutable releases remain available privately for an explicit reviewed rollback; expired or withdrawn data never becomes an automatic fallback.

`/data/skippercast-manifest.json`, both curated data paths and `/api/habitat/tiles` resolve the selected private set. The runtime checks the complete reviewed regional inventory (legacy SLO pair or complete four-region corridor set), consumer metadata, rights, contract and expiry. The served consumer manifest is bound to the exact selected control digest. Every served detail/species body is hash checked, and the pointer is rechecked after transfer. Private canonical/review objects remain unexposed. The original bundled v1 release remains supported until initial migration; a failed live contract cannot fall back to it.

The browser carries the release ID into detail and tile requests and verifies the detail digest before installation. Old URLs fail with 412 after a switch, including a change with the same archive bytes. Its existing minute availability checks withdraw the old layer and recover the new complete set on a later bounded retry; approximately one to four minutes across withdrawal and recovery in an active page, not a guaranteed background-tab latency. Species/day/method selections stay in application state. A release changing between manifest and details is rejected, rather than displayed as a mixed map.

## Verification

Offline checks cover normal upgrade, same-science repair, incompatible species meaning, old data, failed read-back, concurrent promotion, held/expired controls, missing regions, consumer corruption, old URLs and a mid-request upgrade. Actual local R2/Worker transport and rendered browser evidence are recorded separately. Verification does not establish extra surveyed coverage, new fish observations, numerical catch probability, cloud deployment or source freshness beyond the original recorded clocks.

References: [Cloudflare R2 Worker binding API](https://developers.cloudflare.com/r2/api/workers/workers-api-reference/), [Wrangler programmatic API](https://developers.cloudflare.com/workers/wrangler/api/#getplatformproxy), [SkipperCast data contracts](https://github.com/Grahammmm/skippercast/blob/main/docs/data-contracts.md).


## Monterey–Point Conception map release · 2026-10-06

The reviewed inventory in `config/habitat-regions.json` extends government habitat to `monterey-point-sur` and `point-arguello-conception`. A complete legacy SLO pair remains supported for rollback. The expanded publication must contain all four reviewed regions; missing, duplicate, partial or unknown inventories fail closed. Every regional archive is checked before any region or consumer asset is served.

The current owned build is `artifacts/corridor-engine`, pinned to the same reviewed scientific implementation `0978207dd12cc4f0591302f7458f8db75fdfc782`. Every added reach has its own verified inputs, rights, output hashes and original spatial-screen clock. Compatible future producer updates still go through the existing sync command; an unreviewed new geographic namespace or species meaning is not automatically admitted.

Full display outlines are rebuilt with `node scripts/build-coast-habitat.mjs artifacts/corridor-engine` followed by the existing display compiler. Regional terrain rebuilding additionally runs `collect-corridor-land.py`, `collect-corridor-relief.py`, `extend-corridor-terrain.py` and `verify-corridor-terrain.py` with the existing GIS runtime. Model and land context are separate from the original habitat-processing inputs.
