import {getRegion, localContext, pointBundle} from './region.js?v=8.9';
import {matrixHTML} from './forecast-matrix.js?v=8.9';
import { initBiteEvidence } from "./bite-evidence.js?v=8.9";
import {
  POINTS,
  POINT_SIGNATURE,
  MODELS,
  HOUR,
  timeline,
  readConditions,
  comfort,
  directionTo,
  angleBetween,
  distanceNm,
  loadMarine,
} from "./marine-data.js?v=8.9";
import { esc, num, local, full, day } from "./marine-charts.js?v=8.9";
import { rankMornings, rankTimelineDays, renderOutlook } from "./morning-outlook.js?v=8.9";
import { forecastSummaryHTML } from "./forecast-summary.js?v=8.9";
import { localDate } from "./forecast.js?v=8.9";
import { detailHTML } from "./marine-detail.js?v=8.9";
import { loadObservations, observationsHTML, observedDock, OBSERVATION_REFRESH, FORECAST_REFRESH } from "./live-conditions.js?v=8.9";
const $ = (id) => document.getElementById(id);
const isoDay = (t) => localDate(new Date(t*1000));
const colors = {
  calmer: "#278f87",
  mixed: "#be7a29",
  rough: "#c45d4e",
  hazard: "#b0395b",
  unknown: "#778995",
};

export function initWeather(map, layer, onOpen, onForecast = () => {}) {
  let bundle = null,
    observations = null,
    liveLoading = false,
    hours = timeline(),
    index = 0,
    point = Math.max(0,POINTS.findIndex(p=>p.id===(getRegion().default_forecast_point || POINTS[Math.min(1,POINTS.length-1)].id))),
    family = "gfs",
    overlay = "none",
    play = null,
    loading = false,
    requested = null,
    coastalSelection = null,
    lastSpecies = $("species-select").value,
    heading = 0,
    detailTab = "live",
    forecastError = null,
    outlookKey = "",
    dayRatings = [];
  const observationCache=new Map();
  const evidence = initBiteEvidence($("bite-evidence"));
  const dock = $("map-time-dock");
  dock.innerHTML = `<div class="compact-time-row"><button id="map-weather-summary" aria-label="Open detailed weather and tide chart">Loading conditions…</button><button id="toggle-map-timeline" aria-expanded="false" aria-controls="map-timeline-controls">Timeline</button></div><div id="map-timeline-controls" hidden><div class="timeline-actions"><button id="time-play" aria-label="Play hourly forecast">▶</button><span>Now to 7 days</span><button id="ocean-now" aria-label="Jump to current forecast hour">Now</button></div><div class="scrub-row"><label class="sr-only" for="map-time">Forecast hour, now to seven days</label><input id="map-time" type="range" min="0" max="168" step="1" value="0"/><span>+7d</span></div><div class="compact-time-caption"><span id="map-time-label"></span><span id="map-time-range"></span></div></div>`;
  $("toggle-map-timeline").addEventListener("click", () => {
    const controls = $("map-timeline-controls");
    controls.hidden = !controls.hidden;
    $("toggle-map-timeline").setAttribute("aria-expanded", String(!controls.hidden));
    if (controls.hidden) stop();
  });
  $("weather-map-options").innerHTML =
    `<label>Weather layer<select id="ocean-layer"><option value="none">Off · habitat only</option><option value="waves">Waves · feet</option><option value="wind">Wind · knots</option><option value="comfort">Hourly comfort</option><option value="sst">Sea temperature · °F</option></select></label><label>Forecast model<select id="forecast-model"><option value="gfs">NOAA GFS</option><option value="ecmwf">ECMWF</option></select></label><p id="overlay-legend" class="small"></p>`;
  $("forecast-content").innerHTML =
    `<details class="forecast-settings"><summary><span id="forecast-context">Estero Bay · NOAA GFS</span><span>Change</span></summary><div class="marine-controls"><label>Forecast sample<select id="marine-point">${POINTS.map((s, i) => `<option value="${i}" ${i === point ? "selected" : ""}>${s.name}</option>`).join("")}</select></label><label>Model<select id="detail-model"><option value="gfs">NOAA GFS</option><option value="ecmwf">ECMWF</option></select></label></div></details><div id="forecast-time-tools" class="forecast-time-tools" hidden><div class="selected-forecast-time"><span id="detail-provisional" class="eyebrow">HOURLY FORECAST · PACIFIC TIME</span><strong id="detail-time-label"></strong></div><div class="detail-time"><button id="previous-hour" aria-label="Previous forecast hour">←</button><label class="sr-only" for="detail-hour">Forecast hour</label><input id="detail-hour" type="range" min="0" max="168" value="0" step="1"/><button id="next-hour" aria-label="Next forecast hour">→</button></div><div id="day-strip" class="day-strip" aria-label="Choose forecast date"></div></div><div class="condition-tabs" role="tablist" aria-label="Conditions detail"><button role="tab" data-condition-tab="live" aria-selected="true">Live</button><button role="tab" data-condition-tab="waves" aria-selected="false">Waves</button><button role="tab" data-condition-tab="wind" aria-selected="false">Wind</button><button role="tab" data-condition-tab="tides" aria-selected="false">Tides</button><button role="tab" data-condition-tab="sources" aria-selected="false">Sources</button></div><div id="live-conditions" aria-label="Current measured conditions"></div><div id="marine-detail-body" hidden><p>Loading forecast sources…</p></div>`;
  for (const el of [dock, document.querySelector(".species-bar")]) {
    L.DomEvent.disableClickPropagation(el);
    L.DomEvent.disableScrollPropagation(el);
  }
  const methodNote=document.createElement('p');methodNote.className='small';methodNote.id='forecast-method-note';
  const noteForMethod=()=>{methodNote.hidden=lastSpecies!=='lobster';methodNote.textContent='Lobster: daily ratings summarize 7 a.m.–1 p.m. comfort, not a night hoop-net outing. Select every hour of your actual fishing and return window; daylight scores do not rate diving safety.';};
  $('forecast-content').prepend(methodNote);noteForMethod();
  const summary=document.createElement("div");
  summary.id="forecast-hour-summary";
  $("forecast-time-tools").append(summary);
  const matrix=document.createElement("div"); matrix.id="forecast-matrix"; $("forecast-time-tools").append(matrix);
  matrix.addEventListener("click",e=>{const b=e.target.closest("[data-forecast-epoch]");if(b)setHour(Math.round((Number(b.dataset.forecastEpoch)-hours[0])/HOUR));});
  $("best-day-banner").addEventListener("click", () => {
    const epoch = Number($("best-day-banner").dataset.hour);
    if (epoch) setHour(Math.round((epoch - hours[0]) / HOUR));
    onOpen();
    const summary = document.querySelector(".morning-summary");
    if (summary) summary.open = true;
    $("morning-outlook").scrollIntoView({ block: "start" });
  });
  $("morning-outlook").addEventListener("click", (e) => {
    const b = e.target.closest("[data-morning]");
    if (b) setHour(Math.round((Number(b.dataset.morning) - hours[0]) / HOUR));
  });
  function applyDetailTab() {
    const live = detailTab === "live";
    $("live-conditions").hidden = !live;
    $("marine-detail-body").hidden = live;
    document.querySelector(".forecast-settings").hidden = live && !getRegion().contexts;
    $("forecast-time-tools").hidden = false;
    $("forecast-hour-summary").hidden = live;
    $("forecast-matrix").hidden = live;
    const failed = bundle ? MODELS.filter((m) => bundle.models[m.id]?.error).map((m) => m.name) : [];
    $("forecast-status").textContent = live
      ? "Auto refresh · observations every 5 min"
      : forecastError || (bundle ? `Forecast updated ${local(bundle.retrieved / 1000, { hour: "numeric", minute: "2-digit" })} PT${failed.length ? ` · unavailable: ${failed.join(", ")}` : " · refreshes every 30 min"}`
      : "Loading wind, waves and tide forecasts…");
    for (const b of document.querySelectorAll("[data-condition-tab]")) {
      b.setAttribute(
        "aria-selected",
        String(b.dataset.conditionTab === detailTab),
      );
      b.tabIndex = b.dataset.conditionTab === detailTab ? 0 : -1;
    }
    for (const p of document.querySelectorAll("[data-condition-panel]"))
      p.hidden = p.dataset.conditionPanel !== detailTab;
  }
  document.querySelector(".condition-tabs").addEventListener("click", (e) => {
    const b = e.target.closest("[data-condition-tab]");
    if (b) {
      detailTab = b.dataset.conditionTab;
      if (detailTab === "live") {
        stop();
        hours = timeline();
        index = 0;
        if (!observations || Date.now() - observations.retrieved >= OBSERVATION_REFRESH) loadLive();
        render();
      }
      applyDetailTab();
    }
  });
  document.querySelector(".condition-tabs").addEventListener("keydown", (e) => {
    const tabs = [...document.querySelectorAll("[data-condition-tab]")];
    const tabIndex = tabs.indexOf(e.target);
    if (
      tabIndex < 0 ||
      !["ArrowLeft", "ArrowRight", "Home", "End"].includes(e.key)
    )
      return;
    e.preventDefault();
    const next =
      e.key === "Home"
        ? 0
        : e.key === "End"
          ? tabs.length - 1
          : (tabIndex + (e.key === "ArrowRight" ? 1 : -1) + tabs.length) %
            tabs.length;
    detailTab = tabs[next].dataset.conditionTab;
    if (detailTab === "live") {
      stop(); hours = timeline(); index = 0;
      render();
    }
    applyDetailTab();
    tabs[next].focus();
  });
  function setHour(v) {
    index = Math.max(0, Math.min(168, Number(v)));
    if (detailTab === "live") detailTab = "waves";
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
    else refreshDue();
  });
  function refreshDue() {
    if (document.hidden) return;
    if (!observations || Date.now() - observations.retrieved >= OBSERVATION_REFRESH) loadLive();
    if (!bundle || Date.now() - bundle.retrieved >= FORECAST_REFRESH) load();
    if (index === 0) hours = timeline();
    render();
  }
  setInterval(refreshDue, 60000);
  for (const key of ["map-time", "detail-hour"])
    $(key).addEventListener("input", (e) => {
      stop();
      setHour(e.target.value);
    });
  $("ocean-now").addEventListener("click", () => {
    stop();
    hours = timeline();
    index = 0;
    detailTab = "live";
    render();
    refreshDue();
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
  $("map-weather-summary").addEventListener("click", () => {
    if (index === 0) { detailTab = "live"; applyDetailTab(); }
    onOpen();
  });
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
    const items = pointBundle(bundle,i)?.alerts?.[POINTS[i].offshore ? "offshore" : "coastal"];
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
    const ctx=localContext(point);
    observations=observationCache.get(ctx.id)||null;
    if(!liveLoading && (!observations || Date.now()-observations.retrieved>=OBSERVATION_REFRESH)) void loadLive();
    const selectedBundle=pointBundle(bundle,point);
    const expandedLive = [...$("live-conditions").querySelectorAll("[data-live-disclosure][open]")].map((d) => d.dataset.liveDisclosure);
    $("live-conditions").innerHTML = observationsHTML(observations, !!POINTS[point].offshore);
    for (const d of $("live-conditions").querySelectorAll("[data-live-disclosure]")) d.open = expandedLive.includes(d.dataset.liveDisclosure);
    applyDetailTab();
    evidence.select(lastSpecies, requested || POINTS[point]);
    const t = hours[index],
      provisional = index >= 72;
    document.dispatchEvent(new CustomEvent("skippercast:time",{detail:{epoch:t,regionId:getRegion().id}}));
    $("map-time-label").textContent =
      (index === 0 ? "Now · " : "") +
      local(t, { weekday: "short", hour: "numeric", minute: "2-digit" });
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
    $("forecast-context").textContent = POINTS[point].name + " · " + (family === "gfs" ? "NOAA GFS" : "ECMWF");
    const nextKey = `${bundle?.retrieved}:${point}:${lastSpecies}:${Math.floor(Date.now() / 3600000)}`;
    if (nextKey !== outlookKey && bundle) {
      dayRatings=rankTimelineDays(selectedBundle,point,lastSpecies,hours);
      renderOutlook(rankMornings(selectedBundle,point,lastSpecies,Date.now(),hours.at(-1)),point);
      outlookKey=nextKey;
    }
    const dates = new Map();
    hours.forEach((t, i) => {
      const d = isoDay(t);
      if (!dates.has(d)) dates.set(d, i);
    });
    $("day-strip").innerHTML = [...dates.entries()]
      .map(
        ([d, i], n) =>
          {
            const r=dayRatings.find(r=>r.date===d), at=r?Math.max(0,Math.round((r.time-hours[0])/HOUR)):i;
            return `<button data-hour="${at}" aria-pressed="${d === isoDay(t)}" class="${r?.conditions>=8?'good':''}" title="${esc(r?.window||'Forecast loading')} · ${esc(r?.confidence||'')} confidence">${n === 0 ? "Today" : local(hours[i], { weekday: "short" })}<small>${local(hours[i], { month: "numeric", day: "numeric" })}</small><b>${Number.isFinite(r?.conditions)?num(r.conditions)+"/10":"—/10"}</b><small>${r?.confidence==='Low'?'Low':r?'Moderate':'Loading'}${r?.provisional?' · outlook':''}</small></button>`;
          },
      )
      .join("");
    draw();
    const observation = index === 0 ? observedDock(observations, !!POINTS[point].offshore) : null;
    if (!bundle) {
      if (observation) $("map-weather-summary").innerHTML = observation;
      return;
    }
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
      observation || `<strong>${index === 0 ? "Now forecast" : local(t, { weekday: "short", hour: "numeric" })}${provisional ? " · outlook" : ""} · ${num(c.sea.height)} ft <span>@ ${num(c.sea.period)} s</span></strong><span>Wind ${num(c.wind, 0)} · gust ${num(c.gust, 0)} kt</span>`;
    $("map-weather-summary").title = observation ? "Latest measured buoy seas · open current observations" : p.name + " · " + status.label;
    $("forecast-hour-summary").innerHTML=forecastSummaryHTML(selectedBundle,point,lastSpecies,t,family,dayRatings.find(r=>r.date===isoDay(t)));
    $("forecast-matrix").innerHTML=matrixHTML({bundle:selectedBundle,point,species:lastSpecies,time:t,family});
    onForecast({bundle,time:t,family,point,species:lastSpecies});
    document.dispatchEvent(new CustomEvent("skippercast:forecast",{detail:{bundle,time:t,family,point,species:lastSpecies}}));
    const body = $("marine-detail-body"),
      sourcesOpen = body.querySelector("#marine-sources")?.open;
    const expanded = [...body.querySelectorAll("[data-disclosure][open]")].map((d) => d.dataset.disclosure);
    body.innerHTML = detailHTML({
      bundle:selectedBundle,
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
    for (const disclosure of body.querySelectorAll("[data-disclosure]")) disclosure.open = expanded.includes(disclosure.dataset.disclosure);
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
    applyDetailTab();
  }
  async function loadLive() {
    if (liveLoading) return;
    liveLoading = true;
    try {
      const context=localContext(point);
      observations = await loadObservations(undefined,Date.now(),context);
      observationCache.set(context.id,observations);
      if (bundle) {
        const target=bundle.contexts?.[observations.context_id] || (!getRegion().contexts ? bundle : null);
        if(target) Object.assign(target,{alerts:observations.alerts,alertError:observations.alertError,water:observations.water,waterError:observations.waterError});
        outlookKey = "";
      }
      render();
    } finally { liveLoading = false; if(!observationCache.has(localContext(point).id)) void loadLive(); }
  }
  async function load(force = false) {
    if (loading) return;
    loading = true;
    forecastError = null;
    stop();
    $("load-forecast").disabled = true;
    $("forecast-status").textContent =
      "Loading hourly wind and waves from two independent models, ocean context, and NOAA tides…";
    try {
      let cached;
      try {
        cached = JSON.parse(sessionStorage.getItem("skippercast-marine-v4:"+getRegion().id));
      } catch {
        /* Storage is optional. */
      }
      bundle =
        !force && cached?.models && cached.pointSignature===POINT_SIGNATURE && Date.now() - cached.retrieved < FORECAST_REFRESH
          ? cached
          : await loadMarine();
      try {
        sessionStorage.setItem("skippercast-marine-v4:"+getRegion().id, JSON.stringify(bundle));
      } catch {
        /* No cache is needed to browse. */
      }
      const selected = hours[index], wasNow = index === 0;
      hours = timeline();
      index = wasNow ? 0 : Math.max(0, Math.min(168, Math.round((selected - hours[0]) / HOUR)));
      if (observations && Date.now() - observations.retrieved <= 10 * 60000) {
        const target=bundle.contexts?.[observations.context_id] || (!getRegion().contexts ? bundle : null);
        if(target) Object.assign(target,{alerts:observations.alerts,alertError:observations.alertError,water:observations.water,waterError:observations.waterError});
      }
      const failed = MODELS.filter((m) => bundle.models[m.id]?.error).map(
        (m) => m.name,
      );
      $("forecast-status").textContent =
        `Updated ${local(bundle.retrieved / 1000, { hour: "numeric", minute: "2-digit" })} PT.${failed.length ? ` Unavailable: ${failed.join(", ")}.` : " Forecasts, not observations."}`;
      render();
    } catch (e) {
      forecastError = "Forecast refresh failed. Older values may be displayed; retry Refresh.";
      $("forecast-status").textContent =
        "Marine sources could not load. Refresh to retry; no calm conditions are assumed.";
      $("map-weather-summary").textContent =
        "Forecast unavailable · open details ↗";
    } finally {
      loading = false;
      $("load-forecast").disabled = false;
    }
  }
  $("load-forecast").addEventListener("click", () => {
    load(true);
    loadLive();
    evidence.refresh();
  });
  render();
  load();
  loadLive();
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
        (getRegion().target_options?.find(p=>p.id===id)?.kind === "offshore") &&
        !(getRegion().target_options?.find(p=>p.id===lastSpecies)?.kind === "offshore")
      ) {
        coastalSelection={point,requested};
        overlay = "none";
        $("ocean-layer").value = "none";
        point = Math.max(0,POINTS.findIndex(p=>p.offshore));
        requested = null;
      } else if (
        !(getRegion().target_options?.find(p=>p.id===id)?.kind === "offshore") &&
        (getRegion().target_options?.find(p=>p.id===lastSpecies)?.kind === "offshore")
      ) {
        overlay = "none";
        $("ocean-layer").value = "none";
        point = coastalSelection?.point ?? Math.max(0,POINTS.findIndex(p=>p.id===(getRegion().default_forecast_point || POINTS[Math.min(1,POINTS.length-1)].id)));
        requested = coastalSelection?.requested || null;
      }
      lastSpecies = id;
      noteForMethod();
      outlookKey = "";
      render();
    },
  };
}
