# Operating SkipperCast

The public map uses shared browser components and reviewed regional packages. A small Sites Worker serves cached environmental data and private, sign-in-only trip alerts and comfort feedback in D1. The existing personal Telegram monitor stays separate: its credentials, delivery records and route remain outside this site and repository.

| Process | Owner and cadence | Failure behavior |
|---|---|---|
| Legal/source checks, habitat context and dated landing facts | Existing GitHub daily-data workflow | Preserve source times; changed or stale legal sources withhold the open badge |
| Buoys, weather models, ensembles, radar, WCOFS and verification | Existing live-conditions workflow, twice hourly | Atomic regional feed commit; distinguish coverage gaps from failed access |
| Personal trip assessments | Same workflow after public feed publication | Signed GitHub OIDC request; private outbox and per-device receipts; delivery failures fail the job |
| Browser refresh | Forecast 30 minutes; live observations/advisories 5 minutes while open | Shared cache first, direct-source recovery; optional failures do not stop the map |
| Source review and survey rebuild | Onboarding or material source change | Candidate data remain outside qualified fishing layers |

Schedules can be delayed. Freshness uses actual source/run times, not the scheduled time. Jobs discover active and preview region manifests. Public feeds live under `regions/<id>/` on the `data` and `conditions` branches; legacy root feeds are Morro Bay aliases. One writer per workflow and atomic commits prevent mixed snapshots. The 30-day prospective verification state contains public environmental samples, never personal trips.

## Deploy and configure

1. Edit reviewed region/source/jurisdiction/ecology configuration. Run the region compiler and offline tests.
2. `pnpm install --frozen-lockfile`, then `pnpm build`. Authored web files remain in `dist/`; generated `dist/client`, `dist/server` and `dist/.openai` are ignored. The build copies committed Drizzle migrations into `dist/.openai/drizzle`.
3. Publish the exact committed source through Sites. `.openai/hosting.json` declares logical binding `DB`; the platform provisions it and applies migrations. Never create tables in request handlers. Add migrations rather than rewriting a deployed one.
4. Keep `VAPID_PRIVATE_KEY` in Sites as a secret and its matching `VAPID_PUBLIC_KEY` as a runtime value. Preserve the pair across releases so existing subscriptions remain valid. Neither belongs in public feeds or logs.
5. `deployments/production.json` defines the public and allowed origins, plus the scheduler's immutable GitHub repository/owner IDs, branch and workflow. A new deployment must change these reviewed settings. No long-lived scheduler password is needed.
6. Preserve public audience. Anonymous readers use maps and weather. Platform-owned `/signin-with-chatgpt` enables private features; server ownership uses only platform-injected user headers.

The scheduler obtains a short-lived OIDC token for the exact `/api/jobs/check` audience. The Worker accepts RS256 signatures from GitHub's fixed JWKS endpoint and verifies issuer, audience, subject, repository ID, owner ID, branch, workflow, event and validity period. Pull-request identities cannot run production alerts. Tokens are not logged or saved. See [GitHub's claims documentation](https://docs.github.com/en/actions/reference/security/oidc).

## Private records and alerts

Every private query is owner-scoped. Mutations require an allowed Origin, bounded JSON and a rate budget. Trip dates, area, species and numerical preferences are validated. Limits are 20 active trips and five notification devices. Push endpoints are restricted to known browser push services; arbitrary URLs and redirects are rejected.

Saving a trip does not grant notification permission. Permission is requested only after a button press. On iPad/iPhone the site may need to be added to the Home Screen. In-app assessments remain available without push. Stable event IDs and per-subscription claims prevent duplicate sends. Only an accepted adapter response marks push delivery; a timeout remains uncertain and is not automatically retried. Provider acceptance does not prove display on the device.

Checks compare the entire saved hour window, rougher wind/seas, hazards, advisories and reviewed trip-date rules. Source loss retracts prior threshold fit. The final previous-evening assessment is required even when unchanged; a missed final is labeled honestly once. These preference alerts do not certify a route, entrance, bite or whole trip. They do not replace the separate 9/10 personal morning-monitor rubric.

Trips and assessments are retained for 90 days; comfort feedback for one year. Users can export records or delete records and subscriptions. Feedback is private and descriptive; it does not silently train public catch or vessel-motion models. Account IDs and notification endpoints never enter public Git branches.

## Health, recovery and scale

Inspect `/api/health`, the GitHub workflows and regional source health. An empty 1 km radar footprint differs from a failed download; available 6 km observations remain a separate layer. A successful fetch cannot approve a legal change or establish a catch.

Held/uncertain deliveries require receipt reconciliation before a resend. Preserve event identity; do not create a new ID to retry the same send. Users can acknowledge the assessment in the private UI. The scheduler processes 25-trip pages to avoid starving records beyond a single fixed batch.

Retain the previous site version and feed commits. Roll back a coherent site/package version; keep private data intact with forward-compatible migrations. Back up/export D1 before a destructive future migration. Recheck anonymous/private routing and source freshness after publishing. Site publication and feed publication are distinct outcomes.

The Worker caches reviewed regional feeds, not arbitrary URLs. Before coast-wide growth, measure provider budgets, Git feed size, Worker limits and database load. Deduplicate shared station/model requests across regions and move growing archives to immutable object storage when measured size requires it. Open-Meteo free service is for noncommercial access with limits; upstream terms remain separate from the personal-use source license.

Release checks include Python contracts/parsers; JS forecast, GPX, private API and outbox tests; signed-job rejection tests; regional compilation; asset/secret checks; Worker build with migrations; cloud receipts; and a mobile browser pass when authorized tooling is available. An unavailable browser or device check is a limitation, never a pass.
