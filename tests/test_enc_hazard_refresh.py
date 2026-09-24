"""Fail-closed checks for bounded NOAA ENC danger snapshots."""
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from scripts.refresh_enc_hazards import LAYERS, query_layer, refresh


class EncHazardRefreshTests(unittest.TestCase):
    def test_count_disagreement_cannot_be_published_as_empty_hazard_water(self):
        responses = iter([({"count": 1}, "a" * 64),
                          ({"type": "FeatureCollection", "features": []}, "b" * 64)])
        with patch("scripts.refresh_enc_hazards.fetch_json", side_effect=lambda _: next(responses)):
            with self.assertRaisesRegex(ValueError, "Incomplete or changed ENC"):
                query_layer("enc_approach", "Underwater_Awash_Rock_point", 37,
                            [-119.12, 33.33, -118.98, 33.54])

    def test_missing_scale_layer_aborts_the_entire_refresh(self):
        metadata = {"layers": [{"name": "Harbor." + name, "id": i}
                               for i, name in enumerate(LAYERS) if name != "Wreck_area"]}
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "hazards.geojson"
            with patch("scripts.refresh_enc_hazards.fetch_json", return_value=(metadata, "a" * 64)):
                with self.assertRaisesRegex(ValueError, "Required NOAA ENC layer missing"):
                    refresh({"id": "test", "region_id": "southern-california",
                             "bounds": [-119.12, 33.33, -118.98, 33.54]}, output)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
