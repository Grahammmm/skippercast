"""Prospective verification: forecasts must have been acquired before observations.

Unique run/station/valid-time records are immutable. Repeated polling never
inflates N. Statistics stay separate by model, station, variable and lead bucket.
"""
from datetime import datetime, timezone
import math

BUCKETS=((0,12),(12,24),(24,48),(48,72),(72,168))


def forecast_records(model, data, received_at, stations):
    cycle=data['meta']['last_run_initialisation_time'];records=[]
    if not isinstance(cycle,(int,float)) or cycle>received_at:raise ValueError('Invalid forecast initialization')
    for station,point in zip(stations,data['points'],strict=True):
        if not all(isinstance(point.get(k),(int,float)) for k in ('latitude','longitude')):continue
        variables=['wave_height'] if 'wave' in model or 'wam' in model else ['wind_speed_10m']
        for variable in variables:
            if variable not in station['variables']:continue
            unit='ft' if variable=='wave_height' else 'kn'
            if point['hourly_units'].get(variable)!=unit:raise ValueError('Verification unit mismatch')
            for epoch,value in zip(point['hourly']['time'],point['hourly'][variable],strict=True):
                if epoch<=received_at or not isinstance(value,(int,float)) or not math.isfinite(value) or value<0:continue
                if epoch>data['meta'].get('data_end_time',epoch):continue
                ident=f'{model}:{int(cycle)}:{station["id"]}:{epoch}:{variable}'
                records.append({'id':ident,'model':model,'cycle':cycle,'acquired_at':received_at,'station':station['id'],
                                'time':epoch,'variable':variable,'value':value,'unit':unit,'grid':[point['latitude'],point['longitude']]})
    return records


def merge_records(existing,new,now,retention_days=30):
    result={r['id']:r for r in existing if r['time']>=now-retention_days*86400}
    for row in new:result.setdefault(row['id'],row)
    return sorted(result.values(),key=lambda r:(r['time'],r['id']))


def verify(records, observations, now):
    by_station={}
    for row in observations:
        if row['time']<=now and isinstance(row.get('value'),(int,float)) and math.isfinite(row['value']) and row['value']>=0:
            by_station.setdefault((row['station'],row['variable']),[]).append(row)
    groups={};seen=set()
    for f in records:
        if f['id'] in seen or f['time']>now or f['acquired_at']>=f['time']:continue
        seen.add(f['id'])
        lead=(f['time']-f['cycle'])/3600;bucket=next(((a,b) for a,b in BUCKETS if a<=lead<b),None)
        if not bucket:continue
        candidates=[o for o in by_station.get((f['station'],f['variable']),[]) if o['unit']==f['unit'] and abs(o['time']-f['time'])<=1800 and o['time']>f['acquired_at']]
        if not candidates:continue
        obs=min(candidates,key=lambda o:abs(o['time']-f['time']))
        # A grid is a regional forecast, not an exact buoy prediction.
        key=(f['station'],f['model'],f['variable'],bucket)
        groups.setdefault(key,[]).append((f['value']-obs['value'],f['time'],f['cycle']))
    result=[]
    for (station,model,variable,bucket),rows in sorted(groups.items()):
        errors=[r[0] for r in rows];n=len(errors);days=len({datetime.fromtimestamp(r[1],timezone.utc).date() for r in rows})
        result.append({'station':station,'model':model,'variable':variable,'lead_hours':list(bucket),'n':n,'distinct_days':days,'distinct_runs':len({r[2] for r in rows}),
                       'bias':round(sum(errors)/n,3),'mae':round(sum(abs(e) for e in errors)/n,3),'rmse':round(math.sqrt(sum(e*e for e in errors)/n),3),
                       'unit':'ft' if variable=='wave_height' else 'kn','status':'descriptive' if n>=30 and days>=7 else 'early sample'})
    return {'method_version':'prospective-v1','status':'descriptive' if any(r['status']=='descriptive' for r in result) else 'collecting history',
            'groups':result,'archived_forecasts':len(records),'matched_samples':sum(r['n'] for r in result),
            'limitations':'No retrospective forecast reconstruction or automatic bias correction. Samples share weather systems and are not independent. Wind comparison is an unadjusted buoy-height comparison to a 10 m forecast; it does not establish calibrated wind skill. Different grids and buoy exposure can differ.'}
