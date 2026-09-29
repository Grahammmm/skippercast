# 0003. R2 is the feed system of record; git feed branches are single-commit mirrors

- **Status:** Accepted
- **Date:** 2026-09-29 (records decisions merged in PRs #9, #11, #30 and #57)

## Context

- Scheduled jobs publish three feeds: `conditions` (every 30 minutes), `data` (daily) and `forecasts` (per model cycle). They began as git branches read from `raw.githubusercontent.com`, with CDN caching, rate limits and a new commit every cycle.
- PR #9 put every feed behind one site route, `/feeds/<branch>/<path>`, served from Cloudflare R2 first and the GitHub branch second, mirroring each branch to R2 after its push.
- The copies could silently diverge: R2 upload failures were warnings and the freshness monitor read GitHub while the Worker served R2 (guide P0-04).
- Nothing reads branch history; the history the pipeline needs is stored as files inside the snapshot.

## Decision

- **R2 is the system of record** for published feeds. The browser reads every feed through `/feeds/*`, which serves R2 first, and the Worker reads R2 first for its own APIs.
- **R2 publication is verified, not best-effort.** With credentials configured, an upload error fails the job; `verify_published_feed.py` confirms the public route serves this run's `run_id`, and the freshness monitor checks the public route first. PR #30.
- **Forecast tiles sync to R2 on every run**, hash-indexed, so a new bucket is never left empty. PR #11.
- **Git feed branches are single-commit mirrors.** Each publish is one parentless commit force-pushed with a lease, so a concurrent publisher is refused, not overwritten. R2 lifecycle rules expire run manifests after 7 days. PR #57.
- The GitHub branch stays as a fallback when R2 is unbound (local and development deployments) and as a public, inspectable copy.

## Consequences

- (+) Users and monitoring see the same object.
- (+) Branches stay small; a bad generation is replaced by the next good run.
- (–) No git history of feeds.
- (–) Publishing depends on Cloudflare credentials in CI; a revoked token now fails loudly instead of degrading quietly.

## Alternatives

- **Git branches as the store:** free and transparent, but CDN caching, rate limits and unbounded history.
- **R2 only, no branches:** simplest, but loses the fallback and the public copy that data users read today.

## Links

- [Cloudflare](../../cloudflare.md), [production operations](../../production-operations.md), runbooks [feed-stale](../../operations/runbooks/feed-stale.md) and [r2-outage](../../operations/runbooks/r2-outage.md).
- PRs #9, #11, #30, #57; guide P0-04, P2-05, findings A6 and A11.
