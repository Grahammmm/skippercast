from datetime import datetime, timedelta, timezone
import unittest

from scripts import feed_stale_alert as alert

NOW = datetime(2026, 11, 1, 20, tzinfo=timezone.utc)
MEASURED = {
    "feed": "conditions", "last_published": "2026-11-01T14:00:00Z",
    "age_hours": 6.0, "late_hours": 3.0, "limit_hours": 3,
}
UNREADABLE = {"feed": "conditions", "last_published": None}
CHECK = {"feed": "freshness-check", "last_published": None, "reason": "check crashed"}
STALE_TITLE = "Published feed is stale: conditions"
UNKNOWN_TITLE = "Feed freshness unknown: conditions"
CHECK_TITLE = "Feed freshness check could not confirm results"
STALE_LINE = "STALE conditions: last published 2026-11-01T14:00:00Z (6.0 h ago), 3.0 h past its 3 h limit."
UNKNOWN_LINE = "Could not read the last publish time for conditions."
CHECK_LINE = "The check did not finish or reported a stale feed without naming it. Feed freshness is unknown."


def opened(title, number=7, comments=()):
    return {"number": number, "title": title, "createdAt": NOW.isoformat(),
            "comments": [{"body": text} for text in comments]}


class FreshnessUnknownTests(unittest.TestCase):
    def test_C1_measured_lateness_keeps_the_full_original_alert(self):
        """C1: The unknown wording must not replace measured lateness."""
        self.assertEqual(alert.plan([MEASURED], [], NOW), [("create", STALE_TITLE, STALE_LINE)])

    def test_C2_unreadable_publish_time_with_or_without_reason(self):
        """C2: Don't claim staleness, omit a known reason, or print a blank reason."""
        for event, line in ((UNREADABLE, UNKNOWN_LINE),
                            ({**UNREADABLE, "reason": "HTTP 404"}, UNKNOWN_LINE + " Reason: HTTP 404")):
            with self.subTest(event=event):
                self.assertEqual(alert.plan([event], [], NOW), [("create", UNKNOWN_TITLE, line)])

    def test_C3_sentinel_is_a_check_alert_not_a_feed_alert(self):
        """C3: The sentinel must not be formatted as a named feed or echo the reason."""
        self.assertEqual(alert.plan([CHECK], [], NOW), [("create", CHECK_TITLE, CHECK_LINE)])

    def test_C4_named_feed_keeps_its_issue_through_both_transitions(self):
        """C4: Matching only the current title would duplicate or wrongly close an issue."""
        for title, event, line in ((STALE_TITLE, UNREADABLE, UNKNOWN_LINE),
                                   (UNKNOWN_TITLE, MEASURED, STALE_LINE)):
            with self.subTest(title=title):
                issue = opened(title)
                comment = "still: 6 h - " + line
                self.assertEqual(alert.plan([event], [issue], NOW + timedelta(hours=5)), [])
                self.assertEqual(alert.plan([event], [issue], NOW + timedelta(hours=6)),
                                 [("comment", 7, comment)])
                self.assertEqual(alert.plan([event], [opened(title, comments=[comment])],
                                            NOW + timedelta(hours=7)), [])
                self.assertEqual(alert.plan([], [issue], NOW + timedelta(hours=8)),
                                 [("close", 7, "Recovered: published again after about 8 h of alerts.")])

    def test_C4_either_sentinel_title_ages_and_closes_on_check_recovery(self):
        """C4: Neither sentinel title is legacy, and a crash is not feed recovery."""
        for title in ("Published feed is stale: freshness-check", CHECK_TITLE):
            with self.subTest(title=title):
                issues = [opened(title), opened(UNKNOWN_TITLE, 8)]
                self.assertEqual(alert.plan([CHECK], issues, NOW + timedelta(hours=6)),
                                 [("comment", 7, "still: 6 h - " + CHECK_LINE)])
                self.assertEqual(alert.plan([MEASURED], issues, NOW + timedelta(hours=7)), [
                    ("comment", 8, "still: 6 h - " + STALE_LINE),
                    ("close", 7, "Recovered: the freshness check ran and named every stale feed."),
                ])

    def test_C4_unrelated_title_remains_legacy_even_when_check_is_unknown(self):
        """C4: A crash protects recognized titles, not unrelated legacy ones."""
        issues = [opened("Published feed is stale"), opened(STALE_TITLE, 8)]
        self.assertEqual(alert.plan([CHECK], issues, NOW), [
            ("create", CHECK_TITLE, CHECK_LINE),
            ("close", 7, "Replaced by one issue per stale feed (SC-LAUNCH-6)."),
        ])
