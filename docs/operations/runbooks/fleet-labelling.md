# Runbook: label trips for the AIS classifier's validation

**When:** after a MarineCadastre backfill month has run (`fleet-ais.yml` `backfill_month`), or when live trips need labels. The classifier needs at least 30 labelled trips (at least 10 pelagic, and at least 5 salmon trips in season) before anyone else sees a heat map ([graph.md N7](../../plans/charter-fleet/graph.md#n7--labelled-validation-set)).
**Owner:** the repository owner approves every agent-proposed label. An agent with a shell on the data runner runs the export and writes the proposals.
**Setup reference:** [design.md § 11 Validation](../../plans/charter-fleet/design.md#11-ais-processor), `src/skippercast/fleet/ais/label.py`, `src/skippercast/fleet/ais/validate.py`.

Track data stays on the runner. Exports, proposals, trip ids and times never enter the repository, an issue, a PR or a chat. Reports carry counts and scores only.

Unlabelled backfill positions are deleted 30 days after ingest (design.md § 5). Label each backfill month promptly; a labelled trip's positions are kept while its labels exist.

## 1. Export on the data runner

As the runner user, from the deployed revision:

```bash
sudo -iu runner
export SKIPPERCAST_FLEET_VAR="$HOME/.local/share/skippercast/fleet"
cd ~/.local/share/skippercast/app/current && . .venv/bin/activate
python -m skippercast.fleet.ais label export --region CA --source marinecadastre \
  --from 2026-01-01 --to 2026-01-31 --out labelling/2026-01
```

This writes one JSON file per trip to `$SKIPPERCAST_FLEET_VAR/CA/ais/labelling/2026-01/`, skipping trips the last sync listed as labelled (`validation/labels.json`, refreshed after every scheduled processor run). `--out` must stay under FLEET_VAR; the command refuses anything else, and anything in the checkout outside `var/`. Trips are derived with the processor's own steps, so their ids match the trips in D1.

Each file holds `trip_id`, the ports, the departure and return, the `window` labels must fall in, and `minutes`: one row a minute with the columns in `columns`:

| Column | Meaning |
| --- | --- |
| `t` | the fix's UTC time |
| `sog_kn` | speed over ground as reported, or null |
| `course_change_deg` | turn since the previous reported course (0 to 180) |
| `port_nm` | distance to the nearest port geofence, 0 inside one |
| `local_hour` | the region's local hour |
| `classifier_hint` | the classifier's current kind: **a hint, do not copy it as a label** |

## 2. Propose labels

A Large model reads the exports and writes `labelling/2026-01/proposals.json` next to them: a list with one entry per trip.

```json
[{"trip_id": "<32 hex>", "labeller": "agent:<name>",
  "labels": [{"started_at": "2026-01-14T15:02:00Z", "ended_at": "2026-01-14T15:40:00Z",
              "label": "drift-anchor", "basis": "speed under 1 kn for 38 minutes, course wandering, 9 nm out"}]}]
```

- Labels are `in-port`, `transit`, `drift-anchor`, `troll-slow` or `troll-pelagic`. Each one covers at least a minute inside the trip's `window`, and labels on one trip never overlap. A trip has at most 200 labels.
- `basis` (2 to 500 characters) states what the judgement rests on: speed, turning, distance offshore, time of day.
- Judge each stretch from the track. Never derive labels from `classifier_hint`: copied labels would score the classifier against itself. A stretch the track cannot settle stays unlabelled.
- Choose trips across ports and classes until the counts in step 5 are met. Which 2026 salmon openings count as "in season" is the owner's decision (asked on [#570](https://github.com/Grahammmm/skippercast/issues/570)).

Check the file on the runner. Errors name entries by position, never by trip id:

```bash
python -m skippercast.fleet.ais label import "$SKIPPERCAST_FLEET_VAR/CA/ais/labelling/2026-01/proposals.json" --dry-run
```

## 3. Import

`label import` (without `--dry-run`) posts each trip to `POST /api/fleet/jobs/labels`, which replaces that agent's labels on the trip. The route needs a `fleet-ais.yml` job identity, so the import runs through the workflow: dispatch it with `label_import` set to the proposals path under FLEET_VAR. Nothing is posted if any entry fails the checks. (The route and the input come with N7b.)

## 4. Owner approval

In the admin labelling view (`#fleet-trip/<id>`), the owner reviews each trip awaiting approval against its track and either approves it, which rewrites its labels with the owner's id as `labeller` and keeps the agent's name in `basis`, or deletes the labels that are wrong. Approved labels count as `admin` labels.

## 5. Score

Dispatch `fleet-ais.yml` with `validate` checked. The run syncs the labels and their raw copies and writes the report to the run summary: trips scored, labels by labeller kind, fishing precision and recall overall and per mode against the target (0.8 and 0.7), the labelled fishing minutes the classifier called transit (`transit_lost`), and trips by dominant labelled mode, departure port and month (`coverage`). Score approved labels only with `python -m skippercast.fleet.ais validate --region CA --labeller admin`.

Copy the counts and scores, and nothing else, to the README Status log and [#570](https://github.com/Grahammmm/skippercast/issues/570).
