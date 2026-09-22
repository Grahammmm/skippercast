"""Shared regional forecast evidence, observation spectra and uncertainty pipeline."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import argparse
import json
import math
from pathlib import Path
from urllib.parse import urlencode
from .collect import Client, source, stamp, model_loader, MODEL_META
from .ocean import collect_ocean
from .parsers import ndbc
from .verification import ForecastCollectionDeferred, forecast_records, merge_records, observation_records, merge_observations, derived_wind_data, derived_wind_records, verify
from .verification_archive import load_archive, write_archive
from ..platform.contracts import load_region, atomic_json, read_json


def ensemble(client,region):
    model=region['intelligence']['wind_ensemble_model'];points=region['forecast_points']
    if model!='gfs025':raise ValueError('Ensemble model requires a reviewed adapter')
    meta_url='https://ensemble-api.open-meteo.com/data/ncep_gefs025/static/meta.json'
    meta=client.get(meta_url,True)
    params={'latitude':','.join(str(p['latitude']) for p in points),'longitude':','.join(str(p['longitude']) for p in points),
            'models':model,'hourly':'wind_speed_10m,wind_gusts_10m','wind_speed_unit':'kn','timeformat':'unixtime',
            'timezone':'UTC','cell_selection':'sea','forecast_days':8}
    url='https://ensemble-api.open-meteo.com/v1/ensemble?'+urlencode(params)
    data=client.get(url,True);data=data if isinstance(data,list) else [data]
    after=client.get(meta_url,True)
    if any(meta.get(k)!=after.get(k) for k in ('last_run_initialisation_time','last_run_modification_time')):raise ValueError('Ensemble updated during collection; retry next run')
    cycle=meta.get('last_run_initialisation_time')
    if not isinstance(cycle,(int,float)):raise ValueError('Ensemble initialization absent')
    if len(data)!=len(points):raise ValueError('Ensemble regional point mismatch')
    out=[]
    for requested,p in zip(points,data,strict=True):
        h=p.get('hourly',{});units=p.get('hourly_units',{});times=h.get('time',[])
        if units.get('time')!='unixtime' or p.get('utc_offset_seconds')!=0 or len(set(times))!=len(times):raise ValueError('Invalid ensemble time axis')
        frames=[]
        for i,t in enumerate(times):
            if t>meta.get('data_end_time',t):continue
            members=[]
            for member in range(31):
                suffix='' if member==0 else f'_member{member:02d}'
                keys=['wind_speed_10m'+suffix,'wind_gusts_10m'+suffix]
                values=[]
                for key in keys:
                    values.append(h[key][i] if units.get(key)=='kn' and len(h.get(key,[]))==len(times) else None)
                wind,gust=values
                if not isinstance(wind,(int,float)) or not math.isfinite(wind) or wind<0:continue
                gust=gust if isinstance(gust,(int,float)) and math.isfinite(gust) and gust>=wind else None
                members.append([member,wind,gust])
            frames.append({'time':t,'members':members})
        out.append({'point_id':requested['id'],'requested':[requested['latitude'],requested['longitude']],
                    'grid':[p.get('latitude'),p.get('longitude')],'frames':frames})
    return {'provider':'NOAA GEFS via Open-Meteo','model':'ncep_gefs025','issued_at':stamp(datetime.fromtimestamp(cycle,timezone.utc)),
            'meta':meta,'expected_members':31,'native_step_hours':3,'api_step_hours':1,'resolution_km':25,'points':out,'source_url':'https://open-meteo.com/en/docs/ensemble-api',
            'limitations':'Fractions of actual ensemble members, not calibrated probabilities. Provider interpolates native 3-hour forecasts to hourly output. Missing members and inconsistent gusts are excluded; no independent-hour multiplication.'}


def model_source(model,region,now,previous):
    points=[(p['name'],p['latitude'],p['longitude']) for p in region['forecast_points']]
    points += [(p['name'],p['latitude'],p['longitude']) for p in region['intelligence']['verification_stations']]
    expected=[{'name':name,'latitude':lat,'longitude':lon} for name,lat,lon in points]
    if ((previous or {}).get('data') or {}).get('requested_points') != expected:
        # Adding/reordering regional samples must never relabel old verification
        # station rows as new fishing locations after a failed download.
        previous=None
    url,loader=model_loader(model,points)
    def coherent(client):
        result=loader(client);after=client.get(MODEL_META[model],True)
        if any(result['meta'].get(k)!=after.get(k) for k in ('last_run_initialisation_time','last_run_modification_time')):raise ValueError('Model changed during collection')
        return result
    return source('model-'+model,model,'forecast',url,36,coherent,now,previous)


def model_verification_records(model, source_result, npoints, stations):
    """Keep expected provider settling separate from actual collection failures."""
    source_result.pop('verification_issue',None)
    source_result.pop('verification_deferral',None)
    if source_result['status']!='ok':return []
    try:
        return forecast_records(model,{**source_result['data'],'points':source_result['data']['points'][npoints:]},
                                datetime.fromisoformat(source_result['data_retrieved_at'].replace('Z','+00:00')).timestamp(),stations)
    except ForecastCollectionDeferred as error:
        source_result['verification_deferral']=error.as_dict()
    except ValueError as error:
        source_result['verification_issue']=str(error)
    return []


def collection_health(sources):
    return {'status':'ok' if all(s['status']=='ok' and not s.get('verification_issue') for s in sources.values()) else 'degraded',
            'issues':[k for k,s in sources.items() if (s['status']!='ok' or s.get('verification_issue')) and not (k.startswith('hfr-') and s['status']=='missing')],
            'coverage_gaps':[k for k,s in sources.items() if (k.startswith('hfr-') and s['status']=='missing') or s.get('verification_deferral')]}


def run(region_id,output,previous_root=None,now=None):
    now=now or datetime.now(timezone.utc);region=load_region(region_id);prior={};state={}
    if previous_root:
        path=previous_root/'regions'/region_id/'intelligence.json'
        if path.is_file():prior=read_json(path)
        state=load_archive(previous_root/'regions'/region_id,region_id,required=bool(prior))
    if prior and prior.get('region_id')!=region_id:raise ValueError('Prior intelligence belongs to another region')
    if state and state.get('region_id')!=region_id:raise ValueError('Prior verification archive belongs to another region')
    previous=prior.get('sources',{});models=['gfs_global','ecmwf_ifs025','ncep_gfswave025','ecmwf_wam025']
    def one(model):return 'model-'+model,model_source(model,region,now,previous.get('model-'+model))
    with ThreadPoolExecutor(max_workers=4) as pool:sources=dict(pool.map(one,models))
    sources['ensemble']=source('ensemble','NOAA GEFS ensemble','forecast','https://open-meteo.com/en/docs/ensemble-api',36,lambda c:ensemble(c,region),now,previous.get('ensemble'))
    # Expensive regional current reads are shared for an hour; their original times remain intact.
    if prior and (now.timestamp()-datetime.fromisoformat(prior['generated_at'].replace('Z','+00:00')).timestamp())<3600 and prior.get('ocean_collected_at') and (now.timestamp()-datetime.fromisoformat(prior['ocean_collected_at'].replace('Z','+00:00')).timestamp())<3600:
        sources.update({k:v for k,v in previous.items() if k.startswith(('hfr-','spectra-')) or k=='wcofs'});ocean_at=prior['ocean_collected_at']
    else:
        sources.update(collect_ocean(region,now,previous));ocean_at=stamp(now)
    # NOAA wave ensemble fields have their own published thresholds and valid times.
    from .wave_ensemble import wave_probabilities
    sources['wave-ensemble']=source('wave-ensemble','NOAA GEFS Wave probabilities','forecast','https://www.nco.ncep.noaa.gov/pmb/products/gens/',36,lambda c:wave_probabilities(c,region,now),now,previous.get('wave-ensemble'))
    new=[];npoints=len(region['forecast_points']);stations=region['intelligence']['verification_stations']
    for model in models:
        s=sources['model-'+model]
        new+=model_verification_records(model,s,npoints,stations)
    records=merge_records(state.get('forecasts',[]),new,now.timestamp());new_observations=[]
    for station in stations:
        ident=station['id'];url=f'https://www.ndbc.noaa.gov/data/realtime2/{ident}.txt'
        s=source('verify-'+ident,'NDBC verification observations','observation',url,3,lambda c:ndbc(c.get(url),ident,False),now,previous.get('verify-'+ident));sources['verify-'+ident]=s
        if s.get('data_retrieved_at'):
            received=datetime.fromisoformat(s['data_retrieved_at'].replace('Z','+00:00')).timestamp()
            new_observations+=observation_records(station,(s.get('data') or {}).get('observations',[]),received,url)
        wind_provider=station.get('wind_verification')
        if wind_provider and wind_provider!='ndbc-derived-10m':raise ValueError('Unreviewed wind verification provider')
        if wind_provider=='ndbc-derived-10m' and 'wind_speed_10m' in station['variables']:
            wind_url=f'https://www.ndbc.noaa.gov/data/derived2/{ident}.dmv'
            w=source('verify-wind-'+ident,'NDBC derived 10 m verification wind','observation',wind_url,3,
                     lambda c:derived_wind_data(c.get(wind_url),ident),now,previous.get('verify-wind-'+ident))
            sources['verify-wind-'+ident]=w
            if w.get('data_retrieved_at') and w.get('data'):
                received=datetime.fromisoformat(w['data_retrieved_at'].replace('Z','+00:00')).timestamp()
                new_observations+=derived_wind_records(station,w['data'],received,wind_url)
    evaluated_at=max(now.timestamp(),datetime.now(timezone.utc).timestamp())
    observed=merge_observations(state.get('observations',[]),new_observations,evaluated_at)
    verification=verify(records,observed,evaluated_at,stations)
    verification['collection_issues']={k:s.get('verification_issue') or s.get('issue') or (s.get('verification_deferral') or {}).get('reason') for k,s in sources.items()
                                       if k.startswith(('model-','verify-')) and (s.get('verification_issue') or s['status']!='ok' or s.get('verification_deferral'))}
    verification['collection_deferrals']={k:s['verification_deferral'] for k,s in sources.items() if s.get('verification_deferral')}
    forecast={'region_id':region_id,'requested_points':[[p['id'],p['latitude'],p['longitude']] for p in region['forecast_points']],'models':{m:{'data':(sources['model-'+m].get('data') or {}).get('points',[])[:npoints],
        'meta':(sources['model-'+m].get('data') or {}).get('meta'),'error':sources['model-'+m].get('issue') if sources['model-'+m]['status']!='ok' else None} for m in models},'retrieved':int(now.timestamp()*1000)}
    data={'schema_version':1,'region_id':region_id,'generated_at':stamp(now),'completed_at':stamp(),'ocean_collected_at':ocean_at,
          'sources':sources,'verification':verification,'forecast':forecast,
          'health':collection_health(sources)}
    target=output/'regions'/region_id
    write_archive(target,region_id,records,observed,evaluated_at,
                  previous_root/'regions'/region_id if previous_root else None)
    atomic_json(target/'intelligence.json',data)
    return data


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--region',required=True);parser.add_argument('--output',type=Path,required=True);parser.add_argument('--previous-root',type=Path)
    args=parser.parse_args();result=run(args.region,args.output,args.previous_root);print(json.dumps({'region':args.region,**result['health'],'verification':result['verification']['status']}))
