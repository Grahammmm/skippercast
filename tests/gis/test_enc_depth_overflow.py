"""Depth validation through the real private ENC preflight."""
import json

import pytest

from skippercast.relief import receipts
from tests.gis.test_relief_enc import LAYER, REGION, _enc, _json, extract  # noqa: F401 (fixture)


@pytest.mark.parametrize('depth', [10**400, 12.5], ids=['oversized', 'finite'])
def test_private_enc_chart_depth(extract, tmp_path, depth):
    # The oversized integer is valid JSON, but math.isfinite cannot convert it
    # to a float. Pin the modified extract so the test reaches depth validation.
    root, manifest, report, _ = extract
    file = root / 'out/east.OBSTRN.geojson'
    doc = json.loads(file.read_bytes())
    doc['features'][1]['properties'].update(VALSOU=depth, enc_depth_unit_code=2)
    east = next(row for row in report['reaches'] if row['id'] == 'east')
    east['files']['OBSTRN']['sha256'] = _json(file, doc)
    _json(manifest, report)

    out = tmp_path / 'private-output'
    region = receipts.Region(out, REGION)
    result = _enc(root, out)
    if depth == 10**400:
        assert result.returncode == receipts.EXIT_CODES['blocked'], result.stdout + result.stderr
        assert '[enc] BLOCKED: east.OBSTRN.geojson feature 1: invalid chart depth' in result.stdout
        assert result.stderr == ''
        assert not out.exists()  # Neither an attempt receipt nor a layer was created.
    else:
        assert result.returncode == 0, result.stdout + result.stderr
        layer = json.loads((region.dir / LAYER).read_bytes())
        assert layer['private_only'] is True and layer['publication_allowed'] is False
        [props] = [feature['properties'] for feature in layer['features']
                   if feature['properties']['kind'] == 'OBSTRN' and not feature['properties']['fish_haven']]
        assert props['chart_depth'] == depth
        assert props['chart_depth_unit_code'] == 2
        assert props['depth_label'] == 'Estimate from chart soundings'
