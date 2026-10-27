"""File-only offline SC116 runner. Machine validity remains REVIEW REQUIRED."""
import argparse
import base64
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import traceback
import unittest
import uuid

BASE = "2979d59bfbb7d724eb83b34a48102b914ee8eaa3"
MESH_SHA = "c3a6f0678a693a7b0f0ada2d891add312bb3454548fea15f8fb68156cdc7d757"
REPO = Path(__file__).resolve().parents[1]
REGRESSION = ["array_subclasses", "boolean", "degenerate", "empty", "float", "huge_unsigned", "masked",
              "negative_index", "non_index_dtypes", "not_array", "object", "one_dimension", "ragged",
              "three_dimensions", "valid", "vertex_count_index", "wrong_columns"]
COMPATIBILITY = ["four_vertices", "log_seals", "three_vertices"]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def seal_logs(paths):
    """Caller invokes only after the child and its exit writers have finished."""
    return {str(path): {"sha256": sha(path), "size": Path(path).stat().st_size}
            for path in paths}


def verify_logs(seal):
    for name, expected in seal.items():
        path = Path(name)
        if not path.is_file() or {"sha256": sha(path), "size": path.stat().st_size} != expected:
            raise ValueError("sc116_log_integrity_invalid")
    if not seal:
        raise ValueError("sc116_logs_missing")
    return True


def load_tests():
    spec = importlib.util.spec_from_file_location(
        "test_sc116_render_faces", REPO / "tests/gis/test_sc116_render_faces.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def preflight(manifest_path):
    manifest = json.loads(manifest_path.read_text())
    if (manifest.get("schema") != "agentorange.source-manifest/v1"
            or Path(manifest["write_root"]).resolve() != REPO.parent
            or Path(manifest["repo"]).resolve() != REPO
            or manifest.get("head") != BASE or manifest.get("clean") is not True):
        raise ValueError("sc116_source_manifest_invalid")
    if (REPO / ".venv").resolve() != Path(manifest["runtime"]["repo_venv"]).resolve():
        raise ValueError("sc116_runtime_link_invalid")
    if Path(sys.executable).resolve() != (REPO / ".venv/bin/python3").resolve():
        raise ValueError("sc116_interpreter_invalid")
    scan = Path(manifest["runtime"]["credential_scan_python3"])
    if not scan.is_file():
        raise ValueError("sc116_scanner_missing")
    # Metadata lookup completes BEFORE installing the no-subprocess sentinels.
    head = subprocess.run(["git", "-C", str(REPO), "rev-parse", "HEAD"],
                          capture_output=True, text=True, check=True).stdout.strip()
    return manifest, head


def run_named(module, names):
    expected = ["test_sc116_render_faces.RenderFacesTests." + name for name in names]
    suite = unittest.TestSuite(module.RenderFacesTests(name) for name in names)
    stream = io.StringIO()
    class RecordingResult(unittest.TextTestResult):
        def startTest(self, test):
            actual.append(test.id())
            super().startTest(test)
    actual = []
    result = unittest.TextTestRunner(stream=stream, verbosity=2,
                                   resultclass=RecordingResult).run(suite)
    text = stream.getvalue()
    print(text, end="")
    return result, {"expected_ids": expected, "actual_ids": actual,
                    "expected_count": len(expected), "actual_count": result.testsRun,
                    "failures": [(test.id(), text) for test, text in result.failures],
                    "errors": [(test.id(), text) for test, text in result.errors],
                    "skips": [(test.id(), reason) for test, reason in result.skipped]}, text


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", required=True, choices=("regression", "compatibility",
                        "negative-control", "capture-baseline", "premise", "ordinary-check"))
    parser.add_argument("--source-manifest", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    sys.dont_write_bytecode = True
    if not args.out.resolve().is_relative_to(REPO.parent / "out"):
        raise ValueError("sc116_output_root_invalid")
    args.out.mkdir(parents=True, exist_ok=True)
    root = args.out / ("run-" + uuid.uuid4().hex)
    root.mkdir()
    receipt = {"schema": "sc116.receipt/v1", "suite": args.suite, "base": BASE,
               "argv": sys.argv, "cwd": str(Path.cwd()), "interpreter": sys.executable,
               "root": str(root), "exit": 1, "status": "REVIEW_REQUIRED"}
    complete = io.StringIO()
    exit_code = 1
    try:
        manifest, head = preflight(args.source_manifest)
        receipt.update(head=head, source_manifest_sha256=sha(args.source_manifest))
        sys.path.insert(0, str(REPO))
        sys.path.insert(0, str(REPO / "src"))
        module = load_tests()
        module.RUN_ROOT = root
        receipt["import_trace"] = ["skippercast", "skippercast.coastal",
                                   "skippercast.coastal.render", "skippercast.coastal.render.mesh",
                                   "numpy (only inside offline scope)"]
        receipt["fixture_accesses"] = ["tests/fixtures/sc116-render-faces/baseline.json",
                                      "synthetic in-memory NumPy vertices/faces/colors", str(root)]
        receipt["sources"] = {name: sha(REPO / name) for name in
                              ("src/skippercast/coastal/render/mesh.py",
                               "tests/gis/test_sc116_render_faces.py",
                               "tools/run_sc116_render_faces.py")}
        env_before = dict(os.environ)
        temp_before = tempfile.tempdir
        with module.offline_scope():
            api = module.load_api()
            import numpy as np
            if Path(api.__file__).resolve() != REPO / "src/skippercast/coastal/render/mesh.py":
                raise ValueError("sc116_wrong_product_origin")
            receipt["module_origins"] = {name: getattr(value, "__file__", None)
                                          for name, value in sorted(sys.modules.items())
                                          if name == "numpy" or name.startswith("skippercast")}
            if any(name.startswith(("rasterio", "skippercast.coastal.startup"))
                   for name in sys.modules):
                raise ValueError("sc116_unexpected_native_import")
            if args.suite == "capture-baseline":
                if head != BASE or sha(Path(api.__file__)) != MESH_SHA:
                    raise ValueError("sc116_baseline_pin_invalid")
                baseline = {"base": BASE, "mesh_sha256": MESH_SHA, "meshes": {}}
                for count in (3, 4):
                    path = root / f"baseline-{count}.png"
                    mesh = module.synthetic(np, count)
                    metadata = api.render_png(mesh, path)
                    baseline["meshes"][str(count)] = {
                        "png_base64": base64.b64encode(path.read_bytes()).decode("ascii"),
                        "png_sha256": sha(path), "metadata": metadata}
                # This explicit pre-patch authoring mode freezes text fixture bytes once.
                fixture = module.FIXTURES / "baseline.json"
                fixture.parent.mkdir(parents=True, exist_ok=True)
                with fixture.open("x") as output:
                    json.dump(baseline, output, indent=2)
                    output.write("\n")
                receipt["baseline_fixture_sha256"] = sha(fixture)
                exit_code = 0
            elif args.suite == "negative-control":
                from unittest.mock import patch
                if not hasattr(api, "_validate_preview_faces"):
                    raise ValueError("sc116_validation_seam_missing")
                with patch.object(api, "_validate_preview_faces", return_value=None):
                    result, data, text = run_named(module, ["test_regression_negative_index"])
                    complete.write(text)
                    receipt["mutant"] = data
                    detected = (result.testsRun == 1 and len(result.failures) == 1
                                and not result.errors and not result.skipped
                                and "ValueError not raised" in result.failures[0][1])
                    positive, positive_data, text = run_named(module, ["test_regression_valid"])
                    complete.write(text)
                    receipt["mutant_positive"] = positive_data
                restored, restored_data, text = run_named(
                    module, ["test_regression_negative_index", "test_regression_valid"])
                complete.write(text)
                receipt["restored"] = restored_data
                receipt.update(mutant_detected=detected,
                               positive_passed=positive.wasSuccessful() and not positive.skipped,
                               restored_passed=restored.wasSuccessful() and not restored.skipped)
                exit_code = 0 if (detected and receipt["positive_passed"]
                                  and receipt["restored_passed"]) else 1
            else:
                if args.suite in ("premise", "ordinary-check"):
                    names = (["test_regression_negative_index", "test_regression_valid"]
                             if args.suite == "premise" else
                             ["test_compatibility_three_vertices", "test_compatibility_four_vertices"])
                else:
                    prefix = "test_" + args.suite + "_"
                    suffixes = REGRESSION if args.suite == "regression" else COMPATIBILITY
                    names = [prefix + suffix for suffix in suffixes]
                    discovered = sorted(name for name in unittest.defaultTestLoader.getTestCaseNames(
                        module.RenderFacesTests) if name.startswith(prefix))
                    if sorted(names) != discovered:
                        raise ValueError("sc116_missing_or_unexpected_test_ids")
                result, data, text = run_named(module, names)
                complete.write(text)
                receipt["tests"] = data
                success = (result.wasSuccessful() and not result.skipped
                           and result.testsRun == len(names) and result.testsRun > 0)
                if args.suite == "premise":
                    if head != BASE or sha(Path(api.__file__)) != MESH_SHA:
                        raise ValueError("sc116_premise_pin_invalid")
                    success = (result.testsRun == 2 and len(result.failures) == 1
                               and not result.errors and not result.skipped
                               and result.failures[0][0]._testMethodName == "test_regression_negative_index"
                               and "ValueError not raised" in result.failures[0][1])
                    receipt["baseline_defect_reproduced"] = success
                exit_code = 0 if success else 1
        if dict(os.environ) != env_before:
            raise ValueError("sc116_ambient_environment_changed")
        if tempfile.tempdir != temp_before:
            # tempfile caches a computed default; restore this reversible test scope.
            tempfile.tempdir = temp_before
        receipt["ambient_environment_unchanged"] = True
        receipt["fixture_hashes"] = {str(path.relative_to(REPO)): sha(path)
                                     for path in sorted(module.FIXTURES.glob("*.json"))}
        receipt["events"] = module.EVENTS
        if sha(Path(api.__file__)) != receipt["sources"]["src/skippercast/coastal/render/mesh.py"]:
            raise ValueError("sc116_product_bytes_changed")
    except Exception:
        text = traceback.format_exc()
        print(text, file=sys.stderr)
        complete.write(text)
        receipt["error"] = text
        exit_code = 1
    receipt["exit"] = exit_code
    (root / "tests.raw.txt").write_text(complete.getvalue())
    (root / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({"receipt": str(root / "receipt.json"), "exit": exit_code,
                      "suite": args.suite, "head": receipt.get("head")}))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
