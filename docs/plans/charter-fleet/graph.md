# Charter fleet: the run as a node graph

Status: plan (2026-10-10). This file turns the remaining charter-fleet work
(CF-62, Prompt A [#468](https://github.com/Grahammmm/skippercast/issues/468),
Prompt B [#469](https://github.com/Grahammmm/skippercast/issues/469)) into
nine nodes. Every node has exactly **one input, one output and one check**. A
node is done only when its check passes; the result goes in the node's PR body
and as a dated line in the [README](README.md) Status log.

The check is deterministic: a test, a script exit code, a count threshold, or
"owner approves" where only the owner may decide. Output from a smaller model
never passes a node without that check ([AGENTS.md](../../../AGENTS.md)
"Delegate by weight").

Model tiers (AGENTS.md "Delegate by weight"): **Orchestrator** plans, gates and
decides; **Large** (Opus) builds and reviews, and a builder never reviews its
own work; **Mid** (Sonnet) does rebases and merge stewarding; **Small** (Haiku)
does grunt work (fan-out lookups, polling CI, extracting fields, running test
commands). A unit that fails twice moves up one tier.

## Hard rules (every node)

- Public sources only. D7 off-limits sources stay off-limits (FishingBooker,
  FareHarbor, Xola, FishDope, Fish City, Instagram, Facebook); MarineTraffic and
  VesselFinder stay not-cleared (Q16).
- No outreach, purchases, sign-ups or logged-in scraping. Paid options get a
  quote and stop at an owner step.
- Nothing private is committed: this is a public repository. Registry rows,
  OSINT output, manifests, positions and outreach notes stay in D1 or under the
  fleet `var/` directory ([design § 17](design.md#17-privacy-data-rights-and-repo-hygiene)).
  PR bodies and the Status log carry counts only.
- Every gate result is recorded in the node's PR and in the README Status log.

## Owner's product decisions (apply to nodes 5–7)

- **Transit is dropped** from every view and from D1 geometry, except offshore
  pelagic trolling, which counts as fishing (#469 D20, D22).
- **Specific fishing locations are admin-only** (owner view behind
  `FLEET_MAP_ENABLED`).
- **The public site shows only a general heat map**: no boats, pins, tracks,
  ports or classes (#469 D21).

## Nodes

### N1 · Layer 0 baseline · **done**

- Purpose: record what has run, what has not and what is failing before any new work.
- Input: public Actions run metadata and logs for the fleet workflows on `main` at `cb0b0ed`.
- Output: README Status log entry dated 2026-10-10, PR [#509](https://github.com/Grahammmm/skippercast/pull/509) (merged as `7982e39`).
- Check: `PYTHONPATH=src python -m pytest -q -x -m "not gis" -k fleet` exit 0 (453 passed), `node --test tests/test_fleet_*.mjs` exit 0 (130 pass), `python scripts/check_repository.py` exit 0. **Passed.**
- Runs: Orchestrator (read), Small (log extraction).
- Depends on: nothing. Reuses: CF-61 report shape, CF-45 health route.

### N2 · Defect triage and fix (#339, #340, #345)

- Purpose: stop the registry distorting itself before it is measured, and populate the lead-score and schedule evidence that N4 needs.
- Input: issues [#339](https://github.com/Grahammmm/skippercast/issues/339), [#340](https://github.com/Grahammmm/skippercast/issues/340), [#345](https://github.com/Grahammmm/skippercast/issues/345).
- Output: one PR on `claude/cf-defects` closing all three (fix option 1 for #339 and #340 unless the code says otherwise; split into one PR per issue if over ~400 lines, each with the same check scoped to its issue).
- Check: the three regression tests the issues name pass: a failed binding in a `partial` run retires no offering it reported (`tests/unit/test_fleet_refresh.py`); a `teck-reports` fact wins `name` over `uscg-psix` (`tests/unit/test_fleet_resolve.py`); a synthetic trip plus landing report writes one `fleet_trip_reports` row; and `pytest -m "not gis" -k fleet` and `node --test tests/test_fleet_*.mjs` exit 0.
- Runs: Large builds, a second Large reviews.
- Depends on: N1. Reuses: CF-17 (`refresh.py`, `resolve.py`, `catalog/fleet/resolver.json`), CF-03 (`fleet_trip_reports`), CF-32 (`server/fleet/leadscore.ts`).

### N3 · Registry completeness

- Purpose: every for-hire boat in California in the registry, measured against the CPFV licence count, with the gap named.
- Input: `regions/CA/fleet.json` source bindings plus a per-port gap list from `python -m skippercast.fleet report --region CA`.
- Output: registry rows in D1 via `--sink worker` (not git), and a counts-only completeness table in the PR and Status log.
- Check: (a) every Haiku fan-out result passes `python -m skippercast.fleet validate-profile` (100%, else the batch is discarded and re-run one tier up); (b) zero facts from D7 hosts (host scan of the run's `report.json`); (c) every fact has a non-empty `source_url`; (d) active boats ≥ 0.9 × the ~420-boat statewide estimate, by port and class, from `report --region CA`. Below (d), the PR names the gap and the closing source (CPRA list, Google Places, operator sites, landing and report sites).
- Runs: Small fan-out over public sources (one Haiku per port and source, results as candidate JSON only); Orchestrator gates; Large reviews any code change.
- Depends on: N2. Reuses: CF-12 to CF-17 adapters and `run`, CF-20/21 OSINT runner, CF-61 report, `fleet-registry.yml`, `fleet-osint.yml`.

### N4 · AIS match coverage (strong-evidence gate)

- Purpose: give each registry boat an MMSI only on strong evidence.
- Input: the N3 registry and the AIS watch rows (`GET /api/fleet/jobs/watch`), with a live listener (see "AIS health" below) or the MarineCadastre January–June 2026 backfill.
- Output: `fleet_ais_watch` rows with status `watched`, method and confidence, and `watch.json` for the listener (the hand-off to N5); counts by method in the PR.
- Strong evidence (design § 11, #468 D18): (1) a registry MMSI (FCC ULS or PSIX) whose AIS call sign or name agrees (`fcc-uls`), confidence 0.9; (2) an admin-pinned MMSI (`admin`), 1.0; (3) positions in the boat's own port geofence on ≥ 3 distinct days of 30, with a known ship type 30/37/60/69 and known length within 20%, at ≥ `mmsi_auto` (0.85, `geofence-presence`), never when the boat already has a registry MMSI or two boats match; (4) once built, `schedule-correlation` with ≥ 5 matched trip days over ≥ 2 weeks and no rival vessel. Anything weaker is an `mmsi` review, never `watched`.
- Check: every `watched` row has confidence ≥ 0.85 and a method in {`fcc-uls`, `geofence-presence`, `admin`, `schedule-correlation`} (`call-sign` and `ais-static-name` are candidate-only) (assertion over the watch endpoint, exit 0); `pytest tests/unit/test_fleet_match.py` passes; for `schedule-correlation`, precision on the January–June 2026 history ≥ 0.9 against landing-report days, reported with the false-match count.
- Runs: Large builds `schedule-correlation`; Orchestrator gates; Small polls runs.
- Depends on: N3, and the listener healthy (#508). Reuses: CF-46 (`ais/match.py`, `server/fleet/watch.ts`), CF-47 backfill, CF-45 processor.

### N5 · Activity classifier

- Purpose: turn watched boats' positions into fishing modes and drop transit.
- Input: positions of `watched` MMSIs (raw store on Hermes, or MarineCadastre backfill), thresholds in `regions/CA/fleet.json` `thresholds.activity`.
- Output: a PR adding the modes `drift-anchor`, `troll-slow`, `troll-pelagic` and `uncertain`, all thresholds in `fleet.json`, a bumped `classifier_version`, and transit stored as statistics only.
- Check: `pytest tests/unit/test_fleet_classify.py` passes on synthetic tracks: harbor shuffle → no trip; 1 kn drift 30 min → `drift-anchor`; 2.5 kn salmon troll → `troll-slow`; straight 7 kn offshore search with paddy stops → one `troll-pelagic` run; straight 7 kn inshore run → transit; night drift offshore → fishing; changing any threshold changes `classifier_version`; transit segments carry no geometry.
- Runs: Large researches and builds (`references/classification.md` with sources), a second Large reviews.
- Depends on: N4 (needs watched boats to reprocess; code can start in parallel on synthetic tracks). Reuses: CF-43 (`segment.py`, `classify.py`), CF-44 events, CF-45 processor, CF-47 backfill.

### N6 · Heat-map aggregate

- Purpose: a general heat map for the public and an unsuppressed one for the owner.
- Input: N5 fishing events, `thresholds.aggregate` in `regions/CA/fleet.json`.
- Output: a PR with per-mode aggregates (1 km bottom, coarser pelagic), a public heat route and the owner layers (fishing segments only).
- Check: a test (`node --test tests/test_fleet_public_heat.mjs`, new) proves the public route returns only cell geometry, mode, season or month, dwell and distinct-vessel count: no `vessel`, `mmsi`, `port`, `class`, `trip`, `event` or `track` key in any response, no route under it returns events or tracks, every cell has ≥ 3 distinct vessels, nothing newer than 72 h, and `noaa-planning-only` cells are absent from paid surfaces; plus `pytest tests/unit/test_fleet_events.py` and `node --test tests/test_fleet_map.mjs` pass.
- Runs: Large builds, a second Large reviews.
- Depends on: N5. Reuses: CF-44 (`aggregate/grid.py`, privacy knobs), CF-50 (`server/fleet/map.ts`), CF-51 (`dist/fleet-activity.js`).

### N7 · Labelled validation set

- Purpose: prove the classifier before anyone else sees a heat map.
- Input: trips from the admin labelling view (CF-48), January–June 2026 history and live data.
- Output: ≥ 30 labelled trips (≥ 10 pelagic, ≥ 5 salmon in season) and the `validate` report, counts and scores only in the PR.
- Check: **owner approves** the set (or labels it), recorded in `labeller`; then `python -m skippercast.fleet.ais validate` reports fishing precision ≥ 0.8 and recall ≥ 0.7, overall and per mode, and the fishing minutes transit discarding would have lost.
- Runs: Large proposes labels; owner approves; Small runs `validate`.
- Depends on: N5 (N6 public go-live waits on N7 and Q1). Reuses: CF-48 (`validate.py`, `server/fleet/admin/labels.ts`).

### N8 · Skill packaging

- Purpose: make the run repeatable, unattended, on Hermes.
- Input: N2–N7 merged, issues #468 and #469 (which superseded #459), the format of `skills/skippercast-build-coastal-map/`.
- Output: a PR adding `skills/skippercast-charter-fleet/SKILL.md` (modes from #468 `cycle`/`discover`/`match`/`review`/`report` and #469 `cycle`/`backfill`/`reprocess`/`validate`/`tune`/`report`, guardrails, stop conditions, end-of-run report) and `skills/skippercast-charter-fleet/agents/openai.yaml`.
- Check: `python scripts/check_repository.py` exit 0; the SKILL.md front matter has `name` and `description`; every command the skill names exists (`python -m skippercast.fleet --help` and `python -m skippercast.fleet.ais` list them); a separate Large reviewer approves.
- Runs: Large writes, a second Large reviews.
- Depends on: N7. Reuses: CF-61 report, the runbooks `fleet-registry.md`, `fleet-osint.md`, `fleet-ais-down.md`.

### N9 · Skill dry run

- Purpose: show the skill runs end to end without touching production data.
- Input: the N8 skill, `regions/OR/fleet.json` (`dry-run`) and the staging sink.
- Output: a counts-only dry-run report in the PR and Status log.
- Check: `skill cycle --region OR` exits 0 on staging; `--sink worker` is refused for OR (existing CF-60 test); `git status --porcelain` is empty after the run (nothing private written into the checkout); the report has no phone, email, handle or operator URL (`check_repository.py` scan).
- Runs: Mid runs it; Small polls; Orchestrator gates.
- Depends on: N8. Reuses: CF-60 dry run, CF-61 report.

## Dependency diagram

```
N1 (done) ─► N2 ─► N3 ─► N4 ─► N5 ─► N6
                          ▲      └─► N7 ─► N8 ─► N9
                 #508 fix ┘                 ▲
                 (blocks N4, N5, N6)   N6 ──┘
N6 public go-live also waits on N7 and Q1 (owner).
```

## Known AIS health problem (#508)

*Fleet AIS health* opened [#508](https://github.com/Grahammmm/skippercast/issues/508)
on 2026-10-10: heartbeat, last message and processor all older than 3 hours.
While it is open:

- **N4** cannot gain live geofence or `schedule-correlation` evidence; it can
  run only on the January–June 2026 MarineCadastre backfill.
- **N5** can be built and tested on synthetic tracks but has no live tracks to
  reprocess.
- **N6** has no live events to aggregate, and the coverage mask would be wrong.

The fix is the owner-step restart in
[`fleet-ais-down.md`](../../operations/runbooks/fleet-ais-down.md); #508 closes
itself on recovery.

## Owner-only steps

Each becomes an `owner-task` + `charter-fleet` issue linked from
[#437](https://github.com/Grahammmm/skippercast/issues/437) and
[#458](https://github.com/Grahammmm/skippercast/issues/458). Not created here.

1. Restart the AIS listener per `fleet-ais-down.md` (#508; blocks N4–N6).
2. Tick the #458 boxes already done (flags, aisstream key, listener install, OSINT token).
3. Create the Google Places key and add `GOOGLE_PLACES_API_KEY` (N3).
4. Send the CDFW CPRA request for the CPFV list (text in [open-questions.md](open-questions.md) Appendix; N3).
5. Approve or label the validation set (N7).
6. Review the fleet workflows (CODEOWNERS) for any changed workflow (N2–N8).
7. Q16: MarineTraffic and VesselFinder terms review (N3, N4).
8. Q1: aisstream.io written terms (N6 public go-live).
9. Paid AIS history decision (Datalastic, Q6) versus free NOAA backfill (N4, N7).
10. Flip `FLEET_MAP_ENABLED` for the owner view (N6).
11. Approve the public heat map going live (N6, after N7 and Q1).
12. Create a private R2 bucket for the raw-archive backup, if wanted (#469 D20).
