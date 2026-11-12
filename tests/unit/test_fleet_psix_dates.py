"""PSIX slash-form inspection dates: impossible calendar dates are unavailable. Offline, synthetic rows only."""
import json
import unittest

from skippercast.fleet.adapters.uscg_psix import _excel_date, candidates, parse_inspections, vessels
from tests._support import FIXTURES
from tests.unit.test_fleet_registries import NOW, PSIX_URL, psix_xlsx

ROW = json.loads((FIXTURES / "fleet" / "psix" / "inspections.json").read_text())["rows"][0]
SERVICE = "Passenger (Inspected)"


def built(*specs):
    """specs: (started, name, flag) rows of one invented vessel -> candidates."""
    rows = [dict(ROW, **{"Activity Start Date": d, "Vessel Name": n, "Flag at Time of Activity": f})
            for d, n, f in specs]
    found = vessels(parse_inspections(psix_xlsx(rows)), SERVICE)
    return list(candidates(found, source_id="uscg-psix", rights="public-domain", retrieved_at=NOW,
                           fallback_url=PSIX_URL))


def values(cand, field):
    return [f.value for f in cand.facts if f.field == field]


class PsixDateTests(unittest.TestCase):
    def test_impossible_calendar_is_unavailable(self):
        for bad in ("2/29/2026", "2/30/2026", "4/31/2026", "0/5/2026", "5/0/2026", "13/1/2026",
                    "1/32/2026", "1/1/0000", "2/29/1900", "2/30/2026 00:00:00"):
            self.assertIsNone(_excel_date(bad), bad)

    def test_valid_dates_and_serials_unchanged(self):
        self.assertEqual(_excel_date("2/29/2024"), "2024-02-29")
        self.assertEqual(_excel_date("2/29/2000"), "2000-02-29")
        self.assertEqual(_excel_date("11/4/2024 00:00:00"), "2024-11-04")
        self.assertEqual(_excel_date("45600"), "2024-11-04")
        self.assertEqual(_excel_date("45600.9"), "2024-11-04")
        self.assertIsNone(_excel_date("soon"))

    def test_bad_date_cannot_override_latest_valid_row(self):
        for order in (1, -1):
            specs = [("11/4/2026", "GOOD NAME", "UNITED STATES"), ("13/1/2026", "BAD NAME", "SYNTHETIC FOREIGN")][::order]
            (cand,) = built(*specs)
            self.assertEqual(cand.name, "GOOD NAME")
            self.assertEqual(values(cand, "uscg_last_inspection"), ["2026-11-04"])

    def test_all_undated_keeps_fallback_without_fact(self):
        (cand,) = built(("13/1/2026", "AAA", "UNITED STATES"), ("2/30/2026", "ZZZ", "UNITED STATES"))
        self.assertEqual(cand.name, "ZZZ")
        self.assertEqual(values(cand, "uscg_last_inspection"), [])

    def test_equal_date_name_tiebreak(self):
        (cand,) = built(("11/4/2026", "AAA", "UNITED STATES"), ("11/4/2026", "BBB", "UNITED STATES"))
        self.assertEqual(cand.name, "BBB")


if __name__ == "__main__":
    unittest.main()
