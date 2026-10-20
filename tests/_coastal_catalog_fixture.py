"""Frozen-catalog fixtures for the catalog -> acquire bridge tests (SC-3).

`frozen_catalog` builds the `coastal-frozen-discovery-catalog-v1` shape that
`skippercast.coastal.live_discovery.frozen_catalog` (#734) writes: candidate
rows keep the bounded discovery script's fields, and `catalog_id` is the
canonical SHA-256 of every other field. Synthetic values only; no network.
"""
import hashlib
import json
from pathlib import Path

from skippercast.coastal.coordinator import catalog_bridge as bridge
from skippercast.coastal.coordinator.stages import digest

HOST = "data.ngdc.noaa.gov"
BASE = f"https://{HOST}/platforms/ocean/nos/coast/H10001-H12000/H11952/BAG/"
SEGMENT_BBOX = [-120.62, 34.44, -120.56, 34.50]
FAR_FUTURE = "2099-01-01T00:00:00.870400Z"   # the discovery script's stamp() keeps microseconds
BUDGET = {"wall_s": 120, "memory_bytes": 4 * 1024**3, "bytes": 1_000_000, "requests": 0}


def candidate(name, *, url=None, bbox=None, size=None, source_hash=None, usable=True, expires=FAR_FUTURE):
    return dict(
        source_id=f"ncei:{name}", publisher_id=name, title=name, catalog_id="ncei",
        provenance=dict(catalog_url=BASE, response_sha256="0" * 64, request_id=1),
        metadata=dict(crs="EPSG:4326", resolution=None, vertical_datum=None, z_units=None, rights=None,
                      size_bytes=size, source_hash=source_hash),
        extent=dict(bbox=bbox or [-120.6, 34.45, -120.5, 34.55], bbox_crs="CRS84", catalog_geometry=None,
                    overlap_test="bbox_only", actual_data_support=None, actual_support_status="unverified"),
        access_url=url if url is not None else BASE + name,
        unknowns=[], rejection_reasons=[] if usable else ["no_bbox_overlap"], alternate_of=None,
        terrain=dict(status="candidate_for_qualification" if usable else "blocked", blockers=[], accepted=False),
        habitat=dict(status="unassessed", accepted=False, blockers=[]),
        render=dict(status="blocked", accepted=False, blockers=[]),
        next_action="inspect one bounded native terrain window", expires_at=expires, field_evidence={})


def frozen_catalog(rows, **changes):
    body = dict(schema=bridge.CATALOG, region="synthetic-region", bbox=[-120.65, 34.44, -120.46, 34.56],
                source_revision="synthetic-source-1", policy_revision="synthetic-policy-1",
                method_revision="synthetic-method-1", plan_sha256="1" * 64, manifest_sha256="2" * 64,
                checked_from="2026-10-20T00:00:00Z", checked_until="2026-10-20T00:05:00Z",
                manifest_status="PARTIAL", bounded_plan_finished=True, discovery_complete=True,
                unattempted_queries=[], lead_source_ids=[r["source_id"] for r in rows if not r["rejection_reasons"]],
                usable_source_ids=[r["source_id"] for r in rows
                                   if r["terrain"]["status"] == "candidate_for_qualification"],
                candidates=sorted(rows, key=lambda r: r["source_id"]), mapping_accepted=False,
                execution_authorized=False, review_required=True,
                coordinator_boundary="Metadata catalog only.")
    body.update(changes)
    body["catalog_id"] = digest({k: v for k, v in body.items() if k != "catalog_id"})
    return body


def write_catalog(path, catalog):
    raw = (json.dumps(catalog, sort_keys=True, indent=2) + "\n").encode()
    Path(path).write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def cache_file(root, relative, data=b"\x89HDF\r\n\x1a\nsynthetic"):
    path = Path(root) / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return dict(path=relative, sha256=hashlib.sha256(data).hexdigest(), bytes=len(data),
                contract="native-raster-v1")


def plan(catalog, catalog_sha, selections, *, bbox=None, segment_id="seg:3310:0:0:5000", **changes):
    value = dict(schema=bridge.PLAN, catalog_id=catalog["catalog_id"], catalog_sha256=catalog_sha,
                 segment=dict(segment_id=segment_id, bbox_crs84=bbox or SEGMENT_BBOX),
                 synthetic=True, max_total_bytes=10_000_000, budget=dict(BUDGET), selections=selections)
    value.update(changes)
    return value


def selection(source_id, source, window=None, **extra):
    return dict(source_id=source_id, source=source, window=window or [0, 0, 4, 4], vertical=None,
                rights=dict(private_use=True, evidence=[]), **extra)


def window_set(source_id, source, windows, grid=None, **extra):
    """A G5 window-set selection: a deterministic tiling of one source into multiple windows."""
    value = dict(source_id=source_id, source=source, windows=windows, vertical=None,
                 rights=dict(private_use=True, evidence=[]))
    if grid is not None:
        value["grid"] = grid
    value.update(extra)
    return value
