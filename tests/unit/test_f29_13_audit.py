"""F29-13: only a complete PMEP acquisition may replace a regional preview."""
import io
import json
from urllib.parse import parse_qs, urlsplit

import pytest

pytestmark = pytest.mark.gis


@pytest.fixture
def preview(tmp_path, monkeypatch):
    from research.scripts import build_central_habitat_context as habitat
    from shapely.geometry import box, mapping

    region_id = "big-sur-coast"  # select the PMEP branch; all geometry is an invented grid
    asset_dir = f"regions/{region_id}"
    config = tmp_path / asset_dir / "region.json"
    prior = tmp_path / "dist" / asset_dir / "survey-habitat.geojson"
    config.parent.mkdir(parents=True)
    prior.parent.mkdir(parents=True)
    config.write_text(json.dumps({
        "status": "preview", "name": "Synthetic coast", "fishing_bounds": [0, 0, 1000, 1000],
        "mpa": {"minimum_features": 1}, "assets": {
            "protected_areas": f"{asset_dir}/protected.geojson",
            "survey_habitat": f"{asset_dir}/survey-habitat.geojson",
        },
    }))
    (prior.parent / "protected.geojson").write_text(json.dumps({
        "type": "FeatureCollection", "features": [{"geometry": mapping(box(700, 700, 800, 800))}],
    }))
    rows = {
        i: {"type": "Feature", "geometry": mapping(box(i * 150, 150, i * 150 + 100, 250)),
            "properties": {"OBJECTID": i, "NMFS_HAPC": "Rocky Reefs", "PMEP_Zone": "Core Zone",
                           "CMECS_SC_Name": "Synthetic rock"}}
        for i in (1, 2, 3)
    }
    prior.write_text(json.dumps({
        "type": "FeatureCollection",
        "features": [{**rows[i], "properties": {"source_id": f"pmep-hapc-{i}"}} for i in (1, 2)],
    }))
    monkeypatch.setattr(habitat, "ROOT", tmp_path)
    monkeypatch.setattr(habitat, "read", lambda path: json.loads((tmp_path / path).read_text()))
    monkeypatch.setattr(habitat, "TO_METERS", lambda x, y: (x, y))
    monkeypatch.setattr(habitat, "TO_WGS84", lambda x, y: (x, y))

    def run(*, count=2, ids=(1, 2), pages=None, metadata=None):
        def serve(request, *, timeout):
            args = parse_qs(urlsplit(request.full_url).query)
            assert args["geometry"] == ["0,0,1000,1000"]
            assert args["where"] == ["NMFS_HAPC='Rocky Reefs' AND (PMEP_Zone LIKE 'Core Zone%' OR PMEP_Zone LIKE 'Seaward Zone%')"]
            if "returnCountOnly" in args:
                data = {"count": count}
            elif "returnIdsOnly" in args:
                data = {"objectIds": list(ids), "objectIdFieldName": "OBJECTID"}
            else:
                batch = tuple(map(int, args["objectIds"][0].split(","))) if "objectIds" in args else ids
                returned = batch if pages is None else pages[batch]
                data = {"type": "FeatureCollection", "features": [rows[i] for i in returned], **(metadata or {})}
            return io.BytesIO(json.dumps(data).encode())

        monkeypatch.setattr(habitat, "urlopen", serve)
        habitat.build_region(region_id, None, None)

    return habitat, run, prior, config


@pytest.mark.parametrize("returned", [(1,), (1, 1), (1, 3)], ids=["short", "duplicate", "substitute"])
def test_incomplete_page_keeps_prior_preview(preview, returned):
    # A nonempty page (even with the correct row count) doesn't prove both IDs arrived.
    _, run, prior, config = preview
    before = prior.read_bytes(), config.read_bytes()
    with pytest.raises(ValueError, match="Incomplete PMEP feature page"):
        run(pages={(1, 2): returned})
    assert (prior.read_bytes(), config.read_bytes()) == before


@pytest.mark.parametrize("metadata", [{"exceededTransferLimit": True}, {"properties": {"exceededTransferLimit": True}}])
def test_transfer_limit_holds_even_when_page_ids_match(preview, metadata):
    # A flagged response is not a complete acquisition even if the returned ID set happens to match.
    _, run, prior, config = preview
    before = prior.read_bytes(), config.read_bytes()
    with pytest.raises(ValueError, match="truncated"):
        run(metadata=metadata)
    assert (prior.read_bytes(), config.read_bytes()) == before


@pytest.mark.parametrize("last_page", [(2,), ()], ids=["complete", "missing-final-page"])
def test_all_pages_required_before_replacing_preview(preview, monkeypatch, last_page):
    # A complete first page is not permission to write; on success, retain both pages.
    habitat, run, prior, config = preview
    monkeypatch.setattr(habitat, "PMEP_PAGE_SIZE", 1)
    pages = {(1,): (1,), (2,): last_page}
    if not last_page:
        before = prior.read_bytes(), config.read_bytes()
        with pytest.raises(ValueError, match="Incomplete PMEP feature page"):
            run(pages=pages)
        assert (prior.read_bytes(), config.read_bytes()) == before
        return
    run(pages=pages)
    output = json.loads(prior.read_text())
    assert output["source_kind"] == "PMEP compiled rocky-reef HAPC"
    assert {f["properties"]["source_id"] for f in output["features"]} == {"pmep-hapc-1", "pmep-hapc-2"}


@pytest.mark.parametrize(("count", "ids", "reason"), [
    (2, (1,), "Incomplete PMEP ID inventory"),
    (0, (), "PMEP query returned zero features"),
    (2_001, (), "exceeds regional ID budget"),
])
def test_non_buildable_inventories_keep_prior_preview(preview, count, ids, reason):
    # A partial or over-budget inventory may not replace the layer, and a true zero is distinct.
    _, run, prior, config = preview
    before = prior.read_bytes(), config.read_bytes()
    with pytest.raises(ValueError, match=reason):
        run(count=count, ids=ids, pages={})  # none of these cases should reach the feature query
    assert (prior.read_bytes(), config.read_bytes()) == before
