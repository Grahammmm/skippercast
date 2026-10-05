# Charter fleet: design

The engineering design for the charter fleet registry and the AIS activity
map, written for an implementing agent that has not seen the conversation that
produced it. [dev-plan.md](dev-plan.md) is the task list; this document is the
reference each task points to. Decisions D1–D17 are recorded in
[README.md § Decisions already made](README.md#decisions-already-made-d1d17)
and are not reopened here; owner choices with ranked
options are in [open-questions.md](open-questions.md). Steps that need the
owner are marked **Owner**.

Two wording rules apply in code, copy and docs:

- Activity derived from AIS is **"inferred from movement"**. Never call a
  fishing stop, catch or hotspot "confirmed" or "verified" from AIS (the rule in
  [docs/roadmap.md](../../roadmap.md) item 5 and `dist/data/ais-evidence.json`).
- Absence of AIS is not evidence. Class B users may switch off legally; never
  infer non-compliance.

## 1. Overview and goals

The feature finds every for-hire fishing boat operating out of a region,
profiles each boat and operator from public sources with provenance on every
fact, matches boats to AIS, and turns positions into trips, labelled track
segments and activity events on an admin map.

Goals, in order:

1. One command fills the registry from empty for a region id (`CA` first) and
   is safe to re-run; only low-confidence merges and conflicts need a person.
2. Every fact records source URL, retrieval time, method and confidence, and
   keeps its history.
3. Real-time AIS for watched boats, processed every 30 minutes into trips,
   segments and events that can be recomputed over any window.
4. Admin views (review queue, vessels, operators and outreach, AIS health,
   coverage) and a basic public boat profile, behind flags.
5. A second region needs a config file plus optional adapters.

Non-goals: booking and payments (offerings are modelled so they stay
possible), public per-vessel tracks, regional hot-spot claims, inland waters,
automated outreach.

Research findings this design rests on: about 420 boats statewide against 563
CPFV licences (2025); party and long-range boats are well covered by landing
pages, TECK.net report sites, USCG PSIX and the FCC ULS ship file, while
independent six-packs need the CPRA list, Google Places and operators' own
sites. In a 21-boat pilot the FCC file gave an MMSI for 81% of boats, 33% were
seen in an 11-day AIS sample (all in San Diego, none of nine Central Coast and
Bay party boats), and overall field fill was 55%. Terrestrial AIS loses Class B
boats past about 40–90 nm.

## 2. Scope and vessel classes

In scope: vessels taking paying passengers fishing on salt or tidal water,
six-pack (OUPV) and up.

| Field | Values | Rule |
| --- | --- | --- |
| `vessel_class` | `six-pack`, `inspected-party`, `long-range` | six-pack: uninspected, ≤ 6 passengers. inspected-party: COI, > 6 passengers, trips under 3 days. long-range: advertises any trip of 3+ days |
| `waters` | array of `ocean`, `bay`, `delta`, `inland` | `inland` is reserved: accepted by schemas, dropped by discovery when it is a candidate's only water, never rendered |

Dive-only, whale-watch-only and eco boats that hold a CPFV licence but
advertise no fishing are stored with `status='excluded'` and a `scope` fact so
they are not rediscovered as new each run.

## 3. Region config: `regions/<id>/fleet.json`

A fleet region is **state-level** with an upper-case postal id (`CA`, `OR`);
the pattern `^[A-Z]{2}$` keeps it distinct from the lower-case coastal region
ids (`morro-bay`, `southern-california`). `regions/CA/` holds only
`fleet.json`; the platform build and region contract test enumerate
`regions/*/region.json`, so they ignore it, and `scripts/build-worker.mjs`
skips directories without a `region.json` (CF-04). Validated by
`schemas/fleet-region.schema.json` (draft 2020-12, no additional properties),
loaded by `src/skippercast/fleet/config.py`. Nothing state-specific lives in
`src/`.

| Key | Content |
| --- | --- |
| `id`, `name`, `timezone`, `schema_version` | `CA`, `California`, `America/Los_Angeles`, `1` |
| `status` | `active`, or `dry-run` (staging sink only) |
| `ports[]` | `id`, `name`, `point` `[lat, lon]`, `home_port` (a `catalog/home-ports.json` id or null), `region` (coastal region id or null), `waters[]`, `geofence` (GeoJSON Polygon, lon/lat WGS84), `geofence_source` (`drawn` or `chart`) |
| `landings[]` | `id`, `name`, `port`, `point`, `website` (https or null) |
| `ais` | `source`, `bbox` `[[lat_s, lon_w], [lat_n, lon_e]]`, `message_types[]`, `mmsi_filter` |
| `agencies[]` | `id`, `name`, `kind` (`licensing`, `vessel-registry`, `radio-licence`), `notes`, `records_request_url` |
| `sources[]` | adapter bindings: `id`, `adapter`, `enabled`, `params`, `rights`, optional `note` |
| `thresholds` | `activity`, `match`, `refresh`, `retention`, `aggregate` |
| `seasons.parts[]` | `{id, months[]}` for the season filter |
| `resolver_overrides` | per-field overrides of `catalog/fleet/resolver.json` |

Region-independent config in `catalog/fleet/`: `resolver.json` (per field,
ordered source priority and minimum confidence, e.g. `mmsi`: `admin`,
`fcc-uls`, `ais-static`, `osint`), `off-limits.json` (section 6) and
`lead-score.json` (section 13). Their shapes are `$defs` in
`schemas/fleet-region.schema.json`, so one schema covers the region file and
its catalogs.

### CA example excerpt

Geofences here are illustrative. CF-04 committed generous hand-drawn polygons
(about 1–5 km; Humboldt Bay 8 km to reach its entrance) around each harbor basin and entrance, marked
`"geofence_source": "drawn"`; they are config and can be refined from charts
later (then `chart`). Bay Area and Delta ports have `region: null`, as here,
and San Diego is split into `san-diego` (Point Loma landings) and
`mission-bay` (Seaforth), each with its own geofence.

```json
{
  "schema_version": 1, "id": "CA", "name": "California",
  "timezone": "America/Los_Angeles", "status": "active",
  "ports": [
    {"id": "morro-bay", "name": "Morro Bay", "point": [35.3667, -120.868],
     "home_port": "morro-bay", "region": "morro-bay", "waters": ["ocean", "bay"],
     "geofence": {"type": "Polygon", "coordinates": [[[-120.874, 35.374], [-120.858, 35.374],
       [-120.842, 35.330], [-120.856, 35.326], [-120.874, 35.374]]]}},
    {"id": "emeryville", "name": "Emeryville", "point": [37.842, -122.312],
     "home_port": null, "region": null, "waters": ["bay", "ocean"],
     "geofence": {"type": "Polygon", "coordinates": [[[-122.318, 37.846], [-122.306, 37.846],
       [-122.306, 37.838], [-122.318, 37.838], [-122.318, 37.846]]]}},
    {"id": "san-diego", "name": "San Diego", "point": [32.72, -117.22],
     "home_port": "san-diego", "region": "southern-california", "waters": ["ocean", "bay"],
     "geofence": {"type": "Polygon", "coordinates": [[[-117.245, 32.730], [-117.215, 32.730],
       [-117.215, 32.700], [-117.245, 32.700], [-117.245, 32.730]]]}}
  ],
  "landings": [
    {"id": "fishermans-landing", "name": "Fisherman's Landing", "port": "san-diego",
     "point": [32.722, -117.229], "website": "https://www.fishermanslanding.com/"}
  ],
  "ais": {"source": "aisstream", "bbox": [[27.5, -126.5], [42.1, -114.5]],
          "message_types": ["PositionReport", "StandardClassBPositionReport",
            "ExtendedClassBPositionReport", "ShipStaticData", "StaticDataReport"],
          "mmsi_filter": false},
  "agencies": [
    {"id": "cdfw", "name": "California Department of Fish and Wildlife", "kind": "licensing",
     "notes": "CPFV licence (FGC 7920); names and FG numbers public under FGC 8022(b)(2)",
     "records_request_url": "https://wildlife.ca.gov/General-Counsel/Public-Records-Requests"},
    {"id": "uscg", "name": "US Coast Guard", "kind": "vessel-registry",
     "notes": "PSIX sectors San Diego, LA-LB, San Francisco, Humboldt Bay", "records_request_url": null}
  ],
  "sources": [
    {"id": "fcc-uls", "adapter": "fcc-uls", "enabled": true, "rights": "public-domain",
     "params": {"state": "CA", "all_statuses": true}},
    {"id": "uscg-psix", "adapter": "uscg-psix", "enabled": true, "rights": "public-domain",
     "params": {"sectors": ["San Diego", "Los Angeles - Long Beach", "San Francisco", "Humboldt Bay"]}},
    {"id": "socalfishreports", "adapter": "teck-reports", "enabled": true, "rights": "facts-only",
     "params": {"base": "https://www.socalfishreports.com", "directory": "/charter_boats/index.php"}},
    {"id": "fishermans-landing", "adapter": "landing-pages", "enabled": true, "rights": "facts-only",
     "params": {"landing": "fishermans-landing", "template": "fr-fleet-php",
                "url": "https://www.fishermanslanding.com/fleet.php"}},
    {"id": "google-places", "adapter": "google-places", "enabled": true, "rights": "api-terms",
     "params": {"query": "fishing charter", "per_port": true}},
    {"id": "cpra-cpfv", "adapter": "file-import", "enabled": false, "rights": "public-record",
     "params": {"path": "inputs/cpra-cpfv.csv", "columns": "cdfw-cpfv-v1"}}
  ],
  "thresholds": {
    "activity": {"in_port_debounce_min": 3, "min_trip_minutes": 20, "min_trip_offshore_nm": 0.5,
      "gap_unknown_min": 30, "gap_split_hours": 12,
      "max_open_trip_hours": {"six-pack": 18, "inspected-party": 40, "long-range": 480},
      "window_min": 20, "min_segment_minutes": 5, "simplify_tolerance_m": 25,
      "drift": {"max_sog_kn": 2.0, "min_minutes": 15},
      "troll": {"min_sog_kn": 4.0, "max_sog_kn": 9.0, "max_straightness": 0.6,
                "min_heading_variance": 0.35, "min_minutes": 15}},
    "match": {"auto_merge": 0.9, "review_min": 0.6, "mmsi_auto": 0.85},
    "refresh": {"vanished_after_runs": 3, "vanished_after_days": 45,
                "osint_stale_days": 60, "fact_stale_days": 120},
    "retention": {"raw_days": 30, "discovery_days": 7, "static_days": 90},
    "aggregate": {"module": "grid", "resolution_m": 1000,
                  "min_distinct_vessels": null, "delay_hours": null}
  },
  "seasons": {"parts": [{"id": "winter", "months": [12, 1, 2]}, {"id": "spring", "months": [3, 4, 5]},
                        {"id": "summer", "months": [6, 7, 8]}, {"id": "fall", "months": [9, 10, 11]}]},
  "resolver_overrides": {}
}
```

`tests/contract/test_fleet_region.py` checks every `regions/*/fleet.json`:
schema valid; each geofence is a closed simple polygon containing its port and
landing points; `home_port` and `region` ids exist; every adapter id is
registered; no binding names an off-limits host; the AIS bbox contains every
port. `load_region` also rejects a port point inside another port's geofence,
a port outside its coastal region's bounds, non-https binding URLs, seasons
that do not cover each month once, inverted thresholds and resolver overrides
of unknown fields.

## 4. Architecture

| Where | Component | Trigger |
| --- | --- | --- |
| Cloudflare Worker | fleet job API, admin API, map API, `/boats/<slug>` extension, `/go/<slug>` | HTTP |
| Hermes, user systemd unit | AIS listener | always on |
| Hermes, Actions on `vars.DATA_RUNNER` | `fleet-registry.yml` (weekly + dispatch), `fleet-osint.yml` (weekly + dispatch), `fleet-ais.yml` (every 30 min), `fleet-ais-listener.yml` (dispatch: install/update the unit) | schedule, `workflow_dispatch` |
| GitHub-hosted runner | `fleet-health.yml` (hourly staleness check) | schedule |

`fleet-health.yml` runs on `ubuntu-latest` so it can alert while Hermes is
down. No fleet workflow triggers on `pull_request`, so fork code never runs on
Hermes.

```
 Public sources                Hermes (DATA_RUNNER jobs + systemd)                         Cloudflare
 FCC ULS, PSIX, TECK.net, ─► discover ─► candidates ─► resolve ◄── snapshot ───────────── /api/fleet/jobs/snapshot
 landings, directories,                                   │
 Places, operator sites  ─► enrich-code ─► facts ─────────┼─► ingest ──OIDC──────────────► /api/fleet/jobs/registry
                                                          │      ▲                              │
 claude -p charter-osint ◄─ manifests ◄─ plan-agent ◄─────┘      │                              ▼
        └──► profiles/*.json ─► validate-profile ────────────────┘                     D1 fleet_* tables
                                                                                         │      ▲
 aisstream.io ─► listener ─► raw store (SQLite, 30 d) ─► processor (30 min) ──OIDC──►   │      │ /api/fleet/jobs/activity,
 MarineCadastre ─► backfill ─┘                           trips, segments, events,        │      │ /watch, /heartbeat
                                                         aggregates, MMSI matches        ▼      │
                                                                             admin, map API, /boats, /go
 fleet-health.yml (hosted) ──OIDC──► /api/fleet/jobs/health ──► GitHub issue "fleet-ais-stale"
```

Python in `src/skippercast/fleet/`:

```
__main__.py, cli.py      python -m skippercast.fleet <step> --region CA [--sink worker|staging]
config.py                fleet.json + catalog/fleet/* loading and validation
net.py                   fleet HTTP session (allowlist, off-limits deny, robots.txt, cache)
runs.py, sinks.py        run directories and state; WorkerSink, SqliteSink
adapters/                base, fcc_uls, uscg_psix, teck_reports, landing_pages, directories,
                         operator_site, google_places, file_import
normalize.py, resolve.py entity resolution
enrich.py, profile.py    enrich-code; profile validator and profile → facts
agent.py                 plan-agent manifests
ingest.py, refresh.py    upserts and change detection
report.py                fleet report
ais/                     store, listener, watch, match, segment, classify, events, simplify,
                         process, backfill, validate; sources/{base,aisstream,marinecadastre,datalastic};
                         aggregate/{base,grid}
```

TypeScript in `server/fleet/` (`settings.ts`, `ids.ts`, `jobs.ts`,
`registry.ts`, `activity.ts`, `map.ts`, `go.ts`, `admin/*.ts`) behind one
router, `server/routes/fleet.ts`, mounted in `server/app.ts`. Admin UI in
`web/admin/fleet-*.tsx`; map layers in `dist/fleet-activity.js`.

**Working directory.** State lives under `$SKIPPERCAST_FLEET_VAR`, default
`<repo>/var/fleet` (gitignored). On Hermes it is set outside any checkout
(`~/.local/share/skippercast/fleet`), because `actions/checkout` cleans
ignored files and the listener and jobs share the raw store.

```
<FLEET_VAR>/<region>/runs/<run_id>/{candidates,resolved,facts}.jsonl, state.json, report.json
<FLEET_VAR>/<region>/runs/<run_id>/manifests/batch-NNN.json, profiles/<vessel_id>.json
<FLEET_VAR>/<region>/inputs/       owner-supplied files (the CPRA response)
<FLEET_VAR>/<region>/http-cache/
<FLEET_VAR>/<region>/ais/raw/YYYY-MM-DD.sqlite, state.sqlite, heartbeat.json, watch.json, validation/
<FLEET_VAR>/staging/<region>.sqlite
```

## 5. Data model

D1 through Drizzle in `db/schema.ts`, prefix `fleet_`, migrations generated
with `pnpm db:generate --name <name>` and never hand-written
(`tests/test_migrations.mjs`). Existing conventions: snake_case, `text`
primary keys (random 16-byte base64url, or `sha256(...)[:32]` hex where
idempotency needs it), `*_at` ISO-8601 UTC, `*_json` validated on read,
integer booleans, short index names.

| Migration | Tables | Task |
| --- | --- | --- |
| `0013_fleet_registry` | `fleet_operators`, `fleet_vessels`, `fleet_vessel_facts`, `fleet_aliases`, `fleet_offerings`, `fleet_departures`, `fleet_reviews`, `fleet_changes`, `fleet_outreach`, `fleet_link_clicks`, `fleet_runs`; `advisor_boats.fleet_vessel_id` | CF-02 |
| `0014_fleet_activity` | `fleet_ais_watch`, `fleet_trips`, `fleet_segments`, `fleet_events`, `fleet_aggregates`, `fleet_segment_labels`, `fleet_ais_hours`, `fleet_trip_reports` | CF-03 |

### Registry (0013)

**`fleet_vessels`** holds the current resolved value per field (D4).

| Column | Type | Notes |
| --- | --- | --- |
| `id` | text PK | `sha256(region:creation_key)[:32]`; `creation_key` is the strongest key at creation (`uscg:1234567`, `cf:…`, `mmsi:…`, else `name-port:sea-example|morro-bay`), so a rebuild from empty yields the same ids |
| `region`, `slug` | text | slug unique here and across `advisor_boats.slug` (checked in code) |
| `name`, `name_norm` | text | display and normalised (section 7) |
| `operator_id`, `port_id`, `landing_id` | text, nullable | |
| `vessel_class`, `waters_json` | text, nullable | D1; null on a discovery candidate until it is classified (§8 selects vessels missing `vessel_class`) |
| `uscg_doc`, `state_reg`, `hull_id`, `call_sign`, `mmsi` | text, nullable | stable keys |
| `year_built`, `passengers_max`, `bunks` | integer, nullable | |
| `length_ft`, `beam_ft`, `cruise_kn` | real, nullable | |
| `website`, `booking_url`, `booking_platform`, `phone_business`, `email_business` | text, nullable | business contact only |
| `status` | text | `active`, `inactive`, `sold`, `excluded` |
| `profile_status` | text | `listed` or `hidden`, default `hidden` (fail closed): listing is an explicit admin or resolver action |
| `map_display_consent` | text | `none`, `aggregate` or `named`, default `none` (US-C4): the operator's consent for this boat on any public activity layer; admin views ignore it. Changes are recorded as `admin` facts, so who and when stay in the fact history |
| `removal_requested_at` | text, nullable | ISO UTC time the operator asked for this boat to be hidden or removed (US-C3); set by the admin action that sets `profile_status = hidden`, kept when the vessel is later unhidden by an admin so the request date is not lost |
| `pinned_json` | text | fields an admin set; the resolver skips them |
| `completeness` | real | share of target fields filled |
| `first_seen_at`, `last_seen_at`, `last_profiled_at`, `created_at`, `updated_at` | text | `last_seen_at`: last run any discovery source listed it |

Indexes: unique `fv_slug`; `fv_region_port (region, port_id)`, `fv_mmsi`,
`fv_doc`, `fv_state_reg`, `fv_name (region, name_norm)`, `fv_operator`. Stable
keys are deliberately not unique: a conflict is a review, not a failed insert.

**`fleet_vessel_facts`**: one row per observed value.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | text PK | `sha256(vessel_id|field|source_id|source_url|value_key)[:32]`; re-seeing a fact touches it |
| `vessel_id`, `field` | text | field is a profile path (`mmsi`, `trip_types[].price_usd`, `social.instagram.url`); operator-level facts are recorded on each of the operator's vessels |
| `value_json`, `value_key` | text | `value_key = sha256(canonical value)[:16]` separates list items |
| `source_id`, `source_url` | text | binding id (`fcc-uls`, `osint`, `admin`); https URL, or `admin:<users.id>` |
| `method` | text | `page`, `api`, `search`, `inference`, `registry`, `ais`, `operator`, `admin` (`operator`: supplied by the operator directly, e.g. in outreach) |
| `confidence` | real | 0–1 |
| `rights` | text | `public-domain`, `facts-only`, `api-terms`, `public-record`, `noaa-planning-only`, `internal-only` |
| `retrieved_at`, `first_seen_at`, `last_seen_at` | text | |
| `superseded_at`, `superseded_by` | text, nullable | set when the same source reports a new scalar value |
| `run_id` | text, nullable | null for admin edits, which have no run |

Indexes: `fact_vessel_field (vessel_id, field, superseded_at)`,
`fact_source (source_id, last_seen_at)`.

Other registry tables:

- **`fleet_operators`**: `id` random, `region`, `slug` (unique), `name`,
  `user_id` (nullable `users.id`, US-B3: a future operator account; nothing
  assumes operators are anonymous),
  `website`, `phone_business`, `email_business`, `booking_platform`,
  `consent_status` (`unknown`, `contacted`, `declined`, `content-sharing`,
  `partner`), `consent_scope_json`, `consent_recorded_at`,
  `consent_recorded_by`, `consent_revoked_at` (nullable ISO UTC, US-S3: set
  when the operator withdraws consent; reads treat a non-null value as no
  consent from the next request), `outreach_status` (`none`, `drafted`, `contacted`, `declined`,
  `replied`, `partner`, `do-not-contact`), `lead_score` real, `lead_score_json`,
  `created_at`, `updated_at`. Indexes unique `fo_slug`, `fo_region`, `fo_outreach`.
- **`fleet_aliases`**: PK `(vessel_id, alias_norm)`; `alias`, `kind`
  (`former-name`, `spelling`, `ais-name`, `report-name`), `source_url`,
  `first_seen_at`, `last_seen_at`; index `alias_lookup (alias_norm)`.
- **`fleet_offerings`**: `id` `sha256(vessel_id|name_norm|season)[:32]`,
  `vessel_id`, `name`, `trip_type` (`half-day`, `three-quarter-day`,
  `full-day`, `overnight`, `multi-day`, `private-charter`, `other`),
  `duration_h`, `price_cents`, `price_basis` (`per-person`, `private`), `capacity` (nullable integer, passengers per trip),
  `currency`, `departs_local` (`HH:MM`), `days_json`, `season_from`,
  `season_to` (`MM-DD`), `target_species_json` (`catalog/species.json` keys),
  `booking_url`, `status` (`active`, `retired`), `source_fact_ids_json`,
  `valid_from`, `valid_to`, `updated_at`; index `offer_vessel (vessel_id, status)`.
- **`fleet_departures`**: dated trips where a schedule is published. `id`
  `sha256(offering_id|date|departs)[:32]`, `offering_id`, `vessel_id`, `date`,
  `departs_local`, `price_cents`, `load_text` (as published), `source_url`,
  `retrieved_at`; index `dep_vessel_date`.
- **`fleet_reviews`**: `id` `sha256(kind|fingerprint)[:32]` (a repeat updates,
  never duplicates); `region`, `kind` (`merge`, `mmsi`, `class`,
  `fact-conflict`, `change`, `vanished`, `advisor-link`, `scope`),
  `subject_id`, `candidate_json`, `proposal_json`, `score`, `status` (`open`,
  `decided`, `dismissed`), `decision_json`, `decided_by`, `decided_at`,
  `opened_at`, `run_id`; index `fr_open (region, status, opened_at)`.
  Decisions come back in the snapshot so re-runs never re-ask.
- **`fleet_changes`**: `id` `sha256(vessel_id|kind|after_json)[:32]`,
  `vessel_id`, `kind` (section 9), `before_json`, `after_json`, `detected_at`,
  `run_id`, `review_id`; indexes `fc_vessel`, `fc_kind (kind, detected_at)`.
- **`fleet_outreach`** (private, D14): `id` random, `operator_id`, `kind`
  (`note`, `draft`, `sent-by-owner`, `reply`), `channel`, `body` (≤ 8,000
  chars), `status` (`draft`, `approved`, `discarded`, `logged`),
  `created_by`, `created_at`, `approved_by`, `approved_at`; index
  `out_operator`. No code path sends anything.
- **`fleet_link_clicks`** (D15): PK `(vessel_id, target, placement, day)`,
  `count`. `target` `booking`/`website`; `placement`
  `profile`/`directory`/`map`/`other`; no IP, user agent, user id or referrer.
- **`fleet_runs`**: `id` (`run_id:step`), `region`, `step`, `sink`,
  `started_at`, `finished_at`, `status` (`running`, `ok`, `failed`,
  `partial`), `counts_json`, `error`; index `run_region_time`.
- **`advisor_boats.fleet_vessel_id`** (D5): nullable, index `boat_fleet`. Set
  only by an admin deciding an `advisor-link` review, proposed when a
  skipper-registered boat's normalised name and port match a registry vessel.

### Activity (0014)

- **`fleet_ais_watch`**: PK `(region, mmsi)`; `vessel_id` (null while a
  candidate), `match_method` (`fcc-uls`, `call-sign`, `ais-static-name`,
  `geofence-presence`, `admin`), `confidence`, `status` (`candidate`,
  `watched`, `rejected`), `ais_name`, `ais_call_sign`, `ais_class`,
  `first_seen_at`, `last_seen_at`, `last_seen_source`, `positions_30d`,
  `updated_at`; index `watch_vessel (vessel_id)`.
- **`fleet_trips`**: `id` `sha256(mmsi|departed_at|source)[:32]`, `region`,
  `vessel_id`, `mmsi`, `depart_port_id`, `return_port_id`, `departed_at`,
  `returned_at`, `local_date` (departure date in the region timezone; the
  catch-log join key), `season` (`2026`), `season_part`, `status` (`open`,
  `closed`, `truncated`), `trip_type_inferred`, `distance_nm`,
  `max_offshore_nm`, `fishing_min`, `positions_n`, `gap_min`, `source`
  (`aisstream`, `marinecadastre`, `datalastic`), `rights`,
  `classifier_version`, `computed_at`. Indexes `trip_vessel_date (vessel_id,
  local_date)`, `trip_region_season (region, season)`, `trip_source_time
  (source, departed_at)`.
- **`fleet_segments`**: `id` `sha256(trip_id|seq)[:32]`, `trip_id`, `seq`,
  `kind` (`in-port`, `transit`, `fishing-drift`, `fishing-troll`, `gap`),
  `started_at`, `ended_at`, `geometry` (encoded polyline, precision 5),
  `points_n`, `mean_sog`, `straightness`, `heading_var`; index `seg_trip (trip_id, seq)`.
- **`fleet_events`**: one per fishing segment. `id`
  `sha256(trip_id|started_at|kind)[:32]`, `trip_id`, `segment_id`,
  `vessel_id`, `region`, `kind` (`drift-anchor`, `troll`), `lat`, `lon`
  (median), `radius_m` (p90 distance), `started_at`, `ended_at`, `dwell_min`,
  `port_id`, `vessel_class`, `trip_type`, `season`, `season_part`, `basis`
  (always `inferred-from-movement`), `source`, `rights`, `classifier_version`,
  `species_json` (null until catch-log pairing). Indexes `ev_region_time
  (region, started_at)`, `ev_vessel (vessel_id, started_at)`, `ev_season
  (region, season, kind)`.
- **`fleet_aggregates`**: `id` `sha256(module|params_hash|season|season_part|kind|cell)[:32]`,
  `region`, `module`, `params_json`, `cell_id`, `lat`, `lon`, `season`,
  `season_part`, `kind`, `vessels_n`, `events_n`, `dwell_min`, `first_date`,
  `last_date`, `rights` (most restrictive input), `computed_at`; index
  `agg_lookup (region, module, season, kind)`.
  The aggregator always writes whole-season cells (`season_part` null) beside
  the per-part cells, so a reader that wants the season reads the null-part
  rows and never sums parts (the map API's default, § 14).
- **`fleet_segment_labels`**: `id` random, `trip_id`, `started_at`,
  `ended_at`, `label`, `labeller` (`users.id` or `agent:<name>`), `basis`,
  `created_at`; index `label_trip (trip_id)`.
- **`fleet_ais_hours`**: PK `(region, hour)`; `messages`,
  `watched_messages`, `vessels`, `reconnects`, `max_gap_s`, `dropped`.
- **`fleet_trip_reports`** (catch-log pairing, filled later): PK
  `(trip_id, report_kind, report_ref)`; `report_kind` (`advisor`, `landing`),
  `report_ref` (`advisor_reports.id`, or the landing report `id` in the daily
  feed), `match` (`boat-date`, `alias-port-date`), `confidence`, `created_at`.
  Rule: same vessel and trip `local_date` = report date; advisor reports join
  through `advisor_reports.boat_id → advisor_boats.fleet_vessel_id`, landing
  reports through `fleet_aliases.alias_norm` plus port. Species are then
  attributed to the trip's events in proportion to dwell
  (`species_json` with `attribution: "report-paired"`), still not a catch
  location.

### Raw AIS store on Hermes

Never in D1 or git. One SQLite file per UTC day (`ais/raw/YYYY-MM-DD.sqlite`,
WAL) so retention deletes files:

- `positions(mmsi, ts /* epoch ms */, lat, lon, sog, cog, heading, nav_status,
  msg_type, source, received_at, PRIMARY KEY (mmsi, ts, source)) WITHOUT ROWID`
  for watched MMSIs;
- `discovery` (same columns) for unwatched vessels inside a geofence or whose
  static name matches a registry alias;
- `statics(mmsi, ts, name, call_sign, imo, ship_type, dim_bow, dim_stern,
  dim_port, dim_starboard, ais_class, source)` for every vessel in the bbox,
  deduplicated in memory, keyed `(mmsi, ts, source)` like the position tables.

All three ignore a repeated key. A position's `ts` is the transponder's fix
second within the minute of receipt, so one report heard by two stations is
stored once (`fleet/ais/sources/aisstream.py`).

Positions of other vessels are never written. `ais/state.sqlite` holds
processor state (last processed time per MMSI, open trips, run log).

### Retention

| Data | Kept |
| --- | --- |
| Raw positions (Hermes) | 30 days; discovery 7; statics 90 (a day's table goes once more than that many whole days have passed; the day file goes when all three have) |
| Raw positions of labelled validation trips | while the label exists |
| Trips, segments, events, aggregates, labels, hours (D1) | permanently, by season |
| Facts | permanently; superseded rows are history |
| Google rating and count facts | refreshed monthly, purged after 30 days without refresh |
| Outreach | until an admin deletes it; an operator's removal request deletes it |
| Run directories, HTTP cache (Hermes) | 90 days |

## 6. Source adapters

```python
class Adapter(Protocol):
    id: str                                   # registered name, e.g. "fcc-uls"
    kind: Literal["discover", "enrich", "both"]
    def discover(self, binding: Binding, ctx: RunContext) -> Iterable[Candidate]: ...
    def enrich(self, vessel: VesselView, binding: Binding, ctx: RunContext) -> Iterable[Fact]: ...
```

A `Candidate` carries names, port and landing hints, stable keys and `Fact`s
with the profile schema's provenance fields. `RunContext` gives the HTTP
session, run directory, clock and region config. Adapters never write to a
sink.

`fleet/net.py` wraps `skippercast.http.Session` (HTTPS only, public
addresses, size caps, backoff, conditional-GET cache) and adds: an allowlist of
hosts in `fleet.json` bindings plus operator websites already stored as facts;
a hard deny of `catalog/fleet/off-limits.json` before every request and
redirect; robots.txt per host for the `SkipperCast` user agent
(`urllib.robotparser`, cached 24 h); ≥ 1.0 s between requests per host; a
per-run budget per host (default 600). A denied or robots-blocked URL is a
recorded skip.

| Adapter | Gives | Access | Rights and rules |
| --- | --- | --- | --- |
| `fcc-uls` | call sign, MMSI, doc number, licensee entity | weekly `l_ship.zip` (~44 MB), local join, all statuses | public domain; keep a licensee only if an entity (LLC, Inc., Corp.); never addresses |
| `uscg-psix` | official number, service, call sign, hailing port, particulars | XML service / XLSX by sector | public domain |
| `teck-reports` | boats, landing, "Boat Information" block, catch recency | SoCal, SanDiego, NorCal FishReports; SportfishingReport as dedupe index | facts only; no text, images or captain mobiles. **Owner**: ask TECK.net before paid use |
| `landing-pages` | fleet, specs, captains, rates, schedules | per-landing binding, template `fr-fleet-php` or `generic` | facts only; photos as links with attribution |
| `directories` | seed lists | GGFA, Sportfishing Association of California, harbor lists | facts only; vessel and port, no personal names or mobiles |
| `operator-site` | phone, email, website, social links, booking platform signal, og:image link | operator's own site, ≤ 6 pages | business contact only; webmail kept only when published as the business contact, then flagged for review |
| `google-places` | `place_id`, status, rating, review count | Places API (New) | **Owner**: key. `place_id` kept; rating/count `api-terms`, 30-day purge, attribution where shown; CF-16 re-reads the current terms |
| `file-import` | CPRA CPFV list | owner CSV in `inputs/` | public record; entity licensees only |
| `ais-static` | MMSI candidates | listener statics, MarineCadastre | internal (section 11) |

**Off-limits (D7).** `catalog/fleet/off-limits.json`: `fishingbooker.com`,
`fareharbor.com`, `xola.com`, `fishdope.com`, `fishcity.app`,
`instagram.com`, `facebook.com`, `fb.com`, `meta.com`, `threads.net`. No
binding, agent fetch or fact `source_url` may use them (the contract test, the
session deny and the profile validator each check). A URL or handle on these
hosts may be stored as a *value* only when its `source_url` is the operator's
site, a landing page or a report site. Fish City is a manual completeness
benchmark at most. 976-TUNA stays disabled while its TLS certificate is
invalid; TLS is never bypassed. Global Fishing Watch is not used (non-commercial
licence).

### Relationship to the existing reports pipeline

The repository already fetches charter data; the fleet feature builds on it
rather than beside it.

| Existing piece | Fate | Decision |
| --- | --- | --- |
| `src/skippercast/pipeline/collect.py` (fetches TECK.net daily dock totals for regions with `landing_names`) | **extended** | CF-13's `teck-reports` adapter reuses its `Client`/`skippercast.http.Session` setup and the same conditional-GET cache directory, adding the boat-directory and "Boat Information" pages; there is no second TECK.net scraper and no second cache |
| `parsers.charter_reports()` (per-trip rows with `id`, `date`, `boat`, `port`, `trip_type`, `anglers`, `catches`, `source_url`, `boat_source_url`) | **reused** | its output in the daily feed is the alias + date join source for `fleet_trip_reports`: `boat` resolves through `fleet_aliases.alias_norm`, `port` must match, `date` equals the trip's `local_date`, and the row's `id` (sha256 of date, boat, trip type and ground, 16 hex) is stored as `report_ref`; `boat_source_url` seeds `report-name` aliases |
| `catalog/sources.json` `landing-reports` (adapter `landing-facts`) | **reused** | unchanged; it remains the catch-log feed the pairing reads |
| `catalog/sources.json` `operator-identities` (adapter `identity-register`) | **superseded** | `fleet_vessels` becomes the identity register. CF-17 adds a `fleet-registry` source entry, points each coastal region's `source_bindings.charter-identity` at it, and marks `operator-identities` superseded (kept for history, not used) |
| regions' `charter-identity` coverage status (`regions/<id>/region.json` `coverage`) | **extended** | computed from the registry: `python -m skippercast.fleet coverage-status --region CA` derives, per coastal region (via each port's `region`), a status and an aggregate-only reason ("N boats registered, M with an identified MMSI"); CF-17 applies it to `region.json` and rebuilds `dist/` with the platform build. Counts only, never names or contacts |
| `dist/data/ais-evidence.json` `fleet_name_screen` | **reused** | its normalisation rule (upper-case, drop everything except A–Z and 0–9, exact comparison) is the base of `name_norm` in section 7; name matches stay leads, not identifications |

## 7. Entity resolution

`resolve` assigns candidates using the Worker snapshot (vessels, aliases,
stable keys, pinned fields, decided reviews).

1. **Normalise.** `name_norm` starts from the `fleet_name_screen` rule in
   `dist/data/ais-evidence.json` (upper-case, keep only A–Z and 0–9), after
   first dropping a leading `THE`, `M/V` or `F/V` and turning roman numerals
   into digits; `NEW` is kept (New Seaforth is not Seaforth). Phones to E.164; URLs without tracking parameters.
2. **Prior decisions.** A candidate fingerprint (source id + record id or URL)
   with a decided review is assigned as decided.
3. **Stable keys** in order `uscg_doc`, `state_reg`, `hull_id`, `mmsi`,
   `call_sign`. One vessel matched → assign (1.0; 0.9 for call sign alone,
   since call signs are reissued). Different vessels matched by different keys →
   `merge` review. Key match with a new name → assign, add an alias, record
   `renamed`.
4. **Fuzzy fallback**: 0.55 × name similarity (Jaro-Winkler on `name_norm`,
   1.0 on an alias) + 0.25 × same port + 0.10 × same landing + 0.10 × length
   within 10% (unknown parts 0.5). ≥ `auto_merge` → assign; ≥ `review_min` →
   `merge` review with the top two; else new vessel.
5. Same name and port but different stable keys → two vessels (California has
   five FCC licences named Endeavor).
6. Class disagreement between two sources at confidence ≥ 0.7 → `class` review.
7. Out of scope → `excluded` with a `scope` fact.

The resolver then computes each `fleet_vessels` column from non-superseded
facts: highest-priority source, then highest confidence, then latest
`retrieved_at`; pinned fields are skipped. The Python resolver is the only
implementation; the Worker stores what it is sent and applies only "admin
facts pin the field".

## 8. The OSINT agent step

`enrich-agent` covers what code cannot: varied operator sites, free-text rate
tables, class judgment, conflict notes. The pilot estimated about 60% of
fields come from code.

**Manifest.** `python -m skippercast.fleet plan-agent --region CA [--mode
full|refresh]` selects vessels that are new, profiled more than
`osint_stale_days` ago, or missing `website`, `mmsi`, `vessel_class`,
`passengers_max` or `trip_types`, in batches of 20:

```json
{
  "manifest_version": 1, "region": "CA", "run_id": "2026-10-11T101700Z-osint",
  "batch_id": "batch-003", "created_at": "2026-10-11T10:17:00Z",
  "output_dir": "<FLEET_VAR>/CA/runs/<run_id>/profiles",
  "schema": "schemas/fleet-profile.schema.json",
  "validate": "python -m skippercast.fleet validate-profile <file>",
  "policy": {"off_limits": "catalog/fleet/off-limits.json", "min_interval_s": 1.0,
             "max_requests_per_boat": 12, "cache_dir": "<FLEET_VAR>/CA/http-cache/agent"},
  "boats": [
    {"vessel_id": "…", "name": "…", "aliases": ["…"], "port": "morro-bay", "landing": "…",
     "vessel_class_hint": "inspected-party",
     "known": {"website": "https://…", "mmsi": "…", "call_sign": "…", "uscg_doc": "…"},
     "missing": ["passengers_max", "trip_types"],
     "refresh": {"last_profiled_at": "2026-08-01T00:00:00Z", "focus": ["trip_types", "booking_url"]}}
  ]
}
```

Manifests hold only data the pipeline already has, under `<FLEET_VAR>`.

**Output contract.** The pilot schema moves to
`schemas/fleet-profile.schema.json` (`$id`
`https://skippercast.com/schemas/fleet-profile.schema.json`, the repository
convention `tests/contract/test_schemas.py` enforces; kind `fleet-profile` in
`skippercast.validate`) with these changes:
`schema_version` const `1.0.0`; `region` pattern `^[A-Z]{2}$`; new required
`vessel_id` (32 hex), `run_id`, `batch_id` (`batch-NNN`); new `boat.waters`
(provenance objects, enum D1); `boat.phone_business` a NANP number in E.164
(`^\+1[2-9]\d{9}$`, e.g. `+18055550123`), the same form the repository phone
scan matches, so ingest gets one format and the scan sees every fixture number. The provenance object (`value`, `source_url`, `retrieved_at`,
`method`, `confidence`), `conflicts[]` and `notes` are unchanged.

**Validator** (`fleet/profile.py`, CLI `validate-profile`; until CF-10's CLI
exists, `python -m skippercast.fleet.profile <file>`): JSON Schema plus
policy: no `source_url` on an off-limits host (provenance objects and
`conflicts[]`); off-limits values (a URL on an off-limits host, an Instagram or
Facebook handle or URL) only with `method` `page`, that is read off the
operator's site, a landing page or a report site; `boat.mmsi` and `ais.mmsi`
agree or a conflict is listed; `reputation.other` numbers only (never review
text); `notes` and `ais.notes` ≤ 2,000 chars; webmail emails flagged for
review (`review_flags`, not an error). The validator reads
`catalog/fleet/off-limits.json` as the only off-limits list (no copy in code);
a missing or malformed catalog is an error, never an empty list. Ingest refuses invalid files. Each
provenance object becomes one fact (`source_id "osint"`, confidence capped at
0.8 for `search` and `inference`); `trip_types[]` become offerings;
`conflicts[]` become `fact-conflict` reviews.

**Headless scheduled run.** `fleet-osint.yml` runs weekly (Sun 10:17 UTC) and
on dispatch (`region`, `mode`, `max_batches`) on `DATA_RUNNER`, gated
`vars.ENABLE_FLEET == 'true'`:

1. `plan-agent` writes manifests.
2. `scripts/fleet/run_osint.py` runs up to 3 batches at once
   (`FLEET_OSINT_PARALLEL`), each as `claude -p "<prompt naming the manifest>"`
   with the `charter-osint` definition, tools limited to `Read, Write, Glob,
   Grep, WebFetch, WebSearch` and `Bash` for the validator only, the run
   directory as working directory, 60 minutes per batch. CF-21 pins the CLI
   version and confirms the flags (agent selection, `--allowedTools`,
   `--output-format json`) against its `--help`.
3. **Subscription auth, no API key.** **Owner**, once on Hermes as the runner
   user: `claude setup-token` (or `claude login`); the token stays in
   `~/.config/skippercast/claude.env` (0600), not in GitHub. The script exits
   if `ANTHROPIC_API_KEY` is set, so a run can never bill the API.
4. Finished batches are recorded in `state.json`; a re-run skips them and
   retries failed ones once.
5. `ingest --profiles <run_dir>/profiles` validates and pushes.

`.claude/agents/charter-osint.md` (rewritten in the plan PR) lists only
allowed sources and carries the D7 off-limits list and handle rule (a handle or
URL on an off-limits host is recorded only when found on the operator's site, a
landing page or a report site). CF-21 verifies it still matches D7 and adds the
manifest contract. Local-model refreshes are not built:
deterministic adapters already refresh prices and schedules.

**Re-runs.** The same field, source and value re-seen updates `last_seen_at`;
a new scalar value from the same source supersedes the old row; a value missing
from a new profile changes nothing (absence is not evidence). Facts unseen for
`fact_stale_days` stop winning when a fresher fact exists.

## 9. Ingest and refresh

`ingest` sends operations to a sink:

- **WorkerSink**: `POST /api/fleet/jobs/registry` with a GitHub OIDC token (the
  pattern in `scripts/advisor/media_job.py`), ≤ 500 operations per request,
  retried with backoff. Kinds: `vessel.upsert`, `operator.upsert`,
  `fact.upsert`, `alias.upsert`, `offering.upsert`, `departure.upsert`,
  `review.open`, `change.record`, `run.record`.
  The OIDC audience is `<public_origin>/api/fleet/jobs`. `batch` counts up
  across the whole run (kept in the run's `state.json`), so each call has its
  own `fleet_runs` row. The sink runs the Worker's field checks before sending;
  a `413` means its batching is wrong and is not retried.
- **SqliteSink**: applies the committed migrations in `drizzle/meta/_journal.json`
  order to `<FLEET_VAR>/staging/<region>.sqlite` and runs the same operations
  with the same validation, ids and guards (`src/skippercast/fleet/ops.py`
  mirrors `server/fleet/ids.ts` and the field checks;
  `tests/test_fleet_sink_parity.mjs` runs both on the same operations). Used for
  dry runs, new regions and tests. A `dry-run` region refuses the WorkerSink.
  Known gaps, CF-17 scope: it writes no `<run_id>:registry.<batch>` call row;
  canonical JSON sorts keys by code point (JavaScript by UTF-16 unit, which
  differs only for keys outside the Basic Multilingual Plane); `*_json` size is
  counted in code points; https URLs are checked with `urlsplit`, not the
  WHATWG URL parser.

**Idempotency**: deterministic ids, upserts keyed on them, `review.open` never
reopens a decided review, change ids include the after-value. Running a step
twice produces zero row changes the second time; this is a test.

**Operation contract** (CF-11; `server/fleet/registry.ts` is the reference
implementation and the SqliteSink must behave the same).

- *Request*: `POST /api/fleet/jobs/registry` with `{"region", "run_id",
  "batch"?, "ops": [{"op": "<kind>", ...columns}]}`. `region` is a region id
  (letters, digits, `-`); `run_id` is letters, digits and `._-`, at most 80;
  `batch` is an integer 0–99999 (default 0) numbering the requests of one run.
  Body ≤ 1 MB and ≤ 500 ops, else `413`. Unknown top-level keys → `400`.
- *Response*: `200 {"ok": true, "run_id", "batch", "ops", "changed",
  "counts": {"<kind>": {"ops", "changed"}}}`; `changed` counts rows inserted or
  updated, so an identical replay answers `0`.
- *Errors*: every op is validated before anything is written; any invalid op →
  `400 {"error": "invalid operations", "errors": [{"index", "op", "error"}]}`
  (at most 50, by op index) and no registry row changes.
- *Op keys* are the table's column names, plus these non-column keys:
  `creation_key` (`vessel.upsert`, optional: checked against
  `id = sha256(region:creation_key)[:32]`), `seen_at` (`operator.upsert`,
  `offering.upsert`, required: when the pipeline observed the row; stored as
  `updated_at`), `supersedes` (`fact.upsert`, optional: up to 20 fact ids of
  the same vessel and field, not newer, which this fact supersedes),
  `fingerprint` (`review.open`, required: `id = sha256(kind|fingerprint)[:32]`)
  and `step` (`run.record`, required: the row id becomes `<run_id>:<step>`).
  Fact, departure, review and change ids are derived (`server/fleet/ids.ts`)
  and may be omitted; when sent they must match. Vessel, operator and offering
  ids are sent.
- *Worker-owned columns*, which an op must not send (`400`): `region`,
  `run_id`, a review's `status`, `value_key`, `superseded_at`,
  `superseded_by`, `created_at`, `updated_at`, `run.record`'s `id`; and the
  admin's `pinned_json`, `map_display_consent`, `removal_requested_at`, and an
  operator's `user_id`, consent and outreach columns. Unknown keys → `400`.
- *Values*: `*_json` keys take a JSON value (not a string), stored as
  canonical JSON (sorted keys, no whitespace, non-ASCII as is; integral floats
  written as ints: Python sends `int(x)`); `value_key` hashes that text.
  Timestamps are ISO-8601 UTC ending in `Z` and are stored with milliseconds
  (`2026-10-05T09:47:00.000Z`). Facts need an https `source_url`; `admin:`
  provenance and `method: admin` are rejected on the job route (the admin API,
  CF-30, writes them).
- *Updates*: upserts are keyed on the ids and run only when a stored value
  changes. Omitted fields keep their stored value; a present `null` clears it.
  An older replay never overwrites newer values: rows are guarded by their
  recency column (vessels and aliases `last_seen_at`, facts and departures
  `retrieved_at`, operators and offerings `seen_at`), `last_seen_at` and
  `retrieved_at` only move forward and `first_seen_at` only back. Pinned vessel
  columns (`pinned_json`, an object keyed by column name; unreadable pins all)
  are never overwritten, and a vessel with `removal_requested_at` is never
  re-listed. `review.open` updates only an open review of the same region.
  `change.record` inserts once.
- *Run log*: each call writes `fleet_runs` `<run_id>:registry.<batch>` (step
  `registry`, sink `worker`, `ok` or `failed`); the first `ok` is kept.

**Change detection** (`refresh`, after ingest):

| Kind | Rule |
| --- | --- |
| `new` | vessel created this run |
| `renamed` | stable key matched with a new name |
| `sold` | resolved operator changed, or the FCC/PSIX entity changed for the same doc number |
| `moved` | resolved port or landing changed |
| `vanished` | listed by no discovery source for `vanished_after_runs` runs **and** `vanished_after_days`; opens a review; status changes only on the admin decision |
| `returned` | vanished or inactive vessel listed again |
| `price` | active offering's price changed |
| `schedule` | offering added or retired, or departure time/days changed |
| `mmsi`, `class` | resolved value changed (MMSI also re-checks the watch list) |

`fleet-registry.yml` runs weekly (Mon 09:47 UTC) and on dispatch (`region`,
`sink`, `steps`). `python -m skippercast.fleet run --region CA --sink worker`
runs `discover → resolve → enrich-code → ingest → refresh` and writes
`report.json`. From empty: `run`, then `fleet-osint`, then `run` again fills
the registry; the only human step is the review queue.

## 10. AIS listener

```python
class AisSource(Protocol):
    id: str                                   # "aisstream", "datalastic", "marinecadastre"
    realtime: bool
    async def stream(self, bbox, mmsis: set[int] | None) -> AsyncIterator[AisMessage]: ...
    def history(self, day: date, bbox, mmsis) -> Iterator[AisMessage]: ...
```

`AisMessage` is normalised (position or static record, with `source`).
`aisstream` implements `stream` over `wss://stream.aisstream.io/v0/stream`
(`APIKey`, `BoundingBoxes`, optional `FiltersShipMMSI` ≤ 200,
`FilterMessageTypes`); `marinecadastre` implements `history`; `datalastic` is a
stub raising `NotConfigured` until the **Owner** decides to pay.

**Why this shape.** Discovery needs the statics of every vessel in the box
(that is how six-pack MMSIs missing from FCC ULS are found), so one bbox
subscription without an MMSI filter is used and only watched or discovery
positions are written. aisstream has no replay, so the listener must be always
on: a user systemd unit, not a scheduled job. `mmsi_filter: true` switches to
watched-only if volume becomes a problem.

**Service** (`fleet/ais/listener.py`):

- An asyncio reader feeds a bounded queue (50,000); a writer commits every
  second or 1,000 rows. The reader never waits on the database: over 80% full
  it drops discovery positions, then statics; watched positions are dropped
  only when full; drops are counted.
- Reconnect with exponential backoff (1 s to 5 min, full jitter); 120 s without
  a message forces a reconnect.
- Watch list re-read every 10 minutes from `ais/watch.json`, which the
  processor job refreshes from the Worker (the listener holds no GitHub identity).
- Heartbeat every 60 s to `ais/heartbeat.json` (atomic): last message time,
  messages and watched messages per minute, vessels, reconnects, drops, queue
  depth, watch size, start time, git sha.
- Hourly retention by `thresholds.retention`. The listener and the processor
  must not hold expired day files open across retention: open a day file per
  write batch or read window, and close it after. Retention never empties a
  hard-linked day file in place.
- A position whose `received_at - ts` exceeds 55 s may sit in the wrong minute
  (`ts` comes from the fix second); the store keeps the earliest receipt of a
  key, and the processor (CF-43) treats such a position's time as suspect.

Unit template `scripts/fleet/skippercast-fleet-ais@.service`:

```ini
[Unit]
Description=SkipperCast fleet AIS listener (%i)
After=network-online.target
[Service]
EnvironmentFile=%h/.config/skippercast/fleet-ais.env
WorkingDirectory=%h/.local/share/skippercast/app/current
ExecStart=%h/.local/share/skippercast/app/venv/bin/python -m skippercast.fleet.ais listen --region %i
Restart=always
RestartSec=10
MemoryMax=512M
[Install]
WantedBy=default.target
```

`fleet-ais-listener.yml` (dispatch only, `DATA_RUNNER`) copies the revision to
`~/.local/share/skippercast/app/<sha>`, builds the venv with the `fleet` extra
(`websockets`), repoints `current`, writes `fleet-ais.env`
(`AISSTREAM_API_KEY`, `SKIPPERCAST_FLEET_VAR`) with mode 0600, installs and
restarts the unit, then fails unless the heartbeat shows messages within 90 s.
**Owner**: create the aisstream key and add the `AISSTREAM_API_KEY` secret; run
`sudo loginctl enable-linger <runner-user>` once.

## 11. AIS processor

`fleet-ais.yml`: cron `3,33 * * * *`, `DATA_RUNNER`, `concurrency: fleet-ais`.
Each run: push heartbeat and hourly counters (`job_state`
`fleet.ais.<region>.heartbeat`, `fleet_ais_hours`); refresh `watch.json`; run
MMSI matching; process each watched MMSI from its last closed trip end minus
1 h to now minus 10 min; push trips, segments and events (replace-window);
recompute aggregates for touched seasons; apply retention; set
`fleet.ais.<region>.processed`.

**Trip segmentation.** In port = inside any harbor geofence of the region
(ray-casting point-in-polygon, no GIS dependency). A trip starts at the first
position outside after `in_port_debounce_min` inside and ends on return to any
geofence held for the debounce. Trips under `min_trip_minutes` or never beyond
`min_trip_offshore_nm` are dropped. A gap at sea over `gap_unknown_min` is a
`gap` segment; over `gap_split_hours` with the vessel next seen in port, the
trip closes at its last position as `truncated`. An open trip older than
`max_open_trip_hours[class]` is emitted `truncated`.

**Classification (D10).** Over a centred `window_min` (20 min) window per
position: mean SOG (reported, else derived), straightness = net displacement /
path length, heading variance = 1 − mean resultant length of COG. In precedence
order:

| Label | Rule |
| --- | --- |
| `in-port` | inside a geofence |
| `fishing-drift` | SOG ≤ 2 kn sustained ≥ 15 min outside geofences |
| `fishing-troll` | SOG 4–9 kn and (straightness ≤ 0.6 or heading variance ≥ 0.35), sustained ≥ 15 min |
| `transit` | everything else at sea |

Runs shorter than `min_segment_minutes` merge into the longer neighbour; a
fishing run under its minimum becomes transit. Output carries
`classifier_version` (a hash of the thresholds and code version).

**Events, tracks, aggregates.** One event per fishing segment (median point,
p90 radius, `basis=inferred-from-movement`). Each segment's positions are
simplified with Douglas-Peucker at 25 m on a local equirectangular projection
and stored as an encoded polyline; transits are kept. Aggregates are a
pluggable module (`ais/aggregate/base.py`: `compute(events, params) ->
list[Cell]`); `grid` bins dwell into `resolution_m` cells. The privacy knobs
`min_distinct_vessels` and `delay_hours` exist and are `null` for admin views;
an `h3` module needs no schema change.

**Re-runnable windows.** `python -m skippercast.fleet.ais process --region CA
--from 2026-06-01 --to 2026-06-30 [--source marinecadastre] [--mmsi …]`
recomputes trips departing in the window. The activity route deletes, in one
D1 batch, the trips, segments and events for those MMSIs, that source and that
departure window, then inserts the new set. Only rows the pipeline derived are
deleted. Labels are keyed by trip id and time range and survive reprocessing.

**MarineCadastre backfill (D9).** `ais/backfill.py` streams
`csv2/csv2026/ais-YYYY-MM-DD.csv.zst` (240–320 MB/day) through
`MarineCadastreSource.history`, keeps bbox + watched MMSIs in `ais/backfill/`,
and runs the same processor with `source=marinecadastre`,
`rights=noaa-planning-only`. January–June 2026 is available; Jul–Sep is expected
about mid-December 2026. NOAA's June 2026 FAQ limits use to "coastal and ocean
planning purposes" and forbids charging a fee for the data, so map and profile
queries for any paid surface filter this rights tag out in code. `fleet-ais.yml`
takes a dispatch input to backfill a month.

**MMSI matching** (`ais/match.py`): (1) registry MMSI (FCC/PSIX) with an
agreeing AIS call sign or name → `watched` at 0.9; (2) a broadcast name
matching a vessel alias with ship type 30/37/60/69 and length within 20% →
`candidate`; (3) positions inside the vessel's own port geofence on ≥ 3
distinct days → `watched` at ≥ `mmsi_auto`; anything weaker → `mmsi` review.
Disagreeing AIS statics (stale call signs, odd lengths) become `method=ais`
facts and never override registry values.

**Validation.** Label ≥ 30 trips across classes and ports in the admin
labelling view: time ranges marked drift, troll, transit or in-port, with a
basis. `python -m skippercast.fleet.ais validate` compares output to labels by
minutes and reports precision and recall for fishing (drift + troll) and per
type, with a confusion table. Labelled trips' raw positions are copied to
`ais/validation/` so thresholds can be re-tested later. Target before any
public use: fishing precision ≥ 0.8, recall ≥ 0.7. **Owner**: label, or review
and approve an agent-labelled set (`labeller` records who).

## 12. Worker API

**Job routes** (GitHub OIDC via `server/job-auth.ts`), scope
`{audiencePath: '/api/fleet/jobs', workflows: ['fleet-registry.yml',
'fleet-osint.yml', 'fleet-ais.yml', 'fleet-health.yml']}`; the workflows are
also added to `deployments/production.json` `scheduler.workflows`
(CODEOWNERS: **Owner** approval). Bodies ≤ 1 MB; D1 batches chunked under
D1's statement and bound-parameter limits.

| Route | Purpose |
| --- | --- |
| `GET /api/fleet/jobs/snapshot?region&cursor` | vessels, aliases, keys, pinned fields, decided reviews, offerings (paged) |
| `POST /api/fleet/jobs/registry` | registry operations |
| `GET`/`POST /api/fleet/jobs/watch` | watch list; match updates |
| `POST /api/fleet/jobs/activity` | replace-window trips/segments/events; aggregates |
| `POST /api/fleet/jobs/heartbeat` | heartbeat, hourly counters |
| `GET /api/fleet/jobs/labels` | labels for validation |
| `GET /api/fleet/jobs/health` | staleness booleans and ages only |

**Admin routes** (`requireAdmin`, 404 unless `FLEET_ENABLED`):
`GET /api/admin/fleet/reviews`, `POST /api/admin/fleet/reviews/:id`;
`GET /api/admin/fleet/vessels`, `GET|POST /api/admin/fleet/vessels/:id`
(admin facts, pin, `status`, `profile_status`),
`POST /api/admin/fleet/vessels/:id/link-advisor`;
`GET /api/admin/fleet/operators`, `POST /api/admin/fleet/operators/:id`,
`GET|POST /api/admin/fleet/operators/:id/outreach`,
`POST /api/admin/fleet/outreach/:id` (approve, discard, log as sent by owner);
`GET /api/admin/fleet/coverage`, `/ais/health`, `/clicks`;
`GET|POST /api/admin/fleet/labels`. A review decision (CF-30,
`server/fleet/admin/reviews.ts`) is `{action, ...}` stored canonically in
`decision_json`: `same-vessel` (merge, advisor-link; `vessel_id`, and for
advisor-link `boat_id`, which sets `advisor_boats.fleet_vessel_id`),
`new-vessel` (merge), `set-mmsi`/`reject-mmsi` (`mmsi`), `set-class`,
`set-status` (vanished, scope, change), `confirm` (change, fact-conflict) or
`dismiss` (status `dismissed`); `set-*` actions also write the admin fact and
pin. Admin facts carry `source_id = admin`, `source_url = admin:<users.id>`,
`method = admin`, confidence 1, rights `facts-only` and no `run_id`. Today `adminUser` in
`server/middleware/admin.ts` returns null while the advisor is off; CF-01
changes it to "advisor or fleet enabled", and each feature keeps its own check.

**Map routes** (`FLEET_MAP_ENABLED`, admin only in this plan):
`/api/fleet/map/filters`, `/events`, `/tracks`, `/heat` (section 14).

**Public** (`FLEET_ENABLED`): `/boats/<slug>` (section 13) and
`GET /go/<slug>?t=booking|website&p=profile|directory|map`. It redirects only
to the vessel's stored https URL (never a URL from the request), appends
`utm_source=skippercast&utm_medium=referral&utm_campaign=fleet-<region>&utm_content=<p>`
keeping existing `utm_*`, increments `fleet_link_clicks`, writes an Analytics
Engine point (slug, target, placement) when `ANALYTICS` is bound, and answers
302 with `Cache-Control: no-store`. Unknown slug, hidden profile, a vessel that is
not `active` or has a removal request, or no https URL → 404. Limited per IP by `PUBLIC_LIMITER`
(threat model § 10.1); `HEAD` is answered but not counted.

## 13. Admin UI and public profile

New hash routes in `web/admin/` (same patterns as `queue.tsx` and
`skippers.tsx`), shown when the session reports the fleet flag:

- **Fleet review** (`#fleet-review`): open items by kind; candidate facts beside
  the proposed vessel with the score and its parts; actions: same vessel, new
  vessel, set or reject MMSI, set class, mark vanished or active, dismiss.
- **Vessels** (`#fleet-vessels`, `#fleet-vessel/<id>`): filters (port, class,
  status, completeness, AIS); detail shows each resolved field with its winning
  fact, every fact with source link, method, confidence and history,
  offerings, aliases, changes, watch status and trips. Edits become `admin`
  facts and pin the field.
- **Operators and outreach** (`#fleet-operators`, `#fleet-operator/<id>`):
  contact status, consent status and scope (who and when), notes, drafts.
  Drafts stay drafts: approve, discard, or "log as sent by owner". Lead score
  0–100 from `catalog/fleet/lead-score.json` (defaults: landing-report trip
  volume 30%, reporting frequency 25%, social presence found on the operator's
  own site 25%, AIS seen in 30 days 20%), shown with its parts.
- **AIS health** (`#fleet-ais`): last message age, messages per minute,
  reconnects and drops (24 h), gaps over 10 minutes, uptime % for 7 and 30 days,
  last processor run, watch list size.
- **Coverage** (`#fleet-coverage`): boats by port and class; completeness by
  field group; % with MMSI and % seen in 30 days by port and class; sources per
  boat and single-source boats; run history.
- **Labelling** (`#fleet-trip/<id>`): segments on a small map with a speed
  strip; select a time range, label it, give the basis.

**Public profile.** `/boats/<slug>` stays one page
(`server/advisor/pages/boat.ts`); the route moves behind a gate that passes
when either flag is on. Lookup: `advisor_boats` by slug (with its
`fleet_vessel_id`), else `fleet_vessels` by slug with `status='active'` and
`profile_status='listed'`. With `FLEET_ENABLED` it adds: class, landing and
port, length, passengers, year, active offerings (price "as listed on <host>
on <date>"), booking and website links through `/go/`, business phone, photo
links with attribution (linked, not embedded) and a "Sources" list with dates.
It shows the Google aggregate rating and review count (never review text)
with the attribution Google's terms require ("Google" label and a link to the
place), only while the fact is within its 30-day refresh window; it shows no
AIS data, and only facts with display-compatible `rights` and confidence
≥ 0.6. The "Sources" list never renders an `admin:<users.id>` source URL
(no admin id or link reaches a public page): an admin fact is labelled
"SkipperCast". A registry-only profile is `noindex` until its
operator is `content-sharing` or `partner`. Advisor reports and photos render
as today.

As built (CF-33): the rules live in `server/fleet/display.ts`, shared with `/go/`.
A vessel is public only while `status='active' AND profile_status='listed'` and
`removal_requested_at` is null (so an admin unhiding a vessel after a removal
request does not re-publish it). `removal_requested_at` keeps a vessel unlisted
even if an admin sets `listed`, until the request is cleared; CF-31 must show
that state ([open-questions.md](open-questions.md) Q15). A fact is displayable when its `rights` are
`public-domain`, `facts-only`, `public-record` or `api-terms`, its confidence is
≥ 0.6, it is not superseded and its `method` is not `ais`. A resolved column
(`vessel_class`, `length_ft`, `passengers_max`, `year_built`, `phone_business`,
`website`, `booking_url`) renders only when a displayable fact for that field
carries the same value; links to booking and website also need plain https
(`displayableLink`). The page reads these fact fields: `landing` (string),
`photos[]` (`{url, attribution}`, linked with the credit), `reputation.google_rating`
and `reputation.google_reviews` (numbers, whose `source_url` must be the Google
Maps place URL, used as the attribution link; the window runs from
`retrieved_at`; the count needs the same place URL). Sources list hosts and dates
as text; an `admin:<id>` fact shows as "SkipperCast", never its id. An offering renders only with a displayable fact among its
`source_fact_ids_json`; the newest one gives "as listed on <host> on <date>".
`/go/` links use the fleet vessel's slug. A verified advisor boat linked through
`fleet_vessel_id` gains the registry cards after its own content; the vessel's
own slug then stays `noindex` and out of the sitemap. Advisor boats are read
only while the advisor is on; with only `FLEET_ENABLED` on, registry pages
render without the advisor's call to action and chat.

## 14. Map layers and filters

`dist/fleet-activity.js` exports `initFleetActivity(map, {onSelect, showMap})`,
modelled on `dist/commercial-ais.js`: one `L.layerGroup` per layer, toggles
`layer-fleet-events`, `layer-fleet-tracks`, `layer-fleet-heat` in
`dist/index.html` (shown only to an admin with `FLEET_MAP_ENABLED`), a status
line and a details card through `onSelect`; wired in `dist/app.js` with the
existing `optional(...)` guard.

| Layer | Drawing |
| --- | --- |
| Activity events | circles, radius ∝ √dwell (4–18 px), drift filled, troll ringed; card: boat, port, class, date, start/end, dwell, type, source and rights, and "Inferred from movement (speed and track shape). Not a confirmed fishing stop or catch." |
| Trip tracks | decoded polylines per segment coloured by kind (transit grey, drift and troll distinct, gap dashed) |
| Heat | aggregate cells as rectangles, opacity ∝ dwell; no new vendored library |

One filter card, applied server-side: boat, port, vessel class, trip type,
activity type, date range, season (year and part). Endpoints take `region,
bbox, from, to, vessel, port, class, trip_type, kind, season, season_part,
source`, return GeoJSON, and cap results (2,000 events; 300 trips; 5,000 heat
cells per page), paged with a `cursor`. Dates are the trip's local departure date. Aggregate cells hold
no vessel, port, class, trip type or source, so the heat layer lists those
filters in `meta.ignored` instead of applying them. On heat an omitted
`season_part` means the whole-season cells (`season_part` null, which the
aggregator always writes, § 5) and `season_part=all` every part; a cell without
dates is kept under a date filter and `from`/`to` is then listed in
`meta.ignored`. Tracks page by trip (`meta.trips`); a bbox drops segments after
the page is cut, so clients page on `meta.next`, never on feature counts. The
filters endpoint caps its vessel list at 500 and sets `truncated`. Every feature carries
`basis` and `rights`; `noaa-planning-only` rows are returned tagged
`planning_only` so a client can drop them (`server/fleet/map.ts`).

## 15. Presentation options (Part 3)

Ranked; picks marked. Only the admin views and the flagged profile are built.

- **Directory and profiles.** (1, **pick**) Registry boats listed on the
  existing `/ports/<id>` pages (name, class, trip types, from-price, `/go/`
  links), profiles at `/boats/<slug>`. (2) A separate filterable `/boats`
  directory. (3) Profiles only, reached from search and the map.
- **Activity in the map and planner.** (1, **pick**) Aggregates only: an
  "inferred from movement" heat layer at ≥ 1 km cells, ≥ 3 distinct vessels,
  ≥ 72 h delay, MarineCadastre-derived cells kept off paid tiers. (2) Plus
  per-trip tracks for opted-in operators. (3) Admin-only indefinitely.
- **Charter data in trip planning.** (1, **pick**) "Boats from your port this
  week": registry offerings and departures for the trip's port and date, with
  target species and recent landing counts, linked through `/go/`. (2)
  Inferred activity in spot ranking, after validation targets are met. (3)
  Nothing until booking exists.

## 16. Feature flags and deploy wiring

| Flag | Kind | Effect |
| --- | --- | --- |
| `FLEET_ENABLED` | Worker var | admin fleet views, job routes, registry data on `/boats`, `/go/` |
| `FLEET_MAP_ENABLED` | Worker var | map routes and layers (admin only) |
| `ENABLE_FLEET` | repo variable | the Hermes workflows run |

`server/fleet/settings.ts` parses the Worker vars (default off) like
`server/advisor/settings.ts`; `server/env.ts` declares them optional;
`scripts/wrangler_config.mjs` copies `FLEET_*` into `vars`;
`.github/workflows/deploy-cloudflare.yml` passes both from repository
variables. Job routes answer 404 while `FLEET_ENABLED` is off. Secrets
(**Owner**): `AISSTREAM_API_KEY`, `GOOGLE_PLACES_API_KEY`; the Claude token
lives on Hermes only. Flip order: `FLEET_ENABLED` → `ENABLE_FLEET` → listener
install → `FLEET_MAP_ENABLED`.

## 17. Privacy, data rights and repo hygiene

- **Public repo (D13).** Registry rows, OSINT output, manifests, positions,
  outreach and the CPRA response never enter git; they live in D1 or under
  `<FLEET_VAR>`. Fixtures are synthetic: 555-01XX phones, handles from
  `catalog/advisor/fixture-handles.json`, invented vessel names, MMSIs
  `999xxxxxx`.
- `scripts/check_repository.py` extends its advisor privacy scan to
  `tests/fixtures/fleet/` and `docs/plans/charter-fleet/`, tested in
  `tests/unit/test_check_repository.py`. `CONTRIBUTING.md` names fleet
  registry data, OSINT output, positions and outreach as private records.
- **People.** The boat and business only: no home addresses, personal phones,
  family details or personal accounts; no individual FCC licensee names;
  captains only as the operator publishes them.
- **NOAA MarineCadastre**: `noaa-planning-only`, off paid surfaces, cited. The
  repo currently labels it CC0; CF-06 records the FAQ conditions in
  `docs/legal/data-rights-register.md` and corrects the label in
  `docs/data-sources.md`.
- **TECK.net**: facts only; **Owner** asks before paid use.
- **Google Places**: `place_id` only beyond 30 days; attribution where shown.
- **aisstream.io**: no published terms; internal use only until written terms
  exist (**Owner**); no live per-vessel display.
- **Operators' wishes**: `hidden` and `do-not-contact` are honoured by every
  query; a removal request also deletes outreach rows.
- `docs/legal/threat-model.md` gains a fleet section (`/go/` redirect, job
  routes, admin data, outreach) in CF-06.

## 18. Monitoring and alerts

| Signal | Stored | Alert |
| --- | --- | --- |
| Listener heartbeat age, last message | `job_state` `fleet.ais.<region>.heartbeat` | `fleet-health.yml` (hourly, hosted) opens or updates an issue labelled `fleet-ais-stale` when either is older than 3 h, and closes it on recovery (the `feed-freshness.yml` pattern); runbook `docs/operations/runbooks/fleet-ais-down.md` |
| Processor last run | `job_state` `fleet.ais.<region>.processed` | same issue at > 3 h |
| Registry and OSINT runs | `fleet_runs` | failing workflow; health flags no `ok` registry run in 10 days |
| Uptime and gaps | `fleet_ais_hours` | AIS health page; fleet report |
| Daily summary | `scripts/ops_report.py` | one line: heartbeat age, 24 h messages, open fleet issue |

## 19. Monthly cost estimate

Target: $0 beyond the existing Cloudflare plan and Hermes (D16).

| Item | Monthly | Notes |
| --- | --- | --- |
| D1 storage and rows | $0 | registry ~50 MB; activity ~0.5 GB a year at 150 tracked boats; within the plan's included allowances |
| Worker requests | $0 | ~2,000 job calls a day |
| Hermes | $0 marginal | existing machine; listener < 512 MB |
| GitHub Actions | $0 | self-hosted; the hosted health check is free on a public repo |
| Claude (OSINT) | $0 marginal | owner's subscription; a full refresh is ~5–8 agent-hours |
| Google Places | $0 | ~420 lookups within free monthly calls; Text Search Pro $32/1k above it |
| aisstream.io, MarineCadastre | $0 | free |
| **Total** | **$0** | |

Paid options, each an **Owner** decision (nothing is bought):

| Option | Cost | Adds |
| --- | --- | --- |
| Datalastic history, one month | €199 (~$215) once | Jul–Oct 2026 tracks now instead of mid-December |
| Datalastic Experimenter | €569 (~$620)/month | licensed hourly polling, ~60 boats |
| Datalastic Developer Pro+ | €679 (~$740)/month | unlimited polling; candidate for licensed display |
| MarineTraffic API | ~$200–500/month (estimate) | licensed terrestrial data |
| Spire/Kpler satellite | ~$2,000–8,000/month (estimate) | offshore Class A on Baja trips only |
| Own receiver + AISHub | $250–400 once + ~$5/month | Central Coast latency, AISHub; nothing for SoCal or offshore |

**Actuals**: once live, the fleet report (CF-61) appends a monthly line to the
README status log with D1 storage and rows from Cloudflare's usage data, Places
calls, and paid items ("none"). **Owner**: confirm against invoices.

## 20. Risks and mitigations

| Risk | Mitigation |
| --- | --- |
| aisstream has no terms or SLA | internal use only; source interface; Datalastic quote ready; health alert |
| Low AIS coverage (six-packs; Central Coast boats 0 of 9 in the pilot) | coverage by port and class is a first-class metric; MMSI identified reported apart from "seen"; never infer from absence |
| Offshore blind spot past ~40–90 nm | `truncated` trips and `gap` segments; no claims about unseen water |
| Wrong MMSI (same-name pleasure boats) | three-stage match ending in geofence presence; weak matches reviewed |
| Misclassification | config thresholds, versioned output, labelled validation, "inferred from movement" wording |
| Source terms change or sites block us | rights tags, robots and off-limits checks every run, facts-only use |
| Personal data creeping in | validator policy, repo scan, entity-only licensees, admin hide and remove |
| Hermes down | hosted health check alerts; jobs resume from state; lost stream time shows in uptime |
| Self-hosted runner on a public repo | fleet workflows never trigger on `pull_request` |
| Subscription limits stall OSINT | resumable batches, capped parallelism, deterministic refreshes |
| D1 growth from tracks | simplification, encoded polylines, season-scoped queries; revisit at 2 GB |
| Overlap with Codex | fleet code in new files; shared files (`db/schema.ts`, `server/app.ts`, `dist/index.html`) touched by small tasks |

## 21. Adding a second region

Oregon needs only:

1. `regions/OR/fleet.json` with `status: "dry-run"`: ports (Brookings, Gold
   Beach, Port Orford, Bandon, Charleston, Winchester Bay, Florence, Newport,
   Depoe Bay, Garibaldi, Warrenton) with geofences; AIS bbox (about
   41.9–46.3°N, 125.5–123.7°W); agencies (ODFW charter licensing, USCG sectors
   Columbia River and North Bend, FCC state `OR`); bindings to the generic
   adapters (`fcc-uls` `state: OR`, `uscg-psix`, `teck-reports` on
   SportfishingReport's Oregon pages if present, `google-places`,
   `landing-pages` where a fleet page parses).
2. A state-specific adapter only for a source with its own format (an ODFW
   licence list, if one is obtainable).
3. A staging-only dry run: `python -m skippercast.fleet run --region OR --sink
   staging --steps discover,resolve,enrich-code,ingest` (or `fleet-registry.yml`
   with `sink=staging`). Output: `<FLEET_VAR>/staging/OR.sqlite` and
   `report.json` (boats by port and class, sources per boat). No D1 write and
   no Worker call; the `dry-run` status makes the WorkerSink refuse.
4. Promotion is `status: "active"` in its own PR after the owner reads the
   dry-run report.
