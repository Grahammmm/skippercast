"""Synthetic controls for the side diagnostic, not jurisdiction evidence."""

import json

import pytest
from shapely.geometry import Polygon, mapping

from scripts.relief.border_side_probe import main


@pytest.mark.parametrize(
    ("vertices", "exit_code", "observed"),
    [
        # A blanket refusal or binary inside/outside classification fails this control.
        pytest.param([(0, 0), (4, 0), (4, 4)], 0, ("inside", "outside", "on-edge"),
                     id="positive-correct-side-with-ambiguous-edge"),
        # Checking only the bounding box (or trusting the table) misses this reflection.
        pytest.param([(4, 0), (0, 0), (0, 4)], 1, ("outside", "inside", "on-edge"),
                     id="negative-mirror-with-identical-bbox"),
    ],
)
def test_border_side_probe(tmp_path, capsys, vertices, exit_code, observed):
    geometry = Polygon(vertices)
    assert geometry.bounds == (0, 0, 4, 4)  # Both inputs present identical bounds.
    path = tmp_path / "synthetic.geojson"
    path.write_text(json.dumps(mapping(geometry)), encoding="utf-8")

    # The two decisive probes share a latitude and sit inside both bounding boxes.
    # The centre is on both diagonals; it must not count as inside or outside.
    assert main([str(path), "--inside", "3.5", "3", "--outside", "0.5", "3",
                 "--on-edge", "2", "2"]) == exit_code
    report = capsys.readouterr().out.splitlines()
    assert [tuple(row.split("\t")) for row in report[1:]] == [
        ("3.5", "3.0", "inside", observed[0]),
        ("0.5", "3.0", "outside", observed[1]),
        ("2.0", "2.0", "on-edge", observed[2]),
    ]
