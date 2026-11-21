"""The relief stage and platform publisher enforce the same set-aware byte limits."""
import json
from types import SimpleNamespace

import pytest

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
