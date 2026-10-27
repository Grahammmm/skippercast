"""Render and check private terrain-only acceptance packets, one per core (T13).

The prepared layout (T13a/T13b, precedent
``outputs/coastal-h11952-terrain-preview-20261009``) is one directory per core::

    <prep-root>/core-<X>/inputs/{terrain,mask,uncertainty}.tif
    <prep-root>/core-<X>/acceptance-proposal.json   (author, no review)
    <prep-root>/core-<X>/science-review.json        (independent reviewer)
    <prep-root>/core-<X>/acceptance.json            (proposal + review ref)
    <prep-root>/core-<X>/science-review-HOLD.json   (reviewer refused; never rendered)

``run`` renders every accepted core with the existing
``python -m skippercast.coastal.render.terrain_only`` CLI and then checks the
outputs. ``verify`` checks already-rendered outputs without rendering. Both
write one receipt. The checks prove what the renderer kept, not that the
terrain is scientifically right; a vision-capable reviewer still inspects the
previews.

Checks per core: the render output files and their hashes, the render receipt
bound to the reviewed acceptance digest, a bounded fixed-size preview PNG, and
that holes and disjoint supported regions are preserved. Preserved means the
mesh support equals the mask, mesh depths are NaN exactly at unsupported
cells, the triangles are exactly the quads whose three corners are all
supported (so no triangle crosses a hole or joins two separate regions), and
the preview's no-data inset shows the mask. Across cores: one CRS and no
overlapping footprints, so cores are never merged.

Nothing here reads a source, downloads or writes outside ``<prep-root>``
(renders go to ``core-<X>/<output-dir>``; the receipt defaults to
``<prep-root>/t13-receipt.json``). Exit codes: 0 PASS, 3 PARTIAL (some cores
held by their reviewer, the rest pass), 1 FAIL, 2 usage error or a missing
dependency (numpy and rasterio in this interpreter; for ``run`` also
jsonschema in the ``--python`` renderer environment, probed by running that
interpreter; one stderr line names them before any core is touched).

    PYTHONPATH=src python -B research/scripts/check_terrain_acceptance.py run \\
        --prep-root <prep-root> --expect-cores 4 [--style style.json]
"""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import zlib

RECEIPT_SCHEMA = 't13-terrain-acceptance-receipt-v1'
INPUT = 'coastal-terrain-only-input-v1'
REVIEW = 'coastal-terrain-only-science-review-v1'
RESULT = 'coastal-terrain-only-render-v1'
COMPLETE = 'coastal-terrain-only-complete-v1'
WIDTH, HEIGHT = 640, 480
BACKGROUND = (238, 243, 246)
INSET = (slice(400, 464), slice(564, 628))
INSET_SUPPORTED = (80, 130, 155)
INSET_UNSUPPORTED = (225, 80, 190)
TAIL_COLORS = ((255, 100, 30), (245, 45, 170))
DEFAULT_MAX_PNG_BYTES = 8 * 1024 * 1024
MIN_PNG_BYTES = 1024
MAX_JSON_BYTES = 2_000_000
RENDER_TIMEOUT_S = 900


# ---------------------------------------------------------------- utilities

def sha256_file(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def canonical_digest(value):
    """Same canonical JSON digest as skippercast.coastal.handoff.common.digest."""
    data = json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)
    return hashlib.sha256(data.encode()).hexdigest()


def context_digest(document):
    """Acceptance context: the whole document except its review pointer."""
    return canonical_digest({k: v for k, v in document.items() if k != 'scientific_review'})


def read_json(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError(f'regular_json_file_required:{path.name}')
    if path.stat().st_size > MAX_JSON_BYTES:
        raise ValueError(f'json_byte_bound:{path.name}')

    def reject(value):
        raise ValueError('json_nonfinite:' + value)
    return json.loads(path.read_text(encoding='utf-8'), parse_constant=reject)


def write_json_atomic(path, value):
    path = Path(path)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix='.' + path.name + '.')
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(value, stream, sort_keys=True, indent=1, allow_nan=False)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def inside(root, relative):
    """Resolve a root-relative reference path without leaving the root."""
    rel = Path(relative)
    if rel.is_absolute() or '..' in rel.parts or not rel.parts:
        raise ValueError(f'reference_not_root_relative:{relative}')
    path = Path(root) / rel
    for parent in [path, *path.parents]:
        if parent == Path(root):
            break
        if parent.is_symlink():
            raise ValueError(f'reference_symlink:{relative}')
    return path


def file_ref(root, relative):
    path = inside(root, relative)
    return dict(path=Path(relative).as_posix(), sha256=sha256_file(path), bytes=path.stat().st_size)


class Checks:
    """Ordered named checks; a failing check never stops the remaining ones."""

    def __init__(self):
        self.items = []

    def add(self, name, ok, detail=None):
        self.items.append(dict(name=name, ok=bool(ok), **({'detail': detail} if detail is not None else {})))
        return bool(ok)

    def run(self, name, function):
        try:
            ok, detail = function()
        except Exception as error:  # a check that cannot run fails, with its reason
            ok, detail = False, f'{type(error).__name__}: {error}'
        return self.add(name, ok, detail)

    @property
    def ok(self):
        return all(item['ok'] for item in self.items)

    @property
    def failed(self):
        return [item['name'] for item in self.items if not item['ok']]


# ------------------------------------------------------------------- PNG

def decode_png(path):
    """Decode the renderer's PNG (8-bit RGB, non-interlaced) into rows of bytes."""
    data = Path(path).read_bytes()
    if data[:8] != b'\x89PNG\r\n\x1a\n':
        raise ValueError('png_signature')
    pos, header, idat, ended = 8, None, [], False
    while pos < len(data):
        (length,) = struct.unpack('>I', data[pos:pos + 4])
        kind = data[pos + 4:pos + 8]
        body = data[pos + 8:pos + 8 + length]
        (crc,) = struct.unpack('>I', data[pos + 8 + length:pos + 12 + length])
        if zlib.crc32(kind + body) != crc:
            raise ValueError('png_crc')
        if kind == b'IHDR':
            header = struct.unpack('>IIBBBBB', body)
        elif kind == b'IDAT':
            idat.append(body)
        elif kind == b'IEND':
            ended = True
            break
        pos += 12 + length
    if header is None or not ended:
        raise ValueError('png_structure')
    width, height, depth, color, _compression, _filter, interlace = header
    if depth != 8 or color != 2 or interlace != 0:
        raise ValueError(f'png_format:{depth}/{color}/{interlace}')
    raw = zlib.decompress(b''.join(idat))
    stride = width * 3
    if len(raw) != height * (stride + 1):
        raise ValueError('png_length')
    rows, previous = [], bytearray(stride)
    for y in range(height):
        kind = raw[y * (stride + 1)]
        line = bytearray(raw[y * (stride + 1) + 1:(y + 1) * (stride + 1)])
        if kind == 1:
            for i in range(3, stride):
                line[i] = (line[i] + line[i - 3]) & 255
        elif kind == 2:
            for i in range(stride):
                line[i] = (line[i] + previous[i]) & 255
        elif kind != 0:
            raise ValueError(f'png_filter_unsupported:{kind}')
        rows.append(bytes(line))
        previous = line
    return width, height, rows


def pixel(rows, x, y):
    row = rows[y]
    return tuple(row[3 * x:3 * x + 3])


# --------------------------------------------------------------- topology

def label(grid, diagonal):
    """Connected components of True cells (4- or 8-connected); returns (labels, count)."""
    height, width = len(grid), len(grid[0]) if grid else 0
    labels = [[0] * width for _ in range(height)]
    steps = [(-1, 0), (1, 0), (0, -1), (0, 1)]
    if diagonal:
        steps += [(-1, -1), (-1, 1), (1, -1), (1, 1)]
    count = 0
    for r in range(height):
        for c in range(width):
            if grid[r][c] and not labels[r][c]:
                count += 1
                labels[r][c] = count
                stack = [(r, c)]
                while stack:
                    y, x = stack.pop()
                    for dy, dx in steps:
                        yy, xx = y + dy, x + dx
                        if 0 <= yy < height and 0 <= xx < width and grid[yy][xx] and not labels[yy][xx]:
                            labels[yy][xx] = count
                            stack.append((yy, xx))
    return labels, count


def expected_faces(support):
    """The renderer's triangulation, recomputed from the mask alone."""
    faces = set()
    height, width = len(support), len(support[0])
    for r in range(height - 1):
        for c in range(width - 1):
            for corners in (((r, c), (r + 1, c), (r, c + 1)), ((r, c + 1), (r + 1, c), (r + 1, c + 1))):
                if all(support[y][x] for y, x in corners):
                    faces.add(tuple(sorted(corners)))
    return faces


def topology(support, faces_cells):
    """Counts that show what the mask and mesh hold; support is a list of bool rows."""
    height, width = len(support), len(support[0])
    unsupported = [[not v for v in row] for row in support]
    _, components_4 = label(support, diagonal=False)
    labels_8, components_8 = label(support, diagonal=True)
    gap_labels, gaps = label(unsupported, diagonal=False)
    touches_border = set()
    for r in range(height):
        for c in (0, width - 1):
            if gap_labels[r][c]:
                touches_border.add(gap_labels[r][c])
    for c in range(width):
        for r in (0, height - 1):
            if gap_labels[r][c]:
                touches_border.add(gap_labels[r][c])
    hole_cells = sum(1 for r in range(height) for c in range(width)
                     if gap_labels[r][c] and gap_labels[r][c] not in touches_border)
    border_gap_cells = sum(1 for r in range(height) for c in range(width)
                           if gap_labels[r][c] and gap_labels[r][c] in touches_border)
    # Mesh components by union-find over triangle corners.
    parent = {}

    def find(a):
        while parent.setdefault(a, a) != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a
    for face in faces_cells:
        first = find(face[0])
        for other in face[1:]:
            root = find(other)
            if root != first:
                parent[root] = first
    in_faces = set(parent)
    mesh_roots = {find(cell) for cell in in_faces}
    by_root = {}
    for cell in in_faces:
        by_root.setdefault(find(cell), set()).add(labels_8[cell[0]][cell[1]])
    spanning = sum(1 for values in by_root.values() if len(values) != 1)
    supported_cells = sum(sum(1 for v in row if v) for row in support)
    return dict(grid_shape=[height, width], supported_cells=supported_cells,
                unsupported_cells=height * width - supported_cells,
                mask_components_4=components_4, mask_components_8=components_8,
                unsupported_regions=gaps, enclosed_holes=gaps - len(touches_border),
                enclosed_hole_cells=hole_cells, border_gap_cells=border_gap_cells,
                mesh_components=len(mesh_roots), mesh_components_spanning_mask_regions=spanning,
                supported_cells_in_no_triangle=supported_cells - len(in_faces),
                triangles=len(faces_cells))


# ------------------------------------------------------------- per core

def discover_cores(prep_root, labels=None):
    names = sorted(p.name for p in Path(prep_root).iterdir() if p.is_dir() and p.name.startswith('core-'))
    if labels:
        wanted = ['core-' + x for x in labels]
        missing = [w for w in wanted if w not in names]
        if missing:
            raise ValueError('cores_missing:' + ','.join(missing))
        names = wanted
    return names


def core_status(core_dir):
    if (core_dir / 'science-review-HOLD.json').exists():
        return 'held_by_review'
    if (core_dir / 'acceptance.json').is_file():
        return 'accepted'
    return 'missing_acceptance'


def render_command(args, core_dir):
    command = [args.python, '-B', '-m', 'skippercast.coastal.render.terrain_only',
               '--root', str(core_dir), '--acceptance', str(core_dir / 'acceptance.json'),
               '--output-dir', args.output_dir]
    if args.style:
        command += ['--style', str(Path(args.style).resolve())]
    return command


def renderer_env(args):
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1')
    if args.pythonpath:
        env['PYTHONPATH'] = str(Path(args.pythonpath).resolve())
    return env


def render_core(args, core_dir):
    command = render_command(args, core_dir)
    env = renderer_env(args)
    try:
        done = subprocess.run(command, env=env, capture_output=True, text=True, timeout=args.timeout_s, check=False)
        code, out, err = done.returncode, done.stdout, done.stderr
    except subprocess.TimeoutExpired as error:
        code, out, err = 'timeout', error.stdout or '', error.stderr or ''
    parsed = None
    for line in reversed((out or '').strip().splitlines()):
        try:
            parsed = json.loads(line)
            break
        except ValueError:
            continue
    return dict(argv=command, exit_code=code,
                stdout_state=parsed.get('state') if isinstance(parsed, dict) else None,
                stdout_holds=parsed.get('holds', []) if isinstance(parsed, dict) else [],
                stderr_tail=(err or '')[-2000:])


def verify_core(core_dir, *, output_dir, max_png_bytes, require_holes=False):
    """Check one rendered core; returns (checks, facts)."""
    import numpy as np
    import rasterio

    checks, facts = Checks(), {}
    out_rel = Path(output_dir)
    acceptance = read_json(core_dir / 'acceptance.json')
    facts['facts_digest'] = context_digest(acceptance)

    def inputs():
        problems = []
        for role in ('terrain', 'mask', 'uncertainty'):
            item = acceptance.get(role)
            if item is None:
                if role != 'uncertainty':
                    problems.append(role + ':missing')
                continue
            actual = file_ref(core_dir, item['path'])
            if (actual['sha256'], actual['bytes']) != (item['sha256'], item['bytes']):
                problems.append(role + ':hash_or_bytes')
        return not problems, problems or 'terrain/mask/uncertainty match acceptance refs'
    checks.run('inputs_match_acceptance_refs', inputs)

    def review():
        ref = acceptance.get('scientific_review')
        if not ref:
            return False, 'acceptance has no scientific_review'
        actual = file_ref(core_dir, ref['path'])
        if (actual['sha256'], actual['bytes']) != (ref['sha256'], ref['bytes']):
            return False, 'review bytes differ from acceptance ref'
        document = read_json(inside(core_dir, ref['path']))
        problems = [name for name, ok in (
            ('schema', document.get('schema') == REVIEW),
            ('decision', document.get('decision') == 'accept'),
            ('independent', document.get('independent') is True),
            ('reviewer_differs_from_creator', document.get('reviewer_id') not in (None, '', acceptance.get('creator_id'))),
            ('facts_digest', document.get('facts_digest') == facts['facts_digest']),
            ('synthetic_matches', document.get('synthetic') == acceptance.get('synthetic'))) if not ok]
        facts['reviewer_id'] = document.get('reviewer_id')
        facts['review_valid_until'] = document.get('valid_until')
        return not problems, problems or 'independent accept bound to this acceptance digest'
    checks.run('science_review_bound', review)

    def preparation():
        path = core_dir / 'preparation-receipt.json'
        if not path.exists():
            return True, 'no preparation-receipt.json (optional)'
        recorded = read_json(path).get('facts_digest')
        return recorded == facts['facts_digest'], f'preparation facts_digest {recorded}'
    checks.run('preparation_receipt_digest', preparation)

    def labels():
        wanted = dict(schema=INPUT, publication_prohibited=True, internal_diagnostic=True,
                      source_accessed=False, imagery_used=False, website='held', habitat='unassessed')
        wrong = sorted(k for k, v in wanted.items() if acceptance.get(k) != v)
        if not acceptance.get('limitations'):
            wrong.append('limitations')
        return not wrong, wrong or 'private terrain-only labels present'
    checks.run('acceptance_private_labels', labels)

    paths = {name: core_dir / out_rel / name for name in
             ('complete.json', 'render-receipt.json', 'preview.png', 'terrain-mesh.npz')}

    def present():
        missing = [n for n, p in paths.items() if p.is_symlink() or not p.is_file()]
        return not missing, missing or 'all four render outputs present'
    if not checks.run('render_outputs_present', present):
        return checks, facts
    receipt = read_json(paths['render-receipt.json'])
    complete = read_json(paths['complete.json'])
    facts['outputs'] = [file_ref(core_dir, (out_rel / n).as_posix()) for n in sorted(paths)]

    def completion():
        ref = complete.get('receipt') or {}
        actual = file_ref(core_dir, (out_rel / 'render-receipt.json').as_posix())
        problems = [name for name, ok in (
            ('schema', complete.get('schema') == COMPLETE),
            ('receipt_ref', (ref.get('sha256'), ref.get('bytes')) == (actual['sha256'], actual['bytes'])),
            ('binding', complete.get('binding') == receipt.get('render_binding'))) if not ok]
        return not problems, problems or 'complete.json binds the render receipt'
    checks.run('completion_binding', completion)

    def receipt_state():
        wanted = dict(schema=RESULT, state='done', publication_prohibited=True, internal_diagnostic=True,
                      source_accessed=False, imagery_used=False, website='held', habitat='unassessed')
        wrong = sorted(k for k, v in wanted.items() if receipt.get(k) != v)
        return not wrong, wrong or 'done, private, no source/imagery access'
    checks.run('render_receipt_state', receipt_state)

    def acceptance_context():
        ok = (receipt.get('acceptance_context_sha256') == facts['facts_digest']
              and receipt.get('acceptance') == acceptance)
        return ok, dict(receipt=receipt.get('acceptance_context_sha256'), recomputed=facts['facts_digest'])
    checks.run('receipt_acceptance_context_equals_facts_digest', acceptance_context)

    def artifacts():
        expected = {(out_rel / n).as_posix() for n in ('terrain-mesh.npz', 'preview.png')}
        listed = {a.get('path') for a in receipt.get('artifacts', [])}
        if listed != expected:
            return False, dict(listed=sorted(listed), expected=sorted(expected))
        problems = []
        for artifact in receipt['artifacts']:
            actual = file_ref(core_dir, artifact['path'])
            if (actual['sha256'], actual['bytes']) != (artifact['sha256'], artifact['bytes']):
                problems.append(artifact['path'])
        return not problems, problems or 'mesh and preview hashes match the receipt'
    checks.run('artifact_hashes', artifacts)

    # Rasters: the reviewed inputs the renderer was given.
    with rasterio.open(inside(core_dir, acceptance['mask']['path'])) as ds:
        mask = ds.read(1)
        mask_crs, mask_transform = ds.crs.to_string(), list(ds.transform)
    with rasterio.open(inside(core_dir, acceptance['terrain']['path'])) as ds:
        terrain = ds.read(1, masked=True).filled(np.nan).astype('float64')
        terrain_crs, terrain_transform, shape = ds.crs.to_string(), list(ds.transform), ds.shape
    support = mask == 1
    support_rows = support.tolist()
    facts.update(crs=terrain_crs, affine=terrain_transform, shape=list(shape))

    def georeference():
        ok = (terrain_crs == mask_crs == acceptance.get('crs') == receipt.get('crs')
              and terrain_transform == mask_transform == acceptance.get('affine') == receipt.get('affine'))
        return ok, dict(crs=terrain_crs, affine=terrain_transform)
    checks.run('georeference_consistent', georeference)

    def binary_mask():
        values = sorted(int(v) for v in np.unique(mask))
        return set(values) <= {0, 1} and bool(support.any()), dict(values=values)
    checks.run('mask_binary_with_support', binary_mask)

    mesh = None

    def mesh_loads():
        nonlocal mesh
        with np.load(paths['terrain-mesh.npz'], allow_pickle=False) as archive:
            mesh = {k: archive[k] for k in archive.files}
        needed = {'vertices', 'faces', 'grid_pixels', 'support', 'depth_m', 'uncertainty_m', 'affine', 'crs'}
        missing = sorted(needed - set(mesh))
        return not missing, missing or sorted(mesh)
    if not checks.run('mesh_npz_readable', mesh_loads):
        return checks, facts

    def mesh_support():
        ok = mesh['support'].shape == support.shape and bool(np.array_equal(mesh['support'].astype(bool), support))
        return ok, 'mesh support equals the reviewed mask cell for cell'
    checks.run('mesh_support_equals_mask', mesh_support)

    def no_interpolation():
        depth = mesh['depth_m']
        nan = np.isnan(depth)
        problems = []
        if not np.array_equal(nan, ~support):
            problems.append('mesh depth NaN pattern differs from the unsupported cells')
        if not np.array_equal(np.isfinite(terrain), support):
            problems.append('terrain validity differs from the mask')
        if not np.array_equal(depth[support], terrain[support]):
            problems.append('mesh depths differ from terrain values at supported cells')
        return not problems, problems or 'no-data stays no-data; supported depths unchanged'
    checks.run('holes_not_interpolated', no_interpolation)

    def vertices():
        rows, cols = np.nonzero(support)
        grid = mesh['grid_pixels']
        problems = []
        if len(mesh['vertices']) != len(rows) or grid.shape != (len(rows), 2):
            problems.append('vertex count differs from supported cells')
        else:
            if not (np.array_equal(grid[:, 0], cols) and np.array_equal(grid[:, 1], rows)):
                problems.append('vertex grid cells differ from supported cells')
            a = terrain_transform
            x = a[0] * (cols + .5) + a[1] * (rows + .5) + a[2]
            y = a[3] * (cols + .5) + a[4] * (rows + .5) + a[5]
            if not (np.allclose(mesh['vertices'][:, 0], x, atol=1e-6, rtol=0)
                    and np.allclose(mesh['vertices'][:, 1], y, atol=1e-6, rtol=0)):
                problems.append('vertex x/y are not the supported cell centres')
            if not np.array_equal(mesh['vertices'][:, 2], -terrain[rows, cols]):
                problems.append('vertex z is not -depth')
        return not problems, problems or 'one vertex per supported cell centre, z = -depth'
    checks.run('vertices_are_supported_cells', vertices)

    faces_cells = None

    def faces():
        nonlocal faces_cells
        grid = mesh['grid_pixels']
        f = mesh['faces']
        if f.ndim != 2 or f.shape[1] != 3 or (len(f) and (f.min() < 0 or f.max() >= len(grid))):
            return False, 'face indices out of range'
        faces_cells = [tuple(sorted((int(grid[i][1]), int(grid[i][0])) for i in face)) for face in f.tolist()]
        actual = set(faces_cells)
        expected = expected_faces(support_rows)
        extra, missing = actual - expected, expected - actual
        detail = dict(triangles=len(faces_cells), duplicates=len(faces_cells) - len(actual),
                      extra=len(extra), missing=len(missing),
                      receipt_triangles=receipt.get('triangles'))
        ok = not extra and not missing and len(actual) == len(faces_cells) == receipt.get('triangles')
        return ok, detail
    checks.run('triangles_only_inside_supported_quads', faces)

    def counts():
        ok = receipt.get('support_cells') == int(support.sum()) == receipt.get('vertices')
        return ok, dict(receipt_support_cells=receipt.get('support_cells'), mask=int(support.sum()))
    checks.run('receipt_support_counts', counts)

    if faces_cells is not None:
        def components():
            facts['topology'] = topology(support_rows, faces_cells)
            spanning = facts['topology']['mesh_components_spanning_mask_regions']
            if require_holes and not facts['topology']['unsupported_cells']:
                return False, 'no unsupported cells but --require-holes was given'
            return spanning == 0, facts['topology']
        checks.run('disjoint_regions_stay_disjoint', components)

    def png():
        size = paths['preview.png'].stat().st_size
        width, height, rows = decode_png(paths['preview.png'])
        terrain_pixels = sum(1 for y in range(0, height) for x in range(0, width)
                             if pixel(rows, x, y) != BACKGROUND)
        facts['preview'] = dict(width=width, height=height, bytes=size, non_background_pixels=terrain_pixels)
        ok = (width, height) == (WIDTH, HEIGHT) and MIN_PNG_BYTES <= size <= max_png_bytes and terrain_pixels > 0
        return ok, facts['preview']
    checks.run('preview_png_bounded_nonblank', png)

    def inset():
        style = receipt.get('style') or {}
        if style.get('no_data_overlay') is not True:
            return True, 'no_data_overlay off; inset not drawn'
        _w, _h, rows = decode_png(paths['preview.png'])
        h, w = support.shape
        swapped, other, occluded = 0, 0, 0
        for yy in range(64):
            for xx in range(64):
                want = INSET_SUPPORTED if support[min(yy * h // 64, h - 1), min(xx * w // 64, w - 1)] else INSET_UNSUPPORTED
                got = pixel(rows, INSET[1].start + xx, INSET[0].start + yy)
                if got == want:
                    continue
                if got in TAIL_COLORS:
                    occluded += 1
                elif got in (INSET_SUPPORTED, INSET_UNSUPPORTED):
                    swapped += 1
                else:
                    other += 1
        detail = dict(swapped=swapped, other=other, tail_occluded=occluded)
        return swapped == 0 and other == 0 and occluded <= 64 * 64 // 20, detail
    checks.run('preview_nodata_inset_matches_mask', inset)
    return checks, facts


def footprint(affine, shape):
    a, b, c, d, e, f = affine[:6]
    xs = [c + a * col + b * row for col in (0, shape[1]) for row in (0, shape[0])]
    ys = [f + d * col + e * row for col in (0, shape[1]) for row in (0, shape[0])]
    return min(xs), min(ys), max(xs), max(ys)


def cross_core(cores):
    rendered = [c for c in cores if c.get('facts', {}).get('affine')]
    crs = sorted({c['facts']['crs'] for c in rendered})
    pairs, overlaps = [], 0
    for i, left in enumerate(rendered):
        for right in rendered[i + 1:]:
            l = footprint(left['facts']['affine'], left['facts']['shape'])
            r = footprint(right['facts']['affine'], right['facts']['shape'])
            dx = min(l[2], r[2]) - max(l[0], r[0])
            dy = min(l[3], r[3]) - max(l[1], r[1])
            if dx > 0 and dy > 0:
                relation = 'overlapping'
                overlaps += 1
            elif dx >= 0 and dy >= 0:
                relation = 'edge_or_corner_adjacent'
            else:
                relation = 'disjoint'
            pairs.append(dict(cores=[left['label'], right['label']], relation=relation))
    ok = len(crs) <= 1 and overlaps == 0
    return dict(ok=ok, crs=crs, pairs=pairs, overlapping_pairs=overlaps,
                note='Each core is rendered and checked on its own; none is merged with another.')


def git_identity(pythonpath):
    if not pythonpath:
        return dict(sha=None, dirty=None)
    top = Path(pythonpath).resolve().parent
    try:
        sha = subprocess.run(['git', '-C', str(top), 'rev-parse', 'HEAD'], capture_output=True,
                             text=True, check=True).stdout.strip()
        dirty = subprocess.run(['git', '-C', str(top), 'status', '--porcelain', '--', 'src'],
                               capture_output=True, text=True, check=True).stdout.strip() != ''
        return dict(sha=sha, dirty=dirty, checkout=str(top))
    except (OSError, subprocess.CalledProcessError):
        return dict(sha=None, dirty=None, checkout=str(top))


CHECKER_MODULES = ('numpy', 'rasterio')
RENDERER_MODULES = ('jsonschema',)  # terrain_only.verify
PROBE_TIMEOUT_S = 60


def missing_dependencies(names):
    """The per-name dependency loop of coastal/cli.py runtime_identity and
    coordinator/loop.py implementation_hashes, but importing each module:
    installed metadata alone does not prove it loads in this interpreter."""
    missing = []
    for name in names:
        try:
            importlib.import_module(name)
        except ImportError:
            missing.append(name)
    return missing


# Runs missing_dependencies' loop inside the renderer interpreter; prints one JSON line.
RENDERER_PROBE = '''import importlib, json, sys
missing = []
for name in sys.argv[1:]:
    try:
        importlib.import_module(name)
    except ImportError:
        missing.append(name)
print(json.dumps(dict(prefix=sys.prefix, missing=missing)))
'''


def probe_renderer(args, names=RENDERER_MODULES):
    """Import ``names`` in the ``--python`` renderer with the environment
    ``render_core`` gives it. Its interpreter path, even when it resolves to the
    checker's binary, does not identify its site-packages, so only the renderer
    itself can say what it imports. Returns (prefix, missing); raises ValueError
    when the renderer cannot run the probe."""
    try:
        done = subprocess.run([args.python, '-B', '-c', RENDERER_PROBE, *names], env=renderer_env(args),
                              capture_output=True, text=True, timeout=PROBE_TIMEOUT_S, check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ValueError(type(error).__name__) from error
    try:
        result = json.loads(done.stdout.strip().splitlines()[-1])
        return result['prefix'], result['missing']
    except (IndexError, ValueError, KeyError, TypeError) as error:
        raise ValueError(f'exit {done.returncode}') from error


def preflight(args):
    """One stderr line naming what is missing, or None. The checks need numpy and
    rasterio here; ``run`` also needs jsonschema in the renderer environment."""
    missing = missing_dependencies(CHECKER_MODULES)
    if missing:
        return f"{', '.join(missing)} required: install skippercast[survey] into {sys.prefix}"
    if args.mode != 'run':
        return None
    try:
        prefix, missing = probe_renderer(args)
    except ValueError as error:
        return f'renderer --python {args.python} cannot run the dependency probe ({error})'
    if missing:
        return f"{', '.join(missing)} required: install skippercast[survey] into {prefix} (renderer --python)"
    return None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('mode', choices=('run', 'verify'))
    parser.add_argument('--prep-root', type=Path, required=True)
    parser.add_argument('--cores', help='comma-separated labels (default: every core-* directory)')
    parser.add_argument('--expect-cores', type=int, default=4)
    parser.add_argument('--output-dir', default='render', help='render directory inside each core')
    parser.add_argument('--style', type=Path)
    parser.add_argument('--python', default=sys.executable)
    parser.add_argument('--pythonpath', help='src directory used for the renderer (default: inherited PYTHONPATH)')
    parser.add_argument('--receipt', type=Path, help='default <prep-root>/t13-receipt.json')
    parser.add_argument('--overwrite-receipt', action='store_true')
    parser.add_argument('--max-png-bytes', type=int, default=DEFAULT_MAX_PNG_BYTES)
    parser.add_argument('--require-holes', action='store_true', help='fail a core whose mask has no unsupported cell')
    parser.add_argument('--timeout-s', type=int, default=RENDER_TIMEOUT_S)
    parser.add_argument('--reviewer', default='opus-coder', help='recorded as the requested reviewer')
    args = parser.parse_args(argv)

    if args.pythonpath is None and os.environ.get('PYTHONPATH'):
        args.pythonpath = os.environ['PYTHONPATH'].split(os.pathsep)[0]
    problem = preflight(args)
    if problem:
        print(problem, file=sys.stderr)
        return 2

    prep_root = args.prep_root.resolve()
    receipt_path = (args.receipt or prep_root / 't13-receipt.json').resolve()
    out = Path(args.output_dir)
    if out.is_absolute() or '..' in out.parts or not out.parts:
        parser.error('--output-dir must be a relative path inside each core')
    if not prep_root.is_dir():
        parser.error(f'--prep-root {prep_root} is not a directory')
    if receipt_path.exists() and not args.overwrite_receipt:
        parser.error(f'{receipt_path} exists; pass --overwrite-receipt to replace it')
    try:
        names = discover_cores(prep_root, args.cores.split(',') if args.cores else None)
    except ValueError as error:
        parser.error(str(error))

    cores = []
    for name in names:
        core_dir = prep_root / name
        entry = dict(label=name.removeprefix('core-'), directory=str(core_dir), status=core_status(core_dir))
        if entry['status'] == 'accepted':
            if args.mode == 'run':
                entry['render'] = render_core(args, core_dir)
            checks, facts = verify_core(core_dir, output_dir=args.output_dir, max_png_bytes=args.max_png_bytes,
                                        require_holes=args.require_holes)
            if args.mode == 'run':
                render = entry['render']
                checks.add('render_exit_zero', render['exit_code'] == 0 and render['stdout_state'] == 'done',
                           dict(exit_code=render['exit_code'], state=render['stdout_state'],
                                holds=render['stdout_holds']))
            entry.update(checks=checks.items, failed=checks.failed, facts=facts,
                         verdict='PASS' if checks.ok else 'FAIL')
        elif entry['status'] == 'held_by_review':
            entry.update(verdict='HELD', note='reviewer HOLD; not rendered (T13 renders accepted cores only)')
        else:
            entry.update(verdict='FAIL', note='no acceptance.json and no science-review-HOLD.json')
        cores.append(entry)

    across = cross_core(cores)
    verdicts = [c['verdict'] for c in cores]
    if (len(cores) == args.expect_cores and verdicts and all(v == 'PASS' for v in verdicts) and across['ok']):
        verdict = 'PASS'
    elif ('FAIL' not in verdicts and 'PASS' in verdicts and across['ok'] and len(cores) == args.expect_cores):
        verdict = 'PARTIAL'
    else:
        verdict = 'FAIL'
    receipt = dict(
        schema=RECEIPT_SCHEMA, verdict=verdict, mode=args.mode,
        created_at=datetime.now(timezone.utc).isoformat(timespec='seconds'),
        prep_root=str(prep_root), expect_cores=args.expect_cores,
        cores_found=len(cores), cores_passed=verdicts.count('PASS'), cores_held=verdicts.count('HELD'),
        code=dict(git_identity(args.pythonpath), pythonpath=args.pythonpath, python=args.python,
                  checker_sha256=sha256_file(__file__)),
        command=[sys.executable, *(sys.argv if argv is None else [__file__, *argv])],
        style=dict(file_ref(args.style.resolve().parent, args.style.name), source=str(args.style.resolve()))
        if args.style else None,
        cores=cores, cross_core=across, reviewer_requested=args.reviewer,
        limitations=['Machine checks only: review-required, not semantic or publication acceptance.',
                     'A vision-capable reviewer must inspect each preview.png for holes, geography and depth.',
                     'Private internal diagnostic; publication prohibited; website held; habitat unassessed.'])
    write_json_atomic(receipt_path, receipt)
    summary = dict(verdict=verdict, receipt=str(receipt_path), receipt_sha256=sha256_file(receipt_path),
                   cores={c['label']: dict(verdict=c['verdict'], failed=c.get('failed', []),
                                           topology=c.get('facts', {}).get('topology')) for c in cores},
                   cross_core_ok=across['ok'])
    print(json.dumps(summary, sort_keys=True, indent=1))
    return {'PASS': 0, 'PARTIAL': 3}.get(verdict, 1)


if __name__ == '__main__':
    raise SystemExit(main())
