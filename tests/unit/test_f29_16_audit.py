import hashlib
import json

from research.scripts import build_central_300_qualification_plan as plan
from tests._support import ROOT


def test_line_index_bytes_are_bound_without_changing_release_gates(tmp_path, monkeypatch):
    line_index = "dist/data/point-buchon-2007-ncei-line-index.json"
    fixture = tmp_path / "line-index.json"
    original_locate = plan.locate

    def locate(relative, root):
        if relative == line_index:
            return fixture
        return original_locate(relative, root)

    monkeypatch.setattr(plan, "locate", locate)
    # The other inputs are the checked-in summary receipts. Replace the entire
    # deciding input with synthetic counts, no survey lines or geometry needed.
    index = {
        "scope": "point-buchon-2007-ncei-generated-line-depth-index",
        "surveys": [
            {"survey_id": survey, "processed_line_count": count,
             "nominal_200_300ft_unknown_datum_envelope_line_count": in_band}
            for survey, count, in_band in (("PointBuchon", 100, 30), ("PointBuchon_Control", 86, 15))
        ],
        "qualified_waypoints": 0,
        "fishing_target": False,
    }
    plans = []
    for note in ("synthetic control A", "synthetic control B"):
        raw = (json.dumps({**index, "note": note}) + "\n").encode()
        fixture.write_bytes(raw)
        result = plan.build(ROOT)
        hashes = result.pop("source_sha256")
        assert hashes.pop(line_index) == hashlib.sha256(raw).hexdigest()
        assert len(result["release_gate_ids"]) == 6
        assert result["status"] == "research-only"
        plans.append((result, hashes))
    assert plans[0] == plans[1]
