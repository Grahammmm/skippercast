"""A Worker vanished review needs two eligible misses in the Worker registry."""
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from skippercast.fleet import cli
from skippercast.fleet.adapters.base import RunContext
from skippercast.fleet.runs import Run
from skippercast.fleet.sinks import SinkError, SqliteSink
from tests.unit.test_fleet_ingest import REGION, Source, landing


class SyntheticWorker(SqliteSink):
    """Worker sink identity with a separate, entirely local registry."""

    name = "worker"
    reject_ingest = False

    def apply(self, operations):
        if self.reject_ingest and any(op["op"] == "vessel.upsert" for op in operations):
            raise SinkError("synthetic ingest rejection")
        return super().apply(operations)


class VanishedHistoryTests(unittest.TestCase):
    def test_only_successful_listing_ingest_to_this_sink_advances_history(self):
        # Each control gets its own history: otherwise one false miss can mask the rest.
        for control in ("staging", "discover-only", "zero-bindings", "empty-listings", "failed-ingest", "failed-retry",
                        "discovery-retry-without-ingest"):
            with self.subTest(control=control), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                region = replace(REGION, thresholds={**REGION.thresholds, "refresh": {
                    "vanished_after_runs": 2, "vanished_after_days": 45,
                }})

                def cycle(at, steps, *, seen=False, staging=False, zero=False, empty=False, fail=False):
                    run_id = at.replace("-", "").replace(":", "") + "-000001"
                    run = Run(region.id, run_id, var=root)
                    ctx = RunContext(replace(region, sources=()) if zero else region,
                                     SimpleNamespace(skips=[]), run.dir, lambda: at)
                    source = Source()
                    if not empty:
                        source.candidates = [landing("Present Example", at)]
                    if seen:
                        source.candidates.append(landing("Missing Example", at))
                    sink_type = SqliteSink if staging else SyntheticWorker
                    sink = sink_type(root / f"{sink_type.name}.sqlite", region.id, run.id)
                    try:
                        if isinstance(sink, SyntheticWorker):
                            sink.reject_ingest = fail
                        return cli.execute(run, ctx, sink, steps, {
                            "discover": {"adapters": {"landing-pages": source, "uscg-psix": Source()}},
                        })
                    finally:
                        sink.close()

                cycle("2026-08-01T00:00:00Z", ("discover", "ingest"), seen=True)
                rehearsal = "2026-09-10T00:00:00Z"
                if control in ("failed-ingest", "failed-retry"):
                    if control == "failed-retry":
                        cycle(rehearsal, ("discover", "ingest"))
                    with self.assertRaisesRegex(SinkError, "synthetic ingest rejection"):
                        cycle(rehearsal, ("discover", "ingest"), fail=True)
                elif control == "discovery-retry-without-ingest":
                    cycle(rehearsal, ("discover", "ingest"), zero=True)
                    cycle(rehearsal, ("discover",))
                else:
                    cycle(rehearsal, ("discover",) if control == "discover-only" else ("discover", "ingest"),
                          staging=control == "staging", zero=control == "zero-bindings", empty=control == "empty-listings")

                # One eligible miss plus any ineligible control must not open a review.
                first = cycle("2026-09-20T00:00:00Z", ("discover", "ingest", "refresh"))
                self.assertEqual(first["steps"]["refresh"]["counts"]["vanished_reviews"], 0)
                if control in ("staging", "failed-ingest", "failed-retry"):
                    # Pre-apply snapshots also cannot authorize a Worker refresh by themselves.
                    replay = cycle(rehearsal, ("refresh",))
                    self.assertEqual(replay["steps"]["refresh"]["counts"]["no_ingest"], 1)
                # A zero-binding ingest isn't the second miss even as the current run.
                zero = cycle("2026-09-25T00:00:00Z", ("discover", "ingest", "refresh"), zero=True)
                self.assertEqual(zero["steps"]["refresh"]["counts"]["vanished_reviews"], 0)
                # A second eligible miss does open a review, but does not change status.
                second = cycle("2026-09-30T00:00:00Z", ("discover", "ingest", "refresh"))
                self.assertEqual(second["steps"]["refresh"]["counts"]["vanished_reviews"], 1)
                with closing(SyntheticWorker(root / "worker.sqlite", region.id, "20260930T000000Z-000001").db) as db:
                    self.assertEqual(db.execute("SELECT status FROM fleet_vessels WHERE name=?", ("Missing Example",)).fetchone()[0],
                                     "active")
                    self.assertEqual(db.execute("SELECT status FROM fleet_reviews WHERE kind='vanished'").fetchall(),
                                     [("open",)])
