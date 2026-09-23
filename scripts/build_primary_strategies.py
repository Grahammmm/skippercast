"""Compile reviewed starter methods for every species offered in each region.

Habitat and tactics are guidance, not current fish presence or legal clearance.
New regions fail closed until each target has a reviewed method.
"""
import json
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
FIELDS = ('priority', 'find', 'rig', 'steps', 'adjust')


def build(root=ROOT):
    source = json.loads((root / 'catalog/primary-strategies.json').read_text())
    if source.get('schema_version') != 1 or not source.get('reviewed_at'):
        raise ValueError('Invalid strategy catalog')
    for species_id, strategy in source['species'].items():
        if not all(strategy.get(key) for key in FIELDS):
            raise ValueError(f'Incomplete strategy: {species_id}')
        if not all(isinstance(value, str) and value.strip() for value in strategy['find'] + strategy['steps']):
            raise ValueError(f'Empty strategy step: {species_id}')
        if len(strategy['find']) < 2 or len(strategy['steps']) < 3:
            raise ValueError(f'Strategy lacks a practical sequence: {species_id}')
        for link in strategy.get('method_sources', []):
            if not link.get('title') or urlsplit(link.get('url', '')).scheme != 'https':
                raise ValueError(f'Invalid method source: {species_id}')
    written = []
    for region_path in sorted((root / 'regions').glob('*/region.json')):
        region = json.loads(region_path.read_text())
        if region['status'] == 'draft':
            continue
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
        target = root / 'dist/regions' / region['id'] / 'strategies.json'
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix('.json.tmp')
        temporary.write_text(json.dumps(packet, separators=(',', ':'), ensure_ascii=False) + '\n')
        temporary.replace(target)
        written.append(str(target.relative_to(root)))
    return written


if __name__ == '__main__':
    print('\n'.join(build()))
