"""Merge independently audited USGS historical seabed context releases."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path


def merge(legacy,doi):
    if legacy.get('scope')!='generalized-statewide-usgs-hard-bottom-context' or doi.get('scope')!='generalized-usgs-doi-hard-bottom-context':
        raise ValueError('Unexpected USGS source layer scope')
    if legacy.get('failed_blocks') or doi.get('failed_releases'):
        raise ValueError('USGS source review has unresolved failures')
    features=[*legacy['features'],*doi['features']]
    if len(features)<1000:raise ValueError('Combined USGS context unexpectedly incomplete')
    ids=[f['properties']['id'] for f in features]
    if len(set(ids))!=len(ids):raise ValueError('USGS source feature IDs collide')
    checked={f['properties']['mpa_screened_at'] for f in features}
    if len(checked)!=1:raise ValueError('USGS source layers used different MPA snapshots')
    if any(f['properties'].get('fishing_target') is not False or f['properties'].get('exportable') is not False or f['properties'].get('depth_qualified') is not False for f in features):
        raise ValueError('Unreviewed fishing target entered historical layer')
    return {'type':'FeatureCollection','schema_version':1,
            'scope':'generalized-statewide-usgs-hard-bottom-context',
            'compiled_at':datetime.now(timezone.utc).isoformat(),
            'source':'USGS California State Waters Map Series legacy catalogs and DOI releases',
            'source_catalog_url':'https://pubs.usgs.gov/ds/781/',
            'legacy_block_count':len({f['properties']['block_id'] for f in legacy['features']}),
            'doi_release_count':len({f['properties']['release_id'] for f in doi['features']}),
            'mpa_screened_at':checked.pop(),
            'method':'Original video-supervised seafloor character class 3, generalized at 20 m, cut by current complete CDFW MPA polygons. Display only; no fishing waypoint or legal-depth claim.',
            'limitations':['Map blocks are discontinuous and smaller patches are omitted.','No depth-datum conversion, fish presence or legal access is implied.','Original source metadata and archive checksums are recorded on each feature.'],
            'features':features}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--legacy',type=Path,required=True)
    parser.add_argument('--doi',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    result=merge(json.loads(args.legacy.read_text()),json.loads(args.doi.read_text()))
    args.output.parent.mkdir(parents=True,exist_ok=True)
    temp=args.output.with_suffix(args.output.suffix+'.tmp')
    temp.write_text(json.dumps(result,separators=(',',':'))+'\n')
    temp.replace(args.output)
    print(f"{len(result['features'])} context polygons across {result['legacy_block_count']} legacy blocks and {result['doi_release_count']} DOI releases")


if __name__=='__main__':main()
