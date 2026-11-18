#!/usr/bin/env python3
"""Generate the data-sources register on dist/sources.html (the map's "Sources" link target).

The page section ``id="data-sources"`` is built from the reviewed source register, never typed by hand:

* the catalogue and its display contract come from ``catalog/sources.json`` through
  ``skippercast.platform.contracts.load_catalogs`` (so an invalid ``public_display`` fails here too);
* what is live comes from the non-draft ``regions/*/region.json`` bindings and the runtime service scan in
  ``tests/contract/test_commercial_sources.py`` (``published_regions``, ``asset_sources``, ``usages``), the one
  provenance map the commercial-use gate already keeps; the two views must agree or generation fails;
* credits are ``rights.attribution`` verbatim, plus the canonical ``CSUMB_CREDIT`` once, only while a listed source is CSUMB's.

Held rows. A row whose catalogue ``needs`` include an id in ``HELD_NEEDS`` (kelp, until KELP-3) is never listed, live or
not, and its credit is never printed; that holds even when its ``public_display`` is ``allowed``. The page does not mention it.

Listing rule. A row is listed when ``rights.public_display`` is ``allowed`` (live or not), or when a live layer already
uses a row that predates the display decision (no ``public_display`` key, no ``publication_allowed: false``). ``private``
and ``excluded`` rows are never listed, whatever their use. A listed row that no live layer uses sits under "Eligible, not
yet used". Links go to a documentation or terms page only: never an archive, a raw data file or a data-service endpoint.

    python scripts/build_sources_register.py            # rewrite the section in dist/sources.html
    python scripts/build_sources_register.py --check    # exit 1 when the committed page differs from a fresh build
"""
from __future__ import annotations

import argparse
import contextlib
import difflib
import html
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
for entry in (ROOT / 'src', ROOT):  # this script sets its own path; no PYTHONPATH needed
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from skippercast.platform.contracts import load_catalogs, public_url  # noqa: E402
from skippercast.seafloor.rights import CSUMB_CREDIT  # noqa: E402
from tests.contract import test_commercial_sources as contract  # noqa: E402

PAGE = Path('dist/sources.html')
BEGIN = '<!-- BEGIN GENERATED data-sources: scripts/build_sources_register.py (do not edit by hand) -->'
END = '<!-- END GENERATED data-sources -->'
# First run only: the section goes in front of this heading; later runs replace the marked block.
INSERT_BEFORE = '<h2>Current official checks</h2>'
INDENT = '      '

# Services the app calls that have no catalogue row (tests/contract/test_commercial_sources.py RUNTIME_SERVICES).
# Name, agency and a public page only: their credit text lives in the page's own "Map and software" section.
RUNTIME_SERVICE_INFO = {
    'osm-tiles': {'name': 'OpenStreetMap standard tiles', 'provider': 'OpenStreetMap contributors',
                  'provides': 'Base map tiles', 'url': 'https://www.openstreetmap.org/copyright'},
    'noaa-enc-display': {'name': 'NOAA ENC Display service', 'provider': 'NOAA Office of Coast Survey',
                         'provides': 'Nautical chart display', 'url': 'https://nauticalcharts.noaa.gov/'},
}
SERVICE_CREDIT_NOTE = 'see Map and software above'

# Catalogue ``needs`` ids whose rows are held off the page until the named task lands. The task, not this script, owns
# the credit wording, so a held row prints nothing: no credit, no usage line, no "eligible" line. Releasing a hold is
# deleting its entry here and regenerating; the register text itself is never edited.
HELD_NEEDS = {'kelp': 'KELP-3'}

# Layer names for region asset kinds. Presentation only: an unknown kind falls back to its own words.
LAYER_NAMES = {'ais_evidence': 'AIS evidence', 'commercial_ais': 'Commercial AIS', 'bottom_index': 'Bottom views',
               'survey_habitat': 'Survey habitat', 'search_plans': 'Search plans', 'protected_areas': 'Protected areas',
               'daily_evidence': 'Daily evidence', 'target_qualification': 'Target qualification',
               'regional_context': 'Regional context'}

# A link is never a raw-data or data-service address (a barred source's files must not be reachable from here).
RAW_SUFFIXES = ('.zip', '.gz', '.tgz', '.tar', '.7z', '.tif', '.tiff', '.nc', '.csv', '.json', '.geojson', '.gpkg',
                '.shp', '.kml', '.kmz', '.xyz', '.laz', '.las', '.bag', '.grd', '.grib', '.grib2', '.parquet',
                '.mbtiles', '.pmtiles', '.sqlite', '.xls', '.xlsx')
RAW_PATH_PARTS = ('/rest/services', '/mapserver', '/featureserver', '/imageserver', '/wms', '/wfs', '/wcs', '/thredds/')


class RegisterError(Exception):
    """The register cannot be built honestly; nothing is written."""


def _esc(value):
    return html.escape(str(value), quote=True)


def _words(kind):
    return LAYER_NAMES.get(kind) or kind.replace('_', ' ').replace('-', ' ').capitalize()


@contextlib.contextmanager
def _contract_root(root):
    """The contract helpers read a module-level ROOT; point it at the tree being built, then restore it."""
    saved = contract.ROOT
    contract.ROOT = Path(root)
    try:
        yield
    finally:
        contract.ROOT = saved


def safe_link(row):
    """A documentation or terms page for the source, or None. Never ``archive_url`` and never a data endpoint."""
    for url in (row.get('documentation_url'), (row.get('rights') or {}).get('terms_url')):
        if not isinstance(url, str):
            continue
        try:
            public_url(url)
        except ValueError:
            continue
        parts = urlsplit(url)
        path = parts.path.lower()
        if path.endswith(RAW_SUFFIXES) or any(part in path + '/' for part in RAW_PATH_PARTS):
            continue
        if any(token in parts.query.lower() for token in ('service=', 'request=getmap', 'request=getfeature', 'f=json')):
            continue
        return url
    return None


def is_csumb(row):
    """CSUMB's own survey rows: producer named in the register's provider field, or a ``csumb-`` source id."""
    return 'CSUMB' in str(row.get('provider', '')) or 'CSU Monterey Bay' in str(row.get('provider', '')) or str(row.get('id', '')).startswith('csumb-')


def held(row):
    """The release task a row is waiting on, or None. Keyed on the row's own catalogue ``needs``, never on a source id or a credit."""
    for need in row.get('needs') or ():
        if need in HELD_NEEDS:
            return HELD_NEEDS[need]
    return None


def listed(row, live):
    """Display rule (see module docstring). ``private``/``excluded`` never pass, whatever the use.

    A held row (see HELD_NEEDS) never passes either, live or not: nothing about it is printed, no credit and no usage.
    A row without a display decision predates it: it is listed only because a live layer already shows its data to the
    public, so the credit has to be somewhere; an explicit ``publication_allowed: false`` still keeps it off the page.
    """
    if held(row):
        return False
    display = (row.get('rights') or {}).get('public_display')
    if display == 'allowed':
        return True
    if display is None:
        return bool(live) and row.get('publication_allowed') is not False
    return False


def _dates(row, extra=()):
    parts = []
    survey = row.get('survey_date') or row.get('survey_year')
    if survey:
        parts.append(f'survey {survey}')
    if row.get('publication_date'):
        parts.append(f"published {row['publication_date']}")
    parts.extend(extra)
    return '; '.join(parts)


def collect(root=ROOT):
    """Everything the page shows, as plain data. Raises RegisterError when the live views disagree."""
    root = Path(root)
    needs, sources = load_catalogs(root)
    with _contract_root(root):
        regions = list(contract.published_regions())
        found, unmapped, cache = contract.usages()
        if unmapped:
            raise RegisterError('unmapped region assets: ' + ', '.join(sorted(unmapped)))
        live_regions, region_ids = [], set()
        for region in regions:
            layers = {}  # layer name -> {source id: extra date text}

            def add(layer, ident, extra=''):
                layers.setdefault(layer, {}).setdefault(ident, extra)
            for kind, path in sorted(region['assets'].items()):
                if path is None:
                    continue
                ids = contract.asset_sources(kind, path, cache)
                if ids is None:
                    raise RegisterError(f"{region['id']}: asset {kind}={path} has no source mapping")
                for ident in ids:
                    add(_words(kind), ident)
            if (root / 'dist' / f"regions/{region['id']}/shoreline.geojson").is_file():
                add('Shoreline', 'noaa-cusp-shoreline')
            for role, ident in (region.get('intelligence') or {}).get('providers', {}).items():
                add(f'Forecast intelligence: {_words(role).lower()}', ident)
            for role, ident in region.get('pipeline_sources', {}).items():
                add(f'Conditions: {_words(role).lower()}', ident)
            for layer, binding in region.get('basemap', {}).items():
                if layer != 'default':
                    acquired = binding.get('acquired') or {}
                    extra = f"imagery acquired {acquired['first']} to {acquired['last']}" if acquired.get('first') and acquired.get('last') else ''
                    add(f'Basemap: {layer}', binding['source'], extra)
            for need in ('wind-forecast', 'wave-forecast'):
                for ident in region['source_bindings'].get(need, []):
                    if sources[ident]['adapter'] == 'open-meteo' and sources[ident]['review_status'] == 'approved':
                        add(f'Forecast: {need.split("-")[0]}', ident)
            region_ids |= {ident for members in layers.values() for ident in members}
            live_regions.append({'id': region['id'], 'name': region.get('name') or region['id'],
                                 'status': region['status'], 'layers': layers})
        runtime = {ident for label, ident in found if label.startswith('runtime:')}
    expected = {ident for _, ident in found}
    if region_ids | runtime != expected:
        raise RegisterError('live usage disagrees with tests/contract/test_commercial_sources.py usages(): '
                            + ', '.join(sorted((region_ids | runtime) ^ expected)))
    unknown = sorted(ident for ident in expected if ident not in sources and ident not in contract.RUNTIME_SERVICES)
    if unknown:
        raise RegisterError('live usage names unknown sources: ' + ', '.join(unknown))
    missing = sorted(set(contract.RUNTIME_SERVICES) - set(RUNTIME_SERVICE_INFO))
    if missing:
        raise RegisterError('add these runtime services to RUNTIME_SERVICE_INFO: ' + ', '.join(missing))
    return {'needs': needs, 'sources': sources, 'regions': sorted(live_regions, key=lambda r: r['id']),
            'runtime': sorted(runtime)}


def _name(ident, sources):
    return (sources.get(ident) or RUNTIME_SERVICE_INFO.get(ident, {})).get('name', ident)


def _entry(ident, sources, needs, extra=''):
    """One list item. A service without a catalogue row uses its RUNTIME_SERVICE_INFO entry."""
    row = sources.get(ident)
    if row is None:
        info = RUNTIME_SERVICE_INFO[ident]
        head, facts, credit = f"{info['name']}", [f"Provides: {info['provides']}"], SERVICE_CREDIT_NOTE
        agency, link = info['provider'], info['url']
    else:
        head, agency, link = row['name'], row['provider'], safe_link(row)
        facts = []
        if row['needs']:
            facts.append('Provides: ' + ', '.join(needs.get(need, {}).get('name', need) for need in row['needs']))
        dates = _dates(row, [extra] if extra else [])
        if dates:
            facts.append('Date: ' + dates)
        credit = row['rights'].get('attribution') or ''
    lines = [f'<strong>{_esc(head)}</strong> · {_esc(agency)}']
    if facts:
        lines.append(_esc(' · '.join(facts)))
    # The link is a direct child of the item (the readable sheet's touch height rule targets `li > a`); its name carries the source.
    anchor = f'<a href="{_esc(link)}" rel="noopener" aria-label="{_esc(head)}: source page">Source page</a>' if link else ''
    tail = [part for part in (f'Credit: {_esc(credit)}' if credit else '', anchor) if part]
    if tail:
        lines.append(' · '.join(tail))
    return f'{INDENT}    <li>' + f'<br />\n{INDENT}      '.join(lines) + '</li>'


def _list(items):
    return f'{INDENT}  <ul>\n' + '\n'.join(items) + f'\n{INDENT}  </ul>'


def _by_name(ids, sources):
    return sorted(ids, key=lambda ident: (_name(ident, sources), ident))


def render(data):
    """The marked block as text (deterministic: sorted everywhere, no clock) and a summary."""
    sources, needs = data['sources'], data['needs']
    live_ids = {ident for region in data['regions'] for members in region['layers'].values() for ident in members} | set(data['runtime'])

    def show(ident):  # a service without a catalogue row is always shown
        return ident not in sources or listed(sources[ident], True)

    shown = sorted(ident for ident in live_ids if show(ident))
    eligible = [ident for ident, row in sources.items() if ident not in live_ids and listed(row, False)]
    withheld = len(live_ids) - len(shown)
    h = INDENT + '  '
    out = [BEGIN, f'{INDENT}<section id="data-sources" aria-labelledby="data-sources-heading">',
           f'{h}<h2 id="data-sources-heading">Data sources register</h2>',
           f'{h}<p>This list is generated from the reviewed source register, with each credit as the register records it. '
           'The map itself shows no source names; its measured, estimated and unsurveyed labels describe data quality and stay as they are. '
           'Eligibility for public display is a rights decision that does not release a layer.</p>',
           f'{h}<p>{len(shown)} sources are in use on live layers; {len(eligible)} more are eligible for public display but no layer uses them yet.</p>']
    if any(is_csumb(sources[ident]) for ident in shown + eligible if ident in sources):
        out += [f'{h}<h3 id="data-sources-credits">Required credit</h3>',
                f'{h}<p class="data-source-credit">{_esc(CSUMB_CREDIT)}</p>']
    out.append(f'{h}<h3 id="data-sources-live">In use on live layers</h3>')
    for region in data['regions']:
        layers = {layer: _by_name([i for i in members if show(i)], sources) for layer, members in sorted(region['layers'].items())}
        layers = {layer: ids for layer, ids in layers.items() if ids}
        if not layers:
            continue
        label = region['name'] + (f" ({region['status']} region)" if region['status'] != 'active' else '')
        out.append(f"{h}<h4 id=\"data-sources-region-{_esc(region['id'])}\">{_esc(label)}</h4>")
        for layer, ids in layers.items():
            out.append(f'{h}<h5>{_esc(layer)}</h5>')
            out.append(_list(_entry(i, sources, needs, region['layers'][layer][i]) for i in ids))
    services = _by_name([i for i in data['runtime'] if show(i)], sources)
    if services:
        out.append(f'{h}<h4 id="data-sources-services">Services the app calls directly</h4>')
        out.append(_list(_entry(i, sources, needs) for i in services))
    out.append(f'{h}<h3 id="data-sources-eligible">Eligible for public display, not yet used</h3>')
    if eligible:
        out.append(f'{h}<p>These sources may be shown publicly, but no live layer uses them yet. Listing here is a rights status and no release.</p>')
        groups = {}
        for ident in eligible:
            groups.setdefault((sources[ident]['needs'] or ['other'])[0], []).append(ident)
        for need, ids in sorted(groups.items(), key=lambda kv: (needs.get(kv[0], {}).get('name', kv[0]), kv[0])):
            out.append(f"{h}<h4 id=\"data-sources-eligible-{_esc(need)}\">{_esc(needs.get(need, {}).get('name', need.capitalize()))}</h4>")
            out.append(_list(_entry(i, sources, needs) for i in _by_name(ids, sources)))
    else:
        out.append(f'{h}<p>No source is waiting; every eligible source is in use.</p>')
    out += [f'{INDENT}</section>', f'{INDENT}{END}']
    return '\n'.join(out), {'listed_live': len(shown), 'eligible_unused': len(eligible), 'withheld_live': withheld}


def splice(page, block):
    """Replace the marked block, or (first run) insert it before INSERT_BEFORE. ``block`` starts at its BEGIN marker."""
    if BEGIN in page:
        head, rest = page.split(BEGIN, 1)
        if END not in rest:
            raise RegisterError('dist/sources.html has a BEGIN marker without its END marker')
        return head + block + rest.split(END, 1)[1]
    if page.count(INSERT_BEFORE) != 1:
        raise RegisterError(f'expected exactly one {INSERT_BEFORE} to anchor the first insert')
    head, tail = page.split(INSERT_BEFORE)
    return head + block + '\n' + INDENT + INSERT_BEFORE + tail


def build(root=ROOT):
    """(current text, fresh text, summary) for the page under ``root``."""
    root = Path(root)
    block, summary = render(collect(root))
    current = (root / PAGE).read_text(encoding='utf-8')
    return current, splice(current, block), summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--check', action='store_true', help='fail when the committed page differs from a fresh build')
    parser.add_argument('--root', default=str(ROOT), help='repository root (tests use a fixture tree)')
    args = parser.parse_args(argv)
    root = Path(args.root)
    try:
        current, fresh, summary = build(root)
    except RegisterError as error:
        print(f'build_sources_register: {error}', file=sys.stderr)
        return 2
    note = (f"{summary['listed_live']} live, {summary['eligible_unused']} eligible and unused, "
            f"{summary['withheld_live']} live rows withheld by the display rule")
    if args.check:
        if current != fresh:
            diff = difflib.unified_diff(current.splitlines(), fresh.splitlines(), 'dist/sources.html', 'fresh build', lineterm='', n=1)
            print('\n'.join(list(diff)[:40]), file=sys.stderr)
            print('build_sources_register: dist/sources.html is stale; run python scripts/build_sources_register.py and commit the result.', file=sys.stderr)
            return 1
        print(f'build_sources_register: up to date ({note})')
        return 0
    if current != fresh:
        (root / PAGE).write_text(fresh, encoding='utf-8')
    print(f"build_sources_register: {'updated' if current != fresh else 'unchanged'} ({note})")
    return 0


if __name__ == '__main__':
    sys.exit(main())
