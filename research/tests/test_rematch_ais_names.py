"""The AISMATCH-2 name re-match (research/scripts/rematch_ais_names.py) on synthetic records.

Offline and private-data free: invented boats, ``999xxxxxx`` MMSIs (the US-MID check is widened to 999), ``ZZZ`` call
signs. Files are written under a temporary directory only.
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

from research.scripts import join_fleet_registries as J
from research.scripts import rematch_ais_names as M

US = patch.object(J, "US_MIDS", frozenset({"999"}))


def static(mmsi, name, call=None, ship_type=37, length=12.0):
    return J.Static(str(mmsi), name, call, ship_type, length)


def vessel(vid, name, port="san-diego"):
    return {"vessel_id": vid, "name": name, "port_id": port}


def run(registry, statics, presence=None):
    return M.rematch(registry, {s.mmsi: s for s in statics},
                     {m: Counter(p) for m, p in (presence or {}).items()})


class FoldingRules(unittest.TestCase):
    CASES = {
        "R1-ampersand-and": ("Sea Wolf & Sons", "SEA WOLF AND SONS"),
        "R2-generational-jr-sr": ("Capt Dave Jr", "CAPT DAVE"),
        "R3-numerals-words-roman": ("Sea Fox Two", "SEA FOX 2"),
        "R4-articles": ("El Pescador Grande", "PESCADOR GRANDE"),
        "R5-abbreviations": ("Capt Kirk Star", "CAPTAIN KIRK STAR"),
        "R6-possessive-plural-s": ("Nina's Pride", "NINA PRIDE"),
    }

    def test_each_exact_fold_matches_and_is_reported_under_its_rule(self):
        for rule, (ours, theirs) in self.CASES.items():
            with self.subTest(rule=rule):
                rep = run([vessel("v1", ours)], [static(999000001, theirs)])
                self.assertEqual([p["rule"] for p in rep["pairs"]], [rule])
                self.assertEqual(rep["counts"]["newly_matched_vessels"], 1)
                self.assertEqual(rep["counts"]["per_rule"][rule]["clean"], 1)

    def test_a_name_the_base_rule_already_matches_is_not_new(self):
        rep = run([vessel("v1", "Sea Fox")], [static(999000001, "SEA FOX")])
        self.assertEqual(rep["counts"]["matched_aisbulk1_rule"], 1)
        self.assertEqual(rep["pairs"], [])

    def test_a_different_numbered_boat_is_not_a_prefix_match(self):
        rep = run([vessel("v1", "Sea Hunter Fleet")], [static(999000001, "SEA HUNTER FLEET 2")])
        self.assertEqual(rep["pairs"], [])

    def test_one_generic_word_is_not_an_identity(self):
        rep = run([vessel("v1", "Spirit of Adventure")], [static(999000001, "SPIRIT")])
        self.assertEqual(rep["pairs"], [])


@US
class Corroboration(unittest.TestCase):
    def test_a_name_never_resolves_and_a_bare_match_is_a_candidate(self):
        rep = run([vessel("v1", "Sea Fox Two")], [static(999000001, "SEA FOX 2")])
        self.assertEqual(rep["pairs"][0]["status"], "candidate")
        self.assertEqual(rep["counts"]["resolved_by_this_tool"], 0)
        self.assertNotIn("resolved", {p["status"] for p in rep["pairs"]})

    def test_home_port_presence_corroborates_an_exact_fold(self):
        rep = run([vessel("v1", "Sea Fox Two")], [static(999000001, "SEA FOX 2")],
                  {"999000001": {"san-diego": 1}})
        self.assertEqual(rep["pairs"][0]["status"], "corroborated")

    def test_a_weak_rule_needs_three_home_port_days(self):
        ours, theirs = [vessel("v1", "Outrider")], [static(999000001, "OUTSIDER")]
        self.assertEqual(run(ours, theirs, {"999000001": {"san-diego": 2}})["pairs"][0]["status"], "candidate")
        self.assertEqual(run(ours, theirs, {"999000001": {"san-diego": 3}})["pairs"][0]["status"], "corroborated")

    def test_a_contradiction_blocks_corroboration(self):
        rep = run([vessel("v1", "Sea Fox Two")], [static(999000001, "SEA FOX 2", ship_type=70)],
                  {"999000001": {"san-diego": 5}})
        self.assertEqual(rep["pairs"][0]["status"], "contradicted")

    def test_the_patriot_trap_one_mmsi_for_two_ports_is_ambiguous_never_corroborated(self):
        rep = run([vessel("v1", "Sea Fox Two", "san-diego"), vessel("v2", "Sea Fox Two", "long-beach")],
                  [static(999000001, "SEA FOX 2")], {"999000001": {"san-diego": 9}})
        self.assertEqual(len(rep["pairs"]), 2)
        self.assertEqual({p["status"] for p in rep["pairs"]}, {"ambiguous"})
        self.assertEqual(rep["counts"]["newly_matched_ambiguous"], 2)

    def test_the_same_trap_among_base_rule_matches_is_counted(self):
        rep = run([vessel("v1", "Sea Fox 2", "san-diego"), vessel("v2", "Sea Fox 2", "long-beach")],
                  [static(999000001, "SEA FOX 2")])
        self.assertEqual(rep["counts"]["matched_aisbulk1_rule_ambiguous"], 2)

    def test_two_mmsis_for_one_name_are_ambiguous(self):
        rep = run([vessel("v1", "Sea Fox Two")],
                  [static(999000001, "SEA FOX 2"), static(999000002, "SEA FOX 2")],
                  {"999000001": {"san-diego": 9}})
        self.assertEqual({p["status"] for p in rep["pairs"]}, {"ambiguous"})
        self.assertEqual(rep["counts"]["newly_matched_ambiguous"], 1)
        self.assertEqual(rep["counts"]["newly_matched_clean"], 0)

    def test_call_sign_on_a_prior_licence_corroborates(self):
        lic = {("999000001", "WZZ1234"): {"status": "active", "name": "Sea Fox Two", "mmsi": "999000001",
                                          "call_sign": "WZZ1234"}}
        rep = M.rematch([vessel("v1", "Sea Fox Two")], {"999000001": static(999000001, "SEA FOX 2", "WZZ1234")},
                        {}, lic)
        self.assertEqual(rep["pairs"][0]["status"], "corroborated")


class Unmatched(unittest.TestCase):
    def test_causes(self):
        rep = run([vessel("v1", "Zephyrine Quest"), vessel("v2", "Zephyrine Star Quest"), vessel("v3", "Boat name not stated")],
                  [static(999000001, "ZEPHYRINE ONE")])
        causes = {u["name"]: u["cause"] for u in rep["unmatched"]}
        self.assertEqual(causes["Boat name not stated"], "no-vessel-name-in-registry")
        self.assertEqual(causes["Zephyrine Quest"], "name-not-reconciled")


class ReadOnly(unittest.TestCase):
    def test_the_state_is_hashed_before_and_after_and_not_changed(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            state = tmp / "state.sqlite"
            db = sqlite3.connect(state)
            db.executescript("CREATE TABLE match_statics (mmsi INTEGER PRIMARY KEY, ts INTEGER NOT NULL, source TEXT "
                             "NOT NULL, name TEXT, call_sign TEXT, ship_type INTEGER, length_m REAL, ais_class TEXT);"
                             "CREATE TABLE match_presence (mmsi INTEGER NOT NULL, port_id TEXT NOT NULL, day TEXT NOT "
                             "NULL, PRIMARY KEY (mmsi, port_id, day));")
            db.execute("INSERT INTO match_statics VALUES (999000001, 0, 'x', 'SEA FOX 2', NULL, 37, 12.0, 'A')")
            db.execute("INSERT INTO match_presence VALUES (999000001, 'san-diego', '2026-10-06')")
            db.commit()
            db.close()
            resolved = tmp / "resolved.jsonl"
            resolved.write_text(json.dumps(vessel("v1", "Sea Fox Two")) + "\n")
            before = hashlib.sha256(state.read_bytes()).hexdigest()
            out = tmp / "out"
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = M.main(["--resolved", str(resolved), "--state", str(state), "--out", str(out)])
            self.assertEqual(code, 0)
            self.assertEqual(hashlib.sha256(state.read_bytes()).hexdigest(), before)
            counts = json.loads(buf.getvalue())
            self.assertTrue(counts["ais_state_read_only_proof"]["unchanged"])
            self.assertNotIn("999000001", buf.getvalue())
            self.assertNotIn("999000001", (out / "pr-table.md").read_text())
            self.assertIn("999000001", (out / "pairs.md").read_text())

    def test_out_inside_the_repository_is_refused(self):
        with self.assertRaises(SystemExit):
            with contextlib.redirect_stderr(io.StringIO()):
                M.main(["--resolved", "a", "--state", "b", "--out", str(J.ROOT / "var" / "x")])


if __name__ == "__main__":
    unittest.main()
