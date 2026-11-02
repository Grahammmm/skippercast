"""SC2007-11: the daily model check verifies every requested hourly variable's unit."""
from urllib.parse import parse_qs, urlsplit

import pytest

from skippercast.pipeline import collect
from skippercast.pipeline.collect import expected_units, model_loader

POINTS = [("A", 35.3, -120.9), ("B", 35.4, -121.0)]
TIMES = [1790000000, 1790003600]


def requested(model):
    url, _ = model_loader(model, POINTS)
    return parse_qs(urlsplit(url).query)["hourly"][0].split(",")


def point(model, **override):
    variables = requested(model)
    units = {"time": "unixtime", **expected_units(model in ("ecmwf_wam", "ncep_gfswave016"))}
    for var, unit in override.items():
        if unit is None:
            units.pop(var)
        else:
            units[var] = unit
    hourly = {"time": TIMES, **{v: [1.0, 2.0] for v in variables}}
    return {"latitude": 35.3, "longitude": -120.9, "utc_offset_seconds": 0, "hourly_units": units, "hourly": hourly}


def run(monkeypatch, model, points):
    monkeypatch.setattr(collect.forecast_local, "meta", lambda m, c: {"last_run_initialisation_time": 1790000000})
    monkeypatch.setattr(collect.forecast_local, "sample", lambda m, params, c: points)
    _, load = model_loader(model, POINTS)
    return load(None)


@pytest.mark.parametrize("model", ["ecmwf_wam", "ncep_gfswave016", "gfs_global", "ecmwf_ifs025"])
def test_all_units_right_returns_record(monkeypatch, model):
    record = run(monkeypatch, model, [point(model), point(model)])
    assert record["model"] == model
    assert record["sample_at"] == "2026-09-21T14:13:20Z"
    assert len(record["points"]) == 2 and record["meta"]["last_run_initialisation_time"] == 1790000000
    assert [p["name"] for p in record["requested_points"]] == ["A", "B"]


@pytest.mark.parametrize("model,var,unit", [
    ("ecmwf_wam", "swell_wave_height", "m"),
    ("ncep_gfswave016", "swell_wave_height", "m"),
    ("ecmwf_wam", "secondary_swell_wave_direction", "deg"),
    ("ecmwf_wam", "wind_wave_period", "min"),
    ("ecmwf_wam", "secondary_swell_wave_period", None),
    ("gfs_global", "temperature_2m", "°C"),
    ("gfs_global", "visibility", "ft"),
    ("gfs_global", "weather_code", None),
    ("ecmwf_ifs025", "precipitation", "inch"),
    ("ecmwf_ifs025", "cloud_cover", ""),
    ("ecmwf_ifs025", "wind_direction_10m", "deg"),
])
def test_changed_unit_fails_naming_variable(monkeypatch, model, var, unit):
    with pytest.raises(ValueError) as err:
        run(monkeypatch, model, [point(model, **{var: unit}), point(model)])
    assert str(err.value) == f"Forecast units changed: {var} {unit!r}"


@pytest.mark.parametrize("model,var,unit", [("ecmwf_wam", "wind_wave_direction", "rad"),
                                            ("gfs_global", "temperature_2m", "°C")])
def test_mismatch_on_second_point_only_still_fails(monkeypatch, model, var, unit):
    with pytest.raises(ValueError, match=f"^Forecast units changed: {var} "):
        run(monkeypatch, model, [point(model), point(model, **{var: unit})])


def test_wave_height_case_and_whitespace_are_not_accepted(monkeypatch):
    for bad in ("FT", " ft", "feet"):
        with pytest.raises(ValueError, match="^Forecast units changed: wave_height "):
            run(monkeypatch, "ecmwf_wam", [point("ecmwf_wam", wave_height=bad), point("ecmwf_wam")])


@pytest.mark.parametrize("model,wave", [("ecmwf_wam", True), ("ncep_gfswave016", True),
                                        ("gfs_global", False), ("ecmwf_ifs025", False)])
def test_every_requested_variable_has_one_expected_unit(model, wave):
    variables = requested(model)
    assert len(variables) == len(set(variables))
    assert set(expected_units(wave)) == set(variables)
