"""Inventory official USGS California State Waters map-area product links.

This is source discovery, not native-grid coverage or fishing-target approval.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from hashlib import sha256
from html.parser import HTMLParser
import json
from pathlib import Path
import re
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
INDEX = 'https://pubs.usgs.gov/ds/781/'


class Rows(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows = []
        self.row = None
        self.cell = None

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == 'tr':
            self.row = []
        elif tag in ('td', 'th') and self.row is not None:
            self.cell = {'text': [], 'links': []}
        elif tag == 'a' and self.cell is not None and attributes.get('href'):
            self.cell['links'].append(attributes['href'])

    def handle_data(self, data):
        if self.cell is not None:
            self.cell['text'].append(data)

    def handle_endtag(self, tag):
        if tag in ('td', 'th') and self.cell is not None and self.row is not None:
            self.cell['text'] = ' '.join(' '.join(self.cell['text']).split())
            self.row.append(self.cell)
            self.cell = None
        elif tag == 'tr' and self.row is not None:
            self.rows.append(self.row)
            self.row = None


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag == 'a' and dict(attrs).get('href'):
            self.links.append(dict(attrs)['href'])


def fetch(url):
    if urlparse(url).scheme != 'https' or urlparse(url).hostname != 'pubs.usgs.gov':
        raise ValueError('Only the original USGS DS 781 catalog host is accepted')
    request = Request(url, headers={'User-Agent': 'SkipperCast source inventory (research)'})
    with urlopen(request, timeout=40) as response:
        if response.status != 200 or urlparse(response.url).hostname != 'pubs.usgs.gov':
            raise ValueError(f'Unexpected USGS response for {url}')
        content = response.read(2_000_001)
    if len(content) > 2_000_000:
        raise ValueError('USGS catalog page exceeds bounded inventory size')
    return content


def fetch_release(url):
    if urlparse(url).scheme != 'https' or urlparse(url).hostname != 'doi.org':
        raise ValueError('Expected original USGS data-release DOI')
    request = Request(url, headers={'User-Agent': 'SkipperCast source inventory (research)'})
    with urlopen(request, timeout=40) as response:
        final_url = response.url
        if response.status != 200 or urlparse(final_url).hostname not in ('cmgds.marine.usgs.gov', 'pubs.usgs.gov'):
            raise ValueError(f'Unexpected USGS release redirect for {url}')
        content = response.read(3_000_001)
    if len(content) > 3_000_000:
        raise ValueError('USGS release page exceeds bounded inventory size')
    return content, final_url


def rows(content):
    parser = Rows()
    parser.feed(content.decode('utf-8', errors='replace'))
    return parser.rows


def map_areas(content):
    result = []
    for cells in rows(content):
        if len(cells) < 2 or not cells[1]['links']:
            continue
        name = cells[0]['text'].rstrip(']')
        title = cells[1]['text']
        if 'California State Waters Map Series Data Catalog' not in title or 'video observations' in name.lower():
            continue
        url = urljoin(INDEX, cells[1]['links'][0])
        report = urljoin(INDEX, cells[2]['links'][0]) if len(cells) > 2 and cells[2]['links'] else None
        result.append({'name': name, 'catalog_url': url, 'report_url': report,
                       'catalog_kind': 'ds781-html' if url.startswith(INDEX) else 'external-release'})
    if len(result) < 35 or len({x['name'] for x in result}) != len(result):
        raise ValueError('USGS map-area index is incomplete or changed')
    return result


def products(content, page_url):
    found = []
    for cells in rows(content):
        if not cells or not cells[0]['text']:
            continue
        description = cells[0]['text']
        lower = description.lower()
        if ('video observation' in lower or 'visual observation' in lower):
            continue  # The statewide cruise index is inventoried separately; links here do not prove local coverage.
        if not any(word in lower for word in ('bathymetry', 'seafloor character', 'habitat', 'backscatter')):
            continue
        if 'hillshade' in lower or 'shaded' in lower:
            continue
        zips = [urljoin(page_url, href) for cell in cells for href in cell['links'] if href.lower().endswith('.zip')]
        if not zips:
            continue
        metadata = [urljoin(page_url, href) for cell in cells for href in cell['links']
                    if href.lower().endswith(('.xml', '_metadata.txt'))]
        kind = ('seafloor-character' if 'seafloor character' in lower else
                'habitat' if 'habitat' in lower else
                'backscatter' if 'backscatter' in lower else
                'bathymetry')
        for url in zips:
            if '/video_observations/' in urlparse(url).path.lower():
                continue
            if urlparse(url).hostname not in ('pubs.usgs.gov', 'cmgds.marine.usgs.gov'):
                raise ValueError('USGS catalog points to an unexpected product host')
            found.append({'kind': kind, 'description': description, 'archive_url': url,
                          'metadata_url': metadata[0] if metadata else None})
    return sorted({x['archive_url']: x for x in found}.values(), key=lambda x: x['archive_url'])


def release_products(content, page_url, area_name, shared):
    parser = Links()
    parser.feed(content.decode('utf-8', errors='replace'))
    links = [urljoin(page_url, href) for href in parser.links]
    local_key = re.sub(r'[^a-z0-9]', '', area_name.lower().replace('offshore of ', 'offshore '))
    metadata = {urlparse(url).path.rsplit('/', 1)[-1].lower(): url for url in links
                if urlparse(url).path.lower().endswith(('_metadata.xml', '_metadata.txt'))}
    found = []
    for url in links:
        basename = urlparse(url).path.rsplit('/', 1)[-1]
        stem = basename[:-4]
        normalized = re.sub(r'[^a-z0-9]', '', stem.lower())
        if not basename.lower().endswith('.zip') or 'hillshade' in normalized or 'shaded' in normalized:
            continue
        if not any(word in normalized for word in ('bathymetry', 'seafloorcharacter', 'habitat', 'backscatter', 'cmecs')):
            continue
        if shared and local_key not in normalized:
            continue  # A shared DOI does not prove that its other map area's file covers this area.
        if urlparse(url).hostname != 'cmgds.marine.usgs.gov':
            raise ValueError('Unexpected USGS data-release product host')
        kind = ('seafloor-character' if 'seafloorcharacter' in normalized or 'cmecs' in normalized else
                'habitat' if 'habitat' in normalized else
                'backscatter' if 'backscatter' in normalized else 'bathymetry')
        found.append({'kind': kind, 'description': stem, 'archive_url': url,
                      'metadata_url': metadata.get((stem + '_metadata.xml').lower()) or
                                      metadata.get((stem + '_metadata.txt').lower())})
    return sorted({x['archive_url']: x for x in found}.values(), key=lambda x: x['archive_url'])


def inventory():
    index = fetch(INDEX)
    areas = map_areas(index)
    association = json.loads((ROOT / 'catalog/usgs-ds781-sector-associations.json').read_text())
    mapping = association['planning_sectors']
    sector_ids = {s['id'] for s in json.loads((ROOT / 'catalog/coastal-sectors.json').read_text())['sectors']}
    if set(mapping) != {a['name'] for a in areas} or any(not set(ids) <= sector_ids for ids in mapping.values()):
        raise ValueError('USGS map-area planning associations need review')
    for area in areas:
        area['planning_sector_ids'] = mapping[area['name']]
    html_areas = [a for a in areas if a['catalog_kind'] == 'ds781-html']
    def inspect(area):
        page = fetch(area['catalog_url'])
        area['catalog_sha256'] = sha256(page).hexdigest()
        area['products'] = products(page, area['catalog_url'])
        area['priority_product_status'] = 'linked' if area['products'] else 'none-in-this-catalog'
    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(inspect, html_areas))
    release_areas = [a for a in areas if a['catalog_kind'] == 'external-release']
    repeats = {url: sum(a['catalog_url'] == url for a in release_areas)
               for url in {a['catalog_url'] for a in release_areas}}
    def inspect_release(area):
        page, resolved = fetch_release(area['catalog_url'])
        area['resolved_url'] = resolved
        area['catalog_sha256'] = sha256(page).hexdigest()
        area['resolved_kind'] = 'html-data-catalog' if 'data_catalog_' in resolved else 'data-release'
        area['products'] = products(page, resolved) if area['resolved_kind'] == 'html-data-catalog' else []
        if area['resolved_kind'] == 'data-release':
            area['products'] = release_products(page, resolved, area['name'], repeats[area['catalog_url']] > 1)
        area['priority_product_status'] = ('linked' if area['products'] else
                                           'index-link-mismatch' if repeats[area['catalog_url']] > 1 else
                                           'none-in-this-release')
    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(inspect_release, release_areas))
    return {'schema_version': 1, 'source': 'USGS Data Series 781 California State Waters Map Series',
            'index_url': INDEX, 'index_sha256': sha256(index).hexdigest(),
            'retrieved_at': datetime.now(timezone.utc).isoformat(),
            'scope': 'official map-area and product-link inventory; catalog rows are not measured seabed footprints',
            'sector_association_basis': association['basis'],
            'map_areas': areas}


def signature(data):
    # USGS pages can change presentation bytes between requests. Gate on the
    # parsed source identities and product links, while preserving raw hashes
    # in the receipt so reviewers can still inspect page-level changes.
    fields = ('name', 'catalog_url', 'report_url', 'catalog_kind',
              'planning_sector_ids', 'resolved_url', 'resolved_kind',
              'priority_product_status', 'products')
    return {'map_areas': [{field: area[field] for field in fields if field in area}
                          for area in data['map_areas']]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'catalog/usgs-ds781-source-leads.json')
    parser.add_argument('--verify', type=Path)
    args = parser.parse_args()
    data = inventory()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n')
    if args.verify and signature(data) != signature(json.loads(args.verify.read_text())):
        raise SystemExit('USGS DS 781 map-area or original product links changed; review before promotion')
    print(json.dumps({'map_areas': len(data['map_areas']),
                      'html_catalogs': sum(a['catalog_kind'] == 'ds781-html' for a in data['map_areas']),
                      'linked_products': sum(len(a.get('products', [])) for a in data['map_areas'])}))


if __name__ == '__main__':
    main()
