#!/usr/bin/env python3
"""Bounded local sample observations, never survey or mapping acceptance."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import resource
import shutil
import signal
import stat
import subprocess
import sys
import time
import urllib.parse

import discover as d

SCHEMA = "coastal-quality-v1"
METHOD = "format-native-observation-v4"
MAX_FILE = 64_000_000
MAX_PIXELS = 4_000_000
MAX_EXPANDED = 256_000_000
MEMORY_BYTES = 1_073_741_824


def file_hash(path, cap=MAX_FILE, deadline=None):
    p = Path(path)
    if p.is_symlink() or not stat.S_ISREG(p.stat().st_mode) or p.stat().st_size > cap:
        raise ValueError("sample must be a regular local file within byte cap")
    h = hashlib.sha256()
    with p.open("rb") as stream:
        while True:
            if deadline and time.monotonic() >= deadline:
                raise TimeoutError("inspection deadline")
            chunk = stream.read(65536)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def source_digest(c):
    # Quality itself is not included: attachment does not change its own input.
    return d.digest({k: c[k] for k in ("source_id", "publisher_id", "catalog_id", "provenance", "metadata", "extent", "access_url", "alternate_of")})


def base_receipt(c, s, mode, clock=d.now):
    checked = clock()
    return dict(schema=SCHEMA, quality_method=METHOD, mode=mode,
        source_id=c["source_id"], source_metadata_sha256=source_digest(c),
        metadata_response_sha256=c["provenance"]["response_sha256"],
        region=s["region"], assigned_bbox=s["bbox"], source_revision=s["source_revision"],
        policy_revision=s["policy_revision"], discovery_method=s["method_revision"],
        checked_at=d.stamp(checked), expires_at=d.stamp(min(d.timestamp(c["expires_at"]), checked + 86400)),
        sample=None, binding=None, observations={}, blockers=[], unknowns=[], limitations=[
            "One bounded sample/window never certifies a survey or native coverage.",
            "No resampling, terrain mapping, habitat inference or v2 display acceptance performed."],
        status="metadata_only", accepted=False, selected_slice_ids=[],
        usefulness=dict(private_terrain="acquisition_lead", habitat="unassessed", render="blocked"),
        next_action="acquire one explicitly bounded source-linked sample",
        metadata_context=dict(source_date=c["metadata"].get("source_date"),
            acquisition_date=c["metadata"].get("acquisition_date"), age_days=None, age_range_days=None, age_basis=None,
            rights=c["metadata"].get("rights"), rights_accepted=False,
            declared_crs=c["metadata"].get("crs"), vertical_datum=c["metadata"].get("vertical_datum"),
            z_units=c["metadata"].get("z_units"), field_evidence=c.get("field_evidence", {})),
        review=dict(requested_model=None, observed_model=None, requested_effort=None,
                    input_tokens=None, cached_input_tokens=None, output_tokens=None,
                    decision="not_reviewed", scope="bounded sample only"))


def metadata_observations(receipt):
    context = receipt["metadata_context"]
    age_unknown = "acquisition_age: no parseable applicable declared date"
    receipt["unknowns"] = list(dict.fromkeys(label for label in receipt["unknowns"]
                                            if label not in ("acquisition_age", age_unknown)))
    context.update(age_days=None, age_range_days=None, age_basis=None)
    for key in ("source_date", "acquisition_date", "rights", "vertical_datum", "z_units"):
        if context.get(key) in (None, "", "unknown", "Unknown"):
            if key not in receipt["unknowns"]:
                receipt["unknowns"].append(key)
    checked = d.timestamp(receipt["checked_at"])
    acquisition = context.get("acquisition_date")
    def parse_date(value):
        if not isinstance(value, str):
            raise ValueError("declared date must be a string")
        return d.timestamp(value if "T" in value else value + "T00:00:00Z")
    try:
        if isinstance(acquisition, dict):
            start, end = parse_date(acquisition.get("start")), parse_date(acquisition.get("end"))
            if start <= end <= checked:
                context["age_range_days"] = dict(youngest=(checked-end)/86400, oldest=(checked-start)/86400)
                context["age_basis"] = "acquisition_date interval endpoints (declared dates; date-only endpoints use UTC midnight)"
        else:
            missing = acquisition in (None, "", "unknown", "Unknown")
            date, basis = (context.get("source_date"), "source_date") if missing else (acquisition, "acquisition_date")
            parsed = parse_date(date)
            if parsed <= checked:
                context["age_days"] = (checked-parsed)/86400
                context["age_basis"] = basis + " (declared field; source_date is not assumed survey acquisition)"
    except ValueError:
        pass
    if context["age_days"] is None and context["age_range_days"] is None:
        receipt["unknowns"].append(age_unknown)
    return receipt


def verified_binding(c, s, request_id, binding_path=None):
    row = next(r for r in s["requests"] if r["id"] == request_id)
    if row["status"] != "OK" or row["purpose"] != "sample":
        raise ValueError("sample must be a successful bounded sample request in this mission")
    if row["catalog"] != c["catalog_id"]:
        raise ValueError("sample/source catalog mismatch")
    evidence = dict(source_id=c["source_id"], asset_url=row["url"], sample_request_id=request_id,
                    sample_sha256=row["sha256"], source_metadata_sha256=source_digest(c))
    if d.url_key(c["access_url"]) == row["url"]:
        evidence["lineage"] = "exact source access URL"
    else:
        if not binding_path:
            raise ValueError("landing-page sample needs explicit source lineage binding; same host is insufficient")
        binding = d.read(binding_path)
        if any(binding.get(k) != v for k, v in evidence.items()):
            raise ValueError("sample lineage source/request/URL/hash binding mismatch")
        if not binding.get("lineage_confirmed_by") or not binding.get("lineage_reason"):
            raise ValueError("lineage needs operator/reviewer identity and evidence-based reason")
        parent = binding["parent_evidence"]
        if file_hash(parent["path"], d.MAX_METADATA) != parent["sha256"]:
            raise ValueError("parent evidence hash mismatch")
        text = Path(parent["path"]).read_text().replace("\\/", "/")
        links = d.response_links(text, parent["url"])
        if row["url"] not in links:
            catalog = next(cat for cat in s["plan"]["catalogs"] if cat["id"] == c["catalog_id"])
            original = next((link for link in d.raw_response_links(text)
                if d.explicit_https_upgrade(link, row["url"], catalog["allowed_hosts"])
                and any(added.get("original_href") == link
                        and added.get("link_normalization") == "explicit_http_to_https"
                        and added.get("response_sha256") == parent["sha256"]
                        and added["query"]["url"] == row["url"]
                        for added in s["added_queries"])), None)
            if original is None:
                raise ValueError("asset URL is not a link in hash-verified parent evidence")
            evidence["parent_link_normalization"] = dict(original_href=original, method="explicit_http_to_https")
        evidence.update(binding)
        evidence["lineage"] = "explicit confirmed source lineage and saved parent link"
    return row, evidence


def import_sample(path, source, manifest_path, request_id, binding_path=None, clock=d.now):
    s, old=d.read(path),d.read(manifest_path)
    d.active(s,clock)
    old_hash=d.digest(old)
    if not any(r["manifest_sha256"]==old_hash and source in r["source_ids"] for r in s["reuses"]):
        raise ValueError("sample import requires prior scoped source-manifest import")
    current=next(c for c in s["candidates"] if c["source_id"]==source)
    prior=next(c for c in old["candidates"] if c["source_id"]==source)
    d.validate_candidate(prior,old)
    if source_digest(current)!=source_digest(prior) or d.timestamp(prior["expires_at"])<=clock():
        raise ValueError("sample import source evidence changed or expired")
    row,binding=verified_binding(prior,old,request_id,binding_path)
    if file_hash(row["body_path"])!=row["sha256"] or Path(row["body_path"]).stat().st_size!=row["observed_body_bytes"]:
        raise ValueError("imported sample bytes/hash mismatch")
    imports=s.setdefault("sample_imports",[])
    for item in imports:
        if item["source_id"]==source and item["row"]["sha256"]==row["sha256"]:
            return item
    if len(imports)>=4:
        raise ValueError("sample import ceiling")
    item=dict(id=len(imports)+1,source_id=source,row=row,binding=binding,manifest_sha256=old_hash,
              imported_at=d.stamp(clock()),transfer_bytes=0,original_request_id=request_id)
    imports.append(item)
    d.atomic(path,s)
    return item


def unsupported_reason(asset_url, magic):
    name = Path(urllib.parse.urlsplit(asset_url).path).name.lower()
    suffix = Path(name).suffix
    if name.endswith((".gsf.gz", ".mb121.gz", ".gsf.mb121.gz")):
        return "compressed GSF/MB121: bounded decompression and validated MB-System reader are unsupported in this inspector; no extraction or decoding attempted"
    if suffix in (".gsf", ".mb121") or b"GSF" in magic:
        return "GSF/MB121: validated MB-System mbinfo/mblist reader unavailable; no native decoding attempted"
    if suffix == ".bag":
        return "BAG/HDF5: no tested bounded BAG reader in this inspector"
    if suffix in (".nc", ".grd") or magic[:3] == b"CDF":
        return "netCDF/native grid: no tested bounded reader in this inspector"
    if magic.startswith((b"PK", b"\x1f\x8b", b"BZh", b"7z", b"\xfd7z")):
        return "archive/compressed container: bounded extraction reader not implemented; no extraction attempted"
    return "unsupported format: only self-contained local GeoTIFF is enabled; VRT/remote references are rejected"


def inspect_native(receipt, path, limits, deadline):
    """Read one native band/window. No warp, resampling, native exports or network."""
    metadata_observations(receipt)
    receipt["limits"] = limits
    p = Path(path)
    try:
        sha = file_hash(p, limits["file_bytes"], deadline)
        if sha != receipt["sample"]["sha256"]:
            raise ValueError("sample hash mismatch")
        with p.open("rb") as stream:
            magic = stream.read(16)
        if magic[:4] not in (b"II*\x00", b"MM\x00*", b"II+\x00", b"MM\x00+"):
            receipt["blockers"].append(unsupported_reason(receipt["sample"]["url"], magic))
            receipt["status"] = "reader_blocked"
            receipt["usefulness"]["private_terrain"] = "reader_blocked"
            receipt["next_action"] = "obtain a tested bounded native reader or source-linked GeoTIFF; do not infer sample quality"
            return receipt
        import numpy as np
        os.environ["PROJ_NETWORK"] = "OFF"
        import rasterio
        from rasterio.windows import Window, from_bounds, bounds as window_bounds
        from rasterio.warp import transform_bounds
        from pyproj import CRS, network
        network.set_network_enabled(False)
        with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", GDAL_PAM_ENABLED="NO",
                          GDAL_CACHEMAX=16_000_000, GDAL_NUM_THREADS="1",
                          GTIFF_NUM_THREADS="1", CPL_VSIL_CURL_ALLOWED_EXTENSIONS="", PROJ_NETWORK="OFF"):
            with rasterio.open(p, driver="GTiff", sharing=False) as src:
                if src.driver != "GTiff" or src.subdatasets or any(Path(f).resolve() != p.resolve() for f in src.files):
                    raise ValueError("only one self-contained local GeoTIFF is allowed; no sidecars/subdatasets")
                expanded = src.width * src.height * sum(np.dtype(dtype).itemsize for dtype in src.dtypes)
                if expanded > limits["expanded_bytes"] or src.count > 4:
                    raise ValueError("declared decompressed raster exceeds byte/band ceiling")
                block_bytes = max(h * w * np.dtype(dtype).itemsize for (h, w), dtype in zip(src.block_shapes, src.dtypes))
                if block_bytes > limits["expanded_bytes"]:
                    raise ValueError("native block exceeds decompression ceiling")
                if src.crs is None:
                    raise ValueError("native raster CRS missing")
                if np.issubdtype(np.dtype(src.dtypes[0]), np.complexfloating):
                    raise ValueError("complex-valued native bands are unsupported for these observations")
                crs = CRS.from_user_input(src.crs)
                if not crs.is_geographic and not crs.is_projected:
                    raise ValueError("unsupported native CRS type")
                transform = src.transform
                if transform.b or transform.d or transform.a <= 0 or transform.e >= 0:
                    raise ValueError("rotated or non-north-up raster needs a separately tested reader")
                resolution = [abs(transform.a), abs(transform.e)]
                if not all(math.isfinite(x) and x > 0 for x in resolution):
                    raise ValueError("invalid native resolution")
                native_bounds = list(src.bounds)
                extent = list(transform_bounds(src.crs, "EPSG:4326", *src.bounds, densify_pts=21))
                d.bbox(extent)
                receipt["observations"]["header"] = dict(driver=src.driver, width=src.width, height=src.height,
                    band_count=src.count, inspected_band=1, dtype=src.dtypes[0],
                    crs=crs.to_string(), horizontal_units=[axis.unit_name for axis in crs.axis_info[:2]],
                    resolution=resolution, resolution_units="degrees" if crs.is_geographic else crs.axis_info[0].unit_name,
                    native_bounds=native_bounds, bbox_crs84=extent, nodata=str(src.nodata) if src.nodata is not None else None,
                    band_units=src.units[0], scale=src.scales[0], offset=src.offsets[0],
                    declared_expanded_bytes=expanded, native_block_bytes=block_bytes,
                    vertical_datum="not established from raster header", valid_support="unmeasured beyond selected window")
                if crs.is_geographic:
                    receipt["unknowns"].append("metric_resolution: native angular grid; no metre conversion performed")
                if src.units[0] is None:
                    receipt["unknowns"].append("native_band_units")
                declared = receipt["metadata_context"]["declared_crs"]
                if declared and d.known_crs(declared) and not CRS.from_user_input("OGC:CRS84" if declared == "CRS84" else declared).equals(crs, ignore_axis_order=True):
                    receipt["blockers"].append("native CRS differs from source metadata; reconcile exact sample lineage/metadata")
                if not d.overlaps(extent, receipt["assigned_bbox"]):
                    receipt["blockers"].append("native sample does not overlap assigned bbox")
                    receipt["status"] = "sample_blocked"
                    receipt["usefulness"]["private_terrain"] = "nonoverlap"
                    receipt["next_action"] = "choose a source-linked sample overlapping the assigned region"
                    return receipt
                target = transform_bounds("EPSG:4326", src.crs, *receipt["assigned_bbox"], densify_pts=21)
                intersect = [max(target[0], src.bounds.left), max(target[1], src.bounds.bottom), min(target[2], src.bounds.right), min(target[3], src.bounds.top)]
                if intersect[0] >= intersect[2] or intersect[1] >= intersect[3]:
                    raise ValueError("native projected bbox intersection empty")
                wanted = from_bounds(*intersect, transform=transform)
                col = max(0, int(math.floor(wanted.col_off)))
                row = max(0, int(math.floor(wanted.row_off)))
                width = min(src.width - col, max(1, int(math.ceil(wanted.width))))
                height = min(src.height - row, max(1, int(math.ceil(wanted.height))))
                wanted_pixels = width * height
                # Select a centered smaller native window, never downsample.
                if wanted_pixels > limits["pixels"]:
                    side = max(1, int(math.sqrt(limits["pixels"])))
                    new_width, new_height = min(width, side), min(height, max(1, limits["pixels"] // min(width, side)))
                    col += (width - new_width) // 2
                    row += (height - new_height) // 2
                    width, height = new_width, new_height
                    receipt["limitations"].append("pixel ceiling selected a smaller centered native window; remaining overlap unexamined")
                win = Window(col, row, width, height)
                if time.monotonic() >= deadline:
                    raise TimeoutError("inspection deadline before pixel read")
                values = src.read(1, window=win)
                mask = src.read_masks(1, window=win) != 0
                finite = np.isfinite(values)
                nodata_values = (np.isnan(values) if src.nodata is not None and math.isnan(src.nodata)
                                 else values == src.nodata if src.nodata is not None
                                 else np.zeros(values.shape, dtype=bool))
                # An explicit GDAL/internal mask can override the nodata mask;
                # honor both rather than treating finite nodata as measurements.
                valid = mask & finite & ~nodata_values
                valid_count = int(np.count_nonzero(valid))
                stats = dict(count=int(values.size), mask_valid_count=int(np.count_nonzero(mask)),
                    finite_count=int(np.count_nonzero(finite)), valid_count=valid_count,
                    nodata_count=int(np.count_nonzero(nodata_values)),
                    nodata_or_masked_count=int(np.count_nonzero(~mask | nodata_values)),
                    nonfinite_count=int(np.count_nonzero(~finite)), valid_fraction=valid_count / values.size,
                    minimum=None, maximum=None, median=None, robust_outlier_fraction=None,
                    median_adjacent_step=None, value_space="raw stored band values; scale/offset not applied",
                    outlier_rule="absolute deviation >10*MAD; if MAD=0 use >max(1 native value unit,1% of |median|)")
                if valid_count:
                    selected = values[valid].astype("float64")
                    med = float(np.median(selected))
                    mad = float(np.median(np.abs(selected - med)))
                    threshold = 10 * mad if mad > 0 else max(1.0, abs(med) * 0.01)
                    outliers = float(np.count_nonzero(np.abs(selected - med) > threshold) / valid_count)
                    adjacent = valid[:, 1:] & valid[:, :-1]
                    differences = np.abs(values[:, 1:].astype("float64") - values[:, :-1].astype("float64"))[adjacent]
                    stats.update(minimum=float(np.min(selected)), maximum=float(np.max(selected)), median=med,
                                 robust_outlier_fraction=outliers, median_adjacent_step=float(np.median(differences)) if differences.size else None)
                    if outliers:
                        receipt["limitations"].append("robust value outliers observed; may be terrain, encoding or artifact, not a noise diagnosis")
                receipt["observations"].update(window=dict(col_off=col, row_off=row, width=width, height=height,
                    bbox_native=list(window_bounds(win, transform)), crs=crs.to_string(),
                    requested_overlap_pixels=wanted_pixels, native_pixels_read=int(values.size),
                    selection="native integer window without resampling", support_claim="valid fraction only inside selected window"), values=stats)
                if not valid_count:
                    receipt["blockers"].append("selected native window has no finite unmasked values")
                receipt["status"] = "sample_blocked" if receipt["blockers"] else "sample_observed"
                receipt["usefulness"]["private_terrain"] = "held_for_sample_issue" if receipt["blockers"] else "bounded_window_candidate_for_qualification"
                receipt["next_action"] = "resolve recorded native sample blockers" if receipt["blockers"] else "independently review this window and missing units/datum/rights before native qualification"
                if time.monotonic() >= deadline:
                    raise TimeoutError("inspection deadline after pixel read")
    except (ValueError, OSError, RuntimeError, TimeoutError) as exc:
        receipt["status"] = "sample_blocked"
        receipt["blockers"].append(str(exc)[:500])
        receipt["usefulness"]["private_terrain"] = "inspection_blocked"
        receipt["next_action"] = "resolve the exact local inspection blocker without inferring sample quality"
    return receipt


def validate_receipt(receipt):
    from jsonschema import Draft202012Validator
    schema = d.read(Path(__file__).resolve().parent.parent / "references/quality-receipt-v1.schema.json")
    errors = list(Draft202012Validator(schema).iter_errors(receipt))
    if errors:
        raise ValueError("invalid quality receipt: " + errors[0].message)
    if receipt["sample"]:
        sample, binding = receipt["sample"], receipt["binding"]
        for key, expected in dict(source_id=receipt["source_id"], source_metadata_sha256=receipt["source_metadata_sha256"],
                                 asset_url=sample["url"], sample_sha256=sample["sha256"], sample_request_id=sample["request_id"]).items():
            if binding.get(key) != expected:
                raise ValueError("quality sample/source binding identity mismatch")


def validate_attachment(c, state, clock=d.now):
    attachment = c["quality"]
    receipt = d.read(attachment["path"])
    if file_hash(attachment["path"], d.MAX_METADATA) != attachment["sha256"]:
        raise ValueError("quality receipt hash changed")
    validate_receipt(receipt)
    if receipt["quality_method"] != METHOD or receipt["source_id"] != c["source_id"] or receipt["source_metadata_sha256"] != source_digest(c):
        raise ValueError("quality source/method/metadata identity invalidated")
    for rk, sk in (("source_revision", "source_revision"), ("policy_revision", "policy_revision"), ("discovery_method", "method_revision"), ("region", "region"), ("assigned_bbox", "bbox")):
        if receipt[rk] != state[sk]:
            raise ValueError("quality policy/source/region invalidated")
    if not d.timestamp(receipt["checked_at"]) <= clock() < d.timestamp(receipt["expires_at"]) <= min(d.timestamp(c["expires_at"]), d.timestamp(receipt["checked_at"]) + 86400):
        raise ValueError("quality expired or time invalid")
    if receipt["sample"] and file_hash(receipt["sample"]["path"]) != receipt["sample"]["sha256"]:
        raise ValueError("quality sample hash changed")
    if receipt.get("reader"):
        reader=receipt["reader"]["reader"]
        if file_hash(reader["executable"])!=reader["sha256"] or file_hash(Path(__file__).with_name("gsf_probe.c"))!=reader["adapter_sha256"]:
            raise ValueError("quality pinned reader identity changed")
    if attachment["status"] != receipt["status"]:
        raise ValueError("quality status changed")
    return receipt


def assess(path, source, request_id=None, binding=None, seconds=45, max_pixels=1_000_000, max_file=MAX_FILE, clock=d.now, imported_sample=None, reader_receipt=None):
    s = d.read(path)
    remaining = d.active(s, clock)
    if not (0 < seconds <= 60 and 0 < max_pixels <= MAX_PIXELS and 0 < max_file <= MAX_FILE):
        raise ValueError("inspection limits outside fixed ceilings")
    c = next(c for c in s["candidates"] if c["source_id"] == source)
    d.validate_candidate(c, s)
    if d.timestamp(c["expires_at"]) <= clock():
        raise ValueError("source evidence expired")
    if request_id is not None and imported_sample is not None:
        raise ValueError("choose new request or imported sample, not both")
    receipt = metadata_observations(base_receipt(c, s, "native_sample" if request_id is not None or imported_sample is not None else "metadata", clock))
    row = None
    if request_id is not None or imported_sample is not None:
        if imported_sample is not None:
            item=next(item for item in s.get("sample_imports",[]) if item["id"]==imported_sample and item["source_id"]==source)
            row,evidence=item["row"],item["binding"]
            if evidence["source_metadata_sha256"]!=source_digest(c) or file_hash(row["body_path"])!=row["sha256"]:
                raise ValueError("imported sample binding/hash invalidated")
            request_id=row["id"]
            receipt["sample_import"]=dict(id=imported_sample,manifest_sha256=item["manifest_sha256"],transfer_bytes=0)
        else:
            row, evidence = verified_binding(c, s, request_id, binding)
        receipt["binding"] = evidence
        receipt["sample"] = dict(path=row["body_path"], sha256=row["sha256"], bytes=row["observed_body_bytes"], url=row["url"], request_id=request_id)
    reader_identity = None
    if reader_receipt:
        from formats import preflight
        reader = preflight(reader_receipt)["reader"]
        reader_identity = {key: reader[key] for key in ("sha256", "adapter_sha256", "source_revision", "gsf_version")}
    fingerprint = d.digest(dict(source_metadata=source_digest(c),
        sample_sha256=receipt["sample"]["sha256"] if receipt["sample"] else None,
        method=METHOD, reader_identity=reader_identity,bbox=s["bbox"]))
    runs = s.setdefault("quality_runs", [])
    if len(runs) >= 8 or any(r["fingerprint"] == fingerprint for r in runs):
        raise ValueError("quality attempt ceiling or unchanged inspection; reuse existing receipt")
    directory = Path(path).parent / (Path(path).stem + "-quality")
    directory.mkdir(exist_ok=True)
    out = directory / f"{len(runs)+1:03}.json"
    seconds = min(seconds, remaining, d.timestamp(s["discovery_cutoff_utc"]) - clock())
    if seconds <= 0:
        raise ValueError("discovery cutoff reached during quality preflight")
    intent = dict(source_id=source, fingerprint=fingerprint, status="RUNNING", start_utc=d.stamp(clock()), seconds=seconds, path=str(out.resolve()))
    runs.append(intent)
    d.atomic(path, s)
    process = None
    scratch=directory / f"{len(runs):03}-scratch"
    scratch.mkdir(exist_ok=False)
    began = time.monotonic()
    try:
        if row:
            context = directory / f"{len(runs):03}-input.json"
            payload = dict(receipt=receipt, limits=dict(file_bytes=max_file, pixels=max_pixels,
                expanded_bytes=MAX_EXPANDED, address_space_bytes=MEMORY_BYTES),
                deadline_epoch=time.time() + seconds, timeout_seconds=seconds,
                reader_receipt=str(Path(reader_receipt).resolve()) if reader_receipt else None,scratch=str(scratch.resolve()))
            d.atomic(context, payload)
            env = dict(os.environ, OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1", GDAL_NUM_THREADS="1", PROJ_NETWORK="OFF")
            process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "_inspect", str(context), str(out)], start_new_session=True, env=env)
            intent["pid"] = process.pid
            d.atomic(path, s)
            process.wait(timeout=seconds)
            if not out.exists():
                raise ValueError(f"bounded reader exited {process.returncode} without receipt")
            receipt = d.read(out)
        else:
            d.atomic(out, receipt)
        validate_receipt(receipt)
        intent["status"] = "COMPLETED"
    except (ValueError, OSError, subprocess.TimeoutExpired, KeyboardInterrupt, InterruptedError) as exc:
        intent["status"] = "STOPPED"
        receipt["status"] = "sample_blocked" if row else "metadata_only"
        receipt["blockers"].append(str(exc)[:500] or "inspection interrupted")
        receipt["usefulness"]["private_terrain"] = "inspection_blocked"
        receipt["next_action"] = "inspect the saved bounded failure; no unchanged retry"
    finally:
        if process is not None:
            # A worker alarm may fire while its upstream reader still runs.
            # Reap the whole owned group, even after the worker exited.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
        shutil.rmtree(scratch)
        intent.update(elapsed_seconds=time.monotonic() - began, stop_utc=d.stamp(clock()))
        receipt["elapsed_seconds"] = intent["elapsed_seconds"]
        d.atomic(out, receipt)
        c["quality"] = dict(path=str(out.resolve()), sha256=file_hash(out, d.MAX_METADATA), status=receipt["status"], source_metadata_sha256=source_digest(c))
        d.atomic(path, s)
    return receipt


def main():
    if len(sys.argv)>1 and sys.argv[1]=="preflight":
        from formats import preflight
        parser=argparse.ArgumentParser()
        parser.add_argument("preflight")
        parser.add_argument("--reader-receipt")
        args=parser.parse_args()
        print(json.dumps(preflight(args.reader_receipt),indent=2))
        return
    if len(sys.argv) > 1 and sys.argv[1] == "_inspect":
        payload = d.read(sys.argv[2])
        seconds = min(payload["timeout_seconds"], payload["deadline_epoch"] - time.time())
        if seconds <= 0:
            raise ValueError("child inspection deadline expired")
        # Hard child stop remains effective inside native GDAL calls and after
        # loss of the parent. Parent additionally owns a monotonic timeout.
        signal.signal(signal.SIGALRM, signal.SIG_DFL)
        signal.setitimer(signal.ITIMER_REAL, seconds)
        resource.setrlimit(resource.RLIMIT_AS, (MEMORY_BYTES, MEMORY_BYTES))
        resource.setrlimit(resource.RLIMIT_FSIZE, (128_000_000, 128_000_000))
        resource.setrlimit(resource.RLIMIT_NOFILE, (48, 48))
        receipt = payload["receipt"]
        name=Path(urllib.parse.urlsplit(receipt["sample"]["url"]).path).name.lower()
        if payload.get("reader_receipt") and (".gsf" in name or ".mb121" in name):
            from formats import inspect_gsf
            result=inspect_gsf(receipt,receipt["sample"]["path"],payload["reader_receipt"],payload["scratch"],time.monotonic()+seconds,payload["limits"]["file_bytes"])
        else:
            result = inspect_native(receipt, receipt["sample"]["path"], payload["limits"], time.monotonic() + seconds)
        if len((json.dumps(result, indent=2, sort_keys=True) + "\n").encode()) > d.MAX_METADATA:
            raise ValueError("quality receipt exceeds metadata output cap")
        d.atomic(sys.argv[3], result)
        return
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("checkpoint", type=Path)
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("inspect", "metadata"):
        p = sub.add_parser(command)
        p.add_argument("--source", required=True)
        p.add_argument("--seconds", type=float, default=45)
        p.add_argument("--max-pixels", type=int, default=1_000_000)
        p.add_argument("--max-file-bytes", type=int, default=MAX_FILE)
        if command == "inspect":
            samples=p.add_mutually_exclusive_group(required=True)
            samples.add_argument("--sample-request", type=int)
            samples.add_argument("--imported-sample", type=int)
            p.add_argument("--binding")
            p.add_argument("--reader-receipt")
    p=sub.add_parser("import-sample")
    p.add_argument("--source",required=True)
    p.add_argument("--manifest",required=True)
    p.add_argument("--request",type=int,required=True)
    p.add_argument("--binding")
    p = sub.add_parser("validate")
    p.add_argument("--source", required=True)
    args = parser.parse_args()
    def interrupted(*_):
        raise InterruptedError("inspection terminated")
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGHUP, interrupted)
    with d.locked(args.checkpoint):
        if args.command == "import-sample":
            result=import_sample(args.checkpoint,args.source,args.manifest,args.request,args.binding)
        elif args.command == "validate":
            s = d.read(args.checkpoint)
            c = next(c for c in s["candidates"] if c["source_id"] == args.source)
            result = validate_attachment(c, s)
        else:
            result = assess(args.checkpoint, args.source, getattr(args, "sample_request", None), getattr(args, "binding", None), args.seconds, args.max_pixels, args.max_file_bytes,
                            imported_sample=getattr(args,"imported_sample",None),reader_receipt=getattr(args,"reader_receipt",None))
        print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, OSError, StopIteration) as exc:
        print(f"STOP: {exc}", file=sys.stderr)
        sys.exit(2)
