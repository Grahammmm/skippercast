"""All coverage contributors carry deployment-qualified producer terms."""
import json
import pytest
from skippercast.platform.contracts import atomic_json, read_json
from skippercast.seafloor import publish
from skippercast.seafloor.io import sha256
from skippercast.seafloor.rights import CSUMB_CREDIT
from tests.contract.test_seafloor_source_rights import csumb_row
from tests.gis.test_pending_publication_identity import pending_root
from tests._support import NOW


@pytest.mark.parametrize('case', ['noncommercial', 'paid', 'missing-policy', 'unknown-id', 'missing-id', 'reference'])
def test_cell_rights_at_region_boundary(tmp_path, monkeypatch, case):
    folder = pending_root(tmp_path)
    row = dict(csumb_row(), id='csumb')
    atomic_json(tmp_path/'catalog/surveys.json', {'surveys': [row]})
    if case != 'missing-policy':
        paid = case == 'paid'
        atomic_json(tmp_path/'deployments/production.json',
                    {'source_use': 'for-profit' if paid else 'noncommercial',
                     'monetization': 'paid' if paid else 'none'})
    cell = {'id': '3310:0:0', 'reach': 'r01', 'tier': 1, 'band_area_m2': 62500, 'source_id': 'csumb'}
    if case == 'unknown-id': cell['source_id'] = 'absent'
    if case == 'missing-id': cell.pop('source_id')
    if case == 'reference': cell.update(tier=0, source_id='unknown')
    atomic_json(folder/'coverage-cells.json', {'cells': [cell]})
    cp = read_json(folder/'coverage-checkpoint.json')
    cp.update(catalog_sha256=sha256(tmp_path/'catalog/surveys.json'),
              cells_sha256=sha256(folder/'coverage-cells.json'))
    atomic_json(folder/'coverage-checkpoint.json', cp)
    # Isolate the rights gate from the separately tested physical identity gate.
    monkeypatch.setattr(publish, 'current_physical_input_hash', lambda *a: cp['physical_input_hash'])
    if case in {'paid', 'missing-policy', 'unknown-id', 'missing-id'}:
        match = 'For-profit' if case in {'paid', 'missing-policy'} else 'attribution is incomplete'
        with pytest.raises(ValueError, match=match):
            publish.region_layers(tmp_path, 'synthetic', rerun=False)
    else:
        layers, _, _ = publish.region_layers(tmp_path, 'synthetic', rerun=False)
        rights = json.loads(layers['cells'][0]['properties']['source_rights'])
        if case == 'reference': assert rights == []
        else: assert rights[0]['attribution'] == CSUMB_CREDIT


def test_build_rechecks_cell_rights_before_archive(tmp_path, monkeypatch):
    atomic_json(tmp_path/'catalog/surveys.json', {'surveys': [dict(csumb_row(), id='csumb')]})
    atomic_json(tmp_path/'deployments/production.json', {'source_use': 'for-profit', 'monetization': 'paid'})
    layers = {'habitat': [], 'cells': [{'properties': {'tier': 1, 'source_id': 'csumb', 'source_rights': '[]'}}]}
    monkeypatch.setattr(publish, 'region_layers', lambda *a, **k: (layers, {}, NOW))
    import scripts.build_map_tiles as tiles
    monkeypatch.setattr(tiles, 'build_vector_archive', lambda *a, **k: pytest.fail('must refuse before archive writes'))
    with pytest.raises(ValueError, match='For-profit'):
        publish.build('synthetic', root=tmp_path, tool='synthetic')
    assert not (tmp_path/'var/seafloor/public').exists()
