"""Compile reviewed starter methods for every species offered in each region.

Habitat and tactics are guidance, not current fish presence or legal clearance.
New regions fail closed until each target has a reviewed method.
Every published region is validated and built before any file is written.
"""
import json
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
FIELDS = ('priority', 'find', 'rig', 'steps', 'adjust')


def build(root=ROOT):
    source = json.loads((root / 'catalog/primary-strategies.json').read_text())
    if source.get('schema_version') != 1 or not source.get('reviewed_at') or not isinstance(source.get('species'), dict):
        raise ValueError('Invalid strategy catalog')
    for species_id, strategy in source['species'].items():
        if not isinstance(strategy, dict) or not all(strategy.get(key) for key in FIELDS):
            raise ValueError(f'Incomplete strategy: {species_id}')
        if not isinstance(strategy['find'], list) or not isinstance(strategy['steps'], list):
            raise ValueError(f'Empty strategy step: {species_id}')
        if not all(isinstance(value, str) and value.strip() for value in strategy['find'] + strategy['steps']):
            raise ValueError(f'Empty strategy step: {species_id}')
        if len(strategy['find']) < 2 or len(strategy['steps']) < 3:
            raise ValueError(f'Strategy lacks a practical sequence: {species_id}')
        links = strategy.get('method_sources', [])
        if not isinstance(links, list) or not all(isinstance(link, dict) for link in links):
            raise ValueError(f'Invalid method source: {species_id}')
        for link in links:
            url = link.get('url', '')
            if not link.get('title') or not isinstance(url, str) or urlsplit(url).scheme != 'https':
                raise ValueError(f'Invalid method source: {species_id}')
    packets = []
    for region_path in sorted((root / 'regions').glob('*/region.json')):
        region = json.loads(region_path.read_text())
        if region['status'] == 'draft':
            continue
        if not isinstance(region.get('species'), list) or not all(isinstance(key, str) for key in region['species']):
            raise ValueError(f"{region['id']} species list invalid")
        missing = set(region['species']) - source['species'].keys()
        if missing:
            raise ValueError(f"{region['id']} lacks starter methods for {sorted(missing)}")
        packet = {
            'schema_version': 1,
            'region_id': region['id'],
            'reviewed_at': source['reviewed_at'],
            'scope': source['scope'],
            'strategies': {key: source['species'][key] for key in region['species']},
            'limitations': 'Starter boat-fishing methods only. Check date- and position-specific rules, gear, MPA access, species ID, conditions, and actual fish/forage signs before fishing.',
        }
        packets.append((root / 'dist/regions' / region['id'] / 'strategies.json', packet))
    written = []
    for target, packet in packets:
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix('.json.tmp')
        temporary.write_text(json.dumps(packet, separators=(',', ':'), ensure_ascii=False) + '\n')
        temporary.replace(target)
        written.append(str(target.relative_to(root)))
    return written


if __name__ == '__main__':
    print('\n'.join(build()))
