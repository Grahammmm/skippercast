# Schedule evidence collector

This private CA collector captures current facts from the `landing-pages` bindings in `regions/CA/fleet.json` and reads the existing AIS summaries/raw store without modifying them. It is separate from the registry schedule and the 30-minute AIS processor/listener.

## Install the recurring collector

From the isolated, reviewed task worktree on AgentOrange:

```bash
scripts/fleet/install_schedule_evidence.sh CA
systemctl --user list-timers --all --no-pager | grep skippercast-schedule-evidence
```

The user timer starts its first service after two minutes and then repeats every 12 hours. Each service run has a 15-minute hard timeout, a 20-page global cap, and a nonblocking SQLite lock. It is sequential, so it never has more than one active source host. It uses the existing fleet Python runtime and the existing conditional HTTP cache at `~/.local/share/skippercast/fleet/CA/http-cache`.

Do not enable another scheduler for this collector. The timer is user-scoped and requires no `sudo`. The installer writes only its service/timer units and private output/cache directories; it does not modify the AIS listener, credentials, SSH configuration, network policy or GitHub workflows.

## One bounded run

```bash
SKIPPERCAST_FLEET_VAR="$HOME/.local/share/skippercast/fleet" \
SKIPPERCAST_HTTP_CACHE="$HOME/.local/share/skippercast/fleet/CA/http-cache" \
  "$HOME/.local/share/skippercast/app/current/.venv/bin/python" \
  scripts/fleet/schedule_evidence.py --region CA --max-pages 20 --deadline-seconds 900
```

The private database is `~/.local/share/skippercast/fleet/CA/schedule-evidence/evidence.sqlite3`, with directory mode `0700` and file mode `0600`. It contains schedule revisions, source access/hash checks, and AIS identity-candidate summaries. No page body, image, coordinate, load/seat count, contact detail or fishing label is stored there. Raw AIS is read only for event/receipt times; the collector stores counts and gaps, not locations.

## Review the count-only result

The collector prints run/page/trip/revision/assessment counts only. Never query and paste source rows, names, MMSIs, call signs, precise windows, or IDs into chat, GitHub or PRs. Use the database only on AgentOrange. A successful status means the collector completed its bounded work; per-source skips and schedule absence remain unknown, not cancellation.

## Boundaries and recovery

- `skippercast-fleet-registry` owns the registry and all watch-list decisions.
- `skippercast-fleet-activity` owns AIS processing, backfills and fishing-classifier validation.
- A scheduled row is intent; a catch/report page is reported operation; AIS is received observation. No category alone establishes passengers or fishing.
- AIS static fields are self-reported. The existing fleet registry includes FCC ULS and USCG PSIX adapters, but this evidence collector has not integrated their results. A one-sector PSIX check through the existing adapter returned an HTTP status error on 2026-10-12; the export is currently unavailable to this collector, and no result is not a mismatch. Earlier FCC source review found the weekly file download returned 403 to HEAD and was about 41.75 MB; no rows were validated for this database. Do not bypass either access response. VIVS access is restricted to authorized federal/state law-enforcement users.
- Official record enrichment remains separate from schedule operation and does not block the schedule collector. When an official source is reachable under existing policy, retain only allowlisted vessel facts with source version/retrieval provenance; never store owner/contact fields or approve identity automatically.
- Missing source rows do not create cancellations. Only explicit status markers bound to a unique boat, offering, departure date and departure time are saved as cancellation/substitution evidence; ambiguous or date-only matches stay unassigned.
- If a page changes layout, preserve the last successful observations, mark the fetch/layout status, and escalate for deterministic parser review. Do not use an LLM to guess the new layout.
- A lock conflict exits as `skipped-locked`; leave the active collector alone. A failed run is recorded with a generic error class. Inspect user journal locally; do not copy private logs elsewhere.
- Before retiring the worktree, update the unit to a reviewed, pinned code path and verify one scheduled run after that update.

## Raw reception coverage

A file's presence does not prove its database or tables were readable. Each AIS candidate reception summary reports the expected, readable, missing and unreadable UTC partition days over the full observation window and departure-day window, with one inclusive buffer day before and after their combined UTC bounds. Both positions and discovery must finish reading before a day's matching observations count. A missing table, corrupt/locked database or invalid matching receipt date holds that day; error text and raw rows are not retained. Missing buffer or future days keep the summary partial.

`raw-window-readable` and `raw-window-readable-empty` require every scanned day to be readable. `raw-window-partial` retains counts from complete readable days only; `raw-window-unreadable`, `raw-window-not-retained` and `raw-store-unavailable` distinguish the other holds. `coverage_complete` and `messages_complete` explicitly mark whether counts cover the scan. Zero messages with either flag false is an unknown or incomplete observation, never evidence of vessel absence or an unperformed trip. Receipt gaps describe observed messages only. Existing private assessment JSON is retained; no migration or rewrite is performed.
