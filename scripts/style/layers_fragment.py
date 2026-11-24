"""Project layer tokens into the canonical, non-runtime MapLibre reference fragment."""

# Retained verbatim as part of the owner-approved canonical fragment identity.
NOTE = """Generate ../maplibre-layers-fragment.json from ../layer-tokens.json + ../stacking.json (+ the nearshore base tokens
through base: references). Never edit the fragment by hand. Literals appear here for review only; in web/ every colour
must come from web/tokens.css via web/map/palette.ts. Each layer carries "_token" naming the token path it reads.
Layer order in the array = stacking.json z_order. Colour fields are value textures: the fragment fixes their order,
opacity curve, resampling and the colour ramp (metadata) the texture colouring must use; vector layers are complete.
    python make_maplibre.py"""


def _pick(row, *keys):
    return {key: row[key] for key in keys}


def _zoom(pairs):
    return ["interpolate", ["linear"], ["zoom"], *(v for pair in pairs for v in pair)]


def _step(pairs):
    return ["step", ["zoom"], pairs[0][1], *(v for pair in pairs[1:] for v in pair)]


def _opacity(value):
    return _zoom(value) if isinstance(value, tuple) else value


def _match(field, row):
    return ["match", ["get", field], *(v for item in row["colors"].items() for v in item), row["default_color"]]


def _line(row):
    return {"line-color": row["color"], "line-width": row["width_pt"]}


def _dash(row):
    return [length / row["width_pt"] for length in row["dash"]]


def _raster(opacity, resampling="linear", fade=True):
    paint = {"raster-opacity": _opacity(opacity), "raster-resampling": resampling}
    if fade:
        paint["raster-fade-duration"] = 0
    return paint


def fragment(tokens):
    """Use token values for paint, and stable MapLibre IDs/expressions for structure."""
    stack = tokens["stacking"]
    order = {}
    for row in stack["z_order"]:
        slot = row["id"]
        if slot in order:
            raise ValueError(f"duplicate stacking slot: {slot}")
        order[slot] = row["z"]

    layers = tokens["layers"]
    common = tokens["common"]
    font = [common["font"]] if isinstance(common["font"], str) else common["font"]
    rows = []

    def add(group, layer, suffix, name, kind, source=None, *, paint=None, layout=None, meta=None, **extra):
        row = {"id": f"skl-{name}", "type": kind, **extra}
        if source is not None:
            row.update(source=source, layout={"visibility": "none", **(layout or {})})
        if paint is not None:
            row["paint"] = paint
        row["metadata"] = {f"skippercast:{key}": value for key, value in
                           {**(meta or {}), "z": group, "layer": layer}.items()}
        row["_token"] = f"layers.{layer}.{suffix}"
        rows.append(row)

    def label(layer, suffix, name, source, text, size, paint, *, layout=None, meta=None, **extra):
        add("labels", layer, suffix, name, "symbol", source, paint=paint, meta=meta,
            layout={"text-field": text, "text-font": font, "text-size": size, **(layout or {})}, **extra)

    def ink(colour, halo=None, width=1.3):
        return {"text-color": colour, "text-halo-color": common["halo"] if halo is None else halo,
                "text-halo-width": width}

    def circle(row, colour_key, outline=True):
        paint = {"circle-color": row[colour_key], "circle-radius": row["size_pt"] / 2}
        if outline:
            paint.update({"circle-stroke-color": row["outline"], "circle-stroke-width": row["outline_pt"]})
        return paint

    fields = (
        ("sst-fill", "sst", "", "ramp_stops", ("ramp_stops", "band_step_f_by_zoom", "stretch")),
        ("chlorophyll", "chl", "", "ramp_stops", ("ramp_stops", "domain_mg_m3", "scale", "composite")),
        ("kd490", "kd490", "", "colors", ("bands_ft", "colors", "clip_ft")),
        ("currents", "currents", "fill", "fill", ("ramp_stops", "domain_kt")),
        ("subsurface-temp", "subsurface", "", "ramp_stops", ("ramp_stops", "stretch", "depth_stops_ft", "vertical")),
        ("salinity", "salinity", "", "ramp_stops", ("ramp_stops", "stretch")),
        ("wind", "wind", "fill", "fill.ramp_kt", ("ramp_kt",)),
        ("waves-swell", "waves", "fill", "fill", ("ramp_stops", "domain_ft")),
        ("visibility-fog", "visibility", "", "colors", ("bands_nm", "colors", "hide_at_or_above_nm")),
    )
    for layer, source, section, token, keys in fields:
        row = layers[layer][section] if section else layers[layer]
        ramp = _pick(row, *keys)
        if layer == "sst-fill":
            ramp["rule"] = row["band_colors_rule"]
        add("color-field", layer, token, f"{layer}-fill", "raster", f"{source}-texture",
            paint=_raster(row["opacity"]), meta={"ramp": ramp, "water_only": layer != "wind",
                                                "gaps": tokens["display_sampling"]})

    edge = layers["sst-fill"]["band_edge"]
    add("isolines", "sst-fill", "band_edge", "sst-band-edge", "line", "sst-bands",
        paint={**_line(edge), "line-opacity": edge["opacity"]}, meta=_pick(edge, "hide_when_any_on"))
    add("veils", "clouds", "veil", "clouds-veil", "raster", "goes-c13-texture",
        paint=_raster(stack["opacity_by_zoom"]["cloud_veil"]),
        meta={"veil": layers["clouds"]["veil"], "cap_with_field_or_radar": stack["veil_cap_with_field_or_radar"]})
    ice = layers["sea-ice"]
    add("veils", "sea-ice", "veil", "sea-ice-veil", "raster", "ice-texture",
        paint=_raster(1, fade=False), meta=_pick(ice, "veil"))
    add("isolines", "sea-ice", "edge", "sea-ice-edge", "line", "ice-edge",
        paint=_line(ice["edge"]), meta=_pick(ice["edge"], "level_pct"))
    radar = layers["precip-radar"]
    add("radar", "precip-radar", "bands_dbz", "radar", "raster", "mrms-texture",
        paint=_raster(radar["opacity"], "nearest"), meta=_pick(radar, "bands_dbz", "hide_below_dbz", "animation"))

    breaks = layers["sst-breaks"]
    glow = breaks["glow"]
    add("color-field", "sst-breaks", "glow", "sst-breaks-glow", "raster", "sst-gradient-texture",
        paint=_raster(glow["opacity"], fade=False), meta={"ramp": _pick(glow, "ramp_stops", "domain_f_per_nm", "threshold_f_per_nm")})
    iso = breaks["isolines"]
    iso_colour = _step(iso["color_by_zoom"])
    for kind in ("minor", "index"):
        add("isolines", "sst-breaks", f"isolines.{kind}", f"sst-iso-{kind}", "line", "sst-isolines",
            filter=["==", ["get", "index"], kind == "index"],
            paint={"line-color": iso_colour, "line-width": iso[kind]["width_pt"], "line-opacity": iso[kind]["opacity"]},
            meta={"step_f_by_zoom": iso[f"{kind}_step_f_by_zoom"]})
    iso_label = iso["label"]
    label("sst-breaks", "isolines.label", "sst-iso-label", "sst-isolines",
          ["concat", ["to-string", ["get", "label"]], iso_label["suffix"]], iso_label["size_pt"],
          ink(iso_colour, ["step", ["zoom"], common["ink"], 12, common["halo"]], iso_label["halo_pt"] / 2),
          layout={"symbol-placement": "line"}, filter=["==", ["get", "index"], True])
    ssh = layers["ssh"]
    for sign, op in (("positive", ">"), ("negative", "<"), ("zero", "==")):
        paint = _line(ssh[sign])
        if ssh[sign].get("dash"):
            paint["line-dasharray"] = _dash(ssh[sign])
        add("isolines", "ssh", sign, f"ssh-{sign}", "line", "ssh-isolines",
            filter=[op, ["get", "cm"], 0], paint=paint, meta=_pick(ssh, "step_cm", "range_cm"))
    pressure = layers["pressure"]
    bounds = {"minzoom": pressure["min_zoom"], "maxzoom": pressure["max_zoom"] + 1}
    hpa_mod = ["%", ["get", "hpa"], pressure["bold_every_hpa"]]
    for kind, op in (("minor", "!="), ("bold", "==")):
        add("isolines", "pressure", f"width_pt.{kind}", f"isobar-{kind}", "line", "isobars",
            paint={"line-color": pressure["color"], "line-width": pressure["width_pt"][kind]},
            meta=_pick(pressure, "step_hpa"), filter=[op, hpa_mod, 0], **bounds)
    pl = pressure["label"]
    label("pressure", "label", "isobar-label", "isobars", ["to-string", ["get", "hpa"]], pl["size_pt"],
          ink(pressure["color"], pl["halo"], pl["halo_pt"] / 2), layout={"symbol-placement": "line"},
          filter=["==", hpa_mod, 0], **bounds)
    centers = pressure["centers"]
    label("pressure", "centers", "pressure-centers", "pressure-centers", ["get", "letter"], centers["letter_pt"],
          ink(["match", ["get", "letter"], "H", centers["high"], centers["low"]], width=centers["halo_pt"] / 2), **bounds)

    add("particles", "currents", "streamlines", "currents-streamlines", "custom",
        _custom="streamline layer over the HF-radar u/v texture", meta={"params": layers["currents"]["streamlines"]})
    wind = layers["wind"]
    add("particles", "wind", "particles", "wind-particles", "custom", _custom="particle layer over the wind u/v texture",
        meta={"params": wind["particles"], "opacity_by_zoom": stack["opacity_by_zoom"]["particles"]})
    add("arrows-barbs", "wind", "barbs", "wind-barbs", "symbol", "wind-barb-points",
        layout={"icon-image": ["concat", "barb-", ["to-string", ["*", 5, ["round", ["/", ["get", "kt"], 5]]]]],
                "icon-rotate": ["get", "dir_from_deg"], "icon-rotation-alignment": "map",
                "icon-allow-overlap": False, "icon-padding": wind["barbs"]["min_spacing_px"] / 2},
        meta={"barb": wind["barbs"], "icons": "barb sprites drawn from barbs.length_pt/width_pt/halo, colour color_on_field over a fill else color_on_light_base"})
    add("arrows-barbs", "waves-swell", "arrows", "wave-arrows", "symbol", "wave-arrow-points",
        layout={"icon-image": "wave-arrow", "icon-rotate": ["+", ["get", "dir_from_deg"], 180],
                "icon-rotation-alignment": "map"}, meta={"arrow": layers["waves-swell"]["arrows"]})

    zone = "marine-zones-mpas"
    zones = layers[zone]
    habitat = _zoom(stack["opacity_by_zoom"]["habitat_fill"])
    hazard = zones["hazard_fill"]
    add("polygons", zone, "hazard_fill", "hazard-fill", "fill", "marine-zones",
        paint={"fill-color": _match("event", hazard), "fill-opacity": ["min", hazard["opacity"], habitat]},
        filter=["boolean", ["get", "active"], False])
    zone_line = zones["zone_line"]
    add("polygons", zone, "zone_line", "zone-line", "line", "marine-zones",
        paint={**_line(zone_line), "line-dasharray": _dash(zone_line)})
    mpa = zones["mpa"]
    mpa_colours = _match("type", mpa)
    add("polygons", zone, "mpa", "mpa-fill", "fill", "mpas",
        paint={"fill-color": mpa_colours, "fill-opacity": ["min", mpa["fill_opacity"], habitat]})
    add("polygons", zone, "mpa", "mpa-line", "line", "mpas", paint={"line-color": mpa_colours, "line-width": mpa["line_pt"]})
    label(zone, "zone_label", "zone-label", "marine-zone-labels", ["get", "id"], zones["zone_label"]["size_pt"],
          ink(zones["zone_label"]["color"]))
    label(zone, "mpa.label", "mpa-label", "mpa-labels", ["get", "short_name"], mpa["label"]["size_pt"], ink(mpa_colours))
    kelp, shore = (layers["kelp-habitat"][key] for key in ("kelp", "shore"))
    add("polygons", "kelp-habitat", "kelp", "kelp", "fill", "kelp",
        paint={"fill-color": kelp["fill"], "fill-opacity": ["case", ["boolean", ["global-state", "fieldOn"], False],
                                                          kelp["opacity_with_color_field"], kelp["opacity"]]})
    for suffix, name, colour, width in (("halo", "shore-halo", shore["halo"], shore["halo_pt"]),
                                        ("colors", "shore", _match("substrate_key", shore), shore["width_pt"])):
        add("polygons", "kelp-habitat", f"shore.{suffix}", name, "line", "shore-habitat",
            layout={"line-cap": "round"}, paint={"line-color": colour, "line-width": width})
    ais = layers["ais-fleet"]
    add("polygons", "ais-fleet", "fill", "ais-fill", "fill", "ais-effort",
        paint={"fill-color": ais["fill"]["color"], "fill-opacity": _opacity(ais["fill"]["opacity"]), "fill-pattern": "hatch-xx"})
    add("polygons", "ais-fleet", "line", "ais-line", "line", "ais-effort", paint=_line(ais["line"]))
    al = ais["label"]
    label("ais-fleet", "label", "ais-label", "ais-effort-labels", ["slice", ["get", "label"], 0, al["max_chars"]],
          al["size_pt"], ink(al["color"]))
    upwelling = layers["upwelling"]
    low, high = upwelling["domain_m2_s"]
    stops = upwelling["ramp_stops"]
    ramp = [v for i, colour in enumerate(stops) for v in (low + i * (high - low) / (len(stops) - 1), colour)]
    add("polygons", "upwelling", "ramp_stops", "upwelling-ribbon", "fill", "cuti-ribbon",
        paint={"fill-color": ["interpolate", ["linear"], ["get", "cuti"], *ramp], "fill-opacity": upwelling["opacity"]},
        meta=_pick(upwelling, "cell"))

    route = "routes-tracks"
    track, line, wp, leg = (layers[route][key] for key in ("recorded_track", "route", "waypoint", "leg_label"))
    add("routes", route, "recorded_track", "track", "line", "recorded-track",
        paint={**_line(track), "line-opacity": track["opacity"]})
    for suffix, name, colour, width in (("route.halo", "route-halo", line["halo"], line["halo_pt"]),
                                        ("route", "route", line["color"], line["width_pt"])):
        add("routes", route, suffix, name, "line", "planning-route", layout={"line-cap": line["cap"], "line-join": "round"},
            paint={"line-color": colour, "line-width": width})
    add("points", route, "waypoint", "waypoint", "circle", "route-waypoints", paint=circle(wp, "fill"))
    label(route, "waypoint", "waypoint-num", "route-waypoints", ["to-string", ["get", "n"]], wp["text_pt"],
          {"text-color": wp["text"]}, layout={"text-allow-overlap": True})
    label(route, "leg_label", "leg-label", "route-legs",
          ["concat", ["number-format", ["get", "nm"], {"max-fraction-digits": 1, "min-fraction-digits": 1}], " nm"],
          leg["size_pt"], ink(leg["color"]), layout={"symbol-placement": "line-center"},
          filter=[">", ["get", "leg"], int(leg["skip_first_leg"])])

    pier, ramp = (layers["places"][key] for key in ("pier", "ramp"))
    for suffix, name, paint in (("pier.halo", "pier-halo", {"line-color": pier["halo"], "line-width": pier["width_pt"] + pier["halo_extra_pt"]}),
                                ("pier", "pier", _line(pier))):
        add("points", "places", suffix, name, "line", "piers", layout={"line-cap": "butt"}, paint=paint)
    add("points", "places", "ramp", "ramp", "symbol", "launch-ramps",
        layout={"icon-image": "triangle-up", "icon-size": ramp["size_pt"] / 9, "text-field": ["get", "name_short"],
                "text-font": font, "text-size": ramp["label_pt"], "text-anchor": "left", "text-offset": [0.8, 0]},
        paint={**ink(common["ink"]), "icon-color": ramp["color"], "icon-halo-color": ramp["outline"],
               "icon-halo-width": ramp["outline_pt"]}, meta=_pick(ramp, "label_strip"))
    tides = layers["tides"]
    add("points", "tides", "pin", "tide-pin", "circle", "tide-stations", paint=circle(tides["pin"], "color"),
        meta={"panel": _pick(tides, "curve", "now", "hilo_label", "stage_label", "datum", "time")})
    stations = layers["stations"]
    add("points", "stations", "pin", "station-pin", "circle", "stations", paint=circle(stations["pin"], "color"))
    chip = stations["chip"]
    label("stations", "chip", "station-chip", "stations", ["get", "chip_text"], chip["size_pt"], {"text-color": chip["text"]},
          layout={"text-anchor": "left", "text-offset": [1, 0], "icon-image": "chip-bg", "icon-text-fit": "both",
                  "symbol-sort-key": ["get", "priority"]}, meta=_pick(stations, "chip", "collision"))
    spots = layers["spots-marks"]
    badge, others = spots["badge"], spots["others"]
    ranked = ["<=", ["get", "rank"], spots["top_n"]]
    add("points", "spots-marks", "others", "spot-others", "circle", "atlas-marks", paint=circle(others, "color", outline=False),
        filter=[">", ["get", "rank"], spots["top_n"]], meta=_pick(others, "hide_with_color_field"))
    add("points", "spots-marks", "badge", "spot-badge", "circle", "atlas-marks", paint=circle(badge, "fill"),
        filter=ranked, layout={"circle-sort-key": ["get", "rank"]})
    label("spots-marks", "badge", "spot-rank", "atlas-marks", ["to-string", ["get", "rank"]], badge["text_pt"],
          {"text-color": badge["text"]}, filter=ranked, layout={"text-allow-overlap": True}, meta=_pick(spots, "rank_by"))

    # Python sort is stable: keep the authored sublayer order within each slot.
    rows.sort(key=lambda row: order[row["metadata"]["skippercast:z"]])
    sources = sorted({row["source"] for row in rows if "source" in row})
    return {
        "_generated_from": f"layer-tokens.json v{tokens['version']} + stacking.json + nearshore style-tokens.json",
        "_note": NOTE,
        "_z_order": stack["z_order"],
        "_presets": stack["presets"],
        "_precedence": [rule["id"] for rule in stack["precedence"]],
        "sources": {source: {"type": "<raster value texture | geojson | vector — provided by the app's existing feed for this layer>"}
                    for source in sources},
        "layers": rows,
    }
