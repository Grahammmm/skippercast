"""Offline contracts for the SST fronts history index."""

import unittest
from itertools import permutations
from typing import Any

from skippercast.pipeline.fronts_history import FrontsIndexUpdate, dated_fronts_path, next_fronts_index


TODAY = "2024-03-03"
NEW_SHA = "a" * 64
OLD_SHA = "0123456789abcdef" * 4


def record(day, digest=OLD_SHA):
    return {"date": day, "path": f"sst-fronts/{day}.json", "sha256": digest}


class FrontsHistoryTests(unittest.TestCase):
    def assert_update(self, result, index, dropped=()):
        self.assertEqual(result, FrontsIndexUpdate(index, frozenset(e["path"] for e in index), dropped))

    def test_c1_dated_path(self):
        """C1: Use a region-relative path, including for leap day."""
        self.assertEqual(dated_fronts_path("2024-02-29"), "sst-fronts/2024-02-29.json")

    def test_c1_reject_noncanonical_or_impossible_date(self):
        """C1: Reject date spellings an ISO parser might accept and bogus calendar days."""
        invalid_days: tuple[Any, ...] = (
            "20240229", "2024-W09-4", "2024-2-29", "2024-02-29\n", "2023-02-29", "0000-01-01", None,
        )
        for day in invalid_days:
            with self.subTest(day=day):
                with self.assertRaises(ValueError) as error:
                    dated_fronts_path(day)
                self.assertIs(type(error.exception), ValueError)

    def test_c2_result_shape_without_history(self):
        """C2: Zero history still returns the exact three-field NamedTuple, not a bare list."""
        for previous in (None, []):
            with self.subTest(previous=previous):
                result = next_fronts_index(previous, TODAY, NEW_SHA, TODAY)
                self.assertIsInstance(result, FrontsIndexUpdate)
                self.assertEqual(result._fields, ("index", "keep", "dropped"))
                self.assertIsInstance(result.keep, frozenset)
                self.assert_update(result, [record(TODAY, NEW_SHA)])

    def test_c3_reject_only_invalid_caller_values(self):
        """C3: Bad caller values must raise, not be normalized, clipped or reported as rows."""
        valid: dict[str, Any] = {"day": TODAY, "today": TODAY, "sha256": NEW_SHA, "keep_days": 7}
        for name, values in (
            ("day", ("2024-02-30", "2024-03-04", "2024-02-25")),
            ("today", ("20240303", "2023-02-29", None)),
            ("sha256", (None, "a" * 63, "a" * 65, "A" * 64, "g" * 64, NEW_SHA + "\n")),
            ("keep_days", (0, 8, 1.0, "7", True)),
        ):
            for value in values:
                with self.subTest(name=name, value=value):
                    arguments = valid.copy()
                    arguments[name] = value
                    with self.assertRaises(ValueError) as error:
                        next_fronts_index(None, **arguments)
                    self.assertIs(type(error.exception), ValueError)

    def test_c3_report_non_list_history(self):
        """C3: A non-list history gets one sentinel rather than being iterated or ignored."""
        for previous in ({}, (), "", 0):
            with self.subTest(previous=previous):
                self.assert_update(
                    next_fronts_index(previous, TODAY, NEW_SHA, TODAY),
                    [record(TODAY, NEW_SHA)], ((-1, "not a list"),),
                )

    def test_c3_drop_malformed_rows_in_precedence_order(self):
        """C3: Report each first defect by position without losing the first valid row."""
        day = "2024-03-02"
        good = record(day)
        previous = [
            None,
            {"date": [], "sha256": 7, "path": []},
            good | {"sha256": "wrong", "path": {}},
            good | {"path": f"../sst-fronts/{day}.json"},
            good | {"ignored": "extra metadata"},
            good | {"sha256": "wrong"},
            good | {"path": None},
            record(day, "b" * 64),
            record("2024-02-25", "wrong"),  # report corruption even outside the window
        ]
        self.assert_update(
            next_fronts_index(previous, TODAY, NEW_SHA, TODAY),
            [record(TODAY, NEW_SHA), good],
            ((0, "not a dict"), (1, "bad date"), (2, "bad sha256"), (3, "bad path"),
             (5, "bad sha256"), (6, "bad path"), (7, "duplicate date"), (8, "bad sha256")),
        )

    def test_c4_same_date_replacement_in_any_order(self):
        """C4: A backfill replaces exactly its old row without changing input order or data."""
        new_day, older_day = "2024-03-02", "2024-03-01"
        for ordered in permutations([record(TODAY), record(new_day), record(older_day)]):
            previous = [dict(entry) for entry in ordered]
            with self.subTest(order=[entry["date"] for entry in previous]):
                self.assert_update(
                    next_fronts_index(previous, new_day, NEW_SHA, TODAY),
                    [record(TODAY), record(new_day, NEW_SHA), record(older_day)],
                )
                self.assertEqual(previous, list(ordered))

    def test_c4_history_size_and_default_boundary(self):
        """C4: Keep age 6, trim age 7, and leave gaps unfilled with newest dates first."""
        latest = record(TODAY, NEW_SHA)
        kept = [record(day) for day in (
            "2024-03-02", "2024-03-01", "2024-02-29", "2024-02-28", "2024-02-27", "2024-02-26",
        )]
        for previous, expected in (
            (kept[-1:], [latest, kept[-1]]),
            ([*reversed(kept), record("2024-02-25")], [latest, *kept]),
            ([record("2024-02-24"), *reversed(kept), record("2024-02-25")], [latest, *kept]),
        ):
            with self.subTest(history_days=len(previous)):
                self.assert_update(next_fronts_index(previous, TODAY, NEW_SHA, TODAY), expected)

    def test_c4_custom_window(self):
        """C4: A one-day window keeps only today and a longer window admits its oldest day."""
        previous = [record("2024-03-04"), record("2024-03-01"), record("2024-03-02")]
        self.assert_update(
            next_fronts_index(previous, TODAY, NEW_SHA, TODAY, keep_days=1),
            [record(TODAY, NEW_SHA)],
        )
        self.assert_update(
            next_fronts_index(previous, "2024-03-02", NEW_SHA, TODAY, keep_days=2),
            [record("2024-03-02", NEW_SHA)],
        )
