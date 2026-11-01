"""skippercast.report: a cut cell ends with "…" and keeps its escapes; region issues beyond 8 say "+N more"."""
import unittest

from skippercast import report, runs


def manifest(**regions):
    return {"schema_version": runs.SCHEMA_VERSION, "job": "refresh", "run_id": "1", "started_at": "2026-10-31T00:00:00Z",
            "status": "degraded", "inputs": [], "outputs": [], "sources": {}, "regions": regions}


def region_detail(row):
    """The Issues / error cell of the one region row."""
    line = next(l for l in report.regions_table({"r": row}) if l.startswith("| r |"))
    return line.rsplit(" | ", 1)[1][:-2]


class Cells(unittest.TestCase):
    def test_short_values_are_unchanged(self):
        self.assertEqual([report.cell(v) for v in ("abc", None, "", "a | b", "a\\b")],
                         ["abc", "–", "–", "a \\| b", "a\\\\b"])

    def test_300_characters_stay_whole_and_301_are_cut_with_an_ellipsis(self):
        self.assertEqual(report.cell("x" * 300), "x" * 300)
        cut = report.cell("x" * 301)
        self.assertEqual(cut, "x" * 299 + "…")
        self.assertEqual(len(cut), 300)
        self.assertEqual(report.cell("y" * 1000), "y" * 299 + "…")

    def test_pipe_at_the_cut_keeps_its_escape(self):
        cut = report.cell("x" * 298 + "|||")
        self.assertEqual(cut, "x" * 298 + "\\|…")
        self.assertTrue(cut.endswith("xx\\|…"))
        self.assertFalse(cut.endswith("\\"))

    def test_backslash_at_the_cut_keeps_escaped_pairs(self):
        cut = report.cell("x" * 298 + "\\\\\\")
        self.assertEqual(cut, "x" * 298 + "\\\\…")
        body = cut[:-1]
        self.assertEqual(len(body) - len(body.rstrip("\\")), 2)

    def test_exactly_300_with_escapes_is_not_cut(self):
        self.assertEqual(report.cell("x" * 299 + "|"), "x" * 299 + "\\|")

    def test_whitespace_collapses_before_the_cut(self):
        raw = "a  b\n" * 100  # 500 raw characters, 399 once collapsed
        cut = report.cell(raw)
        self.assertNotIn("\n", cut)
        self.assertNotIn("  ", cut)
        self.assertEqual(cut, ("a b " * 100)[:299] + "…")


class RegionIssues(unittest.TestCase):
    def test_up_to_eight_issues_are_listed_without_more(self):
        issues = [f"s{i}" for i in range(8)]
        self.assertEqual(region_detail({"status": "degraded", "issues": issues}), ", ".join(issues))

    def test_issues_beyond_eight_are_counted(self):
        nine = [f"s{i}" for i in range(9)]
        self.assertEqual(region_detail({"status": "degraded", "issues": nine}),
                         ", ".join(nine[:8]) + ", +1 more")
        twenty = region_detail({"status": "failed", "issues": [f"s{i}" for i in range(20)]})
        self.assertTrue(twenty.endswith(", s7, +12 more"))
        self.assertNotIn("s8", twenty)

    def test_no_issues_is_a_dash(self):
        for issues in (None, []):
            self.assertEqual(region_detail({"status": "ok", "issues": issues}), "–")
        self.assertEqual(region_detail({"status": "ok"}), "–")

    def test_error_class_region_does_not_list_issues(self):
        row = {"status": "failed", "error_class": "TimeoutError", "error": "slow", "issues": [f"s{i}" for i in range(12)]}
        self.assertEqual(region_detail(row), "TimeoutError: slow")

    def test_long_detail_row_keeps_its_columns(self):
        issues = [f"station|{i}|" + "x" * 40 for i in range(40)]  # 8 listed are already over 300 characters
        text = report.render(manifest(r={"status": "failed", "issues": issues}))
        lines = text.splitlines()
        header = next(l for l in lines if l.startswith("| Region |"))
        row = next(l for l in lines if l.startswith("| r |"))
        unescaped = lambda l: l.replace("\\\\", "").replace("\\|", "").count("|")
        self.assertEqual(unescaped(row), unescaped(header))
        self.assertTrue(row.endswith("… |"))
        self.assertNotIn("more", row)  # the count was cut with the rest; the ellipsis marks it


if __name__ == "__main__":
    unittest.main()
