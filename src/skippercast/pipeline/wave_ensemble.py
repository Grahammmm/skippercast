"""NOAA's published GEFS-wave exceedance fields; no invented 3-ft threshold."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import math
import re
import tempfile
from urllib.parse import urlencode
from .collect import stamp
from ..util.units import FT_PER_M

# The historical feed rounded this factor to five decimals; keep that so published threshold_ft stays byte-identical.
_THRESHOLD_FT_PER_M = round(FT_PER_M, 5)

# NOAA 0.25° probability product, first seven days only. Both checked-in regional
# intelligence snapshots record these eight exceedance fields at every f000–f168
# three-hour lead. This is inventory, not a test of populated regional sea cells.
_LEAD_HOURS = tuple(range(0, 169, 3))
_THRESHOLDS_M = (0.6, 1, 2, 3, 4, 5.5, 7, 9)


def decode_probabilities(body, points):
    from eccodes import codes_grib_new_from_file,codes_get,codes_get_array,codes_release
    import numpy as np
    if not body.startswith(b'GRIB'):raise ValueError('Expected GRIB2, not an error page')
    records=[]
    with tempfile.TemporaryFile() as file:
        file.write(body);file.seek(0)
        while True:
            gid=codes_grib_new_from_file(file)
            if gid is None:break
            try:
                # Discipline 10, category 0, parameter 3 = combined significant wave height.
                if [codes_get(gid,k) for k in ('discipline','parameterCategory','parameterNumber')]!=[10,0,3]:continue
                if codes_get(gid,'probabilityType')!=1:continue # above upper limit only
                threshold=codes_get(gid,'scaledValueOfUpperLimit')*10**(-codes_get(gid,'scaleFactorOfUpperLimit'))
                cycle=datetime.strptime(str(codes_get(gid,'dataDate'))+f'{codes_get(gid,"dataTime"):04d}','%Y%m%d%H%M').replace(tzinfo=timezone.utc)
                valid=datetime.strptime(str(codes_get(gid,'validityDate'))+f'{codes_get(gid,"validityTime"):04d}','%Y%m%d%H%M').replace(tzinfo=timezone.utc)
                values=[]
                latitudes=codes_get_array(gid,'latitudes');longitudes=((codes_get_array(gid,'longitudes')+180)%360)-180
                probabilities=codes_get_array(gid,'values')
                # Each sampled index is reused across all three arrays; never let NumPy broadcast a mismatched axis.
                if not(latitudes.ndim==longitudes.ndim==probabilities.ndim==1 and latitudes.size>0 and latitudes.shape==longitudes.shape==probabilities.shape):
                    raise ValueError('GEFS wave probability spatial arrays must be nonempty matching one-dimensional arrays')
                # Periodic great-circle math would let latitude 395 impersonate 35; an impossible latitude is no cell at all.
                populated=np.isfinite(probabilities)&(probabilities>=0)&(probabilities<=1)&np.isfinite(latitudes)&(latitudes>=-90)&(latitudes<=90)
                for point in points:
                    identity={'point_id':point['id'],'requested':[point['latitude'],point['longitude']]}
                    # The regional subset is tiny. Array distance avoids ecCodes' floating-point
                    # boundary rejection (e.g. 238.25 versus a grid origin of 238.25001).
                    phi=np.radians(latitudes);p=math.radians(point['latitude'])
                    a=np.sin((phi-p)/2)**2+np.cos(phi)*math.cos(p)*np.sin(np.radians(longitudes-point['longitude'])/2)**2
                    distances=6371*2*np.arcsin(np.sqrt(np.clip(a,0,1)))
                    candidates=np.where(populated&(distances<=30))[0]
                    if not len(candidates):
                        values.append({**identity,'grid':None,'distance_km':None,'percent':None});continue
                    index=candidates[np.argmin(distances[candidates])]
                    values.append({**identity,'grid':[round(float(latitudes[index]),5),round(float(longitudes[index]),5)],
                                   'distance_km':round(float(distances[index]),2),'percent':round(float(probabilities[index])*100,2)})
                records.append({'time':int(valid.timestamp()),'cycle':int(cycle.timestamp()),'threshold_m':threshold,'threshold_ft':round(threshold*_THRESHOLD_FT_PER_M,3),'points':values})
            finally:codes_release(gid)
    if not records:raise ValueError('No recognized wave probability fields')
    return records


def wave_probabilities(client,region,now):
    root='https://nomads.ncep.noaa.gov/pub/data/nccf/com/gens/prod/'
    # Cycle labels and GRIB timestamps are UTC, including for callers supplying a naive UTC clock.
    now=now.replace(tzinfo=timezone.utc) if now.tzinfo is None else now.astimezone(timezone.utc)
    rounded=now.replace(hour=(now.hour//6)*6,minute=0,second=0,microsecond=0)
    # Prefer the newest full listing, otherwise the most populated single run (newest on ties).
    selected=None
    for hours_back in (0,6,12,18,24):
        candidate=rounded-timedelta(hours=hours_back)
        directory=f'gefs.{candidate:%Y%m%d}/{candidate:%H}/wave/gridded/'
        try:listing=client.get(root+directory)
        except Exception:continue
        prefix=f'gefs.wave.t{candidate:%H}z.prob.global.0p25.f'
        names=set(re.findall(r'(?<![\w.-])'+re.escape(prefix)+r'\d{3}\.grib2(?![\w.-])',listing))
        expected={lead:f'{prefix}{lead:03}.grib2' for lead in _LEAD_HOURS}
        files={lead:name for lead,name in expected.items() if name in names}
        if len(files)==len(expected):
            selected=(directory,candidate,files)
            break
        if files and (selected is None or len(files)>len(selected[2])):
            selected=(directory,candidate,files)
    if selected is None:raise ValueError('No recent GEFS Wave probability files')
    base,cycle,files=selected
    west,south,east,north=region['bounds'];frames=[];failures=[]
    cycle_timestamp=int(cycle.timestamp())
    decoded_leads=set();incomplete_thresholds=[]

    def fetch_file(item):
        lead,filename=item
        params={'file':filename,'dir':'/'+base.rstrip('/'),'var_HTSGW':'on','lev_surface':'on','subregion':'',
                'leftlon':west-.3,'rightlon':east+.3,'toplat':north+.3,'bottomlat':south-.3}
        url='https://nomads.ncep.noaa.gov/cgi-bin/filter_gefs_wave_0p25.pl?'+urlencode(params)
        try:return lead,filename,client.get(url,as_binary=True)
        except Exception as e:return lead,filename,e
    with ThreadPoolExecutor(max_workers=3) as pool:
        for lead,filename,value in pool.map(fetch_file,files.items()):
            try:
                if isinstance(value,Exception):raise value
                records=decode_probabilities(value,region['forecast_points'])
            except Exception as e:
                failures.append({'file':filename,'error':str(e)[:160]})
                continue
            same_cycle=[row for row in records if row['cycle']==cycle_timestamp]
            valid_timestamp=cycle_timestamp+lead*3600
            exact=[row for row in same_cycle if row['time']==valid_timestamp]
            if len(exact)!=len(records):
                reason='cycle' if len(same_cycle)!=len(records) else 'valid time'
                failures.append({'file':filename,'error':f'Wave ensemble {reason} mismatch'})
            if not exact:continue
            frames.extend(exact)
            decoded_leads.add(lead)
            thresholds=sorted(row['threshold_m'] for row in exact)
            # Allow only GRIB decimal-to-float noise; duplicates do not fill missing thresholds.
            if len(thresholds)!=len(_THRESHOLDS_M) or not all(
                math.isclose(actual,expected,rel_tol=0,abs_tol=1e-9)
                for actual,expected in zip(thresholds,_THRESHOLDS_M)
            ):incomplete_thresholds.append(lead)
    if not frames:raise ValueError('No valid regional GEFS wave probabilities: '+str(failures[:1]))
    missing=sorted(set(_LEAD_HOURS)-decoded_leads)
    return {'provider':'NOAA GEFS Wave','issued_at':stamp(cycle),'frames':frames,'failed_files':failures,'resolution_km':25,'native_step_hours':3,
            'horizon_status':'partial' if missing or incomplete_thresholds else 'complete',
            'missing_lead_hours':missing,'incomplete_threshold_lead_hours':incomplete_thresholds,
            'source_url':'https://www.nco.ncep.noaa.gov/pmb/products/gens/gefs.wave.t00z.prob.global.0p25.f000.grib2.shtml',
            'sampling':'Nearest populated sea cell within 30 km; returned coordinates and distance accompany every sample.',
            'limitations':'Published uncalibrated ensemble probability at NOAA thresholds. 1 m is 3.28 ft, not the 3 ft comfort limit. No interpolation between thresholds or forecast hours. Regional sea-cell samples do not resolve an individual reef or harbor.'}
