"""Offline tests for the WCOFS zeta read-side contract."""

import unittest

from skippercast.pipeline.wcofs_ssh import ssh_rows
from skippercast.pipeline.wcofs_zeta import (
    WcofsZetaContractError,
    zeta_contract,
    zeta_query,
    zeta_rows,
)


# Synthetic regular-grid DDS: zeta has no Depth axis, unlike temperature.
GRID = """
    Float32 Latitude[ny = 2][nx = 3];
    Float32 Longitude[ny = 2][nx = 3];
    Float32 temp[time = 1][Depth = 41][ny = 2][nx = 3];
"""
ZETA = "Float32 zeta[time = 1][ny = 2][nx = 3];"
DDS = f"Dataset {{ {GRID} {ZETA} }} frame.nc;"
DAS = '''Attributes {
    temp { String units "Celsius"; }
    zeta {
        String long_name "FREE-SURFACE referenced to mean sea level";
        Float32 _FillValue -9.999e3;
        String units "meters";
    }
}'''


class WcofsZetaTests(unittest.TestCase):
    def assert_contract_error(self, check, fn, *args):
        with self.assertRaisesRegex(WcofsZetaContractError, check) as caught:
            fn(*args)
        assert type(caught.exception) is WcofsZetaContractError
        return caught.exception

    def test_c1_missing_block_is_wrapped(self):
        """C1: Catch a generic ValueError leaking from the missing DAS block."""
        assert WcofsZetaContractError.__bases__ == (ValueError,)
        error = self.assert_contract_error(
            "metadata: zeta", zeta_contract, DDS, 'Attributes { temp { String units "m"; } }',
        )
        assert type(error.__cause__) is ValueError

    def test_c2_complete_metadata(self):
        """C2: Catch swapped dimensions, lost fill, or case-sensitive long_name."""
        result = zeta_contract(DDS, DAS)
        assert result == {"units": "meters", "fill_value": -9999.0, "ny": 2, "nx": 3}
        assert type(result["fill_value"]) is float

    def test_c2_optional_metadata_can_be_absent(self):
        """C2: Catch making optional attributes mandatory or rejecting a metre alias."""
        for units in ("m", "meter"):
            with self.subTest(units=units):
                das = f'Attributes {{ zeta {{ String units "{units}"; }} }}'
                assert zeta_contract(DDS, das) == {
                    "units": units, "fill_value": None, "ny": 2, "nx": 3,
                }

    def test_c2_rejects_wrong_dds_declaration(self):
        """C2: Catch accepting missing, duplicate, or differently shaped zeta."""
        for declaration in (
            "",
            f"{ZETA} {ZETA}",
            ZETA.replace("time = 1", "time = 2"),
            ZETA.replace("[ny", "[Depth = 41][ny"),
            ZETA.replace(";", "[Depth = 41];"),
        ):
            with self.subTest(declaration=declaration):
                dds = f"Dataset {{ {GRID} {declaration} }} frame.nc;"
                self.assert_contract_error("DDS declaration", zeta_contract, dds, DAS)

    def test_c2_rejects_mismatched_grid(self):
        """C2: Catch comparing zeta with itself when the declaration comes last."""
        for axis, old in (("ny", 2), ("nx", 3)):
            declaration = ZETA.replace(f"{axis} = {old}", f"{axis} = {old + 1}")
            for variables in (f"{GRID} {declaration}", f"{declaration} {GRID}"):
                with self.subTest(axis=axis, variables=variables):
                    dds = f"Dataset {{ {variables} }} frame.nc;"
                    self.assert_contract_error("grid dimensions", zeta_contract, dds, DAS)

    def test_c2_rejects_missing_or_wrong_units(self):
        """C2: Catch defaulting missing units or accepting a different scale."""
        for attribute in ('String units "cm";', ""):
            with self.subTest(attribute=attribute):
                das = DAS.replace('String units "meters";', attribute)
                self.assert_contract_error("units", zeta_contract, DDS, das)

    def test_c2_rejects_wrong_long_name(self):
        """C2: Catch checking the units while ignoring an inconsistent long_name."""
        das = DAS.replace("FREE-SURFACE referenced to mean sea level", r'bottom \"elevation\"')
        self.assert_contract_error("long_name", zeta_contract, DDS, das)

    def test_c2_rejects_invalid_fill(self):
        """C2: Catch silently treating a malformed fill as absent or leaking ValueError."""
        das = DAS.replace("-9.999e3", "not-a-number")
        self.assert_contract_error("_FillValue", zeta_contract, DDS, das)

    def test_c3_query(self):
        """C3: Catch axis swaps, stray depth indexes, or off-by-one stops."""
        assert zeta_query(0, 4, 6, 8) == "zeta[0][0:1:4][6:1:8]"
        assert zeta_query(0, 0, 3, 3) == "zeta[0][0:1:0][3:1:3]"

    def test_c3_rejects_bad_index_values(self):
        """C3: Catch validating only some positions or treating bool as int."""
        for position, name in enumerate(("y0", "y1", "x0", "x1")):
            for bad, check in ((1.0, "integer"), (True, "integer"), (-1, "nonnegative")):
                with self.subTest(position=name, bad=bad):
                    bounds: list[int | float] = [1, 2, 3, 4]
                    bounds[position] = bad
                    self.assert_contract_error(f"{name}.*{check}", zeta_query, *bounds)

    def test_c3_rejects_reversed_bounds(self):
        """C3: Catch building a reversed slice on either axis."""
        for bounds in ((2, 1, 3, 4), (1, 2, 4, 3)):
            with self.subTest(bounds=bounds):
                self.assert_contract_error("bounds", zeta_query, *bounds)

    def test_c4_rows_feed_ssh_converter(self):
        """C4: Catch transposition or coercion before SSH masks the missing cells."""
        meta = zeta_contract(DDS, DAS)
        nan = float("nan")
        rows = zeta_rows((0.25, None, nan, -9999.0, 0.75, 0.5), meta["ny"], meta["nx"])
        assert rows == [[0.25, None, nan], [-9999.0, 0.75, 0.5]]
        result = ssh_rows([35.0, 35.04], [-121.0, -120.96, -120.92], rows, meta["units"], meta["fill_value"])
        assert result == [
            {"latitude": 35.0, "longitude": -121.0, "ssh_cm": -25.0},
            {"latitude": 35.04, "longitude": -120.96, "ssh_cm": 25.0},
            {"latitude": 35.04, "longitude": -120.92, "ssh_cm": 0.0},
        ]

    def test_c4_rejects_wrong_value_count(self):
        """C4: Catch truncating extra cells or returning a partial final row."""
        for count in (5, 7):
            with self.subTest(count=count):
                self.assert_contract_error("value count", zeta_rows, range(count), 2, 3)

    def test_c4_rejects_nonpositive_dimensions(self):
        """C4: Catch admitting empty grids or checking only one dimension."""
        for ny, nx in ((0, 3), (2, 0), (-1, 3), (2, -1)):
            with self.subTest(ny=ny, nx=nx):
                self.assert_contract_error("dimensions", zeta_rows, (), ny, nx)
