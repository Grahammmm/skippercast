"""RF1221-2: a present run metadata file whose JSON root is not an object is refused with a handled ValueError."""
from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from skippercast.fleet import cli, report
from skippercast.fleet.config import load_region

NOW = 1_794_700_000
HEALTHY = {
    "state.json": {"created_at": "2026-11-16T00:00:00Z", "steps": {"resolve": {"status": "failed"}}},
    "report.json": {"status": "ok"},
    "enrich-code.json": {"bindings": {}},
}
BAD_ROOTS = ("[]", "[1]", "null", "true", "false", "0", "7", '""', '"synthetic-marker"')


def write_run(var: Path, name: str = "20261116T000000Z-aaaaaa", **overrides: str | None) -> Path:
    directory = var / "CA" / "runs" / name
    directory.mkdir(parents=True, exist_ok=True)
    for basename, doc in HEALTHY.items():
        text = overrides.get(basename, json.dumps(doc))
        if text is None:
            continue
        (directory / basename).write_text(text, encoding="utf-8")
    return directory


class RootTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.var = Path(tmp.name)
        self.region = load_region("CA")

    def refusal(self, basename: str) -> str:
        return f"run {basename} must contain a JSON object"

    def test_each_present_run_document_requires_an_object(self):
        for basename in HEALTHY:
            for text in BAD_ROOTS:
                with self.subTest(basename=basename, text=text), tempfile.TemporaryDirectory() as tmp:
                    var = Path(tmp)
                    write_run(var, **{basename: text})
                    with self.assertRaises(ValueError) as caught:
                        report.read_runs(self.region, var)
                    self.assertEqual(str(caught.exception), self.refusal(basename))

    def test_root_validation_precedes_metadata_access(self):
        for first, second in (("state.json", "report.json"), ("report.json", "enrich-code.json")):
            with self.subTest(first=first), tempfile.TemporaryDirectory() as tmp:
                var = Path(tmp)
                write_run(var, **{first: "[]", second: "null"})
                with self.assertRaises(ValueError) as caught:
                    report.read_runs(self.region, var)
                self.assertEqual(str(caught.exception), self.refusal(first))
        # a later run's bad root aborts the reader instead of returning only the earlier healthy row
        write_run(self.var, "20261115T000000Z-aaaaaa")
        write_run(self.var, "20261116T000000Z-bbbbbb", **{"report.json": "[]"})
        with self.assertRaises(ValueError) as caught:
            report.read_runs(self.region, self.var)
        self.assertEqual(str(caught.exception), self.refusal("report.json"))

    def run_cli(self, var: Path):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.dict(os.environ, {"SKIPPERCAST_FLEET_VAR": str(var)}), redirect_stdout(out), \
                mock.patch("sys.stderr", err), mock.patch.object(report.time, "time", return_value=NOW):
            code = cli.main(["report", "--region", "CA"])
        return code, out.getvalue(), err.getvalue()

    def test_report_cli_handles_bad_roots_without_output_or_replacement(self):
        for basename in HEALTHY:
            for text in ("[]", "null"):
                for preexisting in (False, True):
                    with self.subTest(basename=basename, text=text, preexisting=preexisting), \
                            tempfile.TemporaryDirectory() as tmp:
                        var = Path(tmp)
                        directory = write_run(var, **{basename: text})
                        reports = var / "CA" / "reports"
                        sentinels = {}
                        if preexisting:
                            reports.mkdir(parents=True)
                            for suffix in (".json", ".md"):
                                path = reports / f"2026-10-05{suffix}"
                                path.write_bytes(b"sentinel" + suffix.encode())
                                sentinels[path] = path.read_bytes()
                        before = (directory / basename).read_bytes()
                        code, out, err = self.run_cli(var)
                        self.assertEqual(code, 2)
                        self.assertEqual(out, "")
                        self.assertEqual(err, f"fleet report: {self.refusal(basename)}\n")
                        self.assertNotIn("Traceback", err)
                        self.assertEqual((directory / basename).read_bytes(), before)
                        if preexisting:
                            for path, data in sentinels.items():
                                self.assertEqual(path.read_bytes(), data)
                            self.assertEqual(len(list(reports.iterdir())), 2)
                        else:
                            self.assertFalse(reports.exists())

    def test_missing_optional_files_and_object_roots_keep_legacy_rows(self):
        places = next(b.id for b in self.region.sources if b.adapter == "google-places")
        other = next((b.id for b in self.region.sources if b.adapter != "google-places"), "not-a-places-binding")
        write_run(self.var, "20261110T000000Z-aaaaaa", **{"report.json": None, "enrich-code.json": None})
        write_run(self.var, "20261111T000000Z-bbbbbb", **{
            "state.json": "{}", "report.json": "{}", "enrich-code.json": "{}"})
        write_run(self.var, "20261112T000000Z-cccccc", **{
            "report.json": json.dumps({"status": "mystery", "extra": 1}),
            "enrich-code.json": json.dumps({"bindings": {
                places: {"searches": 3, "details": 2}, other: {"searches": 9, "details": 9}}, "unused": []})})
        write_run(self.var, "20261113T000000Z-dddddd", **{"report.json": json.dumps({"status": "ok"})})
        rows = report.read_runs(self.region, self.var)
        self.assertEqual(rows, [
            {"id": "20261110T000000Z-aaaaaa", "created_at": "2026-11-16T00:00:00Z", "status": "incomplete",
             "failed_steps": ["resolve"], "places_calls": 0},
            {"id": "20261111T000000Z-bbbbbb", "created_at": None, "status": "incomplete",
             "failed_steps": [], "places_calls": 0},
            {"id": "20261112T000000Z-cccccc", "created_at": "2026-11-16T00:00:00Z", "status": "incomplete",
             "failed_steps": ["resolve"], "places_calls": 5},
            {"id": "20261113T000000Z-dddddd", "created_at": "2026-11-16T00:00:00Z", "status": "ok",
             "failed_steps": ["resolve"], "places_calls": 0},
        ])

    def test_healthy_staging_report_still_writes_both_outputs(self):
        write_run(self.var)
        code, out, err = self.run_cli(self.var)
        self.assertEqual((code, err), (0, ""))
        files = sorted(p.name for p in (self.var / "CA" / "reports").iterdir())
        self.assertEqual(len(files), 2)
        written = {p.suffix: p.read_text(encoding="utf-8") for p in (self.var / "CA" / "reports").iterdir()}
        self.assertEqual(out, written[".md"])
        self.assertEqual(json.loads(written[".json"])["region"], "CA")
        self.assertIn("20261116T000000Z-aaaaaa", written[".md"])

    def test_json_syntax_error_is_still_a_handled_refusal(self):
        write_run(self.var, **{"state.json": "{not json"})
        code, out, err = self.run_cli(self.var)
        self.assertEqual((code, out), (2, ""))
        self.assertTrue(err.startswith("fleet report: "))
        self.assertNotIn("must contain a JSON object", err)
        self.assertFalse((self.var / "CA" / "reports").exists())


if __name__ == "__main__":
    unittest.main()
