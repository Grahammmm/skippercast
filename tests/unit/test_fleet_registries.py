"""Registry adapters: FCC ULS ship licences and USCG PSIX (CF-12, design section 6).

Offline. The FCC fixture is three tiny synthetic ``.dat`` files zipped at test
time; the PSIX fixture is a synthetic form, result page and inspection rows from
which the test builds the XLSX export. Names, numbers and addresses are invented;
MMSIs are 999xxxxxx.
"""
from datetime import date
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
from pathlib import Path
import socket
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs
import zipfile

from skippercast.fleet import ops
from skippercast.fleet.adapters import get
from skippercast.fleet.adapters.fcc_uls import FccFormatError, FccUls, is_entity, parse_ship_zip
from skippercast.fleet.adapters.uscg_psix import (PsixFormatError, UscgPsix, candidates, parse_form,
                                                  parse_inspections, search_fields, vessels)
from skippercast.fleet.net import FleetSession
from tests._support import FIXTURES

FCC = FIXTURES / "fleet" / "fcc"
PSIX = FIXTURES / "fleet" / "psix"
NOW = "2026-10-05T09:47:00Z"
FCC_URL = "https://data.fcc.gov/download/pub/uls/complete/l_ship.zip"
PSIX_URL = "https://cgmix.uscg.mil/XML/PSIXExportSearch.aspx"
# Everything personal in the FCC fixture: individual licensees, a contact row, street addresses, ZIP codes.
PERSONAL = ("TESTPERSON", "JANE", "PEDRO", "CONTACTO", "PERSONA", "FICTA", "SAMPLE FAMILY", "EXAMPLE WAY",
            "INVENTED LANE", "MADEUP", "FAKE STREET", "99999")


def ship_zip(drop: str | None = None, replace: dict | None = None) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(FCC.glob("*.dat")):
            if path.name != drop:
                archive.writestr(path.name, (replace or {}).get(path.name, path.read_bytes()))
    return buffer.getvalue()


def region():
    ports = [SimpleNamespace(id="morro-bay", name="Morro Bay"), SimpleNamespace(id="san-diego", name="San Diego")]
    return SimpleNamespace(id="CA", ports=ports)


def binding(adapter, **params):
    return SimpleNamespace(id=adapter, adapter=adapter, enabled=True, rights="public-domain", params=params)


def fcc_candidates(**options):
    ports = {"MORROBAY": "morro-bay", "SANDIEGO": "san-diego"}
    return list(parse_ship_zip(ship_zip(), "CA", source_id="fcc-uls", rights="public-domain", retrieved_at=NOW,
                               ports=ports, **options))


def facts(candidate, field):
    return [f.value for f in candidate.facts if f.field == field]


def assert_ops_contract(test, candidates):
    """Every fact is a valid fact.upsert under the CF-11 operation contract."""
    for candidate in candidates:
        test.assertTrue(candidate.facts)
        for fact in candidate.facts:
            row = ops.validate_op({"op": "fact.upsert", "vessel_id": "0" * 32, "field": fact.field,
                                   "value_json": fact.value, "source_id": fact.source_id,
                                   "source_url": fact.source_url, "method": fact.method,
                                   "confidence": fact.confidence, "rights": fact.rights,
                                   "retrieved_at": fact.retrieved_at}, 0, "CA")
            test.assertEqual(row.kind, "fact.upsert")


# ---- XLSX export (built the way PSIX writes it: x: prefix, shared strings, a table per sheet) --------

def _col(index: int) -> str:
    name = ""
    index += 1
    while index:
        index, rem = divmod(index - 1, 26)
        name = chr(65 + rem) + name
    return name


def psix_xlsx(rows=None, drop_column=None) -> bytes:
    data = json.loads((PSIX / "inspections.json").read_text())["rows"] if rows is None else rows
    header = [h for h in data[0] if h != drop_column]
    strings: list[str] = []

    def sid(text):
        if text not in strings:
            strings.append(text)
        return strings.index(text)

    def esc(text):
        return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    sheet_rows = []
    for r, values in enumerate([dict(zip(header, header))] + data, start=1):
        cells = []
        for c, key in enumerate(header):
            value = values.get(key, "")
            if value == "":
                continue
            if r > 1 and key in ("Activity Start Date",):
                cells.append(f'<x:c r="{_col(c)}{r}"><x:v>{value}</x:v></x:c>')
            else:
                cells.append(f'<x:c r="{_col(c)}{r}" t="s"><x:v>{sid(value)}</x:v></x:c>')
        sheet_rows.append(f'<x:row r="{r}">{"".join(cells)}</x:row>')
    ns = 'xmlns:x="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    rel_ns = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
    sheet = f'<?xml version="1.0" encoding="utf-8"?><x:worksheet {rel_ns} {ns}><x:sheetData>{"".join(sheet_rows)}</x:sheetData></x:worksheet>'
    empty = f'<?xml version="1.0" encoding="utf-8"?><x:worksheet {ns}><x:sheetData /></x:worksheet>'
    sst = (f'<?xml version="1.0" encoding="utf-8"?><x:sst {ns}>'
           + "".join(f"<x:si><x:t>{esc(s)}</x:t></x:si>" for s in strings) + "</x:sst>")
    workbook = (f'<?xml version="1.0" encoding="utf-8"?><x:workbook {rel_ns} {ns}><x:sheets>'
                '<x:sheet name="PSIXInspections" sheetId="1" r:id="rId2" />'
                '<x:sheet name="PSIXDeficiencies" sheetId="2" r:id="rId3" /></x:sheets></x:workbook>')
    rels = ('<?xml version="1.0" encoding="utf-8"?><Relationships '
            'xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
            'Target="/xl/worksheets/sheet2.xml" Id="rId3" />'
            '<Relationship Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
            'Target="/xl/worksheets/sheet1.xml" Id="rId2" /></Relationships>')
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("xl/workbook.xml", workbook)
        archive.writestr("xl/_rels/workbook.xml.rels", rels)
        archive.writestr("xl/sharedStrings.xml", sst)
        archive.writestr("xl/worksheets/sheet1.xml", sheet)
        archive.writestr("xl/worksheets/sheet2.xml", empty)
    return buffer.getvalue()


# ---- FCC ULS --------------------------------------------------------------------------------

class FccUlsTests(unittest.TestCase):
    def test_registered(self):
        self.assertIs(get("fcc-uls"), FccUls)
        self.assertEqual((FccUls.id, FccUls.kind), ("fcc-uls", "discover"))

    def test_individual_licensee_name_never_emitted(self):
        candidates = fcc_candidates()
        text = repr(candidates)
        for token in PERSONAL:
            self.assertNotIn(token, text.upper())
        operators = sorted(v for c in candidates for v in facts(c, "operator"))
        self.assertEqual(operators, ["EXAMPLE SPORTFISHING LLC", "Pretend Charters, Inc."])

    def test_same_name_licences_in_different_cities_are_separate_candidates(self):
        same = [c for c in fcc_candidates() if c.name == "SEA EXAMPLE"]
        self.assertEqual(len(same), 2)
        self.assertEqual(sorted(c.port_hint for c in same), ["morro-bay", "san-diego"])
        self.assertEqual(sorted(c.keys["call_sign"] for c in same), ["ZZZ9001", "ZZZ9002"])
        self.assertEqual(len({f.source_url for c in same for f in c.facts}), 2)

    def test_expired_and_cancelled_licences_included_with_status(self):
        by_call = {c.keys["call_sign"]: facts(c, "fcc_licence")[0] for c in fcc_candidates()}
        self.assertEqual(by_call["ZZZ9001"]["status"], "active")
        self.assertEqual(by_call["ZZZ9002"], {"call_sign": "ZZZ9002", "status": "expired", "status_code": "E",
                                              "radio_service": "SA", "grant_date": "2010-03-01",
                                              "expired_date": "2020-03-01", "category": "CHR"})
        self.assertEqual(by_call["ZZZ9003"]["status"], "cancelled")
        self.assertEqual(by_call["ZZZ9003"]["cancellation_date"], "2018-06-01")
        self.assertEqual(by_call["ZZZ9005"]["status"], "terminated")
        active = {c.keys["call_sign"] for c in fcc_candidates(all_statuses=False)}
        self.assertEqual(active, {"ZZZ9001", "ZZZ9007"})

    def test_state_filter_keys_and_categories(self):
        stats = {}
        candidates = list(parse_ship_zip(ship_zip(), "CA", source_id="fcc-uls", rights="public-domain",
                                         retrieved_at=NOW, stats=stats))
        names = {c.name for c in candidates}
        self.assertNotIn("OTHER STATE BOAT", names)  # licensee in Oregon
        self.assertEqual(stats["unnamed"], 1)
        self.assertEqual(stats["candidates"], 5)
        keys = {c.keys["call_sign"]: c.keys for c in candidates}
        self.assertEqual(keys["ZZZ9001"], {"call_sign": "ZZZ9001", "mmsi": "999000001", "uscg_doc": "1234567"})
        self.assertEqual(keys["ZZZ9002"], {"call_sign": "ZZZ9002", "mmsi": "999000002", "state_reg": "CF1234ZZ"})
        self.assertEqual(keys["ZZZ9003"], {"call_sign": "ZZZ9003"})
        self.assertTrue(all(c.port_hint is None for c in candidates))  # no ports given
        charters = list(parse_ship_zip(ship_zip(), "CA", source_id="fcc-uls", rights="public-domain",
                                       retrieved_at=NOW, categories=["chr"]))
        self.assertEqual({c.keys["call_sign"] for c in charters}, {"ZZZ9001", "ZZZ9002"})

    def test_facts_meet_the_operation_contract(self):
        candidates = fcc_candidates()
        assert_ops_contract(self, candidates)
        fact = candidates[0].facts[0]
        self.assertEqual((fact.method, fact.rights, fact.retrieved_at), ("registry", "public-domain", NOW))
        self.assertTrue(fact.source_url.startswith("https://wireless2.fcc.gov/UlsApp/UlsSearch/license.jsp?licKey="))

    def test_changed_layout_raises(self):
        with self.assertRaises(FccFormatError):
            list(parse_ship_zip(ship_zip(drop="SH.dat"), "CA", source_id="fcc-uls", rights="public-domain",
                                retrieved_at=NOW))
        narrow = b"SH|9000001|||ZZZ9001|R||PL|CHR|SEA EXAMPLE|1234567\r\n"
        with self.assertRaises(FccFormatError):
            list(parse_ship_zip(ship_zip(replace={"SH.dat": narrow}), "CA", source_id="fcc-uls",
                                rights="public-domain", retrieved_at=NOW))

    def test_entity_rule(self):
        cases = [("L", "EXAMPLE SPORTFISHING LLC", "", "", True), ("C", "Example Boats, Inc.", "", "", True),
                 ("C", "EXAMPLE CORP", "", "", True), ("P", "EXAMPLE PARTNERS L.P.", "", "", True),
                 ("I", "TESTPERSON, JANE Q", "JANE", "TESTPERSON", False),
                 ("I", "EXAMPLE CHARTERS LLC", "", "", False),          # an individual type is never kept
                 ("C", "PERSONA FICTA INC", "PERSONA", "FICTA", False),  # personal name fields filled
                 ("T", "SAMPLE FAMILY TRUST", "", "", False),          # no entity suffix
                 ("P", "SMITH AND JONES", "", "", False), ("L", "", "", "", False),
                 ("C", "JOHN SMITH D.B.A. SEA LLC", "", "", False),      # dotted DBA
                 ("C", "JOHN SMITH D B A SEA LLC", "", "", False),       # spaced DBA
                 ("C", "JOHN SMITH DOING BUSINESS AS SEA LLC", "", "", False),
                 ("C", "JOHN SMITH IN CARE OF SEA LLC", "", "", False),
                 ("C", "JOHN SMITH TTEE SEA LLC", "", "", False),        # trustee abbreviation
                 ("C", "JANE TESTPERSON C/O SEA EXAMPLE LLC", "", "", False),
                 ("C", "COAST CO LLC", "", "", True),                   # a bare CO is not C/O
                 ("L", "TESTPERSON, JANE LLC", "", "", False),             # SURNAME, GIVEN before the suffix
                 ("C", "JANE TESTPERSON DBA SEA EXAMPLE INC", "", "", False),
                 ("C", "SEA EXAMPLE D/B/A EXAMPLE TOURS CORP", "", "", False),
                 ("C", "SEA EXAMPLE INC C/O JANE TESTPERSON", "", "", False),
                 ("C", "ATTN: JANE TESTPERSON, EXAMPLE CO", "", "", False),
                 ("L", "JANE TESTPERSON TRUSTEE LLC", "", "", False),
                 ("C", "ESTATE OF JANE TESTPERSON INC", "", "", False),
                 ("L", "TESTPERSON ET AL LLC", "", "", False),
                 ("L", "ACME EXAMPLE L.L.C.", "", "", True)]
        for ptype, name, first, last, expected in cases:
            self.assertEqual(is_entity(ptype, name, first, last), expected, name)


# ---- USCG PSIX ------------------------------------------------------------------------------

class PsixParseTests(unittest.TestCase):
    def test_registered(self):
        self.assertIs(get("uscg-psix"), UscgPsix)

    def test_inspections_fold_into_us_flagged_passenger_inspected_vessels(self):
        found = vessels(parse_inspections(psix_xlsx()), "Passenger (Inspected)")
        self.assertEqual([v.vessel_id for v in found], ["9100001", "9100004"])  # foreign and uninspected dropped
        out = list(candidates(found, source_id="uscg-psix", rights="public-domain", retrieved_at=NOW,
                              fallback_url=PSIX_URL))
        first = out[0]
        self.assertEqual(first.name, "SEA EXAMPLE II")  # the name at the latest inspection
        self.assertEqual(first.keys, {"uscg_doc": "1234567", "call_sign": "ZZZ9001"})
        self.assertEqual(facts(first, "year_built"), [1999])
        self.assertEqual(facts(first, "gross_tons"), [45])
        self.assertEqual(facts(first, "uscg_sectors"), [["Sector Los Angeles/Long Beach", "Sector San Diego"]])
        self.assertEqual(facts(first, "uscg_last_inspection"), ["2024-11-04"])
        self.assertEqual(facts(first, "uscg_service"), [{"class": "Passenger Ship", "type": "Passenger (Inspected)"}])
        self.assertEqual(facts(first, "vessel_class"), [])  # inspected does not say party or long-range
        self.assertEqual(first.facts[0].source_url, "https://cgmix.uscg.mil/PSIX/PSIXDetails.aspx?VesselID=9100001")
        self.assertEqual(out[1].keys, {})
        assert_ops_contract(self, out)

    def test_changed_layout_raises(self):
        with self.assertRaises(PsixFormatError):
            parse_inspections(psix_xlsx(drop_column="Vessel Type"))
        with self.assertRaises(PsixFormatError):
            parse_inspections(b"<html>not a workbook</html>")
        with patch("skippercast.fleet.adapters.uscg_psix.MAX_MEMBER", 1000):  # declared size checked before reading
            with self.assertRaisesRegex(PsixFormatError, "larger than"):
                parse_inspections(psix_xlsx())
        form = parse_form((PSIX / "form.html").read_text())
        with self.assertRaises(PsixFormatError):
            search_fields(form, "Humboldt Bay", "Passenger (Inspected)", *_dates())
        with self.assertRaises(PsixFormatError):
            parse_form("<html><form></form></html>")

    def test_search_fields_select_sector_and_service(self):
        form = parse_form((PSIX / "form.html").read_text())
        fields = dict(search_fields(form, "Los Angeles - Long Beach", "Passenger (Inspected)", *_dates()))
        self.assertEqual(fields["DropDownListOriginalUnit"], "4000210")
        self.assertEqual(fields["DropDownListVesselType"], "20")
        self.assertEqual(fields["DropDownListOriginalDistrict"], "ALL")
        self.assertEqual(fields["RadioButtonPortStateControl"], "3")
        self.assertEqual((fields["TextBoxFromDate"], fields["TextBoxToDate"]), ("10/05/2023", "10/05/2026"))
        self.assertEqual(fields["__VIEWSTATE"], "SYNTHETIC-VIEWSTATE-1")
        self.assertNotIn("ButtonReset", fields)


def _dates():
    return date(2023, 10, 5), date(2026, 10, 5)


# ---- through the fleet session (robots, POST bodies, conditional GET) ------------------------------

class _Handler(BaseHTTPRequestHandler):
    def _send(self, status, body=b"", headers=None):
        self.send_response(status)
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        server = self.server
        server.log.append(("GET", self.path, dict(self.headers), b""))
        if self.path == "/robots.txt":
            return self._send(200, server.robots)
        if self.path.startswith("/download/pub/uls/complete/l_ship.zip"):
            if self.headers.get("If-None-Match") == '"ship-1"':
                return self._send(304, headers={"ETag": '"ship-1"'})
            return self._send(200, ship_zip(), {"ETag": '"ship-1"', "Content-Type": "application/zip"})
        if self.path == "/XML/PSIXExportSearch.aspx":
            return self._send(200, (PSIX / "form.html").read_bytes(), {"Content-Type": "text/html"})
        return self._send(404)

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        self.server.log.append(("POST", self.path, dict(self.headers), body))
        fields = parse_qs(body.decode())
        if "ButtonSearch" in fields:
            return self._send(200, (PSIX / "result.html").read_bytes(), {"Content-Type": "text/html"})
        if "ButtonExportExcel" in fields:
            return self._send(200, psix_xlsx(), {"Content-Type": "application/vnd.openxmlformats-officedocument"
                                                                   ".spreadsheetml.sheet"})
        return self._send(400)

    def log_message(self, *args):
        pass


class SessionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        self.server.log = []
        self.server.robots = b"User-agent: *\nDisallow:\n"
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.now = [0.0]

        def factory(host, port, addresses, context=None, timeout=None):
            return HTTPConnection("127.0.0.1", self.server.server_address[1], timeout=timeout)

        def resolver(host, port, type=None):
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]

        def sleep(seconds):
            self.now[0] += seconds

        self.net = FleetSession({"data.fcc.gov", "cgmix.uscg.mil"}, ("fareharbor.com",), sleep=sleep,
                                clock=lambda: self.now[0], connection_factory=factory, resolver=resolver,
                                attempts=1, cache=Path(self.tmp.name) / "cache")
        self.ctx = SimpleNamespace(region=region(), net=self.net, run_dir=Path(self.tmp.name), clock=lambda: NOW)

    def test_fcc_download_uses_conditional_get(self):
        adapter = FccUls()
        first = adapter.discover(binding("fcc-uls", state="CA", url=FCC_URL), self.ctx)
        self.assertFalse(adapter.stats["from_cache"])
        second = adapter.discover(binding("fcc-uls", state="CA", url=FCC_URL), self.ctx)
        self.assertTrue(adapter.stats["from_cache"])
        self.assertEqual(first, second)
        self.assertEqual(len(first), 5)
        downloads = [entry for entry in self.server.log if entry[1].endswith("l_ship.zip")]
        self.assertEqual(downloads[1][2].get("If-None-Match"), '"ship-1"')
        self.assertEqual({c.port_hint for c in first if c.name == "SEA EXAMPLE"}, {"morro-bay", "san-diego"})

    def test_psix_sector_query_through_the_session(self):
        adapter = UscgPsix()
        out = adapter.discover(binding("uscg-psix", sectors=["San Diego", "Los Angeles - Long Beach"],
                                       service="passenger", url=PSIX_URL), self.ctx)
        posts = [entry for entry in self.server.log if entry[0] == "POST"]
        self.assertEqual(len(posts), 4)  # search and export per sector
        search = parse_qs(posts[0][3].decode())
        self.assertEqual(search["DropDownListOriginalUnit"], ["4000100"])
        self.assertEqual(search["DropDownListVesselType"], ["20"])
        self.assertEqual(posts[0][2].get("Content-Type"), "application/x-www-form-urlencoded")
        self.assertEqual(parse_qs(posts[1][3].decode())["__VIEWSTATE"], ["SYNTHETIC-VIEWSTATE-2"])
        self.assertEqual(parse_qs(posts[2][3].decode())["DropDownListOriginalUnit"], ["4000210"])
        self.assertEqual([c.name for c in out], ["SEA EXAMPLE II", "PRETEND CHARTERS"])  # one per vessel
        self.assertEqual(adapter.stats["vessels"], 2)
        assert_ops_contract(self, out)

    def test_psix_robots_refusal_is_a_recorded_skip(self):
        self.server.robots = b"User-agent: *\nDisallow: /XML/\n"
        adapter = UscgPsix()
        out = adapter.discover(binding("uscg-psix", sectors=["San Diego"], url=PSIX_URL), self.ctx)
        self.assertEqual(out, [])
        self.assertEqual(adapter.stats["skips"][0]["reason"], "robots")
        self.assertFalse([entry for entry in self.server.log if entry[1].startswith("/XML/")])


if __name__ == "__main__":
    unittest.main()
