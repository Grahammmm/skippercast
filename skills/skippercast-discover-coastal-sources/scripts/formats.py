"""Pinned format-reader preflight and bounded GSF/gzip integration."""
import gzip
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import discover as d

MAX_EXPANDED = 128_000_000
MAX_RATIO = 200
MAX_READER_OUTPUT = 1_000_000


def preflight(reader_receipt):
    from quality import file_hash
    if not reader_receipt:
        return dict(status="blocked", blocker="GSF requires a pinned upstream-library adapter receipt", format="gsf")
    r = d.read(reader_receipt)
    if r.get("schema") != "gsf-reader-v1" or r.get("gsf_version") != "3.11" or not r.get("source_revision"):
        raise ValueError("unsupported GSF reader receipt/version")
    path = Path(r["executable"])
    if not path.is_absolute() or not os.access(path, os.X_OK) or file_hash(path) != r["sha256"]:
        raise ValueError("pinned reader binary hash/path mismatch")
    adapter = Path(__file__).with_name("gsf_probe.c")
    if file_hash(adapter) != r["adapter_sha256"]:
        raise ValueError("reader adapter source revision mismatch; rebuild before use")
    return dict(status="ready", format="gsf", reader=r, reader_receipt_sha256=file_hash(reader_receipt),
                limits=dict(expanded_bytes=MAX_EXPANDED, expansion_ratio=MAX_RATIO, records=10000, pings=2000, beams=1000000,
                            output_bytes=MAX_READER_OUTPUT),
                scope="bounded sequential GSF API observations; navigation is not sounding support")


def inflate(source, output, deadline, cap=MAX_EXPANDED, ratio=MAX_RATIO):
    """Only gzip, no archive member paths/extraction; fail closed at either cap."""
    size = Path(source).stat().st_size
    limit = min(cap, max(1, size) * ratio)
    count = 0
    try:
        with gzip.open(source, "rb") as inp, Path(output).open("xb") as out:
            while count < limit:
                if time.monotonic() >= deadline:
                    raise TimeoutError("gzip expansion deadline")
                block = inp.read(min(65536, limit-count))
                if not block:
                    return count
                out.write(block)
                count += len(block)
            raise ValueError("gzip expanded-byte or ratio ceiling reached; no extra-byte probe")
    except BaseException:
        Path(output).unlink(missing_ok=True)
        raise


def inspect_gsf(receipt, sample, reader_receipt, scratch, deadline, max_file=64_000_000):
    from quality import file_hash
    result = preflight(reader_receipt)
    if result["status"] != "ready":
        receipt["status"]="reader_blocked"
        receipt["blockers"].append(result["blocker"])
        receipt["usefulness"]["private_terrain"]="reader_blocked"
        return receipt
    receipt["reader"] = result
    sample = Path(sample)
    if file_hash(sample, max_file, deadline=deadline) != receipt["sample"]["sha256"]:
        raise ValueError("GSF sample hash mismatch")
    scratch = Path(scratch)
    scratch.mkdir(exist_ok=True)
    with sample.open("rb") as stream:
        magic = stream.read(2)
    native = sample
    if magic == b"\x1f\x8b":
        native = scratch / "expanded.gsf"
        expanded = inflate(sample, native, deadline)
        receipt["decompression"] = dict(format="gzip", bytes=expanded, sha256=file_hash(native,MAX_EXPANDED,deadline),
                                         ratio_limit=MAX_RATIO, output_byte_limit=MAX_EXPANDED)
    argv = [result["reader"]["executable"], str(native), "10000", "2000", "1000000", *map(str,receipt["assigned_bbox"])]
    out, err = scratch / "reader.json", scratch / "reader.stderr"
    remaining = deadline-time.monotonic()
    if remaining <= 0:
        raise TimeoutError("GSF reader deadline")
    # The reader inherits resource limits and the owned process group, not the
    # worker's alarm across exec. Its wait is bounded below; parent killpg also
    # reaps descendants after worker exit. External cgroup bounds parent failure.
    import resource
    def bound_output():
        resource.setrlimit(resource.RLIMIT_FSIZE,(MAX_READER_OUTPUT,MAX_READER_OUTPUT))
    with out.open("xb") as stdout, err.open("xb") as stderr:
        process=subprocess.Popen(argv,stdout=stdout,stderr=stderr,preexec_fn=bound_output)
        try:
            process.wait(timeout=remaining)
        finally:
            if process.poll() is None:
                process.kill(); process.wait()
    if process.returncode != 0:
        try:
            error=d.read(out).get("gsf_error","unknown")
        except (ValueError,OSError):
            error="unreadable bounded output"
        raise ValueError(f"GSF API decode failed (exit {process.returncode}, gsf_error {error}); no error-loop retry")
    return apply_gsf_summary(receipt, d.read(out))


def apply_gsf_summary(receipt, data):
    """Classify bounded reader evidence without reopening or decoding a sample."""
    if data.get("schema") != "gsf-probe-v1" or data.get("status") != "ok":
        raise ValueError("invalid GSF adapter result")
    for key, cap in (("records",10000),("pings",2000),("beams_scanned",1000000)):
        if not isinstance(data.get(key),int) or not 0<=data[key]<=cap:
            raise ValueError("GSF adapter count exceeds pinned bound")
    valid=data["valid_depth_count"]; count=data["beams_scanned"]
    if not 0<=valid<=data["finite_depth_count"]<=count:
        raise ValueError("GSF validity counts inconsistent")
    receipt["observations"] = dict(
        header=dict(driver="upstream GSF 3.11 sequential API", crs=None, vertical_datum=None, grid_resolution=None,
                    native_depth_units=data["depth_units"], navigation_units=data["navigation_units"],
                    processing_parameters=data["processing_parameters"],parameters_truncated=data["parameters_truncated"]),
        window=dict(kind="bounded native ping/beam scan", scan_stop=data["stop"], records=data["records"],
                    pings=data["pings"], selected_navigation_pings=data["selected_navigation_pings"],
                    navigation_bbox=data["navigation_bbox"], actual_sounding_support=None,
                    selection="vessel navigation inside requested bbox; beam positions not reconstructed"),
        values=dict(count=count,finite_count=data["finite_depth_count"],valid_count=valid,
                    valid_fraction=valid/count if count else None,minimum=data["minimum"],maximum=data["maximum"],mean=data["mean"],
                    denominator_scope="all scanned beams including navigation-outside beams; fraction is qualifying scan yield, not selected-window quality or geographic coverage",
                    missing_beam_flags=data["missing_beam_flags"],ignored_or_unknown_count=data["ignored_or_unknown_count"],
                    validity="finite depth plus explicitly clear ping and beam flags; zero is not automatically invalid"))
    receipt["unknowns"] += ["native_horizontal_datum", "native_vertical_datum", "grid_resolution", "sounding_geographic_support", "depth_calculation_and_tide_correction_semantics: inspect explicit processing parameters"]
    receipt["limitations"].append("GSF API supplies metre/degrees units; no CRS or datum inferred from format defaults. Navigation bbox is not a sounding footprint.")
    if data["parameters_truncated"]:
        receipt["limitations"].append("processing parameters exceeded 16 entries or 256 bytes; unretained parameters remain unknown")
    if data["stop"] != "eof":
        receipt["limitations"].append("native record/ping/beam ceiling reached; unscanned file remains unknown")
    receipt["status"]="sample_observed" if valid else "sample_blocked"
    receipt["usefulness"]["private_terrain"]="bounded_window_candidate_for_qualification" if valid else "held_for_sample_issue"
    receipt["scan_hold"] = None
    if valid:
        receipt["next_action"]="review explicit processing parameters, datum and sounding positions before terrain qualification"
    else:
        if data["pings"] == 0:
            if data["stop"] != "eof":
                code = "scan_limit_before_first_ping"
                action = "use existing catalog or file metadata to select a source-linked file with relevant pings; do not repeat this scan or raise its limits"
            else:
                code = "eof_without_pings"
                action = "check the file role in existing source metadata and select a source-linked ping-bearing file; do not infer survey coverage from this file"
        elif data["selected_navigation_pings"] == 0:
            if data["stop"] == "eof":
                code = "no_navigation_selected_pings_eof"
                action = "review existing sounding-footprint or file-selection evidence for a relevant sample; completed vessel-navigation scan does not establish sounding nonoverlap"
            else:
                code = "no_navigation_selected_pings_partial_scan"
                action = "use existing source-linked file-selection evidence for a relevant bounded sample; unscanned pings and sounding support remain unknown; do not repeat this scan or raise its limits"
        else:
            code = "selected_pings_without_valid_depths"
            action = "review recorded missing or nonzero flags and finite-depth counts for the selected pings before choosing a different source-linked sample; do not treat this hold as whole-source quality"
        receipt["scan_hold"] = code
        receipt["blockers"].append(code + "; bounded sample evidence only, not whole-source coverage or quality")
        receipt["next_action"] = action
    return receipt
