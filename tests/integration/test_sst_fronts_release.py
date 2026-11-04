"""BF-sst-fronts: the regional habitat refresh produces the fronts file the client requests (offline fixture).

web/map/fronts.ts reads /feeds/conditions/regions/<region>/sst-fronts.json. scripts/live_cycle.sh copies
everything the habitat refresh wrote under var/live/regions into the conditions release, so the file only has
to be produced there, beside habitat-dynamics.json, from the tiles that refresh just published."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import refresh_regions
from skippercast.platform.contracts import REPO
from tests.gis.test_sst_fronts import tile

REGION = "morro-bay"


def habitat_run_with(time_of_observation):
    """A stand-in for the network-bound habitat run: it writes one SST tile with a front, as the real run does."""
    def run(ident, output, previous_root, now):
        target = Path(output) / "regions" / ident
        (target / "habitat-tiles").mkdir(parents=True)
        (target / "habitat-tiles" / f"sst-analysis--1--2-{'a' * 16}.json").write_text(json.dumps(tile(range(12), time_of_observation(now))))
        (target / "habitat-dynamics.json").write_text("{}\n")
        return {"completed_at": now.isoformat(), "health": {"status": "ok", "issues": []}}
    return run


def refresh_habitat(output, run):
    with patch("skippercast.pipeline.habitat_dynamics.run", side_effect=run), patch("builtins.print"):
        return refresh_regions.refresh("habitat", output, only_region=REGION)


class FrontsReleaseTests(unittest.TestCase):
    def test_the_habitat_refresh_writes_the_file_the_client_requests(self):
        with tempfile.TemporaryDirectory() as directory:
            rows = refresh_habitat(Path(directory), habitat_run_with(lambda now: (now - timedelta(hours=6)).timestamp()))
            self.assertEqual([row["status"] for row in rows], ["ok"])
            path = Path(directory) / "regions" / REGION / "sst-fronts.json"
            self.assertTrue(path.is_file(), "sst-fronts.json sits beside habitat-dynamics.json, where live_cycle.sh copies the region")
            document = json.loads(path.read_text())
        self.assertEqual((document["schema_version"], document["region_id"], document["layer_id"]), (1, REGION, "sst-fronts"))
        self.assertEqual(len(document["fronts"]), 1)
        self.assertEqual(document["max_age_hours"], json.loads((REPO / "catalog/feed-health.json").read_text())["feeds"]["sst-fronts"]["max_age_hours"])
        observed = datetime.fromisoformat(document["fronts"][0]["observed_at"].replace("Z", "+00:00"))
        self.assertAlmostEqual((datetime.now(timezone.utc) - observed).total_seconds() / 3600, 6, delta=0.1)

    def test_a_stale_observation_still_publishes_a_file_with_no_fronts(self):
        with tempfile.TemporaryDirectory() as directory:
            refresh_habitat(Path(directory), habitat_run_with(lambda now: (now - timedelta(days=30)).timestamp()))
            document = json.loads((Path(directory) / "regions" / REGION / "sst-fronts.json").read_text())
        self.assertEqual(document["fronts"], [])
        self.assertIsNone(document["observed_at"])

    def test_a_fronts_failure_never_stops_the_habitat_refresh(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch("scripts.refresh_regions.publish_region", side_effect=ValueError("bad tile")):
                rows = refresh_habitat(Path(directory), habitat_run_with(lambda now: now.timestamp()))
            self.assertEqual([row["status"] for row in rows], ["ok"])
            self.assertFalse((Path(directory) / "regions" / REGION / "sst-fronts.json").exists())


if __name__ == "__main__":
    unittest.main()
