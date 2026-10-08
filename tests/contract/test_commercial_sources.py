"""Commercial-use gate for everything the product ships or calls at runtime.

Every asset bound in a non-draft ``regions/*/region.json``, every runtime
provider binding in those regions, and every runtime call to a known
third-party service in ``src/``, ``server/``, ``dist/*.js``, ``web/`` and
``packages/coast/src/`` must map to a reviewed source whose
``rights.commercial_use`` is ``"allowed"``.

Known blockers are listed explicitly in ``KNOWN_BLOCKERS``, each pointing to its
row in docs/legal/data-rights-register.md. The test asserts that the allow-list
equals the actual offender set, so a new offender fails CI and a resolved one
must be removed from the list (and the register) in the same PR.
"""
import json
from pathlib import Path
import re
import unittest
from tests._support import ROOT


REGISTER = ROOT / 'docs/legal/data-rights-register.md'

# Non-catalog runtime services (no data-need category fits a basemap). Keep in
# step with the "Runtime services" table in the register.
RUNTIME_SERVICES = {
    'osm-tiles': 'unknown',
    'noaa-enc-display': 'allowed',
}

# Hosts that identify a runtime call to a third-party service. Documentation
# links (for example open-meteo.com/en/terms) deliberately do not match.
RUNTIME_HOSTS = {
    re.compile(r'https://(?:[a-z]+-)?api\.open-meteo\.com'): 'open-meteo-api',
    re.compile(r'https://tile\.openstreetmap\.org'): 'osm-tiles',
    re.compile(r'https://gis\.charttools\.noaa\.gov'): 'noaa-enc-display',
    re.compile(r'https://imagery\.nationalmap\.gov'): 'usgs-naip',
}

# If an asset's text contains one of these hosts, its mapping must name the
# source, so a mapping cannot silently drift away from the data it describes.
SENTINELS = {
    'open-meteo.com': 'open-meteo-api',
    'socalfishreports.com': 'landing-reports',
    'gis.psmfc.org': 'pmep-hapc',
    'cmgds.marine.usgs.gov/data/csmp/': 'usgs-csmp-seafloor-character',
    'pubs.usgs.gov/ds/781/': 'usgs-csmp-seafloor-character',
    'zenodo.14982712': 'gfw-effort',
}

# (asset, source) pairs where the asset only cites the source in prose.
SENTINEL_EXCEPTIONS = {
    ('data/ais-evidence.json', 'gfw-effort'): 'research note links the GFW archive; no GFW records are included',
}

CSUMB_RELEASES = ['usgs-point-buchon', 'usgs-morro-bay', 'usgs-point-estero']

# Region asset path (relative to dist/) -> catalog source ids. Empty
# placeholders (no targets, areas, views) are detected and need no entry;
# search plans inherit the sources of their recorded input receipts.
ASSET_SOURCES = {
    'data/atlas.json': CSUMB_RELEASES,
    'data/habitat-regions.json': CSUMB_RELEASES,
    'regions/morro-bay/bottom/index.json': CSUMB_RELEASES,
    'data/charter-grounds.json': ['landing-reports', 'operator-identities', 'cdfw-mpas', 'ecfr-security', *CSUMB_RELEASES],
    'data/ais-evidence.json': ['noaa-ais', 'operator-identities'],
    'data/commercial-ais-effort.geojson': ['gfw-effort'],
    'data/daily-evidence.json': ['mur-sst', 'modis-chlorophyll', 'ioos-hfr', 'ndbc-buoys', 'noaa-tides', 'nws-weather',
                                 'cdfw-rules', 'cdfw-mpas', 'harbor-authority', 'landing-reports', 'open-meteo-api'],
    'data/protected-areas.geojson': ['cdfw-mpas'],
    'data/regulations.json': ['cdfw-rules', 'ecfr-security', 'noaa-groundfish-areas'],
    'data/regulations-mendocino.json': ['cdfw-rules', 'ecfr-security', 'noaa-groundfish-areas'],
    'data/regulations-northern.json': ['cdfw-rules', 'ecfr-security', 'noaa-groundfish-areas'],
    'data/regulations-san-francisco.json': ['cdfw-rules', 'ecfr-security', 'noaa-groundfish-areas'],
    'regions/southern-california/regulations.json': ['cdfw-rules', 'ecfr-security', 'noaa-groundfish-areas'],
    'regions/southern-california/atlas.json': ['noaa-h13093', 'noaa-h13323'],
    'regions/southern-california/bottom/index.json': ['noaa-cinms-bathymetry-2025', 'noaa-h13093', 'noaa-h13323'],
    'regions/southern-california/qualified-bottom/manifest.json': ['noaa-cinms-bathymetry-2025', 'noaa-h13093', 'noaa-h13323'],
    'regions/southern-california/survey-habitat.geojson': ['noaa-cinms-substrate-2006', 'noaa-cinms-bathymetry-2025', 'cdfw-kelp-2016'],
    'regions/southern-california/reef-context.geojson': ['cdfw-artificial-reefs'],
    'regions/southern-california/groundfish-exclusions.geojson': ['noaa-socal-gea'],
    'regions/southern-california/observations.json': ['ndbc-buoys'],
    'regions/cambria-san-simeon/geology.geojson': ['usgs-san-simeon'],
    'regions/cambria-san-simeon/survey-habitat.geojson': ['usgs-point-estero'],
    'regions/big-sur-coast/survey-habitat.geojson': ['pmep-hapc'],
    'regions/south-big-sur-san-simeon/survey-habitat.geojson': ['pmep-hapc'],
    'regions/monterey-point-sur/survey-habitat.geojson': ['usgs-csmp-seafloor-character'],
    'regions/santa-cruz-monterey-bay/survey-habitat.geojson': ['usgs-csmp-seafloor-character'],
    'regions/point-arguello-conception/survey-habitat.geojson': ['usgs-csmp-seafloor-character'],
    'regions/bodega-point-reyes/survey-habitat.geojson': ['noaa-bag', 'usgs-csmp-seafloor-character'],
    'regions/point-arena-bodega/survey-habitat.geojson': ['noaa-bag', 'usgs-csmp-seafloor-character'],
    'regions/humboldt-bay-cape-mendocino/survey-habitat.geojson': ['noaa-bag', 'usgs-cape-mendocino'],
}

# Asset kinds whose provenance is uniform and checked by a marker in the file.
KIND_SOURCES = {
    'protected_areas': (['cdfw-mpas'], lambda data: 'biosds582' in data.get('source_url', '')),
}

# Asset kinds that are original SkipperCast summaries citing public agency
# pages, rather than redistributed third-party data.
ORIGINAL_KINDS = {'ecology'}

REGISTER_ROW = 'docs/legal/data-rights-register.md#'

# source id -> (register anchor, date listed, offending usages). Remove an
# entry (and update the register) when the blocker is resolved.
KNOWN_BLOCKERS = {
    'open-meteo-api': (REGISTER_ROW + 'b1--open-meteo-free-api-mostly-resolved', '2026-09-28', {
        # Runtime calls were removed in #51/#54; only the committed daily snapshot still carries Open-Meteo data.
        'data/daily-evidence.json',
    }),
    'gfw-effort': (REGISTER_ROW + 'b2--global-fishing-watch-cc-by-nc', '2026-09-28', {
        'data/commercial-ais-effort.geojson',
    }),
    'usgs-point-buchon': (REGISTER_ROW + 'b3--csumb-co-produced-seafloor-data', '2026-09-28', {
        'data/atlas.json', 'data/habitat-regions.json', 'data/charter-grounds.json',
        'regions/morro-bay/bottom/index.json', 'regions/morro-bay/search-plans.json',
    }),
    'usgs-morro-bay': (REGISTER_ROW + 'b3--csumb-co-produced-seafloor-data', '2026-09-28', {
        'data/atlas.json', 'data/habitat-regions.json', 'data/charter-grounds.json',
        'regions/morro-bay/bottom/index.json', 'regions/morro-bay/search-plans.json',
    }),
    'usgs-point-estero': (REGISTER_ROW + 'b3--csumb-co-produced-seafloor-data', '2026-09-28', {
        'data/atlas.json', 'data/habitat-regions.json', 'data/charter-grounds.json',
        'regions/morro-bay/bottom/index.json', 'regions/morro-bay/search-plans.json',
        'regions/cambria-san-simeon/survey-habitat.geojson', 'regions/cambria-san-simeon/search-plans.json',
    }),
    'usgs-csmp-seafloor-character': (REGISTER_ROW + 'b3--csumb-co-produced-seafloor-data', '2026-09-28', {
        'regions/monterey-point-sur/survey-habitat.geojson', 'regions/monterey-point-sur/search-plans.json',
        'regions/santa-cruz-monterey-bay/survey-habitat.geojson', 'regions/santa-cruz-monterey-bay/search-plans.json',
        'regions/point-arguello-conception/survey-habitat.geojson', 'regions/point-arguello-conception/search-plans.json',
        'regions/bodega-point-reyes/survey-habitat.geojson', 'regions/bodega-point-reyes/search-plans.json',
        'regions/point-arena-bodega/survey-habitat.geojson', 'regions/point-arena-bodega/search-plans.json',
    }),
    'pmep-hapc': (REGISTER_ROW + 'b4--pmep-habitat-compilation-terms-unreviewed', '2026-09-28', {
        'regions/big-sur-coast/survey-habitat.geojson', 'regions/big-sur-coast/search-plans.json',
        'regions/south-big-sur-san-simeon/survey-habitat.geojson', 'regions/south-big-sur-san-simeon/search-plans.json',
    }),
    'landing-reports': (REGISTER_ROW + 'b5--landing-report-facts', '2026-09-28', {
        'data/charter-grounds.json', 'data/daily-evidence.json',
    }),
    'osm-tiles': (REGISTER_ROW + 'b6--openstreetmap-tile-service', '2026-09-28', {
        'runtime:dist/chart-map.js', 'runtime:dist/map-test-common.js', 'runtime:server/security-headers.ts',
    }),
}


def catalog():
    return {s['id']: s for s in json.loads((ROOT / 'catalog/sources.json').read_text())['sources']}


def commercial_use(ident, sources):
    if ident in sources:
        return sources[ident]['rights']['commercial_use']
    return RUNTIME_SERVICES[ident]


def is_placeholder(kind, data):
    if kind == 'atlas':
        return not any(data.get(k) for k in ('targets', 'areas', 'drifts'))
    if kind == 'habitats':
        return not data.get('areas')
    if kind == 'bottom_index':
        return not data.get('views')
    return False


def published_regions():
    for path in sorted((ROOT / 'regions').glob('*/region.json')):
        region = json.loads(path.read_text())
        if region['status'] != 'draft':
            yield region


def asset_sources(kind, path, cache):
    """Source ids behind one bound asset, or None when unmapped."""
    if path in cache:
        return cache[path]
    data = json.loads((ROOT / 'dist' / path).read_text())
    if kind in ORIGINAL_KINDS or is_placeholder(kind, data):
        result = set()
    elif kind == 'search_plans':
        result = set()
        for receipt in data['input_receipts']:
            inherited = asset_sources(None, receipt['path'], cache)
            if inherited is None:
                cache[path] = None
                return None
            result |= inherited
    elif path in ASSET_SOURCES:
        result = set(ASSET_SOURCES[path])
    elif kind in KIND_SOURCES:
        ids, marker = KIND_SOURCES[kind]
        result = set(ids) if marker(data) else None
    else:
        # Placeholders reached through search-plan receipts carry no kind.
        guess = {'atlas.json': 'atlas', 'habitats.json': 'habitats'}.get(Path(path).name)
        result = set() if guess and is_placeholder(guess, data) else None
    cache[path] = result
    return result


def usages():
    """(usage label, source id) pairs for everything shipped or called."""
    found, unmapped, cache, sources = set(), set(), {}, catalog()
    for region in published_regions():
        for kind, path in region['assets'].items():
            if path is None:
                continue
            ids = asset_sources(kind, path, cache)
            if ids is None:
                unmapped.add(f"{region['id']}:{kind}={path}")
                continue
            found.update((path, ident) for ident in ids)
        # The CUSP shoreline ships beside the region package (FE-10), outside region.json assets.
        shoreline = f"regions/{region['id']}/shoreline.geojson"
        if (ROOT / 'dist' / shoreline).is_file():
            found.add((shoreline, 'noaa-cusp-shoreline'))
        for role, ident in (region.get('intelligence') or {}).get('providers', {}).items():
            found.add((f'region.json:intelligence.providers.{role}', ident))
        for role, ident in region.get('pipeline_sources', {}).items():
            found.add((f'region.json:pipeline_sources.{role}', ident))
        for layer, binding in region.get('basemap', {}).items():
            found.add((f'region.json:basemap.{layer}', binding['source']))
        for need in ('wind-forecast', 'wave-forecast'):
            # Mirrors the scheduled pipeline's model selection (settings.model_ids).
            for ident in region['source_bindings'].get(need, []):
                if sources[ident]['adapter'] == 'open-meteo' and sources[ident]['review_status'] == 'approved':
                    found.add((f'region.json:source_bindings.{need}', ident))
    files = [*sorted((ROOT / 'src').rglob('*.py')), *sorted((ROOT / 'server').rglob('*.js')), *sorted((ROOT / 'server').rglob('*.ts')),
             *sorted((ROOT / 'dist').glob('*.js')), *sorted((ROOT / 'web').rglob('*.ts')), *sorted((ROOT / 'web').rglob('*.tsx')),
             *sorted((ROOT / 'packages/coast/src').rglob('*.ts'))]
    for path in files:
        text = path.read_text(encoding='utf-8')
        for pattern, ident in RUNTIME_HOSTS.items():
            if pattern.search(text):
                found.add(('runtime:' + path.relative_to(ROOT).as_posix(), ident))
    return found, unmapped, cache


def slug(heading):
    heading = heading.strip().lower()
    return re.sub(r'[^\w\- ]', '', heading).replace(' ', '-')


class CommercialSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sources = catalog()
        cls.found, cls.unmapped, cls.cache = usages()

    def test_every_bound_asset_maps_to_a_reviewed_source(self):
        self.assertFalse(self.unmapped, 'Add these assets to ASSET_SOURCES and the register: '
                         + ', '.join(sorted(self.unmapped)))
        for label, ident in self.found:
            with self.subTest(usage=label):
                self.assertTrue(ident in self.sources or ident in RUNTIME_SERVICES, f'{label} -> unknown source {ident}')

    def test_mappings_name_the_sources_their_data_cite(self):
        for path, ids in self.cache.items():
            if not ids or not (ROOT / 'dist' / path).is_file():
                continue
            text = (ROOT / 'dist' / path).read_text()
            for needle, ident in SENTINELS.items():
                if needle in text and (path, ident) not in SENTINEL_EXCEPTIONS:
                    with self.subTest(asset=path, source=ident):
                        self.assertIn(ident, ids)

    def test_mapping_table_has_no_stale_rows(self):
        bound = {path for region in published_regions() for path in region['assets'].values() if path}
        self.assertFalse(set(ASSET_SOURCES) - bound, 'Mapped assets are no longer bound to any region')

    def test_non_commercial_sources_are_exactly_the_known_blockers(self):
        offenders = {}
        for label, ident in self.found:
            if commercial_use(ident, self.sources) != 'allowed':
                offenders.setdefault(ident, set()).add(label)
        expected = {ident: usage for ident, (_, _, usage) in KNOWN_BLOCKERS.items()}
        new = {i: sorted(u - expected.get(i, set())) for i, u in offenders.items() if u - expected.get(i, set())}
        resolved = {i: sorted(u - offenders.get(i, set())) for i, u in expected.items() if u - offenders.get(i, set())}
        self.assertFalse(new, 'New assets or calls rely on sources not cleared for commercial use '
                              '(fix them, or add a dated KNOWN_BLOCKERS entry and a register row): ' + json.dumps(new, indent=1))
        self.assertFalse(resolved, 'Resolved blockers must be removed from KNOWN_BLOCKERS and the register: '
                                   + json.dumps(resolved, indent=1))

    def test_every_blocker_points_to_a_register_row(self):
        text = REGISTER.read_text()
        anchors = {slug(line.lstrip('#')) for line in text.splitlines() if line.startswith('### ')}
        for ident, (row, listed, _) in KNOWN_BLOCKERS.items():
            with self.subTest(source=ident):
                self.assertTrue(row.startswith(REGISTER_ROW))
                self.assertIn(row.split('#', 1)[1], anchors)
                self.assertRegex(listed, r'^\d{4}-\d{2}-\d{2}$')
                self.assertIn(f'`{ident}`', text)

    def test_register_lists_every_catalog_source(self):
        text = REGISTER.read_text()
        for ident in [*self.sources, *RUNTIME_SERVICES]:
            with self.subTest(source=ident):
                self.assertIn(f'`{ident}`', text)


if __name__ == '__main__':
    unittest.main()
