"""Oversized JSON integers in a current field are refused without aborting the ocean packet (RF1221-4)."""

import copy
import json
import socket

import pytest

from skippercast.pipeline import coast_snapshots as cs
from tests.unit.test_coast_snapshots import NOW, goes, intelligence

HUGE = 10**400
OTHER = {"wcofs": "hfr-1", "hfr-1": "wcofs"}
CASES = [(ident, location, sign)
         for ident, fields in (("wcofs", cs.FIELDS_FORECAST), ("hfr-1", cs.FIELDS_RADAR))
         for location in ["time", *fields] for sign in (1, -1)]


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("network forbidden")
    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(socket.socket, "connect", blocked)


def corrupt(ident, location, sign):
    doc = intelligence()
    fields = cs.FIELDS_FORECAST if ident == "wcofs" else cs.FIELDS_RADAR
    frame = doc["sources"][ident]["data"]["frames"][0]
    if location == "time":
        frame["time"] = sign * HUGE
    else:
        frame["cells"][0][fields.index(location)] = sign * HUGE
    return json.loads(json.dumps(doc))


def by_id(packet):
    return {field["id"]: field for field in packet["currents"]}


def test_number_rejects_oversized_integers_without_raising():
    assert cs._number(HUGE) is False
    assert cs._number(-HUGE) is False
    for good in (0, 7, -3, 1.5, 0.0, 10**300):
        assert cs._number(good) is True
    for bad in (True, False, None, "1", [1], {"a": 1}, float("nan"), float("inf"), float("-inf")):
        assert cs._number(bad) is False


@pytest.mark.parametrize("ident,location,sign", CASES)
def test_each_oversized_current_component_omits_only_its_field(ident, location, sign):
    control = cs.assemble(intelligence(), goes(), NOW)
    doc = corrupt(ident, location, sign)
    before = copy.deepcopy(doc)
    packet = cs.assemble(doc, goes(), NOW)
    assert doc == before
    fields = by_id(packet)
    assert list(fields) == [OTHER[ident]]
    assert fields[OTHER[ident]] == by_id(control)[OTHER[ident]]
    assert packet["cloud"] == control["cloud"]
    assert [s["status"] for s in packet["sources"]] == ["ok", "ok"]


def test_all_invalid_currents_preserve_valid_cloud_and_error_source():
    control = cs.assemble(intelligence(), goes(), NOW)
    doc = corrupt("wcofs", "time", 1)
    doc["sources"]["hfr-1"]["data"]["frames"][0]["cells"][0][0] = HUGE
    packet = cs.assemble(doc, goes(), NOW)
    assert packet["currents"] == []
    assert packet["sources"][0]["status"] == "error"
    assert packet["sources"][0]["error"] == "No fresh reviewed current fields"
    assert packet["cloud"] == control["cloud"]
    assert packet["sources"][1] == control["sources"][1]
    assert packet.keys() == control.keys()
    assert packet["generatedAt"] == control["generatedAt"]
    stale = cs.assemble(doc, goes("2026-10-08T10:00:00.000Z"), NOW)
    assert stale["currents"] == [] and stale["cloud"] is None
    assert [s["status"] for s in stale["sources"]] == ["error", "error"]
    assert stale["sources"][0]["error"] == "No fresh reviewed current fields"
    missing = cs.assemble(doc, None, NOW)
    assert missing["cloud"] is None
    assert [s["status"] for s in missing["sources"]] == ["error", "error"]


def test_main_serializes_degraded_integer_input(tmp_path, capsys):
    region = tmp_path / "regions" / "morro-bay"
    region.mkdir(parents=True)
    # json.dumps writes the oversized integer as plain digits; json.loads reads it back as an int.
    intel_bytes = json.dumps(corrupt("wcofs", "latitude", 1)).encode()
    goes_bytes = json.dumps(goes()).encode()
    (region / "intelligence.json").write_bytes(intel_bytes)
    (tmp_path / "goes-times.json").write_bytes(goes_bytes)
    assert cs.main(["--root", str(tmp_path)], NOW) == 0
    packet = json.loads((region / "coast-ocean.json").read_text())
    assert [f["id"] for f in packet["currents"]] == ["hfr-1"]
    assert packet["cloud"] == goes()
    assert [s["status"] for s in packet["sources"]] == ["ok", "ok"]
    assert (region / "intelligence.json").read_bytes() == intel_bytes
    assert (tmp_path / "goes-times.json").read_bytes() == goes_bytes
    assert json.loads(capsys.readouterr().out)["currents"] == ["hfr-1"]


def test_healthy_packet_is_unchanged():
    packet = cs.assemble(intelligence(), goes(), NOW)
    assert list(by_id(packet)) == ["wcofs", "hfr-1"]
    assert [s["status"] for s in packet["sources"]] == ["ok", "ok"]
    assert packet["cloud"] == goes()
    radar = by_id(packet)["hfr-1"]
    assert [len(f["cells"]) for f in radar["frames"]] == [1, 1]  # the HDOP and site-count gates drop two cells
    assert radar["frames"][1]["cells"][0]["towardDeg"] == 0.0  # 360 normalizes to north
    assert radar["frames"][1]["cells"][0]["uMs"] == 0.0
    assert radar["frames"][1]["cells"][0]["vMs"] == round(0.4 / round(cs.KT_PER_MS, 8), 5)
