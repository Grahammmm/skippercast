"""RF0420-4: a launch point with a missing field or a non-number position is a named
ValueError (point id + field), and no launch-points.json is written unless every
region's points pass."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
from unittest import TestCase, mock

from skippercast.platform import launch_points
from skippercast.platform.contracts import REPO, load_region, read_json
from skippercast.platform.launch_points import compile_launch_points, validate_launch_point


def catalog():
    return read_json(REPO / "catalog/launch-points.json")


def good_point():
    return deepcopy(next(p for p in catalog()["launch_points"] if p["id"] == "morro-bay-public-launch"))


class ShapeErrors(TestCase):
    def setUp(self):
        self.region = load_region("morro-bay")
        self.sources = catalog()["sources"]

    def refused(self, point, message):
        with self.assertRaises(ValueError) as caught:
            validate_launch_point(point, self.region, self.sources)
        self.assertIs(type(caught.exception), ValueError)
        self.assertEqual(str(caught.exception), message)

    def test_a_point_without_departure_names_the_point_and_field(self):
        point = good_point()
        del point["departure"]
        self.refused(point, "Launch point morro-bay-public-launch departure is missing")

    def test_missing_string_and_position_fields_are_named(self):
        for field in ("region", "forecast_point", "source", "latitude", "longitude"):
            point = good_point()
            del point[field]
            self.refused(point, f"Launch point morro-bay-public-launch {field} is missing")
        point = good_point()
        del point["departure"]["latitude"]
        self.refused(point, "Launch point morro-bay-public-launch departure.latitude is missing")

    def test_non_number_positions_name_the_field(self):
        cases = [
            ("latitude", "35.3", "latitude"),
            ("latitude", True, "latitude"),
            ("longitude", float("nan"), "longitude"),
            ("longitude", float("inf"), "longitude"),
            ("departure.longitude", None, "departure.longitude"),
            ("departure.latitude", False, "departure.latitude"),
        ]
        for path, value, field in cases:
            point = good_point()
            if path.startswith("departure."):
                point["departure"][path.split(".")[1]] = value
            else:
                point[path] = value
            with self.subTest(field=field, value=value):
                self.refused(point, f"Launch point morro-bay-public-launch {field} must be a finite number")

    def test_a_huge_integer_position_is_a_named_bounds_error(self):
        cases = [
            ("latitude", "lies outside the morro-bay bounds"),
            ("longitude", "lies outside the morro-bay bounds"),
            ("departure.latitude", "departure lies outside the morro-bay bounds"),
            ("departure.longitude", "departure lies outside the morro-bay bounds"),
        ]
        for path, tail in cases:
            point = good_point()
            if path.startswith("departure."):
                point["departure"][path.split(".")[1]] = 10**400
            else:
                point[path] = 10**400
            with self.subTest(field=path):
                self.refused(point, f"Launch point morro-bay-public-launch {tail}")

    def test_an_entry_without_an_id_is_refused(self):
        no_id = good_point()
        del no_id["id"]
        for entry in ([good_point()], no_id, {**good_point(), "id": ""}, {**good_point(), "id": 7}):
            with self.assertRaisesRegex(ValueError, "^Launch point entry has no id$"):
                validate_launch_point(entry, self.region, self.sources)

    def test_compile_names_a_list_entry_instead_of_a_type_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "catalog").mkdir()
            (root / "catalog/launch-points.json").write_text(
                json.dumps({**catalog(), "launch_points": [good_point(), ["not", "a", "point"]]}))
            with self.assertRaisesRegex(ValueError, "^Launch point entry has no id$"):
                compile_launch_points(root, [self.region])
            self.assertFalse((root / "dist").exists())


class ValidateAllBeforeWriting(TestCase):
    def test_a_bad_point_in_a_later_region_writes_no_file(self):
        morro, crescent = load_region("morro-bay"), load_region("crescent-city")
        bad = {**good_point(), "id": "crescent-bad", "region": "crescent-city",
               "forecast_point": crescent["forecast_points"][0]["id"]}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "catalog").mkdir()
            base = catalog()
            (root / "catalog/launch-points.json").write_text(json.dumps({**base, "launch_points": base["launch_points"] + [bad]}))
            with mock.patch.object(launch_points, "atomic_json", wraps=launch_points.atomic_json) as spy:
                with self.assertRaisesRegex(ValueError, "Launch point crescent-bad lies outside the crescent-city bounds"):
                    compile_launch_points(root, [morro, crescent])
            spy.assert_not_called()
            for region_id in ("morro-bay", "crescent-city"):
                self.assertFalse((root / "dist/regions" / region_id / "launch-points.json").exists())

    def test_the_committed_catalog_compiles_to_the_committed_files(self):
        published = [load_region(e["id"]) for e in read_json(REPO / "dist/regions/index.json")["regions"]]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "catalog").mkdir()
            (root / "catalog/launch-points.json").write_bytes((REPO / "catalog/launch-points.json").read_bytes())
            out = compile_launch_points(root, published)
            self.assertEqual(list(out), [r["id"] for r in published])
            for region in published:
                rel = Path("dist/regions") / region["id"] / "launch-points.json"
                committed = (REPO / rel).read_bytes()
                self.assertEqual((root / rel).read_bytes(), committed, rel)
                self.assertEqual(out[region["id"]], {"sha256": hashlib.sha256(committed).hexdigest(), "bytes": len(committed)})


class CollectionShape(TestCase):
    def compile_with(self, text, regions, seed=None):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        (root / "catalog").mkdir()
        (root / "catalog/launch-points.json").write_text(text)
        for region_id, data in (seed or {}).items():
            path = root / "dist/regions" / region_id / "launch-points.json"
            path.parent.mkdir(parents=True)
            path.write_bytes(data)
        with mock.patch.object(launch_points, "atomic_json", wraps=launch_points.atomic_json) as spy:
            try:
                return compile_launch_points(root, regions), root, spy
            except ValueError as err:
                return err, root, spy

    def test_non_array_collections_refuse_before_any_write(self):
        base = {k: v for k, v in catalog().items() if k != "launch_points"}
        values = [{}, "", "x", None, True, 3, {"a": 1}]
        for value in values:
            with self.subTest(value=value):
                err, root, spy = self.compile_with(json.dumps({**base, "launch_points": value}), [load_region("morro-bay")])
                self.assertIs(type(err), ValueError)
                self.assertEqual(str(err), "Launch point catalog launch_points must be a list")
                spy.assert_not_called()
                self.assertFalse((root / "dist").exists())
        err, _, spy = self.compile_with(json.dumps(base), [])
        self.assertEqual(str(err), "Launch point catalog launch_points must be a list")
        spy.assert_not_called()

    def test_non_object_catalog_refuses(self):
        for text in ("null", "[]", '"s"'):
            with self.subTest(text=text):
                err, _, spy = self.compile_with(text, [])
                self.assertIs(type(err), ValueError)
                self.assertEqual(str(err), "Launch point catalog must be an object")
                spy.assert_not_called()

    def test_refusal_preserves_existing_outputs(self):
        seed = {"morro-bay": b"sentinel-a", "crescent-city": b"sentinel-b"}
        regions = [load_region("morro-bay"), load_region("crescent-city")]
        base = {k: v for k, v in catalog().items() if k != "launch_points"}
        err, root, spy = self.compile_with(json.dumps({**base, "launch_points": {}}), regions, seed)
        self.assertIs(type(err), ValueError)
        spy.assert_not_called()
        for region_id, data in seed.items():
            self.assertEqual((root / "dist/regions" / region_id / "launch-points.json").read_bytes(), data)

    def test_explicit_empty_array_remains_valid(self):
        base = {k: v for k, v in catalog().items() if k != "launch_points"}
        out, root, _ = self.compile_with(json.dumps({**base, "launch_points": []}), [load_region("morro-bay")])
        self.assertEqual(list(out), ["morro-bay"])
        doc = json.loads((root / "dist/regions/morro-bay/launch-points.json").read_text())
        self.assertEqual((doc["launch_points"], doc["sources"]), ([], {}))
