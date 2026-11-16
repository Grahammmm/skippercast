"""RF1201-7: an NDBC table with a repeated column name is refused, never resolved to its last value."""
import copy
import socket
import unittest
from datetime import datetime, timezone
from unittest import mock

from skippercast.pipeline import parsers
from skippercast.pipeline.collect import source

NOW = datetime(2026, 9, 21, 15, 30, tzinfo=timezone.utc)
FIXED = "Duplicate NDBC column names"
STD_PREFIX = "#YY MM DD hh mm "
STD_UNITS = "#yr mo dy hr mn "
STAMP = "2026 09 21 15 00 "


def make(keys, units, values):
    return f"{STD_PREFIX}{keys}\n{STD_UNITS}{units}\n{STAMP}{values}\n"


def std(keys="WVHT DPD WTMP WSPD WVHT", units="m sec degC m/s m", values="1.5 10 16 5 0.0"):
    return make(keys, units, values)


def spec(keys="WVHT SwH SwP WWH WWP WVHT", units="m m sec m sec m", values="1.5 1.2 10 0.3 5 0.0"):
    return make(keys, units, values)


class FakeClient:
    def __init__(self, body):
        self.body, self.requests = body, 0

    def get(self, url, *args):
        self.requests += 1
        return self.body


def run_source(body, spectral, previous=None):
    clients = []

    def factory(now):
        clients.append(FakeClient(body))
        return clients[0]

    def no_network(*args, **kwargs):
        raise AssertionError("network used")

    with mock.patch.object(socket, "socket", no_network):
        row = source("buoy", "Buoy", "buoy", "https://example.invalid/x", 6,
                     lambda c: parsers.ndbc(c.get("u"), "46028", spectral), NOW, previous,
                     client_factory=factory)
    assert len(clients) == 1 and clients[0].requests == 1
    return row


class DuplicateColumnTests(unittest.TestCase):
    def refused(self, body, spectral):
        with self.assertRaises(ValueError) as raised:
            parsers.ndbc(body, "46028", spectral)
        self.assertEqual(str(raised.exception), FIXED)

    def test_duplicate_wave_height_refused_in_both_modes(self):
        cases = {
            False: ("WVHT DPD WTMP WSPD WVHT", "{a} 10 16 5 {b}", "m sec degC m/s {u}"),
            True: ("WVHT SwH SwP WWH WWP WVHT", "{a} 1.2 10 0.3 5 {b}", "m m sec m sec {u}"),
        }
        for spectral, (keys, row, units) in cases.items():
            for a, b in (("1.5", "0.0"), ("0.0", "1.5"), ("1.5", "1.5"), ("MM", "1.5"), ("1.5", "MM")):
                for u in ("m", "ft"):
                    with self.subTest(spectral=spectral, a=a, b=b, unit=u):
                        self.refused(make(keys, units.format(u=u), row.format(a=a, b=b)), spectral)

    def test_any_repeated_header_token_refuses_before_rows(self):
        bad_row = "not a row"
        for keys, units in (
            ("WVHT DPD WTMP WSPD GST GST", "m sec degC m/s m/s m/s"),
            ("WVHT DPD WTMP WSPD APD APD", "m sec degC m/s sec sec"),
            ("WVHT DPD WTMP WSPD FOO FOO", "m sec degC m/s - -"),
        ):
            with self.subTest(keys=keys):
                self.refused(f"{STD_PREFIX}{keys}\n{STD_UNITS}{units}\n{bad_row}\n", False)
        for keys, units in (
            ("WVHT SwH SwP WWH WWP SwD SwD", "m m sec m sec - -"),
            ("WVHT SwH SwP WWH WWP WWD WWD", "m m sec m sec - -"),
        ):
            with self.subTest(keys=keys):
                self.refused(f"{STD_PREFIX}{keys}\n{STD_UNITS}{units}\n{bad_row}\n", True)
        for later in ("YY", "MM"):
            body = f"{STD_PREFIX}WVHT DPD WTMP WSPD {later}\n{STD_UNITS}m sec degC m/s -\n{bad_row}\n"
            with self.subTest(later=later):
                self.refused(body, False)

    def test_source_duplicate_without_previous_fails(self):
        for spectral, body in ((False, std()), (True, spec())):
            with self.subTest(spectral=spectral):
                row = run_source(body, spectral)
                self.assertEqual(row["status"], "failed")
                self.assertIsNone(row["data"])
                self.assertEqual(row["issue"], f"ValueError: {FIXED}")
                self.assertNotIn("last_success_at", row)
                self.assertNotIn("data_retrieved_at", row)
                self.assertEqual(row["requests"], 1)

    def test_source_duplicate_retains_previous_data_and_dates(self):
        for spectral, body, good in ((False, std(), std(keys="WVHT DPD WTMP WSPD", units="m sec degC m/s",
                                                          values="1.5 10 16 5")),
                                     (True, spec(), spec(keys="WVHT SwH SwP WWH WWP", units="m m sec m sec",
                                                         values="1.5 1.2 10 0.3 5"))):
            with self.subTest(spectral=spectral):
                old = run_source(good, spectral)
                self.assertEqual(old["status"], "ok")
                previous = {"data": old["data"], "last_success_at": "2026-09-21T14:00:00Z",
                            "data_retrieved_at": "2026-09-21T14:01:00Z"}
                snapshot = copy.deepcopy(previous)
                row = run_source(body, spectral, previous)
                self.assertEqual(row["status"], "retained")
                self.assertEqual(row["data"], snapshot["data"])
                self.assertEqual(row["data"]["observations"][0]["WVHT"], 1.5)
                self.assertEqual(row["last_success_at"], snapshot["last_success_at"])
                self.assertEqual(row["data_retrieved_at"], snapshot["data_retrieved_at"])
                self.assertEqual(row["issue"], f"ValueError: {FIXED}")
                self.assertEqual(previous, snapshot)
                self.assertEqual(row["requests"], 1)

    def test_unique_headers_preserve_healthy_output(self):
        got = parsers.ndbc(std("WVHT  DPD WTMP   WSPD GST FOO", "m sec degC m/s m/s -", "1.5 10 99 5 MM 7"),
                           "46028", False)
        t = "2026-09-21T15:00:00Z"
        self.assertEqual(got, {
            "station": "46028", "sample_at": t,
            "units": {"YY": "yr", "MM": "mo", "DD": "dy", "hh": "hr", "mm": "mn", "WVHT": "m", "DPD": "sec",
                      "WTMP": "degC", "WSPD": "m/s", "GST": "m/s", "FOO": "-"},
            "observations": [{"time": t, "WVHT": 1.5, "DPD": 10.0, "WTMP": None, "WSPD": 5.0, "GST": None,
                              "FOO": 7.0}]})
        got = parsers.ndbc(spec("WWP WWH SwP SwH WVHT SwD", "sec m sec m m -", "5 0.3 10 1.2 1.5 W"),
                           "46028", True)
        self.assertEqual(got["observations"], [{"time": t, "WWP": 5.0, "WWH": 0.3, "SwP": 10.0, "SwH": 1.2,
                                                "WVHT": 1.5, "SwD": "W"}])
        self.assertEqual(list(got["units"])[5:], ["WWP", "WWH", "SwP", "SwH", "WVHT", "SwD"])
        row = run_source(std("WVHT DPD WTMP WSPD", "m sec degC m/s", "1.5 10 16 5"), False)
        self.assertEqual(row["status"], "ok")


if __name__ == "__main__":
    unittest.main()
