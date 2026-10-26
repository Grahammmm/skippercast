"""Governed live coastal discovery: one bounded host step that freezes a catalog.

This is the host-side wiring around the reviewed bounded discovery script
(`skills/skippercast-discover-coastal-sources/scripts/discover.py`). It adds
three gates the script cannot provide on its own and changes nothing else:

- every catalog host must already be on the repository's reviewed source
  allowlist (`skippercast.http.default_allowlist`); this step never adds hosts;
- the fixed `discovery30` profile caps the run at 250,000,000 response-body
  bytes and 1,800 wall seconds (1,500 discovery seconds plus cleanup), and the
  planned per-query ceilings must fit inside the byte cap before any request;
- the finalized manifest is written once into an immutable frozen catalog with
  a diff against the previous catalog and a receipt. An output directory is
  never reused, so a spent attempt cannot be replayed into a fresh allowance.

`dry-run` performs no network request. `run` performs the live discovery. The
script's own durable byte reservation, owned child process, per-request
timeouts, attempt ceilings and access stops remain the request mechanism.

The coordinator is unchanged: its discover stage still reads only an explicit
`coastal-local-discovery-plan-v1` of cached candidates. A frozen catalog is
metadata evidence for the owner to review; every candidate stays
`accepted=false`, and machine-valid output is review-required, not accepted.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import time
import urllib.parse

from ..http import default_allowlist
from ..paths import repo_root

PLAN = "coastal-governed-live-discovery-plan-v1"
CATALOG = "coastal-frozen-discovery-catalog-v1"
DIFF = "coastal-frozen-discovery-diff-v1"
RECEIPT = "coastal-governed-live-discovery-receipt-v1"
DRY_RUN = "coastal-governed-live-discovery-dry-run-v1"
MAX_BYTES = 250_000_000
WALL_SECONDS = 1800
CLEANUP_SECONDS = 300
PROFILE = "discovery30"
ADAPTERS = ("arcgis", "stac", "listing")
LISTING_SUFFIXES = (".bag", ".bag.gz", ".tif", ".tiff", ".zip", ".xml")
SCRIPT = Path("skills/skippercast-discover-coastal-sources/scripts/discover.py")
DIFF_FIELDS = ("access_url", "metadata", "extent", "rejection_reasons", "unknowns", "terrain")


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _digest(value):
    return _sha(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode())


def _encode(value):
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()


def _stamp(epoch):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(epoch))


def load_script(root=None):
    """Load the reviewed bounded discovery script as a module (no copy, no fork)."""
    path = (Path(root) if root else repo_root()) / SCRIPT
    spec = importlib.util.spec_from_file_location("coastal_bounded_discover", path)
    if spec is None or spec.loader is None:
        raise ValueError("bounded discovery script unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, path


def check_plan(plan, allowlist=None):
    """Return the script plan and per-host decisions, or raise before any request."""
    allowlist = allowlist if allowlist is not None else default_allowlist()
    if not isinstance(plan, dict) or plan.get("schema") != PLAN:
        raise ValueError("governed live discovery plan required")
    for key in ("region", "source_revision", "policy_revision"):
        if not isinstance(plan.get(key), str) or not plan[key].strip():
            raise ValueError(f"plan {key} required")
    limit = plan.get("byte_limit")
    if type(limit) is not int or not 0 < limit <= MAX_BYTES:
        raise ValueError("byte_limit must be an integer within the 250,000,000-byte cap")
    if plan.get("wall_seconds", WALL_SECONDS) != WALL_SECONDS or plan.get("profile", PROFILE) != PROFILE:
        raise ValueError("only the fixed discovery30 profile (1,800 s wall) is governed")
    catalogs = plan.get("catalogs")
    if not isinstance(catalogs, list) or not 1 <= len(catalogs) <= 4:
        raise ValueError("plan must contain 1..4 official catalogs")
    hosts, planned, queries = {}, 0, 0
    for catalog in catalogs:
        allowed = catalog.get("allowed_hosts")
        if not isinstance(allowed, list) or not allowed:
            raise ValueError("catalog exact host allowlist required")
        for host in allowed:
            if not isinstance(host, str) or host != host.lower().rstrip(".") or "*" in host:
                raise ValueError("catalog hosts must be exact lower-case DNS names")
            # Exact membership only: a suffix wildcard in the repository list
            # never widens a governed discovery plan.
            ok = host in allowlist.exact
            hosts[host] = ok
            if not ok:
                raise ValueError(f"host not on the reviewed source allowlist: {host}")
        for url in [catalog.get("authority_url")] + [q.get("url") for q in catalog.get("queries", [])]:
            parts = urllib.parse.urlsplit(url or "")
            if parts.scheme != "https" or parts.hostname not in allowed:
                raise ValueError(f"URL outside the catalog's HTTPS host allowlist: {url}")
        for query in catalog.get("queries", []):
            queries += 1
            if query.get("adapter") not in (None, *ADAPTERS):
                raise ValueError("unknown response adapter")
            size = query.get("max_bytes")
            if type(size) is not int or size <= 0:
                raise ValueError("explicit per-query byte ceiling required")
            planned += size
    if not 1 <= queries <= 12:
        raise ValueError("plan must contain 1..12 finite queries")
    if planned > limit:
        raise ValueError("planned per-query ceilings exceed the byte cap")
    script_plan = dict(catalogs=json.loads(json.dumps(catalogs)))
    return script_plan, dict(hosts=dict(sorted(hosts.items())), planned_max_bytes=planned,
                             queries=queries, byte_limit=limit)


def _bbox(plan):
    value = plan.get("bbox")
    if not isinstance(value, list) or len(value) != 4:
        raise ValueError("bbox of four CRS84 numbers required")
    return value


def _create(directory):
    directory = Path(directory)
    if directory.exists():
        raise ValueError("output directory exists; a governed attempt is never reused")
    if not directory.parent.is_dir():
        raise ValueError("output parent must already exist")
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
    return dict(path=Path(path).name, sha256=_sha(raw), bytes=len(raw))


def dry_run(plan, out, *, root=None, allowlist=None, clock=time.time):
    """Validate the plan and caps through the real script init; no request is made."""
    script_plan, decisions = check_plan(plan, allowlist)
    discover, script = load_script(root)
    out = _create(out)
    checkpoint = out / "dry-run-checkpoint.json"
    with discover.locked(checkpoint):
        state = discover.init(checkpoint, plan["region"], _bbox(plan), script_plan,
                              plan["source_revision"], plan["policy_revision"],
                              byte_limit=plan["byte_limit"], clock=clock, profile=PROFILE)
    start = discover.timestamp(state["start_utc"])
    schedule = [dict(catalog=c["id"], url=q["url"], purpose=q["purpose"], max_bytes=q["max_bytes"],
                     adapter=q.get("adapter")) for c in state["plan"]["catalogs"] for q in c["queries"]]
    receipt = dict(schema=DRY_RUN, region=plan["region"], plan_sha256=_digest(plan),
                   script_plan_sha256=state["plan_sha256"], script_sha256=_sha(script.read_bytes()),
                   allowlist=decisions, schedule=schedule, network_requests=0,
                   caps=dict(byte_limit=state["limits"]["bytes"], max_bytes=MAX_BYTES,
                             wall_seconds=discover.timestamp(state["deadline_utc"]) - start,
                             discovery_seconds=discover.timestamp(state["discovery_cutoff_utc"]) - start,
                             requests=state["limits"]["requests"], request_seconds=state["limits"]["request_seconds"]),
                   checkpoint=dict(path=checkpoint.name, status=state["status"]),
                   note="Dry run: plan, allowlist and caps accepted by the bounded script; nothing fetched.")
    receipt["output"] = _freeze(out / "dry-run-receipt.json", receipt)
    return receipt


def listing_annotation(discover, row, allowed_hosts):
    """Deterministic candidates from literal links in a saved directory listing.

    Only exact links to native-looking files on the catalog's own hosts are kept.
    Footprint, CRS and every other field stay unknown: a file name is not metadata.
    """
    body = Path(row["body_path"]).read_bytes()
    text = body.decode("utf-8", errors="replace")
    found = {}
    for link in sorted(discover.response_links(text, row["url"])):
        parts = urllib.parse.urlsplit(link)
        name = parts.path.rstrip("/").rsplit("/", 1)[-1]
        if parts.hostname in allowed_hosts and name.lower().endswith(LISTING_SUFFIXES) and not parts.query:
            if name in found and found[name] != link:
                raise ValueError("listing_basename_collision")
            found.setdefault(name, link)
    return dict(response_sha256=row["sha256"], candidates=[
        dict(publisher_id=name, title=name, bbox=None, bbox_crs=None, catalog_geometry=None,
             crs=None, resolution=None, vertical_datum=None, z_units=None, rights=None,
             size_bytes=None, source_hash=None, access_url=url, alternate_of=None,
             field_evidence=dict(access_url="literal href in saved directory listing",
                                 publisher_id="file name of that href"))
        for name, url in sorted(found.items())])


def _candidates(document):
    if not isinstance(document, dict) or document.get("schema") not in (CATALOG, "coastal-source-v1"):
        raise ValueError("previous catalog must be a frozen catalog or finalized source manifest")
    rows = document.get("candidates")
    if not isinstance(rows, list):
        raise ValueError("previous catalog candidates required")
    return {row["source_id"]: row for row in rows}


def diff(previous, current, previous_ref=None):
    old = _candidates(previous) if previous is not None else {}
    new = _candidates(current)
    changed = sorted(k for k in set(old) & set(new)
                     if any(old[k].get(f) != new[k].get(f) for f in DIFF_FIELDS))
    return dict(schema=DIFF, previous=previous_ref, current_catalog_id=current.get("catalog_id"),
                added=sorted(set(new) - set(old)), removed=sorted(set(old) - set(new)),
                changed=[dict(source_id=k, fields=[f for f in DIFF_FIELDS if old[k].get(f) != new[k].get(f)])
                         for k in changed],
                unchanged=len(set(old) & set(new)) - len(changed),
                note="Catalog metadata diff only; no candidate is accepted for mapping or rendering.")


def frozen_catalog(manifest, manifest_bytes):
    from copy import deepcopy

    keys = ("source_id", "publisher_id", "title", "catalog_id", "provenance", "metadata", "extent",
            "access_url", "unknowns", "rejection_reasons", "alternate_of", "terrain", "habitat",
            "render", "next_action", "expires_at", "field_evidence")
    candidates = sorted(({k: c.get(k) for k in keys} for c in manifest["candidates"]),
                        key=lambda c: c["source_id"])
    body = dict(schema=CATALOG, region=manifest["region"], bbox=manifest["bbox"],
                source_revision=manifest["source_revision"], policy_revision=manifest["policy_revision"],
                method_revision=manifest["method_revision"], plan_sha256=manifest["plan_sha256"],
                manifest_sha256=_sha(manifest_bytes), checked_from=manifest["start_utc"],
                checked_until=manifest["stopped_at"], manifest_status=manifest["manifest_status"],
                bounded_plan_finished=manifest["bounded_plan_finished"],
                discovery_complete=manifest["discovery_complete"],
                unattempted_queries=manifest["unattempted_queries"],
                lead_source_ids=manifest["lead_source_ids"], usable_source_ids=manifest["usable_source_ids"],
                candidates=candidates, mapping_accepted=False, execution_authorized=False,
                review_required=True,
                coordinator_boundary=("Metadata catalog only. The coordinator discover stage reads an explicit "
                                      "coastal-local-discovery-plan-v1; this catalog does not enqueue work."))
    # Detach every retained JSON value before binding the snapshot's identity.
    body = deepcopy(body)
    body["catalog_id"] = _digest(body)
    return body


def run(plan, out, *, previous=None, root=None, allowlist=None, clock=time.time,
        monotonic=time.monotonic, runner=None):
    """One live bounded discovery attempt; writes catalog, diff and receipt once."""
    script_plan, decisions = check_plan(plan, allowlist)
    discover, script = load_script(root)
    previous_doc = previous_ref = None
    if previous is not None:
        raw = Path(previous).read_bytes()
        if len(raw) > discover.MAX_METADATA:
            raise ValueError("previous catalog exceeds metadata limit")
        previous_doc = json.loads(raw)
        _candidates(previous_doc)
        previous_ref = dict(path=str(Path(previous).resolve()), sha256=_sha(raw), bytes=len(raw),
                            schema=previous_doc["schema"])
    out = _create(out)
    began, mono = clock(), monotonic()
    # Supervisor ceiling independent of the script's own UTC deadline.
    hard_stop = mono + WALL_SECONDS - CLEANUP_SECONDS
    checkpoint = out / "checkpoint.json"
    events = []
    adapters = {(c["id"], discover.url_key(q["url"])): q.get("adapter")
                for c in plan["catalogs"] for q in c["queries"]}
    with discover.locked(checkpoint):
        discover.init(checkpoint, plan["region"], _bbox(plan), script_plan, plan["source_revision"],
                      plan["policy_revision"], byte_limit=plan["byte_limit"], clock=clock, profile=PROFILE)
        stopped = set()
        for catalog in script_plan["catalogs"]:
            for query in catalog["queries"]:
                remaining = hard_stop - monotonic()
                if catalog["id"] in stopped:
                    events.append(dict(url=query["url"], action="skipped", reason="catalog_access_stop"))
                    continue
                if remaining <= 1:
                    events.append(dict(url=query["url"], action="skipped", reason="discovery_cutoff"))
                    continue
                try:
                    row = discover.request(checkpoint, catalog["id"], query["url"],
                                           seconds=min(60, remaining), clock=clock, runner=runner)
                except ValueError as exc:
                    events.append(dict(url=query["url"], action="refused", reason=str(exc)[:300]))
                    continue
                events.append(dict(url=row["url"], action="requested", request_id=row["id"], status=row["status"]))
                if row["status"] == "ACCESS_STOP":
                    stopped.add(catalog["id"])
                adapter = adapters.get((catalog["id"], row["url"]))
                if row["status"] != "OK" or adapter is None:
                    continue
                try:
                    if adapter == "listing":
                        annotation = out / f"annotation-{row['id']:03}.json"
                        annotation.write_bytes(_encode(listing_annotation(discover, row, catalog["allowed_hosts"])))
                        discover.ingest(checkpoint, row["id"], "normalized", str(annotation), clock=clock)
                    else:
                        discover.ingest(checkpoint, row["id"], adapter, clock=clock)
                    events.append(dict(url=row["url"], action="ingested", request_id=row["id"], adapter=adapter))
                except (ValueError, KeyError, TypeError) as exc:
                    events.append(dict(url=row["url"], action="ingest_failed", request_id=row["id"],
                                       reason=str(exc)[:300]))
        manifest = discover.finalize(checkpoint, "governed live discovery: finite plan attempted", clock=clock)
    manifest_path = checkpoint.with_name(checkpoint.stem + "-manifest.json")
    manifest_bytes = manifest_path.read_bytes()
    catalog = frozen_catalog(manifest, manifest_bytes)
    outputs = [_freeze(out / "catalog.json", catalog)]
    change = diff(previous_doc, catalog, previous_ref)
    outputs.append(_freeze(out / "catalog-diff.json", change))
    elapsed = monotonic() - mono
    requests = [{k: r.get(k) for k in ("id", "catalog", "url", "purpose", "status", "http_status",
                                         "byte_reservation", "observed_body_bytes", "sha256",
                                         "elapsed_seconds", "start_utc", "stop_utc", "location")}
                for r in manifest["requests"]]
    receipt = dict(schema=RECEIPT, region=plan["region"], plan_sha256=_digest(plan),
                   script_plan_sha256=manifest["plan_sha256"], script=str(SCRIPT),
                   script_sha256=_sha(script.read_bytes()),
                   module_sha256=_sha(Path(__file__).read_bytes()), allowlist=decisions,
                   caps=dict(byte_limit=manifest["limits"]["bytes"], max_bytes=MAX_BYTES,
                             wall_seconds=WALL_SECONDS, discovery_seconds=WALL_SECONDS - CLEANUP_SECONDS),
                   start_utc=_stamp(began), stop_utc=_stamp(clock()), elapsed_seconds=round(elapsed, 3),
                   budget_charged_bytes=manifest["budget_charged_bytes"],
                   observed_body_bytes=manifest["observed_body_bytes"],
                   within_caps=(manifest["budget_charged_bytes"] <= manifest["limits"]["bytes"] <= MAX_BYTES
                                and elapsed <= WALL_SECONDS),
                   network_requests=len(manifest["requests"]), requests=requests, events=events,
                   manifest=dict(path=manifest_path.name, sha256=_sha(manifest_bytes), bytes=len(manifest_bytes)),
                   catalog_id=catalog["catalog_id"], outputs=outputs,
                   diff_summary=dict(added=len(change["added"]), removed=len(change["removed"]),
                                     changed=len(change["changed"]), unchanged=change["unchanged"]),
                   review_required=True, mapping_accepted=False, execution_authorized=False,
                   model_usage=manifest.get("model_usage"))
    receipt["outputs"].append(_freeze(out / "receipt.json", receipt))
    return receipt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("dry-run", "run"):
        command = sub.add_parser(name)
        command.add_argument("--plan", type=Path, required=True)
        command.add_argument("--out", type=Path, required=True, help="New directory; never reused")
        if name == "run":
            command.add_argument("--previous", type=Path, help="Previous frozen catalog or source manifest")
    args = parser.parse_args(argv)
    if args.plan.stat().st_size > 1_000_000:
        raise SystemExit("plan exceeds 1,000,000 bytes")
    plan = json.loads(args.plan.read_text())
    if args.command == "dry-run":
        result = dry_run(plan, args.out)
    else:
        result = run(plan, args.out, previous=args.previous)
    summary = {k: result.get(k) for k in ("schema", "plan_sha256", "caps", "network_requests",
                                          "budget_charged_bytes", "within_caps", "catalog_id", "diff_summary")}
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
