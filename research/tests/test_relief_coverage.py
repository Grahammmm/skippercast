import json

import pytest

from research.scripts.coast_mvp import relief_coverage as rc


def make_sector(root, name, natives=(), limit=91.44, cells=None, bad=None):
    d = root / name
    (d / "mosaic").mkdir(parents=True)
    cells = cells or {"1": 50, "2": 0}
    band = {"limit_m": limit, "cells": sum(cells.values()), "km2": 0.005,
            "contributor_cells": cells, "note": "n"}
    manifest = {"sources": [{"code": 1, "id": "fine"}, {"code": 2, "id": "coarse"}],
                "band_0_300ft": band}
    cov = {"limit_m": limit, "basis": "b", "background": {"cells": 1, "cell_m": 10, "km2": 0.0},
           "native": [{"id": i, "resolution_m": r, "cells": 1, "km2": k} for i, r, k in natives]}
    if bad != "manifest":
        (d / "mosaic" / "manifest.json").write_text(json.dumps(manifest))
    if bad == "nokey":
        (d / "mosaic" / "manifest.json").write_text(json.dumps({"sources": []}))
    if bad == "json":
        (d / "coverage.json").write_text("{nope")
    elif bad != "coverage":
        (d / "coverage.json").write_text(json.dumps(cov))
    return d


def run(tmp_path, sectors):
    args = [a for s in sectors for a in ("--sector", str(s))]
    return rc.main(args + ["--out-json", str(tmp_path / "o.json"), "--out-md", str(tmp_path / "o.md")])


def test_two_sectors_roll_up_without_summing_overlaps(tmp_path):
    a = make_sector(tmp_path, "a", [("n1", 1, 1.0), ("n2", 2, 0.6), ("n5", 5, 0.2)])
    b = make_sector(tmp_path, "b")
    assert run(tmp_path, [b, a]) == 0
    data = json.loads((tmp_path / "o.json").read_text())
    assert [s["sector"] for s in data["sectors"]] == ["a", "b"]
    row = data["sectors"][0]
    assert row["native"]["le_2m_km2"]["max"] == 1.0
    assert row["native"]["5m_km2"]["max"] == 0.2
    assert "1.6" not in json.dumps(data)
    assert data["sectors"][1]["native"]["le_2m_km2"]["max"] == 0.0


def test_background_codes_map_to_source_ids(tmp_path):
    a = make_sector(tmp_path, "a")
    run(tmp_path, [a])
    row = json.loads((tmp_path / "o.json").read_text())["sectors"][0]
    assert row["background_by_source"] == {"fine": 0.005, "coarse": 0.0}


@pytest.mark.parametrize("bad", ["coverage", "json", "nokey", "manifest"])
def test_missing_or_bad_input_exits_2_before_writing(tmp_path, capsys, bad):
    good = make_sector(tmp_path, "good")
    broken = make_sector(tmp_path, "broken", bad=bad)
    assert run(tmp_path, [good, broken]) == 2
    err = capsys.readouterr().err.strip().splitlines()
    assert len(err) == 1 and err[0].startswith("relief_coverage: broken:")
    assert not (tmp_path / "o.json").exists() and not (tmp_path / "o.md").exists()


def test_mixed_band_limit_is_refused(tmp_path, capsys):
    a = make_sector(tmp_path, "a", limit=60)
    assert run(tmp_path, [a]) == 2
    assert "relief_coverage: a:" in capsys.readouterr().err
    assert not (tmp_path / "o.json").exists()


def test_markdown_has_one_row_per_sector_and_the_overlap_note(tmp_path):
    a = make_sector(tmp_path, "a", [("n1", 1, 1.0)])
    b = make_sector(tmp_path, "b")
    run(tmp_path, [a, b])
    first = ((tmp_path / "o.json").read_bytes(), (tmp_path / "o.md").read_bytes())
    lines = [x for x in first[1].decode().splitlines() if x.startswith("|")]
    assert len(lines) == 2 + 2  # header, separator, two sectors
    assert "Best <=2 m source km²" in lines[0]
    assert rc.NOTE in first[1].decode()
    run(tmp_path, [a, b])
    assert first == ((tmp_path / "o.json").read_bytes(), (tmp_path / "o.md").read_bytes())
