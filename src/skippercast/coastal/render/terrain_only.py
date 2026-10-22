"""Source-free internal terrain diagnostic; never supplies render-v2 acceptance.

Only byte-bound, already-derived GeoTIFFs and a separate scientific review are
read. Source hashes are provenance, never source locations or reader commands.
"""
import argparse
from datetime import datetime, timezone
from importlib.resources import files
import io
import json
import math
import os
from pathlib import Path
import stat
import tempfile
import zipfile

from ..handoff.common import digest, load, ref, resolve, review_holds, write, validate_derived_geotiff
from .. import vertical
from .align import check_header, MAX_FILE_BYTES
from .mesh import CAMERA, MAX_SIDE, WIDTH, HEIGHT, write_png, camera_projection
from .preview import output_path, publish_staging, sync_directory

INPUT = 'coastal-terrain-only-input-v1'
REVIEW = 'coastal-terrain-only-science-review-v1'
RESULT = 'coastal-terrain-only-render-v1'
MAX_CLI_JSON_BYTES = 2_000_000
DEFAULT_STYLE = dict(display_units='m', vertical_exaggeration=1.0,
    light_azimuth_degrees=315.0, light_elevation_degrees=45.0, light_intensity=0.65,
    exposure=1.0, contrast=1.0, depth_bands=0, contour_interval_m=10.0,
    slope_overlay=0.0, uncertainty_overlay=0.0, no_data_overlay=True,
    color_range='adaptive', locked_depth_range_m=None)


def bounded_json(path):
    """Bound regular external CLI files before reading; FIFO opens never wait."""
    fd = os.open(path,os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    try:
        header = os.fstat(fd)
        if not stat.S_ISREG(header.st_mode):
            raise ValueError('cli_json_regular_file_required')
        if header.st_size > MAX_CLI_JSON_BYTES:
            raise ValueError('cli_json_byte_bound')
        with os.fdopen(fd,'rb',closefd=False) as stream:
            data = stream.read(MAX_CLI_JSON_BYTES + 1)
    finally:
        os.close(fd)
    if len(data) > MAX_CLI_JSON_BYTES:
        raise ValueError('cli_json_byte_bound')
    def reject(value):
        raise ValueError('cli_json_nonfinite:' + value)
    document = json.loads(data.decode('utf-8'),parse_constant=reject)
    if not isinstance(document,dict):
        raise ValueError('cli_json_object_required')
    return document


def style_controls(value=None):
    value = {} if value is None else value
    if not isinstance(value, dict) or set(value) - set(DEFAULT_STYLE):
        raise ValueError('unknown_style_control')
    style = {**DEFAULT_STYLE, **value}
    bounds = dict(vertical_exaggeration=(0.25, 10), light_azimuth_degrees=(0, 360),
                  light_elevation_degrees=(0, 90), light_intensity=(0, 1),
                  exposure=(0.25, 4), contrast=(0.25, 3),
                  contour_interval_m=(0.1, 1000), slope_overlay=(0, 1), uncertainty_overlay=(0, 1))
    for name, (low, high) in bounds.items():
        item = style[name]
        if type(item) not in (int, float) or not math.isfinite(item) or not low <= item <= high:
            raise ValueError('invalid_style_' + name)
    if (style['display_units'] not in ('m', 'ft') or type(style['no_data_overlay']) is not bool
            or type(style['depth_bands']) is not int or style['depth_bands'] not in (0, *range(2, 33))
            or style['color_range'] not in ('adaptive', 'global', 'locked')):
        raise ValueError('invalid_style_enum')
    locked = style['locked_depth_range_m']
    if style['color_range'] == 'locked':
        if (not isinstance(locked, list) or len(locked) != 2
                or any(type(x) not in (int, float) or not math.isfinite(x) for x in locked)
                or locked[0] >= locked[1]):
            raise ValueError('locked_depth_range_required')
    elif locked is not None:
        raise ValueError('locked_depth_range_requires_locked_mode')
    return style


def context(document):
    """Digest the complete proposed acceptance, excluding its review pointer."""
    return digest({key: value for key, value in document.items() if key != 'scientific_review'})


def verify(root, acceptance, *, now, minimum_valid_until=None):
    try:
        import jsonschema
    except ImportError as error:  # a hold, not a crash part-way through a run
        raise ValueError('terrain_only_dependency:jsonschema') from error
    document = load(root, acceptance, contract=INPUT)
    schema = json.loads(files('skippercast.coastal.resources').joinpath(INPUT + '.schema.json').read_text())
    try:
        jsonschema.Draft202012Validator(schema).validate(document)
    except jsonschema.ValidationError as error:
        raise ValueError('terrain_only_input_schema:' + error.message) from error
    holds = review_holds(root, document.get('scientific_review'), context(document), now=now,
                         minimum_valid_until=minimum_valid_until, schema=REVIEW)
    if document.get('scientific_review'):
        review = load(root, document['scientific_review'], contract=REVIEW)
        review_schema = json.loads(files('skippercast.coastal.resources').joinpath(REVIEW + '.schema.json').read_text())
        try:
            jsonschema.Draft202012Validator(review_schema).validate(review)
        except jsonschema.ValidationError as error:
            raise ValueError('terrain_only_review_schema:' + error.message) from error
        if (review.get('reviewer_id') == document['creator_id']
                or review.get('scope') != 'internal-terrain-only-scientific-review'
                or review.get('synthetic') != document['synthetic']):
            holds.append('independent_scientific_review_invalid')
    if holds:
        raise ValueError(';'.join(sorted(set(holds))))
    return document


def build_terrain(root, document):
    import numpy as np
    import rasterio
    terrain = validate_derived_geotiff(root, document['terrain'], contract='coastal-normalized-terrain-v1', cap=MAX_FILE_BYTES)
    mask = validate_derived_geotiff(root, document['mask'], contract='coastal-native-support-v2', cap=MAX_FILE_BYTES)
    uncertainty = document.get('uncertainty')
    uncertainty_path = (validate_derived_geotiff(root, uncertainty,
        contract='coastal-derived-uncertainty-m-v1', cap=MAX_FILE_BYTES) if uncertainty else None)
    with rasterio.open(terrain) as ds, rasterio.open(mask) as support:
        for item in (ds, support):
            check_header(item)
        if max(ds.shape) > MAX_SIDE or ds.count != 1 or support.count != 1:
            raise ValueError('terrain_grid_bound_or_bands')
        if not ds.crs.is_projected or ds.crs.linear_units != 'metre':
            raise ValueError('metric_terrain_crs_required')
        grid = (ds.crs, ds.transform, ds.shape)
        if grid != (support.crs, support.transform, support.shape):
            raise ValueError('support_grid_mismatch')
        actual_vertical = vertical.normalized_from_raster(ds, source_sha256=document['terrain']['sha256'])
        # normalized_from_raster uses current-header evidence for its check;
        # the normalized contract in storage preserves original source evidence.
        stored_vertical = json.loads(ds.tags()['vertical_contract'])
        source_vertical = stored_vertical['lineage']['source_vertical']
        if stored_vertical != vertical.normalized(source_vertical):
            raise ValueError('normalized_vertical_lineage_consistency_required')
        source_hash = ds.tags().get('source_sha256')
        for evidence in source_vertical['evidence']:
            if not isinstance(evidence,dict):
                raise ValueError('source_vertical_evidence_invalid')
            if evidence.get('kind') == 'raster_header' and (
                    evidence.get('source_sha256') != source_hash
                    or any(evidence['facts'].get(key) != source_vertical.get(key) for key in vertical.FIELDS)):
                raise ValueError('source_vertical_evidence_lineage_mismatch')
        if (stored_vertical != document['vertical'] or actual_vertical['sign'] != 'positive_down'
                or actual_vertical['units'] != 'm' or ds.descriptions != ('depth_m_positive_down',)
                or ds.units != ('m',) or ds.scales != (1.0,) or ds.offsets != (0.0,)
                or ds.crs.to_string() != document['crs'] or list(ds.transform) != document['affine']):
            raise ValueError('terrain_vertical_or_georeference_mismatch')
        if ds.tags().get('source_sha256') not in document['provenance']['source_sha256s']:
            raise ValueError('terrain_source_provenance_mismatch')
        raw = ds.read(1, masked=True)
        depth = raw.filled(np.nan).astype('float64')
        support_values = support.read(1, masked=True)
        if (np.ma.getmaskarray(support_values).any()
                or not np.isin(support_values, [0, 1]).all()):
            raise ValueError('unmasked_binary_support_required')
        valid = np.asarray(support_values) == 1
        terrain_valid = ~np.ma.getmaskarray(raw) & np.isfinite(depth)
        if not np.array_equal(valid, terrain_valid):
            raise ValueError('terrain_validity_mask_mismatch')
        if not valid.any():
            raise ValueError('no_measured_support')
        uncertainty_m = np.full(ds.shape, np.nan)
        if uncertainty_path:
            with rasterio.open(uncertainty_path) as ud:
                check_header(ud)
                if grid != (ud.crs, ud.transform, ud.shape) or ud.count != 1:
                    raise ValueError('uncertainty_grid_mismatch')
                if ud.units != ('m',) or ud.scales != (1.0,) or ud.offsets != (0.0,):
                    raise ValueError('uncertainty_units_or_packing')
                uv = ud.read(1, masked=True)
                uncertainty_m = uv.filled(np.nan).astype('float64')
                uv_valid = ~np.ma.getmaskarray(uv) & np.isfinite(uncertainty_m)
                if not np.array_equal(uv_valid, valid) or (uncertainty_m[valid] < 0).any():
                    raise ValueError('uncertainty_validity_mismatch')
        rows, cols = np.nonzero(valid)
        x, y = rasterio.transform.xy(ds.transform, rows, cols)
        vertices = np.c_[x, y, -depth[valid]]
        index = np.full(ds.shape, -1, dtype='int32')
        index[valid] = np.arange(len(rows))
        faces = []
        for r in range(ds.height - 1):
            for c in range(ds.width - 1):
                for corners in (((r,c),(r+1,c),(r,c+1)), ((r,c+1),(r+1,c),(r+1,c+1))):
                    ids = [int(index[p]) for p in corners]
                    if min(ids) >= 0:
                        faces.append(ids)
        if not faces:
            raise ValueError('no_measured_triangles')
        return dict(vertices=vertices, faces=np.asarray(faces,dtype='int32'),
                    grid_pixels=np.c_[cols,rows].astype('int32'), support=valid,
                    depth_m=depth, uncertainty_m=uncertainty_m, crs=ds.crs.to_string(),
                    crs_wkt=ds.crs.to_wkt(), affine=list(ds.transform),
                    nodata=repr(ds.nodata), vertical=stored_vertical,
                    uncertainty_kind=document.get('uncertainty_kind','unavailable'))


def save_mesh(path, mesh):
    """NPZ with fixed ZIP timestamps, ordering and numeric source values."""
    import numpy as np
    arrays = {name: mesh[name] for name in ('vertices','faces','grid_pixels','support','depth_m','uncertainty_m')}
    arrays.update(crs=np.asarray(mesh['crs']), crs_wkt=np.asarray(mesh['crs_wkt']),
                  affine=np.asarray(mesh['affine']), nodata=np.asarray(mesh['nodata']),
                  uncertainty_kind=np.asarray(mesh['uncertainty_kind']),
                  vertical_json=np.asarray(json.dumps(mesh['vertical'],sort_keys=True,separators=(',',':'))))
    with zipfile.ZipFile(path,'w',compression=zipfile.ZIP_STORED) as archive:
        for name in sorted(arrays):
            buffer = io.BytesIO()
            np.lib.format.write_array(buffer,np.asarray(arrays[name]),allow_pickle=False)
            item = zipfile.ZipInfo(name + '.npy',date_time=(1980,1,1,0,0,0))
            item.external_attr = 0o600 << 16
            archive.writestr(item,buffer.getvalue())


# Small deterministic bitmap legend, no font/runtime dependency.
_FONT = {
 '0':'111101101101111','1':'010110010010111','2':'111001111100111','3':'111001111001111',
 '4':'101101111001001','5':'111100111001111','6':'111100111101111','7':'111001010010010',
 '8':'111101111101111','9':'111101111001111','A':'010101111101101','B':'110101110101110',
 'C':'111100100100111','D':'110101101101110','E':'111100110100111','F':'111100110100100',
 'G':'111100101101111','H':'101101111101101','I':'111010010010111','J':'001001001101111',
 'K':'101101110101101','L':'100100100100111','M':'101111111101101','N':'101111111111101',
 'O':'111101101101111','P':'111101111100100','Q':'111101101111001','R':'110101110101101',
 'S':'111100111001111','T':'111010010010010','U':'101101101101111','V':'101101101101010',
 'W':'101101111111101','X':'101101010101101','Y':'101101010010010','Z':'111001010100111',
 '-':'000000111000000','.':'000000000000010',':':'000010000010000','/':'001001010100100',
 '=':'000111000111000','%':'101001010100101','_':'000000000000111',' ':'000000000000000'}


def text(pixels,x,y,label,scale=2):
    for char in label.upper():
        bits = _FONT.get(char,_FONT[' '])
        for i,bit in enumerate(bits):
            if bit == '1':
                yy,xx = y + i//3*scale,x + i%3*scale
                if 0 <= yy < HEIGHT-scale and 0 <= xx < WIDTH-scale:
                    pixels[yy:yy+scale,xx:xx+scale] = [22,31,39]
        x += 4*scale


def render_terrain(mesh,path,style):
    import numpy as np
    vertices,faces = mesh['vertices'],mesh['faces']
    projected, _basis = camera_projection(vertices, style['vertical_exaggeration'])
    span = np.ptp(projected[:,:2],axis=0)
    deep_datum = mesh['vertical'].get('deep_datum')
    # Reserve a clear header band: outlier paint must not erase datum warnings.
    plot_height, center_y = (250, 215) if deep_datum else (280, 200)
    scale = min(570/max(span[0],1e-9),plot_height/max(span[1],1e-9))
    screen = np.c_[320+projected[:,0]*scale,center_y-projected[:,1]*scale]
    zbuffer = np.full((HEIGHT,WIDTH),-np.inf)
    depths = np.full((HEIGHT,WIDTH),np.nan)
    slopes = np.full((HEIGHT,WIDTH),np.nan)
    uncertainties = np.full((HEIGHT,WIDTH),np.nan)
    shade = np.ones((HEIGHT,WIDTH))
    la,le = math.radians(style['light_azimuth_degrees']),math.radians(style['light_elevation_degrees'])
    light = np.array([math.sin(la)*math.cos(le),math.cos(la)*math.cos(le),math.sin(le)])
    for face in faces:
        a,b,c = screen[face]
        lo = np.maximum(np.floor(np.min([a,b,c],axis=0)).astype(int),[0,0])
        hi = np.minimum(np.ceil(np.max([a,b,c],axis=0)).astype(int),[WIDTH-1,HEIGHT-1])
        denom = (b[1]-c[1])*(a[0]-c[0])+(c[0]-b[0])*(a[1]-c[1])
        if (hi < lo).any() or abs(denom) < 1e-10:
            continue
        xx,yy = np.meshgrid(np.arange(lo[0],hi[0]+1)+.5,np.arange(lo[1],hi[1]+1)+.5)
        w0 = ((b[1]-c[1])*(xx-c[0])+(c[0]-b[0])*(yy-c[1]))/denom
        w1 = ((c[1]-a[1])*(xx-c[0])+(a[0]-c[0])*(yy-c[1]))/denom
        w2 = 1-w0-w1
        z = w0*projected[face[0],2]+w1*projected[face[1],2]+w2*projected[face[2],2]
        region = np.s_[lo[1]:hi[1]+1,lo[0]:hi[0]+1]
        visible = (w0 >= -1e-9)&(w1 >= -1e-9)&(w2 >= -1e-9)&(z > zbuffer[region])
        weights = np.stack([w0,w1,w2],axis=-1)
        depths[region][visible] = (weights@(-vertices[face,2]))[visible]
        u = mesh['uncertainty_m'][mesh['grid_pixels'][face,1],mesh['grid_pixels'][face,0]]
        uncertainties[region][visible] = (weights@u)[visible]
        normal = np.cross(vertices[face[1]]-vertices[face[0]],vertices[face[2]]-vertices[face[0]])
        normal /= max(np.linalg.norm(normal),1e-12)
        if normal[2] < 0:
            normal = -normal
        slopes[region][visible] = math.degrees(math.acos(float(np.clip(normal[2],-1,1))))
        # Scientific normals are unexaggerated; VE changes camera geometry only.
        shade[region][visible] = 1-style['light_intensity']+style['light_intensity']*max(0,float(normal@light))
        zbuffer[region][visible] = z[visible]
    visible = np.isfinite(depths)
    if not visible.any():
        raise ValueError('preview_has_no_visible_geometry')
    if style['color_range'] == 'adaptive':
        low,high = np.percentile(depths[visible],[2,98])
    elif style['color_range'] == 'global':
        low,high = np.min(mesh['depth_m'][mesh['support']]),np.max(mesh['depth_m'][mesh['support']])
    else:
        low,high = style['locked_depth_range_m']
    if high == low:
        low,high = low-.5,high+.5
    t = np.clip((np.nan_to_num(depths,nan=low)-low)/(high-low),0,1)
    if style['depth_bands']:
        t = np.floor(t*(style['depth_bands']-1))/(style['depth_bands']-1)
    rgb = np.stack([220-190*t,235-120*t,160+65*t],axis=-1)
    rgb *= shade[...,None]
    if style['slope_overlay']:
        amount = np.nan_to_num(slopes/90)*style['slope_overlay']
        rgb = rgb*(1-amount[...,None])+np.array([230,90,35])*amount[...,None]
    if style['uncertainty_overlay']:
        if not np.isfinite(uncertainties[visible]).all():
            raise ValueError('uncertainty_overlay_requires_uncertainty')
        uhigh = max(float(uncertainties[visible].max()),1e-12)
        amount = np.nan_to_num(uncertainties/uhigh)*style['uncertainty_overlay']
        rgb = rgb*(1-amount[...,None])+np.array([210,65,190])*amount[...,None]
    rgb = ((rgb*style['exposure']/255-.5)*style['contrast']+.5)*255
    pixels = np.full((HEIGHT,WIDTH,3),[238,243,246],dtype='uint8')
    pixels[visible] = np.clip(rgb[visible],0,255).astype('uint8')
    below,above = visible&(depths < low),visible&(depths > high)
    # Saturated tails remain conspicuous; range adaptation never hides them.
    pixels[below] = [255,100,30]
    pixels[above] = [245,45,170]
    interval = style['contour_interval_m']
    source_depth = mesh['depth_m'][mesh['support']]
    first_level = math.ceil(float(source_depth.min())/interval)
    last_level = math.floor(float(source_depth.max())/interval)
    if last_level - first_level + 1 > 256:
        raise ValueError('contour_count_bound')
    levels = np.arange(first_level,last_level+1)*interval
    # Contours use absolute unmodified metre depth, with a one-pixel threshold
    # estimated from neighboring projected samples, never normalized colors.
    d = depths.copy()
    delta = np.zeros(d.shape)
    for axis in (0,1):
        difference = np.abs(np.diff(d,axis=axis))
        if axis == 0:
            delta[:-1] = np.maximum(delta[:-1],np.nan_to_num(difference))
        else:
            delta[:,:-1] = np.maximum(delta[:,:-1],np.nan_to_num(difference))
    labels = []
    label_boxes = []
    factor = 1 if style['display_units'] == 'm' else 1/.3048
    for level in levels:
        contour = visible&(np.abs(d-level) <= np.minimum(delta*.55,interval*.12))
        pixels[contour] = [30,45,52]
        yy,xx = np.nonzero(contour)
        if len(xx) and len(labels) < 8:
            index = len(xx)//2
            label = f'{level*factor:.1f} {style["display_units"]}'
            x,y = min(int(xx[index]),550),int(yy[index])
            box = (x-2,y-2,x+len(label)*8+2,y+12)
            box_region = np.s_[max(0,y-2):min(HEIGHT,y+12),max(0,x-2):min(WIDTH,x+len(label)*8+2)]
            if (below[box_region].any() or above[box_region].any()
                    or y < 55 or y > 333 or any(not (box[2] < other[0] or box[0] > other[2]
                    or box[3] < other[1] or box[1] > other[3]) for other in label_boxes)):
                continue
            pixels[max(0,y-2):min(HEIGHT,y+12),max(0,x-2):min(WIDTH,x+len(label)*8+2)] = [248,250,252]
            text(pixels,x,y,label)
            labels.append(float(level))
            label_boxes.append(box)
    datum = mesh['vertical']['datum']
    realization = mesh['vertical'].get('datum_realization','unknown')
    source_vertical = mesh['vertical']['lineage']['source_vertical']
    packing = ('ALREADY APPLIED IN SOURCE' if source_vertical['scale_offset_applied']
               else 'APPLIED AT NORMALIZATION')
    uncertainty_legend = 'UNCERTAINTY KIND: ' + mesh['uncertainty_kind']
    kind = mesh['uncertainty_kind']
    if kind == 'producer_uncertainty_m':
        uncertainty_caution = 'PRODUCER UNCERTAINTY: NO INDEPENDENT CALIBRATION'
    elif kind == 'uncalibrated_dispersion_m':
        uncertainty_caution = 'DISPERSION UNCALIBRATED - NO ABSOLUTE ACCURACY'
    else:
        uncertainty_caution = 'UNCERTAINTY: CALIBRATION NOT VERIFIED HERE'
    if np.isfinite(uncertainties[visible]).all():
        uncertainty_accuracy = f'ABSOLUTE ACCURACY NOT VALIDATED - MAX {uncertainties[visible].max()*factor:.3f} {style["display_units"]}'
    else:
        uncertainty_accuracy = 'UNCERTAINTY UNAVAILABLE - NO ACCURACY CLAIM'
    range_label = {'adaptive':'ADAPTIVE 2ND-98TH PERCENTILE',
                   'global':'GLOBAL SUPPORTED DEPTH RANGE',
                   'locked':'LOCKED ABSOLUTE DEPTH RANGE'}[style['color_range']]
    bands_label = f'BANDS {style["depth_bands"]}' + (' CONTINUOUS' if not style['depth_bands'] else '')
    legend_rows = [
        (5,'INTERNAL DIAGNOSTIC - PUBLICATION PROHIBITED'),
        (18,f'Z=-DEPTH M  VE={style["vertical_exaggeration"]:.2f}X  HABITAT UNASSESSED'),
        (31,f'NOMINAL DATUM {datum} - REALIZATION {realization}'),
        (44,f'NO DATUM XFORM - SRC SCALE {source_vertical["scale"]:.9g} OFFSET {source_vertical["offset"]:.9g} {packing}'),
        (345,uncertainty_legend),
        (357,f'OVERLAY STRENGTH: SLOPE {style["slope_overlay"]:.2f} - UNCERTAINTY {style["uncertainty_overlay"]:.2f}'),
        (369,'SLOPE: UNEXAGGERATED TRIANGLE-NORMAL DEGREES'),
        (381,uncertainty_caution),
        (393,uncertainty_accuracy),
        (405,f'DEPTH {low*factor:.1f} TO {high*factor:.1f} {style["display_units"]}'),
        (417,f'{range_label} - {bands_label}'),
        (429,f'ORANGE=BELOW {int(below.sum())} - PINK=ABOVE {int(above.sum())} PIXELS'),
        (441,f'CONTOURS ABSOLUTE {interval*factor:.1f} {style["display_units"]}'),
        (453,'TRIANGLES INTERPOLATE SUPPORTED SAMPLES ONLY - ADD NO MEASUREMENT'),
        (465,'WEBSITE HELD - NO IMAGERY - NO SOURCE ACCESS')]
    if deep_datum:
        legend_rows.extend([(57,'NOT FOR NAVIGATION - DATUM OFFSET UNBOUNDED'),
                            (70,deep_datum['note'])])
    image_legends = []
    for y,label in legend_rows:
        width = 616 if y < 60 else 524
        font_scale = 2 if len(label)*8 <= width else 1
        text(pixels,12,y,label,font_scale)
        image_legends.append(dict(text=label,x=12,y=y,scale=font_scale))
    if style['no_data_overlay']:
        # Inset is an explicit support diagram, never invented terrain geometry.
        h,w = mesh['support'].shape
        yy,xx = np.indices((64,64))
        inset = mesh['support'][np.minimum(yy*h//64,h-1),np.minimum(xx*w//64,w-1)]
        pixels[400:464,564:628] = np.where(inset[...,None],[80,130,155],[225,80,190])
        no_data_label = f'NO DATA {int((~mesh["support"]).sum())}/{mesh["support"].size}'
        text(pixels,548,382,no_data_label,1)
        text(pixels,548,390,'UNSUPPORTED',1)
        image_legends.extend([dict(text=no_data_label,x=548,y=382,scale=1),
                              dict(text='UNSUPPORTED',x=548,y=390,scale=1)])
    # Apply conspicuous tails last: contours and annotation cannot erase them.
    pixels[below] = [255,100,30]
    pixels[above] = [245,45,170]
    return dict(camera={**CAMERA,'vertical_exaggeration':style['vertical_exaggeration']},
                visible_pixels=int(visible.sum()), color_range_m=[float(low),float(high)],
                color_range_method='visible_depth_percentile_2_98' if style['color_range']=='adaptive' else style['color_range'],
                outlier_pixels=dict(below=int(below.sum()),above=int(above.sum())),
                contour_levels_m=levels.tolist(), labeled_contour_levels_m=labels,
                contour_label_boxes_px=[list(box) for box in label_boxes],
                slope_semantics='unexaggerated_triangle_normal_degrees',
                uncertainty_legend=uncertainty_legend,
                image_legends=image_legends,
                uncertainty_color_max_m=float(uncertainties[visible].max()) if np.isfinite(uncertainties[visible]).all() else None), pixels


def preview(root, acceptance, *, output_dir, now, style=None, minimum_valid_until=None):
    document = verify(root,acceptance,now=now,minimum_valid_until=minimum_valid_until)
    style = style_controls(style)
    mesh = build_terrain(root,document)
    rendered,pixels = render_terrain(mesh,None,style)
    import numpy
    import rasterio
    code_paths = [Path(__file__),Path(vertical.__file__),Path(__file__).parent/'align.py',
                  Path(__file__).parent/'mesh.py',Path(__file__).parent/'preview.py',
                  Path(__file__).parent.parent/'handoff'/'common.py']
    binding = digest(dict(acceptance=document,style=style,
        code={p.name:ref(p.parent,p.name,'python')['sha256'] for p in code_paths},
        schemas={name:digest(json.loads(files('skippercast.coastal.resources').joinpath(name+'.schema.json').read_text()))
                 for name in (INPUT,REVIEW,RESULT)},numpy=numpy.__version__,rasterio=rasterio.__version__))
    base,out = output_path(root,output_dir)
    if out.exists():
        completion = load(base,ref(base,out/'complete.json','coastal-terrain-only-complete-v1'))
        if completion.get('binding') != binding:
            raise ValueError('terrain_only_output_binding_changed')
        result = load(base,completion['receipt'],contract=RESULT)
        if result.get('render_binding') != binding:
            raise ValueError('terrain_only_output_binding_changed')
        if {a['path'] for a in result['artifacts']} != {(out.relative_to(base)/n).as_posix() for n in ('terrain-mesh.npz','preview.png')}:
            raise ValueError('terrain_only_output_artifacts_changed')
        for artifact in result['artifacts']:
            resolve(base,artifact,cap=MAX_FILE_BYTES)
        return result
    out.parent.mkdir(parents=True,exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='.'+out.name+'.terrain-only-',dir=out.parent))
    save_mesh(stage/'terrain-mesh.npz',mesh)
    write_png(stage/'preview.png',pixels)
    for name in ('terrain-mesh.npz','preview.png'):
        with (stage/name).open('rb') as stream:
            os.fsync(stream.fileno())
    sync_directory(stage)
    result = dict(schema=RESULT,state='done',render_binding=binding,
        acceptance_context_sha256=context(document),acceptance=document,
        source_accessed=False,imagery_used=False,internal_diagnostic=True,
        publication_prohibited=True,website='held',habitat='unassessed',
        synthetic=document['synthetic'],style=style,display_z='negative_depth_m_positive_up',
        crs=mesh['crs'],crs_wkt=mesh['crs_wkt'],affine=mesh['affine'],vertical=mesh['vertical'],
        nodata=mesh['nodata'],support_cells=int(mesh['support'].sum()),
        vertices=len(mesh['vertices']),triangles=len(mesh['faces']),
        interpolation='planar_triangles_between_supported_samples_visualization_only',
        uncertainty_kind=document.get('uncertainty_kind','unavailable'),**rendered,
        artifacts=[dict(path=(out.relative_to(base)/name).as_posix(),**{k:v for k,v in ref(stage,name,contract,cap=MAX_FILE_BYTES).items() if k!='path'})
                   for name,contract in (('terrain-mesh.npz','coastal-terrain-only-mesh-v1'),('preview.png','coastal-terrain-only-png-v1'))],
        limitations=document['limitations']+([
            'NOT FOR NAVIGATION - datum offset unbounded. ' + mesh['vertical']['deep_datum']['note']
        ] if mesh['vertical'].get('deep_datum') else [])+['Derived-only diagnostic; no original-source verification performed.',
            'Scientific review is an independent attestation, not cryptographic authority proof.',
            'Fixed orthographic camera; visual triangles are not additional measurements.',
            'Color tails remain orange/pink; contours and mesh depths retain absolute metres.',
            'No datum transform, imagery, habitat assessment or website acceptance.'])
    write(stage/'render-receipt.json',result)
    receipt = ref(stage,'render-receipt.json',RESULT)
    receipt['path'] = (out.relative_to(base)/'render-receipt.json').as_posix()
    write(stage/'complete.json',dict(schema='coastal-terrain-only-complete-v1',binding=binding,receipt=receipt))
    sync_directory(stage)
    publish_staging(stage,out)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--acceptance',type=Path,required=True)
    parser.add_argument('--output-dir',required=True)
    parser.add_argument('--style',type=Path)
    parser.add_argument('--context-only',action='store_true')
    args = parser.parse_args(argv)
    try:
        acceptance = bounded_json(args.acceptance)
        if args.context_only:
            print(context(acceptance))
            return 0
        result = preview(args.root,acceptance,output_dir=args.output_dir,now=datetime.now(timezone.utc),
                         style=bounded_json(args.style) if args.style else None)
        print(json.dumps(result,sort_keys=True,allow_nan=False))
        return 0
    except (ValueError,KeyError,TypeError,OSError) as error:
        print(json.dumps(dict(schema=RESULT,state='held',holds=[str(error)],source_accessed=False,
            imagery_used=False,internal_diagnostic=True,publication_prohibited=True,website='held',habitat='unassessed')))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
