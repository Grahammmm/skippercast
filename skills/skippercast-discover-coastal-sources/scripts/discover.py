#!/usr/bin/env python3
"""Finite, restart-safe coastal catalog discovery. No mapping or publication.

HTTPS requests use the standard library in an owned child process. The parent
reserves each byte allowance durably before launch; ambiguous failures retain
the reservation, so a crash cannot replenish the transfer budget.
"""
import argparse
import contextlib
import datetime as dt
import fcntl
import hashlib
import html
from html.parser import HTMLParser
import json
import math
import os
import re
from pathlib import Path
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

VERSION = "coastal-source-v1"
METHOD = "bounded-catalog-v1"
MAX_BYTES = 250_000_000
MAX_METADATA = 5_000_000
UTC = dt.timezone.utc


def now():
    return dt.datetime.now(UTC).timestamp()


def stamp(value):
    return dt.datetime.fromtimestamp(value, UTC).isoformat().replace("+00:00", "Z")


def timestamp(value):
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.utcoffset() != dt.timedelta(0):
        raise ValueError("time must have explicit UTC offset")
    return parsed.timestamp()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def read(path):
    p = Path(path)
    if p.stat().st_size > MAX_METADATA:
        raise ValueError("JSON exceeds metadata limit")
    return json.loads(p.read_text())


def atomic(path, value):
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w") as f:
        json.dump(value, f, sort_keys=True, indent=2, allow_nan=False)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


@contextlib.contextmanager
def locked(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix(path.suffix + ".lock").open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def url_key(url):
    p = urllib.parse.urlsplit(url)
    if p.scheme != "https" or not p.hostname or p.username or p.password or p.fragment:
        raise ValueError("only unauthenticated HTTPS URLs without fragments")
    if p.port not in (None, 443):
        raise ValueError("only HTTPS port 443")
    return urllib.parse.urlunsplit(("https", p.hostname.lower(), p.path or "/", urllib.parse.urlencode(sorted(urllib.parse.parse_qsl(p.query, keep_blank_values=True))), ""))


def bbox(value):
    if not isinstance(value, list) or len(value) != 4 or any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) for x in value):
        raise ValueError("bbox must be four finite longitude/latitude numbers")
    w, s, e, n = value
    if not (-180 <= w < e <= 180 and -90 <= s < n <= 90):
        raise ValueError("invalid CRS84 bbox; split antimeridian regions into windows")
    return value


def overlaps(a, b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def known_crs(value):
    if not isinstance(value, str) or not value:
        return False
    try:
        from pyproj import CRS
        CRS.from_user_input(value if value != "CRS84" else "OGC:CRS84")
        return True
    except ImportError:
        return value in ("CRS84", "EPSG:4326", "EPSG:3857")
    except Exception:
        return False


def init(path, region, bounds, plan, source_revision, policy_revision, start=None,
         seconds=1800, reserve=300, byte_limit=MAX_BYTES, clock=now, profile="discovery30"):
    if Path(path).exists():
        raise ValueError("checkpoint already exists; use status/resume, never renew")
    current = clock()
    if profile not in ("discovery30", "acquisition60"):
        raise ValueError("unknown explicitly selected mission profile")
    ceiling = 3600 if profile == "acquisition60" else 1800
    if profile == "acquisition60" and seconds == 1800 and reserve == 300:
        seconds, reserve = 3600, 600
    began = timestamp(start) if start else current
    if began > current + 1 or current - began > seconds:
        raise ValueError("start must be an actual current/past UTC trial start")
    if not (0 < reserve < seconds <= ceiling and 0 < byte_limit <= MAX_BYTES):
        raise ValueError("selected profile wall/cleanup or 250,000,000-byte ceiling exceeded")
    if profile == "acquisition60" and reserve < 600:
        raise ValueError("acquisition60 reserves at least 600 seconds for cleanup")
    catalogs = plan.get("catalogs", [])
    if not 1 <= len(catalogs) <= 4:
        raise ValueError("plan must contain 1..4 official catalogs")
    ids, urls = set(), set()
    for c in catalogs:
        if not c.get("id") or c["id"] in ids or not c.get("publisher"):
            raise ValueError("unique catalog id and original publisher required")
        ids.add(c["id"])
        authority = url_key(c["authority_url"])
        hosts = c.get("allowed_hosts", [])
        if not hosts or urllib.parse.urlsplit(authority).hostname not in hosts:
            raise ValueError("official authority URL must be in reviewed exact host allowlist")
        for q in c.get("queries", []):
            q["url"] = url_key(q["url"])
            if urllib.parse.urlsplit(q["url"]).hostname not in hosts or q["url"] in urls:
                raise ValueError("query host not allowlisted or duplicate URL")
            urls.add(q["url"])
            if q.get("purpose") not in ("metadata", "footprint", "sample"):
                raise ValueError("invalid query purpose")
            if not 0 < q.get("max_bytes", 0) <= (MAX_METADATA if q["purpose"] != "sample" else byte_limit):
                raise ValueError("invalid per-query byte limit")
    if not 1 <= len(urls) <= 12:
        raise ValueError("plan must contain 1..12 finite queries")
    state = dict(schema=VERSION, method_revision=METHOD, source_revision=source_revision, profile=profile,
                 policy_revision=policy_revision, region=region, bbox=bbox(bounds),
                 start_utc=stamp(began), discovery_cutoff_utc=stamp(began + seconds - reserve),
                 deadline_utc=stamp(began + seconds), last_clock=current,
                 limits=dict(bytes=byte_limit, requests=16, catalogs=4, candidates=40, attempts_per_url=2, request_seconds=60),
                 plan=plan, plan_sha256=digest(plan), requests=[], candidates=[], reuses=[],
                 added_queries=[],
                 budget_charged_bytes=0, observed_body_bytes=0, status="ACTIVE",
                 model_usage=dict(model=None, effort=None, input_tokens=None, cached_input_tokens=None, output_tokens=None, reason="not exposed by harness"))
    atomic(path, state)
    return state


def active(s, clock=now):
    current = clock()
    if current < s["last_clock"] - 1:
        raise ValueError("UTC clock moved backwards; stop and preserve original deadline")
    s["last_clock"] = current
    if s["status"] != "ACTIVE":
        raise ValueError("run is terminal")
    if any(r["status"] == "RUNNING" for r in s["requests"]):
        raise ValueError("interrupted request remains; finalize conservatively before another mission")
    if any(r["status"] == "RUNNING" for r in s.get("quality_runs", [])):
        raise ValueError("interrupted quality inspection remains; recover before continuing")
    remaining = timestamp(s["discovery_cutoff_utc"]) - current
    if remaining <= 0:
        raise ValueError("discovery cutoff reached; finalize only")
    return remaining


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def fetch(url, cap, seconds, body, result, opener=None):
    """Child only. Never decompress or follow redirects; unknown lengths stream capped."""
    outcome = dict(status="ERROR", observed_body_bytes=0, content_length=None)
    opener = opener or urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "SkipperCast-coastal-discovery/1", "Accept-Encoding": "identity"})
        with opener.open(req, timeout=seconds) as response:
            length = response.headers.get("Content-Length")
            outcome["http_status"] = response.status
            if response.status != 200:
                raise ValueError("only HTTP 200 accepted")
            if length is not None:
                if not length.isdigit():
                    raise ValueError("malformed Content-Length")
                outcome["content_length"] = int(length)
                if int(length) > cap:
                    outcome["status"] = "OVERSIZED"
                    return outcome
            if response.headers.get("Content-Encoding", "identity").lower() != "identity":
                raise ValueError("compressed transfer rejected")
            h = hashlib.sha256()
            with Path(body).open("wb") as output:
                while outcome["observed_body_bytes"] < cap:
                    chunk = response.read(min(65536, cap - outcome["observed_body_bytes"]))
                    if not chunk:
                        break
                    output.write(chunk)
                    output.flush()
                    h.update(chunk)
                    outcome["observed_body_bytes"] += len(chunk)
                # Unknown length at exact cap is conservatively rejected without
                # reading one extra byte beyond the allowance.
                got = outcome["observed_body_bytes"]
                if length is None and got == cap:
                    outcome["status"] = "STREAM_CAP"
                elif length is not None and got != int(length):
                    outcome["status"] = "TRUNCATED"
                else:
                    outcome.update(status="OK", sha256=h.hexdigest())
    except urllib.error.HTTPError as exc:
        outcome.update(status="ACCESS_STOP" if exc.code in (401, 403) else "HTTP_ERROR", http_status=exc.code, error=str(exc))
        if exc.code in (301, 302, 303, 307, 308):
            outcome["location"] = exc.headers.get("Location")
    except (OSError, ValueError) as exc:
        outcome["error"] = str(exc)[:500]
    finally:
        atomic(result, outcome)
    return outcome


def request(path, catalog, url, max_bytes=None, seconds=60, changed=None, clock=now, runner=None):
    s = read(path)
    remaining = active(s, clock)
    url = url_key(url)
    c = next((c for c in s["plan"]["catalogs"] if c["id"] == catalog), None)
    q = next((q for q in c["queries"] if q["url"] == url), None) if c else None
    if q is None:
        raise ValueError("URL not in fixed official catalog query plan")
    if any(r["catalog"] == catalog and r["status"] == "ACCESS_STOP" for r in s["requests"]):
        raise ValueError("catalog access stopped; no authentication bypass or alternate route")
    prior = [r for r in s["requests"] if r["url"] == url]
    if len(prior) >= s["limits"]["attempts_per_url"] or len(s["requests"]) >= s["limits"]["requests"]:
        raise ValueError("attempt/request ceiling")
    change = read(changed) if changed else None
    if prior:
        if not change or not change.get("reason") or not change.get("evidence_url") or not change.get("change_id"):
            raise ValueError("unchanged retries forbidden; explicit changed evidence receipt required")
        if any(r.get("change_sha256") == digest(change) for r in prior):
            raise ValueError("unchanged retry receipt")
        url_key(change["evidence_url"])
    cap = q["max_bytes"] if max_bytes is None else max_bytes
    if not 0 < cap <= q["max_bytes"] or s["budget_charged_bytes"] + cap > s["limits"]["bytes"]:
        raise ValueError("transfer would exceed fixed byte budget")
    if not 0 < seconds <= s["limits"]["request_seconds"]:
        raise ValueError("request timeout outside ceiling")
    seconds = min(seconds, remaining)
    index = len(s["requests"]) + 1
    directory = Path(path).parent / (Path(path).stem + "-responses")
    directory.mkdir(exist_ok=True)
    body, result = directory / f"{index:03}.body", directory / f"{index:03}.json"
    row = dict(id=index, catalog=catalog, url=url, purpose=q["purpose"], start_utc=stamp(clock()),
               status="RUNNING", byte_reservation=cap, timeout_seconds=seconds,
               body_path=str(body.resolve()), result_path=str(result.resolve()),
               change_sha256=digest(change) if change else None)
    s["requests"].append(row)
    s["budget_charged_bytes"] += cap
    atomic(path, s)  # Write ahead: even SIGKILL retains the full byte reservation.
    began = time.monotonic()
    process = None
    interrupted = False
    try:
        if runner:
            runner(url, cap, seconds, body, result)
        else:
            process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "_fetch", url, str(cap), str(seconds), str(body), str(result), str(time.time() + seconds)], start_new_session=True)
            row["pid"] = process.pid
            atomic(path, s)
            process.wait(timeout=seconds)
    except subprocess.TimeoutExpired:
        row["status"] = "TIMEOUT"
    except (KeyboardInterrupt, InterruptedError):
        row["status"] = "INTERRUPTED"
        interrupted = True
    finally:
        if process is not None and process.poll() is None:
            # Kill only the process group launched by this live parent.
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
        observed = min(cap, body.stat().st_size) if body.exists() else 0
        if result.exists():
            outcome = read(result)
            row.update(outcome)
            # A failed read can consume bytes internally before raising, so
            # ERROR/TRUNCATED/interrupted receipts are lower bounds, not exact.
            # Only completed streams and known no-body rejections refund.
            if outcome["status"] in ("OK", "STREAM_CAP", "HTTP_ERROR", "ACCESS_STOP", "OVERSIZED"):
                s["budget_charged_bytes"] -= cap - outcome["observed_body_bytes"]
        elif row["status"] == "RUNNING":
            row["status"] = "FAILED_UNCERTAIN"
        row["observed_body_bytes"] = observed
        row["elapsed_seconds"] = time.monotonic() - began
        row["stop_utc"] = stamp(clock())
        s["observed_body_bytes"] += observed
        s["last_clock"] = max(s["last_clock"], clock())
        atomic(path, s)
    if interrupted:
        raise KeyboardInterrupt
    return row


def raw_response_links(text):
    class Links(HTMLParser):
        def handle_starttag(self, tag, attrs):
            for key, value in attrs:
                if key in ("href", "src") and value:
                    links.append(value)
    links = re.findall(r'https?://[^\s<>"\x27]+', text)
    Links().feed(text)
    return links


def response_links(text, base):
    valid = set()
    for link in raw_response_links(text):
        try:
            resolved = urllib.parse.urljoin(base, link)
            resolved = urllib.parse.urldefrag(resolved)[0]
            valid.add(url_key(resolved))
        except ValueError:
            continue
    return valid


def explicit_https_upgrade(original, target, allowed_hosts):
    """Match an explicit HTTPS equivalent; never fetch or alter path/query."""
    try:
        source, destination = urllib.parse.urlsplit(original), urllib.parse.urlsplit(target)
        if (source.scheme != "http" or destination.scheme != "https"
                or source.hostname not in allowed_hosts
                or source.hostname != destination.hostname
                or source.port not in (None, 80) or destination.port not in (None, 443)
                or source.username is not None or source.password is not None
                or destination.username is not None or destination.password is not None
                or source.path != destination.path or source.query != destination.query):
            return False
        # Signed/access-token links are outside this unauthenticated discovery
        # lane even if their hostname and requested upgrade otherwise match.
        for key, _ in urllib.parse.parse_qsl(source.query, keep_blank_values=True):
            key = key.lower().replace("-", "_")
            if key in ("key", "auth", "sig", "apikey", "session", "sessionid") or re.search(r"token|secret|password|credential|signature|authorization|api_key", key):
                return False
        return True
    except ValueError:
        return False


def add_query(path, response, url, purpose, max_bytes, clock=now, evidence_manifest=None):
    """Follow one literal official catalog link, never widen hosts or ceilings."""
    s = read(path)
    active(s, clock)
    evidence = read(evidence_manifest) if evidence_manifest else s
    evidence_hash = digest(evidence) if evidence_manifest else None
    if evidence_manifest and not any(r["manifest_sha256"] == evidence_hash and r["source_ids"] for r in s["reuses"]):
        raise ValueError("saved query evidence must first pass scoped manifest import")
    row = next(r for r in evidence["requests"] if r["id"] == response)
    c = next(c for c in s["plan"]["catalogs"] if c["id"] == row["catalog"])
    requested_url = url
    original_href = None
    if row["status"] == "OK":
        body = Path(row["body_path"]).read_bytes()
        if hashlib.sha256(body).hexdigest() != row["sha256"]:
            raise ValueError("response hash changed")
        text = html.unescape(body.decode("utf-8").replace("\\/", "/"))
        links = response_links(text, row["url"])
        original_href = next((link for link in raw_response_links(text)
                              if explicit_https_upgrade(link, requested_url, c["allowed_hosts"])), None)
    elif row.get("http_status") in (301, 302, 303, 307, 308) and row.get("location"):
        links = {url_key(urllib.parse.urljoin(row["url"], row["location"]))}
    else:
        raise ValueError("link provenance requires successful response or recorded redirect")
    url = url_key(url)
    if url not in links and original_href is None:
        raise ValueError("URL must be a literal HTTPS link in saved response")
    if urllib.parse.urlsplit(url).hostname not in c["allowed_hosts"]:
        raise ValueError("linked host was not preauthorized")
    queries = [q for c in s["plan"]["catalogs"] for q in c["queries"]]
    if len(queries) >= 12 or any(q["url"] == url for q in queries):
        raise ValueError("query ceiling or duplicate URL")
    if purpose not in ("metadata", "footprint", "sample") or not 0 < max_bytes <= (s["limits"]["bytes"] if purpose == "sample" else MAX_METADATA):
        raise ValueError("invalid query purpose/byte cap")
    q = dict(url=url, purpose=purpose, max_bytes=max_bytes)
    c["queries"].append(q)
    s["added_queries"].append(dict(query=q, response_id=response, response_sha256=row.get("sha256"), redirect_location=row.get("location"),
                                   original_href=original_href, link_normalization="explicit_http_to_https" if original_href else None,
                                   evidence_manifest_sha256=evidence_hash))
    # plan_sha256 pins the original authorization, not a replenishable plan.
    atomic(path, s)
    return q


def adapted(data, adapter):
    if adapter == "normalized":
        records = data.get("candidates")
        if not isinstance(records, list):
            raise ValueError("normalized input requires candidates list")
        return records
    if not isinstance(data.get("features"), list):
        raise ValueError("catalog response has no features array (HTML requires bounded annotation)")
    records = []
    for f in data["features"][:41]:
        if not isinstance(f, dict):
            records.append({"malformed": True})
            continue
        if adapter == "stac":
            p = f.get("properties") or {}
            assets = f.get("assets") or {}
            asset = next((a for a in assets.values() if isinstance(a, dict) and "data" in a.get("roles", [])), {})
            records.append(dict(publisher_id=f.get("id"), title=p.get("title", f.get("id")), bbox=f.get("bbox"), bbox_crs="CRS84",
                catalog_geometry=f.get("geometry"), crs=p.get("proj:code") or (f"EPSG:{p['proj:epsg']}" if p.get("proj:epsg") else None),
                resolution=p.get("gsd"), vertical_datum=p.get("vertical_datum"), z_units=p.get("z_units"),
                rights=p.get("license"), access_url=asset.get("href"), size_bytes=asset.get("file:size"),
                source_hash=asset.get("file:checksum"), format=asset.get("type"), source_date=p.get("datetime"),
                acquisition_date=p.get("start_datetime"), quality=p.get("quality"), limitations=p.get("limitations")))
        else:
            p, g = f.get("attributes") or {}, f.get("geometry") or {}
            spatial = g.get("spatialReference") or data.get("spatialReference") or {}
            wkid = spatial.get("latestWkid", spatial.get("wkid"))
            bounds = None
            if all(k in g for k in ("xmin", "ymin", "xmax", "ymax")):
                bounds = [g[k] for k in ("xmin", "ymin", "xmax", "ymax")]
            elif g.get("rings"):
                points = [xy for ring in g["rings"] for xy in ring]
                if points:
                    bounds = [min(p[0] for p in points), min(p[1] for p in points), max(p[0] for p in points), max(p[1] for p in points)]
            records.append(dict(publisher_id=p.get("NCEI_ID", p.get("id", p.get("OBJECTID"))), title=p.get("SURVEY_ID", p.get("title", p.get("name"))),
                bbox=bounds, bbox_crs="CRS84" if wkid == 4326 else f"EPSG:{wkid}" if wkid else None,
                catalog_geometry=g or None, crs=p.get("crs"), resolution=p.get("resolution"),
                vertical_datum=p.get("vertical_datum"), z_units=p.get("z_units"), rights=p.get("license"), access_url=p.get("DOWNLOAD_URL", p.get("url")),
                source_date=p.get("SURVEY_YEAR", p.get("source_date")), acquisition_date=p.get("START_TIME", p.get("acquisition_date")),
                format=p.get("format"), quality=p.get("quality"), limitations=p.get("limitations")))
    return records


def candidate(raw, s, row):
    if (not isinstance(raw, dict) or isinstance(raw.get("publisher_id"), bool)
            or not isinstance(raw.get("publisher_id"), (str, int))
            or not str(raw["publisher_id"]).strip()):
        raise ValueError("candidate requires stable original publisher_id")
    ident = f"{row['catalog']}:{raw['publisher_id']}"
    unknown = [k for k in ("crs", "resolution", "vertical_datum", "z_units", "rights", "size_bytes", "source_hash") if raw.get(k) in (None, "", "unknown")]
    rejection = []
    bounds = raw.get("bbox")
    if raw.get("bbox_crs") not in ("CRS84", "EPSG:4326"):
        rejection.append("unknown_or_non_geographic_bbox_crs")
    else:
        try:
            bbox(bounds)
            if not overlaps(bounds, s["bbox"]):
                rejection.append("no_bbox_overlap")
        except ValueError:
            rejection.append("malformed_bbox")
    access = raw.get("access_url")
    if access:
        try:
            access = url_key(access)
        except ValueError:
            rejection.append("invalid_access_url")
            access = None
    if not access:
        unknown.append("access_url")
    valid_crs = known_crs(raw.get("crs"))
    if not valid_crs and "crs" not in unknown:
        unknown.append("crs")
    ready = not rejection and access is not None and valid_crs
    criteria = dict(bbox_overlap=not rejection, native_crs=valid_crs,
        resolution=raw.get("resolution") not in (None, "", "unknown"),
        date=bool(raw.get("source_date")), quality=bool(raw.get("quality")),
        format=bool(raw.get("format")), access=bool(access),
        license=raw.get("rights") not in (None, "", "unknown"), citation=True,
        size=raw.get("size_bytes") is not None, hash=bool(raw.get("source_hash")),
        processing=bool(raw.get("processing_requirements")))
    return dict(source_id=ident, title=raw.get("title"), publisher_id=raw["publisher_id"], catalog_id=row["catalog"],
        provenance=dict(catalog_url=row["url"], response_sha256=row.get("sha256"), response_body_path=row.get("body_path"), request_id=row["id"], checked_at=row["stop_utc"]),
        field_evidence=raw.get("field_evidence", {}),
        metadata={k: raw.get(k) for k in ("crs", "resolution", "vertical_datum", "vertical_sign", "z_units", "rights", "size_bytes", "source_hash", "source_date", "acquisition_date", "format", "quality", "limitations", "processing_requirements", "task_fit")},
        extent=dict(bbox=bounds, bbox_crs=raw.get("bbox_crs"), catalog_geometry=raw.get("catalog_geometry"),
                    overlap_test="bbox_only", actual_data_support=None, actual_support_status="unverified"),
        access_url=access, cache=dict(path=None, sha256=None, status="not_acquired"),
        acquisition_recipe=dict(method="bounded HTTPS GET within explicitly authorized discovery sample scope; native mapping requires its own task", url=access, byte_limit_required=True),
        fitness=dict(kind="metadata-completeness triage only", known_criteria=criteria,
                     score=sum(criteria.values()), maximum=len(criteria),
                     actual_support="unknown", task_fit=raw.get("task_fit"),
                     ranking_limit="Not a scientific fitness/coverage rank; compare verified resolution/date/quality within task before selection"),
        next_action="inspect one bounded native terrain window and unresolved metadata" if ready else "resolve rejected extent, native CRS or access metadata",
        unknowns=unknown, rejection_reasons=rejection, alternate_of=raw.get("alternate_of"),
        terrain=dict(status="candidate_for_qualification" if ready else "blocked", blockers=rejection + ([] if ready else ["resolve CRS and access"]), accepted=False),
        habitat=dict(status="unassessed", accepted=False, blockers=["native measurements, support and habitat review required"]),
        render=dict(status="blocked", accepted=False, blockers=["completed reviewed v2 mapping handoff and paired imagery required"]),
        expires_at=stamp(timestamp(row["stop_utc"]) + 7 * 86400))


def ingest(path, response, adapter, annotation=None, clock=now):
    s = read(path)
    active(s, clock)
    row = next(r for r in s["requests"] if r["id"] == response)
    if row["status"] != "OK" or row.get("ingested"):
        raise ValueError("response must be successful and not previously ingested")
    body = Path(row["body_path"])
    if hashlib.sha256(body.read_bytes()).hexdigest() != row["sha256"]:
        raise ValueError("response hash changed")
    data = read(annotation or body)
    if annotation and (adapter != "normalized" or data.get("response_sha256") != row["sha256"]):
        raise ValueError("annotation must bind exact response hash and normalized adapter")
    records = adapted(data, adapter)
    limitations = []
    if data.get("exceededTransferLimit"):
        limitations.append("ArcGIS exceededTransferLimit: additional records not examined")
    if any(link.get("rel") == "next" for link in data.get("links", []) if isinstance(link, dict)):
        limitations.append("STAC next page exists: additional records not examined")
    rejected, duplicate = [], []
    for raw in records:
        if len(s["candidates"]) >= s["limits"]["candidates"]:
            rejected.append("candidate ceiling reached; remaining records not processed")
            break
        try:
            c = candidate(raw, s, row)
        except (ValueError, TypeError, KeyError) as exc:
            rejected.append(str(exc))
            continue
        if any(old["source_id"] == c["source_id"] for old in s["candidates"]):
            duplicate.append(c["source_id"])
            continue
        s["candidates"].append(c)
    row.update(ingested=True, malformed_records=rejected, duplicate_source_ids=duplicate,
               annotation_sha256=digest(data) if annotation else None, limitations=limitations)
    atomic(path, s)
    return s


def reuse(path, manifest_path, clock=now, scope_import=None):
    s, manifest = read(path), read(manifest_path)
    active(s, clock)
    validate_schema(manifest)
    required = ("schema", "method_revision", "source_revision", "policy_revision", "region", "bbox")
    transition = read(scope_import) if scope_import else None
    if transition:
        if (transition.get("manifest_sha256") != digest(manifest)
                or transition.get("new_plan_sha256") != s["plan_sha256"]
                or not transition.get("reason") or not isinstance(transition.get("source_ids"), list)
                or not set(transition["source_ids"]) <= {c["source_id"] for c in manifest.get("candidates", [])}):
            raise ValueError("scoped import must bind old manifest, new authorized plan and exact source IDs")
    elif manifest.get("plan_sha256") != s["plan_sha256"]:
        raise ValueError("manifest plan invalidated; explicit scoped import required")
    if any(manifest.get(k) != s[k] for k in required):
        raise ValueError("manifest source/policy/method/region/plan invalidated")
    if manifest.get("status") != "FINALIZED" or manifest.get("mapping_accepted") is not False or manifest.get("selected_slice_ids") != []:
        raise ValueError("reuse requires a finalized discovery-only manifest")
    if not isinstance(manifest.get("candidates"), list) or len(manifest["candidates"]) > s["limits"]["candidates"]:
        raise ValueError("manifest candidate ceiling")
    accepted = []
    for c in manifest.get("candidates", []):
        validate_candidate(c, manifest)
        if transition and c["source_id"] not in transition["source_ids"]:
            continue
        if timestamp(c["expires_at"]) <= clock() or timestamp(c["provenance"]["checked_at"]) > clock():
            continue
        if not c["rejection_reasons"] and c.get("access_url"):
            if not any(old["source_id"] == c["source_id"] for old in s["candidates"]):
                if len(s["candidates"]) >= s["limits"]["candidates"]:
                    break
                imported = dict(c)
                if imported.get("quality"):
                    from quality import validate_attachment
                    try:
                        validate_attachment(imported, s, clock=clock)
                    except (ValueError, OSError, KeyError) as exc:
                        imported["stale_quality"] = dict(attachment=imported.pop("quality"), reason=str(exc))
                s["candidates"].append(imported)
                accepted.append(c["source_id"])
    s["reuses"].append(dict(manifest_sha256=digest(manifest), source_ids=accepted, checked_at=stamp(clock()),
                            scope_import_sha256=digest(transition) if transition else None,
                            prior_plan_sha256=manifest["plan_sha256"], new_plan_sha256=s["plan_sha256"]))
    atomic(path, s)
    return {"reused": accepted, "cache_miss": not accepted}


def validate_schema(manifest):
    try:
        from jsonschema import Draft202012Validator
    except ImportError as exc:
        raise ValueError("manifest validation needs existing repository jsonschema runtime") from exc
    schema = read(Path(__file__).resolve().parent.parent / "references/source-manifest-v1.schema.json")
    errors = list(Draft202012Validator(schema).iter_errors(manifest))
    if errors:
        raise ValueError("invalid source manifest: " + errors[0].message)


def validate_candidate(c, state):
    """Validate portable metadata semantics; never trust saved readiness booleans."""
    p = c["provenance"]
    checked, expiry = timestamp(p["checked_at"]), timestamp(c["expires_at"])
    if not checked < expiry <= checked + 7 * 86400:
        raise ValueError("source TTL invalid")
    if c["catalog_id"] not in {catalog["id"] for catalog in state["plan"]["catalogs"]}:
        raise ValueError("source catalog outside original authorization")
    body = Path(p["response_body_path"])
    if body.stat().st_size > MAX_METADATA or hashlib.sha256(body.read_bytes()).hexdigest() != p["response_sha256"]:
        raise ValueError("source metadata proof missing or changed")
    raw = dict(c["metadata"], publisher_id=c["publisher_id"], title=c["title"],
               bbox=c["extent"]["bbox"], bbox_crs=c["extent"]["bbox_crs"],
               catalog_geometry=c["extent"].get("catalog_geometry"), access_url=c["access_url"],
               alternate_of=c["alternate_of"], field_evidence=c.get("field_evidence", {}))
    row = dict(catalog=c["catalog_id"], url=p["catalog_url"], id=p["request_id"], stop_utc=p["checked_at"], sha256=p["response_sha256"], body_path=str(body))
    expected = candidate(raw, state, row)
    for key in ("source_id", "extent", "terrain", "habitat", "render", "rejection_reasons", "fitness"):
        if c[key] != expected[key]:
            raise ValueError(f"invalid derived discovery field: {key}")
    if c["cache"]["status"] == "sample_acquired_unqualified":
        sample = Path(c["cache"]["path"])
        if sample.stat().st_size != c["cache"]["bytes"] or sample.stat().st_size > MAX_BYTES:
            raise ValueError("cached sample size changed")
        h = hashlib.sha256()
        with sample.open("rb") as stream:
            for block in iter(lambda: stream.read(65536), b""):
                h.update(block)
        if h.hexdigest() != c["cache"]["sha256"]:
            raise ValueError("cached sample hash changed")


def attach_samples(s):
    for c in s["candidates"]:
        for row in s["requests"]:
            if row["status"] == "OK" and row["purpose"] == "sample" and row["url"] == c["access_url"]:
                c["cache"] = dict(path=row["body_path"], sha256=row["sha256"], bytes=row["observed_body_bytes"], status="sample_acquired_unqualified", checked_at=row["stop_utc"])


def finalize(path, reason, clock=now):
    s = read(path)
    if s["status"] == "FINALIZED":
        return s
    # Do not signal stale PIDs. An interrupted parent can leave an owned child;
    # inspect under supervisor before finalizing rather than risking PID reuse.
    if any(r["status"] == "RUNNING" for r in s["requests"]):
        raise ValueError("unresolved request intent: inspect owned child and use recover after confirmed stop")
    if any(r["status"] == "RUNNING" for r in s.get("quality_runs", [])):
        raise ValueError("unresolved quality intent: recover after confirmed owned child stop")
    s.update(status="FINALIZED", stopped_at=stamp(clock()), stop_reason=reason)
    attach_samples(s)
    usable = [c["source_id"] for c in s["candidates"] if c["terrain"]["status"] == "candidate_for_qualification"]
    leads = [c["source_id"] for c in s["candidates"] if not c["rejection_reasons"] and c.get("access_url")]
    for c in s["candidates"]:
        if c.get("quality"):
            from quality import validate_attachment
            try:
                validate_attachment(c, s, clock=clock)
            except (ValueError, OSError, KeyError) as exc:
                c["stale_quality"] = dict(attachment=c.pop("quality"), reason=str(exc))
    planned = {q["url"] for c in s["plan"]["catalogs"] for q in c["queries"]}
    attempted = {r["url"] for r in s["requests"]}
    s["bounded_plan_finished"] = planned <= attempted
    s["discovery_complete"] = (s["bounded_plan_finished"] and
        all(r["status"] == "OK" and r.get("ingested") and not r.get("limitations") and not r.get("malformed_records") for r in s["requests"]))
    s["unattempted_queries"] = sorted(planned - attempted)
    s["failed_requests"] = [r["id"] for r in s["requests"] if r["status"] != "OK"]
    s["manifest_status"] = "PARTIAL" if leads else "BLOCKED"
    s["lead_source_ids"] = leads
    s["usable_source_ids"] = usable
    s["sample_observed_source_ids"] = [c["source_id"] for c in s["candidates"] if c.get("quality", {}).get("status") == "sample_observed"]
    s["mapping_accepted"] = False
    s["selected_slice_ids"] = []
    s["next_action"] = "qualify one bounded native terrain window" if usable else "resolve one recorded source blocker"
    validate_schema(s)
    atomic(path, s)
    atomic(Path(path).with_name(Path(path).stem + "-manifest.json"), s)
    return s


def recover(path, receipt):
    s, evidence = read(path), read(receipt)
    if evidence.get("checkpoint_sha256") != digest(s) or evidence.get("processes_stopped") is not True:
        raise ValueError("recovery receipt must bind checkpoint and confirmed stopped processes")
    for r in s["requests"] + s.get("quality_runs", []):
        if r["status"] == "RUNNING":
            if r.get("pid"):
                try:
                    os.kill(r["pid"], 0)
                except ProcessLookupError:
                    pass
                else:
                    raise ValueError("recorded PID still exists; inspect, never kill a stale PID blindly")
            r["status"] = "INTERRUPTED_UNCERTAIN"
            r["recovery_receipt_sha256"] = digest(evidence)
    atomic(path, s)
    return s


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "_fetch":
        # Independent child ceiling survives loss of the supervising parent.
        # Absolute UTC includes interpreter startup; parent adds monotonic guard.
        remaining = min(float(sys.argv[4]), float(sys.argv[7]) - time.time())
        if remaining <= 0:
            atomic(sys.argv[6], dict(status="TIMEOUT", observed_body_bytes=0))
            return
        def expired(*_):
            raise TimeoutError("independent child deadline")
        signal.signal(signal.SIGALRM, expired)
        signal.setitimer(signal.ITIMER_REAL, remaining)
        fetch(sys.argv[2], int(sys.argv[3]), float(sys.argv[4]), sys.argv[5], sys.argv[6])
        return
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("checkpoint", type=Path)
    sub = p.add_subparsers(dest="command", required=True)
    a = sub.add_parser("init")
    a.add_argument("--region", required=True)
    a.add_argument("--bbox", type=float, nargs=4, required=True)
    a.add_argument("--plan", required=True)
    a.add_argument("--source-revision", required=True)
    a.add_argument("--policy-revision", required=True)
    a.add_argument("--start-utc")
    a.add_argument("--byte-limit", type=int, default=MAX_BYTES)
    a.add_argument("--profile", choices=("discovery30", "acquisition60"), default="discovery30")
    a = sub.add_parser("request")
    a.add_argument("--catalog", required=True)
    a.add_argument("--url", required=True)
    a.add_argument("--max-bytes", type=int)
    a.add_argument("--seconds", type=float, default=60)
    a.add_argument("--changed")
    a = sub.add_parser("ingest")
    a.add_argument("--response", type=int, required=True)
    a.add_argument("--adapter", choices=("arcgis", "stac", "normalized"), required=True)
    a.add_argument("--annotation")
    a = sub.add_parser("add-query")
    a.add_argument("--response", type=int, required=True)
    a.add_argument("--url", required=True)
    a.add_argument("--purpose", choices=("metadata", "footprint", "sample"), required=True)
    a.add_argument("--max-bytes", type=int, required=True)
    a.add_argument("--evidence-manifest")
    a = sub.add_parser("reuse")
    a.add_argument("--manifest", required=True)
    a.add_argument("--scope-import")
    a = sub.add_parser("finalize")
    a.add_argument("--reason", required=True)
    a = sub.add_parser("recover")
    a.add_argument("--receipt", required=True)
    sub.add_parser("status")
    sub.add_parser("validate")
    a = p.parse_args()
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(InterruptedError("terminated")))
    signal.signal(signal.SIGHUP, lambda *_: (_ for _ in ()).throw(InterruptedError("hangup")))
    with locked(a.checkpoint):
        if a.command == "init":
            result = init(a.checkpoint, a.region, a.bbox, read(a.plan), a.source_revision, a.policy_revision, a.start_utc, byte_limit=a.byte_limit, profile=a.profile)
        elif a.command == "request":
            result = request(a.checkpoint, a.catalog, a.url, a.max_bytes, a.seconds, a.changed)
        elif a.command == "ingest":
            result = ingest(a.checkpoint, a.response, a.adapter, a.annotation)
        elif a.command == "add-query":
            result = add_query(a.checkpoint, a.response, a.url, a.purpose, a.max_bytes, evidence_manifest=a.evidence_manifest)
        elif a.command == "reuse":
            result = reuse(a.checkpoint, a.manifest, scope_import=a.scope_import)
        elif a.command == "finalize":
            result = finalize(a.checkpoint, a.reason)
        elif a.command == "recover":
            result = recover(a.checkpoint, a.receipt)
        elif a.command == "validate":
            result = read(a.checkpoint)
            validate_schema(result)
            for c in result["candidates"]:
                validate_candidate(c, result)
            result = {"valid": True, "schema": VERSION, "mapping_accepted": False}
        else:
            result = read(a.checkpoint)
            result = {k: result.get(k) for k in ("status", "start_utc", "discovery_cutoff_utc", "deadline_utc", "budget_charged_bytes", "observed_body_bytes", "limits", "usable_source_ids", "model_usage")}
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, OSError, StopIteration) as exc:
        print(f"STOP: {exc}", file=sys.stderr)
        sys.exit(2)
