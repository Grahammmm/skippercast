import pytest


@pytest.mark.gis
@pytest.mark.parametrize(("changes", "status", "reason", "height_echo"), [
    ({"s_z": "0.0"}, "sample_available", None, 0.0),
    ({}, "sample_available", None, None),
    ({"s_x": "NaN"}, "invalid_response", "source_coordinate_mismatch", None),
    ({"s_y": "Infinity"}, "invalid_response", "source_coordinate_mismatch", None),
    ({"s_z": "1.0"}, "invalid_response", "source_height_mismatch", None),
    ({"s_z": "NaN"}, "invalid_response", "source_height_mismatch", None),
    ({"s_z": "bad"}, "invalid_response", "source_height_mismatch", None),
    ({"s_v_frame": "MLLW"}, "invalid_response", "frame_or_schema_mismatch", None),
    ({"s_v_unit": "ft"}, "invalid_response", "frame_or_schema_mismatch", None),
])
def test_available_sample_matches_zero_height_request(changes, status, reason, height_echo):
    from research.scripts.audit_vdatum_samples import assess_response

    payload = {
        "region": "WESTCOAST", "s_h_frame": "NAD83_2011", "s_v_frame": "NAVD88",
        "s_v_unit": "m", "t_h_frame": "IGS14", "t_v_frame": "MLLW", "t_v_unit": "m",
        "s_x": "0", "s_y": "0", "t_x": "0", "t_y": "0", "t_z": "0.2", "uncertainty": "0.1",
    }
    result = assess_response({**payload, **changes}, 0, 0)
    assert result["status"] == status
    assert result.get("reason") == reason
    if status == "sample_available":
        assert result["source_height_echo_m"] == height_echo
        assert result["offset_m"] == 0.2
