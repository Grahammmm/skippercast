"""One-open cell-level mask-topology pre-scan of the pinned SC-5 partial windows.

SC-5b (G option A; budget: signed amendment v7, ONE advance-charged cached-BAG
open of 36,757,568 B, no refund). The partial-support policy treats mask-invalid
native cells as unsupported nodata, and the governed run wants holes in its
cores (check_terrain_acceptance.py --require-holes). A count of mask-invalid
cells is NOT proof of an enclosed hole: a border-connected notch counts the same.
This tool reads the paired validity masks of the four EXACT pinned windows from
ONE opened dataset and records, per window, every unsupported cell (as row runs)
and its connected components under 4- and 8-neighbour rules, each tagged
enclosed or border-connected.

Subcommands
  plan    source-free: bind the signed amendment to the reviewed charge-ledger
          head, check the read plan, the output reservation and the absent output
          root, and print the exact scan command. Never opens or stats the source.
  scan    the ONE charged open (later admitted card only; never on CI): no source
          re-hash, no second open, no retries, no alternate windows, search or
          relocation, no h5py/metadata pass. Writes one bounded JSON receipt.
  verify  source-free: recompute every component and the --require-holes gate
          from the receipt's row runs alone.

Nothing here admits, accepts or publishes a window. The receipt is a
machine-valid observation that still needs independent review; native quality,
sample quality and scientific acceptance stay unverified.
"""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

SCHEMA = "coastal-four128-mask-topology-prescan-v1"
REVIEW_SCHEMA = "coastal-four128-mask-topology-review-v1"
RUN_TAG = "20261020p1"
SOURCE_SHA256 = "0cb528795f939e9238e9b11f52279940a2365b2b4b6f52d9f9db8aea82b235fa"  # recorded, never recomputed
SOURCE_BYTES = 36757568
SOURCE_RELATIVE = "repo/var/seafloor/cache/" + SOURCE_SHA256 + "/source.bag"
GRID_SHAPE = (10495, 10034)  # rows, cols
AFFINE = (2, 0, 721091, 0, -2, 3826155)
SIDE = 128
# Fixed decisions (t_689254ff); cross-checked against the shared pins at import of
# the project code (profiles.PARTIAL_WINDOWS, ordered_trial.PARTIAL_BOUNDS).
WINDOWS = ([4402, 3872, 128, 128], [3762, 3744, 128, 128], [3634, 3616, 128, 128], [4018, 3488, 128, 128])
BOUNDS = (728359, 3818155, 730151, 3819179)
# Retained count-only comparison evidence (hole-candidates.json 024d474a...): NOT expected output.
COUNT_ONLY_MASK_INVALID = (14, 4, 299, 18)
OUTPUT_NAME = "sc5-partial-" + RUN_TAG + "-prescan"
RECEIPT_NAME = "mask-topology-receipt.json"
RECEIPT_MAX_BYTES = 1048576  # signed retained prescan_reservation_bytes
MAX_RUNS_PER_WINDOW = 4096
MAX_COMPONENTS_PER_WINDOW = 1024
LABELS = "ABCD"
# --require-holes intent, fixed here so the gate is reviewable rather than chosen
# after the observation: every window keeps >= 1 unsupported cell (the partial
# policy's minimum_unsupported_pairs and terrain --require-holes per core) and the
# policy's 8,192-pair supported floor, and at least one window has an ENCLOSED
# unsupported region under the 4-neighbour rule that check_terrain_acceptance.topology
# uses for gaps. Border-connected notches alone do not satisfy it.
REQUIRE_HOLES = dict(minimum_unsupported_cells_per_window=1, minimum_supported_cells_per_window=8192,
                     minimum_enclosed_regions_4_total=1,
                     connectivity="4-neighbour unsupported regions (check_terrain_acceptance.topology)")
# Envelope the scan must already run inside (systemd-run transient unit).
ENVELOPE = {"memory.max": 1073741824, "pids.max": 32}
UNIT_PROPERTIES = ("RuntimeMaxSec=180", "MemoryMax=1073741824", "MemorySwapMax=0", "CPUQuota=200%",
                   "TasksMax=32", "LimitFSIZE=2097152", "KillMode=control-group", "KillSignal=SIGKILL")

OPENS = []  # every source open made by this process


def encoded(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


# ---------------------------------------------------------------- pure topology

def runs_from_mask(unsupported):
    """Row runs [row, col_start, length] of True cells, row-major. Accepts nested lists or arrays."""
    runs = []
    for r, row in enumerate(unsupported):
        row = [bool(v) for v in row]
        c = 0
        while c < len(row):
            if row[c]:
                start = c
                while c < len(row) and row[c]:
                    c += 1
                runs.append([r, start, c - start])
            else:
                c += 1
    return runs


def mask_from_runs(runs, side=SIDE):
    grid = [[False] * side for _ in range(side)]
    previous = None
    for run in runs:
        if (not isinstance(run, list) or len(run) != 3 or any(type(v) is not int for v in run)):
            raise ValueError("row run must be three integers")
        r, c, n = run
        if not (0 <= r < side and 0 <= c < side and 1 <= n <= side - c):
            raise ValueError("row run outside the window")
        if previous is not None and (r, c) <= previous:
            raise ValueError("row runs must be strictly row-major")
        if previous is not None and r == previous[0] and c <= previous[2]:
            raise ValueError("row runs must not touch or overlap")
        for k in range(c, c + n):
            grid[r][k] = True
        previous = (r, c, c + n)
    return grid


def components(unsupported, *, diagonal):
    """Connected unsupported regions; each with cells, bbox and enclosed/border flag.

    A region is enclosed when none of its cells lies on the window edge: every
    neighbour outside it is then a supported cell inside the window."""
    height = len(unsupported)
    width = len(unsupported[0]) if height else 0
    seen = [[False] * width for _ in range(height)]
    steps = [(-1, 0), (1, 0), (0, -1), (0, 1)]
    if diagonal:
        steps += [(-1, -1), (-1, 1), (1, -1), (1, 1)]
    found = []
    for r0 in range(height):
        for c0 in range(width):
            if not unsupported[r0][c0] or seen[r0][c0]:
                continue
            stack = [(r0, c0)]
            seen[r0][c0] = True
            cells = 0
            rows, cols = [r0, r0], [c0, c0]
            border = False
            while stack:
                r, c = stack.pop()
                cells += 1
                rows = [min(rows[0], r), max(rows[1], r)]
                cols = [min(cols[0], c), max(cols[1], c)]
                if r in (0, height - 1) or c in (0, width - 1):
                    border = True
                for dr, dc in steps:
                    rr, cc = r + dr, c + dc
                    if 0 <= rr < height and 0 <= cc < width and unsupported[rr][cc] and not seen[rr][cc]:
                        seen[rr][cc] = True
                        stack.append((rr, cc))
            found.append(dict(cells=cells, row_range=rows, col_range=cols,
                              touches_border=border, enclosed=not border))
    found.sort(key=lambda d: (d["row_range"][0], d["col_range"][0], -d["cells"]))
    return found


def summary(regions):
    enclosed = [d for d in regions if d["enclosed"]]
    border = [d for d in regions if not d["enclosed"]]
    return dict(regions=len(regions), enclosed_regions=len(enclosed), border_regions=len(border),
                enclosed_cells=sum(d["cells"] for d in enclosed), border_cells=sum(d["cells"] for d in border),
                largest_enclosed_cells=max((d["cells"] for d in enclosed), default=0))


def window_topology(unsupported, *, side=SIDE):
    """Bounded per-window record reproducible from its row runs alone."""
    if len(unsupported) != side or any(len(row) != side for row in unsupported):
        raise ValueError("exact square window mask required")
    runs = runs_from_mask(unsupported)
    if len(runs) > MAX_RUNS_PER_WINDOW:
        raise ValueError("unsupported row runs exceed the bounded receipt")
    grid = mask_from_runs(runs, side)
    four, eight = components(grid, diagonal=False), components(grid, diagonal=True)
    if max(len(four), len(eight)) > MAX_COMPONENTS_PER_WINDOW:
        raise ValueError("unsupported components exceed the bounded receipt")
    count = sum(n for _, _, n in runs)
    return dict(cells=side * side, unsupported_cells=count, supported_cells=side * side - count,
                unsupported_row_runs=runs, components_4=four, components_8=eight,
                topology_4=summary(four), topology_8=summary(eight),
                whole_window_unsupported=count == side * side)


def require_holes(windows):
    """Evaluate REQUIRE_HOLES over per-window topology records; returns (met, reasons)."""
    reasons = []
    if len(windows) != len(WINDOWS):
        reasons.append("exactly four windows required")
    low = [w["label"] for w in windows if w["unsupported_cells"] < REQUIRE_HOLES["minimum_unsupported_cells_per_window"]]
    if low:
        reasons.append("windows without an unsupported cell: " + ",".join(low))
    thin = [w["label"] for w in windows if w["supported_cells"] < REQUIRE_HOLES["minimum_supported_cells_per_window"]]
    if thin:
        reasons.append("windows below the partial policy's supported-pair floor: " + ",".join(thin))
    enclosed = sum(w["topology_4"]["enclosed_regions"] for w in windows)
    if enclosed < REQUIRE_HOLES["minimum_enclosed_regions_4_total"]:
        reasons.append("no enclosed 4-neighbour unsupported region in any window (border notches only)")
    return not reasons, reasons


def verify_receipt(doc):
    """Source-free: recompute every window's components and the gate from row runs."""
    if doc.get("schema") != SCHEMA or doc.get("run_tag") != RUN_TAG:
        raise ValueError("mask-topology receipt schema/run tag differs")
    if [w["window"] for w in doc.get("windows", [])] != [list(w) for w in WINDOWS]:
        raise ValueError("receipt windows differ from the pinned partial windows")
    if doc.get("native_bounds") != list(BOUNDS):
        raise ValueError("receipt native bounds differ from the pinned partial bounds")
    if doc["source"].get("opens") != 1 or doc["source"].get("sha256_recomputed") is not False:
        raise ValueError("receipt is not a one-open, no-rehash observation")
    recomputed = []
    for label, w in zip(LABELS, doc["windows"]):
        if w.get("label") != label:
            raise ValueError("window labels must be A,B,C,D in pinned order")
        again = window_topology(mask_from_runs(w["unsupported_row_runs"]))
        for key in ("unsupported_cells", "supported_cells", "components_4", "components_8",
                    "topology_4", "topology_8", "whole_window_unsupported"):
            if again[key] != w[key]:
                raise ValueError("receipt " + key + " differs from its row runs: " + label)
        recomputed.append(dict(again, label=label))
    met, reasons = require_holes(recomputed)
    if doc["require_holes"] != dict(REQUIRE_HOLES, met=met, reasons=reasons):
        raise ValueError("receipt --require-holes evaluation differs from recomputation")
    return dict(met=met, reasons=reasons,
                per_window=[dict(label=w["label"], unsupported=w["unsupported_cells"],
                                 enclosed_4=w["topology_4"]["enclosed_regions"],
                                 border_4=w["topology_4"]["border_regions"],
                                 enclosed_8=w["topology_8"]["enclosed_regions"]) for w in recomputed])


def validate_review(review, receipt_raw, *, receipt_author="opus-coder"):
    """Independent review of a receipt: exact bytes, different model/profile, gate met."""
    receipt = json.loads(receipt_raw)
    checked = verify_receipt(receipt)
    reviewer = review.get("reviewer") or {}
    if (review.get("schema") != REVIEW_SCHEMA or review.get("status") != "ACCEPTED_TOPOLOGY_OBSERVATION_ONLY"
            or review.get("independent") is not True
            or review.get("receipt", {}).get("sha256") != digest(receipt_raw)
            or review.get("receipt", {}).get("bytes") != len(receipt_raw)
            or not reviewer.get("profile") or reviewer.get("profile") == receipt_author
            or not reviewer.get("model") or "opus" in reviewer["model"].lower()
            or review.get("require_holes_met") is not True or checked["met"] is not True
            or review.get("scientific_acceptance") is not False or review.get("holds") != []):
        raise ValueError("independently reviewed --require-holes pre-scan receipt required")
    return checked


# ---------------------------------------------------------------- source-free plan

def project_root():
    return Path.home() / "skippercast-data" / "2026-10-07-pge-south"


def code_root():
    return Path(__file__).resolve().parents[2]


def _ledger_limits(raw):
    """budget_limits_bytes of the reviewed charge ledger (raw SHA must be its head)."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import coastal_four128_resources as resources
    return resources.budget_limits_bytes(raw)


def amendment_reference(path):
    """The signed amendment's raw bytes must be the reviewed charge-ledger head."""
    p = Path(path)
    if p.is_symlink() or not p.is_file() or p.stat().st_size > 2_000_000:
        raise ValueError("bounded regular signed amendment file required")
    raw = p.read_bytes()
    limits = _ledger_limits(raw)
    doc = json.loads(raw)
    plan = doc.get("read_plan") or {}
    retained = doc.get("retained_output") or {}
    charge = doc["source"].get("sc5_geometry_prescan_charged_bytes")
    if (doc.get("run_tag") != RUN_TAG or plan.get("pre_scan_opens") != 1 or plan.get("retries") != 0
            or plan.get("downloads") != 0 or plan.get("network_requests") != 0
            or plan.get("extra_source_identity_reads") != 0
            or charge != SOURCE_BYTES or plan.get("pre_scan_reservation_bytes") != charge
            or retained.get("prescan_reservation_bytes") != RECEIPT_MAX_BYTES
            or (doc.get("cash") or {}).get("maximum") != 0):
        raise ValueError("signed amendment does not reserve exactly one precharged pre-scan open")
    return dict(path=str(p), sha256=digest(raw), bytes=len(raw), revision=doc["amendment_revision"],
                sc5_geometry_prescan_charged_bytes=charge, charged_in_advance=True, refunds=False,
                remaining_run_allowance_bytes=limits["source_limit_bytes"] - limits["source_prior_bytes"],
                run_admissions=plan.get("run_admissions"),
                retained_prescan_reservation_bytes=retained["prescan_reservation_bytes"], limits=limits)


def output_root(project):
    out = Path(project) / "outputs" / OUTPUT_NAME
    if out.exists() or out.is_symlink():
        raise ValueError("pre-scan output root already exists; preserve it, never rerun")
    return out


def pinned_geometry():
    """Cross-check the fixed decisions against the shared authority pins."""
    sys.path.insert(0, str(code_root() / "src"))
    from skippercast.coastal.authenticated_v1.profiles import PARTIAL_WINDOWS
    from skippercast.coastal.coordinator.ordered_trial import PARTIAL_BOUNDS
    if PARTIAL_WINDOWS != [list(w) for w in WINDOWS] or PARTIAL_BOUNDS != list(BOUNDS):
        raise ValueError("fixed pre-scan windows/bounds differ from the shared partial pins")
    x0 = min(AFFINE[2] + AFFINE[0] * w[0] for w in WINDOWS)
    x1 = max(AFFINE[2] + AFFINE[0] * (w[0] + w[2]) for w in WINDOWS)
    y0 = min(AFFINE[5] + AFFINE[4] * (w[1] + w[3]) for w in WINDOWS)
    y1 = max(AFFINE[5] + AFFINE[4] * w[1] for w in WINDOWS)
    if [x0, y0, x1, y1] != list(BOUNDS):
        raise ValueError("pinned bounds are not the union of the pinned windows")
    return True


def plan(amendment, *, project=None, head=None):
    """Everything that needs no source access. Never opens or stats the source."""
    project = Path(project) if project else project_root()
    pinned_geometry()
    reference = amendment_reference(amendment)
    out = output_root(project)
    source = project / SOURCE_RELATIVE
    python = sys.executable
    scan = [python, "-I", "-B", str(Path(__file__).resolve()), "scan", "--amendment", reference["path"],
            "--code-head", head or "<reviewed merged head>"]
    unit = ["/usr/bin/systemd-run", "--user", "--wait", "--pipe", "--collect",
            "--unit=skippercast-sc5-mask-prescan-" + RUN_TAG + ".service",
            *["--property=" + p for p in UNIT_PROPERTIES],
            "--setenv=PROJ_NETWORK=OFF", "--setenv=GDAL_NUM_THREADS=1", "--setenv=GDAL_PAM_ENABLED=NO",
            "--setenv=CPL_VSIL_CURL_ALLOWED_EXTENSIONS=none", "--setenv=GDAL_HTTP_TIMEOUT=1",
            "--property=WorkingDirectory=" + str(code_root())]
    return dict(schema="coastal-four128-mask-topology-plan-v1", run_tag=RUN_TAG, source_opened=False,
                source_path=str(source), source_recorded_sha256=SOURCE_SHA256, source_recorded_bytes=SOURCE_BYTES,
                windows=[list(w) for w in WINDOWS], native_bounds=list(BOUNDS), output_root=str(out),
                receipt=str(out / RECEIPT_NAME), receipt_max_bytes=RECEIPT_MAX_BYTES, amendment=reference,
                require_holes=REQUIRE_HOLES, command=unit + scan,
                limits=["one source open; no re-hash, retries, alternate windows, search or relocation",
                        "no h5py/metadata pass, no network, no downloads, $0",
                        "writes only the bounded receipt; never a managed mission"])


# ---------------------------------------------------------------- the one open (not run on CI)

def resource_envelope(read=lambda p: Path(p).read_text()):
    membership = read("/proc/self/cgroup").strip()
    if not membership.startswith("0::/") or "\n" in membership or ".." in Path(membership[3:]).parts:
        raise ValueError("unified cgroup membership required")
    leaf = "/sys/fs/cgroup" + membership[3:]
    readings = {k: read(leaf + "/" + k).strip() for k in ENVELOPE}
    for key, ceiling in ENVELOPE.items():
        if not readings[key].isdigit() or int(readings[key]) > ceiling:
            raise ValueError("pre-scan must run inside the bounded unit: " + key + "=" + readings[key])
    return dict(cgroup=membership[3:], readings=readings)


def clean_head(head, run=subprocess.run):
    actual = run(["git", "-C", str(code_root()), "rev-parse", "HEAD"], check=True, capture_output=True,
                 text=True).stdout.strip()
    dirty = run(["git", "-C", str(code_root()), "status", "--porcelain"], check=True, capture_output=True,
                text=True).stdout.strip()
    if actual != head or dirty:
        raise ValueError("pre-scan must run from the exact clean reviewed head")
    return actual


def open_source(path, opener):
    """The single open of the source BAG; a second call refuses before opening."""
    OPENS.append(str(path))
    if len(OPENS) != 1:
        raise RuntimeError("the source BAG may be opened once per invocation")
    return opener(str(path))


def read_windows(dataset):
    """Paired validity masks for the four exact windows from one opened dataset."""
    import numpy as np
    from rasterio.windows import Window
    if dataset.driver != "BAG" or dataset.count != 2 or (dataset.height, dataset.width) != GRID_SHAPE:
        raise ValueError("expected the two-band regular four128 BAG grid")
    if [float(v) for v in list(dataset.transform)[:6]] != [float(v) for v in AFFINE]:
        raise ValueError("BAG affine differs from the four128 grid")
    nodata = tuple(dataset.nodatavals)
    records = []
    for label, (col, row, w, h) in zip(LABELS, WINDOWS):
        window = Window(col, row, w, h)
        elevation = dataset.read(1, window=window, masked=True)
        uncertainty = dataset.read(2, window=window, masked=True)
        if elevation.shape != (SIDE, SIDE) or uncertainty.shape != (SIDE, SIDE):
            raise ValueError("partial window read")
        e_mask, u_mask = np.ma.getmaskarray(elevation), np.ma.getmaskarray(uncertainty)
        unsupported = e_mask | u_mask  # partial policy: mask-invalid cells only
        e, u = elevation.filled(np.nan), uncertainty.filled(np.nan)
        valid = ~unsupported
        nonfinite = valid & ~(np.isfinite(e) & np.isfinite(u))
        sentinel = np.zeros_like(valid)
        if nodata[0] is not None and np.isfinite(nodata[0]):
            sentinel |= valid & (e == nodata[0])
        if nodata[1] is not None and np.isfinite(nodata[1]):
            sentinel |= valid & (u == nodata[1])
        topology = window_topology(unsupported.tolist())
        records.append(dict(label=label, window=[col, row, w, h],
                            elevation_mask_invalid=int(e_mask.sum()), uncertainty_mask_invalid=int(u_mask.sum()),
                            # Mask-valid but not a usable pair would HOLD the partial policy; recorded, not judged.
                            mask_valid_raw_nonfinite=int(nonfinite.sum()), mask_valid_sentinel=int(sentinel.sum()),
                            **topology))
    return records, dict(nodata=list(nodata), shape=[dataset.height, dataset.width],
                         transform=list(dataset.transform)[:6], driver=dataset.driver)


def build_receipt(records, header, *, started, finished, reference, head, envelope, source):
    met, reasons = require_holes(records)
    comparison = [dict(label=r["label"], count_only_mask_invalid=n, observed_unsupported=r["unsupported_cells"],
                       equal=r["unsupported_cells"] == n) for r, n in zip(records, COUNT_ONLY_MASK_INVALID)]
    script = Path(__file__).resolve()
    return dict(
        schema=SCHEMA, run_tag=RUN_TAG, status="TOPOLOGY_RECORDED_REVIEW_REQUIRED",
        started_utc=started, finished_utc=finished, code_head=head,
        script=dict(path="research/scripts/coastal_four128_mask_topology.py", sha256=digest(script.read_bytes())),
        source=dict(path=str(source), recorded_sha256=SOURCE_SHA256, recorded_bytes=SOURCE_BYTES,
                    sha256_recomputed=False, opens=len(OPENS), metadata_pass=False,
                    access="one rasterio/GDAL BAG open; two masked band reads per pinned window"),
        budget=dict(reference, this_open_bytes=SOURCE_BYTES,
                    meaning="charged in advance by signed amendment v7; no refund; not a runtime admission"),
        resource_envelope=envelope, grid=dict(shape=list(GRID_SHAPE), affine=list(AFFINE), header=header),
        windows=records, native_bounds=list(BOUNDS), count_only_comparison=comparison,
        require_holes=dict(REQUIRE_HOLES, met=met, reasons=reasons),
        network_requests=0, downloads=0, cash_usd=0, managed_mission_writes=0, retries=0,
        machine_valid_is_not_acceptance=True, scientific_acceptance=False, native_quality_accepted=False,
        publication=False, execution_authorized=False,
        evidence_scope="Cell-level mask topology of four pinned windows only; native quality, depth and "
                       "uncertainty UNVERIFIED; independent review required before any admission.")


def write_receipt(out, document):
    raw = encoded(document)
    if len(raw) > RECEIPT_MAX_BYTES:
        raise ValueError("receipt exceeds the signed 1 MiB retained reservation")
    out.mkdir(parents=True, exist_ok=False)
    path = out / RECEIPT_NAME
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o444)
    with os.fdopen(fd, "wb") as handle:
        handle.write(raw)
    return path, digest(raw), len(raw)


def scan(amendment, head, *, project=None, opener=None, envelope=resource_envelope, git=clean_head):
    import contextlib
    project = Path(project) if project else project_root()
    pinned_geometry()
    reference = amendment_reference(amendment)
    out = output_root(project)
    source = project / SOURCE_RELATIVE
    checked_head = git(head)
    limits = envelope()
    with contextlib.ExitStack() as stack:
        if opener is None:
            import rasterio
            stack.enter_context(rasterio.Env(GDAL_PAM_ENABLED="NO", GDAL_NUM_THREADS="1",
                                             CPL_VSIL_CURL_ALLOWED_EXTENSIONS="none"))
            opener = lambda path: rasterio.open(path, driver="BAG")  # noqa: E731
        started = dt.datetime.now(dt.timezone.utc).isoformat()
        dataset = stack.enter_context(contextlib.closing(open_source(source, opener)))
        records, header = read_windows(dataset)
    finished = dt.datetime.now(dt.timezone.utc).isoformat()
    document = build_receipt(records, header, started=started, finished=finished, reference=reference,
                             head=checked_head, envelope=limits, source=source)
    verify_receipt(document)
    path, sha, size = write_receipt(out, document)
    return dict(receipt=str(path), sha256=sha, bytes=size, opens=len(OPENS), require_holes=document["require_holes"],
                status=document["status"])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="action", required=True)
    p = sub.add_parser("plan", help="source-free plan; never opens the source")
    p.add_argument("--amendment", required=True)
    p.add_argument("--code-head")
    s = sub.add_parser("scan", help="the ONE charged open (admitted pre-scan card only)")
    s.add_argument("--amendment", required=True)
    s.add_argument("--code-head", required=True)
    v = sub.add_parser("verify", help="source-free recomputation from a receipt")
    v.add_argument("receipt")
    args = parser.parse_args(argv)
    if args.action == "plan":
        out = plan(args.amendment, head=args.code_head)
    elif args.action == "verify":
        p = Path(args.receipt)
        if p.is_symlink() or p.stat().st_size > RECEIPT_MAX_BYTES:
            raise ValueError("bounded regular receipt required")
        raw = p.read_bytes()
        out = dict(receipt=str(p), sha256=digest(raw), **verify_receipt(json.loads(raw)))
    else:
        out = scan(args.amendment, args.code_head)
    print(json.dumps(out, sort_keys=True))
    return 0 if args.action != "verify" or out["met"] else 2


if __name__ == "__main__":
    sys.exit(main())
