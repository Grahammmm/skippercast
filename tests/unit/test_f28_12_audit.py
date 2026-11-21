"""F28-12 / SCA-569: the San Miguel danger polygon is not bound to the reviewed text.

Offline fixture. The verifier (`verify`) and the VR consumer both accept a
manifest whose interior vertex was edited while the bounds, polygon validity
and reviewed text hash stay fixed. The first test shows the valid control and
the observation; the strict xfail states the wanted outcome (reject until
reviewed) and turns into a failure, to be removed, once the binding exists.
"""
from copy import deepcopy
from datetime import datetime, timezone
import json
from tests._support import ROOT

import pytest

pytest.importorskip("shapely")
pytestmark = pytest.mark.gis

from research.scripts import audit_san_miguel_naval_zone as naval

MANIFEST = ROOT / "research" / "catalog" / "san-miguel-naval-danger-zone.json"
NOW = datetime(2026, 11, 18, tzinfo=timezone.utc)


def _manifest():
    return json.loads(MANIFEST.read_text())


def _edit_interior_vertex(manifest):
    # Vertex 4 (index 3) is interior to the bounding box; nudge it slightly.
    edited = deepcopy(manifest)
    edited["vertices_n_w"][3][0] = "34°02′55″"
    return edited


def _verify(monkeypatch, manifest):
    def fake_source(_client, _spec):
        return {"content_sha256": manifest["reviewed_content_sha256"],
                "normalization": manifest["normalization"],
                "source_url": "https://example.invalid/synthetic-ecfr",
                "up_to_date_as_of": "2026-11-17",
                "title_latest_issue_date": "2026-11-17"}
    monkeypatch.setattr(naval, "Client", lambda now=None: object())
    monkeypatch.setattr(naval, "ecfr_section", fake_source)
    return naval.verify(manifest, now=NOW)


def _consumer_accepts(manifest, receipt):
    # Mirrors the naval gate in audit_san_miguel_vr_habitat.review(): id and
    # text hash against the receipt, then the polygon rebuilt from the manifest.
    if (receipt.get("id") != manifest["id"]
            or receipt.get("source_content_sha256") != manifest["reviewed_content_sha256"]
            or receipt.get("operational_status_checked") is not False):
        return None
    return naval.danger_polygon(manifest)


def test_valid_control_and_unbound_vertex_edit(monkeypatch):
    base = _manifest()
    edited = _edit_interior_vertex(base)
    base_receipt = _verify(monkeypatch, base)
    edited_receipt = _verify(monkeypatch, edited)
    base_polygon = naval.danger_polygon(base)
    edited_polygon = naval.danger_polygon(edited)

    # Valid control passes through verifier and consumer.
    assert _consumer_accepts(base, base_receipt) is not None
    # Affected control: geometry differs, but nothing the receipt records does.
    assert not base_polygon.equals(edited_polygon)
    assert edited_polygon.is_valid
    assert edited_receipt["polygon_bounds_lon_lat"] == base_receipt["polygon_bounds_lon_lat"]
    assert edited_receipt["source_content_sha256"] == base_receipt["source_content_sha256"]


@pytest.mark.xfail(strict=True, reason="F28-12: geometry not bound to reviewed text revision")
def test_changed_geometry_is_rejected_until_reviewed(monkeypatch):
    base = _manifest()
    edited = _edit_interior_vertex(base)
    base_polygon = naval.danger_polygon(base)
    receipt = _verify(monkeypatch, base)  # receipt of the reviewed pair
    with pytest.raises(ValueError):
        naval.verify(edited, now=NOW)  # verifier side (stubs from _verify still active)
    accepted = _consumer_accepts(edited, receipt)
    assert accepted is None or accepted.equals(base_polygon)
