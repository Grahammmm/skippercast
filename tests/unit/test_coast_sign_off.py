"""Non-GIS boundary for coast sign-off (runs in the CI `check` job, no survey stack).

The full sign-off chain pins a producer-bound admission graph and therefore lives
in tests/gis/test_coast_sign_off_graph.py. These tests prove the non-GIS side:
the sign-off scripts and the shared contract factory import without pyproj or
shapely, prepare_round requests the shared v2 run/enqueue contracts, and the
generated admission schema enforces the single-selected vs window-set grid shapes.
"""
import importlib.util
import sys

import pytest
from jsonschema import Draft202012Validator

from tests._support import ROOT

SCRIPTS = ROOT / 'skills/coast-sign-off/scripts'
SHARED_SCRIPTS = ROOT / 'skills/coast-campaign-shared/scripts'
GIS_IMPORTS = ('pyproj', 'shapely', 'rasterio', 'numpy', 'scipy')


def fresh(name, directory, monkeypatch):
    spec = importlib.util.spec_from_file_location(name, directory / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def no_gis(monkeypatch):
    for name in GIS_IMPORTS:
        monkeypatch.setitem(sys.modules, name, None)  # import now raises ModuleNotFoundError
    with pytest.raises(ModuleNotFoundError):
        __import__('pyproj')
    return monkeypatch


def test_sign_off_scripts_and_factory_import_without_gis(no_gis):
    for name in ('coast_refs', 'coast_sample', 'coast_receipt_versions', 'coast_ledger', 'validate_coast_receipt'):
        fresh(name, SHARED_SCRIPTS, no_gis)
    for name in ('review_common', 'prepare_round', 'open_packet', 'write_verdict'):
        fresh(name, SCRIPTS, no_gis)
    import tests.coast_contract_factory as contract_factory  # module import itself needs no GIS
    assert 'admission' in contract_factory.schemas()


def test_prepare_round_requests_shared_v2_contracts(monkeypatch):
    for name in ('coast_refs', 'coast_sample', 'coast_receipt_versions', 'coast_ledger', 'validate_coast_receipt'):
        fresh(name, SHARED_SCRIPTS, monkeypatch)
    fresh('review_common', SCRIPTS, monkeypatch)
    prepare = fresh('prepare_round', SCRIPTS, monkeypatch)
    constants = set(prepare.prepare.__code__.co_consts)
    assert {'coast-run-summary-v2', 'coast-enqueue-receipt-v2'} <= constants
    assert not {'coast-run-summary-v1', 'coast-enqueue-receipt-v1'} & constants


def grid_schema():
    import tests.coast_contract_factory as contract_factory
    admission = contract_factory.schemas()['admission']
    return Draft202012Validator(admission['properties']['grids']['items'])


SINGLE = dict(source_id='s', grid_sha256='a' * 64, cols=1, rows=1, total=1,
              definition=dict(source_sha256='b' * 64, raster_crs='EPSG:3310', affine_transform=[1, 0, 0, 0, -1, 0],
                              width=4, height=4, tile_width=4, tile_height=4, tiling_version='single-selected-v1',
                              pixel_window=[0, 0, 4, 4]))
TILING = dict(tile=512, width=1024, height=512, origin=[0, 0], anchor=[-120.6, 34.46], cell=[1e-6, 1e-6])
WINDOW_SET = dict(source_id='s', grid_sha256='a' * 64, cols=2, rows=1, total=2,
                  definition=dict(source_sha256='b' * 64, raster_crs='EPSG:3310', affine_transform=[1, 0, 0, 0, -1, 0],
                                  width=1024, height=512, tile_width=512, tile_height=512, tiling_version='window-set-v1',
                                  tiling=TILING))


def test_admission_grid_schema_accepts_both_producer_shapes():
    schema = grid_schema()
    assert not list(schema.iter_errors(SINGLE))
    assert not list(schema.iter_errors(WINDOW_SET))


@pytest.mark.parametrize('grid', [
    dict(SINGLE, cols=2, total=2),                                          # single grid cannot claim a set
    dict(SINGLE, definition=dict(SINGLE['definition'], width=None)),        # the old flat/edited width shape
    dict(WINDOW_SET, definition=dict(WINDOW_SET['definition'], pixel_window=[0, 0, 4, 4])),  # mixed shapes
    dict(WINDOW_SET, definition={k: v for k, v in WINDOW_SET['definition'].items() if k != 'tiling'}),
    dict(WINDOW_SET, definition=dict(WINDOW_SET['definition'], tiling=dict(TILING, extra=1))),
    dict(SINGLE, width=4),                                                  # flat grid fields refused
])
def test_admission_grid_schema_refuses_malformed_shapes(grid):
    assert list(grid_schema().iter_errors(grid))
