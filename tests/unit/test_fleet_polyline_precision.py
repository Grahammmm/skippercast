"""High-precision polylines round-trip; the overlong-varint guard stays bounded."""

from skippercast.fleet.ais.simplify import decode_polyline, encode_polyline


def test_precision_eight_dateline_roundtrip():
    pts = [(0.0, 179.0), (0.0, -179.0)]
    assert decode_polyline(encode_polyline(pts, 8), 8) == pts


def test_precision_nine_extreme_delta_roundtrip():
    pts = [(-90.0, -180.0), (90.0, 180.0), (-90.0, -180.0)]
    assert decode_polyline(encode_polyline(pts, 9), 9) == pts
    assert decode_polyline(encode_polyline(pts[:1], 9), 9) == pts[:1]
    assert decode_polyline("", 9) == []


def test_precision_guard_remains_bounded():
    for precision in (5, 9):
        assert decode_polyline("_", precision) == []  # truncated varint
        assert decode_polyline("_ _", precision) == []  # invalid character
        assert decode_polyline("~" * 40 + "?", precision) == []  # overlong continuation
        assert decode_polyline("??~", precision) == []  # odd value count


def test_default_google_vector_unchanged():
    google = "_p~iF~ps|U_ulLnnqC_mqNvxq`@"
    pts = [(38.5, -120.2), (40.7, -120.95), (43.252, -126.453)]
    assert encode_polyline(pts) == google
    assert decode_polyline(google) == pts
    edge = [(0.0, 179.0), (0.0, -179.0)]
    assert decode_polyline(encode_polyline(edge)) == edge
