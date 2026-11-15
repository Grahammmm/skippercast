# Subsystem retirement — 19-01 frozen source inventory

**CANDIDATE ONLY · UNINSTALLED · applied=false · REVIEW REQUIRED.**
This is planning metadata, not an extraction, privacy implementation or retirement.
Machine-valid output does not supply semantic acceptance, human/legal conclusions,
custody approval, live release authority or lost history. No later card is created.
The retire/delete HOLD and signing HOLD remain in force.

## Authority and immutable source

G's 2026-11-14 06:50 choices in [audit item 19](https://github.com/Grahammmm/skippercast/issues/2184)
are settled: SHELVE advisor/social, MOVE fleet privately, EXTRACT campaign/research.
The admitted unit is **19-01 only**, from the operator's
`reports/sc-audit-19/PLAN.md` (lines 56–61; not tracked in this repository),
under inventory SCA-22 / AUDINV-SCA-22. Admission does not release retained holds.

Inspected main: **`351e321dd8c7b3ef82b149d2bb9476fbe337e180`**.
The [manifest](subsystem-retirement.manifest.json) freezes that immutable commit,
not a moving branch. Advisor history is this commit plus its `advisor-history`
prefix cover; recover it from Git only after explicit reauthorization. No duplicate
archive, second advisor repository or running advisor service is proposed here.
The source commit is a candidate archive identity, not evidence of legal acceptance.

## Ownership contract

Every one of the **5,529 tracked paths** at `source_commit` has exactly one owner.
A trailing `/` means directory prefix; otherwise the entry is an exact file.
Prefixes are disjoint: no priority rules, globs or implicit overrides. Per-file
ownership follows its prefix. Ownership is a receiving responsibility, **not a
permission to remove**. Mixed files stay with their current product/maintenance
owner until their held seams are resolved; no directory-name mass deletion.

| Owner | Paths | Receiving responsibility |
| --- | ---: | --- |
| retain-product | 3,669 | Accounts, trips, push, feeds, map, platform, published outputs, shared schema/build/CI and boundary guards stay in SkipperCast. |
| advisor-history | 320 | Immutable source history; advisor engine, channels, social publishing and detached UI/tooling are shelved only after privacy and public-page separation. |
| privacy-maintenance | 9 | SkipperCast retains contact export/forget, retention, related tests and relay cleanup responsibility. The independent non-messaging module is NOT implemented yet. |
| private-fleet | 311 | Proposed private `Grahammmm/skippercast-fleet`; source/synthetic-fixture candidate only, not provisioned or activated. |
| private-coastal-research | 1,220 | Proposed private `Grahammmm/skippercast-coastal-research`; campaign tooling, dated research, receipts and selected tests/skills, not provisioned or installed. |

`server/advisor/pages/`, mixed gates, page copy and required catalogs stay product
owned. `web/admin` is classified file by file: fleet views go to private fleet,
advisor-only views to history, mixed app/API/route/key shells stay product owned.
Shared neutral IDs, aliases and schemas stay product contracts until separate
behavior-preserving seams exist. `scripts/coast/`, `pipeline.coastal_watch`,
`seafloor`, platform, `packages/coast/`, `web/map/`, collectors, region inputs and
reviewed `dist/` outputs are NOT extracted by a coastal substring match.
Generic test infrastructure and boundary guards remain product owned. Private
candidate tests follow their implementation; classification is not source-closure
qualification. Shared fixtures, catalogs, skills and docs retained by product
must be rechecked for required destination closure before any future transfer.

## Cross-boundary edges and explicit resolutions

The manifest contains source/target pairs for **814 resolved literal-import
references**, grouped into 13 owner-direction edges with a resolution for each,
plus eight non-import seams below. All are HOLD for later implementation.
Enumeration scans tracked Python and JS/TS source only: resolvable relative JS/TS
imports and absolute Python `skippercast.*` / `research.*` imports. It is not a
whole-program proof: dynamic imports, Python relative imports, SQL, bindings,
workflow strings, output paths and licensing require the explicit seam inventory.
Any newly discovered/unmatched edge holds its dependent future change, not this
metadata unit; none is silently treated as detached or safe to delete.

| Seam / evidence | Resolution before any dependent removal |
| --- | --- |
| Fleet IDs/activity/admin import advisor hash, validation and outcome types; pairing reads advisor aliases | Product owns neutral reviewed contracts; private fleet may vendor only minimal licensed utilities/catalog or consume a pinned product API. Never vendor the advisor engine. |
| Advisor boat/data/sitemap rendering imports fleet display/settings/go and reads legacy tables | Separate product port/species rendering and sitemap from fleet boat behavior; no product-to-private runtime import or cross-repository database join. |
| `db/schema.ts`, `advisor_boats.fleet_vessel_id`, fleet linking and mixed queries | Keep schema/migrations; detach legacy identifiers or disable an explicit adapter. Never replicate contacts/transcripts to make fleet run. |
| `server/app.ts`, `server/index.ts`, `server/routes/{admin,public,account}.ts` | Coordinated mount/session/heat split; preserve auth, account/trips, trip queue and watchdog. Unknown advisor queues must not fall through to trip handling. |
| Privacy contacts/exports/retention import advisor IDs/log/media dependencies | Keep minimal closure until separately proven authorized, flag-off, non-messaging maintenance exists. No sender, relay, model or social dependency in the eventual maintenance path. |
| Bucket/cron/queue bindings and host runners | Keep retention invocation and necessary bucket while data remains. Custodians reconcile writers, backlogs and holds before optional bindings/schedules change; no runtime action here. |
| `pyproject.toml`, Worker builders, deploy entrypoints, CI selectors and boundary tests | Collision hotspots stay product-owned; reconcile extras, package namespaces, resources, mounts and selectors in one admitted seam at a time. No competing overlapping `skippercast` distributions. |
| Fleet `coverage.py` can write product regional coverage | Replace private checkout writes with reviewed counts-only proposed artifacts; preserve missing/partial semantics. No automatic ready status or shared live store. |
| Campaign/research imports product and packages schema symlinks | One-way pinned product wheel in an isolated environment; prove actual imported paths and resource closure. Product never imports private packages or reads their stores. |
| Research receipts, provenance pointers, generated output and rights | Preserve bytes and historical `dist/data/` strings through `research.lib.receipts.locate`. Product keeps required provenance and outputs. Preserve LICENSE, third-party notices, source-specific rights, datum/restrictions and review holds; no new license or publication grant. |

Independently enabled **port and species pages** are retained:
`server/advisor/gate.ts:pagesGate` accepts `PUBLIC_PAGES_ENABLED` independently of
advisor. `boatsGate` instead accepts advisor OR fleet; disabling advisor alone
proves neither boat-page inactivity nor fleet absence. Public port/species routes,
copy, catalogs, canonical/noindex and sitemap contracts need a product-only seam,
not wholesale removal of `server/routes/advisor.ts` or `web/advisor/`.
Actual public exposure is UNKNOWN, not inferred from source defaults.

## Retained data and migration policy

All **37 migration files** (18 top-level SQL and 19 metadata/journal files) are
SHA-256 pinned individually in the manifest. Never edit, delete, squash, renumber
or rewrite them; preserve dormant schema declarations. Future schema work is
forward-only and separately reviewed. Destination bootstrap schemas must record
origin and never replace the product migration chain.

Product account deletion is not advisor-contact deletion. Existing `forgetContact`
does R2 work before a D1 batch, detaches reports/boats, and retains posted/partial/
publishing social records; missing bucket does not prove objects were erased.
Keep independent privacy responsibility until its separately admitted seam proves
authorization, missing-bucket refusal, bounded/restartable work, shared-media
protection and export expiry. No confirmation send is part of retirement.
Source retention periods are not runtime receipts: bodies 180 days, media/reviews/
web-only contacts 90, daily/job state 30, stats 730, exports 7, with published/
shared-object exceptions and bounded batches. Custodians must reconcile actual
retention, backups, legal holds and pending work. Darkness never means empty;
retention policy is not a blanket indefinite-retention or purge authorization.
No export, purge, credential duplication, store inspection or live verification
has occurred. Restoring erased data from backups is not a rollback strategy.

## Counts-only runtime facts — all UNKNOWN / HOLD

No sanitized custodian receipts were supplied to this unit. Each table row below
expands to a named manifest fact with its custodian; UNKNOWN is not zero, false,
stopped, empty or compliant. Enabled switches are counts (0/1 when attested), not
configuration strings. No job/service names, record IDs or private values are
collected. Flag claims such as historical `FLEET_ENABLED=true` are NOT runtime
facts established by this tracked-source inventory.

| Fact family (manifest prefix) | Enabled switches | Running jobs | Queue backlog | Stored rows | Stored objects | Retention obligations | Legal holds | Existing custodian |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| advisor | UNKNOWN/HOLD | UNKNOWN/HOLD | UNKNOWN/HOLD | UNKNOWN/HOLD | UNKNOWN/HOLD | UNKNOWN/HOLD | UNKNOWN/HOLD | Advisor service and data custodian |
| fleet | UNKNOWN/HOLD | UNKNOWN/HOLD | UNKNOWN/HOLD | UNKNOWN/HOLD | UNKNOWN/HOLD | UNKNOWN/HOLD | UNKNOWN/HOLD | Fleet service and data custodian |
| coastal_research | UNKNOWN/HOLD | UNKNOWN/HOLD | UNKNOWN/HOLD | UNKNOWN/HOLD | UNKNOWN/HOLD | UNKNOWN/HOLD | UNKNOWN/HOLD | Coastal campaign coordinator and research custodian |
| public_pages | UNKNOWN/HOLD | — | — | — | — | — | — | Product deployment custodian |

Existing custodians retain host jobs, relay, AIS/native runners, caches, ledgers,
canonical stores and sole scheduling/verification ownership. Missing facts hold
only dependent operations; this document supplies no quiescence or cutover proof.

## Existing audit work and frozen product baseline

- Item 9 is already implemented in `19c2e8ee7`: map-style modules live under
  `web/map/preview/`, and the research boundary covers `web/` and `packages/`.
- Item 16 is already implemented in `c736b5f36` (with `83cda6e9f` reference fix):
  32 research-only outputs moved to `research/receipts/`; preserve locator/hashes.
- Item 15 is unchecked on issue #2184 but **already implemented in tracked main**
  by `893ca9e4c`: substrate/fish-survey have manual dispatch, no cron.
  Research-daily still has its `workflow_run` relationship. Do not redo/revert it.
- The manifest records **858 tracked `dist/` outputs/entry sources** at the source
  commit and SHA-256 of the exact UTF-8 `git ls-tree -r <source_commit> -- dist/`
  output (including final newline). Its blob IDs pin bytes, paths and modes.
  The separate sorted tracked-path-list digest uses one path per line plus final
  newline. These are frozen source baselines, NOT a newly executed product build
  or live-output certification. No generated artifact was rewritten here.

Rollback is reverting these documentation/manifest/test additions only. Stop
here after 19-01: no 19-02..19-15 cards, extraction, deletion, destination creation,
runtime/flag/store change, installation, source acquisition or outbound activity.
Future admitted work must revalidate current source and unresolved seams, retain
all data/publication/privacy gates, and obtain its own authority and acceptance.
