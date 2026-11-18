"""F07-01 / F08-01: history may be replaced only over proven-complete source coverage (offline fixture).

Missing observations are not evidence that no trip happened. The Worker deletes every trip of a replace window before
inserting the derived ones, so a window is safe only if every UTC day the processor reads for it is in the store, with
its positions table, and was ingested whole. ``process.push_trips`` reads ``[from - LEAD_MS, min(to + longest open
trip, settled))``; ``coverage_gaps`` derives that span and inspects the store itself (never backfill's own counts), so
it also sees a lead/return-context day the backfill never asked for, a day retention emptied, and a day file with no
positions table. A day file with its manifest and an empty positions table is a certified-complete empty day.

Three kinds of test, kept apart:

* the safety contract, ``verdict``: with gaps, a destructive window or lost history is unsafe, and a no-window
  outcome that keeps the prior trip is safe (proven on hand-built observations, so it cannot pass vacuously);
* coverage controls on the live backfill: the valid control and the certified-empty control have no gaps, each
  affected control has exactly its expected gap, and ``verdict`` agrees with what the live code did;
* the baseline receipt: ``test_baseline_receipt_is_reported`` prints, per affected case, whether the live code sent a
  window or lost history at this head. It is reported, never asserted as the desired outcome, so these tests stay
  green when a guard lands.

Everything is synthetic; no Worker, network or real data.
"""
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import sqlite3

from skippercast.fleet.ais import backfill as bf
from skippercast.fleet.ais import process
from skippercast.fleet.ais.sources.marinecadastre import MarineCadastreSource
from skippercast.http import FakeSession
from tests.unit.test_fleet_backfill import (DAY, MMSI, NEXT, REGION, T0, BackfillTestCase, day_file, day_url, zst)
from tests.unit.test_fleet_process import FakeWorker

UTC = timezone.utc
NOW = T0 + 200 * 86_400_000
PRIOR = {"id": "trip-prior", "mmsi": str(MMSI), "source": bf.SOURCE_ID, "departed_at": "2026-06-20T17:00:00Z"}
SENT_WINDOW = {"mmsi": str(MMSI), "from": "2026-06-20T07:00:00Z", "to": "2026-06-21T07:00:00Z"}


def _utc_day(ms):
    return datetime.fromtimestamp(ms / 1000, UTC).date()


def required_days(start_ms, end_ms, region, now_ms):
    """The UTC days ``push_trips`` reads for a departure window ``[start, end)``: an hour of lead, the longest open trip."""
    longest = int(max(region.thresholds["activity"]["max_open_trip_hours"].values()) * process.HOUR)
    read_end = min(end_ms + longest, now_ms - process.SETTLE_MS)
    first, last = _utc_day(start_ms - process.LEAD_MS), _utc_day(read_end - 1)
    return [first + timedelta(days=k) for k in range((last - first).days + 1)]


def coverage_gaps(store, days):
    """``{day: reason}`` for every required day the store cannot vouch for; ``{}`` means proven complete."""
    gaps = {}
    for day in days:
        path = store.day_path(day)
        if not path.exists():
            gaps[day.isoformat()] = "no-file"
            continue
        with closing(sqlite3.connect(path)) as conn:
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        if "positions" not in tables:
            gaps[day.isoformat()] = "absent-table"
        elif not bf._manifest_path(store, day).exists():   # retention removes it with the positions it emptied
            gaps[day.isoformat()] = "partly-retained"
    return gaps


@dataclass(frozen=True)
class Observation:
    gaps: dict            # required day -> reason, read from the store
    windows: tuple        # replace windows sent to the Worker
    prior_survived: bool  # the pre-existing trip is still stored afterwards


def verdict(obs):
    """The contract: with any gap, no destructive window and no lost history. Returns ``(detected, safe)``."""
    detected = bool(obs.gaps)
    safe = not detected or (not obs.windows and obs.prior_survived)
    return detected, safe


class SafetyContractTests(BackfillTestCase):
    """``verdict`` on hand-built observations: it must flag the unsafe outcome and clear the compliant one."""

    def test_unsafe_replacement_over_a_gap_is_detected(self):
        for reason in ("no-file", "partly-retained", "absent-table"):
            gaps = {"2026-06-22": reason}
            self.assertEqual(verdict(Observation(gaps, (SENT_WINDOW,), prior_survived=False)), (True, False), reason)
            self.assertEqual(verdict(Observation(gaps, (SENT_WINDOW,), prior_survived=True)), (True, False),
                             "a window over a gap is unsafe even before the Worker deletes anything")
            self.assertEqual(verdict(Observation(gaps, (), prior_survived=False)), (True, False),
                             "lost history is unsafe whatever was sent")

    def test_no_window_outcome_that_keeps_history_is_safe(self):
        self.assertEqual(verdict(Observation({"2026-06-22": "no-file"}, (), prior_survived=True)), (True, True))

    def test_complete_coverage_may_replace(self):
        self.assertEqual(verdict(Observation({}, (SENT_WINDOW,), prior_survived=False)), (False, True))
        self.assertEqual(verdict(Observation({}, (), prior_survived=True)), (False, True))

    def test_required_days_include_lead_and_return_context(self):
        start, end = bf.window_ms(DAY, DAY, REGION.timezone)
        days = required_days(start, end, REGION, NOW)
        self.assertEqual(days[:2], [DAY, NEXT], "the requested Pacific day touches two UTC days")
        self.assertGreater(len(days), 2, "the tail of a trip departing late in the window needs later days")
        midnight = round(datetime(2026, 6, 21, tzinfo=UTC).timestamp() * 1000)
        self.assertEqual(required_days(midnight, midnight + 3_600_000, REGION, NOW)[0], DAY,
                         "an hour of lead before a window that starts at UTC midnight needs the day before")
        settled = T0 + process.SETTLE_MS + 1
        self.assertEqual(required_days(T0, T0 + 3_600_000, REGION, settled), [DAY], "unsettled positions need no later day")


class CoverageControlTests(BackfillTestCase):
    """The live backfill against synthetic archives, one case per coverage state."""

    def observe(self, requested=None, *, context="complete", prior=True):
        """Backfill 2026-06-20 with ``requested`` day files; ``context`` is the state of the later context days."""
        start, end = bf.window_ms(DAY, DAY, REGION.timezone)
        days = required_days(start, end, REGION, NOW)
        context_days = [d for d in days if d not in (DAY, NEXT)]
        routes = {day_url(DAY): day_file(), day_url(NEXT): zst([]), **(requested or {})}
        routes.update({day_url(d): zst([]) for d in context_days})
        source = MarineCadastreSource(session=FakeSession(routes), workdir=self.store.root / "staging")
        bbox = bf.bbox_of(REGION.ais)
        if context != "no-file":
            for day in context_days:
                bf.ingest_day(source, self.store, day, bbox, {MMSI}, now_ms=NOW)
        for day in context_days:
            if context == "partly-retained":   # retention emptied the positions and removed the manifest
                with closing(sqlite3.connect(self.store.day_path(day))) as conn, conn:
                    conn.execute("DELETE FROM positions")
                bf._manifest_path(self.store, day).unlink()
            elif context == "absent-table":
                with closing(sqlite3.connect(self.store.day_path(day))) as conn, conn:
                    conn.execute("DROP TABLE positions")
        worker = FakeWorker()
        if prior:
            worker.stored = {PRIOR["id"]: dict(PRIOR)}
        counts = bf.backfill(REGION, worker, first=DAY, last=DAY, root=self.root, source=source, now_ms=NOW)
        windows = tuple(w for body in worker.posts("activity", "replace") for w in body["replace"])
        survived = PRIOR["id"] in getattr(worker, "stored", {})
        return Observation(coverage_gaps(self.store, days), windows, survived), counts, days

    def check(self, obs, expected_gaps):
        """The exact expected gaps are detected, and the verdict agrees with what the live code did."""
        self.assertEqual(obs.gaps, expected_gaps)
        detected, safe = verdict(obs)
        self.assertEqual(detected, bool(expected_gaps), "the control detects exactly the planted gap")
        self.assertEqual(safe, (not obs.windows and obs.prior_survived) if expected_gaps else True)

    def test_valid_control_complete_input_may_replace_history(self):
        obs, counts, _ = self.observe()
        self.assertEqual((counts["missing"], counts["failed"]), ([], []))
        self.check(obs, {})
        self.assertTrue(obs.windows)
        self.assertFalse(obs.prior_survived, "a proven-complete window replaces the prior trip with the derived one")

    def test_complete_empty_interval_may_replace_its_window(self):
        obs, counts, _ = self.observe({day_url(DAY): zst([])}, prior=False)
        self.assertEqual((counts["missing"], counts["failed"]), ([], []))
        self.check(obs, {})
        self.assertTrue(obs.windows, "a certified-complete empty interval stays representable")

    def test_unpublished_requested_day_is_a_gap(self):
        obs, counts, _ = self.observe({day_url(NEXT): (404, b"")})
        self.assertEqual(counts["missing"], ["2026-06-21"])
        self.check(obs, {"2026-06-21": "no-file"})

    def test_corrupt_requested_day_is_a_gap(self):
        whole = day_file()
        obs, counts, _ = self.observe({day_url(DAY): whole[:len(whole) // 2]})
        self.assertEqual([f["day"] for f in counts["failed"]], ["2026-06-20"])
        self.check(obs, {"2026-06-20": "no-file"})

    def test_missing_return_context_day_is_a_gap(self):
        obs, counts, days = self.observe(context="no-file")
        self.assertEqual((counts["missing"], counts["failed"]), ([], []), "the backfill itself saw nothing wrong")
        self.check(obs, {d.isoformat(): "no-file" for d in days if d not in (DAY, NEXT)})

    def test_partly_retained_context_day_is_a_gap(self):
        obs, _, days = self.observe(context="partly-retained")
        self.check(obs, {d.isoformat(): "partly-retained" for d in days if d not in (DAY, NEXT)})

    def test_absent_positions_table_is_a_gap(self):
        obs, _, days = self.observe(context="absent-table")
        self.check(obs, {d.isoformat(): "absent-table" for d in days if d not in (DAY, NEXT)})

    def test_baseline_receipt_is_reported(self):
        """Report, per affected case, what the live code did at this head; a receipt, not a requirement."""
        cases = {"unpublished": {"requested": {day_url(NEXT): (404, b"")}}, "no-file": {"context": "no-file"},
                 "partly-retained": {"context": "partly-retained"}, "absent-table": {"context": "absent-table"}}
        receipt = {}
        for name, options in cases.items():
            with self.subTest(name):
                self.setUp()
                obs, _, _ = self.observe(**options)
                detected, safe = verdict(obs)
                self.assertTrue(detected, "the negative control must plant a gap")
                receipt[name] = {"windows": len(obs.windows), "prior_survived": obs.prior_survived, "safe": safe}
        print("F07-01 baseline receipt:", receipt)
