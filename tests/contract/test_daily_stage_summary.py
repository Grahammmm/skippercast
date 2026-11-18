"""Daily Actions failure attribution and read-only release reporting, offline."""
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import tempfile
import unittest

from scripts.daily_stage_summary import OPTIONAL, STAGES, render
from tests._support import ROOT


NOW = datetime(2026, 11, 17, 14, tzinfo=timezone.utc)
PREVIOUS = "2026-11-17T10:00:00Z"
CURRENT = "2026-11-17T13:55:00Z"
WORKFLOW = ROOT / ".github/workflows/daily-data.yml"


class DailyStageSummaryTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.pointer = self.root / "published/latest.json"
        self.put("published/latest.json", {"generated_at": PREVIOUS})

    def put(self, name, value):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding="utf-8")

    def check_failure(self, failed):
        # Check the real workflow's default success() gates before modeling their
        # outcomes: a blocking failure must skip the release writer, but not the summary.
        body = WORKFLOW.read_text(encoding="utf-8").split("    steps:\n", 1)[1]
        steps = re.split(r"^      - ", body, flags=re.M)[1:]
        ordered = [re.findall(r"^        id: ([\w-]+)$", block, re.M)[0] for block in steps[:-1]]
        fail_at, publish_at = ordered.index(failed), ordered.index("publish")
        self.assertLess(fail_at, publish_at)
        self.assertNotRegex(steps[fail_at], r"(?m)^        continue-on-error:")
        self.assertNotRegex(steps[publish_at], r"(?m)^        if:")
        self.assertIn("if: always()", steps[-1])
        outcomes = dict.fromkeys(ordered[:fail_at], "success")
        outcomes.update(dict.fromkeys(ordered[fail_at:], "skipped"))
        outcomes[failed] = "failure"
        for stage in ("report-coastal", "report-discussion", "report-surveys"):
            outcomes[stage] = "failure"
        before = self.pointer.read_bytes()
        summary = render(self.root, outcomes, NOW)
        self.assertEqual(self.pointer.read_bytes(), before)
        self.assertIn("Release (data branch): retained — this run did not advance the pointer", summary)
        self.assertIn("Public site verification: not run", summary)
        self.assertNotIn("First failed stage: Report", summary)
        return summary

    def test_parser_failure_precedes_coverage_and_does_not_advance_pointer(self):
        # A file on disk is not proof that this run loaded or collected it.
        self.put("previous.json", {"generated_at": PREVIOUS})
        self.put("daily/regions/index.json", {"regions": [{"status": "failed"}]})
        summary = self.check_failure("parser")
        self.assertIn("First failed stage: Test evidence parsing and failure handling", summary)
        self.assertIn("Previous data-branch generation: unknown", summary)
        self.assertIn("Previous generation age at summary time: unknown", summary)
        self.assertIn("Affected regions (degraded or failed in this attempt): unknown", summary)

    def test_upstream_failure_keeps_the_loaded_generation_and_counts_affected_regions(self):
        self.put("previous.json", {"generated_at": PREVIOUS})
        self.put("daily/regions/index.json", {"regions": [
            {"status": "failed", "error": "<synthetic private source detail>"},
            {"status": "ok", "region_id": "synthetic-region-name"},
            {"status": "degraded"},
        ]})
        summary = self.check_failure("collect")
        self.assertIn("First failed stage: Collect and validate public sources", summary)
        self.assertIn("Previous data-branch generation: 2026-11-17T10:00:00+00:00", summary)
        self.assertIn("Previous generation age at summary time: 240 min", summary)
        self.assertIn("Affected regions (degraded or failed in this attempt): 2", summary)
        self.assertNotIn("private source detail", summary)
        self.assertNotIn("synthetic-region-name", summary)

    def test_success_control_reports_new_generation_and_verification(self):
        self.put("previous.json", {"generated_at": PREVIOUS})
        self.put("published/latest.json", {"generated_at": CURRENT})
        self.put("daily/regions/index.json", {"regions": [{"status": "ok"}]})
        summary = render(self.root, dict.fromkeys(STAGES, "success"), NOW)
        self.assertIn("First failed stage: none", summary)
        self.assertIn("Affected regions (degraded or failed in this attempt): 0", summary)
        self.assertIn("Release (data branch): new daily generation", summary)
        self.assertIn("Public site verification: passed", summary)

    def test_failed_publish_does_not_claim_new_or_retained_release(self):
        self.put("previous.json", {"generated_at": PREVIOUS})
        self.put("published/latest.json", {"generated_at": CURRENT})
        outcomes = dict.fromkeys(STAGES, "success") | {"publish": "failure", "verify": "skipped"}
        summary = render(self.root, outcomes, NOW)
        self.assertIn("First failed stage: Publish an atomic data snapshot", summary)
        self.assertIn("Release (data branch): unknown", summary)

    def test_malformed_metadata_is_unknown_and_not_echoed(self):
        self.put("previous.json", {"generated_at": "[injected](https://example.test/)"})
        self.put("daily/regions/index.json", {"regions": [{"status": "ok"}, {"status": "garbled"}]})
        summary = render(self.root, dict.fromkeys(STAGES, "success"), NOW)
        self.assertIn("Previous data-branch generation: unknown", summary)
        self.assertIn("Affected regions (degraded or failed in this attempt): unknown", summary)
        self.assertIn("Release (data branch): unknown", summary)
        self.assertNotIn("injected", summary)

    def test_optional_failure_does_not_hide_the_blocking_failure(self):
        outcomes = dict.fromkeys(STAGES, "success") | {"discussion": "failure", "verify": "failure"}
        summary = render(self.root, outcomes, NOW)
        self.assertIn("First failed stage: Discover recent local fishing discussions (non-blocking)", summary)
        self.assertIn("First blocking failure: Verify the public site serves this snapshot", summary)

    def test_stage_order_and_optional_outcomes_match_the_workflow(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        observed = re.findall(r"^            ([\w-]+)=\$\{\{ steps\.\1\.outcome \}\}$", text, re.M)
        self.assertEqual(observed, re.findall(r"^        id: ([\w-]+)$", text, re.M))
        self.assertEqual(observed, list(STAGES))
        optional = re.findall(r"^        id: ([\w-]+)\n        continue-on-error: true$", text, re.M)
        self.assertEqual(set(optional), OPTIONAL)
