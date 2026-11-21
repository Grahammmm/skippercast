"""Prior-feed receipts must identify the bytes used for carry-forward."""
import hashlib
import json
from unittest.mock import patch

import pytest

from scripts import refresh_regions
from skippercast.runs import RunManifest
from tests._support import FIXTURES, NOW


@pytest.mark.parametrize('kind', ['daily', 'live'])
@pytest.mark.parametrize('has_regional', [False, True], ids=['alias-only', 'regional-wins'])
def test_manifest_records_only_the_prior_feed_passed_to_the_collector(tmp_path, monkeypatch, kind, has_regional):
    # Reconstructing the regional path dropped alias-only receipts. Recording both
    # candidates would also misstate provenance when the regional copy wins.
    monkeypatch.chdir(tmp_path)
    ident = 'morro-bay'
    region = {'id': ident, 'species': []}
    previous = tmp_path / 'previous'
    regional = previous / 'regions' / ident / 'latest.json'
    regional.parent.mkdir(parents=True)
    alias = previous / 'latest.json'
    alias.write_bytes(b'{ "origin": "alias" }\n')
    if has_regional:
        regional.write_bytes(b'{ "origin": "regional" }\n')
    chosen = regional if has_regional else alias
    prior_bytes = chosen.read_bytes()
    feed = json.loads((FIXTURES / 'feeds' / f'{kind}-latest.json').read_text())
    run = RunManifest(f'refresh-{kind}', '1')

    with patch.object(refresh_regions, kind, return_value=feed) as collector, \
            patch.object(refresh_regions, 'coverage', return_value={'species': {}}):
        refresh_regions.refresh_region(kind, region, tmp_path / 'output', previous, NOW, ident, run)

    collector.assert_called_once_with(NOW, json.loads(prior_bytes), region_id=ident)
    path = refresh_regions.write_manifest(run, tmp_path / 'runs', 0)
    assert path is not None
    manifest = json.loads(path.read_text())
    assert manifest['inputs'] == [{
        'path': chosen.relative_to(tmp_path).as_posix(),
        'bytes': len(prior_bytes),
        'sha256': hashlib.sha256(prior_bytes).hexdigest(),
    }]
