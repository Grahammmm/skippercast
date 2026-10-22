"""Render accepted private v2.1 inputs with fixed cameras; grants no display approval."""
import argparse
import ctypes
import errno
from datetime import datetime, timezone
import json
import os
import tempfile
from pathlib import Path

from .align import identity, verify_alignment
from .mesh import build_mesh, render_png
from ..receipts import atomic_json


def read_json(path):
    path = Path(path)
    if path.stat().st_size > 2 * 1024 * 1024:
        raise ValueError("json_byte_bound")
    def reject(value):
        raise ValueError("nonfinite_json:" + value)
    return json.loads(path.read_text(), parse_constant=reject)


def verified_path(root, ref):
    base = Path(root).resolve(strict=True)
    raw = Path(ref["path"])
    if raw.is_absolute() or ".." in raw.parts:
        raise ValueError("artifact_path_must_be_confined_relative")
    target = base
    for part in raw.parts:
        target /= part
        if target.is_symlink():
            raise ValueError("symlink_artifact")
    path = target.resolve(strict=True)
    if not path.is_relative_to(base) or identity(path) != {k: ref[k] for k in ("sha256", "bytes")}:
        raise ValueError("artifact_identity_mismatch")
    return path


def preview(root, manifest, *, output_dir, now, slice_id=None, _checkpoint=None, minimum_valid_until=None):
    """The producer's verifier is the sole approval gate, never a preview flag."""
    from skippercast.coastal.handoff.render import verify
    checked = verify(root, manifest, now=now, purpose="private_preview",
                     minimum_valid_until=minimum_valid_until)
    if slice_id is None and len(checked["selected_slice_ids"]) == 1:
        slice_id = checked["selected_slice_ids"][0]
    if not checked["ready"] or slice_id not in checked["selected_slice_ids"]:
        return {"schema": "coastal-render-preview-v1", "state": "held",
                "holds": checked["holds"] or ["slice_not_accepted"], "artifacts": [],
                "publication_or_fishing_approval": False}
    document = checked["document"]
    rows = [row for row in document["slices"] if row["id"] == slice_id]
    if len(rows) != 1:
        raise ValueError("single_selected_slice_required")
    row = rows[0]
    terrain = verified_path(root, row["terrain"])
    support = verified_path(root, row["mask"])
    imagery = verified_path(root, row["imagery"])
    alignment = verified_path(root, row["alignment"])
    measured = verify_alignment(read_json(alignment), terrain, imagery, root=root, now=now,
                                minimum_valid_until=minimum_valid_until)
    import numpy as np
    base, out = output_path(root, output_dir)
    binding = render_binding(row, document)
    if out.exists():
        return completed_result(out, out, base, binding)
    out.parent.mkdir(parents=True, exist_ok=True)
    # Recover only complete matching stages; incomplete stages stay as evidence.
    stages = sorted(out.parent.glob("." + out.name + ".render-*"))
    for stage in stages:
        if stage.is_symlink() or not stage.is_dir():
            raise ValueError("preview_staging_unknown")
        if (stage / "complete.json").exists():
            result = completed_result(stage, out, base, binding)
            publish_staging(stage, out)
            return result
    if len(stages) >= 4:
        raise ValueError("preview_staging_recovery_bound")
    stage = Path(tempfile.mkdtemp(prefix="." + out.name + ".render-", dir=out.parent))
    atomic_json(stage / "ownership.json", {"schema": "coastal-render-staging-v1", "binding": binding})
    checkpoint = _checkpoint or (lambda event: None)
    checkpoint("staging_created")
    mesh = build_mesh(terrain, support, imagery, row["vertical"])
    mesh_path, image_path = stage / "measured-mesh.npz", stage / "preview.png"
    # Finite vertices only; supported grid positions preserve auditability.
    np.savez(mesh_path, vertices=mesh["vertices"], faces=mesh["faces"],
             colors=mesh["colors"], grid_pixels=mesh["grid_pixels"], support=mesh["support"])
    checkpoint("mesh_written")
    rendered = render_png(mesh, image_path)
    checkpoint("png_written")
    measured_support = document["run"]["mapping_input"]["native_facts"]["support"]
    result = {"schema": "coastal-render-preview-v1", "state": "done", "holds": [], "render_binding": binding,
              "slice_id": slice_id, "private_preview_ready": True,
              "product_integration": {"state": "held",
                  "holds": ["product_loader_support_contract_unavailable"]},
              "publication_or_fishing_approval": False,
              "synthetic": document.get("synthetic") is True,
              "imagery_label": "synthetic test texture" if document.get("synthetic") is True else "accepted source imagery",
              "artifacts": [{"path": (out.relative_to(base) / path.name).as_posix(), **identity(path), "format": fmt, "contract": "coastal-measured-mesh-v1" if fmt == "npz" else "coastal-fixed-preview-png-v1"}
                            for path, fmt in ((mesh_path, "npz"), (image_path, "png"))],
              "terrain": row["terrain"], "support": row["mask"], "imagery": row["imagery"],
              "alignment": row["alignment"], "max_residual_m": measured["max_residual_m"],
              "vertices": len(mesh["vertices"]), "triangles": len(mesh["faces"]),
              "supported_cells": int(mesh["support"].sum()),
              "imagery_mask_excluded_triangles": mesh["imagery_mask_excluded_triangles"],
              "meshed_support_cells": mesh["meshed_support_cells"],
              "unmeshed_support_cells": mesh["unmeshed_support_cells"],
              "source_support_kind": measured_support["support_kind"],
              "source_limitations": measured_support["limitations"] + row.get("limitations", []),
              "geometry_interpolation": "planar_triangles_between_native_samples_visualization_only",
              "color_interpolation": "vertex_sampled_imagery_interpolation_visualization_only",
              "grid_cells": int(mesh["support"].size), "crs": mesh["crs"],
              "vertical": row["vertical"], "display_z": "positive_up_metres", **rendered,
              "limitations": ["No vertical datum transformation performed.",
                               "Only triangles whose three original samples are supported are rendered.",
                               "Fixed private camera; no product loader or website acceptance.",
                               "Imagery correspondence uses independent authority attestation, not cryptographic proof or feature matching.",
                               "Triangle interiors and color gradients visualize between-node interpolation; they are not additional measurements.",
                               "Imagery void boundaries use conservative triangle bounding rectangles."]}
    for path in (mesh_path, image_path):
        with path.open("rb") as stream:
            os.fsync(stream.fileno())
    atomic_json(stage / "preview-receipt.json", result)
    atomic_json(stage / "complete.json", {"schema": "coastal-render-complete-v1", "binding": binding,
                                          "receipt": identity(stage / "preview-receipt.json")})
    checkpoint("complete_staged")
    publish_staging(stage, out)
    checkpoint("published")
    return result


def output_path(root, relative):
    base = Path(root).resolve(strict=True)
    relative = Path(relative)
    if relative.is_absolute() or ".." in relative.parts or not relative.parts:
        raise ValueError("preview_output_must_be_root_relative")
    out = base
    for part in relative.parts:
        out /= part
        if out.is_symlink():
            raise ValueError("preview_output_symlink")
    return base, out


def render_binding(row, document):
    from ..receipts import digest
    from .mesh import CAMERA
    import numpy
    import rasterio
    module = Path(__file__).parent
    return digest({"inputs": row, "synthetic": document.get("synthetic") is True,
                   "code": {name: identity(module / name) for name in ("align.py", "mesh.py", "preview.py")},
                   "dependencies": {"numpy": numpy.__version__, "rasterio": rasterio.__version__},
                   "camera": CAMERA})


def completed_result(candidate, out, base, binding):
    for name in ("complete.json", "preview-receipt.json", "ownership.json"):
        if (candidate/name).is_symlink():
            raise ValueError("preview_completion_symlink")
    ownership = read_json(candidate / "ownership.json") if (candidate / "ownership.json").is_file() else {}
    if ownership.get("schema") != "coastal-render-staging-v1":
        raise ValueError("preview_output_incomplete_or_unknown")
    if ownership.get("binding") != binding:
        raise ValueError("preview_output_input_or_code_changed")
    marker_path = candidate / "complete.json"
    if not marker_path.is_file():
        raise ValueError("preview_output_incomplete_or_unknown")
    marker = read_json(marker_path)
    if marker.get("schema") != "coastal-render-complete-v1" or marker.get("binding") != binding:
        raise ValueError("preview_output_input_or_code_changed")
    receipt_path = candidate / "preview-receipt.json"
    if identity(receipt_path) != marker.get("receipt"):
        raise ValueError("preview_receipt_identity_mismatch")
    result = read_json(receipt_path)
    if result.get("render_binding") != binding or result.get("state") != "done":
        raise ValueError("preview_completion_binding_invalid")
    for ref in result["artifacts"]:
        expected = out.relative_to(base) / Path(ref["path"]).name
        if Path(ref["path"]) != expected or Path(ref["path"]).name not in {"measured-mesh.npz", "preview.png"}:
            raise ValueError("preview_completion_ref_invalid")
        artifact = candidate / Path(ref["path"]).name
        if artifact.is_symlink() or identity(artifact) != {key: ref[key] for key in ("sha256", "bytes")}:
            raise ValueError("preview_completed_artifact_changed")
    if {ref["path"] for ref in result["artifacts"]} != {
            (out.relative_to(base)/"measured-mesh.npz").as_posix(), (out.relative_to(base)/"preview.png").as_posix()}:
        raise ValueError("preview_completion_missing_artifacts")
    return result


def sync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def publish_staging(stage, out):
    if out.exists():
        raise ValueError("preview_output_collision")
    # AgentOrange/Linux renameat2 makes no-replacement atomic: even an empty
    # concurrently created unknown directory must remain untouched.
    libc = ctypes.CDLL(None, use_errno=True)
    rename = getattr(libc, "renameat2", None)
    if rename is None:
        raise ValueError("atomic_directory_no_replace_unavailable")
    rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    rename.restype = ctypes.c_int
    if rename(-100, os.fsencode(stage), -100, os.fsencode(out), 1) != 0:
        error = ctypes.get_errno()
        if error in (errno.EEXIST, errno.ENOTEMPTY):
            raise ValueError("preview_output_collision")
        raise OSError(error, os.strerror(error))
    sync_directory(out.parent)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--handoff", type=Path, required=True)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--slice-id", required=True)
    parser.add_argument("--result", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = preview(args.root, read_json(args.handoff), output_dir=args.output_dir,
                         slice_id=args.slice_id, now=datetime.now(timezone.utc))
    except (ValueError, KeyError, TypeError, OSError) as error:
        result = {"schema": "coastal-render-preview-v1", "state": "held",
                  "holds": [str(error)], "artifacts": [], "publication_or_fishing_approval": False}
    args.result.parent.mkdir(parents=True, exist_ok=True)
    atomic_json(args.result, result)
    print(json.dumps(result, indent=2, allow_nan=False))
    return 0 if result["state"] == "done" else 2


if __name__ == "__main__":
    raise SystemExit(main())
