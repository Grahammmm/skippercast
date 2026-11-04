"""RF0420-2: file-import reads its input safely and names every read or CSV failure (synthetic CSVs only).

A link below the region folder, a FIFO, an oversized or unreadable file and an unparseable CSV each raise
FileImportError naming the reason, never the content; enrich-code marks only that binding failed.
"""
import json
import os
from pathlib import Path
import shutil
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest import mock

from skippercast.fleet import enrich
from skippercast.fleet.adapters import file_import
from skippercast.fleet.adapters.base import Fact, RunContext
from skippercast.fleet.adapters.file_import import FileImport, FileImportError, read_rows
from skippercast.fleet.config import load_region
from skippercast.fleet.runs import Run
from tests._support import FIXTURES

NOW = "2026-10-05T10:00:00Z"
REGION = load_region("CA")
VALID = (FIXTURES / "fleet" / "cpra" / "cpfv-v1.csv").read_bytes()
SECRET = "Secret Cell Text"


class _Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.fleet_run = Run("CA", "20261005T100000Z-abcdef", var=self.tmp)
        self.ctx = RunContext(region=REGION, net=None, run_dir=self.fleet_run.dir, clock=lambda: NOW)
        self.inputs = self.tmp / "CA" / "inputs"
        self.path = self.inputs / "cpfv.csv"
        self.binding = SimpleNamespace(id="cpra-cpfv", adapter="file-import", enabled=True, rights="public-record",
                                       params={"path": "inputs/cpfv.csv", "columns": "cdfw-cpfv-v1"})

    def refused(self, adapter=None) -> str:
        with self.assertRaises(FileImportError) as caught:
            list((adapter or FileImport()).discover(self.binding, self.ctx))
        return str(caught.exception)


class SafeReadTests(_Base):
    def test_symlinked_file_is_refused_and_target_never_opened(self):
        target = self.tmp / "elsewhere.csv"
        target.write_bytes(VALID)
        self.path.symlink_to(target)
        with mock.patch.object(file_import.os, "open", wraps=os.open) as opened:
            message = self.refused()
        self.assertEqual(message, "cpra-cpfv: input path goes through a link")
        self.assertEqual(opened.call_count, 0, "nothing is opened once a link is seen")

    def test_symlinked_inputs_folder_is_refused(self):
        real = self.tmp / "real-inputs"
        real.mkdir()
        (real / "cpfv.csv").write_bytes(VALID)
        self.inputs.rmdir()
        self.inputs.symlink_to(real, target_is_directory=True)
        self.assertEqual(self.refused(), "cpra-cpfv: input path goes through a link")

    def test_symlinked_region_folder_is_refused_before_anything_is_opened(self):
        region = self.tmp / "CA"
        external = self.tmp / "external-region"
        region.rename(external)
        (external / "inputs" / "cpfv.csv").write_bytes(VALID)
        region.symlink_to(external, target_is_directory=True)
        self.assertTrue(self.path.is_file(), "the external file is reachable through the region link")
        with mock.patch.object(file_import.os, "open", wraps=os.open) as opened:
            message = self.refused()
        self.assertEqual(message, "cpra-cpfv: input path goes through a link")
        self.assertEqual(opened.call_count, 0, "nothing is opened once a link is seen")

    def test_dangling_link_is_a_link_not_a_missing_file(self):
        self.path.symlink_to(self.tmp / "gone.csv")
        adapter = FileImport()
        self.assertEqual(self.refused(adapter), "cpra-cpfv: input path goes through a link")
        self.assertNotIn("status", adapter.report["cpra-cpfv"])

    def test_fifo_is_not_a_regular_file_and_never_blocks(self):
        os.mkfifo(self.path)
        result = []
        worker = threading.Thread(target=lambda: result.append(self.refused()), daemon=True)
        worker.start()
        worker.join(5)
        self.assertFalse(worker.is_alive(), "reading a FIFO must not block")
        self.assertEqual(result, ["cpra-cpfv: input is not a regular file"])

    def test_directory_at_the_path_is_not_a_regular_file(self):
        self.path.mkdir()
        self.assertEqual(self.refused(), "cpra-cpfv: input is not a regular file")

    def test_size_cap(self):
        body = b"Vessel Name,FG Number\nSea Example,FG1\n"
        filler = 64 - len(body) - 4
        body += b"A" * filler + b",F1\n"
        self.assertEqual(len(body), 64)
        with mock.patch.object(file_import, "MAX_INPUT_BYTES", 64):
            self.path.write_bytes(body + b"\n")
            self.assertEqual(self.refused(), "cpra-cpfv: input is larger than 16 MiB")
            self.path.write_bytes(body)
            names = [c.name for c in FileImport().discover(self.binding, self.ctx)]
        self.assertEqual(names, ["Sea Example", "A" * filler])

    @unittest.skipIf(os.geteuid() == 0, "root reads a mode-000 file")
    def test_unreadable_file(self):
        self.path.write_bytes(VALID)
        self.path.chmod(0)
        self.addCleanup(self.path.chmod, 0o600)
        self.assertEqual(self.refused(), "cpra-cpfv: input file unreadable (PermissionError)")


class CsvErrorTests(_Base):
    def test_nul_byte_in_row_three_names_the_line_not_the_cell(self):
        data = f"Vessel Name,FG Number\nSea Example,FG1\n{SECRET}\x00,FG2\n".encode()
        with self.assertRaises(FileImportError) as caught:
            read_rows(data, "cdfw-cpfv-v1")
        self.assertEqual(str(caught.exception), "cdfw-cpfv-v1: CSV unreadable near line 3")
        self.path.write_bytes(data)
        message = self.refused()
        self.assertIn("near line", message)
        self.assertNotIn(SECRET, message)
        with self.assertRaises(FileImportError) as caught:
            read_rows(b"Vessel\x00 Name,FG Number\nSea Example,FG1\n", "cdfw-cpfv-v1")
        self.assertEqual(str(caught.exception), "cdfw-cpfv-v1: CSV unreadable near line 1")

    def test_field_over_the_csv_limit_names_the_line_not_the_cell(self):
        huge = SECRET + "x" * 200_000
        for data, line in ((f"Vessel Name,FG Number\nSea Example,FG1\n{huge},FG2\n".encode(), 3),
                           (f"Vessel Name,{huge}\n".encode(), 1)):
            with self.assertRaises(FileImportError) as caught:
                read_rows(data, "cdfw-cpfv-v1")
            self.assertEqual(str(caught.exception), f"cdfw-cpfv-v1: CSV unreadable near line {line}")
            self.assertNotIn(SECRET, str(caught.exception))


class TodayTests(_Base):
    def test_missing_file_is_skipped_with_todays_reason(self):
        adapter = FileImport()
        self.assertEqual(list(adapter.discover(self.binding, self.ctx)), [])
        self.assertEqual(adapter.report["cpra-cpfv"]["status"], "skipped")
        self.assertEqual(adapter.report["cpra-cpfv"]["reason"], "input file not found: inputs/cpfv.csv")

    def test_valid_csv_gives_todays_candidates_and_counts(self):
        self.path.write_bytes(VALID)
        adapter = FileImport()
        names = [c.name for c in adapter.discover(self.binding, self.ctx)]
        self.assertEqual(names, ["Sea Example", "Test Boat", "Placeholder Queen"])
        self.assertEqual(adapter.report["cpra-cpfv"], {"rows": 4, "candidates": 3, "individual_licensees_dropped": 1,
                                                       "rows_without_name": 1, "status": "ok"})


class _FakeSite:
    report = {"status": "ok"}

    def enrich(self, vessel, binding, ctx):
        return [Fact("phone", "+18055550100", binding.id, "https://www.seaexample.example/", "page", 0.8,
                     "public", NOW)]


class EnrichStepTests(_Base):
    def test_failing_import_marks_one_binding_failed_and_the_step_still_writes(self):
        target = self.tmp / "elsewhere.csv"
        target.write_bytes(VALID)
        self.path.symlink_to(target)
        site = SimpleNamespace(id="operator-site", adapter="operator-site", enabled=True)
        sources = (site, self.binding)
        region = SimpleNamespace(sources=sources, enabled_sources=lambda: sources,
                                 binding=lambda ident: next(b for b in sources if b.id == ident))
        ctx = RunContext(region=region, net=None, run_dir=self.fleet_run.dir, clock=lambda: NOW)
        counts = enrich.enrich_code(ctx, None, vessels=[{"vessel_id": "v-1", "name": "Sea Example"}],
                                    adapters={"operator-site": _FakeSite()})
        report = json.loads((self.fleet_run.dir / "enrich-code.json").read_text())
        self.assertEqual(report["bindings"]["cpra-cpfv"],
                         {"status": "failed", "error": "cpra-cpfv: input path goes through a link"})
        self.assertEqual(report["bindings"]["operator-site"], {"status": "ok"})
        facts = [json.loads(line) for line in (self.fleet_run.dir / "facts.jsonl").read_text().splitlines()]
        self.assertEqual([(f["vessel_id"], f["field"], f["value"]) for f in facts], [("v-1", "phone", "+18055550100")])
        self.assertEqual((counts["facts"], counts["imported"]), (1, 0))
