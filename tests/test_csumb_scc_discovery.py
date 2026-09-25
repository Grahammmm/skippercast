import json
from pathlib import Path
import unittest

from scripts.discover_csumb_scc_blocks import compare, parse_report


ROOT = Path(__file__).resolve().parents[1]


class CsumbSccDiscoveryTest(unittest.TestCase):
    def test_pinned_roster_is_a_source_worklist_only(self):
        result = json.loads((ROOT / "catalog/csumb-scc-source-leads.json").read_text())
        self.assertEqual(result["survey_count"], 28)
        self.assertEqual([x["survey_id"] for x in result["surveys"]],
                         [f"SCC_Block{i:02d}" for i in range(1, 29)])
        self.assertEqual(result["surveys"][0]["sector_ids"], ["sur-san-simeon"])
        self.assertEqual(result["surveys"][7]["sector_ids"], ["cambria-morro"])
        for row in result["surveys"]:
            self.assertEqual(row["status"], "source-lead-only")
            self.assertNotIn("fishing_target", row)
            self.assertNotIn("geometry", row)

    def test_changed_archive_or_metadata_fails_review_baseline(self):
        baseline = json.loads((ROOT / "catalog/csumb-scc-source-leads.json").read_text())
        current = json.loads(json.dumps(baseline))
        current["surveys"][0]["original_products_url"] += "?changed=1"
        self.assertEqual(compare(current, baseline), ["SCC_Block01"])
        current["surveys"][0]["original_products_url"] = baseline["surveys"][0]["original_products_url"]
        current["series_metadata_sha256"] = "different"
        self.assertEqual(compare(current, baseline), ["series-metadata-or-roster"])

    def test_report_parser_rejects_missing_envelope(self):
        with self.assertRaisesRegex(ValueError, "Northern Extent"):
            parse_report(1, b"<html>no surveyed bounds</html>")


if __name__ == "__main__":
    unittest.main()
