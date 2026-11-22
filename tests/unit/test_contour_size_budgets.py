"""The relief stage and platform publisher enforce the same set-aware byte limits."""
import json
from types import SimpleNamespace

import pytest

from skippercast import style
from skippercast.platform import depth_contours as dc
from skippercast.relief import contours, receipts


def _encoded(value):
    return (json.dumps(value, ensure_ascii=False, separators=(',', ':')) + '\n').encode()


def _pair(contour_set, full_bytes, overview_bytes):
    provenance = {'bounds': [0, 0, 1, 1], 'features': 2}
    if contour_set is not None:
        provenance['set'] = contour_set
    # Only the first feature survives projection: the second is both short (v1)
    # and detail-only (v2/v3). Pad synthetic properties, not expensive geometry.
    visible = {'type': 'Feature', 'properties': {'minzoom': 11, 'padding': ''},
               'geometry': {'type': 'LineString', 'coordinates': [[0, 0], [1, 1]]}}
    detail = {'type': 'Feature', 'properties': {'minzoom': 15, 'padding': ''},
              'geometry': {'type': 'LineString', 'coordinates': [[0, 0], [0.0001, 0.0001]]}}
    full = {'type': 'FeatureCollection', 'provenance': provenance, 'features': [visible, detail]}
    visible['properties']['padding'] = 'x' * (overview_bytes - len(_encoded(dc.overview_contours(full))))
    detail['properties']['padding'] = 'x' * (full_bytes - len(_encoded(full)))
    return full, dc.overview_contours(full)


@pytest.fixture(params=['relief', 'platform'])
def writer(request, tmp_path, monkeypatch):
    if request.param == 'platform':
        paths = tuple(tmp_path / name for name in ('depth-contours.geojson', 'depth-contours-overview.geojson'))

        def publish(full, light):
            dc._stage_and_replace(paths[0], paths[1], full, light, 'synthetic-bay')

        return publish, paths, ValueError, '{name} for synthetic-bay is {size} bytes, over its {budget}-byte budget'

    paths = tuple(tmp_path / name for name in ('contours.geojson', 'contours-overview.geojson'))
    monkeypatch.setattr(dc, 'check_selected_contours', lambda *args, **kwargs: None)
    ctx = SimpleNamespace(contour_job=(None, {}, {}, [({'source_id': 'synthetic'},)]),
                          contour_view=None, contour_style=None)

    def write(full, _light):
        # Stand in for tracing only; exercise real projection, serialization and budget checks.
        if full['provenance'].get('set') == dc.FT_V3:
            ctx.contour_view = object()
            monkeypatch.setattr(contours, 'trace_v3', lambda *_: full)
        else:
            monkeypatch.setattr(contours, 'trace', lambda _: (full, {}))
        contours.build(ctx, tmp_path)

    return write, paths, receipts.ReceiptError, '{name} exceeds its byte budget ({size} bytes, budget {budget} bytes)'


@pytest.mark.parametrize(('contour_set', 'sizes', 'refusal'), [
    (dc.FT_V2, (1_600_000, 110_000), None),
    (dc.FT_V3, (1_600_000, 110_000), None),
    (None, (1_600_000, 110_000), (0, 1_000_000)),
    (None, (1_000_000, 110_000), (1, 64_000)),
    (None, (1_000_000, 64_000), None),
    (dc.FT_V2, (3_000_001, 300_000), (0, 3_000_000)),
    (dc.FT_V2, (3_000_000, 300_001), (1, 300_000)),
], ids=['v2', 'v3', 'legacy-full', 'legacy-overview', 'legacy-inclusive', 'v2-full', 'v2-overview'])
def test_contour_writer_applies_set_budget(writer, contour_set, sizes, refusal):
    # Catch either writer using unconditional legacy caps, relaxing legacy caps,
    # or skipping either limit. At the legacy boundary, output bytes stay unchanged.
    write, paths, error, message = writer
    pair = _pair(contour_set, *sizes)
    expected = tuple(_encoded(value) for value in pair)
    assert tuple(map(len, expected)) == sizes
    if refusal is None:
        write(*pair)
        assert tuple(path.read_bytes() for path in paths) == expected
    else:
        index, budget = refusal
        with pytest.raises(error) as exc:
            write(*pair)
        assert str(exc.value) == message.format(name=paths[index].name, size=sizes[index], budget=budget)


@pytest.fixture
def morro_pair(tmp_path, monkeypatch):
    view = style.load('nearshore-v1.0.0').view('contours')
    region = {'id': 'morro-bay', 'bounds': [0, 0, 1, 1]}
    sources = {ident: {'needs': ['bathymetry'], 'review_status': 'approved',
                       'rights': {'public_display': 'allowed'}} for ident in ('a', 'b')}
    common = {'survey_date': '2020', 'vertical_datum': 'MLLW'}
    tiers = list(dc.v3_tiers(view, 1, certified=True))
    low, detail, pier = tiers[0], tiers[-2], tiers[-1]
    wide = [[0.1123456789, 0.1], [0.4123456789, 0.1]]
    narrow = [[0.1123456789, 0.7], [0.2123456789, 0.7]]

    def feature(ident, source, tier_rule):
        tier, stop = tier_rule
        depth, index = next(iter(dc.v3_levels(tier).items()))
        return {'type': 'Feature', 'id': ident,
                'geometry': {'type': 'MultiLineString', 'coordinates': [narrow, wide]},
                'properties': {**common, 'kind': 'contour', 'estimated': True, 'native_cell_m': 1,
                               'source_id': source, 'tier': tier['name'], 'depth_ft': depth, 'index': index,
                               'minzoom': tier['min_zoom'], **({'maxzoom': stop} if stop is not None else {})}}

    features = [feature('z', 'a', low), feature('b', 'b', low), feature('a', 'a', low),
                feature('detail', 'a', detail), feature('pier', 'a', pier)]
    full = {'type': 'FeatureCollection', 'features': features, 'provenance': {
        'region_id': region['id'], 'bounds': region['bounds'], 'units': 'ft', 'set': dc.FT_V3,
        'contours': view.digest('contours'), 'shelf_limit_ft': dc.V2_SHELF_LIMIT_FT, 'features': len(features),
        'sources': [{**common, 'source_id': ident, 'sha256': '0' * 64, 'name': 'Côte'} for ident in sources]}}
    expected = {**full, 'features': [
        {**f, 'geometry': {**f['geometry'], 'coordinates': [wide]}} if f['id'] != 'pier' else f
        for f in features[1:]], 'provenance': {**full['provenance'], 'features': 4}}
    ctx = SimpleNamespace(contour_view=view, contour_style={},
                          contour_job=(None, region, sources, [({'source_id': ident},) for ident in sources]))
    monkeypatch.setattr(contours, 'trace_v3', lambda *_: full)
    return ctx, full, expected


@pytest.mark.parametrize('mode', ['overflow', 'inclusive', 'foreign', 'missing-group', 'protected'])
def test_morro_writer_whole_line_budget(morro_pair, mode, tmp_path, monkeypatch):
    # At the real writer, catch re-drawn/rounded lines, lost groups or pier
    # components, non-deterministic ties, and accidental thinning elsewhere.
    ctx, original, compacted = morro_pair
    result = original if mode == 'inclusive' else compacted
    expected = tuple(map(_encoded, (result, dc.overview_contours(result))))
    full_cap, overview_cap = map(len, expected)
    if mode == 'foreign':
        ctx.contour_job[1]['id'] = original['provenance']['region_id'] = 'other-bay'
    if mode == 'missing-group':
        overview_cap -= 1  # both low groups' shortest whole parts need the last byte (LF)
    if mode == 'protected':
        full_cap = len(_encoded({**compacted, 'features': [compacted['features'][-1]],
                                'provenance': {**compacted['provenance'], 'features': 1}})) - 1
    monkeypatch.setattr(dc, 'size_budgets', lambda _: (full_cap, overview_cap))
    errors = {'foreign': r'contours\.geojson exceeds its byte budget',
              'missing-group': r'contours-overview\.geojson exceeds its byte budget.*cannot retain group',
              'protected': r'contours\.geojson exceeds its byte budget.*protected.*pier'}
    if mode in errors:
        with pytest.raises(receipts.ReceiptError, match=errors[mode]):
            contours.build(ctx, tmp_path)
        if mode != 'foreign':
            assert not list(tmp_path.iterdir())
        return

    paths = tuple(tmp_path / name for name in ('contours.geojson', 'contours-overview.geojson'))
    for _ in range(2):
        metrics = contours.build(ctx, tmp_path)
        assert tuple(path.read_bytes() for path in paths) == expected
        assert dc.overview_contours(json.loads(paths[0].read_bytes())) == json.loads(paths[1].read_bytes())
        assert metrics['compacted'] is (mode == 'overflow')
        for name, lines, groups in (('full', 10, 4), ('overview', 6, 2)):
            stats = metrics[name]
            assert stats['original_groups'] == stats['retained_groups'] == groups
            assert stats['original_lines'] == lines
            assert stats['retained_lines'] == (groups + (name == 'full') if mode == 'overflow' else lines)
            assert sum(row['dropped'] for row in stats['dropped_lines_by_group']) == lines - stats['retained_lines']
