"""Stage order and independent dispatch gates. No user-supplied executable paths."""
import hashlib
import json
import math
from pathlib import Path
import sys

ORDER = ("render", "map", "qualify", "acquire", "discover")
NEXT = {"discover": "acquire", "acquire": "qualify", "qualify": "map", "map": "render"}
DIMENSION = {"acquire": "discovery", "qualify": "observation", "map": "qualification", "render": "mapping"}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def verify_ref(root, ref):
    """Reject symlinks at every component and verify actual bytes, not path claims."""
    base = Path(root).resolve(strict=True)
    raw = Path(ref["path"])
    target = raw if raw.is_absolute() else base / raw
    if ".." in target.parts:
        raise ValueError("parent traversal")
    relative = target.relative_to(base)
    cursor = base
    for part in relative.parts:
        cursor /= part
        if cursor.is_symlink():
            raise ValueError("symlink artifact")
    path = target.resolve(strict=True)
    path.relative_to(base)
    if not path.is_file() or path.stat().st_size != ref["bytes"]:
        raise ValueError("artifact byte count")
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b""):
            h.update(chunk)
    if h.hexdigest() != ref["sha256"]:
        raise ValueError("artifact hash mismatch")
    return path


def readiness(stage, evidence, *, now, duration_s, code_sha, deps_sha, synthetic=False):
    """Freshness, readiness dimensions, holds and implementation identity are separate gates.

    The stage wrapper must provide a verified receipt; this gate never manufactures
    scientific qualification or removes a hold from that receipt.
    """
    if stage == "render" and evidence.get("schema") == "coastal-terrain-only-input-v1":
        import json
        from importlib.resources import files
        from jsonschema import Draft202012Validator
        holds = []
        schema=json.loads(files("skippercast.coastal.resources").joinpath("coastal-terrain-only-input-v1.schema.json").read_text())
        if list(Draft202012Validator(schema).iter_errors(evidence)):
            holds.append("terrain_only_input_schema_invalid")
        review=evidence.get("scientific_review",{})
        if review.get("contract") != "coastal-terrain-only-science-review-v1":
            holds.append("independent_scientific_review_required")
        # Fixed existing renderer verification checks the actual independent
        # review before output; completion rechecks that same contract.
        return (not holds, sorted(set(holds)))
    holds = list(evidence.get("holds", []))
    if stage == "discover":
        return not holds, holds
    if evidence.get("code_sha") != code_sha or evidence.get("deps_sha") != deps_sha:
        holds.append("implementation_stale")
    expires = evidence.get("valid_until_epoch")
    if not isinstance(expires, (int, float)) or not math.isfinite(expires) or expires <= now + duration_s:
        holds.append("evidence_expired")
    if evidence.get("dimensions", {}).get(DIMENSION[stage]) != "ready":
        holds.append("dimension_not_ready")
    if evidence.get("synthetic") and not synthetic:
        holds.append("synthetic_not_real_evidence")
    if stage in {"map", "render"} and evidence.get("rights", {}).get("private_use") is not True:
        holds.append("private_rights_unresolved")
    if stage == "map":
        if evidence.get("schema") != "private-mapping-input-v2":
            holds.append("mapping_contract_unavailable")
        if evidence.get("review", {}).get("independent") is not True:
            holds.append("independent_review_required")
    if stage == "render":
        if evidence.get("schema") not in {"render-handoff-v2.1", "render-handoff-v2"}:
            holds.append("render_contract_unavailable")
        alignment = evidence.get("alignment", {})
        residual, resolution = alignment.get("max_residual_m"), alignment.get("terrain_resolution_m")
        if not isinstance(residual, (int, float)) or not isinstance(resolution, (int, float)) or not (math.isfinite(residual) and math.isfinite(resolution) and 0 <= residual <= resolution):
            holds.append("alignment_unresolved")
    return not holds, sorted(set(holds))


def argv_for(job, job_path, output_dir):
    if job["stage"] not in ORDER:
        raise ValueError("unsupported stage")
    return [sys.executable, "-m", "skippercast.coastal.stage_cli", "run", "--job", str(job_path), "--out", str(output_dir)]
