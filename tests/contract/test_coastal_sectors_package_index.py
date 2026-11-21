"""Duplicate package IDs cannot change sector overlap through last-row wins."""
import json
from unittest.mock import patch

import pytest

from skippercast.platform import sectors
from tests._support import FIXTURES


@pytest.mark.parametrize('reverse', [False, True])
def test_duplicate_package_id_is_refused_before_region_reads_or_packet_write(tmp_path, reverse):
    scenario = json.loads((FIXTURES / 'sp1807_sector_endpoint/scenario.json').read_text())
    index = scenario['packages']
    package = index['regions'][0]
    # One row overlaps the coast; the other would silently exclude its atlas.
    index['regions'].append({**package, 'fishing_bounds': [-122, 37, -120, 38]})
    if reverse:
        index['regions'].reverse()

    inputs = {
        'catalog/coastal-sectors.json': scenario['source'],
        'catalog/coasts.json': scenario['coasts'],
        'dist/regions/index.json': index,
    }
    for name, value in inputs.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value))
    packet = tmp_path / 'dist/data/coastal-sectors.json'
    packet.parent.mkdir(parents=True)
    previous = b'{"existing_sector_packet":true}\n'
    packet.write_bytes(previous)

    read_json = sectors.read_json

    def read_input(path):
        assert path.relative_to(tmp_path).as_posix() in inputs, f'unexpected read: {path}'
        return read_json(path)

    with patch.object(sectors, 'read_json', read_input), patch.object(sectors, 'atomic_json') as write:
        with pytest.raises(ValueError) as refused:
            sectors.compile_sectors(tmp_path)
        write.assert_not_called()
    assert 'dist/regions/index.json' in str(refused.value)
    assert package['id'] in str(refused.value)
    assert 'duplicate' in str(refused.value).lower()
    assert packet.read_bytes() == previous
