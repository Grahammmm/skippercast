"""COAST-LOCALSCREEN tier-1 screener (skills/coast-local-screen/scripts/local_screen.py).

The local model is replaced by an in-process fake of the single loopback POST
helper, so these tests never open a socket. Raster tests need the survey stack
and are marked gis; the parsing/endpoint/PNG/fixture-eval tests are pure stdlib.
"""
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import urllib.error
import urllib.parse
import zlib

import pytest

from tests._support import ROOT

SCRIPT = ROOT / "skills/coast-local-screen/scripts/local_screen.py"
_spec = importlib.util.spec_from_file_location("coast_local_screen", SCRIPT)
ls = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ls)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


class FakeModel:
    """Stands in for the loopback endpoint: records calls, answers by kind."""

    def __init__(self, text="pass", vision="pass", fail=False):
        self.text, self.vision, self.fail, self.calls = text, vision, fail, []

    def __call__(self, url, body, timeout):
        self.calls.append((url, body))
        assert url.startswith("http://127.0.0.1:")
        if self.fail:
            raise urllib.error.URLError("connection refused")
        content = body["messages"][0]["content"]
        kind = "text" if isinstance(content, str) else "vision"
        answer = self.text if kind == "text" else self.vision
        if callable(answer):
            answer = answer(content)
        return {"choices": [{"message": {"content": answer}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 5}, "system_fingerprint": "fake-1"}


@pytest.fixture
def model(monkeypatch):
    fake = FakeModel()
    monkeypatch.setattr(ls, "_post", fake)
    monkeypatch.setattr(ls, "_get", lambda url, timeout: {"data": [{"id": "fake-model"}]})
    return fake


# ----------------------------------------------------------------------------- pure

@pytest.mark.parametrize("reply,verdict,found", [
    ("pass", "pass", []), ("Pass.", "pass", []), ("<think>hmm flag?</think>\npass", "pass", []),
    ("reasoning stripped of its opening tag</think>\npass", "pass", []),
    ("flag\nHOLES, EDGE_GAP", "flag", ["HOLES", "EDGE_GAP"]),
    ("The window looks fine, pass", "flag", ["OTHER"]), ("", "flag", ["OTHER"]), ("PASSABLE", "flag", ["OTHER"]),
    ("flag\nHOLES, VALID_LOW, EDGE_GAP, SLOPE_SPIKE", "flag", ["HOLES", "VALID_LOW", "EDGE_GAP"]),
    # contradictory, extra-line or unclosed replies are never a pass (review round 1, item 4)
    ("pass\nflag\nHOLES", "flag", ["HOLES"]), ("pass\nHOLES", "flag", ["HOLES"]), ("pass\nlooks fine", "flag", ["OTHER"]),
    ("pass pass", "flag", ["OTHER"]), ("<think>still thinking about whether to pass", "flag", ["OTHER"]),
    ("flag\npass", "flag", ["OTHER"]),
])
def test_anything_not_pass_is_flag(reply, verdict, found):
    got = ls.parse_reply(reply, ls.TEXT_REASONS, upper=True)
    assert got[0] == verdict
    if verdict == "flag":
        assert got[1] == found
        assert got[3] in {"flag", "malformed"}
    else:
        assert got[3] == "pass"


def test_reply_format_distinguishes_flag_from_malformed():
    assert ls.parse_reply("flag\nHOLES", ls.TEXT_REASONS, upper=True)[3] == "flag"
    assert ls.parse_reply("pass\nflag\nHOLES", ls.TEXT_REASONS, upper=True)[3] == "malformed"
    assert ls.parse_reply("pass\nflag\nstripe", ls.VISION_ARTEFACTS, upper=False)[:2] == ("flag", ["stripe"])


@pytest.mark.parametrize("finish", ["length", "content_filter", "tool_calls"])
def test_incomplete_completion_is_never_a_pass(finish):
    verdict, found, _, fmt = ls.parse_reply("pass", ls.TEXT_REASONS, upper=True, finish_reason=finish)
    assert (verdict, found, fmt) == ("flag", ["OTHER"], "truncated")
    assert ls.parse_reply("pass", ls.TEXT_REASONS, upper=True, finish_reason="stop")[0] == "pass"


def test_vision_artefacts_are_a_fixed_vocabulary():
    assert ls.parse_reply("flag\nseam, stripe, crater", ls.VISION_ARTEFACTS, upper=False)[1] == ["seam", "stripe"]
    assert ls.parse_reply("flag", ls.VISION_ARTEFACTS, upper=False)[1] == ["other"]


@pytest.mark.parametrize("endpoint", ["http://10.0.0.5:8003/v1", "https://127.0.0.1:8003/v1",
                                      "http://example.org/v1", "http://127.0.0.1.evil.org/v1"])
def test_endpoint_must_be_loopback(endpoint):
    with pytest.raises(ls.Refused):
        ls.check_endpoint(endpoint)


def test_loopback_endpoints_accepted():
    assert ls.check_endpoint("http://127.0.0.1:8003/v1/") == "http://127.0.0.1:8003/v1"
    assert ls.check_endpoint("http://localhost:8003/v1")


class FakeTransport:
    """Replaces urllib's default http transport (no socket): loopback answers per `answer`; any other
    host is recorded as an off-loopback attempt and refused."""

    def __init__(self, monkeypatch, answer):
        import urllib.request
        self.seen, self.off_loopback, self.answer = [], [], answer
        fake = self

        def http_open(handler, req):
            import email.message
            import io
            import urllib.response
            host = urllib.parse.urlparse(req.full_url).hostname
            fake.seen.append((req.get_method(), req.full_url))
            if host not in ls.LOOPBACK:
                fake.off_loopback.append(req.full_url)
                raise AssertionError("off-loopback transport attempted: " + req.full_url)
            code, headers, body = fake.answer(req)
            msg = email.message.Message()
            for k, v in headers.items():
                msg[k] = v
            resp = urllib.response.addinfourl(io.BytesIO(body), msg, req.full_url, code)
            resp.msg = "fake"
            return resp
        monkeypatch.setattr(urllib.request.HTTPHandler, "http_open", http_open)


REDIRECT_TARGETS = ["http://203.0.113.1:9/review-no-connection", "http://127.0.0.1:8004/v1/models"]


@pytest.mark.parametrize("target", REDIRECT_TARGETS)
@pytest.mark.parametrize("method", ["GET", "POST"])
def test_redirects_are_never_followed(monkeypatch, target, method):
    transport = FakeTransport(monkeypatch, lambda req: (302, {"Location": target}, b""))
    with pytest.raises(ls.Refused, match="redirect refused"):
        if method == "GET":
            ls._get("http://127.0.0.1:8003/v1/models", 1)
        else:
            ls._post("http://127.0.0.1:8003/v1/chat/completions", {"x": 1}, 1)
    assert transport.off_loopback == []
    assert transport.seen == [(method, "http://127.0.0.1:8003/v1/" + ("models" if method == "GET" else "chat/completions"))]


def test_redirect_makes_the_client_unavailable_not_redirected(monkeypatch):
    transport = FakeTransport(monkeypatch, lambda req: (307, {"Location": REDIRECT_TARGETS[0]}, b""))
    client = ls.Client("http://127.0.0.1:8003/v1", "m", timeout=1, retries=1, retry_wait=0, max_tokens=8)
    assert client.chat("x")["error"] == "ENDPOINT_UNAVAILABLE"
    assert client.model_tag() is None
    assert transport.off_loopback == [] and len(transport.seen) == 3        # 2 POST attempts + 1 GET, all loopback


def test_local_get_and_post_still_work(monkeypatch):
    def answer(req):
        if req.get_method() == "GET":
            return 200, {"Content-Type": "application/json"}, b'{"data":[{"id":"m1"}]}'
        assert json.loads(req.data) == {"x": 1}
        return 200, {"Content-Type": "application/json"}, b'{"ok":true}'
    transport = FakeTransport(monkeypatch, answer)
    assert ls._get("http://127.0.0.1:8003/v1/models", 1) == {"data": [{"id": "m1"}]}
    assert ls._post("http://localhost:8003/v1/chat/completions", {"x": 1}, 1) == {"ok": True}
    assert transport.off_loopback == []


@pytest.mark.parametrize("url", ["http://203.0.113.1:9/v1/models", "file:///etc/passwd", "https://127.0.0.1/v1"])
def test_transport_helpers_refuse_non_loopback_urls(monkeypatch, url):
    transport = FakeTransport(monkeypatch, lambda req: (200, {}, b"{}"))
    with pytest.raises(ls.Refused):
        ls._get(url, 1)
    with pytest.raises(ls.Refused):
        ls._post(url, {}, 1)
    assert transport.seen == []


def test_png_is_deterministic_and_well_formed():
    pixels = bytes(range(256)) * 32          # 64 x 64 gray+alpha
    a, b = ls.encode_png(pixels, 64, 64, 2), ls.encode_png(pixels, 64, 64, 2)
    assert a == b and a.startswith(b"\x89PNG\r\n\x1a\n")
    width, height, depth, color = struct.unpack(">IIBB", a[16:26])
    assert (width, height, depth, color) == (64, 64, 8, 4)
    idat_len = struct.unpack(">I", a[33:37])[0]
    raw = zlib.decompress(a[41:41 + idat_len])
    assert len(raw) == 64 * (1 + 64 * 2)


def test_unavailable_endpoint_trips_once_then_skips(monkeypatch):
    fake = FakeModel(fail=True)
    monkeypatch.setattr(ls, "_post", fake)
    client = ls.Client("http://127.0.0.1:9/v1", "m", timeout=1, retries=2, retry_wait=0, max_tokens=8)
    assert client.chat("x")["error"] == "ENDPOINT_UNAVAILABLE"
    assert len(fake.calls) == 3                       # 1 + 2 retries
    assert client.chat("y")["error"] == "ENDPOINT_UNAVAILABLE"
    assert len(fake.calls) == 3                       # circuit open: no further calls


def test_cli_refuses_relative_plan_dir(capsys):
    assert ls.main(["stats", "--plan-dir", "plans/p1"]) == 2
    assert "absolute" in capsys.readouterr().err


def test_cli_refuses_non_loopback_before_any_call(tmp_path, monkeypatch, capsys):
    fake = FakeModel()
    monkeypatch.setattr(ls, "_post", fake)
    out = tmp_path / "eval.json"
    assert ls.main(["fixture-eval", "--out", str(out), "--endpoint", "http://192.168.1.2:8003/v1"]) == 2
    assert fake.calls == [] and not out.exists()


def test_fixture_eval_adapter_and_confusion(tmp_path, model):
    receipt = {"window_id": "W1", "cells_total": 100, "expected_band": {"shallow_m": -10.0, "deep_m": -40.0},
               "depth_m": {"min": -38.0, "max": -12.0, "median": -20.0}, "counts": {"valid": 90, "hole": 6, "fill": 4},
               "slope_p95_deg": 3.0, "neighbour_delta_m": {"N": 0.1}, "hold_reasons": [], "status": "pass"}
    text = [{"id": "W1", "receipt": receipt, "gold": {"flag": False}},
            {"id": "W2", "receipt": dict(receipt, window_id="W2"), "gold": {"flag": True, "type": "seam"}}]
    png = ls.encode_png(bytes(64 * 64 * 2), 64, 64, 2)
    (tmp_path / "v1.png").write_bytes(png)
    vision = [{"id": "V1", "image": str(tmp_path / "v1.png"), "image_sha256": sha(png), "gold": {"flag": True, "type": "void"}}]
    (tmp_path / "t.json").write_text(json.dumps(text))
    (tmp_path / "v.json").write_text(json.dumps(vision))
    line = ls._fixture_line(receipt)
    assert line["depth_m_positive_down"] == {"min": 12.0, "median": 20.0, "max": 38.0}
    assert line["expected_depth_range_m"] == [10.0, 40.0]
    model.text = lambda content: "flag\nNEIGHBOUR_STEP" if '"W2"' in content else "pass"
    model.vision = "flag\nvoid"
    out = tmp_path / "eval.json"
    assert ls.main(["fixture-eval", "--text-fixtures", str(tmp_path / "t.json"), "--vision-fixtures",
                    str(tmp_path / "v.json"), "--out", str(out)]) == 0
    report = json.loads(out.read_text())
    metrics = report["suites"]["text"]["metrics"]
    assert {k: metrics[k] for k in ("tp", "fp", "fn", "tn", "recall")} == {"tp": 1, "fp": 0, "fn": 0, "tn": 1, "recall": 1.0}
    assert report["suites"]["vision"]["metrics"]["tp"] == 1
    assert report["screener"]["model_tag"] == "fake-model"


# ----------------------------------------------------------------------------- plan fixture (PC-9 shape)

TILE = 16
GRID = "a" * 64


def _write(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return raw


def _ref(root, path):
    raw = path.read_bytes()
    return {"path": path.relative_to(root).as_posix(), "sha256": sha(raw), "bytes": len(raw), "root_id": "queue:" + root.name}


def _rasters(root, out, depth, valid):
    import numpy as np
    import rasterio
    from rasterio.transform import from_origin
    h, w = depth.shape
    transform = from_origin(100000, 4000000, 10, 10)
    terrain = out / "terrain.tif"
    terrain.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(terrain, "w", driver="GTiff", width=w, height=h, count=1, dtype="float32",
                       crs="EPSG:3310", transform=transform, nodata=-9999.0) as ds:
        ds.write(np.where(valid, depth, -9999.0).astype("float32"), 1)
    support = out / "support.tif"
    with rasterio.open(support, "w", driver="GTiff", width=w, height=h, count=1, dtype="uint8",
                       crs="EPSG:3310", transform=transform) as ds:
        ds.write(valid.astype("uint8"), 1)
    vals = depth[valid]
    depth_m = ({"count": int(vals.size), "min": float(vals.min()), "max": float(vals.max()), "mean": float(vals.mean()),
                "p80": float(np.percentile(vals, 80))} if vals.size else
               {"count": 0, "min": "unknown", "max": "unknown", "mean": "unknown", "p80": "unknown"})
    cells = out / "cells.json"
    _write(cells, ls.canonical({"schema": "coastal-terrain-summary-v1", "native_valid_count": int(valid.sum()),
                                "depth_m": depth_m, "native_resolution_m": [10.0, 10.0]}))
    return {"terrain": _ref(root, terrain), "mask": _ref(root, support), "cells": _ref(root, cells)}, depth_m


def build_plan(tmp_path, specs, *, depth_range=None):
    """specs: list of dicts {col, row, state ('map_done'|'held'), offset, shape, holes}."""
    import numpy as np
    root = tmp_path / "C1-synthetic"
    plan = root / "plans" / "C1-M-test-ws00"
    (plan / "runs").mkdir(parents=True)
    candidates = [{"source_id": "src", "metadata": ({"depth_range_m": depth_range} if depth_range else {})}]
    _write(root / "catalog.json", ls.canonical({"schema": "synthetic-catalog", "candidates": candidates}))
    _write(plan / "bridge/bridge-receipt.json", b'{"synthetic":true}\n')
    _write(plan / "bridge/enqueue-receipt.json", b'{"synthetic":true}\n')
    adm_windows, windows = [], []
    yy, xx = np.mgrid[0:TILE, 0:TILE]
    for i, spec in enumerate(specs):
        idx = spec["row"] * 2 + spec["col"]
        key = f"src#{GRID}#{idx}"
        shape = spec.get("shape", (TILE, TILE))
        pixel = [spec["col"] * TILE, spec["row"] * TILE, shape[1], shape[0]]
        adm_windows.append({"window_key": key, "window_dir": sha(key.encode()), "source_id": "src", "grid_sha256": GRID,
                            "idx": idx, "pixel_window": pixel})
        jobs = root / "var/coastal/jobs" / f"job-{i:024d}"
        stages = {}
        manifest = _write(jobs / "acq/input.json", b'{"native":1}\n')
        del manifest
        acq_result = jobs / "acq/output/result.json"
        _write(acq_result, ls.canonical({"schema": "coastal-stage-result-v1", "state": "held" if spec["state"] == "held" else "done"}))
        stages["acquire"] = {"job_id": f"job:{i:024d}", "state": "held" if spec["state"] == "held" else "done",
                             "holds": ["vertical_sign_unobserved"] if spec["state"] == "held" else [],
                             "input_manifest": _ref(root, jobs / "acq/input.json"), "result_ref": _ref(root, acq_result),
                             "products": {}}
        if spec["state"] == "map_done":
            gx = (pixel[0] + xx[:shape[0], :shape[1]]) * 0.05
            gy = (pixel[1] + yy[:shape[0], :shape[1]]) * 0.05
            depth = 20.0 + gx + gy + spec.get("offset", 0.0)
            valid = np.ones(shape, bool)
            if spec.get("holes"):
                valid[:, : shape[1] * 3 // 4] = False
            products, depth_m = _rasters(root, jobs / "map/output", depth, valid)
            mresult = _write(jobs / "map/output/result.json", b'{"schema":"coastal-stage-result-v1","state":"done"}\n')
            del mresult
            stages["qualify"] = {"job_id": "q", "state": "done", "holds": [], "result_ref": None, "products": {},
                                 "support": {"valid_cells": int(valid.sum()), "mask_sha256": "b" * 64}}
            stages["map"] = {"job_id": "m", "state": "done", "holds": [], "result_ref": _ref(root, jobs / "map/output/result.json"),
                             "products": products, "native_valid_count": int(valid.sum()), "depth_m": depth_m}
        else:
            stages["qualify"] = {"state": "missing", "holds": [], "result_ref": None, "products": {}}
            stages["map"] = {"state": "missing", "holds": [], "result_ref": None, "products": {}}
        windows.append({"window_key": key, "source_id": "src", "root_job_id": f"job:{i:024d}",
                        "state": spec["state"], "unfinished_reason": None, "stages": stages})
    _write(plan / "admission.json", ls.canonical({"schema": "coast-admission-v1", "plan_id": plan.name, "windows": adm_windows,
                                                  "catalog": _ref(root, root / "catalog.json"), "grids": []}))
    summary = {"schema": "coast-run-summary-v1", "plan_id": plan.name, "plan_sha256": "c" * 64, "sequence": 0,
               "continuation_of": None, "admission": _ref(root, plan / "admission.json"),
               "bridge": _ref(root, plan / "bridge/bridge-receipt.json"),
               "enqueue": _ref(root, plan / "bridge/enqueue-receipt.json"), "problems": [], "windows": windows}
    _write(plan / "runs/run-00.json", ls.canonical(summary))
    return root, plan


def screen(plan, *extra, out=None):
    args = ["all", "--plan-dir", str(plan), "--retry-wait", "0", *extra]
    if out:
        args += ["--out", str(out)]
    code = ls.main(args)
    target = (out or plan / "review/tier1") / "flagged-windows.json"
    return code, (json.loads(target.read_text()) if target.exists() else None)


GRID4 = [dict(col=0, row=0, state="map_done"), dict(col=1, row=0, state="map_done"),
         dict(col=0, row=1, state="map_done"), dict(col=1, row=1, state="held")]


@pytest.mark.gis
def test_every_window_screened_with_fixed_order(tmp_path, model):
    pytest.importorskip("rasterio")
    root, plan = build_plan(tmp_path, GRID4)
    code, doc = screen(plan)
    assert code == 0
    assert doc["schema"] == "coast-tier1-screen-v1" and doc["accepted"] is False and doc["review_required"] is True
    keys = [w["window_key"] for w in doc["windows"]]
    assert keys == [f"src#{GRID}#{i}" for i in range(4)]
    by = {w["idx"]: w for w in doc["windows"]}
    for i in range(3):
        assert by[i]["tier1"] == "pass", by[i]["tier1_reasons"]
        assert by[i]["text_model"]["verdict"] == "pass" and by[i]["vision_model"]["verdict"] == "pass"
        det = by[i]["deterministic"]
        assert det["hash_ok"] and det["refs_checked"] >= 5
        assert det["producer"]["native_valid_count"] == TILE * TILE
        assert det["derived"]["valid_fraction"] == 1.0 and det["derived"]["slope_p99_deg"] is not None
        thumb = by[i]["vision_model"]["thumbnail"]
        assert thumb["px"] == 256 and sha((root / thumb["path"]).read_bytes()) == thumb["sha256"]
    # the held window is reported, not screened; holds copied
    assert by[3]["tier1"] == "held" and by[3]["text_model"] is None
    assert by[3]["deterministic"]["holds"] == ["vertical_sign_unobserved"]
    # adjacency: window 0 compares with 1 (E) and 2 (S); 3 is held so never compared
    n0 = {n["direction"]: n for n in by[0]["deterministic"]["neighbours"]}
    assert set(n0) == {"E", "S"} and abs(n0["E"]["delta_median_m"]) < 0.1
    assert {n["direction"] for n in by[1]["deterministic"]["neighbours"]} == {"W"}
    s = doc["summary"]
    assert (s["windows"], s["pass"], s["flag"], s["held"], s["hash_mismatches"]) == (4, 3, 0, 1, 0)
    assert s["must_examine"] == [f"src#{GRID}#3"]
    assert doc["screener"]["prompt_sha256"]["text"] == sha((SCRIPT.parents[1] / "prompts/text.md").read_bytes())
    # 3 text + 3 vision calls; the held window never reaches a model
    assert len(model.calls) == 6
    vision_bodies = [b for _, b in model.calls if not isinstance(b["messages"][0]["content"], str)]
    assert all(c["image_url"]["url"].startswith("data:image/png;base64,")
               for b in vision_bodies for c in b["messages"][0]["content"] if c["type"] == "image_url")


@pytest.mark.gis
def test_thumbnails_and_stats_are_deterministic(tmp_path, model):
    pytest.importorskip("rasterio")
    root, plan = build_plan(tmp_path, GRID4[:2])
    assert screen(plan, out=plan / "review/tier1-a")[0] == 0
    assert screen(plan, out=plan / "review/tier1-b")[0] == 0
    for w in json.loads((plan / "review/tier1-a/stats.json").read_text())["windows"]:
        a = (plan / "review/tier1-a/windows" / w["window_dir"] / "hillshade.png").read_bytes()
        b = (plan / "review/tier1-b/windows" / w["window_dir"] / "hillshade.png").read_bytes()
        assert a == b and struct.unpack(">II", a[16:24]) == (256, 256)


@pytest.mark.gis
def test_neighbour_step_flags_both_sides(tmp_path, model):
    pytest.importorskip("rasterio")
    specs = [dict(GRID4[0]), dict(GRID4[1], offset=5.0)]
    _, plan = build_plan(tmp_path, specs)
    _, doc = screen(plan)
    for w in doc["windows"]:
        assert "NEIGHBOUR_STEP" in w["deterministic"]["flags"] and w["tier1"] == "flag"
    assert abs(abs(doc["windows"][0]["deterministic"]["neighbour_delta_median_m"]) - 5.0) < 0.2


@pytest.mark.gis
def test_hash_mismatch_is_never_overridden_by_a_model(tmp_path, model):
    pytest.importorskip("rasterio")
    root, plan = build_plan(tmp_path, GRID4[:2])
    summary = json.loads((plan / "runs/run-00.json").read_text())
    terrain = root / summary["windows"][1]["stages"]["map"]["products"]["terrain"]["path"]
    terrain.write_bytes(terrain.read_bytes() + b"tampered")
    _, doc = screen(plan)
    w = doc["windows"][1]
    assert w["deterministic"]["hash_ok"] is False and "HASH_MISMATCH" in w["deterministic"]["flags"]
    assert "DERIVED_UNAVAILABLE" in w["deterministic"]["flags"]
    assert w["text_model"]["verdict"] == "pass" and w["tier1"] == "flag"
    assert doc["summary"]["hash_mismatches"] == 1
    assert w["window_key"] in doc["summary"]["must_examine"]


@pytest.mark.gis
def test_plan_level_receipt_mismatch_flags_every_window(tmp_path, model):
    pytest.importorskip("rasterio")
    _, plan = build_plan(tmp_path, GRID4[:2])
    path = plan / "bridge/enqueue-receipt.json"
    path.write_bytes(b'{"synthetic":false}\n')
    _, doc = screen(plan)
    assert all(w["tier1"] == "flag" and "HASH_MISMATCH" in w["deterministic"]["flags"] for w in doc["windows"])
    assert "PLAN_RECEIPT_PROBLEM" in doc["summary"]["flags"]


@pytest.mark.gis
def test_free_text_and_vision_flags_are_flags(tmp_path, model):
    pytest.importorskip("rasterio")
    _, plan = build_plan(tmp_path, GRID4)
    model.text = "Looks clean to me."
    model.vision = lambda content: "flag\nstripe"
    _, doc = screen(plan)
    mapped = [w for w in doc["windows"] if w["deterministic"]["state"] == "map_done"]
    assert all(w["tier1"] == "flag" for w in mapped)
    assert all(w["text_model"]["reasons"] == ["OTHER"] and w["vision_model"]["artefacts"] == ["stripe"] for w in mapped)
    assert doc["windows"][3]["tier1"] == "held"
    assert doc["summary"]["text_flags"] == 3 and doc["summary"]["vision_flags"] == 3


@pytest.mark.gis
def test_endpoint_unavailable_lets_nothing_pass(tmp_path, model):
    pytest.importorskip("rasterio")
    _, plan = build_plan(tmp_path, GRID4)
    model.fail = True
    code, doc = screen(plan)
    assert code == 0
    assert "ENDPOINT_UNAVAILABLE" in doc["summary"]["flags"]
    assert doc["summary"]["pass"] == 0 and doc["summary"]["flag"] == 3 and doc["summary"]["held"] == 1
    assert all("TEXT_UNAVAILABLE" in w["tier1_reasons"] for w in doc["windows"] if w["tier1"] == "flag")


@pytest.mark.gis
def test_deterministic_rules_and_null_statistics(tmp_path, model):
    pytest.importorskip("rasterio")
    specs = [dict(col=0, row=0, state="map_done", holes=True), dict(col=1, row=0, state="map_done", shape=(2, 2))]
    _, plan = build_plan(tmp_path, specs, depth_range=[0.0, 10.0])
    _, doc = screen(plan)
    holes, tiny = doc["windows"]
    assert {"VALID_FRACTION_LOW", "EDGE_VALID_LOW", "DEPTH_RANGE_OUT"} <= set(holes["deterministic"]["flags"])
    assert holes["deterministic"]["depth_range_plausible"] is False
    assert "DERIVED_UNAVAILABLE" in tiny["deterministic"]["flags"]
    assert tiny["deterministic"]["derived"]["slope_p99_deg"] is None and tiny["tier1"] == "flag"
    assert doc["summary"]["derived_unavailable"] == 1


@pytest.mark.gis
def test_catalog_without_range_is_null_not_pass(tmp_path, model):
    pytest.importorskip("rasterio")
    _, plan = build_plan(tmp_path, GRID4[:1])
    _, doc = screen(plan)
    det = doc["windows"][0]["deterministic"]
    assert det["depth_range_plausible"] is None and det["depth_range_reason"] == "catalog_range_unavailable"


@pytest.mark.gis
def test_outputs_are_write_once_and_confined(tmp_path, model, capsys):
    pytest.importorskip("rasterio")
    _, plan = build_plan(tmp_path, GRID4[:1])
    assert screen(plan)[0] == 0
    assert ls.main(["stats", "--plan-dir", str(plan)]) == 2
    assert "exists" in capsys.readouterr().err
    assert ls.main(["stats", "--plan-dir", str(plan), "--out", str(tmp_path / "elsewhere")]) == 2
    before = sorted(p.relative_to(plan).as_posix() for p in plan.rglob("*") if "review" not in p.parts)
    assert before == sorted(["admission.json", "bridge", "bridge/bridge-receipt.json", "bridge/enqueue-receipt.json",
                             "runs", "runs/run-00.json"])


def _edit_summary(plan, edit):
    path = plan / "runs/run-00.json"
    summary = json.loads(path.read_text())
    edit(summary)
    path.write_bytes(ls.canonical(summary))


ALL_PASS = (4, 3, 0, 1)   # windows, pass, flag, held for an untouched GRID4 control


@pytest.mark.gis
def test_control_untouched_plan_has_no_integrity_flags(tmp_path, model):
    pytest.importorskip("rasterio")
    _, plan = build_plan(tmp_path, GRID4)
    _, doc = screen(plan)
    s = doc["summary"]
    assert (s["windows"], s["pass"], s["flag"], s["held"]) == ALL_PASS
    assert s["plan_integrity_problems"] == [] and "PLAN_INTEGRITY" not in s["flags"]


@pytest.mark.gis
def test_missing_window_is_preserved_as_non_pass(tmp_path, model):
    pytest.importorskip("rasterio")
    _, plan = build_plan(tmp_path, GRID4[:2])
    _edit_summary(plan, lambda s: s["windows"].pop(1))
    code, doc = screen(plan)
    assert code == 0
    s = doc["summary"]
    assert s["windows"] == 2 and s["pass"] == 0 and s["flag"] == 2
    assert s["must_examine"] == sorted([f"src#{GRID}#0", f"src#{GRID}#1"])
    assert "PLAN_INTEGRITY" in s["flags"] and any("missing" in p for p in s["plan_integrity_problems"])
    gone = doc["windows"][1]
    assert gone["deterministic"]["state"] == "missing_from_run_summary"
    assert {"PLAN_INTEGRITY", "NOT_MAPPED"} <= set(gone["deterministic"]["flags"])
    assert gone["deterministic"]["integrity"] == ["MISSING_FROM_RUN_SUMMARY"] and gone["text_model"] is None


@pytest.mark.gis
@pytest.mark.parametrize("ref", ["admission", "bridge", "enqueue"])
def test_missing_required_ref_fails_closed(tmp_path, model, ref):
    pytest.importorskip("rasterio")
    _, plan = build_plan(tmp_path, GRID4[:2])
    _edit_summary(plan, lambda s: s.pop(ref))
    _, doc = screen(plan)
    s = doc["summary"]
    assert s["pass"] == 0 and s["flag"] == 2 and len(s["must_examine"]) == 2
    assert "PLAN_INTEGRITY" in s["flags"] and f"required ref missing: {ref}" in s["plan_integrity_problems"]
    assert all("PLAN_INTEGRITY" in w["deterministic"]["flags"] for w in doc["windows"])


@pytest.mark.gis
def test_extra_and_duplicate_windows_flag_the_plan(tmp_path, model):
    pytest.importorskip("rasterio")
    _, plan = build_plan(tmp_path, GRID4[:2])

    def edit(s):
        extra = json.loads(json.dumps(s["windows"][0]))
        extra["window_key"] = f"src#{GRID}#99"
        s["windows"].append(extra)
        s["windows"].append(json.loads(json.dumps(s["windows"][1])))
    _edit_summary(plan, edit)
    _, doc = screen(plan)
    s = doc["summary"]
    keys = [w["window_key"] for w in doc["windows"]]
    assert keys == [f"src#{GRID}#0", f"src#{GRID}#1", f"src#{GRID}#99"]
    assert s["pass"] == 0 and s["flag"] == 3 and len(s["must_examine"]) == 3
    by = {w["window_key"]: w for w in doc["windows"]}
    assert by[f"src#{GRID}#99"]["deterministic"]["integrity"] == ["NOT_IN_ADMISSION"]
    assert by[f"src#{GRID}#1"]["deterministic"]["integrity"] == ["DUPLICATE_IN_RUN_SUMMARY"]


@pytest.mark.gis
@pytest.mark.parametrize("stage", ["map", "qualify", "acquire"])
def test_hold_on_a_mapped_window_is_never_a_pass(tmp_path, model, stage):
    pytest.importorskip("rasterio")
    _, plan = build_plan(tmp_path, GRID4[:2])
    _edit_summary(plan, lambda s: s["windows"][0]["stages"][stage]["holds"].append("review_test_hold"))
    _, doc = screen(plan)
    w = doc["windows"][0]
    assert w["deterministic"]["holds"] == ["review_test_hold"]
    assert {"HOLD", "STATE_INCONSISTENT"} <= set(w["deterministic"]["flags"])
    assert w["tier1"] == "flag" and w["window_key"] in doc["summary"]["must_examine"]
    assert doc["windows"][1]["tier1"] == "pass"            # control


@pytest.mark.gis
def test_held_stage_state_on_a_mapped_window_is_never_a_pass(tmp_path, model):
    pytest.importorskip("rasterio")
    _, plan = build_plan(tmp_path, GRID4[:2])
    _edit_summary(plan, lambda s: s["windows"][0]["stages"]["qualify"].update(state="held"))
    _, doc = screen(plan)
    w = doc["windows"][0]
    assert {"HOLD", "STATE_INCONSISTENT"} <= set(w["deterministic"]["flags"]) and w["tier1"] == "flag"


@pytest.mark.gis
@pytest.mark.parametrize("text,vision", [("pass\nflag\nHOLES", "pass"), ("pass", "pass\nflag\nstripe"),
                                         ("pass\nflag\nHOLES", "pass\nflag\nstripe")])
def test_contradictory_model_replies_never_pass(tmp_path, model, text, vision):
    pytest.importorskip("rasterio")
    _, plan = build_plan(tmp_path, GRID4[:2])
    model.text, model.vision = text, vision
    _, doc = screen(plan)
    s = doc["summary"]
    assert s["pass"] == 0 and s["flag"] == 2 and len(s["must_examine"]) == 2
    for w in doc["windows"]:
        if text != "pass":
            assert w["text_model"]["verdict"] == "flag" and w["text_model"]["reasons"] == ["HOLES"]
            assert w["text_model"]["reply_format"] == "malformed"
        if vision != "pass":
            assert w["vision_model"]["verdict"] == "flag" and w["vision_model"]["artefacts"] == ["stripe"]


@pytest.mark.gis
def test_truncated_completion_never_passes(tmp_path, monkeypatch, model):
    pytest.importorskip("rasterio")
    _, plan = build_plan(tmp_path, GRID4[:1])

    def truncated(url, body, timeout):
        reply = model(url, body, timeout)
        reply["choices"][0]["finish_reason"] = "length"
        return reply
    monkeypatch.setattr(ls, "_post", truncated)
    _, doc = screen(plan)
    w = doc["windows"][0]
    assert w["tier1"] == "flag" and w["text_model"]["reply_format"] == "truncated"


# ----------------------------------------------------------------------------- real PC-9 receipts

from tests.unit.test_coastal_bridge_run import enqueue as _enqueue  # noqa: E402
from tests.unit.test_coastal_bridge_run import offline_and_provenance  # noqa: E402,F401  (autouse: sockets refused)
from tests.unit.test_coastal_bridge_run import run as _bridge_run  # noqa: E402
from tests.unit.test_coastal_bridge_run import world  # noqa: E402,F401


@pytest.mark.gis
@pytest.mark.parametrize("world", ["real-stages"], indirect=True)
def test_screens_a_real_pc9_run_summary(world, monkeypatch, model):
    """Real Store, real acquire/qualify/map producers, real bridge_run summary -> the screener."""
    from types import SimpleNamespace
    from skippercast.coastal.coordinator import loop
    from skippercast.coastal.handoff.common import write
    from skippercast.coastal.stage_cli import execute
    from tests._support import NOW
    w = world
    _enqueue(w)
    original_init = loop.Coordinator.__init__

    def dispatch(job, job_path, out, identity_callback, deadline):
        value = execute(job, out, now=NOW)
        write(out / "result.json", value)
        return SimpleNamespace(rc={"done": 0, "held": 3}[value["state"]])

    def initialize(coordinator, store, **kwargs):
        original_init(coordinator, store, dispatcher=dispatch, **kwargs)
    monkeypatch.setattr(loop.Coordinator, "__init__", initialize)
    summary = _bridge_run(w)
    assert summary["counts"]["map_done"] == 2
    code, doc = screen(w.p)
    assert code == 0
    assert doc["receipt_shape"] == "pc9"
    assert [x["window_key"] for x in doc["windows"]] == [x["window_key"] for x in w.admission["windows"]]
    for x in doc["windows"]:
        det = x["deterministic"]
        assert det["hash_ok"], det["hash_problems"]
        assert det["state"] == "map_done" and det["refs_checked"] >= 8
        assert det["producer"]["native_valid_count"] == det["derived"]["valid_cells"] == 16
        assert det["producer"]["valid_cells"] == 16
        assert det["derived"]["resolution_m"] is not None
        assert x["window_dir"] == next(a["window_dir"] for a in w.admission["windows"] if a["window_key"] == x["window_key"])
        assert x["vision_model"]["thumbnail"]["px"] == 256
        assert "COUNT_MISMATCH" not in det["flags"] and "HASH_MISMATCH" not in det["flags"]
    # two different sources share no grid: no adjacency across sources
    assert all(x["deterministic"]["neighbours"] == [] for x in doc["windows"])
    assert doc["run_summary"]["path"] == "plans/pilot01/runs/run-00.json"


@pytest.mark.gis
@pytest.mark.parametrize("stage,state", [("map", "failed"), ("qualify", "failed"), ("acquire", "missing")])
def test_mapped_window_with_an_unfinished_stage_is_never_a_pass(tmp_path, model, stage, state):
    pytest.importorskip("rasterio")
    _, plan = build_plan(tmp_path, GRID4[:2])
    _edit_summary(plan, lambda s: s["windows"][0]["stages"][stage].update(state=state))
    _, doc = screen(plan)
    w = doc["windows"][0]
    assert "STATE_INCONSISTENT" in w["deterministic"]["flags"] and w["tier1"] == "flag"
    assert doc["windows"][1]["tier1"] == "pass"            # control
