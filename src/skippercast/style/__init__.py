"""Verified nearshore style snapshots for checkout-based render tools.

``load()`` returns the whole token file (generators, QA). Render code takes a group view:
``load().view('baked')`` is a read-only mapping that raises ``StyleGroupError`` on any key
path outside the named groups of ``style/groups.json``, so a stage cannot read a value that
its generation key (the group digest) does not cover.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
from math import exp, log
from pathlib import Path
from types import MappingProxyType
from typing import Any
import json
import re

_STYLE_DIR = Path(__file__).resolve().parents[3] / "style"
GROUPS = ("baked", "contours", "habitat", "paint")


class StyleGroupError(LookupError):
    """A key path outside a view's groups. Not a KeyError, so ``Mapping.get`` cannot hide it."""


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


def _leaf_groups(tokens, rules):
    """Every leaf path (tuple) -> its group; the longest matching dotted prefix wins."""
    for group in rules.values():
        if group not in (*GROUPS, "meta"):
            raise ValueError(f"unknown style group: {group}")
    leaves = {}

    def walk(value, path, group):
        group = rules.get(".".join(path), group)
        if isinstance(value, dict) and value:
            for key, item in value.items():
                walk(item, (*path, key), group)
        elif group is None:
            raise ValueError(f"unassigned style key: {'.'.join(path)}")
        else:
            leaves[path] = group

    walk(tokens, (), None)
    return leaves


def _group_digests(tokens, leaves):
    """The canonical group subsets that ``scripts/style/gen_style.py`` hashes into index.json."""
    subsets = {group: {} for group in GROUPS}
    for path, group in leaves.items():
        if group in subsets:
            value = tokens
            for key in path:
                value = value[key]
            target = subsets[group]
            for key in path[:-1]:
                target = target.setdefault(key, {})
            target[path[-1]] = value
    return {group: sha256(json.dumps(subset, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False, allow_nan=False).encode()).hexdigest()
            for group, subset in subsets.items()}


def _below_map(leaves):
    """Every node path -> the groups of the leaves at or under it."""
    below = {(): set()}
    for path, group in leaves.items():
        for depth in range(len(path) + 1):
            below.setdefault(path[:depth], set()).add(group)
    return MappingProxyType({path: frozenset(groups) for path, groups in below.items()})


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


class _Helpers(Mapping):
    """Token helpers shared by a full ``Style`` and a ``StyleView``.

    On a view every lookup goes through the view, so a helper that needs a key outside the
    view's groups raises ``StyleGroupError`` instead of silently widening a stage's inputs.
    """

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
        """The kit reference's choice: the pier tier only in the pier view (on fine enough
        cells); otherwise the finest other tier that this zoom and native cell size allow."""
        tiers = self["contours"]["tiers"]
        pier_name = self["pier_view"]["contours_tier"]
        if view == "pier":
            pier = next(tier for tier in tiers if tier["name"] == pier_name)
            if cell_m <= pier["max_cell_m"]:
                return pier
        return max((tier for tier in tiers if tier["name"] != pier_name
                    and tier["min_zoom"] <= zoom and cell_m <= tier["max_cell_m"]),
                   key=lambda tier: tier["min_zoom"], default=tiers[0])

    def features_for(self, cell_m):
        rows = self["resolution_tiers"]["features_by_cell_m"]
        return _tier_value(sorted((float(size), features) for size, features in rows.items()), cell_m)

    def native_max_zoom(self, cell_m):
        return _tier_value(self["resolution_tiers"]["native_max_zoom_by_cell_m"], cell_m)

    zinterp = staticmethod(zinterp)


class StyleView(_Helpers):
    """Read-only token subtree restricted to a set of groups.

    A key is visible when a leaf at or below it is in an allowed group. Reading any other
    key path raises ``StyleGroupError``; iteration and ``in`` show only visible keys.
    """

    __slots__ = ("version", "groups", "_digests", "_node", "_path", "_below")

    def __init__(self, version, groups, digests, node, path, below):
        self.version = version
        self.groups = groups
        self._digests = digests
        self._node = node
        self._path = path
        self._below = below

    def _visible(self, path):
        return not self._below[path].isdisjoint(self.groups)

    def __getitem__(self, key):
        value = self._node[key]
        path = (*self._path, key)
        if not self._visible(path):
            raise StyleGroupError(f"{'.'.join(path)} is outside style group(s) {sorted(self.groups)}")
        if isinstance(value, Mapping) and value:
            return StyleView(self.version, self.groups, self._digests, value, path, self._below)
        return value

    def __contains__(self, key):
        return key in self._node and self._visible((*self._path, key))

    def __iter__(self):
        return (key for key in self._node if self._visible((*self._path, key)))

    def __len__(self):
        return sum(1 for _ in self)

    def __repr__(self):
        return f"StyleView({self.version!r}, {sorted(self.groups)}, {'.'.join(self._path) or '<root>'})"

    def digest(self, group):
        """The digest of one of this view's groups (what a stage hashes as its style input)."""
        if group not in self.groups:
            raise StyleGroupError(f"{group} is outside style group(s) {sorted(self.groups)}")
        return self._digests[group]


@dataclass(frozen=True, eq=False)
class Style(_Helpers):
    version: str
    _tokens: Mapping
    _digests: Mapping
    _below: Mapping

    def __getitem__(self, key):
        return self._tokens[key]

    def __iter__(self):
        return iter(self._tokens)

    def __len__(self):
        return len(self._tokens)

    def digest(self, group):
        return self._digests[group]

    def view(self, *groups):
        """A read-only mapping of only these groups' keys (``StyleGroupError`` outside them)."""
        if not groups or any(group not in GROUPS for group in groups):
            raise ValueError(f"a style view needs one or more of {list(GROUPS)}, got {list(groups)}")
        return StyleView(self.version, frozenset(groups), self._digests, self._tokens, (), self._below)


def load(version=None, root=None):
    """Read the named (or indexed default) style after verifying its raw bytes and that
    ``groups.json`` still yields the index's group digests.

    ``root`` is an alternative style directory (tests); the default is the checkout's ``style/``.
    """
    directory = _STYLE_DIR if root is None else Path(root)
    index = _read_index(directory)
    version = index["default"] if version is None else version
    entry = index["versions"][version]
    if entry.get("legacy"):
        raise ValueError(f"{version}: legacy style; use the legacy builder")
    tokens = _verified_tokens(directory, version, entry)
    leaves = _leaf_groups(tokens, json.loads((directory / "groups.json").read_bytes()))
    if _group_digests(tokens, leaves) != dict(entry["digests"]):
        raise ValueError(f"{version}: groups.json disagrees with the index digests "
                         "(regenerate with scripts/style/gen_style.py)")
    return Style(version, _freeze(tokens), _freeze(entry["digests"]), _below_map(leaves))


_LAYER_REF = re.compile(r"(base|stacking):([A-Za-z0-9_.-]+)")


def _resolve_layer_refs(value, roots, hops=0):
    if isinstance(value, dict):
        return {key: _resolve_layer_refs(item, roots, hops) for key, item in value.items()}
    if isinstance(value, list):
        return [_resolve_layer_refs(item, roots, hops) for item in value]
    if not isinstance(value, str) or not (match := _LAYER_REF.fullmatch(value)):
        return value
    if hops == 8:
        raise ValueError(f"layer reference depth exceeds 8: {value}")
    target = roots[match[1]]
    try:
        for key in match[2].split("."):
            if isinstance(target, list):
                if not key.isascii() or not key.isdecimal():
                    raise ValueError(key)
                target = target[int(key)]
            else:
                target = target[key]
    except (KeyError, IndexError, TypeError, ValueError):
        raise ValueError(f"unresolvable layer reference: {value}") from None
    return _resolve_layer_refs(target, roots, hops + 1)


def load_layers(version=None, root=None):
    """Load immutable all-layers tokens (including `stacking`) from a style directory."""
    directory = _STYLE_DIR if root is None else Path(root)
    index = _read_index(directory)
    version = index["layers_default"] if version is None else version
    entry = index["layers"][version]
    tokens = _verified_tokens(directory, version, entry)
    stacking = _verified_tokens(directory, entry["stacking_file"], {
        "file": entry["stacking_file"], "sha256": entry["stacking_sha256"],
    })
    base_version = entry["base"]
    base = _verified_tokens(directory, base_version, index["versions"][base_version])
    # Kit files carry the release number, while index IDs include the product prefix.
    if tokens["base_tokens"]["version"] != base["version"] or base_version != f"nearshore-v{base['version']}":
        raise ValueError(f"{version}: base_tokens.version does not match pinned base {base_version}")
    return _freeze(_resolve_layer_refs({**tokens, "stacking": stacking}, {"base": base, "stacking": stacking}))


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
