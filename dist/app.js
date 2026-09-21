import { initWeather } from "./weather-ui.js?v=5.4";
import { initNavigation } from "./navigation.js?v=5.4";
import { initChart } from "./chart-map.js?v=5.4";
import { initSpecies, matchesSpecies } from "./species.js?v=5.4";
const $ = (id) => document.getElementById(id);
const escapeHTML = (value) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const areaNames = {
  PointBuchon: "Avila / Point Buchon",
  MorroBay: "Morro Bay",
  PointEstero: "Point Estero",
};
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
  visible = [];
let speciesUI, weather;
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
  map = L.map("map", { zoomControl: false, minZoom: 7, maxZoom: 18 }).setView(
    [35.36, -120.95],
    10,
  );
  L.control.zoom({ position: "topright" }).addTo(map);
  L.control
    .scale({ imperial: true, metric: false, position: "bottomleft" })
    .addTo(map);
  initChart(map, toast);
  for (const name of ["targets", "areas", "drifts", "forecast"]) {
    layers[name] = L.layerGroup();
    if ($(`layer-${name}`).checked) layers[name].addTo(map);
    $(`layer-${name}`).addEventListener("change", (e) =>
      e.target.checked
        ? layers[name].addTo(map)
        : map.removeLayer(layers[name]),
    );
  }
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
  $("map-empty").hidden = visible.length > 0;
  $("map-empty").querySelector("strong").textContent =
    "No targets in these filters";
  $("map-empty").querySelector("p").textContent =
    "Try a wider area, depth or grade filter.";
  navigation.setHasSelection(!!selected);
  drawHabitat();
  speciesUI?.draw();
}

function drawHabitat() {
  for (const name of ["targets", "areas", "drifts"]) layers[name].clearLayers();
  markers.clear();
  const ids = new Set(visible.map((t) => t.id));
  for (const a of atlas.areas.filter(
    (a) => selected && a.target_ids.includes(selected.id),
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
      const lat = group.reduce((s, t) => s + t.latitude, 0) / group.length,
        lon = group.reduce((s, t) => s + t.longitude, 0) / group.length;
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
  if (!target) return;
  selected = target;
  drawHabitat();
  $("export-selected").hidden = false;
  weather?.selectLocation(target);
  for (const t of visible) markers.get(t.id)?.setIcon(pin(t));
  for (const button of document.querySelectorAll("[data-target]"))
    button.setAttribute("aria-pressed", String(button.dataset.target === id));
  const t = selected;
  const grade = gradeGuide[t.habitat_grade];
  $("detail").innerHTML =
    `<div class="detail-top"><span class="grade ${t.habitat_grade}">${t.habitat_grade}</span><div><div class="eyebrow">${t.id} · TERRAIN RANK ${t.rank} OF ${atlas.targets.length}</div><h2>${escapeHTML(t.label)}</h2></div></div><span class="coordinates">${t.latitude.toFixed(6)}, ${t.longitude.toFixed(6)}</span><p>${escapeHTML(t.terrain_interpretation)}</p><div class="grade-explanation"><strong>Grade ${t.habitat_grade} · ${grade.label} · ${grade.range}</strong><p>${grade.description}</p><a href="#grade-guide">Compare A, B, and C</a></div><div class="stats"><div class="stat"><span>Center depth</span><strong>${t.center_depth_ft} ft</strong></div><div class="stat"><span>Terrain score</span><strong>${t.habitat_score}<small>/100</small></strong></div><div class="stat"><span>Nearby depths</span><strong>${t.neighborhood_depth_ft.join("–")}</strong><span>feet · survey MLLW</span></div><div class="stat"><span>Rough habitat</span><strong>${(t.metrics.rough_habitat_within_250m_ha * 2.47105).toFixed(1)} acres</strong><span>within 820 ft (250 m)</span></div></div><div class="evidence-note"><p><strong>Mapped habitat candidate</strong><br>Terrain interpretation confidence: ${escapeHTML(t.confidence)}. Fish presence is unverified; no verified charter AIS visits at this target. <a href="#charter-evidence">See the AIS research coverage.</a></p></div><div class="detail-section"><h3>Structure &amp; approach</h3><span class="tag">${escapeHTML(t.feature_type)}</span><span class="tag">${t.area_ids.length} linked reef area${t.area_ids.length === 1 ? "" : "s"}</span><p>${t.feature_type === "localized rocky target" ? "This marker identifies a more localized rocky feature to investigate." : "This marker is a starting position for searching a broader patch of reef."} The analysis uses a roughly 33-foot grid; it does not identify an individual boulder.</p><p>${t.area_ids.length ? "The shaded outline shows part of the mapped rough habitat to work across, not the entire reef. " : "No reef outline is linked to this marker. "}${t.drift_id ? "The dashed line follows the structure. Measure your drift first, then choose a setup position that carries your rig across it; either end may be appropriate." : "Use your sounder to locate relief and fish, then set a drift across the structure you find."} Check a nautical chart for your approach; these search geometries are not navigation routes.</p></div><a class="primary" id="download-target" href="downloads/targets/${t.id}.gpx" download="SkipperCast-${t.id}.gpx">↓ Export this spot + geometry</a><div class="detail-section"><h3>Source</h3><p>${areaNames[t.source_id]} · USGS survey ${t.survey_year}<br>Research screen ${atlas.source_validation_date}</p><a href="${t.source_url}" target="_blank" rel="noopener">Open survey record ↗</a></div>`;
  $("export-selected").href = `downloads/targets/${t.id}.gpx`;
  $("export-selected").download = `SkipperCast-${t.id}.gpx`;
  const noteSection = document.createElement("div");
  noteSection.className = "detail-section";
  const metrics = t.metrics;
  noteSection.innerHTML = `<h3>Why this terrain ranks here</h3>${[
    [
      "Local relief",
      `${(metrics.relief_210m_m * 3.28084).toFixed(0)} ft`,
      Math.min(metrics.relief_210m_m / 15, 1),
      35,
      "Local height change. Full credit at about 49 ft (15 m); this is not boulder height.",
    ],
    [
      "Rough / bedrock cover",
      `${Math.round(metrics.rugose_or_bedrock_fraction_210m * 100)}%`,
      metrics.rugose_or_bedrock_fraction_210m,
      30,
      "The fraction of the local neighborhood classified as rough seabed or bedrock.",
    ],
    [
      "Seabed unevenness",
      `${(metrics.plane_residual_rms_250m_m * 3.28084).toFixed(1)} ft RMS`,
      Math.min(metrics.plane_residual_rms_250m_m / 3, 1),
      20,
      "Variation after removing the overall slope. A smooth steep slope does not earn complexity points; full credit at 9.8 ft (3 m) RMS.",
    ],
    [
      "Nearby rough habitat",
      `${(metrics.rough_habitat_within_250m_ha * 2.47105).toFixed(1)} acres`,
      Math.min(metrics.rough_habitat_within_250m_ha / 10, 1),
      15,
      "Mapped rough habitat within an 820-foot radius. Full credit at 24.7 acres (10 ha), so area alone cannot earn an A.",
    ],
  ]
    .map(
      ([label, value, fraction, weight, explanation]) =>
        `<div class="metric-row"><div><span>${label}</span><strong>${value}</strong></div><div class="meter"><span style="width:${Math.round(fraction * 100)}%"></span></div><span class="score-points">${(fraction * weight).toFixed(1)} of ${weight} points</span><p class="small metric-explanation">${explanation}</p></div>`,
    )
    .join(
      "",
    )}<p class="small">The weighted contributions sum to the terrain score, rounded to a whole number. This formula has not been validated against catches; a higher score does not guarantee better fishing. <a href="sources.html#grades">Full grading method.</a></p>`;
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
}

async function initAISContext() {
  const panel = $("ais-context");
  try {
    const response = await fetch("data/ais-evidence.json");
    if (!response.ok)
      throw new Error(`AIS summary request failed (${response.status})`);
    const evidence = await response.json();
    const count = evidence.summary;
    panel.innerHTML = `<p><strong>There are currently no verified charter hotspot markers.</strong> A/B/C marks terrain quality; numbered clusters count nearby reef candidates. They do not show boat visits.</p><p><strong>Archive samples obtained; no verified local sportfishing-charter tracks yet.</strong> The current map has no charter-activity overlay. Its A/B/C grades use terrain only.</p><div class="evidence-counts"><span>${count.sample_days} sampled UTC dates</span><span>${count.regional_records.toLocaleString()} regional AIS records</span><span>${count.unique_mmsi} vessel identifiers</span><span>${count.verified_local_sportfishing_charters} verified sportfishing charters</span></div><p>Research checked ${escapeHTML(evidence.audit_date_pacific)}. Sample dates: ${evidence.daily_samples.map((sample) => escapeHTML(sample.day_utc)).join(", ")}. June 27–30 consists of four consecutive daily files; the other dates are isolated samples. This is a limited search, not a season-wide charter history.</p><p>At this dated audit, the checked NOAA daily index listed broadcasts through ${escapeHTML(evidence.archive.latest_listed_broadcast_date)}. Vessel-name screening found no matches to the researched local fleet. Missing, changing, or differently reported identities and receiver coverage can hide trips; absence here does not mean charters never fish these areas.</p>`;
    panel.insertAdjacentHTML(
      "beforeend",
      '<details><summary>Where charters have publicly reported fishing</summary><p>A first-hand June 10, 2019 report aboard the Fiesta describes Cape San Martin / southern Big Sur, with an initial stop in 280 ft followed by a shallower lingcod search. This is historical, broad-area evidence outside the Avila–Cambria / 200-ft bottom-fishing scope. It does not locate a current hotspot.</p><a href="https://wonews.com/a-trip-to-lingcod-alley/" target="_blank" rel="noopener">Read the dated Fiesta trip report ↗</a><p>Exact within-scope charter fishing positions remain unverified. Repeated visits require an independently identified vessel and complete timed tracks; reported catches alone do not provide GPS positions.</p></details>',
    );
  } catch (error) {
    panel.innerHTML =
      '<p class="error">The dated AIS research summary could not load. Charter activity remains unverified; see <a href="sources.html#ais">sources and coverage</a>.</p>';
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
        $("species-select").value = "rockfish";
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
  if (speciesUI?.fit()) {
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

try {
  const response = await fetch("data/atlas.json");
  if (!response.ok)
    throw new Error(`Atlas request failed (${response.status})`);
  atlas = await response.json();
  initMap();
  speciesUI = await initSpecies(map, layers, {
    onChange: () => {
      filterTargets();
      fitTargets();
      weather?.setSpecies($("species-select").value);
    },
    onConditions: (p) => {
      weather?.selectLocation(p);
      navigation.showView("forecast");
    },
    showGuide: () => navigation.showView("guide"),
    onSelect: (html, area) => {
      selected = undefined;
      weather?.selectLocation(area);
      $("detail").innerHTML = html;
      $("export-selected").hidden = true;
      $("area-weather").addEventListener("click", () =>
        navigation.showView("forecast"),
      );
      navigation.setHasSelection(true);
      navigation.openDetails();
    },
  });
  filterTargets();
  map.on("zoomend", () => {
    if (atlas) {
      drawHabitat();
      speciesUI?.draw();
    }
  });
  fitTargets();
  weather = initWeather(map, layers.forecast, () =>
    navigation.showView("forecast"),
  );
  if (selected) weather.selectLocation(selected);
  registerTools();
} catch (error) {
  $("map-empty").hidden = false;
  $("map-empty").innerHTML =
    '<strong>Atlas unavailable</strong><p>Refresh to try again, or use the <a href="downloads/complete.gpx">GPX download</a>.</p>';
  console.error(error);
}
