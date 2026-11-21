"""F32-11: a length conflict needs more than nested AIS/licence matches."""
from collections import Counter

import pytest

from research.scripts import join_fleet_registries as joiner


@pytest.mark.parametrize("psix_evidence", ["absent", "ambiguous", "corroborating"])
def test_length_conflict_requires_independent_corroboration(monkeypatch, psix_evidence):
    # Both nested labels must survive for review, but neither an absent nor an
    # ambiguous PSIX link can make them independent. A valid PSIX link can.
    monkeypatch.setattr(joiner, "US_MIDS", frozenset({"999"}))
    name, mmsi, call, official = "Audit Length Vessel", "999000346", "ZZZ0346", "audit-official"
    port = "morro-bay"
    registry = [{"vessel_id": "synthetic-vessel", "name": name, "port_id": port}]
    statics = {mmsi: joiner.Static(mmsi, name, call, ship_type=30, length_m=100)}
    licences = [joiner.Licence("synthetic-licence", call, name, official, mmsi, length=30, status="active")]
    psix = [] if psix_evidence == "absent" else [
        joiner.PsixVessel("synthetic-psix", name, official, "", "", units={"Marine Safety Detachment Santa Barbara"})
    ]
    if psix_evidence == "ambiguous":
        licences.append(joiner.Licence("other-licence", "", "Other Audit Vessel", official, "999000347",
                                       status="active"))

    row, = joiner.join(registry, statics, {mmsi: Counter({port: 3})}, licences, psix)
    candidate = next(c for c in row["candidates"] if c["mmsi"] == mmsi)
    assert candidate["length_check"] == "contradicts"
    assert {"licence-call-sign", "licence-mmsi"} <= set(candidate["methods"])
    if psix_evidence == "corroborating":
        assert (row["verdict"], row["mmsi"]) == ("resolved", mmsi)
        assert "official-number" in candidate["methods"]
        assert "ais-length-differs-from-licence" in candidate["notes"]
        assert not candidate["conflicts"]
    else:
        assert (row["verdict"], row["mmsi"]) == ("unresolved", None)
        assert "official-number" not in candidate["methods"]
        assert "length-contradicts-licence" in candidate["conflicts"]
