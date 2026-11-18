"""Synthetic CLI controls for statewide regular BAG/camera audit receipts."""
import hashlib
import json
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.gis
CANONICAL = Path("research/receipts/noaa-statewide-regular-camera-review.json")


@pytest.fixture
def run_audit(tmp_path, monkeypatch):
    from research.scripts import audit_statewide_regular_camera as camera

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(camera, "ROOT", tmp_path / "checkout", raising=False)
    records = [
        {"survey_id": name, "url": f"https://example.invalid/{name}.bag", "status": "ok",
         "raster_bounds_wgs84": [-1, -1, 1, 1], "overview_resolution_m": [4, 4],
         "variable_refinement_records": 0}
        for name in ("fixture-cached", "fixture-uncached")
    ]
    inputs = {
        "audit": {"files": records}, "manifest": {}, "sectors": {"sectors": []},
        "mpas": {"sources": {"mpas": {"data": {"geojson": {}, "source_url": "https://example.invalid/mpas"},
                                      "data_retrieved_at": "2020-01-01T00:00:00Z"}}},
        "holds": {"holds": []}, "hazards": {"surveys": []},
    }
    argv = ["audit", "--bag-cache", "cache"]
    for name, content in inputs.items():
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps(content))
        argv.extend((f"--{name}", str(path)))
    cached = records[0]
    digest = hashlib.sha256(cached["url"].encode()).hexdigest()[:16]
    (tmp_path / "cache").mkdir()
    (tmp_path / "cache" / f"{cached['survey_id']}-{digest}.bag").touch()
    monkeypatch.setattr(camera, "rocky_camera_positions", lambda *_: {"fixture-cruise": [(0, 0)]})
    reviewed = []

    def review(*args, **kwargs):
        reviewed.append(kwargs["survey_id"])
        return {"bag_sha256": "a" * 64, "camera_archive_sha256": "b" * 64,
                "camera_archive_url": "https://example.invalid/cruise.zip", "native_cell_m": 4,
                "counts": {}, "transects": [], "camera_species_fields": {}}

    monkeypatch.setattr(camera, "review", review)

    def run(*flags):
        monkeypatch.setattr(sys, "argv", [*argv, *flags])
        camera.main()

    return run, reviewed


@pytest.mark.parametrize("destination", ["omitted", "explicit", "symlink", "hardlink", "checkout"])
def test_diagnostic_cannot_overwrite_canonical(run_audit, destination):
    # F28-13: a zero-limit run used to replace this complete receipt.
    run, reviewed = run_audit
    canonical = Path("checkout") / CANONICAL if destination == "checkout" else CANONICAL
    canonical.parent.mkdir(parents=True)
    original = b'{"scope": "complete fixture"}\n'
    canonical.write_bytes(original)
    output = canonical.resolve()
    if destination == "hardlink":
        output = Path("alias.json")
        output.hardlink_to(canonical)
    elif destination == "symlink":
        output = Path("alias.json")
        output.symlink_to(canonical)
    flags = () if destination == "omitted" else ("--output", str(output))
    with pytest.raises(SystemExit) as exc:
        run("--limit", "0", *flags)
    assert exc.value.code == 2
    assert canonical.read_bytes() == original
    assert not reviewed


@pytest.mark.parametrize(("limit", "attempted", "completed", "failed"), [
    (0, 0, 0, 0), (1, 1, 1, 0), (2, 2, 1, 1), (None, 2, 1, 1),
])
def test_receipt_distinguishes_unattempted_and_failed_pairs(run_audit, limit, attempted, completed, failed):
    # Taking the inventory count after slicing would make even zero-limit look complete.
    run, reviewed = run_audit
    output = Path("diagnostic.json") if limit is not None else CANONICAL
    flags = ("--limit", str(limit), "--output", str(output)) if limit is not None else ()
    run(*flags)
    receipt = json.loads(output.read_text())
    assert receipt["candidate_pairs_with_actual_rocky_camera_positions"] == 2
    assert receipt["attempted_pairs"] == attempted
    assert receipt["unattempted_pairs"] == 2 - attempted
    assert receipt["limit"] == limit
    scope = "statewide-original-camera-regular-bag-discovery-review"
    assert receipt["scope"] == (scope + "-partial" if attempted < 2 else scope)
    assert receipt["reviewed_pairs"] == len(receipt["pair_reviews"]) == completed
    assert reviewed == ["fixture-cached"] * completed
    assert receipt["summary"]["failed_pairs"] == failed
    assert [row["reason"] for row in receipt["failed_or_uncached_pairs"]] == [
        "reviewed original BAG is not cached"
    ] * failed
    if limit is not None:
        assert not CANONICAL.exists()


def test_negative_limit_is_refused(run_audit):
    # A negative slice would silently omit the tail rather than reject the limit.
    run, reviewed = run_audit
    output = Path("new-directory/diagnostic.json")
    with pytest.raises(SystemExit) as exc:
        run("--limit", "-1", "--output", str(output))
    assert exc.value.code == 2
    assert not output.parent.exists()
    assert not reviewed
