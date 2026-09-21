import {
  POINTS,
  MODELS,
  HOUR,
  timeline,
  readConditions,
  comfort,
  directionTo,
  angleBetween,
  distanceNm,
  loadMarine,
} from "./marine-data.js?v=4.1";
import { esc, num, local, full, day } from "./marine-charts.js?v=4.1";
import { detailHTML } from "./marine-detail.js?v=4.1";
const $ = (id) => document.getElementById(id);
const colors = {
  calmer: "#278f87",
  mixed: "#be7a29",
  rough: "#c45d4e",
  hazard: "#b0395b",
  unknown: "#778995",
};

export function initWeather(map, layer, onOpen) {
  let bundle = null,
    hours = timeline(),
    index = 0,
    point = 1,
    family = "gfs",
    overlay = "waves",
    play = null,
    loading = false,
    requested = null,
    lastSpecies = "lingcod",
    heading = 0;
  const dock = $("map-time-dock");
  dock.innerHTML = `<div class="dock-controls"><label class="sr-only" for="ocean-layer">Ocean overlay</label><select id="ocean-layer"><option value="waves">Waves · ft</option><option value="wind">Wind · kt</option><option value="comfort">Comfort</option><option value="sst">Sea temp · °F</option><option value="none">Chart only</option></select><label class="sr-only" for="forecast-model">Forecast model</label><select id="forecast-model"><option value="gfs">NOAA GFS</option><option value="ecmwf">ECMWF</option></select><button id="ocean-now" class="text-button">Now</button></div><button id="map-weather-summary" class="map-weather-summary" aria-label="Open detailed weather and tide chart"><span>Loading ocean conditions…</span><span aria-hidden="true">↗</span></button><div class="time-heading"><button id="time-play" aria-label="Play hourly forecast">▶</button><strong id="map-time-label">Now · forecast</strong><span id="map-time-range">+7 days</span></div><label class="sr-only" for="map-time">Forecast hour, now to seven days</label><input id="map-time" type="range" min="0" max="168" step="1" value="0"/><div id="day-strip" class="day-strip" aria-label="Choose forecast date"></div><div id="overlay-legend" class="overlay-legend"></div>`;
  $("forecast-content").innerHTML =
    `<div class="marine-controls"><label>Forecast sample<select id="marine-point">${POINTS.map((s, i) => `<option value="${i}" ${i === point ? "selected" : ""}>${s.name}</option>`).join("")}</select></label><label>Model<select id="detail-model"><option value="gfs">NOAA GFS</option><option value="ecmwf">ECMWF</option></select></label><div><span id="detail-provisional" class="eyebrow">HOURLY FORECAST · PACIFIC TIME</span><strong id="detail-time-label"></strong></div></div><div class="detail-time"><button id="previous-hour" aria-label="Previous forecast hour">←</button><label class="sr-only" for="detail-hour">Forecast hour</label><input id="detail-hour" type="range" min="0" max="168" value="0" step="1"/><button id="next-hour" aria-label="Next forecast hour">→</button></div><div id="marine-detail-body"><p>Loading forecast sources…</p></div>`;
  for (const el of [
    dock,
    document.querySelector(".species-bar"),
    document.querySelector(".map-toolbar"),
  ]) {
    L.DomEvent.disableClickPropagation(el);
    L.DomEvent.disableScrollPropagation(el);
  }
  function setHour(v) {
    index = Math.max(0, Math.min(168, Number(v)));
    render();
  }
  function stop() {
    if (play) clearInterval(play);
    play = null;
    $("time-play").textContent = "▶";
    $("time-play").setAttribute("aria-label", "Play hourly forecast");
  }
  $("time-play").addEventListener("click", () => {
    if (play) {
      stop();
      return;
    }
    $("time-play").textContent = "Ⅱ";
    $("time-play").setAttribute("aria-label", "Pause hourly forecast");
    play = setInterval(() => {
      if (index >= 168) {
        stop();
        return;
      }
      setHour(index + 1);
    }, 1000);
  });
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) stop();
    else if (bundle && Date.now() - bundle.retrieved >= 3600000) load();
  });
  for (const key of ["map-time", "detail-hour"])
    $(key).addEventListener("input", (e) => {
      stop();
      setHour(e.target.value);
    });
  $("ocean-now").addEventListener("click", () => {
    stop();
    hours = timeline();
    setHour(0);
    if (!bundle || Date.now() - bundle.retrieved >= 3600000) load();
  });
  $("ocean-layer").addEventListener("change", (e) => {
    overlay = e.target.value;
    draw();
  });
  for (const key of ["forecast-model", "detail-model"])
    $(key).addEventListener("change", (e) => {
      family = e.target.value;
      $("forecast-model").value = family;
      $("detail-model").value = family;
      render();
    });
  $("map-weather-summary").addEventListener("click", onOpen);
  $("day-strip").addEventListener("click", (e) => {
    const b = e.target.closest("[data-hour]");
    if (b) {
      stop();
      setHour(b.dataset.hour);
    }
  });
  $("marine-point").addEventListener("change", (e) => {
    point = Number(e.target.value);
    requested = null;
    render();
  });
  $("previous-hour").addEventListener("click", () => setHour(index - 1));
  $("next-hour").addEventListener("click", () => setHour(index + 1));
  function alertsFor(i, t) {
    const items = bundle?.alerts?.[POINTS[i].offshore ? "offshore" : "coastal"];
    return Array.isArray(items)
      ? items
          .filter(
            (a) =>
              (!Number.isFinite(a.starts) || a.starts <= t) &&
              (!Number.isFinite(a.ends) || a.ends >= t),
          )
          .map((a) => a.title)
      : null;
  }
  function statusFor(i, t, c, other) {
    const result = comfort(c, other, alertsFor(i, t));
    const stale = Date.now() - bundle.retrieved > 3 * 3600000;
    const ids = [
      "gfs_global",
      "ecmwf_ifs025",
      "ncep_gfswave025",
      "ecmwf_wam025",
    ];
    const unavailable = ids.some(
      (id) =>
        !Number.isFinite(bundle.models[id]?.meta?.last_run_initialisation_time),
    );
    const old = ids.some((id) => {
      const m = bundle.models[id]?.meta;
      return (
        m && Date.now() / 1000 - m.last_run_initialisation_time > 36 * HOUR
      );
    });
    if ((stale || unavailable || old) && result.level !== "hazard")
      return {
        level: "unknown",
        label: "Uncertain",
        flags: [
          stale
            ? "Forecast retrieval is over 3 hours old"
            : old
              ? "One or more model runs are over 36 hours old"
              : "Model initialization unavailable",
          ...result.flags,
        ],
      };
    return result;
  }
  function draw() {
    layer.clearLayers();
    const legend = $("overlay-legend");
    if (!bundle) {
      legend.textContent = "Loading live sources; no values assumed.";
      return;
    }
    if (overlay === "none") {
      legend.textContent = "NOAA chart · depth labels use the chart’s units.";
      return;
    }
    const labels = {
      waves: "Seas · ft · arrows travel toward",
      wind: "Wind · kt · arrows blow toward",
      sst: "Modeled SST · °F · ~8 km source",
      comfort: "Hourly comfort · not a trip clearance",
    };
    legend.innerHTML = `<span>${labels[overlay]}</span><span class="legend-scale ${overlay}"></span><span>${overlay === "waves" ? "0 → 8+ ft" : overlay === "wind" ? "0 → 20+ kt" : overlay === "sst" ? "50 → 75 °F" : "Calmer → mixed → more motion · gray unknown"}</span>`;
    const seen = new Set(),
      t = hours[index];
    const id =
      overlay === "sst"
        ? "meteofrance_currents"
        : overlay === "wind"
          ? family === "gfs"
            ? "gfs_global"
            : "ecmwf_ifs025"
          : family === "gfs"
            ? "ncep_gfswave025"
            : "ecmwf_wam025";
    POINTS.forEach((p, i) => {
      const grid = bundle.models[id]?.data?.[i];
      if (!Number.isFinite(grid?.latitude) || !Number.isFinite(grid?.longitude))
        return;
      const key = `${grid.latitude},${grid.longitude}`;
      if (seen.has(key)) return;
      seen.add(key);
      const c = readConditions(bundle, i, t, family),
        other = readConditions(
          bundle,
          i,
          t,
          family === "gfs" ? "ecmwf" : "gfs",
        );
      const n =
        overlay === "waves"
          ? c.sea.height
          : overlay === "wind"
            ? c.wind
            : overlay === "sst"
              ? c.sst
              : null;
      const status = statusFor(i, t, c, other);
      const color =
        overlay === "comfort"
          ? colors[status.level]
          : !Number.isFinite(n)
            ? "#8d9aa2"
            : overlay === "sst"
              ? `hsl(${Math.max(0, Math.min(230, 230 - (n - 50) * 9))} 62% 48%)`
              : overlay === "waves"
                ? `hsl(${Math.max(0, 180 - n * 22)} 58% 45%)`
                : `hsl(${Math.max(0, 185 - n * 8)} 58% 43%)`;
      L.circle([grid.latitude, grid.longitude], {
        radius: overlay === "sst" ? 4400 : 10500,
        color,
        weight: 1,
        fillOpacity: 0.2,
        interactive: false,
        pane: "overlayPane",
      }).addTo(layer);
      const direction =
        overlay === "wind"
          ? c.windFrom
          : overlay === "waves"
            ? c.sea.from
            : null;
      const label = overlay === "comfort" ? status.label : num(n);
      L.marker([grid.latitude, grid.longitude], {
        keyboard: true,
        title: `${p.name}: ${label}; ${full(t)}`,
        icon: L.divIcon({
          className: "weather-sample",
          html: `<span class="weather-arrow" style="transform:rotate(${directionTo(direction) ?? 0}deg)" aria-hidden="true">${Number.isFinite(direction) ? "↑" : "·"}</span><b>${esc(label)}</b>`,
          iconSize: [76, 48],
          iconAnchor: [38, 24],
        }),
        zIndexOffset: -100,
      })
        .on("click", () => {
          point = i;
          requested = null;
          render();
          onOpen();
        })
        .addTo(layer);
    });
  }
  function render() {
    const t = hours[index],
      provisional = index >= 72;
    $("map-time-label").textContent = (index === 0 ? "Now · " : "") + full(t);
    for (const key of ["map-time", "detail-hour"]) {
      $(key).value = index;
      $(key).setAttribute(
        "aria-valuetext",
        full(t) + (provisional ? " · provisional" : ""),
      );
    }
    $("map-time-range").textContent = provisional
      ? "Provisional"
      : `+${index}h`;
    $("detail-time-label").textContent = full(t);
    $("detail-provisional").textContent =
      (provisional ? "PROVISIONAL OUTLOOK" : "HOURLY FORECAST") +
      " · PACIFIC TIME";
    $("marine-point").value = point;
    const dates = new Map();
    hours.forEach((t, i) => {
      const d = day(t);
      if (!dates.has(d)) dates.set(d, i);
    });
    $("day-strip").innerHTML = [...dates.entries()]
      .map(
        ([d, i], n) =>
          `<button data-hour="${i}" aria-pressed="${d === day(t)}">${n === 0 ? "Today" : local(hours[i], { weekday: "short" })}<small>${local(hours[i], { month: "numeric", day: "numeric" })}</small></button>`,
      )
      .join("");
    draw();
    if (!bundle) return;
    const c = readConditions(bundle, point, t, family),
      other = readConditions(
        bundle,
        point,
        t,
        family === "gfs" ? "ecmwf" : "gfs",
      ),
      status = statusFor(point, t, c, other),
      p = POINTS[point];
    $("map-weather-summary").innerHTML =
      `<span><strong>${esc(p.name)}${p.offshore ? " · offshore" : ""}</strong><span>${num(c.sea.height)} ft · ${num(c.sea.period)} s ${family === "gfs" ? "primary" : "mean"} · wind ${num(c.wind, 0)} / gust ${num(c.gust, 0)} kt</span></span><span class="comfort-pill ${status.level}">${status.label} ↗</span>`;
    const body = $("marine-detail-body"),
      sourcesOpen = body.querySelector("#marine-sources")?.open;
    body.innerHTML = detailHTML({
      bundle,
      hours,
      index,
      point,
      family,
      requested,
      c,
      other,
      status,
      sourcesOpen,
      heading,
    });
    const explain = () => {
      const a = angleBetween(heading, c.swell.from);
      $("encounter-note").textContent =
        a === null || heading < 0 || heading >= 360
          ? "Enter a heading from 0° to 359°; swell direction must be available."
          : `Primary swell approaches approximately ${a < 45 ? "from ahead" : a > 135 ? "from behind" : "across the beam"} (${num(a, 0)}° off the bow). Beam seas can increase roll; head seas can shorten time between encounters.`;
    };
    $("boat-heading").addEventListener("input", (e) => {
      heading = e.target.value === "" ? NaN : Number(e.target.value);
      explain();
    });
    explain();
  }
  async function load(force = false) {
    if (loading) return;
    loading = true;
    stop();
    $("load-forecast").disabled = true;
    $("forecast-status").textContent =
      "Loading hourly wind and waves from two independent models, ocean context, and NOAA tides…";
    try {
      let cached;
      try {
        cached = JSON.parse(sessionStorage.getItem("skippercast-marine-v1"));
      } catch {
        /* Storage is optional. */
      }
      bundle =
        !force && cached?.models && Date.now() - cached.retrieved < 3600000
          ? cached
          : await loadMarine();
      try {
        sessionStorage.setItem("skippercast-marine-v1", JSON.stringify(bundle));
      } catch {
        /* No cache is needed to browse. */
      }
      hours = timeline();
      const failed = MODELS.filter((m) => bundle.models[m.id]?.error).map(
        (m) => m.name,
      );
      $("forecast-status").textContent =
        `Retrieved ${full(bundle.retrieved / 1000)}. ${failed.length ? `Unavailable: ${failed.join(", ")}. Missing values remain blank.` : "Now is a forecast hour; observations carry separate timestamps."}`;
      render();
    } catch (e) {
      $("forecast-status").textContent =
        "Marine sources could not load. Refresh to retry; no calm conditions are assumed.";
      $("map-weather-summary").textContent =
        "Forecast unavailable · open details ↗";
    } finally {
      loading = false;
      $("load-forecast").disabled = false;
    }
  }
  $("load-forecast").addEventListener("click", () => load(true));
  render();
  load();
  return {
    selectLocation(p) {
      requested = p;
      point = POINTS.reduce(
        (best, s, i) =>
          distanceNm(s, p) < distanceNm(POINTS[best], p) ? i : best,
        0,
      );
      if (bundle) render();
    },
    setSpecies(id) {
      if (
        ["albacore", "bluefin"].includes(id) &&
        !["albacore", "bluefin"].includes(lastSpecies)
      ) {
        overlay = "sst";
        $("ocean-layer").value = "sst";
        point = 8;
        requested = null;
      } else if (
        !["albacore", "bluefin"].includes(id) &&
        ["albacore", "bluefin"].includes(lastSpecies)
      ) {
        overlay = "waves";
        $("ocean-layer").value = "waves";
        point = 1;
        requested = null;
      }
      lastSpecies = id;
      render();
    },
  };
}
