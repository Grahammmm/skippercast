# Fish archive (historical)

This folder keeps the documentation and research receipts of `fish`, the
owner's SLO Fish Report repository (SLOFishReport.com), before the owner
archives and deletes it ([front-end design § 15](../../plans/front-end/design.md#15-retiring-fish),
dev-plan FE-62, issue [#570](https://github.com/Grahammmm/skippercast/issues/570)).
Fish's features now live in SkipperCast: the map and coast renderer, the
profiles, the brief, Conditions, History, shore runs, the cloud loop and the
`fish`-only data sources (FE-40 … FE-45, FE-60, FE-84, FE-85, FE-87).

**Everything under [`repo/`](repo/README.md) is historical.** It describes
Fish as it was at commit `68d7b44` (2026-10-06): its services, data, numbers
and claims are not maintained and some no longer exist. SkipperCast's own
documentation is the live truth: [data sources](../../data-sources.md),
[the front-end plan](../../plans/front-end/README.md),
[the coastal service](../../coastal-service.md) and
[the Fish merge status](../../FISH-MERGE-STATUS.md). Do not cite an archived
file as current evidence of a source, a right or a result.

## What was copied

Copied on 2026-10-11 from a read-only clone of `fish` at `68d7b44`, keeping
Fish's own paths under `repo/`:

| Fish path | Here | Note |
| --- | --- | --- |
| `README.md`, `NOTICE.md` | [repo/README.md](repo/README.md), [repo/NOTICE.md](repo/NOTICE.md) | Fish's overview and attribution record |
| `docs/*.md` (19 files) | [repo/docs/](repo/docs/ARCHITECTURE.md) | The § 15 list ([architecture](repo/docs/ARCHITECTURE.md), [surface layer design](repo/docs/SURFACE-LAYER-DESIGN.md), [history pipeline](repo/docs/HISTORY-PIPELINE.md), [species opportunity](repo/docs/SPECIES-OPPORTUNITY.md), [bathymetry overlay](repo/docs/BATHYMETRY-OVERLAY.md), [independent review](repo/docs/INDEPENDENT-REVIEW.md), [quality review](repo/docs/QUALITY-REVIEW.md), [launch](repo/docs/LAUNCH.md)) and the other 11 docs, which are small |
| `docs/acceptance/*.json` | `repo/docs/acceptance/` | Dated source acceptance |
| `research/**/*.md` | [repo/research/](repo/research/source-registry.md) | [Source registry](repo/research/source-registry.md), [spatial review](repo/research/spatial-review.md), [reviewed catch binding](repo/research/reviewed-catch-binding.md), nearshore enrichment, fishing needs, domain and distribution, the coast audit |
| `research/**/*.json` | `repo/research/` | Source registry (`sources.json`), access probes, the dated validation, runtime, publication and acceptance receipts |
| `research/**/*.jpg` (14 of 15) | `repo/research/` | Only the screenshots a copied receipt cites; pinned by SHA-256 in `scripts/web-vendor-sha256.json` |

Each Markdown file starts with a one-paragraph historical note. Local links to
Fish files that were not archived (one, to a sibling checkout) are shown as
plain text.

## What was not copied

- Nothing under `fish/public/data` (784 MB): SkipperCast regenerates every
  feed with its own collectors.
- Fish's code and configuration: `src/`, `scripts/`, `tests/`, `config/`,
  `migrations/`, `wrangler*.jsonc`, `package*.json`, `tsconfig*.json`,
  `node_modules`, and `research/probe-sources.py`. Ported code already lives in
  `packages/coast/` and `src/skippercast/pipeline/`.
- `research/noaa-enc-morro-bay/{depth-areas,land-areas,quality,soundings}.json`
  (3.3 MB): extracted NOAA ENC geometry, which is data, not a receipt. Its
  collection, datum, source-candidate and publication receipts are kept.
- `research/production-launch-2026-10-03/worker-live-desktop.jpg`: no copied
  document cites it.
- `research/restart-handoff-2026-10-02.json`: an agent session hand-off holding
  local workstation paths and session identifiers, not a receipt.

## Redactions

`fish` is private and SkipperCast is public, so every copied file was scanned
for secrets, tokens, account ids, emails, phone numbers, private hostnames and
paths, and third-party-restricted data before commit. Two values were redacted:

- the `fish` D1 database id in
  `repo/research/production-launch-2026-10-03/launch.json`;
- a commit co-author email in `repo/research/habitat-rights-change-2026-10-02.json`.

No credentials, phone numbers, private hostnames or Cloudflare account id
were found. The `*.workers.dev` preview origins and Cloudflare Worker version
ids that remain are already public (`server/coast-data.ts`) or grant no
access. Catch facts in the receipts are the linked factual counts already
published on SkipperCast's `data` branch; no articles, photos or raw pages.
The screenshots show the public app only.

## § 15 checklist

Status as of 2026-10-11. The owner confirms this list before archiving the
repository.

1. **Landing and app, layers, Terrain, `/coast`.** Live check 2026-10-11 on
   desktop and phone passed except the Chart basemap, which waits on its first
   publish ([#474](https://github.com/Grahammmm/skippercast/issues/474)):
   FE-60 ([#540](https://github.com/Grahammmm/skippercast/pull/540), fixes
   [#556](https://github.com/Grahammmm/skippercast/pull/556),
   [#557](https://github.com/Grahammmm/skippercast/pull/557)); `/coast` and
   Fish links open the app (FE-78,
   [#424](https://github.com/Grahammmm/skippercast/pull/424)). Since FE-61
   part 1 ([#561](https://github.com/Grahammmm/skippercast/pull/561)) the v2
   app is the only shell.
2. **Boat, Shore and Spear.** Profiles across the app (FE-30); covered by the
   FE-60 live check of 2026-10-11 (item 1).
3. **Brief.** Tiles, tide curve, lower-exposure window and fleet line (FE-31,
   FE-33, FE-37); covered by the FE-60 live check of 2026-10-11.
4. **Conditions and History.** FE-32 and FE-35; History reads 46028 and 46215
   from the SkipperCast history feed (FE-42,
   [#423](https://github.com/Grahammmm/skippercast/pull/423)); covered by the
   FE-60 live check of 2026-10-11.
5. **Shore runs and beach notices.** FE-36; shore habitat (FE-43,
   [#463](https://github.com/Grahammmm/skippercast/pull/463)) and beach water
   quality (FE-41, [#460](https://github.com/Grahammmm/skippercast/pull/460));
   review dates are described in [data sources](../../data-sources.md#shore-runs-and-beach-approaches).
   Covered by the FE-60 live check of 2026-10-11.
6. **Cloud loop.** FE-22 ([#484](https://github.com/Grahammmm/skippercast/pull/484))
   and the cloud collector (FE-44, [#471](https://github.com/Grahammmm/skippercast/pull/471));
   covered by the FE-60 live check of 2026-10-11.
7. **Every § 11 source catalogued, registered and collected.** Collectors and
   catalog entries: FE-40 ([#466](https://github.com/Grahammmm/skippercast/pull/466)),
   FE-41, FE-42, FE-43, FE-44 (above) and FE-45
   ([#465](https://github.com/Grahammmm/skippercast/pull/465)), listed in
   [design § 11](../../plans/front-end/design.md#11-data-ingest-for-the-fish-only-sources).
   2026-10-11: register rows are **Owner** and some await confirmation (for
   example `noaa-esi-2006` and `ccc-access-points`); collector-run evidence is
   recorded in the [Fish merge status](../../FISH-MERGE-STATUS.md) acceptance
   matrix by FE-62b.
8. **Assets, bridge, refresh runs, merge status.** Terrain, imagery and
   habitat assets in SkipperCast storage with their SHA manifest (FE-85,
   [#462](https://github.com/Grahammmm/skippercast/pull/462)); bridge reads
   SkipperCast feeds for nearshore, beach, ocean and history (FE-84,
   [#478](https://github.com/Grahammmm/skippercast/pull/478)) and the rest of
   the report (FE-87, [#481](https://github.com/Grahammmm/skippercast/pull/481)).
   2026-10-11: `server/coast-data.ts` still falls back to the Fish Worker when
   SkipperCast's feed lacks `nearshore` or `water-quality`; FE-62b
   (`claude/fe-62-bridge`) removes the fallback and completes the
   [Fish merge status](../../FISH-MERGE-STATUS.md) matrix with dated evidence.
9. **This archive.** Copied 2026-10-11 by FE-62a (this folder).
10. **Cloudflare resources.** Listed below.

## Cloudflare resources to delete (owner)

Names from Fish's `wrangler*.jsonc` at `68d7b44`; ids and secrets are not
recorded here. Delete them after the repository is archived and FE-62b has
merged, because until then SkipperCast's bridge can still call the Worker.

| Kind | Name | Fish config | Note |
| --- | --- | --- | --- |
| Worker | `fish-report` | `wrangler.jsonc` | The deployed site; its `*.workers.dev` preview is the Fish Worker origin in `server/coast-data.ts`. Hourly cron trigger (`17 * * * *`), static assets binding, observability on. |
| Custom domains | `slofishreport.com`, `www.slofishreport.com` | `wrangler.jsonc` | Routes of `fish-report`; the redirect decision is open-questions Q10. |
| D1 database | `fish` | `wrangler.jsonc`, `wrangler.data-remote.jsonc` | Binding `DB`; migrations `0001_initial.sql`, `0002_auxiliary.sql`. |
| R2 bucket | `fish-habitat` | `wrangler.jsonc`, `wrangler.habitat-*.jsonc` | Binding `HABITAT`; private, no public access. |
| Worker configs | `fish-data-bootstrap`, `fish-habitat-publisher`, `fish-habitat-local` | `wrangler.data-remote.jsonc`, `wrangler.habitat-remote.jsonc`, `wrangler.habitat-local.jsonc` | Used for remote D1 and R2 commands; delete any that exist as deployed Workers. |

Worker secrets on `fish-report`, if any, go with the Worker. No KV
namespaces, queues or Durable Objects are configured.

## Owner steps, in order

1. Confirm the checklist above.
2. Archive `Grahammmm/fish` on GitHub.
3. Delete the Cloudflare resources listed above.
4. Delete the repository.
5. Decide the `slofishreport.com` redirect (open-questions Q10).
