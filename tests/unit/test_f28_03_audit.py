"""Exercise receipt verification with synthetic collector results and real paths."""
import importlib
import json
import sys

import pytest


@pytest.fixture(params=[
    "noaa_seabed_samples",
    pytest.param("san_miguel_original_habitat", marks=pytest.mark.gis),
    pytest.param("san_miguel_vr_habitat", marks=pytest.mark.gis),
])
def receipt_cli(request, tmp_path, monkeypatch):
    name = request.param
    script = importlib.import_module(f"research.scripts.audit_{name}")
    monkeypatch.chdir(tmp_path)
    inputs = tmp_path / "inputs.json"
    inputs.write_text('{"sectors": []}\n')
    if name == "noaa_seabed_samples":
        flags = ["--sectors", str(inputs)]
        verify = "--baseline"
        collector = "audit"

        def receipt(count, stamp):
            return {"bounded_original_sample_count": count, "page_sha256": ["synthetic"],
                    "assigned_to_browse_sector_count": 0, "sectors": [], "retrieved_at": stamp}
    else:
        flags = ["--manifest", str(inputs)]
        if name == "san_miguel_vr_habitat":
            for flag in ("mpas", "federal", "hazards", "enc", "naval-manifest", "naval-receipt"):
                flags.extend([f"--{flag}", str(inputs)])
        verify = "--verify"
        collector = "review"
        field = "counts" if name.endswith("vr_habitat") else "substrate_classes"

        def receipt(count, stamp):
            return {field: {"synthetic": count}, "reviewed_at": stamp}

    def run(baseline, output, report, calls):
        def collect(*args):
            calls.append(True)
            return report

        monkeypatch.setattr(script, collector, collect)
        monkeypatch.setattr(sys, "argv", [name, *flags, verify, str(baseline), "--output", str(output)])
        try:
            script.main()
        except SystemExit as exc:
            return exc.code
        return 0

    return run, receipt


@pytest.mark.parametrize("alias", ["same", "symlink", "hardlink"])
def test_alias_refused_before_collection(receipt_cli, tmp_path, alias):
    # Writing before reading lets changed receipts verify against themselves.
    run, receipt = receipt_cli
    output = tmp_path / "candidate.json"
    baseline = tmp_path / "reviewed.json"

    original = json.dumps(receipt(1, "reviewed")).encode()
    baseline.write_bytes(original)
    if alias == "same":
        output = baseline
    elif alias == "symlink":
        output.symlink_to(baseline)
    elif alias == "hardlink":
        output.hardlink_to(baseline)
    calls = []
    status = run(baseline, output, receipt(2, "new"), calls)
    assert baseline.read_bytes() == original
    assert calls == []
    assert status == 2


@pytest.mark.parametrize("receipt_cli", ["noaa_seabed_samples"], indirect=True)
def test_noaa_staging_alias_refused(receipt_cli, tmp_path):
    # The staging write can clobber or rename a reference even with a distinct output.
    run, receipt = receipt_cli
    output = tmp_path / "candidate.json"
    baseline = output.with_suffix(".json.tmp")
    original = json.dumps(receipt(1, "reviewed")).encode()
    baseline.write_bytes(original)
    calls = []
    assert run(baseline, output, receipt(2, "new"), calls) == 2
    assert baseline.read_bytes() == original
    assert calls == []
    assert not output.exists()


@pytest.mark.parametrize("changed", [False, True])
def test_distinct_candidate_remains_available(receipt_cli, tmp_path, changed):
    # A mismatch must still leave a separate candidate for review; timestamp-only changes pass.
    run, receipt = receipt_cli
    baseline = tmp_path / "reviewed.json"
    output = tmp_path / "new" / "candidate.json"
    original = json.dumps(receipt(1, "reviewed")).encode()
    baseline.write_bytes(original)
    report = receipt(2 if changed else 1, "new")
    calls = []
    status = run(baseline, output, report, calls)
    assert (status != 0) == changed
    assert calls == [True]
    assert baseline.read_bytes() == original
    assert json.loads(output.read_bytes()) == report
