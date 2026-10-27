"""Portable synthetic render-face contract; imports are inert for peer discovery.

Only mesh.render_png and its pure NumPy dependency are exercised. No align,
build_mesh, rasterio, contracts, startup, source or cache imports are needed.
Baseline PNG bytes were captured from the complete pinned, unmodified API.
"""
import base64
from contextlib import ExitStack, contextmanager
import hashlib
import importlib
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch
import zlib

from tests._support import ROOT as REPO

FIXTURES = REPO / "tests/fixtures/sc116-render-faces"
RUN_ROOT = None
EVENTS = []
BASE = "2979d59bfbb7d724eb83b34a48102b914ee8eaa3"
MESH_SHA = "c3a6f0678a693a7b0f0ada2d891add312bb3454548fea15f8fb68156cdc7d757"


def digest(data):
    return hashlib.sha256(data).hexdigest()


@contextmanager
def offline_scope():
    """Reversible sentinels, installed before product imports, not a sandbox."""
    def denied(*args, **kwargs):
        raise RuntimeError("sc116_offline_boundary")
    with ExitStack() as stack:
        for target in ("socket.socket.connect", "socket.socket.connect_ex",
                       "socket.socket.send", "socket.socket.sendall", "socket.socket.sendto",
                       "socket.create_connection", "socket.getaddrinfo",
                       "subprocess.Popen", "subprocess.run", "os.system",
                       "os.posix_spawn", "os.posix_spawnp", "os.fork"):
            stack.enter_context(patch(target, denied))
        yield


def load_api():
    """Use the registered package, never extracted or executed source strings."""
    return importlib.import_module("skippercast.coastal.render.mesh")


def synthetic(np, count=3, dtype="int32"):
    vertices = np.array([[0., 0., 0.], [10., 0., 1.], [0., 10., 2.],
                         [10., 10., 0.]], dtype=np.float64)[:count].copy()
    colors = np.array([[220, 40, 60], [30, 210, 80], [40, 80, 230],
                       [230, 180, 40]], dtype=np.uint8)[:count].copy()
    faces = [[0, 1, 2]] if count == 3 else [[0, 1, 2], [1, 3, 2]]
    return {"vertices": vertices, "colors": colors,
            "faces": np.array(faces, dtype=dtype)}


def snapshot(mesh):
    result = {}
    for key, value in mesh.items():
        if hasattr(value, "dtype"):
            result[key] = {"dtype": str(value.dtype), "shape": list(value.shape),
                           "sha256": digest(value.tobytes()),
                           "mask": digest(value.mask.tobytes()) if hasattr(value, "mask") else None}
        else:
            result[key] = repr(value)
    return result


def png_pixels(np, encoded):
    if encoded[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not_png")
    offset, packed, dimensions = 8, b"", None
    while offset < len(encoded):
        size = struct.unpack(">I", encoded[offset:offset + 4])[0]
        kind = encoded[offset + 4:offset + 8]
        data = encoded[offset + 8:offset + 8 + size]
        if kind == b"IHDR":
            dimensions = struct.unpack(">IIBBBBB", data)
        if kind == b"IDAT":
            packed += data
        offset += size + 12
    if dimensions != (640, 480, 8, 2, 0, 0, 0):
        raise ValueError("wrong_png_dimensions")
    rows = np.frombuffer(zlib.decompress(packed), dtype=np.uint8).reshape(480, 1921)
    if rows[:, 0].any():
        raise ValueError("unexpected_png_filter")
    return rows[:, 1:].reshape(480, 640, 3)


class RenderFacesTests(unittest.TestCase):
    def setUp(self):
        self.scope = offline_scope()
        self.scope.__enter__()
        self.addCleanup(self.scope.__exit__, None, None, None)
        self.api = load_api()
        self.np = importlib.import_module("numpy")
        self.assertEqual(Path(self.api.__file__).resolve(),
                         REPO / "src/skippercast/coastal/render/mesh.py")
        if RUN_ROOT is None:
            temporary = tempfile.TemporaryDirectory(prefix="sc116-case-")
            self.addCleanup(temporary.cleanup)
            self.root = Path(temporary.name)
        else:
            RUN_ROOT.mkdir(parents=True, exist_ok=True)
            self.root = Path(tempfile.mkdtemp(prefix="sc116-case-", dir=RUN_ROOT))
        self.baseline = json.loads((FIXTURES / "baseline.json").read_text())
        self.assertEqual(self.baseline["base"], BASE)
        self.assertEqual(self.baseline["mesh_sha256"], MESH_SHA)

    def valid(self, count=3, dtype="int32"):
        mesh = synthetic(self.np, count, dtype)
        before = snapshot(mesh)
        path = self.root / f"valid-{count}-{dtype}.png"
        metadata = self.api.render_png(mesh, path)
        encoded = path.read_bytes()
        expected = self.baseline["meshes"][str(count)]
        self.assertEqual(encoded, base64.b64decode(expected["png_base64"], validate=True))
        self.assertEqual(metadata, expected["metadata"])
        self.assertEqual(snapshot(mesh), before)
        pixels = png_pixels(self.np, encoded)
        occupied = (pixels != [232, 240, 244]).any(axis=2)
        y, x = self.np.nonzero(occupied)
        self.assertEqual(metadata["visible_pixels"], int(occupied.sum()))
        self.assertEqual(metadata["visible_bounds_px"],
                         [int(x.min()), int(y.min()), int(x.max()), int(y.max())])
        self.assertGreater(metadata["visible_pixels"], 0)
        EVENTS.append({"id": self.id(), "fixture": before, "after": snapshot(mesh),
                       "png": str(path), "png_sha256": digest(encoded), "metadata": metadata})

    def refusal(self, faces):
        mesh = synthetic(self.np)
        mesh["faces"] = faces
        before = snapshot(mesh)
        path = self.root / "sentinel.png"
        sentinel = b"sc116-existing-target-unchanged\n"
        path.write_bytes(sentinel)
        with patch.object(self.api, "camera_projection", wraps=self.api.camera_projection) as camera, \
             patch.object(self.api, "write_png", wraps=self.api.write_png) as writer, \
             patch.object(self.np, "full", wraps=self.np.full) as allocation:
            with self.assertRaisesRegex(ValueError, "preview_faces_invalid"):
                self.api.render_png(mesh, path)
            camera.assert_not_called()
            writer.assert_not_called()
            allocation.assert_not_called()
        self.assertEqual(path.read_bytes(), sentinel)
        self.assertEqual(snapshot(mesh), before)
        EVENTS.append({"id": self.id(), "fixture": before, "after": snapshot(mesh),
                       "sentinel": str(path), "before_sha256": digest(sentinel),
                       "after_sha256": digest(path.read_bytes()), "projection_write_allocation_calls": 0})

    def test_regression_negative_index(self):
        self.refusal(self.np.array([[0, 1, -1]], dtype=self.np.int64))

    def test_regression_vertex_count_index(self):
        self.refusal(self.np.array([[0, 1, 3]], dtype=self.np.int32))

    def test_regression_huge_unsigned(self):
        self.refusal(self.np.array([[0, 1, 2**64 - 1]], dtype=self.np.uint64))

    def test_regression_float(self):
        self.refusal(self.np.array([[0., 1., 2.]]))

    def test_regression_boolean(self):
        self.refusal(self.np.array([[True, False, True]]))

    def test_regression_object(self):
        self.refusal(self.np.array([[0, 1, 2]], dtype=object))

    def test_regression_non_index_dtypes(self):
        for dtype in ("timedelta64[s]", "datetime64[s]", "complex128", "U1"):
            with self.subTest(dtype=dtype):
                self.refusal(self.np.array([[0, 1, 2]], dtype=dtype))

    def test_regression_array_subclasses(self):
        class FaceArray(self.np.ndarray):
            pass

        plain = self.np.array([[0, 1, 2]], dtype=self.np.int64)
        for faces in (self.np.matrix(plain), plain.view(FaceArray)):
            with self.subTest(kind=type(faces).__name__):
                self.refusal(faces)

    def test_regression_empty(self):
        self.refusal(self.np.empty((0, 3), dtype=self.np.int64))

    def test_regression_ragged(self):
        ragged = self.np.empty(2, dtype=object)
        ragged[:] = [[0, 1, 2], [0, 1]]
        for faces in ([[0, 1, 2], [0, 1]], ragged):
            with self.subTest(kind=type(faces).__name__):
                self.refusal(faces)

    def test_regression_not_array(self):
        self.refusal([[0, 1, 2]])

    def test_regression_one_dimension(self):
        for faces in (self.np.array([0, 1, 2]), self.np.array(0)):
            with self.subTest(shape=faces.shape):
                self.refusal(faces)

    def test_regression_wrong_columns(self):
        for columns in (0, 1, 2, 4):
            with self.subTest(columns=columns):
                self.refusal(self.np.zeros((1, columns), dtype=self.np.int32))

    def test_regression_three_dimensions(self):
        self.refusal(self.np.array([[[0, 1, 2]]]))

    def test_regression_masked(self):
        for mask in (False, [[False, True, False]]):
            with self.subTest(mask=mask):
                self.refusal(self.np.ma.array([[0, 1, 2]], mask=mask))

    def test_regression_valid(self):
        for count in (3, 4):
            for dtype in ("int32", "int64", "uint8", "uint32", "uint64"):
                with self.subTest(count=count, dtype=dtype):
                    self.valid(count, dtype)

    def test_regression_degenerate(self):
        mesh = synthetic(self.np)
        mesh["faces"][:] = 0
        before = snapshot(mesh)
        path = self.root / "degenerate.png"
        path.write_bytes(b"degenerate-sentinel")
        with patch.object(self.api, "write_png", wraps=self.api.write_png) as writer:
            with self.assertRaisesRegex(ValueError, "preview_has_no_visible_geometry"):
                self.api.render_png(mesh, path)
            writer.assert_not_called()
        self.assertEqual(path.read_bytes(), b"degenerate-sentinel")
        self.assertEqual(snapshot(mesh), before)
        EVENTS.append({"id": self.id(), "fixture": before, "after": snapshot(mesh),
                       "sentinel_sha256": digest(path.read_bytes())})

    def test_compatibility_log_seals(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "sc116_evidence", REPO / "tools/run_sc116_render_faces.py")
        runner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(runner)
        paths = [self.root / name for name in ("stdout.txt", "stderr.txt")]
        for path in paths:
            path.write_text("completed child output\n")
        seal = runner.seal_logs(paths)
        self.assertTrue(runner.verify_logs(seal))
        missing = {str(self.root / "absent.txt"): next(iter(seal.values()))}
        with self.assertRaisesRegex(ValueError, "sc116_log_integrity_invalid"):
            runner.verify_logs(missing)
        paths[0].write_text("changed child output\n")
        with self.assertRaisesRegex(ValueError, "sc116_log_integrity_invalid"):
            runner.verify_logs(seal)
        # A separate pristine log is sealed, then an exit-writer-like append occurs.
        late = self.root / "late.txt"
        late.write_text("complete\n")
        late_seal = runner.seal_logs([late])
        self.assertTrue(runner.verify_logs(late_seal))
        with late.open("a") as output:
            output.write("late append\n")
        with self.assertRaisesRegex(ValueError, "sc116_log_integrity_invalid"):
            runner.verify_logs(late_seal)
        with self.assertRaisesRegex(ValueError, "sc116_logs_missing"):
            runner.verify_logs({})
        EVENTS.append({"id": self.id(), "complete_positive": True,
                       "missing_rejected": True, "changed_rejected": True,
                       "late_append_rejected": True})

    def test_compatibility_three_vertices(self):
        for dtype in ("int32", "int64", "uint64"):
            with self.subTest(dtype=dtype):
                self.valid(3, dtype)

    def test_compatibility_four_vertices(self):
        for dtype in ("int32", "int64", "uint64"):
            with self.subTest(dtype=dtype):
                self.valid(4, dtype)


if __name__ == "__main__":
    unittest.main()
