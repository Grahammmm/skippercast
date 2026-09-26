import { assetURL } from "./region.js?v=8.12";
import { loadDailyEvidence, reportEvidence } from "./bite-evidence.js?v=8.12";
import { matchesTargetSpecies } from "./target-groups.js?v=8.12";
const $ = (id) => document.getElementById(id);
const esc = (s) =>
  String(s ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const date = (s) =>
  new Date(`${s}T12:00:00Z`).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    timeZone: "UTC",
  });
const boatIcon =
  '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 13h18l-3 6H7zM7 13V8h10v5M10 8V4h4v4M3 21c2-2 4 2 6 0s4 2 6 0 4 2 6 0"/></svg>';

export function matchingGrounds(
  grounds,
  { species, area = "all", depth = 200, search = "" },
) {
  const query = search.toLowerCase().trim();
  return grounds.filter(
    (g) =>
      g.precision !== "Broad regional name" &&
      g.map_species.some((id) => matchesTargetSpecies(id, species)) &&
      g.reports.some((r) => r.species.some((id) => matchesTargetSpecies(id, species))) &&
      (area === "all" || area === g.source_id) &&
      g.depth_ft[1] <= depth &&
      `${g.id} ${g.label} ${g.reported_ground} ${g.boats.join(" ")}`
        .toLowerCase()
        .includes(query),
  );
}

export function reportSummary(ground, species) {
  const reports = ground.reports.filter((r) => r.species.some((id) => matchesTargetSpecies(id, species)));
  return {
    trips: reports.length,
    dates: new Set(reports.map((r) => r.date)).size,
    boats: [...new Set(reports.map((r) => r.boat))].sort(),
    latest:
      reports
        .map((r) => r.date)
        .sort()
        .at(-1) || null,
  };
}

export async function initCharterGrounds(
  map,
  layer,
  { onSelect, onTarget, showMap, toast, protectedAreas },
) {
  const chip = $("show-charter-grounds"),
    context = $("charter-ground-context");
  if (!assetURL("charters")) { chip.hidden=true; $("charter-status").querySelector("span").textContent="No charter grounds verified for this region"; context.textContent="No geographically specific charter evidence is published here yet."; return {draw(){}}; }
  let evidence;
  try {
    const r = await fetch(assetURL("charters"));
    if (!r.ok) throw Error(`Charter reports request failed (${r.status})`);
    evidence = await r.json();
  } catch (error) {
    chip.hidden = true;
    $("charter-status").querySelector("span").textContent =
      "Reports unavailable · see evidence";
    context.innerHTML =
      '<p class="error">The charter-report layer could not load. Refresh to retry. No charter positions have been inferred from missing data.</p>';
    console.error(error);
    return { draw() {} };
  }
  const grounds = evidence.grounds.filter(g => g.precision !== "Broad regional name");
  let current = [];
  function choose() {
    return matchingGrounds(grounds, {
      species: $("species-select").value,
      area: $("area").value,
      depth: Number($("depth").value),
      search: $("search").value,
    }).filter(g => protectedAreas.pointAllowed(g) && protectedAreas.geometryAllowed(g.geometry));
  }
  function fit(items, separate = false) {
    if (!items.length) return false;
    map.invalidateSize({ pan: false });
    const h = map.getSize().y;
    if (separate) {
      // Fitting full outlines can leave nearby labels in the same cluster.
      const positions = L.latLngBounds(
        items.map((g) => [g.latitude, g.longitude]),
      );
      map.setView(positions.getCenter(), Math.max(13, map.getZoom() + 1));
    } else {
      map.fitBounds(
        L.featureGroup(items.map((g) => L.geoJSON(g.geometry))).getBounds(),
        {
          paddingTopLeft: [28, Math.min(140, h * 0.28)],
          paddingBottomRight: [28, Math.min(150, h * 0.3)],
          maxZoom: 13,
        },
      );
    }
    return true;
  }
  function focus(items, separate = false) {
    $("map-options").close();
    showMap();
    $("layer-charters").checked = true;
    layer.addTo(map);
    requestAnimationFrame(() => fit(items, separate));
  }
  function select(g) {
    const species = $("species-select").value;
    const summary = reportSummary(g, species);
    const speciesName = species === "reef" ? "lingcod or rockfish" : species === "lingcod" ? "lingcod" : "rockfish";
    const boatFacts = g.boats.map((boat) => ({
      boat,
      count: g.reports.filter((r) => r.boat === boat).length,
      url: g.reports.find((r) => r.boat === boat).boat_source_url,
    }));
    const html = `<div class="eyebrow charter-ink">CHARTER-REPORTED GROUND · ${esc(g.precision)}</div>
      <h2>${esc(g.label)}</h2>
      <p class="charter-lead"><strong>${g.report_count} reported trips · ${g.boats.length} boat${g.boats.length === 1 ? "" : "s"}</strong><br>Latest report ${date(g.latest_report)}</p>
      <p class="evidence-note charter-note"><strong>Reported area, exact stops unknown.</strong><br>Captains named “${esc(g.reported_ground)}”; they did not publish GPS positions or fishing depths. Purple shows our approximate search water, not a boat track or a confirmed reef.</p>
      <div class="stats"><div class="stat"><span>Trips reporting ${speciesName}</span><strong>${summary.trips}</strong><span>on ${summary.dates} dates</span></div><div class="stat"><span>Outline survey depths</span><strong>${g.depth_ft.join("–")} ft</strong><span>${g.survey_year} · MLLW</span></div></div>
      <div id="charter-recent-evidence" class="evidence-note"><p class="small">Checking recent reports for this named ground…</p></div>
      <p>${esc(g.approach)}</p>
      <button id="charter-weather" class="primary">Conditions for this area ↗</button>
      <details class="detail-section" open><summary>Boats & dated reports</summary>
      <p class="small">${g.report_count} single-ground reports across ${g.report_dates.length} dates (${date(g.report_dates[0])}–${date(g.latest_report)}). Report counts are not catch rates or a popularity ranking.</p>
      <div class="charter-boats">${boatFacts.map((b) => `<a href="${esc(b.url)}" target="_blank" rel="noopener">${esc(b.boat)} <span>${b.count} report${b.count === 1 ? "" : "s"} ↗</span></a>`).join("")}</div>
      <details class="charter-report-history"><summary>Read all ${g.report_count} source reports</summary><ul>${g.reports.map((r) => `<li><a href="${esc(r.source_url)}" target="_blank" rel="noopener">${date(r.date)} · ${esc(r.boat)} ↗</a><span>${r.species.map((s) => (s === "rockfish" ? "Rockfish" : s[0].toUpperCase() + s.slice(1))).join(" · ")}</span></li>`).join("")}</ul></details></details>
      <details class="detail-section"><summary>Find structure in this search area</summary><p>These are separate surveyed habitat candidates inside our outline. No published report identifies any of them as an actual charter stop.</p>
      <div class="charter-reef-links">${
        g.nearby_target_ids
          .slice(0, 4)
          .map(
            (id) =>
              `<button data-charter-target="${id}">${id} · inspect reef →</button>`,
          )
          .join("") || "No surveyed reef candidates inside this outline."
      }</div><p class="small">Top terrain scores shown first. Check sonar and present depth at the spot.</p></details>
      <details class="detail-section"><summary>Outline accuracy, access & sources</summary><p><strong>Location precision: ${esc(g.location_confidence)}.</strong> ${esc(g.boundary_note)}</p>
      <p>${g.area_km2} km² of retained search water. Depths come from the survey, not the charter reports. Gaps preserve deep water, missing survey coverage and exclusions. The dated closure screen includes a 505 m planning margin; this is not a live legal-access layer.</p>
      <p><a href="${esc(g.survey_source)}" target="_blank" rel="noopener">USGS depth survey ↗</a> · <a href="${esc(g.anchor_source)}" target="_blank" rel="noopener">Geographic reference ↗</a></p>
      <p><a href="https://wildlife.ca.gov/Fishing/Ocean/Regulations/Fishing-Map/Central" target="_blank" rel="noopener">Current CDFW rules ↗</a> · <a href="https://wildlife.ca.gov/Conservation/Marine/MPAs/Point-Buchon" target="_blank" rel="noopener">Point Buchon MPAs ↗</a> · <a href="https://www.ecfr.gov/current/title-33/section-165.1155" target="_blank" rel="noopener">Diablo security zone ↗</a></p>
      <p>Research checked ${date(evidence.audit_date)}. This sample supports prior reported use of a named ground, not current fish presence. AIS-confirmed visits remain unavailable. <a href="sources.html#charter-reports">Full method and coverage</a>.</p></details>`;
    onSelect(html, g);
    const recentHost = $("charter-recent-evidence");
    loadDailyEvidence()
      .then(({ data, fallback }) => {
        if (!recentHost?.isConnected) return;
        const recent = reportEvidence(data, species, Date.now(), g.id);
        recentHost.innerHTML = `<strong>Recent ${esc(speciesName)} evidence · ${recent.confidence}</strong><p>${recent.reports.length} positive reports from ${recent.boats} boat${recent.boats === 1 ? "" : "s"} naming this ground, ${date(recent.start)}–${date(recent.end)}. ${esc(recent.reason)}</p><p class="small">${fallback ? "Saved snapshot. " : "Updated by the daily data feed. "}No exact charter stops are inferred. The historical totals above remain a separate dated audit.</p>`;
      })
      .catch(() => {
        if (recentHost?.isConnected)
          recentHost.textContent =
            "Recent report feed unavailable; the historical audit above is unchanged.";
      });
    for (const button of document.querySelectorAll("[data-charter-target]"))
      button.addEventListener("click", () =>
        onTarget(button.dataset.charterTarget),
      );
  }
  function draw() {
    layer.clearLayers();
    current = choose();
    const bottom = ["reef", "lingcod", "rockfish"].includes($("species-select").value);
    chip.hidden = !bottom;
    chip.innerHTML = `${boatIcon}<span>${current.length ? `Charter grounds · ${current.length}` : "Charter grounds · filtered"}</span>`;
    chip.setAttribute(
      "aria-label",
      current.length
        ? `Show ${current.length} charter-reported grounds on the map`
        : "Charter grounds hidden by filters; open options",
    );
    if (current.length && $("layer-charters").checked)
      $("map-empty").hidden = true;
    for (const g of current) {
      L.geoJSON(g.geometry, {
        pane: "charterAreas",
        style: {
          color: "#7540a0",
          weight: 2.5,
          fillColor: "#9256bb",
          fillOpacity: 0.085,
          dashArray: g.precision === "Broad regional name" ? "3 7" : "9 5",
        },
      })
        .on("click", () => select(g))
        .addTo(layer);
    }
    const groups = [];
    for (const g of current) {
      const p = map.project([g.latitude, g.longitude], map.getZoom());
      const group =
        map.getZoom() < 13 &&
        groups.find(
          (a) => Math.abs(a.p.x - p.x) < 150 && Math.abs(a.p.y - p.y) < 60,
        );
      if (group) group.items.push(g);
      else groups.push({ p, items: [g] });
    }
    for (const { items } of groups) {
      const g = items[0],
        single = items.length === 1;
      const label = single ? g.label : `${items.length} charter grounds`;
      const subtitle = single
        ? g.precision === "Broad regional name"
          ? "Regional reports"
          : `${g.report_count} reported trips`
        : "Tap to explore";
      L.marker([g.latitude, g.longitude], {
        zIndexOffset: 1200,
        icon: L.divIcon({
          className: "charter-pin",
          html: `${boatIcon}<span>${esc(label)}<small>${subtitle}</small></span>`,
          iconSize: [158, 52],
          iconAnchor: [79, 26],
        }),
        title: `${label} · ${subtitle} · approximate reported area`,
        keyboard: true,
      })
        .on("click", () => (single ? select(g) : focus(items, true)))
        .addTo(layer);
    }
  }
  map.createPane("charterAreas").style.zIndex = 390;
  chip.addEventListener("click", () => {
    if (current.length) focus(current);
    else {
      $("map-options").showModal();
      toast("Widen your area, search or depth filter to show charter grounds.");
    }
  });
  $("layer-charters").addEventListener("change", draw);
  const c = evidence.coverage;
  $("charter-status").querySelector("span").textContent =
    `${grounds.length} named vicinities · no verified charter AIS ↗`;
  context.innerHTML = `<p><strong>Purple boat labels and dashed outlines identify charter-reported grounds.</strong> These are named areas from published trip records, not AIS-confirmed fishing positions. A/B/C reef grades remain separate.</p><div class="charter-ground-links">${grounds.map((g) => `<button data-charter-ground="${g.id}"><strong>${esc(g.label)}</strong><span>${g.report_count} trips · ${g.boats.length} boat${g.boats.length === 1 ? "" : "s"} · latest ${date(g.latest_report)} →</span><small>${esc(g.precision)}</small></button>`).join("")}</div><p>Reviewed ${c.dates_available} daily pages from ${date(c.from)} through ${date(c.through)}: ${c.local_trips} local trip records, including ${grounds.reduce((sum,g)=>sum+g.report_count,0)} single-ground reports in these two named vicinities. Broad Morro Bay and “Out Front” reports are retained as regional evidence but have no map outline. The ${c.ground_counts["Out Front"]} “Out Front” records are too vague to locate; other named grounds fall outside Avila–Cambria. Multi-ground trips are not allocated to a single area.</p><p class="small">The outlines are our survey-depth-screened search windows, not published charter boundaries. Only lingcod and rockfish are supported by this layer. No present bite or catch probability is inferred. <a href="sources.html#charter-reports">Method, coverage and source data ↗</a></p><h3>Separate AIS research</h3>`;
  for (const button of context.querySelectorAll("[data-charter-ground]")) {
    button.addEventListener("click", () => {
      const ground = grounds.find((g) => g.id === button.dataset.charterGround);
      $("species-select").value = "reef";
      $("search").value = "";
      $("area").value = "all";
      $("depth").value = "200";
      $("species-select").dispatchEvent(new Event("change"));
      focus([ground]);
    });
  }
  return { draw, fit: () => $("layer-charters").checked && fit(current) };
}
