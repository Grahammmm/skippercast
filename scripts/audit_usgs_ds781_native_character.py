"""Audit original DS781 seafloor-character rasters across reviewed map areas.

Every archive is SHA-pinned by this receipt, but no classified pixel becomes a
fishing target. A missing/changed raster or value table remains an explicit gap.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
import zipfile

from scripts.inspect_usgs_native_grids import inspect_archive

MAX_ARCHIVE = 180_000_000
HOSTS = {'pubs.usgs.gov', 'cmgds.marine.usgs.gov'}


def allowed(url):
    p = urlsplit(url or '')
    return p.scheme == 'https' and p.hostname in HOSTS and p.path.endswith('.zip') and (
        p.path.startswith('/ds/781/') or p.path.startswith('/data/csmp/')
        or p.path.startswith('/data-releases/media/'))


def download(url, path):
    if not allowed(url):
        raise ValueError('Archive URL is outside reviewed USGS hosts')
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.part')
    try:
        with urlopen(Request(url, headers={'User-Agent': 'SkipperCast statewide native character review/1.0'}), timeout=60) as response, temp.open('wb') as out:
            if response.status != 200 or not allowed(response.url):
                raise ValueError('Archive redirected outside reviewed USGS hosts')
            size = 0
            while chunk := response.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_ARCHIVE:
                    raise ValueError('Archive exceeds bounded source review')
                out.write(chunk)
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


def audit(inventory, metadata, cache, *, selected=None, workers=3, fetcher=download):
    if (inventory.get('schema_version') != 1 or len(inventory.get('map_areas', [])) != 39
            or metadata.get('scope') != 'usgs-ds781-original-fgdc-metadata-triage'):
        raise ValueError('Complete DS781 catalog and metadata triage required')
    by_url = {row['archive_url']: row for row in metadata['records']}
    if len(by_url) != metadata['record_count']:
        raise ValueError('Duplicate original archive metadata')
    tasks = []
    for area in inventory['map_areas']:
        if selected and area['name'] not in selected:
            continue
        for product in area['products']:
            if product['kind'] != 'seafloor-character' or product['description'].lower().startswith('cmecs'):
                continue
            url = product['archive_url']
            if not allowed(url) or url not in by_url:
                raise ValueError('Unreviewed character archive link')
            tasks.append((area, product, by_url[url]))
    if selected and {area['name'] for area, _, _ in tasks} != selected:
        raise ValueError('Selected map area has no raster character archive')
    if not tasks:
        raise ValueError('No original character rasters selected')

    def one(task):
        area, product, meta = task
        url = product['archive_url']
        lead = {'map_area': area['name'], 'planning_sector_ids': area['planning_sector_ids'],
                'archive_url': url, 'catalog_url': area['catalog_url'],
                'metadata_url': meta.get('xml_url'), 'metadata_sha256': meta.get('metadata_sha256')}
        if meta['status'] != 'reviewed' or meta.get('rights_evidence') != 'explicit-public-domain-redistribution':
            return {**lead, 'status': 'held', 'issue': 'Original metadata or reuse rights not reviewed'}
        path = cache / (hashlib.sha256(url.encode()).hexdigest()[:24] + '.zip')
        try:
            if not path.exists():
                fetcher(url, path)
            if not 0 < path.stat().st_size <= MAX_ARCHIVE:
                raise ValueError('Archive size outside bounded source review')
            with path.open('rb') as stream:
                digest = hashlib.file_digest(stream, 'sha256').hexdigest()
            # The original FGDC review does not describe a reliable measured
            # polygon. Use global bounds only for its coarse identity check;
            # inspect_archive reports exact georeferenced raster bounds and
            # measured pixel totals, never a full-coverage polygon.
            legacy = {'kind': 'seafloor_character', 'bounds': {
                'westbc': -130, 'eastbc': -115, 'southbc': 30, 'northbc': 43}}
            raster = inspect_archive(path, legacy, product['description'])
            return {**lead, 'status': 'ok', 'archive_sha256': digest,
                    'archive_bytes': path.stat().st_size, **raster}
        except (OSError, ValueError, zipfile.BadZipFile, RuntimeError) as error:
            return {**lead, 'status': 'failed', 'issue': str(error)[:220]}

    rows = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(one, task) for task in tasks]
        for future in as_completed(futures):
            rows.append(future.result())
    rows.sort(key=lambda row: (row['map_area'], row['archive_url']))
    sector_ids = sorted({sector for area in inventory['map_areas'] for sector in area['planning_sector_ids']})
    sectors = [{'sector_id': sector,
                'catalog_archive_leads': sum(sector in row['planning_sector_ids'] for row in rows),
                'opened_native_rasters': sum(sector in row['planning_sector_ids'] and row['status'] == 'ok' for row in rows),
                'verified_original_class_tables': sum(sector in row['planning_sector_ids'] and
                    row.get('class_table_status') == 'verified' for row in rows)}
               for sector in sector_ids]
    return {'schema_version': 1, 'scope': 'usgs-ds781-statewide-original-character-raster-audit',
            'reviewed_at': datetime.now(timezone.utc).isoformat(),
            'source_catalog_sha256': inventory['index_sha256'],
            'source_metadata_inventory_sha256': metadata['source_inventory_sha256'],
            'product_count': len(rows), 'inspected_count': sum(row['status'] == 'ok' for row in rows),
            'held_count': sum(row['status'] == 'held' for row in rows),
            'failed_count': sum(row['status'] == 'failed' for row in rows),
            'fishing_target': False, 'exportable': False,
            'limitations': [
                'These original character rasters are historical source evidence, not qualified fishing spots or a continuous California habitat map.',
                'Raster bounds include nodata and planning-sector labels are catalog associations, not a measured spatial join.',
                'Class values without a verified original value table do not identify rock; depth, MPAs, hazards, rules and routes remain separate gates.'
            ], 'sectors': sectors, 'products': rows}


def signature(packet):
    return {key: value for key, value in packet.items() if key != 'reviewed_at'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inventory', type=Path, default=Path('catalog/usgs-ds781-source-leads.json'))
    parser.add_argument('--metadata', type=Path, default=Path('catalog/usgs-ds781-metadata-review.json'))
    parser.add_argument('--cache', type=Path, default=Path('var/usgs-ds781-character-cache'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--area', action='append')
    parser.add_argument('--workers', type=int, default=3)
    parser.add_argument('--verify', type=Path, help='Reviewed original-raster baseline; changed evidence fails')
    args = parser.parse_args()
    if not 1 <= args.workers <= 6:
        raise ValueError('workers must be 1–6')
    result = audit(json.loads(args.inventory.read_text()), json.loads(args.metadata.read_text()),
                   args.cache, selected=set(args.area) if args.area else None, workers=args.workers)
    if args.verify and signature(result) != signature(json.loads(args.verify.read_text())):
        raise ValueError('Original DS781 character evidence changed; review before publication')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temp = args.output.with_suffix(args.output.suffix + '.tmp')
    temp.write_text(json.dumps(result, separators=(',', ':')) + '\n')
    temp.replace(args.output)
    print(json.dumps({'products': result['product_count'], 'inspected': result['inspected_count'],
                      'held': result['held_count'], 'failed': result['failed_count']}))


if __name__ == '__main__':
    main()
