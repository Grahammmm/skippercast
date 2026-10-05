// Charter fleet activity layers (docs/plans/charter-fleet/design.md § 14, D11; CF-51).
// Modelled on commercial-ais.js: one L.layerGroup per layer, toggles in
// index.html, a status line and a details card through onSelect.
//
// Admin only while the public layer is undecided. The fleet section of the map
// options ships hidden and is removed from the page unless /api/session says
// is_admin and the map API's filters probe answers; that probe is a 404 for a
// non-admin and whenever FLEET_ENABLED or FLEET_MAP_ENABLED is off
// (server/fleet/map.ts, routes/fleet.ts), so the client never decides access.
//
// Layers: activity events (circles, radius ∝ √dwell, drift filled, troll
// ringed), trip tracks (segments coloured by kind, gaps dashed; the API returns
// them decoded) and heat (aggregate cells, opacity ∝ dwell). Filters are applied
// server-side; every layer pages on meta.next, never on feature counts. Rows
// whose rights are NOAA planning-only (MarineCadastre, D9) are drawn dotted and
// can be left out with one checkbox.
import {getRegion} from "./region.js";
import {esc} from "./marine-charts.js";

export const LAYERS = ["events", "tracks", "heat"];
export const INFERRED = "Inferred from movement (speed and track shape). Not a confirmed fishing stop or catch.";
export const EVENT_STYLE = {
  "drift-anchor": {color: "#1f5f8b", fill: true, label: "Drift or anchor"},
  troll: {color: "#c0561b", fill: false, label: "Troll"},
};
export const SEGMENT_STYLE = {
  "in-port": {color: "#9aa9b0", weight: 1.5, label: "In port"},
  transit: {color: "#64747d", weight: 2, label: "Transit"},
  "fishing-drift": {color: "#1f5f8b", weight: 4, label: "Drift or anchor"},
  "fishing-troll": {color: "#c0561b", weight: 4, label: "Troll"},
  gap: {color: "#64747d", weight: 2, dashArray: "6 6", label: "Gap in coverage"},
};
export const HEAT_COLOR = "#b4441e";
/** Dash pattern for rows whose rights are NOAA planning-only. */
export const PLANNING_DASH = "1 5";
/** Query names the filter card sets; the map API takes each (server/fleet/map.ts). */
export const FILTERS = ["vessel", "port", "class", "trip_type", "kind", "from", "to", "season", "season_part"];
/** Pages followed per layer and redraw; the status line says when more remain. */
export const MAX_PAGES = 3;
// Coastal regions name their state in jurisdiction_id ("california-central"); the
// fleet API is keyed by the state-level fleet region (§ 3: "CA").
const STATES = {california: "CA", oregon: "OR", washington: "WA"};

/** The fleet region (state id) for a coastal region, or null when it has none. */
export function fleetRegion(region) {
  const state = String(region?.jurisdiction_id || "").split("-")[0];
  return STATES[state] || null;
}

/** Circle radius in px, proportional to the square root of dwell, 4–18 px. */
export function eventRadius(dwellMin) {
  const r = 2 * Math.sqrt(Math.max(0, Number(dwellMin) || 0));
  return Math.min(18, Math.max(4, r));
}

/** Heat cell fill opacity, proportional to dwell against the heaviest drawn cell. */
export function heatOpacity(dwellMin, maxDwell) {
  if (!(maxDwell > 0)) return 0.1;
  return 0.1 + 0.6 * Math.min(1, Math.max(0, Number(dwellMin) || 0) / maxDwell);
}

/**
 * The map API URL for a layer. Empty filters are left out: an omitted season
 * part is every part on events and tracks and the whole-season cells on heat,
 * the API's own defaults, so no dwell is ever counted twice.
 */
export function layerQuery(layer, filters, {region, bbox, cursor} = {}) {
  const q = new URLSearchParams({region});
  if (bbox) q.set("bbox", bbox.map(v => Number(v.toFixed(5))).join(","));
  for (const name of FILTERS) if (filters?.[name]) q.set(name, filters[name]);
  if (cursor) q.set("cursor", cursor);
  return `/api/fleet/map/${layer}?${q}`;
}

/** The map's visible bounds as minLon,minLat,maxLon,maxLat, clamped to the API's range. */
export function mapBBox(map) {
  const b = map.getBounds?.();
  if (!b) return null;
  const w = Math.max(-180, b.getWest()), s = Math.max(-90, b.getSouth()), e = Math.min(180, b.getEast()), n = Math.min(90, b.getNorth());
  return w < e && s < n ? [w, s, e, n] : null;
}

const label = v => (v ? String(v).replace(/[-_]+/g, " ").replace(/^./, c => c.toUpperCase()) : "—");
const minutes = n => {
  const m = Math.round(Number(n));
  if (n === null || n === undefined || !Number.isFinite(m)) return "—";
  return m >= 60 ? `${Math.floor(m / 60)} hr ${m % 60} min` : `${m} min`;
};
const miles = n => (Number.isFinite(Number(n)) && n !== null ? `${Number(n).toFixed(1)} nm` : "—");
function clock(iso, timezone) {
  const t = Date.parse(iso);
  if (!Number.isFinite(t)) return "—";
  try { return new Intl.DateTimeFormat("en-US", {timeZone: timezone, hour: "numeric", minute: "2-digit"}).format(t); }
  catch { return new Date(t).toISOString().slice(11, 16) + " UTC"; }
}
const fact = (name, value) => `<dt>${esc(name)}</dt><dd>${esc(value ?? "—")}</dd>`;
const boat = p => p.vessel_name || p.vessel_id || "Unnamed boat";
const season = p => [p.season, p.season_part && label(p.season_part)].filter(Boolean).join(" · ") || "—";
const eyebrow = (what, p) => `<div class="eyebrow">${what} · ADMIN${p.planning_only ? " · PLANNING-ONLY" : ""}</div>`;
const inferred = `<p class="evidence-note fleet-inferred"><strong>${esc(INFERRED)}</strong></p>`;

function rightsHTML(p) {
  const planning = p.planning_only
    ? "<p><strong>NOAA planning-only.</strong> MarineCadastre backfill for verification and internal use; keep it off paid surfaces.</p>"
    : "";
  const version = p.classifier_version ? ` · classifier ${esc(p.classifier_version)}` : "";
  return `<details class="detail-section"><summary>Source &amp; rights</summary><p>Source: ${esc(p.source || "—")} · rights: ${esc(p.rights || "—")}${version}</p>${planning}<p>Basis: ${esc(p.basis || "inferred-from-movement")}. AIS reception can miss boats or drop out offshore.</p></details>`;
}

/** The details card for one activity event. */
export function eventCardHTML(p, {timezone = "America/Los_Angeles"} = {}) {
  const kind = EVENT_STYLE[p.kind]?.label || label(p.kind);
  return `${eyebrow("FLEET ACTIVITY", p)}<h2>${esc(boat(p))}</h2>${inferred}`
    + `<div class="stats"><div class="stat"><span>Type</span><strong>${esc(kind)}</strong></div><div class="stat"><span>Dwell</span><strong>${esc(minutes(p.dwell_min))}</strong></div>`
    + `<div class="stat"><span>Date</span><strong>${esc(p.local_date || "—")}</strong></div><div class="stat"><span>Start–end</span><strong>${esc(clock(p.started_at, timezone))}–${esc(clock(p.ended_at, timezone))}</strong></div></div>`
    + `<dl class="fleet-facts">${fact("Boat", boat(p))}${fact("Port", label(p.port_id))}${fact("Class", label(p.vessel_class))}${fact("Trip type", label(p.trip_type))}${fact("Season", season(p))}${fact("Started", p.started_at)}${fact("Ended", p.ended_at)}</dl>`
    + `<button id="fleet-weather" class="primary">Conditions near this stop</button>${rightsHTML(p)}`;
}

/** The details card for one track segment and its trip. */
export function trackCardHTML(p, {timezone = "America/Los_Angeles"} = {}) {
  const kind = SEGMENT_STYLE[p.segment_kind]?.label || label(p.segment_kind);
  const ports = [p.depart_port_id, p.return_port_id].filter(Boolean).map(label).join(" → ") || "—";
  return `${eyebrow("FLEET TRIP", p)}<h2>${esc(boat(p))}</h2>${inferred}`
    + `<div class="stats"><div class="stat"><span>Segment</span><strong>${esc(kind)}</strong></div><div class="stat"><span>Date</span><strong>${esc(p.local_date || "—")}</strong></div>`
    + `<div class="stat"><span>Departed–returned</span><strong>${esc(clock(p.departed_at, timezone))}–${esc(p.returned_at ? clock(p.returned_at, timezone) : "open")}</strong></div><div class="stat"><span>Fishing time</span><strong>${esc(minutes(p.fishing_min))}</strong></div></div>`
    + `<dl class="fleet-facts">${fact("Boat", boat(p))}${fact("Ports", ports)}${fact("Class", label(p.vessel_class))}${fact("Trip type", label(p.trip_type))}${fact("Trip status", label(p.trip_status))}${fact("Distance", miles(p.distance_nm))}${fact("Furthest offshore", miles(p.max_offshore_nm))}${fact("Segment time", `${clock(p.started_at, timezone)}–${clock(p.ended_at, timezone)}`)}${fact("Season", season(p))}</dl>`
    + `<button id="fleet-weather" class="primary">Conditions along this trip</button>${rightsHTML(p)}`;
}

/** The details card for one aggregate cell. */
export function heatCardHTML(p) {
  const kind = EVENT_STYLE[p.kind]?.label || label(p.kind);
  const dates = p.first_date || p.last_date ? `${p.first_date || "?"} to ${p.last_date || "?"}` : "—";
  return `${eyebrow("FLEET ACTIVITY HEAT", p)}<h2>${esc(kind)} cell</h2>${inferred}`
    + `<div class="stats"><div class="stat"><span>Total dwell</span><strong>${esc(minutes(p.dwell_min))}</strong></div><div class="stat"><span>Boats</span><strong>${esc(p.vessels_n ?? "—")}</strong></div><div class="stat"><span>Stops</span><strong>${esc(p.events_n ?? "—")}</strong></div></div>`
    + `<dl class="fleet-facts">${fact("Season", season(p))}${fact("Dates", dates)}${fact("Cell", p.cell_id)}${fact("Module", p.module)}${fact("Computed", p.computed_at)}</dl>`
    + `<button id="fleet-weather" class="primary">Conditions near this cell</button>${rightsHTML(p)}`;
}

/** A feature's centre as an area for the details card and conditions. */
export function featureArea(f, name) {
  const g = f.geometry || {};
  const points = g.type === "Point" ? [g.coordinates] : g.type === "LineString" ? g.coordinates : g.type === "Polygon" ? g.coordinates[0].slice(0, -1) : [];
  const valid = points.filter(c => Array.isArray(c) && Number.isFinite(c[0]) && Number.isFinite(c[1]));
  if (!valid.length) return null;
  const lon = valid.reduce((s, c) => s + c[0], 0) / valid.length, lat = valid.reduce((s, c) => s + c[1], 0) / valid.length;
  return {...f.properties, latitude: lat, longitude: lon, label: name, geometry: g};
}

const option = (value, text) => `<option value="${esc(value)}">${esc(text)}</option>`;
/** The filter card's select options from GET /api/fleet/map/filters. */
export function filterOptions(data) {
  const any = option("", "Any");
  const values = list => (Array.isArray(list) ? list : []);
  return {
    vessel: any + values(data?.vessels).map(v => option(v.id, v.name || v.id)).join(""),
    port: any + values(data?.ports).map(v => option(v, label(v))).join(""),
    class: any + values(data?.classes).map(v => option(v, label(v))).join(""),
    trip_type: any + values(data?.trip_types).map(v => option(v, label(v))).join(""),
    kind: any + values(data?.kinds).map(v => option(v, EVENT_STYLE[v]?.label || label(v))).join(""),
    season: any + values(data?.seasons).map(v => option(v, v)).join(""),
    season_part: option("", "Whole season") + values(data?.season_parts).map(v => option(v, label(v))).join(""),
  };
}

/** The filter values from the card's form controls, by name. */
export function readFilters(form) {
  const out = {};
  for (const name of FILTERS) {
    const value = String(form.elements?.[name]?.value ?? "").trim();
    if (value) out[name] = value;
  }
  return out;
}

/**
 * The map API's filter values when this viewer may see the fleet layers, else
 * null. Asks /api/session first, so a visitor who is not an admin never calls
 * the map API; the filters probe then answers 404 while either flag is off.
 */
export async function fleetAccess(region, fetcher = fetch) {
  if (!region) return null;
  try {
    const session = await fetcher("/api/session", {credentials: "same-origin", signal: AbortSignal.timeout(10000)});
    if (!session.ok || !(await session.json())?.is_admin) return null;
    const probe = await fetcher(`/api/fleet/map/filters?region=${encodeURIComponent(region)}`, {credentials: "same-origin", signal: AbortSignal.timeout(10000)});
    if (!probe.ok) return null;
    const data = await probe.json();
    return data && data.region === region ? data : null;
  } catch { return null; }
}

/** Every page of a layer up to MAX_PAGES, following meta.next. */
export async function fetchLayer(layer, filters, {region, bbox, fetcher = fetch, signal} = {}) {
  const features = [], ignored = new Set();
  let cursor = null, pages = 0, trips = 0;
  do {
    const r = await fetcher(layerQuery(layer, filters, {region, bbox, cursor}), {credentials: "same-origin", signal});
    if (!r.ok) throw Error(`Fleet ${layer} request failed (${r.status})`);
    const page = await r.json();
    features.push(...(page.features || []));
    for (const name of page.meta?.ignored || []) ignored.add(name);
    trips += page.meta?.trips || 0;
    cursor = page.meta?.next || null;
    pages++;
  } while (cursor && pages < MAX_PAGES);
  return {features, more: !!cursor, ignored: [...ignored], trips};
}

const IGNORED_NAMES = {vessel: "boat", port: "port", class: "class", trip_type: "trip type", source: "source", from: "from date", to: "to date"};

/** The status line for the drawn layers. */
export function statusText(results) {
  const parts = [];
  if (results.events) parts.push(`${results.events.features.length}${results.events.more ? "+" : ""} stops`);
  if (results.tracks) parts.push(`${results.tracks.trips}${results.tracks.more ? "+" : ""} trips`);
  if (results.heat) parts.push(`${results.heat.features.length}${results.heat.more ? "+" : ""} heat cells`);
  if (!parts.length) return "Fleet activity is off. Turn on a layer to load it.";
  let text = parts.join(" · ") + " · inferred from movement";
  if (Object.values(results).some(r => r?.more)) text += ". More remain: zoom in or narrow the filters";
  const ignored = results.heat?.ignored?.map(n => IGNORED_NAMES[n] || n) || [];
  if (ignored.length) text += `. Heat cells ignore ${ignored.join(", ")}`;
  return text + ".";
}

/** Drop NOAA planning-only rows when asked. */
export const visibleFeatures = (features, hidePlanning) => (hidePlanning ? features.filter(f => !f.properties?.planning_only) : features);

export async function initFleetActivity(map, {onSelect, showMap, fetcher = fetch, region = fleetRegion(getRegion())} = {}) {
  const section = document.getElementById("fleet-layers");
  const toggles = Object.fromEntries(LAYERS.map(name => [name, document.getElementById(`layer-fleet-${name}`)]));
  const access = await fleetAccess(region, fetcher);
  if (!access) { section?.remove(); return {draw() {}, enabled: false}; }
  const form = document.getElementById("fleet-filters");
  const status = document.getElementById("fleet-activity-status");
  const hidePlanning = document.getElementById("fleet-hide-planning");
  const options = filterOptions(access);
  for (const [name, html] of Object.entries(options)) if (form.elements[name]) form.elements[name].innerHTML = html;
  for (const name of ["from", "to"]) {
    const input = form.elements[name];
    if (input && access.dates?.min) input.min = access.dates.min;
    if (input && access.dates?.max) input.max = access.dates.max;
  }
  if (access.truncated) document.getElementById("fleet-vessels-note").hidden = false;
  section.hidden = false;

  const groups = Object.fromEntries(LAYERS.map(name => [name, L.layerGroup()]));
  const results = {};
  const timezone = getRegion().timezone || "America/Los_Angeles";
  let controller = null, timer = 0;

  const select = (f, html, name) => { const area = featureArea(f, name); if (area) onSelect(html, area); };
  const paint = {
    heat(features) {
      const max = Math.max(0, ...features.map(f => Number(f.properties.dwell_min) || 0));
      for (const f of features) {
        const p = f.properties;
        L.geoJSON(f, {style: {color: HEAT_COLOR, weight: 0.5, opacity: 0.5, dashArray: p.planning_only ? PLANNING_DASH : null, fillColor: HEAT_COLOR, fillOpacity: heatOpacity(p.dwell_min, max)}})
          .on("click", () => select(f, heatCardHTML(p), `Fleet heat cell · ${EVENT_STYLE[p.kind]?.label || label(p.kind)}`)).addTo(groups.heat);
      }
    },
    tracks(features) {
      for (const f of features) {
        const p = f.properties, style = SEGMENT_STYLE[p.segment_kind] || SEGMENT_STYLE.transit;
        L.geoJSON(f, {style: {color: style.color, weight: style.weight, opacity: 0.85, dashArray: style.dashArray || (p.planning_only ? PLANNING_DASH : null)}})
          .on("click", () => select(f, trackCardHTML(p, {timezone}), `${boat(p)} · trip ${p.local_date || ""}`.trim())).addTo(groups.tracks);
      }
    },
    events(features) {
      for (const f of features) {
        const p = f.properties, style = EVENT_STYLE[p.kind] || EVENT_STYLE["drift-anchor"];
        const [lon, lat] = f.geometry.coordinates;
        const marker = L.circleMarker([lat, lon], {radius: eventRadius(p.dwell_min), color: style.color, weight: style.fill ? 1 : 2.5, fill: true,
          fillColor: style.color, fillOpacity: style.fill ? 0.55 : 0.05, dashArray: p.planning_only ? PLANNING_DASH : null});
        marker.bindTooltip?.(`${esc(boat(p))} · ${esc(style.label)} · ${esc(minutes(p.dwell_min))} · inferred`);
        marker.on("click", () => select(f, eventCardHTML(p, {timezone}), `${boat(p)} · ${style.label.toLowerCase()} stop`)).addTo(groups.events);
      }
    },
  };

  function render() {
    // Heat under tracks under events: re-adding in this order keeps the stack.
    for (const name of ["heat", "tracks", "events"]) {
      groups[name].clearLayers();
      map.removeLayer(groups[name]);
      if (!toggles[name]?.checked || !results[name]) continue;
      paint[name](visibleFeatures(results[name].features, hidePlanning?.checked));
      groups[name].addTo(map);
    }
    status.textContent = statusText(Object.fromEntries(LAYERS.filter(n => toggles[n]?.checked && results[n]).map(n => [n, results[n]])));
  }

  async function load() {
    controller?.abort();
    for (const name of LAYERS) if (!toggles[name]?.checked) delete results[name];
    const wanted = LAYERS.filter(name => toggles[name]?.checked);
    if (!wanted.length) { render(); return; }
    const mine = controller = new AbortController();
    status.textContent = "Loading fleet activity…";
    const filters = readFilters(form), bbox = mapBBox(map);
    try {
      const loaded = await Promise.all(wanted.map(name => fetchLayer(name, filters, {region, bbox, fetcher, signal: mine.signal})));
      if (mine !== controller) return;
      wanted.forEach((name, i) => { results[name] = loaded[i]; });
      render();
    } catch (error) {
      if (mine !== controller || error?.name === "AbortError") return;
      status.textContent = "Fleet activity could not load. The map and other layers remain available.";
    }
  }
  const later = () => { clearTimeout(timer); timer = setTimeout(load, 400); };

  for (const name of LAYERS) toggles[name]?.addEventListener("change", load);
  hidePlanning?.addEventListener("change", render);
  form.addEventListener("submit", event => { event.preventDefault(); load(); });
  document.getElementById("fleet-show")?.addEventListener("click", () => {
    if (!LAYERS.some(name => toggles[name]?.checked)) toggles.events.checked = true;
    load();
    document.getElementById("map-options")?.close?.();
    showMap?.();
  });
  map.on?.("moveend", () => { if (LAYERS.some(name => toggles[name]?.checked)) later(); });
  render();
  return {draw: render, load, enabled: true};
}
