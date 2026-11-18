"""The generated Sources register on dist/sources.html (scripts/build_sources_register.py).

Offline. Fixture trees are tiny copies of the layout the generator reads (catalog/, regions/, dist/), built under tmp_path;
nothing writes into the repository. Each test names the contract it protects and the believable bug that breaks it.
"""
import json
import re
import unittest.mock

import pytest

from scripts import build_sources_register as bsr
from skippercast.seafloor.rights import CSUMB_CREDIT
from tests._support import ROOT

PAGE_STUB = '''<main id="sources-content">
      <h1>Sources</h1>
      <p>Hand-written method text stays.</p>
      <h2>Current official checks</h2>
      <ul><li><a href="https://example.org/">Official</a></li></ul>
    </main>
'''
# Real asset bindings from tests/contract/test_commercial_sources.py ASSET_SOURCES: the fixture reuses them, it never copies them.
BOUND_PATH, BOUND_KIND, BOUND_SOURCE = 'data/protected-areas.geojson', 'protected_areas', 'cdfw-mpas'


def row(ident, name=None, display='allowed', **extra):
    rights = {'license': 'facts-only', 'attribution': f'Credit for {ident}', 'terms_url': f'https://example.org/{ident}/terms',
              'commercial_use': 'allowed', 'attribution_required': True}
    if display is not None:
        rights['public_display'] = display
    base = {'id': ident, 'name': name or f'Source {ident}', 'provider': f'Agency {ident}', 'needs': ['bathymetry'],
            'documentation_url': f'https://example.org/{ident}/about', 'adapter': 'vector', 'review_status': 'approved',
            'reviewed_at': '2026-09-01', 'rights': rights}
    base.update(extra)
    return base


def region(ident, name, status='active', bound=False):
    return {'schema_version': 1, 'id': ident, 'name': name, 'status': status, 'source_bindings': {},
            'assets': {BOUND_KIND: BOUND_PATH} if bound else {}}


def make_root(tmp_path, rows, regions, stub=PAGE_STUB):
    (tmp_path / 'catalog').mkdir()
    (tmp_path / 'catalog/data-needs.json').write_text(json.dumps({'schema_version': 1, 'needs': [
        {'id': 'bathymetry', 'name': 'Seabed depth and relief'}, {'id': 'kelp', 'name': 'Kelp canopy'}]}))
    (tmp_path / 'catalog/sources.json').write_text(json.dumps({'schema_version': 1, 'sources': rows}))
    for item in regions:
        (tmp_path / 'regions' / item['id']).mkdir(parents=True)
        (tmp_path / 'regions' / item['id'] / 'region.json').write_text(json.dumps(item))
    (tmp_path / 'dist/data').mkdir(parents=True)
    (tmp_path / 'dist' / BOUND_PATH).write_text('{"features": []}')
    (tmp_path / 'dist/sources.html').write_text(stub)
    return tmp_path


def generated(tmp_path, rows, regions):
    """(fresh page, summary) for a fixture tree in its own subfolder of tmp_path."""
    root = tmp_path / f'root{len(list(tmp_path.iterdir()))}'
    root.mkdir()
    make_root(root, rows, regions)
    current, fresh, summary = bsr.build(root)
    return fresh, summary


def section(page, anchor):
    """The text from one heading id to the next heading of the same or higher level."""
    start = page.index(f'id="{anchor}"')
    ends = [i for i in (page.find('<h3 ', start), page.find('</section>', start)) if i != -1]
    return page[start:min(ends)]


# ---- the committed page and the generator's modes -------------------------------------------------------------------

def test_committed_page_is_a_fresh_build_and_rerun_changes_nothing():
    """Contract: dist/sources.html equals the generator's output. Bug caught: the catalogue or a region binding changed and the page was not regenerated."""
    current, fresh, _ = bsr.build(ROOT)
    assert current == fresh
    assert bsr.splice(fresh, bsr.render(bsr.collect(ROOT))[0]) == fresh  # second run: same bytes


def test_check_mode_fails_on_stale_content_and_write_mode_repairs_it(tmp_path, capsys):
    """Contract: --check exits 1 on a stale page and 0 once rewritten. Bug caught: --check that only looks for the markers."""
    root = make_root(tmp_path, [row('a-src')], [region('r1', 'Region One')])
    assert bsr.main(['--root', str(root)]) == 0
    assert bsr.main(['--check', '--root', str(root)]) == 0
    page = (root / 'dist/sources.html').read_text()
    (root / 'dist/sources.html').write_text(page.replace('Credit for a-src', 'Credit for a-src, edited by hand'))
    assert bsr.main(['--check', '--root', str(root)]) == 1
    assert 'stale' in capsys.readouterr().err
    assert bsr.main(['--root', str(root)]) == 0
    assert bsr.main(['--check', '--root', str(root)]) == 0
    # A catalogue change with no regeneration is stale too.
    (root / 'catalog/sources.json').write_text(json.dumps({'schema_version': 1, 'sources': [row('a-src'), row('b-src')]}))
    assert bsr.main(['--check', '--root', str(root)]) == 1


def test_hand_written_page_text_and_structure_survive_regeneration(tmp_path):
    """Contract: only the marked block is generated; method text, tables, ids and headings elsewhere stay. Bug caught: the splice eats or duplicates surrounding sections."""
    fresh, _ = generated(tmp_path, [row('a-src')], [region('r1', 'Region One')])
    assert fresh.count('Hand-written method text stays.') == 1 and fresh.count('<h2>Current official checks</h2>') == 1
    assert fresh.count(bsr.BEGIN) == 1 and fresh.count(bsr.END) == 1
    assert fresh.index(bsr.END) < fresh.index('<h2>Current official checks</h2>')
    ids = re.findall(r'\bid="([^"]+)"', fresh)
    assert len(ids) == len(set(ids))


def test_real_page_keeps_its_tables_and_has_unique_ids():
    """Contract: the register adds lists, not tables (tests/test_static_info_a11y.mjs pins exactly two named table scrollers). Bug caught: a table inside the register."""
    page = (ROOT / 'dist/sources.html').read_text()
    assert len(re.findall(r'<table[\s>]', page)) == 2
    ids = re.findall(r'\bid="([^"]+)"', page)
    assert len(ids) == len(set(ids))
    assert '<main id="sources-content">' in page


def test_fragment_target_matches_the_maps_sources_link():
    """Contract: the map's one Sources link (#2747 SOURCES_HREF) lands on a real id. Bug caught: renaming the section id strands the link."""
    page = (ROOT / 'dist/sources.html').read_text()
    assert page.count('id="data-sources"') == 1
    assert re.search(r'<section id="data-sources" aria-labelledby="data-sources-heading">\s*<h2 id="data-sources-heading">', page)
    engine = ROOT / 'web/map/engine.ts'
    declared = re.search(r"SOURCES_HREF\s*=\s*'([^']+)'", engine.read_text()) if engine.is_file() else None
    if declared:  # present once #2747 is on main; until then the link target is the contract above
        assert declared.group(1) == '/sources#data-sources'


# ---- what is listed, and where --------------------------------------------------------------------------------------

def test_a_newly_used_source_moves_from_eligible_to_the_live_region_layer(tmp_path):
    """Contract: use is read from non-draft region bindings. Bug caught: the register lists by catalogue only, so a newly bound source stays 'not yet used'."""
    unused, _ = generated(tmp_path, [row(BOUND_SOURCE, 'Protected areas source')], [region('r1', 'Region One')])
    assert '<strong>Protected areas source</strong>' in section(unused, 'data-sources-eligible')
    assert 'data-sources-region-r1' not in unused
    used, summary = generated(tmp_path, [row(BOUND_SOURCE, 'Protected areas source')], [region('r1', 'Region One', bound=True)])
    live = section(used, 'data-sources-live')
    assert 'Region One' in live and '<h5>Protected areas</h5>' in live and '<strong>Protected areas source</strong>' in live
    assert '<strong>Protected areas source</strong>' not in section(used, 'data-sources-eligible')
    assert summary == {'listed_live': 1, 'eligible_unused': 0, 'withheld_live': 0}


def test_an_allowed_but_unused_source_is_listed_apart_with_its_credit_verbatim(tmp_path):
    """Contract: every public_display=allowed row appears, labelled as not yet used, with rights.attribution verbatim. Bug caught: allowed rows with no live use are dropped or shown as live."""
    credit = 'Smith & Jones, "Seabed survey" <2019>'
    idle = row('idle-src', 'Idle source')
    idle['rights']['attribution'] = credit
    fresh, summary = generated(tmp_path, [idle], [region('r1', 'Region One')])
    eligible = section(fresh, 'data-sources-eligible')
    assert 'no live layer uses them yet' in eligible and 'Seabed depth and relief' in eligible
    assert 'Credit: Smith &amp; Jones, &quot;Seabed survey&quot; &lt;2019&gt;' in eligible
    assert 'Idle source' not in section(fresh, 'data-sources-live')
    assert summary['eligible_unused'] == 1 and summary['listed_live'] == 0


def test_private_excluded_and_undecided_unused_rows_never_reach_the_page(tmp_path):
    """Contract: private/excluded rows stay off the page even when a live layer binds them; an undecided unused row is not eligible. Bug caught: listing by 'in the catalogue' or by 'used'."""
    rows = [row(BOUND_SOURCE, 'Private but bound', display='private'), row('gone-src', 'Excluded one', display='excluded'),
            row('quiet-src', 'Undecided unused', display=None), row('ok-src', 'Allowed one')]
    fresh, summary = generated(tmp_path, rows, [region('r1', 'Region One', bound=True)])
    for hidden in ('Private but bound', 'Excluded one', 'Undecided unused', 'Credit for ' + BOUND_SOURCE, 'Credit for gone-src', 'Credit for quiet-src'):
        assert hidden not in fresh
    assert '<strong>Allowed one</strong>' in fresh
    assert summary == {'listed_live': 0, 'eligible_unused': 1, 'withheld_live': 1}


def test_a_live_source_that_predates_display_decisions_is_credited_unless_publication_is_denied(tmp_path):
    """Contract: live use of an undecided row is a public use that needs its credit; publication_allowed:false still removes it. Bug caught: a live source with no credit anywhere, or a denied one shown."""
    fresh, summary = generated(tmp_path, [row(BOUND_SOURCE, 'Legacy live source', display=None)], [region('r1', 'Region One', bound=True)])
    assert '<strong>Legacy live source</strong>' in section(fresh, 'data-sources-live')
    denied, summary = generated(tmp_path, [row(BOUND_SOURCE, 'Legacy live source', display=None, publication_allowed=False)], [region('r1', 'Region One', bound=True)])
    assert 'Legacy live source' not in denied and summary['withheld_live'] == 1


def test_a_draft_region_and_its_name_do_not_leak(tmp_path):
    """Contract: only non-draft regions are read (contract.published_regions). Bug caught: globbing regions/*/region.json without the status filter."""
    regions = [region('r1', 'Region One'), region('hidden-draft', 'Secret Draft Bay', status='draft', bound=True)]
    fresh, _ = generated(tmp_path, [row(BOUND_SOURCE, 'Protected areas source')], regions)
    assert 'Secret Draft Bay' not in fresh and 'hidden-draft' not in fresh
    # Bound only by the draft region, the source is eligible, not live.
    assert '<strong>Protected areas source</strong>' in section(fresh, 'data-sources-eligible')
    assert 'Region One' not in section(fresh, 'data-sources-live')


def test_html_in_catalogue_text_and_links_is_escaped(tmp_path):
    """Contract: every catalogue string is escaped. Bug caught: f-string HTML without escaping lets a source name or URL inject markup."""
    evil = row('evil-src', 'Name <script>alert(1)</script> & "q"', documentation_url='https://example.org/a?x="><img src=x onerror=alert(1)>')
    evil['provider'] = '<b>Agency</b>'
    fresh, _ = generated(tmp_path, [evil], [region('r1', 'Region <i>One</i>')])
    assert '<script>' not in fresh and '<img' not in fresh and '<b>Agency' not in fresh and '<i>One' not in fresh
    assert 'Name &lt;script&gt;alert(1)&lt;/script&gt; &amp; &quot;q&quot;' in fresh
    assert 'href="https://example.org/a?x=&quot;&gt;&lt;img src=x onerror=alert(1)&gt;"' in fresh


def test_links_are_documentation_pages_never_archives_or_data_endpoints(tmp_path):
    """Contract: no raw-data link where redistribution is barred (or anywhere). Bug caught: linking archive_url or a file/ArcGIS-service documentation_url."""
    rows = [row('barred-a', 'Barred with archive', archive_url='https://example.org/files/raw-grid.tar.gz',
                documentation_url='https://example.org/files/grid.tif', publication_allowed=True),
            row('barred-b', 'Barred service only', documentation_url='https://example.org/arcgis/rest/services/X/MapServer/1'),
            row('plain-c', 'Plain page')]
    rows[1]['rights']['terms_url'] = 'https://example.org/arcgis/rest/services/X/MapServer/1'
    fresh, _ = generated(tmp_path, rows, [region('r1', 'Region One')])
    assert 'raw-grid' not in fresh and 'grid.tif' not in fresh and 'MapServer' not in fresh
    entries = {m.group(1): m.group(0) for m in re.finditer(r'<li><strong>([^<]+)</strong>.*?</li>', fresh, re.S)}
    assert 'href="https://example.org/barred-a/terms"' in entries['Barred with archive']  # falls back to the terms page
    assert '<a ' not in entries['Barred service only']
    assert 'href="https://example.org/plain-c/about"' in entries['Plain page']


def test_csumb_credit_is_the_canonical_text_once_and_only_while_csumb_rows_are_listed(tmp_path):
    """Contract: CSUMB_CREDIT (rights.py) appears once, not per row, and only when a CSUMB row is displayable; row credits stay verbatim. Bug caught: hand-typed credit, per-row repeats, or credit shown while the rows are private."""
    csumb = [row(f'csumb-blk{n}', f'CSUMB block {n}', provider='CSUMB Seafloor Mapping Lab') for n in range(3)]
    fresh, _ = generated(tmp_path, csumb, [region('r1', 'Region One')])
    assert fresh.count(CSUMB_CREDIT) == 1 and 'id="data-sources-credits"' in fresh
    assert 'Credit: Credit for csumb-blk2' in fresh
    private = [{**r, 'rights': {**r['rights'], 'public_display': 'private'}} for r in csumb]
    hidden, _ = generated(tmp_path, private, [region('r1', 'Region One')])
    assert CSUMB_CREDIT not in hidden and 'data-sources-credits' not in hidden


def test_generator_states_no_kelp_credit_of_its_own(tmp_path):
    """Contract: KELP-3 owns kelp credits. Bug caught: a hand-typed kelp credit in the generator; a kelp row shows only its register attribution."""
    assert 'kelp' not in (ROOT / 'scripts/build_sources_register.py').read_text().lower()
    fresh, _ = generated(tmp_path, [row('kelp-src', 'Kelp row', needs=['kelp'])], [region('r1', 'Region One')])
    assert fresh.count('Credit for kelp-src') == 1


# ---- drift guards on the real repository ----------------------------------------------------------------------------

def test_every_displayable_real_source_is_on_the_page_and_no_private_one_is():
    """Contract: the committed page lists every public_display=allowed row and none marked private/excluded. Bug caught: a filter that drops rows, or leaks a held one."""
    page = (ROOT / 'dist/sources.html').read_text()
    data = bsr.collect(ROOT)
    for ident, source in data['sources'].items():
        display = source['rights'].get('public_display')
        mark = f"<strong>{bsr._esc(source['name'])}</strong>"
        if display == 'allowed':
            assert mark in page, ident
            assert f"Credit: {bsr._esc(source['rights']['attribution'])}" in page, ident
        elif display in ('private', 'excluded'):
            assert mark not in page, ident


def test_register_follows_the_contract_usage_scan_and_names_every_runtime_service():
    """Contract: live use equals tests/contract usages(); a new runtime service needs a RUNTIME_SERVICE_INFO entry. Bug caught: a second, drifting notion of 'live'."""
    data = bsr.collect(ROOT)
    assert data['runtime']
    assert set(bsr.contract.RUNTIME_SERVICES) <= set(bsr.RUNTIME_SERVICE_INFO)
    with unittest.mock.patch.dict(bsr.contract.RUNTIME_SERVICES, {'brand-new-service': 'unknown'}):
        with pytest.raises(bsr.RegisterError, match='RUNTIME_SERVICE_INFO'):
            bsr.collect(ROOT)


def test_unmapped_live_asset_fails_generation(tmp_path):
    """Contract: an asset with no source mapping stops the build instead of being omitted. Bug caught: silently dropping a layer's sources."""
    root = make_root(tmp_path, [row('a-src')], [region('r1', 'Region One')])
    unknown = region('r2', 'Region Two')
    unknown['assets'] = {'survey_habitat': 'regions/r2/not-in-the-map.geojson'}
    (root / 'regions/r2').mkdir()
    (root / 'regions/r2/region.json').write_text(json.dumps(unknown))
    (root / 'dist/regions/r2').mkdir(parents=True)
    (root / 'dist/regions/r2/not-in-the-map.geojson').write_text('{"features": []}')
    with pytest.raises(bsr.RegisterError, match='r2'):
        bsr.collect(root)
