"""Public-release integrity checks, using only the bundled reviewed dataset."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from xml.etree import ElementTree as ET

from skippercast.atlas.export import GPX, validate, write_exports

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "atlas/avila-point-estero-2026-09-20/data/atlas.json"


class PublicAtlas(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads(DATA.read_text(encoding="utf-8"))

    def test_published_scope_and_rights_exclusions(self):
        result = validate(self.data)
        self.assertEqual((result["targets"], result["areas"], result["drifts"]), (132, 107, 31))
        self.assertEqual(result["grades"], {"A": 35, "B": 74, "C": 23})
        self.assertEqual({r["source_id"] for r in self.data["targets"]},
                         {"PointBuchon", "MorroBay", "PointEstero"})
        excluded = {f"MB26-{i:03d}" for i in (13, 14, 15, 16, *range(137, 144))}
        self.assertFalse(excluded & {r["legacy_id"] for r in self.data["targets"]})
        self.assertNotIn("historical_charter_context", DATA.read_text(encoding="utf-8"))

    def test_broken_geometry_link_rejected(self):
        data = deepcopy(self.data)
        data["targets"][0]["area_ids"] = ["unknown"]
        with self.assertRaisesRegex(ValueError, "target-to-area"):
            validate(data)

    def test_missing_native_evidence_and_excess_depth_rejected(self):
        for change in ({"native_circle_has_gap": True},
                       {"native_100m_circle_max_depth_ft": 201}):
            data = deepcopy(self.data)
            data["targets"][0]["recorded_validation"].update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate(data)

    def test_exports_preserve_positions_and_separate_geometry_types(self):
        with TemporaryDirectory() as directory:
            output = Path(directory) / "export"
            manifest = write_exports(self.data, output)
            root = ET.parse(output / "complete.gpx").getroot()
            points = root.findall(f"{{{GPX}}}wpt")
            routes = root.findall(f"{{{GPX}}}rte")
            tracks = root.findall(f"{{{GPX}}}trk")
            self.assertEqual((len(points), len(routes), len(tracks)), (132, 31, 107))
            expected = {(f"{r['latitude']:.6f}", f"{r['longitude']:.6f}") for r in self.data["targets"]}
            self.assertEqual({(r.attrib["lat"], r.attrib["lon"]) for r in points}, expected)
            for point in points:
                note = point.findtext(f"{{{GPX}}}desc")
                self.assertIn("MLLW", note)
                self.assertIn("Not a catch prediction", note)
                self.assertIn("https://doi.org/", note)
            for track in tracks:
                for segment in track.findall(f"{{{GPX}}}trkseg"):
                    vertices = segment.findall(f"{{{GPX}}}trkpt")
                    self.assertEqual(vertices[0].attrib, vertices[-1].attrib)
            self.assertEqual(len(json.loads((output / "atlas.geojson").read_text())["features"]), 270)
            for item in manifest["files"]:
                self.assertEqual(hashlib.sha256((output / item["name"]).read_bytes()).hexdigest(), item["sha256"])

    def test_exports_are_deterministic_and_do_not_overwrite(self):
        with TemporaryDirectory() as directory:
            first, second = Path(directory) / "one", Path(directory) / "two"
            self.assertEqual(write_exports(self.data, first), write_exports(self.data, second))
            with self.assertRaises(FileExistsError):
                write_exports(self.data, first)

    def test_shipped_exports_match_current_data_and_exporter(self):
        shipped = DATA.parent.parent / "exports"
        with TemporaryDirectory() as directory:
            rebuilt = Path(directory) / "rebuilt"
            write_exports(self.data, rebuilt)
            for path in rebuilt.iterdir():
                with self.subTest(file=path.name):
                    self.assertEqual(path.read_bytes(), (shipped / path.name).read_bytes())


if __name__ == "__main__":
    unittest.main()
