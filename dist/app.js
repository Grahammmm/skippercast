import {initSearchPlans} from './search-plans.js?v=8.11';
import {initTripAlerts} from './trip-alerts.js?v=8.11';
import {initExport} from './export-ui.js?v=8.11';
import {mountSpotEvidence} from './spot-evidence.js?v=8.11';
import {initIntelligence} from './intelligence.js?v=8.11';
import {initHabitatDynamics} from './habitat-map.js?v=8.11';
import {terrainSource,terrainMetricsHTML} from './terrain-evidence.js?v=8.11';
let tripExport;
import { getRegion, assetURL } from "./region.js?v=8.11";
import { mountBottom } from "./bottom-view.js?v=8.11";
import { initSurveyHabitat } from "./survey-habitat.js?v=8.11";
import { initRegionalContext } from "./regional-context.js?v=8.11";
import { initGeology } from "./geology.js?v=8.11";
import { initWeather } from "./weather-ui.js?v=8.11";
import { initNavigation } from "./navigation.js?v=8.11";
import { initChart } from "./chart-map.js?v=8.11";
import { initSpecies, matchesSpecies } from "./species.js?v=8.11";
import { initRegulations } from "./regulations.js?v=8.12";
import { initLocationContext, viewFromURL } from './location-context.js?v=8.11';
import { initCharterGrounds } from "./charter-grounds.js?v=8.11";
import { initProtectedAreas } from "./protected-areas.js?v=8.11";
import { initDriftGuides } from "./drift-guides.js?v=8.11";
import { initCommercialAIS } from "./commercial-ais.js?v=8.11";
const $ = (id) => document.getElementById(id);
const escapeHTML = (value) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const areaNames = getRegion().source_names;
const gradeGuide = {
  A: {
    label: "First look",
    range: "75–100",
    description:
      "A stronger combined terrain score makes this a sensible place to start a sounder search when access and conditions suit.",
  },
  B: {
    label: "Useful alternative",
    range: "55–74",
    description:
      "Meaningful mapped structure with a lower combined terrain score. Keep it as an alternative when another area is crowded or the drift is awkward.",
  },
  C: {
    label: "Exploratory",
    range: "below 55",
    description:
      "Less mapped relief, rough cover, complexity, or nearby habitat area. An isolated productive feature can still receive this grade.",
  },
};
let atlas,
  map,
  selected,
  initialFitPending = true,
  initialViewShown = false,
  visible = [];
let speciesUI, charterUI, weather, protectedAreas, driftGuides, commercialUI, locationUI;
let boundaryRefreshDone=false;
const layers = {},
  markers = new Map();
const navigation = initNavigation({
  onMapVisible: () => {
    if (!map) return;
    map.invalidateSize({ pan: false });
    if (initialFitPending) fitTargets();
  },
});

function initMap() {
  const view=viewFromURL(location.href);
  map = L.map("map", { zoomControl: false, minZoom: 7, maxZoom: 18 }).setView(
    view?[view.latitude,view.longitude]:getRegion().map.center,
    view?.zoom||getRegion().map.zoom,
  );
  L.control.zoom({ position: "topright" }).addTo(map);
  L.control
    .scale({ imperial: true, metric: false, position: "bottomleft" })
    .addTo(map);
  initChart(map, toast);
  const coverage=document.createElement('div');coverage.id='reef-coverage';coverage.className='reef-coverage';coverage.hidden=true;
  document.querySelector('.map-wrap').append(coverage);
  map.on('moveend',updateReefCoverage);
  for (const name of ["targets", "areas", "drifts", "forecast", "charters"]) {
    layers[name] = L.layerGroup();
    if ($(`layer-${name}`).checked) layers[name].addTo(map);
    $(`layer-${name}`).addEventListener("change", (e) =>
      e.target.checked
        ? layers[name].addTo(map)
        : map.removeLayer(layers[name]),
    );
  }
}

function updateReefCoverage() {
  const box=$('reef-coverage');if(!box||!atlas||!protectedAreas)return;
  const reef=['reef','rockfish','lingcod'].includes($('species-select').value);
  box.hidden=!reef;box.replaceChildren();if(!reef)return;
  if(!protectedAreas.ready()){box.textContent=boundaryRefreshDone?'Protected-area check unavailable · fishing spots withheld':'Checking protected areas before showing fishing spots…';return;}
  if(!visible.length){box.hidden=true;return;}
  if($('layer-targets').checked&&visible.some(t=>map.getBounds().contains([t.latitude,t.longitude]))){box.hidden=true;return;}
  const label=document.createElement('span');label.textContent=$('layer-targets').checked?`${visible.length} reef areas outside this view`:'Reef markers are turned off';
  const button=document.createElement('button');button.type='button';button.textContent='Show reef areas';
  button.onclick=()=>{if(!$('layer-targets').checked){$('layer-targets').checked=true;$('layer-targets').dispatchEvent(new Event('change'));}map.fitBounds(visible.map(t=>[t.latitude,t.longitude]),{padding:[65,120],maxZoom:12});updateReefCoverage();};
  box.append(label,button);
}

function pin(target) {
  return L.divIcon({
    className: "target-pin",
    html: `<span aria-hidden="true" class="pin-content ${target.habitat_grade} ${selected?.id === target.id ? "selected" : ""}">${target.habitat_grade}</span><span class="sr-only">${escapeHTML(target.id)}: ${escapeHTML(target.label)}, grade ${target.habitat_grade}, ${target.center_depth_ft} feet</span>`,
    iconSize: [44, 44],
    iconAnchor: [22, 22],
  });
}

function filterTargets() {
  const search = $("search").value.toLowerCase().trim();
  visible = atlas.targets
    .filter(
      (t) =>
        protectedAreas?.pointAllowed(t) &&
        matchesSpecies(t, $("species-select").value) &&
        ($("area").value === "all" || t.source_id === $("area").value) &&
        ($("grade").value === "all" || t.habitat_grade === $("grade").value) &&
        t.neighborhood_depth_ft[1] <= Number($("depth").value) &&
        ($("geometry").value === "all" ||
          ($("geometry").value === "drift"
            ? !!t.drift_id
            : t.area_ids.length > 0)) &&
        `${t.id} ${t.name} ${t.legacy_id} ${t.label} ${t.terrain_interpretation}`
          .toLowerCase()
          .includes(search),
    )
    .sort(
      (a, b) => b.habitat_score - a.habitat_score || a.id.localeCompare(b.id),
    );
  if (selected && !visible.some((t) => t.id === selected.id)) {
    selected = undefined;
    $("export-selected").hidden = true;
    $("export-selected").removeAttribute("href");
    $("detail").innerHTML =
      '<div class="empty-detail"><h2>Pick a target.</h2><p>Your selected target is outside these filters.</p></div>';
  }
  $("filter-summary").textContent = [
    $("area").value === "all" ? "All areas" : areaNames[$("area").value],
    $("grade").value === "all" ? null : `Grade ${$("grade").value}`,
    `${$("depth").value} ft`,
    $("geometry").value === "all"
      ? null
      : $("geometry").value === "drift"
        ? "Drift lines"
        : "Reef areas",
  ]
    .filter(Boolean)
    .join(" · ");
  $("map-empty").hidden = visible.length > 0 || !!assetURL("geology") || !!assetURL("regional_context") || !!assetURL("survey_habitat");
  $("map-empty").querySelector("strong").textContent =
    "No targets in these filters";
  $("map-empty").querySelector("p").textContent =
    "Try a wider area, depth or grade filter.";
  navigation.setHasSelection(!!selected);
  drawHabitat();
  speciesUI?.draw();
  charterUI?.draw();
  driftGuides?.draw();
  commercialUI?.draw();
  updateExports();
  updateReefCoverage();
}

function updateExports() {
  const intro=document.querySelector('.guide-downloads > p');
  if(intro && atlas)intro.textContent=atlas.targets.length?`${getRegion().name}: choose from ${atlas.targets.length} qualified habitat candidates. Build a day plan, select its layers, and download GPX with optional offline notes.`:`${getRegion().name} publishes habitat context. Depth-qualified waypoints are not available yet; protected-area reference outlines can be exported.`;
  for(const notes of document.querySelectorAll('a[href="downloads/spot-notes.html"]'))notes.hidden=getRegion().id!=='morro-bay';
  for(const link of [$("export-selected"),$("download-target")].filter(Boolean)) {
    link.removeAttribute('download');link.href='#export';link.textContent='Review & export this spot';
    link.onclick=event=>{event.preventDefault();if(selected)tripExport?.review(selected.id);};
  }
}

function drawHabitat() {
  for (const name of ["targets", "areas", "drifts"]) layers[name].clearLayers();
  markers.clear();
  const ids = new Set(visible.map((t) => t.id));
  for (const a of atlas.areas.filter(
    (a) => a.target_ids.some(id => ids.has(id)) &&
      (map.getZoom() >= 13 || a.target_ids.includes(selected?.id)) &&
      protectedAreas.geometryAllowed(a.geometry),
  )) {
    L.geoJSON(a.geometry, {
      style: {
        color: "#007f73",
        weight: 1.5,
        fillColor: "#19bca9",
        fillOpacity: 0.18,
      },
    })
      .bindTooltip(
        `${a.id} · ${a.area_ha.toFixed(1)} ha partial reef footprint`,
      )
      .on("click", () => selectTarget(a.target_ids.find((id) => ids.has(id))))
      .addTo(layers.areas);
  }
  for (const d of atlas.drifts.filter(
    (d) =>
      ids.has(d.target_id) &&
      (map.getZoom() >= 13 || d.target_id === selected?.id) &&
      protectedAreas.geometryAllowed(d.geometry) &&
      ($("layer-drifts").checked || d.target_id === selected?.id),
  )) {
    L.geoJSON(d.geometry, {
      style: { color: "#a66310", weight: 3, dashArray: "8 5" },
    })
      .bindTooltip(`${d.id} · ${Math.round(d.length_m)} m structure alignment`)
      .on("click", () => selectTarget(d.target_id))
      .addTo(d.target_id === selected?.id ? layers.areas : layers.drifts);
  }
  const cells = new Map();
  for (const t of visible) {
    const xy = map.project([t.latitude, t.longitude], map.getZoom());
    const key =
      map.getZoom() < 14
        ? `${Math.floor(xy.x / 56)},${Math.floor(xy.y / 56)}`
        : t.id;
    if (!cells.has(key)) cells.set(key, []);
    cells.get(key).push(t);
  }
  for (const group of cells.values()) {
    if (group.length > 1) {
      let lat = group.reduce((s, t) => s + t.latitude, 0) / group.length,
        lon = group.reduce((s, t) => s + t.longitude, 0) / group.length;
      if(!protectedAreas.pointAllowed({latitude:lat,longitude:lon})) {lat=group[0].latitude;lon=group[0].longitude;}
      L.marker([lat, lon], {
        icon: L.divIcon({
          className: "reef-cluster",
          html: `<span>${group.length}</span>`,
          iconSize: [44, 44],
          iconAnchor: [22, 22],
        }),
        title: `${group.length} reef candidates · zoom to separate`,
      })
        .on("click", () =>
          map.fitBounds(
            group.map((t) => [t.latitude, t.longitude]),
            { padding: [70, 120], maxZoom: 15 },
          ),
        )
        .addTo(layers.targets);
    } else {
      const t = group[0];
      const m = L.marker([t.latitude, t.longitude], {
        icon: pin(t),
        title: `${t.id}: ${t.label}, grade ${t.habitat_grade}, ${t.center_depth_ft} ft`,
        keyboard: true,
      })
        .bindTooltip(`${escapeHTML(t.label)} · ${t.center_depth_ft} ft`)
        .on("click", () => selectTarget(t.id))
        .addTo(layers.targets);
      markers.set(t.id, m);
    }
  }
}

function selectTarget(id, pan = true) {
  const target = atlas.targets.find((t) => t.id === id);
  if (!target || !protectedAreas?.pointAllowed(target)) return;
  selected = target;
  locationUI?.select(target);
  drawHabitat();
  driftGuides?.draw();
  $("export-selected").hidden = false;
  weather?.selectLocation(target);
  for (const t of visible) markers.get(t.id)?.setIcon(pin(t));
  for (const button of document.querySelectorAll("[data-target]"))
    button.setAttribute("aria-pressed", String(button.dataset.target === id));
  const t = selected;
  const grade = gradeGuide[t.habitat_grade];
  const survey=terrainSource(t);
  $("detail").innerHTML =
    `<div class="detail-top"><span class="grade ${t.habitat_grade}">${t.habitat_grade}</span><div><div class="eyebrow">${t.id} · TERRAIN RANK ${t.rank} OF ${atlas.targets.length}</div><h2>${escapeHTML(t.label)}</h2></div></div><span class="coordinates">${t.latitude.toFixed(6)}, ${t.longitude.toFixed(6)}</span><p>${escapeHTML(t.terrain_interpretation)}</p><div class="grade-explanation"><strong>Grade ${t.habitat_grade} · ${grade.label} · ${grade.range}</strong><p>${grade.description}</p><a href="#grade-guide">Compare A, B, and C</a></div><div class="stats"><div class="stat"><span>Center depth</span><strong>${t.center_depth_ft} ft</strong></div><div class="stat"><span>Terrain score</span><strong>${t.habitat_score}<small>/100</small></strong></div><div class="stat"><span>Nearby depths</span><strong>${t.neighborhood_depth_ft.join("–")}</strong><span>feet · ${escapeHTML(survey.datum)}</span></div><div class="stat"><span>Rough habitat</span><strong>${(t.metrics.rough_habitat_within_250m_ha * 2.47105).toFixed(1)} acres</strong><span>within 820 ft (250 m)</span></div></div><div class="evidence-note"><p><strong>Mapped habitat candidate</strong><br>Terrain interpretation confidence: ${escapeHTML(t.confidence)}. Fish presence is unverified; no verified charter AIS visits at this target. <a href="#charter-evidence">See the AIS research coverage.</a></p></div><div class="detail-section"><h3>Structure &amp; approach</h3><span class="tag">${escapeHTML(t.feature_type)}</span><span class="tag">${t.area_ids.length} linked reef area${t.area_ids.length === 1 ? "" : "s"}</span><p>${t.feature_type === "localized rocky target" ? "This marker identifies a more localized rocky feature to investigate." : "This marker is a starting position for searching a broader patch of reef."} ${escapeHTML(survey.grid)}; this does not identify an individual boulder.</p><p>${t.area_ids.length ? "The shaded outline shows part of the mapped rough habitat to work across, not the entire reef. " : "No reef outline is linked to this marker. "}${t.drift_id ? "The dashed line follows the structure. Measure your drift first, then choose a setup position that carries your rig across it; either end may be appropriate." : "Use your sounder to locate relief and fish, then set a drift across the structure you find."} Check a nautical chart for your approach; these search geometries are not navigation routes.</p></div><a class="primary" id="download-target" href="downloads/targets/${t.id}.gpx" download="SkipperCast-${t.id}.gpx">↓ Export this spot + geometry</a><div class="detail-section"><h3>Source</h3><p>${escapeHTML(t.source_name||areaNames[t.source_id]||t.source_id)} · ${escapeHTML(survey.producer)} ${t.survey_year}<br>Research screen ${atlas.source_validation_date}</p><a href="${t.source_url}" target="_blank" rel="noopener">Open survey record ↗</a></div>`;
  $("export-selected").href = `downloads/targets/${t.id}.gpx`;
  $("export-selected").download = `SkipperCast-${t.id}.gpx`;
  updateExports();
  const noteSection = document.createElement("div");
  noteSection.className = "detail-section";
  noteSection.innerHTML = terrainMetricsHTML(t);
  $("detail").insertBefore(noteSection, $("download-target"));
  if (t.special_note && !t.special_note.startsWith("No additional")) {
    const p = document.createElement("p");
    p.textContent = t.special_note;
    noteSection.append(p);
  }
  const drift = atlas.drifts.find((d) => d.id === t.drift_id);
  if (drift) {
    const p = document.createElement("p");
    p.textContent = `${Math.round(drift.length_m)} m alignment · axis ${Math.round(drift.bearing_true_axis_deg)}° / ${Math.round((drift.bearing_true_axis_deg + 180) % 360)}° true · ${Math.round(drift.rough_fraction_in_corridor * 100)}% mapped rough habitat in its corridor.`;
    noteSection.append(p);
  }
  navigation.setHasSelection(true);
  if (pan) {
    navigation.showView("map");
    requestAnimationFrame(() => {
      map.invalidateSize({ pan: false });
      map.setView([t.latitude, t.longitude], Math.max(map.getZoom(), 14));
      navigation.openDetails();
    });
  }
  const geometries = [
    ...atlas.areas.filter((a) => t.area_ids.includes(a.id)),
    ...(drift ? [drift] : []),
  ];
  for (const shape of geometries) {
    const p = document.createElement("p"),
      v = shape.recorded_validation;
    p.textContent = `${shape.id}: ${Math.round(v.minimum_ft)}–${Math.round(v.maximum_ft)} ft survey depth across the geometry.${v.maximum_ft > Number($("depth").value) ? " Extends deeper than the selected target-neighborhood limit." : ""}`;
    noteSection.append(p);
  }
  const extra = document.createElement("details");
  extra.innerHTML = "<summary>Structure, grading & sources</summary>";
  for (const el of [
    ...$("detail").querySelectorAll(".grade-explanation,.detail-section"),
  ])
    extra.append(el);
  $("detail").append(extra);
  const conditions = document.createElement("button");
  conditions.className = "primary";
  conditions.textContent = "Conditions for this spot ↗";
  conditions.addEventListener("click", () => navigation.showView("forecast"));
  $("detail").insertBefore(conditions, extra);
  mountBottom($("detail"), t);
  mountSpotEvidence($("detail"),t,$('species-select').value);
  rulesUI.mountSpot($("detail"),locationUI?.get(),$('species-select').value);
  tripExport?.mount($("detail"),t);
}

async function initAISContext() {
  const panel = $("ais-context");
  try {
    if (!assetURL("ais_evidence")) { panel.textContent = "No reviewed charter AIS archive is published for this region. Boat names and slow movement alone do not establish fishing spots."; return; }
    const response = await fetch(assetURL("ais_evidence"));
    if (!response.ok)
      throw new Error(`AIS summary request failed (${response.status})`);
    const evidence = await response.json();
    const count = evidence.summary;
    panel.innerHTML = `<p><strong>No independently verified local charter AIS tracks yet.</strong> The purple charter layer uses published named-ground reports. It does not use vessel tracks, and it does not change terrain grades.</p><div class="evidence-counts"><span>${count.sample_days} sampled UTC dates</span><span>${count.regional_records.toLocaleString()} regional AIS records</span><span>${count.unique_mmsi} vessel identifiers</span><span>${count.verified_local_sportfishing_charters} verified charter identities</span></div><details><summary>AIS sample coverage</summary><p>Research checked ${escapeHTML(evidence.audit_date_pacific)}. Sample dates: ${evidence.daily_samples.map((sample) => escapeHTML(sample.day_utc)).join(", ")}. June 24–30 is a consecutive seven-day block; the other dates are isolated samples.</p><p>The checked NOAA index listed broadcasts through ${escapeHTML(evidence.archive.latest_listed_broadcast_date)}. Missing identities and receiver gaps can hide trips. This limited sample cannot establish where charters do or do not fish.</p></details>`;
  } catch (error) {
    panel.innerHTML =
      '<p class="error">The dated AIS research summary could not load. AIS-derived charter activity remains unverified; see <a href="sources.html#ais">sources and coverage</a>.</p>';
    console.error(error);
  }
}

function registerTools() {
  if (!document.modelContext?.registerTool) return;
  const lifetime = new AbortController();
  window.addEventListener("pagehide", () => lifetime.abort(), { once: true });
  const tools = [
    {
      name: "list_fishing_targets",
      title: "List researched fishing targets",
      description:
        "Read the targets currently visible after the map filters, including terrain grades and survey depths. No catch success is implied.",
      inputSchema: {
        type: "object",
        properties: {},
        additionalProperties: false,
      },
      annotations: { readOnlyHint: true },
      execute(input) {
        if (!input || Object.keys(input).length)
          throw new Error("No arguments accepted");
        return visible.map((t) => ({
          id: t.id,
          name: t.label,
          grade: t.habitat_grade,
          terrainScore: t.habitat_score,
          depthFt: t.center_depth_ft,
          hasDrift: !!t.drift_id,
        }));
      },
    },
    {
      name: "show_fishing_target",
      title: "Show a fishing target",
      description:
        "Select an existing target, reset filters if needed, center the map, and show its evidence and notes. Does not create a trip or download files.",
      inputSchema: {
        type: "object",
        properties: { target_id: { type: "string" } },
        required: ["target_id"],
        additionalProperties: false,
      },
      annotations: { readOnlyHint: false },
      execute(input) {
        if (
          !input ||
          typeof input.target_id !== "string" ||
          Object.keys(input).some((k) => k !== "target_id") ||
          !atlas.targets.some((t) => t.id === input.target_id)
        )
          throw new Error("Unknown target_id");
        $("search").value = "";
        for (const id of ["area", "grade", "geometry"]) $(id).value = "all";
        $("depth").value = "200";
        $("species-select").value = "reef";
        speciesUI?.refresh();
        filterTargets();
        selectTarget(input.target_id);
        requestAnimationFrame(() => navigation.openDetails());
        return {
          selectedTarget: selected.id,
          terrainScore: selected.habitat_score,
          evidence: selected.evidence_status,
        };
      },
    },
  ];
  for (const tool of tools)
    try {
      Promise.resolve(
        document.modelContext.registerTool(tool, { signal: lifetime.signal }),
      ).catch(() => {});
    } catch {
      /* Browsers without the proposed API retain the full visible UI. */
    }
}

function fitTargets() {
  if ($("map-panel").hidden || !map?.getSize().y) {
    initialFitPending = true;
    return;
  }
  if (!initialViewShown) {
    const view=viewFromURL(location.href);
    map.setView(view?[view.latitude,view.longitude]:getRegion().map.center, view?.zoom||getRegion().map.zoom);
    initialViewShown = true;
    initialFitPending = false;
    return;
  }
  if (speciesUI?.fit() || (!visible.length && charterUI?.fit?.())) {
    initialFitPending = false;
    return;
  }
  if (visible.length && !$("map-panel").hidden && map?.getSize().y) {
    const height = map.getSize().y;
    map.fitBounds(
      visible.map((t) => [t.latitude, t.longitude]),
      {
        paddingTopLeft: [35, 75],
        paddingBottomRight: [35, Math.min(145, height * 0.27)],
        maxZoom: 14,
      },
    );
    initialFitPending = false;
  }
}
let toastTimer;
function toast(message) {
  (document.querySelector("dialog[open]") || document.body).append($("toast"));
  $("toast").textContent = message;
  $("toast").hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => ($("toast").hidden = true), 6000);
}

function showAreaDetails(html, area, conditionsButton) {
  selected = undefined;
  locationUI?.select(area);
  drawHabitat();
  speciesUI?.draw();
  weather?.selectLocation(area);
  $("detail").innerHTML = html;
  mountBottom($("detail"), area);
  mountSpotEvidence($("detail"),area,$('species-select').value);
  rulesUI.mountSpot($("detail"),locationUI?.get(),$('species-select').value);
  $("export-selected").hidden = true;
  $(conditionsButton).addEventListener("click", () =>
    navigation.showView("forecast"),
  );
  navigation.setHasSelection(true);
  navigation.openDetails();
  $("spot-dialog-body").scrollTop = 0;
}

for (const id of ["about-button", "about-guide"])
  $(id).addEventListener("click", () => {
    $("map-options").close();
    $("about-dialog").showModal();
  });
$("close-about").addEventListener("click", () => $("about-dialog").close());
function showFilteredMap() {
  navigation.showView("map");
  requestAnimationFrame(() => {
    map?.invalidateSize({ pan: false });
    fitTargets();
  });
}

$("fit-map").addEventListener("click", showFilteredMap);
$("reset-filters").addEventListener("click", () => {
  $("search").value = "";
  for (const id of ["area", "grade", "geometry"]) $(id).value = "all";
  $("depth").value = "200";
  if (atlas) filterTargets();
});
for (const id of ["search", "area", "grade", "depth", "geometry"])
  $(id).addEventListener(id === "search" ? "input" : "change", () => {
    if (atlas) filterTargets();
  });

$("open-map-options").addEventListener("click", () =>
  $("map-options").showModal(),
);
$("empty-options").addEventListener("click", () =>
  $("map-options").showModal(),
);
$("close-map-options").addEventListener("click", () =>
  $("map-options").close(),
);
$("charter-status").addEventListener("click", () => {
  $("map-options").close();
  location.hash = "charter-evidence";
});
initAISContext();
const rulesUI=initRegulations($("species-regulations"), $("species-select"),{resolveLocation:context=>locationUI?.resolve(context)||context});
updateExports();

try {
  const response = await fetch(assetURL("atlas"),{signal:AbortSignal.timeout(15000)});
  if (!response.ok)
    throw new Error(`Atlas request failed (${response.status})`);
  atlas = await response.json();
  initMap();
  protectedAreas = await initProtectedAreas(map, () => filterTargets());
  tripExport=initExport({atlas,screen:protectedAreas,map,getVisible:()=>visible,navigation});
  filterTargets();
  void protectedAreas.refresh().finally(()=>{boundaryRefreshDone=true;updateReefCoverage();});
  fitTargets();
  driftGuides=initDriftGuides(map,{targets:()=>visible,selected:()=>selected,protectedAreas,selectTarget});
  weather=initWeather(map,layers.forecast,()=>navigation.showView("forecast"),driftGuides.update);
  locationUI=initLocationContext(map,{
    select:$("species-select"),protectedAreas,
    onLocation:point=>weather?.selectLocation({...point,label:point.label||'Map location'}),
    onSpeciesChange:()=>$("species-select").dispatchEvent(new CustomEvent('change',{detail:{location:true}})),
  });
  $("spot-dialog").addEventListener('close',()=>{if(document.body.dataset.view==='map')locationUI.clear();});
  const intelligence=initIntelligence(map);
  initTripAlerts(intelligence);
  registerTools();
  const optional=async(name,work)=>{try{return await work();}catch{toast(`${name} could not load. The map and other layers remain available.`);return undefined;}};
  void optional('Species search plan',()=>initSearchPlans(map,protectedAreas,showAreaDetails));
  void optional('Ocean habitat',()=>initHabitatDynamics(map,protectedAreas,area=>{locationUI?.select(area);weather.selectLocation(area);}));
  void optional("Survey habitat",()=>initSurveyHabitat(map, protectedAreas, (html, area) => showAreaDetails(html, area, "survey-weather"), area=>weather.selectLocation(area)));
  void optional("Historical reef areas",()=>initRegionalContext(map, protectedAreas, (html, area) => showAreaDetails(html, area, "regional-weather")));
  void optional("Geological context",()=>initGeology(map, protectedAreas, (html, area) => showAreaDetails(html, area, "geology-weather")));
  speciesUI = await optional("Species habitat",()=>initSpecies(map, layers, {
    protectedAreas,
    onChange: () => {
      filterTargets();
      weather?.setSpecies($("species-select").value);
    },
    onConditions: (p) => {
      weather?.selectLocation(p);
      navigation.showView("forecast");
    },
    showGuide: () => navigation.showView("guide"),
    onSelect: (html, area) => {
      showAreaDetails(html, area, "area-weather");
    },
  }));
  charterUI = await optional("Charter context",()=>initCharterGrounds(map, layers.charters, {
    protectedAreas,
    onSelect: (html, area) => showAreaDetails(html, area, "charter-weather"),
    onTarget: (id) => {
      $("species-select").value = "reef";
      $("search").value = "";
      for (const name of ["area", "grade", "geometry"]) $(name).value = "all";
      $("depth").value = "200";
      speciesUI?.refresh();
      filterTargets();
      weather?.setSpecies("reef");
      selectTarget(id);
      $("spot-dialog-body").scrollTop = 0;
    },
    showMap: () => navigation.showView("map"),
    toast,
  }));
  filterTargets();
  commercialUI=await optional("Commercial AIS",()=>initCommercialAIS(map,{protectedAreas,onSelect:(html,area)=>showAreaDetails(html,area,"commercial-weather"),showMap:()=>navigation.showView("map")}));
  map.on("zoomend", () => {
    if (atlas) {
      drawHabitat();
      speciesUI?.draw();
      charterUI?.draw();
    }
  });
  locationUI.refresh();
  if (selected) weather.selectLocation(selected);
} catch (error) {
  if(!tripExport)$("export-content").textContent='Regional export data could not load. Refresh this page to retry.';
  $("map-empty").hidden = false;
  $("map-empty").innerHTML =
    '<strong>Atlas unavailable</strong><p>Refresh to reload the atlas and protected-area screen.</p>';
  updateExports();
  console.error(error);
}
