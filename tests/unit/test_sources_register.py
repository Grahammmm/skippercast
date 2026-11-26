"""The generated Sources register on dist/sources.html (scripts/build_sources_register.py).

Offline. Fixture trees are tiny copies of the layout the generator reads (catalog/, regions/, dist/), built under tmp_path;
nothing writes into the repository. Each test names the contract it protects and the believable bug that breaks it.
"""
import json
import re
import shutil
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


def row(ident, name=None, display: str | None = 'allowed', **extra):
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

def test_c3_committed_page_is_fresh_and_credits_morro_contours(capsys):
    """C3: A stale page or a generator that drops the live contour layer leaves Morro without its credits."""
    current, fresh, _ = bsr.build(ROOT)
    assert current == fresh
    assert bsr.splice(fresh, bsr.render(bsr.collect(ROOT))[0]) == fresh  # second run: same bytes
    morro = re.search(r'<h4 id="region-morro-bay">.*?</h4>(.*?)(?=<h[34]\b)', current, re.S)
    assert morro is not None
    contours, = re.findall(r'<h5>Depth contours</h5>\s*<ul>(.*?)</ul>', morro[1], re.S)
    # The committed Morro contour set decides which surveys the page must credit: ft-v1 (USGS 2008 grids) until the
    # Morro v2 data lands, then ft-v3 (the 2022 NOAA lidar and BlueTopo, whose files state no survey date).
    contour_set = json.loads((ROOT / 'catalog/depth-contours/morro-bay.geojson').read_text())['provenance'].get('set')
    if contour_set == 'ft-v3':
        assert re.findall(r'<strong>([^<]+)</strong>', contours) == [
            '2022 NOAA Morro Bay topobathy lidar DEM',
            'NOAA BlueTopo bathymetry',
        ]
        assert contours.count('Date: survey date not stated') == 2
    else:
        assert re.findall(r'<strong>([^<]+)</strong>', contours) == [
            'Point Buchon bathymetry and seafloor character',
            'Morro Bay bathymetry and seafloor character',
            'Point Estero bathymetry and seafloor character',
        ]
    assert bsr.main(['--check', '--root', str(ROOT)]) == 0
    assert capsys.readouterr().err == ''


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
    assert 'Protected areas source' not in section(unused, 'data-sources-live')
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
    assert 'Protected areas source' not in section(fresh, 'data-sources-live')


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


def test_kelp_rows_are_held_until_kelp_3_and_the_generator_states_no_credit_of_its_own(tmp_path):
    """Contract: KELP-3 owns kelp credits, so a row needing kelp prints no credit, usage line or eligible line, even when public_display is allowed and a live layer binds it. Bug caught: the credit printed early, or a hand-typed kelp credit or source-id allowlist in the generator."""
    text = (ROOT / 'scripts/build_sources_register.py').read_text()
    assert 'Sandoval' not in text and 'cdfw-kelp' not in text  # keyed on catalogue needs, not a copied id or credit
    assert bsr.HELD_NEEDS == {'kelp': 'KELP-3'}
    rows = [row('kelp-src', 'Kelp row', needs=['kelp']), row('mixed-src', 'Mixed row', needs=['bathymetry', 'kelp']),
            row('mpa-src', 'MPA row'), row('cdfw-mpas', 'Bound row')]
    fresh, summary = generated(tmp_path, rows, [region('r1', 'Region One', bound=True)])
    assert 'kelp-src' not in fresh and 'mixed-src' not in fresh and 'Kelp row' not in fresh and 'Mixed row' not in fresh
    assert 'KELP-3' not in fresh and 'kelp' not in section(fresh, 'data-sources-live').lower()
    assert 'Credit for mpa-src' in fresh and 'Credit for cdfw-mpas' in fresh  # other rows are untouched
    assert summary['eligible_unused'] == 1 and summary['listed_live'] == 1
    assert bsr.held(rows[0]) == 'KELP-3' and bsr.held(rows[2]) is None


def test_real_page_never_prints_the_cdfw_kelp_credit_or_any_kelp_need_row():
    """Contract: the committed page carries no row that needs kelp (CDFW 2016 canopy, Kelpwatch) and no Sandoval kelp credit before KELP-3. Bug caught: the hold dropped or the page left stale after regeneration."""
    page = (ROOT / 'dist/sources.html').read_text()
    block = page[page.index(bsr.BEGIN):page.index(bsr.END)]
    data = bsr.collect(ROOT)
    kelp_rows = [source for source in data['sources'].values() if 'kelp' in source['needs']]
    assert kelp_rows
    for source in kelp_rows:
        assert f"<strong>{bsr._esc(source['name'])}</strong>" not in block, source['id']
        assert bsr._esc(source['rights']['attribution']) not in block, source['id']
    assert 'Sandoval' not in block and 'aerial kelp canopy' not in block


def add_relief_pointer(root, ids=('synthetic-grid',), *, region_id='r1'):
    fixtures = ROOT / 'tests/fixtures/relief/pointer-style'
    directory = root / 'catalog/relief'
    directory.mkdir()
    for name in ('pointer.schema.json', 'README.md'):
        shutil.copyfile(ROOT / 'catalog/relief' / name, directory / name)
    document = json.loads((fixtures / 'v1.json').read_text())
    source = document['sources'][0]
    source.update(label='Pointer-only label', attribution='Pointer-only credit', survey_dates=['Pointer-only date'])
    source['rights']['attribution'] = 'Pointer-only rights credit'
    document.update(region=region_id, sources=[{**source, 'id': ident} for ident in ids])
    document['detail_summary']['depth_bands'][0]['source_id'] = ids[0]
    path = directory / 'synthetic-review.json'  # The document, not the filename, determines the region.
    path.write_text(json.dumps(document))
    return path


def test_c1_depth_shading_lists_unique_catalogue_sources_in_pointer_order(tmp_path):
    """C1: A filename-based join, alphabetical sort, or pointer-text renderer gives the wrong region or credits."""
    rows = [row('z-grid', 'Z grid'), row('a-grid', 'A grid', display=None), row('held-row', needs=['kelp'])]
    rows[0]['rights']['attribution'] = 'Survey & agency'
    root = make_root(tmp_path, rows, [region('r0', 'Other Region'), region('r1', 'Region One')])
    add_relief_pointer(root, ('z-grid', 'a-grid', 'z-grid'))
    _, fresh, summary = bsr.build(root)
    assert bsr.collect(root)['regions'][1]['layers'] == {'Depth shading': {'z-grid': '', 'a-grid': ''}}
    live = section(fresh, 'data-sources-live')
    assert re.findall(r'<h4 id="region-([^"]+)">([^<]+)</h4>', live) == [('r0', 'Other Region'), ('r1', 'Region One')]
    assert re.findall(r'<h5>([^<]+)</h5>', live) == ['Depth shading']
    assert re.findall(r'<strong>([^<]+)</strong>.*?Credit: ([^<]+?) · <a ', live, re.S) == [
        ('Z grid', 'Survey &amp; agency'), ('A grid', 'Credit for a-grid'),
    ]
    assert 'Pointer-only' not in fresh and 'held-row' not in fresh
    assert summary == {'listed_live': 2, 'eligible_unused': 0, 'withheld_live': 0}


def test_c1_reviewed_pointer_does_not_list_a_draft_regions_other_assets(tmp_path):
    """C1: A reviewed pointer is listed on its own; treating it as region activation leaks draft asset usage."""
    root = make_root(tmp_path, [row('synthetic-grid'), row(BOUND_SOURCE)],
                     [region('r1', 'Region One', status='draft', bound=True)])
    add_relief_pointer(root)
    _, fresh, summary = bsr.build(root)
    live = section(fresh, 'data-sources-live')
    assert re.findall(r'<h4 id="region-([^"]+)">([^<]+)</h4>', live) == [('r1', 'Region One (draft region)')]
    assert re.findall(r'<h5>([^<]+)</h5>', live) == ['Depth shading']
    assert re.findall(r'<strong>([^<]+)</strong>', live) == ['Source synthetic-grid']
    assert summary == {'listed_live': 1, 'eligible_unused': 1, 'withheld_live': 0}


@pytest.mark.parametrize('rows, problem', [
    pytest.param([], 'unknown source', id='C2: unknown source'),
    pytest.param([row('synthetic-grid', display='private')], 'unlistable source', id='C2: private source'),
    pytest.param([row('synthetic-grid', display='excluded')], 'unlistable source', id='C2: excluded source'),
    pytest.param([row('synthetic-grid', display=None, publication_allowed=False)], 'unlistable source', id='C2: denied legacy source'),
    pytest.param([row('synthetic-grid', needs=['kelp'])], 'unlistable source', id='C2: held source'),
])
def test_c2_pointer_sources_must_be_listable(tmp_path, rows, problem):
    """C2: Filtering bad rows during rendering instead of failing would conceal missing or barred credits."""
    root = make_root(tmp_path, rows, [region('r1', 'Region One')])
    add_relief_pointer(root)
    with pytest.raises(bsr.RegisterError) as caught:
        bsr.build(root)
    assert type(caught.value) is bsr.RegisterError
    assert str(caught.value) == f"r1: depth shading has {problem} 'synthetic-grid'"


def test_c2_pointer_must_pass_the_schema(tmp_path):
    """C2: Reading just region and source IDs accepts an unreviewed pointer with valid-looking references."""
    root = make_root(tmp_path, [row('synthetic-grid')], [region('r1', 'Region One')])
    path = add_relief_pointer(root)
    document = json.loads(path.read_text())
    path.write_text(json.dumps({**document, 'status': 'draft'}))
    with pytest.raises(bsr.RegisterError, match=r'r1:.*synthetic-grid.*invalid relief metadata at status') as caught:
        bsr.build(root)
    assert type(caught.value) is bsr.RegisterError


def test_c2_malformed_json_names_the_pointer_when_no_region_or_id_can_be_read(tmp_path):
    """C2: Broken JSON must not be ignored or escape the generator as a parser exception."""
    root = make_root(tmp_path, [row('synthetic-grid')], [region('r1', 'Region One')])
    add_relief_pointer(root).write_text('{')
    with pytest.raises(bsr.RegisterError, match=r'synthetic-review\.json: invalid relief pointer') as caught:
        bsr.build(root)
    assert type(caught.value) is bsr.RegisterError


def test_c2_pointer_region_requires_a_config(tmp_path):
    """C2: An orphaned but schema-valid pointer must not silently disappear from the page."""
    root = make_root(tmp_path, [row('synthetic-grid')], [region('r1', 'Region One')])
    add_relief_pointer(root, region_id='missing-region')
    with pytest.raises(bsr.RegisterError) as caught:
        bsr.build(root)
    assert type(caught.value) is bsr.RegisterError
    assert str(caught.value) == "missing-region: no region config for depth shading sources 'synthetic-grid'"


@pytest.mark.parametrize('extra_usage', [False, True], ids=['C3: agreement', 'C3: disagreement'])
def test_c3_pointer_usage_counts_without_masking_a_runtime_mismatch(tmp_path, monkeypatch, extra_usage):
    """C3: Omitting relief from expected usage rejects good builds; disabling comparison admits actual drift."""
    root = make_root(tmp_path, [row('synthetic-grid')], [region('r1', 'Region One')])
    add_relief_pointer(root)
    (root / 'web').mkdir()
    (root / 'web/map.ts').write_text('const tiles = "https://tile.openstreetmap.org/{z}/{x}/{y}.png";\n')
    if extra_usage:
        scan = bsr.contract.usages

        def usages():
            found, unmapped, cache = scan()
            return found | {(BOUND_PATH, 'synthetic-grid')}, unmapped, cache

        monkeypatch.setattr(bsr.contract, 'usages', usages)
        with pytest.raises(bsr.RegisterError) as caught:
            bsr.build(root)
        assert type(caught.value) is bsr.RegisterError
        assert str(caught.value) == ('live usage disagrees with tests/contract/test_commercial_sources.py usages(): '
                                     'synthetic-grid')
    else:
        _, fresh, summary = bsr.build(root)
        assert summary == {'listed_live': 2, 'eligible_unused': 0, 'withheld_live': 0}
        live = section(fresh, 'data-sources-live')
        assert re.findall(r'<strong>([^<]+)</strong>', live) == ['Source synthetic-grid', 'OpenStreetMap standard tiles']


def add_contours(root, ids=('contour-grid',), *, region_id='r1'):
    path = root / 'catalog/depth-contours' / f'{region_id}.geojson'
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps({
        'type': 'FeatureCollection', 'features': [],
        'provenance': {'region_id': region_id, 'sources': [
            {'source_id': ident, 'name': 'Contour-only name', 'attribution': 'Contour-only credit',
             'url': 'https://example.org/contour-only', 'survey_date': 'Contour-only date'} for ident in ids
        ]},
    }))
    return path


def test_c1_contour_provenance_credits_only_its_catalogue_members(tmp_path):
    """C1: Reading the relief schema, using bindings instead of provenance, or rendering file credits all miscredit the layer."""
    rows = [row('z-grid', display=None), row('a-grid'), row('shade-grid')]
    root = make_root(tmp_path, rows, [region('r1', 'Region One'), region('r2', 'Region Two')])
    add_contours(root, ('z-grid', 'a-grid', 'z-grid'))
    add_relief_pointer(root, ('shade-grid',))
    assert {r['id']: r['layers'] for r in bsr.collect(root)['regions']} == {
        'r1': {'Depth contours': {'z-grid': '', 'a-grid': ''}, 'Depth shading': {'shade-grid': ''}},
        'r2': {},
    }
    _, page, summary = bsr.build(root)
    live = section(page, 'data-sources-live')
    assert re.findall(r'<h5>([^<]+)</h5>', live) == ['Depth contours', 'Depth shading']
    assert re.findall(r'<strong>([^<]+)</strong>.*?Credit: ([^<]+?) · <a ', live, re.S) == [
        ('Source z-grid', 'Credit for z-grid'), ('Source a-grid', 'Credit for a-grid'),
        ('Source shade-grid', 'Credit for shade-grid'),
    ]
    assert 'Contour-only' not in page and 'contour-only' not in page
    assert summary == {'listed_live': 3, 'eligible_unused': 0, 'withheld_live': 0}


# ---- M43: the committed page states survey dates the way the reviewed stage overlay does ---------------------------------

def test_m43_depth_layers_state_checked_survey_dates_and_never_free_text(tmp_path):
    """M43: production serves the committed page, so it must say what the reviewed /sources overlay said.

    Bug caught: v2 Morro credits on production without "survey date not stated" (or with free text from a file).
    """
    rows = [row('lidar'), row('topo'), row('dated', survey_year=2008), row('shade')]
    root = make_root(tmp_path, rows, [region('r1', 'Region One')])
    add_contours(root, ('lidar', 'topo', 'dated'))
    path = root / 'catalog/depth-contours/r1.geojson'
    document = json.loads(path.read_text())
    for entry, date in zip(document['provenance']['sources'], ('unstated', '2019-06', '2008')):
        entry['survey_date'] = date
    path.write_text(json.dumps(document))
    pointer = add_relief_pointer(root, ('shade', 'lidar'))
    document = json.loads(pointer.read_text())
    document['sources'][0]['survey_dates'] = ['unstated']
    document['sources'][1]['survey_dates'] = ['2019', '2021']
    pointer.write_text(json.dumps(document))
    layers = {r['id']: r['layers'] for r in bsr.collect(root)['regions']}['r1']
    assert layers == {
        'Depth contours': {'lidar': 'survey date not stated', 'topo': 'survey 2019-06', 'dated': ''},
        'Depth shading': {'shade': 'survey date not stated', 'lidar': ''},
    }
    _, page, _ = bsr.build(root)
    live = section(page, 'data-sources-live')
    assert live.count('Date: survey date not stated') == 2
    assert 'Date: survey 2019-06' in live and live.count('Date: survey 2008') == 1
    assert 'Contour-only' not in page and 'Pointer-only' not in page


def test_m43_a_file_date_that_contradicts_the_catalogue_fails_generation(tmp_path):
    """M43: a catalogue date renders from the catalogue, so the contour file must agree with it (the overlay's rule)."""
    root = make_root(tmp_path, [row('dated', survey_year=2008)], [region('r1', 'Region One')])
    path = add_contours(root, ('dated',))
    document = json.loads(path.read_text())
    document['provenance']['sources'][0]['survey_date'] = '2009'
    path.write_text(json.dumps(document))
    with pytest.raises(bsr.RegisterError, match=r"r1: depth contours source 'dated' records survey dates \['2009'\]"):
        bsr.collect(root)


@pytest.mark.parametrize('catalog, values', [
    pytest.param({}, ['unstated'], id='unstated'),
    pytest.param({}, ['2019'], id='one date'),
    pytest.param({}, ['2019', '2021'], id='two dates'),
    pytest.param({}, ['unstated', '2019'], id='mixed'),
    pytest.param({'survey_year': 2008}, ['2008'], id='catalogue date'),
])
def test_m43_register_and_stage_overlay_agree_on_every_date_case(catalog, values):
    """M43: one rule for preview and production; a drift between the two copies shows up here."""
    from scripts.relief import morro_sources_overlay as overlay
    sources = {'grid': row('grid', **catalog)}
    expected = overlay._credits(sources, [('grid', 'Credit for grid', values)])
    assert bsr._survey_extras(sources, 'r1', 'Depth contours', [('grid', values)]) == expected


@pytest.mark.parametrize('ident, rows, problem', [
    pytest.param('osm-tiles', [], 'unknown', id='C1: runtime-only id'),
    pytest.param('contour-grid', [row('contour-grid', display='private')], 'unlistable', id='C1: private id'),
    pytest.param('contour-grid', [row('contour-grid', needs=['kelp'])], 'unlistable', id='C1: held id'),
])
def test_c1_uncreditable_contour_sources_fail_generation(tmp_path, ident, rows, problem):
    """C1: Unknown and unlistable IDs must not get fallback credits or disappear silently."""
    root = make_root(tmp_path, rows, [region('r1', 'Region One')])
    add_contours(root, (ident,))
    with pytest.raises(bsr.RegisterError) as caught:
        bsr.build(root)
    assert type(caught.value) is bsr.RegisterError
    assert str(caught.value) == f'r1: depth contours has {problem} source {ident!r}'


@pytest.mark.parametrize('provenance, problem', [
    pytest.param({'region': 'r1', 'sources': [{'id': 'contour-grid'}]}, 'invalid contour provenance',
                 id='C1: relief shape is not contour provenance'),
    pytest.param({'region_id': 'r2', 'sources': [{'source_id': 'contour-grid'}]}, 'invalid contour region or source IDs',
                 id='C1: wrong region'),
    pytest.param({'region_id': 'r1', 'sources': []}, 'invalid contour region or source IDs', id='C1: empty source list'),
    pytest.param({'region_id': 'r1', 'sources': [{'source_id': 'contour-grid'}], 'publication_held': True},
                 'depth contours are held', id='C1: held contour file'),
])
def test_c1_invalid_contour_provenance_fails_generation(tmp_path, provenance, problem):
    """C1: A misbound, unusable or explicitly held file must not be treated as live credits."""
    root = make_root(tmp_path, [row('contour-grid')], [region('r1', 'Region One'), region('r2', 'Region Two')])
    path = add_contours(root)
    path.write_text(json.dumps({'type': 'FeatureCollection', 'features': [], 'provenance': provenance}))
    with pytest.raises(bsr.RegisterError, match=f'r1\\.geojson: {problem}') as caught:
        bsr.build(root)
    assert type(caught.value) is bsr.RegisterError


def test_c2_region_anchors_are_unique_and_stable_under_name_changes(tmp_path):
    """C2: An anchor based on the title or layer would change on rename or collide for two regions with the same title."""
    rows = [row(BOUND_SOURCE), row('contour-grid')]
    root = make_root(tmp_path, rows, [region('r1', 'Shared name', bound=True), region('r2', 'Shared name')])
    add_contours(root, region_id='r2')
    for names in [('Shared name', 'Shared name'), ('New name', 'Shared name')]:
        _, page, _ = bsr.build(root)
        assert re.findall(r'<h4 id="(region-[^"]+)">([^<]+)</h4>', page) == list(zip(('region-r1', 'region-r2'), names))
        ids = re.findall(r'\bid="([^"]+)"', page)
        assert len(ids) == len(set(ids))
        (root / 'regions/r1/region.json').write_text(json.dumps(region('r1', 'New name', bound=True)))


# ---- drift guards on the real repository ----------------------------------------------------------------------------

def test_every_displayable_real_source_is_on_the_page_and_no_private_one_is():
    """Contract: the committed page lists every public_display=allowed row and none marked private/excluded. Bug caught: a filter that drops rows, or leaks a held one."""
    page = (ROOT / 'dist/sources.html').read_text()
    data = bsr.collect(ROOT)
    for ident, source in data['sources'].items():
        display = source['rights'].get('public_display')
        mark = f"<strong>{bsr._esc(source['name'])}</strong>"
        if bsr.held(source):
            assert mark not in page, ident  # held until its release task (kelp: KELP-3)
        elif display == 'allowed':
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


def test_runtime_service_credits_are_specific_and_never_point_at_missing_text():
    """Contract: each runtime service prints its own credit; a 'see ... above' pointer is only allowed where that page text exists.
    Bug caught: the NOAA ENC service pointing readers at a 'Map and software' credit that names only OpenStreetMap."""
    page = (ROOT / 'dist/sources.html').read_text(encoding='utf-8')
    software = page.split('<h2>Map and software</h2>')[1].split('<h2', 1)[0]
    for ident, info in bsr.RUNTIME_SERVICE_INFO.items():
        assert info.get('credit'), ident
        if 'see Map and software above' in info['credit']:
            assert info['provider'].split()[0] in software, ident
    assert 'Credit: NOAA Office of Coast Survey, Electronic Navigational Charts (ENC)' in page
    assert 'NOAA ENC Display service</strong>' in page
    assert 'Credit: see Map and software above' not in page


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
