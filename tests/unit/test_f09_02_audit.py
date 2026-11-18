"""F09-02: a square NetCDF grid can hide swapped named axes."""

from datetime import datetime, timezone
from io import BytesIO

import pytest


pytestmark = pytest.mark.gis  # The reserved unit path needs the survey tier's SciPy.
GRID_DIMS = ("time", "lat", "lon")
WHEN = datetime(2000, 1, 1, tzinfo=timezone.utc)
BOUNDS = {"latitude": [-.0625, .125], "longitude": [-.125, .0625]}
FIELDS = ("u", "v", "number_of_sites", "hdop")


def decode(*, transposed=(), axis=None):
    import numpy as np
    from scipy.io import netcdf_file

    from skippercast.pipeline.noaa_hfr import read_subset

    stream = BytesIO()
    with netcdf_file(stream, mode="w") as nc:
        for name, values, dtype in (("time", [946684800], "i"), ("lat", [0, .0625], "f"),
                                    ("lon", [-.0625, 0], "f")):
            nc.createDimension(name, len(values))
            dimension = name
            if name == axis:
                dimension = "other"
                nc.createDimension(dimension, len(values))
            nc.createVariable(name, dtype, (dimension,))[:] = values
        nc.variables["time"].units = "seconds since 1970-01-01"
        nc.createVariable("depth", "f", ()).data[...] = 1
        for name, values in zip(FIELDS, (((1, 2), (3, 4)), ((-.5, -1), (-1.5, -2)),
                                         ((2, 3), (4, 5)), ((.25, .5), (.75, 1)))):
            dims = GRID_DIMS
            data = np.array([values])
            if name in transposed:
                dims = ("time", "lon", "lat")
                data = data.swapaxes(1, 2)
            nc.createVariable(name, "f", dims)[:] = data
        for name, direction in (("u", "eastward"), ("v", "northward")):
            nc.variables[name].units = "m s-1"
            nc.variables[name].standard_name = f"surface_{direction}_sea_water_velocity"
        nc.variables["number_of_sites"].units = "count"
        nc.flush()
        body = stream.getvalue()
    return read_subset(body, BOUNDS, WHEN, [.0625, .0625])


def test_canonical_square_grid_pairs_vectors_and_quality_with_locations():
    decoded = decode()
    assert (decoded["valid_cells"], decoded["total_cells"]) == (4, 4)
    keys = ("latitude", "longitude", "water_u", "water_v", "number_of_sites", "hdop")
    assert [tuple(row[key] for key in keys) for row in decoded["samples"]] == [
        (0, -.0625, 1, -.5, 2, .25),
        (0, 0, 2, -1, 3, .5),
        (.0625, -.0625, 3, -1.5, 4, .75),
        (.0625, 0, 4, -2, 5, 1),
    ]


@pytest.mark.parametrize("transposed", [FIELDS, *((field,) for field in FIELDS)])
def test_transposed_square_grid_fields_are_refused(transposed):
    with pytest.raises(ValueError, match="unsupported dimension layout"):
        decode(transposed=transposed)


@pytest.mark.parametrize("axis", GRID_DIMS)
def test_coordinate_on_same_length_but_unrelated_dimension_is_refused(axis):
    with pytest.raises(ValueError, match="axes changed"):
        decode(axis=axis)
