"""SC-RIGHTS-DELTA JSON decoder failures (recursion) map to INVALID/2 without a report."""
import json

import pytest

from scripts.coast_diagnostics import rights_delta as rd
from tests._support import ROOT

FIXTURES = ROOT / "tests" / "fixtures" / "sc_rights_delta"
LEFT = FIXTURES / "observation_left.json"
RIGHT = FIXTURES / "observation_right.json"
DETAIL = "JSON nesting exceeds parser limit"
DEEP_ARRAY = b"[" * 100000 + b"0" + b"]" * 100000
DEEP_OBJECT = b'{"x":' * 100000 + b"0" + b"}" * 100000


def _boom(*_args, **_kwargs):
    raise RecursionError("synthetic decoder exhaustion")


def _diag(capsys):
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Traceback" not in captured.err
    lines = captured.err.splitlines()
    assert len(lines) == 1
    return json.loads(lines[0])


def test_decoder_recursion_is_invalid_json(monkeypatch):
    monkeypatch.setattr(rd.json, "loads", _boom)
    with pytest.raises(rd.InvalidJSON, match=DETAIL):
        rd.parse_json_strict(b"{}")


@pytest.mark.parametrize("failing_call", [1, 2])
def test_cli_decoder_recursion_returns_invalid_without_write(monkeypatch, tmp_path, capsys, failing_call):
    real = rd.json.loads
    calls = []

    def loads(*args, **kwargs):
        calls.append(1)
        if len(calls) == failing_call:
            raise RecursionError("synthetic decoder exhaustion")
        return real(*args, **kwargs)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("must not be reached")

    monkeypatch.setattr(rd.json, "loads", loads)
    monkeypatch.setattr(rd, "compare_rights", forbidden)
    monkeypatch.setattr(rd, "write_new", forbidden)
    out = tmp_path / "out" / "report.json"
    before = (LEFT.read_bytes(), RIGHT.read_bytes())
    assert rd.main(["--left", str(LEFT), "--right", str(RIGHT), "--out", str(out)]) == 2
    assert _diag(capsys) == {"schema": rd.DELTA_SCHEMA, "status": "INVALID", "detail": DETAIL}
    assert not out.parent.exists()
    assert (LEFT.read_bytes(), RIGHT.read_bytes()) == before


@pytest.mark.parametrize("deep", [DEEP_ARRAY, DEEP_OBJECT], ids=["array", "object"])
@pytest.mark.parametrize("side", ["left", "right"])
def test_real_overdeep_inputs_are_invalid(tmp_path, capsys, deep, side):
    bad = tmp_path / "deep.json"
    bad.write_bytes(deep)
    healthy = LEFT if side == "right" else RIGHT
    paths = {"left": str(bad), "right": str(healthy)} if side == "left" else {"left": str(healthy), "right": str(bad)}
    out = tmp_path / "report.json"
    assert rd.main(["--left", paths["left"], "--right", paths["right"], "--out", str(out)]) == 2
    assert _diag(capsys)["status"] == "INVALID"
    assert not out.exists()
    assert bad.read_bytes() == deep


def test_parse_controls_unchanged():
    assert rd.parse_json_strict(b'{"a": [1, 2]}') == {"a": [1, 2]}
    for data, detail in [
        (b"\xff", "input is not UTF-8"),
        (b"{", "malformed JSON"),
        (b'{"a":1,"a":2}', "duplicate object key"),
        (b"NaN", "nonfinite number NaN"),
        (b"[Infinity]", "nonfinite number Infinity"),
    ]:
        with pytest.raises(rd.InvalidJSON, match=detail):
            rd.parse_json_strict(data)
