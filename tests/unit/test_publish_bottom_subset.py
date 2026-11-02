"""RF0510-8: publish_bottom_subset takes exactly the three qualification artifacts,
parses each from the bytes it hashed, and restores the atlas if the index write fails."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from research.scripts import publish_bottom_subset as mod
from skippercast.platform.contracts import atomic_json as real_atomic_json, read_json as real_read_json

V = "qualified-v1"
BASE = "regions/test-coast/"


class PublishBottomSubsetTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.dist = self.root / "dist"
        self.folder = self.dist / BASE / "qualified-bottom"
        self.region = {"id": "test-coast", "assets": {"target_qualification": BASE + "qualified-bottom/manifest.json",
                                                      "bottom_index": BASE + "bottom-index.json",
                                                      "atlas": BASE + "atlas.json"}}
        self.atlas_path, self.index_path = self.dist / BASE / "atlas.json", self.dist / BASE / "bottom-index.json"
        self.raw(self.atlas_path, {"targets": [{"id": "OWNED-OLD", "qualification": {"policy": V}},
                                               {"id": "OTHER", "qualification": {"policy": "older"}}]})
        self.raw(self.index_path, {"schema_version": 1, "views": {"OWNED-OLD": {"v": 0}, "OTHER": {"v": 0},
                                                                   "T1": {"v": 0}}, "sources": {"s0": {}}})
        self.artifacts = {"atlas.json": {"targets": [{"id": "T1", "qualification": {"policy": V}}]},
                          "quality.json": {"status": "qualified-partial"},
                          "bottom-index-fragment.json": {"views": {"T1": {"v": 1}}, "sources": {"s1": {}}}}
        for name, value in self.artifacts.items():
            self.raw(self.folder / name, value)
        self.write_manifest()
        region_patch = patch.object(mod, "load_region", return_value=self.region)
        validate_patch = patch.object(mod, "validate_qualified_scope", return_value={"ready": True})
        region_patch.start()
        self.validate_qualified_scope = validate_patch.start()
        self.addCleanup(region_patch.stop)
        self.addCleanup(validate_patch.stop)

    def raw(self, path, value):
        data = value if isinstance(value, bytes) else (json.dumps(value) + "\n").encode()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def write_manifest(self, names=None):
        receipts = {}
        for name in names or self.artifacts:
            data = (self.folder / name).read_bytes() if (self.folder / name).exists() else b""
            receipts[name] = {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
        self.raw(self.folder / "manifest.json", {"transformation_version": V, "artifacts": receipts})

    def public(self):
        return self.atlas_path.read_bytes(), self.index_path.read_bytes()

    def assert_refused(self, message):
        before = self.public()
        with self.assertRaisesRegex(ValueError, message):
            mod.publish("test-coast", self.root)
        self.assertEqual(self.public(), before)

    def test_good_tree_writes_atlas_and_merged_index_from_hashed_bytes(self):
        with patch.object(mod, "read_json", side_effect=real_read_json) as reader:
            self.assertEqual(mod.publish("test-coast", self.root), {"ready": True})
        self.assertFalse([c for c in reader.call_args_list if Path(c.args[0]).parent == self.folder.resolve()
                          and Path(c.args[0]).name != "manifest.json"])  # artifacts parsed from hashed bytes
        self.assertEqual(real_read_json(self.atlas_path), self.artifacts["atlas.json"])
        index = real_read_json(self.index_path)
        self.assertEqual(index["views"], {"OTHER": {"v": 0}, "T1": {"v": 1}})  # owned stale view dropped
        self.assertEqual(index["sources"], {"s0": {}, "s1": {}})
        self.assertEqual(self.validate_qualified_scope.call_args.kwargs["bottom_index"], index)
        self.assertEqual(sorted(p.name for p in self.atlas_path.parent.glob("*.tmp")), [])

    def test_extra_artifact_is_refused(self):
        self.raw(self.folder / "extra.json", {"x": 1})
        self.write_manifest([*self.artifacts, "extra.json"])
        self.assert_refused("Subset artifacts must be atlas.json, quality.json and bottom-index-fragment.json")
        self.validate_qualified_scope.assert_not_called()

    def test_each_missing_artifact_is_refused(self):
        for missing in self.artifacts:
            with self.subTest(missing=missing):
                self.write_manifest([n for n in self.artifacts if n != missing])
                self.assert_refused("Subset artifacts must be atlas.json, quality.json and bottom-index-fragment.json")
        self.validate_qualified_scope.assert_not_called()

    def test_hashed_bytes_that_are_not_json_are_refused(self):
        for data in (b"{not json", b"\xff\xfe{}"):
            with self.subTest(data=data):
                self.raw(self.folder / "atlas.json", data)
                self.write_manifest()
                self.assert_refused("Subset artifact is not JSON: atlas.json")

    def test_parse_keeps_read_json_strictness(self):
        for data, message in ((b'{"a":1,"a":2}', "Duplicate JSON key"), (b'{"a":NaN}', "Non-finite JSON number")):
            with self.subTest(data=data):
                self.raw(self.folder / "quality.json", data)
                self.write_manifest()
                self.assert_refused(message)

    def test_hash_mismatch_is_refused(self):
        self.raw(self.folder / "bottom-index-fragment.json", {"views": {"T1": {"v": 2}}})
        self.assert_refused("Subset artifact changed")

    def test_validation_failure_leaves_both_public_files(self):
        self.validate_qualified_scope.side_effect = ValueError("closure review failed")
        self.assert_refused("closure review failed")

    def test_failed_index_write_restores_previous_atlas(self):
        old_atlas = self.atlas_path.read_bytes()
        old_index = self.index_path.read_bytes()

        def failing(path, value, **kwargs):
            if Path(path) == self.index_path.resolve():
                raise OSError("disk full")
            return real_atomic_json(path, value, **kwargs)
        with patch.object(mod, "atomic_json", side_effect=failing) as writer:
            with self.assertRaisesRegex(OSError, "disk full"):
                mod.publish("test-coast", self.root)
        self.assertEqual(writer.call_count, 2)  # the new atlas was written before the index failed
        self.assertEqual(self.public(), (old_atlas, old_index))
        self.assertEqual(sorted(p.name for p in self.atlas_path.parent.glob("*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
