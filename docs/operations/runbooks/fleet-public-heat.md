# Runbook: public heat map go-live

**Use when:** switching on the public charter-fleet heat route (`GET /api/fleet/public/heat`), checking it before or after the switch, or taking it down again.
**Severity:** going live is a planned owner step (graph.md owner step 11), not an incident. Treat any response that carries a boat, track, port, class or a cell under the floors as SEV2: switch the flag off first, then investigate.
**Owner:** repository owner (the repository variable, the deploy workflow, the Q1 decision). An agent can run the checks below and opens fix PRs.
**Setup reference:** [design.md § 14–17](../../plans/charter-fleet/design.md#14-map-layers-and-filters), `server/fleet/public-heat.ts`.

## What the route serves

Whole-season aggregate cells only, as GeoJSON polygons with `kind`, `season`, `dwell_min`, `vessels_n`, `basis` and `computed_at`. Season-part cells are never served (a `season_part` parameter is a 400): subtracting published parts from a whole season would reveal a withheld part's dwell. The floors are fixed in code (`PUBLIC_HEAT`): at least 3 distinct vessels, a last date wholly at least 72 h old, and rights `public-domain`, `public-record`, `facts-only` or `api-terms`. `internal-only` and `noaa-planning-only` (MarineCadastre) cells never appear. Nothing else exists under `/api/fleet/public/`.

## Before the switch (all must hold)

1. **N7 passed**: the owner approved the labelled validation set and `python -m skippercast.fleet.ais validate` met its targets.
2. **Q1 settled**: aisstream.io gave written terms that allow display. Then a one-line PR changes `SOURCE_RIGHTS["aisstream"]` in `src/skippercast/fleet/ais/process.py` from `internal-only` to `api-terms`, and the next processor run rewrites the cells' rights. Until then the route returns an empty collection, which is correct.
3. **The deploy passes the flag**: `.github/workflows/deploy-cloudflare.yml` (owner area) passes `FLEET_PUBLIC_HEAT_ENABLED: ${{ vars.FLEET_PUBLIC_HEAT_ENABLED }}` beside `FLEET_ENABLED`; `scripts/wrangler_config.mjs` already copies it into the Worker's vars.
4. **Checks green on `main`**: `node --test tests/test_fleet_public_heat.mjs tests/test_fleet_map.mjs` and `PYTHONPATH=src python -m pytest -q tests/unit/test_fleet_aggregate.py tests/unit/test_fleet_events.py`.

## Switch on

Set the repository variable `FLEET_PUBLIC_HEAT_ENABLED` to `true` (with `FLEET_ENABLED` already `true`) and redeploy `main`. `FLEET_MAP_ENABLED` is independent: it opens the admin map only.

## Check after the deploy

```bash
curl -s 'https://skippercast.com/api/fleet/public/heat?region=CA' | jq '.meta, (.features[0].properties | keys)'
curl -s -o /dev/null -w '%{http_code}\n' 'https://skippercast.com/api/fleet/public/events?region=CA'   # 404
```

`meta.min_vessels` is 3, `meta.delay_hours` is 72, every feature's `vessels_n` is at least 3, and the property keys are exactly the six above. No public page draws the layer yet: the map UI is a separate change.

## Switch off

Set `FLEET_PUBLIC_HEAT_ENABLED` to `false` (or delete it) and redeploy; the route answers 404 again. No data changes.
