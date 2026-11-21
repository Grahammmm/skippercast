"""Offline retention controls for unchained, legacy-keyed live observations."""
from datetime import timedelta
from functools import partial

import pytest

from skippercast.pipeline import live
from skippercast.pipeline.collect import Client, source
from tests._support import NOW


@pytest.fixture
def live_run(monkeypatch):
    stations = {
        "nearshore_buoy": "00001",
        "nearshore_buoy_name": "Synthetic A",
        "offshore_buoy": "00003",
        "offshore_buoy_name": "Synthetic offshore",
    }
    monkeypatch.setattr(live, "settings", lambda region_id: {"region": {"stations": stations}})

    def run(now, previous=None, *, outage=False):
        class FixtureClient(Client):
            def __init__(self, now):
                self.requests = []

            def get(self, url, as_json=False, as_pdf=False, as_binary=False):
                if outage and f"/{stations['nearshore_buoy']}." in url:
                    raise OSError("synthetic outage")
                time = now.strftime("%Y %m %d %H %M")
                if url.endswith(".spec"):
                    return f"#YY MM DD hh mm WVHT SwH SwP WWH WWP\n#yr mo dy hr mn m m sec m sec\n{time} 1.5 1.2 10 0.3 5\n"
                return f"#YY MM DD hh mm WVHT DPD WTMP WSPD\n#yr mo dy hr mn m sec degC m/s\n{time} 1.5 10 18 4\n"

        monkeypatch.setattr(live, "source", partial(source, client_factory=FixtureClient))
        monkeypatch.setattr("skippercast.pipeline.collect.stamp", lambda t=now: t.isoformat())
        monkeypatch.setattr(live, "stamp", lambda t=now: t.isoformat())
        return live.collect(now, previous, region_id="synthetic")

    return stations, run


@pytest.mark.parametrize("key,suffix,extension", [
    ("diablo", "", "txt"),
    ("diablo-spectrum", " swell and wind waves", "spec"),
])
def test_station_rebind_does_not_relabel_failed_observation(live_run, key, suffix, extension):
    stations, run = live_run
    previous = run(NOW)
    assert previous["sources"][key]["status"] == "ok"
    stations.update(nearshore_buoy="00002", nearshore_buoy_name="Synthetic B")

    failed = run(NOW + timedelta(minutes=30), previous, outage=True)
    row = failed["sources"][key]
    assert row["status"] == "failed"
    assert row["data"] is None
    assert row["name"] == "Synthetic B" + suffix
    assert row["url"].endswith(f"/00002.{extension}")
    assert row["station_url"].endswith("station=00002")
    assert "data_retrieved_at" not in row and "last_success_at" not in row
    assert failed["health"]["status"] == "degraded"
    assert failed["sources"]["offshore"]["status"] == "ok"


@pytest.mark.parametrize("has_source_url", [True, False])
@pytest.mark.parametrize("key", ["diablo", "diablo-spectrum"])
def test_same_station_and_product_retains_identity_and_original_clocks(live_run, key, has_source_url):
    _, run = live_run
    previous = run(NOW)
    old = previous["sources"][key]
    url = old["url"]
    if not has_source_url:
        del old["url"]
    failed = run(NOW + timedelta(minutes=30), previous, outage=True)
    row = failed["sources"][key]
    assert row["url"] == url
    assert row["status"] == "retained"
    assert row["data"]["station"] == "00001"
    for field in ("data", "name", "station_url", "data_retrieved_at", "last_success_at"):
        assert row[field] == old[field]
    assert row["checked_at"] != old["checked_at"]
    assert failed["health"]["status"] == "degraded"


@pytest.mark.parametrize("has_source_url", [True, False])
def test_same_station_wrong_product_is_not_retained(live_run, has_source_url):
    _, run = live_run
    previous = run(NOW)
    spectrum = {**previous["sources"]["diablo-spectrum"], "id": "diablo"}
    if not has_source_url:
        del spectrum["url"]
    previous["sources"]["diablo"] = spectrum

    row = run(NOW + timedelta(minutes=30), previous, outage=True)["sources"]["diablo"]
    assert row["status"] == "failed"
    assert row["data"] is None


def test_old_data_already_mislabeled_with_current_station_is_not_retained(live_run):
    stations, run = live_run
    old = run(NOW)["sources"]["diablo"]
    stations.update(nearshore_buoy="00002", nearshore_buoy_name="Synthetic B")
    previous = run(NOW + timedelta(minutes=30))
    previous["sources"]["diablo"].update(status="retained", data=old["data"])

    row = run(NOW + timedelta(hours=1), previous, outage=True)["sources"]["diablo"]
    assert row["status"] == "failed"
    assert row["data"] is None
