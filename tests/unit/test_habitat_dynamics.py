from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from skippercast.pipeline.habitat_dynamics import (
    frame_for_time, gradients, publish_tiles, species_support, _copy_previous_tiles, _cleanup_tiles, satellite, run,
)


class HabitatDynamicsTests(unittest.TestCase):
    def layer(self, kind="forecast"):
        return {"id": "test", "kind": kind, "status": "ok", "issued_at": "2026-09-22T03:00:00Z",
                "max_age_hours": 36, "frames": [{"time": 1790042400, "valid_cells": 1}, {"time": 1790053200, "valid_cells": 1}]}

    def test_native_forecast_frame_and_no_extrapolation(self):
        layer = self.layer(); first, last = [f["time"] for f in layer["frames"]]
        # Use its native clocks rather than any wall-clock dependence.
        layer["issued_at"] = datetime.fromtimestamp(first-3600, timezone.utc).isoformat()
        self.assertEqual(frame_for_time(layer, first+3600, first)["frame"]["time"], first)
        self.assertEqual(frame_for_time(layer, first+3600, first)["mode"], "forecast")
        self.assertIsNone(frame_for_time(layer, first-1, first)["frame"])
        self.assertIsNone(frame_for_time(layer, last+1, first)["frame"])

    def test_gap_and_empty_frame_are_not_interpolated(self):
        layer = self.layer(); first = layer["frames"][0]["time"]
        layer["issued_at"] = datetime.fromtimestamp(first, timezone.utc).isoformat()
        layer["frames"] = [{"time": first, "valid_cells": 1}, {"time": first+10800, "valid_cells": 0}, {"time": first+21600, "valid_cells": 1}]
        self.assertIsNone(frame_for_time(layer, first+10800, first)["frame"])

    def test_dated_satellite_context_never_becomes_future_forecast(self):
        layer = self.layer("analysis"); first = layer["frames"][0]["time"]
        layer.pop("issued_at"); layer["sample_at"] = datetime.fromtimestamp(first, timezone.utc).isoformat()
        layer["frames"] = layer["frames"][:1]; layer["max_age_hours"] = 72
        selection = frame_for_time(layer, first+7*86400, first+3600)
        self.assertEqual(selection["mode"], "observed-context")
        self.assertEqual(selection["frame"]["time"], first)
        self.assertIsNone(frame_for_time(layer, first-1, first+3600)["frame"])

    def test_freshness_uses_actual_now_not_selected_date(self):
        layer = self.layer("analysis"); first = layer["frames"][0]["time"]
        layer.pop("issued_at"); layer["sample_at"] = datetime.fromtimestamp(first, timezone.utc).isoformat()
        self.assertIsNone(frame_for_time(layer, first, first+37*3600)["frame"])
        layer["status"] = "failed"
        self.assertIsNone(frame_for_time(layer, first, first)["frame"])
        layer["status"] = "retained"
        self.assertEqual(frame_for_time(layer, first, first)["mode"], "observed-context")

    def test_malformed_metadata_cannot_render(self):
        for layer in ({}, {"status": "ok", "issued_at": "bad"}, self.layer() | {"max_age_hours": None}):
            self.assertIsNone(frame_for_time(layer, 0, 0)["frame"])

    def test_gradients_use_native_four_neighbors(self):
        rows = [[y, x, x*10, .001] for y in (33.99, 34, 34.01) for x in (-120.01, -120, -119.99)]
        result = gradients(rows, [.01, .01], error_index=3)
        center = next(r for r in result if r[:2] == [34, -120])
        self.assertGreater(center[-2], .10); self.assertLess(center[-2], .12)
        self.assertEqual(center[-1], 1)
        self.assertIsNone(result[0][-2])
        missing = gradients([r for r in rows if r[:2] != [34, -119.99]], [.01, .01], error_index=3)
        self.assertIsNone(next(r for r in missing if r[:2] == [34, -120])[-2])

    def test_unknown_error_does_not_mean_confident_front(self):
        rows = [[y, x, x*10, None] for y in (33.99, 34, 34.01) for x in (-120.01, -120, -119.99)]
        center = next(r for r in gradients(rows, [.01, .01], error_index=3) if r[:2] == [34, -120])
        self.assertIsNotNone(center[-2]); self.assertIsNone(center[-1])

    def test_specifically_scoped_thermal_evidence_is_not_a_bite_score(self):
        inside = species_support("yellowfin", 22, .02)
        self.assertTrue(inside["temperature_within_reference_range"])
        self.assertIsNone(inside["catch_probability"]); self.assertIsNone(inside["habitat_score"])
        self.assertFalse(species_support("yellowfin", 14)["temperature_within_reference_range"])
        self.assertIn("absence", species_support("yellowfin", 14)["reason"])
        self.assertIsNone(species_support("bluefin", 14)["temperature_within_reference_range"])
        self.assertFalse(species_support("reef", 14)["supported"])
        self.assertIsNone(species_support("yellowfin", float("nan"))["temperature_within_reference_range"])

    def test_tiling_keeps_source_pixels_masks_times_and_hashes(self):
        layer = {"id": "sst-analysis", "fields": ["latitude", "longitude", "temperature_c"], "resolution_degrees": [.01, .01],
                 "frames": [{"time": 100, "cells": [[34, -120, 18], [34.01, -120, 19], [34.6, -120, 20]], "valid_cells": 3, "total_cells": 4}]}
        with tempfile.TemporaryDirectory() as root:
            base = Path(root); manifest = publish_tiles(layer, base/"one", "southern-california")
            self.assertEqual(len(manifest["tiles"]), 2)
            self.assertNotIn("cells", manifest["frames"][0])
            self.assertEqual(manifest["frames"][0]["total_cells"], 4)
            cells = []
            for item in manifest["tiles"]:
                data = (base/"one"/item["path"]).read_bytes()
                self.assertEqual(hashlib.sha256(data).hexdigest(), item["sha256"])
                content = json.loads(data)
                self.assertEqual(content["region_id"], "southern-california")
                cells.extend(content["frames"][0]["cells"])
            self.assertEqual(sorted(cells), sorted(layer["frames"][0]["cells"]))
            _copy_previous_tiles(manifest, base/"one", base/"two")
            tile = manifest["tiles"][0]
            (base/"one"/tile["path"]).write_text("{}")
            with self.assertRaises(ValueError): _copy_previous_tiles(manifest, base/"one", base/"three")

    def test_retained_tile_path_cannot_escape_region(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(ValueError):
                _copy_previous_tiles({"tiles": [{"path": "../other-region/tile.json"}]}, Path(root), Path(root))

    def test_cleanup_only_removes_unreferenced_compiler_owned_tiles(self):
        with tempfile.TemporaryDirectory() as root:
            target = Path(root); folder = target/"habitat-tiles"; folder.mkdir()
            old = folder/"sst-analysis--240-68-0123456789abcdef.json"; old.write_text("{}")
            keep = folder/"notes.json"; keep.write_text("do not delete")
            _cleanup_tiles(target, {})
            self.assertFalse(old.exists()); self.assertTrue(keep.exists())

    def test_satellite_native_mask_error_and_units_contract(self):
        from unittest.mock import patch
        metadata = {"attrs": {"NC_GLOBAL": {"geospatial_lat_resolution": ".01", "geospatial_lon_resolution": ".01", "license": "public"}}}
        rows = [{"latitude": 34, "longitude": -120+.01*i, "mask": mask, "analysed_sst": 18, "analysis_error": error}
                for i, (mask, error) in enumerate(((1, .1), (3, .1), (9, .1), (1, None)))]
        class Client:
            def get(self, *args): return {}
        with patch("skippercast.pipeline.habitat_dynamics.erddap_metadata", return_value=metadata), patch("skippercast.pipeline.habitat_dynamics.erddap_query", return_value="bounded"), patch("skippercast.pipeline.habitat_dynamics.erddap_grid", return_value={"sample_at": "2026-09-22T09:00:00Z", "samples": rows}):
            layer = satellite(Client(), {"bounds": [-120, 34, -119.96, 34.02]}, {"base_url": "https://example.test", "dataset": "test", "variables": ["analysed_sst"]}, "sst")
        self.assertEqual(layer["native_stride"], 1)
        self.assertEqual(layer["valid_cells"], 2)
        self.assertEqual(layer["total_cells"], 4)
        self.assertIsNone(layer["frames"][0]["cells"][-1][3])
        self.assertEqual(layer["resolution_degrees"], [.01, .01])

    def test_masked_scene_is_cached_coverage_gap_not_broken_job(self):
        region = {"id": "test-region", "bounds": [-121, 34, -120, 35], "species": ["bluefin"],
                  "pipeline_sources": {"sst": "mur-sst", "chlorophyll": "modis-chlorophyll"},
                  "source_bindings": {"sea-temperature": ["mur-sst"], "chlorophyll": ["modis-chlorophyll"]}}
        cfg = {"review_status": "approved", "adapter": "erddap-grid", "allowed_hosts": ["example.test"],
               "request": {"base_url": "https://example.test", "max_age_hours": 72}, "name": "test", "documentation_url": "https://example.test", "rights": {"license": "test"}}
        catalogs = {"mur-sst": cfg, "modis-chlorophyll": cfg, "noaa-wcofs": {}}
        now = datetime(2026, 9, 22, 12, tzinfo=timezone.utc)
        def response(ident, name, kind, url, max_age, loader, clock):
            return {"id": ident, "status": "missing", "checked_at": clock.isoformat(), "data_retrieved_at": now.isoformat(), "last_success_at": now.isoformat(), "requests": [],
                    "data": {"kind": kind, "sample_at": now.isoformat(), "resolution_degrees": [.01, .01], "fields": ["latitude", "longitude", "temperature_c"],
                             "valid_cells": 0, "total_cells": 100, "frames": [{"time": int(now.timestamp()), "cells": [], "valid_cells": 0, "total_cells": 100}]}}
        with tempfile.TemporaryDirectory() as root, patch("skippercast.pipeline.habitat_dynamics.load_region", return_value=region), patch("skippercast.pipeline.habitat_dynamics.load_catalogs", return_value=({}, catalogs)), patch("skippercast.pipeline.habitat_dynamics.source", side_effect=response) as acquire:
            first = run("test-region", Path(root), now=now)
            self.assertEqual(first["health"]["issues"], [])
            self.assertEqual(len(first["health"]["coverage_gaps"]), 2)
            self.assertEqual(first["health"]["status"], "degraded")
            second = run("test-region", Path(root), Path(root), now+timedelta(hours=1))
            self.assertEqual(acquire.call_count, 2)
            self.assertEqual(second["sources"]["sst-analysis"]["data_retrieved_at"], now.isoformat())
            self.assertTrue(second["sources"]["sst-analysis"]["reused"])
            # A held/empty scene never conceals a stale original clock.
            second["layers"]["sst-analysis"]["sample_at"] = (now-timedelta(hours=73)).isoformat()
            (Path(root)/"regions/test-region/habitat-dynamics.json").write_text(json.dumps(second))
            third = run("test-region", Path(root), Path(root), now+timedelta(hours=2))
            self.assertIn("sst-analysis", third["health"]["issues"])


if __name__ == "__main__": unittest.main()
