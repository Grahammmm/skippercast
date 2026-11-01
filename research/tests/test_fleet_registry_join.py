"""The AISBULK-1 registry join (research/scripts/join_fleet_registries.py) on synthetic records.

Offline and private-data free: invented boats, ``999xxxxxx`` MMSIs (the module's US-MID check is widened to
999 for the test), ``ZZZ`` call signs, invented licensees and ZIP codes. Every file is written under a
temporary directory.
"""
from collections import Counter
import contextlib
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from research.lib.paths import ROOT
from research.scripts import join_fleet_registries as J

US = patch.object(J, "US_MIDS", frozenset({"999"}))


def ship_zip(path: Path, licences: list[dict]) -> Path:
    """An l_ship.zip with EN, HD and SH records for the given licences (FCC layout, 0-based positions)."""
    en, hd, sh = [], [], []
    for n, lic in enumerate(licences, start=1):
        usi = str(n)
        f = [""] * 30
        f[0], f[1], f[5], f[16], f[17], f[18] = "EN", usi, "L", "INVENTED TOWN", lic.get("state", "CA"), lic["zip"]
        if lic.get("person"):
            f[7], f[8], f[10], f[23] = "TESTPERSON, JANE", "JANE", "TESTPERSON", "I"
        else:
            f[7], f[23] = lic["entity"], "L"
        en.append("|".join(f))
        h = [""] * 59
        h[0], h[1], h[4], h[5] = "HD", usi, lic["call"], lic.get("status", "A")
        hd.append("|".join(h))
        s = [""] * 27
        s[0], s[1], s[4], s[7], s[8], s[9] = "SH", usi, lic["call"], "FV", "PA", lic["name"]
        s[10], s[16], s[21] = lic.get("official", ""), str(lic.get("length", "")), lic["mmsi"]
        sh.append("|".join(s))
    with zipfile.ZipFile(path, "w") as archive:
        for kind, lines in (("EN", en), ("HD", hd), ("SH", sh)):
            archive.writestr(f"{kind}.dat", "\r\n".join(lines) + "\r\n")
    return path


def state_db(path: Path, statics: list[tuple], presence: list[tuple]) -> Path:
    db = sqlite3.connect(path)
    db.executescript("CREATE TABLE match_statics (mmsi INTEGER PRIMARY KEY, ts INTEGER NOT NULL, source TEXT NOT NULL,"
                     " name TEXT, call_sign TEXT, ship_type INTEGER, length_m REAL, ais_class TEXT);"
                     "CREATE TABLE match_presence (mmsi INTEGER NOT NULL, port_id TEXT NOT NULL, day TEXT NOT NULL,"
                     " PRIMARY KEY (mmsi, port_id, day));")
    db.executemany("INSERT INTO match_statics VALUES (?, 0, 'aisstream', ?, ?, ?, ?, 'A')", statics)
    db.executemany("INSERT INTO match_presence VALUES (?, ?, ?)", presence)
    db.commit()
    db.close()
    return path


def lic(name, call, mmsi, *, status="active", official="", zip_groups=frozenset(), length=None, entity=None,
        state="CA") -> J.Licence:
    return J.Licence(usi=call, call_sign=call, name=name, official=official, mmsi=mmsi, length=length,
                     status=status, licensee=entity, individual=entity is None, state=state, groups=zip_groups)


def static(mmsi, name, call=None, ship_type=30, length=None) -> J.Static:
    return J.Static(mmsi, name, call, ship_type, length)


def psix(name, official, call, unit="Marine Safety Detachment Santa Barbara") -> J.PsixVessel:
    return J.PsixVessel(vessel_id=f"v{official}", name=name, official=official, call_sign=call,
                        flag="UNITED STATES", units={unit}, types={"Passenger (Inspected)"})


def vessel(name, port, vid=None) -> dict:
    return {"name": name, "port_id": port, "vessel_id": vid or f"{name}-{port}", "website": "https://example.test/"}


def by_name(rows):
    return {(r["name"], r["port_id"]): r for r in rows}


SLO = frozenset({"slo"})


class NormalisationTests(unittest.TestCase):
    def test_numerals_distinguish_boats_where_the_first_pass_rule_merged_them(self):
        self.assertNotEqual(J.norm("Sea Example II"), J.norm("Sea Example"))
        self.assertEqual(J.norm("Sea Example II"), J.norm("SEA EXAMPLE 2"))
        self.assertEqual(J.legacy_norm("Sea Example II"), J.legacy_norm("Sea Example"))
        self.assertNotEqual(J.legacy_norm("Test Wave III"), J.legacy_norm("TEST WAVE 3"))

    def test_prefixes_and_parenthetical_notes_drop(self):
        self.assertEqual(J.norm("FV Test Wave"), "TESTWAVE")
        self.assertEqual(J.norm("F/V Test Wave"), "TESTWAVE")
        self.assertEqual(J.norm("Test Wave (as named on harbor page)"), "TESTWAVE")
        self.assertEqual(J.norm("New Test Wave"), "NEWTESTWAVE")

    def test_name_kind(self):
        self.assertEqual(J.name_kind("Example Sportfishing"), "operator")
        self.assertEqual(J.name_kind("Example Charters (LLC)"), "operator")
        self.assertEqual(J.name_kind("Example fleet (vessel names not stated)"), "placeholder")
        self.assertEqual(J.name_kind("Test Wave"), "vessel")

    def test_near_name_is_one_substituted_letter_only(self):
        self.assertTrue(J.near_name("TESTWAVE", "TASTWAVE"))
        self.assertFalse(J.near_name("TESTWAVE", "TESTWAVES"))
        self.assertFalse(J.near_name("WAVE", "WAVY"))

    def test_cut_short_ais_name_matches_by_prefix(self):
        self.assertTrue(J.same_name("EXAMPLEEXAMPLEEXAMPLE", "EXAMPLEEXAMPLEEX", truncated=True))
        self.assertFalse(J.same_name("EXAMPLEEXAMPLEEXAMPLE", "EXAMPLEEXAMPLEEX"))


class LoaderTests(unittest.TestCase):
    def test_fcc_keeps_entities_withholds_individuals_and_never_writes_addresses(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = ship_zip(Path(tmp) / "l_ship.zip", [
                {"name": "Test Wave", "call": "ZZZ9001", "mmsi": "999000001", "zip": "93499", "person": True,
                 "official": "D1234567"},
                {"name": "Sea Example", "call": "ZZZ9002", "mmsi": "999000002", "zip": "92199",
                 "entity": "Example Fishing LLC", "status": "E"},
                {"name": "Unrelated Boat", "call": "ZZZ9003", "mmsi": "999000003", "zip": "92199",
                 "entity": "Other Co LLC"}])
            found = {l.name: l for l in J.load_fcc(path, names={"TESTWAVE", "SEAEXAMPLE"}, mmsis=set(), calls=set(),
                                                   officials=set())}
        self.assertEqual(set(found), {"Test Wave", "Sea Example"})
        wave, sea = found["Test Wave"], found["Sea Example"]
        self.assertTrue(wave.individual)
        self.assertIsNone(wave.licensee)
        self.assertEqual((wave.official, wave.status), ("1234567", "active"))
        self.assertIn("slo", wave.groups)
        self.assertEqual((sea.licensee, sea.status), ("Example Fishing LLC", "expired"))
        text = json.dumps([wave.public(), sea.public()])
        for private in ("TESTPERSON", "JANE", "INVENTED TOWN", "93499", "92199"):
            self.assertNotIn(private, text)
        self.assertIn("individual (withheld)", text)

    def test_ais_state_is_opened_read_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = state_db(Path(tmp) / "state.sqlite", [(999000001, "TEST WAVE", "ZZZ9001", 30, 12.0)],
                            [(999000001, "morro-bay", "2026-10-01"), (999000001, "morro-bay", "2026-10-02")])
            before = hashlib.sha256(path.read_bytes()).hexdigest()
            statics, presence, window = J.load_ais(path)
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), before)
        self.assertEqual(statics["999000001"].call_sign, "ZZZ9001")
        self.assertEqual(presence["999000001"]["morro-bay"], 2)
        self.assertEqual(window, {"first_day": "2026-10-01", "last_day": "2026-10-02"})

    def test_psix_rows_fold_per_vessel(self):
        rows = [{"vessel_id": "1", "name": "TEST WAVE", "official": "1234567", "imo": "", "call_sign": "ZZZ9001",
                 "vessel_class": "", "vessel_type": "Passenger (Inspected)", "tonnage": "", "built": "",
                 "flag": "UNITED STATES", "unit": unit, "started": started}
                for unit, started in (("Sector San Diego", "45000"), ("Sector Los Angeles - Long Beach", "45500"))]
        (found,) = J.fold_psix(rows)
        self.assertEqual((found.official, found.call_sign), ("1234567", "ZZZ9001"))
        self.assertEqual(found.groups(), {"sd", "oc", "la", "channel", "slo"})


@US
class JoinTests(unittest.TestCase):
    def test_call_sign_confirmed_in_licence_data_resolves(self):
        rows = J.join([vessel("Test Wave", "morro-bay")],
                      {"999000001": static("999000001", "TEST WAVE", "ZZZ9001")}, {"999000001": Counter({"morro-bay": 3})},
                      [lic("Test Wave", "ZZZ9001", "999000001", zip_groups=SLO)], [])
        (row,) = rows
        self.assertEqual((row["verdict"], row["mmsi"], row["method"]), ("resolved", "999000001", "licence-call-sign"))
        self.assertIn("call_sign(fcc-licence=ais-static)", row["best"]["keys"])

    def test_name_match_alone_never_resolves_and_a_shared_mmsi_stays_unresolved(self):
        statics = {"999000002": static("999000002", "SEA EXAMPLE", None, 37, 10.0)}
        rows = by_name(J.join([vessel("Sea Example", "morro-bay"), vessel("Sea Example", "port-san-luis")], statics,
                              {"999000002": Counter({"san-francisco": 4})}, [], []))
        for row in rows.values():
            self.assertEqual(row["verdict"], "unresolved")
            self.assertTrue(row["reason"].startswith("uncorroborated"))
            self.assertEqual(row["candidates"][0]["registry_vessels_sharing"], 2)

    def test_foreign_mmsi_and_call_sign_are_contradictions(self):
        statics = {"319000009": static("319000009", "TEST WAVE", "ZZB09", 37, 29.0)}
        (row,) = J.join([vessel("Test Wave", "santa-barbara")], statics, {}, [], [])
        self.assertEqual(row["verdict"], "unresolved")
        self.assertIn("non-us-mmsi(mid 319)", row["reason"])
        self.assertIn("call-sign-not-us-format", row["reason"])

    def test_licence_elsewhere_and_ais_elsewhere_is_reported_wrong(self):
        statics = {"999000003": static("999000003", "TEST WAVE", "ZZZ9003", 30, 11.0)}
        (row,) = J.join([vessel("Test Wave", "morro-bay")], statics, {"999000003": Counter({"san-pedro": 25})},
                        [lic("Test Wave", "ZZZ9003", "999000003", zip_groups=frozenset({"la", "oc"}))], [])
        self.assertEqual(row["verdict"], "unresolved")
        self.assertIn("seen-only-in-other-ports-and-licensee-elsewhere", row["reason"])
        (call,) = J.call_sign_report([row], [lic("Test Wave", "ZZZ9003", "999000003")])
        self.assertTrue(call["verdict"].startswith("licensee elsewhere"))

    def test_official_number_resolves_only_with_home_port_evidence_beyond_the_psix_unit(self):
        records = [psix("TEST WAVE", "1234567", "ZZZ9004")]
        here = [lic("Test Wave", "ZZZ9004", "999000004", official="1234567", zip_groups=SLO)]
        (row,) = J.join([vessel("Test Wave", "morro-bay")], {}, {}, here, records)
        self.assertEqual((row["verdict"], row["method"]), ("resolved", "official-number"))
        away = [lic("Test Wave", "ZZZ9004", "999000004", official="1234567", zip_groups=frozenset({"sd"}))]
        (row,) = J.join([vessel("Test Wave", "morro-bay")], {}, {}, away, records)
        self.assertEqual(row["verdict"], "unresolved")
        self.assertIn("official-number-matches-but-home-port-only-from-psix-unit", row["candidates"][0]["notes"])

    def test_call_sign_of_an_earlier_licence_for_the_same_mmsi_still_confirms(self):
        statics = {"999000005": static("999000005", "TEST WAVE", "ZZZ9050", 60, 20.0)}
        licences = [lic("Test Wave", "ZZZ9050", "999000005", status="expired"),
                    lic("Test Wave", "ZZZ9051", "999000005", zip_groups=SLO)]
        (row,) = J.join([vessel("Test Wave", "morro-bay")], statics, {"999000005": Counter({"morro-bay": 2})},
                        licences, [])
        self.assertEqual(row["verdict"], "resolved")
        self.assertIn("call_sign(fcc-licence=ais-static, earlier licence)", row["best"]["keys"])

    def test_call_sign_licensed_under_another_name_contradicts(self):
        statics = {"999000006": static("999000006", "TEST WAVE", "ZZZ9060", 30, 10.0)}
        licences = [lic("Other Boat", "ZZZ9060", "999000006", status="cancelled"),
                    lic("Test Wave", "ZZZ9061", "999000006", zip_groups=SLO)]
        (row,) = J.join([vessel("Test Wave", "morro-bay")], statics, {"999000006": Counter({"morro-bay": 2})},
                        licences, [])
        self.assertEqual(row["verdict"], "unresolved")
        self.assertIn("call-sign-licensed-under-another-name", row["reason"])

    def test_on_air_licence_beats_a_superseded_licence_only_mmsi(self):
        # One official number on two active licences: the stale one is never resolved by official number,
        # the MMSI that broadcasts the name and call sign at the home port is.
        records = [psix("TEST WAVE", "7654321", "ZZZ9071")]
        licences = [lic("Test Wave", "ZZZ9070", "999000070", official="7654321", zip_groups=SLO),
                    lic("Tast Wave", "ZZZ9071", "999000071", official="7654321", zip_groups=SLO)]
        statics = {"999000071": static("999000071", "TEST WAVE", "ZZZ9071", 60, 24.0)}
        (row,) = J.join([vessel("Test Wave", "morro-bay")], statics, {"999000071": Counter({"morro-bay": 8})},
                        licences, records)
        self.assertEqual((row["verdict"], row["mmsi"]), ("resolved", "999000071"))
        stale = next(c for c in row["candidates"] if c["mmsi"] == "999000070")
        self.assertEqual(stale["methods"], [])
        self.assertIn("official-number-also-points-at(999000071)", stale["notes"])

    def test_licence_only_mmsi_with_an_unlicensed_rival_on_air_is_ambiguous(self):
        records = [psix("TEST WAVE", "1111111", "ZZZ9080")]
        licences = [lic("Test Wave", "ZZZ9080", "999000080", official="1111111", zip_groups=SLO)]
        statics = {"999000081": static("999000081", "TEST WAVE", None, 30, 12.0)}
        (row,) = J.join([vessel("Test Wave", "morro-bay")], statics, {"999000081": Counter({"morro-bay": 5})},
                        licences, records)
        self.assertEqual(row["verdict"], "unresolved")
        self.assertTrue(row["reason"].startswith("ambiguous"))

    def test_summary_is_counts_only(self):
        rows = J.join([vessel("Test Wave", "morro-bay"), vessel("Example Sportfishing", "san-diego")],
                      {"999000001": static("999000001", "TEST WAVE", "ZZZ9001")},
                      {"999000001": Counter({"morro-bay": 3})},
                      [lic("Test Wave", "ZZZ9001", "999000001", zip_groups=SLO, entity="Example Fishing LLC")], [])
        counts = J.summary(rows)
        self.assertEqual((counts["resolved"], counts["remaining"]), (1, 1))
        self.assertEqual(counts["remaining_by_name_kind"], {"operator": 1})
        text = json.dumps(counts)
        for private in ("Test Wave", "TEST WAVE", "999000001", "ZZZ9001", "Example"):
            self.assertNotIn(private, text)


class CommandTests(unittest.TestCase):
    def test_refuses_an_output_directory_inside_the_repository(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                J.main(["--resolved", f"{tmp}/r.jsonl", "--state", f"{tmp}/s.sqlite", "--fcc", f"{tmp}/l.zip",
                        "--out", str(ROOT / "var" / "aisbulk-test")])
        self.assertFalse((ROOT / "var" / "aisbulk-test").exists())

    @US
    def test_writes_private_table_and_prints_counts_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / "resolved.jsonl").write_text(json.dumps(vessel("Test Wave", "morro-bay")) + "\n")
            state = state_db(tmp / "state.sqlite", [(999000001, "TEST WAVE", "ZZZ9001", 30, 12.0)],
                             [(999000001, "morro-bay", "2026-10-01")])
            fcc = ship_zip(tmp / "l_ship.zip", [{"name": "Test Wave", "call": "ZZZ9001", "mmsi": "999000001",
                                                 "zip": "93499", "entity": "Example Fishing LLC", "length": 39}])
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                J.main(["--resolved", str(tmp / "resolved.jsonl"), "--state", str(state), "--fcc", str(fcc),
                        "--out", str(tmp / "out")])
            counts = json.loads(out.getvalue())
            table = (tmp / "out" / "join.md").read_text()
            data = json.loads((tmp / "out" / "join.json").read_text())
        self.assertEqual((counts["resolved"], counts["remaining"]), (1, 0))
        self.assertNotIn("Test Wave", out.getvalue())
        self.assertNotIn("999000001", out.getvalue())
        self.assertIn("| Test Wave | morro-bay | resolved | 999000001 | ZZZ9001 |", table)
        self.assertEqual(data["rows"][0]["best"]["licence"]["licensee"], "Example Fishing LLC")
        self.assertNotIn("93499", json.dumps(data))


if __name__ == "__main__":
    unittest.main()
