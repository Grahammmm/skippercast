import { targetGPX } from "./gpx.js";
import { initWeather } from "./weather-ui.js";
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
let atlas,
  map,
  selected,
  visible = [];
const layers = {},
  markers = new Map();

function initMap() {
  map = L.map("map", { zoomControl: false, minZoom: 7, maxZoom: 18 }).setView(
    [35.36, -120.95],
    10,
  );
  L.control.zoom({ position: "topright" }).addTo(map);
  L.control
    .scale({ imperial: true, metric: false, position: "bottomright" })
    .addTo(map);
  const tiles = L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution:
      '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
  }).addTo(map);
  let failed = false;
  tiles.on("tileerror", () => {
    if (!failed) {
      failed = true;
      toast(
        "Base map unavailable. Habitat layers and coordinates remain available.",
      );
    }
  });
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
    html: `<span class="pin-content ${target.habitat_grade} ${selected?.id === target.id ? "selected" : ""}">${target.habitat_grade}</span>`,
    iconSize: [28, 28],
    iconAnchor: [14, 14],
  });
}

function filterTargets() {
  const search = $("search").value.toLowerCase().trim();
  visible = atlas.targets
    .filter(
      (t) =>
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
  $("result-count").textContent =
    `${visible.length} target${visible.length === 1 ? "" : "s"}`;
  $("target-list").innerHTML = visible.length
    ? visible
        .map(
          (t) =>
            `<button class="target-card" data-target="${t.id}" aria-pressed="${selected?.id === t.id}"><span class="grade ${t.habitat_grade}">${t.habitat_grade}</span><span><strong>${escapeHTML(t.label)}</strong><span class="meta">${t.center_depth_ft} ft · ${t.habitat_score}/100 terrain${t.drift_id ? " · drift line" : ""}</span><span class="id">${t.id} · ${areaNames[t.source_id]}</span></span></button>`,
        )
        .join("")
    : '<p class="no-results">No targets match. Try another area, grade, or depth.</p>';
  drawHabitat();
  if (selected) selectTarget(selected.id, false);
}

function drawHabitat() {
  for (const name of ["targets", "areas", "drifts"]) layers[name].clearLayers();
  markers.clear();
  const ids = new Set(visible.map((t) => t.id));
  for (const a of atlas.areas.filter((a) =>
    a.target_ids.some((id) => ids.has(id)),
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
  for (const d of atlas.drifts.filter((d) => ids.has(d.target_id))) {
    L.geoJSON(d.geometry, {
      style: { color: "#a66310", weight: 3, dashArray: "8 5" },
    })
      .bindTooltip(`${d.id} · ${Math.round(d.length_m)} m structure alignment`)
      .on("click", () => selectTarget(d.target_id))
      .addTo(layers.drifts);
  }
  for (const t of visible) {
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

function selectTarget(id, pan = true) {
  const target = atlas.targets.find((t) => t.id === id);
  if (!target) return;
  selected = target;
  for (const t of visible) markers.get(t.id)?.setIcon(pin(t));
  for (const button of document.querySelectorAll("[data-target]"))
    button.setAttribute("aria-pressed", String(button.dataset.target === id));
  const t = selected;
  $("detail").innerHTML =
    `<button class="detail-close text-button" id="back-map">↑ Back to map</button><div class="detail-top"><span class="grade ${t.habitat_grade}">${t.habitat_grade}</span><div><div class="eyebrow">${t.id} · PRIORITY ${t.rank}</div><h2>${escapeHTML(t.label)}</h2></div></div><span class="coordinates">${t.latitude.toFixed(6)}, ${t.longitude.toFixed(6)}</span><p>${escapeHTML(t.terrain_interpretation)}</p><div class="stats"><div class="stat"><span>Center depth</span><strong>${t.center_depth_ft} ft</strong></div><div class="stat"><span>Terrain score</span><strong>${t.habitat_score}<small>/100</small></strong></div><div class="stat"><span>Nearby depths</span><strong>${t.neighborhood_depth_ft.join("–")}</strong><span>feet · survey MLLW</span></div><div class="stat"><span>Rough habitat</span><strong>${t.metrics.rough_habitat_within_250m_ha.toFixed(1)} ha</strong><span>within 250 m</span></div></div><div class="evidence-note"><p><strong>Mapped habitat candidate</strong><br>No verified catches or AIS-confirmed charter hotspot. Source confidence: ${escapeHTML(t.confidence)}.</p></div><div class="detail-section"><h3>Structure &amp; approach</h3><span class="tag">${escapeHTML(t.feature_type)}</span><span class="tag">${t.area_ids.length} linked reef area${t.area_ids.length === 1 ? "" : "s"}</span><p>${t.drift_id ? "An optional drift alignment is available. Set up according to the wind and current you measure on the water." : "Explore the surrounding mapped structure and find fish with your sounder."} These are search targets, not safe navigation routes.</p></div><button class="primary" id="download-target">↓ Export this target + geometry</button><div class="detail-section"><h3>Source</h3><p>${areaNames[t.source_id]} · USGS survey ${t.survey_year}<br>Research screen ${atlas.source_validation_date}</p><a href="${t.source_url}" target="_blank" rel="noopener">Open survey record ↗</a></div>`;
  $("back-map")?.addEventListener("click", () =>
    $("map").scrollIntoView({ block: "center" }),
  );
  $("download-target").addEventListener("click", () => downloadTarget(t.id));
  const noteSection = document.createElement("div");
  noteSection.className = "detail-section";
  const metrics = t.metrics;
  noteSection.innerHTML = `<h3>Why this terrain ranks here</h3>${[
    [
      "Local relief",
      `${(metrics.relief_210m_m * 3.28084).toFixed(0)} ft`,
      Math.min(metrics.relief_210m_m / 15, 1),
    ],
    [
      "Rough / bedrock cover",
      `${Math.round(metrics.rugose_or_bedrock_fraction_210m * 100)}%`,
      metrics.rugose_or_bedrock_fraction_210m,
    ],
    [
      "Terrain complexity",
      `${metrics.plane_residual_rms_250m_m.toFixed(1)} m RMS`,
      Math.min(metrics.plane_residual_rms_250m_m / 3, 1),
    ],
  ]
    .map(
      ([label, value, fraction]) =>
        `<div class="metric-row"><div><span>${label}</span><strong>${value}</strong></div><div class="meter"><span style="width:${Math.round(fraction * 100)}%"></span></div></div>`,
    )
    .join(
      "",
    )}<p class="small">Relief, rock cover, complexity, and habitat area contribute to the score. It does not measure individual boulder sizes.</p>`;
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
  if (pan) map.setView([t.latitude, t.longitude], Math.max(map.getZoom(), 14));
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
  if (pan && window.matchMedia("(max-width:1150px)").matches)
    $("detail").scrollIntoView({ block: "start" });
}

function downloadTarget(id) {
  const url = URL.createObjectURL(
    new Blob([targetGPX(atlas, id)], { type: "application/gpx+xml" }),
  );
  const a = document.createElement("a");
  a.href = url;
  a.download = `SkipperCast-${id}.gpx`;
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10000);
  toast("GPX prepared. On iPad, open the download and share it to iNavX.");
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
        filterTargets();
        selectTarget(input.target_id);
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
  if (visible.length)
    map.fitBounds(
      visible.map((t) => [t.latitude, t.longitude]),
      { padding: [40, 40], maxZoom: 14 },
    );
}
let toastTimer;
function toast(message) {
  $("toast").textContent = message;
  $("toast").hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => ($("toast").hidden = true), 6000);
}

$("about-button").addEventListener("click", () =>
  $("about-dialog").showModal(),
);
$("close-about").addEventListener("click", () => $("about-dialog").close());
$("fit-targets").addEventListener("click", fitTargets);
$("target-list").addEventListener("click", (e) => {
  const b = e.target.closest("[data-target]");
  if (b) selectTarget(b.dataset.target);
});
for (const id of ["search", "area", "grade", "depth", "geometry"])
  $(id).addEventListener(id === "search" ? "input" : "change", () => {
    if (atlas) filterTargets();
  });

try {
  const response = await fetch("data/atlas.json");
  if (!response.ok)
    throw new Error(`Atlas request failed (${response.status})`);
  atlas = await response.json();
  initMap();
  filterTargets();
  fitTargets();
  selectTarget(visible[0].id, false);
  initWeather(map, layers.forecast);
  registerTools();
} catch (error) {
  $("result-count").textContent = "Atlas unavailable";
  $("target-list").innerHTML =
    '<p class="error">The atlas could not load. Refresh the page, or use the GPX and offline notes from the download links.</p>';
  console.error(error);
}
