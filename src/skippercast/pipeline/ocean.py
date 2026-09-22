"""Bounded NOAA surface vectors and spectral observations, with source receipts.

Provider-specific formats live here. Regions supply footprints and stations.
No interpolation across missing cells, extrapolation, or bottom-current claims.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import math
import re
from urllib.parse import quote
from .collect import source, stamp


def dap_arrays(text):
    """Read the numeric part of a DAP2 ASCII response, preserving fill values."""
    if '---------------------------------------------' not in text:
        raise ValueError('Expected DAP ASCII response')
    arrays={}; key=None
    for line in text.split('---------------------------------------------',1)[1].splitlines():
        line=line.strip()
        header=re.fullmatch(r'([\w.]+)((?:\[\d+\])+)',line)
        if header:
            key=header[1]; arrays[key]=[]; continue
        if not line or key is None: continue
        line=re.sub(r'^(?:\[\d+\])+\s*,?\s*','',line)
        try: arrays[key].extend(float(x) for x in re.split(r'\s*,\s*',line) if x)
        except ValueError as e: raise ValueError('Invalid numeric DAP record') from e
    return arrays


def dap(client, base, query):
    return dap_arrays(client.get(base+'.ascii?'+quote(query,safe=',._')))


def vector(u,v):
    if not all(math.isfinite(x) for x in (u,v)) or max(abs(u),abs(v))>5:
        return None
    return round(math.hypot(u,v)*1.94384449,3), round(math.degrees(math.atan2(u,v))%360,1)


def bounds_indices(values,lo,hi):
    indices=[i for i,v in enumerate(values) if lo<=v<=hi]
    if not indices: raise ValueError('Dataset has no regional coordinate coverage')
    return indices[0],indices[-1]


def hfr(client, region, resolution=6):
    base=f'https://dods.ndbc.noaa.gov/thredds/dodsC/hfradar_uswc_{resolution}km'
    dds=client.get(base+'.dds'); das=client.get(base+'.das')
    sizes={k:int(v) for k,v in re.findall(r'\[(time|lat|lon) = (\d+)\]',dds)}
    if not all(k in sizes for k in ('time','lat','lon')): raise ValueError('Unknown HFR axes')
    if '1970-01-01' not in das or 'scale_factor 0.01' not in das or '_FillValue -32767' not in das:
        raise ValueError('HFR units/packing contract changed')
    first=max(0,sizes['time']-6)
    axes=dap(client,base,f'time[{first}:1:{sizes["time"]-1}],lat,lon')
    west,south,east,north=region['bounds']; y0,y1=bounds_indices(axes['lat'],south,north);x0,x1=bounds_indices(axes['lon'],west,east)
    stride=max(1,math.ceil(math.sqrt((y1-y0+1)*(x1-x0+1)/1200)))
    sel=f'[{first}:1:{sizes["time"]-1}][{y0}:{stride}:{y1}][{x0}:{stride}:{x1}]'
    a=dap(client,base,','.join(k+sel for k in ('u','v','hdop','number_of_sites')))
    lat=axes['lat'][y0:y1+1:stride];lon=axes['lon'][x0:x1+1:stride];n=len(lat)*len(lon)
    arrays={k:a.get(k+'.'+k,a.get(k)) for k in ('u','v','hdop','number_of_sites')}
    if any(v is None or len(v)!=n*len(axes['time']) for v in arrays.values()):raise ValueError('Incomplete HFR vectors')
    frames=[]
    for ti,epoch in enumerate(axes['time']):
        cells=[]
        for yi,latitude in enumerate(lat):
            for xi,longitude in enumerate(lon):
                i=ti*n+yi*len(lon)+xi
                u,v=arrays['u'][i],arrays['v'][i]; hdop=arrays['hdop'][i]; sites=arrays['number_of_sites'][i]
                if u==-32767 or v==-32767 or hdop<0 or hdop*.01>2 or not 2<=sites<=20:continue
                vec=vector(u*.01,v*.01)
                if vec:cells.append([round(latitude,6),round(longitude,6),*vec,round(hdop*.01,2),int(sites)])
        frames.append({'time':int(epoch),'cells':cells,'valid_cells':len(cells),'total_cells':n})
    populated=[f for f in frames if f['cells']]
    return {'provider':'NOAA / IOOS HFR','kind':'observation','sample_at':stamp(datetime.fromtimestamp(populated[-1]['time'],timezone.utc)) if populated else None,
            'latest_grid_time':stamp(datetime.fromtimestamp(axes['time'][-1],timezone.utc)),
            'resolution_km':resolution,'surface_only':True,'grid_stride':stride,'fields':['latitude','longitude','speed_knots','toward_degrees','hdop','radar_count'],
            'frames':frames,'total_cells':n,'valid_cells':len(populated[-1]['cells']) if populated else 0,'source_url':base+'.html',
            'limitations':'Observed near-surface flow; local gaps retained. Not boat drift or bottom current. HDOP <=2 and at least two contributing radars.'}


def wcofs(client, region, now):
    # Use public daily catalogs and actual files. Never infer an available run from the clock alone.
    base=None;files=[];cycle=None
    for day in (now,now-timedelta(days=1)):
        directory=f'NOAA/WCOFS/MODELS/{day:%Y/%m/%d}/'
        try:
            catalog=client.get('https://opendap.co-ops.nos.noaa.gov/thredds/catalog/'+directory+'catalog.xml')
        except Exception:continue
        files=sorted(set(re.findall(r'wcofs\.t\d{2}z\.\d{8}\.regulargrid\.f\d{3}\.nc',catalog)))
        if files:
            base='https://opendap.co-ops.nos.noaa.gov/thredds/dodsC/'+directory
            match=re.search(r't(\d{2})z\.(\d{8})',files[-1]);cycle=datetime.strptime(match[2]+match[1],'%Y%m%d%H').replace(tzinfo=timezone.utc)
            files=[f for f in files if match[0] in f];break
    if not base:raise ValueError('No recent WCOFS file catalog')
    first=base+files[0];dds=client.get(first+'.dds');das=client.get(first+'.das')
    if 'hours since 2016-01-01' not in das and 'seconds since' not in das and 'days since' not in das:
        # Parse rather than assume NOAA's time origin.
        if not re.search(r'(?:hours|seconds|days) since \d{4}-\d{2}-\d{2}',das):raise ValueError('Unknown WCOFS time unit')
    dims={k:int(v) for k,v in re.findall(r'\[(ny|nx) = (\d+)\]',dds)}
    axes=dap(client,first,f'Latitude[0:1:{dims["ny"]-1}][0],Longitude[0][0:1:{dims["nx"]-1}],Depth')
    if axes['Depth'][0]!=0:raise ValueError('First WCOFS layer is not surface')
    west,south,east,north=region['bounds'];y0,y1=bounds_indices(axes['Latitude'],south,north);x0,x1=bounds_indices(axes['Longitude'],west,east)
    time_block=re.search(r'\btime\s*\{(.*?)\}',das,re.S)
    unit=re.search(r'(seconds|hours|days) since ([^"]+)',time_block[1] if time_block else '')
    if not unit:raise ValueError('WCOFS time metadata unavailable')
    origin=datetime.fromisoformat(unit[2].strip().replace('UTC','').strip().replace('Z','+00:00')).replace(tzinfo=timezone.utc)
    factor={'seconds':1,'hours':3600,'days':86400}[unit[1]]
    cut=f'[{y0}:1:{y1}][{x0}:1:{x1}]';query=f'Latitude{cut},Longitude{cut},mask{cut},u_eastward[0][0]{cut},v_northward[0][0]{cut},time'
    frames=[]
    # DAP clients share no mutable library state. Bounded HTTP reads retain hashes.
    for filename in files:
        fh=int(re.search(r'\.f(\d+)',filename)[1])
        if fh>72 or fh%3:continue
        a=dap(client,base+filename,query);cells=[]
        for lat,lon,mask,u,v in zip(a['Latitude'],a['Longitude'],a['mask'],a['u_eastward'],a['v_northward'],strict=True):
            vec=vector(u,v)
            if mask==1 and vec:cells.append([round(lat,6),round(lon,6),*vec])
        epoch=origin.timestamp()+a['time'][0]*factor
        if abs(epoch-(cycle.timestamp()+fh*3600))>60:raise ValueError('WCOFS valid time conflicts with cycle')
        frames.append({'time':int(epoch),'cells':cells,'source_file':filename})
    if not frames:raise ValueError('No populated WCOFS forecast hours')
    return {'provider':'NOAA WCOFS','kind':'forecast','issued_at':stamp(cycle),'resolution_km':4,'horizontal_datum':'NAD83','vertical_layer':'surface (0 m)','surface_only':True,
            'fields':['latitude','longitude','speed_knots','toward_degrees'],'frames':frames,'valid_from':frames[0]['time'],'valid_through':frames[-1]['time'],
            'source_url':'https://tidesandcurrents.noaa.gov/ofs/wcofs/wcofs_info.html',
            'limitations':'Regional surface model, 3-hour output; no extrapolation. Assimilates HF radar, so agreement is not independent validation. Does not resolve a reef, bottom current or harbor bar.'}


def spectral_rows(text):
    result={}
    for line in text.splitlines():
        if not line or line.startswith('#'):continue
        fields=line.split()
        if len(fields)<8:continue
        epoch=int(datetime(*map(int,fields[:5]),tzinfo=timezone.utc).timestamp())
        bins=[(float(f),float(value)) for value,f in re.findall(r'([\d.eE+-]+)\s*\(([\d.eE+-]+)\)',line)]
        if not bins:continue
        if any(not math.isfinite(f) or f<=0 for f,_ in bins):raise ValueError('Invalid spectral frequency')
        result[epoch]=dict(bins)
        if len(result)>=12:break
    if not result:raise ValueError('No spectral observations')
    return result


def spectra(client, station):
    base=f'https://www.ndbc.noaa.gov/data/realtime2/{station}'
    densities=spectral_rows(client.get(base+'.data_spec'));directions=spectral_rows(client.get(base+'.swdir'))
    frames=[]
    for epoch,density in sorted(densities.items()):
        if epoch not in directions:continue
        bins=[]
        for f,e in sorted(density.items()):
            d=directions[epoch].get(f)
            if 0<=e<999 and d is not None and 0<=d<=360:bins.append([f,e,d])
        if bins:frames.append({'time':epoch,'bins':bins})
    if not frames:raise ValueError('No time-aligned density/direction spectra')
    return {'station':station,'provider':'NOAA NDBC','sample_at':stamp(datetime.fromtimestamp(frames[-1]['time'],timezone.utc)),
            'fields':['frequency_hz','density_m2_per_hz','mean_direction_from_degrees'],'frames':frames,
            'source_url':f'https://www.ndbc.noaa.gov/station_page.php?station={station}',
            'limitations':'Observed energy density and mean direction per frequency, not a full directional distribution or forecast.'}


def collect_ocean(region, now, previous=None):
    previous=previous or {};config=region.get('intelligence',{});jobs=[]
    for resolution in config.get('hfr_resolutions_km',[]):
        jobs.append((f'hfr-{resolution}',f'NOAA HFR {resolution} km','observation',f'https://dods.ndbc.noaa.gov/thredds/dodsC/hfradar_uswc_{resolution}km.html',6,lambda c,r=resolution:hfr(c,region,r)))
    if config.get('regional_current_model')=='wcofs':jobs.append(('wcofs','NOAA WCOFS surface currents','forecast','https://tidesandcurrents.noaa.gov/ofs/wcofs/wcofs_info.html',36,lambda c:wcofs(c,region,now)))
    for key in ('nearshore_buoy','offshore_buoy'):
        station=region['stations'][key]
        jobs.append(('spectra-'+station,'NDBC observed wave spectrum','observation',f'https://www.ndbc.noaa.gov/station_page.php?station={station}',3,lambda c,s=station:spectra(c,s)))
    def one(job):
        ident,name,kind,url,max_age,loader=job
        return ident,source(ident,name,kind,url,max_age,loader,now,previous.get(ident))
    with ThreadPoolExecutor(max_workers=4) as pool:return dict(pool.map(one,jobs))
