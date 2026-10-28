"""Bounded native-only triangles and fixed orthographic software rasterization."""
import math
import struct
import zlib
from pathlib import Path

MAX_SIDE = 129
WIDTH, HEIGHT = 640, 480
CAMERA = {"projection": "orthographic", "azimuth_degrees": 35, "elevation_degrees": 40,
          "vertical_exaggeration": 1, "width": WIDTH, "height": HEIGHT}


def camera_projection(vertices, vertical_exaggeration=1.0):
    """Project world XYZ into a centered camera basis; return projected XYZ and basis rows."""
    import numpy as np

    points = np.asarray(vertices, dtype=np.float64).copy()
    if points.ndim != 2 or points.shape[1] != 3 or not len(points):
        raise ValueError("camera_xyz_vertices_required")
    if not math.isfinite(float(vertical_exaggeration)) or float(vertical_exaggeration) <= 0:
        raise ValueError("camera_vertical_exaggeration_invalid")
    points[:, 2] *= float(vertical_exaggeration)
    points -= (points.min(axis=0) + points.max(axis=0)) / 2
    az = math.radians(CAMERA["azimuth_degrees"])
    el = math.radians(CAMERA["elevation_degrees"])
    right = np.array([-math.cos(az), math.sin(az), 0.0])
    view = np.array([math.sin(az) * math.cos(el), math.cos(az) * math.cos(el), math.sin(el)])
    up = np.cross(view, right)
    basis = np.stack((right, up, view))
    projected = points @ basis.T
    projected[:, :2] -= (projected[:, :2].min(axis=0) + projected[:, :2].max(axis=0)) / 2
    return projected, basis


def build_mesh(terrain_path, support_path, imagery_path, vertical):
    import numpy as np
    import rasterio
    from rasterio.warp import transform
    from .align import check_header, check_geotiff

    if vertical.get("units") != "m" or vertical.get("sign") not in {"positive_up", "positive_down"}:
        raise ValueError("normalized_vertical_semantics_required")
    if vertical.get("datum") not in {"MLLW", "MSL", "NAVD88", "ellipsoid:WGS84"}:
        raise ValueError("vertical_datum_unknown")
    if any(c.get("resolution") not in {"resolved", "accepted"} for c in vertical.get("conflicts", [])):
        raise ValueError("vertical_conflict_unresolved")
    for path in (terrain_path, support_path, imagery_path):
        check_geotiff(path)
    with rasterio.open(terrain_path) as ds, rasterio.open(support_path) as support, rasterio.open(imagery_path) as image:
        for item in (ds, support, image):
            check_header(item)
        if ds.width > MAX_SIDE or ds.height > MAX_SIDE:
            raise ValueError("native_mesh_side_bound")
        if not ds.crs.is_projected or ds.crs.linear_units != "metre":
            raise ValueError("metric_terrain_crs_required")
        if (ds.crs, ds.transform, ds.width, ds.height) != (support.crs, support.transform, support.width, support.height):
            raise ValueError("support_grid_mismatch")
        if ds.count != 1 or support.count != 1 or image.count not in (3, 4):
            raise ValueError("terrain_mask_rgb_bands_required")
        # Mapping outputs must already be unpacked physical metres.
        if ds.scales != (1.0,) or ds.offsets != (0.0,):
            raise ValueError("unapplied_terrain_packing")
        # Integer storage is valid for unpacked metres, but cannot hold a NaN fill.
        raw = ds.read(1, masked=True).astype(np.float64)
        mask = support.read(1, masked=True)
        mask_values = mask.compressed()
        if not np.isin(mask_values, [0, 1]).all():
            raise ValueError("binary_support_required")
        values = raw.filled(np.nan)
        valid = (~np.ma.getmaskarray(raw) & ~np.ma.getmaskarray(mask)
                 & (mask.filled(0) == 1) & np.isfinite(values))
        if vertical["sign"] == "positive_down":
            values = -values
        rows, cols = np.nonzero(valid)
        if not len(rows):
            raise ValueError("no_measured_support")
        x = ds.transform.c + (cols + 0.5) * ds.transform.a
        y = ds.transform.f + (rows + 0.5) * ds.transform.e
        vertices = np.c_[x, y, values[rows, cols]]
        index = np.full(valid.shape, -1, dtype=np.int32)
        index[rows, cols] = np.arange(len(rows))
        faces = []
        for row in range(ds.height - 1):
            for col in range(ds.width - 1):
                for pixels in (((row, col), (row + 1, col), (row, col + 1)),
                               ((row, col + 1), (row + 1, col), (row + 1, col + 1))):
                    ids = [int(index[p]) for p in pixels]
                    if min(ids) >= 0:
                        faces.append(ids)
        if not faces:
            raise ValueError("no_measured_triangles")
        # The minimum private adapter only textures co-CRS north-up grids. A
        # nonlinear reprojection needs curved-footprint rasterization first.
        if ds.crs != image.crs:
            raise ValueError("same_crs_masked_texturing_required")
        ix, iy = transform(ds.crs, image.crs, x.tolist(), y.tolist())
        inv = ~image.transform
        ic, ir = zip(*(inv @ (a, b) for a, b in zip(ix, iy)))
        image_pixels = np.c_[ic, ir]
        ic, ir = np.floor(ic).astype(int), np.floor(ir).astype(int)
        if ((ic < 0) | (ic >= image.width) | (ir < 0) | (ir >= image.height)).any():
            raise ValueError("imagery_missing_at_supported_vertex")
        rgb = image.read([1, 2, 3])
        if rgb.dtype != np.uint8:
            raise ValueError("uint8_rgb_imagery_required")
        image_valid = (image.read_masks([1, 2, 3]) > 0).all(axis=0)
        if not image_valid[ir, ic].all():
            raise ValueError("imagery_mask_missing_at_supported_vertex")
        # Conservatively require the entire image-pixel bounding rectangle of
        # each triangle to be supported. This may exclude extra valid area near
        # a void, but never paints over a finer-resolution unsupported cell.
        bad = np.pad((~image_valid).astype(np.int32), ((1,0),(1,0))).cumsum(0).cumsum(1)
        supported_faces = []
        for face in faces:
            footprint = image_pixels[face]
            left, top = np.floor(footprint.min(axis=0)).astype(int)
            right, bottom = np.floor(footprint.max(axis=0)).astype(int)
            invalid = bad[bottom+1,right+1] - bad[top,right+1] - bad[bottom+1,left] + bad[top,left]
            if invalid == 0:
                supported_faces.append(face)
        if not supported_faces:
            raise ValueError("no_imagery_supported_triangles")
        excluded = len(faces) - len(supported_faces)
        colors = rgb[:, ir, ic].T
        faces = supported_faces
        return {"vertices": vertices, "faces": np.asarray(faces, dtype=np.int32),
                "colors": colors, "grid_pixels": np.c_[cols, rows].astype(np.int32),
                "support": valid, "crs": ds.crs.to_string(), "vertical": vertical,
                "imagery_mask_excluded_triangles": excluded}


def _validate_preview_faces(faces, vertex_count):
    """Reject malformed indexes in their original dtype, before projection."""
    import numpy as np

    if (type(faces) is not np.ndarray
            or faces.ndim != 2 or faces.shape[1] != 3 or not len(faces)
            or faces.dtype.kind not in "iu"):
        raise ValueError("preview_faces_invalid")
    if (faces < 0).any() or (faces >= vertex_count).any():
        raise ValueError("preview_faces_invalid")


def render_png(mesh, path):
    """Project actual mesh triangles, texture their faces, and resolve occlusion."""
    import numpy as np

    vertices, faces = mesh["vertices"], mesh["faces"]
    _validate_preview_faces(faces, len(vertices))
    projected, _basis = camera_projection(vertices)
    # Fit and center the actual projected 2D bounds instead of the 3D box.
    span = np.ptp(projected[:, :2], axis=0)
    scale = min((WIDTH - 48) / max(span[0], 1e-9), (HEIGHT - 48) / max(span[1], 1e-9))
    screen = np.c_[WIDTH / 2 + projected[:, 0] * scale,
                   HEIGHT / 2 - projected[:, 1] * scale]
    pixels = np.full((HEIGHT, WIDTH, 3), [232, 240, 244], dtype=np.uint8)
    depth = np.full((HEIGHT, WIDTH), -np.inf)
    light = np.array([-0.3, -0.4, 0.8660254])
    light /= np.linalg.norm(light)
    for face in faces:
        a, b, c = screen[face]
        lo = np.maximum(np.floor(np.min([a, b, c], axis=0)).astype(int), [0, 0])
        hi = np.minimum(np.ceil(np.max([a, b, c], axis=0)).astype(int), [WIDTH - 1, HEIGHT - 1])
        if (hi < lo).any():
            continue
        denom = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1])
        if abs(denom) < 1e-10:
            continue
        xx, yy = np.meshgrid(np.arange(lo[0], hi[0] + 1) + 0.5, np.arange(lo[1], hi[1] + 1) + 0.5)
        w0 = ((b[1] - c[1]) * (xx - c[0]) + (c[0] - b[0]) * (yy - c[1])) / denom
        w1 = ((c[1] - a[1]) * (xx - c[0]) + (a[0] - c[0]) * (yy - c[1])) / denom
        w2 = 1 - w0 - w1
        z = w0 * projected[face[0], 2] + w1 * projected[face[1], 2] + w2 * projected[face[2], 2]
        region = np.s_[lo[1]:hi[1] + 1, lo[0]:hi[0] + 1]
        visible = (w0 >= -1e-9) & (w1 >= -1e-9) & (w2 >= -1e-9) & (z > depth[region])
        normal = np.cross(vertices[face[1]] - vertices[face[0]], vertices[face[2]] - vertices[face[0]])
        normal /= max(np.linalg.norm(normal), 1e-12)
        if normal[2] < 0:
            normal = -normal
        shade = 0.35 + 0.65 * max(0, float(normal @ light))
        # Gouraud texture sampling retains imagery color, with measured slope light.
        rgb = (w0[..., None] * mesh["colors"][face[0]]
               + w1[..., None] * mesh["colors"][face[1]] + w2[..., None] * mesh["colors"][face[2]])
        pixels[region][visible] = np.clip(rgb[visible] * shade, 0, 255).astype(np.uint8)
        depth[region][visible] = z[visible]
    if not np.isfinite(depth).any():
        raise ValueError("preview_has_no_visible_geometry")
    write_png(path, pixels)
    occupied_y, occupied_x = np.nonzero(np.isfinite(depth))
    return {"visible_pixels": int(np.isfinite(depth).sum()), "camera": CAMERA.copy(),
            "projected_bounds_px": [float(screen[:,0].min()),float(screen[:,1].min()),
                                     float(screen[:,0].max()),float(screen[:,1].max())],
            "visible_bounds_px": [int(occupied_x.min()),int(occupied_y.min()),
                                  int(occupied_x.max()),int(occupied_y.max())]}


def write_png(path, rgb):
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    h, w, channels = rgb.shape
    if channels != 3 or w != WIDTH or h != HEIGHT:
        raise ValueError("fixed_preview_size_required")
    # The IHDR below always declares 8-bit samples: refuse any other dtype before encoding
    # or opening the target (no implicit scaling, narrowing or reinterpretation).
    dtype = getattr(rgb, "dtype", None)
    if getattr(dtype, "kind", None) != "u" or getattr(dtype, "itemsize", None) != 1:
        raise ValueError("fixed_preview_uint8_required")
    data = b"".join(b"\0" + row.tobytes() for row in rgb)
    encoded = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
               + chunk(b"IDAT", zlib.compress(data, 6)) + chunk(b"IEND", b""))
    Path(path).write_bytes(encoded)
