"""Audit original XML metadata from newer USGS DS781 DOI releases."""
from datetime import datetime, timezone
from pathlib import Path
import sys
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # repository root, for research.*
from research.scripts.audit_usgs_map_metadata import (
    MAX_XML, _audit_xml, _bind, _digest, _healthy, _main, parse_metadata,
)
from research.scripts.discover_usgs_doi_releases import official

SCOPE = 'usgs-state-waters-doi-native-metadata'


def fetch(url):
    with urlopen(Request(url,headers={'User-Agent':'SkipperCast USGS original metadata review/1.0'}),timeout=25) as response:
        raw=response.read(MAX_XML+1)
        if len(raw)>MAX_XML:raise ValueError('USGS XML exceeds size limit')
        return response.url,raw


def _inventory(data):
    if (not isinstance(data, dict) or data.get('scope') != 'usgs-state-waters-doi-product-links'
            or not isinstance(data.get('releases'), list)):
        raise ValueError('Invalid USGS DOI inventory')
    releases = data['releases']
    source = data.get('index_url')
    sources, targets = [], {}
    product_count = 0
    for release in releases:
        ident, landing, areas = release['release_id'], release['landing_url'], release['study_areas']
        doi = release.get('doi')
        if (not isinstance(ident, str) or not ident or (doi is not None and doi != f'https://doi.org/10.5066/{ident}')
                or not isinstance(areas, list) or not all(isinstance(area, str) for area in areas)):
            raise ValueError('Invalid USGS DOI release identity')
        products = release['products']
        if not isinstance(products, list) or (landing is None and products) or (
                landing is not None and not official(landing, ident)):
            raise ValueError('Invalid USGS DOI release landing or product list')
        areas = sorted(set(areas))
        attribution = _digest([source, ident, doi, landing, areas, release.get('official_source_page')])
        sources.append(attribution)
        product_count += len(products)
        for product in products:
            url, archive, kind, filename = (product[field] for field in ('metadata_url', 'archive_url', 'kind', 'filename'))
            if (not official(url, ident, landing) or not urlsplit(url).path.lower().endswith('.xml')
                    or not official(archive, ident, landing) or not urlsplit(archive).path.lower().endswith('.zip')
                    or kind not in ('bathymetry', 'seafloor_character', 'cmecs')
                    or not isinstance(filename, str) or not filename):
                raise ValueError('Invalid original XML product identity for DOI release')
            targets[_digest([attribution, url, archive, kind, filename])] = (url, {
                'release_id': ident, 'study_areas': areas, 'landing_url': landing, 'kind': kind,
                'archive_url': archive, 'filename': filename,
            })
    if data.get('release_count', len(releases)) != len(releases) or data.get('product_count', product_count) != product_count:
        raise ValueError('USGS DOI inventory counts do not match products')
    healthy = _healthy(data, releases) and all(row['landing_url'] for row in releases)
    return _bind(SCOPE, source, sources, targets, healthy)


def _parse(url, result, attribution, *, now):
    final, raw = result
    if not official(final, attribution['release_id'], attribution['landing_url']):
        raise ValueError('USGS XML redirected outside reviewed DOI release')
    return parse_metadata(url, raw, now=now)


def audit(releases, previous=None, *, now=None, fetcher=fetch):
    return _audit_xml(_inventory(releases), previous, now=now or datetime.now(timezone.utc), fetcher=fetcher,
                      parse=_parse, scope=SCOPE,
                      method='Original CMGDS metadata XML linked from a USGS DOI release. Bounds and class descriptions are source evidence only, not surveyed-pixel or fishing coverage.')


def main():
    _main('releases', __doc__, _inventory, audit, SCOPE)


if __name__=='__main__':main()
