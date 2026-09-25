"""Review original FGDC metadata for DS 781 bathymetry and character leads.

This is a source triage receipt. Described bounds, spacing and datums are not
inspected raster cells, chart depths, habitat boundaries or fishing targets.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from hashlib import sha256
import json
import math
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
HOSTS = {'pubs.usgs.gov', 'cmgds.marine.usgs.gov'}
KINDS = {'bathymetry', 'seafloor-character'}
MAX_XML = 1_500_000


def official(url):
    parsed = urlparse(url or '')
    return parsed.scheme == 'https' and parsed.hostname in HOSTS and parsed.path.lower().endswith('.xml')


def catalog_metadata_url(url):
    parsed = urlparse(url or '')
    return parsed.scheme == 'https' and parsed.hostname in HOSTS and parsed.path.lower().endswith(('.xml', '.txt'))


def xml_sibling(url):
    # Older original catalogs link FGDC text, but host a same-stem XML sibling.
    # The sibling is accepted only after fetch verifies the exact USGS response.
    return url[:-4] + '.xml' if url.lower().endswith('.txt') else url


def fetch(url):
    if not official(url):
        raise ValueError('Metadata URL is outside original USGS XML hosts')
    request = Request(url, headers={'User-Agent': 'SkipperCast original FGDC source review/1.0'})
    with urlopen(request, timeout=35) as response:
        if response.status != 200 or not official(response.url):
            raise ValueError('Original USGS XML returned unexpected status or redirect')
        raw = response.read(MAX_XML + 1)
    if not raw or len(raw) > MAX_XML:
        raise ValueError('Original USGS XML is empty or oversized')
    return raw


def parse_xml(raw):
    root = ET.fromstring(raw)
    if root.tag != 'metadata':
        raise ValueError('Expected FGDC metadata root')
    text = lambda path: ' '.join((root.findtext(path) or '').split())
    title = text('./idinfo/citation/citeinfo/title')
    if not title:
        raise ValueError('FGDC metadata has no title')
    vertical = text('./spref/vertdef/altsys/altdatum') or text('./spref/vertdef/depthsys/depthdn')
    resolution = text('./spref/horizsys/planar/planci/coordrep/absres')
    resolution_units = text('./spref/horizsys/planar/planci/plandu')
    spacing = [float(part.strip()) for part in resolution.split(',')] if resolution else []
    if len(spacing) > 4 or any(not math.isfinite(value) for value in spacing):
        raise ValueError('Unexpected metadata spacing dimensions')
    access = text('./idinfo/accconst')
    use = text('./idinfo/useconst')
    rights = ('explicit-public-domain-redistribution' if 'public domain' in use.lower()
              and 'freely redistributable' in use.lower() else 'requires-review')
    return {'title': title[:250], 'publication_date': text('./idinfo/citation/citeinfo/pubdate') or None,
            'ground_condition_date': text('./idinfo/timeperd/timeinfo/sngdate/caldate') or None,
            'horizontal_spacing_in_metadata': spacing or None,
            'horizontal_spacing_units_in_metadata': resolution_units or None,
            'horizontal_spacing_plausible': (all(0.25 <= value <= 100 for value in spacing)
                                             and resolution_units.lower() in {'meter', 'meters'}),
            'vertical_datum_declared': vertical or None,
            'access_constraints': access[:600] or None, 'use_constraints': use[:1200] or None,
            'rights_evidence': rights}


def audit(source, *, fetcher=fetch):
    areas = source.get('map_areas', [])
    if source.get('schema_version') != 1 or len(areas) != 39:
        raise ValueError('Expected complete reviewed DS 781 area inventory')
    tasks = []
    for area in areas:
        for product in area['products']:
            if product['kind'] not in KINDS:
                continue
            if urlparse(product['archive_url']).hostname not in HOSTS:
                raise ValueError('USGS product archive host changed')
            url = product.get('metadata_url')
            if url is not None and not catalog_metadata_url(url):
                raise ValueError('USGS product metadata host changed')
            tasks.append((area['name'], product))
    if len(tasks) < 70:
        raise ValueError('DS 781 bathymetry/character product inventory shrank')

    def inspect(task):
        name, product = task
        row = {'map_area': name, 'kind': product['kind'],
               'archive_url': product['archive_url'], 'metadata_url': product.get('metadata_url')}
        if not row['metadata_url']:
            return {**row, 'status': 'missing-metadata-link'}
        try:
            xml_url = xml_sibling(row['metadata_url'])
            raw = fetcher(xml_url)
            return {**row, 'status': 'reviewed', 'xml_url': xml_url,
                    'metadata_sha256': sha256(raw).hexdigest(),
                    **parse_xml(raw)}
        except (OSError, TimeoutError, ValueError, ET.ParseError) as exc:
            return {**row, 'status': 'fetch-or-parse-failed', 'issue': str(exc)[:180]}

    with ThreadPoolExecutor(max_workers=5) as executor:
        rows = list(executor.map(inspect, tasks))
    rows.sort(key=lambda item: (item['map_area'], item['kind'], item['archive_url']))
    return {'schema_version': 1, 'scope': 'usgs-ds781-original-fgdc-metadata-triage',
            'reviewed_at': datetime.now(timezone.utc).isoformat(),
            'source_inventory_sha256': sha256(json.dumps(source['map_areas'], sort_keys=True).encode()).hexdigest(),
            'limitations': [
                'Metadata spacing and datum describe the source; exact archive rasters and valid-cell footprints have not been opened by this audit.',
                'An explicit USGS public-domain statement supports source reuse with attribution but does not confer fishing or navigation clearance.',
                'Missing or failed metadata and ambiguous rights remain held from derivative publication.',
            ], 'record_count': len(rows), 'records': rows}


def signature(data):
    return [{key: value for key, value in row.items() if key not in {'issue'}} for row in data['records']]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inventory', type=Path, default=ROOT / 'catalog/usgs-ds781-source-leads.json')
    parser.add_argument('--output', type=Path, default=ROOT / 'catalog/usgs-ds781-metadata-review.json')
    parser.add_argument('--verify', type=Path)
    args = parser.parse_args()
    result = audit(json.loads(args.inventory.read_text()))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n')
    if args.verify and signature(result) != signature(json.loads(args.verify.read_text())):
        raise SystemExit('USGS original FGDC metadata changed or failed; review before promotion')
    print(json.dumps({'records': result['record_count'],
                      'reviewed': sum(row['status'] == 'reviewed' for row in result['records']),
                      'explicit_reuse': sum(row.get('rights_evidence') == 'explicit-public-domain-redistribution'
                                            for row in result['records'])}))


if __name__ == '__main__':
    main()
