from copy import deepcopy
from datetime import datetime, timedelta, timezone
import math
import sys

import pytest

from skippercast.pipeline.eddies import EddyFeature, eddies_for
from skippercast.pipeline.eddies_tile import EddyTileError, eddies_tile, read_eddies_tile
from tests.unit.test_eddies import _vortex

_STAMP = "2026-11-20T00:30:00Z"
_FRAME = datetime(2026, 11, 20, 0, 30, tzinfo=timezone.utc)


def _feature(lon: float = -123.123456, diameter: float = 12.344) -> EddyFeature:
    return {
        "outline": [[lon, 38.123456], [lon + 0.1, 38.123456], [lon + 0.1, 38.223456],
                    [lon, 38.223456], [lon, 38.123456]],
        "sense": "ccw",
        "diameter_km": diameter,
        "ow_min": -0.00001234678,
    }


def test_c1_c3_naive_frame_time():
    """C1: Bad frame times must be catchable as ValueError, not silently treated as local time (C3)."""
    with pytest.raises(ValueError) as exc:
        eddies_tile(_FRAME.replace(tzinfo=None), [])
    assert exc.type is EddyTileError
    assert "frame_time" in str(exc.value)


def test_c2_rounding_order_and_input_preservation():
    """C2: Sort on rounded size before outline, without rounding or reordering the caller's data."""
    features = [_feature(-122.123456, 12.344), _feature(-123.123456, 12.341), _feature(-121.123456, 15.006)]
    features[2]["sense"] = "cw"
    original = deepcopy(features)
    local_time = datetime(2026, 11, 19, 16, 30, 0, 999999, tzinfo=timezone(timedelta(hours=-8)))
    assert eddies_tile(local_time, features) == {
        "frame_time": _STAMP,
        "features": [
            {"outline": [[-121.12346, 38.12346], [-121.02346, 38.12346], [-121.02346, 38.22346],
                         [-121.12346, 38.22346], [-121.12346, 38.12346]],
             "sense": "cw", "diameter_km": 15.01, "ow_min": -0.00001235},
            {"outline": [[-123.12346, 38.12346], [-123.02346, 38.12346], [-123.02346, 38.22346],
                         [-123.12346, 38.22346], [-123.12346, 38.12346]],
             "sense": "ccw", "diameter_km": 12.34, "ow_min": -0.00001235},
            {"outline": [[-122.12346, 38.12346], [-122.02346, 38.12346], [-122.02346, 38.22346],
                         [-122.12346, 38.22346], [-122.12346, 38.12346]],
             "sense": "ccw", "diameter_km": 12.34, "ow_min": -0.00001235},
        ],
    }
    assert features == original


def test_c2_c4_empty_tile():
    """C2: A frame with no eddies retains its timestamp and empty array, and is readable (C4)."""
    expected = {"frame_time": _STAMP, "features": []}
    doc = eddies_tile(_FRAME, [])
    assert doc == expected
    assert read_eddies_tile(doc) == expected


def _broken_feature(field, value):
    feature = dict(_feature())
    if field is None:
        del feature["ow_min"]
    else:
        feature[field] = value
    return feature


@pytest.mark.parametrize(("bad_feature", "field"), [
    (None, ""),
    (_broken_feature(None, None), ""),
    (_broken_feature("extra", True), ""),
    (_broken_feature("sense", "CW"), "sense"),
    (_broken_feature("outline", None), "outline"),
    (_broken_feature("outline", [[0, 0], [1, 0], [1, 1], [0, 0]]), "outline"),
    (_broken_feature("outline", [[0, 0], [1, 0], [1, 1], [0, 1], [0.000001, 0]]), "outline"),
    *[(_broken_feature("outline", [[0, 0], point, [1, 1], [0, 1], [0, 0]]), "outline")
      for point in (None, [1], [1, 2, 3], ["1", 0], [0, True], [math.nan, 0], [0, math.inf],
                    [-181, 0], [181, 0], [0, -91], [0, 91])],
    *[(_broken_feature("diameter_km", value), "diameter_km")
      for value in (True, "1", math.nan, math.inf, 0, -1, 10**400)],
    *[(_broken_feature("ow_min", value), "ow_min")
      for value in (False, "-1", math.nan, -math.inf, -0.0, 1)],
])
def test_c3_c4_bad_feature_is_rejected_with_input_index(bad_feature, field):
    """C3: Neither API may coerce, round away or overlook a defect in a later feature (C4)."""
    features = [_feature(), bad_feature]
    label = f"features[1].{field}" if field else "features[1] "
    with pytest.raises(EddyTileError) as encode_exc:
        eddies_tile(_FRAME, features)
    with pytest.raises(EddyTileError) as read_exc:
        read_eddies_tile({"frame_time": _STAMP, "features": features})
    assert encode_exc.type is read_exc.type is EddyTileError
    assert str(encode_exc.value).startswith(label)
    assert str(read_exc.value).startswith(label)


@pytest.mark.parametrize(("field", "value"), [("diameter_km", 0.0038), ("ow_min", -sys.float_info.max)])
def test_c3_rejects_values_invalidated_by_rounding(field, value):
    """C3: A positive size can round to zero and a finite OW minimum can round to infinity."""
    features = [_feature(), _broken_feature(field, value)]
    with pytest.raises(EddyTileError) as exc:
        eddies_tile(_FRAME, features)
    assert exc.type is EddyTileError
    assert str(exc.value).startswith(f"features[1].{field}")
    assert str(exc.value).endswith("after rounding")


@pytest.mark.parametrize(("doc", "label"), [
    (None, "tile"),
    ({"features": []}, "tile"),
    ({"frame_time": _STAMP}, "tile"),
    ({"frame_time": _STAMP, "features": [], "extra": True}, "tile"),
    ({"frame_time": _STAMP, "features": ()}, "features"),
    *[({"frame_time": stamp, "features": []}, "frame_time") for stamp in (
        42, "2026-11-20T00:30:00", "2026-11-20T00:30:00+01:00", "2026-11-20T00:30:00-00:00",
        "2026-11-20+00:00", "2026-11-20x00:30:00Z", "2026-02-30T00:30:00Z",
    )],
])
def test_c4_rejects_malformed_document(doc, label):
    """C4: The reader must reject malformed containers, timestamps and non-UTC zone spellings."""
    with pytest.raises(EddyTileError) as exc:
        read_eddies_tile(doc)
    assert exc.type is EddyTileError
    assert str(exc.value).startswith(label)


def test_c4_reader_preserves_noncanonical_but_valid_document():
    """C4: An explicit UTC offset, bounds, extra precision and existing feature order survive reading."""
    doc = {"frame_time": "2026-11-20T00:30:00.123+00:00", "features": [_feature(), {
        "outline": [[-180, -90], [180, -90], [180, 90], [-180, 90], [-180, -90]],
        "sense": "cw", "diameter_km": 22.12345, "ow_min": -0.000009876543,
    }]}
    original = deepcopy(doc)
    assert read_eddies_tile(doc) == original
    assert doc == original


def test_c4_detector_output_round_trips():
    """C4: The real offline detector's ring, sense and metrics must survive the producer/reader seam."""
    feature, = eddies_for(*_vortex(), _FRAME)
    expected = {"frame_time": _STAMP, "features": [{
        "outline": [[float(f"{lon:.5f}"), float(f"{lat:.5f}")] for lon, lat in feature["outline"]],
        "sense": feature["sense"],
        "diameter_km": float(f"{feature['diameter_km']:.2f}"),
        "ow_min": float(f"{feature['ow_min']:.4g}"),
    }]}
    doc = eddies_tile(_FRAME, [feature])
    assert doc == expected
    assert read_eddies_tile(doc) == expected


def _ring(points: int) -> list[list[float]]:
    """A closed ring with exactly ``points`` points (first == last)."""
    ring = [[-123.0 + i * 1e-5, 36.0] for i in range(points - 2)]
    return [*ring, [ring[-1][0], 36.1], ring[0]]


def _ring_feature(points: int) -> EddyFeature:
    return {"outline": _ring(points), "sense": "cw", "diameter_km": 10.0, "ow_min": -0.5}


def test_c3_c4_eddy_count_matches_browser_limit_in_writer_and_reader():
    """C3/C4: The Chart's parser refuses more than 200 eddies, so neither API may emit or accept 201.

    Catches an off-by-one (`>= 200`) or a missing count cap, which would publish a tile that draws nothing.
    """
    at_limit = [_feature(-123.0 + i * 0.001) for i in range(200)]
    assert len(eddies_tile(_FRAME, at_limit)["features"]) == 200
    assert len(read_eddies_tile({"frame_time": _STAMP, "features": at_limit})["features"]) == 200
    over = [*at_limit, _feature(-100.0)]
    with pytest.raises(EddyTileError) as encode_exc:
        eddies_tile(_FRAME, over)
    with pytest.raises(EddyTileError) as read_exc:
        read_eddies_tile({"frame_time": _STAMP, "features": over})
    assert str(encode_exc.value).startswith("features ")
    assert str(read_exc.value).startswith("features ")


def test_c3_c4_writer_counts_a_one_shot_iterable_of_features():
    """C3: The writer takes any iterable; a generator of 201 must be refused as a list of 201 is."""
    with pytest.raises(EddyTileError) as exc:
        eddies_tile(_FRAME, (_feature(-123.0 + i * 0.001) for i in range(201)))
    assert str(exc.value).startswith("features ")
    assert len(eddies_tile(_FRAME, (_feature(-123.0 + i * 0.001) for i in range(200)))["features"]) == 200


def test_c3_c4_outline_length_matches_browser_limit_in_writer_and_reader():
    """C3/C4: The Chart's parser refuses an outline over 2000 points; exactly 2000 passes.

    Catches a missing outline cap, an off-by-one, or a cap applied to the wrong feature index.
    """
    at_limit = [_ring_feature(2000)]
    assert len(eddies_tile(_FRAME, at_limit)["features"][0]["outline"]) == 2000
    assert len(read_eddies_tile({"frame_time": _STAMP, "features": at_limit})["features"][0]["outline"]) == 2000
    for size in (2001, 2002):
        over = [_feature(), _ring_feature(size)]
        with pytest.raises(EddyTileError) as encode_exc:
            eddies_tile(_FRAME, over)
        with pytest.raises(EddyTileError) as read_exc:
            read_eddies_tile({"frame_time": _STAMP, "features": over})
        assert str(encode_exc.value).startswith("features[1].outline")
        assert str(read_exc.value).startswith("features[1].outline")
