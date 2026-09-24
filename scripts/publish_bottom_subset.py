"""Merge a reviewed, hash-bound survey subset into a regional web package.

Run the original-survey compiler first, review its receipts, then use this step
before platform.build and release tests. This does not refresh legal permission.
"""
import argparse
import hashlib
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from skippercast.platform.contracts import REPO,load_region,read_json,within,atomic_json
from skippercast.platform.qualified_scope import validate_qualified_scope

def publish(region_id,root=REPO):
    region=load_region(region_id,root)
    path=within(root/'dist',region['assets']['target_qualification'])
    manifest=read_json(path);payload={}
    for name,receipt in manifest['artifacts'].items():
        file=within(path.parent,name);data=file.read_bytes()
        if hashlib.sha256(data).hexdigest()!=receipt['sha256'] or len(data)!=receipt['bytes']:raise ValueError('Subset artifact changed')
        payload[name]=read_json(file)
    old_index=read_json(within(root/'dist',region['assets']['bottom_index']))
    old_atlas=read_json(within(root/'dist',region['assets']['atlas']))
    fragment=payload['bottom-index-fragment.json'];index={**old_index,'views':{**old_index['views'],**fragment['views']},'sources':{**old_index.get('sources',{}),**fragment.get('sources',{})}}
    # Only previously compiler-owned qualified views may be superseded.
    owned={t['id'] for t in old_atlas['targets'] if t.get('qualification',{}).get('policy')==manifest['transformation_version']}
    index['views']={k:v for k,v in index['views'].items() if k not in owned or k in fragment['views']}
    # Validate the complete proposed state before replacing either public asset.
    # A failed source/closure review must leave the current atlas intact.
    result=validate_qualified_scope(region,payload['atlas.json'],root,bottom_index=index)
    atomic_json(within(root/'dist',region['assets']['atlas']),payload['atlas.json'])
    atomic_json(within(root/'dist',region['assets']['bottom_index']),index)
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--region',required=True)
    print(publish(p.parse_args().region))
