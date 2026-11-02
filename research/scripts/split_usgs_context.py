"""Shard statewide optional USGS context by coast for responsive mobile maps."""
import argparse
import json
import math
import re
from pathlib import Path

from shapely.geometry import shape

PLAIN_ID=re.compile(r'[a-z0-9]+(?:-[a-z0-9]+)*')


def split(data,coasts):
    if data.get('scope')!='generalized-statewide-usgs-hard-bottom-context':raise ValueError('Wrong USGS context scope')
    bands={}
    for i,r in enumerate(coasts['regions']):
        ident=r.get('id') if isinstance(r,dict) else None
        if not isinstance(ident,str) or not PLAIN_ID.fullmatch(ident):raise ValueError(f'Coast {i} id is not a plain id')
        if ident in bands:raise ValueError(f'Coast id listed twice: {ident}')
        band=r.get('latitude')
        if not (isinstance(band,(list,tuple)) and len(band)==2 and all(isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) for v in band) and band[0]<band[1]):raise ValueError(f'Coast {ident} latitude band invalid')
        bands[ident]=band
    rows={ident:[] for ident in bands}
    for i,feature in enumerate(data['features']):
        props=feature.get('properties') if isinstance(feature,dict) else None
        label=props['id'] if isinstance(props,dict) and isinstance(props.get('id'),str) and len(props['id'])<=64 and PLAIN_ID.fullmatch(props['id']) else f'#{i}'
        try:geom=shape(feature['geometry'])
        except Exception:geom=None
        if geom is None or geom.is_empty:raise ValueError(f'USGS feature {label} has no usable geometry')
        lat=geom.centroid.y
        matched=[ident for ident,(lo,hi) in bands.items() if lo<=lat<hi]
        if len(matched)!=1:raise ValueError(f'USGS polygon {label} falls outside one California coast')
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
        tmp=path.with_name(path.name+'.tmp')
        tmp.write_text(json.dumps(data,separators=(',',':'))+'\n')
        tmp.replace(path)
        print(ident,len(data['features']))


if __name__=='__main__':main()
