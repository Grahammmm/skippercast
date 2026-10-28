"""Known gaps in a fleet run (T17): adapters that are not implemented, unsupported, unavailable or empty.

A discovery binding whose adapter is registered but not built (``ais-static``),
whose pages the adapter does not read (a ``layout`` skip), whose fetches were
all refused (robots fail-closed on a 503, the USCG PSIX outage) or that listed
nothing is a known gap: the run is ``complete-with-known-gaps``, never
``partial``, and only an adapter that raised makes it ``partial``. A gap that
means the source did not list its boats keeps ``discover.json`` ``complete``
false, so refresh never counts its boats towards ``vanished``. Shares the
synthetic fleet of ``test_fleet_ingest``; every name and URL is invented.
"""
from dataclasses import replace
import json
import tempfile
import unittest

from skippercast.fleet import cli, report
from skippercast.fleet.adapters import REGISTRY
from skippercast.fleet.config import Binding
from skippercast.fleet.ingest import GAP_STATUSES
from tests.unit.test_fleet_ingest import REGION, Pipeline, Source, baseline, day

KNOWN = "complete-with-known-gaps"


class Net:
    """The one FleetSession attribute discover reads: the run's refused or failed fetches."""

    def __init__(self):
        self.skips = []


class Skipping(Source):
    """An adapter that lists nothing and records why on ``ctx.net.skips``, as the real adapters do."""

    def __init__(self, *reasons):
        super().__init__()
        self.reasons = reasons

    def discover(self, binding, ctx):
        for reason in self.reasons:
            ctx.net.skips.append({"url": f"https://{binding.id}.example.com/fleet", "reason": reason, "detail": ""})
        return []


def gap_pipeline(tmp, **extra):
    """The two-source pipeline plus ``ais-static`` (no adapter) and one binding per extra fake adapter."""
    p = Pipeline(tmp)
    bindings = [Binding("ais-static", "ais-static", True, {"sources": ["aisstream"]}, "internal-only")]
    for ident, adapter in extra.items():
        bindings.append(Binding(ident, ident, True, {}, "facts-only"))
        p.extra[ident] = adapter
    p.region, p.net = replace(REGION, sources=REGION.sources + tuple(bindings)), Net()
    return p


def discovered(p, run_id):
    return json.loads((p.var / "CA" / "runs" / run_id / "discover.json").read_text())


class KnownGapTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_ais_static_is_registered_but_not_implemented(self):
        self.assertIn("ais-static", REGISTRY)
        self.assertIsNone(REGISTRY["ais-static"])

    def test_known_gaps_make_the_run_complete_with_known_gaps(self):
        p = gap_pipeline(self.tmp.name, **{"landing-layout": Skipping("layout"),
                                           "landing-robots": Skipping("robots", "fetch-error"),
                                           "landing-empty": Source()})
        result = p.run(day(0), *baseline(day(0)))
        self.assertEqual(result["status"], KNOWN, result)
        self.assertEqual(result["steps"]["discover"]["status"], KNOWN)
        self.assertEqual(result["steps"]["discover"]["counts"]["failed"], 0)
        self.assertEqual(result["steps"]["discover"]["counts"]["gaps"], 4)
        gaps = {"ais-static": "not-implemented", "landing-empty": "empty", "landing-layout": "unsupported",
                "landing-robots": "unavailable"}
        self.assertEqual(result["known_gaps"], gaps)
        self.assertTrue(set(gaps.values()) <= set(GAP_STATUSES))
        doc = discovered(p, result["run_id"])
        self.assertEqual(doc["gaps"], gaps)
        self.assertEqual(doc["bindings"]["ais-static"],
                         {"status": "not-implemented",
                          "reason": "adapter 'ais-static' is registered but not implemented yet"})
        self.assertEqual(doc["bindings"]["landing-robots"],
                         {"status": "unavailable", "candidates": 0, "skips": {"fetch-error": 1, "robots": 1}})
        self.assertEqual(doc["bindings"]["landing-layout"]["skips"], {"layout": 1})
        self.assertEqual(doc["bindings"]["landing-pages"], {"status": "ok", "candidates": 4})
        self.assertFalse(doc["complete"], "unsupported and unavailable sources did not list their boats")
        saved = json.loads((p.var / "CA" / "runs" / result["run_id"] / "report.json").read_text())
        self.assertEqual((saved["status"], saved["known_gaps"]), (KNOWN, gaps))
        # The Worker's fleet_runs vocabulary is ok/partial/failed: the step row is ok, its counts carry the gaps.
        runs = {r["step"]: r for r in p.rows("fleet_runs") if r["id"].startswith(result["run_id"])}
        self.assertEqual({step: r["status"] for step, r in runs.items()}, {step: "ok" for step in cli.PIPELINE})
        self.assertEqual(json.loads(runs["discover"]["counts_json"])["gaps"], 4)

    def test_only_not_implemented_and_empty_keep_discovery_complete(self):
        p = gap_pipeline(self.tmp.name, **{"landing-empty": Source()})
        result = p.run(day(0), *baseline(day(0)))
        self.assertEqual(result["status"], KNOWN)
        self.assertTrue(discovered(p, result["run_id"])["complete"])

    def test_a_skip_on_a_source_that_listed_boats_is_counted_not_a_gap(self):
        p = gap_pipeline(self.tmp.name)
        p.landing = PartlySkipping()
        result = p.run(day(0), *baseline(day(0)))
        doc = discovered(p, result["run_id"])
        self.assertEqual(doc["bindings"]["landing-pages"], {"status": "ok", "candidates": 4, "skips": {"layout": 1}})
        self.assertEqual(doc["gaps"], {"ais-static": "not-implemented"})
        # SP1308: the skipped page may have listed boats too, so discovery is not complete
        # (refresh must not count an unlisted vessel towards vanished on this run).
        self.assertFalse(doc["complete"], "a binding that skipped work did not list all its boats")

    def test_an_adapter_that_raises_still_makes_the_run_partial(self):
        p = gap_pipeline(self.tmp.name, **{"landing-layout": Skipping("layout")})
        p.psix.error = RuntimeError("PsixFormatError: PSIX PSIXInspections sheet is empty")
        result = p.run(day(0), *baseline(day(0)))
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["steps"]["discover"]["status"], "partial")
        self.assertEqual(result["known_gaps"], {"ais-static": "not-implemented", "landing-layout": "unsupported"})
        runs = {r["step"]: r["status"] for r in p.rows("fleet_runs") if r["id"].startswith(result["run_id"])}
        self.assertEqual(runs["discover"], "partial")

    def test_no_gap_is_ok(self):
        result = Pipeline(self.tmp.name).run(day(0), *baseline(day(0)))
        self.assertEqual((result["status"], result["known_gaps"]), ("ok", {}))

    def test_an_unavailable_source_never_counts_towards_vanished(self):
        """The PSIX outage shape: every fetch refused, nothing listed; its boats are not marked vanished."""
        p = gap_pipeline(self.tmp.name)
        p.run(day(0), *baseline(day(0)))
        p.psix = Skipping("robots")
        for n in (20, 40, 60, 80):
            result = p.run(day(n), baseline(day(n))[0])
            self.assertEqual(result["status"], KNOWN)
            self.assertEqual(result["known_gaps"]["uscg-psix"], "unavailable")
        self.assertEqual([c["kind"] for c in p.rows("fleet_changes") if c["kind"] == "vanished"], [])
        self.assertEqual([r for r in p.rows("fleet_reviews") if r["kind"] == "vanished"], [])


class PartlySkipping(Source):
    """landing-pages listing its boats with one boat page in a layout it does not read."""

    def discover(self, binding, ctx):
        ctx.net.skips.append({"url": "https://landing.example.com/boat/odd", "reason": "layout", "detail": ""})
        return list(self.candidates)


class ReportStatusTests(unittest.TestCase):
    def test_the_fleet_report_counts_runs_complete_with_known_gaps(self):
        rows = [{"id": f"20261004T06000{i}Z-aaaaaa", "created_at": "2026-10-04T06:00:00Z", "status": status,
                 "failed_steps": []} for i, status in enumerate(("ok", KNOWN, KNOWN, "partial"))]
        runs = report.runs_summary(rows, now_ms=1_791_200_000_000)
        self.assertEqual((runs["runs"], runs["ok"], runs["complete_with_known_gaps"], runs["partial"]), (4, 1, 2, 1))
        self.assertIn(KNOWN, report.RUN_STATUSES)


if __name__ == "__main__":
    unittest.main()
