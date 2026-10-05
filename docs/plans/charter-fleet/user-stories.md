# User stories: charter fleet registry and AIS activity map

Who the feature serves and what each must be able to do. Each story has an
acceptance note, a scope (**MVP** is built in this plan; **Later** is
designed for, not built) and the [dev-plan.md](dev-plan.md) phase that
delivers it. [design.md](design.md) holds the technical detail.

Phases and task ids (CF-xx) follow dev-plan.md:

| Phase | Theme | Tasks |
| --- | --- | --- |
| P0 | Foundations: flags, router, job scope, admin gate, `fleet_` tables, region config and loader, profile schema and repo-hygiene scan, ADR and data rights | CF-01 – CF-06 |
| P1 | Registry pipeline: CLI and sinks, job API, adapters, entity resolution, enrichment, ingest and refresh, weekly workflow | CF-10 – CF-18 |
| P2 | OSINT agent step: manifests, profile ingest, headless runner | CF-20 – CF-21 |
| P3 | Admin, profile, outreach, links: review and vessel admin, operators and outreach, public boat profile, `/go/`, coverage page | CF-30 – CF-35 |
| P4 | AIS: store, listener, segmentation and classification, events and aggregates, processor and health, MMSI matching, backfill, labelling and validation | CF-40 – CF-48 |
| P5 | Map: map API and client layers (admin, behind `FLEET_MAP_ENABLED`) | CF-50 – CF-51 |
| P6 | Second region and reporting: Oregon dry run, fleet report, full California run | CF-60 – CF-62 |

If dev-plan.md changes its phases, it wins; fix this file.

Ground rules for every story: flags `FLEET_ENABLED` / `FLEET_MAP_ENABLED`
default off; every displayed fact has a source and date; movement labels say
"inferred from movement", never "confirmed fishing"; only business
information the operator publishes.

## Angler

**US-A1. Find boats by port.** As an angler, I want a list of the charter
and party boats that sail from a port, grouped by vessel class, so that I can
see my options without knowing landing names.
- Acceptance: `/boats?port=<port-id>` (or the port page section chosen in
  design.md § 15. Presentation options) lists every `active` registry vessel
  for that port with name, class, landing, trip types and a link to its profile.
  Ports come from `fleet.json`. Vanished or sold boats are not listed.
- Later: design.md § 15 builds only the admin views and the flagged profile;
  the registry data comes from P1 (CF-17).

**US-A2. See a trustworthy boat profile.** As an angler, I want one page per
boat with its specs, trips, prices, contact and booking link, so that I can
decide whether to book it.
- Acceptance: the existing `/boats/<slug>` page renders registry data (D5). Each fact shows its date and source link.
  Photos are attributed links, never rehosted. Ratings show only aggregate
  and count, with Google attribution.
- MVP. Phase P3 (CF-33).

**US-A3. Book through the operator.** As an angler, I want the "Book" button
to take me straight to the operator's own booking page, so that I deal with
the boat, not a middleman.
- Acceptance: the button points at `/go/<vessel-slug>`, which 302s to the
  booking URL with UTM tags and increments that day's `fleet_link_clicks`
  counter (no IP, user id or cookie). Without a booking URL, show phone or website.
- MVP. Phase P3 (CF-34).

**US-A4. Recent catches on the profile.** As an angler, I want to see the
boat's recent fish counts on its profile, so that I can judge how it is
fishing.
- Acceptance: counts come from the landing-reports pipeline and Text
  Advisor reports, joined through vessel aliases (D5), each linked to its
  source. No reports in 30 days is stated.
- MVP; display reuses the Text Advisor boat-page section.
  Phase P1 (alias join, CF-15/CF-17), P3 (display, CF-33).

**US-A5. Filter the directory.** As an angler, I want to filter boats by
vessel class (six-pack, party, long range), trip type and target species, so
that I find a half-day rockfish trip or a private six-pack quickly.
- Acceptance: filters use registry fields; species uses offering season
  months.
- Later (UI follows the design.md § 15. Presentation options choice).
  Phase P1 (data).

**US-A6. "Boats from my port targeting X this week."** As an angler using the
trip planner, I want to see which boats from my chosen port are running trips
for my target species this week, so that I can plan around a real departure.
- Acceptance: up to five boats whose offerings list the species in season
  and whose latest report or schedule is within 14 days, each with a `/go/`
  link; none shown if none qualify; never ranked by AIS activity.
- Later. Data from P1; no dev-plan task yet for the API or UI (dev-plan.md
  § Backlog; design.md § 15. Presentation options).

**US-A7. Where the fleet fishes (aggregate).** As an angler, I want to see a
seasonal heat map of where charter boats spend fishing time, so that I
understand which grounds the fleet works by month.
- Acceptance: public only after the owner decides
  ([open-questions.md](open-questions.md) § Q8. Public exposure of per-vessel
  tracks); when public it uses the aggregate module with its privacy knobs
  on (minimum distinct vessels, delay, cell size) and the existing "not a
  catch or hotspot claim" copy. No per-vessel tracks publicly.
- Later. Phase P4 builds the aggregate module and its knobs (CF-44), P5 the
  admin map (CF-50, CF-51).

## Captain and operator

**US-C1. Appear accurately.** As a captain, I want my boat listed with the
right name, landing, trips and contact, so that anglers find me and nothing
wrong is said about my business.
- Acceptance: when sources disagree (the pilot found conflicts on 11 of 21
  boats), the config resolver rule picks the value and admin shows the
  conflict. Admin- or operator-supplied facts outrank scraped ones.
- MVP. Phase P1.

**US-C2. Correct my listing.** As an operator, I want to tell SkipperCast that
a fact is wrong (sold boat, new price, new captain) and see it fixed, so that
I am not misrepresented.
- Acceptance: a "Report a correction" link opens a short form (or the Text
  Advisor chat) that creates a review item with field, proposed value and
  business contact. Approval writes a fact with `method = operator` that
  supersedes the old one; history is kept.
- MVP (queue), Later (public form). Phase P3 (queue: CF-30, CF-31); the
  form has no dev-plan task yet (dev-plan.md § Backlog).

**US-C3. Hide or remove my listing.** As an operator, I want to ask for my
boat to be hidden, so that I am not listed if I don't want to be.
- Acceptance: admin can set a vessel to `hidden`; hidden vessels disappear
  from public pages, `/go/` links return 404, and refresh runs never unhide
  them. The request date is recorded in
  `fleet_vessels.removal_requested_at`.
- MVP. Phase P0 (column, CF-02), P3 (CF-30 sets `hidden`; CF-33 and CF-34
  honour it).

**US-C4. Opt in to be shown by name on the activity map.** As a captain, I
want to choose whether my boat's tracks and stops are shown under its name,
so that my fishing spots stay mine unless I decide otherwise.
- Acceptance: `fleet_vessels.map_display_consent` (`none`, `aggregate`,
  `named`), default `none` (design.md § 5. Data model). Public layers, when
  they exist, include a vessel by name only at `named`. Admin views ignore
  it.
- MVP for the field; Later for any public use. Phase P0 (column, CF-02);
  honoured by any public layer task once Q8 is decided.

**US-C5. Share catch logs by text.** As a captain registered with the Text
Advisor, I want my texted counts and photos credited to my registry boat, so
that my profile, reports and social posts all point to the same boat.
- Acceptance: `advisor_boats.fleet_vessel_id` is set through the review queue
  when a skipper registers; the registry profile shows advisor reports for
  that vessel. A registered boat never creates a duplicate vessel.
- MVP. Phase P0 (column, CF-02), P1 (review item, CF-15), P3 (link action
  CF-30, display CF-33).

**US-C6. See what SkipperCast sends me.** As an operator, I want a monthly
count of clicks SkipperCast sent to my booking page, so that I can see the
value of being listed and sharing reports.
- Acceptance: admin sees a per-vessel monthly click report (US-S5); the
  CSV export and sending it to operators are Later.
- MVP (admin view), Later (CSV export, sent to operators). Phase P3 (CF-34);
  the export has no dev-plan task yet (dev-plan.md § Backlog).

**US-C7. Only business information.** As a captain, I want SkipperCast to
hold only what my business publishes, so that my home, family and personal
accounts are never collected.
- Acceptance: the OSINT contract forbids personal fields; `ingest` rejects
  unknown fields; individual FCC licensee names are never stored; the
  repository check fails on real contacts in fixtures or plan docs.
- MVP. Phase P0 (checks, CF-05), P2 (agent contract, CF-21).

## Owner as admin

**US-O1. Review queue.** As the owner, I want one queue for low-confidence
merges, MMSI matches, renames, Text Advisor boat links and operator
corrections, so that I resolve ambiguity in one place.
- Acceptance: `/admin/#fleet-review` shows candidates side by side with
  evidence and approve, reject or merge actions. Each decision writes a fact
  or alias with `method = admin`; re-runs never re-ask a decided question
  without new evidence.
- MVP. Phase P1 (review items, CF-15), P3 (admin API and UI, CF-30,
  CF-31).

**US-O2. Coverage dashboard.** As the owner, I want boats per port and vessel
class, the sources that found each boat, single-source boats, field
completeness and AIS coverage, so that I know how complete the registry is.
- Acceptance: `/admin/#fleet-coverage` shows per region, port and class:
  boats, % with MMSI, % seen in AIS in 30 days, single-source count and field
  completeness by group; numbers match a fixture query.
- MVP. Phase P3 (CF-35); the AIS columns fill once P4 runs.

**US-O3. AIS health.** As the owner, I want to know when the AIS listener has
stopped, so that a gap does not silently cost me a week of tracks.
- Acceptance: the listener writes a heartbeat; the processor pushes it to
  `job_state`; the admin health page shows last message time, messages per
  hour and gaps over 30 minutes; the existing ops-report path alerts the
  owner when the heartbeat is older than 3 hours.
- MVP. Phase P4 (CF-45; health view CF-35).

**US-O4. Re-run a region.** As the owner, I want to re-run any pipeline step
for a region id, so that a fixed adapter or a new threshold reprocesses
everything without duplicates.
- Acceptance: every step accepts `--region` (AIS also `--from/--to`);
  running twice changes nothing; a `workflow_dispatch` input runs it on the
  data runner.
- MVP. Phases P1, P2 and P4 (CF-17, CF-18, CF-21, CF-45, CF-47).

**US-O5. Add a region by config.** As the owner, I want to add Oregon with a
`fleet.json` and optional adapters only, so that the system grows state by
state.
- Acceptance: a dry-run discovery for `OR` writes to a staging store only and
  produces a coverage report; no file under `src/` mentions a California
  port, agency or bounding box.
- MVP (dry run). Phase P6 (CF-60).

**US-O6. Activity map for admin.** As the owner, I want to see every
inferred fishing stop, every trip track and a heat map, filtered by boat,
port, class, trip type, activity type, date range and season, so that I
learn where the fleet goes before deciding what to publish.
- Acceptance: three layers behind `FLEET_MAP_ENABLED`, admin-visible while
  off for the public; filters change the API query; event popups show boat,
  trip, dwell, type and "inferred from movement".
- MVP. Phase P5 (CF-50, CF-51).

**US-O7. Validate the classifier.** As the owner, I want precision and recall
of the fishing classifier against hand-labelled trips, so that I know how far
to trust the map.
- Acceptance: a labelling view or file format for at least 30 trips; a
  report command prints precision and recall per activity type; thresholds
  come from `fleet.json` and a change re-runs history.
- MVP. Phase P4 (CF-48: labelling view and report).

**US-O8. Fact history.** As the owner, I want to see every value a field has
had, with source and date, so that I can explain any displayed fact and spot
renames and sales.
- Acceptance: the admin vessel view lists facts per field, newest first.
- MVP. Phase P3 (CF-30, CF-31).

**US-O9. Cost tracking.** As the owner, I want a monthly line of what the
feature costs, so that it stays near zero.
- Acceptance: the fleet report lists each service and its monthly cost.
- MVP. Phase P6 (CF-61).

## Owner as content and sales

**US-S1. Outreach pipeline.** As the owner, I want each operator's contact
status (not contacted, drafted, contacted, replied, partner, declined) with
notes and dates, so that I can recruit captains to share photos and catch
logs.
- Acceptance: `/admin/#fleet-operators` lists operators with status, last
  touch, next step and notes; notes stay in D1, never in the repo.
- MVP. Phase P3 (CF-32).

**US-S2. Lead score.** As the owner, I want operators ranked by trip volume,
social activity, reporting frequency and AIS presence, so that I contact the
most valuable ones first.
- Acceptance: weights in config; admin shows the score, its components and
  which inputs were missing (counted as zero).
- MVP. Phase P3 (CF-32).

**US-S3. Consent status.** As the owner, I want partnership, content-sharing
and map-display consent recorded per operator with the date and how it was
given, so that I never post or show anything they did not agree to.
- Acceptance: consent fields on `fleet_operators` mirror the Text Advisor's
  consent pattern (timestamp plus the message or note that gave it, and a
  `consent_revoked_at`); revoking takes effect on the next request, with no deploy.
- MVP. Phase P0 (columns, CF-02), P3 (UI, CF-32).

**US-S4. Draft, never send.** As the owner, I want outreach messages drafted
for me but sent only by me, so that nothing reaches a partner without my
approval.
- Acceptance: drafts are stored with status `draft`; there is no code path
  that sends an outreach message; a test asserts it.
- MVP. Phase P3 (CF-32).

**US-S5. Click reports.** As the owner, I want clicks per boat per month by
UTM source and page, so that I can show operators the traffic we send.
- Acceptance: the admin clicks endpoint (CF-34); Analytics Engine is
  written too when `ENABLE_ANALYTICS` is on. A CSV export is Later.
- MVP (endpoint), Later (CSV export). Phase P3 (CF-34); the export has no
  dev-plan task yet (dev-plan.md § Backlog).

## Future booking

Booking is out of scope. These stories say what the model must not preclude.

**US-B1. Offerings as dated, priced records.** As a future booking feature, I
want each trip offering stored as a record with trip type, departure time,
duration, price per spot or charter, capacity, season and the dates it was
seen, so that availability and booking can attach to it later.
- Acceptance: `fleet_offerings` is its own table keyed to the vessel; price
  changes are new facts, not overwrites.
- MVP (data model). Phase P0 (CF-02).

**US-B2. Replaceable outbound link.** As a future booking feature, I want the
`/go/<slug>` route to be the single place anglers leave for a booking, so
that it can later route to an in-house checkout without changing pages.
- Acceptance: every booking button in the app uses `/go/`; no page links to
  an operator's booking URL directly.
- MVP. Phase P3 (CF-33, CF-34).

**US-B3. Operator accounts.** As a future operator portal, I want operators
to be linkable to a signed-in `users` row, so that they can later manage
their own listing and bookings.
- Acceptance: `fleet_operators` has a nullable `user_id`; nothing assumes
  operators are anonymous.
- MVP (column only). Phase P0 (CF-02; design.md § 5. Data model).

**US-B4. Trip-to-report pairing.** As a future catch-log feature, I want a
boat's AIS trip on a date joinable to its catch report for that date, so
that species can be attributed to that trip's fishing stops.
- Acceptance: `fleet_trips` carries `vessel_id` and `local_date`; the
  join to reports by (vessel, date) is documented in design.md § 5. Data
  model (`fleet_trip_reports`) and covered
  by one fixture test; species attribution itself is not built.
- MVP (schema and join test), Later (attribution). Phase P0 (schema,
  CF-03), P4 (trips, CF-45).

## Story-to-phase map

| Story | Scope | Phase (tasks) |
| --- | --- | --- |
| US-A1 directory by port | Later | P1 data (CF-17) |
| US-A2 boat profile | MVP | P3 (CF-33) |
| US-A3 book via `/go/` | MVP | P3 (CF-34) |
| US-A4 recent catches | MVP | P1 (CF-15, CF-17), P3 (CF-33) |
| US-A5 directory filters | Later | P1 (data) |
| US-A6 trip-planner boats | Later | P1 (data); no task yet (Backlog) |
| US-A7 public heat map | Later | P4 (CF-44 knobs), P5 (CF-50, CF-51 admin map) |
| US-C1 accurate listing | MVP | P1 (CF-15, CF-17) |
| US-C2 corrections | MVP queue, Later form | P3 (CF-30, CF-31); form: Backlog |
| US-C3 hide listing | MVP | P0 (CF-02), P3 (CF-30, CF-33, CF-34) |
| US-C4 map display consent | MVP field, Later use | P0 (CF-02) |
| US-C5 Text Advisor link | MVP | P0 (CF-02), P1 (CF-15), P3 (CF-30, CF-33) |
| US-C6 traffic report | MVP view, Later CSV and send | P3 (CF-34); CSV: Backlog |
| US-C7 business info only | MVP | P0 (CF-05), P2 (CF-21) |
| US-O1 review queue | MVP | P1 (CF-15), P3 (CF-30, CF-31) |
| US-O2 coverage dashboard | MVP | P3 (CF-35) |
| US-O3 AIS health | MVP | P4 (CF-45), P3 (CF-35 view) |
| US-O4 re-run a region | MVP | P1, P2, P4 (CF-17, CF-18, CF-21, CF-45, CF-47) |
| US-O5 add a region | MVP (dry run) | P6 (CF-60) |
| US-O6 admin activity map | MVP | P5 (CF-50, CF-51) |
| US-O7 classifier validation | MVP | P4 (CF-48) |
| US-O8 fact history | MVP | P3 (CF-30, CF-31) |
| US-O9 cost tracking | MVP | P6 (CF-61) |
| US-S1 outreach pipeline | MVP | P3 (CF-32) |
| US-S2 lead score | MVP | P3 (CF-32) |
| US-S3 consent status | MVP | P0 (CF-02), P3 (CF-32) |
| US-S4 draft never send | MVP | P3 (CF-32) |
| US-S5 click reports | MVP endpoint, Later CSV | P3 (CF-34); CSV: Backlog |
| US-B1 offerings as records | MVP (model) | P0 (CF-02) |
| US-B2 single outbound route | MVP | P3 (CF-33, CF-34) |
| US-B3 operator accounts | MVP (column) | P0 (CF-02) |
| US-B4 trip-to-report join | MVP (schema), Later | P0 (CF-03), P4 (CF-45) |
