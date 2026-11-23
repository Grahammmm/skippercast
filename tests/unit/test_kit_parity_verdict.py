"""The nearshore comparator client must reject bad evidence before sealing it."""
import json
from subprocess import CompletedProcess
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.gis
CASE_PASS = {"pass": True, "base.png": {"delta": 0}, "piles": {"iou": 1}}


@pytest.fixture
def parity_run(tmp_path, monkeypatch):
    from scripts.style import kit_parity

    kit = tmp_path / "kit"
    manifest = tmp_path / "FILES.sha256"
    manifest.touch()
    kit_zip = tmp_path / "synthetic.zip"
    kit_zip.write_bytes(b"synthetic archive")
    out = tmp_path / "out"
    (tmp_path / "style").mkdir()
    (tmp_path / "style/index.json").write_text(json.dumps({"versions": {"test": {
        "kit_zip_sha256": kit_parity.sha(kit_zip), "sha256": "a" * 64,
    }}}), encoding="utf-8")
    monkeypatch.setattr(kit_parity, "ROOT", tmp_path)
    baked = SimpleNamespace(digest=lambda _: "b" * 64)
    monkeypatch.setattr(kit_parity, "style", SimpleNamespace(
        load=lambda _: SimpleNamespace(version="test", view=lambda _: baked)))
    case = "synthetic"
    monkeypatch.setattr(kit_parity, "selftest_cases", lambda _: {
        case: ["$FX/dem.tif", "--view", "base", "--zoom", "16"],
    })
    monkeypatch.setattr(kit_parity, "verify_kit_files", lambda _kit, _rows, paths: [
        {"path": path, "sha256": "a" * 64} for path in paths
    ])
    monkeypatch.setattr(kit_parity, "run_selftest", lambda *_: {"ok": True, "lines": ["SELFTEST OK"]})
    monkeypatch.setattr(kit_parity, "kit_runtime", lambda _: {"python": "test"})
    monkeypatch.setattr(kit_parity, "render_engine", lambda *_: {})

    def oracle(_kit, _python, _fixtures, _cases, directory):
        (directory / case).mkdir(parents=True)
        rows = []
        for name in kit_parity.ORACLE_FILES:
            path = directory / case / name
            path.write_bytes(b"synthetic oracle bytes")
            rows.append({"path": f"{case}/{name}", "sha256": kit_parity.sha(path)})
        return rows, {}

    monkeypatch.setattr(kit_parity, "build_oracle", oracle)

    def run(mode, report, status):
        def stub(argv, **_kwargs):
            assert argv[1] == str(kit / "reference/compare.py")
            current = argv[2]
            assert current in ("case", "xres")
            payload, code = (report, status) if current == mode else (
                CASE_PASS if current == "case" else {"pass": True}, 0)
            return CompletedProcess(argv, code, json.dumps(payload), "")

        monkeypatch.setattr(kit_parity, "subprocess", SimpleNamespace(run=stub))
        return kit_parity.run(kit, manifest, kit_zip, out, "stub-python", None)

    return run, out, kit_parity.ParityError


@pytest.mark.parametrize("mode, verdict", [("case", True), ("case", False), ("xres", False)])
def test_seals_actual_boolean_verdict(parity_run, mode, verdict):
    run, out, _ = parity_run
    report = {**CASE_PASS, "pass": verdict} if mode == "case" else {"pass": verdict}
    assert run(mode, report, int(not verdict)) == int(not verdict)
    (sealed,) = out.glob("parity/*/parity.json")
    doc = json.loads(sealed.read_text(encoding="utf-8"))
    assert doc["pass"] is verdict
    assert doc["cases"]["synthetic"]["pass"] is (verdict if mode == "case" else True)
    assert doc["xres"]["pass"] is (verdict if mode == "xres" else True)


@pytest.mark.parametrize("mode, report, status", [
    pytest.param("case", {**CASE_PASS, "pass": "false"}, 1, id="truthy-case-failure"),
    pytest.param("xres", {"pass": "false"}, 1, id="truthy-xres-failure"),
    pytest.param("case", {"base.png": {}, "piles": {}}, 0, id="missing-pass"),
    pytest.param("case", {**CASE_PASS, "pass": 1}, 0, id="numeric-pass"),
    pytest.param("xres", None, 0, id="not-an-object"),
    pytest.param("case", CASE_PASS, 1, id="true-with-failure-exit"),
    pytest.param("xres", {"pass": False}, 0, id="false-with-success-exit"),
    pytest.param("case", {"pass": True, "piles": {}}, 0, id="missing-base-report"),
    pytest.param("case", {**CASE_PASS, "piles": None}, 0, id="invalid-piles-report"),
])
def test_refuses_malformed_verdict_before_sealing(parity_run, mode, report, status):
    # A comparator serializing false as a string used to seal a PASS despite exit 1.
    run, out, error = parity_run
    with pytest.raises(error):
        run(mode, report, status)
    assert not list(out.glob("parity/*/parity.json*"))
