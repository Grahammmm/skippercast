"""Compile original DOI-release USGS hard-substrate rasters as non-target context."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

from shapely.geometry import mapping

from build_usgs_statewide_context import compile_block, hard_class_review, mpa_union


def reviewed_holds(packet):
    if packet.get('schema_version') != 1 or packet.get('scope') != 'reviewed-usgs-natural-hard-context-holds':
        raise ValueError('USGS natural-hard context holds are missing or unreviewed')
    holds = {}
    for row in packet.get('holds', []):
        ident = row.get('release_id')
        urls = row.get('evidence_urls', [])
        if (not isinstance(ident, str) or not re.fullmatch(r'[A-Z0-9]{8}', ident)
                or ident in holds or row.get('disposition') != 'exclude_from_natural_hard_context'
                or not re.fullmatch(r'[a-f0-9]{64}', row.get('source_archive_sha256', ''))
                or not row.get('reason') or not urls or any(
                    urlsplit(url).scheme != 'https' or urlsplit(url).hostname not in {
                        'api.tidesandcurrents.noaa.gov', 'data.ngdc.noaa.gov', 'doi.org', 'cmgds.marine.usgs.gov'
                    } for url in urls)):
            raise ValueError('Invalid original-source anthropogenic context hold')
        landmark=row.get('landmark')
        if landmark and (not 32 <= landmark.get('latitude',0) <= 42
                         or not -125 <= landmark.get('longitude',0) <= -117
                         or landmark.get('source_url') not in urls):
            raise ValueError('Anthropogenic hold landmark is not source-backed')
        cmecs=row.get('cmecs_archive')
        if cmecs and (urlsplit(cmecs.get('url','')).hostname!='cmgds.marine.usgs.gov'
                      or not all(re.fullmatch(r'[a-f0-9]{64}',cmecs.get(key,''))
                                 for key in ('sha256','metadata_sha256'))):
            raise ValueError('Anthropogenic hold CMECS source is not pinned')
        for point in row.get('candidate_centroids',[]):
            if (not point.get('id','').startswith('usgs-doi-'+ident+'-')
                    or not 32 <= point.get('latitude',0) <= 42
                    or not -125 <= point.get('longitude',0) <= -117):
                raise ValueError('Invalid source-derived anthropogenic candidate centroid')
        for product_row in row.get('survey_products',[]):
            if (not re.fullmatch(r'[A-Z][0-9]{5}',product_row.get('survey_id',''))
                    or not product_row.get('bag_filename','').startswith(product_row['survey_id']+'_')
                    or not product_row['bag_filename'].endswith('.bag')
                    or not re.fullmatch(r'[a-f0-9]{64}',product_row.get('report_sha256',''))):
                raise ValueError('Anthropogenic hold has an invalid original survey product')
        holds[ident] = row
    return holds


def build(releases,metadata,audit,mpas,cache,hold_packet):
    if releases.get('scope')!='usgs-state-waters-doi-product-links' or metadata.get('scope')!='usgs-state-waters-doi-native-metadata' or audit.get('scope')!='usgs-state-waters-doi-native-grid-audit':
        raise ValueError('Invalid USGS DOI source scopes')
    source={row['metadata_url']:row for row in metadata['records'] if row['status']=='ok'}
    product={p['metadata_url']:p for r in releases['releases'] for p in r['products']}
    excluded=mpa_union(mpas)
    features=[];failures=[];blocks=set();held=[]
    holds=reviewed_holds(hold_packet)
    candidates=[row for row in audit['products'] if row['kind']=='seafloor_character']
    # For releases publishing both 2 m and 5 m grids, use the 2 m product in
    # this nearshore display. The 5 m release remains audited and sourced.
    by_release={}
    for row in candidates:
        by_release.setdefault(row['release_id'],[]).append(row)
    for ident,options in sorted(by_release.items()):
        options.sort(key=lambda row:(0 if '_2m_' in product.get(row['metadata_url'],{}).get('filename','').lower() else 1,row['archive_url']))
        row=options[0]
        if row['status']!='ok' or row['metadata_url'] not in source or row['metadata_url'] not in product:
            failures.append(ident+': native seafloor grid unavailable');continue
        record=source[row['metadata_url']]
        if not hard_class_review(record):
            failures.append(ident+': original XML does not define hard class 3');continue
        hold=holds.get(ident)
        if hold:
            if row['archive_sha256'] != hold['source_archive_sha256']:
                raise ValueError(ident+': original class grid changed; anthropogenic hold needs review')
            held.append({'release_id':ident,'reason':hold['reason'],'evidence_urls':hold['evidence_urls']})
            continue
        entry=product[row['metadata_url']]
        description=entry['filename'].replace('_2m_',' (2m/pixel) ').replace('_5m_',' (5m/pixel) ')
        adjusted={**row,'block_id':ident}
        try:areas=compile_block(adjusted,{**record,'description':description},cache,excluded)
        except (OSError,ValueError) as error:
            failures.append(ident+': '+str(error)[:120]);continue
        blocks.add(ident)
        for rank,(native_area,geometry) in enumerate(areas[:100],1):
            features.append({'type':'Feature','geometry':mapping(geometry),'properties':{
                'id':f'usgs-doi-{ident}-{rank:03d}','release_id':ident,'study_area':row.get('study_areas',[''])[0],
                'source_url':row['archive_url'],'metadata_url':row['metadata_url'],
                'source_file_sha256':row['archive_sha256'],'source_metadata_sha256':row['metadata_sha256'],
                'source_year':record['published_date'],'source_class':'Class 3 · hard, rugose rock/boulder',
                'approx_original_area_m2':round(native_area),'display_resolution_m':20,
                'fishing_target':False,'exportable':False,'depth_qualified':False,
                'fish_confirmed':False,'mpa_screened_at':mpas['sources']['mpas']['data_retrieved_at']}})
    return {'type':'FeatureCollection','schema_version':1,'scope':'generalized-usgs-doi-hard-bottom-context',
            'compiled_at':datetime.now(timezone.utc).isoformat(),'source':'USGS California State Waters Map Series DOI releases',
            'source_catalog_url':'https://pubs.usgs.gov/ds/781/',
            'method':'Original categorical GeoTIFF class 3, mode resampled to 20 m, polygons >=5,000 m², largest 100 per source, cut by current complete CDFW MPA polygons. Historical context only.',
            'release_count':len(blocks),'failed_releases':failures,'held_releases':held,
            'limitations':['Discontinuous source coverage and unsurveyed pixels remain.','No legal depth, fish presence or navigation use is implied.','Some releases use direct class codes; others encode substrate, depth zone and slope. Original XML is checked per release.'],
            'features':features}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('releases','metadata','audit','mpas','cache','output'):parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--context-holds',type=Path,default=Path('catalog/usgs-context-holds.json'))
    args=parser.parse_args()
    result=build(*(json.loads(getattr(args,name).read_text()) for name in ('releases','metadata','audit','mpas')),
                 args.cache,json.loads(args.context_holds.read_text()))
    args.output.parent.mkdir(parents=True,exist_ok=True)
    temp=args.output.with_suffix(args.output.suffix+'.tmp')
    temp.write_text(json.dumps(result,separators=(',',':'))+'\n')
    temp.replace(args.output)
    print(f"{len(result['features'])} DOI hard-bottom context polygons from {result['release_count']} releases; "
          f"{len(result['held_releases'])} source-review holds; {len(result['failed_releases'])} failures")


if __name__=='__main__':main()
