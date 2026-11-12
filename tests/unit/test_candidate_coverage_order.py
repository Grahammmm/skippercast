"""Coverage endpoint ordering for source candidates."""
from copy import deepcopy
from unittest import TestCase
from skippercast.platform.candidate import validate_candidate


def candidate(start=None, end=None):
    return {"schema_version": 1, "id": "example-survey", "name": "Survey candidate", "region_ids": ["cambria-san-simeon"],
            "need_ids": ["bathymetry"], "documentation_url": "https://example.org/docs", "access_url": None,
            "access_status": "not-tested", "producer": {"name": "Example publisher", "url": "https://example.org"},
            "variables": ["elevation"], "units": {"elevation": "m"},
            "provenance": {"access_service": None, "raw_sha256": None, "transformations": []},
            "rights": {"license": None, "terms_url": None, "redistribution_reviewed": False},
            "spatial": {"bounds": None, "resolution_m": None, "horizontal_crs": None, "vertical_datum": None},
            "temporal": {"source_time": None, "checked_at": None, "update_cadence": None,
                         "coverage_start": start, "coverage_end": end},
            "evidence": [{"url": "https://example.org/docs", "supports": "Discovery lead only"}],
            "limitations": ["Coverage unknown"]}


class CoverageOrder(TestCase):
    def accept(self, start, end):
        data = candidate(start, end)
        before = deepcopy(data)
        result = validate_candidate(data)
        self.assertIs(result["publication_approved"], False)
        self.assertEqual(data, before)

    def refuse(self, start, end, message="Coverage interval is reversed"):
        data = candidate(start, end)
        before = deepcopy(data)
        with self.assertRaisesRegex(ValueError, message):
            validate_candidate(data)
        self.assertEqual(data, before)

    def test_same_day_reversed_instants_refused(self):
        self.refuse("2026-01-02T12:00:00Z", "2026-01-02T11:00:00Z")
        self.accept("2026-01-02T11:00:00Z", "2026-01-02T12:00:00Z")
        self.accept("2026-01-02T12:00:00Z", "2026-01-02T12:00:00Z")

    def test_offset_local_dates_do_not_reverse_time(self):
        self.accept("2026-01-02T00:30:00+02:00", "2026-01-01T23:00:00Z")
        self.refuse("2026-01-01T23:30:00-02:00", "2026-01-02T01:00:00Z")
        self.accept("2026-01-02T00:30:00+02:00", "2026-01-01T22:30:00Z")

    def test_subsecond_order_is_preserved(self):
        self.refuse("2026-01-02T12:00:00.500Z", "2026-01-02T12:00:00.250Z")
        self.accept("2026-01-02T12:00:00.250Z", "2026-01-02T12:00:00.500Z")

    def test_calendar_dates_unchanged(self):
        self.accept("2026-01-01", "2026-01-02")
        self.accept("2028-02-29", "2028-02-29")
        self.refuse("2026-01-02", "2026-01-01")
        self.refuse("2026-02-30", "2026-03-01", "day is out of range")

    def test_mixed_precision_keeps_calendar_projection(self):
        self.accept("2026-01-02", "2026-01-02T00:30:00+02:00")
        self.accept("2026-01-02T23:00:00-05:00", "2026-01-02")
        self.refuse("2026-01-03", "2026-01-02T23:59:00Z")
        self.refuse("2026-01-02T00:30:00Z", "2026-01-01")

    def test_optional_and_malformed_endpoints_unchanged(self):
        self.accept(None, None)
        self.accept("2026-01-02T12:00:00Z", None)
        self.accept(None, "2026-01-02")
        self.refuse("2026-01-02T12:00:00", "2026-01-03T12:00:00Z", "need a timezone")
        self.refuse("garbage-in-here", None, "Invalid isoformat")

    def test_no_mutation_or_publication_approval(self):
        result = validate_candidate(candidate("2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"))
        self.assertEqual(result["candidate_id"], "example-survey")
        self.assertIs(result["publication_approved"], False)
        data = candidate("2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z")
        data["access_status"] = "accessible"
        with self.assertRaisesRegex(ValueError, "checked_at"):
            validate_candidate(data)
