"""Pin the Morro Bay USGS report's depth reference without clearing TIFFs.

The report speaks about its own depth values. The three linked bathymetry
GeoTIFFs still require product-specific datum and uncertainty review before
they can supply target depths or exportable fishing positions.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET


def audit(manifest, raw, ledger, product_xml):
    if (manifest.get('scope') != 'usgs-morro-report-depth-reference-review'
            or manifest.get('depth_reference_reported') != 'MLLW'
            or len(manifest.get('release_ids', [])) != 3):
        raise ValueError('Unexpected USGS report review manifest')
    if hashlib.sha256(raw).hexdigest() != manifest['report_sha256']:
        raise ValueError('USGS report content changed; review its datum statement')
    if ledger.get('scope') != 'california-usgs-original-bathymetry-datum-ledger':
        raise ValueError('Original USGS raster ledger required')
    report = ' '.join(' '.join(ET.fromstring(raw).itertext()).split()).lower()
    if ('depth, as referred to in this report, is relative to mean lower low water (mllw) from verified tides.'
            not in report):
        raise ValueError('USGS report MLLW statement changed')
    for name in ('offshore of morro bay', 'offshore of point estero',
                 'offshore of point buchon'):
        if 'bathymetry, backscatter intensity, and benthic habitat ' + name not in report:
            raise ValueError('USGS report no longer links one of the three releases')
    sources = [row for row in ledger['sources'] if row['id'] in manifest['release_ids']]
    if len(sources) != 3 or {row['id'] for row in sources} != set(manifest['release_ids']):
        raise ValueError('Linked original bathymetry rasters not fully audited')
    if any(row['has_per_cell_product_uncertainty'] or row['depth_qualified_for_fishing']
           for row in sources):
        raise ValueError('USGS bathymetry qualification changed; review the gate')
    if set(product_xml) != set(manifest['release_ids']):
        raise ValueError('All three original product XML files are required')
    source_rows = []
    for row in sorted(sources, key=lambda r: r['id']):
        xml = product_xml[row['id']]
        if hashlib.sha256(xml).hexdigest() != row['metadata_sha256']:
            raise ValueError('Original USGS product XML changed: ' + row['id'])
        root = ET.fromstring(xml)
        vertical_accuracy = ' '.join((root.findtext('.//vertaccr') or '').split())
        horizontal_accuracy = ' '.join((root.findtext('.//horizpar') or '').split())
        if ('Estimated to be no less than 20 cm' not in vertical_accuracy
                or 'total propagated uncertainties' not in vertical_accuracy
                or 'Accuracies of final products may be lower' not in horizontal_accuracy):
            raise ValueError('Original USGS accuracy statements changed: ' + row['id'])
        source_rows.append({'release_id': row['id'], 'archive_url': row['archive_url'],
                            'archive_sha256': row['archive_sha256'],
                            'metadata_url': row['metadata_url'],
                            'metadata_sha256': row['metadata_sha256'],
                            'original_tiff_declared_vertical_datum': row['declared_vertical_datum'],
                            'vertical_accuracy_lower_bound_m': 0.2,
                            'vertical_accuracy_upper_bound_m': None,
                            'has_per_cell_product_uncertainty': False,
                            'depth_qualified_for_fishing': False})
    return {'schema_version': 1, 'scope': manifest['scope'],
            'reviewed_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
            'report_url': manifest['report_url'],
            'report_sha256': manifest['report_sha256'],
            'report_depth_reference': 'MLLW',
            'report_evidence': 'The report states that its depths are relative to MLLW from verified tides and links three corresponding data releases.',
            'sources': source_rows,
            'fishing_target': False, 'exportable': False,
            'limitation': 'Report-level MLLW terminology is not an original GeoTIFF datum certificate. The original XML states a vertical accuracy floor of 20 cm but no upper bound or per-cell uncertainty; it cannot prove the <=1 m target gate. No fishing depth, point or route is promoted.'}


def fetch(url):
    if url != 'https://pubs.usgs.gov/of/2023/1064/ofr20231064.xml':
        raise ValueError('Unreviewed USGS report URL')
    with urlopen(Request(url, headers={'User-Agent': 'SkipperCast source audit/1.0'}),
                 timeout=30) as response:
        raw = response.read(1_000_001)
        if (response.status != 200 or response.url != url or len(raw) > 1_000_000
                or 'xml' not in response.headers.get('Content-Type', '')):
            raise ValueError('Unexpected USGS report response')
        return raw


def fetch_product_xml(url):
    if (not url.startswith('https://cmgds.marine.usgs.gov/data-releases/media/')
            or not url.endswith('.xml')):
        raise ValueError('Unreviewed USGS product XML URL')
    with urlopen(Request(url, headers={'User-Agent': 'SkipperCast source audit/1.0'}),
                 timeout=30) as response:
        raw = response.read(1_500_001)
        if response.status != 200 or response.url != url or len(raw) > 1_500_000:
            raise ValueError('Unexpected USGS product XML response')
        return raw


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path,
                        default=Path('catalog/usgs-morro-report-datum-source.json'))
    parser.add_argument('--ledger', type=Path,
                        default=Path('dist/data/usgs-depth-datum-ledger.json'))
    parser.add_argument('--cache', type=Path,
                        default=Path('var/usgs-report-cache/ofr20231064.xml'))
    parser.add_argument('--fetch', action='store_true')
    parser.add_argument('--output', type=Path,
                        default=Path('dist/data/usgs-morro-report-datum-review.json'))
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text())
    ledger = json.loads(args.ledger.read_text())
    sources = {row['id']: row for row in ledger['sources']
               if row['id'] in manifest['release_ids']}
    if set(sources) != set(manifest['release_ids']):
        raise ValueError('Original bathymetry ledger does not contain all reviewed products')
    if args.fetch:
        raw = fetch(manifest['report_url'])
        args.cache.parent.mkdir(parents=True, exist_ok=True)
        args.cache.write_bytes(raw)
    else:
        raw = args.cache.read_bytes()
    product_xml = {}
    for ident, source in sources.items():
        cache = args.cache.parent / (ident + '-bathymetry.xml')
        if args.fetch:
            product_xml[ident] = fetch_product_xml(source['metadata_url'])
            cache.write_bytes(product_xml[ident])
        else:
            product_xml[ident] = cache.read_bytes()
    result = audit(manifest, raw, ledger, product_xml)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temp = args.output.with_suffix(args.output.suffix + '.tmp')
    temp.write_text(json.dumps(result, separators=(',', ':')) + '\n')
    temp.replace(args.output)
    print('USGS report MLLW reference and three original XML accuracy floors confirmed; TIFFs remain unqualified')


if __name__ == '__main__':
    main()
