"""latest.json staging isolation in the daily pipeline CLI (offline, tmp_path only)."""
import json
import os
import sys
from pathlib import Path

import pytest

from skippercast.pipeline import __main__ as cli


def _snapshot(tag):
    return {"generated_at": "2026-01-01T00:00:00Z", "tag": tag, "text": "caf\u00e9",
            "health": {"status": "ok", "tag": tag}}


@pytest.fixture
def run(monkeypatch, tmp_path):
    out = tmp_path / "out"
    state = {"tag": "a", "checked": []}
    monkeypatch.setattr(cli, "collect", lambda now, previous, region_id: _snapshot(state["tag"]))
    monkeypatch.setattr(cli.schemas, "check", lambda name, snap: state["checked"].append(snap["tag"]))

    def go():
        monkeypatch.setattr(sys, "argv", ["pipeline", "--output", str(out)])
        cli.main()

    return out, state, go


def _stages(out):
    return sorted(p.name for p in out.iterdir() if p.name.endswith(".tmp"))


def test_overlapping_main_calls_have_independent_latest_stages(run, monkeypatch):
    out, state, go = run
    real_replace = Path.replace
    sources = []
    nested = []

    def replace(self, target):
        if Path(target).name == "latest.json":
            sources.append(self)
            if not nested:
                nested.append(True)
                state["tag"] = "inner"
                go()
        return real_replace(self, target)

    monkeypatch.setattr(Path, "replace", replace)
    state["tag"] = "outer"
    go()
    assert len(sources) == 2 and sources[0] != sources[1]
    assert json.loads((out / "latest.json").read_text())["tag"] in {"outer", "inner"}
    assert _stages(out) == []


def test_single_writer_preserves_serialized_bytes_and_public_mode(run, capsys):
    out, state, go = run
    go()
    expected = json.dumps(_snapshot("a"), separators=(",", ":"), allow_nan=False) + "\n"
    assert (out / "latest.json").read_bytes() == expected.encode("ascii")
    assert "\\u00e9" in expected
    history = list((out / "history").glob("*.json"))
    assert len(history) == 1 and history[0].read_bytes() == expected.encode("ascii")
    assert json.loads(capsys.readouterr().out) == _snapshot("a")["health"]
    assert json.loads((out / "health.json").read_text())["status"] == "ok"
    if os.name == "posix":
        assert (out / "latest.json").stat().st_mode & 0o777 == 0o644


@pytest.mark.parametrize("failure", ["write", "replace"])
def test_write_and_replace_failures_preserve_latest_and_cleanup(run, monkeypatch, failure):
    out, state, go = run
    out.mkdir()
    (out / "latest.json").write_bytes(b"sentinel\n")
    if failure == "write":
        import tempfile
        real = tempfile.NamedTemporaryFile

        class Broken:
            def __init__(self, *a, **k):
                self.inner = real(*a, **k)
                self.name = self.inner.name

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                self.inner.close()

            def write(self, text):
                raise OSError("disk full")

        monkeypatch.setattr(cli.tempfile, "NamedTemporaryFile", Broken)
    else:
        def replace(self, target):
            raise OSError("replace refused")

        monkeypatch.setattr(Path, "replace", replace)
    with pytest.raises(OSError, match="disk full|replace refused"):
        go()
    assert (out / "latest.json").read_bytes() == b"sentinel\n"
    assert _stages(out) == []


def test_foreign_legacy_stage_is_untouched(run):
    out, state, go = run
    out.mkdir()
    (out / "latest.tmp").write_bytes(b"foreign\n")
    go()
    assert (out / "latest.tmp").read_bytes() == b"foreign\n"
    assert json.loads((out / "latest.json").read_text())["tag"] == "a"


def test_schema_failure_precedes_output_write(run, monkeypatch):
    out, state, go = run

    def boom(name, snap):
        raise ValueError("schema")

    monkeypatch.setattr(cli.schemas, "check", boom)
    with pytest.raises(ValueError):
        go()
    assert not out.exists()
    out.mkdir()
    (out / "latest.json").write_bytes(b"sentinel\n")
    with pytest.raises(ValueError):
        go()
    assert sorted(p.name for p in out.iterdir()) == ["latest.json"]
    assert (out / "latest.json").read_bytes() == b"sentinel\n"
