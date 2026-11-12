"""RF2340-9: file-import refuses a CSV record with more cells than its header (synthetic CSVs only).

A surplus cell (typically an unquoted comma) shifts identity text into a different vessel or registration; the whole
binding is refused with the existing safe FileImportError, never a partial import.
"""
import json
from pathlib import Path
import shutil
import tempfile
from types import SimpleNamespace
import unittest

from skippercast.fleet import enrich
from skippercast.fleet.adapters.base import Fact, RunContext
from skippercast.fleet.adapters.file_import import FileImport, FileImportError, read_rows
from skippercast.fleet.config import load_region
from skippercast.fleet.runs import Run

NOW = "2026-10-05T10:00:00Z"
CDFW = "cdfw-cpfv-v1"
SCOUT = "scout-candidates-v1"
CDFW_HEAD = "Vessel Name,FG Number\n"
SCOUT_HEAD = "Port ID,Boat,Operator,Class,Landing,Website,Evidence URLs\n"
SCOUT_ROW = "fixture-port,Sea Example,Example Charters,unknown,,,https://sea.example/"
SENTINEL = "Sentinel Cell Text"


def refused(data: bytes, column_set: str) -> str:
    with unittest.TestCase().assertRaises(FileImportError) as caught:
        read_rows(data, column_set)
    return str(caught.exception)


class ReadRowsSurplusTests(unittest.TestCase):
    def test_surplus_cells_refused_for_both_formats(self):
        cases = [
            (CDFW, CDFW_HEAD + "Sea Example,FG1,extra\n", 2),
            (CDFW, CDFW_HEAD + "Sea Example,FG1,a,b,c\n", 2),
            (CDFW, CDFW_HEAD + "Sea Example,FG1,\n", 2),  # one empty surplus cell is still a malformed record
            (CDFW, CDFW_HEAD + "Ok Boat,FG0\nSea Example,FG1,\n", 3),
            (SCOUT, SCOUT_HEAD + SCOUT_ROW + ",extra\n", 2),
            (SCOUT, SCOUT_HEAD + SCOUT_ROW + ",a,b\n", 2),
            (SCOUT, SCOUT_HEAD + SCOUT_ROW + ",\n", 2),
        ]
        for column_set, text, line in cases:
            with self.subTest(column_set=column_set, text=text):
                self.assertEqual(refused(text.encode(), column_set), f"{column_set}: CSV unreadable near line {line}")

    def test_sentinel_cell_never_in_diagnostic(self):
        message = refused(f"{CDFW_HEAD}Sea Example,FG1,{SENTINEL}\n".encode(), CDFW)
        self.assertNotIn(SENTINEL, message)

    def test_unquoted_comma_never_creates_shifted_identity(self):
        for text in ("Sea, Example,FG1\n", "Sea Example,FG1,\n"):
            for prefix in ("", "First Boat,FG0\n"):
                with self.subTest(text=text, prefix=prefix):
                    self.assertTrue(refused((CDFW_HEAD + prefix + text).encode(), CDFW).startswith(CDFW))
        self.assertEqual(read_rows(f'{CDFW_HEAD}"Sea, Example",FG1\n'.encode(), CDFW),
                         [{"vessel_name": "Sea, Example", "fg_number": "FG1"}])

    def test_multiline_bad_record_names_ending_line(self):
        bad = '"Sea\nExample",FG1,extra\n'
        for data in ((CDFW_HEAD + bad).encode(), (CDFW_HEAD + bad).replace("\n", "\r\n").encode(),
                     b"\xef\xbb\xbf" + (CDFW_HEAD + bad.rstrip("\n")).encode()):
            with self.subTest(data=data):
                self.assertEqual(refused(data, CDFW), f"{CDFW}: CSV unreadable near line 3")
        good = read_rows(f'{CDFW_HEAD}"Sea\nExample ""A"", Two",FG1'.encode(), CDFW)  # no final newline
        self.assertEqual(good, [{"vessel_name": 'Sea\nExample "A", Two', "fg_number": "FG1"}])

    def test_declared_unknown_columns_are_not_surplus(self):
        head = "Notes,FG Number,Extra,Vessel Name,Extra,\n"
        self.assertEqual(read_rows((head + "n,FG1,x,Sea Example,y,z\n").encode(), CDFW),
                         [{"vessel_name": "Sea Example", "fg_number": "FG1"}])
        self.assertEqual(refused((head + "n,FG1,x,Sea Example,y,z,\n").encode(), CDFW),
                         f"{CDFW}: CSV unreadable near line 2")

    def test_legacy_short_and_empty_inputs_unchanged(self):
        self.assertEqual(read_rows((CDFW_HEAD + "Sea Example\n").encode(), CDFW),
                         [{"vessel_name": "Sea Example", "fg_number": ""}])
        self.assertEqual(read_rows((CDFW_HEAD + "\nSea Example,\n\n").encode(), CDFW),
                         [{"vessel_name": "Sea Example", "fg_number": ""}])
        self.assertEqual(read_rows(CDFW_HEAD.encode(), CDFW), [])
        short = read_rows((SCOUT_HEAD + "fixture-port,Sea Example\n").encode(), SCOUT)
        self.assertEqual((short[0]["vessel_name"], short[0]["evidence_urls"]), ("Sea Example", ""))


class _Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.fleet_run = Run("CA", "20261005T100000Z-abcdef", var=self.tmp)
        self.region = load_region("CA")
        self.ctx = RunContext(region=self.region, net=None, run_dir=self.fleet_run.dir, clock=lambda: NOW)
        self.path = self.tmp / "CA" / "inputs" / "list.csv"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def binding(self, columns):
        return SimpleNamespace(id="import-binding", adapter="file-import", enabled=True, rights="public-record",
                               params={"path": "inputs/list.csv", "columns": columns,
                                       "source_url": "https://records.example/cpra"})


class AtomicTests(_Base):
    def test_late_surplus_is_atomic_before_candidate_processing(self):
        port = self.region.ports[0].id
        cases = {CDFW: CDFW_HEAD + "First Boat,FG0\nSea, Example,FG1\n",
                 SCOUT: SCOUT_HEAD + SCOUT_ROW.replace("fixture-port", port) + "\n"
                 + SCOUT_ROW.replace("fixture-port", port) + ",extra\n"}
        for columns, text in cases.items():
            with self.subTest(columns=columns):
                self.path.write_bytes(text.encode())
                adapter = FileImport()
                with self.assertRaises(FileImportError):
                    list(adapter.discover(self.binding(columns), self.ctx))
                report = adapter.report["import-binding"]
                self.assertEqual((report["rows"], report["candidates"]), (0, 0))
                self.assertEqual(self.path.read_bytes(), text.encode())


class _FakeSite:
    report = {"status": "ok"}

    def enrich(self, vessel, binding, ctx):
        return [Fact("phone", "+180****0100", binding.id, "https://www.seaexample.example/", "page", 0.8,
                     "public", NOW)]


class EnrichIsolationTests(_Base):
    def test_surplus_binding_failure_does_not_abort_other_sources(self):
        self.path.write_bytes(f"{CDFW_HEAD}First Boat,FG0\nSea Example,FG1,{SENTINEL}\n".encode())
        binding = self.binding(CDFW)
        site = SimpleNamespace(id="operator-site", adapter="operator-site", enabled=True)
        sources = (site, binding)
        region = SimpleNamespace(sources=sources, enabled_sources=lambda: sources,
                                 binding=lambda ident: next(b for b in sources if b.id == ident))
        ctx = RunContext(region=region, net=None, run_dir=self.fleet_run.dir, clock=lambda: NOW)
        counts = enrich.enrich_code(ctx, None, vessels=[{"vessel_id": "v-1", "name": "Sea Example"}],
                                    adapters={"operator-site": _FakeSite()})
        text = (self.fleet_run.dir / "enrich-code.json").read_text()
        report = json.loads(text)
        self.assertEqual(report["bindings"]["import-binding"],
                         {"status": "failed", "error": f"{CDFW}: CSV unreadable near line 3"})
        self.assertEqual(report["bindings"]["operator-site"], {"status": "ok"})
        self.assertNotIn(SENTINEL, text)
        self.assertNotIn("FG0", text)
        self.assertEqual((counts["facts"], counts["imported"]), (1, 0))


if __name__ == "__main__":
    unittest.main()
