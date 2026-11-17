"""Wrongly typed coverage endpoints are refused, not read as absent."""
from copy import deepcopy

import pytest

from skippercast.platform.candidate import validate_candidate


def candidate(**temporal):
    return {"schema_version": 1, "id": "example-survey", "name": "Survey candidate", "region_ids": ["cambria-san-simeon"],
            "need_ids": ["bathymetry"], "documentation_url": "https://example.org/docs", "access_url": None,
            "access_status": "not-tested", "producer": {"name": "Example publisher", "url": "https://example.org"},
            "variables": ["elevation"], "units": {"elevation": "m"},
            "provenance": {"access_service": None, "raw_sha256": None, "transformations": []},
            "rights": {"license": None, "terms_url": None, "redistribution_reviewed": False},
            "spatial": {"bounds": None, "resolution_m": None, "horizontal_crs": None, "vertical_datum": None},
            "temporal": {"source_time": None, "checked_at": None, "update_cadence": None,
                         "coverage_start": None, "coverage_end": None, **temporal},
            "evidence": [{"url": "https://example.org/docs", "supports": "Discovery lead only"}],
            "limitations": ["Coverage unknown"]}


FIELDS = ("coverage_start", "coverage_end")
FALSEY = (False, 0, 0.0, [], {})
TRUTHY = (True, 1, 20260101, 1.5, ["2026-01-01"], {"d": "2026-01-01"})


def refuse(field, value):
    data = candidate(**{field: value})
    before = deepcopy(data)
    with pytest.raises(ValueError, match=field) as err:
        validate_candidate(data)
    assert data == before
    return str(err.value)


@pytest.mark.parametrize("field", FIELDS)
@pytest.mark.parametrize("value", FALSEY, ids=repr)
def test_falsey_coverage_endpoints_are_not_absence(field, value):
    refuse(field, value)


@pytest.mark.parametrize("field", FIELDS)
@pytest.mark.parametrize("value", TRUTHY, ids=repr)
def test_truthy_wrong_types_get_value_error(field, value):
    assert "2026" not in refuse(field, value)


@pytest.mark.parametrize("start,end", [(None, None), ("", ""), ("2026-01-01", "2026-01-02"),
                                       ("2026-01-01T00:00:00+02:00", None), (None, "2026-01-02T12:00:00Z")])
def test_optional_and_valid_string_endpoints_unchanged(start, end):
    data = candidate(coverage_start=start, coverage_end=end)
    before = deepcopy(data)
    result = validate_candidate(data)
    assert result["valid"] is True and result["publication_approved"] is False
    assert data == before


def test_endpoint_refusal_keeps_existing_errors():
    with pytest.raises(ValueError, match="reversed"):
        validate_candidate(candidate(coverage_start="2026-01-02", coverage_end="2026-01-01"))
    with pytest.raises(ValueError, match="timezone"):
        validate_candidate(candidate(coverage_start="2026-01-02T12:00:00"))
