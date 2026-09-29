"""Pin the official Block 03 CARIS archive as an uninspected acquisition lead."""
import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import tarfile
from urllib.request import Request, urlopen


URL = ('https://data.ngdc.noaa.gov/platforms/ocean/ships/harold_heath/'
       'BSS_Block03/multibeam/data/version2/ancillary/BSSBlock03_caris.tar.gz')
CATALOG = 'https://www.ngdc.noaa.gov/ships/r_v_harold_heath/BSS_Block03_mb.html'
PREFIX_BYTES = 8_388_608


def fetch_prefix():
    with urlopen(Request(URL, headers={
            'User-Agent': 'SkipperCast original-survey-source-review/1.0',
            'Range': f'bytes=0-{PREFIX_BYTES - 1}'}), timeout=60) as response:
        if (response.status != 206 or response.geturl() != URL
                or response.headers.get('Content-Range')
                != f'bytes 0-{PREFIX_BYTES - 1}/42090312342'):
            raise ValueError('Official CARIS archive byte range unavailable or changed')
        data = response.read(PREFIX_BYTES + 1)
    if len(data) != PREFIX_BYTES:
        raise ValueError('Official CARIS archive prefix truncated or exceeded bound')
    return data


def inspect_prefix(data):
    """Read only complete early text members and a later TPE member header."""
    if len(data) != PREFIX_BYTES:
        raise ValueError('CARIS archive prefix size changed')
    found = {}
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode='r|gz') as archive:
            for member in archive:
                if member.name == 'BSS_Block03/BSS_Block03.hpf':
                    if member.size > 10_000:
                        raise ValueError('Unexpected CARIS project-definition size')
                    found['project'] = archive.extractfile(member).read()
                elif member.name.endswith('/LogFile') and '45HaroldHeath_PPK/' in member.name:
                    if member.size > 100_000:
                        raise ValueError('Unexpected CARIS processing-log size')
                    found['log'] = archive.extractfile(member).read()
                elif member.name.endswith('/TPE') and '45HaroldHeath_PPK/' in member.name:
                    found['tpe_size'] = member.size
                    break  # The full TPE member lies beyond this bounded byte range.
    except (EOFError, OSError, tarfile.TarError) as exc:
        raise ValueError('CARIS prefix ended before expected project records') from exc
    if set(found) != {'project', 'log', 'tpe_size'}:
        raise ValueError('Expected project, processing log or TPE header is missing')
    project = found['project'].decode('latin1')
    log = found['log'].decode('latin1')
    if ('PROJECTION = AUTO_UTM,WG84_10N' not in project
            or 'Uncertainty Source: Vessel Settings' not in log
            or 'Compute TPU end:' not in log
            or 'Tide Values:  Measured 0.000 (m), Zoning 0.000 (m)' not in log
            or found['tpe_size'] <= 0):
        raise ValueError('CARIS projection or uncertainty-processing evidence changed')
    return {'prefix_bytes': len(data), 'prefix_sha256': hashlib.sha256(data).hexdigest(),
            'project_definition_member_sha256': hashlib.sha256(found['project']).hexdigest(),
            'processing_log_member_sha256': hashlib.sha256(found['log']).hexdigest(),
            'project_projection': 'AUTO_UTM,WG84_10N',
            'processing_log_computed_tpu': True,
            'processing_log_uncertainty_source': 'Vessel Settings',
            'processing_log_tide_uncertainty_input_m': 0.0,
            'tpe_member_declared_bytes': found['tpe_size'],
            'tpe_member_downloaded_or_decoded': False}


def inspect(head=None, prefix=None):
    if head is None:
        with urlopen(Request(URL, method='HEAD', headers={
                'User-Agent': 'SkipperCast original-survey-source-review/1.0'}), timeout=30) as response:
            metadata = {'status': response.status, 'url': response.geturl(),
                        'content_length_bytes': response.headers.get('Content-Length'),
                        'last_modified': response.headers.get('Last-Modified'),
                        'accept_ranges': response.headers.get('Accept-Ranges'),
                        'content_type': response.headers.get('Content-Type')}
    else:
        metadata = head()
    if (metadata['status'] != 200 or metadata['url'] != URL
            or int(metadata['content_length_bytes']) != 42_090_312_342
            or metadata['accept_ranges'] != 'bytes'
            or not metadata['last_modified']):
        raise ValueError('Official CARIS archive availability or identity changed')
    prefix_evidence = inspect_prefix(fetch_prefix() if prefix is None else prefix)
    return {'schema_version': 1, 'scope': 'bss03-caris-original-project-acquisition-lead',
            'checked_at': datetime.now(timezone.utc).isoformat(),
            'catalog_url': CATALOG, 'archive_url': URL,
            'http_head': metadata,
            'bounded_original_prefix': prefix_evidence,
            'archive_downloaded': False, 'archive_contents_verified': False,
            'cube_or_tpu_surface_confirmed': False,
            'horizontal_realization_confirmed': False,
            'producer_redistribution_terms_confirmed': False,
            'depth_qualified': False, 'fishing_target': False, 'exportable': False,
            'next_acquisition': ('Request a targeted CARIS/BASE or CUBE depth, TPU and '
                                 'horizontal-frame extract from the survey custodian; '
                                 'the published archive is roughly 42 GB and its internal '
                                 'uncertainty output has not been decoded.'),
            'limitations': [
                'The first 8 MiB reveals the CARIS project definition, one processing log and a TPE member header, not a decoded per-cell uncertainty surface.',
                'CARIS project projection WG84_10N and released ArcInfo grid EPSG:26910 require a documented horizontal-frame and processing crosswalk; neither establishes the final raster realization or epoch.',
                'The log shows a TPU computation based on vessel settings with zero-valued tide uncertainty inputs; this is not a verified upper bound on the published bathymetry.',
                'The original public 2 m ArcInfo grid has no verified product uncertainty and does not state NAD83 realization or epoch.',
            ]}


def stable(report):
    return {k: v for k, v in report.items() if k != 'checked_at'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('research/receipts/bss03-caris-acquisition-lead.json'))
    parser.add_argument('--verify', type=Path)
    args = parser.parse_args()
    report = inspect()
    if args.verify and stable(report) != stable(json.loads(args.verify.read_text())):
        raise SystemExit('Official CARIS archive metadata changed; review before publishing')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    print(json.dumps({'available': True, 'contents_verified': False, 'depth_qualified': False}))


if __name__ == '__main__':
    main()
