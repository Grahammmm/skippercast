import json

import pytest

from skippercast.platform.contracts import indexed, load_catalogs

NEED = {"id": "synthetic-need"}
SOURCE = {
    "id": "synthetic-source",
    "needs": ["synthetic-need"],
    "documentation_url": "https://example.org/docs",
    "review_status": "approved",
    "rights": {"license": "CC0-1.0", "commercial_use": "allowed", "attribution_required": False},
}
SCALARS = [None, [], "x", 5, True]


def doc(key, rows):
    return {"schema_version": 1, key: rows}


def write(root, needs, sources):
    (root / "catalog").mkdir(exist_ok=True)
    (root / "catalog/data-needs.json").write_text(json.dumps(needs))
    (root / "catalog/sources.json").write_text(json.dumps(sources))


@pytest.mark.parametrize("key", ["needs", "sources"])
def test_empty_object_or_string_is_not_empty_list(key):
    for bad in ({}, ""):
        with pytest.raises(ValueError, match="expected a list"):
            indexed(doc(key, bad), key)


@pytest.mark.parametrize("key", ["needs", "sources"])
def test_roots_and_collections_fail_as_valueerror(key):
    for root in SCALARS:
        with pytest.raises(ValueError, match="expected an object"):
            indexed(root, key)
    with pytest.raises(ValueError, match="expected a list"):
        indexed({"schema_version": 1}, key)
    for bad in [None, {}, "x", 5, True]:
        with pytest.raises(ValueError, match="expected a list"):
            indexed(doc(key, bad), key)


@pytest.mark.parametrize("key", ["needs", "sources"])
def test_rows_and_id_types_fail_before_regex(key):
    good = {"id": "good-row"}
    for bad in SCALARS:
        rows = [good, bad]
        before = json.dumps(rows)
        with pytest.raises(ValueError, match="expected object rows"):
            indexed(doc(key, rows), key)
        assert json.dumps(rows) == before
    for bad in [None, [], {}, 5, True]:
        with pytest.raises(ValueError, match="Invalid or duplicate"):
            indexed(doc(key, [good, {"id": bad}]), key)


@pytest.mark.parametrize("key", ["needs", "sources"])
def test_valid_rows_keep_order_and_identity(key):
    a, b = {"id": "zeta-row"}, {"id": "alpha-row"}
    result = indexed(doc(key, [a, b]), key)
    assert list(result) == ["zeta-row", "alpha-row"]
    assert result["zeta-row"] is a and result["alpha-row"] is b
    assert indexed(doc(key, []), key) == {}


def test_file_backed_healthy_and_malformed(tmp_path):
    write(tmp_path, doc("needs", [NEED]), doc("sources", [SOURCE]))
    before = (tmp_path / "catalog/sources.json").read_bytes()
    needs, sources = load_catalogs(tmp_path)
    assert list(needs) == ["synthetic-need"] and list(sources) == ["synthetic-source"]
    assert (tmp_path / "catalog/sources.json").read_bytes() == before
    write(tmp_path, doc("needs", [NEED]), doc("sources", {}))
    with pytest.raises(ValueError, match="sources catalog: expected a list"):
        load_catalogs(tmp_path)
    write(tmp_path, doc("needs", ""), doc("sources", [SOURCE]))
    with pytest.raises(ValueError, match="needs catalog: expected a list"):
        load_catalogs(tmp_path)
    write(tmp_path, [], doc("sources", [SOURCE]))
    with pytest.raises(ValueError, match="needs catalog: expected an object"):
        load_catalogs(tmp_path)
    write(tmp_path, doc("needs", [NEED]), doc("sources", [None]))
    with pytest.raises(ValueError, match="expected object rows"):
        load_catalogs(tmp_path)
    write(tmp_path, doc("needs", [NEED]), doc("sources", []))
    assert load_catalogs(tmp_path)[1] == {}


def test_existing_refusals_still_apply(tmp_path):
    with pytest.raises(ValueError, match="Unsupported needs schema"):
        indexed({"schema_version": 2, "needs": []}, "needs")
    for rows in ([{}], [{"id": "Bad Id"}], [{"id": "dup-row"}, {"id": "dup-row"}]):
        with pytest.raises(ValueError, match="Invalid or duplicate"):
            indexed(doc("needs", rows), "needs")
    write(tmp_path, doc("needs", [NEED]), doc("sources", [{**SOURCE, "needs": ["other-need"]}]))
    with pytest.raises(ValueError, match="Unknown need"):
        load_catalogs(tmp_path)
    bad_rights = {**SOURCE, "rights": {"license": "unknown", "commercial_use": "allowed", "attribution_required": False}}
    write(tmp_path, doc("needs", [NEED]), doc("sources", [bad_rights]))
    with pytest.raises(ValueError, match="Unresolved redistribution"):
        load_catalogs(tmp_path)
    (tmp_path / "catalog/data-needs.json").write_text('{"schema_version": 1, "schema_version": 1, "needs": []}')
    with pytest.raises(ValueError):
        load_catalogs(tmp_path)
    (tmp_path / "catalog/data-needs.json").write_text('{"schema_version": NaN, "needs": []}')
    with pytest.raises(ValueError, match="Non-finite"):
        load_catalogs(tmp_path)
