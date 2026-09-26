"""Fetch fresh official CDFW MPAs for the unpublished Big Sur Block 03 screen."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from urllib.request import Request, urlopen

from scripts.prepare_regional_mpas import source_url, validate_response


ROOT = Path(__file__).resolve().parents[1]
REGION = 'south-big-sur-san-simeon'
EXPECTED = {'Piedras Blancas SMCA', 'Piedras Blancas SMR'}


def collect():
    config = json.loads((ROOT / 'regions' / REGION / 'region.json').read_text())
    if config['id'] != REGION or config['mpa']['minimum_features'] != 2:
        raise ValueError('Regional MPA source configuration changed')
    bounds = config['mpa']['bounds']
    url = source_url(bounds)
    with urlopen(Request(url, headers={'User-Agent': 'SkipperCast Big Sur Block03 research MPA review'}), timeout=45) as response:
        if response.status != 200 or response.url != url:
            raise ValueError('Official CDFW MPA response failed or redirected')
        raw = response.read(6_000_001)
    if not raw or len(raw) > 6_000_000:
        raise ValueError('Official CDFW MPA response empty or oversized')
    result = json.loads(raw)
    features = validate_response(result, bounds, 2)
    if {item['properties']['NAME'] for item in features} != EXPECTED:
        raise ValueError('Official Big Sur MPA identity changed; review needed')
    result.update(source_url=url, checked_at=datetime.now(timezone.utc).isoformat(),
                  verification_sha256=hashlib.sha256(raw).hexdigest(),
                  status='research-closure-screen-only')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to((ROOT / 'var/review').resolve()):
        raise ValueError('Raw CDFW geometry must stay under var/review')
    result = collect()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, separators=(',', ':')) + '\n')
    print('CDFW Big Sur MPAs:', len(result['features']))


if __name__ == '__main__':
    main()
