"""N7 counts only trips that contribute to the scored part of the confusion table."""
import json
from unittest.mock import patch

import pytest

from skippercast.fleet.ais import validate
from skippercast.fleet.ais.events import iso_utc
from skippercast.fleet.ais.process import MINUTE
from skippercast.fleet.ais.sources.base import AisPosition
from skippercast.fleet.ais.validate import Interval
from tests.unit.test_fleet_process import REGION, T0


@pytest.mark.parametrize(
    "padding, scored, gaps, eligible",
    [("gap", 3, 27, False), ("sub-minute", 3, 0, False), ("scored", 30, 0, True)],
)
def test_n7_requires_contributing_trips(tmp_path, padding, scored, gaps, eligible):
    directory = validate.validation_dir(tmp_path)
    directory.mkdir()
    trips, predictions = [], {}
    modes = ("drift-anchor", "troll-slow", "troll-pelagic")
    for i in range(30):
        trip_id = f"{i:032x}"
        mmsi = 999_000_000 + i
        start = T0 + i * MINUTE
        mode = modes[i % len(modes)]
        label_start, label_end = start, start + MINUTE
        prediction = mode
        if i >= 3 and padding == "gap":
            prediction = "gap"
        if i >= 3 and padding == "sub-minute":
            # No minute boundary falls inside this otherwise nonempty label.
            label_start, label_end = start + 1_000, start + 59_000
        if i == 29 and padding == "scored":
            # A non-fishing label with no derived segment is still a scored minute.
            mode, prediction = "transit", None
        predictions[mmsi] = [] if prediction is None else [Interval(start, start + MINUTE, prediction)]
        trips.append({
            "id": trip_id, "mmsi": mmsi, "source": "aisstream", "departed_at": iso_utc(start),
            "depart_port_id": "port-a" if i < 3 else "port-b",
            "labels": [{"started_at": iso_utc(label_start), "ended_at": iso_utc(label_end),
                        "label": mode, "labeller": "admin-test"}],
        })
        pos = AisPosition(mmsi, start, 0.0, 0.0, None, None, None, None, "PositionReport", "aisstream", start)
        validate._copy(directory / f"{trip_id}.sqlite", [pos])
    (directory / validate.LABELS_FILE).write_text(json.dumps({"trips": trips}), encoding="utf-8")

    with patch.object(validate, "predict", side_effect=lambda positions, *_: predictions[positions[0].mmsi]):
        result = validate.report(REGION, tmp_path, labeller="admin", now_ms=T0)

    assert result["minutes"] == {"labelled": scored + gaps, "scored": scored, "gap_unscored": gaps}
    assert all(mode["met"] for mode in result["target"]["per_mode"].values())
    assert result["target"]["met"] is eligible
    assert result["trips"] == {"scored": scored, "missing": 0, "ports": 2 if eligible else 1}
    assert result["coverage"]["ports"] == ({"port-a": 3, "port-b": 27} if eligible else {"port-a": 3})
