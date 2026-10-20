"""Source-free bridge from a frozen discovery catalog to the coordinator's acquire stage.

Governed live discovery (`skippercast.coastal.live_discovery`, #734) freezes a
`coastal-frozen-discovery-catalog-v1`. Until now nothing read it. This bridge
turns an owner-reviewed selection from that catalog into the acquire stage's
existing input contract, `coastal-native-job-v1`, and nothing more:

- it reads only JSON metadata: the catalog and the owner's bridge plan. A
  cached native source is checked with `lstat` (regular file, no symlink
  component, size) and never opened, hashed or downloaded. The acquire stage
  verifies the bytes against the ref when it runs;
- it makes no network request and imports no fetcher. Every selected
  candidate's `access_url` must be HTTPS on a host that is an exact member of
  the reviewed source allowlist (`skippercast.http.default_allowlist`). A
  suffix wildcard never admits a host and the bridge never adds one;
- caps are fixed before any write: at most `MAX_JOBS` acquire jobs, at most
  `MAX_TOTAL_BYTES` of cached source across them, zero requests per job;
- the catalog must still say `review_required=true` and authorize nothing.
  A bridged job is evidence for the existing coordinator gates, not scientific
  acceptance: qualification, mapping and rendering keep their own holds.

`dry-run` writes one receipt and no job. `run` writes the native-job manifests
inside the coordinator queue root plus a receipt; `enqueue` puts them on an
open `Store` as acquire jobs through the ordinary `Store.enqueue`.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import urllib.parse

from .stages import digest, verify_ref

CATALOG = "coastal-frozen-discovery-catalog-v1"
PLAN = "coastal-catalog-acquire-bridge-plan-v1"
RECEIPT = "coastal-catalog-acquire-bridge-receipt-v1"
DRY_RUN = "coastal-catalog-acquire-bridge-dry-run-v1"
NATIVE_JOB = "coastal-native-job-v1"
MAX_JOBS = 4
MAX_TOTAL_BYTES = 2 * 1024**3          # the acquire stage's default per-job byte ceiling
MAX_WALL_S = 3600
MAX_DOCUMENT_BYTES = 4 * 1024 * 1024    # catalog / plan metadata read bound
MAX_WINDOW_CELLS = 1048576              # same bound as the Store's acquire dispatch gate
NATIVE_SUFFIXES = (".bag", ".tif", ".tiff", ".nc")
GEOGRAPHIC = ("CRS84", "EPSG:4326")
HEX64 = re.compile("[0-9a-f]{64}")


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _encode(value):
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()


def _read(path, label):
    path = Path(path)
    info = os.lstat(path)
    if not stat.S_ISREG(info.st_mode):
        raise ValueError(f"{label} must be a regular file")
    if info.st_size > MAX_DOCUMENT_BYTES:
        raise ValueError(f"{label} exceeds the metadata read bound")
    raw = path.read_bytes()
    return json.loads(raw), raw


def _stamp(value):
    """UTC `...Z` timestamp as the discovery script writes it (fractional seconds allowed)."""
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError("UTC timestamp required")
    moment = datetime.fromisoformat(value[:-1] + "+00:00")
    if moment.utcoffset() != timezone.utc.utcoffset(None):
        raise ValueError("UTC timestamp required")
    return moment.timestamp()


def check_catalog(catalog):
    """A frozen catalog is accepted only intact and only as review-required metadata."""
    if not isinstance(catalog, dict) or catalog.get("schema") != CATALOG:
        raise ValueError("frozen discovery catalog required")
    body = {k: v for k, v in catalog.items() if k != "catalog_id"}
    if catalog.get("catalog_id") != digest(body):
        raise ValueError("catalog_id does not match catalog content")
    if (catalog.get("review_required") is not True or catalog.get("mapping_accepted") is not False
            or catalog.get("execution_authorized") is not False):
        raise ValueError("catalog must be review-required metadata that authorizes nothing")
    rows = catalog.get("candidates")
    if not isinstance(rows, list) or not isinstance(catalog.get("usable_source_ids"), list):
        raise ValueError("catalog candidates and usable_source_ids required")
    ids = [row.get("source_id") for row in rows if isinstance(row, dict)]
    if len(ids) != len(rows) or len(set(ids)) != len(ids):
        raise ValueError("catalog source_id values must be unique")
    return {row["source_id"]: row for row in rows}


def host_decision(url, allowlist):
    """HTTPS on an exact allowlisted host, no credentials, no port. Never widens the list."""
    try:
        parts = urllib.parse.urlsplit(url if isinstance(url, str) else "")
        host = parts.hostname
        port = parts.port
    except ValueError:
        return None, "access_url_malformed"
    if parts.scheme != "https" or not host:
        return host, "access_url_not_https"
    if parts.username or parts.password or port is not None:
        return host, "access_url_credentials_or_port"
    if host not in allowlist.exact:
        return host, "access_host_not_on_reviewed_allowlist"
    return host, None


def _overlaps(a, b):
    try:
        w1, s1, e1, n1 = (float(v) for v in a)
        w2, s2, e2, n2 = (float(v) for v in b)
    except (TypeError, ValueError):
        return False
    if not (w1 < e1 and s1 < n1 and w2 < e2 and s2 < n2):
        return False
    return min(e1, e2) > max(w1, w2) and min(n1, n2) > max(s1, s2)


def _window(value):
    if (not isinstance(value, list) or len(value) != 4 or any(type(v) is not int for v in value)
            or min(value[:2]) < 0 or min(value[2:]) <= 0 or value[2] * value[3] > MAX_WINDOW_CELLS):
        raise ValueError("explicit bounded integer native window required")
    return value


def _hash_binding(declared, sha256):
    """Bind to the catalog's hash only when it is a SHA-256; otherwise record it as unknown."""
    if declared in (None, "", "unknown"):
        return "unknown"
    text = str(declared).lower()
    text = text[7:] if text.startswith("sha256:") else text
    if not HEX64.fullmatch(text):
        return "unknown"
    return "matched" if text == sha256 else "mismatch"


def cached_source(root, source):
    """lstat-only check of a cached native source inside the queue root. Never opens it."""
    if not isinstance(source, dict):
        raise ValueError("cached source ref required")
    path, sha, size = source.get("path"), source.get("sha256"), source.get("bytes")
    if not isinstance(path, str) or not path or Path(path).is_absolute() or ".." in Path(path).parts:
        raise ValueError("cached source path must be relative to the queue root")
    if not isinstance(sha, str) or not HEX64.fullmatch(sha) or type(size) is not int or size <= 0:
        raise ValueError("cached source sha256 and positive byte count required")
    if not isinstance(source.get("contract"), str) or not source["contract"]:
        raise ValueError("cached source contract required")
    if not path.lower().endswith(NATIVE_SUFFIXES):
        raise ValueError("cached source must be a native BAG or GeoTIFF, or a netCDF grid")
    cursor, info = Path(root), None
    for part in Path(path).parts:
        cursor = cursor / part
        info = os.lstat(cursor)
        if stat.S_ISLNK(info.st_mode):
            raise ValueError("symlink in cached source path")
    if info is None or not stat.S_ISREG(info.st_mode):
        raise ValueError("cached source must be a regular file")
    if info.st_size != size:
        raise ValueError("cached source byte count differs from its ref")
    return dict(path=path, sha256=sha, bytes=size, contract=source["contract"],
                **({"kind": source["kind"]} if "kind" in source else {}))


def check_budget(budget):
    if not isinstance(budget, dict) or set(budget) != {"wall_s", "memory_bytes", "bytes", "requests"}:
        raise ValueError("acquire budget needs exactly wall_s, memory_bytes, bytes, requests")
    if any(type(budget[k]) is not int for k in budget):
        raise ValueError("acquire budget values must be integers")
    if budget["requests"] != 0:
        raise ValueError("source-free acquire budget allows zero requests")
    if not 0 < budget["wall_s"] <= MAX_WALL_S or budget["memory_bytes"] <= 0:
        raise ValueError("acquire wall/memory budget outside the bridge cap")
    if not 0 < budget["bytes"] <= MAX_TOTAL_BYTES:
        raise ValueError("acquire byte budget outside the bridge cap")
    return budget


def check_plan(plan, catalog_raw, catalog):
    if not isinstance(plan, dict) or plan.get("schema") != PLAN:
        raise ValueError("catalog acquire bridge plan required")
    if plan.get("catalog_id") != catalog["catalog_id"] or plan.get("catalog_sha256") != _sha(catalog_raw):
        raise ValueError("plan is not bound to this exact frozen catalog")
    segment = plan.get("segment")
    if (not isinstance(segment, dict) or not isinstance(segment.get("segment_id"), str)
            or not isinstance(segment.get("bbox_crs84"), list) or len(segment["bbox_crs84"]) != 4):
        raise ValueError("plan segment_id and bbox_crs84 required")
    if type(plan.get("synthetic", False)) is not bool:
        raise ValueError("synthetic must be a boolean")
    limit = plan.get("max_total_bytes")
    if type(limit) is not int or not 0 < limit <= MAX_TOTAL_BYTES:
        raise ValueError("max_total_bytes must be a positive integer within the bridge cap")
    check_budget(plan.get("budget"))
    selections = plan.get("selections")
    if not isinstance(selections, list) or not 1 <= len(selections) <= MAX_JOBS:
        raise ValueError(f"plan must select 1..{MAX_JOBS} catalog candidates")
    ids = [s.get("source_id") if isinstance(s, dict) else None for s in selections]
    if None in ids or len(set(ids)) != len(ids):
        raise ValueError("each selection names one distinct source_id")
    return segment, selections


def _decide(root, selection, row, catalog, segment, allowlist, now):
    holds = []
    if row is None:
        return dict(source_id=selection["source_id"], state="held", holds=["not_in_catalog"])
    if row["source_id"] not in catalog["usable_source_ids"]:
        holds.append("not_a_usable_catalog_lead")
    if row.get("rejection_reasons"):
        holds.append("catalog_rejection_reasons_present")
    if (row.get("terrain") or {}).get("status") != "candidate_for_qualification":
        holds.append("terrain_not_candidate_for_qualification")
    host, refused = host_decision(row.get("access_url"), allowlist)
    if refused:
        holds.append(refused)
    extent = row.get("extent") or {}
    if extent.get("bbox_crs") not in GEOGRAPHIC or not _overlaps(extent.get("bbox"), segment["bbox_crs84"]):
        holds.append("catalog_extent_does_not_overlap_segment")
    try:
        if _stamp(row.get("expires_at")) <= now:
            holds.append("catalog_candidate_expired")
    except ValueError:
        holds.append("catalog_candidate_expiry_unknown")
    decision: dict = dict(source_id=row["source_id"], publisher_id=row.get("publisher_id"),
                    access_url=row.get("access_url"), access_host=host)
    try:
        source = cached_source(root, selection.get("source"))
        _window(selection.get("window"))
    except (ValueError, OSError) as exc:
        holds.append("cached_source_or_window_invalid:" + str(exc)[:200])
        return dict(decision, state="held", holds=holds)
    metadata = row.get("metadata") or {}
    if metadata.get("size_bytes") not in (None, "", "unknown") and metadata["size_bytes"] != source["bytes"]:
        holds.append("cached_size_differs_from_catalog")
    binding = _hash_binding(metadata.get("source_hash"), source["sha256"])
    if binding == "mismatch":
        holds.append("cached_sha256_differs_from_catalog")
    decision.update(source=source, catalog_hash_binding=binding)
    return dict(decision, state="held" if holds else "selected", holds=holds)


def evaluate(root, catalog_path, plan, *, allowlist=None, now=None):
    """All gates, no writes. Raises on a plan-level refusal; per-candidate holds are returned."""
    if allowlist is None:
        from ...http import default_allowlist
        allowlist = default_allowlist()
    now = now if now is not None else datetime.now(timezone.utc).timestamp()
    root = Path(root).resolve(strict=True)
    catalog, catalog_raw = _read(catalog_path, "catalog")
    rows = check_catalog(catalog)
    segment, selections = check_plan(plan, catalog_raw, catalog)
    decisions = [_decide(root, s, rows.get(s["source_id"]), catalog, segment, allowlist, now) for s in selections]
    selected = [d for d in decisions if d["state"] == "selected"]
    total = sum(d["source"]["bytes"] for d in selected)
    if total > plan["max_total_bytes"]:
        raise ValueError("selected cached sources exceed max_total_bytes")
    for d in selected:
        if d["source"]["bytes"] > plan["budget"]["bytes"]:
            raise ValueError("a cached source exceeds the per-job acquire byte budget")
    return dict(catalog=catalog, catalog_ref=dict(sha256=_sha(catalog_raw), bytes=len(catalog_raw),
                                                  catalog_id=catalog["catalog_id"], schema=CATALOG),
                segment=segment, selections={s["source_id"]: s for s in selections},
                decisions=decisions, selected_bytes=total)


def native_job(plan, selection, decision, catalog_ref):
    """The acquire stage's existing input contract, with catalog lineage attached."""
    job = dict(schema=NATIVE_JOB, synthetic=plan.get("synthetic", False),
               segment_id=plan["segment"]["segment_id"], source=decision["source"],
               window=selection["window"], vertical=selection.get("vertical"),
               rights=selection.get("rights"),
               catalog_lineage=dict(catalog_id=catalog_ref["catalog_id"], catalog_sha256=catalog_ref["sha256"],
                                    source_id=decision["source_id"], publisher_id=decision["publisher_id"],
                                    access_url=decision["access_url"],
                                    catalog_hash_binding=decision["catalog_hash_binding"],
                                    review_required=True))
    for key in ("review", "source_row", "metadata_sha256"):
        if key in selection:
            job[key] = selection[key]
    return job


def _create(directory, inside=None):
    """Make a new output directory, returned as resolved-parent / leaf.

    Normalizing before any check or write keeps a relative `out` consistent with the
    resolved queue root, so every ref later derived with `relative_to(root)` holds.
    """
    directory = Path(directory)
    if directory.name in ("", ".", ".."):
        raise ValueError("output directory needs a plain final name")
    if not directory.parent.is_dir():
        raise ValueError("output parent must already exist")
    directory = directory.parent.resolve(strict=True) / directory.name
    if directory.exists() or directory.is_symlink():
        raise ValueError("output directory exists; a bridge attempt is never reused")
    if inside is not None and not directory.parent.is_relative_to(inside):
        raise ValueError("bridge output must be inside the coordinator queue root")
    directory.mkdir(mode=0o700)
    return directory


def _freeze(path, value):
    raw = _encode(value)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o444)
    try:
        os.write(fd, raw)
        os.fsync(fd)
    finally:
        os.close(fd)
    return raw


def _receipt(schema, plan, checked):
    selected = [d for d in checked["decisions"] if d["state"] == "selected"]
    return dict(schema=schema, plan_sha256=digest(plan), catalog=checked["catalog_ref"],
                segment_id=checked["segment"]["segment_id"], decisions=checked["decisions"],
                selected_source_ids=[d["source_id"] for d in selected],
                held_source_ids=[d["source_id"] for d in checked["decisions"] if d["state"] != "selected"],
                caps=dict(max_jobs=MAX_JOBS, max_total_bytes=MAX_TOTAL_BYTES,
                          plan_max_total_bytes=plan["max_total_bytes"], selected_bytes=checked["selected_bytes"],
                          acquire_budget=plan["budget"]),
                network_requests=0, source_opens=0, source_bytes_read=0,
                review_required=True, mapping_accepted=False, execution_authorized=False,
                note=("Source-free bridge: catalog and plan JSON read, cached sources lstat-checked only. "
                      "Acquire, qualify, map and render keep their own gates; nothing here is accepted."))


def dry_run(root, catalog_path, plan, out, *, allowlist=None, now=None):
    """Prove the gates and show what would be enqueued; writes only the receipt."""
    checked = evaluate(root, catalog_path, plan, allowlist=allowlist, now=now)
    out = _create(out)
    receipt = _receipt(DRY_RUN, plan, checked)
    receipt["would_enqueue"] = [dict(stage="acquire", source_id=d["source_id"],
                                     native_job_sha256=digest(native_job(plan, checked["selections"][d["source_id"]],
                                                                         d, checked["catalog_ref"])))
                                for d in checked["decisions"] if d["state"] == "selected"]
    raw = _freeze(out / "bridge-dry-run-receipt.json", receipt)
    return dict(receipt, output=dict(path="bridge-dry-run-receipt.json", sha256=_sha(raw), bytes=len(raw)))


def run(root, catalog_path, plan, out, *, allowlist=None, now=None):
    """Write the native-job manifests (inside the queue root) and the receipt, once."""
    root = Path(root).resolve(strict=True)
    checked = evaluate(root, catalog_path, plan, allowlist=allowlist, now=now)
    out = _create(out, inside=root)
    jobs = []
    for index, decision in enumerate(d for d in checked["decisions"] if d["state"] == "selected"):
        manifest = native_job(plan, checked["selections"][decision["source_id"]], decision, checked["catalog_ref"])
        path = out / f"native-job-{index:02}.json"
        raw = _freeze(path, manifest)
        jobs.append(dict(source_id=decision["source_id"], stage="acquire",
                         input_manifest=dict(path=path.relative_to(root).as_posix(), sha256=_sha(raw),
                                             bytes=len(raw), kind="input", contract=NATIVE_JOB)))
    receipt = _receipt(RECEIPT, plan, checked)
    receipt.update(jobs=jobs, budget=plan["budget"], segment=checked["segment"])
    raw = _freeze(out / "bridge-receipt.json", receipt)
    return dict(receipt, output=dict(path=(out / "bridge-receipt.json").relative_to(root).as_posix(),
                                     sha256=_sha(raw), bytes=len(raw)))


def enqueue(store, receipt_ref, *, code_sha, deps_sha, max_attempts=2):
    """Queue each bridged native job at the acquire stage through the ordinary Store API."""
    root = Path(store.root)
    path = verify_ref(root, receipt_ref)
    receipt, _ = _read(path, "bridge receipt")
    if receipt.get("schema") != RECEIPT or receipt.get("execution_authorized") is not False:
        raise ValueError("bridge receipt required")
    if not 1 <= len(receipt.get("jobs", [])) <= MAX_JOBS:
        raise ValueError("bridge receipt carries no bounded job set")
    budget = check_budget(receipt.get("budget"))
    segment = receipt["segment"]
    row = store.db.execute("SELECT record_json FROM segments WHERE segment_id=?",
                           (segment["segment_id"],)).fetchone()
    if row is None:
        raise ValueError("unknown segment")
    record = json.loads(row[0])
    if record.get("bbox_crs84") != segment["bbox_crs84"]:
        raise ValueError("store segment differs from the bridged segment")
    job_ids = []
    for job in receipt["jobs"]:
        ref = job["input_manifest"]
        verify_ref(root, ref)
        job_ids.append(store.enqueue(segment["segment_id"], "acquire", code_sha=code_sha, deps_sha=deps_sha,
                                     input_manifest=ref, budget=dict(budget), max_attempts=max_attempts))
    return job_ids


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("dry-run", "run"):
        command = sub.add_parser(name)
        command.add_argument("--root", type=Path, required=True, help="Coordinator queue root")
        command.add_argument("--catalog", type=Path, required=True, help="Frozen discovery catalog.json")
        command.add_argument("--plan", type=Path, required=True, help="Owner bridge plan JSON")
        command.add_argument("--out", type=Path, required=True, help="New directory; never reused")
    args = parser.parse_args(argv)
    plan, _ = _read(args.plan, "plan")
    action = dry_run if args.command == "dry-run" else run
    result = action(args.root, args.catalog, plan, args.out)
    print(json.dumps({k: result.get(k) for k in ("schema", "plan_sha256", "catalog", "selected_source_ids",
                                                  "held_source_ids", "caps", "network_requests", "output")},
                     indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
