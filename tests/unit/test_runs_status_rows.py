"""Nested source/region statuses in a read run manifest must be nonempty text (RF1221-5)."""
from datetime import datetime, timezone
import copy
import json

import pytest

from skippercast import report, runs
from skippercast.platform.contracts import read_json

SOURCES_MESSAGE = "Run manifest sources must map ids to status rows"
REGIONS_MESSAGE = "Run manifest regions must map ids to status rows"
BAD_STATUSES = [[], {}, ["ok"], {"state": "ok"}, None, True, False, 0, 7, 1.5, ""]
BAD_IDS = [f"bad-{i}" for i in range(len(BAD_STATUSES))]
SENTINEL_ID, SENTINEL_VALUE = "SECRET-ID-7731", "SECRET-VALUE-4482"


def manifest(**fields):
    doc = {"schema_version": runs.SCHEMA_VERSION, "job": "refresh", "run_id": "1", "started_at": "2026-10-31T00:00:00Z",
           "status": "ok", "inputs": [], "outputs": [], "sources": {}}
    doc.update(fields)
    return doc


@pytest.mark.parametrize("status", BAD_STATUSES, ids=repr)
def test_sources_reject_nontext_or_empty_status(status):
    doc = manifest(sources={"good": {"status": "ok"}, "bad": {"status": status}})
    before = copy.deepcopy(doc)
    with pytest.raises(ValueError) as caught:
        runs.validate(doc)
    assert str(caught.value) == SOURCES_MESSAGE
    with pytest.raises(ValueError) as caught:
        report.render(doc)
    assert str(caught.value) == SOURCES_MESSAGE
    assert doc == before


@pytest.mark.parametrize("status", BAD_STATUSES, ids=repr)
def test_regions_reject_nontext_or_empty_status(status):
    doc = manifest(sources={"s": {"status": "ok"}},
                   regions={"good": {"status": "ok"}, "bad": {"status": status}})
    before = copy.deepcopy(doc)
    with pytest.raises(ValueError) as caught:
        runs.validate(doc)
    assert str(caught.value) == REGIONS_MESSAGE
    with pytest.raises(ValueError) as caught:
        report.render(doc)
    assert str(caught.value) == REGIONS_MESSAGE
    assert doc == before


def test_status_diagnostics_do_not_echo_rejected_ids_or_values():
    for field, message in (("sources", SOURCES_MESSAGE), ("regions", REGIONS_MESSAGE)):
        doc = manifest(**{field: {SENTINEL_ID: {"status": [SENTINEL_VALUE]}}})
        with pytest.raises(ValueError) as caught:
            report.render(doc)
        assert str(caught.value) == message
        assert SENTINEL_ID not in str(caught.value) and SENTINEL_VALUE not in str(caught.value)


def test_legacy_and_unknown_text_statuses_are_preserved():
    assert runs.validate(legacy := manifest()) is legacy
    assert "regions" not in legacy
    for doc in (manifest(regions={}), manifest(sources={}, regions={})):
        assert runs.validate(doc) is doc
    doc = manifest(status="degraded",
                   sources={"a": {"status": "stale"}, "b": {"status": "retained"}, "c": {"status": "ok"},
                            "d": {"status": " spaced out "}},
                   regions={"r1": {"status": "missing"}, "r2": {"status": "unchecked"}, "r3": {"status": "failed"}})
    assert runs.validate(doc) is doc
    assert report.render(doc) == "\n".join([
        "### refresh: ⚠️ degraded", "",
        "| Run | Commit | Started | Duration | Exit |", "| --- | --- | --- | --- | --- |",
        "| 1 | – | 2026-10-31T00:00:00Z | – | – |", "",
        "| Region | Status | Sources ok | Duration | Issues / error |", "| --- | --- | ---: | --- | --- |",
        "| r3 | ❌ failed | – | – | – |", "| r1 | missing | – | – | – |", "| r2 | unchecked | – | – | – |", "",
        "Regions: 1 failed, 1 missing, 1 unchecked", "",
        "| Source | Status | Duration | Detail |", "| --- | --- | --- | --- |",
        "| a | stale | – | – |", "| b | retained | – | – |", "| d | spaced out | – | – |", "",
        "Sources: 1  spaced out , 1 ok, 1 retained, 1 stale",
    ]) + "\n"


def run_main(args, capsys):
    status = report.main([str(p) for p in args])
    out = capsys.readouterr()
    return status, out.out, out.err


@pytest.mark.parametrize("order", ["bad-first", "healthy-first"])
def test_report_main_continues_past_bad_status_files(tmp_path, capsys, order):
    bad_source = tmp_path / "bad-source.json"
    bad_region = tmp_path / "bad-region.json"
    good = tmp_path / "good.json"
    bad_source.write_text(json.dumps(manifest(sources={SENTINEL_ID: {"status": [SENTINEL_VALUE]}})))
    bad_region.write_text(json.dumps(manifest(regions={SENTINEL_ID: {"status": {"k": SENTINEL_VALUE}}})))
    good.write_text(json.dumps(manifest(job="healthy")))
    before = {p: p.read_bytes() for p in (bad_source, bad_region, good)}
    paths = [bad_source, bad_region, good] if order == "bad-first" else [good, bad_source, bad_region]
    status, out, err = run_main(paths, capsys)
    assert status == 1
    assert err.count("ValueError: " + SOURCES_MESSAGE) == 1
    assert err.count("ValueError: " + REGIONS_MESSAGE) == 1
    assert len(err.strip().splitlines()) == 2
    assert "Traceback" not in err and SENTINEL_ID not in err and SENTINEL_VALUE not in err
    assert out == report.render(manifest(job="healthy"))
    assert out.count("### healthy: ✅ ok") == 1
    assert {p: p.read_bytes() for p in (bad_source, bad_region, good)} == before
    assert sorted(p.name for p in tmp_path.iterdir()) == ["bad-region.json", "bad-source.json", "good.json"]


def test_real_run_manifest_statuses_round_trip(tmp_path):
    ticks = iter([0.0, 2.0])
    run = runs.RunManifest("refresh", "42", git_sha="a" * 40, clock=lambda: next(ticks),
                           wall_clock=lambda: datetime(2026, 10, 31, tzinfo=timezone.utc))
    run.source("noaa", "ok", duration_ms=1200, detail="fine")
    run.region("CA", "degraded", sources_ok=0, sources_total=1)
    run.write(tmp_path / "run.json")
    doc = read_json(tmp_path / "run.json")
    assert doc == run.to_dict()
    assert runs.validate(doc) is doc
    assert report.render(doc) == "\n".join([
        "### refresh: ⚠️ degraded", "",
        "| Run | Commit | Started | Duration | Exit |", "| --- | --- | --- | --- | --- |",
        "| 42 | aaaaaaaaaaaa | 2026-10-31T00:00:00Z | 2.0 s | 0 |", "",
        "| Region | Status | Sources ok | Duration | Issues / error |", "| --- | --- | ---: | --- | --- |",
        "| CA | ⚠️ degraded | 0/1 | – | – |", "", "Regions: 1 degraded", "", "",
        "Sources: 1 ok",
    ]) + "\n"
