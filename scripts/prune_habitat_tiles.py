"""Keep current and incoming habitat generations before an atomic feed commit.

Only compiler-owned tile names are eligible for deletion. Keeping the outgoing
manifest's tiles gives cached browsers a full refresh cycle to switch manifests.
"""
import argparse
import json
from pathlib import Path
import re

OWNED=re.compile(r'(?:sst-analysis|chlorophyll-observation|wcofs-surface-forecast)--?\d+--?\d+-[a-f0-9]{16}\.json')

def prune(published,incoming):
    removed=0
    for manifest in (incoming/'regions').glob('*/habitat-dynamics.json'):
        ident=manifest.parent.name
        if not re.fullmatch(r'[a-z][a-z0-9-]{1,63}',ident):raise ValueError('Invalid region')
        target=published/'regions'/ident
        keep=set()
        for path in (manifest,target/'habitat-dynamics.json'):
            if not path.exists():continue
            data=json.loads(path.read_text())
            if data['region_id']!=ident or data['schema_version']!=1:raise ValueError('Habitat identity mismatch')
            for layer in data['layers'].values():
                for tile in layer['tiles']:
                    p=Path(tile['path'])
                    if p.parent!=Path('habitat-tiles') or not OWNED.fullmatch(p.name):raise ValueError('Invalid owned tile')
                    keep.add(p.name)
        for path in (target/'habitat-tiles').glob('*.json'):
            if not path.is_symlink() and OWNED.fullmatch(path.name) and path.name not in keep:
                path.unlink();removed+=1
    return removed

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('published',type=Path);p.add_argument('incoming',type=Path)
    a=p.parse_args();print('Removed',prune(a.published,a.incoming),'unreferenced old habitat tiles')
