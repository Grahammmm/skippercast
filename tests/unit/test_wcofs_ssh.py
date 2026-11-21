"""Offline contract tests for the WCOFS zeta frame converter."""

import unittest

from skippercast.pipeline.wcofs_ssh import ZETA_UNITS, WcofsSshError, ssh_rows


class WcofsSshTests(unittest.TestCase):
    def assert_ssh_error(self, *args, **kwargs):
        with self.assertRaises(WcofsSshError) as caught:
            ssh_rows(*args, **kwargs)
        self.assertIs(type(caught.exception), WcofsSshError)

    def test_c1_module_contract(self):
        """C1: Catch a mutable or changed units set and a changed error base."""
        self.assertIs(type(ZETA_UNITS), frozenset)
        self.assertEqual(ZETA_UNITS, frozenset({"m", "meter", "meters"}))
        self.assertEqual(WcofsSshError.__bases__, (ValueError,))

    def test_c2_masked_regional_frame(self):
        """C2: Catch masked cells affecting the mean, order, or rounding."""
        lat = (35.012345678, 35.04, 35.08)
        lon = (-121.012345678, -120.96, -120.92, -120.88)
        rows = ssh_rows(lat, lon, [
            [0.111, float("nan"), 0.222, 0.333],
            [-9999, 0.444, 0.555, True],
            [0.666, 0.777, 0.888, 0.999],
        ], "m", fill_value=-9999)
        self.assertEqual(rows, [
            {"latitude": lat[0], "longitude": lon[0], "ssh_cm": -44.4},
            {"latitude": lat[0], "longitude": lon[2], "ssh_cm": -33.3},
            {"latitude": lat[0], "longitude": lon[3], "ssh_cm": -22.2},
            {"latitude": lat[1], "longitude": lon[1], "ssh_cm": -11.1},
            {"latitude": lat[1], "longitude": lon[2], "ssh_cm": 0.0},
            {"latitude": lat[2], "longitude": lon[0], "ssh_cm": 11.1},
            {"latitude": lat[2], "longitude": lon[1], "ssh_cm": 22.2},
            {"latitude": lat[2], "longitude": lon[2], "ssh_cm": 33.3},
            {"latitude": lat[2], "longitude": lon[3], "ssh_cm": 44.4},
        ])
        self.assertAlmostEqual(sum(row["ssh_cm"] for row in rows), 0.0)

    def test_c2_unit_spellings_and_range_boundaries(self):
        """C2: Catch rejecting a metres alias or either inclusive endpoint."""
        for units in ("meter", "meters"):
            with self.subTest(units=units):
                rows = ssh_rows([35], [-121, -120], [[-20, 20]], units)
                self.assertEqual(rows, [
                    {"latitude": 35, "longitude": -121, "ssh_cm": -2000.0},
                    {"latitude": 35, "longitude": -120, "ssh_cm": 2000.0},
                ])
                self.assertIs(type(rows[0]["latitude"]), int)
                self.assertIs(type(rows[0]["longitude"]), int)

    def test_c2_only_finite_numeric_non_fill_cells_survive(self):
        """C2: Catch numeric coercion, infinite values, and checking range before fill."""
        fill = 10**400
        row = [float("inf"), -float("inf"), "4", None, 3 + 0j, False, fill, 5]
        self.assertEqual(ssh_rows([35], range(8), [row], "m", fill), [
            {"latitude": 35, "longitude": 7, "ssh_cm": 0.0},
        ])

    def test_c2_fill_uses_equality(self):
        """C2: Catch identity or type checks in place of numeric equality for fill."""
        self.assertEqual(ssh_rows([35], [-121, -120], [[1, 0]], "m", 1.0), [
            {"latitude": 35, "longitude": -120, "ssh_cm": 0.0},
        ])

    def test_c3_rejects_unsupported_units(self):
        """C3: Catch normalization, unknown units, or an unhashable units error leak."""
        for units in ("M", "cm", " meters ", ["m"]):
            with self.subTest(units=units):
                self.assert_ssh_error([35], [-121], [[0]], units)

    def test_c3_rejects_mismatched_shape(self):
        """C3: Catch silently truncating the grid or validating only its first row."""
        for zeta in ([[0, 0]], [[0, 0]] * 3, [[0, 0], [0]], [[0, 0], [0, 0, 0]]):
            with self.subTest(zeta=zeta):
                self.assert_ssh_error([35, 36], [-121, -120], zeta, "m")

    def test_c3_rejects_bad_coordinates_even_on_masked_cells(self):
        """C3: Catch checking coordinates only where a zeta cell survives."""
        for bad in (float("nan"), float("inf"), -float("inf")):
            with self.subTest(coordinate="latitude", bad=bad):
                self.assert_ssh_error([35, bad], [-121], [[0], [None]], "m")
            with self.subTest(coordinate="longitude", bad=bad):
                self.assert_ssh_error([35], [-121, bad], [[0, None]], "m")

    def test_c3_rejects_empty_or_fully_masked_frames(self):
        """C3: Catch returning empty rows or dividing by zero."""
        for lat, lon, zeta in (([], [-121], []), ([35], [], [[]]), ([35], [-121], [[-9999]])):
            with self.subTest(zeta=zeta):
                self.assert_ssh_error(lat, lon, zeta, "m", fill_value=-9999)

    def test_c3_rejects_out_of_range_valid_cells(self):
        """C3: Catch dropping outliers or enforcing only one side of the range."""
        for value in (-20.001, 20.001, 10**400):
            with self.subTest(value=value):
                self.assert_ssh_error([35], [-121, -120], [[0, value]], "m")

    def test_c3_malformed_inputs_do_not_leak_builtin_errors(self):
        """C3: Catch TypeError leaking from lengths or nonnumeric coordinates."""
        for lat, lon, zeta in ((None, [-121], [[0]]), ([35], None, [[0]]),
                               ([35], [-121], None), ([35], [-121], [0]),
                               (["35"], [-121], [[0]])):
            with self.subTest(lat=lat, lon=lon, zeta=zeta):
                self.assert_ssh_error(lat, lon, zeta, "m")
