"""PSIX official numbers are admitted as written or not at all (RF0834-6). Offline, synthetic records only."""
import io
import json
import unittest
import zipfile

from skippercast.fleet import ops
from skippercast.fleet.adapters.uscg_psix import candidates, parse_inspections, vessels
from skippercast.fleet.resolve import ResolverConfig, Snapshot, fingerprint, resolve
from tests._support import FIXTURES, ROOT
from tests.unit.test_fleet_registries import NOW, PSIX_URL, psix_xlsx
from tests.unit.test_fleet_resolve import CONFIG, stored

ROW = json.loads((FIXTURES / "fleet" / "psix" / "inspections.json").read_text())["rows"][0]
OFFICIAL = "U.S. Official Number"


def candidate_for(official, *, numeric=False, name=None):
    row = dict(ROW, **{OFFICIAL: official})
    if name:
        row["Vessel Name"] = name
    data = psix_xlsx([row])
    if numeric:  # turn the shared-string official-number cell into a genuine numeric cell with this raw text
        source = zipfile.ZipFile(io.BytesIO(data))
        shared = source.read("xl/sharedStrings.xml").decode()
        sheet = source.read("xl/worksheets/sheet1.xml").decode()
        index = [s.split("</x:t>")[0] for s in shared.split("<x:t>")[1:]].index(official)
        old = f' t="s"><x:v>{index}</x:v>'
        cell = sheet.index(old, sheet.index("<x:row r=\"2\">"))
        sheet = sheet[:cell] + sheet[cell:].replace(old, f"><x:v>{official}</x:v>", 1)
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w") as archive:
            for name in source.namelist():
                archive.writestr(name, sheet if name == "xl/worksheets/sheet1.xml" else source.read(name))
        data = out.getvalue()
    found = vessels(parse_inspections(data), "Passenger (Inspected)")
    return list(candidates(found, source_id="uscg-psix", rights="public-domain", retrieved_at=NOW,
                           fallback_url=PSIX_URL))[0]


def doc_facts(cand):
    return [f for f in cand.facts if f.field == "uscg_doc"]


class PsixOfficialNumberTests(unittest.TestCase):
    def test_official_number_is_not_salvaged_from_bad_text(self):
        for bad in ("123AB4567", "D1234567", "-1234567", "+1234567", "123-4567", "123 4567", "1,234,567",
                    "1.234567E6", "1234567.0", "١٢٣٤٥٦٧", "1234", "123456789", "N/A", "1234567\u00a0X"):
            with self.subTest(bad=bad):
                cand = candidate_for(bad)
                self.assertNotIn("uscg_doc", cand.keys)
                self.assertEqual(doc_facts(cand), [])
                self.assertEqual(cand.keys, {"call_sign": "ZZZ9001"})

    def test_canonical_official_number_is_preserved_exactly(self):
        for text, want in (("12345", "12345"), ("12345678", "12345678"), ("0012345", "0012345"),
                           ("  1234567 ", "1234567")):
            with self.subTest(text=text):
                cand = candidate_for(text)
                self.assertEqual(cand.keys["uscg_doc"], want)
                (fact,) = doc_facts(cand)
                self.assertEqual((fact.value, fact.confidence, fact.method), (want, 0.95, "registry"))

    def test_workbook_cell_paths_do_not_fabricate_keys(self):
        self.assertEqual(candidate_for("1234567", numeric=True).keys["uscg_doc"], "1234567")
        for bad in ("1.234567E6", "1234567.0"):
            with self.subTest(bad=bad):
                self.assertNotIn("uscg_doc", candidate_for(bad, numeric=True).keys)

    def test_other_candidate_evidence_survives_invalid_official(self):
        cand = candidate_for("123AB4567")
        self.assertEqual(cand.name, "SEA EXAMPLE")
        fields = {f.field for f in cand.facts}
        self.assertTrue({"name", "call_sign", "year_built", "uscg_service", "uscg_sectors",
                         "uscg_last_inspection"} <= fields)
        self.assertEqual(cand.keys["call_sign"], "ZZZ9001")

    def test_bad_official_cannot_force_a_wrong_registry_key_hit(self):
        decoy = stored("Unrelated Craft", n=1, uscg_doc="1234567")
        target = stored("Different Boat", n=2, uscg_doc="12345676")
        snapshot = Snapshot([decoy, target])
        bad = candidate_for("1.234567E6", name="Zebra Quartz")
        result = resolve(snapshot, [bad], CONFIG, NOW)
        self.assertNotIn(result.assignments.get(fingerprint(bad)), (decoy["id"], target["id"]))
        for op in result.ops:
            ops.validate_op(op, 0, "CA")
        control = candidate_for("1234567", name="Zebra Quartz")
        good = resolve(snapshot, [control], CONFIG, NOW)
        self.assertEqual(good.assignments[fingerprint(control)], decoy["id"])
        self.assertEqual(good.scores[fingerprint(control)], 1.0)


if __name__ == "__main__":
    unittest.main()
