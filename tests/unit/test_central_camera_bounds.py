import json

import pytest

from scripts.relief import central_camera_bounds
from tests._support import ROOT


CENTRAL_COAST = (
    'big-sur-coast', 'cambria-san-simeon', 'south-big-sur-san-simeon',
    'monterey-point-sur', 'point-arguello-conception', 'santa-cruz-monterey-bay',
)


def test_reports_every_configured_camera_in_the_six_regions(monkeypatch, capsys):
    # A missing region, omitted preview, or reused region box would misreport
    # the checked-in recipes. Derive expectations from the files so correcting
    # a camera later does not require keeping the current outliers in this test.
    monkeypatch.setenv('SKIPPERCAST_ROOT', str(ROOT))
    result = central_camera_bounds.main([])
    heading, *lines = capsys.readouterr().out.splitlines()
    assert 'center check only' in heading and 'not window extent or data coverage' in heading

    expected = {}
    for region in CENTRAL_COAST:
        directory = ROOT / 'regions' / region
        west, south, east, north = json.loads((directory / 'region.json').read_text())['bounds']
        previews = json.loads((directory / 'render.json').read_text())['previews']
        assert previews, region
        for preview in previews:
            lon, lat = preview['center']
            inside = (lon, lat) == (sorted((west, lon, east))[1], sorted((south, lat, north))[1])
            expected[f"{region}/{preview['id']}"] = [
                'IN_BOUNDS' if inside else 'OUT_OF_BOUNDS',
                f'center=({lon}, {lat})', f"size_m={preview['size_m']}", f"zoom={preview['zoom']}",
            ]
    actual = {}
    for line in lines:
        status, camera, fields = line.split(maxsplit=2)
        actual[camera] = [status, *fields.rsplit(maxsplit=2)]
    assert len(lines) == len(expected)
    assert actual == expected
    assert result == int(any(fields[0] == 'OUT_OF_BOUNDS' for fields in expected.values()))


@pytest.mark.parametrize(
    ('center', 'status', 'exit_code'),
    [
        pytest.param([-121.5, 35.2], 'IN_BOUNDS', 0, id='edge-outside-fishing-bounds'),
        pytest.param([-121.5, 36.2], 'OUT_OF_BOUNDS', 1, id='swapped-region-center'),
    ],
)
def test_checks_only_the_center_against_its_own_region(
    tmp_path, monkeypatch, capsys, center, status, exit_code,
):
    # A legal center on the region edge (but outside fishing bounds) must pass
    # even though its window crosses that edge; a valid center from the next
    # region with the same longitude must fail, naming its recipe and preview.
    monkeypatch.setenv('SKIPPERCAST_ROOT', str(tmp_path))
    (tmp_path / 'schemas').mkdir()
    schema = 'sc-render-v1.schema.json'
    (tmp_path / 'schemas' / schema).write_bytes((ROOT / 'schemas' / schema).read_bytes())
    (tmp_path / 'style').mkdir()
    (tmp_path / 'style/index.json').write_bytes((ROOT / 'style/index.json').read_bytes())

    for region, south, camera in (
        ('big-sur-coast', 35, center), ('monterey-point-sur', 36, [-121.5, 36.2]),
    ):
        directory = tmp_path / 'regions' / region
        directory.mkdir(parents=True)
        (directory / 'region.json').write_text(json.dumps({
            'bounds': [-121.5, south, -121.0, south + 0.5],
            'fishing_bounds': [-121.4, south + 0.1, -121.1, south + 0.4],
        }))
        (directory / 'render.json').write_text(json.dumps({
            'schema': 'sc-render/1', 'region': region, 'piers': [],
            'previews': [{'id': 'review', 'center': camera, 'size_m': 2500, 'zoom': 12}],
        }))

    monkeypatch.setattr(central_camera_bounds, 'REGIONS', ('big-sur-coast', 'monterey-point-sur'))
    before = {p: p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    assert central_camera_bounds.main([]) == exit_code
    assert capsys.readouterr().out.splitlines()[1:] == [
        f'{status} big-sur-coast/review center=({center[0]}, {center[1]}) size_m=2500 zoom=12',
        'IN_BOUNDS monterey-point-sur/review center=(-121.5, 36.2) size_m=2500 zoom=12',
    ]
    assert {p: p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()} == before


def test_missing_recipe_is_not_reported_as_a_default_camera(tmp_path, monkeypatch, capsys):
    # A deleted recipe must not silently pass on the shared loader's fallback.
    monkeypatch.setenv('SKIPPERCAST_ROOT', str(tmp_path))
    directory = tmp_path / 'regions' / 'big-sur-coast'
    directory.mkdir(parents=True)
    (directory / 'region.json').write_text(json.dumps({
        'bounds': [-121.5, 35, -121.0, 35.5],
        'fishing_bounds': [-121.4, 35.1, -121.1, 35.4],
    }))
    with pytest.raises(SystemExit) as error:
        central_camera_bounds.main([])
    assert error.value.code == 2
    captured = capsys.readouterr()
    assert 'big-sur-coast: missing render.json' in captured.err
    assert 'fishing-z11' not in captured.out
