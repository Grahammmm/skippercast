"""Audit repro paths obey the same survey isolation as the GIS layer."""
from tests import _support


def test_audit_collection_is_gated_before_import(tmp_path, monkeypatch):
    directory = tmp_path/'audit_repro'
    directory.mkdir()
    monkeypatch.delenv(_support.REQUIRE_GIS, raising=False)
    monkeypatch.setattr(_support, 'missing_gis_packages', lambda: ['rasterio'])
    assert _support.ignore_gis_directory(directory)
    monkeypatch.setenv(_support.REQUIRE_GIS, '1')
    assert not _support.ignore_gis_directory(directory)
    monkeypatch.delenv(_support.REQUIRE_GIS)
    monkeypatch.setattr(_support, 'missing_gis_packages', lambda: [])
    assert not _support.ignore_gis_directory(directory)


def test_audit_repros_get_gis_marker_and_unit_tests_do_not(tmp_path):
    class Item:
        def __init__(self, path):
            self.path = path
            self.keywords = {}
            self.markers = []
        def add_marker(self, marker):
            self.markers.append(marker.name)
    audit = Item(tmp_path/'audit_repro/test_synthetic.py')
    unit = Item(tmp_path/'unit/test_synthetic.py')
    _support.mark_items([audit, unit], tmp_path)
    assert audit.markers == ['gis']
    assert unit.markers == []
