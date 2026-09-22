"""NOAA's published GEFS-wave exceedance fields; no invented 3-ft threshold."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import math
import re
import tempfile
from urllib.parse import urlencode
from .collect import stamp


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
                populated=np.isfinite(probabilities)&(probabilities>=0)&(probabilities<=1)
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
                records.append({'time':int(valid.timestamp()),'cycle':int(cycle.timestamp()),'threshold_m':threshold,'threshold_ft':round(threshold*3.28084,3),'points':values})
            finally:codes_release(gid)
    if not records:raise ValueError('No recognized wave probability fields')
    return records


def wave_probabilities(client,region,now):
    root='https://nomads.ncep.noaa.gov/pub/data/nccf/com/gens/prod/';base=None;names=[];cycle=None
    # A newly created directory may still be empty or incomplete. Require a complete horizon.
    rounded=now.replace(hour=(now.hour//6)*6,minute=0,second=0,microsecond=0)
    for hours_back in (0,6,12,18,24):
        candidate=rounded-timedelta(hours=hours_back)
        directory=f'gefs.{candidate:%Y%m%d}/{candidate:%H}/wave/gridded/'
        try:listing=client.get(root+directory)
        except Exception:continue
        available=sorted(set(re.findall(r'gefs\.wave\.t\d{2}z\.prob\.global\.0p25\.f\d{3}\.grib2',listing)))
        if any('.f168.' in f for f in available):base=directory;names=available;cycle=candidate;break
    if not base:raise ValueError('No complete recent GEFS Wave probability run')
    west,south,east,north=region['bounds'];frames=[];failures=[]
    # Three-hour source snapshots; exact times only, not an interpolated probability.
    files=[f for f in names if int(re.search(r'\.f(\d+)',f)[1])<=168]
    def fetch_file(filename):
        params={'file':filename,'dir':'/'+base.rstrip('/'),'var_HTSGW':'on','lev_surface':'on','subregion':'',
                'leftlon':west-.3,'rightlon':east+.3,'toplat':north+.3,'bottomlat':south-.3}
        url='https://nomads.ncep.noaa.gov/cgi-bin/filter_gefs_wave_0p25.pl?'+urlencode(params)
        try:return filename,client.get(url,as_binary=True)
        except Exception as e:return filename,e
    with ThreadPoolExecutor(max_workers=3) as pool:
        for filename,value in pool.map(fetch_file,files):
            if isinstance(value,Exception):failures.append({'file':filename,'error':str(value)[:160]});continue
            try:frames.extend(decode_probabilities(value,region['forecast_points']))
            except Exception as e:failures.append({'file':filename,'error':str(e)[:160]})
    if not frames:raise ValueError('No valid regional GEFS wave probabilities: '+str(failures[:1]))
    if any(f['cycle']!=int(cycle.timestamp()) for f in frames):raise ValueError('Wave ensemble cycle mismatch')
    return {'provider':'NOAA GEFS Wave','issued_at':stamp(cycle),'frames':frames,'failed_files':failures,'resolution_km':25,'native_step_hours':3,
            'source_url':'https://www.nco.ncep.noaa.gov/pmb/products/gens/gefs.wave.t00z.prob.global.0p25.f000.grib2.shtml',
            'sampling':'Nearest populated sea cell within 30 km; returned coordinates and distance accompany every sample.',
            'limitations':'Published uncalibrated ensemble probability at NOAA thresholds. 1 m is 3.28 ft, not the 3 ft comfort limit. No interpolation between thresholds or forecast hours. Regional sea-cell samples do not resolve an individual reef or harbor.'}
