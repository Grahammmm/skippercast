#!/usr/bin/env python3
"""Generate the checkout's nearshore CSS, web data and 3D palette."""

import argparse
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.dont_write_bytecode = True  # --check must also work in a pristine checkout without writes.
sys.path.insert(0, str(ROOT / "src"))
from skippercast.style import _read_index, _verified_tokens

SCRIPT = "scripts/style/gen_style.py"
GROUPS = ("baked", "contours", "habitat", "paint")
HEX = re.compile(r"#[\da-fA-F]{6}")
# A look is what a region's relief tiles were baked with: its key is the baked group digest (two versions with the
# same baked digest draw identical relief), or the version id for a legacy look that has no token file. The legend
# reads its depth chips by the relief pointer's look key, so every version a live pointer may name keeps its chips.
LOOK_STATUSES = ("active", "rolling")
LEGEND_MAX_FT = 300  # MAP-DESIGN-LOCK § 1.2: depth chips run to the 300 ft shelf limit, then one "300+" chip
LEGACY_CHIP_FEET = {"deep-fixed-v1": (0, 10, 20, 33, 50, 66, 100, 150, 200, 300)}  # ramp B: --depth-b-<n>, then 300+
LEGACY_LOOK = "deep-fixed-v1"  # what a pointer without a `style` member was baked with
DIGEST = re.compile(r"[a-f0-9]{64}")
VERSION_ID = re.compile(r"[a-z0-9.-]{1,64}")


def group_digests(tokens, rules):
    subsets = {group: {} for group in (*GROUPS, "meta")}
    for group in rules.values():
        if group not in subsets:
            raise ValueError(f"unknown style group: {group}")

    def assign(value, path=(), group=None):
        name = ".".join(path)
        group = rules.get(name, group)
        if isinstance(value, dict) and value:
            for key, item in value.items():
                assign(item, (*path, key), group)
        else:
            if group is None:
                raise ValueError(f"unassigned style key: {name}")
            target = subsets[group]
            for key in path[:-1]:
                target = target.setdefault(key, {})
            target[path[-1]] = value

    assign(tokens)
    return {group: sha256(json.dumps(subsets[group], sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False, allow_nan=False).encode()).hexdigest()
            for group in GROUPS}


def pretty(value):
    return json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False)


def get(data, path):
    for key in path.split("."):
        data = data[key]
    return data


def projections(tokens, version, digests, looks):
    colours = {}

    def colour(name, value):
        if name in colours or not re.fullmatch(r"[a-z][a-z\d-]*", name) or not HEX.fullmatch(value):
            raise ValueError(f"invalid or duplicate colour token: {name}")
        css_var = f"--skn-{name}"
        colours[name] = value
        return css_var

    ramp = tokens["depth_ramp"]
    stops = ramp["stops_ft"]
    depth_vars = [colour(f"{ramp['id_prefix']}{i}", value) for i, (_, value) in enumerate(stops)]
    shared_colour_paths = {
        "surface.land.color": get(tokens, "surface.land.token"),
        "surface.no_data.color": get(tokens, "surface.no_data.token"),
        "contours.ink": get(tokens, "contours.token_minor"),
        "rock_piles.fill": get(tokens, "rock_piles.token_fill"),
        "rock_piles.outline": get(tokens, "rock_piles.token_outline"),
        "bottom_type.hard_edge.color": get(tokens, "bottom_type.hard_edge.token"),
        "pier_view.pier.fill": get(tokens, "pier_view.pier.token_fill"),
        "pier_view.pier.casing": get(tokens, "pier_view.pier.token_casing"),
        "pier_view.cast_arcs.color": get(tokens, "pier_view.cast_arcs.token"),
        "pier_view.cast_arcs.halo": f"{get(tokens, 'pier_view.cast_arcs.token')}-halo",
        "pier_view.cast_arcs.label.color": get(tokens, "pier_view.cast_arcs.label.token"),
        "typography.ink": get(tokens, "typography.token_ink"),
        "typography.halo": get(tokens, "typography.token_halo"),
    }
    for key, item in tokens["bottom_type"]["subtle"].items():
        if isinstance(item, dict):
            shared_colour_paths[f"bottom_type.subtle.{key}.color"] = item["token"]
    for key, value in tokens["bottom_type"]["detailed_toggle"].items():
        if HEX.fullmatch(value):
            shared_colour_paths[f"bottom_type.detailed_toggle.{key}"] = f"bottom-type-detail-{key}"

    web = deepcopy({key: tokens[key] for key in (
        "contours", "rock_piles", "bottom_type", "pier_view", "overlays", "resolution_tiers", "typography",
    )})
    for path, name in shared_colour_paths.items():
        var = colour(name, get(tokens, path))
        parent, key = path.rsplit(".", 1)
        if parent.split(".")[0] in web:
            get(web, parent)[key] = var
    web["contours"]["index_ink"] = colour(get(tokens, "contours.token_index"), get(tokens, "contours.ink"))
    web["rock_piles"]["label"]["ink"] = colour(get(tokens, "rock_piles.label.token"), get(tokens, "typography.ink"))
    arc_label = web["pier_view"]["cast_arcs"]["label"]
    if get(tokens, "typography.arc_label.color") != get(tokens, "pier_view.cast_arcs.label.color"):
        raise ValueError("arc label colours disagree")
    web["typography"]["arc_label"]["color"] = arc_label["color"]
    web["depth_stops_ft"] = [depth for depth, _ in stops]
    web["depth_stop_vars"] = depth_vars
    web["surface_vars"] = {key: f"--skn-{value['token']}" for key, value in tokens["surface"].items()
                           if isinstance(value, dict)}
    literals = re.search(r'"#[\da-fA-F]{3,8}"', pretty(web))
    if literals:
        raise ValueError("web projection contains an unmapped colour")

    web_looks, look_colours, coast_looks = looks
    if web_looks[digests["baked"]]["chips"][0]["cssVar"] != depth_vars[0]:
        raise ValueError("the default look must use the default depth colours")
    header = f"{version} generated by {SCRIPT}; do not edit"
    css = (f"  /* skn:begin {header} */\n"
           + "".join(f"  --skn-{name}: {value};\n" for name, value in {**colours, **look_colours}.items())
           + "  /* skn:end */\n")
    ts = (f"// {header}\n"
          f"export const NEARSHORE_STYLE_VERSION = {json.dumps(version)};\n"
          f"export const NEARSHORE_STYLE_DIGESTS = {pretty(digests)} as const;\n"
          f"export const NEARSHORE_STYLE = {pretty(web)} as const;\n"
          f"/** Legend depth chips by look key (baked digest, or a legacy version id); every active or rolling version. */\n"
          f"export const NEARSHORE_LOOKS = {pretty(web_looks)} as const;\n")
    coast = (f"// skn:begin {header}\nexport const NEARSHORE_COAST_PALETTE = {{\n"
             "  depthStopsFt: [\n"
             + "".join(f"    {json.dumps(stop)},\n" for stop in stops)
             + f"  ],\n  contour: {json.dumps(get(tokens, 'contours.ink'))},\n"
             f"  noData: {json.dumps(get(tokens, 'surface.no_data.color'))},\n"
             "} as const;\n"
             f"export const NEARSHORE_COAST_LOOKS = {{\n"
             + ",\n".join(f"  {json.dumps(key)}: {json.dumps(look, ensure_ascii=False)}" for key, look in coast_looks.items())
             + "\n} as const;\n"
             "// skn:end\n")
    return css, ts, coast


def look_table(index, tokens_by_version):
    """Web chips, extra CSS colours and 3D ramps for every active or rolling look, keyed by look key."""
    default = index["versions"][index["default"]]
    if default.get("status") not in LOOK_STATUSES:
        raise ValueError(f"default version {index['default']} is not active or rolling")
    web, colours, coast = {}, {}, {}
    for version, entry in index["versions"].items():
        if entry.get("status") not in LOOK_STATUSES:
            continue
        if entry.get("legacy"):
            if version not in LEGACY_CHIP_FEET:
                raise ValueError(f"{version}: legacy look without legend chips")
            feet = LEGACY_CHIP_FEET[version]
            web[version] = {"legacy": True, "versions": [version],
                            "chips": [{"depth_ft": depth, "cssVar": f"--depth-b-{i}"} for i, depth in enumerate(feet)],
                            "plus300": f"--depth-b-{len(feet)}"}
            coast[version] = {"legacy": True, "versions": [version]}
            continue
        key = entry["digests"]["baked"]
        if key in web:  # a paint-only bump: same baked relief, same chips
            web[key]["versions"].append(version)
            coast[key]["versions"].append(version)
            continue
        tokens = tokens_by_version[version]
        stops = tokens["depth_ramp"]["stops_ft"]
        # The default look keeps the released MSK-1 names; any other look gets its own names while it is live.
        name = (f"{tokens['depth_ramp']['id_prefix']}{{}}" if key == default["digests"]["baked"]
                else f"look-{key[:12]}-depth-{{}}")
        names = [name.format(i) for i in range(len(stops))]
        if key != default["digests"]["baked"]:
            colours.update({n: colour for n, (_, colour) in zip(names, stops)})
        deeper = [n for n, (depth, _) in zip(names, stops) if depth > LEGEND_MAX_FT]
        if not deeper:
            raise ValueError(f"{version}: depth ramp has no stop deeper than {LEGEND_MAX_FT} ft")
        web[key] = {"legacy": False, "versions": [version],
                    "chips": [{"depth_ft": depth, "cssVar": f"--skn-{n}"} for n, (depth, _) in zip(names, stops)
                              if depth <= LEGEND_MAX_FT],
                    "plus300": f"--skn-{deeper[0]}"}
        coast[key] = {"legacy": False, "versions": [version], "depthStopsFt": stops,
                      "contour": get(tokens, "contours.ink"), "noData": get(tokens, "surface.no_data.color")}
    return web, colours, coast


def pointer_look(item):
    """The look key a pointer (or its `previous` lineage entry) was baked with; ValueError if its style is invalid."""
    style = item.get("style")
    if style is None:
        return LEGACY_LOOK
    keys = {"baked", "contours", "habitat", "built_with"}
    if (not isinstance(style, dict) or set(style) != keys
            or not (isinstance(style["baked"], str) and DIGEST.fullmatch(style["baked"]))
            or not all(style[k] is None or isinstance(style[k], str) and DIGEST.fullmatch(style[k])
                       for k in ("contours", "habitat"))
            or not isinstance(style["built_with"], str) or not VERSION_ID.fullmatch(style["built_with"])):
        raise ValueError("invalid style member")
    return style["baked"]


def check_pointers(root, web_looks):
    """A version cannot leave index.json while a pointer, or the lineage it can roll back to, names its look."""
    for path in sorted((root / "catalog/relief").glob("*.json")):
        if path.name.endswith(".schema.json"):
            continue
        pointer = json.loads(path.read_bytes())
        previous = pointer.get("previous")
        for label, item in (("pointer", pointer), ("previous", previous)):
            if label == "previous" and not isinstance(previous, dict):
                continue
            try:
                key = pointer_look(item)
            except ValueError as exc:
                raise ValueError(f"{path.relative_to(root)}: {label} {exc}") from None
            if key not in web_looks:
                raise ValueError(f"{path.relative_to(root)}: {label} look {key} is missing from LOOKS "
                                 "(keep its version active or rolling in style/index.json)")


def without_block(source, start, end):
    """Remove one owned block, preserving all other source text."""
    pattern = rf"(?ms)^{start}[^\n]*\n.*?^{end}\n"
    stripped, count = re.subn(pattern, "", source)
    if count > 1 or "skn:begin" in stripped or "skn:end" in stripped:
        raise ValueError("duplicate or unpaired skn markers")
    return stripped


def generate(root, check):
    directory = root / "style"
    index = _read_index(directory)
    rules = json.loads((directory / "groups.json").read_bytes())
    default = index["default"]
    tokens_by_version = {}
    for version, entry in index["versions"].items():
        if not entry.get("legacy"):
            tokens = _verified_tokens(directory, version, entry)
            tokens_by_version[version] = tokens
            digests = group_digests(tokens, rules)
            if check and entry.get("digests") != digests:
                raise ValueError(f"{version}: index digests disagree (regenerate with {SCRIPT})")
            entry["digests"] = digests

    looks = look_table(index, tokens_by_version)
    check_pointers(root, looks[0])
    css, ts, coast = projections(tokens_by_version[default], default, index["versions"][default]["digests"], looks)
    css_path = root / "web/tokens.css"
    coast_path = root / "packages/coast/src/palette.ts"
    css_source = without_block(css_path.read_bytes().decode(), r"  /\* skn:begin ", r"  /\* skn:end \*/")
    roots = list(re.finditer(r"(?m)^:root \{[^{}]*^\}", css_source))
    if len(roots) != 1:
        raise ValueError("expected a single plain :root block in web/tokens.css")
    insert = roots[0].end() - 1
    coast_source = without_block(coast_path.read_bytes().decode(), "// skn:begin ", "// skn:end")
    outputs = {
        css_path: css_source[:insert] + css + css_source[insert:],
        coast_path: coast_source + coast,
        root / "web/map/nearshore-style.gen.ts": ts,
    }
    if not check:
        outputs[directory / "index.json"] = pretty(index) + "\n"
    drift = []
    for path, text in outputs.items():
        expected = text.encode()
        if not path.exists() or path.read_bytes() != expected:
            drift.append(str(path.relative_to(root)))
            if not check:
                path.write_bytes(expected)
    if check and drift:
        raise ValueError(f"generated file drift: {', '.join(drift)} (regenerate with {SCRIPT})")
    print(f"{default}: {'style tokens and projections match' if check else 'style projections generated'}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="check for drift without writing")
    args = parser.parse_args()
    try:
        generate(ROOT, args.check)
    except (OSError, ValueError, KeyError) as exc:
        print(f"{SCRIPT}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
