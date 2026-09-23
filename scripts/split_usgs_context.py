"""Shard statewide optional USGS context by coast for responsive mobile maps."""
import argparse
import json
from pathlib import Path

from shapely.geometry import shape


def split(data,coasts):
    if data.get('scope')!='generalized-statewide-usgs-hard-bottom-context':raise ValueError('Wrong USGS context scope')
    rows={r['id']:[] for r in coasts['regions']}
    for feature in data['features']:
        lat=shape(feature['geometry']).centroid.y
        matched=[r['id'] for r in coasts['regions'] if r['latitude'][0]<=lat<r['latitude'][1]]
        if len(matched)!=1:raise ValueError('USGS polygon falls outside one California coast')
        rows[matched[0]].append(feature)
    return {ident:{key:value for key,value in data.items() if key!='features'}|{'coast_id':ident,'features':features} for ident,features in rows.items()}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',type=Path,required=True)
    parser.add_argument('--coasts',type=Path,required=True)
    parser.add_argument('--output-dir',type=Path,required=True)
    args=parser.parse_args()
    shards=split(json.loads(args.input.read_text()),json.loads(args.coasts.read_text()))
    args.output_dir.mkdir(parents=True,exist_ok=True)
    for ident,data in shards.items():
        path=args.output_dir/f'usgs-hard-context-{ident}.geojson'
        path.write_text(json.dumps(data,separators=(',',':'))+'\n')
        print(ident,len(data['features']))


if __name__=='__main__':main()
