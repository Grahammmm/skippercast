"""RF0140-11: collect_cdfw_mpas uses one clock, names capture failures and checks --output first."""
from datetime import datetime, timezone
import json

import pytest

from scripts import collect_cdfw_mpas as mod

NOW = datetime(2026, 11, 2, 9, 30, tzinfo=timezone.utc)
DATA = {"geojson": {"type": "FeatureCollection", "features": []}, "feature_count": 123, "source_url": "fake://mpa"}


class FakeClient:
    made = []

    def __init__(self, now):
        self.now = now
        self.requests = [{"url": "fake://mpa"}]
        FakeClient.made.append(self)


@pytest.fixture
def fakes(monkeypatch):
    FakeClient.made = []
    calls = []

    def loader(client):
        calls.append(client)
        return DATA

    monkeypatch.setattr(mod, "CoastalClient", FakeClient)
    monkeypatch.setattr(mod, "mpa_loader", loader)
    return calls


def failing(monkeypatch, exc):
    def loader(client):
        raise exc
    monkeypatch.setattr(mod, "CoastalClient", FakeClient)
    monkeypatch.setattr(mod, "mpa_loader", loader)


def test_fixed_now_is_used_for_client_and_checked_at(fakes):
    result = mod.collect(NOW)
    assert result["checked_at"] == NOW.isoformat()
    assert [c.now for c in FakeClient.made] == [NOW]


def test_collect_without_arguments_still_works_for_screen_sources(fakes):
    result = mod.collect()
    assert datetime.fromisoformat(result["checked_at"]) == FakeClient.made[0].now


class NetworkDownClient(FakeClient):
    def get(self, url, as_json=False):
        raise OSError("network unreachable")


@pytest.mark.parametrize("loader_error, client, line", [
    (ValueError("Incomplete statewide MPA boundaries"), FakeClient, "ValueError: Incomplete statewide MPA boundaries"),
    (None, NetworkDownClient, "OSError: network unreachable"),
])
def test_capture_failure_one_line_exit_1_output_untouched(monkeypatch, tmp_path, capsys, loader_error, client, line):
    if loader_error:
        failing(monkeypatch, loader_error)
    monkeypatch.setattr(mod, "CoastalClient", client)  # no loader_error: real mpa_loader, fake get fails
    out = tmp_path / "mpa.json"
    out.write_bytes(b'{"previous": true}\n')
    assert mod.main(["--output", str(out)]) == 1
    captured = capsys.readouterr()
    assert captured.err == "collect_cdfw_mpas: capture failed: " + line + "\n" and captured.out == ""
    assert out.read_bytes() == b'{"previous": true}\n'
    assert sorted(p.name for p in tmp_path.iterdir()) == ["mpa.json"]


def test_long_multiline_message_is_first_line_capped_at_200(monkeypatch, tmp_path, capsys):
    failing(monkeypatch, ValueError("x" * 500 + "\nsecond line"))
    assert mod.main(["--output", str(tmp_path / "mpa.json")]) == 1
    err = capsys.readouterr().err
    assert err.count("\n") == 1
    assert err == "collect_cdfw_mpas: capture failed: ValueError: " + "x" * 200 + "\n"


def test_other_exceptions_propagate(monkeypatch, tmp_path):
    failing(monkeypatch, KeyError("unexpected"))
    with pytest.raises(KeyError):
        mod.main(["--output", str(tmp_path / "mpa.json")])


def test_directory_output_refused_before_client(fakes, tmp_path, capsys):
    assert mod.main(["--output", str(tmp_path)]) == 2
    assert capsys.readouterr().err == "collect_cdfw_mpas: --output must be a file path, not a directory or link\n"
    assert fakes == [] and FakeClient.made == []


@pytest.mark.parametrize("target_exists", [True, False])
def test_symlink_output_refused_target_unchanged(fakes, tmp_path, capsys, target_exists):
    target = tmp_path / "real.json"
    if target_exists:
        target.write_bytes(b"keep\n")
    link = tmp_path / "mpa.json"
    link.symlink_to(target)
    assert mod.main(["--output", str(link)]) == 2
    assert capsys.readouterr().err == "collect_cdfw_mpas: --output must be a file path, not a directory or link\n"
    assert fakes == [] and FakeClient.made == []
    assert link.is_symlink()
    assert target.read_bytes() == b"keep\n" if target_exists else not target.exists()


def test_success_writes_five_keys(fakes, tmp_path, capsys):
    out = tmp_path / "nested" / "mpa.json"
    assert mod.main(["--output", str(out)]) == 0
    written = json.loads(out.read_text())
    assert set(written) == {"status", "checked_at", "data", "requests", "fishing_permission"}
    assert written["fishing_permission"] is None and written["status"] == "ok"
    assert written["data"] == DATA and written["requests"] == [{"url": "fake://mpa"}]
    assert json.loads(capsys.readouterr().out) == {"cdfw_mpa_features": 123}
