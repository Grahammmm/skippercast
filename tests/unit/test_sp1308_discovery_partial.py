"""SP-13-v2 A1-A4: synthetic discovery receipts, never an operational sink.

No process-wide environment changes or hooks at import time: the acceptance
bootstrap owns its isolated child guards. Ordinary unittest discovery is inert.
"""
from copy import deepcopy
import itertools
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from skippercast.fleet import ingest, ops
from skippercast.fleet.adapters.base import Candidate, RunContext
from skippercast.fleet.refresh import detect, discovery_history
from skippercast.fleet.resolve import Snapshot

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "sp1308_discovery_partial"
AT = "2026-10-05T09:47:00Z"
LAYOUT = {"url": "https://fleet.example.com/synthetic/unread-page", "reason": "layout"}
CASE_MAP = {
    "A1": ["RegressionTests.test_primary_regression", "RegressionTests.test_healthy_control"],
    "A2": ["DiscoveryTests.test_mixed_success_order_and_skip_reasons",
           "DiscoveryTests.test_existing_outcomes_and_gap_summary",
           "DiscoveryTests.test_all_success_empty_and_no_skip_collection",
           "DiscoveryTests.test_preexisting_skips_do_not_belong_to_this_run",
           "DiscoveryTests.test_scout_report_fields_are_preserved"],
    "A3": ["HistoryTests.test_partial_current_run_cannot_finish_vanished_threshold",
           "HistoryTests.test_partial_historical_run_does_not_count"],
    "A4": ["RegressionTests.test_primary_regression", "RegressionTests.test_healthy_control"],
}


class Source:
    kind = "discover"

    def __init__(self, candidates=(), skips=(), error=None, report=None):
        self.candidates, self.skips, self.error = candidates, skips, error
        self.report = report or {}

    def discover(self, binding, ctx):
        if self.skips:
            ctx.net.skips.extend(deepcopy(self.skips))
        if self.error:
            raise self.error
        return list(self.candidates)


class SyntheticCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="sp1308-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.payload = json.loads((FIXTURES / "candidate.json").read_text(encoding="utf-8"))
        self.candidate = ingest.candidate_from_dict(self.payload)
        self.sequence = 0

    def discover(self, sources, *, net=True, previous=(), bindings=None):
        self.sequence += 1
        run_dir = self.root / f"discovery-{self.sequence}"
        run_dir.mkdir()
        if bindings is None:
            bindings = tuple(SimpleNamespace(id=key, adapter=key, params={}) for key in sources)
        region = SimpleNamespace(id="CA", enabled_sources=lambda: bindings)
        context = RunContext(region, SimpleNamespace(skips=list(previous)) if net else None, run_dir, lambda: AT)
        # discover has no need for a sink. A None sink makes accidental use fail.
        result = ingest.discover(context, None, adapters=sources)
        doc = json.loads((run_dir / "discover.json").read_text(encoding="utf-8"))
        rows = [json.loads(line) for line in (run_dir / "candidates.jsonl").read_text(encoding="utf-8").splitlines()]
        return result, doc, rows


class RegressionTests(SyntheticCase):
    def test_primary_regression(self):
        result, doc, rows = self.discover({"synthetic-primary": Source([self.candidate], [LAYOUT])})
        self.assertEqual(rows, [self.payload])
        self.assertEqual(result, {"candidates": 1, "bindings": 1, "failed": 0, "gaps": 0})
        self.assertEqual(doc["bindings"], {"synthetic-primary": {
            "status": "ok", "candidates": 1, "skips": {"layout": 1}}})
        self.assertEqual(doc["gaps"], {})
        # This specific semantic assertion is the sole expected baseline failure.
        self.assertIs(doc["complete"], False, "A1: usable candidate plus skipped layout is incomplete")

    def test_healthy_control(self):
        result, doc, rows = self.discover({"synthetic-primary": Source([self.candidate])})
        self.assertEqual(rows, [self.payload])
        self.assertEqual(result, {"candidates": 1, "bindings": 1, "failed": 0, "gaps": 0})
        self.assertEqual(doc, {"at": ops.iso(AT, "at"), "complete": True,
                               "bindings": {"synthetic-primary": {"status": "ok", "candidates": 1}}, "gaps": {}})


class DiscoveryTests(SyntheticCase):
    def test_mixed_success_order_and_skip_reasons(self):
        other = Candidate("uscg-psix", "Second Synthetic Example", record_id="synthetic-second")
        for reason in ("layout", "unsupported-list", "robots", "budget", "http-503", "", None, "new-reason"):
            for order in itertools.permutations(("synthetic-partial", "synthetic-whole")):
                with self.subTest(reason=reason, order=order):
                    sources = {"synthetic-partial": Source([self.candidate], [{"reason": reason}, {"reason": reason}]),
                               "synthetic-whole": Source([other])}
                    result, doc, rows = self.discover({key: sources[key] for key in order})
                    expected_rows = {"synthetic-partial": self.payload, "synthetic-whole": other.as_dict()}
                    self.assertEqual(rows, [expected_rows[key] for key in order])
                    self.assertIs(doc["complete"], False)
                    self.assertEqual(doc["bindings"], {
                        "synthetic-partial": {"status": "ok", "candidates": 1, "skips": {reason or "unknown": 2}},
                        "synthetic-whole": {"status": "ok", "candidates": 1}})
                    self.assertEqual(doc["gaps"], {})
                    self.assertEqual(result, {"candidates": 2, "bindings": 2, "failed": 0, "gaps": 0})

    def test_existing_outcomes_and_gap_summary(self):
        cases = (
            ("synthetic-empty", Source(), {"status": "empty", "candidates": 0}, True),
            ("synthetic-unsupported", Source(skips=[LAYOUT]),
             {"status": "unsupported", "candidates": 0, "skips": {"layout": 1}}, False),
            ("synthetic-list", Source(skips=[{"reason": "unsupported-list"}]),
             {"status": "unsupported", "candidates": 0, "skips": {"unsupported-list": 1}}, False),
            ("synthetic-unavailable", Source(skips=[{"reason": "robots"}]),
             {"status": "unavailable", "candidates": 0, "skips": {"robots": 1}}, False),
            ("synthetic-failed", Source(error=ValueError("synthetic source failure")),
             {"status": "failed", "error": "ValueError: synthetic source failure"}, False),
            ("ais-static", None, {"status": "not-implemented",
             "reason": "adapter 'ais-static' is registered but not implemented yet"}, True),
        )
        for key, source, expected, complete in cases:
            for order in ((key, "synthetic-ok"), ("synthetic-ok", key)):
                with self.subTest(key=key, order=order):
                    sources = {"synthetic-ok": Source([self.candidate])}
                    if source is not None:
                        sources[key] = source
                    bindings = tuple(SimpleNamespace(id=k, adapter=k, params={}) for k in order)
                    result, doc, rows = self.discover(sources, bindings=bindings)
                    self.assertEqual(rows, [self.payload])
                    self.assertIs(doc["complete"], complete)
                    self.assertEqual(doc["bindings"], {key: expected, "synthetic-ok": {"status": "ok", "candidates": 1}})
                    gap = {} if expected["status"] == "failed" else {key: expected["status"]}
                    self.assertEqual(doc["gaps"], gap)
                    self.assertEqual(result, {"candidates": 1, "bindings": 2,
                                             "failed": int(expected["status"] == "failed"), "gaps": len(gap)})
        sources = {key: source for key, source, _, _ in cases if source is not None}
        bindings = tuple(SimpleNamespace(id=key, adapter=key, params={}) for key, _, _, _ in cases)
        result, doc, rows = self.discover(sources, bindings=bindings)
        self.assertEqual(rows, [])
        self.assertEqual(doc["bindings"], {key: expected for key, _, expected, _ in cases})
        self.assertEqual(doc["gaps"], {key: expected["status"] for key, _, expected, _ in cases
                                       if expected["status"] != "failed"})
        self.assertIs(doc["complete"], False)
        self.assertEqual(result, {"candidates": 0, "bindings": 6, "failed": 1, "gaps": 5})

    def test_all_success_empty_and_no_skip_collection(self):
        for sources in ({}, {"synthetic-empty": Source()},
                        {"synthetic-a": Source([self.candidate]), "synthetic-b": Source([self.candidate])}):
            for net in (True, False):
                with self.subTest(sources=list(sources), net=net):
                    result, doc, rows = self.discover(sources, net=net)
                    self.assertIs(doc["complete"], True)
                    self.assertEqual(rows, [self.payload] * (2 if len(sources) == 2 else 0))
                    self.assertEqual(result["failed"], 0)
                    self.assertEqual(doc["bindings"], {key: {"status": "ok" if source.candidates else "empty",
                                                            "candidates": len(source.candidates)}
                                                      for key, source in sources.items()})

    def test_preexisting_skips_do_not_belong_to_this_run(self):
        _, doc, rows = self.discover({"synthetic-ok": Source([self.candidate])}, previous=[LAYOUT])
        self.assertIs(doc["complete"], True)
        self.assertEqual(rows, [self.payload])
        self.assertEqual(doc["bindings"], {"synthetic-ok": {"status": "ok", "candidates": 1}})

    def test_scout_report_fields_are_preserved(self):
        source = Source([self.candidate], [LAYOUT], report={"synthetic-scout": {
            "rows_read": 2, "rows_accepted": 1, "synthetic_marker": "kept"}})
        binding = SimpleNamespace(id="synthetic-scout", adapter="file-import", params={"columns": "scout-candidates-v1"})
        _, doc, rows = self.discover({"file-import": source}, bindings=(binding,))
        self.assertEqual(rows, [self.payload])
        self.assertIs(doc["complete"], False)
        self.assertEqual(doc["bindings"], {"synthetic-scout": {
            "status": "ok", "candidates": 1, "skips": {"layout": 1},
            "rows_read": 2, "rows_accepted": 1, "synthetic_marker": "kept"}})


class HistoryTests(SyntheticCase):
    def snapshot(self):
        return Snapshot([{"id": "a" * 32, "name": "Missing Synthetic Example", "status": "active",
                          "last_seen_at": "2026-08-01T09:47:00Z", "offerings": []}])

    def history(self, flags):
        region_dir = self.root / f"history-{self.sequence}"
        for index, complete in enumerate(flags):
            run = region_dir / "runs" / f"synthetic-{index}"
            run.mkdir(parents=True)
            (run / "discover.json").write_text(json.dumps({"at": f"2026-09-{index + 1:02d}T09:47:00Z",
                                                          "complete": complete}), encoding="utf-8")
        return discovery_history(region_dir)

    def check_vanished(self, out):
        self.assertEqual([op["op"] for op in out], ["review.open", "change.record"])
        self.assertEqual([op["kind"] for op in out], ["vanished", "vanished"])
        review, change = out
        self.assertEqual(review["subject_id"], "a" * 32)
        self.assertEqual(review["proposal_json"], {"vessel_id": "a" * 32, "status": "inactive"})
        self.assertEqual(change["vessel_id"], "a" * 32)
        self.assertEqual(change["review_id"], ops.review_id("vanished", "a" * 32 + "|2026-08-01T09:47:00.000Z"))

    def test_partial_current_run_cannot_finish_vanished_threshold(self):
        history = self.history([True, True])
        for skips in ([LAYOUT], []):
            _, doc, _ = self.discover({"synthetic-current": Source([self.candidate], skips)})
            self.assertIs(doc["complete"], not bool(skips))
            out = detect(self.snapshot(), [], AT, complete=doc["complete"], history=history,
                         vanished_runs=3, vanished_days=45)
            if skips:
                self.assertEqual(out, [])
            else:
                self.check_vanished(out)

    def test_partial_historical_run_does_not_count(self):
        for complete in (False, True):
            self.sequence += 1
            history = self.history([True, complete])
            self.assertEqual(history, ["2026-09-01T09:47:00.000Z"] +
                             (["2026-09-02T09:47:00.000Z"] if complete else []))
            out = detect(self.snapshot(), [], AT, complete=True, history=history,
                         vanished_runs=3, vanished_days=45)
            if complete:
                self.check_vanished(out)
            else:
                self.assertEqual(out, [])


if __name__ == "__main__":
    unittest.main()
