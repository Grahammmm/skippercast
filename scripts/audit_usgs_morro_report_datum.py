"""Pin the Morro Bay USGS report's depth reference without clearing TIFFs.

The report speaks about its own depth values. The three linked bathymetry
GeoTIFFs still require product-specific datum and uncertainty review before
they can supply target depths or exportable fishing positions.
"""
import argparse
from datetime import datetime, timezone
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
from urllib.request import Request, urlopen


class Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)


def audit(manifest, raw, ledger):
    if (manifest.get('scope') != 'usgs-morro-report-depth-reference-review'
            or manifest.get('depth_reference_reported') != 'MLLW'
            or len(manifest.get('release_ids', [])) != 3):
        raise ValueError('Unexpected USGS report review manifest')
    if hashlib.sha256(raw).hexdigest() != manifest['report_sha256']:
        raise ValueError('USGS report content changed; review its datum statement')
    if ledger.get('scope') != 'california-usgs-original-bathymetry-datum-ledger':
        raise ValueError('Original USGS raster ledger required')
    parser = Text()
    parser.feed(raw.decode('utf-8'))
    report = ' '.join(' '.join(parser.parts).split()).lower()
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
    return {'schema_version': 1, 'scope': manifest['scope'],
            'reviewed_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
            'report_url': manifest['report_url'],
            'report_sha256': manifest['report_sha256'],
            'report_depth_reference': 'MLLW',
            'report_evidence': 'The report states that its depths are relative to MLLW from verified tides and links three corresponding data releases.',
            'sources': [{'release_id': row['id'], 'archive_url': row['archive_url'],
                         'archive_sha256': row['archive_sha256'],
                         'original_tiff_declared_vertical_datum': row['declared_vertical_datum'],
                         'has_per_cell_product_uncertainty': False,
                         'depth_qualified_for_fishing': False}
                        for row in sorted(sources, key=lambda r: r['id'])],
            'fishing_target': False, 'exportable': False,
            'limitation': 'Report-level MLLW terminology is not an original GeoTIFF datum certificate or a per-cell uncertainty field; no fishing depth, point or route is promoted.'}


def fetch(url):
    if url != 'https://pubs.usgs.gov/publication/ofr20231064/full':
        raise ValueError('Unreviewed USGS report URL')
    with urlopen(Request(url, headers={'User-Agent': 'SkipperCast source audit/1.0'}),
                 timeout=30) as response:
        raw = response.read(1_000_001)
        if (response.status != 200 or response.url != url or len(raw) > 1_000_000
                or 'html' not in response.headers.get('Content-Type', '')):
            raise ValueError('Unexpected USGS report response')
        return raw


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path,
                        default=Path('catalog/usgs-morro-report-datum-source.json'))
    parser.add_argument('--ledger', type=Path,
                        default=Path('dist/data/usgs-depth-datum-ledger.json'))
    parser.add_argument('--cache', type=Path,
                        default=Path('var/usgs-report-cache/ofr20231064.html'))
    parser.add_argument('--fetch', action='store_true')
    parser.add_argument('--output', type=Path,
                        default=Path('dist/data/usgs-morro-report-datum-review.json'))
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text())
    if args.fetch:
        raw = fetch(manifest['report_url'])
        args.cache.parent.mkdir(parents=True, exist_ok=True)
        args.cache.write_bytes(raw)
    else:
        raw = args.cache.read_bytes()
    result = audit(manifest, raw, json.loads(args.ledger.read_text()))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temp = args.output.with_suffix(args.output.suffix + '.tmp')
    temp.write_text(json.dumps(result, separators=(',', ':')) + '\n')
    temp.replace(args.output)
    print('USGS report MLLW reference confirmed; 3 original TIFFs remain unqualified')


if __name__ == '__main__':
    main()
