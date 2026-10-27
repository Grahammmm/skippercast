"""Fixed-center header planning on the same reserved sealed source; no search."""
import hashlib,math
from pathlib import Path
from urllib.parse import urlparse
from skippercast.coastal.handoff.common import digest

# validate_spec/geometry_roles are pure metadata predicates. Keep native/GIS
# dependencies at their actual call sites so dry admission needs no survey stack.

SPEC='coastal-fixed-window-spec-v1'
LARGER_SPEC='coastal-fixed-native-window-spec-v2'
CONTAINED_SPEC='coastal-contained-native-window-spec-v3'
ORDERED_SCOPE='coastal-ordered-four128-v2'
def geometry_roles(spec):
    if spec.get('ordered_scope_contract') is None:
        return ('segment','legacy_bounds','historical_support')
    if (spec.get('ordered_scope_contract')!=ORDERED_SCOPE
        or spec.get('execution_profile')!='coastal-contained-windows-v3'
        or spec.get('window_side')!=128 or spec.get('window_count')!=4
        or spec.get('scope_basis')!='new_native_grid_target'
        or spec.get('historical_support_qualified') is not False
        or any(k in spec for k in ('historical_support','legacy_bounds','historical_support_evidence'))):
        raise ValueError('explicit new native-interest scope cannot claim historical support')
    return ('segment','native_interest')

def _finite(values,n):
    return isinstance(values,list) and len(values)==n and all(type(v) in (int,float) and math.isfinite(v) for v in values)
def rectangle(bounds,source,target):
    from pyproj import Transformer
    from shapely.geometry import Polygon
    x0,y0,x1,y1=bounds
    if not _finite(list(bounds),4) or x0>=x1 or y0>=y1:raise ValueError('finite nonempty rectangle required')
    points=[]
    for a,b in (((x0,y0),(x1,y0)),((x1,y0),(x1,y1)),((x1,y1),(x0,y1)),((x0,y1),(x0,y0))):
        points.extend((a[0]+(b[0]-a[0])*i/64,a[1]+(b[1]-a[1])*i/64) for i in range(64))
    transform=Transformer.from_crs(source,target,always_xy=True,allow_ballpark=False)
    x,y=transform.transform(*zip(*points),errcheck=True)
    geometry=Polygon(zip(x,y))
    if not geometry.is_valid or geometry.is_empty or not _finite(list(geometry.bounds),4):raise ValueError('invalid projected footprint')
    return geometry
def geometry_in_target(record,target='EPSG:3310'):
    from pyproj import CRS,Transformer
    from shapely.geometry import shape
    from shapely.ops import transform as project
    from shapely import segmentize
    source=CRS.from_user_input(record['crs'])
    if 'bbox' in record:return rectangle(record['bbox'],source,target)
    geometry=shape(record['geometry'])
    if geometry.is_empty or not geometry.is_valid:raise ValueError('invalid support geometry')
    # Densify geographic edges before transforming; preserve interior rings.
    geometry=segmentize(geometry,.00001 if source.is_geographic else 2.)
    transform=Transformer.from_crs(source,target,always_xy=True,allow_ballpark=False)
    result=project(lambda x,y,z=None:transform.transform(x,y,errcheck=True),geometry)
    if result.is_empty or not result.is_valid or not _finite(list(result.bounds),4):raise ValueError('invalid transformed support')
    return result
def validate_spec(spec,source):
    from .profiles import profile
    selected=profile(spec.get('execution_profile'),spec);side=selected['side']
    schema=CONTAINED_SPEC if selected['name']=='coastal-contained-windows-v3' else LARGER_SPEC if selected['name'] else SPEC
    if (spec.get('schema')!=schema or spec.get('source_sha256')!=source['sha256']
        or spec.get('window_shape')!=[side,side] or type(spec.get('halo')) is not int or spec['halo']!=0
        or type(spec.get('minimum_margin_m')) not in (int,float) or spec['minimum_margin_m']!=.1
        or not _finite(spec.get('center_native'),2) or not _finite(spec.get('safety_bbox_native'),4)):
        raise ValueError('exact fixed16x16 zero-halo source/geometry contract required')
    if selected['name']:
        window=spec.get('native_window')
        if (not isinstance(window,list) or len(window)!=4 or any(type(v) is not int for v in window)
            or min(window[:2])<0 or window[2:]!=[side,side]):raise ValueError('explicit native window required')
    for role in geometry_roles(spec):
        if not isinstance(spec.get(role),dict):raise ValueError('all approved geometry roles required')
    return spec
def read_header(view,source,row,metadata_sha256,declared_vertical=None):
    from pyproj import CRS
    from skippercast.coastal import vertical
    from .metadata_bag import inspect_metadata
    from .adapter_bag import _reviewed_horizontal_crs
    survey=Path(urlparse(row['url']).path).name.split('_')[0]
    metadata=inspect_metadata(view,survey)
    if metadata['metadata_sha256']!=metadata_sha256 or metadata.get('vertical_datum')!='MLLW' or metadata.get('uncertainty_type')!='productUncert':
        raise ValueError('strict embedded metadata/source lineage required')
    with view.open_raster() as ds:
        crs=CRS.from_user_input(ds.crs)
        horizontal=[p for p in crs.sub_crs_list if p.is_bound or p.is_projected]
        verts=[p for p in crs.sub_crs_list if p.is_vertical]
        if not crs.is_compound or len(horizontal)!=1 or len(verts)!=1 or ds.dtypes!=('float32','float32'):
            raise ValueError('strict regular compound-CRS FLOAT32 BAG required')
        _reviewed_horizontal_crs(horizontal[0],CRS.from_wkt(metadata['horizontal_wkt']),CRS.from_user_input(row['horizontal_crs']))
        observed=vertical.from_raster(ds,source_sha256=source['sha256'],bag_metadata=metadata)
        block=vertical.require_resolved(declared_vertical,observed,[vertical.evidence_from_observation(observed)])
        return dict(schema='coastal-authenticated-header-v1',source=source,driver=ds.driver,count=ds.count,
            shape=[ds.height,ds.width],transform=list(ds.transform)[:6],resolution_m=list(ds.res),
            horizontal_crs=horizontal[0].to_wkt(),compound_crs=crs.to_wkt(),observed_vertical=observed,
            vertical=block,metadata_sha256=metadata_sha256,metadata=metadata)
def plan_header(header,spec):
    from affine import Affine
    from pyproj import CRS
    from shapely.geometry import box
    from skippercast.coastal import vertical
    source=header['source'];validate_spec(spec,source)
    dims=header.get('shape');values=header.get('transform')
    if header.get('driver')!='BAG' or type(header.get('count')) is not int or header['count']!=2:
        raise ValueError('regular two-band BAG required')
    if not isinstance(dims,list) or len(dims)!=2 or any(type(v) is not int or v<=0 for v in dims):raise ValueError('actual dimensions required')
    if not _finite(values,6):raise ValueError('finite actual affine required')
    a,b,c,d,e,f=values
    if a!=2 or e!=-2 or b!=0 or d!=0 or header.get('resolution_m')!=[2,2]:
        raise ValueError('strict native north-up2m grid required')
    observed=header['observed_vertical']
    if observed.get('source_sha256')!=source['sha256'] or observed.get('header_sha256')!=digest(observed['header']) or observed.get('facts',{}).get('datum')!='MLLW':
        raise ValueError('actual vertical source/header binding required')
    block=vertical.require_resolved(header['vertical'],observed,[vertical.evidence_from_observation(observed)])
    if block!=header['vertical']:raise ValueError('header vertical contract changed')
    x,y=(~Affine(*values))*spec['center_native']
    side=spec['window_shape'][0]
    if spec.get('execution_profile'):
        col,row=spec['native_window'][:2]
        if spec['center_native']!=[c+2*(col+side/2),f-2*(row+side/2)]:
            raise ValueError('center must exactly bind native window; no snapping')
    else:col,row=math.floor(x)-8,math.floor(y)-8
    if col<0 or row<0 or col+side>dims[1] or row+side>dims[0]:raise ValueError('fixed window outside grid; relocation prohibited')
    bounds=[c+2*col,f-2*(row+side),c+2*(col+side),f-2*row]
    native=box(*bounds)
    if not box(*spec['safety_bbox_native']).buffer(-.1).covers(native):raise ValueError('entire footprint outside safety margin')
    footprint=rectangle(bounds,CRS.from_user_input(header['horizontal_crs']),'EPSG:3310')
    for role in geometry_roles(spec):
        if not geometry_in_target(spec[role]).buffer(-.1).covers(footprint):raise ValueError('entire footprint outside '+role)
    result=dict(schema='coastal-authenticated-window-plan-v1',source=source,window=[col,row,side,side],halo=0,
        spec_sha256=digest(spec),header_sha256=digest(header),center_native=spec['center_native'],
        bounds_native=bounds,footprint=footprint.__geo_interface__,relocation_allowed=False,accepted=False)
    if spec.get('ordered_scope_contract'):
        result.update(ordered_scope_contract=ORDERED_SCOPE,scope_basis='new_native_grid_target',
                      historical_support_qualified=False)
    return result
