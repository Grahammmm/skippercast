"""Native C1 notices cannot silently become C5 legal-clearance declarations."""
from copy import deepcopy
import pytest
from research.scripts.coast_mvp.coast_c1_preview import rights_page, validate_manifest


def manifest_fixture():
    return {
        'schema_version': 1, 'units': 'm', 'value_convention': 'elevation_positive_up',
        'contributor_cells': {'1': 10, '2': 0}, 'stats': {'valid_cells': 10},
        'limitations': ['Unstated datum remains unresolved.'],
        'sources': [
            {'id': 'synthetic-a', 'code': 1, 'rights': 'Terms not verified; no clearance',
             'attribution': 'Synthetic institution <not HTML>', 'citation': 'https://example.org/source',
             'sha256': 'a' * 64, 'vertical_datum': 'unstated',
             'offset_note': 'Zero offset is not a datum conversion', 'path': '/private/not-displayed'},
            {'id': 'unused', 'code': 2},
        ],
    }


def test_native_notices_and_all_caveats_preserved():
    manifest = manifest_fixture()
    before = deepcopy(manifest)
    html = rights_page(manifest, 'b' * 64)
    assert manifest == before
    for item in ('NOT FOR NAVIGATION', 'review_required', 'Terms not verified; no clearance',
                 'commercial permission unresolved', 'CSUMB', 'for-profit', 'Unstated datum remains unresolved.',
                 'Zero offset is not a datum conversion', 'b' * 64, 'a' * 64):
        assert item in html
    assert 'Synthetic institution &lt;not HTML&gt;' in html
    assert '/private/not-displayed' not in html
    assert 'data-source="unused"' not in html
    assert html.count('data-source=') == 1


@pytest.mark.parametrize('change', [
    lambda m: m.update(schema_version=True),
    lambda m: m.update(units='ft'),
    lambda m: m['contributor_cells'].update({'1': True}),
    lambda m: m['contributor_cells'].update({'1': -1}),
    lambda m: m['contributor_cells'].update({'3': 0}),
    lambda m: m['sources'][0].update(rights=''),
    lambda m: m['sources'][0].update(citation='javascript:alert(1)'),
    lambda m: m['sources'][0].update(citation='https://user:pass@example.org'),
    lambda m: m['sources'][0].update(sha256='not-a-hash'),
    lambda m: m['sources'][1].update(code=1),
    lambda m: m['sources'][1].update(id='synthetic-a'),
    lambda m: m['stats'].update(valid_cells=11),
])
def test_refuses_missing_or_inconsistent_metadata(change):
    manifest = manifest_fixture()
    change(manifest)
    with pytest.raises(ValueError):
        validate_manifest(manifest)


def test_html_is_inert_and_escaped():
    manifest = manifest_fixture()
    manifest['sources'][0]['rights'] = '<script>alert(1)</script>'
    html = rights_page(manifest, 'b' * 64)
    assert '<script>' not in html
    assert '&lt;script&gt;' in html
    assert 'Content-Security-Policy' in html
    with pytest.raises(ValueError, match='manifest SHA'):
        rights_page(manifest, 'bad')
