"""Offline checks for depth confidence on individual /sources region entries."""
import json
import re

import pytest

from scripts import build_sources_register as register
from tests.unit.test_sources_register import BOUND_SOURCE, add_contours, add_relief_pointer, make_root, region, row


@pytest.fixture
def pointer_tree(tmp_path):
    root = make_root(tmp_path, [row('fine-grid'), row('coarse-grid'), row('compiled-grid')],
                     [region(ident, ident) for ident in ('mixed', 'measured', 'contours-only')])
    measured_path = add_relief_pointer(root, ('fine-grid',), region_id='measured')
    measured = json.loads(measured_path.read_text())
    measured['sources'][0].update(label='measured', estimated=False)
    measured['detail_summary']['depth_bands'][0].update(resolution_m=1, support_class=2)
    measured['native_support_by_zoom']['8']['sources'] = [{'id': 'fine-grid', 'resolution_m': 1, 'tiles': 1}]
    measured_path.write_text(json.dumps(measured))

    mixed_path = measured_path.with_name('other-review.json')
    mixed = json.loads(measured_path.read_text())
    mixed.update(region='mixed', minzoom=14, maxzoom=16)
    fine = mixed['sources'][0]
    mixed['sources'] += [{**fine, 'id': 'coarse-grid'},
                         {**fine, 'id': 'compiled-grid', 'label': 'estimated', 'estimated': True}]
    band = mixed['detail_summary']['depth_bands'][0]
    band.update(support_class=3)
    mixed['detail_summary']['depth_bands'] += [
        {**band, 'source_id': ident, 'resolution_m': grid, 'support_class': 2}
        for ident, grid in [('coarse-grid', 5), ('coarse-grid', 2), ('compiled-grid', 4), ('compiled-grid', 8)]
    ]
    mixed['native_support_by_zoom'] = {
        '14': {'tiles': 3, 'limit_m': 91.44, 'sources': [
            {'id': ident, 'resolution_m': grid, 'tiles': 1}
            for ident, grid in [('coarse-grid', 5), ('compiled-grid', 4), ('coarse-grid', 2)]
        ]},
        '15': {'tiles': 1, 'limit_m': 91.44, 'sources': [{'id': 'coarse-grid', 'resolution_m': 2.0, 'tiles': 1}]},
        '16': {'tiles': 1, 'limit_m': 20, 'support_class': 3,
               'sources': [{'id': 'fine-grid', 'resolution_m': 1, 'tiles': 1}]},
    }
    mixed_path.write_text(json.dumps(mixed))
    add_contours(root, ('coarse-grid',), region_id='contours-only')
    return root, measured_path


def _region_depth_lines(page, region_id):
    entry, = re.findall(rf'<h4 id="region-{region_id}">[^<]*</h4>(.*?)(?=<h[34]\b)', page, re.S)
    return re.findall(r'<p>(Depth detail: [^<]*)</p>', entry)


def test_public_region_fragments_survive_without_listable_credits(tmp_path):
    """Skipping empty layers strands public links; globbing configs or crediting held rows leaks details."""
    root = make_root(tmp_path, [row(BOUND_SOURCE, 'Withheld source', display='private')], [
        region('empty', 'Empty Bay'),
        region('filtered', 'Filtered Bay', bound=True),
        region('candidate', 'Candidate Bay', status='draft', bound=True),
    ])
    _, page, _ = register.build(root)
    for ident, name in [('empty', 'Empty Bay'), ('filtered', 'Filtered Bay')]:
        assert page.count(f'id="region-{ident}"') == 1
        entry, = re.findall(rf'<h4 id="region-{ident}">{name}</h4>(.*?)(?=<h[34]\b)', page, re.S)
        assert entry.strip() == '<p>No sources are listed for this region.</p>'
    for hidden in ('region-candidate', 'Candidate Bay', 'Withheld source', BOUND_SOURCE):
        assert hidden not in page


def test_c1_depth_detail_is_region_local_and_uses_confidence_words_only(pointer_tree):
    """C1: Cross-region evidence, duplicate grids, or promoting an estimated or uncertified grid misstates detail (C2 copy)."""
    root, _ = pointer_tree
    _, page, _ = register.build(root)
    assert _region_depth_lines(page, 'mixed') == ['Depth detail: 1 m measured, 2 m, 5 m, estimated']
    assert _region_depth_lines(page, 'measured') == ['Depth detail: 1 m']
    assert _region_depth_lines(page, 'contours-only') == []


@pytest.mark.parametrize('estimated, expected', [
    pytest.param(False, 'Depth detail: not stated', id='C2: valid pointer with no usable confidence evidence'),
    pytest.param(True, 'Depth detail: estimated', id='C1: estimated without native support'),
])
def test_c2_no_native_sizes_do_not_imply_no_survey(pointer_tree, estimated, expected):
    """C2: A depth band or nodata mask is not a native size or evidence of unsurveyed water."""
    root, path = pointer_tree
    document = json.loads(path.read_text())
    document['native_support_by_zoom']['8']['sources'] = []
    document['sources'][0].update(estimated=estimated, label='estimated' if estimated else 'measured')
    path.write_text(json.dumps(document))
    _, page, _ = register.build(root)
    assert _region_depth_lines(page, 'measured') == [expected]


def test_c2_missing_required_native_support_refuses_before_rendering(pointer_tree):
    """C2: A rejected pointer must raise RegisterError, not be rendered as 'not stated'."""
    root, path = pointer_tree
    document = json.loads(path.read_text())
    del document['native_support_by_zoom']
    path.write_text(json.dumps(document))
    with pytest.raises(register.RegisterError, match=r"'native_support_by_zoom' is a required property") as error:
        register.build(root)
    assert type(error.value) is register.RegisterError


def test_c3_check_detects_stale_region_confidence_until_regeneration(pointer_tree):
    """C3: A pointer-only change must invalidate the generated page, even when the credits are unchanged."""
    root, path = pointer_tree
    args = ['--root', str(root)]
    assert register.main(args) == 0
    assert register.main(['--check', *args]) == 0
    document = json.loads(path.read_text())
    document['native_support_by_zoom']['8']['sources'] = []
    path.write_text(json.dumps(document))
    assert register.main(['--check', *args]) == 1
    assert register.main(args) == 0
    assert register.main(['--check', *args]) == 0
