"""Nearshore house-style render engine (kit v1.0.0 decisions 1A/2A/3A): the baked relief raster.

A pure function of one grid window: elevation in metres (positive up, NaN = no data) on square
cells of a projected metric CRS, the cell size, the window bounds and a ``view('baked')`` of the
selected style. Every style value is read through that view, so the ``baked`` group digest is
the complete style input of a render. No substrate input exists in this engine (public products
only): every pile's ``basis`` is ``relief``. Style guide sections 3-5 define the order:

1. no data keeps a mask and is nearest-filled for derivatives only;
2. water is elevation < 0, depth in feet;
3. depth ramp (linear sRGB);
4. shade = hillshade hs6 (cell-size VE), high-pass, slope, sky-view and cast shadow;
5. (bottom-type tint: substrate only, not in this engine);
6. rock-pile tint, at overview strength below ``rock_piles.closeup_min_zoom``;
7. land paint; 8. no-data repaint.

Kernels are in metres, converted with ``round(m / cell)``. Thresholds are absolute: no
percentile or per-window statistic, so chunks rendered with a ``shading.tile_buffer_m`` buffer
and cropped agree with a whole-grid render.
"""

import math

import numpy as np
from scipy import ndimage
from scipy.signal import fftconvolve

from skippercast.style import StyleView

# Bump in the same PR as any change of rendered pixels (engine goldens are pinned per epoch).
ENGINE_EPOCH = 1

FT_PER_M = 3.28084  # unit conversion (international foot), as the kit
_TOLERANCE = 1e-9  # float slack on cell-size gates, as the kit
_CONTOUR_LAND_FT = -3.0  # land depth before contour smoothing (kit reference plumbing, not a token)
ZOOM_CLASSES = ("overview", "closeup")


def _require_view(view, groups, what):
    if not isinstance(view, StyleView) or view.groups != frozenset(groups):
        raise TypeError(f"{what} needs a style view of exactly {sorted(groups)}, got {view!r}")


def _rgb(hex_colour):
    """A '#RRGGBB' token as float sRGB in [0, 1]."""
    return np.frombuffer(bytes.fromhex(hex_colour[1:]), np.uint8) / np.float64(np.iinfo(np.uint8).max)


def _cells(metres, cell_m, minimum=1, odd=False):
    count = max(minimum, int(round(metres / cell_m)))
    return count | 1 if odd else count


def _distance_m(mask, cell_m):
    """Metres from each cell to the nearest True cell; infinite when there is none."""
    if not mask.any():
        return np.full(mask.shape, np.inf)
    return ndimage.distance_transform_edt(~mask) * cell_m


def _hillshade(z, cell_m, ve, lights, altitude_deg):
    dy, dx = np.gradient(z * ve, -cell_m, cell_m)
    normal = np.stack([-dx, -dy, np.ones_like(z)], -1)
    normal /= np.linalg.norm(normal, axis=-1, keepdims=True)
    out = np.zeros_like(z)
    h = math.radians(altitude_deg)
    for azimuth, weight in lights:
        a = math.radians(90 - azimuth)
        light = np.array([math.cos(a) * math.cos(h), math.sin(a) * math.cos(h), math.sin(h)])
        out += weight * np.clip(normal @ light, 0, 1)
    return out / sum(weight for _, weight in lights)


def _ring(inner, outer):
    y, x = np.mgrid[-outer:outer + 1, -outer:outer + 1]
    d = np.hypot(x, y)
    kernel = ((d >= inner) & (d <= outer)).astype(np.float64)
    return kernel / kernel.sum()


def _bpi(z, inner, outer):
    padded = np.pad(z, outer, mode="reflect")
    return z - fftconvolve(padded, _ring(inner, outer), mode="same")[outer:-outer, outer:-outer]


def _vrm(z, cell_m, window):
    dy, dx = np.gradient(z, cell_m, cell_m)
    slope = np.arctan(np.hypot(dx, dy))
    aspect = np.arctan2(dy, dx)

    def mean(q):
        return ndimage.uniform_filter(q, window, mode="nearest")

    return 1 - np.sqrt(mean(np.sin(slope) * np.cos(aspect)) ** 2
                       + mean(np.sin(slope) * np.sin(aspect)) ** 2 + mean(np.cos(slope)) ** 2)


def _sky_view(z, cell_m, radius, ve, directions):
    rows, cols = z.shape
    zz = z * ve
    padded = np.pad(zz, radius, mode="edge")
    out = np.zeros_like(z)
    for k in range(directions):
        theta = math.tau * k / directions
        horizon = np.full(z.shape, -np.inf)
        for r in range(1, radius + 1):
            oy, ox = int(round(-r * math.sin(theta))), int(round(r * math.cos(theta)))
            shifted = padded[radius + oy:radius + oy + rows, radius + ox:radius + ox + cols]
            horizon = np.maximum(horizon, np.arctan((shifted - zz) / (r * cell_m)))
        out += (1 - np.sin(np.clip(horizon, 0, None))) / directions
    return out


def _cast_shadow(z, cell_m, azimuth_deg, altitude_deg, ve, steps):
    rows, cols = z.shape
    zz = z * ve
    pad = steps + 1
    padded = np.pad(zz, pad, mode="edge")
    shadow = np.zeros(z.shape, bool)
    rise = math.tan(math.radians(altitude_deg))
    az = math.radians(azimuth_deg)
    for r in range(1, steps + 1):
        oc, orow = int(round(math.sin(az) * r)), int(round(-math.cos(az) * r))
        shadow |= (padded[pad + orow:pad + orow + rows, pad + oc:pad + oc + cols] - zz) > r * cell_m * rise
    return shadow


def to_bytes(rgb):
    """Float sRGB in [0, 1] -> uint8, rounding half up (the kit's PNG quantisation)."""
    top = np.iinfo(np.uint8).max
    return (np.clip(rgb, 0, 1) * top + 0.5).astype(np.uint8)


class Nearshore:
    """All derived layers of one grid window, computed from a ``view('baked')`` only."""

    def __init__(self, elevation, cell_m, bounds, baked):
        _require_view(baked, ("baked",), "the nearshore engine")
        z = np.array(elevation, dtype=np.float64)
        if z.ndim != 2 or min(z.shape) < 1:
            raise ValueError("elevation must be a non-empty 2-D grid")
        cell_m = float(cell_m)
        if not math.isfinite(cell_m) or cell_m <= 0:
            raise ValueError("cell_m must be a positive number of metres")
        west, south, east, north = (float(v) for v in bounds)
        if not (math.isclose((east - west) / cell_m, z.shape[1], abs_tol=_TOLERANCE * z.shape[1] + _TOLERANCE)
                and math.isclose((north - south) / cell_m, z.shape[0], abs_tol=_TOLERANCE * z.shape[0] + _TOLERANCE)):
            raise ValueError("bounds do not match the grid shape and square cell size")
        self.style = baked
        self.cell_m = cell_m
        self.bounds = (west, south, east, north)
        self.nodata = ~np.isfinite(z)
        if self.nodata.all():
            raise ValueError("elevation has no valid cells")
        # Step 1: nearest valid value, for derivatives only (repainted at the end).
        index = ndimage.distance_transform_edt(self.nodata, return_distances=False, return_indices=True)
        self.filled = z[tuple(index)]
        # Step 2.
        self.water = (self.filled < 0) & ~self.nodata
        self.land = (self.filled >= 0) & ~self.nodata
        self.depth_ft = np.where(self.water, -self.filled * FT_PER_M, 0.0)
        self.ve = baked.ve_for(cell_m)
        self.x = west + (np.arange(z.shape[1]) + 0.5) * cell_m
        self.y = north - (np.arange(z.shape[0]) + 0.5) * cell_m
        self._shade = self._piles = self._land_shade = None

    # ------------------------------------------------------------------ step 4: shade
    def shade(self):
        if self._shade is None:
            s, z, cell = self.style["shading"], self.filled, self.cell_m
            hs = s["hillshade"]
            hs6 = _hillshade(z, cell, self.ve, hs["lights"], hs["altitude_deg"])
            fine = hs6 - ndimage.gaussian_filter(hs6, s["hp_sigma_m"] / cell, mode="nearest")
            dy, dx = np.gradient(z, cell, cell)
            slope = np.degrees(np.arctan(np.hypot(dx, dy)))
            sv = s["sky_view"]
            svf = _sky_view(z, cell, _cells(sv["radius_m"], cell), sv["ve"], sv["directions"])
            svf_norm = np.clip((svf - sv["norm_floor"]) / (1 - sv["norm_floor"]), 0, 1)
            cs = s["cast_shadow"]
            shadow = _cast_shadow(z, cell, cs["azimuth_deg"], cs["altitude_deg"], cs["ve"], _cells(cs["search_m"], cell))
            shade = (s["base"] + s["gain"] * (hs6 - hs["flat_reference"])
                     + s["hp_gain"] * np.clip(fine, -s["hp_clip"], s["hp_clip"]))
            shade = shade * (1 - s["slope_gain"] * np.clip(slope / s["slope_full_deg"], 0, 1))
            shade = shade * (s["ao_base"] + s["ao_gain"] * svf_norm)
            self._shade = shade * np.where(shadow, cs["factor"], 1.0)
        return self._shade

    def depth_rgb(self):
        """Step 3: the depth ramp, linear in sRGB, clamped beyond the end stops."""
        stops = self.style["depth_ramp"]["stops_ft"]
        depths = np.array([depth for depth, _ in stops], np.float64)
        colours = np.array([_rgb(colour) for _, colour in stops])
        return np.stack([np.interp(self.depth_ft, depths, colours[:, k]) for k in range(colours.shape[1])], -1)

    # ------------------------------------------------------------------ derived layers
    def bpi(self):
        """Fine BPI: elevation minus the annulus mean, land set to the token height first."""
        b = self.style["derived"]["bpi_fine"]
        z = np.where(self.land, b["land_elevation_set_to"], self.filled)
        return _bpi(z, _cells(b["inner_m"], self.cell_m, b["min_inner_cells"]), _cells(b["outer_m"], self.cell_m))

    def vrm(self):
        v = self.style["derived"]["vrm"]
        return _vrm(self.filled, self.cell_m, _cells(v["window_m"], self.cell_m, v["min_cells"], v["odd"]))

    def piles_enabled(self):
        """Coarse rule: no piles on cells over ``rock_piles.max_cell_m`` or without the feature."""
        p = self.style["derived"]["rock_piles"]
        return (self.cell_m <= p["max_cell_m"] + _TOLERANCE
                and "rock_piles" in self.style.features_for(self.cell_m))

    def piles(self):
        """(mask, piles): kept 4-connected candidate components and their peak points."""
        if self._piles is None:
            self._piles = self._detect()
        return self._piles

    def _detect(self):
        empty = np.zeros(self.filled.shape, bool)
        if not self.piles_enabled():
            return empty, []
        p, cell = self.style["derived"]["rock_piles"], self.cell_m
        bpi = self.bpi()
        hard = self.vrm() > self.style.vrm_hard_min(cell)  # no substrate: hard from relief only
        zone = (self.water & (_distance_m(self.land, cell) > p["min_dist_from_land_m"])
                & (_distance_m(self.nodata, cell) > p["min_dist_from_nodata_m"]))
        candidates = (bpi > p["bpi_min_m"]) & zone & hard
        labels, count = ndimage.label(candidates)
        if count == 0:
            return empty, []
        ids = np.arange(1, count + 1)
        area = ndimage.sum(candidates, labels, ids) * cell ** 2
        peak = ndimage.maximum(bpi, labels, ids)
        where = ndimage.maximum_position(bpi, labels, ids)
        keep = np.zeros(count + 1, bool)
        keep[1:] = (area >= p["min_area_m2"]) & (peak >= p["min_peak_m"])
        piles = []
        for (row, col), height, size, kept in zip(where, peak, area, keep[1:]):
            if kept:
                piles.append({"id": len(piles) + 1, "row": int(row), "col": int(col),
                              "x": float(self.x[col]), "y": float(self.y[row]),
                              "height_m": float(height), "height_ft": float(height * FT_PER_M),
                              "area_m2": float(size), "depth_ft": float(self.depth_ft[row, col]),
                              "basis": "relief"})
        return keep[labels], piles

    # ------------------------------------------------------------------ steps 6-8
    def zoom_class(self, zoom):
        return ZOOM_CLASSES[zoom >= self.style["rock_piles"]["closeup_min_zoom"]]

    def base(self, zoom_class, mask=None):
        """The baked relief (float sRGB, 1 px per cell) for ``'closeup'`` or ``'overview'``."""
        if zoom_class not in ZOOM_CLASSES:
            raise ValueError(f"zoom_class must be one of {ZOOM_CLASSES}")
        r = self.style["rock_piles"]
        shade = self.shade()
        under = self.depth_rgb() * shade[..., None]
        if mask is None:
            mask = self.piles()[0]
        full = under.copy()
        k = r["fill_mix"]
        full[mask] = (1 - k) * under[mask] + k * _rgb(r["fill"]) * shade[mask, None]
        if zoom_class == "overview":
            s = r["overview_strength"]
            full = (1 - s) * under + s * full
        return self._finish(full)

    def base_nopiles(self, zoom_class):
        return self.base(zoom_class, np.zeros(self.filled.shape, bool))

    def _finish(self, rgb):
        surface = self.style["surface"]
        land = surface["land"]
        if self._land_shade is None:
            self._land_shade = _hillshade(self.filled, self.cell_m, land["ve"], [(land["light_azimuth_deg"], 1)],
                                          land["light_altitude_deg"])
        hs1 = self._land_shade
        rgb = rgb.copy()
        rgb[self.land] = np.clip(_rgb(land["color"]) * (land["shade_base"] + land["shade_gain"] * hs1[self.land, None]), 0, 1)
        rgb[self.nodata] = _rgb(surface["no_data"]["color"])
        return np.clip(rgb, 0, 1)

    # ------------------------------------------------------------------ products
    def metrics(self):
        mask, piles = self.piles()
        depth = self.depth_ft[self.water]
        return {"cell_m": self.cell_m, "shape": list(self.filled.shape), "bounds": list(self.bounds),
                "ve": self.ve, "valid_frac": float((~self.nodata).mean()), "water_frac": float(self.water.mean()),
                "depth_ft_range": [float(depth.min()), float(depth.max())] if depth.size else None,
                "piles": len(piles), "piles_relief": len(piles), "pile_area_frac": float(mask.mean())}

    def contour_depth(self, contours, zoom, view=None):
        """(tier, depth_ft): Gaussian-smoothed depth of the contour tier for this zoom and view,
        NaN outside water or valid data. ``contours`` is a ``view('contours')``."""
        _require_view(contours, ("contours",), "contour smoothing")
        tier = contours.contour_tier(zoom, self.cell_m, view)
        smooth = ndimage.gaussian_filter(np.where(self.water, self.depth_ft, _CONTOUR_LAND_FT),
                                         tier["sigma_m"] / self.cell_m)
        smooth[~self.water | self.nodata] = np.nan
        return tier, smooth


def pile_labels(piles, habitat, cell_m, window=None, margins_m=(0, 0, 0, 0)):
    """Labelled piles: tallest first, ``nms_m`` suppression, at most ``max_per_view``.

    ``habitat`` is a ``view('baked', 'habitat')``. ``window`` (west, south, east, north) limits
    the piles considered; ``margins_m`` (left, bottom, right, top) keeps labels off its edges.
    Labels exist only on cells up to ``rock_piles.label.max_cell_m``.
    """
    _require_view(habitat, ("baked", "habitat"), "pile labels")
    rule = habitat["rock_piles"]["label"]
    if cell_m > rule["max_cell_m"] + _TOLERANCE:
        return []
    if window is not None:
        x0, y0, x1, y1 = window
        piles = [p for p in piles if x0 <= p["x"] < x1 and y0 <= p["y"] < y1]
    ranked = sorted((p for p in piles if p["height_m"] >= rule["min_peak_m"]), key=lambda p: -p["height_m"])
    kept = []
    for pile in ranked:
        if all((pile["x"] - q["x"]) ** 2 + (pile["y"] - q["y"]) ** 2 > rule["nms_m"] ** 2 for q in kept):
            kept.append(pile)
    if window is not None:
        left, bottom, right, top = margins_m
        kept = [p for p in kept if x0 + left < p["x"] < x1 - right and y0 + bottom < p["y"] < y1 - top]
    return kept[:rule["max_per_view"]]
