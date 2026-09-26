"""Pin the official Block 03 CARIS archive as an uninspected acquisition lead."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from urllib.request import Request, urlopen


URL = ('https://data.ngdc.noaa.gov/platforms/ocean/ships/harold_heath/'
       'BSS_Block03/multibeam/data/version2/ancillary/BSSBlock03_caris.tar.gz')
CATALOG = 'https://www.ngdc.noaa.gov/ships/r_v_harold_heath/BSS_Block03_mb.html'


def inspect(head=None):
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
            or int(metadata['content_length_bytes']) < 1_000_000_000
            or metadata['accept_ranges'] != 'bytes'
            or not metadata['last_modified']):
        raise ValueError('Official CARIS archive availability or identity changed')
    return {'schema_version': 1, 'scope': 'bss03-caris-original-project-acquisition-lead',
            'checked_at': datetime.now(timezone.utc).isoformat(),
            'catalog_url': CATALOG, 'archive_url': URL,
            'http_head': metadata,
            'archive_downloaded': False, 'archive_contents_verified': False,
            'cube_or_tpu_surface_confirmed': False,
            'horizontal_realization_confirmed': False,
            'producer_redistribution_terms_confirmed': False,
            'depth_qualified': False, 'fishing_target': False, 'exportable': False,
            'next_acquisition': ('Request a targeted CARIS/BASE or CUBE depth, TPU and '
                                 'horizontal-frame extract from the survey custodian; '
                                 'the published archive is roughly 42 GB and its internal '
                                 'contents have not been inspected.'),
            'limitations': [
                'An HTTP HEAD receipt proves only that the official archive endpoint is available; it does not establish that any TPU/CUBE grid exists inside.',
                'The original public 2 m ArcInfo grid has no verified product uncertainty and does not state NAD83 realization or epoch.',
            ]}


def stable(report):
    return {k: v for k, v in report.items() if k != 'checked_at'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('dist/data/bss03-caris-acquisition-lead.json'))
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
