"""build_home_ports checks every port before writing and writes through a temp file (RF0450-5)."""
import copy
import importlib.util
import json
import pathlib
import shutil

import pytest

from research.lib.paths import ROOT

SPEC = importlib.util.spec_from_file_location('build_home_ports', ROOT / 'research/scripts/build_home_ports.py')
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)

CATALOG = json.loads((ROOT / 'catalog/home-ports.json').read_text())
INDEX = json.loads((ROOT / 'dist/regions/index.json').read_text())


@pytest.fixture
def root(tmp_path):
    for rel in ['catalog/home-ports.json', 'dist/regions/index.json'] + ['dist/' + r['config'] for r in INDEX['regions']]:
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / rel, tmp_path / rel)
    (tmp_path / 'dist/data').mkdir(parents=True, exist_ok=True)
    return tmp_path


def write_ports(root, ports):
    source = copy.deepcopy(CATALOG)
    source['ports'] = ports
    (root / 'catalog/home-ports.json').write_text(json.dumps(source))


def output(root):
    return root / 'dist/data/home-ports.json'


def ports():
    return copy.deepcopy(CATALOG['ports'])


def test_real_catalog_bytes_match_committed_output(root):
    mod.build(root)
    assert output(root).read_bytes() == (ROOT / 'dist/data/home-ports.json').read_bytes()
    assert not output(root).with_suffix('.json.tmp').exists()


def test_missing_id_names_index_and_leaves_existing_output(root):
    output(root).write_bytes(b'previous\n')
    rows = ports()
    del rows[1]['id']
    write_ports(root, rows)
    with pytest.raises(ValueError, match=r'^Port 1 missing id$'):
        mod.build(root)
    assert output(root).read_bytes() == b'previous\n'


@pytest.mark.parametrize('field,value', [('name', ''), ('region', 7), ('forecast_point', None)])
def test_bad_text_field_names_index_and_field(root, field, value):
    rows = ports()
    rows[0][field] = value
    write_ports(root, rows)
    with pytest.raises(ValueError, match=rf'^Port 0 missing {field}$'):
        mod.build(root)


def test_port_that_is_not_an_object_is_named(root):
    write_ports(root, ports()[:2] + ['crescent-city'])
    with pytest.raises(ValueError, match=r'^Port 2 missing id$'):
        mod.build(root)


def test_duplicate_and_unknown_region_are_separate_messages(root):
    rows = ports()
    write_ports(root, rows + [copy.deepcopy(rows[0])])
    with pytest.raises(ValueError, match=r'^Duplicate port: ' + rows[0]['id'] + '$'):
        mod.build(root)
    rows[2]['region'] = 'no-such-region'
    write_ports(root, rows)
    with pytest.raises(ValueError, match=r'^Unknown region for port: ' + rows[2]['id'] + '$'):
        mod.build(root)


@pytest.mark.parametrize('match', [[True, -121], [35], ['35', -121], [float('nan'), -121],
                                   [35, float('inf')], [35, -121, 0], None, {'lat': 35}])
def test_match_must_be_two_finite_numbers(root, match):
    rows = ports()
    if match is None:
        del rows[0]['match']
    else:
        rows[0]['match'] = match
    write_ports(root, rows)
    with pytest.raises(ValueError, match=r'^Port match must be two numbers: ' + rows[0]['id'] + '$'):
        mod.build(root)


def test_bad_last_port_writes_nothing(root):
    rows = ports()
    rows[-1]['forecast_point'] = 'no-such-point'
    write_ports(root, rows)
    with pytest.raises(ValueError, match=r'^Unknown forecast point for port: ' + rows[-1]['id'] + '$'):
        mod.build(root)
    assert not output(root).exists()
    assert not output(root).with_suffix('.json.tmp').exists()


def test_outside_california_message_unchanged(root):
    rows = ports()
    rows[0]['match'] = [45.0, -124.0]
    write_ports(root, rows)
    with pytest.raises(ValueError, match=r'^Port match location outside California: ' + rows[0]['id'] + '$'):
        mod.build(root)


def test_valid_temp_catalog_written_and_equal_to_return(root, monkeypatch):
    rows = ports()[:3]
    rows.append(dict(rows[0], id='second-in-region', match=[41.0, -124.0]))
    write_ports(root, rows)
    reads = []
    real = pathlib.Path.read_text
    monkeypatch.setattr(pathlib.Path, 'read_text', lambda self, *a, **k: reads.append(self.name) or real(self, *a, **k))
    result = mod.build(root)
    assert json.loads(output(root).read_text()) == result
    assert [p['id'] for p in result['ports']] == [r['id'] for r in rows]
    assert reads.count('region.json') == 3
    assert not output(root).with_suffix('.json.tmp').exists()
