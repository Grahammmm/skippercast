"""Keep current and incoming habitat generations before an atomic feed commit.

Only compiler-owned tile names are eligible for deletion. Keeping the outgoing
manifest's tiles gives cached browsers a full refresh cycle to switch manifests.
"""
import argparse
import json
from pathlib import Path
import re
import sys

OWNED=re.compile(r'(?:sst-analysis|chlorophyll-observation|wcofs-surface-forecast)--?\d+--?\d+-[a-f0-9]{16}\.json')

def _load(path,ident):
    try:data=json.loads(path.read_text())
    except (OSError,ValueError):raise ValueError(f'Habitat manifest unreadable: {ident}') from None
    layers=data.get('layers') if isinstance(data,dict) else None
    if not (isinstance(layers,dict) and all(isinstance(v,dict) and isinstance(v.get('tiles'),list)
            and all(isinstance(t,dict) and isinstance(t.get('path'),str) for t in v['tiles']) for v in layers.values())):
        raise ValueError(f'Habitat manifest misshaped: {ident}')
    return data

def prune(published,incoming):
    """Check every manifest first; only then delete the planned stale tiles (all-or-nothing)."""
    plan=[]
    for manifest in sorted((incoming/'regions').glob('*/habitat-dynamics.json')):
        ident=manifest.parent.name
        if not re.fullmatch(r'[a-z][a-z0-9-]{1,63}',ident):raise ValueError(f'Invalid region: {ident}')
        target=published/'regions'/ident
        keep=set()
        for path in (manifest,target/'habitat-dynamics.json'):
            if not path.exists():continue
            data=_load(path,ident)
            if data.get('region_id')!=ident or data.get('schema_version')!=1:raise ValueError(f'Habitat identity mismatch: {ident}')
            for layer in data['layers'].values():
                for tile in layer['tiles']:
                    p=Path(tile['path'])
                    if p.parent!=Path('habitat-tiles') or not OWNED.fullmatch(p.name):raise ValueError(f'Invalid owned tile: {ident}')
                    keep.add(p.name)
        if (target/'habitat-tiles').is_symlink():raise ValueError(f'Habitat tile folder is a link: {ident}')
        plan+=[path for path in sorted((target/'habitat-tiles').glob('*.json'))
               if not path.is_symlink() and OWNED.fullmatch(path.name) and path.name not in keep]
    for path in plan:path.unlink()
    return len(plan)

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('published',type=Path);p.add_argument('incoming',type=Path)
    a=p.parse_args(argv)
    try:removed=prune(a.published,a.incoming)
    except ValueError as error:
        print(f'prune_habitat_tiles: {error}',file=sys.stderr);return 1
    print('Removed',removed,'unreferenced old habitat tiles');return 0

if __name__=='__main__':sys.exit(main())
