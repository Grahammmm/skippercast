"""Verified nearshore style snapshots for checkout-based render tools."""

from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
from math import exp, log
from pathlib import Path
from types import MappingProxyType
from typing import Any
import json

_STYLE_DIR = Path(__file__).resolve().parents[3] / "style"


def _read_index(directory):
    return json.loads((directory / "index.json").read_bytes())


def _verified_tokens(directory, version, entry):
    raw = (directory / entry["file"]).read_bytes()
    actual = sha256(raw).hexdigest()
    if actual != entry["sha256"]:
        raise ValueError(f"{version}: sha256 mismatch (expected {entry['sha256']}, got {actual})")
    return json.loads(raw)


def _freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(map(_freeze, value))
    return value


def _segment(pairs, x):
    """Bracket x in an ascending table, clamping to the end points."""
    first = pairs[0]
    if x <= first[0]:
        return first, first
    for left, right in zip(pairs, pairs[1:]):
        if x <= right[0]:
            return left, right
    return pairs[-1], pairs[-1]


def zinterp(pairs, z):
    """Interpolate ascending (zoom, value) pairs, clamped at both ends."""
    (x0, y0), (x1, y1) = _segment(pairs, z)
    if x0 == x1 or z == x0:
        return y0
    if z == x1:
        return y1
    return y0 + (y1 - y0) * ((z - x0) / (x1 - x0))


def _tier_value(pairs, cell_m):
    # Between rows use the coarser tier; don't promise finer detail.
    return next((value for size, value in pairs if cell_m <= size), pairs[-1][1])


@dataclass(frozen=True, eq=False)
class Style(Mapping):
    version: str
    _tokens: Mapping
    _digests: Mapping

    def __getitem__(self, key):
        return self._tokens[key]

    def __iter__(self):
        return iter(self._tokens)

    def __len__(self):
        return len(self._tokens)

    def digest(self, group):
        return self._digests[group]

    def ve_for(self, cell_m):
        h = self["shading"]["hillshade"]
        ve = h["ve_reference"] * (cell_m / h["ve_reference_cell_m"]) ** h["ve_exponent"]
        return max(h["ve_min"], min(h["ve_max"], ve))

    def vrm_hard_min(self, cell_m):
        pairs = self["derived"]["rock_piles"]["vrm_hard_min_by_cell_m"]
        (x0, y0), (x1, y1) = _segment(pairs, cell_m)
        if x0 == x1 or cell_m == x0:
            return y0
        if cell_m == x1:
            return y1
        return exp(zinterp(((log(x0), log(y0)), (log(x1), log(y1))), log(cell_m)))

    def ramp_rgb(self, depth_ft):
        """Return unrounded sRGB channels on the byte scale."""
        (d0, c0), (d1, c1) = _segment(self["depth_ramp"]["stops_ft"], depth_ft)
        return tuple(zinterp(((d0, a), (d1, b)), depth_ft)
                     for a, b in zip(bytes.fromhex(c0[1:]), bytes.fromhex(c1[1:])))

    def contour_tier(self, zoom, cell_m, view=None):
        tiers = self["contours"]["tiers"]
        pier_name = self["pier_view"]["contours_tier"]
        if view == "pier":
            pier = next(tier for tier in tiers if tier["name"] == pier_name)
            if cell_m <= pier["max_cell_m"]:
                return pier
        return max((tier for tier in tiers if tier["min_zoom"] <= zoom and cell_m <= tier["max_cell_m"]),
                   key=lambda tier: tier["min_zoom"], default=tiers[0])

    def features_for(self, cell_m):
        rows = self["resolution_tiers"]["features_by_cell_m"]
        return _tier_value(sorted((float(size), features) for size, features in rows.items()), cell_m)

    def native_max_zoom(self, cell_m):
        return _tier_value(self["resolution_tiers"]["native_max_zoom_by_cell_m"], cell_m)

    zinterp = staticmethod(zinterp)


def load(version=None):
    """Read the named (or indexed default) style, verifying its raw bytes first."""
    index = _read_index(_STYLE_DIR)
    version = index["default"] if version is None else version
    entry = index["versions"][version]
    if entry.get("legacy"):
        raise ValueError(f"{version}: legacy style; use the legacy builder")
    return Style(version, _freeze(_verified_tokens(_STYLE_DIR, version, entry)), _freeze(entry["digests"]))


def digest(group):
    return load().digest(group)


def ve_for(cell_m):
    return load().ve_for(cell_m)


def vrm_hard_min(cell_m):
    return load().vrm_hard_min(cell_m)


def ramp_rgb(depth_ft):
    return load().ramp_rgb(depth_ft)


def contour_tier(zoom, cell_m, view=None):
    return load().contour_tier(zoom, cell_m, view)


def features_for(cell_m):
    return load().features_for(cell_m)


def native_max_zoom(cell_m):
    return load().native_max_zoom(cell_m)
