"""SCA-103: the manual forecast readback must belong to this build.

The readback step script is extracted from the workflow and run against a fake
loader, so no network is used.
"""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
import textwrap
import types

from skippercast.forecast import local as forecast_local
from tests._support import ROOT

WORKFLOW = ROOT / ".github/workflows/forecast-tiles.yml"
MODELS = ("gfs_global", "ecmwf_ifs025", "ncep_gfswave016", "ecmwf_wam")
OLD, NEW = "2026-11-17T12:00:00Z", "2026-11-18T00:00:00Z"


def step_script():
    text = WORKFLOW.read_text(encoding="utf-8")
    match = re.search(r"python - <<'PY'\n(.*?)\n\s*PY\n", text[text.index("Read the published tiles back"):], re.S)
    assert match, "readback step script not found"
    return textwrap.dedent(match.group(1))


def epoch(cycle):
    return int(datetime.strptime(cycle, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp())


def run_readback(monkeypatch, tmp_path, report, published, attempts=3, tiles=None):
    """published: model -> list (one entry per read) of manifest cycle string or Exception; last entry repeats.

    tiles: model -> list (one entry per read) of the cycles the sampled tile files carry
    (a string, or a list of strings for several tiles); defaults to the manifest cycle.
    """
    reads = {m: 0 for m in MODELS}
    sleeps = []
    tiles = tiles or {}

    def pick(seq, model):
        return seq[min(reads[model], len(seq) - 1)]

    def model_loader(model, points):
        def load(client):
            item = pick(published[model], model)
            reads[model] += 1
            if isinstance(item, Exception):
                raise item
            # The readback must sample the one staged copy it checked, not refetch.
            root = Path(os.environ["SKIPPERCAST_FORECAST_ROOT"])
            assert (root / "index.json").is_file() and (root / model / "tiles").is_dir()
            wave = model in ("ncep_gfswave016", "ecmwf_wam")
            key = "wave_height" if wave else "wind_speed_10m"
            return {"sample_at": item, "points": [{"hourly": {key: [1.0] * 192}}]}
        return "url", load

    def stage(client, models, points, root):
        (root / models[0] / "tiles").mkdir(parents=True)
        manifest = pick(published[models[0]], models[0])
        if isinstance(manifest, Exception):  # the fetch itself fails
            reads[models[0]] += 1
            raise manifest
        cycles = pick(tiles[models[0]], models[0]) if models[0] in tiles else manifest
        for n, cycle in enumerate(cycles if isinstance(cycles, list) else [cycles]):
            tile = {"cycle": epoch(cycle) if isinstance(cycle, str) else cycle}
            (root / models[0] / "tiles" / f"{n}.json").write_text(json.dumps(tile))

    monkeypatch.setattr(forecast_local, "_stage", stage)
    fake = types.ModuleType("skippercast.pipeline.collect")
    fake.model_loader = model_loader
    fake.Client = lambda now: object()
    monkeypatch.setitem(sys.modules, "skippercast.pipeline.collect", fake)
    monkeypatch.setattr("time.sleep", lambda s: sleeps.append(s))
    path = tmp_path / "forecast-build.json"
    path.write_text(json.dumps({"models": report}))
    monkeypatch.setenv("BUILD_REPORT", str(path))
    monkeypatch.setenv("READBACK_ATTEMPTS", str(attempts))
    monkeypatch.setenv("READBACK_DELAY_SECONDS", "60")
    code = 0
    try:
        exec(compile(step_script(), "readback", "exec"), {"__name__": "readback"})
    except SystemExit as exit_:
        code = exit_.code or 0
    return code, reads, sleeps


def ok(cycle, state="built"):
    return {"status": "ok", "state": state, "cycle": cycle, "built_at": "x", "tiles": 5}


def all_ok(cycle=NEW):
    return {m: ok(cycle) for m in MODELS}


def test_old_but_complete_forecast_fails_for_changed_model(monkeypatch, tmp_path, capsys):
    published = {m: [NEW] for m in MODELS}
    published["gfs_global"] = [OLD]
    code, reads, sleeps = run_readback(monkeypatch, tmp_path, all_ok(), published)
    out = capsys.readouterr().out
    assert code == 1
    assert reads["gfs_global"] == 3 and len(sleeps) == 2  # bounded: attempts-1 sleeps
    assert "::error title=Forecast model gfs_global::published cycle does not match" in out


def test_delayed_then_matching_succeeds_within_bound(monkeypatch, tmp_path):
    published = {m: [NEW] for m in MODELS}
    published["ecmwf_wam"] = [OLD, RuntimeError("raw cache"), NEW]
    code, reads, sleeps = run_readback(monkeypatch, tmp_path, all_ok(), published)
    assert code == 0
    assert reads["ecmwf_wam"] == 3 and len(sleeps) == 2


def test_new_manifest_over_stale_tile_fails(monkeypatch, tmp_path, capsys):
    # Contract: a model reads back as this build only if the SAMPLED TILES carry the cycle,
    # not just the separately cached manifest. Bug: manifest at NEW + tile still at OLD passed.
    tiles = {"gfs_global": [OLD]}
    code, reads, sleeps = run_readback(monkeypatch, tmp_path, all_ok(), {m: [NEW] for m in MODELS}, tiles=tiles)
    out = capsys.readouterr().out
    assert code == 1
    assert reads["gfs_global"] == 3 and len(sleeps) == 2  # bounded retries
    assert f"published cycle {NEW} (manifest) with tiles at {OLD}, build expects {NEW}" in out
    assert "::error title=Forecast model gfs_global::published cycle does not match" in out
    assert "gfs_global: this build" not in out


def test_one_stale_tile_among_current_tiles_fails(monkeypatch, tmp_path):
    # Bug: checking only the first sampled tile hides an old second tile.
    code, _, _ = run_readback(monkeypatch, tmp_path, all_ok(), {m: [NEW] for m in MODELS},
                              tiles={"ecmwf_ifs025": [[NEW, OLD]]})
    assert code == 1


def test_stale_tile_then_matching_tile_succeeds(monkeypatch, tmp_path):
    code, reads, sleeps = run_readback(monkeypatch, tmp_path, all_ok(), {m: [NEW] for m in MODELS},
                                       tiles={"ecmwf_wam": [OLD, [NEW, NEW]]})
    assert code == 0 and reads["ecmwf_wam"] == 2 and len(sleeps) == 1


def test_non_integer_tile_cycle_fails(monkeypatch, tmp_path):
    code, _, _ = run_readback(monkeypatch, tmp_path, all_ok(), {m: [NEW] for m in MODELS},
                              tiles={"gfs_global": [None]})
    assert code == 1


def test_reused_current_model_must_match_and_is_reported(monkeypatch, tmp_path, capsys):
    report = all_ok()
    report["ecmwf_ifs025"] = ok(NEW, "current")
    code, _, _ = run_readback(monkeypatch, tmp_path, report, {m: [NEW] for m in MODELS})
    assert code == 0
    assert "ecmwf_ifs025: this build (current)" in capsys.readouterr().out


def test_retained_model_reported_separately_not_fresh(monkeypatch, tmp_path, capsys):
    report = all_ok()
    report["gfs_global"] = {"status": "failed", "issue": "upstream outage", "kept_previous": True}
    published = {m: [NEW] for m in MODELS}
    published["gfs_global"] = [OLD]
    code, reads, sleeps = run_readback(monkeypatch, tmp_path, report, published)
    out = capsys.readouterr().out
    assert code == 0 and not sleeps and reads["gfs_global"] == 1
    assert f"gfs_global: RETAINED previous build, cycle {OLD} (not this build)" in out
    assert "gfs_global: this build" not in out


def test_failed_without_retention_fails(monkeypatch, tmp_path, capsys):
    report = all_ok()
    report["ecmwf_wam"] = {"status": "failed", "issue": "boom", "kept_previous": False}
    code, _, _ = run_readback(monkeypatch, tmp_path, report, {m: [NEW] for m in MODELS})
    assert code == 1
    assert "build failed with nothing retained" in capsys.readouterr().out


def test_shape_check_retained_for_retained_model(monkeypatch, tmp_path, capsys):
    report = all_ok()
    report["gfs_global"] = {"status": "failed", "issue": "x", "kept_previous": True}
    published = {m: [NEW] for m in MODELS}
    published["gfs_global"] = [ValueError("Forecast units changed: wind_speed_10m 'm/s'")]
    code, _, _ = run_readback(monkeypatch, tmp_path, report, published)
    assert code == 1
    assert "retained tiles unreadable" in capsys.readouterr().out


def test_sleep_60_blind_wait_is_gone():
    assert "sleep 60" not in WORKFLOW.read_text(encoding="utf-8")
