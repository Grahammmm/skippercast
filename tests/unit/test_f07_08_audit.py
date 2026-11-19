"""F07-08: a unique name match cannot take another vessel's stored Places ID."""
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from skippercast.fleet.adapters.base import RunContext
from skippercast.fleet.adapters.google_places import GooglePlaces
from skippercast.fleet.enrich import enrich_code


@pytest.mark.parametrize("owner_port", ["port-a", "port-b", None, "no-owner"],
                         ids=["same-port", "other-port", "portless-owner", "unreserved"])
def test_existing_place_ids_are_reserved_across_resolved_snapshot(tmp_path, owner_port):
    reserved = "SyntheticPlaceA"
    free = "SyntheticPlaceB"
    vessels = [
        {"id": "v-new", "name": "Example Skiff", "port_id": "port-a"},
        {"id": "v-free", "name": "Example Sloop", "port_id": "port-a"},
        {"id": "v-ambiguous", "name": "Example Cutter", "port_id": "port-a"},
    ]
    if owner_port != "no-owner":
        # Put the stored row last to catch checks that reserve IDs only as vessels are matched.
        vessels.append({"id": "v-owner", "name": "Other Vessel", "port_id": owner_port, "place_id": reserved})
    (tmp_path / "resolved.jsonl").write_text("".join(json.dumps(v) + "\n" for v in vessels), encoding="utf-8")

    transport = Mock(spec=["search_text", "details"])
    transport.search_text.return_value = {"places": [
        {"id": reserved, "displayName": {"text": "Example Skiff Charters"}},
        {"id": free, "displayName": {"text": "Example Sloop Charters"}},
        {"id": "SyntheticPlaceC", "displayName": {"text": "Example Cutter East"}},
        {"id": "SyntheticPlaceD", "displayName": {"text": "Example Cutter West"}},
    ]}
    transport.details.return_value = {"id": reserved}
    binding = SimpleNamespace(id="google-places", adapter="google-places", params={}, rights="api-terms")
    ports = {"port-a": SimpleNamespace(name="Port A", point=(0.0, 0.0))}
    region = SimpleNamespace(name="Test Region", sources=[binding], enabled_sources=lambda: [binding],
                             binding={binding.id: binding}.__getitem__, port=ports.__getitem__)
    ctx = RunContext(region=region, net=None, run_dir=tmp_path, clock=lambda: "2026-01-01T00:00:00Z")
    adapter = GooglePlaces(transport=transport, environ={})
    sink = Mock(spec=["apply"])
    sink.apply.return_value = {"changed": 0}
    enrich_code(ctx, sink, adapters={"google-places": adapter})

    facts = [json.loads(line) for line in (tmp_path / "facts.jsonl").read_text(encoding="utf-8").splitlines()]
    expected_holder = "v-new" if owner_port == "no-owner" else "v-owner"
    assert sorted((f["vessel_id"], f["field"], f["value"]) for f in facts) == sorted([
        ("v-free", "place_id", free), (expected_holder, "place_id", reserved),
    ])
