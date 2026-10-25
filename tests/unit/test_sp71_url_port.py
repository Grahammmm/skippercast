"""Synthetic string inputs through the complete fleet normalization module.

No global patches/hooks: ordinary test discovery must not affect peer suites.
The acceptance runner installs process-local offline guards before imports.
"""
import copy
import json
from pathlib import Path
import unittest
from urllib.parse import urlsplit

from skippercast.fleet.normalize import clean_url

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "sp71_url_port" / "urls.json"
CASES = json.loads(FIXTURES.read_text(encoding="utf-8"))


class CleanUrlAuthorityTests(unittest.TestCase):
    def test_primary_bad_port(self):
        case = CASES["baseline"][0]
        # Capture a known product exception as DATA, not a unittest harness error.
        # The assertion and its bytes are identical before and after the repair.
        try:
            observed = {"return": clean_url(case["input"])}
        except ValueError as error:
            observed = {"exception": type(error).__name__, "message": str(error)}
        print("PRIMARY_OBSERVATION=" + json.dumps(observed, sort_keys=True))
        self.assertEqual(observed, {"return": None}, "primary bad port must return None")

    def test_healthy_control(self):
        case = CASES["baseline"][1]
        self.assertEqual(clean_url(case["input"]), case["expected"])


def authority_case(case, group):
    def test(self):
        before = copy.deepcopy(case)
        result = clean_url(case["input"])
        self.assertEqual(result, case.get("expected"), case["name"])
        self.assertEqual(case, before, "normalization must not mutate input")
        if group == "valid_authorities":
            # Parsing the emitted authority must preserve its host and port.
            original, normalized = urlsplit(case["input"]), urlsplit(result)
            self.assertEqual(normalized.hostname, original.hostname.lower())
            self.assertEqual(normalized.port, original.port)
    return test


for _group in ("invalid", "valid_authorities", "preservation"):
    for _case in CASES[_group]:
        setattr(CleanUrlAuthorityTests, "test_" + _group + "_" + _case["name"], authority_case(_case, _group))


if __name__ == "__main__":
    unittest.main()
