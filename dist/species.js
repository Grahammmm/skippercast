import { POINTS, distanceNm } from "./marine-data.js?v=4.1";
const $ = (id) => document.getElementById(id);
const fishSource = {
  title: "CDFW · California fish habitat",
  url: "https://wildlife.ca.gov/Conservation/Marine/Life-History-Fish",
};
const rules = {
  title: "CDFW · current Central Coast regulations",
  url: "https://wildlife.ca.gov/Fishing/Ocean/Regulations/Fishing-Map/Central",
};
export const PROFILES = {
  lingcod: {
    name: "Lingcod",
    short: "Raised rock & reef edges",
    kind: "reef",
    habitat:
      "Adults use rocky reefs and kelp habitat, as well as other bottom types. Here the map prioritizes rough rock with relief; it does not resolve individual boulders.",
    approach:
      "Sound the high point and its edges. Set a test drift, keep the rig near the bottom, and reset when line angle prevents reliable contact. A structure line is an alignment to cross, not a predicted drift.",
    conditions:
      "Choose manageable wind and chop so you can hold bottom and reset accurately. A bigger swell or current is not evidence of a better bite. Surface current forecasts cannot set your sinker weight.",
    map: "Subset of the rocky atlas: at least 3 m of local relief and 60% rough cover. This is a transparent search preference, not a validated species score.",
    season:
      "Season and depth access are regulated. Check Central Management Area groundfish rules and in-season changes before each trip.",
    unknown:
      "Bottom current, bait, kelp cover, fishing pressure, and fish presence are not measured here.",
    sources: [fishSource, rules],
  },
  rockfish: {
    name: "Rockfish / rock cod",
    short: "Rocky habitat, different niches",
    kind: "reef",
    habitat:
      "Rockfish are many species, not one habitat preference. Some school above reefs; others stay close to rock, kelp, or sediment edges. This layer covers the rocky-habitat subset within 200 ft.",
    approach:
      "Watch the sounder through the water column as well as near bottom. Work a short controlled pass over relief, then adjust to marks. Identify each fish: similar-looking species have different limits.",
    conditions:
      "Comfort and control matter more than a universal temperature or tide recipe. Short-period chop and a fast drift make precise presentations harder; test the drift at the actual reef.",
    map: "All 132 published rocky targets. A/B/C describes mapped terrain only. The larger reef does not automatically hold more fish.",
    season:
      "Check current species sublimits, prohibited species, depth rules, and descending-device requirements.",
    unknown:
      "No species-level catch model or confirmed charter hotspot is available.",
    sources: [
      fishSource,
      rules,
      {
        title: "CDFW · groundfish",
        url: "https://wildlife.ca.gov/Fishing/Ocean/Regulations/Groundfish-Summary",
      },
    ],
  },
  halibut: {
    name: "California halibut",
    short: "Shallow soft bottom",
    kind: "soft",
    habitat:
      "California halibut are ambush predators of the inner shelf and estuaries. CDFW reports most angler catches in 10–90 ft. This is California halibut, not the separate Pacific halibut fishery.",
    approach:
      "Search sand or mud with bait nearby. Start with a controlled bottom presentation, measure the drift, and move when bait or bottom contact is absent. These survey circles contain soft sediment, not a verified bite.",
    conditions:
      "Light wind and modest boat motion help maintain a consistent near-bottom presentation. Water clarity and local prey matter, but this app does not measure them. No universal ideal tide or drift speed is established.",
    map: "Only native-survey-checked soft-bottom circles whose full depth range is at most 100 ft. Shallow water inside the surf zone is deliberately not proposed.",
    season:
      "The Central Coast summary lists year-round access, subject to MPAs and current rules. Confirm species, size, and bag limits.",
    unknown:
      "Sand can shift since the 2008 survey. Surface temperature is not bottom temperature.",
    sources: [
      {
        title: "CDFW · California halibut research",
        url: "https://wildlife.ca.gov/Conservation/Marine/Nearshore",
      },
      rules,
    ],
  },
  salmon: {
    name: "Chinook salmon",
    short: "Find forage in the water column",
    kind: "pelagic",
    habitat:
      "Ocean Chinook follow feeding opportunities and migrate. Adult fish eat other fish; a fixed rock coordinate is a weak substitute for current forage and fish observations.",
    approach:
      "Use recent legal-season reports, bait schools, birds, and sonar to choose trolling water and depth. The three coastal circles are forecast/search reference areas, not salmon sightings or troll routes.",
    conditions:
      "Choose a sea state that permits controlled trolling and a comfortable return. Cold productive ocean conditions can support the food web; juvenile-survival studies do not establish a precise adult fishing-temperature optimum.",
    map: "Coastal search reference areas replace reef pins. Fishing depth is in the water column; the circles have no surveyed bottom-depth guarantee.",
    season:
      "Checked Sep 21, 2026: south of Pigeon Point scheduled Sep 1–30, subject to early harvest closure. This dated note is not live permission. Check the salmon page on the trip day.",
    unknown:
      "No live bait, salmon reports, thermocline, or migration forecast is integrated.",
    sources: [
      {
        title: "NOAA · Chinook salmon ecology",
        url: "https://www.fisheries.noaa.gov/species/chinook-salmon",
      },
      {
        title: "NOAA · ocean indicators and juvenile salmon",
        url: "https://www.fisheries.noaa.gov/west-coast/science-data/local-physical-indicators",
      },
      {
        title: "CDFW · current salmon season",
        url: "https://wildlife.ca.gov/Fishing/Ocean/Regulations/Salmon",
      },
    ],
  },
  albacore: {
    name: "Albacore tuna",
    short: "Offshore forage & temperature boundaries",
    kind: "offshore",
    habitat:
      "Albacore are highly mobile. NOAA describes temperature as a distribution driver and juveniles as associated with oceanic fronts. Migration timing changes with ocean conditions.",
    approach:
      "Use the sea-temperature layer to compare water masses, then verify bait, birds, color changes, and fish locally. Broad forecast samples are starting references; they do not locate a sharp front or a school.",
    conditions:
      "A light morning nearshore does not establish a comfortable offshore day. Inspect offshore wind, crossing swell, and return hours. Temperature alone never earns a fishing-quality score.",
    map: "Nine explicitly constructed offshore search sectors replace bottom targets. Centers are forecast samples, not historical catches. They extend beyond the 200-foot bottom-fishing scope.",
    season:
      "Check current tuna regulations. Availability off Morro Bay varies with the ocean; the calendar does not guarantee accessible fish.",
    unknown:
      "No satellite front analysis, chlorophyll, bait observations, or current tuna catch locations are included. SST is modeled at about 8 km.",
    sources: [
      {
        title: "NOAA · Pacific albacore ecology",
        url: "https://www.fisheries.noaa.gov/species/pacific-albacore-tuna",
      },
      {
        title: "NOAA · albacore essential habitat",
        url: "https://www.fisheries.noaa.gov/inport/item/80237",
      },
      rules,
    ],
  },
  bluefin: {
    name: "Pacific bluefin tuna",
    short: "Mobile offshore prey search",
    kind: "offshore",
    habitat:
      "Pacific bluefin range widely through temperate and other ocean waters and feed on fish and squid. A single warm-water cutoff is too simplistic for this species.",
    approach:
      "Prioritize fresh, credible fish and bait reports, birds, and sonar. Compare temperature patterns as context. These are the same geographic search sectors as albacore, with different biological guidance; they are not evidence that either species is there.",
    conditions:
      "Plan for the exposed return and extended search time. Check wind and seas at every hour you could be offshore. Do not assume a 20-knot cruise is maintainable in the forecast sea.",
    map: "Broad offshore planning sectors; no catch-based rank, bottom-depth limit, or navigable route is implied.",
    season:
      "Bluefin rules differ from other tunas. Verify current limits and identification before fishing.",
    unknown:
      "Fish locations, size, tackle suitability, forage, and subsurface temperatures are not measured.",
    sources: [
      {
        title: "NOAA · Pacific bluefin ecology",
        url: "https://www.fisheries.noaa.gov/species/pacific-bluefin-tuna",
      },
      {
        title: "NOAA · bluefin essential habitat",
        url: "https://www.fisheries.noaa.gov/inport/item/80247",
      },
      rules,
    ],
  },
  dungeness: {
    name: "Dungeness crab",
    short: "Soft sediment & gear access",
    kind: "soft",
    habitat:
      "Dungeness use soft-bottom habitat, including sand and mud. This layer includes mapped soft-sediment circles within the 200-foot planning limit; reef size is not its ranking criterion.",
    approach:
      "Confirm bottom, legal gear, and the full gear deployment and retrieval window. Avoid navigation channels and other gear. A seabed circle does not establish abundance or authorize a trap set.",
    conditions:
      "Manageable current, wind, and waves help with gear control and retrieval. The coarse surface-current model does not predict bottom current or trap movement.",
    map: "Native-depth-checked soft-bottom windows replace the rocky targets. No A/B/C catch grade is assigned.",
    season:
      "Checked Sep 21, 2026: closed locally; scheduled reopening Nov 7, subject to changes. Habitat remains visible for future planning. Check whale-risk gear restrictions and health advisories before crabbing.",
    unknown:
      "No crab abundance, molt condition, bottom current, or live gear-closure feed is integrated.",
    sources: [
      {
        title: "CDFW · Dungeness habitat and monitoring",
        url: "https://marinespecies.wildlife.ca.gov/dungeness-crab/monitoring/",
      },
      rules,
      {
        title: "CDFW · whale-safe fishery status",
        url: "https://wildlife.ca.gov/Conservation/Marine/Whale-Safe-Fisheries",
      },
    ],
  },
};
export function matchesSpecies(target, id) {
  if (id === "rockfish") return true;
  return (
    id === "lingcod" &&
    target.metrics.relief_210m_m >= 3 &&
    target.metrics.rugose_or_bedrock_fraction_210m >= 0.6
  );
}
const escapeHTML = (v) =>
  String(v ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
export async function initSpecies(
  map,
  layers,
  { onChange, onConditions, showGuide },
) {
  let habitats = [],
    error = false,
    current = [];
  try {
    const r = await fetch("data/species-habitat.json");
    if (!r.ok) throw Error();
    habitats = (await r.json()).areas;
  } catch {
    error = true;
  }
  const port = { latitude: 35.3667, longitude: -120.868 };
  const id = () => $("species-select").value;
  function guide() {
    const p = PROFILES[id()];
    $("species-guide").innerHTML =
      `<div class="eyebrow">SPECIES FIELD NOTES · RESEARCHED SEP 21, 2026</div><h2>${p.name}</h2><p class="guide-lead">${p.short}</p><div class="field-note-grid">${[
        ["Habitat", p.habitat],
        ["What to look for", p.approach],
        ["Conditions that help", p.conditions],
        ["What changes on the map", p.map],
        ["Season & access", p.season],
        ["What we still cannot see", p.unknown],
      ]
        .map(([h, t]) => `<div><h3>${h}</h3><p>${t}</p></div>`)
        .join(
          "",
        )}</div><p><strong>Habitat fit, fishing control, and boat comfort are separate.</strong> There is no supported universal recipe for “perfect” fishing. Favorable conditions improve presentation and comfort, not guaranteed catches.</p><p class="source-links">${p.sources.map((s) => `<a href="${s.url}" target="_blank" rel="noopener">${s.title} ↗</a>`).join("")}</p><p class="small"><a href="species-research.html">Research, methods, and limitations ↗</a></p>`;
    $("species-list-guide").innerHTML =
      `<label>Target species<select id="list-species">${Object.entries(PROFILES)
        .map(
          ([key, v]) =>
            `<option value="${key}" ${key === id() ? "selected" : ""}>${v.name}</option>`,
        )
        .join(
          "",
        )}</select></label><p>${p.short}. <a href="#guide">Read field notes ↗</a></p>`;
    $("list-species").addEventListener("change", (e) => {
      $("species-select").value = e.target.value;
      refresh();
      onChange();
    });
    $("species-list-context").textContent =
      p.kind === "reef"
        ? "Surveyed rocky habitat · ≤200 ft"
        : p.kind === "soft"
          ? "Surveyed soft-sediment windows · ≤200 ft"
          : "Search references · fish locations unverified";
    document.querySelector(".map-banner").hidden = p.kind !== "reef";
    $("species-season").hidden = !["salmon", "dungeness"].includes(id());
    $("species-season").textContent =
      id() === "dungeness"
        ? "Closed in Sep 21 record · check current season"
        : id() === "salmon"
          ? "Season can close early · check CDFW today"
          : "";
    document.querySelector(".side-foot").textContent =
      p.kind === "reef"
        ? "Terrain grades are not catch predictions."
        : "Search areas are not confirmed catches.";
    $("filter-options").hidden = !["reef", "soft"].includes(p.kind);
    for (const control of ["grade", "geometry"])
      $(control).disabled = p.kind !== "reef";
  }
  function chooseAreas() {
    const p = PROFILES[id()];
    if (p.kind === "soft")
      return habitats.filter(
        (a) =>
          a.species.includes(id()) &&
          a.depth_ft[1] <= Number($("depth").value) &&
          ($("area").value === "all" || a.source_id === $("area").value) &&
          `${a.id} ${a.label}`
            .toLowerCase()
            .includes($("search").value.toLowerCase().trim()),
      );
    if (p.kind === "offshore")
      return POINTS.filter((p) => p.offshore).map((p) => ({
        ...p,
        label: p.name,
        radius_m: 5500,
        kind: "search",
      }));
    if (p.kind === "pelagic")
      return POINTS.slice(0, 3).map((p) => ({
        ...p,
        label: p.name + " forage search",
        radius_m: 1800,
        kind: "search",
      }));
    return [];
  }
  function selectArea(a) {
    const container = document.createElement("div");
    container.className = "species-popup";
    const dist = distanceNm(port, a),
      off = PROFILES[id()].kind === "offshore";
    container.innerHTML = `<div class="eyebrow">${a.kind === "search" ? "SEARCH REFERENCE" : "SOFT SEDIMENT"}</div><h3>${escapeHTML(a.label)}</h3><p>${a.latitude.toFixed(4)}, ${a.longitude.toFixed(4)}</p><p>${a.depth_ft ? `${a.depth_ft.join("–")} ft MLLW · ${a.soft_bottom_percent}% mapped soft sediment. Partial 200 m search window.` : "Constructed search sector centered on a weather sample. No catch evidence or bottom-depth assurance."}</p>${off ? `<p>At least ${dist.toFixed(1)} nm from the harbor entrance; ≥${Math.ceil((dist / 20) * 60)} min each way at 20 kt. Straight-line lower bound only: charted route, harbor travel, sea-state slowdown, search, and reserve are additional.</p>` : ""}<p class="small">${a.evidence || "Use current forage and fish evidence to choose where to fish. The circle is not a navigation route or MPA screen."}</p>${id() === "dungeness" ? '<p class="error">Season closed in the Sep 21 research. Check current access.</p>' : ""}${a.source_url ? `<a href="${a.source_url}" target="_blank" rel="noopener">USGS survey source ↗</a>` : ""}<button class="primary">Weather at nearest sample ↗</button>`;
    container
      .querySelector("button")
      .addEventListener("click", () => onConditions(a));
    L.popup({ maxWidth: 320 })
      .setLatLng([a.latitude, a.longitude])
      .setContent(container)
      .openOn(map);
  }
  function draw() {
    const p = PROFILES[id()];
    if (p.kind === "reef") return;
    current = chooseAreas();
    $("map-empty").hidden = current.length > 0;
    if (!current.length)
      $("map-empty").innerHTML =
        `<strong>${error ? "Habitat data unavailable" : "No areas in these filters"}</strong><p>${error ? "Refresh to try again." : "Try a wider area or depth filter."}</p>`;
    $("result-count").textContent =
      `${current.length} ${p.kind === "soft" ? "sediment windows" : "search sectors"}`;
    $("map-result-count").textContent = current.length;
    $("target-list").innerHTML = current
      .map(
        (a) =>
          `<button class="target-card search-card" data-search="${a.id}"><span class="search-symbol" aria-hidden="true">${p.kind === "soft" ? "◌" : "⌕"}</span><span><strong>${escapeHTML(a.label)}</strong><span class="meta">${a.depth_ft ? `${a.depth_ft.join("–")} ft · ${a.soft_bottom_percent}% soft sediment` : "Broad search reference · no catch rank"}</span><span class="id">${a.id}${p.kind === "offshore" ? ` · ≥${distanceNm(port, a).toFixed(0)} nm from entrance` : ""}</span></span></button>`,
      )
      .join("");
    const color = p.kind === "soft" ? "#ad7439" : "#9e5985";
    for (const a of current) {
      const area = a.geometry
        ? L.geoJSON(a.geometry, {
            style: { color, weight: 2, fillOpacity: 0.17 },
          })
        : L.circle([a.latitude, a.longitude], {
            radius: a.radius_m,
            color,
            weight: 1.5,
            dashArray: "6 6",
            fillOpacity: 0.07,
          });
      area.on("click", () => selectArea(a)).addTo(layers.areas);
      L.marker([a.latitude, a.longitude], {
        icon: L.divIcon({
          className: "search-marker",
          html: `<span aria-hidden="true">${p.kind === "soft" ? "S" : "?"}</span>`,
          iconSize: [36, 36],
          iconAnchor: [18, 18],
        }),
        title: a.label + " · unverified fish presence",
        keyboard: true,
      })
        .on("click", () => selectArea(a))
        .addTo(layers.targets);
    }
  }
  function fit() {
    if (PROFILES[id()].kind === "reef" || !current.length) return false;
    const h = map.getSize().y;
    map.fitBounds(
      current.map((p) => [p.latitude, p.longitude]),
      {
        paddingTopLeft: [40, Math.min(150, h * 0.25)],
        paddingBottomRight: [40, Math.min(270, h * 0.4)],
        maxZoom: 12,
      },
    );
    return true;
  }
  function refresh() {
    guide();
    map.closePopup();
  }
  $("species-select").addEventListener("change", () => {
    refresh();
    onChange();
  });
  $("species-info").addEventListener("click", showGuide);
  $("target-list").addEventListener("click", (e) => {
    const b = e.target.closest("[data-search]");
    if (b) {
      const a = current.find((a) => a.id === b.dataset.search);
      if (a) {
        location.hash = "#map";
        map.setView(
          [a.latitude, a.longitude],
          PROFILES[id()].kind === "offshore" ? 10 : 13,
        );
        selectArea(a);
      }
    }
  });
  refresh();
  return { draw, fit, refresh };
}
