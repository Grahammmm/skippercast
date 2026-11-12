"""Self-contained internal Canvas demo of an existing hash-bound terrain mesh.

No raster/native reader, imagery, external resources or website acceptance.
The supplied receipt hash is an identity pin, not a new scientific approval.
"""
import argparse
import ast
import base64
import errno
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import stat
import struct
import tempfile
import zipfile

from .. import vertical
from ..handoff.common import digest, write
from .preview import output_path, publish_staging, sync_directory

SCHEMA = 'coastal-terrain-demo-v1'
MAX_JSON_BYTES = 2_000_000
MAX_ARTIFACT_BYTES = 8 * 1024**2
MAX_HTML_BYTES = 6 * 1024**2
MAX_SIDE = 129
MAX_NPY_HEADER_BYTES = 4096
ARRAY_NAMES = {'vertices', 'faces', 'grid_pixels', 'support', 'depth_m', 'uncertainty_m',
               'crs', 'crs_wkt', 'affine', 'nodata', 'uncertainty_kind', 'vertical_json'}
FLAGS = dict(source_accessed=False, imagery_used=False, internal_diagnostic=True,
             publication_prohibited=True, website='held', habitat='unassessed')


def _preflight_npy(archive, member):
    """Check bounded primitive headers and exact data length before numpy allocates."""
    import numpy as np
    with archive.open(member) as stream:
        prefix = stream.read(8)
        if prefix[:6] != b'\x93NUMPY' or prefix[6:] not in (b'\x01\x00', b'\x02\x00'):
            raise ValueError('mesh_npy_version_invalid')
        length_size = 2 if prefix[6:] == b'\x01\x00' else 4
        length_bytes = stream.read(length_size)
        if len(length_bytes) != length_size:
            raise ValueError('mesh_npy_header_truncated')
        length = struct.unpack('<H' if length_size == 2 else '<I', length_bytes)[0]
        if not 0 < length <= MAX_NPY_HEADER_BYTES or 8 + length_size + length > member.file_size:
            raise ValueError('mesh_npy_header_byte_bound')
        raw = stream.read(length)
        if len(raw) != length:
            raise ValueError('mesh_npy_header_truncated')
        try:
            header = ast.literal_eval(raw.decode('latin1'))
        except (SyntaxError, ValueError, TypeError, RecursionError) as error:
            raise ValueError('mesh_npy_header_invalid') from error
        if (not isinstance(header, dict) or set(header) != {'descr', 'fortran_order', 'shape'}
                or type(header['fortran_order']) is not bool):
            raise ValueError('mesh_npy_header_invalid')
        descriptor = header['descr']
        if not isinstance(descriptor, str) or not re.fullmatch(r'[<>=|](?:[fiub][1248]|U[0-9]{1,6})', descriptor):
            raise ValueError('mesh_npy_dtype_invalid:Object arrays and structured dtypes forbidden')
        dtype = np.dtype(descriptor)
        shape = header['shape']
        if not isinstance(shape, tuple) or any(type(side) is not int or side < 0 for side in shape):
            raise ValueError('mesh_npy_shape_invalid')
        name = member.filename[:-4]
        if name in ('support', 'depth_m', 'uncertainty_m'):
            shape_valid = len(shape) == 2 and all(2 <= side <= MAX_SIDE for side in shape)
            dtype_valid = (dtype.kind == 'b' and dtype.itemsize == 1 if name == 'support'
                           else dtype.kind == 'f' and dtype.itemsize in (4, 8))
        elif name in ('vertices', 'faces', 'grid_pixels'):
            limit = 2 * (MAX_SIDE - 1)**2 if name == 'faces' else MAX_SIDE**2
            columns = 2 if name == 'grid_pixels' else 3
            shape_valid = len(shape) == 2 and 0 < shape[0] <= limit and shape[1] == columns
            dtype_valid = (dtype.kind == 'f' and dtype.itemsize in (4, 8) if name == 'vertices'
                           else dtype.kind in 'iu' and dtype.itemsize in (1, 2, 4, 8))
        elif name == 'affine':
            shape_valid = shape == (9,)
            dtype_valid = dtype.kind == 'f' and dtype.itemsize in (4, 8)
        else:
            shape_valid = shape == ()
            dtype_valid = dtype.kind == 'U' and 0 < dtype.itemsize <= 4 * 100_000
        if not shape_valid or not dtype_valid:
            raise ValueError('mesh_npy_shape_or_dtype_bound:' + name)
        data_bytes = math.prod(shape) * dtype.itemsize
        if data_bytes > MAX_ARTIFACT_BYTES or stream.tell() + data_bytes != member.file_size:
            raise ValueError('mesh_npy_data_bytes_mismatch:' + name)
        return shape


def _json(data):
    def reject(value):
        raise ValueError('nonfinite_json:' + value)
    result = json.loads(data, parse_constant=reject)
    if not isinstance(result, dict):
        raise ValueError('json_object_required')
    return result


def _bytes(root, descriptor, cap):
    """Confine and hash the same bounded regular-file bytes that will be parsed."""
    if (not isinstance(descriptor, dict) or type(descriptor.get('bytes')) is not int
            or not 0 < descriptor['bytes'] <= cap
            or not re.fullmatch('[a-f0-9]{64}', str(descriptor.get('sha256')))):
        raise ValueError('artifact_descriptor_invalid')
    base = Path(root).resolve(strict=True)
    relative = Path(descriptor['path'])
    if relative.is_absolute() or '..' in relative.parts or not relative.parts:
        raise ValueError('artifact_path_must_be_root_relative')
    # Anchor each directory by descriptor, so replacing a checked parent with
    # a symlink cannot redirect the subsequent leaf open outside this root.
    directory = os.open(base, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in relative.parts[:-1]:
            next_directory = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            os.close(directory)
            directory = next_directory
        fd = os.open(relative.parts[-1], os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW, dir_fd=directory)
    except OSError as error:
        if error.errno in (errno.ELOOP, errno.ENOTDIR):
            raise ValueError('artifact_symlink_or_invalid_directory') from error
        raise
    finally:
        os.close(directory)
    try:
        header = os.fstat(fd)
        if not stat.S_ISREG(header.st_mode):
            raise ValueError('artifact_regular_file_required')
        if header.st_size != descriptor['bytes']:
            raise ValueError('artifact_bytes_changed')
        with os.fdopen(fd, 'rb', closefd=False) as stream:
            data = stream.read(cap + 1)
    finally:
        os.close(fd)
    if len(data) != descriptor['bytes'] or hashlib.sha256(data).hexdigest() != descriptor['sha256']:
        raise ValueError('artifact_hash_or_bytes_changed')
    return data


def payload(root, receipt_ref):
    """Validate only the receipt and already-produced derived NPZ/PNG bytes."""
    import numpy as np
    receipt = _json(_bytes(root, receipt_ref, MAX_JSON_BYTES))
    if (receipt.get('schema') != 'coastal-terrain-only-render-v1' or receipt.get('state') != 'done'
            or any(receipt.get(k) != v for k, v in FLAGS.items())
            or receipt.get('display_z') != 'negative_depth_m_positive_up'
            or not re.fullmatch('[a-f0-9]{64}', str(receipt.get('render_binding')))):
        raise ValueError('internal_render_receipt_required')
    acceptance = receipt['acceptance']
    if (acceptance.get('schema') != 'coastal-terrain-only-input-v1'
            or any(acceptance.get(k) != v for k, v in FLAGS.items())
            or digest({k: v for k, v in acceptance.items() if k != 'scientific_review'}) != receipt['acceptance_context_sha256']):
        raise ValueError('acceptance_context_or_holds_mismatch')
    artifacts = receipt['artifacts']
    expected = {'terrain-mesh.npz': 'coastal-terrain-only-mesh-v1', 'preview.png': 'coastal-terrain-only-png-v1'}
    if (len(artifacts) != 2 or {Path(a['path']).name for a in artifacts} != set(expected)
            or any(a.get('contract') != expected[Path(a['path']).name] for a in artifacts)):
        raise ValueError('render_artifact_set_invalid')
    verified = {Path(a['path']).name: _bytes(root, a, MAX_ARTIFACT_BYTES) for a in artifacts}
    with zipfile.ZipFile(io.BytesIO(verified['terrain-mesh.npz'])) as archive:
        members = archive.infolist()
        if (len(members) != len(ARRAY_NAMES) or {m.filename for m in members} != {n+'.npy' for n in ARRAY_NAMES}
                or any(m.flag_bits & 1 or m.is_dir() for m in members)
                or sum(m.file_size for m in members) > MAX_ARTIFACT_BYTES):
            raise ValueError('mesh_archive_bound_or_members')
        shapes = {m.filename[:-4]: _preflight_npy(archive, m) for m in members}
        if (shapes['depth_m'] != shapes['support'] or shapes['uncertainty_m'] != shapes['support']
                or shapes['vertices'][0] != shapes['grid_pixels'][0]
                or shapes['vertices'][0] > math.prod(shapes['support'])
                or shapes['faces'][0] > 2 * (shapes['support'][0]-1) * (shapes['support'][1]-1)):
            raise ValueError('mesh_npy_grid_shapes_mismatch')
    with np.load(io.BytesIO(verified['terrain-mesh.npz']), allow_pickle=False) as saved:
        mesh = {key: saved[key] for key in ARRAY_NAMES}
    support, depth, uncertainty = (mesh[k] for k in ('support', 'depth_m', 'uncertainty_m'))
    if (support.dtype != np.dtype('bool') or support.ndim != 2
            or min(support.shape) < 2 or max(support.shape) > MAX_SIDE
            or depth.shape != support.shape or uncertainty.shape != support.shape
            or depth.dtype.kind != 'f' or uncertainty.dtype.kind != 'f'
            or not np.array_equal(np.isfinite(depth), support)
            or not np.isnan(depth[~support]).all() or not np.isnan(uncertainty[~support]).all()):
        raise ValueError('mesh_depth_support_bound_or_mismatch')
    def scalar(name):
        value = mesh[name]
        if value.shape != () or value.dtype.kind != 'U' or len(value.item()) > 100_000:
            raise ValueError('mesh_metadata_scalar_invalid')
        return value.item()
    block = _json(scalar('vertical_json'))
    if (block != receipt['vertical'] or block != acceptance['vertical']
            or block != vertical.normalized(block['lineage']['source_vertical'])
            or block['lineage']['source_vertical_sha256'] != vertical.digest(block['lineage']['source_vertical'])):
        raise ValueError('mesh_vertical_metadata_mismatch')
    for key in ('crs', 'crs_wkt', 'nodata', 'uncertainty_kind'):
        if scalar(key) != receipt[key]:
            raise ValueError('mesh_' + key + '_metadata_mismatch')
    affine = mesh['affine']
    if (affine.shape != (9,) or affine.dtype.kind != 'f' or not np.isfinite(affine).all()
            or affine.tolist() != receipt['affine'] or affine.tolist() != acceptance['affine']
            or affine[0] <= 0 or affine[4] >= 0 or affine[1] != 0 or affine[3] != 0
            or affine[6:].tolist() != [0, 0, 1] or scalar('crs') != acceptance['crs']):
        raise ValueError('mesh_affine_or_crs_mismatch')
    kind = scalar('uncertainty_kind')
    if kind != acceptance.get('uncertainty_kind', 'unavailable'):
        raise ValueError('mesh_uncertainty_kind_mismatch')
    if kind == 'unavailable':
        if 'uncertainty' in acceptance or not np.isnan(uncertainty).all():
            raise ValueError('unexpected_uncertainty')
    elif (kind not in ('standard_uncertainty_m', 'producer_uncertainty_m', 'uncalibrated_dispersion_m') or 'uncertainty' not in acceptance
            or not np.array_equal(np.isfinite(uncertainty), support) or (uncertainty[support] < 0).any()):
        raise ValueError('mesh_uncertainty_support_mismatch')
    vertices, faces, pixels = (mesh[k] for k in ('vertices', 'faces', 'grid_pixels'))
    rows, cols = np.nonzero(support)
    positions = np.c_[cols, rows]
    expected_vertices = np.c_[affine[0]*(cols+.5)+affine[2], affine[4]*(rows+.5)+affine[5], -depth[support]]
    if (vertices.dtype.kind != 'f' or not np.array_equal(vertices, expected_vertices)
            or pixels.dtype.kind not in 'iu' or not np.array_equal(pixels, positions)
            or receipt['support_cells'] != int(support.sum()) or receipt['vertices'] != len(vertices)):
        raise ValueError('mesh_original_vertices_mismatch')
    index = np.full(support.shape, -1, dtype='int32'); index[support] = np.arange(len(vertices))
    expected_faces = []
    for r in range(support.shape[0]-1):
        for c in range(support.shape[1]-1):
            for corners in (((r,c),(r+1,c),(r,c+1)), ((r,c+1),(r+1,c),(r+1,c+1))):
                ids = [int(index[p]) for p in corners]
                if min(ids) >= 0:
                    expected_faces.append(ids)
    if (not expected_faces or faces.dtype.kind not in 'iu' or not np.array_equal(faces, expected_faces)
            or receipt['triangles'] != len(faces)):
        raise ValueError('mesh_supported_triangles_mismatch')
    def nullable(array):
        return np.where(np.isfinite(array), array, None).tolist()
    return dict(schema=SCHEMA, vertices=vertices.tolist(), faces=faces.tolist(), grid_pixels=pixels.tolist(),
        support=support.tolist(), depth_m=nullable(depth), uncertainty_m=nullable(uncertainty),
        vertex_uncertainty_m=nullable(uncertainty[support]), uncertainty_kind=kind,
        center=((vertices.min(axis=0)+vertices.max(axis=0))/2).tolist(), span=np.ptp(vertices,axis=0).tolist(),
        metadata=dict(crs=scalar('crs'), crs_wkt=scalar('crs_wkt'), affine=affine.tolist(), nodata=scalar('nodata'),
            vertical=block, acceptance=acceptance, render_binding=receipt['render_binding'],
            limitations=receipt['limitations'], support_cells=receipt['support_cells'], uncertainty_kind=kind,
            interpolation='planar_supported_triangle_interpolation_visualization_only', **FLAGS))


CSS = 'body{font:14px system-ui,-apple-system,sans-serif;margin:0;background:#e9f0f3;color:#163448}main{max-width:1140px;margin:auto;padding:28px}h1{font-size:30px;letter-spacing:-1px;margin:5px 0 12px}.eyebrow{font-size:11px;letter-spacing:2px;text-transform:uppercase;color:#527587;font-weight:700}.intro{max-width:760px;color:#506b79;line-height:1.6}.warning{padding:10px 14px;background:#fff1d7;border-left:3px solid #b68133;border-radius:5px;font-size:11px;letter-spacing:.5px;font-weight:650;line-height:1.5}.controls{display:flex;gap:12px;flex-wrap:wrap;align-items:end;padding:12px 0}label{display:flex;flex-direction:column;gap:6px;font-size:11px;font-weight:600;color:#4b6675}input[type=number]{width:84px}button,select,input{font:inherit}button,select,input[type=number]{border:1px solid #c3d2da;border-radius:6px;background:#fff;color:#163448;padding:8px 10px}button{cursor:pointer;font-size:12px;font-weight:600}button:hover{background:#dfeef2}button[aria-pressed=true]{background:#163e55;color:white;border-color:#163e55}button:focus-visible,select:focus-visible,input:focus-visible,canvas:focus-visible{outline:3px solid #38899a;outline-offset:3px}input[type=range]{width:140px;accent-color:#28718a}canvas{display:block;width:100%;height:auto;background:#e8eef1;touch-action:none;border:1px solid #bdcfd8;border-radius:10px;box-shadow:0 12px 28px #183b4c12}.toolbar{display:flex;gap:8px;flex-wrap:wrap;padding:12px 0}.readout{background:#fff;border:1px solid #d1dfe5;border-radius:8px;padding:12px 16px;margin:12px 0}.caption{font-size:12px;color:#527182;line-height:1.6}#error{color:#992411}#legend,#camera,#probe{line-height:1.6}#camera,#contourStatus{font-size:11px;color:#527182}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:11px}details{margin:16px 0}summary{cursor:pointer;color:#446776;font-size:12px}.swatch{display:inline-block;width:11px;height:11px;border-radius:2px;vertical-align:middle}.below{background:#e0edf0;border:1px solid #9bbec9}.above{background:#143851}#depthRamp{height:10px;border-radius:5px;background:linear-gradient(90deg,#dbeef0,#a8d7df,#64aebe,#367f9d,#1d577b,#173955);margin:8px 0}#rangeEnds{display:flex;justify-content:space-between;font-size:12px;font-weight:600}.map-title{display:flex;justify-content:space-between;align-items:center;gap:12px}.map-title small{color:#658594;font-size:11px;font-weight:600}@media(max-width:600px){main{padding:14px}h1{font-size:25px}.controls{gap:9px}input[type=range]{width:105px}.warning{font-size:10px}.map-title small{max-width:125px;text-align:right}}'
DEFAULT_STYLE = dict(profile_version='flow-v1',display_mode='Flow', subdivisions=8, strength=.75, haloCells=0)
BODY = '<main><div class="eyebrow">SkipperCast / seafloor study</div><div class="map-title"><h1>Read the shape of the bottom.</h1><small>Accepted mesh · measured sample tile</small></div>\n<p class="warning">INTERNAL DIAGNOSTIC · NOT FOR NAVIGATION · PUBLICATION PROHIBITED<br>WEBSITE HELD · HABITAT UNASSESSED</p>\n<p class="intro">A bathymetric view of the accepted depth mesh. Colour follows the visible depth range; fine absolute contours and gentle relief make changes in depth easier to read.</p>\n<div class="controls"><label>Depth units<select id="units"><option>m</option><option>ft</option></select></label>\n<label>Visible depth range<select id="mode"><option>Auto</option><option>Locked</option><option>Manual</option></select></label>\n<label>Manual minimum<input id="min" type="number" value="0" step="any"></label><label>Manual maximum<input id="max" type="number" value="50" step="any"></label><button id="apply">Apply range</button>\n<label>Display surface<select id="displayMode"><option>Flow</option><option>Measured</option></select></label>\n<label>Absolute contours (m)<input id="contours" type="number" value="0.5" min="0.1" max="1000" step="any"></label></div>\n<div class="toolbar"><button type="button" id="planView" aria-pressed="true">Plan view</button><button type="button" id="view3d" aria-pressed="false">3D relief</button><button id="zoomIn">Zoom +</button><button id="zoomOut">Zoom −</button><button id="reset">Reset view</button><button id="probeCentre">Probe centre</button></div>\n<p id="error" role="alert"></p><canvas id="terrain" tabindex="0" aria-label="Supported terrain diagnostic. Arrow keys pan, shift-arrow keys orbit, plus/minus zoom, Enter or Space probes the centre crosshair. Drag to pan or orbit; wheel or pinch to zoom; tap to probe."></canvas>\n<div class="readout"><div id="depthRamp" aria-hidden="true"></div><div id="rangeEnds"><span id="rangeLow"></span><span id="rangeHigh"></span></div><p id="legend"></p><p class="caption"><span class="swatch below"></span> Shallower than range · <span class="swatch above"></span> Deeper than range. Endpoint tones and counts indicate colour clipping, not data quality. Grey is outside supported terrain.</p><p id="probe" role="status" aria-live="polite"></p></div>\n<p class="caption">Drag to pan · wheel or pinch to zoom · tap to probe. Keyboard: arrows pan, shift-arrows orbit, +/− zoom, Enter/Space probes the centre. Flow is a labelled interpolation estimate between measured samples; its contours and relief share that display surface. Measured mode shows original triangles. Every probe reads original depth and producer uncertainty. Missing data stays blank.</p><p id="camera"></p><p id="contourStatus"></p>\n<details><summary>Camera & gentle relief</summary><div class="controls"><label>Drag gesture<select id="gesture"><option>Pan</option><option>Orbit</option></select></label><label>Orbit azimuth<input id="azimuth" type="range" min="0" max="360" value="0"></label><label>Orbit elevation<input id="elevation" type="range" min="10" max="90" value="90"></label><label>Display-only exaggeration<input id="ve" type="range" min="0.25" max="10" step="0.05" value="1"></label><label>Light azimuth<input id="lightAz" type="range" min="0" max="360" value="315"></label><label>Light elevation<input id="lightEl" type="range" min="0" max="90" value="45"></label><label>Relief intensity<input id="lightIntensity" type="range" min="0" max="1" step="0.05" value="0.5"></label></div></details>\n<details><summary>Exact original metadata and diagnostic holds</summary><p class="caption">No imagery, source access or datum transformation. Producer uncertainty is not independently calibrated absolute accuracy. Viewport-adaptive colour is a reference idea; no replication of an undisclosed author algorithm is claimed.</p><pre id="metadata"></pre></details></main>'

def style_config(style=None):
    config = {**DEFAULT_STYLE, **(style or {})}
    if set(config) != set(DEFAULT_STYLE) or config['display_mode'] not in ('Flow', 'Measured') or config['profile_version'] != 'flow-v1':
        raise ValueError('invalid_display_style')
    if type(config['subdivisions']) is not int or not 1 <= config['subdivisions'] <= 8:
        raise ValueError('display_subdivision_bound')
    if type(config['strength']) not in (int, float) or not math.isfinite(config['strength']) or not 0 <= config['strength'] <= 1:
        raise ValueError('display_strength_bound')
    if config['haloCells'] != 0:
        raise ValueError('external_halo_not_declared_by_internal_packet')
    return config


def html(data, style=None):
    module = Path(__file__).parent
    core = (module/'terrain_demo_core.js').read_text()
    ui = (module/'terrain_demo_ui.js').read_text()
    encoded = json.dumps(data, sort_keys=True, separators=(',', ':'), allow_nan=False)
    encoded = encoded.replace('&', '\\u0026').replace('<', '\\u003c').replace('>', '\\u003e')
    script = 'const TERRAIN_STYLE=' + json.dumps(style_config(style), sort_keys=True, separators=(',', ':')) + ';\nconst TERRAIN_PAYLOAD=' + encoded + ';\n' + core + '\n' + ui
    def csp_hash(text):
        return "'sha256-" + base64.b64encode(hashlib.sha256(text.encode()).digest()).decode() + "'"
    csp = "default-src 'none'; script-src " + csp_hash(script) + "; style-src " + csp_hash(CSS) + "; connect-src 'none'; img-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'"
    document = '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="' + csp + '"><title>Internal terrain diagnostic</title><style>' + CSS + '</style></head><body>' + BODY + '<script>' + script + '</script></body></html>\n'
    result = document.encode('utf-8')
    if len(result) > MAX_HTML_BYTES:
        raise ValueError('demo_html_byte_bound')
    return result


def build_demo(root, receipt_ref, *, output_dir, style=None):
    """Atomically create a new deterministic output directory; never overwrite."""
    data = payload(root, receipt_ref)
    config = style_config(style)
    encoded = html(data, config)
    base, out = output_path(root, output_dir)
    if out.exists():
        raise ValueError('demo_output_collision')
    code_paths = [Path(__file__), Path(__file__).with_name('terrain_demo_core.js'), Path(__file__).with_name('terrain_demo_ui.js'), Path(vertical.__file__), Path(__file__).with_name('preview.py')]
    result = dict(schema=SCHEMA, state='done', **FLAGS, render_receipt=receipt_ref,
        payload_sha256=digest(data), html=dict(path='terrain-demo.html',bytes=len(encoded),sha256=hashlib.sha256(encoded).hexdigest()),
        code_sha256={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in code_paths},
        vertices=len(data['vertices']), triangles=len(data['faces']), support_cells=data['metadata']['support_cells'],
        range_algorithm=dict(auto='visible_topmost_supported_pixel_centres_2nd_98th_percentiles',minimum_span_m=1,hysteresis_fraction=.08,
            locked='captures_current_range_until_mode_changed',manual='explicit_finite_min_less_than_max'),
        display_polish=dict(config=config, interpolation='bounded_monotone_hermite_display_only', backing_canvas=[1600,1000], shading='area_weighted_vertex_normals_barycentric_display_only',
            raw_probe_geometry='unchanged_original_planar_triangles', display_geometry='bounded_interpolation_estimate_in_flow_mode', palette='six_stop_blue_bathymetry', default_view='north_up_east_right_plan'),
        contour_display=dict(flow_max_faces=131072,flow_max_candidates=262144,flow_max_segments=8192,flow_decimation='whole_absolute_levels',max_triangle_level_candidates=8192,max_segments=1024,max_drawing_steps=16384,
            decimation='deterministic_even_sampling_of_display_candidates_only'),
        probe='barycentric_original_depth_and_uncertainty_on_topmost_supported_triangle',
        limitations=['Internal diagnostic identity binding; no renewed scientific review or publication acceptance.',
            'Orthographic projection; units and vertical exaggeration are display-only.',
            'Canvas pixel centres determine visible Auto statistics; no new measurement or habitat claim.'])
    out.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='.'+out.name+'.terrain-demo-',dir=out.parent))
    with (stage/'terrain-demo.html').open('xb') as stream:
        stream.write(encoded); stream.flush(); os.fsync(stream.fileno())
    write(stage/'demo-receipt.json', result)
    receipt_bytes = (stage/'demo-receipt.json').read_bytes()
    write(stage/'complete.json', dict(schema='coastal-terrain-demo-complete-v1',
        receipt=dict(path='demo-receipt.json',bytes=len(receipt_bytes),sha256=hashlib.sha256(receipt_bytes).hexdigest()),html=result['html']))
    sync_directory(stage)
    publish_staging(stage,out)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--render-receipt', required=True, help='Root-relative already-produced render receipt')
    parser.add_argument('--receipt-sha256', required=True)
    parser.add_argument('--receipt-bytes', type=int, required=True)
    parser.add_argument('--output-dir', required=True)
    parser.add_argument('--display-mode', choices=('Flow','Measured'), default='Flow')
    parser.add_argument('--display-subdivisions', type=int, default=8)
    parser.add_argument('--display-strength', type=float, default=.75)
    args = parser.parse_args(argv)
    try:
        result = build_demo(args.root,dict(path=args.render_receipt,sha256=args.receipt_sha256,bytes=args.receipt_bytes),output_dir=args.output_dir, style=dict(display_mode=args.display_mode, subdivisions=args.display_subdivisions, strength=args.display_strength))
        print(json.dumps(result,sort_keys=True,allow_nan=False));return 0
    except (ValueError,KeyError,TypeError,OSError,zipfile.BadZipFile) as error:
        print(json.dumps(dict(schema=SCHEMA,state='held',holds=[str(error)],**FLAGS)));return 2


if __name__ == '__main__':
    raise SystemExit(main())
