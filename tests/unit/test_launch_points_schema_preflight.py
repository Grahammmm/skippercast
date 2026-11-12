"""RF1315-8: every launch document passes the output schema before any region is written."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
from unittest import TestCase, mock

from skippercast import validate
from skippercast.platform import launch_points
from skippercast.platform.contracts import ContractError, load_region
from skippercast.platform.launch_points import compile_launch_points


def source(tag):
    return {"name": f"Source {tag}", "url": f"https://example.com/{tag}", "retrieved": "2026-01-01", "note": "synthetic"}


def point(region, tag):
    west, south, east, north = region["bounds"]
    lat, lon = (south + north) / 2, (west + east) / 2
    return {
        "id": f"{tag}-ramp", "region": region["id"], "name": f"{tag} ramp", "kind": "ramp", "operator": None,
        "address": "1 Synthetic Way", "latitude": lat, "longitude": lon,
        "departure": {"latitude": lat, "longitude": lon, "note": "synthetic"},
        "forecast_point": region["forecast_points"][0]["id"], "trailer_parking": None, "boarding_floats": None,
        "services": [], "phone": None, "url": f"https://example.com/{tag}", "note": None,
        "source": f"src-{tag}", "source_id": tag,
    }


FAULTS = ("url", "name", "source-url", "source-field")


class SchemaPreflight(TestCase):
    def setUp(self):
        self.regions = [load_region("morro-bay"), load_region("crescent-city")]
        self.docs = {r["id"]: point(r, r["id"]) for r in self.regions}
        self.catalog = {
            "description": "synthetic", "sources": {f"src-{k}": source(k) for k in self.docs},
            "launch_points": list(self.docs.values()),
        }

    def compile(self, catalog, regions, seed=None):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        (root / "catalog").mkdir()
        (root / "catalog/launch-points.json").write_text(json.dumps(catalog))
        for region_id, data in (seed or {}).items():
            path = root / "dist/regions" / region_id / "launch-points.json"
            path.parent.mkdir(parents=True)
            path.write_bytes(data)
        with mock.patch.object(launch_points, "atomic_json", wraps=launch_points.atomic_json) as spy:
            try:
                return compile_launch_points(root, regions), root, spy
            except ContractError as err:
                return err, root, spy

    def faulty(self, fault, region_id):
        catalog = deepcopy(self.catalog)
        if fault in ("url", "name"):
            target = next(p for p in catalog["launch_points"] if p["region"] == region_id)
            if fault == "url":
                target["url"] = "not a url"
            else:
                del target["name"]
        elif fault == "source-url":
            catalog["sources"][f"src-{region_id}"]["url"] = "not a url"
        else:
            del catalog["sources"][f"src-{region_id}"]["note"]
        return catalog

    def snapshot(self, root):
        return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}

    def test_late_schema_fault_precedes_all_writes_when_absent(self):
        self.assertTrue(validate.enabled() and validate.available())
        for fault in FAULTS:
            for order in (self.regions, self.regions[::-1]):
                with self.subTest(fault=fault, first=order[0]["id"]):
                    err, root, spy = self.compile(self.faulty(fault, order[-1]["id"]), order)
                    self.assertIsInstance(err, ContractError)
                    spy.assert_not_called()
                    self.assertFalse((root / "dist").exists())

    def test_late_schema_fault_preserves_existing_outputs(self):
        seed = {"morro-bay": b"sentinel-a", "crescent-city": b"sentinel-b"}
        for fault in FAULTS:
            for order in (self.regions, self.regions[::-1]):
                with self.subTest(fault=fault, first=order[0]["id"]):
                    err, root, spy = self.compile(self.faulty(fault, order[-1]["id"]), order, seed)
                    self.assertIsInstance(err, ContractError)
                    spy.assert_not_called()
                    self.assertEqual(self.snapshot(root), {
                        f"dist/regions/{k}/launch-points.json": v for k, v in seed.items()} | {
                        "catalog/launch-points.json": (root / "catalog/launch-points.json").read_bytes()})

    def test_valid_documents_write_in_region_order(self):
        before = deepcopy(self.catalog)
        out, root, spy = self.compile(self.catalog, self.regions)
        self.assertEqual(list(out), ["morro-bay", "crescent-city"])
        self.assertEqual(spy.call_count, 2)
        self.assertEqual(self.catalog, before)
        for region_id in out:
            doc = json.loads((root / "dist/regions" / region_id / "launch-points.json").read_text())
            self.assertEqual(doc["launch_points"], [self.docs[region_id]])

    def test_disabled_or_unavailable_validation_keeps_prior_behavior(self):
        catalog = self.faulty("url", "crescent-city")
        with mock.patch.dict("os.environ", {validate.SWITCH: "off"}):
            out, _, spy = self.compile(catalog, self.regions)
        self.assertNotIsInstance(out, ContractError)
        self.assertEqual(spy.call_count, 2)
        with mock.patch.object(validate, "available", return_value=False):
            out, _, spy = self.compile(catalog, self.regions)
        self.assertNotIsInstance(out, ContractError)
        self.assertEqual(spy.call_count, 2)
