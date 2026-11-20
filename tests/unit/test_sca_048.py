"""Offline replay of the habitat manifest producer across source changes."""
import json
from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from skippercast.pipeline import habitat_dynamics as habitat


NOW = datetime(2026, 1, 2, 12, tzinfo=timezone.utc)
SST = "sst-analysis"
CHL = "chlorophyll-observation"
REGION = "fixture-region"


@pytest.fixture
def replay(tmp_path, monkeypatch):
    config = {
        "name": "Fixture publisher",
        "documentation_url": "https://fixture.invalid/about",
        "review_status": "approved",
        "allowed_hosts": ["fixture.invalid"],
        "adapter": "erddap-grid",
        "rights": {"license": "Fixture terms", "allow_redistribute": True},
        "request": {"base_url": "https://fixture.invalid", "dataset": "grid-a",
                    "variables": ["temperature"], "max_age_hours": 72},
    }
    catalog = {"publisher-a": config, "chlorophyll": deepcopy(config), "noaa-wcofs": {}}
    region = {"bounds": [0, 0, 1, 1], "species": [],
              "pipeline_sources": {"sst": "publisher-a", "chlorophyll": "chlorophyll"},
              "source_bindings": {"sea-temperature": ["publisher-a", "publisher-b"],
                                  "chlorophyll": ["chlorophyll"]}}
    calls = []
    unavailable = set()

    def satellite(client, area, request, kind):
        calls.append((kind, request["dataset"]))
        if kind in unavailable:
            raise OSError("Synthetic acquisition failure")
        cells = [[.25, .25, 18 if request["dataset"] == "grid-a" else 21]]
        return {"kind": "analysis" if kind == "sst" else "observation",
                "sample_at": habitat.stamp(NOW), "dataset": request["dataset"],
                "fields": ["latitude", "longitude", "value"], "resolution_degrees": [.01, .01],
                "valid_cells": 1, "total_cells": 1,
                "frames": [{"time": int(NOW.timestamp()), "cells": cells, "valid_cells": 1, "total_cells": 1}]}

    # Use the real source receipt, injecting only an inert client and loader.
    real_source = habitat.source

    class OfflineClient(habitat.Client):
        def __init__(self, now):
            self.requests = []

        def get(self, *args, **kwargs):
            pytest.fail("Synthetic habitat replay attempted network acquisition")

    def source(*args):
        return real_source(*args, client_factory=OfflineClient)

    monkeypatch.setattr(habitat, "source", source)
    monkeypatch.setattr(habitat, "load_region", lambda _: region)
    monkeypatch.setattr(habitat, "load_catalogs", lambda: ({}, catalog))
    monkeypatch.setattr(habitat, "satellite", satellite)
    monkeypatch.setattr("skippercast.pipeline.collect.stamp", lambda dt=None: habitat.stamp(dt or NOW))
    real_stamp = habitat.stamp
    monkeypatch.setattr(habitat, "stamp", lambda dt=None: real_stamp(dt or NOW))
    original = tmp_path / "original"
    first = habitat.run(REGION, original, now=NOW)
    calls.clear()
    return region, catalog, calls, unavailable, original, first


def regional(root):
    return root / "regions" / REGION


@pytest.mark.parametrize("hours", [1, 7])
@pytest.mark.parametrize("change", ["publisher", "request", "rights", "adapter", "legacy", "layer-source", "bounds", "method"])
def test_incompatible_cache_is_absent_on_failed_acquisition(replay, tmp_path, monkeypatch, hours, change):
    region, catalog, calls, unavailable, original, first = replay
    cfg = catalog["publisher-a"]
    source_id = "publisher-a"
    if change == "publisher":
        source_id = "publisher-b"
        region["pipeline_sources"]["sst"] = source_id
        catalog[source_id] = cfg
    elif change == "request":
        cfg["request"]["dataset"] = "grid-b"
    elif change == "rights":
        cfg["rights"]["allow_redistribute"] = False
    elif change == "adapter":
        cfg["adapter"] = "noaa-ncss-sst"
    elif change == "legacy":
        for row in (first["layers"][SST], first["sources"][SST]):
            row.pop("cache_binding", None)
    elif change == "layer-source":
        first["layers"][SST]["source_id"] = "publisher-b"
    elif change == "bounds":
        region["bounds"] = [0, 0, 2, 2]
    else:
        monkeypatch.setattr(habitat, "METHOD", "fixture-next-method")
    if change in ("legacy", "layer-source"):
        (regional(original) / "habitat-dynamics.json").write_text(json.dumps(first), encoding="utf-8")
    old_path = first["layers"][SST]["tiles"][0]["path"]
    old_bytes = (regional(original) / old_path).read_bytes()
    unavailable.add("sst")
    output = tmp_path / "output"
    result = habitat.run(REGION, output, original, NOW + timedelta(hours=hours))
    assert ("sst", cfg["request"]["dataset"]) in calls
    assert SST not in result["layers"]
    assert result["sources"][SST]["source_id"] == source_id
    assert result["sources"][SST]["status"] == "failed"
    assert result["sources"][SST]["last_populated_at"] is None
    assert SST in result["health"]["issues"]
    assert not (regional(output) / old_path).exists()
    assert (regional(original) / old_path).read_bytes() == old_bytes


def test_recent_rebind_acquires_new_product_without_refreshing_other_layer(replay, tmp_path):
    _, catalog, calls, _, original, first = replay
    catalog["publisher-a"]["request"]["dataset"] = "grid-b"
    output = tmp_path / "output"
    result = habitat.run(REGION, output, original, NOW + timedelta(hours=1))
    assert calls == [("sst", "grid-b")]
    assert result["layers"][SST]["dataset"] == "grid-b"
    assert result["layers"][SST]["tiles"] != first["layers"][SST]["tiles"]
    assert result["layers"][CHL] == first["layers"][CHL]
    assert result["sources"][CHL] == {**first["sources"][CHL], "reused": True}


@pytest.mark.parametrize("hours, status", [(1, "ok"), (7, "retained")])
def test_matching_cache_preserves_bytes_and_original_provenance(replay, tmp_path, hours, status):
    _, _, calls, unavailable, original, first = replay
    unavailable.update({"sst", "chlorophyll"})
    outputs = [tmp_path / "one", tmp_path / "two"]
    for output in outputs:
        result = habitat.run(REGION, output, original, NOW + timedelta(hours=hours))
        assert result["layers"][SST] == {**first["layers"][SST], "status": status}
        old_source, source = first["sources"][SST], result["sources"][SST]
        for field in ("source_id", "rights", "data_retrieved_at", "last_success_at", "last_populated_at"):
            assert source[field] == old_source[field]
        assert source["status"] == status
        if hours == 1:
            assert source == {**old_source, "reused": True}
        for tile in result["layers"][SST]["tiles"]:
            path = tile["path"]
            assert (regional(output) / path).read_bytes() == (regional(original) / path).read_bytes()
    assert len(calls) == (0 if hours == 1 else 4)
    for path in ("habitat-dynamics.json", "habitat-health.json"):
        assert (regional(outputs[0]) / path).read_bytes() == (regional(outputs[1]) / path).read_bytes()
