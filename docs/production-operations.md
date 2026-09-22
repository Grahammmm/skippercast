# Operating SkipperCast

The deployable system stays small: a static mobile web app, reviewed regional packages and scheduled Python collectors. There is no public write API, user account database or server-side execution of user input. The existing private Telegram monitor remains separate from the public site; no credentials or delivery records are moved into this repository.

| Owner | Work | Cadence | Failure behavior |
| --- | --- | --- | --- |
| GitHub daily-data workflow | Regional surface grids, model archives, legal/source watches, dated landing facts | Daily at the configured Pacific schedule | Publish explicit health and preserved source timestamps; fail the workflow for critical coverage failure |
| GitHub live-conditions workflow | Region-bound NOAA buoy feeds | Every 30 minutes | Publish missing/stale/retained states, report failure |
| Browser | Fresh forecast requests, observation/advisory refresh, live MPA query | Forecast 30 min; observations 5 min while open | Show source gaps, withhold unsupported claims |
| Reviewed source update | Source identity, rights, species evidence, static survey/closure derivations | When changed or onboarding a region | Hold candidate data outside fishing layers |

The jobs discover active and preview regions from configuration and publish each under `regions/<id>/`. Legacy root feeds remain aliases of Morro Bay for existing clients. Each feed branch update is one Git commit; workflow concurrency prevents overlapping writers. A source failure does not erase the last good payload, but its old observation/retrieval times and failure state remain visible. Never retry ambiguous external deliveries with a new event ID; the private alert adapter owns that lifecycle.

The scheduled refresh uses read-only public APIs and bounded downloads. Keep secrets in the hosting/GitHub credential stores, never in regions, source registries, browser JavaScript or logs. Review changes to workflows, catalogs and parsers as code. Provider responses are untrusted data; source-page text cannot authorize commands, endpoint changes or publication. URLs must be public HTTPS; documentation auditing rejects non-public DNS addresses and unsafe redirects. The collectors accept reviewed configuration rather than visitor-supplied URLs.

The public app inserts provider names and narrative facts as escaped text; region selectors and coverage reports use DOM text nodes. Survey and package paths are confined to the public root. Local dependencies are vendored and checked by digest. No tracking/analytics was added. Provider APIs and map tile hosts will receive normal network metadata from visitors; a public GitHub source repository cannot store personal trip data. Open-Meteo's free service has use and request limits; its license and service terms are distinct. A growing or commercial deployment must choose an authorized service plan before exceeding them. Do not pool traffic into an unbounded anonymous proxy.

For coast-wide growth, keep one region manifest and lazy assets per area. Deduplicate shared stations, model requests and legal jurisdictions when network volume warrants it. Move large raster/AIS archives to immutable object storage and spatial indexes only when actual dataset size justifies that change. The current static Git branch feed is intentionally simple; its request limits and branch size should be measured before a coast-wide launch. The personal-use source license and each upstream data license continue to apply independently.

Release checks: Python contract/parser tests; JS forecast/geometry tests; region compiler; source/asset integrity; closure exclusions; a mobile map/selection/forecast pass in both regions; and actual feed delivery receipts. Site publication and feed publication are separate outcomes. A healthy code deployment does not prove live sources are available. Inspect GitHub Actions failures and per-source health before claiming live coverage.

Recovery: retain the last published site version and feed commits; roll back a coherent site/package version; do not overwrite a feed's region or observation time to make it look fresh. If rules or MPA access fail, withhold the affected permission/target claims. If a single expansion fails, keep its preview clearly limited while the established region continues. GitHub schedules can be delayed; freshness thresholds, not the scheduled time, decide whether data are current.

Before adding accounts, payments, public uploads or messaging, define access control, abuse limits, privacy retention and an appropriate security review for those actual features. This release does not pretend those future surfaces already exist.
