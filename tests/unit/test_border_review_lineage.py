"""Replay saved synthetic border-gap reports at the offline lineage CLI."""

import json
import subprocess
import sys

import pytest

from tests._support import ROOT

_CLI = ROOT / "scripts/relief/border_review_lineage.py"
_POLYGONS = {
    "water": b'{"type":"Polygon","coordinates":[[[0,0],[4,0],[4,4],[0,4],[0,0]]]}\n',
    "support": b'{"type":"Polygon","coordinates":[[[1,1],[2,1],[2,2],[1,2],[1,1]]]}\n',
    "window": b'{"type":"Polygon","coordinates":[[[0,0],[3,0],[3,3],[0,3],[0,0]]]}\n',
    "boundary": b'{"type":"Polygon","coordinates":[[[0,0],[4,1],[4,4],[0,4],[0,0]]]}\n',
}
# Captured with border_depth_gap.py on the exact synthetic bytes above. No GIS
# imports are needed in the reader tests, and their expected digests are frozen.
_REPORT = {
    "us_water_m2": 96391237738.23795,
    "support_m2": 12304586796.447853,
    "remainder_m2": 84086650941.7901,
    "sha256": {
        "water": "1efd9c717d25fc5db119fd96ac978446b41b53e806ea21164ce1692cb6f0d71a",
        "support": "375cb4ef111a63111a9688d41aa781402384eba325d568ad5f3f7898b2ce4b58",
        "window": "17abf7b0fdfbb20214d61ca35db7651acc62aafd2c22ae346a1e2ca4e4108bca",
        "boundary": "5e5a4d71baecc266b7a9c5bfa194498f23ef0cc7dc3b35bace7ab26c4c9161cb",
    },
}
_MATCHES = dict.fromkeys(_POLYGONS, "match")


@pytest.fixture
def saved_gap(tmp_path):
    fixtures = tmp_path / "fixtures"
    fixtures.mkdir()
    for role, data in _POLYGONS.items():
        (fixtures / f"{role}.json").write_bytes(data)
    report = tmp_path / "gap.json"
    report.write_text(json.dumps(_REPORT), encoding="utf-8")
    return report, fixtures


def _run(saved_gap):
    report, fixtures = saved_gap
    return subprocess.run(
        [sys.executable, str(_CLI), "--report", str(report), "--fixture-dir", str(fixtures)],
        cwd=report.parent, capture_output=True, text=True, timeout=10,
    )


def _expect(saved_gap, exit_code, **changes):
    result = _run(saved_gap)
    assert result.returncode == exit_code, result.stderr
    assert json.loads(result.stdout) == {"inputs": _MATCHES | changes, "approval": "not_assessed"}


def test_unchanged_bytes_match_without_implying_approval(saved_gap):
    """All four dispositions must match, but a green comparison must not approve anything."""
    _expect(saved_gap, 0)


def test_stale_boundary_digest_rejects_a_valid_revised_polygon(saved_gap):
    """A geometry-only check would accept the revised oblique polygon with the original report."""
    # This changed polygon was also accepted by the actual border gap producer.
    (saved_gap[1] / "boundary.json").write_bytes(_POLYGONS["boundary"].replace(b"[4,1]", b"[4,2]"))
    _expect(saved_gap, 1, boundary="mismatch")


@pytest.mark.parametrize("role", tuple(_POLYGONS))
def test_roles_bind_raw_bytes_not_reserialized_geometry(saved_gap, role):
    """Per-role whitespace edits remain valid JSON; canonical hashing or ignoring a role would pass."""
    (saved_gap[1] / f"{role}.json").write_bytes(_POLYGONS[role] + b"\n")
    _expect(saved_gap, 1, **{role: "mismatch"})


@pytest.mark.parametrize("present", [False, True], ids=["unknown", "unrecorded"])
def test_null_support_pin_cannot_verify_supplied_support(saved_gap, present):
    """Only genuinely absent support is unknown; a late-supplied file cannot inherit a match."""
    report, fixtures = saved_gap
    omitted = _REPORT | {
        "sha256": _REPORT["sha256"] | {"support": None},
        "support_m2": None,
        "remainder_m2": None,
    }
    report.write_text(json.dumps(omitted), encoding="utf-8")
    if not present:
        (fixtures / "support.json").unlink()
    _expect(saved_gap, 1 if present else 0, support="unrecorded" if present else "unknown")


def test_missing_pinned_files_do_not_disappear_or_become_unknown(saved_gap):
    """A disappeared required file and a disappeared recorded support file must both fail."""
    for role in ("support", "window"):
        (saved_gap[1] / f"{role}.json").unlink()
    _expect(saved_gap, 1, support="missing", window="missing")


def test_role_file_cannot_redirect_outside_fixture_directory(saved_gap):
    """Following a symlink to matching bytes elsewhere would certify the wrong directory."""
    report, fixtures = saved_gap
    decoy = report.parent / "boundary.json"
    decoy.write_bytes(_POLYGONS["boundary"])
    boundary = fixtures / "boundary.json"
    boundary.unlink()
    boundary.symlink_to(decoy)
    _expect(saved_gap, 1, boundary="unreadable")


@pytest.mark.parametrize("kind", ["omitted", "duplicate"])
def test_rejects_ambiguous_role_inventory(saved_gap, kind):
    """Omitting support is not a null pin, and duplicate keys must not be silently overwritten."""
    report, _ = saved_gap
    if kind == "omitted":
        digests = {role: digest for role, digest in _REPORT["sha256"].items() if role != "support"}
        text = json.dumps(_REPORT | {"sha256": digests})
    else:
        text = report.read_text(encoding="utf-8").replace('"boundary":', '"boundary": null, "boundary":')
    report.write_text(text, encoding="utf-8")
    result = _run(saved_gap)
    assert result.returncode == 2
    assert not result.stdout
    assert ("exactly" if kind == "omitted" else "duplicate JSON member") in result.stderr


def test_null_required_pin_is_invalid_even_with_matching_fixture_set(saved_gap):
    """The support exception must not let a missing boundary digest act as a wildcard."""
    report, _ = saved_gap
    doc = _REPORT | {"sha256": _REPORT["sha256"] | {"boundary": None}}
    report.write_text(json.dumps(doc), encoding="utf-8")
    _expect(saved_gap, 1, boundary="invalid_digest")
