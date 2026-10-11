> **Historical archive (copied 2026-10-11, SkipperCast FE-62).** This is `research/reviewed-catch-binding.md` from the retired Fish (SLO Fish Report) repository at commit `68d7b44` (2026-10-06). It records how Fish worked and what was checked at the time, is not maintained, and may describe services, data and claims that no longer exist. SkipperCast's own documentation is the live truth: start at the [archive index](../../README.md) and [front-end design § 15](../../../../plans/front-end/design.md#15-retiring-fish). Links to Fish code, configuration or data that were not archived are shown as plain text, and identifiers that could not be published were redacted.

# Reviewed linked catch facts

Reviewed October 2, 2026 using the `skippercast-discover-data` skill and existing read-only SkipperCast source review, parser and normalized feeds. No new publisher crawl, report prose, photographs, private logs, operator contact or accounts were used.

## Reviewed scope and original producer

SkipperCast's [`landing-reports` catalog entry at a fixed commit](https://github.com/Grahammmm/skippercast/blob/a481da68923649db6fda277af4bd6f40813f6436/catalog/sources.json) is `approved`, reviewed September 21, with `facts-only` rights and operator/SoCalFishReports attribution. Its explicit scope allows concise factual counts with source links and excludes articles/images. This is an existing reviewed publication scope for selected linked facts, not a provider-issued bulk database license or authorization to reproduce the underlying website. Broader licensed operator ingestion remains a separate future pipeline.

[SkipperCast's Morro Bay normalized feed](https://raw.githubusercontent.com/Grahammmm/skippercast/data/regions/morro-bay/latest.json) distributes operator-reported facts originally published by [SoCalFishReports](https://www.socalfishreports.com/). It is one underlying reported source, not independent confirmation. The normalized `reported` disposition does not establish retained catch. Fish keeps the original category labels instead of silently combining generic rockfish, copper/red rockfish and bocaccio into a specific species or inferred catch rate.

## Actual access and clocks

The initial bounded public feed request returned HTTP200 and 1,388,319 bytes. Its schema was version1, region `morro-bay`, generated October1 at 00:37:50Z, with a thirty-day August31–September29 window and 74 trip records. The latest actual trip was September28; a successful September29 source day had no reported local rows. Neither absence establishes no fishing or zero catch.

The actual new adapter collection at **2026-10-02T04:20:31.423Z** retained **19** independently matched dated reports, excluded **52** stale/failed/conflicting/invalid source records, and ignored three records outside the most recent thirty actual local days. Latest trip date remained **2026-09-28**. `landing-reports` outcome was explicitly `error` for the omitted subset while the valid facts remained available. Whole-feed/source-day age must be no more than72hours; old archived checks are not refreshed by downloading the containing feed.

Example: September28 Avenger, Morro Bay, three-quarter-day trip,17anglers; reported categories copper rockfish2, lingcod8, rockfish138, red rockfish13. [Original dated source](https://www.socalfishreports.com/dock_totals/boats.php?date=2026-09-28). Original source-day retrieval: **2026-10-01T00:37:50Z**. Fish retrieval: **2026-10-02T04:20:31.423Z**. No trip time, catch position, depth, fishing duration or retention status was invented.

The separate [recent-intelligence candidate feed](https://raw.githubusercontent.com/Grahammmm/skippercast/data/recent-intel.json) returned HTTP200 but only unreviewed Southern California candidates with catch/date/geometry null. It contributes no reviewed SLO catch facts.

## Adapter contract and gates

`src/providers/catches.ts` exports:

```ts
collectCatches(county, now = new Date(), fetcher = fetch)
// -> {catches: CatchReport[], source: SourceStatus,
//     catchStatus: string, context: CatchContext | null}
```

Only the exact existing SLO/Morro Bay feed is bound. Other counties fail before network access. The request has manual redirects, a12-second abort and3MiB declared-length/stream cap. It requires schema/region, valid UTC calendar clocks, no more than five minutes of future clock tolerance, a real window of at most thirty dates, and records within the last thirty actual America/Los_Angeles calendar dates. It does not use a selected future forecast hour as its freshness clock.

Each accepted top-level record must match exactly one normalized record in its own original day receipt. That receipt must have successful `charter-reports` status, matching day and exact HTTPS publisher URL, and a valid/fresh original `checked_at` no later than the feed clock plus five minutes. Invalid/missing counters, blank/unsafe/oversized labels, unknown port, missing count categories, changed original records and malformed/future dates are excluded. Unknown anglers remain explicit null; a zero category counter remains literal without establishing all-trip zero catch. Exact duplicate trips are deduplicated; conflicting independently valid records sharing an ID are both withdrawn. Failed ocean sources do not invalidate successful catch-day facts.

Mapping: `date`→tripDate, `port`→landing, `trip_type`→tripType, each original catch `label/count/disposition`→species, source day `checked_at`→retrievedAt. Only released disposition also sets the legacy released boolean. Missing grounds remain absent. No coordinates are imported or generated. Context preserves the original feed window/generation clock, new receipt clock and fixed reviewed rights URL. SourceStatus has kind report, Fish fetchedAt, and no fabricated issuedAt.

## Display and verification

Display these as **linked dated boat-trip reports**, with the actual latest trip date and source link. Do not describe them as today's catches, verified retained totals, fleet-wide catch rates, shore/dive catches, precise spots or a bite prediction. Landing port and broad named ground are separate from where an individual fish was caught. A partial source error or older edition must remain visible; stale whole-feed access returns no imported facts.

Eleven focused offline tests pass: original clocks and category/release semantics, county/schema isolation, stale/future/bad calendar dates, missing/invalid counters and labels, original-day matching, failed/stale day receipts, independent partial availability, duplicate/conflicting IDs, empty-feed semantics, thirty-day cutoff, manual redirects, HTTP/malformed JSON failures and bounded bodies. TypeScript checks pass. The live collection above exercised the actual approved feed without changing the public snapshot.
