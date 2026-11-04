"""SC2007-10: the NDBC realtime reader refuses a period or temperature column in unexpected units
(so degF is never published as degC) and keeps the existing 99/999/9999/MM fill handling."""
import unittest

from skippercast.pipeline import parsers

KEYS = "WDIR WSPD GST WVHT DPD APD MWD PRES ATMP WTMP DEWP VIS PTDY TIDE".split()
# The real NDBC realtime2 units line.
UNITS = "degT m/s m/s m sec sec degT hPa degC degC degC nmi hPa ft".split()
ROW = "180 5.0 6.0 1.2 10 6.5 270 1015.0 15.0 16.5 12.0 MM MM MM".split()


def table(keys=KEYS, units=UNITS, row=ROW, **changed):
    units = [changed.get(k, u) for k, u in zip(keys, units)]
    return ("#YY  MM DD hh mm " + " ".join(keys) + "\n#yr  mo dy hr mn " + " ".join(units) +
            "\n2026 09 21 15 50 " + " ".join(row) + "\n")


def without(column):
    i = KEYS.index(column)
    drop = lambda seq: seq[:i] + seq[i + 1:]
    return dict(keys=drop(KEYS), units=drop(UNITS), row=drop(ROW))


SPEC_KEYS = "WVHT SwH SwP WWH WWP SwD WWD STEEPNESS APD MWD".split()
SPEC_UNITS = "m m sec m sec - - - sec degT".split()
SPEC_ROW = dict(zip(SPEC_KEYS, "1.5 1.2 10.0 0.3 5.0 W NW SWELL 6.0 270".split()))


def spec_table(keys=SPEC_KEYS, units=SPEC_UNITS, row=SPEC_ROW, **changed):
    """A synthetic .spec table; `units` may be shorter than `keys` (a truncated units line)."""
    units = [changed.get(k, u) for k, u in zip(keys, units)]
    values = list(row.values()) if isinstance(row, dict) else row
    return ("#YY  MM DD hh mm " + " ".join(keys) + "\n#yr  mo dy hr mn " + " ".join(units) +
            "\n2026 09 21 15 00 " + " ".join(values) + "\n")


class NdbcUnitsTests(unittest.TestCase):
    def refused(self, body, named, spectral=False):
        with self.assertRaises(ValueError) as raised:
            parsers.ndbc(body, "46028", spectral)
        self.assertTrue(str(raised.exception).startswith("Unexpected NDBC units"), raised.exception)
        self.assertIn(named, str(raised.exception))

    def test_real_units_line_parses(self):
        result = parsers.ndbc(table(), "46028")
        obs = result["observations"][0]
        self.assertEqual((obs["DPD"], obs["WTMP"], obs["ATMP"], obs["GST"], obs["APD"]), (10, 16.5, 15.0, 6, 6.5))
        self.assertEqual(result["units"]["WTMP"], "degC")

    def test_water_temperature_in_fahrenheit_is_refused(self):
        self.refused(table(WTMP="degF"), "WTMP 'degF'")

    def test_dominant_period_not_in_sec_is_refused(self):
        self.refused(table(DPD="s"), "DPD 's'")
        self.refused(table(DPD="min"), "DPD 'min'")

    def test_air_temperature_checked_only_when_present(self):
        self.refused(table(ATMP="degF"), "ATMP 'degF'")
        self.assertIsNone(parsers.ndbc(table(**without("ATMP")), "46028")["observations"][0].get("ATMP"))

    def test_gust_and_average_period_checked_when_present(self):
        self.refused(table(GST="kn"), "GST 'kn'")
        self.refused(table(APD="min"), "APD 'min'")
        parsers.ndbc(table(**without("GST")), "46028")
        parsers.ndbc(table(**without("APD")), "46028")

    def test_first_offending_column_in_header_order_is_named(self):
        self.refused(table(WSPD="kn", WTMP="degF"), "WSPD 'kn'")

    def test_missing_unit_for_a_checked_column_is_refused(self):
        self.refused(table(units=UNITS[:8]), "ATMP None")  # units line stops before ATMP/WTMP

    def test_spectral_table_checks_partition_units(self):
        body = "#YY MM DD hh mm WVHT SwH SwP WWH WWP SwD WWD STEEPNESS APD MWD\n" \
               "#yr mo dy hr mn m m sec m sec - - - sec degT\n" \
               "2026 09 21 15 00 1.5 1.2 10.0 0.3 5.0 W NW SWELL 6.0 270\n"
        obs = parsers.ndbc(body, "46028", spectral=True)["observations"][0]
        self.assertEqual((obs["SwH"], obs["SwP"], obs["SwD"]), (1.2, 10, "W"))
        parsers.ndbc(body.replace(" sec degT", " min degT"), "46028", spectral=True)  # APD unchecked in spectral
        self.refused(body.replace("mn m m", "mn ft m"), "WVHT 'ft'", spectral=True)

    def test_spectral_partition_units_refused(self):
        # Exact tokens only: ft is not m, and s / min are not sec. A fill value ("MM", "99") in the
        # measurement does not bypass the header check.
        for column, unit in (("SwH", "ft"), ("WWH", "ft"), ("SwP", "min"), ("SwP", "s"),
                             ("WWP", "min"), ("WWP", "s")):
            for fill in (None, "MM", "99"):
                with self.subTest(column=column, unit=unit, fill=fill):
                    row = dict(SPEC_ROW)
                    if fill:
                        row[column] = fill
                    self.refused(spec_table(row=row, **{column: unit}), f"{column} {unit!r}", spectral=True)

    def test_spectral_partition_unit_missing(self):
        # The units line stops before one required partition field: that field is named with None.
        keys = list(SPEC_KEYS)
        for column in ("SwH", "SwP", "WWH", "WWP"):
            with self.subTest(column=column):
                body = spec_table(units=SPEC_UNITS[:keys.index(column)])
                self.refused(body, f"{column} None", spectral=True)

    def test_spectral_unit_error_uses_header_order(self):
        keys = "WVHT WWP SwH SwP WWH SwD WWD STEEPNESS APD MWD".split()
        units = "m sec m sec m - - - sec degT".split()
        row = "1.5 5.0 1.2 10.0 0.3 W NW SWELL 6.0 270".split()
        # SwH precedes WWP in the dictionary but follows it in this header.
        body = spec_table(keys=keys, units=units, row=row, SwH="ft", WWP="min")
        self.refused(body, "WWP 'min'", spectral=True)
        self.refused(spec_table(SwH="ft", WWP="min"), "SwH 'ft'", spectral=True)

    def test_spectral_good_units_preserve_output(self):
        result = parsers.ndbc(spec_table(), "46028", spectral=True)
        self.assertEqual(result["station"], "46028")
        self.assertEqual(result["sample_at"], "2026-09-21T15:00:00Z")
        self.assertEqual(result["units"], dict(zip(["YY", "MM", "DD", "hh", "mm"] + SPEC_KEYS,
                                                   ["yr", "mo", "dy", "hr", "mn"] + SPEC_UNITS)))
        obs = result["observations"][0]
        self.assertEqual((obs["time"], obs["WVHT"], obs["SwH"], obs["SwP"], obs["WWH"], obs["WWP"], obs["APD"], obs["MWD"]),
                         ("2026-09-21T15:00:00Z", 1.5, 1.2, 10.0, 0.3, 5.0, 6.0, 270))
        self.assertEqual((obs["SwD"], obs["WWD"], obs["STEEPNESS"]), ("W", "NW", "SWELL"))
        for fill in ("MM", "99", "99.0", "999", "999.0", "9999", "9999.0"):
            filled = {k: fill for k in ("SwH", "SwP", "WWH", "WWP")}
            obs = parsers.ndbc(spec_table(row=dict(SPEC_ROW, **filled)), "46028", spectral=True)["observations"][0]
            for column in filled:
                self.assertIsNone(obs[column], (column, fill))
            self.assertEqual((obs["WVHT"], obs["SwD"]), (1.5, "W"))
        # Optional APD stays outside the spectral partition check.
        parsers.ndbc(spec_table(APD="min"), "46028", spectral=True)

    def test_fill_values_become_none(self):
        row = list(ROW)
        for column, value in (("WVHT", "99.00"), ("DPD", "99"), ("WTMP", "999.0"), ("PRES", "9999.0"),
                              ("MWD", "999"), ("WSPD", "MM"), ("WDIR", "99")):
            row[KEYS.index(column)] = value
        obs = parsers.ndbc(table(row=row), "46028")["observations"][0]
        for column in ("WVHT", "DPD", "WTMP", "PRES", "MWD", "WSPD"):
            self.assertIsNone(obs[column], column)
        self.assertEqual(obs["WDIR"], 99)  # 99 is a real direction, not a fill
        self.assertEqual(obs["ATMP"], 15.0)


if __name__ == "__main__":
    unittest.main()
