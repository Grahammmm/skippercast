"""Merge a reviewed, hash-bound survey subset into a regional web package.

Run the original-survey compiler first, review its receipts, then use this step
before platform.build and release tests. This does not refresh legal permission.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'src'))
from skippercast.platform.contracts import REPO,_unique,load_region,read_json,within,atomic_json
from skippercast.platform.qualified_scope import validate_qualified_scope

# The same three names validate_qualified_scope requires; nothing else is loaded.
SUBSET={'atlas.json','quality.json','bottom-index-fragment.json'}

def _nonfinite(value):raise ValueError(f'Non-finite JSON number: {value}')

def publish(region_id,root=REPO):
    region=load_region(region_id,root)
    path=within(root/'dist',region['assets']['target_qualification'])
    manifest=read_json(path);payload={}
    if set(manifest['artifacts'])!=SUBSET:raise ValueError('Subset artifacts must be atlas.json, quality.json and bottom-index-fragment.json')
    for name,receipt in manifest['artifacts'].items():
        file=within(path.parent,name);data=file.read_bytes()
        if hashlib.sha256(data).hexdigest()!=receipt['sha256'] or len(data)!=receipt['bytes']:raise ValueError('Subset artifact changed')
        # Parse the very bytes that were hashed, with read_json's duplicate-key and NaN rules.
        try:payload[name]=json.loads(data.decode('utf-8'),object_pairs_hook=_unique,parse_constant=_nonfinite)
        except (UnicodeDecodeError,json.JSONDecodeError) as error:raise ValueError(f'Subset artifact is not JSON: {name}') from error
    old_index=read_json(within(root/'dist',region['assets']['bottom_index']))
    old_atlas=read_json(within(root/'dist',region['assets']['atlas']))
    fragment=payload['bottom-index-fragment.json'];index={**old_index,'views':{**old_index['views'],**fragment['views']},'sources':{**old_index.get('sources',{}),**fragment.get('sources',{})}}
    # Only previously compiler-owned qualified views may be superseded.
    owned={t['id'] for t in old_atlas['targets'] if t.get('qualification',{}).get('policy')==manifest['transformation_version']}
    index['views']={k:v for k,v in index['views'].items() if k not in owned or k in fragment['views']}
    # Validate the complete proposed state before replacing either public asset.
    # A failed source/closure review must leave the current atlas intact.
    result=validate_qualified_scope(region,payload['atlas.json'],root,bottom_index=index)
    atlas_path=within(root/'dist',region['assets']['atlas']);old_atlas_bytes=atlas_path.read_bytes()
    atomic_json(atlas_path,payload['atlas.json'])
    try:atomic_json(within(root/'dist',region['assets']['bottom_index']),index)
    except BaseException:
        # Never leave a new atlas beside an old index: put the previous atlas bytes back.
        tmp=atlas_path.with_name(atlas_path.name+'.restore.tmp')
        try:tmp.write_bytes(old_atlas_bytes);os.replace(tmp,atlas_path)
        finally:tmp.unlink(missing_ok=True)
        raise
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--region',required=True)
    print(publish(p.parse_args().region))
