"""Shared regional forecast evidence, observation spectra and uncertainty pipeline."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import argparse
import json
import math
from pathlib import Path
from .collect import Client, source, stamp, model_loader, MODEL_META
from ..forecast import ensemble as forecast_ensemble
from ..forecast import local as forecast_local
from .ocean import collect_ocean
from .parsers import ndbc
from .verification import ForecastCollectionDeferred, forecast_records, merge_records, observation_records, merge_observations, derived_wind_data, derived_wind_records, verify
from .verification_archive import load_archive, write_archive
from .forecast_coverage import audit_forecast_coverage
from ..platform.contracts import load_region, atomic_json, read_json


KNOTS_PER_MS=3600/1852


def _member_value(series,t,times):
    """A member's value at unix time t, linear between native three-hour steps; None if a neighbour is missing."""
    if t in times:
        value=series[times.index(t)]
        return value if isinstance(value,(int,float)) and math.isfinite(value) else None
    after=next(i for i,x in enumerate(times) if x>t);before=after-1
    a,b=series[before],series[after]
    if not all(isinstance(v,(int,float)) and math.isfinite(v) for v in (a,b)):return None
    return a+(b-a)*(t-times[before])/(times[after]-times[before])


def ensemble(client,region):
    """GEFS wind members at the region's forecast points from SkipperCast's own NOAA build.

    `forecast.ensemble` reads the members from NOAA's AWS bucket once per cycle for
    every region; this samples that build and keeps the hourly frame shape the app uses."""
    model=region['intelligence']['wind_ensemble_model'];points=region['forecast_points']
    if model!='gfs025':raise ValueError('Ensemble model requires a reviewed adapter')
    manifest=forecast_ensemble.read('manifest.json',client)
    data=forecast_ensemble.read(f"regions/{region['id']}.json",client)
    after=forecast_ensemble.read('manifest.json',client)
    meta,later=manifest.get('meta') or {},after.get('meta') or {}
    if any(meta.get(k)!=later.get(k) for k in ('last_run_initialisation_time','last_run_modification_time')):raise ValueError('Ensemble updated during collection; retry next run')
    cycle=meta.get('last_run_initialisation_time')
    if not isinstance(cycle,(int,float)) or data.get('cycle')!=cycle or manifest.get('model')!=forecast_ensemble.MODEL_ID:raise ValueError('Ensemble initialization absent or inconsistent')
    times=data.get('times',[]);members=data.get('members')
    if members!=forecast_ensemble.MEMBERS or data.get('units')!={'wind_speed_10m':'m/s','wind_gusts_10m':'m/s'}:raise ValueError('Ensemble members or units changed')
    if not times or times[0]!=cycle or any(b-a!=3*3600 for a,b in zip(times,times[1:])):raise ValueError('Invalid ensemble time axis')
    rows=data.get('points',[])
    if len(rows)!=len(points) or any([r.get('latitude'),r.get('longitude')]!=[p['latitude'],p['longitude']] for r,p in zip(rows,points)):
        raise ValueError('Ensemble regional point mismatch; waiting for the next build')
    out=[]
    for requested,p in zip(points,rows,strict=True):
        wind_series,gust_series=p.get('wind_speed_10m',[]),p.get('wind_gusts_10m',[])
        if len(wind_series)!=members or len(gust_series)!=members or any(len(s)!=len(times) for s in wind_series+gust_series):raise ValueError('Ensemble member series length mismatch')
        frames=[]
        for t in range(times[0],times[-1]+1,3600):
            if p.get('grid') is None:break
            values=[]
            for member in range(members):
                wind=_member_value(wind_series[member],t,times);gust=_member_value(gust_series[member],t,times)
                if wind is None or wind<0:continue
                wind=round(wind*KNOTS_PER_MS,1);gust=None if gust is None else round(gust*KNOTS_PER_MS,1)
                gust=gust if gust is not None and gust>=wind else None
                values.append([member,wind,gust])
            frames.append({'time':t,'members':values})
        out.append({'point_id':requested['id'],'requested':[requested['latitude'],requested['longitude']],
                    'grid':p.get('grid'),'distance_km':p.get('distance_km'),'frames':frames})
    upstream=manifest.get('upstream') or {}
    return {'provider':'NOAA GEFS (NOAA Open Data Dissemination on AWS)','model':forecast_ensemble.MODEL_ID,'issued_at':stamp(datetime.fromtimestamp(cycle,timezone.utc)),
            'meta':meta,'expected_members':members,'native_step_hours':3,'api_step_hours':1,'resolution_km':25,'points':out,
            'source_url':forecast_ensemble.DOCUMENTATION,'upstream':{k:upstream.get(k) for k in ('cycle_prefix','product','fields','land_mask','messages','messages_sha256','missing')},
            'sampling':f"Nearest GFS-0.25° sea cell within {manifest.get('sea_radius_km',forecast_ensemble.SEA_RADIUS_KM)} km; returned coordinates and distance accompany every point.",
            'limitations':'Fractions of actual ensemble members, not calibrated probabilities. SkipperCast linearly interpolates native 3-hour member output to hourly. Missing members and inconsistent gusts are excluded; no independent-hour multiplication.'}


def forecast_currents(source,points):
    """WCOFS surface-current samples at each forecast point, for the app's hourly view.

    Replaces the browser's direct Open-Meteo (Météo-France) request. Only the nearest
    ocean cell within 1.5 grid lengths of the point is kept for each actual three-hour
    frame; a missing cell stays missing. Stale or failed WCOFS publishes no samples."""
    data=(source or {}).get('data') or {}
    out={'source':'wcofs','name':(source or {}).get('name'),'status':(source or {}).get('status','missing'),'issued_at':data.get('issued_at'),
         'valid_from':data.get('valid_from'),'valid_through':data.get('valid_through'),'resolution_km':data.get('resolution_km'),
         'source_url':data.get('source_url'),'units':{'speed':'kn','direction':'° toward'},'points':[]}
    if out['status']!='ok' or not data.get('frames') or not data.get('resolution_km'):return out
    limit=data['resolution_km']*1.5
    for point in points:
        samples=[]
        for frame in data['frames']:
            best=None
            for lat,lon,speed,toward in frame.get('cells',[]):
                phi,p=math.radians(lat),math.radians(point['latitude'])
                a=math.sin((phi-p)/2)**2+math.cos(phi)*math.cos(p)*math.sin(math.radians(lon-point['longitude'])/2)**2
                km=6371*2*math.asin(math.sqrt(min(1,a)))
                if km<=limit and (best is None or km<best[5]):best=[frame['time'],lat,lon,speed,toward,round(km,2)]
            if best:samples.append(best)
        out['points'].append({'point_id':point['id'],'requested':[point['latitude'],point['longitude']],'samples':samples})
    return out


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
        result=loader(client);after=forecast_local.meta(model,client)
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
    previous=prior.get('sources',{});models=['gfs_global','ecmwf_ifs025','ncep_gfswave016','ecmwf_wam']
    def one(model):return 'model-'+model,model_source(model,region,now,previous.get('model-'+model))
    with ThreadPoolExecutor(max_workers=4) as pool:sources=dict(pool.map(one,models))
    sources['ensemble']=source('ensemble','NOAA GEFS ensemble','forecast',forecast_ensemble.DOCUMENTATION,36,lambda c:ensemble(c,region),now,previous.get('ensemble'))
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
        'meta':(sources['model-'+m].get('data') or {}).get('meta'),'error':sources['model-'+m].get('issue') if sources['model-'+m]['status']!='ok' else None} for m in models},
        'currents':forecast_currents(sources.get('wcofs'),region['forecast_points']),'retrieved':int(now.timestamp()*1000)}
    coverage=audit_forecast_coverage(forecast,region,now)
    forecast['coverage']=coverage
    health=collection_health(sources)
    health['forecast_coverage']=coverage['summary']
    missing=coverage['summary']['incomplete_point_days']
    if missing:
        health['status']='degraded'
        health['issues'].append(f'forecast: {missing} point-days lack a full 7-hour wind and combined-sea window')
    elif coverage['summary']['two_model_point_days']<coverage['summary']['point_days']:
        health['coverage_gaps'].append('forecast: independent model comparison incomplete for some point-days')
    data={'schema_version':1,'region_id':region_id,'generated_at':stamp(now),'completed_at':stamp(),'ocean_collected_at':ocean_at,
          'sources':sources,'verification':verification,'forecast':forecast,
          'health':health}
    target=output/'regions'/region_id
    write_archive(target,region_id,records,observed,evaluated_at,
                  previous_root/'regions'/region_id if previous_root else None)
    atomic_json(target/'intelligence.json',data)
    return data


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--region',required=True);parser.add_argument('--output',type=Path,required=True);parser.add_argument('--previous-root',type=Path)
    args=parser.parse_args();result=run(args.region,args.output,args.previous_root);print(json.dumps({'region':args.region,**result['health'],'verification':result['verification']['status']}))
